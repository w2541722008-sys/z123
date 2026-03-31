# 迁移问题排查清单

## 🔴 关键问题（必须解决）

### 1. 数据库配置问题
**问题描述**：代码已从 SQLite 迁移到 PostgreSQL，但环境变量配置可能缺失。

**检查项**：
- [ ] `.env.production.example` 中已添加 `DATABASE_URL` 配置
- [ ] 生产环境 `.env` 文件中已设置正确的 `DATABASE_URL`
- [ ] DATABASE_URL 格式正确：`postgresql://user:password@host:port/database`
- [ ] 数据库连接池参数已配置（在 `database.py` 中）

**解决方案**：
```bash
# 在生产环境 .env 文件中添加：
DATABASE_URL=postgresql://postgres:your_password@your_supabase_host:5432/postgres
```

### 2. 数据迁移问题
**问题描述**：本地 SQLite 数据需要迁移到 Supabase PostgreSQL。

**检查项**：
- [ ] 已运行 `migrate_to_supabase.py` 脚本迁移数据
- [ ] 已验证所有表和数据都已成功迁移
- [ ] 已检查数据完整性（用户数、角色数、对话数等）

**解决方案**：
```bash
# 运行迁移脚本
cd backend
python migrate_to_supabase.py
```

### 3. SQL 语法兼容性问题
**问题描述**：SQLite 和 PostgreSQL 的 SQL 语法有差异。

**已解决**：
- ✅ 所有 SQL 占位符已从 `?` 改为 `%s`
- ✅ 数据库连接已改为 psycopg2 连接池

**需要注意**：
- PostgreSQL 对大小写敏感（表名、字段名）
- PostgreSQL 的自增主键使用 SERIAL 类型
- PostgreSQL 的布尔类型是 BOOLEAN，不是 INTEGER

## 🟡 重要问题（强烈建议解决）

### 4. 依赖包版本问题
**问题描述**：生产环境可能缺少 PostgreSQL 驱动。

**检查项**：
- [ ] `requirements.txt` 中已包含 `psycopg2-binary>=2.9.0`
- [ ] 生产环境已安装所有依赖包

**解决方案**：
```bash
pip install -r requirements.txt
```

### 5. 连接池配置问题
**问题描述**：PostgreSQL 连接池参数可能需要根据生产环境调整。

**检查项**：
- [ ] 连接池最小连接数（minconn）是否合适
- [ ] 连接池最大连接数（maxconn）是否合适
- [ ] 是否需要配置连接超时时间

**当前配置**（在 `database.py` 中）：
```python
pool = psycopg2.pool.ThreadedConnectionPool(
    minconn=2,
    maxconn=20,
    dsn=DATABASE_URL
)
```

**建议**：
- 小型应用：minconn=2, maxconn=10
- 中型应用：minconn=5, maxconn=20
- 大型应用：minconn=10, maxconn=50

### 6. 环境变量配置问题
**问题描述**：生产环境配置可能不完整。

**检查项**：
- [ ] `ENV=production`
- [ ] `DEBUG=false`
- [ ] `ALLOWED_ORIGINS` 已改为生产域名
- [ ] `AIFRIEND_API_KEY` 已设置
- [ ] `RESEND_API_KEY` 已设置
- [ ] `ADMIN_EMAILS` 已设置

### 7. 文件路径问题
**问题描述**：本地和生产环境的文件路径可能不同。

**检查项**：
- [ ] 头像文件路径（avatars/）
- [ ] 封面文件路径（covers/）
- [ ] 日志文件路径
- [ ] 数据库备份路径

**建议**：使用相对路径或环境变量配置路径。

## 🟢 次要问题（建议检查）

### 8. 性能优化问题
**问题描述**：生产环境可能需要性能优化。

**检查项**：
- [ ] 数据库索引是否已创建
- [ ] SQL 查询是否已优化
- [ ] 是否需要添加缓存（Redis）
- [ ] 是否需要配置 CDN

### 9. 日志和监控问题
**问题描述**：生产环境需要完善的日志和监控。

**检查项**：
- [ ] 日志级别是否合适（生产环境建议 INFO 或 WARNING）
- [ ] 日志文件是否会自动轮转
- [ ] 是否配置了错误监控（如 Sentry）
- [ ] 是否配置了性能监控

### 10. 安全问题
**问题描述**：生产环境需要加强安全性。

**检查项**：
- [ ] 数据库密码是否足够强
- [ ] API Key 是否已妥善保管
- [ ] CORS 配置是否正确
- [ ] 是否启用了 HTTPS
- [ ] 是否配置了防火墙规则

### 11. 备份策略问题
**问题描述**：生产环境需要定期备份。

**检查项**：
- [ ] 是否配置了自动备份
- [ ] 备份频率是否合适
- [ ] 备份文件是否异地存储
- [ ] 是否测试过恢复流程

**参考文档**：`docs/DATABASE_BACKUP_GUIDE.md`

## 📋 迁移步骤建议

### 第一步：准备工作
1. 备份本地 SQLite 数据库
2. 在 Supabase 创建数据库
3. 配置生产环境 `.env` 文件

### 第二步：数据迁移
1. 运行 `migrate_to_supabase.py` 脚本
2. 验证数据完整性
3. 测试数据库连接

### 第三步：代码部署
1. 上传代码到生产服务器
2. 安装依赖包
3. 配置环境变量

### 第四步：测试验证
1. 测试用户注册/登录
2. 测试聊天功能
3. 测试管理后台
4. 测试支付功能

### 第五步：监控和优化
1. 监控数据库性能
2. 监控 API 响应时间
3. 根据需要调整配置

## 🔧 常见问题解决

### 问题 1：连接数据库失败
**错误信息**：`could not connect to server`

**解决方案**：
1. 检查 DATABASE_URL 是否正确
2. 检查网络连接
3. 检查防火墙规则
4. 检查 Supabase 数据库是否正常运行

### 问题 2：SQL 语法错误
**错误信息**：`syntax error at or near "?"`

**解决方案**：
1. 检查是否还有 `?` 占位符未替换为 `%s`
2. 运行以下命令检查：
```bash
grep -r '\?' backend --include="*.py" | grep -v ".venv" | grep -v "regex"
```

### 问题 3：连接池耗尽
**错误信息**：`connection pool exhausted`

**解决方案**：
1. 增加连接池最大连接数（maxconn）
2. 检查是否有连接泄漏（未正确关闭连接）
3. 优化 SQL 查询，减少连接占用时间

### 问题 4：数据迁移不完整
**症状**：部分数据缺失

**解决方案**：
1. 重新运行迁移脚本
2. 检查迁移日志
3. 手动补充缺失数据

## 📚 相关文档

- [部署检查清单](./DEPLOYMENT_CHECKLIST.md)
- [VPS 部署指南](./DEPLOYMENT_GUIDE_VPS.md)
- [数据库备份指南](./DATABASE_BACKUP_GUIDE.md)
- [代码优化检查清单](./CODE_OPTIMIZATION_CHECKLIST.md)
