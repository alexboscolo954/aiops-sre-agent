"""The Actuator (slice 12.1): applies the Hub's Approved Sizings inside a client's cluster.

It runs in that cluster with its own token, bound to one Contract's cluster, and RBAC that
can resize pods but never edit a workload (which could change its image). Every minute
it pulls its desired state from the Hub, resizes the pods of each new Approved Sizing's
workload in place (Kubernetes 1.33+), keeps what it did in one ConfigMap so a restart
applies nothing twice, writes an Event on the workload and reports each outcome (an
Actuation) to the Hub. The Hub decides and never pushes; a Kill switch reaches it as no
Sizings at all.

What it applied it holds (slice 12.2): its pod-creation webhook gives a new pod of that
Deployment the same requests (it fails open: with the Actuator down, pods start from their
template), until a person changes the template's requests, which hands the container back.

Before a resize (slice 12.3) it checks what would refuse or fight it: a pod's QoS class, a
VPA, an HPA on a resource's utilization, the namespace's LimitRange and ResourceQuota. Then
it resizes one canary pod, watches it 10 minutes, and the others one at a time, each until
the kubelet allocated it and the pod is Ready; an Infeasible resize, or one not done in 10
minutes, stops it there. Deployments, and from slice 12.8a StatefulSets and DaemonSets: a
DaemonSet's new pod gets only lowered requests from the webhook (it must fit any node), a
DaemonSet's pod whose node has no room is left as it runs while the others go on, and
neither kind's pod is ever evicted. From slice 12.8b Argo Rollouts, in place only: read as a
Deployment (`Apps`), their pods their own ReplicaSets', never evicted. From slice 12.8c
CronJobs, through the webhook only: held at once for their next run's pods, that first run
watched until it ends (`first_run`), a pod of it Failed or OOM-killed a Rollback.

Slice 12.9a (an audit's findings): a network failure is an ApiException (`Calm`), a minute
that fails keeps and reports what it did, a rollout waits out a passing failure, a put back
some pod refused is finished later (`finish`), restarts are counted from when a rollout
begins, and a refused approval leaves the earlier hold as it is. Slice 12.9b: the Kill
switch as last heard and the reports not yet taken are kept in its ConfigMap (`state.json`),
an approval a passing failure met is tried again, a rollout scaled to zero ends applied, a
CronJob's run is told by a recent minute in its Job's name, and an approval made again after
a Revert (`again`) applies the run that Revert undid.

Under Automation (slice 12.5) it also applies, unasked, the newest Sizing of each container
the Contract automates: a change under 10% ignored, an increase at once, a decrease at most
once a day. A workload a person annotated `squero-actuator/pause: "true"` is left alone,
as under the Kill switch. While the Hub is unreachable it changes nothing new, and says so
in an Event after 15 minutes.

A Revert (slice 12.6a), the Operator's undo, puts a container's pods back to its template's
requests in place, as a rollback does, and the Actuator stops holding it.

With the Contract's eviction on (slice 12.7), a pod whose resize its node can never fit (the
kubelet's Infeasible, or from Kubernetes 1.35 the API server's refusal) is evicted through
the Eviction API (PodDisruptionBudgets hold) inside one of the Contract's windows, one at a
time and at least 5 minutes apart; the webhook gives its
replacement the requests. Outside a window the rollout waits on it; a replacement not Ready
in 10 minutes is a rollback. A pod of a Deployment with one replica, or that no
PodDisruptionBudget covers, is never evicted: its rollout fails as with eviction off.
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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
import urllib3
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
KEPT_REPORTS = 200  # of its unsent reports, the newest kept across a restart: the
# ConfigMap's megabyte is its holds' first
STATE = "state.json"  # beside it: the Kill switch as last heard, reports not yet taken
RUN_AGE = 30 * 1440  # minutes: how old a CronJob run's scheduled time may be (slice 12.9b)
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
ENDING = 3  # Rollbacks of a Workload in 7 days that end its Automation (slice 12.5)
CHURN = Decimal("0.10")  # under Automation, a change smaller than this is ignored (slice 12.5)
LOWER_EVERY = 86400  # under Automation, a container's requests go down at most this often
UNREACHABLE_SECONDS = 900  # the Hub unanswered this long: an Event says so
PAUSE = "squero-actuator/pause"  # a workload annotated "true" is left alone
# the kinds it resizes (StatefulSet and DaemonSet from slice 12.8a, Argo Rollouts from 12.8b),
# as named in its API calls (a Rollout's through `Apps`)
KINDS = {
    "Deployment": "deployment",
    "StatefulSet": "stateful_set",
    "DaemonSet": "daemon_set",
    "Rollout": "rollout",
    "CronJob": "cron_job",  # slice 12.8c: through the webhook only
}
ARGO = ("argoproj.io", "v1alpha1")  # an Argo Rollout's API group and version
API = {"Rollout": "/".join(ARGO), "CronJob": "batch/v1"}  # others: apps/v1
RUN_WATCH = 7 * 86400  # a CronJob's first run under its hold is watched this long at most
EVICT_EVERY = 300  # at least this long between two evictions (slice 12.7)
# held while rolling; "waiting": on an Infeasible pod, to evict it; "evicted": its replacement
ROLLOUT = (
    *("pod", "since", "canary_until", "resized", "notes", "waiting", "evicted", "no_room"),
    "stalled",  # since when the API server hasn't let it go on (slice 12.9a)
)
# seconds one call to the API server may take, once (`single`: its client's own retries
# would make it four times that). ponytail: a minute of some twenty calls can still take
# five against an API server that accepts and never answers; stop at the first if it matters
API_TIMEOUT = 15
WATCHED = ("pods", "watch_until", "first_run")  # held while watched
Outcome = Literal["applied", "skipped", "failed", "handed_back", "rolled_back", "reverted"]
# held, never reported: "rolling"
Ending = Callable[[Outcome, str], "Actuation"]  # how advance() ends a rollout


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
    # approved after a Revert of that container (slice 12.9b): applied even if it is the
    # run that Revert undid, which an approval from before it never is
    again: bool = False


class Undo(BaseModel):
    """A Revert the Operator asked of one container (slice 12.6a)."""

    model_config = ConfigDict(extra="ignore")

    id: int
    namespace: str
    kind: str
    name: str
    container: str


class Desired(BaseModel):
    kill_switch: bool
    sizings: list[Wanted]  # Approved Sizings
    # Automation's (slice 12.5): a list of their own, so an older Actuator never applies them
    # as if approved, without the churn rule or the pause annotation
    automated: list[Wanted] = []
    reverts: list[Undo] = []  # slice 12.6a
    # slice 12.7: the Contract's eviction off, or on and its window closed or open now
    eviction: Literal["off", "closed", "open"] = "off"


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


def unreal(a: Actuation) -> str | None:
    """Which of an Actuation's numbers no Actuator sends (slice 12.9c), or None: one that
    isn't a number (NaN, infinity) or is below zero. The Hub refuses the whole report
    for it; nothing an honest Actuator may send is refused, since a refused report is
    dropped there, its Rollbacks with it. Checked by the Hub, not by the model: the
    Actuator builds one after it has resized, and reads its own stored ones back."""
    for name in ("cpu", "memory", "at"):
        value = getattr(a, name)
        if value is not None and not (math.isfinite(value) and value >= 0):
            return name
    return None


def rollbacks_of(
    actuations: list[dict[str, Any]], cluster: str, now: float
) -> dict[tuple[str, ...], list[float]]:
    """The Hub's side: each Workload's Rollbacks on `cluster` in the 7 days to `now`,
    oldest first, from its stored Actuations."""
    out: dict[tuple[str, ...], list[float]] = {}
    for r in sorted(actuations, key=lambda r: r["at"]):
        if (
            r["cluster"] == cluster
            and r["outcome"] == "rolled_back"
            and r["at"] >= now - ROLLBACKS_FOR
        ):
            out.setdefault((r["namespace"], r["kind"], r["name"]), []).append(r["at"])
    return out


def resumes(rollbacks: dict[tuple[str, ...], list[float]]) -> dict[tuple[str, ...], float]:
    """Each Workload whose Automation the Rollbacks ended, and when it resumes: once the
    oldest of the last three is 7 days old."""
    return {w: ts[-ENDING] + ROLLBACKS_FOR for w, ts in rollbacks.items() if len(ts) >= ENDING}


def qty(q: str) -> Decimal:
    return parse_quantity(q)  # type: ignore[no-untyped-call,no-any-return]


def cpu_text(cores: float) -> str:
    return f"{math.ceil(round(cores * 1000, 6))}m"


def memory_text(b: float) -> str:
    return f"{math.ceil(round(b / MI, 6))}Mi"


def same(a: str | None, b: str | None) -> bool:
    """Two requests as quantities (`0.1` is `100m`); unset is only ever unset."""
    return a == b if a is None or b is None else qty(a) == qty(b)


def no_room(e: ApiException) -> str | None:
    """The API server's refusal of a resize its pod's node can never fit (Kubernetes 1.35+
    says so at once, where 1.33 marks the pod's resize Infeasible), its message; else None."""
    message = why(e).split(": ", 1)[-1]
    return message if e.status == 403 and "enough allocatable" in message else None


def why(e: ApiException) -> str:
    """The API server's own message, short: never more than it said."""
    try:
        message = json.loads(e.body or "{}").get("message") or e.reason
    except (ValueError, AttributeError):
        message = e.reason
    return f"{e.status}: {message}"[:300]


def passing(e: ApiException) -> bool:
    """A failure that may be gone next minute: the network's, a 429 or the server's own."""
    return not e.status or e.status == 429 or e.status >= 500


def single() -> None:
    """The Kubernetes clients made from now on try each call once: the Actuator's own
    minute is the retry. Their default retries a read that timed out three times, so a call
    to an API server that never answers held the minute four timeouts long (found in
    12.9's live check: no pull for almost four minutes, the Kill switch unheard)."""
    cfg = client.Configuration.get_default_copy()
    cfg.retries = 0
    client.Configuration.set_default(cfg)


class Calm:
    """A Kubernetes API whose network failures (urllib3's, which its client lets through)
    are ApiExceptions as its refusals are, so the handling of one covers both and none ends
    the Actuator's minute; and no call waits forever (slice 12.9a)."""

    def __init__(self, api: Any) -> None:
        self.api = api

    def __getattr__(self, name: str) -> Any:
        call = getattr(self.api, name)

        def calm(*args: Any, **kw: Any) -> Any:
            kw.setdefault("_request_timeout", API_TIMEOUT)
            try:
                return call(*args, **kw)
            except urllib3.exceptions.HTTPError as e:
                raise ApiException(status=0, reason=type(e).__name__) from e

        return calm


class Apps:
    """AppsV1Api with Argo Rollouts beside its own kinds (slice 12.8b): a Rollout read as
    a Deployment, its template its own or its `workloadRef` Deployment's."""

    def __init__(self, apps: Any, custom: Any, batch: Any = None) -> None:
        self.apps, self.custom, self.batch, self.decoder = apps, custom, batch, client.ApiClient()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.apps, name)

    def shaped(self, r: dict[str, Any]) -> Any:
        spec = r.get("spec") or {}
        ref = spec.get("workloadRef") or {}
        if ref.get("kind") == "Deployment":
            d = self.apps.read_namespaced_deployment(ref.get("name"), r["metadata"]["namespace"])
            on = self.decoder.sanitize_for_serialization(d.spec)  # type: ignore[no-untyped-call]
            spec = {
                **spec,
                "template": on["template"],
                "selector": spec.get("selector") or on["selector"],
            }
        # its status left out; its spec's own fields (a canary strategy) a Deployment ignores
        body = json.dumps({"metadata": r.get("metadata"), "spec": spec})
        try:
            return self.decoder.deserialize(body, "V1Deployment", None)
        except ValueError as e:  # no template: a workloadRef of another kind, or none
            raise ApiException(status=422, reason=f"not read as a Deployment: {e}") from e

    def read_namespaced_rollout(self, name: str, ns: str) -> Any:
        return self.shaped(self.custom.get_namespaced_custom_object(*ARGO, ns, "rollouts", name))

    def list_namespaced_rollout(self, ns: str) -> Any:
        """Their metadata only, all the pause annotation needs: one Rollout that can't be
        shaped never hides another's pause."""
        found = self.custom.list_namespaced_custom_object(*ARGO, ns, "rollouts")
        metas = [json.dumps(r.get("metadata") or {}) for r in found.get("items") or []]
        return SimpleNamespace(
            items=[
                SimpleNamespace(metadata=self.decoder.deserialize(m, "V1ObjectMeta", None))
                for m in metas
            ]
        )

    # a CronJob's and its Jobs' (slice 12.8c), from BatchV1Api
    def read_namespaced_cron_job(self, name: str, ns: str) -> Any:
        return self.batch.read_namespaced_cron_job(name, ns)

    def list_namespaced_cron_job(self, ns: str) -> Any:
        return self.batch.list_namespaced_cron_job(ns)

    def list_namespaced_job(self, ns: str) -> Any:
        return self.batch.list_namespaced_job(ns)


