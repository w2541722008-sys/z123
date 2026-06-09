"""Report maintainability risks in the test suite.

The gate is intentionally narrow: syntax errors and direct imports from
``conftest`` fail the command. Other findings are risk signals that help keep
tests useful, clear, and resilient without turning assertion counts into a
vanity metric.
"""

from __future__ import annotations

import ast
import hashlib
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = PROJECT_ROOT / "tests"
BACKEND_DIR = PROJECT_ROOT / "backend"

LOW_SEMANTIC_NAMES = {
    "test_basic",
    "test_default",
    "test_failure",
    "test_found",
    "test_minimal",
    "test_not_found",
    "test_simple",
    "test_success",
    "test1",
    "test2",
}

MOCK_NAMES = {
    "AsyncMock",
    "MagicMock",
    "Mock",
    "PropertyMock",
    "call",
    "mock_open",
    "monkeypatch",
    "patch",
}

ASSERTION_CALLS = {
    "assert_any_call",
    "assert_called",
    "assert_called_once",
    "assert_called_once_with",
    "assert_called_with",
    "assert_equal",
    "assert_not_called",
    "assert_raises",
    "fail",
    "pytest.raises",
    "raises",
}

SOURCE_TO_TEST_MAP = {
    "core/auth/_dependencies.py": "tests/unit/core/auth/test_auth_dependencies.py",
    "core/auth/_password.py": "tests/unit/core/auth/test_auth_password.py",
    "core/auth/_token.py": "tests/unit/core/auth/test_auth_token.py",
    "core/auth/__init__.py": "tests/unit/core/auth/test_current_user_cache.py",
    "core/model_adapter.py": "tests/unit/core/test_model_adapter.py",
    "core/schemas/__init__.py": "tests/contracts/test_schemas.py",
    "services/cache_service.py": "tests/unit/services/test_cache_service.py",
    "services/character_affection.py": "tests/unit/services/test_character_affection.py",
    "services/character_state.py": "tests/unit/services/test_character_state.py",
    "services/chat_query.py": "tests/unit/services/test_chat_query.py",
    "services/chat_send.py": "tests/service_flows/test_chat_send.py",
    "services/chat_stream/__init__.py": "tests/unit/services/test_chat_stream_service.py",
    "services/circuit_breaker.py": "tests/unit/services/test_circuit_breaker.py",
    "services/email.py": "tests/unit/services/test_email.py",
    "services/memory_service.py": "tests/service_flows/test_memory_service.py",
    "services/plan_service.py": "tests/service_flows/test_plan_service.py",
    "services/prompt_assembler.py": "tests/unit/services/test_prompt_assembler.py",
    "services/prompt_builder.py": "tests/unit/services/test_prompt_builder.py",
    "services/rate_limit.py": "tests/unit/services/test_rate_limit.py",
    "services/runtime_bundle.py": "tests/unit/services/test_runtime_bundle.py",
    "services/story_event_service.py": "tests/unit/services/test_story_event_service.py",
    "services/token_budget.py": "tests/unit/services/test_token_budget.py",
    "services/usage_guard.py": "tests/unit/services/test_usage_guard.py",
    "utils/card_text.py": "tests/unit/utils/test_card_text_utils.py",
    "utils/json_utils.py": "tests/unit/utils/test_json_utils.py",
    "utils/stream_filter.py": "tests/unit/utils/test_stream_filter.py",
}


@dataclass
class TestFinding:
    path: Path
    line: int
    message: str

    def display(self) -> str:
        rel = self.path.relative_to(PROJECT_ROOT)
        return f"{rel}:{self.line} - {self.message}"


@dataclass
class FileReport:
    path: Path
    tests: int = 0
    assertions: int = 0
    mock_signals: int = 0
    low_names: list[TestFinding] = field(default_factory=list)
    no_assertions: list[TestFinding] = field(default_factory=list)
    private_imports: list[TestFinding] = field(default_factory=list)
    conftest_imports: list[TestFinding] = field(default_factory=list)
    duplicate_fingerprints: dict[str, list[str]] = field(default_factory=dict)


