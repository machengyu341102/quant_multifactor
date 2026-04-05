#!/bin/bash
#
# Alpha AI PWA 生产环境部署脚本
# =====================================
# 用法: ./deploy.sh [域名]
# 示例: ./deploy.sh alpha.yourdomain.com
#

set -e

DOMAIN=${1:-"alpha.example.com"}
APP_DIR="/opt/alpha-ai"
BACKEND_PORT=8000
FRONTEND_PORT=3000

echo "🚀 Alpha AI PWA 部署脚本"
echo "域名: $DOMAIN"
echo "安装目录: $APP_DIR"
echo ""

# ================================================================
# 1. 系统环境准备
# ================================================================

echo "📦 [1/8] 更新系统包..."
sudo apt update
sudo apt upgrade -y

echo "📦 [2/8] 安装依赖..."
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    nginx \
    certbot \
    python3-certbot-nginx \
    git \
    curl

# 安装 Node.js 18
if ! command -v node &> /dev/null; then
    echo "📦 安装 Node.js 18..."
    curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
    sudo apt install -y nodejs
fi

echo "✅ Node 版本: $(node -v)"
echo "✅ npm 版本: $(npm -v)"
echo "✅ Python 版本: $(python3 --version)"

# ================================================================
# 2. 创建应用目录
# ================================================================

echo "📁 [3/8] 创建应用目录..."
sudo mkdir -p $APP_DIR
sudo chown -R $USER:$USER $APP_DIR

# ================================================================
# 3. 复制代码
# ================================================================

echo "📋 [4/8] 复制代码..."
# 假设当前在项目目录
cp -r . $APP_DIR/
cd $APP_DIR

# ================================================================
# 4. 安装Python依赖
# ================================================================

echo "🐍 [5/8] 安装Python依赖..."
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn websockets python-multipart

# ================================================================
# 5. 构建前端
# ================================================================

echo "⚛️  [6/8] 构建前端..."
cd mobile_app
npm install --registry https://registry.npmmirror.com
npm run build
cd ..

# ================================================================
# 6. 配置Nginx
# ================================================================

echo "🌐 [7/8] 配置Nginx..."
sudo tee /etc/nginx/sites-available/alpha-ai > /dev/null <<EOF
# Alpha AI PWA Nginx配置

# HTTP重定向到HTTPS
server {
    listen 80;
    server_name $DOMAIN;
    return 301 https://\$server_name\$request_uri;
}

# HTTPS主配置
server {
    listen 443 ssl http2;
    server_name $DOMAIN;

    # SSL证书 (certbot自动配置)
    ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # 前端静态文件
    location / {
        root $APP_DIR/mobile_app/dist;
        try_files \$uri \$uri/ /index.html;

        # PWA缓存策略
        add_header Cache-Control "public, max-age=31536000" always;
    }

    # Service Worker (不缓存)
    location ~* (sw\.js|workbox-.*\.js)$ {
        root $APP_DIR/mobile_app/dist;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }

    # 后端API
    location /api {
        proxy_pass http://127.0.0.1:$BACKEND_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # WebSocket
    location /ws {
        proxy_pass http://127.0.0.1:$BACKEND_PORT;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 86400;
    }

    # Gzip压缩
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;
}
EOF

# 启用站点
sudo ln -sf /etc/nginx/sites-available/alpha-ai /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# ================================================================
# 7. 配置SSL证书
# ================================================================

echo "🔒 [8/8] 配置SSL证书..."
echo "请确保域名 $DOMAIN 已解析到本服务器IP"
read -p "按回车继续申请SSL证书..."

sudo certbot --nginx -d $DOMAIN --non-interactive --agree-tos --email admin@$DOMAIN || {
    echo "⚠️  SSL证书申请失败，请检查:"
    echo "  1. 域名是否正确解析"
    echo "  2. 80/443端口是否开放"
    echo "  3. 手动运行: sudo certbot --nginx -d $DOMAIN"
}

# ================================================================
# 8. 配置systemd服务
# ================================================================

echo "⚙️  配置systemd服务..."

# 后端服务
sudo tee /etc/systemd/system/alpha-ai-backend.service > /dev/null <<EOF
[Unit]
Description=Alpha AI Backend API
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin"
Environment="WORLD_DATA_GATEWAY_BASE_URL=http://127.0.0.1:18080"
ExecStart=$APP_DIR/venv/bin/python api_server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 世界硬源网关服务
sudo tee /etc/systemd/system/alpha-ai-world-gateway.service > /dev/null <<EOF
[Unit]
Description=Alpha AI World Data Gateway
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
Environment="PATH=$APP_DIR/venv/bin"
ExecStart=$APP_DIR/venv/bin/python world_data_gateway.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 启动服务
sudo systemctl daemon-reload
sudo systemctl enable alpha-ai-backend
sudo systemctl enable alpha-ai-world-gateway
sudo systemctl start alpha-ai-world-gateway
sudo systemctl start alpha-ai-backend

# ================================================================
# 9. 完成
# ================================================================

echo ""
echo "✅ 部署完成！"
echo ""
echo "📱 访问地址: https://$DOMAIN"
echo ""
echo "🔍 检查服务状态:"
echo "  sudo systemctl status alpha-ai-backend"
echo "  sudo systemctl status nginx"
echo ""
echo "📋 查看日志:"
echo "  sudo journalctl -u alpha-ai-backend -f"
echo "  sudo tail -f /var/log/nginx/error.log"
echo ""
echo "🔄 重启服务:"
echo "  sudo systemctl restart alpha-ai-backend"
echo "  sudo systemctl reload nginx"
echo ""