def template_of(d: Any, kind: str) -> Any:
    """The pod template of a workload read with `read`: a CronJob's is its Jobs'."""
    return (d.spec.job_template.spec if kind == "CronJob" else d.spec).template


def read(apps: Any, kind: str, name: str, ns: str) -> Any:
    """The workload `kind`/`name` (one of KINDS) from the API server."""
    return getattr(apps, f"read_namespaced_{KINDS[kind]}")(name, ns)


def pods_of(core: Any, apps: Any, d: Any, kind: str) -> list[Any]:
    """The workload's live pods, however its selector reads: a Deployment's or Rollout's
    are its own ReplicaSets', a StatefulSet's or DaemonSet's its own (slice 12.8a). A CronJob's
    none: they are never resized in place, the webhook gives its next run's pods the hold
    (slice 12.8c)."""
    if kind == "CronJob":
        return []
    ns = d.metadata.namespace
    labels = ",".join(f"{k}={v}" for k, v in sorted((d.spec.selector.match_labels or {}).items()))
    if kind in ("Deployment", "Rollout"):
        mine = {
            rs.metadata.name
            for rs in apps.list_namespaced_replica_set(ns, label_selector=labels).items
            if any(o.uid == d.metadata.uid for o in rs.metadata.owner_references or [])
        }

        def own(o: Any) -> bool:
            return bool(o.kind == "ReplicaSet" and o.name in mine)
    else:

        def own(o: Any) -> bool:
            return bool(o.uid == d.metadata.uid)

    return [
        p
        for p in core.list_namespaced_pod(ns, label_selector=labels).items
        if any(own(o) for o in p.metadata.owner_references or [])
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


def vpa_mode(custom: Any, ns: str, kind: str, name: str) -> str | None:
    """The mode of a VPA that changes this workload's pods, or None (none, or `Off`)."""
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
        if ref.get("kind") == kind and ref.get("name") == name:
            mode = (spec.get("updatePolicy") or {}).get("updateMode") or "Auto"
            if mode != "Off":
                return str(mode)
    return None


def hpa_resources(autoscaling: Any, ns: str, kind: str, name: str, container: str) -> set[str]:
    """The resources an HPA of this workload scales on by utilization: a request it
    divides by, so the Actuator leaves it alone. An HPA without metrics means cpu."""
    out: set[str] = set()
    for h in autoscaling.list_namespaced_horizontal_pod_autoscaler(ns).items:
        ref = h.spec.scale_target_ref
        if ref.kind != kind or ref.name != name:
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
    eviction: str = "off",
    left: list[str] | None = None,
) -> tuple[Actuation | None, dict[str, Any]]:
    """Start resizing `w`'s container in place on its workload's pods (slice 12.3): the
    pre-checks, then one canary pod. An Actuation when it ends here (skipped or failed),
    None while it rolls; and what to remember of it, empty when Automation's churn rule
    leaves nothing to change. `old`: the hold a new Sizing replaces (None: catching up)."""
    set_to: dict[str, str] = {}
    template_had: dict[str, str | None] = {}  # its template's requests then: a change hands back
    notes: list[str] = []

    def done(outcome: Outcome, pods: int, reason: str) -> tuple[Actuation, dict[str, Any]]:
        values = {r: float(qty(q)) for r, q in set_to.items()}
        a = Actuation(
            **w.model_dump(exclude={"cpu", "memory", "again"}),
            outcome=outcome,
            pods=pods,
            reason=(reason + "".join(notes))[:1000],
            at=at,
            **values,
        )
        kept = {"requests": set_to, "template": template_had}
        return a, {"run_id": w.run_id, "outcome": outcome, **kept, "at": at}

    def failed(e: ApiException, reason: str) -> tuple[Actuation, dict[str, Any]]:
        a, held = done("failed", 0, reason)
        if passing(e):
            held["passing"] = True  # nothing changed, and it may work next minute (12.9b)
        return a, held

    if w.kind not in KINDS:
        return done("skipped", 0, f"a {w.kind} is not resized")
    try:
        d = read(apps, w.kind, w.name, w.namespace)
    except ApiException as e:
        if e.status == 404:
            return done("skipped", 0, f"no such {w.kind}")
        return failed(e, f"reading the {w.kind}: {why(e)}")
    containers = template_of(d, w.kind).spec.containers
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
        mode = vpa_mode(custom, w.namespace, w.kind, w.name)
        if mode:
            return done("skipped", 0, f"a VPA in mode {mode} sizes it")
        scaled = hpa_resources(autoscaling, w.namespace, w.kind, w.name, w.container)
        for r in sorted(scaled & set(set_to)):
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
        if w.kind == "CronJob":  # through the webhook only (slice 12.8c): its next run
            runs = d.spec.job_template.spec.parallelism or 1
            why_not = quota_breach(core, w.namespace, set_to, asked, runs)
            if why_not:
                return done("skipped", 0, why_not)
            a, held = done("applied", 0, "held for its next run's pods, given them as they start")
            held["first_run"] = {"after": at, "until": at + RUN_WATCH}
            if lowered:
                held["lowered_at"] = at
            if deferred:
                held["deferred"] = deferred
            return a, held
        pods = pods_of(core, apps, d, w.kind)
        if not pods:
            return done("skipped", 0, "no live pods")
        why_not = quota_breach(core, w.namespace, set_to, asked, len(pods))
        if why_not:
            return done("skipped", 0, why_not)
    except ApiException as e:  # a namespace its RoleBinding misses: the others still go on
        return failed(e, f"checking it: {why(e)}")
    todo = [
        p for p in pods if needs(p, w.container, set_to) and p.metadata.name not in (left or [])
    ]
    if not todo:
        return done("skipped", 0, f"all {len(pods)} pods already have these requests")
    room = None
    try:
        resize(core, todo[0], w.container, set_to)
    except ApiException as e:
        room = no_room(e)
        if room is None or (eviction == "off" and w.kind != "DaemonSet"):  # off: failed at once
            return failed(e, f"{todo[0].metadata.name}: {why(e)}")
    _, held = done("applied", 1, "")
    held |= {
        "outcome": "rolling",
        # the canary, and each pod that already has them (a catch-up's others, whose old
        # restarts are no news: slice 12.9a), counted from now
        "pods": {
            p.metadata.name: baseline(p, w.container, at)
            if p is todo[0]
            else {"restarts": restarts_of(p, w.container)}  # not resized now: no NotReady rule
            for p in pods
            if p is todo[0] or not needs(p, w.container, set_to)
        },
        "pod": todo[0].metadata.name,
        "since": at,
        "canary_until": at + CANARY_SECONDS,
        "resized": 1,
        "notes": "".join(notes),
    }
    if room:  # its node can never fit it: evicted in a window, as one Infeasible (slice 12.7)
        held["no_room"] = room
    if lowered:
        held["lowered_at"] = at
    if deferred:  # an approval of this run still applies them
        held["deferred"] = deferred
    return None, held


