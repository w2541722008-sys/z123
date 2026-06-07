# AIFriend 测试系统指南

## 测试分层

```
         ╱  Integration (15%)    ╲  真实 PostgreSQL
        ╱   Service/API (35%)     ╲ TestClient + FakeSequenceConn
       ╱    Unit (50%)             ╲ 纯函数 + FakeSequenceConn
```

| 层级 | 目录 | 执行时机 | 运行时 |
|------|------|---------|--------|
| 单元测试 | `tests/unit/` | pre-commit | < 10s |
| 服务测试 | `tests/services/` | pre-push, 部署门禁 | < 30s |
| 路由测试 | `tests/routers/` | pre-push, 部署门禁 | < 30s |
| 契约测试 | `tests/contracts/` | pre-push, 部署门禁 | < 30s |
| 回归测试 | `tests/regression/` | 发布前 | < 60s |
| 集成测试 | `tests/integration/` | CI 每次 PR | < 120s |
| 负载测试 | `tests/load/` | 手动, 发布前 | 按需 |

## 快速命令

```bash
# 日常开发 — 快速单元测试
cd backend && python3 -m pytest ../tests/unit/ -q

# Push 前 — 服务 + API + 契约
cd backend && python3 -m pytest ../tests/unit/ ../tests/services/ ../tests/routers/ ../tests/contracts/ -q
node tests/frontend_smoke.js

# CI / 部署前 — 全量（排除集成）
cd backend && python3 -m pytest ../tests/ --ignore=../tests/integration -q

# 集成测试（需真实 PostgreSQL）
DATABASE_URL=postgresql://... python3 -m pytest ../tests/integration/ -v

# 并行加速（需先 pip install pytest-xdist，见 requirements-dev.txt）
cd backend && python3 -m pytest ../tests/ -n auto --dist loadscope -q
```

## 测试数据工厂

所有测试文件可以使用集中式数据工厂替代手写 dict（位于 `tests/factories.py`）：

```python
from factories import UserFactory, CharacterFactory, MessageFactory

user = UserFactory.admin()
char = CharacterFactory.intimate(name="露娜")
msgs = MessageFactory.history(turns=3)
```

## 命名规范

- 类名: `Test<被测对象>` — `TestCalculateAffectionChange`
- 方法名: `test_<条件>_<预期行为>` — `test_negative_event_lover_phase_amplifies`

## 部署门禁

`deploy.sh` 自动执行以下检查，**失败阻止部署**：

1. Fast unit tests (838 个)
2. Service + API + Contract tests (386 个)
3. 前端冒烟测试
4. Admin action 完整性检查

## 开发依赖

```bash
pip install -r requirements-dev.txt   # pytest, ruff, black, mypy, pre-commit 等
```
