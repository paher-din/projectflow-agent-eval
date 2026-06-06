# ProjectFlow AgentEval CLI + Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a stable `pfae` CLI and `projectflow-agent-eval` skill so agents can run, inspect, compare, and diagnose ProjectFlow AgentEval without memorizing runner internals.

**Architecture:** Keep `app.agent_eval.runner` as the benchmark execution core. Add a thin `app.agent_eval.cli` parser and focused command modules that delegate to existing runner/report functions or read existing artifacts. Add skill documentation under `skills/projectflow-agent-eval` to teach agents when and how to use the CLI.

**Tech Stack:** Python 3.11+, `argparse`, existing Pydantic schemas, `pytest`, Markdown skill files.

---

## File Structure

- Create `app/agent_eval/cli.py`: top-level `pfae` command parser and dispatch.
- Create `app/agent_eval/commands/__init__.py`: command package marker.
- Create `app/agent_eval/commands/common.py`: shared path resolution, latest-run lookup, JSON loading, and error helpers.
- Create `app/agent_eval/commands/cases.py`: `pfae case list` and `pfae case show`.
- Create `app/agent_eval/commands/runs.py`: `pfae run mock|real|resume|retry-failed|retry-errors`.
- Create `app/agent_eval/commands/reports.py`: `pfae report latest` and `pfae report show`.
- Create `app/agent_eval/commands/compare.py`: `pfae compare <baseline> <candidate>`.
- Create `app/agent_eval/commands/diagnose.py`: `pfae diagnose latest|<run_dir>`.
- Modify `pyproject.toml`: route both `pfae` and `projectflow-agent-eval` to `app.agent_eval.cli:main`.
- Create `tests/test_agent_eval_cli.py`: parser and command-level coverage using temporary fixtures/artifacts where possible.
- Create `skills/projectflow-agent-eval/SKILL.md`: agent-facing trigger and workflow instructions.
- Create `skills/projectflow-agent-eval/references/command-guide.md`: concise CLI command guide.
- Create `skills/projectflow-agent-eval/references/report-interpretation.md`: report and failure interpretation guide.
- Modify `README.md`: add the new short CLI surface while keeping existing runner command compatibility.

## Task 1: CLI Shared Helpers

**Files:**
- Create: `app/agent_eval/commands/__init__.py`
- Create: `app/agent_eval/commands/common.py`
- Test: `tests/test_agent_eval_cli.py`

- [ ] **Step 1: Write failing tests for latest-run and JSON helpers**

Add this to `tests/test_agent_eval_cli.py`:

```python
import json
from pathlib import Path

import pytest

from app.agent_eval.commands.common import CommandError, load_json_file, resolve_run_dir


def test_resolve_run_dir_latest_uses_most_recent_directory(tmp_path: Path) -> None:
    output_base = tmp_path / "output" / "agent-eval"
    older = output_base / "20260101T000000-stub-aaaaaa"
    newer = output_base / "20260102T000000-stub-bbbbbb"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    (older / "suite_summary.json").write_text("{}", encoding="utf-8")
    (newer / "suite_summary.json").write_text("{}", encoding="utf-8")

    assert resolve_run_dir("latest", output_base=output_base) == newer


def test_resolve_run_dir_latest_without_runs_raises_clear_error(tmp_path: Path) -> None:
    with pytest.raises(CommandError, match="No benchmark run directories found"):
        resolve_run_dir("latest", output_base=tmp_path / "missing")


def test_load_json_file_reports_missing_path(tmp_path: Path) -> None:
    with pytest.raises(CommandError, match="JSON file not found"):
        load_json_file(tmp_path / "missing.json")


def test_load_json_file_reads_json(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    path.write_text(json.dumps({"ok": True}), encoding="utf-8")

    assert load_json_file(path) == {"ok": True}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_agent_eval_cli.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `app.agent_eval.commands`.

- [ ] **Step 3: Create the command package and common helpers**

Create `app/agent_eval/commands/__init__.py`:

```python
"""Command modules for the ProjectFlow AgentEval CLI."""
```

Create `app/agent_eval/commands/common.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_BASE = Path("output") / "agent-eval"


