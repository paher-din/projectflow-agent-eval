"""Report writer for Agent Evaluation Benchmark.

Produces three artifact levels per run:
1. Per-case JSON report.
2. Suite summary JSON.
3. Human-readable Markdown summary.

Also provides a ``compare_runs()`` function for baseline vs candidate diff reports.
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Sequence

from app.agent_eval.schemas import (
    CaseReport,
    CaseStatus,
    DiffEntry,
    DiffReport,
    RunConfig,
    SuiteSummary,
)


def write_case_report(
    report: CaseReport,
    output_dir: str | Path,
    *,
    filename: str | None = None,
) -> str:
    """Write a single case report as JSON.

    Returns the absolute path to the written file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    fpath = output_dir / (filename or f"{report.case_id}.report.json")
    _write_agent_output_artifact(report, output_dir, fpath)
    fpath.write_text(
        report.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8",
    )

    # Also store the output_path for reference
    report.output_path = str(fpath)
    return str(fpath)


def _write_agent_output_artifact(
    report: CaseReport,
    output_dir: Path,
    report_path: Path,
) -> None:
    if report.agent_output is None and report.raw_agent_output is None:
        return

    output_name = report_path.name.replace(".report.json", ".output.json")
    if output_name == report_path.name:
        output_name = f"{report_path.stem}.output.json"

    output_path = output_dir / output_name
    output_path.write_text(
        json.dumps(
            {
                "case_id": report.case_id,
                "agent_status": report.agent_status,
                "used_fallback": report.used_fallback,
                "agent_output": report.agent_output,
                "raw_agent_output": report.raw_agent_output,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    report.agent_output_path = str(output_path)


def write_suite_summary(
    summary: SuiteSummary,
    output_dir: str | Path,
) -> str:
    """Write the suite summary JSON.

    Returns the absolute path to the written file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    fpath = output_dir / "suite_summary.json"
    fpath.write_text(
        summary.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8",
    )
    return str(fpath)


def write_markdown_summary(
    summary: SuiteSummary,
    reports: Sequence[CaseReport],
    output_dir: str | Path,
    *,
    baseline_summary: SuiteSummary | None = None,
) -> str:
    """Write a human-readable Markdown summary.

    Parameters
    ----------
    summary
        The suite summary.
    reports
        All case reports for this run.
    output_dir
        Output directory for the markdown file.
    baseline_summary
        Optional previous run for regression comparison.

    Returns the absolute path to the written file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append("# Agent Evaluation Benchmark Report")
    lines.append("")
    lines.append(f"**Run ID:** {summary.run_id}")
    lines.append(f"**Model:** {summary.model}")
    lines.append(f"**Date:** {summary.timestamp}")
    lines.append(f"**Duration:** {summary.duration_seconds:.1f}s")
    lines.append("")

    # Config section
    if summary.config and summary.config.mode != "mock":
        lines.append("## Configuration")
        lines.append("")
        lines.append(f"- Mode: {summary.config.mode}")
        lines.append(f"- Model: {summary.config.model}")
        lines.append(f"- Provider: {summary.config.provider}")
        lines.append(f"- Base URL: {summary.config.base_url_host}")
        lines.append(f"- Judge Mode: {summary.config.judge_mode}")
        lines.append(f"- Semantic Guard: {summary.config.semantic_guard_mode.value}")
        if summary.config.semantic_judge_model:
            lines.append(f"- Semantic Judge Model: {summary.config.semantic_judge_model}")
        if summary.config.semantic_judge_base_url_host:
            lines.append(f"- Semantic Judge Base URL: {summary.config.semantic_judge_base_url_host}")
        if summary.config.semantic_judge_prompt_version:
            lines.append(f"- Semantic Judge Prompt: {summary.config.semantic_judge_prompt_version}")
        lines.append(f"- Cache Enabled: {summary.config.cache_enabled}")
        if summary.config.cache_dir:
            lines.append(f"- Cache Dir: {summary.config.cache_dir}")
        if summary.config.resume_from:
            lines.append(f"- Resume From: {summary.config.resume_from}")
        if summary.config.retry_from:
            lines.append(f"- Retry From: {summary.config.retry_from}")
            lines.append(f"- Retry Mode: {summary.config.retry_mode}")
        lines.append(f"- Temperature: {summary.config.temperature}")
        if summary.config.case_ids:
            lines.append(f"- Case Filter: {', '.join(summary.config.case_ids)}")
        if summary.config.projectflow_source_path:
            lines.append(f"- ProjectFlow Agent Source: {summary.config.projectflow_source_path}")
        if summary.config.projectflow_git_commit:
            lines.append(f"- ProjectFlow Agent Commit: {summary.config.projectflow_git_commit}")
        if summary.config.agent_model:
            lines.append(f"- Agent Model: {summary.config.agent_model}")
        lines.append("")

    # Overall summary
    lines.append("## Overall Result")
    lines.append("")
    pass_rate = summary.cases_passed / max(summary.cases_total, 1) * 100
    lines.append(f"- **Cases:** {summary.cases_passed} / {summary.cases_total} passed ({pass_rate:.0f}%)")
    lines.append(f"- **Average Score:** {summary.average_score:.3f}")
    lines.append(f"- **Hard Failures:** {summary.hard_failure_count}")
    lines.append(f"- **Judge Failures:** {summary.cases_judge_failed}")
    semantic_reports = [r.semantic_guard for r in reports if r.semantic_guard is not None]
    if semantic_reports:
        semantic_hard = sum(len(r.hard_failures) for r in semantic_reports)
        semantic_uncertain = sum(r.uncertain_count for r in semantic_reports)
        semantic_called = sum(1 for r in semantic_reports if r.called)
        semantic_diag_count = sum(len(r.diagnostics) for r in semantic_reports)
        diag_suffix = f", {semantic_diag_count} diagnostic(s)" if semantic_diag_count else ""
        lines.append(f"- **Semantic Guard:** {semantic_hard} hard, {semantic_uncertain} uncertain, {semantic_called} judge call(s){diag_suffix}")
    if summary.cache_hits or summary.cache_misses:
        lines.append(f"- **Cache:** {summary.cache_hits} hit / {summary.cache_misses} miss")
    if summary.skipped_cases:
        lines.append(f"- **Skipped by Resume:** {summary.skipped_cases}")
    lines.append("")

    # Regression comparison
    if baseline_summary:
        score_delta = summary.average_score - baseline_summary.average_score
        delta_str = f"{score_delta:+.3f}"
        lines.append("### Regression vs Baseline")
        lines.append("")
        lines.append(f"- Baseline Run: `{baseline_summary.run_id}`")
        lines.append(f"- Score Delta: {delta_str}")
        lines.append(f"- Baseline Average: {baseline_summary.average_score:.3f}")
        lines.append("")

    # Case table
    lines.append("## Case Results")
    lines.append("")
    lines.append("| Case ID | Module | Judge Score | Status | Hard Failures | Semantic Guard | Assertions Failed/Total | Assertion Score |")
    lines.append("|---------|--------|------:|--------|---------------|----------------|------------|------|")

    for rep in sorted(reports, key=lambda r: r.case_id):
        hf_str = ", ".join(rep.hard_failures) if rep.hard_failures else "-"
        status_icon = "✅" if rep.status == CaseStatus.passed else "❌"
        if rep.assertion_results:
            failed_ct = sum(1 for r in rep.assertion_results if r.status == "failed")
            total_ct = len(rep.assertion_results)
            as_count = f"{failed_ct}/{total_ct}"
        else:
            as_count = "-"
        sg_str = "-"
        if rep.semantic_guard:
            if rep.semantic_guard.hard_failures:
                sg_str = f"hard:{len(rep.semantic_guard.hard_failures)}"
            elif rep.semantic_guard.uncertain_count:
                sg_str = f"uncertain:{rep.semantic_guard.uncertain_count}"
            elif rep.semantic_guard.diagnostics:
                sg_str = f"diagnostic:{len(rep.semantic_guard.diagnostics)}"
            elif rep.semantic_guard.called:
                sg_str = "judged"
        ws_str = f"{rep.weighted_score:.2f}" if hasattr(rep, 'weighted_score') and rep.weighted_score != rep.overall_score else "-"
        lines.append(f"| {rep.case_id} | {rep.module} | {rep.overall_score:.2f} | {status_icon} {rep.status.value} | {hf_str} | {sg_str} | {as_count} | {ws_str} |")

    lines.append("")

    # Top failures
    if summary.top_failure_categories:
        lines.append("## Top Failure Categories")
        lines.append("")
        for cat in summary.top_failure_categories:
            lines.append(f"- {cat}")
        lines.append("")

    # Module scores
    if summary.module_scores:
        lines.append("## Module Averages")
        lines.append("")
        lines.append("| Module | Average Score |")
        lines.append("|--------|--------------:|")
        for module, score in sorted(summary.module_scores.items()):
            lines.append(f"| {module} | {score:.3f} |")
        lines.append("")

    # Failure details
    failed_reports = [r for r in reports if r.status != CaseStatus.passed]
    if failed_reports:
        lines.append("## Failed Cases Detail")
        lines.append("")
        for rep in failed_reports:
            lines.append(f"### {rep.case_id}")
            lines.append("")
            lines.append(f"- **Status:** {rep.status.value}")
            lines.append(f"- **Score:** {rep.overall_score:.3f}")
            if rep.hard_failures:
                lines.append(f"- **Hard Failures:** {', '.join(rep.hard_failures)}")
            if rep.failure_categories:
                lines.append(f"- **Failure Categories:** {', '.join(rep.failure_categories)}")
            if rep.error_message:
                lines.append(f"- **Error:** {rep.error_message}")
            if rep.judge_result and rep.judge_result.diagnostics:
                lines.append("- **Judge Diagnostics:**")
                for diagnostic in rep.judge_result.diagnostics[:5]:
                    detail = f"{diagnostic.kind.value}: {diagnostic.message}"
                    if diagnostic.candidate_count:
                        detail += f" (candidates: {diagnostic.candidate_count})"
                    if diagnostic.case_impact != "none":
                        detail += f" (case impact: {diagnostic.case_impact})"
                    lines.append(f"  - {detail}")
            if rep.semantic_guard and (
                rep.semantic_guard.hard_failures
                or rep.semantic_guard.uncertain_count
                or rep.semantic_guard.error_message
                or rep.semantic_guard.diagnostics
            ):
                lines.append(f"- **Semantic Guard:** {len(rep.semantic_guard.hard_failures)} hard, {rep.semantic_guard.uncertain_count} uncertain")
                if rep.semantic_guard.error_message:
                    lines.append(f"- **Semantic Guard Error:** {rep.semantic_guard.error_message}")
                for finding in rep.semantic_guard.findings[:5]:
                    lines.append(
                        f"  - {finding.decision.value} `{finding.span}` at `{finding.path}`: {finding.evidence}"
                    )
                if rep.semantic_guard.diagnostics:
                    lines.append("- **Semantic Judge Diagnostics:**")
                    for diagnostic in rep.semantic_guard.diagnostics[:5]:
                        detail = f"{diagnostic.kind.value}: {diagnostic.message}"
                        if diagnostic.candidate_count:
                            detail += f" (candidates: {diagnostic.candidate_count})"
                        if diagnostic.case_impact != "none":
                            detail += f" (case impact: {diagnostic.case_impact})"
                        lines.append(f"  - {detail}")
            lines.append("")

    # Failed assertion leaderboard (uses assertion_summary from SuiteSummary)
    if summary.assertion_summary and summary.assertion_summary.get("top_failing_assertions"):
        top_fails = summary.assertion_summary["top_failing_assertions"]
        if top_fails:
            lines.append("## Failed Assertion Leaderboard")
            lines.append("")
            lines.append("| Assertion ID | Fail Count |")
            lines.append("|--------------|-----------:|")
            for entry in top_fails:
                lines.append(f"| {entry['assertion_id']} | {entry['fail_count']} |")
            lines.append("")

    # Stability summary
    if summary.stability_summary:
        stab = summary.stability_summary
        lines.append("## Stability Summary")
        lines.append("")
        if stab.get("avg_pass_at_1") is not None:
            lines.append(f"- Avg pass@1: {stab['avg_pass_at_1']:.3f}")
        if stab.get("avg_score_variance") is not None:
            lines.append(f"- Avg score variance: {stab['avg_score_variance']:.6f}")
        if stab.get("flaky_assertions"):
            lines.append(f"- Flaky assertions: {', '.join(stab['flaky_assertions'])}")
        lines.append("")

    # Next steps
    if failed_reports:
        lines.append("## Suggested Next Fixes")
        lines.append("")
        for rep in failed_reports:
            if rep.hard_failures:
                lines.append(f"- **{rep.case_id}:** Fix hard failures: {', '.join(rep.hard_failures)}")
            if rep.failure_categories:
                for cat in rep.failure_categories:
                    lines.append(f"  - Address failure category: {cat}")
        lines.append("")

    fpath = output_dir / "summary.md"
    fpath.write_text("\n".join(lines), encoding="utf-8")
    return str(fpath)


def build_suite_summary(
    run_id: str,
    reports: Sequence[CaseReport],
    *,
    config: RunConfig | None = None,
    duration_seconds: float = 0.0,
    skipped_cases: int = 0,
) -> SuiteSummary:
    """Aggregate per-case reports into a ``SuiteSummary``."""
    total = len(reports)
    passed = sum(1 for r in reports if r.status == CaseStatus.passed)
    failed = sum(1 for r in reports if r.status == CaseStatus.failed)
    judge_failed = sum(1 for r in reports if r.status == CaseStatus.judge_failed)
    quality_reports = [r for r in reports if _counts_toward_quality_score(r)]
    scores = [_effective_score(r) for r in quality_reports]
    avg = sum(scores) / max(len(scores), 1)

    hard_failure_count = sum(len(_hard_failure_ids(r)) for r in reports)
    cache_hits = sum(1 for r in reports if r.cache_hit)
    cache_misses = sum(1 for r in reports if r.cache_key and not r.cache_hit)

    # Collect failure categories
    all_categories: list[str] = []
    for r in reports:
        all_categories.extend(r.failure_categories)
        if r.semantic_guard:
            for category in r.semantic_guard.failure_categories:
                if category not in r.failure_categories:
                    all_categories.append(category)
        for ar in r.assertion_results:
            if ar.status == "failed" and ar.failure_category:
                all_categories.append(ar.failure_category)
    category_counts = Counter(all_categories)
    top_cats = [cat for cat, _ in category_counts.most_common(5)]

    # Module averages
    module_scores: dict[str, list[float]] = {}
    for r in quality_reports:
        module_scores.setdefault(r.module, []).append(_effective_score(r))
    module_avgs = {m: sum(s) / len(s) for m, s in module_scores.items()}

    # Determine model from first report
    model = reports[0].model if reports else "unknown"

    # Aggregate assertion data across all reports
    assertion_fail_counts: dict[str, int] = {}
    assertion_fail_details: dict[str, list[str]] = {}
    for r in reports:
        for ar in r.assertion_results:
            if ar.status == "failed":
                aid = ar.assertion_id
                assertion_fail_counts[aid] = assertion_fail_counts.get(aid, 0) + 1
                cat = ar.failure_category or "unknown"
                if aid not in assertion_fail_details:
                    assertion_fail_details[aid] = []
                if cat not in assertion_fail_details[aid]:
                    assertion_fail_details[aid].append(cat)
    top_failing_assertions = sorted(
        assertion_fail_counts.items(),
        key=lambda x: -x[1]
    )[:10]

    # Build aggregate stability summary
    stability_active = any(r.stability is not None for r in reports)

    assertion_summary = {
        "total_assertions_run": sum(
            len(r.assertion_results) for r in reports
        ),
        "total_failed_assertions": sum(
            assertion_fail_counts.values()
        ),
        "top_failing_assertions": [
            {"assertion_id": aid, "fail_count": cnt}
            for aid, cnt in top_failing_assertions
        ],
    }

    stability_summary = None
    if stability_active:
        avg_pass_at_1 = 0.0
        avg_variance = 0.0
        flaky_all: list[str] = []
        st_count = 0
        for r in reports:
            if r.stability:
                avg_pass_at_1 += r.stability.get("pass_at_1", 0)
                avg_variance += r.stability.get("score_variance", 0)
                flaky_all.extend(r.stability.get("flaky_assertions", []))
                st_count += 1
        if st_count > 0:
            avg_pass_at_1 /= st_count
            avg_variance /= st_count
        stability_summary = {
            "avg_pass_at_1": round(avg_pass_at_1, 4) if st_count else None,
            "avg_score_variance": round(avg_variance, 6) if st_count else None,
            "flaky_assertions": sorted(set(flaky_all)),
            "multi_run_cases": st_count,
        }

    local_as = locals().get('assertion_summary') if 'assertion_summary' in locals() else None
    local_ss = locals().get('stability_summary') if 'stability_summary' in locals() else None

    return SuiteSummary(
        run_id=run_id,
        model=model,
        cases_total=total,
        cases_passed=passed,
        cases_failed=failed,
        cases_judge_failed=judge_failed,
        average_score=round(avg, 4),
        hard_failure_count=hard_failure_count,
        top_failure_categories=top_cats,
        module_scores=module_avgs,
        config=config,
        timestamp="",
        duration_seconds=duration_seconds,
        cache_hits=cache_hits,
        cache_misses=cache_misses,
        skipped_cases=skipped_cases,
        assertion_summary=local_as,
        stability_summary=local_ss,
    )


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def compare_runs(
    baseline_summary: SuiteSummary,
    candidate_summary: SuiteSummary,
    baseline_reports: list[CaseReport],
    candidate_reports: list[CaseReport],
) -> DiffReport:
    """Compare two runs and produce a ``DiffReport``."""
    baseline_map = {r.case_id: r for r in baseline_reports}
    candidate_map = {r.case_id: r for r in candidate_reports}
    all_ids = sorted(set(baseline_map.keys()) | set(candidate_map.keys()))

    entries: list[DiffEntry] = []
    failed_candidates: list[str] = []
    new_hard_failures_by_case: dict[str, list[str]] = {}
    fixed_hard_failures_by_case: dict[str, list[str]] = {}
    regression_notes: list[str] = []

    for case_id in all_ids:
        base = baseline_map.get(case_id)
        cand = candidate_map.get(case_id)

        base_score = _effective_score(base) if base else 0.0
        cand_score = _effective_score(cand) if cand else 0.0
        delta = round(cand_score - base_score, 4)

        base_hf = _hard_failure_ids(base) if base else []
        cand_hf = _hard_failure_ids(cand) if cand else []

        new_hf = [f for f in cand_hf if f not in base_hf]
        fixed_hf = [f for f in base_hf if f not in cand_hf]

        if new_hf:
            new_hard_failures_by_case[case_id] = new_hf
        if fixed_hf:
            fixed_hard_failures_by_case[case_id] = fixed_hf

        if cand and cand.status != CaseStatus.passed:
            failed_candidates.append(case_id)

        entries.append(DiffEntry(
            case_id=case_id,
            baseline_score=base_score,
            candidate_score=cand_score,
            score_delta=delta,
            baseline_hard_failures=base_hf,
            candidate_hard_failures=cand_hf,
            new_hard_failures=new_hf,
            fixed_hard_failures=fixed_hf,
            baseline_status=base.status.value if base else "",
            candidate_status=cand.status.value if cand else "",
        ))

    # Regression gates
    regression_passed = True
    avg_delta = round(candidate_summary.average_score - baseline_summary.average_score, 4)

    if new_hard_failures_by_case:
        regression_notes.append(f"New hard failures in {len(new_hard_failures_by_case)} case(s)")
        regression_passed = False

    if failed_candidates:
        regression_notes.append(f"Candidate has {len(failed_candidates)} failed case(s)")
        regression_passed = False

    if avg_delta < -0.03:
        regression_notes.append(f"Average score dropped by {abs(avg_delta):.3f} (threshold: 0.03)")
        regression_passed = False

    # Core module checks
    for module in ["clarification", "risk", "replan"]:
        base_mod = baseline_summary.module_scores.get(module)
        cand_mod = candidate_summary.module_scores.get(module)
        if base_mod and cand_mod and (cand_mod - base_mod) < -0.05:
            regression_notes.append(
                f"Core module '{module}' score dropped by {abs(cand_mod - base_mod):.3f} (requires manual review)"
            )

    return DiffReport(
        baseline_run_id=baseline_summary.run_id,
        candidate_run_id=candidate_summary.run_id,
        cases_compared=len(entries),
        average_score_delta=avg_delta,
        failed_candidates=failed_candidates,
        new_hard_failures_by_case=new_hard_failures_by_case,
        fixed_hard_failures_by_case=fixed_hard_failures_by_case,
        entries=entries,
        regression_passed=regression_passed,
        regression_notes=regression_notes,
    )


def _effective_score(report: CaseReport) -> float:
    if report.assertion_results:
        return min(report.overall_score, report.weighted_score)
    return report.overall_score


def _counts_toward_quality_score(report: CaseReport) -> bool:
    return report.status not in {CaseStatus.error, CaseStatus.judge_failed}


def _hard_failure_ids(report: CaseReport) -> list[str]:
    hard_failures = list(report.hard_failures)
    if report.semantic_guard:
        for hard_failure in report.semantic_guard.hard_failures:
            semantic_id = f"semantic:{hard_failure}"
            if hard_failure not in hard_failures and semantic_id not in hard_failures:
                hard_failures.append(semantic_id)
    for result in report.assertion_results:
        if result.status == "failed" and result.severity.value == "hard":
            hard_failures.append(f"assertion:{result.assertion_id}")
    return hard_failures
