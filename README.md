# OpenClaw Model Switch Panel

OpenClaw 模型切换面板。在网页上查看所有模型提供商的连通性和延迟，一键切换模型——**所有平台同时生效**（Telegram、飞书、Discord、微信等）。

## 功能

- 提供商状态实时检测（延迟、可用性）
- 模型分组展示（按提供商）
- 一键切换模型 → 自动更新配置 + 所有平台会话 + 热重载 Gateway
- 直接对话测试（`/api/chat`，跳过 Gateway，直连 API）
- 密码保护 + 修改口令

## 前置依赖

- OpenClaw Gateway（2026.5+）
- systemd（user mode）
- Python 3.10+
- nginx（可选，域名访问用）

## 安装

```bash
# 1. 下载文件到 OpenClaw 脚本目录
cp model-switch.py model-switch.html ~/.openclaw/workspace/scripts/

# 2. 设置面板口令（首次部署）
# 把下面的 CHANGE_MY_PASSWORD 换成你自己的密码
echo "PANEL_PASSWORD=CHANGE_MY_PASSWORD" >> ~/.openclaw/gateway.systemd.env

# 3. 安装系统服务
cp model-switch.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now openclaw-model-switch.service

# 4. 验证
curl http://127.0.0.1:18790/
```

> 提供商和 API Key 通过 OpenClaw 配置文件（`openclaw.json`）自动读取，无需额外配置。

## 修改口令

部署后修改口令请用**面板上的「修改口令」按钮**（右上角），输入原口令和新口令即可。也可以手动编辑 `gateway.systemd.env` 文件：

```bash
# 修改 PANEL_PASSWORD= 这一行的值，然后重启面板
systemctl --user restart openclaw-model-switch.service
```

> ⚠️ 不要重复执行 `echo "PANEL_PASSWORD=..." >>`，否则文件里会多行冲突。

## nginx 反代（可选）

```nginx
server {
    listen 80;
    server_name panel.example.com;
    location / {
        proxy_pass http://127.0.0.1:18790;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## API

| 路径 | 方法 | 说明 |
|---|---|---|
| `/api/status` | GET | 查询所有提供商连通性 |
| `/api/config` | GET | 获取当前配置 |
| `/api/models` | GET | 获取所有可用模型 |
| `/api/switch` | POST | 切换模型（所有平台同步） |
| `/api/chat` | POST | 直接对话测试 |
| `/api/reload` | POST | 重载 Gateway |
| `/api/login` | POST | 登录获取 Token |
| `/api/change-password` | POST | 修改口令 |

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `PANEL_PASSWORD` | 是 | 面板登录口令 |
| `HTTP_PROXY` | 否 | HTTP 代理地址 |
| `HTTPS_PROXY` | 否 | HTTPS 代理地址 |
| `NO_PROXY` | 否 | 不走代理的域名 |

各提供商的 API Key 通过 `openclaw.json` 中的 `models.providers.*.apiKey` 字段自动读取。

## 工作原理

1. 面板读取 OpenClaw 配置（`openclaw.json`）中所有提供商和模型
2. 切换模型时 **同时更新**：config + 所有平台会话（`sessions.json`）+ SIGHUP 热重载 Gateway
3. 所有平台（Telegram / 飞书 / Discord / 微信 / WebChat）即时生效