class CommandError(Exception):
    """User-facing CLI error with a clear message."""


def resolve_run_dir(raw: str, *, output_base: Path = DEFAULT_OUTPUT_BASE) -> Path:
    """Resolve a run directory path or the special `latest` reference."""
    if raw != "latest":
        path = Path(raw)
        if not path.is_dir():
            raise CommandError(f"Run directory not found: {path}")
        return path

    if not output_base.exists():
        raise CommandError(f"No benchmark run directories found in {output_base}")

    candidates = [
        path
        for path in output_base.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    ]
    if not candidates:
        raise CommandError(f"No benchmark run directories found in {output_base}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def load_json_file(path: Path) -> Any:
    """Read JSON and raise CommandError with the failing path."""
    if not path.exists():
        raise CommandError(f"JSON file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CommandError(f"Malformed JSON file: {path}: {exc}") from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_agent_eval_cli.py -v
```

Expected: PASS for the four helper tests.

- [ ] **Step 5: Commit**

```powershell
git add app/agent_eval/commands/__init__.py app/agent_eval/commands/common.py tests/test_agent_eval_cli.py
git commit -m "feat: add AgentEval CLI helpers"
```

## Task 2: Case Commands

**Files:**
- Create: `app/agent_eval/commands/cases.py`
- Modify: `tests/test_agent_eval_cli.py`

- [ ] **Step 1: Write failing tests for case listing and case show**

Append to `tests/test_agent_eval_cli.py`:

```python
from app.agent_eval.commands.cases import show_case, list_cases


def test_list_cases_prints_fixture_ids(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = list_cases("app/agent_eval/fixtures")

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "clarify_sparse_project" in captured.out
    assert "Total:" in captured.out


def test_show_case_prints_selected_fixture(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = show_case("clarify_sparse_project", "app/agent_eval/fixtures")

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Case: clarify_sparse_project" in captured.out
    assert "Entry point:" in captured.out
    assert "Minimum score:" in captured.out


def test_show_case_unknown_id_raises_clear_error() -> None:
    with pytest.raises(CommandError, match="Case fixture not found"):
        show_case("missing_case", "app/agent_eval/fixtures")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_agent_eval_cli.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `app.agent_eval.commands.cases`.

- [ ] **Step 3: Implement case commands**

Create `app/agent_eval/commands/cases.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.agent_eval.case_loader import list_fixture_ids
from app.agent_eval.commands.common import CommandError


def list_cases(fixtures: str) -> int:
    ids = list_fixture_ids(fixtures)
    print(f"Fixtures in {fixtures}:")
    for fixture_id in ids:
        print(f"  - {fixture_id}")
    print(f"\nTotal: {len(ids)} fixture(s)")
    return 0


def show_case(case_id: str, fixtures: str) -> int:
    path = Path(fixtures) / f"{case_id}.json"
    if not path.exists():
        raise CommandError(f"Case fixture not found: {path}. Run `pfae case list`.")

    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    print(f"Case: {data.get('id', case_id)}")
    print(f"Title: {data.get('title', '')}")
    print(f"Module: {data.get('module', '')}")
    print(f"Entry point: {data.get('entrypoint', '')}")
    print(f"Minimum score: {data.get('minimum_score', '')}")

    expected = data.get("expected_behavior", [])
    forbidden = data.get("forbidden_behavior", [])
    hard_rules = data.get("hard_fail_rules", [])

    if expected:
        print("\nExpected behavior:")
        for item in expected:
            print(f"  - {item}")
    if forbidden:
        print("\nForbidden behavior:")
        for item in forbidden:
            print(f"  - {item}")
    if hard_rules:
        print("\nHard fail rules:")
        for item in hard_rules:
            print(f"  - {item}")
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_agent_eval_cli.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app/agent_eval/commands/cases.py tests/test_agent_eval_cli.py
git commit -m "feat: add AgentEval case commands"
```

## Task 3: Top-Level CLI Parser

**Files:**
- Create: `app/agent_eval/cli.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_agent_eval_cli.py`

- [ ] **Step 1: Write failing tests for parser dispatch**

Append to `tests/test_agent_eval_cli.py`:

```python
from app.agent_eval.cli import main


def test_cli_case_list_dispatches(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["case", "list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "clarify_sparse_project" in captured.out


def test_cli_returns_nonzero_for_command_error(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["case", "show", "missing_case"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Case fixture not found" in captured.err
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_agent_eval_cli.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `app.agent_eval.cli`.

- [ ] **Step 3: Implement CLI parser and script entry points**

Create `app/agent_eval/cli.py`:

```python
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from app.agent_eval.commands.cases import list_cases, show_case
from app.agent_eval.commands.common import CommandError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ProjectFlow AgentEval Toolkit")
    sub = parser.add_subparsers(dest="command")

    case_parser = sub.add_parser("case", help="Inspect benchmark cases")
    case_sub = case_parser.add_subparsers(dest="case_command")
    case_list = case_sub.add_parser("list", help="List fixture IDs")
    case_list.add_argument("--fixtures", default="app/agent_eval/fixtures")
    case_show = case_sub.add_parser("show", help="Show one fixture")
    case_show.add_argument("case_id")
    case_show.add_argument("--fixtures", default="app/agent_eval/fixtures")

    return parser


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "case" and args.case_command == "list":
        return list_cases(args.fixtures)
    if args.command == "case" and args.case_command == "show":
        return show_case(args.case_id, args.fixtures)
    raise CommandError("No command selected. Run `pfae --help`.")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except CommandError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

Modify `pyproject.toml`:

```toml
[project.scripts]
pfae = "app.agent_eval.cli:main"
projectflow-agent-eval = "app.agent_eval.cli:main"
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_agent_eval_cli.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app/agent_eval/cli.py pyproject.toml tests/test_agent_eval_cli.py
git commit -m "feat: add AgentEval CLI entrypoint"
```

## Task 4: Run Commands

**Files:**
- Create: `app/agent_eval/commands/runs.py`
- Modify: `app/agent_eval/cli.py`
- Modify: `tests/test_agent_eval_cli.py`

- [ ] **Step 1: Write failing tests for run command dispatch with monkeypatch**

Append to `tests/test_agent_eval_cli.py`:

```python
import app.agent_eval.commands.runs as run_commands


def test_run_mock_delegates_to_runner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run_suite(fixtures: str, **kwargs: object) -> tuple[list[object], object]:
        captured["fixtures"] = fixtures
        captured.update(kwargs)

        class Summary:
            run_id = "run-1"
            model = "stub"
            cases_passed = 1
            cases_total = 1
            average_score = 1.0
            hard_failure_count = 0
            duration_seconds = 0.1
            cases_failed = 0
            cases_judge_failed = 0
            cache_hits = 0
            cache_misses = 0
            skipped_cases = 0
            config = None

        return [], Summary()

    monkeypatch.setattr(run_commands, "run_suite", fake_run_suite)

    exit_code = run_commands.run_benchmark("mock", output_dir=str(tmp_path / "run"))

    assert exit_code == 0
    assert captured["mode"] == "mock"
    assert captured["model"] == "stub"


def test_cli_run_mock_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_commands, "run_benchmark", lambda action, **kwargs: 0)

    assert main(["run", "mock"]) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_agent_eval_cli.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `app.agent_eval.commands.runs`.

- [ ] **Step 3: Implement run command wrapper and parser routes**

Create `app/agent_eval/commands/runs.py`:

```python
from __future__ import annotations

from pathlib import Path

from app.agent_eval.runner import DEFAULT_CACHE_DIR, run_suite


def run_benchmark(
    action: str,
    *,
    fixtures: str = "app/agent_eval/fixtures",
    output_dir: str | None = None,
    model: str | None = None,
    runs_per_case: int = 1,
    workers: int = 4,
    judge_mode: str = "auto",
    semantic_guard: str = "auto",
    semantic_judge_model: str = "",
    semantic_judge_base_url: str = "",
    case_filter: str = "",
    cache_dir: str = str(DEFAULT_CACHE_DIR),
    no_cache: bool = False,
    run_ref: str = "",
) -> int:
    mode = "real" if action == "real" else "mock"
    selected_model = model or ("stub" if mode == "mock" else "")
    case_ids = [part.strip() for part in case_filter.split(",") if part.strip()] or None
    resume_from = run_ref if action == "resume" else ""
    retry_failed_from = run_ref if action == "retry-failed" else ""
    retry_errors_from = run_ref if action == "retry-errors" else ""

    reports, summary = run_suite(
        fixtures,
        mode=mode,
        output_dir=output_dir,
        model=selected_model,
        runs_per_case=runs_per_case,
        workers=workers,
        judge_mode=judge_mode,
        case_ids=case_ids,
        cache_dir=cache_dir,
        use_cache=not no_cache,
        resume_from=resume_from,
        retry_failed_from=retry_failed_from,
        retry_errors_from=retry_errors_from,
        semantic_guard_mode=semantic_guard,
        semantic_judge_model=semantic_judge_model,
        semantic_judge_base_url=semantic_judge_base_url,
    )

    print(f"Run ID: {summary.run_id}")
    print(f"Model: {summary.model}")
    print(f"Cases: {summary.cases_passed}/{summary.cases_total} passed")
    print(f"Average score: {summary.average_score:.3f}")
    print(f"Hard failures: {summary.hard_failure_count}")
    print(f"Duration: {summary.duration_seconds:.1f}s")
    if reports:
        print(f"Reports: {Path(reports[0].output_path).parent}")

    return 0 if summary.cases_failed == 0 and summary.cases_judge_failed == 0 else 1
```

Modify `app/agent_eval/cli.py` to import `run_benchmark`, add the `run` parser, and dispatch:

```python
from app.agent_eval.commands.runs import run_benchmark
```

Inside `_build_parser()` before `return parser`:

```python
    run_parser = sub.add_parser("run", help="Run benchmark suites")
    run_sub = run_parser.add_subparsers(dest="run_command")
    for name in ("mock", "real"):
        item = run_sub.add_parser(name, help=f"Run benchmark in {name} mode")
        _add_run_options(item)
    for name in ("resume", "retry-failed", "retry-errors"):
        item = run_sub.add_parser(name, help=f"Run benchmark with {name}")
        item.add_argument("run_ref", nargs="?", default="latest")
        _add_run_options(item)
```

Add this helper in `cli.py`:

```python
def _add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--fixtures", default="app/agent_eval/fixtures")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--runs-per-case", type=int, default=1)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--judge-mode", default="auto", choices=["auto", "llm", "stub"])
    parser.add_argument("--semantic-guard", default="auto", choices=["off", "auto", "required"])
    parser.add_argument("--semantic-judge-model", default="")
    parser.add_argument("--semantic-judge-base-url", default="")
    parser.add_argument("--case-filter", default="")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--no-cache", action="store_true")
```

Also import `DEFAULT_CACHE_DIR` in `cli.py`:

```python
from app.agent_eval.runner import DEFAULT_CACHE_DIR
```

Add to `_dispatch()`:

```python
    if args.command == "run" and args.run_command:
        return run_benchmark(
            args.run_command,
            fixtures=args.fixtures,
            output_dir=args.output_dir,
            model=args.model,
            runs_per_case=args.runs_per_case,
            workers=args.workers,
            judge_mode=args.judge_mode,
            semantic_guard=args.semantic_guard,
            semantic_judge_model=args.semantic_judge_model,
            semantic_judge_base_url=args.semantic_judge_base_url,
            case_filter=args.case_filter,
            cache_dir=args.cache_dir,
            no_cache=args.no_cache,
            run_ref=getattr(args, "run_ref", ""),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_agent_eval_cli.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app/agent_eval/commands/runs.py app/agent_eval/cli.py tests/test_agent_eval_cli.py
git commit -m "feat: add AgentEval run commands"
```

## Task 5: Report and Diagnose Commands

**Files:**
- Create: `app/agent_eval/commands/reports.py`
- Create: `app/agent_eval/commands/diagnose.py`
- Modify: `app/agent_eval/cli.py`
- Modify: `tests/test_agent_eval_cli.py`

- [ ] **Step 1: Write failing tests for report and diagnose summaries**

Append to `tests/test_agent_eval_cli.py`:

```python
from app.agent_eval.commands.reports import show_report
from app.agent_eval.commands.diagnose import diagnose_run


def _write_minimal_run(run_dir: Path) -> None:
    run_dir.mkdir(parents=True)
    (run_dir / "suite_summary.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "model": "stub",
                "cases_total": 1,
                "cases_passed": 0,
                "cases_failed": 1,
                "cases_judge_failed": 0,
                "average_score": 0.42,
                "hard_failure_count": 1,
                "top_failure_categories": ["scope_creep"],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "case_one.report.json").write_text(
        json.dumps(
            {
                "case_id": "case_one",
                "module": "planning",
                "status": "failed",
                "hard_failures": ["violates_mvp_boundary"],
                "failure_categories": ["scope_creep"],
                "assertion_results": [
                    {
                        "assertion_id": "no_external_integrations",
                        "status": "failed",
                        "severity": "hard",
                        "message": "mentions external integration",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_show_report_prints_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_dir = tmp_path / "run-1"
    _write_minimal_run(run_dir)

    exit_code = show_report(str(run_dir))

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Run ID: run-1" in captured.out
    assert "Hard failures: 1" in captured.out


def test_diagnose_run_prints_failed_case(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_dir = tmp_path / "run-1"
    _write_minimal_run(run_dir)

    exit_code = diagnose_run(str(run_dir))

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Failed cases:" in captured.out
    assert "case_one" in captured.out
    assert "violates_mvp_boundary" in captured.out
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_agent_eval_cli.py -v
```

Expected: FAIL with missing report and diagnose modules.

- [ ] **Step 3: Implement report and diagnose commands**

Create `app/agent_eval/commands/reports.py`:

```python
from __future__ import annotations

from pathlib import Path

from app.agent_eval.commands.common import DEFAULT_OUTPUT_BASE, load_json_file, resolve_run_dir


def show_report(run_ref: str, *, output_base: Path = DEFAULT_OUTPUT_BASE) -> int:
    run_dir = resolve_run_dir(run_ref, output_base=output_base)
    summary = load_json_file(run_dir / "suite_summary.json")

    print(f"Run ID: {summary.get('run_id', '')}")
    print(f"Model: {summary.get('model', '')}")
    print(f"Cases: {summary.get('cases_passed', 0)}/{summary.get('cases_total', 0)} passed")
    print(f"Average score: {float(summary.get('average_score', 0.0)):.3f}")
    print(f"Hard failures: {summary.get('hard_failure_count', 0)}")
    categories = summary.get("top_failure_categories", [])
    if categories:
        print(f"Top failure categories: {', '.join(categories)}")
    print(f"Report directory: {run_dir}")
    return 0
```

Create `app/agent_eval/commands/diagnose.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agent_eval.commands.common import DEFAULT_OUTPUT_BASE, load_json_file, resolve_run_dir


def diagnose_run(run_ref: str, *, output_base: Path = DEFAULT_OUTPUT_BASE) -> int:
    run_dir = resolve_run_dir(run_ref, output_base=output_base)
    report_paths = sorted(run_dir.glob("*.report.json"))

    failed: list[dict[str, Any]] = []
    skipped: list[str] = []
    for path in report_paths:
        try:
            report = load_json_file(path)
        except Exception as exc:
            skipped.append(f"{path}: {exc}")
            continue
        if report.get("status") != "passed":
            failed.append(report)

    if not failed:
        print(f"No failed cases in {run_dir}")
    else:
        print("Failed cases:")
        for report in failed:
            print(f"  - {report.get('case_id', '')} [{report.get('module', '')}] {report.get('status', '')}")
            hard_failures = report.get("hard_failures", [])
            if hard_failures:
                print(f"    hard failures: {', '.join(hard_failures)}")
            categories = report.get("failure_categories", [])
            if categories:
                print(f"    categories: {', '.join(categories)}")
            for assertion in report.get("assertion_results", []):
                if assertion.get("status") == "failed":
                    assertion_id = assertion.get("assertion_id", "")
                    severity = assertion.get("severity", "")
                    message = assertion.get("message", "")
                    print(f"    assertion: {assertion_id} [{severity}] {message}")

    if skipped:
        print("\nSkipped malformed reports:")
        for item in skipped:
            print(f"  - {item}")
    return 0 if not failed else 1
```

Modify `app/agent_eval/cli.py` imports:

```python
from app.agent_eval.commands.diagnose import diagnose_run
from app.agent_eval.commands.reports import show_report
```

Add parsers before `return parser`:

```python
    report_parser = sub.add_parser("report", help="Read benchmark reports")
    report_sub = report_parser.add_subparsers(dest="report_command")
    report_latest = report_sub.add_parser("latest", help="Show latest report")
    report_latest.set_defaults(run_ref="latest")
    report_show = report_sub.add_parser("show", help="Show report directory")
    report_show.add_argument("run_ref")

    diagnose_parser = sub.add_parser("diagnose", help="Diagnose benchmark failures")
    diagnose_parser.add_argument("run_ref", nargs="?", default="latest")
```

Add dispatch:

```python
    if args.command == "report" and args.report_command:
        return show_report(args.run_ref)
    if args.command == "diagnose":
        return diagnose_run(args.run_ref)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_agent_eval_cli.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app/agent_eval/commands/reports.py app/agent_eval/commands/diagnose.py app/agent_eval/cli.py tests/test_agent_eval_cli.py
git commit -m "feat: add AgentEval report diagnostics"
```

## Task 6: Compare Command

**Files:**
- Create: `app/agent_eval/commands/compare.py`
- Modify: `app/agent_eval/cli.py`
- Modify: `tests/test_agent_eval_cli.py`

- [ ] **Step 1: Write failing tests for compare delegation**

Append to `tests/test_agent_eval_cli.py`:

```python
import app.agent_eval.commands.compare as compare_commands


def test_compare_command_delegates_to_runner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    baseline.mkdir()
    candidate.mkdir()
    captured: dict[str, object] = {}

    def fake_compare(args: object) -> int:
        captured["baseline_dir"] = args.baseline_dir
        captured["candidate_dir"] = args.candidate_dir
        return 0

    monkeypatch.setattr(compare_commands, "_runner_compare", fake_compare)

    assert compare_commands.compare_runs_command(str(baseline), str(candidate)) == 0
    assert captured["baseline_dir"] == str(baseline)
    assert captured["candidate_dir"] == str(candidate)


def test_cli_compare_dispatches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    baseline.mkdir()
    candidate.mkdir()
    monkeypatch.setattr(compare_commands, "compare_runs_command", lambda baseline_ref, candidate_ref, output_dir=None: 0)

    assert main(["compare", str(baseline), str(candidate)]) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_agent_eval_cli.py -v
```

Expected: FAIL with missing compare command module.

- [ ] **Step 3: Implement compare command wrapper and parser route**

Create `app/agent_eval/commands/compare.py`:

```python
from __future__ import annotations

import argparse
from pathlib import Path

from app.agent_eval.commands.common import DEFAULT_OUTPUT_BASE, resolve_run_dir
from app.agent_eval.runner import _cmd_compare as _runner_compare


def compare_runs_command(
    baseline_ref: str,
    candidate_ref: str,
    *,
    output_dir: str | None = None,
    output_base: Path = DEFAULT_OUTPUT_BASE,
) -> int:
    baseline_dir = resolve_run_dir(baseline_ref, output_base=output_base)
    candidate_dir = resolve_run_dir(candidate_ref, output_base=output_base)
    args = argparse.Namespace(
        baseline_dir=str(baseline_dir),
        candidate_dir=str(candidate_dir),
        output_dir=output_dir,
    )
    return _runner_compare(args)
```

Modify `app/agent_eval/cli.py` imports:

```python
from app.agent_eval.commands.compare import compare_runs_command
```

Add parser before `return parser`:

```python
    compare_parser = sub.add_parser("compare", help="Compare two benchmark runs")
    compare_parser.add_argument("baseline")
    compare_parser.add_argument("candidate")
    compare_parser.add_argument("--output-dir", default=None)
```

Add dispatch:

```python
    if args.command == "compare":
        return compare_runs_command(args.baseline, args.candidate, output_dir=args.output_dir)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_agent_eval_cli.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add app/agent_eval/commands/compare.py app/agent_eval/cli.py tests/test_agent_eval_cli.py
git commit -m "feat: add AgentEval compare command"
```

## Task 7: Skill and User Documentation

**Files:**
- Create: `skills/projectflow-agent-eval/SKILL.md`
- Create: `skills/projectflow-agent-eval/references/command-guide.md`
- Create: `skills/projectflow-agent-eval/references/report-interpretation.md`
- Modify: `README.md`

- [ ] **Step 1: Create the skill file**

Create `skills/projectflow-agent-eval/SKILL.md`:

```markdown
---
name: projectflow-agent-eval
description: Use when running, inspecting, comparing, or diagnosing ProjectFlow AgentEval benchmark results through the `pfae` CLI.
---

# ProjectFlow AgentEval

Use this skill when the user asks to run ProjectFlow AgentEval, benchmark the ProjectFlow agent, compare quality across runs, inspect failures, rerun failed cases, or turn AgentEval reports into repair guidance.

## First Steps

1. Prefer `pfae run mock` for fast local checks that do not need provider credentials.
2. Use `pfae run real --model <model>` only when the environment is already configured.
3. Use `pfae report latest` for a concise run summary.
4. Use `pfae diagnose latest` before proposing fixes for benchmark failures.
5. Use `pfae compare <baseline> <candidate>` for regression checks.

## Safety Boundaries

- Do not edit `.env`, keys, tokens, CI/CD configuration, or provider credentials.
- Do not commit `output/`, caches, local virtual environments, or generated benchmark artifacts.
- Treat deterministic hard failures as authoritative.
- Treat LLM judge output as semantic evidence, not the sole source of hard failures.
- Keep this benchmark independent from ProjectFlow product backend persistence.

## References

- Read `references/command-guide.md` for exact command shapes.
- Read `references/report-interpretation.md` when explaining failures.
```

- [ ] **Step 2: Create command reference**

Create `skills/projectflow-agent-eval/references/command-guide.md`:

```markdown
# ProjectFlow AgentEval Command Guide

## Inspect Cases

```powershell
pfae case list
pfae case show <case_id>
```

## Run Benchmark

```powershell
pfae run mock
pfae run real --model deepseek-v4-pro
pfae run resume latest
pfae run retry-failed latest
pfae run retry-errors latest
```

Use `mock` when credentials are unavailable or the user only wants a local sanity check.

## Read Reports

```powershell
pfae report latest
pfae report show <run_dir>
pfae diagnose latest
```

Run `diagnose` before recommending code or prompt changes.

## Compare Runs

```powershell
pfae compare <baseline_run_dir> <candidate_run_dir>
```

A non-zero exit code means the candidate failed the regression gate.
```

- [ ] **Step 3: Create report interpretation reference**

Create `skills/projectflow-agent-eval/references/report-interpretation.md`:

```markdown
# Report Interpretation

Prioritize failures in this order:

1. Deterministic hard failures.
2. Failed hard assertions.
3. Semantic guard hard failures with evidence.
4. Repeated failure categories across cases.
5. Low semantic judge scores.

Do not mark a run healthy because the average score is high if any hard failure exists.

When summarizing failures, include:

- case ID
- module
- hard failures
- failed assertions
- failure categories
- report directory
- the smallest likely repair target

Do not quote secrets or dump full raw model outputs unless the user explicitly asks and the content has been checked for sensitive values.
```

- [ ] **Step 4: Update README with short CLI usage**

Add this section after `## Setup` in `README.md`:

```markdown
## CLI Toolkit

After editable install, use the short CLI:

```powershell
pfae case list
pfae run mock
pfae report latest
pfae diagnose latest
```

The compatibility command is also available:

```powershell
projectflow-agent-eval run mock
```

The lower-level runner module remains available for direct development use, but agents should prefer `pfae`.
```

- [ ] **Step 5: Run documentation sanity checks**

Run:

```powershell
Select-String -Path 'skills/projectflow-agent-eval/SKILL.md','skills/projectflow-agent-eval/references/*.md','README.md' -Pattern 'T[B]D|T[O]DO|PLACE[H]OLDER' -CaseSensitive:$false
```

Expected: no matches.

- [ ] **Step 6: Commit**

```powershell
git add skills/projectflow-agent-eval README.md
git commit -m "docs: add AgentEval skill guide"
```

## Task 8: Integration Verification and Public Repo Safety

**Files:**
- Modify only if verification exposes a bug.

- [ ] **Step 1: Run focused CLI tests**

Run:

```powershell
python -m pytest tests/test_agent_eval_cli.py -v
```

Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run:

```powershell
python -m pytest -v
```

Expected: PASS.

- [ ] **Step 3: Reinstall editable package if `pfae` is not on PATH**

Run:

```powershell
python -m pip install -e ".[dev]"
```

Expected: package installs successfully.

- [ ] **Step 4: Verify CLI commands**

Run:

```powershell
pfae case list
pfae run mock --output-dir output/agent-eval-cli-smoke
pfae report show output/agent-eval-cli-smoke
pfae diagnose output/agent-eval-cli-smoke
```

Expected:

- `case list` prints fixture IDs.
- `run mock` completes without credentials.
- `report show` prints run ID, cases, average score, and hard failures.
- `diagnose` prints either no failed cases or a deterministic failure summary.

- [ ] **Step 5: Run secret scan before any final commit or push**

Run:

```powershell
$files = git ls-files
$patterns = @(
  'sk-[A-Za-z0-9_-]{20,}',
  'AKIA[0-9A-Z]{16}',
  '-----BEGIN (RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----',
  '(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*["''][^"'']{8,}["'']'
)
$hits = @()
foreach ($file in $files) {
  if (Test-Path -LiteralPath $file) {
    foreach ($pattern in $patterns) {
      $match = Select-String -LiteralPath $file -Pattern $pattern -ErrorAction SilentlyContinue
      if ($match) { $hits += $match }
    }
  }
}
if ($hits.Count -gt 0) {
  $hits | ForEach-Object { "${($_.Path)}:$($_.LineNumber): $($_.Line.Trim())" }
  exit 1
}
"Secret scan passed."
```

Expected: `Secret scan passed.`

- [ ] **Step 6: Check git status excludes generated output**

Run:

```powershell
git status --short
```

Expected: no tracked changes under `output/`, `.pytest_cache/`, `.venv/`, or cache directories.

- [ ] **Step 7: Commit final verification fixes if needed**

If verification required fixes:

```powershell
git add <fixed_files>
git commit -m "fix: stabilize AgentEval CLI verification"
```

If no fixes were needed, do not create an empty commit.

## Self-Review

- Spec coverage: The plan covers CLI entry points, command modules, run/report/compare/diagnose behavior, skill documentation, README updates, focused tests, full tests, and secret scanning.
- Marker scan: No unfinished-work markers are intentionally left in the plan.
- Type consistency: The plan consistently uses `CommandError`, `resolve_run_dir`, `load_json_file`, `run_benchmark`, `show_report`, `diagnose_run`, and `compare_runs_command`.
