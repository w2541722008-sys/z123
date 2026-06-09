"""Coverage baseline gate for critical backend modules.

Usage:
    cd backend
    python -m pytest ../tests/unit ../tests/service_flows ../tests/api ../tests/contracts \
        --cov=. --cov-report=json --cov-report=term-missing --cov-fail-under=0
    python ../scripts/check_coverage.py

Refresh the ratchet baseline intentionally after a useful test-suite change:
    python ../scripts/check_coverage.py --update-baseline
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
COVERAGE_JSON = BACKEND_DIR / "coverage.json"
BASELINE_JSON = PROJECT_ROOT / "scripts" / "coverage_baseline.json"

ALLOWED_DROP_PERCENT = 2
DEFAULT_TOTAL_BASELINE = 68.0

CRITICAL_MODULES = {
    "backend/routers/admin/_helpers.py": 70.0,
    "backend/routers/admin/_router.py": 70.0,
    "backend/routers/admin/characters_core.py": 70.0,
    "backend/routers/admin/characters_insights.py": 70.0,
    "backend/routers/admin/characters_memory.py": 70.0,
    "backend/routers/admin/characters_rules_events.py": 70.0,
    "backend/routers/admin/characters_story.py": 70.0,
    "backend/routers/admin/dashboard.py": 70.0,
    "backend/routers/admin/orders.py": 70.0,
    "backend/routers/admin/users.py": 70.0,
    "backend/routers/characters.py": 70.0,
    "backend/services/character_state.py": 70.0,
    "backend/services/chat_stream/_postprocess.py": 70.0,
    "backend/services/email.py": 60.0,
}


def normalize_path(path: str) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            return candidate.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            try:
                return (Path("backend") / candidate.relative_to(BACKEND_DIR)).as_posix()
            except ValueError:
                return candidate.as_posix()

    normalized = candidate.as_posix()
    if normalized.startswith("backend/"):
        return normalized
    if (BACKEND_DIR / normalized).exists():
        return f"backend/{normalized}"
    return normalized


def load_coverage() -> dict[str, Any]:
    if not COVERAGE_JSON.exists():
        print("FAIL: backend/coverage.json not found. Run pytest with --cov-report=json first.")
        sys.exit(1)

    data = json.loads(COVERAGE_JSON.read_text(encoding="utf-8"))
    files = {
        normalize_path(path): file_info
        for path, file_info in data.get("files", {}).items()
    }
    return {
        "totals": data.get("totals", {}),
        "files": files,
    }


def coverage_percent(file_info: dict[str, Any]) -> float:
    summary = file_info.get("summary", {})
    if "percent_covered" in summary:
        return round(float(summary["percent_covered"]), 2)

    covered = float(summary.get("covered_lines", 0))
    statements = float(summary.get("num_statements", 0))
    if statements == 0:
        return 100.0
    return round(covered / statements * 100, 2)


def totals_percent(totals: dict[str, Any]) -> float:
    if "percent_covered" in totals:
        return round(float(totals["percent_covered"]), 2)

    covered = float(totals.get("covered_lines", 0))
    statements = float(totals.get("num_statements", 0))
    if statements == 0:
        return 100.0
    return round(covered / statements * 100, 2)


def load_baseline() -> dict[str, Any]:
    if BASELINE_JSON.exists():
        return json.loads(BASELINE_JSON.read_text(encoding="utf-8"))

    return {
        "allowed_drop_percent": ALLOWED_DROP_PERCENT,
        "total": DEFAULT_TOTAL_BASELINE,
        "modules": CRITICAL_MODULES,
    }


def threshold_for(baseline: float, allowed_drop: float) -> int:
    return max(0, math.floor(baseline - allowed_drop))


def write_baseline(coverage: dict[str, Any]) -> None:
    modules = {}
    files = coverage["files"]
    for module_path in sorted(CRITICAL_MODULES):
        file_info = files.get(module_path)
        if file_info is not None:
            modules[module_path] = coverage_percent(file_info)
        else:
            modules[module_path] = CRITICAL_MODULES[module_path]

    payload = {
        "allowed_drop_percent": ALLOWED_DROP_PERCENT,
        "total": totals_percent(coverage["totals"]),
        "modules": modules,
    }
    BASELINE_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Updated {BASELINE_JSON.relative_to(PROJECT_ROOT)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args(argv)

    coverage = load_coverage()
    if args.update_baseline:
        write_baseline(coverage)
        return 0

    baseline = load_baseline()
    allowed_drop = float(baseline.get("allowed_drop_percent", ALLOWED_DROP_PERCENT))
    module_baselines = baseline.get("modules", CRITICAL_MODULES)
    files = coverage["files"]

    failed = False
    actual_total = totals_percent(coverage["totals"])
    total_baseline = float(baseline.get("total", DEFAULT_TOTAL_BASELINE))
    total_threshold = threshold_for(total_baseline, allowed_drop)

    print("=" * 70)
    print("Coverage Gate")
    print("=" * 70)

    if actual_total >= total_threshold:
        print(f"PASS total: {actual_total:.1f}% >= {total_threshold}% (baseline {total_baseline:.1f}%)")
    else:
        failed = True
        print(f"FAIL total: {actual_total:.1f}% < {total_threshold}% (baseline {total_baseline:.1f}%)")

    print("\nCritical modules")
    print("-" * 70)
    checked = 0
    passed = 0
    for module_path, module_baseline in sorted(module_baselines.items()):
        if module_path not in files:
            failed = True
            print(f"FAIL {module_path}: no coverage data")
            continue

        actual = coverage_percent(files[module_path])
        threshold = threshold_for(float(module_baseline), allowed_drop)
        checked += 1
        if actual >= threshold:
            passed += 1
            print(f"PASS {module_path}: {actual:.1f}% >= {threshold}% (baseline {float(module_baseline):.1f}%)")
        else:
            failed = True
            print(f"FAIL {module_path}: {actual:.1f}% < {threshold}% (baseline {float(module_baseline):.1f}%)")

    print()
    print(f"Result: {passed}/{checked} critical modules passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
