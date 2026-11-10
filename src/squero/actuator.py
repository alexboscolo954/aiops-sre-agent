"""The Actuator (slice 12.1): applies the Hub's Approved Sizings inside a client's cluster.

It runs in that cluster with its own token, bound to one Contract's cluster, and RBAC that
can resize pods but never edit a Deployment (which could change its image). Every minute
it pulls its desired state from the Hub, resizes the pods of each new Approved Sizing's
Deployment in place (Kubernetes 1.33+), keeps what it did in one ConfigMap so a restart
applies nothing twice, writes an Event on the Deployment and reports each outcome (an
Actuation) to the Hub. The Hub decides and never pushes; a Kill switch reaches it as no
Sizings at all.

What it applied it holds (slice 12.2): its pod-creation webhook gives a new pod of that
Deployment the same requests (it fails open: with the Actuator down, pods start from their
template), until a person changes the template's requests, which hands the container back.

Before a resize (slice 12.3) it checks what would refuse or fight it: a pod's QoS class, a
VPA, an HPA on a resource's utilization, the namespace's LimitRange and ResourceQuota. Then
it resizes one canary pod, watches it 10 minutes, and the others one at a time, each until
the kubelet allocated it and the pod is Ready; an Infeasible resize, or one not done in 10
minutes, stops it there. Deployments only.

Under Automation (slice 12.5) it also applies, unasked, the newest Sizing of each container
the Contract automates: a change under 10% ignored, an increase at once, a decrease at most
once a day. A Deployment a person annotated `squero-actuator/pause: "true"` is left alone,
as under the Kill switch. While the Hub is unreachable it changes nothing new, and says so
in an Event after 15 minutes.
"""

import base64
import json
import logging
import math
import re
import ssl
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.utils.quantity import parse_quantity
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("squero.actuator")

CONFIGMAP = "squero-actuator"  # in its own namespace: what it applied, by container
KEY = "applied.json"
MAX_REPORTS = 1000  # per POST, and kept unsent while the Hub is unreachable
MIN_MINOR = 33  # Kubernetes 1.33: in-place pod resize on by default
MI = 2**20
WEBHOOK = "squero-actuator"  # its MutatingWebhookConfiguration and its Service, by name
WEBHOOK_PORT = 8443
MAX_REVIEW = 1024 * 1024  # bytes: an AdmissionReview of one pod is far smaller
CANARY_SECONDS = 600  # the first pod resized is watched this long before the others
WAIT_SECONDS = 600  # how long one pod's resize may take, Deferred included
WATCH_SECONDS = 3600  # resized pods are watched this long for a rollback (slice 12.4)
NOT_READY_SECONDS = 120  # a resized pod NotReady this long is a reason to roll back
BACKOFF_SECONDS = 86400  # after a rollback, no new Sizing of that container this long, doubling
ROLLBACKS_FOR = 7 * 86400  # how far back rollbacks count for the doubling
CHURN = Decimal("0.10")  # under Automation, a change smaller than this is ignored (slice 12.5)
LOWER_EVERY = 86400  # under Automation, a container's requests go down at most this often
UNREACHABLE_SECONDS = 900  # the Hub unanswered this long: an Event says so
PAUSE = "squero-actuator/pause"  # a Deployment annotated "true" is left alone
ROLLOUT = ("pod", "since", "canary_until", "resized", "notes")  # held while rolling
WATCHED = ("pods", "watch_until")  # held while watched
Outcome = Literal["applied", "skipped", "failed", "handed_back", "rolled_back"]  # also "rolling"


class ActuatorSettings(BaseSettings):
    """The Actuator's own configuration, set by the client in its manifest. No field may
    be named like a Service link (`port`, `service_host`): see RelaySettings."""

    model_config = SettingsConfigDict(env_prefix="SQUERO_ACTUATOR_")

    hub: str  # https://<the Hub's domain>
    token: SecretStr
    namespace: str  # its own, where its ConfigMap lives (the manifest's downward API)
    interval: float = 60


class Wanted(BaseModel):
    """One current Approved Sizing, as the Hub sends it: cores and bytes, None to leave."""

    model_config = ConfigDict(extra="ignore")

    run_id: int
    namespace: str
    kind: str
    name: str
    container: str
    cpu: float | None
    memory: float | None


class Desired(BaseModel):
    kill_switch: bool
    sizings: list[Wanted]  # Approved Sizings
    # Automation's (slice 12.5): a list of their own, so an older Actuator never applies them
    # as if approved, without the churn rule or the pause annotation
    automated: list[Wanted] = []


class Actuation(BaseModel):
    """What the Actuator did with one Approved Sizing: the requests it set, on how many pods."""

    model_config = ConfigDict(extra="forbid")

    namespace: str = Field(max_length=253)
    kind: str = Field(max_length=63)
    name: str = Field(max_length=253)
    container: str = Field(max_length=253)
    run_id: int
    outcome: Outcome
    cpu: float | None = None
    memory: float | None = None
    pods: int = Field(ge=0)
    reason: str = Field(max_length=1000)
    at: float


def qty(q: str) -> Decimal:
    return parse_quantity(q)  # type: ignore[no-untyped-call,no-any-return]


def cpu_text(cores: float) -> str:
    return f"{math.ceil(round(cores * 1000, 6))}m"


def memory_text(b: float) -> str:
    return f"{math.ceil(round(b / MI, 6))}Mi"


def same(a: str | None, b: str | None) -> bool:
    """Two requests as quantities (`0.1` is `100m`); unset is only ever unset."""
    return a == b if a is None or b is None else qty(a) == qty(b)


def why(e: ApiException) -> str:
    """The API server's own message, short: never more than it said."""
    try:
        message = json.loads(e.body or "{}").get("message") or e.reason
    except (ValueError, AttributeError):
        message = e.reason
    return f"{e.status}: {message}"[:300]


