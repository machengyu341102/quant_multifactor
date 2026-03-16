#!/bin/bash

echo "📦 安装 PWA 移动端依赖..."
echo ""

cd "$(dirname "$0")/mobile_app"

# 检查 node 和 npm
if ! command -v node &> /dev/null; then
    echo "❌ 未找到 node，请先安装 Node.js"
    exit 1
fi

if ! command -v npm &> /dev/null; then
    echo "❌ 未找到 npm，请先安装 npm"
    exit 1
fi

echo "Node 版本: $(node -v)"
echo "npm 版本: $(npm -v)"
echo ""

# 安装依赖
echo "📥 安装依赖包..."
npm install

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ 依赖安装完成！"
    echo ""
    echo "🚀 启动开发服务器:"
    echo "   cd mobile_app && npm run dev"
    echo ""
    echo "或使用一键启动脚本:"
    echo "   ./start_pwa.sh"
else
    echo ""
    echo "❌ 依赖安装失败，请检查网络连接"
    exit 1
fi
