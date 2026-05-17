# Model Switch Panel

通用模型切换面板。在网页上查看所有模型提供商的连通性和延迟，一键切换模型——**所有平台同时生效**。

## 支持的框架

| 框架 | 配置格式 | 默认路径 |
|---|---|---|
| **OpenClaw** | JSON | `~/.openclaw/openclaw.json` |
| **Hermes** | YAML | `~/.hermes/config.yaml` |

自动检测：`.yaml` / `.yml` 后缀 → Hermes，否则 OpenClaw。也可通过 `PANEL_FRAMEWORK` 强制指定。

## 功能

- 提供商状态实时检测（延迟、可用性）
- 模型分组展示（按提供商）
- 一键切换模型 → 更新配置 + 同步会话 + 热重载服务
- 直连 API 对话测试（跳过 Bot）
- 密码保护 + 修改口令
- 框架自动适配（JSON / YAML / 不同 Provider 来源）

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PANEL_PASSWORD` | `changeme` | 面板登录口令 |
| `PANEL_CONFIG` | `~/.openclaw/openclaw.json` | 配置文件路径 |
| `PANEL_CONFIG_FORMAT` | `auto` | json / yaml / auto |
| `PANEL_SESSIONS` | `~/.openclaw/agents/main/sessions/sessions.json` | 会话文件（仅 OpenClaw） |
| `PANEL_SERVICE` | `openclaw-gateway.service` | systemd 服务名 |
| `PANEL_RESTART_CMD` | — | 自定义重启命令 |
| `PANEL_PORT` | `18790` | 监听端口 |
| `PANEL_ENV_PATH` | `~/.openclaw/gateway.systemd.env` | 环境变量文件 |
| `PANEL_MODEL_FIELD` | 自动 | 模型字段路径 (Hermes: `model.default`) |
| `PANEL_PROVIDERS_PATH` | 自动 | Provider 路径 (Hermes 不从配置读取) |
| `PANEL_FRAMEWORK` | `auto` | openclaw / hermes / auto |

## 安装

```bash
# 1. 下载文件
cp model-switch.py model-switch.html /path/to/script/dir/

# 2. 安装依赖（如需 YAML 支持）
pip install pyyaml

# 3. 设置口令
echo "PANEL_PASSWORD=CHANGE_MY_PASSWORD" >> ~/.openclaw/gateway.systemd.env

# 4. 安装服务
cp model-switch.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now model-switch.service

# 5. 验证
curl http://127.0.0.1:18790/
```

### Hermes 用户

```bash
# 设置 Hermes 相关环境变量
echo "PANEL_CONFIG=~/.hermes/config.yaml" >> ~/.hermes/.env
echo "PANEL_SERVICE=hermes-gateway.service" >> ~/.hermes/.env
echo "PANEL_MODEL_FIELD=model.default" >> ~/.hermes/.env
echo "PANEL_FRAMEWORK=hermes" >> ~/.hermes/.env
```

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