def pods_of(core: Any, apps: Any, d: Any) -> list[Any]:
    """The Deployment's live pods: those of its own ReplicaSets, however its selector reads."""
    ns = d.metadata.namespace
    labels = ",".join(f"{k}={v}" for k, v in sorted((d.spec.selector.match_labels or {}).items()))
    mine = {
        rs.metadata.name
        for rs in apps.list_namespaced_replica_set(ns, label_selector=labels).items
        if any(o.uid == d.metadata.uid for o in rs.metadata.owner_references or [])
    }
    return [
        p
        for p in core.list_namespaced_pod(ns, label_selector=labels).items
        if any(o.kind == "ReplicaSet" and o.name in mine for o in p.metadata.owner_references or [])
        and p.status.phase not in ("Succeeded", "Failed")
        and not p.metadata.deletion_timestamp
    ]


def requests_of(c: Any) -> dict[str, str]:
    return dict((c.resources.requests if c and c.resources else None) or {})


def limits_of(c: Any) -> dict[str, str]:
    return dict((c.resources.limits if c and c.resources else None) or {})


def qos(containers: list[tuple[dict[str, str], dict[str, str]]]) -> str:
    """A pod's QoS class from its containers' (requests, limits). Kubernetes refuses a
    resize that changes it. ponytail: init containers left out; add them if one matters."""
    if all(not r and not lim for r, lim in containers):
        return "BestEffort"
    guaranteed = all(
        all(res in lim and same(r.get(res, lim[res]), lim[res]) for res in ("cpu", "memory"))
        for r, lim in containers
    )
    return "Guaranteed" if guaranteed else "Burstable"


def qos_change(
    containers: list[tuple[str, dict[str, str], dict[str, str]]], name: str, set_to: dict[str, str]
) -> str | None:
    """Why setting `name`'s requests to `set_to` would change the pod's QoS class, or None."""
    before = [(r, lim) for _, r, lim in containers]
    after = [({**r, **set_to} if n == name else r, lim) for n, r, lim in containers]
    was, would = qos(before), qos(after)
    if was == would:
        return None
    if was == "Guaranteed":
        return "it is Guaranteed: its limits must change too"
    return f"it would turn its pods from {was} to {would}"


def vpa_mode(custom: Any, ns: str, name: str) -> str | None:
    """The mode of a VPA that changes this Deployment's pods, or None (none, or `Off`)."""
    try:
        found = custom.list_namespaced_custom_object(
            "autoscaling.k8s.io", "v1", ns, "verticalpodautoscalers"
        )
    except ApiException as e:
        if e.status == 404:  # no VPA installed
            return None
        raise
    for v in found.get("items") or []:
        spec = v.get("spec") or {}
        ref = spec.get("targetRef") or {}
        if ref.get("kind") == "Deployment" and ref.get("name") == name:
            mode = (spec.get("updatePolicy") or {}).get("updateMode") or "Auto"
            if mode != "Off":
                return str(mode)
    return None


def hpa_resources(autoscaling: Any, ns: str, name: str, container: str) -> set[str]:
    """The resources an HPA of this Deployment scales on by utilization: a request it
    divides by, so the Actuator leaves it alone. An HPA without metrics means cpu."""
    out: set[str] = set()
    for h in autoscaling.list_namespaced_horizontal_pod_autoscaler(ns).items:
        ref = h.spec.scale_target_ref
        if ref.kind != "Deployment" or ref.name != name:
            continue
        if not h.spec.metrics:
            out.add("cpu")
        for m in h.spec.metrics or []:
            if m.type == "Resource" and m.resource.target.type == "Utilization":
                out.add(m.resource.name)
            if (
                m.type == "ContainerResource"
                and m.container_resource.container == container
                and m.container_resource.target.type == "Utilization"
            ):
                out.add(m.container_resource.name)
    return out


def limit_range_breach(
    core: Any, ns: str, set_to: dict[str, str], limits: dict[str, str]
) -> str | None:
    """Why the namespace's LimitRange would refuse these requests, or None. Never clamped."""
    for lr in core.list_namespaced_limit_range(ns).items:
        for item in lr.spec.limits or []:
            if item.type != "Container":
                continue
            for r, q in set_to.items():
                low, high = (item.min or {}).get(r), (item.max or {}).get(r)
                ratio = (item.max_limit_request_ratio or {}).get(r)
                if low and qty(q) < qty(low):
                    return f"{r} {q} is under its LimitRange's minimum {low}"
                if high and qty(q) > qty(high):
                    return f"{r} {q} is over its LimitRange's maximum {high}"
                if ratio and r in limits and qty(limits[r]) / qty(q) > qty(ratio):
                    return f"{r} {q} under limit {limits[r]} passes its LimitRange's ratio {ratio}"
    return None


def quota_breach(
    core: Any, ns: str, set_to: dict[str, str], now: dict[str, str], pods: int
) -> str | None:
    """Why raising requests on `pods` pods would pass a ResourceQuota, or None."""
    for rq in core.list_namespaced_resource_quota(ns).items:
        hard, used = (rq.status.hard or {}), (rq.status.used or {})
        for r, q in set_to.items():
            more = (qty(q) - qty(now.get(r) or "0")) * pods
            for key in (f"requests.{r}", r):
                if more > 0 and key in hard and qty(used.get(key) or "0") + more > qty(hard[key]):
                    quota = f"ResourceQuota {rq.metadata.name}'s {key} {hard[key]}"
                    return f"{pods} pods at {r} {q} would pass {quota}"
    return None


