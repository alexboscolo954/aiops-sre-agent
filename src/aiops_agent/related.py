"""Related alert groups: when a new Alert group joins an open Triage instead of
starting one (CONTEXT.md). Pure rules; the store finds the candidates."""

from dataclasses import dataclass
from typing import Any

from aiops_agent.contracts import Related
from aiops_agent.models import AlertGroup, Investigation

SEVERITY = {"info": 0, "warning": 1, "error": 2, "high": 2, "critical": 3}


def labels(group: AlertGroup) -> dict[str, str]:
    """What the whole group shares: its common labels, plus any label every firing
    Alert has with the same value."""
    firing = group.firing
    shared = dict(firing[0].labels) if firing else {}
    for a in firing[1:]:
        shared = {k: v for k, v in shared.items() if a.labels.get(k) == v}
    return {**shared, **group.commonLabels}


@dataclass
class Match:
    investigation: Investigation
    matched: dict[str, str]  # the match labels the two share
    louder: bool  # the new group's severity is higher than the Triage's


def find(group: AlertGroup, open_triages: list[Investigation], rules: Related) -> Match | None:
    """The open Triage this group joins, or None. open_triages: the Contract's own,
    already within the window, still firing and not failed. Compared with each
    Triage's own Alert group only. Most shared match labels wins; then the newest."""
    mine, best = labels(group), None
    for t in open_triages:
        if not t.input or t.group_key == group.groupKey:
            continue  # its own group with a new Alert: a new Triage, as before
        theirs = labels(AlertGroup.model_validate(t.input))
        if any(k in mine and k in theirs and mine[k] != theirs[k] for k in rules.scope_labels):
            continue
        matched = {k: mine[k] for k in rules.match_labels if k in mine and mine[k] == theirs.get(k)}
        if not matched:
            continue
        rank = (len(matched), t.started)
        if best is None or rank > best[0]:
            louder = _severity(mine) > _severity(theirs) >= 0
            best = (rank, Match(t, matched, louder))
    return best[1] if best else None


def _severity(group_labels: dict[str, Any]) -> int:
    return SEVERITY.get(str(group_labels.get("severity", "")).lower(), -1)
