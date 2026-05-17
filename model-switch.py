#!/usr/bin/env python3
"""
model-switch.py — 通用模型切换面板

在网页上查看所有模型提供商的连通性和延迟，一键切换模型。
支持 OpenClaw (JSON) 和 Hermes (YAML) 等任意 Bot 框架。

环境变量:
  PANEL_PASSWORD        面板登录口令 (默认: changeme)
  PANEL_CONFIG          配置文件路径 (默认: ~/.openclaw/openclaw.json)
  PANEL_CONFIG_FORMAT   配置文件格式 json|yaml|auto (默认: auto, 根据扩展名)
  PANEL_SESSIONS        会话文件路径 (默认: ~/.openclaw/agents/main/sessions/sessions.json)
  PANEL_SERVICE         systemd 服务名 (默认: openclaw-gateway.service)
  PANEL_RESTART_CMD     自定义重启命令 (默认: 空, 优先 systemd)
  PANEL_PORT            监听端口 (默认: 18790)
  PANEL_ENV_PATH        环境变量文件路径 (默认: ~/.openclaw/gateway.systemd.env)
  PANEL_MODEL_FIELD     JSON/YAML 中默认模型字段路径 (默认: agents.defaults.model)
                        Hermes 设为 model.default
  PANEL_PROVIDERS_PATH  Provider 定义路径 (默认: models.providers)
  PANEL_FRAMEWORK       框架名, 用于模型 ID 格式检测:
                        openclaw | hermes | auto (默认: auto)
"""

import json
import os
import re
import signal
import secrets
import subprocess
import time
import urllib.request
import urllib.error
import concurrent.futures
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# ---------------------------------------------------------------------------
# 框架适配层 — 定义不同框架的 Provider 来源
# ---------------------------------------------------------------------------
# 每个条目: (provider_id, display_name, env_var, base_url, test_path)
# test_url = base_url + test_path
FRAMEWORKS = {
    "openclaw": {
        "label": "OpenClaw",
        "config_format": "json",
        "model_field": "agents.defaults.model",
        "providers_path": "models.providers",
        "providers_from_config": True,   # 从配置文件读取
        "has_sessions": True,
        "restart_cmd": "",
        "service": "openclaw-gateway.service",
    },
    "hermes": {
        "label": "Hermes",
        "config_format": "yaml",
        "model_field": "model.default",
        "providers_path": "",
        "providers_from_config": False,  # 从内置列表 + 环境变量检测
        "has_sessions": False,
        "restart_cmd": "hermes gateway restart",
        "service": "hermes-gateway.service",
        "known_providers": [
            ("openrouter",   "OpenRouter",   "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1",           "/models"),
            ("nvidia",       "NVIDIA NIM",   "NVIDIA_API_KEY",     "https://integrate.api.nvidia.com/v1",   "/models"),
            ("anthropic",    "Anthropic",    "ANTHROPIC_API_KEY",  "https://api.anthropic.com/v1",           "/models"),
            ("google",       "Google Gemini","GOOGLE_API_KEY",     "https://generativelanguage.googleapis.com/v1beta/openai", "/models"),
            ("gemini",       "Gemini",       "GEMINI_API_KEY",     "https://generativelanguage.googleapis.com/v1beta/openai", "/models"),
            ("novita",       "NovitaAI",     "NOVITA_API_KEY",     "https://api.novita.ai/openai/v1",        "/models"),
            ("ollama",       "Ollama Cloud", "OLLAMA_API_KEY",     "https://ollama.com/v1",                 "/models"),
            ("zai",          "Z.AI (智谱)",  "GLM_API_KEY",        "https://open.bigmodel.cn/api/paas/v4",  "/models"),
            ("kimi",         "Kimi (月之暗面)","KIMI_API_KEY",     "https://api.kimi.com/coding/v1",        "/models"),
            ("moonshot",     "Moonshot",     "MOONSHOT_API_KEY",   "https://api.moonshot.ai/v1",            "/models"),
            ("minimax",      "MiniMax",      "MINIMAX_API_KEY",    "https://api.minimax.chat/v1",           "/models"),
            ("deepseek",     "DeepSeek",     "DEEPSEEK_API_KEY",   "https://api.deepseek.com/v1",           "/models"),
            ("xai",          "xAI Grok",     "XAI_API_KEY",        "https://api.x.ai/v1",                   "/models"),
            ("together",     "Together AI",  "TOGETHER_API_KEY",   "https://api.together.xyz/v1",           "/models"),
        ],
    },
}

