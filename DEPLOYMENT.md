# Alpha AI PWA 云服务器部署指南

> 这份文档主要对应旧的 `mobile_app` PWA。
> 原生 App 的公网发布，请优先看 [公网发布说明_20260312.md](/Users/zchtech002/machengyu/quant_multifactor/公网发布说明_20260312.md)。

## 📋 部署步骤

### 1️⃣ 准备工作

**购买云服务器:**
- 阿里云: https://www.aliyun.com/product/ecs
- 腾讯云: https://cloud.tencent.com/product/cvm
- AWS: https://aws.amazon.com/ec2/

**配置建议:**
- CPU: 2核
- 内存: 4GB
- 硬盘: 40GB SSD
- 系统: Ubuntu 22.04 LTS
- 带宽: 5Mbps
- 费用: ~¥100/月

**域名准备:**
- 购买域名 (阿里云/腾讯云/GoDaddy)
- 完成ICP备案 (国内服务器必须)
- DNS解析到服务器IP

---

### 2️⃣ 上传代码到服务器

**方法1: Git (推荐)**
```bash
# 本地推送到Git仓库
cd /Users/zchtech002/machengyu/quant_multifactor
git init
git add .
git commit -m "PWA移动端完成"
git remote add origin https://github.com/你的用户名/alpha-ai.git
git push -u origin main

# 服务器拉取
ssh root@你的服务器IP
git clone https://github.com/你的用户名/alpha-ai.git
cd alpha-ai
```

**方法2: SCP直接上传**
```bash
# 本地执行
cd /Users/zchtech002/machengyu
tar -czf quant_multifactor.tar.gz quant_multifactor/
scp quant_multifactor.tar.gz root@你的服务器IP:/root/

# 服务器解压
ssh root@你的服务器IP
tar -xzf quant_multifactor.tar.gz
cd quant_multifactor
```

---

### 3️⃣ 运行部署脚本

**SSH登录服务器:**
```bash
ssh root@你的服务器IP
```

**执行部署:**
```bash
cd quant_multifactor
chmod +x deploy.sh
./deploy.sh alpha.yourdomain.com
```

