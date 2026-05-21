"""测试质量报告生成脚本。

分析测试文件的以下指标：
    1. 断言密度（每个测试方法的平均断言数）
    2. 源文件与测试文件行数比
    3. 低质量命名信号（包含 minimal/basic/test1 等）
    4. 零覆盖模块清单
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = PROJECT_ROOT / "tests"
BACKEND_DIR = PROJECT_ROOT / "backend"

# 源模块 -> 对应测试文件映射
SOURCE_TO_TEST_MAP = {
    "services/character_affection.py": "tests/unit/test_character_affection.py",
    "services/circuit_breaker.py": "tests/unit/test_circuit_breaker.py",
    "services/prompt_builder.py": "tests/unit/test_prompt_builder.py",
    "services/chat_query.py": "tests/unit/test_chat_query.py",
    "services/character_state.py": "tests/unit/test_character_state.py",
    "services/chat_send.py": "tests/unit/test_chat_send.py",
    "services/chat_stream/__init__.py": "tests/unit/test_chat_stream_service.py",
    "services/memory_service.py": "tests/services/test_memory_service.py",
    "services/prompt_assembler.py": "tests/unit/test_prompt_assembler.py",
    "services/email.py": "tests/unit/test_email.py",
    "services/rate_limit.py": "tests/unit/test_rate_limit.py",
    "services/usage_guard.py": "tests/unit/test_usage_guard.py",
    "services/cache_service.py": "tests/unit/test_cache_service.py",
    "services/plan_service.py": "tests/services/test_plan_service.py",
    "services/health_service.py": None,
    "services/runtime_bundle.py": "tests/unit/test_runtime_bundle.py",
    "services/token_budget.py": "tests/unit/test_token_budget.py",
    "services/story_event_service.py": "tests/unit/test_story_event_service.py",
    "core/model_adapter.py": "tests/unit/test_model_adapter.py",
    "core/auth/__init__.py": "tests/unit/test_auth.py",
    "core/schemas/__init__.py": "tests/contracts/test_schemas.py",
    "utils/json_utils.py": "tests/unit/test_json_utils.py",
    "utils/card_text.py": "tests/unit/test_card_text_utils.py",
    "utils/stream_filter.py": "tests/unit/test_stream_filter.py",
}

LOW_QUALITY_SIGNALS = ["test_minimal", "test_basic", "test_simple", "test1", "test2", "test_default"]


class TestFileAnalyzer(ast.NodeVisitor):
    def __init__(self):
        self.test_methods: list[str] = []
        self.assertions_per_method: dict[str, int] = {}
        self.current_method: str | None = None
        self.low_quality: list[str] = []

    def visit_FunctionDef(self, node):
        if node.name.startswith("test_"):
            self.test_methods.append(node.name)
            self.assertions_per_method[node.name] = 0
            self.current_method = node.name

            if any(signal in node.name for signal in LOW_QUALITY_SIGNALS):
                self.low_quality.append(node.name)

            self.generic_visit(node)
            self.current_method = None
        else:
            self.generic_visit(node)

    def visit_Assert(self, node):
        if self.current_method:
            self.assertions_per_method[self.current_method] += 1
        self.generic_visit(node)

    def visit_Call(self, node):
        name = getattr(getattr(node.func, "attr", None), "value", None)
        if name in ("assert_called_once_with", "assert_called_with", "assert_called_once",
                     "assert_not_called", "assert_any_call", "assertRaises",
                     "assertTrue", "assertFalse", "assertEqual", "assertIn",
                     "assertNotIn", "assertIsNone", "assertIsNotNone",
                     "assertIsInstance", "assertRaisesRegex"):
            if self.current_method:
                self.assertions_per_method[self.current_method] += 1
        self.generic_visit(node)


def analyze_test_file(filepath: Path) -> TestFileAnalyzer | None:
    if not filepath.exists():
        return None
    try:
        tree = ast.parse(filepath.read_text())
        analyzer = TestFileAnalyzer()
        analyzer.visit(tree)
        return analyzer
    except SyntaxError as e:
        print(f"  ⚠️ 语法错误: {filepath} - {e}")
        return None


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return len([l for l in path.read_text().splitlines() if l.strip()])


def main() -> int:
    issues = 0

    print("=" * 70)
    print("测试质量报告")
    print("=" * 70)

    # 1. 断言密度分析
    print("\n📊 断言密度（目标: >= 3 断言/测试方法）")
    print("-" * 50)

    total_methods = 0
    total_assertions = 0

    for py_file in sorted(TESTS_DIR.rglob("test_*.py")):
        if "__pycache__" in str(py_file) or "e2e" in str(py_file):
            continue

        analyzer = analyze_test_file(py_file)
        if analyzer is None:
            continue

        if not analyzer.test_methods:
            continue

        methods = len(analyzer.test_methods)
        assertions = sum(analyzer.assertions_per_method.values())
        avg = assertions / methods if methods > 0 else 0
        total_methods += methods
        total_assertions += assertions

        relative = str(py_file.relative_to(PROJECT_ROOT))
        flag = ""
        if avg < 3:
            flag = " ⚠️"
            issues += 1
        elif avg < 1:
            flag = " ❌"

        if analyzer.low_quality:
            flag += f" 低质量命名: {', '.join(analyzer.low_quality[:3])}"
            issues += 1

        print(f"  {relative}: {avg:.1f} 断言/方法 ({assertions}/{methods}){flag}")

    overall_avg = total_assertions / total_methods if total_methods > 0 else 0
    print(f"\n  总计: {overall_avg:.1f} 断言/方法 ({total_assertions}/{total_methods})")

    # 2. 源-测试行数比
    print("\n📏 源文件 vs 测试文件行数比")
    print("-" * 50)

    for source_rel, test_rel in sorted(SOURCE_TO_TEST_MAP.items()):
        source_path = BACKEND_DIR / source_rel
        if not source_path.exists():
            continue

        source_lines = count_lines(source_path)
        test_path = PROJECT_ROOT / test_rel if test_rel else None
        test_lines = count_lines(test_path) if test_path else 0

        ratio = test_lines / source_lines if source_lines > 0 else 0
        flag = ""
        if test_lines == 0:
            flag = " ❌ 无测试!"
            issues += 1
        elif ratio < 0.5:
            flag = " ⚠️ 测试偏少"
            issues += 1

        test_display = test_rel if test_rel else "无"
        print(f"  {source_rel}: {source_lines}行源 → {test_lines}行测试 ({ratio:.1%}){flag}")

    # 3. 总结
    print(f"\n{'=' * 70}")
    if issues > 0:
        print(f"⚠️ 发现 {issues} 个质量问题，建议处理后再提交。")
    else:
        print("✅ 测试质量良好。")
    print(f"{'=' * 70}")

    return 0 if issues == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
