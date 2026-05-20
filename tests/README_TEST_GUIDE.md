# AIFriend 测试系统指南

## 测试分层架构

```
         ╱  E2E (5%)              ╲   全栈端到端
        ╱   Integration (15%)       ╲  真实 PostgreSQL
       ╱    Service/API (30%)         ╲ TestClient + Mock DB
      ╱     Unit (50%)                 ╲ 纯函数
```

| 层级 | 目录 | 标记 | 执行时机 | 运行时 |
|------|------|------|---------|--------|
| 单元测试 | `tests/unit/` | `@pytest.mark.unit` | pre-commit | < 10s |
| 服务/API | `tests/services/` + `tests/routers/` | `@pytest.mark.service` / `api` | pre-push, 部署门禁 | < 60s |
| 集成测试 | `tests/integration/` | `@pytest.mark.integration` | CI 每次 PR | < 120s |
| E2E | `tests/e2e/` | `@pytest.mark.e2e` | 手动, 发布前 | < 300s |

## 快速命令

```bash
# 日常开发 — 快速单元测试 (< 30s)
cd backend && python3 -m pytest ../tests/unit/ -q -m "not slow"

# Push 前 — 服务 + API + 前端
cd backend && python3 -m pytest ../tests/unit/ ../tests/services/ ../tests/routers/ ../tests/contracts/ -q
node tests/frontend_smoke.js
node tests/test_frontend_utils.js

# CI / 部署前 — 全量（排除集成和 E2E）
cd backend && python3 -m pytest ../tests/ --ignore=../tests/integration --ignore=../tests/e2e -q

# 集成测试（需真实 PostgreSQL）
DATABASE_URL=postgresql://... python3 -m pytest ../tests/integration/ -v -m integration

# 并行加速（自行安装 pytest-xdist 后）
cd backend && python3 -m pytest ../tests/ -n auto --dist loadscope -q
```

## 测试数据工厂

所有测试文件可以使用集中式数据工厂替代手写 dict：

```python
from factories import UserFactory, CharacterFactory, MessageFactory, CharacterStateFactory

user = UserFactory.admin()
char = CharacterFactory.intimate(name="露娜")
msgs = MessageFactory.history(turns=3)
state = CharacterStateFactory.at_phase("friend", affection=55)
```

## 命名规范

- 类名: `Test<被测对象>`  — `TestCalculateAffectionChange`
- 方法名: `test_<条件>_<预期行为>` — `test_negative_event_lover_phase_amplifies`
- 参数化: `<描述性名称>` — `"phase=stranger,affection=0,expected=stranger"`

## 覆盖率目标

| 核心模块 | 目标 |
|---------|------|
| `character_affection.py` | 90% |
| `circuit_breaker.py` | 90% |
| `prompt_builder.py` | 85% |
| `schemas.py` | 95% |
| `character_state.py` | 80% |
| `chat_query.py` | 80% |

检查命令: `python3 scripts/check_coverage.py`

## 部署门禁

`deploy.sh` 自动执行以下检查，**失败阻止部署**：

1. Fast unit tests
2. Service + API tests
3. 前端冒烟测试
4. 前端工具函数测试
5. Admin action 完整性检查

## 质量报告

```bash
python3 scripts/test_quality_report.py
```

输出：断言密度、源-测试行数比、低质量命名信号、零覆盖模块清单。
