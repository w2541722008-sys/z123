# aifriend 开发规则

最后更新：2026-05-04

---

## 1. 总则

- **稳定优先**：稳定 > 可维护 > 可回退 > 结构优化
- **一次一目标**：一个分支只做一件事
- **先回退点再改**：高风险模块修改前确认已有可回退版本

---

## 2. 数据库操作

### 游标生命周期

`conn.commit()` 会关闭所有游标，`fetchone()` 必须在 `commit()` 之前：

```python
# ✅ 先取值再提交
cur.execute("INSERT INTO ... RETURNING id", (...))
row = cur.fetchone()
conn.commit()

# ❌ commit 后游标已关闭
conn.commit()
row = cur.fetchone()  # InterfaceError
```

### 类型与参数

- **int 列用 `1`/`0`，禁止 `True`/`False`**
- **`%s` 占位符必须与参数元组严格对齐**
- 有 DB DEFAULT 的列（`created_at`、`updated_at`）不在 INSERT 中显式传入

### JSON 列

- 新增结构化数据列必须用 `jsonb`
- `jsonb` 列：psycopg2 自动序列化，直接传/读 dict
- `text` 列（历史遗留）存 JSON：写 `json.dumps()`，读 `json.loads()`

### 连接管理

- 路由层通过 `get_db_dep()` 获取连接，禁止 `with get_db()`
- 连接归还前确保无未提交事务

---

## 3. 分层架构

```
routers → services → repositories → core/constants
```

| 层 | 职责 | 禁止 |
|---|------|------|
| routers | 参数校验、鉴权、调用 service、构造响应 | 包含裸 SQL |
| services | 业务逻辑、跨表操作、缓存 | 导入 routers |
| repositories | 纯 SQL，不含业务逻辑 | — |
| core | 基础设施（auth/config/database/schemas） | 依赖 services（需通信用回调注入） |

---

## 4. 错误处理

- **禁止 `assert` 做运行时校验**，改用 `if + raise HTTPException`
- 用户侧：`HTTPException(4xx)`，`detail` 不暴露内部实现
- 服务端：`logger.exception()` 记录日志，返回 500 不含技术细节

---

## 5. 测试

- `FakeSequenceConn` 模拟 DB，commit 后 fetchone 抛 RuntimeError（模拟 psycopg2）
- 修改路由/服务 SQL 后，必须同步检查对应测试的 FakeQueryResult
- 测试分层：`unit/`、`services/`、`routers/`、`contracts/`、`integration/`（需真实 DB）、`regression/`
- 集成测试标记 `@pytest.mark.integration`，默认不执行
- 覆盖率目标：70%+

---

## 6. Git 与提交

- `main` 只放稳定版本
- 分支：`fix/` `feat/` `refactor/`
- 提交格式：`type(scope): 简明说明`
- 禁止无信息量提交

---

## 7. 高风险模块

以下改动需单独开分支：

- `backend/routers/admin/`、`backend/routers/billing.py`
- `backend/services/chat_stream_service.py`、`backend/services/chat_send.py`
- `backend/core/auth.py`、`backend/core/database.py`
- `backend/repositories/`、`backend/alembic/versions/`

---

## 8. 敏感信息

严禁提交：`.env`、API Key、私钥/证书、用户数据、备份文件。
