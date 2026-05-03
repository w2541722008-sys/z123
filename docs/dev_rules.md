# aifriend 开发规则

最后更新：2026-05-03

---

## 1. 总则

- **稳定优先**：稳定 > 可维护 > 可回退 > 结构优化，未经确认不做大重构
- **一次一目标**：一个分支只做一件事，一次提交只解决一个问题
- **先回退点再改**：高风险模块修改前必须确认已有可回退版本点

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

- **int 列用 `1`/`0`，禁止 `True`/`False`**：PostgreSQL integer 列不接受 Python 布尔值（如 `is_visible`、`is_active`）
- **`%s` 占位符必须与参数元组严格对齐**：修改 SQL 后逐一核对
- **有 DB DEFAULT 的列**（`created_at`、`updated_at`）不在 INSERT 中显式传入

### JSON 列

- 新增结构化数据列必须用 `jsonb`，禁止 `text` 存储 JSON
- `jsonb` 列：psycopg2 自动序列化，直接传/读 dict
- `text` 列（历史遗留）存 JSON：写 `json.dumps()`，读 `json.loads()` + 异常处理

### 连接管理

- 路由层通过 `get_db_dep()` 获取连接，禁止 `with get_db()` 手动管理
- 服务层事务控制使用 `ConnWrapper` 或 `_transaction()`
- 连接归还前确保无未提交事务，不依赖 finally rollback 兜底

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
| constants | 枚举常量，单一来源 | — |

---

## 4. 错误处理

- **禁止 `assert` 做运行时校验**（`-O` 模式下会移除），改用 `if + raise HTTPException`
- 用户侧：`HTTPException(4xx)`，`detail` 简明，不暴露内部实现/堆栈/SQL
- 服务端：`logger.exception()` 记录日志，不用 f-string；返回 `500` 不含技术细节
- 数据库异常：先 rollback 再返回错误

---

## 5. 测试

- 当前使用 `FakeSequenceConn` 模拟，**不执行真实 SQL**，`FakeQueryResult` 数量必须与实际 SQL 序列一致
- **commit 后游标失效**：`FakeSequenceConn.commit()` 后，上次 execute 返回的 `FakeQueryResult.fetchone()` 将抛出 `RuntimeError`，模拟 psycopg2 真实行为；但可以执行新的 `execute()` 创建新游标
- 修改路由/服务 SQL 后，必须同步检查对应测试的 FakeQueryResult
- 必须覆盖：admin 鉴权守卫、RETURNING id 的 fetchone 顺序、int 列类型校验
- 命名：文件 `test_{模块}_{场景}.py`，函数 `test_{功能}_{条件}_{预期}`
- 测试分层：`unit/`（纯函数零 mock）、`services/`（轻 mock）、`routers/`（TestClient + mock DB）、`contracts/`（API 契约）、`integration/`（真实 DB，需 `-m integration`）、`regression/`（Bug 回归）
- 集成测试标记 `@pytest.mark.integration`，默认不执行；运行：`pytest -m integration`
- 覆盖率阈值：51%，目标 80%

---

## 6. Git 与提交

- `main` 只放稳定版本，禁止长期直接开发
- 分支：`fix/` `feat/` `refactor/` `audit/` `release/`
- 提交格式：`type(scope): 简明说明`（如 `fix(admin): 补充鉴权`）
- 禁止无信息量提交（`update` / `fix bug` / `change`）
- 回退：优先最小范围，上线故障优先回退到最近稳定标签

---

## 7. 高风险模块

以下改动默认需单独开分支、写清原因和影响范围：

- `backend/routers/admin/`、`backend/routers/billing.py`
- `backend/services/chat_stream_service.py`、`backend/services/chat_send.py`
- `backend/core/auth.py`、`backend/core/database.py`
- `backend/repositories/`（SQL 集中管理）
- `backend/alembic/versions/`（数据库迁移）
- 鉴权/支付/部署配置/线上用户数据相关逻辑

未经确认禁止：大规模重构、改数据库结构、改鉴权/支付逻辑、批量删代码、替换核心依赖。

---

## 8. 敏感信息

严禁提交：`.env`、API Key、Cookie、支付密钥、私钥/证书、真实数据库、用户导出数据、备份文件。已被 Git 跟踪的敏感文件必须单独处理。
