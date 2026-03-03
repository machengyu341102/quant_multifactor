#!/bin/bash
# launchd 安装脚本
# 用法: bash launchd/install.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAUNCH_DIR="$HOME/Library/LaunchAgents"

mkdir -p "$LAUNCH_DIR"

echo "安装 launchd 服务..."

# 安装 watchdog (每10分钟健康检查)
cp "$SCRIPT_DIR/com.quant.watchdog.plist" "$LAUNCH_DIR/"
launchctl load "$LAUNCH_DIR/com.quant.watchdog.plist" 2>/dev/null
echo "  [OK] com.quant.watchdog — 每10分钟健康检查"

# 安装 scheduler (常驻守护进程, 崩溃自动重启)
cp "$SCRIPT_DIR/com.quant.scheduler.plist" "$LAUNCH_DIR/"
launchctl load "$LAUNCH_DIR/com.quant.scheduler.plist" 2>/dev/null
echo "  [OK] com.quant.scheduler — 常驻守护 + 崩溃自动重启"

echo ""
echo "安装完成! 查看状态:"
echo "  launchctl list | grep quant"
echo ""
echo "卸载:"
echo "  launchctl unload ~/Library/LaunchAgents/com.quant.watchdog.plist"
echo "  launchctl unload ~/Library/LaunchAgents/com.quant.scheduler.plist"
