#!/bin/bash

# 快速修复脚本 - 只打包修复的文件

set -e

echo "创建修复包..."

FIX_DIR="aifriend_fix_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$FIX_DIR/backend/services"
mkdir -p "$FIX_DIR/backend/routers"

# 复制修复的文件
cp backend/main.py "$FIX_DIR/backend/"
cp backend/database.py "$FIX_DIR/backend/"
cp backend/services/cache_service.py "$FIX_DIR/backend/services/"

# 打包
tar -czf "${FIX_DIR}.tar.gz" "$FIX_DIR"
rm -rf "$FIX_DIR"

echo "✅ 修复包已创建: ${FIX_DIR}.tar.gz"
echo ""
echo "上传并解压："
echo "scp ${FIX_DIR}.tar.gz user@server:/opt/aifriend/"
echo "cd /opt/aifriend && tar -xzf ${FIX_DIR}.tar.gz"
echo "cp -r ${FIX_DIR}/backend/* backend/"
echo "rm -rf ${FIX_DIR}*"
