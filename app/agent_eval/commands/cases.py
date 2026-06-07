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
