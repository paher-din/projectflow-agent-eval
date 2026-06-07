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
