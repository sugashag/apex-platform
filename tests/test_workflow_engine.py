"""Unit tests for the workflow engine internals — condition evaluation
and template rendering — that don't touch the database."""

from __future__ import annotations

from app.models.workflow_condition import (
    WorkflowCondition,
    WorkflowConditionOperator,
)
from app.services.template_service import render_template, resolve_path
from app.services.workflow_engine import evaluate_condition


def _cond(field: str, op: WorkflowConditionOperator, value: str | None) -> WorkflowCondition:
    cond = WorkflowCondition()
    cond.field = field
    cond.operator = op
    cond.value = value
    cond.position = 0
    return cond


def test_resolve_path_walks_dotted_lookup() -> None:
    ctx = {"contact": {"first_name": "Pat", "company": {"name": "Acme"}}}
    assert resolve_path("contact.first_name", ctx) == "Pat"
    assert resolve_path("contact.company.name", ctx) == "Acme"
    assert resolve_path("contact.missing", ctx) is None
    assert resolve_path("missing.path", ctx) is None


def test_render_template_substitutes_known_vars() -> None:
    ctx = {"contact": {"first_name": "Pat", "email": "pat@example.com"}}
    out = render_template(
        "Hi {{contact.first_name}}, your email is {{contact.email}}.", ctx
    )
    assert out == "Hi Pat, your email is pat@example.com."


def test_render_template_missing_var_renders_empty_string() -> None:
    ctx: dict[str, object] = {}
    assert render_template("Hello {{contact.first_name}}!", ctx) == "Hello !"


def test_render_template_handles_none() -> None:
    assert render_template(None, {}) == ""


def test_evaluate_condition_equals() -> None:
    cond = _cond("contact.source", WorkflowConditionOperator.EQUALS, "google_ads")
    assert evaluate_condition(cond, {"contact": {"source": "google_ads"}}) is True
    assert evaluate_condition(cond, {"contact": {"source": "facebook"}}) is False


def test_evaluate_condition_not_equals() -> None:
    cond = _cond("status", WorkflowConditionOperator.NOT_EQUALS, "closed")
    assert evaluate_condition(cond, {"status": "open"}) is True
    assert evaluate_condition(cond, {"status": "closed"}) is False


def test_evaluate_condition_numeric() -> None:
    gt = _cond("deal.value_cents", WorkflowConditionOperator.GREATER_THAN, "1000")
    lt = _cond("deal.value_cents", WorkflowConditionOperator.LESS_THAN, "1000")
    ctx_big = {"deal": {"value_cents": 5000}}
    ctx_small = {"deal": {"value_cents": 500}}
    assert evaluate_condition(gt, ctx_big) is True
    assert evaluate_condition(gt, ctx_small) is False
    assert evaluate_condition(lt, ctx_big) is False
    assert evaluate_condition(lt, ctx_small) is True


def test_evaluate_condition_contains_and_not_contains() -> None:
    contains = _cond("note", WorkflowConditionOperator.CONTAINS, "urgent")
    not_contains = _cond("note", WorkflowConditionOperator.NOT_CONTAINS, "urgent")
    ctx_yes = {"note": "this is urgent!"}
    ctx_no = {"note": "all good"}
    assert evaluate_condition(contains, ctx_yes) is True
    assert evaluate_condition(contains, ctx_no) is False
    assert evaluate_condition(not_contains, ctx_yes) is False
    assert evaluate_condition(not_contains, ctx_no) is True


def test_evaluate_condition_is_set_and_is_not_set() -> None:
    is_set = _cond("contact.email", WorkflowConditionOperator.IS_SET, None)
    is_not_set = _cond("contact.email", WorkflowConditionOperator.IS_NOT_SET, None)
    assert evaluate_condition(is_set, {"contact": {"email": "a@b.com"}}) is True
    assert evaluate_condition(is_set, {"contact": {"email": ""}}) is False
    assert evaluate_condition(is_set, {"contact": {}}) is False
    assert evaluate_condition(is_not_set, {"contact": {}}) is True
    assert evaluate_condition(is_not_set, {"contact": {"email": "a@b.com"}}) is False
