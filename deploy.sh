#!/bin/bash

# AIFriend 项目部署打包脚本
# 只打包必要的文件，排除开发环境和敏感信息

set -e

echo "开始打包部署文件..."

# 创建临时目录
DEPLOY_DIR="aifriend_deploy_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$DEPLOY_DIR"

echo "复制必要文件到 $DEPLOY_DIR ..."

# 复制后端文件
mkdir -p "$DEPLOY_DIR/backend"
cp -r backend/*.py "$DEPLOY_DIR/backend/" 2>/dev/null || true
cp backend/requirements.txt "$DEPLOY_DIR/backend/"
cp backend/.env.example "$DEPLOY_DIR/backend/"

# 复制后端子目录
cp -r backend/routers "$DEPLOY_DIR/backend/"
cp -r backend/services "$DEPLOY_DIR/backend/"
cp -r backend/models "$DEPLOY_DIR/backend/"
cp -r backend/utils "$DEPLOY_DIR/backend/"
cp -r backend/cli "$DEPLOY_DIR/backend/"
cp backend/backup_supabase.sh "$DEPLOY_DIR/backend/" 2>/dev/null || true

# 复制前端文件（包括管理后台）
mkdir -p "$DEPLOY_DIR/frontend"
mkdir -p "$DEPLOY_DIR/frontend/admin/js"
cp frontend/*.html "$DEPLOY_DIR/frontend/" 2>/dev/null || true
cp frontend/*.js "$DEPLOY_DIR/frontend/"
cp frontend/*.css "$DEPLOY_DIR/frontend/"
cp -r frontend/admin/*.html "$DEPLOY_DIR/frontend/admin/" 2>/dev/null || true
cp -r frontend/admin/*.css "$DEPLOY_DIR/frontend/admin/" 2>/dev/null || true
cp -r frontend/admin/js/*.js "$DEPLOY_DIR/frontend/admin/js/" 2>/dev/null || true

# 复制根目录的 HTML 文件
cp *.html "$DEPLOY_DIR/" 2>/dev/null || true

# 复制静态资源
cp -r assets "$DEPLOY_DIR/" 2>/dev/null || true
cp -r avatars "$DEPLOY_DIR/" 2>/dev/null || true
cp -r covers "$DEPLOY_DIR/" 2>/dev/null || true

# 复制文档
mkdir -p "$DEPLOY_DIR/docs"
cp docs/*.md "$DEPLOY_DIR/docs/" 2>/dev/null || true
cp docs/*.sql "$DEPLOY_DIR/docs/" 2>/dev/null || true

# 复制工具脚本
cp -r scripts "$DEPLOY_DIR/" 2>/dev/null || true

# 复制配置文件
cp README.md "$DEPLOY_DIR/" 2>/dev/null || true
cp .gitignore "$DEPLOY_DIR/" 2>/dev/null || true

echo "清理不需要的文件..."

# 删除 Python 缓存
find "$DEPLOY_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$DEPLOY_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true

# 删除系统文件
find "$DEPLOY_DIR" -name ".DS_Store" -delete 2>/dev/null || true

# 删除开发环境文件（如果误复制）
rm -f "$DEPLOY_DIR/backend/.env" 2>/dev/null || true
rm -rf "$DEPLOY_DIR/backend/data" 2>/dev/null || true

echo "打包文件..."
tar -czf "${DEPLOY_DIR}.tar.gz" "$DEPLOY_DIR"

echo "清理临时目录..."
rm -rf "$DEPLOY_DIR"

echo ""
echo "✅ 部署包已创建: ${DEPLOY_DIR}.tar.gz"
echo ""
echo "📦 部署步骤："
echo "1. 上传到服务器: scp ${DEPLOY_DIR}.tar.gz user@server:/path/to/deploy/"
echo "2. 在服务器上解压: tar -xzf ${DEPLOY_DIR}.tar.gz"
echo "3. 进入目录: cd ${DEPLOY_DIR}"
echo "4. 配置环境变量: cp backend/.env.example backend/.env"
echo "5. 编辑 backend/.env 填入实际配置"
echo "6. 安装依赖: cd backend && pip install -r requirements.txt"
echo "7. 启动应用: uvicorn main:app --host 0.0.0.0 --port 8000"
echo ""
