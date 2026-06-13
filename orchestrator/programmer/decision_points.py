"""
decision_points.py — Decision-point taxonomy for YANA programmer mode.

Defines what surfaces to Fred vs. stays in the engine layer.

Decision points (surface to Fred):
  Any EngineEvent where kind is a DecisionPointKind value requires Fred's input.

Technical noise (never surfaces unless Fred explicitly asks via /show-output):
  Build logs, test runner stdout/stderr, compiler output, linter output,
  git operation confirmations, progress indicators.
"""

from __future__ import annotations

from enum import Enum


class DecisionPointKind(Enum):
    """Categories of engine output that require Fred's attention."""

    ERROR_REQUIRING_CHOICE = "error_requiring_choice"
    # Engine hit an error where the correct action is ambiguous.
    # Examples: "file already exists — overwrite?", "test failed — fix or skip?",
    # "merge conflict — which version to keep?"

    AMBIGUITY = "ambiguity"
    # Engine encountered underspecification mid-task that was not caught at clarification time.
    # Examples: "which authentication strategy?", "should this be async or sync?"

    COMPLETION = "completion"
    # Task finished successfully. Fred decides what to do next.

    PERMISSION_REQUEST = "permission_request"
    # Engine needs explicit approval before proceeding with a state-changing action.
    # Examples: "about to push branch X — confirm?", "about to open PR — confirm?"

    ENGINE_FAILURE = "engine_failure"
    # Unrecoverable engine error. Fred decides whether to retry, inspect, or abandon.
    # Examples: engine process died, SDK authentication failure, timeout.
