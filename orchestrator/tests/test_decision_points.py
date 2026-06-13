"""
test_decision_points.py — Story 0.2: decision-point taxonomy tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from programmer.decision_points import DecisionPointKind


class TestDecisionPointKind:
    def test_all_required_kinds_present(self) -> None:
        names = {e.name for e in DecisionPointKind}
        assert "ERROR_REQUIRING_CHOICE" in names
        assert "AMBIGUITY" in names
        assert "COMPLETION" in names
        assert "PERMISSION_REQUEST" in names
        assert "ENGINE_FAILURE" in names

    def test_values_are_strings(self) -> None:
        for kind in DecisionPointKind:
            assert isinstance(kind.value, str), f"{kind.name} value should be str"

    def test_values_are_snake_case(self) -> None:
        for kind in DecisionPointKind:
            assert kind.value == kind.value.lower(), f"{kind.name} value should be lowercase"
            assert " " not in kind.value, f"{kind.name} value should not contain spaces"

    def test_no_duplicate_values(self) -> None:
        values = [e.value for e in DecisionPointKind]
        assert len(values) == len(set(values)), "All DecisionPointKind values must be unique"

    def test_roundtrip_by_value(self) -> None:
        for kind in DecisionPointKind:
            assert DecisionPointKind(kind.value) is kind