def resize_state(pod: Any, container: str, set_to: dict[str, str]) -> tuple[str, str]:
    """Where a pod's resize is: done (allocated, and the pod Ready), waiting, deferred or
    infeasible (the kubelet's word, Kubernetes 1.33+), with its message."""
    conditions = pod.status.conditions or []
    for c in conditions:
        if c.type == "PodResizePending" and c.status == "True":
            state = "infeasible" if (c.reason or "").lower() == "infeasible" else "deferred"
            return state, c.message or ""
        if c.type == "PodResizeInProgress" and c.status == "True":
            return "waiting", "in progress"
    st = next((s for s in pod.status.container_statuses or [] if s.name == container), None)
    allocated = (st.resources.requests if st and st.resources else None) or {}
    if not all(same(allocated.get(r), q) for r, q in set_to.items()):
        return "waiting", "not yet allocated"
    if not any(c.type == "Ready" and c.status == "True" for c in conditions):
        return "waiting", "not Ready"
    return "done", ""


def resize(core: Any, pod: Any, container: str, set_to: dict[str, str]) -> None:
    body = {"spec": {"containers": [{"name": container, "resources": {"requests": set_to}}]}}
    core.patch_namespaced_pod_resize(pod.metadata.name, pod.metadata.namespace, body)


def needs(pod: Any, container: str, set_to: dict[str, str]) -> bool:
    c = next((c for c in pod.spec.containers if c.name == container), None)
    now = requests_of(c)
    return not all(same(now.get(r), q) for r, q in set_to.items())


def apply(
    core: Any,
    apps: Any,
    w: Wanted,
    at: float,
    autoscaling: Any,
    custom: Any,
    old: dict[str, Any] | None = None,
    automated: bool = False,
) -> tuple[Actuation | None, dict[str, Any]]:
    """Start resizing `w`'s container in place on its Deployment's pods (slice 12.3): the
    pre-checks, then one canary pod. An Actuation when it ends here (skipped or failed),
    None while it rolls; and what to remember of it, empty when Automation's churn rule
    leaves nothing to change. `old`: the hold a new Sizing replaces (None: catching up)."""
    set_to: dict[str, str] = {}
    template_had: dict[str, str | None] = {}  # its template's requests then: a change hands back
    notes: list[str] = []

    def done(outcome: Outcome, pods: int, reason: str) -> tuple[Actuation, dict[str, Any]]:
        values = {r: float(qty(q)) for r, q in set_to.items()}
        a = Actuation(
            **w.model_dump(exclude={"cpu", "memory"}),
            outcome=outcome,
            pods=pods,
            reason=(reason + "".join(notes))[:1000],
            at=at,
            **values,
        )
        kept = {"requests": set_to, "template": template_had}
        return a, {"run_id": w.run_id, "outcome": outcome, **kept, "at": at}

    try:
        d = apps.read_namespaced_deployment(w.name, w.namespace)
    except ApiException as e:
        if e.status == 404:
            return done("skipped", 0, "no such Deployment")
        return done("failed", 0, f"reading the Deployment: {why(e)}")
    containers = d.spec.template.spec.containers
    template = next((c for c in containers if c.name == w.container), None)
    if template is None:
        return done("skipped", 0, f"no container {w.container!r} in its template")
    limits, asked = limits_of(template), requests_of(template)
    capped = []
    for res, value, text in (("cpu", w.cpu, cpu_text), ("memory", w.memory, memory_text)):
        if value is None:
            continue
        q = text(value)
        if res in limits and qty(q) > qty(limits[res]):
            q = limits[res]  # requests never above the limit: the Sizing's risk stays shown
            capped.append(res)
        set_to[res] = q
        template_had[res] = asked.get(res)
    if capped:
        notes.append(f"; capped at its limit: {capped}")
    kept = old if old and old.get("outcome") in ("applied", "rolling") else {}
    holds = kept.get("requests") or {}
    was = {r: holds.get(r) or asked.get(r) for r in set_to}  # what its pods ask now

    def lower(r: str) -> bool:
        return bool(was[r]) and qty(set_to[r]) < qty(was[r] or "0")

    deferred = []
    if automated:  # the churn rule (slice 12.5)
        since = at - (old or {}).get("lowered_at", -LOWER_EVERY)
        for r in list(set_to):
            if was[r] and qty(was[r] or "0") > 0:
                change = abs(qty(set_to[r]) / qty(was[r] or "0") - 1)
                if change < CHURN or (lower(r) and since < LOWER_EVERY):
                    del set_to[r], template_had[r]
                    deferred.append(r)
        if not set_to:
            return None, {}
    lowered = old is not None and any(lower(r) for r in set_to)
    for r, q in holds.items():  # a resource this Sizing leaves alone keeps what it holds
        if r not in set_to:
            set_to[r] = q
            template_had[r] = (kept.get("template") or {}).get(r)
    restarts = sorted(
        p.resource_name
        for p in template.resize_policy or []
        if p.restart_policy == "RestartContainer" and p.resource_name in set_to
    )
    if restarts:
        return done("skipped", 0, f"its resizePolicy restarts the container for {restarts}")
    try:
        mode = vpa_mode(custom, w.namespace, w.name)
        if mode:
            return done("skipped", 0, f"a VPA in mode {mode} sizes it")
        for r in sorted(hpa_resources(autoscaling, w.namespace, w.name, w.container) & set(set_to)):
            del set_to[r], template_had[r]
            notes.append(f"; {r} left to its HPA, which scales on its utilization")
        if not set_to:
            return done("skipped", 0, "nothing its HPA doesn't scale on")
        pairs = [(c.name, requests_of(c), limits_of(c)) for c in containers]
        why_not = qos_change(pairs, w.container, set_to) or limit_range_breach(
            core, w.namespace, set_to, limits
        )
        if why_not:
            return done("skipped", 0, why_not)
        pods = pods_of(core, apps, d)
        if not pods:
            return done("skipped", 0, "no live pods")
        why_not = quota_breach(core, w.namespace, set_to, asked, len(pods))
        if why_not:
            return done("skipped", 0, why_not)
    except ApiException as e:  # a namespace its RoleBinding misses: the others still go on
        return done("failed", 0, f"checking it: {why(e)}")
    todo = [p for p in pods if needs(p, w.container, set_to)]
    if not todo:
        return done("skipped", 0, f"all {len(pods)} pods already have these requests")
    try:
        resize(core, todo[0], w.container, set_to)
    except ApiException as e:
        return done("failed", 0, f"{todo[0].metadata.name}: {why(e)}")
    _, held = done("applied", 1, "")
    held |= {
        "outcome": "rolling",
        "pods": {todo[0].metadata.name: baseline(todo[0], w.container, at)},
        "pod": todo[0].metadata.name,
        "since": at,
        "canary_until": at + CANARY_SECONDS,
        "resized": 1,
        "notes": "".join(notes),
    }
    if lowered:
        held["lowered_at"] = at
    if deferred:  # an approval of this run still applies them
        held["deferred"] = deferred
    return None, held


