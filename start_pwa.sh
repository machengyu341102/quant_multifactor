#!/bin/bash

# Alpha AI PWA 快速启动脚本

echo "🚀 启动 Alpha AI PWA 开发环境"
echo ""

# 检查依赖
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到 python3，请先安装"
    exit 1
fi

if ! command -v node &> /dev/null; then
    echo "❌ 未找到 node，请先安装"
    exit 1
fi

# 进入项目目录
cd "$(dirname "$0")"

# 启动后端
echo "📡 启动后端 API 服务 (端口 8000)..."
python3 api_server.py &
BACKEND_PID=$!
echo "后端 PID: $BACKEND_PID"

# 等待后端启动
sleep 2

# 启动前端
echo ""
echo "📱 启动前端开发服务器 (端口 3000)..."
cd mobile_app

# 检查是否已安装依赖
if [ ! -d "node_modules" ]; then
    echo "📦 首次运行，安装依赖..."
    npm install
fi

npm run dev &
FRONTEND_PID=$!
echo "前端 PID: $FRONTEND_PID"

echo ""
echo "✅ 启动完成！"
echo ""
echo "📡 后端 API: http://localhost:8000"
echo "📚 API 文档: http://localhost:8000/docs"
echo "📱 前端应用: http://localhost:3000"
echo ""
echo "按 Ctrl+C 停止所有服务"

# 捕获退出信号
trap "echo ''; echo '🛑 停止服务...'; kill $BACKEND_PID $FRONTEND_PID; exit" INT TERM

# 等待
wait