def advance(
    core: Any,
    apps: Any,
    key: str,
    h: dict[str, Any],
    now: float,
    eviction: str = "off",
    policy: Any = None,
) -> Actuation | None:
    """One minute of a rolling resize: wait for its current pod, then (after the canary's
    10 minutes) resize the next one. An Actuation once it ends: applied when every live pod
    has the requests, failed when a pod's resize is Infeasible or not done in 10 minutes.
    With eviction on (slice 12.7) an Infeasible pod is evicted instead, when `eviction` is
    open, its replacement getting the requests from the webhook; until then it waits. Not
    a pod `unevictable` names: that still fails. A DaemonSet's pod whose node has no room is
    left as it runs instead (slice 12.8a), the rollout failing only when every pod is.
    `policy` is a PolicyV1Api."""
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
    if "evicted" in h:
        return replaced(core, apps, key, h, now, end)
    try:
        p = core.read_namespaced_pod(pod, ns)
    except ApiException as e:
        if e.status != 404:
            log.warning("reading %s/%s: %s", ns, pod, why(e))
            return None
        p = None  # gone: its replacement is one of the pods still to do
    if p is not None and not p.metadata.deletion_timestamp:
        state, message = resize_state(p, container, set_to)
        if "no_room" in h:  # the API server refused its resize: no room on its node, ever
            state, message = "infeasible", h["no_room"]
        late = now - h["since"] >= WAIT_SECONDS
        if kind == "DaemonSet" and (state == "infeasible" or (state == "deferred" and late)):
            leave(core, p, key, h, message)  # its node has no room: the others go on
            resized, notes = h["resized"], h["notes"]
        elif state == "infeasible":
            never = None if eviction == "off" else unevictable(apps, policy, ns, kind, name, p)
            if eviction == "off" or never:
                why_ = f"{pod}: Infeasible: {message}; {resized - 1} other pods resized"
                return end("failed", why_ + (f"; {never}" if never else ""))
            if eviction == "open":
                return evict(core, apps, key, h, now, message, end)
            wait(core, key, h, "window", f"{pod}: Infeasible: {message}; it waits to be "
                 "evicted, in an eviction window and one pod at a time")  # fmt: skip
            return None
        elif state != "done":
            if not late:
                return None
            return end("failed", f"{pod}: {state} for {WAIT_SECONDS // 60} minutes: {message}")
    if now < h["canary_until"]:
        return None
    try:
        pods = pods_of(core, apps, read(apps, kind, name, ns), kind)
        left = h.get("left") or []
        todo = [x for x in pods if needs(x, container, set_to) and x.metadata.name not in left]
        if not pods:  # scaled to zero meanwhile: held, and its webhook gives them to new pods
            return end("applied", f"{resized} pods resized in place, then none left to resize")
        if not todo:
            if all(needs(x, container, set_to) for x in pods):  # every pod left: none has room
                return end("failed", f"no node of its {len(pods)} pods has room for them")
            return end("applied", f"{resized} of {len(pods)} pods resized in place, one at a time")
        resize(core, todo[0], container, set_to)
    except ApiException as e:
        room = no_room(e)
        if room is None and passing(e) and now - h.setdefault("stalled", now) < WAIT_SECONDS:
            log.warning("%s waits: %s", key, why(e))  # tried again next minute, 10 at most
            return None
        if room is None or (eviction == "off" and kind != "DaemonSet"):
            return end("failed", f"resizing its next pod: {why(e)}")
        h["no_room"] = room
    h.pop("stalled", None)
    if resized == 0:  # the canary was left: the next pod resized is the canary
        h["canary_until"] = now + CANARY_SECONDS
    h.update(pod=todo[0].metadata.name, since=now, resized=resized + 1)
    h.setdefault("pods", {})[todo[0].metadata.name] = baseline(todo[0], container, now)
    return None


