# 快速部署指南

## 方法一：使用部署脚本（推荐）

### 1. 打包项目
```bash
./deploy.sh
```

这会创建一个 `aifriend_deploy_YYYYMMDD_HHMMSS.tar.gz` 文件，只包含必要的文件，不包含：
- `.env` 环境变量文件
- `backend/data/` 数据库文件
- `__pycache__` 和 `.pyc` 缓存文件
- `.DS_Store` 系统文件

### 2. 上传到服务器
```bash
scp aifriend_deploy_*.tar.gz user@your-server:/path/to/deploy/
```

### 3. 在服务器上部署
```bash
# 解压
tar -xzf aifriend_deploy_*.tar.gz
cd aifriend_deploy_*

# 配置环境变量
cp backend/.env.example backend/.env
nano backend/.env  # 编辑配置

# 安装依赖
cd backend
pip install -r requirements.txt

# 启动应用
uvicorn main:app --host 0.0.0.0 --port 8000
```

## 方法二：使用 Git（更推荐）

### 1. 提交代码到 Git 仓库
```bash
git add .
git commit -m "准备部署到生产环境"
git push origin main
```

### 2. 在服务器上克隆
```bash
git clone https://github.com/your-username/aifriend.git
cd aifriend
```

### 3. 配置和启动
```bash
# 配置环境变量
cp backend/.env.example backend/.env
nano backend/.env

# 安装依赖
cd backend
pip install -r requirements.txt

# 启动应用
uvicorn main:app --host 0.0.0.0 --port 8000
```

## 重要提醒

1. **环境变量**: 务必在服务器上创建 `backend/.env` 并填入正确的配置（参考 `backend/.env.example`）
2. **数据库**: 确保 `DATABASE_URL` 指向正确的 Supabase PostgreSQL 数据库
3. **建表**: 首次部署需要在 Supabase SQL Editor 中执行 `docs/supabase_schema.sql`
4. **备份**: 部署前先备份本地数据（使用 `bash backend/backup_supabase.sh`）
5. **测试**: 部署后测试所有功能是否正常

## 相关文档

- [完整部署指南](./DEPLOYMENT_GUIDE_VPS.md)
- [部署检查清单](./DEPLOYMENT_CHECKLIST.md)
- [数据库备份指南](./DATABASE_BACKUP_GUIDE.md)
- [Supabase 建表 SQL](./supabase_schema.sql)