**脚本会自动完成:**
1. ✅ 安装系统依赖 (Python/Node.js/Nginx)
2. ✅ 安装Python包 (FastAPI/uvicorn)
3. ✅ 构建前端 (npm run build)
4. ✅ 配置Nginx反向代理
5. ✅ 申请SSL证书 (Let's Encrypt)
6. ✅ 配置systemd服务 (开机自启)
7. ✅ 启动后端API服务
8. ✅ 重启Nginx

---

### 4️⃣ 验证部署

**检查服务状态:**
```bash
# 后端API
sudo systemctl status alpha-ai-backend

# Nginx
sudo systemctl status nginx

# 查看日志
sudo journalctl -u alpha-ai-backend -f
```

**测试访问:**
```bash
# 本地测试
curl https://alpha.yourdomain.com/api/system

# 浏览器访问
https://alpha.yourdomain.com
```

---

### 5️⃣ 手机添加到主屏幕

**iOS:**
1. Safari打开 `https://alpha.yourdomain.com`
2. 点击底部分享按钮 ⬆️
3. 选择"添加到主屏幕"
4. 完成！桌面出现Alpha AI图标

**Android:**
1. Chrome打开 `https://alpha.yourdomain.com`
2. 点击右上角菜单 ⋮
3. 选择"添加到主屏幕"
4. 完成！

---

## 🔧 常用运维命令

### 服务管理
```bash
# 重启后端
sudo systemctl restart alpha-ai-backend

# 重启Nginx
sudo systemctl reload nginx

# 查看后端日志
sudo journalctl -u alpha-ai-backend -f

# 查看Nginx日志
sudo tail -f /var/log/nginx/error.log
```

### 更新代码
```bash
cd /opt/alpha-ai

# 拉取最新代码
git pull

# 重新构建前端
cd mobile_app
npm run build
cd ..

# 重启服务
sudo systemctl restart alpha-ai-backend
sudo systemctl reload nginx
```

### SSL证书续期
```bash
# 自动续期 (certbot已配置cron)
sudo certbot renew

# 手动续期
sudo certbot renew --force-renewal
```

---

## 🔒 安全配置

### 防火墙设置
```bash
# 安装UFW
sudo apt install ufw

# 允许SSH/HTTP/HTTPS
sudo ufw allow 22
sudo ufw allow 80
sudo ufw allow 443

# 启用防火墙
sudo ufw enable
```

### 修改SSH端口 (可选)
```bash
# 编辑SSH配置
sudo nano /etc/ssh/sshd_config

# 修改端口
Port 2222

# 重启SSH
sudo systemctl restart sshd

# 防火墙允许新端口
sudo ufw allow 2222
```

---

## 📊 性能优化

### Nginx缓存配置
```nginx
# 在 /etc/nginx/sites-available/alpha-ai 添加
proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=api_cache:10m max_size=100m;

location /api {
    proxy_cache api_cache;
    proxy_cache_valid 200 5m;
    proxy_cache_key "$request_uri";
    # ... 其他配置
}
```

### 后端进程数优化
```bash
# 使用Gunicorn多进程
pip install gunicorn

# 修改 systemd 服务
ExecStart=/opt/alpha-ai/venv/bin/gunicorn -w 4 -k uvicorn.workers.UvicornWorker api_server:app --bind 0.0.0.0:8000
```

### 世界硬源网关
```bash
# 启动 world gateway
python3 world_data_gateway.py

# 或作为独立 systemd 服务运行
ExecStart=/opt/alpha-ai/venv/bin/python world_data_gateway.py

# 后端接本机 gateway
Environment="WORLD_DATA_GATEWAY_BASE_URL=http://127.0.0.1:18080"
```

---

## 🔍 故障排查

### 问题1: 502 Bad Gateway
```bash
# 检查后端是否运行
sudo systemctl status alpha-ai-backend

# 检查端口占用
sudo netstat -tlnp | grep 8000

# 查看后端日志
sudo journalctl -u alpha-ai-backend -n 50
```

### 问题2: SSL证书申请失败
```bash
# 检查域名解析
nslookup alpha.yourdomain.com

# 检查80端口
sudo netstat -tlnp | grep :80

# 手动申请
sudo certbot --nginx -d alpha.yourdomain.com
```

### 问题3: WebSocket连接失败
```bash
# 检查Nginx配置
sudo nginx -t

# 查看Nginx错误日志
sudo tail -f /var/log/nginx/error.log

# 测试WebSocket
wscat -c wss://alpha.yourdomain.com/ws
```

---

## 📱 部署后效果

**访问地址:**
```
https://alpha.yourdomain.com
```

**功能:**
- ✅ 全球任何地方访问
- ✅ HTTPS安全加密
- ✅ 添加到主屏幕
- ✅ 离线访问
- ✅ 推送通知
- ✅ 自动更新
- ✅ 原生APP体验

---

## 💰 成本估算

| 项目 | 费用 | 周期 |
|------|------|------|
| 云服务器 (2核4G) | ¥100 | /月 |
| 域名 | ¥50 | /年 |
| SSL证书 | ¥0 (Let's Encrypt免费) | - |
| 备案 | ¥0 | 一次性 |
| **总计** | **¥100/月** | - |

---

## 🎯 下一步

1. **购买云服务器** (阿里云/腾讯云)
2. **购买域名** (如 alpha-ai.com)
3. **完成ICP备案** (国内服务器必须)
4. **上传代码到服务器**
5. **运行部署脚本** `./deploy.sh alpha.yourdomain.com`
6. **手机添加到主屏幕**
7. **开始使用！**

---

**需要帮助？**
- 查看日志: `sudo journalctl -u alpha-ai-backend -f`
- 重启服务: `sudo systemctl restart alpha-ai-backend`
- Nginx配置: `/etc/nginx/sites-available/alpha-ai`