def leave(core: Any, p: Any, key: str, h: dict[str, Any], message: str) -> None:
    """A DaemonSet's pod whose node has no room for the requests (slice 12.8a): its pending
    resize undone (back to what the kubelet allocated it) but for the requests it lowers,
    which always fit and are set in place; the pod left out of this rollout and of
    catch-ups, said in an Event; the other pods go on."""
    ns, kind, name, container = key.split("/")
    pod = p.metadata.name
    st = container_status(p, container)
    allocated = (st.resources.requests if st and st.resources else None) or {}
    lower = {
        r: q for r, q in h["requests"].items() if r in allocated and qty(q) < qty(allocated[r])
    }
    pending = h.pop("no_room", None) is None  # refused at once (Kubernetes 1.35+): nothing is
    back = {r: allocated[r] for r in h["requests"] if r in allocated} if pending else {}
    try:
        if back or lower:
            resize(core, p, container, back | lower)
    except ApiException as e:
        log.warning("resizing %s back: %s", pod, why(e))
    h.setdefault("left", []).append(pod)
    (h.get("pods") or {}).pop(pod, None)
    h["resized"] -= 1
    if h["resized"] == 0:  # the canary: no wait on it, the next pod resized is the canary
        h["canary_until"] = 0.0
    h["notes"] = h.get("notes", "") + f"; {pod} left without its raise: its node has no room"
    said = f"{pod} left without its raise: its node has no room for {texts(h['requests'])}"
    said += f" ({message})" + (f"; lowered in place to {texts(lower)}" if lower else "")
    log.info("%s: %s", key, said)
    post(core, ns, ("apps/v1", kind, name), "PodLeft", said, False)


def selects(s: Any, labels: dict[str, str]) -> bool:
    """A label selector `s` matches `labels`: a null one matches nothing, an empty one all."""
    if s is None:
        return False
    for e in s.match_expressions or []:
        has, values = e.key in labels, e.values or []
        if not {
            "In": labels.get(e.key) in values,
            "NotIn": labels.get(e.key) not in values,
            "Exists": has,
            "DoesNotExist": not has,
        }.get(e.operator, False):
            return False
    return all(labels.get(k) == v for k, v in (s.match_labels or {}).items())


def unevictable(apps: Any, policy: Any, ns: str, kind: str, name: str, p: Any) -> str | None:
    """Why the workload's pod `p` is never evicted, if it is not: not a Deployment's (a
    StatefulSet's keeps its state, a DaemonSet's would start again on its node), one replica
    (eviction would stop it) or no PodDisruptionBudget covering it (nothing would keep
    enough pods up). A read that fails: never evicted either."""
    if kind != "Deployment":
        return f"a {kind}'s pod is never evicted"
    try:
        replicas = apps.read_namespaced_deployment(name, ns).spec.replicas
        if (1 if replicas is None else replicas) < 2:
            return "it has one replica, so it is never evicted"
        budgets = policy.list_namespaced_pod_disruption_budget(ns).items
    except ApiException as e:
        return f"not evicted: checking it: {why(e)}"
    labels = p.metadata.labels or {}
    if not any(selects(b.spec.selector, labels) for b in budgets):
        return "no PodDisruptionBudget covers it, so it is never evicted"
    return None


def is_ready(p: Any) -> bool:
    return any(c.type == "Ready" and c.status == "True" for c in (p.status.conditions or []))


def wait(core: Any, key: str, h: dict[str, Any], why_: str, message: str) -> None:
    """The rollout waits to evict its Infeasible pod: said once in an Event per reason."""
    if h.get("waiting") != why_:
        h["waiting"] = why_
        ns, kind, name, _ = key.split("/")
        log.info("%s waits: %s", key, message)
        post(core, ns, ("apps/v1", kind, name), "EvictionWaiting", message, False)


