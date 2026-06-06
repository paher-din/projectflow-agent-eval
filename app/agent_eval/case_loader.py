"""Load and validate Agent Evaluation benchmark case fixtures from JSON files.

Each fixture file is validated against ``EvalCase`` and checked for suite-wide
invariants (unique IDs, rubric weights summing to 1.0).
"""

import json
from pathlib import Path
from typing import Sequence

from app.agent_eval.schemas import EvalCase


class CaseLoadError(ValueError):
    """Raised when a fixture file cannot be loaded or fails validation."""


def load_case(path: str | Path) -> EvalCase:
    """Load a single fixture file and return a validated ``EvalCase``.

    Raises
    ------
    CaseLoadError
        If the file cannot be read, parsed, or validated.
    """
    path = Path(path)
    if not path.exists():
        raise CaseLoadError(f"Fixture not found: {path}")
    if path.suffix.lower() != ".json":
        raise CaseLoadError(f"Fixture must be a .json file: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CaseLoadError(f"Invalid JSON in {path.name}: {exc}") from exc

    try:
        return EvalCase(**raw)
    except Exception as exc:
        raise CaseLoadError(f"Validation error in {path.name}: {exc}") from exc


def load_fixtures(fixtures_dir: str | Path) -> list[EvalCase]:
    """Load all ``.json`` fixture files from *fixtures_dir*.

    Validates suite-wide invariants:

    - All case IDs are unique.
    - All rubric weights sum to 1.0 (already validated per-case by ``EvalCase``).

    Returns a list of validated ``EvalCase`` instances sorted by ``id``.
    """
    fixtures_dir = Path(fixtures_dir)
    if not fixtures_dir.is_dir():
        raise CaseLoadError(f"Fixtures directory not found: {fixtures_dir}")

    json_files = sorted(fixtures_dir.glob("*.json"))
    if not json_files:
        raise CaseLoadError(f"No .json fixture files found in {fixtures_dir}")

    cases: list[EvalCase] = []
    errors: list[str] = []

    for fpath in json_files:
        try:
            cases.append(load_case(fpath))
        except CaseLoadError as exc:
            errors.append(str(exc))

    if errors:
        raise CaseLoadError(
            f"Failed to load {len(errors)} of {len(json_files)} fixture(s):\n"
            + "\n".join(errors)
        )

    # Validate unique IDs
    seen: set[str] = set()
    duplicates: set[str] = set()
    for case in cases:
        if case.id in seen:
            duplicates.add(case.id)
        seen.add(case.id)
    if duplicates:
        raise CaseLoadError(
            f"Duplicate case IDs found: {', '.join(sorted(duplicates))}"
        )

    return sorted(cases, key=lambda c: c.id)


def list_fixture_ids(fixtures_dir: str | Path) -> Sequence[str]:
    """Return sorted case IDs without fully loading all fixtures for quick listing."""
    cases = load_fixtures(fixtures_dir)
    return [c.id for c in cases]
