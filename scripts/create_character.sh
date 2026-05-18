#!/bin/bash
# 白小棠角色卡一键创建脚本
# 使用方法: bash create_character.sh

echo "🚀 开始创建白小棠角色卡..."

# 1. 先登录获取管理员 token（需要你提供管理员邮箱和密码）
echo ""
echo "请输入管理员邮箱:"
read ADMIN_EMAIL
echo "请输入管理员密码:"
read -s ADMIN_PASSWORD

echo ""
echo "正在登录..."

TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}" | \
  python3 -c "import sys, json; print(json.load(sys.stdin)['token'])" 2>/dev/null)

if [ -z "$TOKEN" ]; then
  echo "❌ 登录失败，请检查邮箱和密码"
  exit 1
fi

echo "✅ 登录成功！"
echo ""

# 2. 使用 Python 脚本创建角色
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$SCRIPT_DIR/create_bai_xiaotang.py" "$TOKEN"