def evict(
    core: Any, apps: Any, key: str, h: dict[str, Any], now: float, message: str, end: Ending
) -> Actuation | None:
    """Evict the rollout's Infeasible pod through the Eviction API, so PodDisruptionBudgets
    hold (slice 12.7): its ReplicaSet starts a replacement, which the webhook gives the
    requests. A budget that allows no disruption now: it waits."""
    ns, kind, name, _ = key.split("/")
    pod = h["pod"]
    try:
        before = [p.metadata.name for p in pods_of(core, apps, read(apps, kind, name, ns), kind)]
    except ApiException as e:
        log.warning("listing %s's pods to evict %s: %s", key, pod, why(e))
        return None
    h["evicted"] = {"pod": pod, "at": now, "before": before}  # first: the webhook reads it
    body = client.V1Eviction(metadata=client.V1ObjectMeta(name=pod, namespace=ns))
    try:
        core.create_namespaced_pod_eviction(pod, ns, body)
    except ApiException as e:
        del h["evicted"]
        if e.status == 429:
            wait(core, key, h, "budget", f"{pod}: Infeasible: {message}; a PodDisruptionBudget "
                 "allows no eviction now")  # fmt: skip
            return None
        return end("failed", f"evicting {pod}: {why(e)}")
    h.pop("waiting", None)
    h["evicted_at"] = now
    h["notes"] = h.get("notes", "") + f"; {pod} evicted, its resize Infeasible"
    said = f"{pod} evicted: its resize was Infeasible ({message}); its replacement starts with "
    log.info("%s: %s", key, said + texts(h["requests"]))
    post(core, ns, ("apps/v1", kind, name), "PodEvicted", said + texts(h["requests"]), False)
    return None


def replacements(d: Any, pods: list[Any], ev: dict[str, Any]) -> list[Any] | None:
    """The pods started since the eviction `ev`; None when none is owed: none started and
    the Deployment already has as many live pods as it wants (an HPA scaled it down)."""
    new = [p for p in pods if p.metadata.name not in ev["before"]]
    wants = d.spec.replicas if d.spec.replicas is not None else 1
    return None if not new and len(pods) >= wants else new


