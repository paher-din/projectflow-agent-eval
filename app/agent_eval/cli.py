from __future__ import annotations

import argparse
import sys

from app.agent_eval.commands.cases import list_cases, show_case
from app.agent_eval.commands.common import CommandError
from app.agent_eval.runner import DEFAULT_CACHE_DIR


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ProjectFlow AgentEval Toolkit")
    sub = parser.add_subparsers(dest="command")

    # case
    case_parser = sub.add_parser("case", help="Inspect benchmark cases")
    case_sub = case_parser.add_subparsers(dest="case_command")
    case_list = case_sub.add_parser("list", help="List fixture IDs")
    case_list.add_argument("--fixtures", default="app/agent_eval/fixtures")
    case_show = case_sub.add_parser("show", help="Show one fixture")
    case_show.add_argument("case_id")
    case_show.add_argument("--fixtures", default="app/agent_eval/fixtures")

    # run
    run_parser = sub.add_parser("run", help="Run benchmark suites")
    run_sub = run_parser.add_subparsers(dest="run_command")
    for name in ("mock", "real"):
        item = run_sub.add_parser(name, help=f"Run benchmark in {name} mode")
        _add_run_options(item)
    for name in ("resume", "retry-failed", "retry-errors"):
        item = run_sub.add_parser(name, help=f"Run benchmark with {name}")
        item.add_argument("run_ref", nargs="?", default="latest")
        _add_run_options(item)

    # report
    report_parser = sub.add_parser("report", help="Read benchmark reports")
    report_sub = report_parser.add_subparsers(dest="report_command")
    report_latest = report_sub.add_parser("latest", help="Show latest report")
    report_latest.set_defaults(run_ref="latest")
    report_show = report_sub.add_parser("show", help="Show report directory")
    report_show.add_argument("run_ref")

    # diagnose
    diagnose_parser = sub.add_parser("diagnose", help="Diagnose benchmark failures")
    diagnose_parser.add_argument("run_ref", nargs="?", default="latest")

    # compare
    compare_parser = sub.add_parser("compare", help="Compare two benchmark runs")
    compare_parser.add_argument("baseline")
    compare_parser.add_argument("candidate")
    compare_parser.add_argument("--output-dir", default=None)

    # config
    config_parser = sub.add_parser("config", help="Manage real-mode LLM config")
    config_sub = config_parser.add_subparsers(dest="config_command")
    config_sub.add_parser("init", help="Create or overwrite user config")
    config_sub.add_parser("show", help="Show masked user config")
    config_sub.add_parser("path", help="Show user config path")

    return parser


def _add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--fixtures", default="app/agent_eval/fixtures")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--runs-per-case", type=int, default=1)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--judge-mode", default="auto", choices=["auto", "llm", "stub"]
    )
    parser.add_argument(
        "--semantic-guard",
        default="auto",
        choices=["off", "auto", "required"],
    )
    parser.add_argument("--semantic-judge-model", default="")
    parser.add_argument("--semantic-judge-base-url", default="")
    parser.add_argument("--case-filter", default="")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--no-cache", action="store_true")


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "case" and args.case_command == "list":
        return list_cases(args.fixtures)
    if args.command == "case" and args.case_command == "show":
        return show_case(args.case_id, args.fixtures)
    if args.command == "run" and args.run_command:
        from app.agent_eval.commands.runs import run_benchmark

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
    if args.command == "report" and args.report_command:
        from app.agent_eval.commands.reports import show_report

        return show_report(args.run_ref)
    if args.command == "diagnose":
        from app.agent_eval.commands.diagnose import diagnose_run

        return diagnose_run(args.run_ref)
    if args.command == "compare":
        from app.agent_eval.commands.compare import compare_runs_command

        return compare_runs_command(
            args.baseline, args.candidate, output_dir=args.output_dir
        )
    if args.command == "config" and args.config_command:
        from app.agent_eval.commands import config as config_commands

        if args.config_command == "init":
            return config_commands.config_init()
        if args.config_command == "show":
            return config_commands.config_show()
        if args.config_command == "path":
            return config_commands.config_path_command()
    raise CommandError("No command selected. Run `pfae --help`.")


def _is_legacy_runner_invocation(argv: list[str]) -> bool:
    if not argv:
        return False
    if argv[0] == "list-fixtures":
        return True
    return argv[0] == "run" and (len(argv) == 1 or argv[1].startswith("--"))


def main(argv: list[str] | None = None) -> int:
    selected_argv = list(sys.argv[1:] if argv is None else argv)
    if _is_legacy_runner_invocation(selected_argv):
        from app.agent_eval.runner import main as runner_main

        return runner_main(selected_argv)

    parser = _build_parser()
    args = parser.parse_args(selected_argv)
    try:
        return _dispatch(args)
    except CommandError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
