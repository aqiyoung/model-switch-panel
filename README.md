# Model Switch Panel

通用模型切换面板。在网页上查看所有模型提供商的连通性和延迟，一键切换模型——**所有平台同时生效**。

## 支持的框架

| 框架 | 配置文件 | 格式 |
|---|---|---|
| **OpenClaw** | `~/.openclaw/openclaw.json` | JSON（默认） |
| **Hermes** | `~/.hermes/config.yaml` | YAML |

面板会自动检测：配置文件后缀是 `.yaml` / `.yml` → Hermes，否则 OpenClaw。也可设置环境变量 `PANEL_FRAMEWORK=hermes` 强制指定。

---

## 安装（OpenClaw 用户）

### 1. 下载文件

把 `model-switch.py` 和 `model-switch.html` 放到 OpenClaw 脚本目录：

```bash
cp model-switch.py model-switch.html ~/.openclaw/workspace/scripts/
```

### 2. 安装 Python 依赖

```bash
# YAML 支持（非必需，只有 Hermes 用户需要）
pip install pyyaml
```

### 3. 设置面板登录口令

```bash
echo "PANEL_PASSWORD=你的密码" >> ~/.openclaw/gateway.systemd.env
```

> ⚠️ 把 `你的密码` 换成真的密码。如果不设，默认口令是 `changeme`。
>
> ⚠️ 这个命令只能执行**一次**。每次 `>>` 都会追加一行，如果执行多次文件里会有多行 `PANEL_PASSWORD=`，造成冲突。改密码请登陆面板后点右上角「修改口令」。

### 4. 修改 service 文件路径

编辑 `model-switch.service`，把 `ExecStart=` 后面的路径改成你实际的路径：

```ini
ExecStart=/usr/bin/python3 /home/你的用户名/.openclaw/workspace/scripts/model-switch.py
```

### 5. 安装系统服务

```bash
cp model-switch.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now model-switch.service
```

### 6. 验证

```bash
systemctl --user status model-switch.service
# 看到 active (running) 就成功了

curl http://127.0.0.1:18790/
# 返回 HTML 页面内容
```

### 7. 访问

浏览器打开 `http://你的服务器IP:18790`，输入口令登录。

> 如果需要域名 + HTTPS，参考下面的 nginx 反代。

---

## 安装（Hermes 用户）

### 1. 下载文件

```bash
cp model-switch.py model-switch.html ~/.hermes/
```

### 2. 安装 Python 依赖

```bash
pip install pyyaml
```

### 3. 设置面板登录口令

```bash
echo "PANEL_PASSWORD=你的密码" >> ~/.hermes/.env
```

### 4. 配置面板环境变量

把 Hermes 的配置告诉面板：

```bash
cat >> ~/.hermes/.env << 'EOF'
PANEL_CONFIG=~/.hermes/config.yaml
PANEL_SERVICE=hermes-gateway.service
PANEL_MODEL_FIELD=model.default
PANEL_FRAMEWORK=hermes
PANEL_ENV_PATH=~/.hermes/.env
EOF
```

### 5. 修改 service 文件路径

编辑 `model-switch.service`，把 `ExecStart=` 和 `EnvironmentFile=` 路径改对。

### 6. 安装系统服务

```bash
cp model-switch.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now model-switch.service
```

---

## nginx 反代（可选）

通过域名 + HTTPS 访问：

```nginx
server {
    listen 80;
    server_name panel.你的域名.com;
    location / {
        proxy_pass http://127.0.0.1:18790;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

> 之后用 certbot 申请 SSL 证书，把 80 改为 443 即可。

---

## 修改口令

部署后改口令有两种方式：

| 方式 | 操作 |
|---|---|
| **面板上点按钮**（推荐） | 右上角「修改口令」，输入原口令+新口令 |
| **手动改文件** | 编辑 `PANEL_ENV_PATH` 对应的文件，改 `PANEL_PASSWORD=` 那一行，然后 `systemctl --user restart model-switch.service` |

> ⚠️ 不要重复用 `echo "PANEL_PASSWORD=..." >>` 追加，会多行冲突。

---

## API

| 路径 | 方法 | 说明 |
|---|---|---|
| `/api/status` | GET | 查询所有提供商连通性 |
| `/api/config` | GET | 获取当前配置 |
| `/api/models` | GET | 获取所有可用模型 |
| `/api/switch` | POST | 切换模型 |
| `/api/chat` | POST | 直连 API 对话测试 |
| `/api/reload` | POST | 重载服务 |
| `/api/login` | POST | 登录 |
| `/api/change-password` | POST | 修改口令 |

---

## 环境变量（完整参考）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PANEL_PASSWORD` | `changeme` | 面板登录口令 |
| `PANEL_CONFIG` | `~/.openclaw/openclaw.json` | 配置文件路径 |
| `PANEL_CONFIG_FORMAT` | `auto` | json / yaml / auto |
| `PANEL_SESSIONS` | `~/.openclaw/agents/main/sessions/sessions.json` | 会话文件路径（仅 OpenClaw） |
| `PANEL_SERVICE` | `openclaw-gateway.service` | systemd 服务名 |
| `PANEL_RESTART_CMD` | — | 自定义重启命令（优先于 systemd） |
| `PANEL_PORT` | `18790` | 监听端口 |
| `PANEL_ENV_PATH` | `~/.openclaw/gateway.systemd.env` | 面板读取的环境变量文件 |
| `PANEL_MODEL_FIELD` | 自动 | 配置文件中模型字段路径（Hermes: `model.default`） |
| `PANEL_PROVIDERS_PATH` | 自动 | Provider 定义路径（仅 OpenClaw） |
| `PANEL_FRAMEWORK` | `auto` | openclaw / hermes / auto |
