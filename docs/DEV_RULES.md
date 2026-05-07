# 开发规范

## 架构分层

```
routers/ → services/ → repositories/ → core/ + constants/
```

| 层 | 职责 | 禁止 |
|---|------|------|
| routers | 参数校验、鉴权、调用 service | 包含裸 SQL |
| services | 业务逻辑、跨表操作、缓存 | 导入 routers |
| repositories | 纯 SQL，不含业务逻辑 | — |
| core | 基础设施（auth/config/database/schemas） | 依赖 services（需通信用回调注入） |

---

## 数据库规则

### 游标生命周期

**`conn.commit()` 会关闭所有游标，`fetchone()` 必须在 `commit()` 之前**

```python
# ✅ 正确
cur.execute("INSERT INTO ... RETURNING id", (...))
row = cur.fetchone()
conn.commit()

# ❌ 错误
conn.commit()
row = cur.fetchone()  # InterfaceError: cursor already closed
```

### 类型规则

- **int 列用 `1`/`0`，禁止 `True`/`False`**
- **`jsonb` 列直接传 dict**（psycopg2 自动序列化）
- **`text` 列存 JSON**（历史遗留）：写 `json.dumps()`，读 `json.loads()`

### 连接管理

- 路由层通过 `get_db_dep()` 获取连接
- **禁止在路由层使用 `with get_db()`**

---

## 错误处理

- **禁止 `assert` 做运行时校验**，改用 `if + raise HTTPException`
- 用户侧错误：`HTTPException(4xx)`，`detail` 不暴露内部实现
- 服务端错误：`logger.exception()` + 返回 500

---

## 测试规则

- 修改 SQL 后，必须同步更新测试的 `FakeQueryResult`
- `FakeSequenceConn` 模拟 commit 后游标关闭（抛 RuntimeError）
- 集成测试标记 `@pytest.mark.integration`，默认跳过
- 运行测试：`pytest tests/unit/ -q`

---

## Git 规范

- `main` 只放稳定版本
- 分支命名：`fix/` `feat/` `refactor/`
- 提交格式：`type(scope): 简明说明`

---

## 高风险模块

以下改动需单独开分支：

- `routers/admin/`、`routers/billing.py`
- `services/chat_stream_service.py`、`services/chat_send.py`
- `core/auth.py`、`core/database.py`
- `repositories/`、`alembic/versions/`

---

## 安全规则

- 严禁提交：`.env`、API Key、私钥、用户数据
- Admin 端点必须使用 `get_admin_user` 鉴权
- Cookie 生产环境：`HttpOnly + SameSite=Strict + Secure`