def replaced(
    core: Any, apps: Any, key: str, h: dict[str, Any], now: float, end: Ending
) -> Actuation | None:
    """Whether the evicted pod's replacement is up with the requests: then it stands for
    the evicted pod in the rollout (a canary's 10 minutes start again). Not Ready in 10
    minutes is trouble(): a rollback."""
    ns, kind, name, container = key.split("/")
    ev = h["evicted"]
    try:
        d = read(apps, kind, name, ns)
        pods = pods_of(core, apps, d, kind)
    except ApiException as e:
        log.warning("watching %s's replacement: %s", key, why(e))
        return None
    new = replacements(d, pods, ev)
    if new is None:  # none owed: the rollout goes on with the pods it has
        del h["evicted"]
        return None
    up = [p for p in new if is_ready(p)]
    if not up:
        return None
    p = up[0]
    if needs(p, container, h["requests"]):
        return end(
            "failed",
            f"{p.metadata.name}, replacing evicted {ev['pod']}, started from its template",
        )
    del h["evicted"]
    h.pop("no_room", None)
    h.setdefault("pods", {})[p.metadata.name] = baseline(p, container, now)
    h.update(pod=p.metadata.name, since=now)
    if h["resized"] == 1:
        h["canary_until"] = now + CANARY_SECONDS
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
    a pod it resized that has been NotReady for 2 minutes since, or an evicted pod's
    replacement not Ready in 10 minutes (slice 12.7). Throttling is not one."""
    ns, kind, name, container = key.split("/")
    try:
        d = read(apps, kind, name, ns)
        pods = pods_of(core, apps, d, kind)
    except ApiException as e:
        log.warning("watching %s: %s", key, why(e))
        return None
    ev = h.get("evicted")
    new = replacements(d, pods, ev) if ev else []
    if ev and now - ev["at"] >= WAIT_SECONDS and new is not None and not any(map(is_ready, new)):
        return f"{ev['pod']} evicted: no replacement Ready in {WAIT_SECONDS // 60} minutes"
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
        if "at" not in mine or p.metadata.name not in seen:
            continue  # a new pod may take its time to be Ready; only one it resized counts
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


def first_run(core: Any, apps: Any, key: str, h: dict[str, Any], now: float) -> str | None:
    """Why a CronJob's first run under the requests held as `h` (slice 12.8c) is a reason
    to roll back, or None: a pod of it with them Failed or OOM-killed. That run is the first
    Job, created since, whose pods got them (one started from its template, the webhook
    missing it, is not); it ends the watch once it finished or is gone, as do 7 days
    without one."""
    ns, kind, name, container = key.split("/")
    run = h["first_run"]

    def pods(job: str) -> list[Any]:  # Succeeded and Failed ones too: pods_of drops them
        selector = f"batch.kubernetes.io/job-name={job}"
        return list(core.list_namespaced_pod(ns, label_selector=selector).items)

    try:
        cj = read(apps, kind, name, ns)
        jobs = sorted(
            (
                j
                for j in apps.list_namespaced_job(ns).items
                if any(o.uid == cj.metadata.uid for o in j.metadata.owner_references or [])
                and j.metadata.creation_timestamp.timestamp() >= run["after"]
            ),
            key=lambda j: j.metadata.creation_timestamp,
        )
        if "job" not in run:
            chosen = next(
                (
                    j.metadata.name
                    for j in jobs
                    if any(not needs(p, container, h["requests"]) for p in pods(j.metadata.name))
                ),
                None,
            )
            if chosen is None:
                if now >= run["until"]:
                    h.pop("first_run")  # no run in 7 days: kept, no longer watched
                return None
            run["job"] = chosen
        job = next((j for j in jobs if j.metadata.name == run["job"]), None)
        for p in pods(run["job"]) if job else []:
            if needs(p, container, h["requests"]):
                continue  # from its template: not the Actuator's doing
            st = container_status(p, container)
            for state in (st.state, st.last_state) if st else ():
                if state and state.terminated and state.terminated.reason == "OOMKilled":
                    return f"{p.metadata.name}: {container} was OOM-killed"
            if p.status.phase == "Failed":
                return f"{p.metadata.name} Failed"
    except ApiException as e:
        log.warning("watching %s: %s", key, why(e))
        return None
    finished = job is None or any(
        c.type in ("Complete", "Failed") and c.status == "True"
        for c in (job.status.conditions if job.status else None) or []
    )
    if finished:
        h.pop("first_run")  # its first run is over: kept, no longer watched
    return None


def rollback(core: Any, apps: Any, key: str, h: dict[str, Any], why_: str, now: float) -> Actuation:
    """Every pod with the Actuator's requests back to its template's, in place and at once;
    then no new Sizing of that container for 24 hours, doubling with each rollback in 7 days."""
    rollbacks = [t for t in h.get("rollbacks") or [] if now - t < ROLLBACKS_FOR] + [now]
    until = now + BACKOFF_SECONDS * 2 ** (len(rollbacks) - 1)
    a = put_back(core, apps, key, h, "rolled_back", why_, now)
    h.update(rollbacks=rollbacks, backoff_until=until)
    when = datetime.fromtimestamp(until, UTC)
    a.reason = f"{a.reason}; no new Sizing of it until {when:%Y-%m-%d %H:%M} UTC"[:1000]
    return a


def put_back(
    core: Any, apps: Any, key: str, h: dict[str, Any], outcome: Outcome, why_: str, now: float
) -> Actuation:
    """Every pod with the requests held as `h` back to its template's, in place and at once
    (a request the template doesn't set left as it is); `h` is no longer held."""
    ns, kind, name, container = key.split("/")
    had = h.get("template") or {}
    back = {r: had[r] for r in h["requests"] if had.get(r) is not None}
    unset = sorted(r for r in h["requests"] if had.get(r) is None)
    done, refused, stuck = 0, [], 0
    try:
        pods = pods_of(core, apps, read(apps, kind, name, ns), kind)
    except ApiException as e:
        pods, refused = [], [f"listing its pods: {why(e)}"]
    ev = h.pop("evicted", None)  # first: the webhook gives its next replacement nothing
    for p in pods:
        if ev and p.metadata.name not in ev["before"] and p.status.phase == "Pending":
            # an evicted pod's replacement, unscheduled at the held size: started again from
            # its template, the hold gone (a Pending pod's eviction ignores budgets)
            body = client.V1Eviction(
                metadata=client.V1ObjectMeta(name=p.metadata.name, namespace=ns)
            )
            try:
                core.create_namespaced_pod_eviction(p.metadata.name, ns, body)
                stuck += 1
            except ApiException as e:
                refused.append(f"evicting {p.metadata.name}: {why(e)}")
            continue
        if back and not needs(p, container, h["requests"]):
            try:
                resize(core, p, container, back)
                done += 1
            except ApiException as e:
                refused.append(f"{p.metadata.name}: {why(e)}")
    for k in ROLLOUT + WATCHED:
        h.pop(k, None)
    h["outcome"] = outcome
    if kind == "CronJob":  # never resized in place (slice 12.8c)
        reason = f"{why_}: its next run's pods start from its template, not {texts(h['requests'])}"
    else:
        reason = f"{why_}: {done} pods back from {texts(h['requests'])}"
        if back:
            reason += f" to their template's {texts(back)}"
        if unset:
            reason += f" ({unset} left: the template sets none)"
    if stuck:
        reason += f"; {stuck} Pending replacement evicted to start from its template"
    if refused:
        reason += f"; {len(refused)} refused, first {refused[0]}"
        if back and kind != "CronJob":
            h["unfinished"] = True
            reason += "; tried again each minute"
    return Actuation(
        namespace=ns,
        kind=kind,
        name=name,
        container=container,
        run_id=h["run_id"],
        outcome=outcome,
        pods=done,
        reason=reason[:1000],
        at=now,
        **{r: float(qty(q)) for r, q in back.items()},
    )


def undo(h: dict[str, Any]) -> dict[str, Any]:
    """What a put back still to finish needs of the hold `h`, kept when a Sizing that
    changes nothing (skipped, failed) takes its place."""
    return {k: h[k] for k in ("unfinished", "requests", "template") if h.get("unfinished")}


def finish(core: Any, apps: Any, key: str, h: dict[str, Any]) -> None:
    """A Rollback or Revert that some pod refused (slice 12.9a), again: each pod still with
    the requests held as `h` back to its template's, until none refuses. A template that no
    longer asks what it did then is a person's: theirs, and nothing more to undo. Only a
    refusal that may pass is tried again; another is the API server's verdict, said once."""
    ns, kind, name, container = key.split("/")
    had = h.get("template") or {}
    back = {r: had[r] for r in h["requests"] if had.get(r) is not None}
    pods = []
    try:
        d = read(apps, kind, name, ns)
        c = next((c for c in template_of(d, kind).spec.containers if c.name == container), None)
        if c is not None and all(same(requests_of(c).get(r), q) for r, q in back.items()):
            pods = pods_of(core, apps, d, kind)
    except ApiException as e:
        if e.status != 404:  # 404: the workload is gone, and its pods with it
            log.warning("putting %s back: %s", key, why(e))
            return
    again = False
    for p in pods:
        if needs(p, container, h["requests"]):
            continue
        try:
            resize(core, p, container, back)
        except ApiException as e:  # one pod's refusal never keeps the others waiting
            if passing(e):
                again = True
                log.warning("putting %s back: %s", p.metadata.name, why(e))
            elif e.status != 404:  # its verdict (a pod gone meanwhile aside): not tried again
                log.error("%s keeps %s: %s", p.metadata.name, texts(h["requests"]), why(e))
    if not again:
        log.info("%s: no pod left to put back", key)
        h.pop("unfinished")


EVENTS = {
    "applied": "SizingApplied",
    "skipped": "SizingSkipped",
    "failed": "SizingFailed",
    "handed_back": "HandedBack",
    "rolled_back": "SizingRolledBack",
    "reverted": "SizingReverted",
}


GONE = dict.fromkeys(("handed_back", "rolled_back", "reverted"), "back to its template")


def event(core: Any, a: Actuation, h: dict[str, Any] | None = None) -> None:
    """A Kubernetes Event on the workload, so `kubectl describe` shows what was done;
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
    api_version = API.get(kind, api_version)
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
    """The JSON Patch giving a new pod of a workload the requests applied to it: only
    where its container still asks what the template asked then (a person's change wins),
    never above its limit, never in kube-* or the Actuator's own namespace, never for a
    paused workload (`ns/kind/name` in `paused`). A DaemonSet's pod gets only requests
    lower than its template's (slice 12.8a): it must fit on whatever node it starts; a raise
    reaches it in place, where its node has room. An Argo Rollout's pod is told by its
    `rollouts-pod-template-hash` label (slice 12.8b)."""
    ns = req.get("namespace") or ""
    if req.get("operation") != "CREATE" or ns == own or ns.startswith("kube-"):
        return []
    pod = req.get("object") or {}
    meta = pod.get("metadata") or {}
    owners = {o.get("kind"): o.get("name", "") for o in meta.get("ownerReferences") or []}
    labels = meta.get("labels") or {}
    kind = next((k for k in ("StatefulSet", "DaemonSet") if owners.get(k)), "Deployment")
    name = owners.get(kind, "")
    # a CronJob's run, its Job named for its minute (slice 12.8c); a lone Job's pod falls
    # through to a Deployment's, which its missing `pod-template-hash` refuses
    run = re.fullmatch(r"(.+)-(\d+)", owners.get("Job", ""))
    if run and not -5 <= time.time() / 60 - int(run.group(2)) <= RUN_AGE:
        run = None  # digits that are no recent minute: a lone Job's own name (slice 12.9b)
    if kind == "Deployment" and run:
        kind, name = "CronJob", run.group(1)
    elif kind == "Deployment" and "rollouts-pod-template-hash" in labels:
        kind = "Rollout"  # Argo's ReplicaSet, named and labelled as a Deployment's (12.8b)
    if kind in ("Deployment", "Rollout"):
        hashed = labels.get(
            "rollouts-pod-template-hash" if kind == "Rollout" else "pod-template-hash"
        )
        rs = owners.get("ReplicaSet", "")
        if not hashed or not rs.endswith(f"-{hashed}"):
            return []  # not a workload's pod it resizes
        name = rs.removesuffix(f"-{hashed}")
    if f"{ns}/{kind}/{name}" in paused:
        return []
    ops: list[Any] = []
    for i, c in enumerate((pod.get("spec") or {}).get("containers") or []):
        h = held.get(f"{ns}/{kind}/{name}/{c.get('name')}")
        if not h or (h.get("outcome") != "applied" and "evicted" not in h):
            continue  # applied, or rolling with a pod evicted for these requests (slice 12.7)
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
            if kind == "DaemonSet" and not (requests.get(r) and qty(q) < qty(requests[r])):
                continue  # a raise: in place only, where its node has room
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
    stored: str = ""  # its state() as last saved
    reverting: frozenset[str] | set[str] = frozenset()  # containers with a Revert in this pull
    killed: bool = False
    autoscaling: Any = None  # AutoscalingV2Api: HPAs (slice 12.3)
    custom: Any = None  # CustomObjectsApi: VPAs
    paused: frozenset[str] = frozenset()  # `ns/kind/name` of the workloads a person paused
    unanswered: float | None = None  # since when the Hub hasn't answered
    told: bool = False  # the Event that it hasn't is out
    eviction: str = "off"  # the Hub's last word on eviction (slice 12.7)
    policy: Any = None  # PolicyV1Api: PodDisruptionBudgets, read before an eviction

    def load(self) -> None:
        try:
            cm = self.core.read_namespaced_config_map(CONFIGMAP, self.namespace)
        except ApiException as e:
            if e.status != 404:
                raise
            return
        self.held = json.loads((cm.data or {}).get(KEY) or "{}")
        try:  # what it can't read (another version's) is dropped, never its holds with it
            state = json.loads((cm.data or {}).get(STATE) or "{}")
            self.killed = bool(state.get("killed", False))
            for a in state.get("unsent") or []:
                try:
                    self.unsent.append(Actuation(**a))
                except (ValidationError, TypeError) as e:
                    log.error("a stored report dropped: %s", type(e).__name__)
        except (ValueError, AttributeError) as e:
            log.error("reading %s: %s", STATE, type(e).__name__)
        self.stored = self.state()

    def state(self) -> str:
        """What a restart must not forget beside its holds (slice 12.9b): the Kill switch as
        the Hub last said it (the Hub may be unreachable then), and the reports not yet taken."""
        unsent = [a.model_dump() for a in self.unsent[-KEPT_REPORTS:]]
        return json.dumps({"killed": self.killed, "unsent": unsent}, sort_keys=True)

    def save(self) -> None:
        body = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(name=CONFIGMAP),
            data={KEY: json.dumps(self.held, sort_keys=True), STATE: (state := self.state())},
        )
        try:
            try:
                self.core.replace_namespaced_config_map(CONFIGMAP, self.namespace, body)
            except ApiException as e:
                if e.status != 404:
                    raise
                self.core.create_namespaced_config_map(self.namespace, body)
            self.stored = state
        except ApiException as e:  # pods already match: a restart finds nothing to change
            log.error("saving %s: %s", CONFIGMAP, why(e))

    def pull(self) -> Desired | None:
        try:
            r = self.http.get("/actuator/desired", params={"kinds": ",".join(KINDS)})
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
        done: list[Actuation] = []
        undoing = any("unfinished" in h for h in self.held.values())  # saved once finished too
        try:
            done += self.hand_back()
            if not self.killed:  # the Actuator undoes its own harm, the Hub reachable or not
                done += self.watch()
                for key, h in self.held.items():
                    if h.get("unfinished"):
                        finish(self.core, self.apps, key, h)
            if desired is not None and not self.killed:  # the Hub's word: rollouts go on
                self.eviction = desired.eviction
                self.reverting = {
                    "/".join((u.namespace, u.kind, u.name, u.container)) for u in desired.reverts
                }
                done += self.revert(desired.reverts) + self.advance(desired.eviction)
                done += self.act(desired.sizings, desired.automated)
                done += self.catch_up()
        except Exception:  # its own bug: what it changed before is kept, not done twice
            self.unsent += done
            self.save()
            self.send()  # a Rollback before the bug still reaches the Hub
            raise
        rolling = any(
            h.get("outcome") == "rolling" or "pods" in h or "first_run" in h
            for h in self.held.values()
        )
        self.unsent += done
        if done or rolling or undoing:
            self.save()  # before reporting: a restart sends again what the Hub didn't take
        self.send()

    def send(self) -> None:
        self.report()
        if self.state() != self.stored:  # taken (or refused): not sent again after a restart
            self.save()

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
        """Which workloads (`ns/kind/name`) a person paused, read again for each kind in each
        namespace it has keys in; one it can't list keeps what it knew."""
        paused: set[str] = set()
        for ns, kind in sorted({tuple(k.split("/")[:2]) for k in keys}):
            if kind not in KINDS:
                continue
            try:
                found = getattr(self.apps, f"list_namespaced_{KINDS[kind]}")(ns).items
            except ApiException as e:
                log.warning("reading %s's %ss: %s", ns, kind, why(e))
                paused |= {p for p in self.paused if p.startswith(f"{ns}/{kind}/")}
                continue
            paused |= {
                f"{ns}/{kind}/{d.metadata.name}"
                for d in found
                if (d.metadata.annotations or {}).get(PAUSE) == "true"
            }
        for p in sorted(paused ^ self.paused):
            log.warning("%s is %s", p, "paused" if p in paused else "no longer paused")
        self.paused = frozenset(paused)

    def is_paused(self, key: str) -> bool:
        return "/".join(key.split("/")[:3]) in self.paused

    def watch(self) -> list[Actuation]:
        """Roll back each Sizing that made its pods unhealthy within its hour (slice 12.4)."""
        out, now = [], time.time()
        for key, h in self.held.items():
            if "first_run" in h:  # a CronJob's (slice 12.8c)
                reason = first_run(self.core, self.apps, key, h, now)
                if reason:
                    a = rollback(self.core, self.apps, key, h, reason, now)
                    log.warning("rolled back %s: %s", key, a.reason)
                    event(self.core, a, h)
                    out.append(a)
                continue
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

    def revert(self, undos: list[Undo]) -> list[Actuation]:
        """Each Revert newer than the last it did of that container (slice 12.6a): its pods
        back to their template's requests, held no more; reported even with nothing held,
        so the Hub knows it is done. A paused Deployment's waits."""
        out = []
        for u in undos:
            key = "/".join((u.namespace, u.kind, u.name, u.container))
            h = self.held.setdefault(key, {})
            if h.get("revert", -1) >= u.id or self.is_paused(key):
                continue
            h["revert"] = u.id
            why_ = f"reverted by the Operator ({u.id})"
            if h.get("outcome") in ("applied", "rolling", "failed") and h.get("requests"):
                a = put_back(self.core, self.apps, key, h, "reverted", why_, time.time())
            else:
                a = Actuation(
                    **u.model_dump(exclude={"id"}),
                    run_id=h.get("run_id", 0),
                    outcome="reverted",
                    pods=0,
                    reason=f"{why_}: nothing held",
                    at=time.time(),
                )
            log.info("reverted %s: %s", key, a.reason)
            event(self.core, a, h)
            out.append(a)
        return out

    def advance(self, eviction: str = "off") -> list[Actuation]:
        """Each rollout's minute. An eviction only when the window is open, no other evicted
        pod awaits its replacement, and the last eviction is 5 minutes old (slice 12.7)."""
        out = []
        for key, h in self.held.items():
            if h.get("outcome") == "rolling" and not self.is_paused(key):
                now, may = time.time(), eviction
                last = max((x.get("evicted_at", 0.0) for x in self.held.values()), default=0.0)
                busy = any("evicted" in x for x in self.held.values())
                if may == "open" and (busy or now - last < EVICT_EVERY):
                    may = "closed"
                a = advance(self.core, self.apps, key, h, now, may, self.policy)
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
                pods = pods_of(self.core, self.apps, read(self.apps, kind, name, ns), kind)
            except ApiException as e:
                log.warning("checking %s: %s", key, why(e))
                continue
            left = h.get("left") or []  # a DaemonSet's pods with no room on their node
            behind = [
                p.metadata.name
                for p in pods
                if needs(p, container, h["requests"]) and p.metadata.name not in left
            ]
            if not behind:
                continue
            values = {r: float(qty(q)) for r, q in h["requests"].items()}
            w = Wanted(
                run_id=h["run_id"], namespace=ns, kind=kind, name=name, container=container,
                cpu=values.get("cpu"), memory=values.get("memory"),
            )  # fmt: skip
            a, new = apply(
                self.core, self.apps, w, time.time(), self.autoscaling, self.custom,
                eviction=self.eviction, left=left,
            )  # fmt: skip
            if new.pop("passing", False):
                log.warning("%s waits to catch up: %s", key, a.reason if a else "")
                continue  # still held: tried again next minute
            carried = (
                *("rollbacks", "backoff_until", "watch_until", "lowered_at", "automated"),
                *("revert", "evicted_at", "left"),
            )
            kept = {k: h[k] for k in carried if k in h}
            watched = (new.get("pods") or {}) | (h.get("pods") or {})  # still watched: as it was
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
        """Each container it holds whose workload's template now asks other requests than
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
        ns, kind, name, container = key.split("/")
        try:
            d = read(self.apps, kind, name, ns)
        except ApiException as e:
            if e.status == 404:
                return f"no such {kind}"
            log.warning("reading %s: %s", key, why(e))  # the API server's trouble, no change
            return None
        c = next((c for c in template_of(d, kind).spec.containers if c.name == container), None)
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
            if self.is_paused(key) or key in self.reverting:
                continue  # waits: for the pause to lift; for a Revert still listed (12.9b)
            old = self.held.get(key, {})
            now = time.time()
            if "evicted" in old:
                continue  # its evicted pod's replacement first: 10 minutes at most
            if auto:
                if max(old.get("run_id", -1), old.get("seen", -1)) >= w.run_id:
                    continue
                rolling = old.get("outcome") == "rolling" and not old.get("waiting")
                if rolling or now < old.get("backoff_until", 0):
                    continue  # waits, unsaid: a new Sizing comes every hour
            elif old.get("refused") == w.run_id:
                continue  # said once: what it holds stays (slice 12.9a)
            elif old.get("run_id", -1) > w.run_id or (
                old.get("run_id") == w.run_id
                and not old.get("automated")
                and not (w.again and old.get("outcome") == "reverted")
            ):
                continue
            elif old.get("run_id") == w.run_id and old.get("outcome") in ("applied", "rolling"):
                # the run Automation holds, now approved
                if not old.get("deferred"):  # the same requests: approved as they are held
                    old.pop("automated")
                    continue
                if old.get("outcome") == "rolling":
                    continue  # what the churn rule left out goes once this rollout ends
            carried = ("rollbacks", "backoff_until", "lowered_at", "revert", "evicted_at")
            carry: dict[str, Any] = {k: old[k] for k in carried if k in old}
            a: Actuation | None
            if now < old.get("backoff_until", 0):
                until = datetime.fromtimestamp(old["backoff_until"], UTC)
                a = Actuation(
                    **w.model_dump(exclude={"cpu", "memory", "again"}),
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
                    **undo(old),
                }
            else:
                args = (self.core, self.apps, w, now, self.autoscaling, self.custom, old, auto)
                a, new = apply(*args, eviction=self.eviction)
                if new.pop("passing", False):  # tried again each minute, 10 at most
                    t = old.get("trying") or {}
                    if t.get("run") != w.run_id:
                        t = {"run": w.run_id, "since": now}
                    if now - t["since"] < WAIT_SECONDS:
                        log.warning("%s waits: %s", key, a.reason if a else "")
                        self.held[key] = {**old, "trying": t}
                        continue
                old.pop("trying", None)
                if not new:  # nothing moves enough: the churn rule
                    self.held[key] = {**old, "seen": w.run_id}
                    continue
                if auto and a is not None and a.outcome in ("skipped", "failed"):
                    # what it holds stays held; the same reason again goes unsaid
                    kept = old if old.get("outcome") == "applied" else carry | new | undo(old)
                    said = gist(old.get("unapplied") or "") == gist(a.reason)
                    self.held[key] = {**kept, "seen": w.run_id, "unapplied": a.reason}
                    if said:
                        continue
                elif (
                    a is not None
                    and a.outcome in ("skipped", "failed")
                    and old.get("outcome") in ("applied", "rolling", "failed")
                ):  # a refused approval: the one before stays held, and reverted by a Revert
                    self.held[key] = {**old, "refused": w.run_id}
                    a.reason = f"{a.reason}; run {old['run_id']}'s requests stay held"[:1000]
                else:
                    refused = a is not None and a.outcome in ("skipped", "failed")
                    self.held[key] = carry | new | ({"automated": True} if auto else {})
                    self.held[key] |= undo(old) if refused else {}
            if a is None:
                log.info("rolling %s: canary %s", key, self.held[key]["pod"])
                continue
            log.info("%s %s: %s", a.outcome, key, a.reason)
            event(self.core, a, {"automated": auto})
            out.append(a)
        return out


def main(s: ActuatorSettings) -> None:  # pragma: no cover - the cluster's own process
    config.load_incluster_config()  # type: ignore[no-untyped-call]
    single()
    core, custom = Calm(client.CoreV1Api()), Calm(client.CustomObjectsApi())
    apps = Apps(Calm(client.AppsV1Api()), custom, Calm(client.BatchV1Api()))
    check_version(client.VersionApi())
    cert, key = certificate(f"{WEBHOOK}.{s.namespace}.svc")
    headers = {"Authorization": f"Bearer {s.token.get_secret_value()}"}
    with httpx.Client(base_url=s.hub, headers=headers, timeout=15) as http:
        a = Actuator(http, core, apps, s.namespace)
        a.autoscaling, a.custom = Calm(client.AutoscalingV2Api()), custom
        a.policy = Calm(client.PolicyV1Api())
        a.load()
        serve(a, cert, key)
        try:  # until then the API server can't call it, and pods start unchanged
            trust(client.AdmissionregistrationV1Api(), cert)
        except ApiException as e:
            log.error("its webhook's caBundle: %s: new pods start from their template", why(e))
        log.info("actuator started: %d containers held", len(a.held))
        while True:
            try:
                a.step()
            except Exception:  # a bug in one minute's work: said, and the next still runs
                log.exception("this minute failed")
            time.sleep(s.interval)
