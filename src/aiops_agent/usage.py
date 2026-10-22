"""Workload usage for Sizings (slice 9.1): read-only, from each cluster's Prometheus.

The Hub queries Prometheus itself, with no model call. Prometheus does the time math
(`rate` handles counter resets, `max_over_time` keeps memory peaks between steps); this
module pools the samples of a Workload's pods per container, so a Sizing is per replica
whatever the replica count, and follows pod owners up to their Workload.

Every query carries the cluster's namespaces and label matchers: on a store shared by
several clusters or Contracts (Thanos, Mimir) nothing else may come back.
"""

import dataclasses
import math
import re
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import SecretStr

from aiops_agent.contracts import Contract, Prometheus

MAX_POINTS = 10_000  # Prometheus refuses a range query over 11,000 points per series
CONTAINERS = 'container!="",container!="POD"'  # cAdvisor's pod-level and pause series
REQUIRED = {  # metric -> what it gives a Sizing
    "container_cpu_usage_seconds_total": "CPU usage (cAdvisor)",
    "container_memory_working_set_bytes": "memory usage (cAdvisor)",
    "kube_pod_container_resource_requests": "requests (kube-state-metrics)",
    "kube_pod_owner": "pod owners (kube-state-metrics)",
}
OPTIONAL = {
    "kube_pod_container_resource_limits": "limits",
    "kube_replicaset_owner": "Deployments and Rollouts behind ReplicaSets",
    "kube_job_owner": "CronJobs behind Jobs",
    "kube_pod_container_status_last_terminated_reason": "OOM kills",
    "container_cpu_cfs_throttled_periods_total": "CPU throttling",
}
KSM = {m for m in (*REQUIRED, *OPTIONAL) if m.startswith("kube_")}


@dataclass(frozen=True)
class Target:
    """One cluster's metrics, scoped to its Contract's namespaces."""

    cluster: str
    url: str
    token: SecretStr | None
    labels: dict[str, str]
    namespaces: list[str]
    # kube-state-metrics scraped without honor_labels puts the pod's namespace in
    # exported_namespace (its own namespace wins `namespace`); check() finds out.
    ksm_namespace: str = "namespace"


def targets(contract: Contract) -> list[Target]:
    """A Target per cluster with a Prometheus: its own URL, else the Contract's
    prometheus integration's. A cluster with neither has no Sizings."""
    shared = next((i for i in contract.integrations if isinstance(i, Prometheus)), None)
    out = []
    for c in contract.clusters:
        url, secret = (
            (c.prometheus_url, c.prometheus_token_secret)
            if c.prometheus_url
            else ((shared.url, shared.token_secret) if shared else (None, None))
        )
        if url:
            token = contract.secret(secret) if secret else None
            out.append(Target(c.name, url, token, dict(c.prometheus_labels), list(c.namespaces)))
    return out


def _string(value: str) -> str:
    """A PromQL double-quoted string."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _any_of(values: list[str]) -> str:
    """An RE2 alternation matching exactly these values (PromQL anchors =~)."""
    return _string("|".join(re.escape(v) for v in values))


def selector(metric: str, t: Target, *extra: str) -> str:
    """`metric{...}` limited to the Target's namespaces and labels: no other Contract's
    or cluster's series can match."""
    ns = t.ksm_namespace if metric in KSM else "namespace"
    matchers = [f"{ns}=~{_any_of(t.namespaces)}"]
    matchers += [f"{k}={_string(v)}" for k, v in sorted(t.labels.items())]
    return f"{metric}{{{','.join([*matchers, *extra])}}}"


