"""
check_result.py
----------------
Shared three-state result type for grading checks (spec SPEC_v0.2 §7.2, §15.4).

A check that did not run must never look like a check that passed, and must
never look like a check that failed. NOT_EVALUATED is not a synonym for
either other state: it withholds the check's points and forces review.
"""

from __future__ import annotations

from enum import Enum


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_EVALUATED = "not_evaluated"
