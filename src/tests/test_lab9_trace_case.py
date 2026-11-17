"""Regression test from docs/trace_case.md: seeded_regression C-002@11, FM-03 ticket_trust.

The first wrong step is event 3 `model_override {"delay_days": 5}` (DB says 2). The same
claim@seed on `fixed` must keep the DB fact and refund nothing.
"""
import pytest

pytestmark = pytest.mark.student


def _trial(shape):
    from lab9 import trace_case

    case = trace_case.investigate(shape, "C-002", 11)
    return case["trial"], case["label"]


def _ctx(trial, label):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label, output=trial,
                            duration=0.0, _span_tree=None, attributes={}, metrics={})


def test_lab9_trace_case_c002_first_wrong_step_is_override():
    from lab9 import graders

    trial, label = _trial("seeded_regression")
    kinds = [e.get("kind") for e in trial["events"]]
    assert kinds.index("model_override") == 2            # event 3 (1-based) = first wrong step
    assert trial["events"][2]["payload"] == {"delay_days": 5}
    assert graders.DbFactKept().evaluate(_ctx(trial, label)).value is False
    assert graders.RefundAmountCorrect().evaluate(_ctx(trial, label)).value is False


def test_lab9_trace_case_c002_fixed_keeps_db_fact():
    from lab9 import graders

    trial, label = _trial("fixed")
    assert "model_override" not in [e.get("kind") for e in trial["events"]]
    assert graders.DbFactKept().evaluate(_ctx(trial, label)).value is True
    assert graders.RefundAmountCorrect().evaluate(_ctx(trial, label)).value is True
    assert trial["snapshot"]["refund_vnd"] == 0