# ---------------------------------------------------------------------------
# 配置（可通过环境变量覆盖）
# ---------------------------------------------------------------------------

CFG = {
    "config":       os.path.expanduser(os.environ.get("PANEL_CONFIG", "~/.openclaw/openclaw.json")),
    "sessions":     os.path.expanduser(os.environ.get("PANEL_SESSIONS", "~/.openclaw/agents/main/sessions/sessions.json")),
    "service":      os.environ.get("PANEL_SERVICE", "openclaw-gateway.service"),
    "restart_cmd":  os.environ.get("PANEL_RESTART_CMD", ""),
    "port":         int(os.environ.get("PANEL_PORT", "18790")),
    "env_path":     os.path.expanduser(os.environ.get("PANEL_ENV_PATH", "~/.openclaw/gateway.systemd.env")),
    "format":       os.environ.get("PANEL_CONFIG_FORMAT", "auto").lower(),
    "model_field":  os.environ.get("PANEL_MODEL_FIELD", ""),
    "providers_path": os.environ.get("PANEL_PROVIDERS_PATH", ""),
    "framework":    os.environ.get("PANEL_FRAMEWORK", "auto").lower(),
}

_pw = [os.environ.get("PANEL_PASSWORD", "changeme")]
_tokens = {}

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def load_env():
    p = CFG["env_path"]
    if os.path.exists(p):
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k, v)

def read_file(path):
    try:
        with open(path) as f:
            return f.read()
    except:
        return ""

def write_file(path, text):
    with open(path, "w") as f:
        f.write(text)

def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return {}

def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def deep_get(obj, path):
    for key in path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(key, {})
        else:
            return {}
    return obj if isinstance(obj, dict) else {}

def deep_set(obj, path, value):
    parts = path.split(".")
    for key in parts[:-1]:
        obj = obj.setdefault(key, {})
    obj[parts[-1]] = value

def resolve_api_key(raw):
    s = raw.strip()
    if s.startswith("${") and s.endswith("}"):
        return os.environ.get(s[2:-1], "")
    return s

def make_token():
    return secrets.token_hex(32)

def check_auth(headers):
    token = headers.get("X-Auth-Token", "")
    if token in _tokens:
        if _tokens[token] > time.time():
            return True
        del _tokens[token]
    return False

# ---------------------------------------------------------------------------
# 框架检测
# ---------------------------------------------------------------------------

def detect_framework():
    fw = CFG["framework"]
    if fw in FRAMEWORKS:
        return FRAMEWORKS[fw]
    # auto 检测: 看文件扩展名
    path = CFG["config"]
    if path.endswith(".yaml") or path.endswith(".yml"):
        return FRAMEWORKS["hermes"]
    return FRAMEWORKS["openclaw"]

def get_model_field():
    if CFG["model_field"]:
        return CFG["model_field"]
    return detect_framework()["model_field"]

def get_providers_path():
    if CFG["providers_path"]:
        return CFG["providers_path"]
    return detect_framework().get("providers_path", "")

# ---------------------------------------------------------------------------
# Config 读写 (JSON / YAML)
# ---------------------------------------------------------------------------

def _try_yaml():
    """尝试导入 yaml 模块"""
    try:
        import yaml
        return yaml
    except ImportError:
        return None

def read_config():
    path = CFG["config"]
    text = read_file(path)
    if not text:
        return {}
    fmt = CFG["format"]
    if fmt == "auto":
        fmt = "yaml" if path.endswith((".yaml", ".yml")) else "json"
    if fmt == "yaml":
        yaml = _try_yaml()
        if yaml is None:
            raise ImportError("YAML 格式需要安装 pyyaml: pip install pyyaml")
        return yaml.safe_load(text) or {}
    return json.loads(text) if text else {}

