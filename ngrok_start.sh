#!/bin/bash
#
# 使用 ngrok 快速获得公网访问地址
# 用法: ./ngrok_start.sh
#

echo "🚀 启动 ngrok 内网穿透..."
echo ""

# 检查 ngrok 是否安装
if ! command -v ngrok &> /dev/null; then
    echo "📦 ngrok 未安装，正在安装..."

    # Mac安装
    if [[ "$OSTYPE" == "darwin"* ]]; then
        if command -v brew &> /dev/null; then
            brew install ngrok/ngrok/ngrok
        else
            echo "请先安装 Homebrew: https://brew.sh"
            exit 1
        fi
    else
        echo "请手动安装 ngrok: https://ngrok.com/download"
        exit 1
    fi
fi

echo "✅ ngrok 已安装"
echo ""

# 检查服务是否运行
if ! curl -s http://localhost:3000 > /dev/null; then
    echo "❌ 前端服务未运行，请先启动:"
    echo "   cd mobile_app && npm run dev"
    exit 1
fi

echo "✅ 前端服务运行中"
echo ""

# 启动 ngrok
echo "🌐 启动 ngrok 隧道..."
echo ""
echo "⚠️  注意: 免费版每次重启URL会变化"
echo ""

ngrok http 3000
