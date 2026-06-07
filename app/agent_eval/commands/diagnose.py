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
    return 0
