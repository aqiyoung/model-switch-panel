#!/usr/bin/env python3
"""
model-switch.py - 通用模型切换面板

在网页上查看所有模型提供商的连通性和延迟，一键切换模型。
支持 OpenClaw、Hermes 等任意 Bot 框架，通过环境变量配置。

环境变量:
  PANEL_CONFIG      配置文件路径            默认: ~/.openclaw/openclaw.json
  PANEL_SESSIONS    会话文件路径            默认: ~/.openclaw/agents/main/sessions/sessions.json
  PANEL_SERVICE     systemd 服务名          默认: openclaw-gateway.service
  PANEL_PORT        监听端口                默认: 18790
  PANEL_PASSWORD    面板登录口令            默认: changeme
  PANEL_PROVIDERS_PATH   JSON 中 provider 路径  默认: models.providers
  PANEL_DEFAULT_MODEL_PATH  JSON 中默认模型路径  默认: agents.defaults.model
"""

import json
import os
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
# 配置（可通过环境变量覆盖）
# ---------------------------------------------------------------------------

CFG = {
    "config": os.path.expanduser(os.environ.get("PANEL_CONFIG", "~/.openclaw/openclaw.json")),
    "sessions": os.path.expanduser(os.environ.get("PANEL_SESSIONS", "~/.openclaw/agents/main/sessions/sessions.json")),
    "service": os.environ.get("PANEL_SERVICE", "openclaw-gateway.service"),
    "port": int(os.environ.get("PANEL_PORT", "18790")),
    "providers_path": os.environ.get("PANEL_PROVIDERS_PATH", "models.providers"),
    "default_model_path": os.environ.get("PANEL_DEFAULT_MODEL_PATH", "agents.defaults.model"),
    "env_path": os.path.expanduser(os.environ.get("PANEL_ENV_PATH", "~/.openclaw/gateway.systemd.env")),
}

_pw = [os.environ.get("PANEL_PASSWORD", "changeme")]
_tokens = {}

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def load_env():
    p = CFG["env_path"]
    if not os.path.exists(p):
        return
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k, v)

def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def deep_get(obj, path):
    """按 a.b.c 路径从嵌套 dict 中取值"""
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
# Provider / Config 读取
# ---------------------------------------------------------------------------

def load_providers():
    """从配置文件读取所有提供商（baseUrl, apiKey, models）"""
    cfg = read_json(CFG["config"])
    providers = deep_get(cfg, CFG["providers_path"])
    result = {}
    for pname, pconf in providers.items():
        base_url = pconf.get("baseUrl", "").rstrip("/")
        api_key = resolve_api_key(pconf.get("apiKey", ""))
        if not api_key or not base_url:
            continue
        display = pconf.get("name") or pname
        test_url = f"{base_url}/models" if "/v1" in base_url else f"{base_url}/v1/models"
        result[pname] = {
            "name": display,
            "test_url": test_url,
            "api_key": api_key,
        }
    return result

def get_provider_base_urls():
    """读取所有 provider 的 baseUrl 和 resolved apiKey（用于 chat）"""
    cfg = read_json(CFG["config"])
    providers = deep_get(cfg, CFG["providers_path"])
    result = {}
    for pname, pconf in providers.items():
        base_url = pconf.get("baseUrl", "").rstrip("/")
        api_key = resolve_api_key(pconf.get("apiKey", ""))
        if not api_key or not base_url:
            continue
        result[pname] = {"base_url": base_url, "api_key": api_key}
    return result

def get_all_models():
    """读取所有模型（分组）"""
    cfg = read_json(CFG["config"])
    providers = deep_get(cfg, CFG["providers_path"])
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
    if not pcfg:
        return {"error": f"未知提供商: {provider}"}
    api_key = pcfg.get("api_key", "")
    if not api_key:
        return {"error": f"{provider} 未设置 API Key"}
    url = f"{pcfg['base_url']}/chat/completions"
    body = json.dumps({
        "model": model_id,
        "messages": [{"role": "user", "content": message}],
        "max_tokens": 1024,
        "temperature": 0.7,
    }).encode()
    try:
        req = urllib.request.Request(url, data=body)
        req.add_header("Authorization", f"Bearer {api_key}")
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
    """通过 systemd 或 SIGHUP 重启服务"""
    # 优先 systemctl
    try:
        r = subprocess.run(["systemctl", "--user", "restart", CFG["service"]],
                          capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return True, f"systemd 服务 {CFG['service']} 已重启"
    except:
        pass
    # 回退 SIGHUP
    pid = None
    try:
        r = subprocess.run(["pgrep", "-f", CFG["service"].replace(".service", "")],
                          capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            pid = int(r.stdout.strip().split()[0])
    except:
        pass
    if pid:
        try:
            os.kill(pid, signal.SIGHUP)
            return True, f"SIGHUP 已发送 (PID {pid})"
        except Exception as e:
            return False, str(e)
    return False, "找不到服务进程"

def switch_model(provider, model_id):
    cfg = read_json(CFG["config"])
    old_model = deep_get(cfg, CFG["default_model_path"]).get("model", "")
    deep_set(cfg, CFG["default_model_path"], model_id)
    write_json(CFG["config"], cfg)

    # 更新会话（如有）
    session_updated = False
    try:
        if os.path.exists(CFG["sessions"]):
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
            cfg = read_json(CFG["config"])
            self._send({
                "default_model": deep_get(cfg, CFG["default_model_path"]).get("model", ""),
                "providers": list(deep_get(cfg, CFG["providers_path"]).keys()),
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
                                lines.append(f"PANEL_PASSWORD={new}\n")
                                found = True
                            else:
                                lines.append(line)
                    if not found:
                        lines.append(f"PANEL_PASSWORD={new}\n")
                    write_json(CFG["env_path"], "".join(lines))
                except:
                    pass
                try:
                    with open(CFG["env_path"], "w") as f:
                        f.writelines(lines)
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

    def _html(self):
        d = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(d, "model-switch.html")) as f:
            return f.read()

# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    load_env()
    _pw[0] = os.environ.get("PANEL_PASSWORD", "changeme")
    server = HTTPServer(("0.0.0.0", CFG["port"]), Handler)
    print(f"面板已启动: http://127.0.0.1:{CFG['port']}")
    server.serve_forever()