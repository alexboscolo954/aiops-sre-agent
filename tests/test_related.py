from typing import Any

from aiops_agent import related
from aiops_agent.contracts import Related
from aiops_agent.models import AlertGroup, Investigation


def group(key: str, severity: str = "warning", **labels: str) -> AlertGroup:
    common = {"alertname": f"A-{key}", "severity": severity, **labels}
    return AlertGroup.model_validate(
        {
            "status": "firing",
            "groupKey": key,
            "commonLabels": common,
            "alerts": [{"status": "firing", "labels": common}],
        }
    )


def triage(key: str, started: float = 100.0, **labels: Any) -> Investigation:
    g = group(key, **labels)
    return Investigation(
        id=f"t-{key}",
        contract_id="acme",
        title=g.title,
        group_key=key,
        started=started,
        input=g.model_dump(mode="json"),
    )


RULES = Related()


def test_a_shared_match_label_in_the_same_scope_joins() -> None:
    open_ = [triage("a", cluster="prod", namespace="shop", service="payments")]
    m = related.find(group("b", cluster="prod", namespace="shop", service="payments"), open_, RULES)
    assert m is not None and m.investigation.id == "t-a" and m.matched == {"service": "payments"}


def test_scope_alone_never_joins_and_a_differing_scope_blocks() -> None:
    open_ = [triage("a", cluster="prod", namespace="shop", service="payments")]
    same_namespace = group("b", cluster="prod", namespace="shop", service="reports")
    assert related.find(same_namespace, open_, RULES) is None
    other_cluster = group("c", cluster="stg", namespace="shop", service="payments")
    assert related.find(other_cluster, open_, RULES) is None


def test_a_scope_label_missing_on_one_side_neither_blocks_nor_matches() -> None:
    """Grafana's alerts often carry no cluster."""
    open_ = [triage("a", cluster="prod", service_name="payments")]
    assert related.find(group("b", service_name="payments"), open_, RULES) is not None


def test_never_its_own_group_nor_a_triage_without_input_nor_with_no_match_labels() -> None:
    open_ = [triage("a", service="payments")]
    assert related.find(group("a", service="payments"), open_, RULES) is None
    old = triage("b", service="payments")
    old.input = None
    assert related.find(group("c", service="payments"), [old], RULES) is None
    assert related.find(group("d", service="payments"), open_, Related(match_labels=[])) is None


def test_most_shared_labels_win_then_the_newest() -> None:
    one = triage("one", started=300.0, service="payments")
    two = triage("two", started=100.0, service="payments", app="pay")
    newer = triage("newer", started=200.0, service="payments", app="pay")
    m = related.find(group("x", service="payments", app="pay"), [one, two, newer], RULES)
    assert m is not None and m.investigation.id == "t-newer"
    assert m.matched == {"service": "payments", "app": "pay"}


def test_a_louder_related_group_is_flagged() -> None:
    open_ = [triage("a", severity="warning", service="payments")]
    critical = related.find(group("b", severity="critical", service="payments"), open_, RULES)
    assert critical is not None and critical.louder
    quieter = related.find(group("c", severity="info", service="payments"), open_, RULES)
    assert quieter is not None and not quieter.louder
    unknown = [triage("d", severity="sev1", service="payments")]
    assert not related.find(
        group("e", severity="critical", service="payments"), unknown, RULES
    ).louder  # type: ignore[union-attr]


def test_labels_are_what_every_firing_alert_shares() -> None:
    g = AlertGroup.model_validate(
        {
            "status": "firing",
            "commonLabels": {"alertname": "X"},
            "alerts": [
                {"status": "firing", "labels": {"service": "payments", "pod": "p1"}},
                {"status": "firing", "labels": {"service": "payments", "pod": "p2"}},
                {"status": "resolved", "labels": {"service": "other"}},
            ],
        }
    )
    assert related.labels(g) == {"service": "payments", "alertname": "X"}