def advance(core: Any, apps: Any, key: str, h: dict[str, Any], now: float) -> Actuation | None:
    """One minute of a rolling resize: wait for its current pod, then (after the canary's
    10 minutes) resize the next one. An Actuation once it ends: applied when every live pod
    has the requests, failed when a pod's resize is Infeasible or not done in 10 minutes."""
    ns, kind, name, container = key.split("/")
    set_to = h["requests"]

    def end(outcome: Outcome, reason: str) -> Actuation:
        h["outcome"] = outcome
        for k in ROLLOUT:
            h.pop(k, None)
        h["watch_until"] = now + WATCH_SECONDS  # the pods resized, applied or not
        return Actuation(
            namespace=ns,
            kind=kind,
            name=name,
            container=container,
            run_id=h["run_id"],
            outcome=outcome,
            pods=resized,
            reason=(reason + notes)[:1000],
            at=now,
            **{r: float(qty(q)) for r, q in set_to.items()},
        )

    resized, notes, pod = h["resized"], h.get("notes", ""), h["pod"]
    try:
        p = core.read_namespaced_pod(pod, ns)
    except ApiException as e:
        if e.status != 404:
            log.warning("reading %s/%s: %s", ns, pod, why(e))
            return None
        p = None  # gone: its replacement is one of the pods still to do
    if p is not None and not p.metadata.deletion_timestamp:
        state, message = resize_state(p, container, set_to)
        if state == "infeasible":
            return end("failed", f"{pod}: Infeasible: {message}; {resized - 1} other pods resized")
        if state != "done":
            if now - h["since"] < WAIT_SECONDS:
                return None
            return end("failed", f"{pod}: {state} for {WAIT_SECONDS // 60} minutes: {message}")
    if now < h["canary_until"]:
        return None
    try:
        d = apps.read_namespaced_deployment(name, ns)
        pods = pods_of(core, apps, d)
        todo = [x for x in pods if needs(x, container, set_to)]
        if not todo:
            return end("applied", f"{resized} of {len(pods)} pods resized in place, one at a time")
        resize(core, todo[0], container, set_to)
    except ApiException as e:
        return end("failed", f"resizing its next pod: {why(e)}")
    h.update(pod=todo[0].metadata.name, since=now, resized=resized + 1)
    h.setdefault("pods", {})[todo[0].metadata.name] = baseline(todo[0], container, now)
    return None


def gist(reason: str) -> str:
    """A reason without its numbers: a skip for a quota is the same skip at next hour's values."""
    return re.sub(r"\d[\w.]*", "N", reason)


def texts(requests: dict[str, str]) -> str:
    return ", ".join(f"{r} {q}" for r, q in sorted(requests.items()))


def baseline(pod: Any, container: str, at: float) -> dict[str, Any]:
    """What a pod was when it was resized: a later restart is counted from here."""
    return {"at": at, "restarts": restarts_of(pod, container)}


def restarts_of(pod: Any, container: str) -> int:
    st = container_status(pod, container)
    return int(st.restart_count or 0) if st else 0


def container_status(pod: Any, container: str) -> Any:
    statuses = (pod.status.container_statuses if pod.status else None) or []
    return next((s for s in statuses if s.name == container), None)


def trouble(core: Any, apps: Any, key: str, h: dict[str, Any], now: float) -> str | None:
    """Why the Sizing held as `h` made its pods unhealthy (slice 12.4), or None: a pod with
    its requests whose container restarted (an OOM kill named as one) since it got them, or
    a pod it resized that has been NotReady for 2 minutes since. Throttling is not one."""
    ns, _, name, container = key.split("/")
    try:
        pods = pods_of(core, apps, apps.read_namespaced_deployment(name, ns))
    except ApiException as e:
        log.warning("watching %s: %s", key, why(e))
        return None
    seen = h.get("pods") or {}
    for p in pods:
        if needs(p, container, h["requests"]):
            continue  # not the Actuator's requests: not its doing
        st = container_status(p, container)
        mine = seen.get(p.metadata.name) or {"at": 0.0, "restarts": 0}  # new: from the webhook
        if st and (st.restart_count or 0) > mine["restarts"]:
            ended = st.last_state.terminated if st.last_state else None
            what = "was OOM-killed" if ended and ended.reason == "OOMKilled" else "restarted"
            return f"{p.metadata.name}: {container} {what}"
        if p.metadata.name not in seen:
            continue  # a new pod may take its time to be Ready
        for c in (p.status.conditions if p.status else None) or []:
            since = c.last_transition_time.timestamp() if c.last_transition_time else None
            if (
                c.type == "Ready"
                and c.status != "True"
                and since is not None
                and since >= mine["at"]
                and now - since >= NOT_READY_SECONDS
            ):
                return f"{p.metadata.name}: NotReady for {NOT_READY_SECONDS // 60} minutes"
    return None