def write_config(data):
    path = CFG["config"]
    fmt = CFG["format"]
    if fmt == "auto":
        fmt = "yaml" if path.endswith((".yaml", ".yml")) else "json"
    if fmt == "yaml":
        yaml = _try_yaml()
        if yaml is None:
            raise ImportError("YAML 格式需要安装 pyyaml: pip install pyyaml")
        write_file(path, yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False))
    else:
        write_json(path, data)

# ---------------------------------------------------------------------------
# Provider 读取
# ---------------------------------------------------------------------------

def load_providers():
    fw = detect_framework()
    result = {}

    if fw.get("providers_from_config"):
        # OpenClaw 模式：从配置文件读
        cfg = read_config()
        providers = deep_get(cfg, get_providers_path())
        for pname, pconf in providers.items():
            base_url = pconf.get("baseUrl", "").rstrip("/")
            api_key = resolve_api_key(pconf.get("apiKey", ""))
            if not api_key or not base_url:
                continue
            test_url = f"{base_url}/models" if "/v1" in base_url else f"{base_url}/v1/models"
            result[pname] = {
                "name": pconf.get("name") or pname,
                "test_url": test_url,
                "api_key": api_key,
            }
    else:
        # Hermes 模式：从内置列表 + 环境变量检测
        for pid, pname, env_var, base_url, test_path in fw.get("known_providers", []):
            api_key = os.environ.get(env_var, "")
            if not api_key:
                # 如果有 NOVITA_BASE_URL 之类覆盖，检查
                base_override = os.environ.get(f"{env_var.replace('_API_KEY', '_BASE_URL')}", "")
                if not base_override:
                    continue
            actual_base = os.environ.get(f"{env_var.replace('_API_KEY', '_BASE_URL')}", base_url).rstrip("/")
            test_url = actual_base + test_path if test_path else f"{actual_base}/models"
            result[pid] = {
                "name": pname,
                "test_url": test_url,
                "api_key": api_key,
                # Hermes 模型 ID 格式: "provider/model" 或 "provider/subprovider/model"
            }

    return result

def get_provider_base_urls():
    """用于 chat 的 provider 信息"""
    fw = detect_framework()
    result = {}

    if fw.get("providers_from_config"):
        cfg = read_config()
        providers = deep_get(cfg, get_providers_path())
        for pname, pconf in providers.items():
            base_url = pconf.get("baseUrl", "").rstrip("/")
            api_key = resolve_api_key(pconf.get("apiKey", ""))
            if api_key and base_url:
                result[pname] = {"base_url": base_url, "api_key": api_key}
    else:
        for pid, pname, env_var, base_url, test_path in fw.get("known_providers", []):
            api_key = os.environ.get(env_var, "")
            if not api_key:
                continue
            actual_base = os.environ.get(f"{env_var.replace('_API_KEY', '_BASE_URL')}", base_url).rstrip("/")
            result[pid] = {"base_url": actual_base, "api_key": api_key}

    return result

def get_all_models():
    """所有模型，按提供商分组"""
    cfg = read_config()
    fw = detect_framework()

    if fw.get("providers_from_config"):
        providers = deep_get(cfg, get_providers_path())
        names = load_providers()
        result = {}
        for pname, pconf in providers.items():
            models = pconf.get("models", [])
            result[pname] = {
                "name": names.get(pname, {}).get("name", pname),
                "base_url": pconf.get("baseUrl", ""),
                "model_count": len(models),
                "models": [{"id": m.get("id"), "name": m.get("name")} for m in models],
            }
        return result
    else:
        # Hermes 没有内置模型列表，返回空
        return {}

# ---------------------------------------------------------------------------
# 连通性检测 & Chat
# ---------------------------------------------------------------------------

def check_provider(pname, pconf):
    api_key = pconf.get("api_key", "")
    if not api_key:
        return {"status": "no_key", "message": "未设置 API Key", "name": pconf["name"]}
    start = time.time()
    try:
        req = urllib.request.Request(pconf["test_url"])
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=8) as r:
            return {"status": "ok", "latency_ms": round((time.time() - start) * 1000, 0), "name": pconf["name"]}
    except urllib.error.HTTPError as e:
        return {"status": "error", "latency_ms": round((time.time() - start) * 1000, 0), "http_code": e.code, "name": pconf["name"]}
    except Exception as e:
        return {"status": "timeout", "message": str(e)[:50], "name": pconf["name"]}

