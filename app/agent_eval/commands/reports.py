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
