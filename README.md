# model-switch-panel

通用模型切换面板 — 原生支持 OpenClaw (JSON) + Hermes (YAML) 双框架。

在网页上查看所有模型提供商的连通性和延迟，一键切换模型。

## 功能

- 实时检测各模型提供商连通性和延迟
- 一键切换默认模型
- 配置热重载（切换后立即生效）
- 手机浏览器完全适配
- 支持 OpenClaw 和 Hermes 双框架

## 快速安装

```bash
git clone https://github.com/aqiyoung/model-switch-panel.git
cd model-switch-panel
bash install.sh
```

## 手动安装

1. 复制文件到安装目录：
```bash
mkdir -p ~/model-switch
cp model-switch.py model-switch.html ~/.model-switch/
```

2. 创建 systemd 服务：
```bash
mkdir -p ~/.config/systemd/user
cp model-switch.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable model-switch
systemctl --user start model-switch
```

3. 配置 nginx 反代（可选）：
```nginx
server {
    listen 443 ssl http2;
    server_name model.example.com;
    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;
    location / {
        proxy_pass http://127.0.0.1:18790;
        proxy_set_header Host $host;
    }
}
```

## 管理命令

```bash
# 查看状态
systemctl --user status model-switch

# 重启服务
systemctl --user restart model-switch

# 查看日志
journalctl --user -u model-switch -f

# 停止服务
systemctl --user stop model-switch

# 禁用自动启动
systemctl --user disable model-switch
```

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PANEL_PASSWORD` | `changeme` | 面板登录口令 |
| `PANEL_CONFIG` | `~/.openclaw/openclaw.json` | 配置文件路径 |
| `PANEL_CONFIG_FORMAT` | `auto` | json / yaml / auto |
| `PANEL_SERVICE` | `openclaw-gateway.service` | systemd 服务名 |
| `PANEL_PORT` | `18790` | 监听端口 |
| `PANEL_ENV_PATH` | `~/.openclaw/gateway.systemd.env` | 环境变量文件路径 |
| `PANEL_MODEL_FIELD` | 自动检测 | 模型字段路径（Hermes 设为 `model.default`） |
| `PANEL_FRAMEWORK` | `auto` | openclaw / hermes / auto |

## 注意事项

- 服务配置了 `Restart=always`，崩溃后会自动重启
- 设置了 `WatchdogSec=60`，确保服务健康
- 首次访问需要输入密码（默认: changeme）
- 修改配置后会自动热重载 OpenClaw gateway