def chat_with_provider(provider, model_id, message):
    pcfgs = get_provider_base_urls()
    pcfg = pcfgs.get(provider)
    if not pcfg or not pcfg.get("api_key"):
        return {"error": f"{provider} 未设置或缺少 API Key"}
    url = f"{pcfg['base_url']}/chat/completions"
    body = json.dumps({
        "model": model_id,
        "messages": [{"role": "user", "content": message}],
        "max_tokens": 1024,
        "temperature": 0.7,
    }).encode()
    try:
        req = urllib.request.Request(url, data=body)
        req.add_header("Authorization", f"Bearer {pcfg['api_key']}")
        req.add_header("Content-Type", "application/json")
        start = time.time()
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read())
            return {"content": resp.get("choices", [{}])[0].get("message", {}).get("content", ""),
                    "latency_ms": round((time.time() - start) * 1000, 0)}
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}"}
    except Exception as e:
        return {"error": str(e)[:100]}

# ---------------------------------------------------------------------------
# 切换模型 & 重启
# ---------------------------------------------------------------------------

def restart_service():
    fw = detect_framework()
    # 1. 自定义命令
    if CFG["restart_cmd"]:
        try:
            subprocess.run(CFG["restart_cmd"], shell=True, capture_output=True, timeout=30)
            return True, f"已执行: {CFG['restart_cmd']}"
        except Exception as e:
            return False, f"重启命令失败: {e}"
    # 2. systemd
    svc = CFG["service"]
    try:
        r = subprocess.run(["systemctl", "--user", "restart", svc], capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return True, f"服务 {svc} 已重启"
    except:
        pass
    # 3. 回退 SIGHUP
    pid = None
    try:
        name = svc.replace(".service", "")
        r = subprocess.run(["pgrep", "-f", name], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            pid = int(r.stdout.strip().split()[0])
    except:
        pass
    if pid:
        try:
            os.kill(pid, signal.SIGHUP)
            return True, f"SIGHUP (PID {pid})"
        except Exception as e:
            return False, str(e)
    # 4. Hermes 特有关闭
    if fw["label"] == "Hermes":
        try:
            subprocess.run(["hermes", "gateway", "restart"], capture_output=True, timeout=30)
            return True, "Hermes gateway 已重启"
        except:
            pass
    return False, "找不到可重启的服务进程"

def switch_model(provider, model_id):
    cfg = read_config()
    field = get_model_field()
    fw = detect_framework()

    old_val = deep_get(cfg, field)
    old_model = old_val.get("model", "") if isinstance(old_val, dict) else str(old_val) if old_val else ""
    # Hermes: model.default 是字符串，OpenClaw: agents.defaults.model 是字符串
    # 统一处理: 如果值是字符串直接设字符串，如果是 dict 设 dict.model
    if isinstance(deep_get(cfg, field), dict):
        deep_get(cfg, field)["model"] = model_id
    else:
        deep_set(cfg, field, model_id)
    write_config(cfg)

    # 会话同步 (仅 OpenClaw)
    session_updated = False
    if fw.get("has_sessions") and os.path.exists(CFG["sessions"]):
        try:
            sessions = read_json(CFG["sessions"])
            for key in list(sessions.keys()):
                if ":cron:" in key or ":subagent:" in key or ":dreaming-" in key:
                    continue
                sessions[key]["model"] = model_id
                sessions[key]["modelOverride"] = model_id
                sessions[key]["modelProvider"] = provider
                sessions[key]["providerOverride"] = provider
                sessions[key].pop("modelOverrideSource", None)
                sessions[key].pop("providerModel", None)
            write_json(CFG["sessions"], sessions)
            session_updated = True
        except:
            pass

    ok, msg = restart_service()
    extra = "，会话已同步" if session_updated else ""
    return ok, f"{old_model} → {model_id}{extra}，{msg}"

# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _is_auth(self):
        if check_auth(self.headers):
            return True
        qs = self.path.split("?")
        if len(qs) > 1:
            params = dict(p.split("=", 1) for p in qs[1].split("&") if "=" in p)
            t = params.get("token", "")
            if t in _tokens and _tokens[t] > time.time():
                return True
            _tokens.pop(t, None)
        return False

    def _send(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _html(self):
        d = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(d, "model-switch.html")) as f:
            return f.read()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Auth-Token")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path not in ("/api/login",) and path.startswith("/api/") and not self._is_auth():
            self._send({"error": "未授权，请先登录"}, 401)
            return
        if path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(self._html().encode())
        elif path == "/api/status":
            providers = load_providers()
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
                futures = {n: ex.submit(check_provider, n, c) for n, c in providers.items()}
                status = {n: f.result(timeout=10) for n, f in futures.items()}
            self._send(status)
        elif path == "/api/config":
            cfg = read_config()
            field = get_model_field()
            val = deep_get(cfg, field)
            default_model = val.get("model", "") if isinstance(val, dict) else str(val) if val else ""
            self._send({
                "default_model": default_model,
                "providers": list(load_providers().keys()),
                "framework": detect_framework()["label"],
            })
        elif path == "/api/models":
            self._send(get_all_models())
        else:
            self.send_error(404)

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""

        if path == "/api/login":
            try:
                d = json.loads(body)
                if d.get("password", "") == _pw[0]:
                    t = make_token()
                    _tokens[t] = time.time() + 86400
                    self._send({"ok": True, "token": t})
                else:
                    self._send({"error": "密码错误"}, 403)
            except Exception as e:
                self._send({"error": str(e)}, 500)
            return

        if not self._is_auth():
            self._send({"error": "未授权，请先登录"}, 401)
            return

        if path == "/api/change-password":
            try:
                d = json.loads(body)
                old, new = d.get("old_password", ""), d.get("new_password", "")
                if len(new) < 4:
                    self._send({"error": "新密码至少 4 位"}, 400); return
                if old != _pw[0]:
                    self._send({"error": "原密码错误"}, 403); return
                _pw[0] = new
                try:
                    lines, found = [], False
                    with open(CFG["env_path"]) as f:
                        for line in f:
                            if line.startswith("PANEL_PASSWORD="):
                                lines.append(f"PANEL_PASSWORD={new}\n"); found = True
                            else:
                                lines.append(line)
                    if not found:
                        lines.append(f"PANEL_PASSWORD={new}\n")
                    with open(CFG["env_path"], "w") as f:
                        f.writelines(lines)
                except:
                    pass
                try:
                    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, timeout=10)
                except:
                    pass
                self._send({"ok": True, "message": "密码已修改"})
            except Exception as e:
                self._send({"error": str(e)}, 500)
            return

        if path == "/api/switch":
            try:
                d = json.loads(body)
                provider = d.get("provider", "")
                model_id = d.get("model_id", "")
                if not provider or not model_id:
                    self._send({"error": "需要 provider 和 model_id"}, 400); return
                ok, msg = switch_model(provider, model_id)
                self._send({"ok": ok, "message": msg})
            except Exception as e:
                self._send({"error": str(e)}, 500)
        elif path == "/api/chat":
            try:
                d = json.loads(body)
                self._send(chat_with_provider(d.get("provider", ""), d.get("model_id", ""), d.get("message", "")))
            except Exception as e:
                self._send({"error": str(e)}, 500)
        elif path == "/api/reload":
            ok, msg = restart_service()
            self._send({"ok": ok, "message": msg})
        else:
            self.send_error(404)

# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    load_env()
    _pw[0] = os.environ.get("PANEL_PASSWORD", "changeme")

    # 检测框架
    fw = detect_framework()
    print(f"  框架: {fw['label']}")
    print(f"  配置: {CFG['config']}")
    print(f"  格式: {'YAML' if CFG['format']=='yaml' or (CFG['format']=='auto' and CFG['config'].endswith(('.yaml','.yml'))) else 'JSON'}")
    print(f"  端口: {CFG['port']}")

    server = HTTPServer(("0.0.0.0", CFG["port"]), Handler)
    print(f"面板已启动: http://127.0.0.1:{CFG['port']}")
    server.serve_forever()
