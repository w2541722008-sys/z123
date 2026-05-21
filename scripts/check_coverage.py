"""分模块覆盖率阈值检查脚本。

用法：
    cd backend && python -m pytest ../tests/ --cov=. --cov-report=json --cov-report=term-missing
    python ../scripts/check_coverage.py

按模块配置的阈值逐一检查覆盖率 JSON 报告，任一模块低于阈值则 exit(1)。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COVERAGE_JSON = PROJECT_ROOT / "backend" / "coverage.json"

THRESHOLDS: dict[str, int] = {
    "backend/services/character_affection.py": 90,
    "backend/services/circuit_breaker.py": 90,
    "backend/services/prompt_builder.py": 85,
    "backend/core/schemas/_base.py": 95,
    "backend/core/schemas/_auth.py": 90,
    "backend/services/character_state.py": 80,
    "backend/services/chat_query.py": 80,
    "backend/services/chat_send.py": 75,
    "backend/services/chat_stream/_sse.py": 70,
    "backend/services/memory_service.py": 75,
    "backend/services/prompt_assembler.py": 70,
    "backend/services/email.py": 60,
    "backend/services/rate_limit.py": 70,
    "backend/services/usage_guard.py": 70,
    "backend/services/cache_service.py": 70,
    "backend/services/plan_service.py": 70,
    "backend/services/health_service.py": 50,
    "backend/core/model_adapter.py": 75,
    "backend/core/auth/_token.py": 70,
    "backend/core/auth/_password.py": 90,
    "backend/utils/json_utils.py": 80,
    "backend/utils/card_text.py": 80,
    "backend/utils/stream_filter.py": 80,
}


def load_coverage_data() -> dict[str, dict]:
    if not COVERAGE_JSON.exists():
        print("❌ 未找到 coverage.json，请先运行 pytest --cov=. --cov-report=json")
        sys.exit(1)

    with open(COVERAGE_JSON) as f:
        data = json.load(f)

    files_data = data.get("files", {})
    result: dict[str, dict] = {}
    for filepath, file_info in files_data.items():
        rel = filepath.replace(str(PROJECT_ROOT) + "/", "")
        result[rel] = file_info
    return result


def compute_line_coverage(file_info: dict) -> float:
    summary = file_info.get("summary", {})
    covered = summary.get("covered_lines", 0)
    total = summary.get("num_statements", 0)
    if total == 0:
        return 100.0
    return round(covered / total * 100, 2)


def main() -> int:
    cov_data = load_coverage_data()

    failed = False
    checked = 0
    passed = 0

    for module_path, threshold in sorted(THRESHOLDS.items()):
        if module_path not in cov_data:
            print(f"⚠️  {module_path}: 无覆盖率数据（可能未被导入/测试）")
            failed = True
            continue

        actual = compute_line_coverage(cov_data[module_path])
        checked += 1
        if actual >= threshold:
            passed += 1
            print(f"✅ {module_path}: {actual:.1f}% (阈值 {threshold}%)")
        else:
            failed = True
            print(f"❌ {module_path}: {actual:.1f}% < {threshold}%（差 {threshold - actual:.1f}%）")

    print()
    print(f"结果: {passed}/{checked} 模块达标")

    if failed:
        print("❌ 覆盖率检查未通过，请补充测试后再提交。")
        return 1
    else:
        print("✅ 所有模块覆盖率达标。")
        return 0


if __name__ == "__main__":
    sys.exit(main())