def rollback(core: Any, apps: Any, key: str, h: dict[str, Any], why_: str, now: float) -> Actuation:
    """Every pod with the Actuator's requests back to its template's, in place and at once;
    then no new Sizing of that container for 24 hours, doubling with each rollback in 7 days."""
    ns, kind, name, container = key.split("/")
    had = h.get("template") or {}
    back = {r: had[r] for r in h["requests"] if had.get(r) is not None}
    unset = sorted(r for r in h["requests"] if had.get(r) is None)
    done, refused = 0, []
    try:
        pods = pods_of(core, apps, apps.read_namespaced_deployment(name, ns))
    except ApiException as e:
        pods, refused = [], [f"listing its pods: {why(e)}"]
    for p in pods:
        if back and not needs(p, container, h["requests"]):
            try:
                resize(core, p, container, back)
                done += 1
            except ApiException as e:
                refused.append(f"{p.metadata.name}: {why(e)}")
    rollbacks = [t for t in h.get("rollbacks") or [] if now - t < ROLLBACKS_FOR] + [now]
    until = now + BACKOFF_SECONDS * 2 ** (len(rollbacks) - 1)
    for k in ROLLOUT + WATCHED:
        h.pop(k, None)
    h.update(outcome="rolled_back", rollbacks=rollbacks, backoff_until=until)
    reason = f"{why_}: {done} pods back from {texts(h['requests'])}"
    if back:
        reason += f" to their template's {texts(back)}"
    if unset:
        reason += f" ({unset} left: the template sets none)"
    if refused:
        reason += f"; {len(refused)} refused, first {refused[0]}"
    reason += f"; no new Sizing of it until {datetime.fromtimestamp(until, UTC):%Y-%m-%d %H:%M} UTC"
    return Actuation(
        namespace=ns,
        kind=kind,
        name=name,
        container=container,
        run_id=h["run_id"],
        outcome="rolled_back",
        pods=done,
        reason=reason[:1000],
        at=now,
        **{r: float(qty(q)) for r, q in back.items()},
    )


EVENTS = {
    "applied": "SizingApplied",
    "skipped": "SizingSkipped",
    "failed": "SizingFailed",
    "handed_back": "HandedBack",
    "rolled_back": "SizingRolledBack",
}


GONE = {"handed_back": "back to its template", "rolled_back": "back to its template"}


def event(core: Any, a: Actuation, h: dict[str, Any] | None = None) -> None:
    """A Kubernetes Event on the Deployment, so `kubectl describe` shows what was done;
    `h`, its hold, tells Automation's from an approval's."""
    values = ", ".join(
        f"{r} {text(v)}"
        for r, v, text in (("cpu", a.cpu, cpu_text), ("memory", a.memory, memory_text))
        if v is not None
    )
    by = "Automation" if (h or {}).get("automated") else "Approved Sizing"
    message = (
        f"{a.container}: {GONE.get(a.outcome) or values or 'no change'} "
        f"({by}, run {a.run_id}): {a.reason}"
    )
    warning = a.outcome in ("failed", "rolled_back")
    post(core, a.namespace, ("apps/v1", a.kind, a.name), EVENTS[a.outcome], message, warning)


def post(
    core: Any, ns: str, what: tuple[str, str, str], reason: str, message: str, warning: bool
) -> None:
    """An Event on `what` (api version, kind, name) in `ns`; a refused one is only logged."""
    now = datetime.now(UTC)
    api_version, kind, name = what
    body = client.CoreV1Event(
        metadata=client.V1ObjectMeta(name=f"{name}.{uuid.uuid4().hex[:16]}"),
        involved_object=client.V1ObjectReference(
            api_version=api_version, kind=kind, name=name, namespace=ns
        ),
        reason=reason,
        message=message[:1024],
        type="Warning" if warning else "Normal",
        source=client.V1EventSource(component="squero-actuator"),
        reporting_component="squero-actuator",
        first_timestamp=now,
        last_timestamp=now,
        count=1,
    )
    try:
        core.create_namespaced_event(ns, body)
    except ApiException as e:
        log.warning("event on %s/%s: %s", ns, name, why(e))


def check_version(version: Any) -> None:
    """Refuse a cluster without in-place pod resize on by default."""
    v = version.get_code()
    minor = re.match(r"\d+", v.minor or "")
    if (int(v.major), int(minor.group()) if minor else 0) < (1, MIN_MINOR):
        raise SystemExit(f"Kubernetes {v.git_version}: the Actuator needs 1.{MIN_MINOR} or later")


# --- the pod-creation webhook (slice 12.2) ------------------------------------------------


def mutation(
    req: dict[str, Any], held: dict[str, dict[str, Any]], own: str, paused: Any = frozenset()
) -> list[Any]:
    """The JSON Patch giving a new pod of a Deployment the requests applied to it: only
    where its container still asks what the template asked then (a person's change wins),
    never above its limit, never in kube-* or the Actuator's own namespace, never for a
    paused Deployment (`ns/name` in `paused`)."""
    ns = req.get("namespace") or ""
    if req.get("operation") != "CREATE" or ns == own or ns.startswith("kube-"):
        return []
    pod = req.get("object") or {}
    meta = pod.get("metadata") or {}
    hashed = (meta.get("labels") or {}).get("pod-template-hash")
    rs = next(
        (
            o.get("name", "")
            for o in meta.get("ownerReferences") or []
            if o.get("kind") == "ReplicaSet"
        ),
        "",
    )
    if not hashed or not rs.endswith(f"-{hashed}"):
        return []  # not a Deployment's pod
    deployment = rs.removesuffix(f"-{hashed}")
    if f"{ns}/{deployment}" in paused:
        return []
    ops: list[Any] = []
    for i, c in enumerate((pod.get("spec") or {}).get("containers") or []):
        h = held.get(f"{ns}/Deployment/{deployment}/{c.get('name')}")
        if not h or h.get("outcome") != "applied":
            continue
        resources = c.get("resources") or {}
        requests = resources.get("requests") or {}
        limits = resources.get("limits") or {}
        had = h.get("template")  # None: held before slice 12.2 recorded it
        if had is None or not all(same(requests.get(r), had.get(r)) for r in h["requests"]):
            continue  # its template's requests changed since: theirs, not ours
        new = {}
        for r, q in h["requests"].items():
            if r in limits and qty(q) > qty(limits[r]):
                q = limits[r]
            if not same(requests.get(r), q):
                new[r] = q
        everyone = [
            (
                x.get("name", ""),
                dict((x.get("resources") or {}).get("requests") or {}),
                dict((x.get("resources") or {}).get("limits") or {}),
            )
            for x in (pod.get("spec") or {}).get("containers") or []
        ]
        if not new or qos_change(everyone, c.get("name", ""), new):
            continue  # a pod's QoS class stays its template's (slice 12.3)
        at = f"/spec/containers/{i}/resources"
        if "resources" not in c:
            ops.append({"op": "add", "path": at, "value": {"requests": new}})
        elif "requests" not in resources:
            ops.append({"op": "add", "path": f"{at}/requests", "value": new})
        else:
            ops += [{"op": "add", "path": f"{at}/requests/{r}", "value": q} for r, q in new.items()]
    return ops


