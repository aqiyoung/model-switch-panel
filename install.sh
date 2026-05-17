#!/bin/bash
set -e

# ============================================================
# model-switch-panel 安装脚本
# 用于 OpenClaw / Hermes 模型切换面板
# ============================================================

echo "=== model-switch-panel 安装脚本 ==="

# 1. 安装目录
INSTALL_DIR="$HOME/model-switch"
mkdir -p "$INSTALL_DIR"

# 2. 复制文件
echo "[1/5] 复制文件..."
cp model-switch.py "$INSTALL_DIR/"
cp model-switch.html "$INSTALL_DIR/"
cp .env.example "$INSTALL_DIR/.env"

# 3. 配置环境变量
echo "[2/5] 配置环境变量..."
if [ -f "$HOME/.openclaw/gateway.systemd.env" ]; then
    ENV_PATH="$HOME/.openclaw/gateway.systemd.env"
elif [ -f "$HOME/.hermes/.env" ]; then
    ENV_PATH="$HOME/.hermes/.env"
else
    ENV_PATH="$INSTALL_DIR/.env"
fi
echo "  环境变量文件: $ENV_PATH"

# 4. 配置密码
read -sp "  设置面板登录口令 (默认: changeme): " PASSWORD
echo ""
PASSWORD=${PASSWORD:-changeme}

# 5. 创建 systemd 服务
echo "[3/5] 创建 systemd 服务..."
SERVICE_FILE="$HOME/.config/systemd/user/model-switch.service"

mkdir -p "$(dirname "$SERVICE_FILE")"

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Model Switch Panel
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $INSTALL_DIR/model-switch.py
Restart=always
RestartSec=5
Environment=PANEL_PASSWORD=$PASSWORD
Environment=PANEL_ENV_PATH=$ENV_PATH

[Install]
WantedBy=default.target
EOF

# 6. 启动服务
echo "[4/5] 启动服务..."
systemctl --user daemon-reload
systemctl --user enable model-switch.service
systemctl --user start model-switch.service

# 7. 配置 nginx 反代（可选）
echo "[5/5] 配置 nginx 反代..."
if command -v nginx &>/dev/null; then
    NGINX_CONF="/etc/nginx/conf.d/model-switch.conf"
    if [ ! -f "$NGINX_CONF" ]; then
        read -p "  输入域名 (如 model.example.com，留空跳过): " DOMAIN
        if [ -n "$DOMAIN" ]; then
            cat > "$NGINX_CONF" << NGINX
server {
    listen 80;
    server_name $DOMAIN;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name $DOMAIN;
    ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    location / {
        proxy_pass http://127.0.0.1:18790;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
NGINX
            sudo nginx -t && sudo nginx -s reload
            echo "  ✅ nginx 反代已配置: https://$DOMAIN"
        fi
    else
        echo "  nginx 配置已存在，跳过"
    fi
else
    echo "  nginx 未安装，跳过"
fi

# 8. 完成
echo ""
echo "=== 安装完成 ==="
echo "  安装目录: $INSTALL_DIR"
echo "  服务文件: $SERVICE_FILE"
echo "  访问地址: http://localhost:18790"
echo ""
echo "  管理命令:"
echo "    查看状态: systemctl --user status model-switch"
echo "    重启服务: systemctl --user restart model-switch"
echo "    查看日志: journalctl --user -u model-switch -f"