class Prom:
    """Prometheus' HTTP API, read-only. Raises UsageError on anything but success."""

    def __init__(self, t: Target, http: httpx.Client | None = None) -> None:
        if http is None:
            auth = {"Authorization": f"Bearer {t.token.get_secret_value()}"} if t.token else {}
            http = httpx.Client(base_url=t.url, headers=auth, timeout=30)
        self.http = http

    def _get(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            resp = self.http.get(path, params=params)
            body = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise UsageError(f"Prometheus unreachable: {e}") from None
        if resp.status_code != 200 or body.get("status") != "success":
            raise UsageError(f"Prometheus error {resp.status_code}: {body.get('error', '')}")
        result: list[dict[str, Any]] = body["data"]["result"]
        return result

    def instant(self, promql: str, at: float) -> list[dict[str, Any]]:
        return self._get("/api/v1/query", {"query": promql, "time": at})

    def range(self, promql: str, start: float, end: float, step: int) -> list[dict[str, Any]]:
        return self._get(
            "/api/v1/query_range", {"query": promql, "start": start, "end": end, "step": step}
        )


class UsageError(Exception):
    pass


def step_for(window_s: int) -> int:
    """Seconds between samples: one minute, coarser when the window needs it so no
    series goes over MAX_POINTS."""
    return max(60, 60 * math.ceil(window_s / MAX_POINTS / 60))


def check(prom: Prom, t: Target, at: float | None = None) -> tuple[Target, dict[str, str]]:
    """Which metrics are missing (metric -> what it gives), and the Target with the
    namespace label kube-state-metrics uses here."""
    at = at or time.time()
    found = set()
    for label in ("namespace", "exported_namespace"):
        probe = dataclasses.replace(t, ksm_namespace=label)
        if prom.instant(f"count({selector('kube_pod_owner', probe)})", at):
            t, found = probe, {"kube_pod_owner"}
            break
    for metric in (*REQUIRED, *OPTIONAL):
        if metric not in found and prom.instant(f"count({selector(metric, t)})", at):
            found.add(metric)
    missing = {m: w for m, w in {**REQUIRED, **OPTIONAL}.items() if m not in found}
    return t, missing


def label(m: dict[str, str], name: str) -> str:
    """A pod's own label on a kube-state-metrics series: scraped without honor_labels,
    Prometheus renames the colliding namespace, pod and container to exported_*."""
    return m.get(f"exported_{name}", m.get(name, ""))


@dataclass(frozen=True)
class Workload:
    namespace: str
    kind: str  # Deployment, StatefulSet, DaemonSet, Job, CronJob, Rollout, ReplicaSet, Pod, ...
    name: str


def _controller_first(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """An object can list several owners; its controller is the one that counts."""
    return sorted(series, key=lambda s: s["metric"].get("owner_is_controller") != "true")


def resolve(
    pod_owners: list[dict[str, Any]],
    rs_owners: list[dict[str, Any]],
    job_owners: list[dict[str, Any]],
) -> dict[tuple[str, str], Workload]:
    """(namespace, pod) -> its Workload, from kube-state-metrics' owner series: a
    ReplicaSet up to its Deployment or Rollout, a Job up to its CronJob, an ownerless
    pod as itself, any other owner (a StatefulSet, a custom resource) as it is."""

    def owners(series: list[dict[str, Any]], key: str) -> dict[tuple[str, str], tuple[str, str]]:
        out: dict[tuple[str, str], tuple[str, str]] = {}
        for s in reversed(_controller_first(series)):  # the controller written last wins
            m = s["metric"]
            out[(label(m, "namespace"), label(m, key))] = (
                m.get("owner_kind", "<none>"),
                m.get("owner_name", ""),
            )
        return out

    rs, jobs = owners(rs_owners, "replicaset"), owners(job_owners, "job_name")
    result = {}
    for (ns, pod), (kind, name) in owners(pod_owners, "pod").items():
        if kind == "<none>":
            kind, name = "Pod", pod
        elif kind == "ReplicaSet" and rs.get((ns, name), ("<none>",))[0] != "<none>":
            kind, name = rs[(ns, name)]
        elif kind == "Job" and jobs.get((ns, name), ("<none>",))[0] != "<none>":
            kind, name = jobs[(ns, name)]
        result[(ns, pod)] = Workload(ns, kind, name)
    return result


def owners_from_api(
    core: Any, apps: Any, batch: Any, namespaces: list[str]
) -> dict[tuple[str, str], Workload]:
    """The same map from the Kubernetes API, for a cluster without kube-state-metrics
    or pods it doesn't list. ponytail: live pods only, so a replaced pod's usage has
    no Workload this way; kube-state-metrics keeps history."""

    def series(objs: list[Any], key: str) -> list[dict[str, Any]]:
        out = []
        for o in objs:
            refs = o.metadata.owner_references or [None]
            for r in refs:
                out.append(
                    {
                        "metric": {
                            "namespace": o.metadata.namespace,
                            key: o.metadata.name,
                            "owner_kind": r.kind if r else "<none>",
                            "owner_name": r.name if r else "<none>",
                            "owner_is_controller": "true" if r and r.controller else "false",
                        }
                    }
                )
        return out

    pods, rss, jobs = [], [], []
    for ns in namespaces:
        pods += core.list_namespaced_pod(ns).items
        rss += apps.list_namespaced_replica_set(ns).items
        jobs += batch.list_namespaced_job(ns).items
    return resolve(series(pods, "pod"), series(rss, "replicaset"), series(jobs, "job_name"))


@dataclass
class ContainerUsage:
    """One container of one Workload over the window, its pods' samples pooled."""

    workload: Workload
    container: str
    cpu: list[float] = field(default_factory=list)  # cores, one per pod per step
    memory: list[float] = field(default_factory=list)  # working set bytes, peak per step
    requests: dict[str, float] = field(default_factory=dict)  # cpu (cores), memory (bytes)
    limits: dict[str, float] = field(default_factory=dict)
    pods: set[str] = field(default_factory=set)
    oom_killed_pods: int = 0
    throttled: float | None = None  # share of CFS periods throttled, None: no data


@dataclass
class Usage:
    rows: list[ContainerUsage]
    unknown: list[str]  # namespace/pod with usage but no Workload
    fallback_error: str | None = None  # why the Kubernetes API couldn't fill the gaps


def usage(
    prom: Prom,
    t: Target,
    window_s: int,
    end: float | None = None,
    fallback: Callable[[], dict[tuple[str, str], Workload]] | None = None,
) -> Usage:
    """Every container's pooled usage over the window, and the pods whose Workload
    nobody knows. `fallback` (the Kubernetes API) is asked once, only when a pod with
    usage isn't in kube-state-metrics; kube-state-metrics wins where both know a pod.
    A fallback that fails leaves those pods unknown, never the rest unread."""
    end = end or time.time()
    start, step = end - window_s, step_for(window_s)
    window = f"{window_s}s"

    def at_end(promql: str) -> list[dict[str, Any]]:
        return prom.instant(promql, end)

    owners = resolve(
        at_end(f"last_over_time({selector('kube_pod_owner', t)}[{window}])"),
        at_end(f"last_over_time({selector('kube_replicaset_owner', t)}[{window}])"),
        at_end(f"last_over_time({selector('kube_job_owner', t)}[{window}])"),
    )
    cpu_q = selector("container_cpu_usage_seconds_total", t, CONTAINERS)
    mem_q = selector("container_memory_working_set_bytes", t, CONTAINERS)
    cpu = prom.range(f"rate({cpu_q}[{max(300, step)}s])", start, end, step)
    mem = prom.range(f"max_over_time({mem_q}[{step}s])", start, end, step)
    pods = {(label(s["metric"], "namespace"), label(s["metric"], "pod")) for s in cpu + mem}
    error = None
    if fallback and pods - owners.keys():
        try:
            owners = {**fallback(), **owners}
        except Exception as e:  # forbidden, unreachable: kube-state-metrics' answer stands
            error = f"{type(e).__name__}: {str(e)[:200]}"

    rows: dict[tuple[Workload, str], ContainerUsage] = {}
    for samples, into in ((cpu, "cpu"), (mem, "memory")):
        for s in samples:
            m = s["metric"]
            w = owners.get((label(m, "namespace"), label(m, "pod")))
            if w is None:
                continue
            container = label(m, "container")
            r = rows.setdefault((w, container), ContainerUsage(w, container))
            r.pods.add(label(m, "pod"))
            getattr(r, into).extend(float(v) for _, v in s["values"])
    for metric, into in (
        ("kube_pod_container_resource_requests", "requests"),
        ("kube_pod_container_resource_limits", "limits"),
    ):
        for s in at_end(f"last_over_time({selector(metric, t)}[{window}])"):
            m = s["metric"]
            if m.get("resource") in ("cpu", "memory") and (hit := _known(rows, owners, m)):
                # ponytail: the largest across the window's pods; mid-rollout that is
                # the old or the new value, whichever is bigger
                current = getattr(hit, into)
                current[m["resource"]] = max(current.get(m["resource"], 0.0), float(s["value"][1]))
    oom = selector("kube_pod_container_status_last_terminated_reason", t, 'reason="OOMKilled"')
    for s in at_end(f"max_over_time({oom}[{window}])"):
        if float(s["value"][1]) > 0 and (hit := _known(rows, owners, s["metric"])):
            hit.oom_killed_pods += 1
    throttled, periods = (
        _sum_by_row(at_end(f"increase({selector(m, t, CONTAINERS)}[{window}])"), rows, owners)
        for m in ("container_cpu_cfs_throttled_periods_total", "container_cpu_cfs_periods_total")
    )
    for key, total in periods.items():
        if total > 0:
            rows[key].throttled = throttled.get(key, 0.0) / total
    unknown = sorted(f"{n}/{p}" for n, p in pods - owners.keys())
    return Usage(list(rows.values()), unknown, error)


def _known(
    rows: dict[tuple[Workload, str], ContainerUsage],
    owners: dict[tuple[str, str], Workload],
    m: dict[str, str],
) -> ContainerUsage | None:
    """The row a kube-state-metrics or cAdvisor series belongs to, if it has usage."""
    w = owners.get((label(m, "namespace"), label(m, "pod")))
    return rows.get((w, label(m, "container"))) if w else None


def _sum_by_row(
    series: list[dict[str, Any]],
    rows: dict[tuple[Workload, str], ContainerUsage],
    owners: dict[tuple[str, str], Workload],
) -> dict[tuple[Workload, str], float]:
    out: dict[tuple[Workload, str], float] = defaultdict(float)
    for s in series:
        if r := _known(rows, owners, s["metric"]):
            out[(r.workload, r.container)] += float(s["value"][1])
    return out
