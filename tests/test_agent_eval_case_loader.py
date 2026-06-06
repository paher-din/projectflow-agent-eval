"""Tests for agent_eval case_loader module."""
import json
import tempfile
from pathlib import Path

import pytest

from app.agent_eval.case_loader import CaseLoadError, load_case, load_fixtures, list_fixture_ids
from app.agent_eval.schemas import EvalCase, HardFailRule


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_FIXTURE = {
    "id": "test_case",
    "title": "测试用例",
    "module": "clarification",
    "entrypoint": "clarify",
    "workspace_state": {
        "workspace_id": "ws-1",
        "workspace_name": "Test",
        "current_date": "2026-06-05",
        "current_datetime": "2026-06-05T10:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "members": [
            {
                "user_id": "user-1",
                "display_name": "测试用户",
                "skills": ["backend"],
                "available_hours_per_week": 10,
                "role_preference": "backend",
                "interests": "开发",
                "constraints": "",
            }
        ],
        "project": None,
    },
    "expected_behavior": ["测试行为"],
    "forbidden_behavior": ["禁止行为"],
    "rubric_weights": {
        "context_grounding": 0.5,
        "mvp_boundary": 0.3,
        "actionability": 0.2,
    },
    "minimum_score": 0.8,
    "hard_fail_rules": ["invalid_schema", "fabricated_workspace_entity"],
}


@pytest.fixture
def tmp_fixtures_dir():
    """Create a temporary directory with sample fixture files."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        # Valid fixture
        (d / "test_case.json").write_text(json.dumps(SAMPLE_FIXTURE), encoding="utf-8")
        # Second valid fixture
        second = dict(SAMPLE_FIXTURE)
        second["id"] = "test_case_2"
        second["rubric_weights"] = {"context_grounding": 0.4, "mvp_boundary": 0.3, "actionability": 0.2, "reliability": 0.1}
        (d / "test_case_2.json").write_text(json.dumps(second), encoding="utf-8")
        yield d


@pytest.fixture
def tmp_empty_dir():
    """Create an empty directory."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


# ---------------------------------------------------------------------------
# Tests for load_case
# ---------------------------------------------------------------------------


class TestLoadCase:
    def test_load_valid_case(self, tmp_fixtures_dir):
        case = load_case(tmp_fixtures_dir / "test_case.json")
        assert isinstance(case, EvalCase)
        assert case.id == "test_case"
        assert case.module == "clarification"
        assert case.minimum_score == 0.8
        assert HardFailRule.invalid_schema in case.hard_fail_rules

    def test_load_nonexistent_file(self):
        with pytest.raises(CaseLoadError, match="not found"):
            load_case("/nonexistent/path.json")

    def test_load_non_json_file(self, tmp_fixtures_dir):
        f = tmp_fixtures_dir / "test.txt"
        f.write_text("{}")
        with pytest.raises(CaseLoadError, match="must be a .json file"):
            load_case(f)

    def test_load_invalid_json(self, tmp_fixtures_dir):
        f = tmp_fixtures_dir / "bad.json"
        f.write_text("{invalid json}", encoding="utf-8")
        with pytest.raises(CaseLoadError, match="Invalid JSON"):
            load_case(f)

    def test_load_missing_required_field(self, tmp_fixtures_dir):
        data = dict(SAMPLE_FIXTURE)
        del data["id"]
        f = tmp_fixtures_dir / "missing_id.json"
        f.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(CaseLoadError, match="Validation error"):
            load_case(f)

    def test_load_case_with_empty_string_id(self, tmp_fixtures_dir):
        data = dict(SAMPLE_FIXTURE)
        data["id"] = ""
        f = tmp_fixtures_dir / "empty_id.json"
        f.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(CaseLoadError, match="Validation error"):
            load_case(f)


# ---------------------------------------------------------------------------
# Tests for load_fixtures
# ---------------------------------------------------------------------------


class TestLoadFixtures:
    def test_load_all_fixtures(self, tmp_fixtures_dir):
        cases = load_fixtures(tmp_fixtures_dir)
        assert len(cases) == 2
        assert cases[0].id == "test_case"
        assert cases[1].id == "test_case_2"

    def test_load_fixtures_missing_dir(self, tmp_empty_dir):
        with pytest.raises(CaseLoadError, match="not found"):
            load_fixtures(tmp_empty_dir / "nonexistent")

    def test_load_fixtures_no_json_files(self, tmp_empty_dir):
        with pytest.raises(CaseLoadError, match="No .json fixture files"):
            load_fixtures(tmp_empty_dir)

    def test_load_fixtures_duplicate_ids(self, tmp_fixtures_dir):
        # Add a file with duplicate ID
        data = dict(SAMPLE_FIXTURE)
        data["id"] = "test_case"  # duplicate
        (tmp_fixtures_dir / "dup.json").write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(CaseLoadError, match="Duplicate case IDs"):
            load_fixtures(tmp_fixtures_dir)

    def test_load_fixtures_with_validation_error(self, tmp_fixtures_dir):
        # Add a broken fixture
        (tmp_fixtures_dir / "bad.json").write_text("{invalid}", encoding="utf-8")
        with pytest.raises(CaseLoadError, match="Failed to load"):
            load_fixtures(tmp_fixtures_dir)

    def test_real_fixtures_directory(self):
        """Load the actual fixture directory to verify all 12 fixtures load."""
        fixtures_dir = Path(__file__).resolve().parent.parent / "app" / "agent_eval" / "fixtures"
        if not fixtures_dir.exists():
            pytest.skip("Fixtures directory not found")
        cases = load_fixtures(fixtures_dir)
        assert len(cases) == 12
        assert cases[0].id < cases[-1].id  # sorted


# ---------------------------------------------------------------------------
# Tests for RubricWeights validation
# ---------------------------------------------------------------------------


class TestRubricWeights:
    def test_weights_must_sum_to_one(self):
        """Rubric weights that don't sum to 1.0 should fail."""
        from app.agent_eval.schemas import RubricWeights

        with pytest.raises(ValueError, match="must sum to 1.0"):
            RubricWeights(
                context_grounding=0.5,
                mvp_boundary=0.5,
                actionability=0.5,  # over
            )

    def test_weights_all_zero_ok(self):
        """All zero weights should not raise (edge case for partial config)."""
        from app.agent_eval.schemas import RubricWeights

        rw = RubricWeights()
        assert rw.active_dimensions() == {}

    def test_active_dimensions(self):
        from app.agent_eval.schemas import RubricWeights

        rw = RubricWeights(context_grounding=0.5, mvp_boundary=0.3, actionability=0.2)
        active = rw.active_dimensions()
        assert set(active.keys()) == {"context_grounding", "mvp_boundary", "actionability"}
        assert abs(sum(active.values()) - 1.0) < 0.01


# ---------------------------------------------------------------------------
# Tests for list_fixture_ids
# ---------------------------------------------------------------------------


class TestListFixtureIds:
    def test_list_ids(self, tmp_fixtures_dir):
        ids = list_fixture_ids(tmp_fixtures_dir)
        assert ids == ["test_case", "test_case_2"]