class TestAnalyzer(ast.NodeVisitor):
    def __init__(self, path: Path):
        self.path = path
        self.report = FileReport(path=path)
        self.current_test: str | None = None
        self.current_assertions = 0
        self.current_mock_signals = 0
        self.test_fingerprints: dict[str, list[str]] = defaultdict(list)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if module in {"conftest", "tests.conftest"}:
            self.report.conftest_imports.append(
                TestFinding(self.path, node.lineno, "direct conftest import is forbidden; use tests.support")
            )

        if module != "__future__" and module and any(part.startswith("_") for part in module.split(".")):
            self.report.private_imports.append(
                TestFinding(self.path, node.lineno, f"imports private module {module}")
            )

        for alias in node.names:
            if module == "__future__":
                continue
            if alias.name.startswith("_") and alias.name != "__all__":
                self.report.private_imports.append(
                    TestFinding(self.path, node.lineno, f"imports private symbol {alias.name}")
                )
            if alias.name in MOCK_NAMES:
                self.report.mock_signals += 1

        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name != "__future__" and any(part.startswith("_") for part in alias.name.split(".")):
                self.report.private_imports.append(
                    TestFinding(self.path, node.lineno, f"imports private module {alias.name}")
                )
            if alias.name.rsplit(".", 1)[-1] in MOCK_NAMES:
                self.report.mock_signals += 1
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        if self.current_test:
            self.current_assertions += 1
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        call_name = self._call_name(node.func)
        if self.current_test and call_name in ASSERTION_CALLS:
            self.current_assertions += 1
        if call_name in MOCK_NAMES or call_name.endswith(".patch"):
            self.current_mock_signals += 1
            self.report.mock_signals += 1
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in MOCK_NAMES:
            self.current_mock_signals += 1
        self.generic_visit(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if not node.name.startswith("test_"):
            self.generic_visit(node)
            return

        self.report.tests += 1
        previous_test = self.current_test
        previous_assertions = self.current_assertions
        previous_mock_signals = self.current_mock_signals
        self.current_test = node.name
        self.current_assertions = 0
        self.current_mock_signals = 0

        if self._is_low_semantic_name(node.name):
            self.report.low_names.append(
                TestFinding(self.path, node.lineno, f"low-semantic test name {node.name}")
            )

        self.generic_visit(node)

        self.report.assertions += self.current_assertions
        if self.current_assertions == 0:
            self.report.no_assertions.append(
                TestFinding(self.path, node.lineno, f"{node.name} has no explicit assertion")
            )
        if self.current_mock_signals >= 8:
            self.report.private_imports.append(
                TestFinding(self.path, node.lineno, f"{node.name} has high mock density ({self.current_mock_signals})")
            )

        fingerprint = self._fingerprint(node)
        self.test_fingerprints[fingerprint].append(node.name)

        self.current_test = previous_test
        self.current_assertions = previous_assertions
        self.current_mock_signals = previous_mock_signals

    @staticmethod
    def _call_name(func: ast.expr) -> str:
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            owner = TestAnalyzer._call_name(func.value)
            return f"{owner}.{func.attr}" if owner else func.attr
        return ""

    @staticmethod
    def _is_low_semantic_name(name: str) -> bool:
        return name in LOW_SEMANTIC_NAMES or any(
            name.endswith(f"_{signal.removeprefix('test_')}") for signal in LOW_SEMANTIC_NAMES
        )

    @staticmethod
    def _fingerprint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        copied = ast.FunctionDef(
            name="test_x",
            args=node.args,
            body=node.body,
            decorator_list=[],
            returns=None,
            type_comment=None,
        )
        normalized = ast.dump(copied, annotate_fields=False, include_attributes=False)
        return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def parse_test_file(path: Path) -> tuple[FileReport | None, SyntaxError | None]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return None, exc

    analyzer = TestAnalyzer(path)
    analyzer.visit(tree)
    analyzer.report.duplicate_fingerprints = {
        fingerprint: names
        for fingerprint, names in analyzer.test_fingerprints.items()
        if len(names) > 1
    }
    return analyzer.report, None


def iter_test_files() -> list[Path]:
    return sorted(
        path
        for path in TESTS_DIR.rglob("test_*.py")
        if "__pycache__" not in path.parts and "e2e" not in path.parts
    )


def count_nonblank_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def print_findings(title: str, findings: list[TestFinding], *, limit: int = 25) -> None:
    print(f"\n{title} ({len(findings)})")
    print("-" * 70)
    if not findings:
        print("  none")
        return
    for finding in findings[:limit]:
        print(f"  {finding.display()}")
    if len(findings) > limit:
        print(f"  ... {len(findings) - limit} more")


def main() -> int:
    hard_failures: list[TestFinding] = []
    syntax_errors: list[TestFinding] = []
    low_names: list[TestFinding] = []
    no_assertions: list[TestFinding] = []
    private_imports: list[TestFinding] = []
    high_mock_files: list[str] = []
    duplicate_clusters: list[str] = []
    large_files: list[str] = []

    reports: list[FileReport] = []

    for path in iter_test_files():
        report, syntax_error = parse_test_file(path)
        if syntax_error:
            syntax_errors.append(
                TestFinding(path, syntax_error.lineno or 1, f"syntax error: {syntax_error.msg}")
            )
            continue
        if report is None:
            continue

        reports.append(report)
        hard_failures.extend(report.conftest_imports)
        low_names.extend(report.low_names)
        no_assertions.extend(report.no_assertions)
        private_imports.extend(report.private_imports)

        if report.mock_signals >= 20:
            high_mock_files.append(
                f"{report.path.relative_to(PROJECT_ROOT)} - {report.mock_signals} mock signals"
            )

        for names in report.duplicate_fingerprints.values():
            duplicate_clusters.append(
                f"{report.path.relative_to(PROJECT_ROOT)} - duplicate bodies: {', '.join(names[:4])}"
            )

        line_count = count_nonblank_lines(report.path)
        if line_count > 650 or report.tests > 55:
            large_files.append(
                f"{report.path.relative_to(PROJECT_ROOT)} - {line_count} lines, {report.tests} tests"
            )

    hard_failures.extend(syntax_errors)

    total_tests = sum(report.tests for report in reports)
    total_assertions = sum(report.assertions for report in reports)

    print("=" * 70)
    print("Test Quality Report")
    print("=" * 70)
    print(f"Files analyzed: {len(reports)}")
    print(f"Tests analyzed: {total_tests}")
    print(f"Explicit assertion signals: {total_assertions}")

    print_findings("Hard failures", hard_failures)
    print_findings("Low-semantic test names", low_names)
    print_findings("Tests with no explicit assertion", no_assertions)
    print_findings("Private imports / high per-test mock density", private_imports)

    print("\nHigh mock files")
    print("-" * 70)
    if high_mock_files:
        for item in high_mock_files[:25]:
            print(f"  {item}")
    else:
        print("  none")

    print("\nDuplicate test body signals")
    print("-" * 70)
    if duplicate_clusters:
        for item in duplicate_clusters[:25]:
            print(f"  {item}")
    else:
        print("  none")

    print("\nLarge test files")
    print("-" * 70)
    if large_files:
        for item in large_files:
            print(f"  {item}")
    else:
        print("  none")

    print("\nCritical source-test map")
    print("-" * 70)
    for source_rel, test_rel in sorted(SOURCE_TO_TEST_MAP.items()):
        source_path = BACKEND_DIR / source_rel
        test_path = PROJECT_ROOT / test_rel
        if not source_path.exists():
            continue
        status = "ok" if test_path.exists() else "missing"
        print(f"  {source_rel} -> {test_rel} [{status}]")

    print("\n" + "=" * 70)
    if hard_failures:
        print(f"FAIL: {len(hard_failures)} hard test-quality violation(s).")
        return 1
    print("PASS: no hard test-quality violations. Review warnings during refactors.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
