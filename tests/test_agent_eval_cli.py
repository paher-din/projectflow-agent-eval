"""Tests for the AgentEval CLI modules."""

import json
from pathlib import Path

import pytest

from app.agent_eval.cli import main
import app.agent_eval.commands.compare as compare_commands
from app.agent_eval.commands.cases import show_case, list_cases
from app.agent_eval.commands.common import CommandError, load_json_file, resolve_run_dir
from app.agent_eval.commands.diagnose import diagnose_run
from app.agent_eval.commands.reports import show_report
import app.agent_eval.commands.runs as run_commands


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


def test_cli_legacy_runner_arguments_still_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_runner_main(argv: list[str] | None = None) -> int:
        captured["argv"] = argv
        return 0

    monkeypatch.setattr("app.agent_eval.runner.main", fake_runner_main)

    exit_code = main(["run", "--mode", "mock", "--model", "stub"])

    assert exit_code == 0
    assert captured["argv"] == ["run", "--mode", "mock", "--model", "stub"]


def _write_minimal_run(run_dir: Path) -> None:
    run_dir.mkdir(parents=True)
    (run_dir / "suite_summary.json").write_text(
        json.dumps({
            "run_id": "run-1",
            "model": "stub",
            "cases_total": 1,
            "cases_passed": 0,
            "cases_failed": 1,
            "cases_judge_failed": 0,
            "average_score": 0.42,
            "hard_failure_count": 1,
            "top_failure_categories": ["scope_creep"],
        }),
        encoding="utf-8",
    )
    (run_dir / "case_one.report.json").write_text(
        json.dumps({
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
        }),
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
    monkeypatch.setattr(
        compare_commands, "compare_runs_command", lambda baseline_ref, candidate_ref, output_dir=None: 0
    )

    assert main(["compare", str(baseline), str(candidate)]) == 0


def test_cli_config_path_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.agent_eval.commands.config as config_commands
    monkeypatch.setattr(config_commands, "config_path_command", lambda **kwargs: 0)

    assert main(["config", "path"]) == 0


def test_cli_config_init_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.agent_eval.commands.config as config_commands
    monkeypatch.setattr(config_commands, "config_init", lambda **kwargs: 0)

    assert main(["config", "init"]) == 0


def test_cli_config_show_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.agent_eval.commands.config as config_commands
    monkeypatch.setattr(config_commands, "config_show", lambda **kwargs: 0)

    assert main(["config", "show"]) == 0


def test_run_real_ensures_config_before_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    import app.agent_eval.commands.config as config_commands
    monkeypatch.setattr(config_commands, "ensure_real_config", lambda **kwargs: calls.append("config"))

    def fake_run_suite(fixtures: str, **kwargs: object) -> tuple[list[object], object]:
        calls.append("run")

        class Summary:
            run_id = "run-1"
            model = "model"
            cases_passed = 1
            cases_total = 1
            average_score = 1.0
            hard_failure_count = 0
            duration_seconds = 0.1
            cases_failed = 0
            cases_judge_failed = 0

        return [], Summary()

    monkeypatch.setattr(run_commands, "run_suite", fake_run_suite)

    assert run_commands.run_benchmark("real") == 0
    assert calls == ["config", "run"]


def test_cli_config_agent_use_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.agent_eval.commands.config as config_commands
    monkeypatch.setattr(config_commands, "config_agent_use", lambda name, **kwargs: 0)

    assert main(["config", "agent", "use", "agent-main"]) == 0


def test_cli_config_agent_add_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.agent_eval.commands.config as config_commands
    monkeypatch.setattr(config_commands, "config_agent_add", lambda name, **kwargs: 0)

    assert main(["config", "agent", "add", "agent-new"]) == 0


def test_cli_config_agent_list_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.agent_eval.commands.config as config_commands
    monkeypatch.setattr(config_commands, "config_agent_list", lambda config=None: 0)

    assert main(["config", "agent", "list"]) == 0


def test_cli_config_agent_show_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.agent_eval.commands.config as config_commands
    monkeypatch.setattr(config_commands, "config_agent_show", lambda name, config=None: 0)

    assert main(["config", "agent", "show", "agent-main"]) == 0


def test_cli_config_judge_use_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.agent_eval.commands.config as config_commands
    monkeypatch.setattr(config_commands, "config_judge_use", lambda name, **kwargs: 0)

    assert main(["config", "judge", "use", "judge-main"]) == 0


def test_cli_config_judge_add_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.agent_eval.commands.config as config_commands
    monkeypatch.setattr(config_commands, "config_judge_add", lambda name, **kwargs: 0)

    assert main(["config", "judge", "add", "judge-new"]) == 0


def test_cli_config_judge_list_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.agent_eval.commands.config as config_commands
    monkeypatch.setattr(config_commands, "config_judge_list", lambda config=None: 0)

    assert main(["config", "judge", "list"]) == 0


def test_cli_config_judge_show_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.agent_eval.commands.config as config_commands
    monkeypatch.setattr(config_commands, "config_judge_show", lambda name, config=None: 0)

    assert main(["config", "judge", "show", "judge-main"]) == 0
