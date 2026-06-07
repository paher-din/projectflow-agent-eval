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
