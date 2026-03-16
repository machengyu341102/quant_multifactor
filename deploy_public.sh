#!/bin/bash
#
# Alpha AI Native 公网部署脚本
# 用法: ./deploy_public.sh api.example.com download.example.com
#

set -euo pipefail

API_DOMAIN=${1:-"api.example.com"}
DOWNLOAD_DOMAIN=${2:-"download.example.com"}
APP_DIR="/opt/alpha-ai"
DOWNLOAD_DIR="/var/www/alpha-ai-downloads"
SERVICE_NAME="alpha-ai-api"
BACKEND_PORT=8000

echo "Alpha AI Native 公网部署"
echo "API 域名: $API_DOMAIN"
echo "下载域名: $DOWNLOAD_DOMAIN"
echo

sudo apt update
sudo apt install -y \
  python3 \
  python3-pip \
  python3-venv \
  nginx \
  certbot \
  python3-certbot-nginx \
  rsync \
  curl

sudo mkdir -p "$APP_DIR" "$DOWNLOAD_DIR"
sudo chown -R "$USER:$USER" "$APP_DIR"
sudo chown -R "$USER:$USER" "$DOWNLOAD_DIR"

rsync -av --delete ./ "$APP_DIR"/ \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude 'mobile_app/node_modules' \
  --exclude 'native_app/node_modules' \
  --exclude 'native_app/android/app/build' \
  --exclude 'native_app/android/build' \
  --exclude 'native_app/.expo'

cd "$APP_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.server.txt

if [ -f ".env.production" ]; then
  cp .env.production .env
elif [ ! -f ".env" ]; then
  cp .env.production.example .env
  echo "已生成 .env，请先编辑 $APP_DIR/.env 后再继续。"
fi

mkdir -p public_release/releases
rsync -av --delete public_release/ "$DOWNLOAD_DIR"/

sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" >/dev/null <<EOF
[Unit]
Description=Alpha AI Trading API
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
Environment=PATH=$APP_DIR/venv/bin
ExecStart=$APP_DIR/venv/bin/uvicorn api_server:app --host 127.0.0.1 --port $BACKEND_PORT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/nginx/sites-available/alpha-ai-public >/dev/null <<EOF
server {
    listen 80;
    server_name $API_DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:$BACKEND_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}

server {
    listen 80;
    server_name $DOWNLOAD_DOMAIN;
    root $DOWNLOAD_DIR;
    index index.html;

    location / {
        try_files \$uri \$uri/ /index.html;
    }

    location /releases/ {
        add_header Cache-Control "public, max-age=300";
    }

    location = /alpha-ai-latest.apk {
        add_header Cache-Control "no-store";
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/alpha-ai-public /etc/nginx/sites-enabled/alpha-ai-public
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl reload nginx

echo
echo "部署完成。"
echo "API: http://$API_DOMAIN"
echo "下载页: http://$DOWNLOAD_DOMAIN"
echo
echo "后续建议："
echo "1. 编辑 $APP_DIR/.env，填入真实密码和 CORS 域名"
echo "2. 运行 certbot 给 $API_DOMAIN 和 $DOWNLOAD_DOMAIN 申请 HTTPS"
echo "3. 原生包构建时把 EXPO_PUBLIC_API_BASE_URL 指向 https://$API_DOMAIN"