def admit(
    review: Any, held: dict[str, dict[str, Any]], killed: bool, own: str, paused: Any = frozenset()
) -> dict[str, Any]:
    """The AdmissionReview answer: always allowed; a patch unless the Kill switch is on."""
    req = review.get("request") if isinstance(review, dict) else None
    req = req if isinstance(req, dict) else {}
    answer: dict[str, Any] = {"uid": req.get("uid", ""), "allowed": True}
    try:
        ops = [] if killed else mutation(req, held, own, paused)
    except Exception:  # fail open, as the webhook's failurePolicy does
        log.exception("webhook: pod left as it is")
        ops = []
    if ops:
        answer["patchType"] = "JSONPatch"
        answer["patch"] = base64.b64encode(json.dumps(ops).encode()).decode()
    return {"apiVersion": "admission.k8s.io/v1", "kind": "AdmissionReview", "response": answer}


def certificate(host: str) -> tuple[bytes, bytes]:
    """A self-signed certificate for `host` and its key (PEM), new at every start: the
    Actuator patches it into its own webhook's caBundle, so no cert-manager is needed."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(host)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    pem = serialization.Encoding.PEM
    private = key.private_bytes(
        pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return cert.public_bytes(pem), private


def trust(admission: Any, cert: bytes) -> None:
    """Its webhook's caBundle becomes this start's certificate (RBAC: this object only)."""
    ca = base64.b64encode(cert).decode()
    patch = [{"op": "replace", "path": "/webhooks/0/clientConfig/caBundle", "value": ca}]
    admission.patch_mutating_webhook_configuration(WEBHOOK, patch)


def serve(a: "Actuator", cert: bytes, key: bytes, port: int = WEBHOOK_PORT) -> ThreadingHTTPServer:
    """The webhook over TLS on `port`, in its own threads; it reads `a`'s holds and Kill
    switch as they are at each pod's creation."""

    class Webhook(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            path = urlsplit(self.path).path  # the API server adds ?timeout=2s
            if path != "/mutate" or not 0 < length <= MAX_REVIEW:
                self.send_error(404 if path != "/mutate" else 413)
                return
            try:
                review = json.loads(self.rfile.read(length))
            except ValueError:
                self.send_error(400)
                return
            answer = admit(review, a.held, a.killed, a.namespace, a.paused)
            body = json.dumps(answer).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass  # every pod's creation: too much for the log

    server = ThreadingHTTPServer(("0.0.0.0", port), Webhook)  # noqa: S104
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    with tempfile.TemporaryDirectory() as d:  # ssl reads files; gone once loaded
        (Path(d) / "tls.crt").write_bytes(cert)
        (Path(d) / "tls.key").write_bytes(key)
        tls.load_cert_chain(Path(d) / "tls.crt", Path(d) / "tls.key")
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@dataclass
class Actuator:
    """One cluster's Actuator: `step` is one minute's work."""

    http: httpx.Client  # base_url the Hub, with the token's header
    core: Any
    apps: Any
    namespace: str
    held: dict[str, dict[str, Any]] = field(default_factory=dict)
    unsent: list[Actuation] = field(default_factory=list)
    killed: bool = False
    autoscaling: Any = None  # AutoscalingV2Api: HPAs (slice 12.3)
    custom: Any = None  # CustomObjectsApi: VPAs
    paused: frozenset[str] = frozenset()  # `ns/name` of the Deployments a person paused
    unanswered: float | None = None  # since when the Hub hasn't answered
    told: bool = False  # the Event that it hasn't is out

    def load(self) -> None:
        try:
            cm = self.core.read_namespaced_config_map(CONFIGMAP, self.namespace)
        except ApiException as e:
            if e.status != 404:
                raise
            return
        self.held = json.loads((cm.data or {}).get(KEY) or "{}")

    def save(self) -> None:
        body = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(name=CONFIGMAP),
            data={KEY: json.dumps(self.held, sort_keys=True)},
        )
        try:
            try:
                self.core.replace_namespaced_config_map(CONFIGMAP, self.namespace, body)
            except ApiException as e:
                if e.status != 404:
                    raise
                self.core.create_namespaced_config_map(self.namespace, body)
        except ApiException as e:  # pods already match: a restart finds nothing to change
            log.error("saving %s: %s", CONFIGMAP, why(e))

    def pull(self) -> Desired | None:
        try:
            r = self.http.get("/actuator/desired")
            r.raise_for_status()
            return Desired.model_validate_json(r.content)
        except httpx.HTTPStatusError as e:
            log.warning("the Hub answered %s for the desired state", e.response.status_code)
        except (httpx.HTTPError, ValidationError) as e:
            log.warning("the Hub's desired state: %s", type(e).__name__)
        return None

    def report(self) -> None:
        while self.unsent:
            batch = self.unsent[:MAX_REPORTS]
            try:
                r = self.http.post("/actuator/reports", json=[a.model_dump() for a in batch])
                r.raise_for_status()
            except httpx.HTTPError as e:
                code = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None
                if code and 400 <= code < 500 and code not in (401, 403, 429):
                    # the Hub's verdict on these reports, not an outage: resending never helps
                    log.error("the Hub refused %d reports (%d): dropped", len(batch), code)
                    del self.unsent[: len(batch)]
                    continue
                log.warning("reporting to the Hub: %s", code or type(e).__name__)
                self.unsent = self.unsent[-MAX_REPORTS:]  # the oldest go first
                return
            del self.unsent[: len(batch)]

    def step(self) -> None:
        desired = self.pull()
        self.answered(desired is not None, time.time())
        if desired is not None and desired.kill_switch != self.killed:
            self.killed = desired.kill_switch
            log.warning("the Kill switch is %s", "on" if self.killed else "off")
        wanted = (desired.sizings + desired.automated) if desired else []
        self.pauses({*self.held, *(f"{w.namespace}/{w.kind}/{w.name}" for w in wanted)})
        done = self.hand_back()
        if not self.killed:  # the Actuator undoes its own harm, the Hub reachable or not
            done += self.watch()
        if desired is not None and not self.killed:  # the Hub's word: rollouts go on
            done += self.advance() + self.act(desired.sizings, desired.automated)
            done += self.catch_up()
        rolling = any(h.get("outcome") == "rolling" or "pods" in h for h in self.held.values())
        if done or rolling:
            self.save()
        self.unsent += done
        self.report()

    def answered(self, ok: bool, now: float) -> None:
        """Count how long the Hub hasn't answered; at 15 minutes, one Event on its ConfigMap."""
        if ok:
            if self.told:
                log.warning("the Hub answers again")
            self.unanswered, self.told = None, False
            return
        if self.unanswered is None:
            self.unanswered = now
        if not self.told and now - self.unanswered >= UNREACHABLE_SECONDS:
            self.told = True
            message = (
                f"the Hub has not answered for {UNREACHABLE_SECONDS // 60} minutes: "
                "holding what it applied, changing nothing new"
            )
            log.warning(message)
            post(self.core, self.namespace, ("v1", "ConfigMap", CONFIGMAP), "HubUnreachable",
                 message, warning=True)  # fmt: skip

    def pauses(self, keys: set[str]) -> None:
        """Which Deployments a person paused, read again in each namespace it has keys in;
        a namespace it can't list keeps what it knew."""
        paused: set[str] = set()
        for ns in sorted({k.split("/")[0] for k in keys}):
            try:
                found = self.apps.list_namespaced_deployment(ns).items
            except ApiException as e:
                log.warning("reading %s's Deployments: %s", ns, why(e))
                paused |= {p for p in self.paused if p.startswith(f"{ns}/")}
                continue
            paused |= {
                f"{ns}/{d.metadata.name}"
                for d in found
                if (d.metadata.annotations or {}).get(PAUSE) == "true"
            }
        for p in sorted(paused ^ self.paused):
            log.warning("%s is %s", p, "paused" if p in paused else "no longer paused")
        self.paused = frozenset(paused)

    def is_paused(self, key: str) -> bool:
        ns, _, name, *_ = key.split("/")
        return f"{ns}/{name}" in self.paused

    def watch(self) -> list[Actuation]:
        """Roll back each Sizing that made its pods unhealthy within its hour (slice 12.4)."""
        out, now = [], time.time()
        for key, h in self.held.items():
            if "pods" not in h:
                continue
            if h.get("outcome") != "rolling" and now >= h.get("watch_until", 0):
                for k in WATCHED:  # its hour is over: kept, no longer watched
                    h.pop(k, None)
                continue
            reason = trouble(self.core, self.apps, key, h, now)
            if reason:
                a = rollback(self.core, self.apps, key, h, reason, now)
                log.warning("rolled back %s: %s", key, a.reason)
                event(self.core, a, h)
                out.append(a)
        return out

    def advance(self) -> list[Actuation]:
        out = []
        for key, h in self.held.items():
            if h.get("outcome") == "rolling" and not self.is_paused(key):
                a = advance(self.core, self.apps, key, h, time.time())
                if a:
                    log.info("%s %s: %s", a.outcome, key, a.reason)
                    event(self.core, a, h)
                    out.append(a)
        return out

    def catch_up(self) -> list[Actuation]:
        """Pods that started from their template while it held a Sizing (the Kill switch on,
        or the Actuator down: its webhook fails open) get its requests again: the pre-checks
        again, then a canary and one pod at a time, as a new approval would. The pods it
        is still watching stay watched."""
        out = []
        for key, h in self.held.items():
            if h.get("outcome") != "applied" or self.is_paused(key):
                continue
            ns, kind, name, container = key.split("/")
            try:
                pods = pods_of(self.core, self.apps, self.apps.read_namespaced_deployment(name, ns))
            except ApiException as e:
                log.warning("checking %s: %s", key, why(e))
                continue
            behind = [p.metadata.name for p in pods if needs(p, container, h["requests"])]
            if not behind:
                continue
            values = {r: float(qty(q)) for r, q in h["requests"].items()}
            w = Wanted(
                run_id=h["run_id"], namespace=ns, kind=kind, name=name, container=container,
                cpu=values.get("cpu"), memory=values.get("memory"),
            )  # fmt: skip
            a, new = apply(self.core, self.apps, w, time.time(), self.autoscaling, self.custom)
            carried = ("rollbacks", "backoff_until", "watch_until", "lowered_at", "automated")
            kept = {k: h[k] for k in carried if k in h}
            watched = (h.get("pods") or {}) | (new.get("pods") or {})
            if watched:
                new["pods"] = watched
            self.held[key] = kept | new
            if a is None:
                log.info("catching up %s: %s from its template", key, ", ".join(behind))
                continue
            log.info("%s %s: %s", a.outcome, key, a.reason)
            event(self.core, a, h)
            out.append(a)
        return out

    def hand_back(self) -> list[Actuation]:
        """Each container it holds whose Deployment's template now asks other requests than
        when it applied (a person's change), or that is gone: its own again, never held."""
        out = []
        for key, h in self.held.items():
            if h.get("outcome") in ("applied", "rolling"):
                reason = self.changed(key, h)
                if reason is None:
                    continue
                ns, kind, name, container = key.split("/")
                for k in ROLLOUT + WATCHED:
                    h.pop(k, None)
                h["outcome"] = "handed_back"
                a = Actuation(
                    namespace=ns,
                    kind=kind,
                    name=name,
                    container=container,
                    run_id=h["run_id"],
                    outcome="handed_back",
                    pods=0,
                    reason=reason,
                    at=time.time(),
                )
                log.info("handed back %s: %s", key, reason)
                event(self.core, a, h)
                out.append(a)
        return out

    def changed(self, key: str, h: dict[str, Any]) -> str | None:
        """Why the container held as `h` is no longer the Actuator's, or None."""
        had = h.get("template")
        if had is None:
            return "held without its template's requests (before slice 12.2)"
        ns, _, name, container = key.split("/")
        try:
            d = self.apps.read_namespaced_deployment(name, ns)
        except ApiException as e:
            if e.status == 404:
                return "no such Deployment"
            log.warning("reading %s: %s", key, why(e))  # the API server's trouble, no change
            return None
        c = next((c for c in d.spec.template.spec.containers if c.name == container), None)
        if c is None:
            return f"no container {container!r} in its template"
        now = (c.resources.requests if c.resources else None) or {}
        moved = [r for r in h.get("requests") or {} if not same(now.get(r), had.get(r))]
        if not moved:
            return None
        return "its template's requests changed: " + ", ".join(
            f"{r} {had.get(r) or 'unset'} to {now.get(r) or 'unset'}" for r in moved
        )

    def act(self, sizings: list[Wanted], automated: list[Wanted] | None = None) -> list[Actuation]:
        """Each Approved Sizing newer than what it applied to that container: applied once,
        whatever its outcome (a refused one waits for the next approval). Then each
        Automation Sizing newer than the last it saw (slice 12.5): under the churn rule, never
        while the container rolls or backs off, and a skip said once while its reason holds."""
        out = []
        for w, auto in [*((w, False) for w in sizings), *((w, True) for w in automated or [])]:
            key = "/".join((w.namespace, w.kind, w.name, w.container))
            if self.is_paused(key):
                continue  # waits: applied once the person lifts the pause, if still current
            old = self.held.get(key, {})
            now = time.time()
            if auto:
                if max(old.get("run_id", -1), old.get("seen", -1)) >= w.run_id:
                    continue
                if old.get("outcome") == "rolling" or now < old.get("backoff_until", 0):
                    continue  # waits, unsaid: a new Sizing comes every hour
            elif old.get("run_id", -1) > w.run_id or (
                old.get("run_id") == w.run_id and not old.get("automated")
            ):
                continue
            elif old.get("run_id") == w.run_id:  # the run Automation applied, now approved
                if not old.get("deferred"):  # the same requests: approved as they are held
                    old.pop("automated")
                    continue
                if old.get("outcome") == "rolling":
                    continue  # what the churn rule left out goes once this rollout ends
            carried = ("rollbacks", "backoff_until", "lowered_at")
            carry: dict[str, Any] = {k: old[k] for k in carried if k in old}
            a: Actuation | None
            if now < old.get("backoff_until", 0):
                until = datetime.fromtimestamp(old["backoff_until"], UTC)
                a = Actuation(
                    **w.model_dump(exclude={"cpu", "memory"}),
                    outcome="skipped",
                    pods=0,
                    reason=f"rolled back {len(old.get('rollbacks') or [])} times in 7 days: "
                    f"no new Sizing of it until {until:%Y-%m-%d %H:%M} UTC",
                    at=now,
                )
                self.held[key] = {
                    "run_id": w.run_id,
                    "outcome": "skipped",
                    "requests": {},
                    "template": {},
                    "at": now,
                    **carry,
                }
            else:
                args = (self.core, self.apps, w, now, self.autoscaling, self.custom, old, auto)
                a, new = apply(*args)
                if not new:  # nothing moves enough: the churn rule
                    self.held[key] = {**old, "seen": w.run_id}
                    continue
                if auto and a is not None and a.outcome in ("skipped", "failed"):
                    # what it holds stays held; the same reason again goes unsaid
                    kept = old if old.get("outcome") == "applied" else carry | new
                    said = gist(old.get("unapplied") or "") == gist(a.reason)
                    self.held[key] = {**kept, "seen": w.run_id, "unapplied": a.reason}
                    if said:
                        continue
                else:
                    self.held[key] = carry | new | ({"automated": True} if auto else {})
            if a is None:
                log.info("rolling %s: canary %s", key, self.held[key]["pod"])
                continue
            log.info("%s %s: %s", a.outcome, key, a.reason)
            event(self.core, a, {"automated": auto})
            out.append(a)
        return out


def main(s: ActuatorSettings) -> None:  # pragma: no cover - the cluster's own process
    config.load_incluster_config()  # type: ignore[no-untyped-call]
    core, apps = client.CoreV1Api(), client.AppsV1Api()
    check_version(client.VersionApi())
    cert, key = certificate(f"{WEBHOOK}.{s.namespace}.svc")
    headers = {"Authorization": f"Bearer {s.token.get_secret_value()}"}
    with httpx.Client(base_url=s.hub, headers=headers, timeout=15) as http:
        a = Actuator(http, core, apps, s.namespace)
        a.autoscaling, a.custom = client.AutoscalingV2Api(), client.CustomObjectsApi()
        a.load()
        serve(a, cert, key)
        try:  # until then the API server can't call it, and pods start unchanged
            trust(client.AdmissionregistrationV1Api(), cert)
        except ApiException as e:
            log.error("its webhook's caBundle: %s: new pods start from their template", why(e))
        log.info("actuator started: %d containers held", len(a.held))
        while True:
            a.step()
            time.sleep(s.interval)
