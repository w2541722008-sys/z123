# ADR-0003：数据库连接池选型 — ThreadedConnectionPool

**日期**：2025-05-01（推定，基于代码历史）
**状态**：已接受

## 背景

aifriend 使用 FastAPI（异步框架）+ PostgreSQL。需要选择数据库连接管理方案。关键约束：
- FastAPI 的 async 特性与 psycopg2（同步驱动）的协作方式
- 多线程并发场景下的连接复用和安全性
- 与 alembic migration 工具的兼容性

## 决策

使用 **psycopg2 的 ThreadedConnectionPool**（而非 connection pool 其他方案），封装在 `backend/core/database.py` 中。

关键实现细节：
- 连接池在应用启动时创建，全局共享
- 路由层通过 `get_db_dep()` FastAPI 依赖注入获取连接
- 每次请求获取一个连接，请求结束归还池中
- `fetchone()` 必须在 `conn.commit()` 之前调用（游标生命周期约束）

## 备选方案

- **方案 A：asyncpg + async/await** — 原生异步 PostgreSQL 驱动
  - 未选原因：项目初期团队对同步编程更熟悉；psycopg2 生态（alembic、测试工具）更成熟。asyncpg 在复杂事务场景下的错误信息不如 psycopg2 友好

- **方案 B：SQLAlchemy ORM + connection pooling** — 最流行的 Python 数据库方案
  - 未选原因：项目选择了手写 SQL（通过 repository 层），以保持对查询的完全控制。SQLAlchemy ORM 对于手写 SQL 的项目增加了复杂度而非减少

- **方案 C：Pgbouncer 外部连接池** — 独立的连接池中间件
  - 未选原因：增加运维复杂度。ThreadedConnectionPool 对于当前并发量（<1000 QPS）足够

## 后果

### 正面
- psycopg2 生态成熟，与 alembic 完美兼容
- ThreadedConnectionPool 性能对于当前并发量足够
- 手动管理连接生命周期，完全控制事务边界

### 负面
- psycopg2 是同步驱动，在 async 框架中需要使用 `run_in_executor` 或线程池
- 连接池参数（最小/最大连接数）需要根据实际负载调优
- 游标生命周期约束（commit 后游标失效）是常见的坑，已在 CLAUDE.md 中显式文档化

## 相关
- CLAUDE.md "游标生命周期"规则
- `backend/core/database.py`
- `backend/core/auth/_dependencies.py` — get_db_dep 定义
