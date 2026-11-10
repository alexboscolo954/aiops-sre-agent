"""The Actuator (slice 12.1): the Hub's two routes for it, bound by its token to one
Contract's cluster, and the Actuator resizing a Deployment's pods in place."""

import asyncio
import base64
import json
import ssl
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient
from kubernetes import client as k
from kubernetes.client.exceptions import ApiException
from pydantic import SecretStr

from aiops_agent import actuator, contracts
from aiops_agent.api import create_app
from aiops_agent.config import Settings
from aiops_agent.store import Store, connect
from tests.conftest import scripted

A_TOKEN = "a" * 40
B_TOKEN = "b" * 40
MI = 2**20
ROOT = Path(__file__).resolve().parent.parent


def actuated(cid: str, token: str, **cluster: Any) -> contracts.Contract:
    """A Contract whose cluster `test` (namespace shop) runs an Actuator; `edge` doesn't."""
    data = {
        "id": cid,
        "name": cid,
        "clusters": [
            {
                "name": "test",
                "context": "test",
                "namespaces": ["shop"],
                "actuator_token_secret": "act",
                **cluster,
            },
            {"name": "edge", "context": "edge", "namespaces": ["shop"]},
        ],
        "integrations": [{"name": "kubernetes"}],
    }
    return contracts.build(data, secrets={"act": SecretStr(token), "r": SecretStr("r" * 40)})


def hub(settings: Settings, database_url: str, *cs: contracts.Contract, **kw: Any) -> Any:
    settings.database_url = SecretStr(database_url)
    settings.approver_token = SecretStr(kw.get("approver", "approver-token"))
    return create_app(settings, scripted(), lambda c: None, {c.id: c for c in cs})  # type: ignore[arg-type]


def sql(database_url: str, *statements: tuple[str, tuple[Any, ...]]) -> list[Any]:
    with psycopg.connect(database_url) as conn:
        out = [conn.execute(q, args) for q, args in statements]
        return out[-1].fetchall() if out[-1].description else []


def approve(cid: str, run_id: int, cluster: str = "test", ns: str = "shop", **more: Any) -> Any:
    keys = {"kind": "Deployment", "name": "api", "container": "app", **more}
    return (
        "insert into approved_sizings values (%s, %s, %s, %s, %s, %s, %s, 0.115, null, 't', 1)",
        (cid, run_id, cluster, ns, keys["kind"], keys["name"], keys["container"]),
    )


def run(cid: str, clusters: str = "{}") -> Any:
    return (
        "insert into sizing_runs (contract_id, at, clusters) values (%s, 1, %s)",
        (cid, clusters),
    )


def as_actuator(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- the Hub's side -------------------------------------------------------------------------


def test_an_actuator_gets_only_its_own_clusters_current_approved_deployments(
    settings: Settings, database_url: str
) -> None:
    app = hub(settings, database_url, actuated("acme", A_TOKEN), actuated("bank", B_TOKEN))
    with TestClient(app) as c:
        sql(
            database_url,
            run("acme"),  # run 1, still going: supersedes nothing
            approve("acme", 1),
            approve("acme", 1, name="db", kind="StatefulSet"),  # other kinds: slice 12.8
            approve("acme", 1, cluster="edge"),  # another cluster of acme's
            approve("acme", 1, ns="old"),  # no longer one of its namespaces
            approve("bank", 1, name="ledger"),
        )
        mine = c.get("/actuator/desired", headers=as_actuator(A_TOKEN))
        theirs = c.get("/actuator/desired", headers=as_actuator(B_TOKEN))
        wrong = c.get("/actuator/desired", headers=as_actuator(A_TOKEN + "x"))
        none = c.get("/actuator/desired")
    wanted = {"run_id": 1, "namespace": "shop", "kind": "Deployment", "container": "app"}
    assert mine.json() == {
        "kill_switch": False,
        "sizings": [{**wanted, "name": "api", "cpu": 0.115, "memory": None}],
    }
    assert theirs.json()["sizings"] == [{**wanted, "name": "ledger", "cpu": 0.115, "memory": None}]
    assert wrong.status_code == 401 and none.status_code in (401, 403)


def test_the_kill_switch_and_a_later_run_leave_nothing_to_apply(
    settings: Settings, database_url: str
) -> None:
    app = hub(settings, database_url, actuated("acme", A_TOKEN), actuated("bank", B_TOKEN))
    with TestClient(app) as c:
        sql(database_url, run("acme"), approve("acme", 1), approve("bank", 1))
        sql(database_url, ("insert into kill_switches values ('acme', 't', 1)", ()))
        killed = c.get("/actuator/desired", headers=as_actuator(A_TOKEN)).json()
        # bank's run 2 read its cluster test: run 1's approval was never applied, and won't be
        sql(database_url, run("bank", '{"edge": null}'), run("bank", '{"test": null}'))
        superseded = c.get("/actuator/desired", headers=as_actuator(B_TOKEN)).json()
    assert killed == {"kill_switch": True, "sizings": []}
    assert superseded == {"kill_switch": False, "sizings": []}


def report(**more: Any) -> dict[str, Any]:
    base = {
        "namespace": "shop",
        "kind": "Deployment",
        "name": "api",
        "container": "app",
        "run_id": 1,
        "outcome": "applied",
        "cpu": 0.115,
        "memory": None,
        "pods": 2,
        "reason": "2 of 2 pods resized in place",
        "at": 100.0,
    }
    return base | more


def test_reports_are_stored_as_the_tokens_contract_and_cluster_once(
    settings: Settings, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = hub(settings, database_url, actuated("acme", A_TOKEN), actuated("bank", B_TOKEN))
    with TestClient(app) as c:
        ok = c.post("/actuator/reports", json=[report()], headers=as_actuator(A_TOKEN))
        again = c.post("/actuator/reports", json=[report()], headers=as_actuator(A_TOKEN))
        later = report(outcome="handed_back", at=160.0, pods=0)  # slice 12.2
        c.post("/actuator/reports", json=[later], headers=as_actuator(B_TOKEN))
        outside = c.post(
            "/actuator/reports",
            json=[report(at=200.0), report(namespace="kube-system", at=200.0)],
            headers=as_actuator(A_TOKEN),
        )
        wrong = c.post("/actuator/reports", json=[report()], headers=as_actuator("x" * 40))
        unknown = c.post(
            "/actuator/reports", json=[report(outcome="done")], headers=as_actuator(A_TOKEN)
        )
        monkeypatch.setattr(actuator, "MAX_REPORTS", 1)
        many = c.post("/actuator/reports", json=[report()] * 2, headers=as_actuator(A_TOKEN))
    assert (ok.status_code, again.status_code) == (204, 204)
    assert outside.status_code == 422 and "kube-system" in outside.json()["detail"]
    assert (wrong.status_code, unknown.status_code, many.status_code) == (401, 422, 413)
    rows = sql(
        database_url,
        ("select contract_id, cluster, outcome, pods, at from actuations order by at", ()),
    )
    assert rows == [
        ("acme", "test", "applied", 2, 100.0),
        ("bank", "test", "handed_back", 0, 160.0),
    ]


def test_actuations_are_kept_90_days(database_url: str) -> None:
    async def go() -> list[dict[str, Any]]:
        async with connect(database_url) as pool:
            store = Store(pool)
            await store.migrate()
            day = 86400.0
            rows = [report(at=0.0), report(at=10 * day)]
            await store.record_actuations("acme", "test", rows, 0.0)
            await store.record_actuations("bank", "test", [report(at=0.0)], 0.0)
            await store.prune_sizings("acme", 90 * day + 1)
            return await store.actuations("acme", 0.0) + await store.actuations("bank", 0.0)

    assert [(r["contract_id"], r["at"]) for r in asyncio.run(go())] == [
        ("acme", 10 * 86400.0),
        ("bank", 0.0),
    ]


def test_an_actuator_token_is_no_other_token(settings: Settings, database_url: str) -> None:
    def refused(*cs: contracts.Contract, approver: str = "approver-token") -> str:
        with pytest.raises(RuntimeError) as e:
            hub(settings, database_url, *cs, approver=approver)
        return str(e.value)

    relayed = actuated("acme", A_TOKEN, via="relay", context=None, relay_token_secret="act")
    assert "its Actuator token is another Relay's or Actuator's" in refused(relayed)
    assert "another Relay's or Actuator's" in refused(
        actuated("acme", A_TOKEN), actuated("bank", A_TOKEN)
    )
    assert "an Actuator token is the approver token" in refused(
        actuated("acme", A_TOKEN), approver=A_TOKEN
    )
    hooked = actuated("acme", A_TOKEN)
    hooked = hooked.model_copy(update={"webhook_token_sha256": contracts.token_hash(B_TOKEN)})
    assert "bank/test: its Actuator token is 'acme''s webhook token" in refused(
        hooked, actuated("bank", B_TOKEN)
    )
    with pytest.raises(ValueError, match="Actuator token is too short"):
        from aiops_agent import relay

        relay.tokens({"acme": actuated("acme", "x" * 31)}, "Actuator")


# --- the Actuator's side ------------------------------------------------------------------


def owner(kind: str, name: str, uid: str = "") -> k.V1OwnerReference:
    return k.V1OwnerReference(api_version="apps/v1", kind=kind, name=name, uid=uid)


def container(
    requests: dict[str, str], limits: dict[str, str] | None = None, policy: Any = None
) -> k.V1Container:
    return k.V1Container(
        name="app",
        resources=k.V1ResourceRequirements(requests=requests, limits=limits),
        resize_policy=policy,
    )


def pod(
    name: str, rs: str, phase: str = "Running", deleting: bool = False, **requests: str
) -> k.V1Pod:
    meta = k.V1ObjectMeta(name=name, owner_references=[owner("ReplicaSet", rs)])
    meta.deletion_timestamp = datetime.now(UTC) if deleting else None
    return k.V1Pod(
        metadata=meta,
        spec=k.V1PodSpec(containers=[container(requests or {"cpu": "1", "memory": "512Mi"})]),
        status=k.V1PodStatus(phase=phase),
    )


KEY = "shop/Deployment/api/app"


def cluster(
    limits: dict[str, str] | None = None, policy: Any = None, requests: Any = None
) -> tuple[Any, Any]:
    """api (uid u1) with ReplicaSet api-1; another Deployment's api-x shares its labels. A
    resize changes the pod's spec, and the kubelet allocates it at once, Ready."""
    core, apps = MagicMock(), MagicMock()
    template = container({"cpu": "1"} if requests is None else requests, limits, policy)
    apps.read_namespaced_deployment.return_value = k.V1Deployment(
        metadata=k.V1ObjectMeta(name="api", namespace="shop", uid="u1"),
        spec=k.V1DeploymentSpec(
            selector=k.V1LabelSelector(match_labels={"app": "api"}),
            template=k.V1PodTemplateSpec(spec=k.V1PodSpec(containers=[template])),
        ),
    )
    apps.list_namespaced_replica_set.return_value = k.V1ReplicaSetList(
        items=[
            k.V1ReplicaSet(
                metadata=k.V1ObjectMeta(name=n, owner_references=[owner("Deployment", d, u)]),
                spec=k.V1ReplicaSetSpec(selector=k.V1LabelSelector()),
            )
            for n, d, u in (("api-1", "api", "u1"), ("api-x", "api-old", "u2"))
        ]
    )
    pods = [
        pod("api-1-a", "api-1"),
        pod("api-1-b", "api-1"),
        pod("api-1-done", "api-1", phase="Succeeded"),
        pod("api-1-gone", "api-1", deleting=True),
        pod("api-x-a", "api-x"),
    ]
    for p in pods:
        p.metadata.namespace = "shop"
    core.list_namespaced_pod.return_value = k.V1PodList(items=pods)

    def patch(name: str, ns: str, body: Any) -> None:
        c = next(p for p in pods if p.metadata.name == name).spec.containers[0]
        c.resources.requests = {
            **c.resources.requests,
            **body["spec"]["containers"][0]["resources"]["requests"],
        }

    def read(name: str, ns: str) -> Any:
        p = next(p for p in core.list_namespaced_pod.return_value.items if p.metadata.name == name)
        allocated = k.V1ResourceRequirements(requests=p.spec.containers[0].resources.requests)
        p.status = k.V1PodStatus(
            phase="Running",
            conditions=[k.V1PodCondition(type="Ready", status="True")],
            container_statuses=[status("app", allocated)],
        )
        return p

    core.patch_namespaced_pod_resize.side_effect = patch
    core.read_namespaced_pod.side_effect = read
    core.list_namespaced_limit_range.return_value = k.V1LimitRangeList(items=[])
    core.list_namespaced_resource_quota.return_value = k.V1ResourceQuotaList(items=[])
    return core, apps


def status(name: str, resources: Any) -> Any:
    return k.V1ContainerStatus(
        name=name, image="app", image_id="", ready=True, restart_count=0, resources=resources
    )


def scalers(hpas: list[Any] | None = None, vpas: Any = None) -> tuple[Any, Any]:
    """(AutoscalingV2Api, CustomObjectsApi) mocks: these HPAs, these VPAs (an exception: raised)."""
    autoscaling, custom = MagicMock(), MagicMock()
    autoscaling.list_namespaced_horizontal_pod_autoscaler.return_value = MagicMock(items=hpas or [])
    if isinstance(vpas, Exception):
        custom.list_namespaced_custom_object.side_effect = vpas
    else:
        custom.list_namespaced_custom_object.return_value = {"items": vpas or []}
    return autoscaling, custom


def start(core: Any, apps: Any, w: Any, at: float = 0.0, **scaling: Any) -> Any:
    return actuator.apply(core, apps, w, at, *scalers(**scaling))


def wanted(run_id: int = 1, cpu: float | None = 0.115, memory: float | None = 96 * MI) -> Any:
    return actuator.Wanted(
        run_id=run_id,
        namespace="shop",
        kind="Deployment",
        name="api",
        container="app",
        cpu=cpu,
        memory=memory,
    )


def resized(core: Any) -> list[tuple[str, Any]]:
    return [(c.args[0], c.args[2]) for c in core.patch_namespaced_pod_resize.call_args_list]


def body(**requests: str) -> Any:
    return {"spec": {"containers": [{"name": "app", "resources": {"requests": requests}}]}}


def test_a_canary_first_then_one_pod_at_a_time_never_above_the_limit() -> None:
    core, apps = cluster(limits={"memory": "64Mi"})
    a, held = start(core, apps, wanted())
    both = body(cpu="115m", memory="64Mi")
    assert a is None and resized(core) == [("api-1-a", both)]
    assert held == {
        "run_id": 1,
        "outcome": "rolling",
        "requests": {"cpu": "115m", "memory": "64Mi"},
        "template": {"cpu": "1", "memory": None},  # what a person's change is told from
        "at": 0.0,
        "pods": {"api-1-a": {"at": 0.0, "restarts": 0}},  # watched from its resize (12.4)
        "pod": "api-1-a",
        "since": 0.0,
        "canary_until": 600.0,
        "resized": 1,
        "notes": "; capped at its limit: ['memory']",
    }
    assert actuator.advance(core, apps, KEY, held, 599.0) is None  # the canary's 10 minutes
    assert len(resized(core)) == 1
    assert actuator.advance(core, apps, KEY, held, 600.0) is None
    assert resized(core) == [("api-1-a", both), ("api-1-b", both)]
    assert (held["pod"], held["since"], held["resized"]) == ("api-1-b", 600.0, 2)
    done = actuator.advance(core, apps, KEY, held, 660.0)
    assert done is not None and (done.outcome, done.pods, done.cpu, done.memory) == (
        "applied",
        2,
        0.115,
        64.0 * MI,
    )
    assert (
        done.reason
        == "2 of 2 pods resized in place, one at a time; capped at its limit: ['memory']"
    )
    assert held == {
        "run_id": 1,
        "outcome": "applied",
        "requests": {"cpu": "115m", "memory": "64Mi"},
        "template": {"cpu": "1", "memory": None},
        "at": 0.0,
        "pods": {n: {"at": t, "restarts": 0} for n, t in (("api-1-a", 0.0), ("api-1-b", 600.0))},
        "watch_until": 660.0 + 3600,  # an hour for a rollback
    }
    labels = apps.list_namespaced_replica_set.call_args.kwargs["label_selector"]
    assert labels == "app=api" == core.list_namespaced_pod.call_args.kwargs["label_selector"]


def test_a_request_left_as_it_is_and_pods_that_already_match_are_not_touched() -> None:
    core, apps = cluster(limits={"cpu": "2"})
    core.list_namespaced_pod.return_value.items[1].spec.containers[0].resources.requests = {
        "cpu": "115m"
    }
    a, held = start(core, apps, wanted(memory=None))
    done = actuator.advance(core, apps, KEY, held, 600.0)
    assert a is None and resized(core) == [("api-1-a", body(cpu="115m"))]  # b already 115m
    assert done is not None and (done.outcome, done.pods, done.memory) == ("applied", 1, None)
    again, _ = start(core, apps, wanted(memory=None))
    assert (again.outcome, again.reason) == ("skipped", "all 2 pods already have these requests")


def refusal(status: int = 422, message: str = "Pod QoS Class may not change") -> ApiException:
    e = ApiException(status=status, reason="Unprocessable Entity")
    e.body = json.dumps({"message": message})
    return e


def pending(reason: str, message: str) -> Any:
    """A pod whose resize the kubelet holds back (PodResizePending)."""
    p = pod("api-1-a", "api-1")
    p.status = k.V1PodStatus(
        conditions=[
            k.V1PodCondition(type="PodResizePending", status="True", reason=reason, message=message)
        ]
    )
    return p


def test_a_resize_the_kubelet_cannot_make_stops_its_rollout() -> None:
    core, apps = cluster()
    _, held = start(core, apps, wanted())
    core.read_namespaced_pod.side_effect = None
    core.read_namespaced_pod.return_value = pending(
        "Infeasible", "Node didn't have enough capacity"
    )
    infeasible = actuator.advance(core, apps, KEY, dict(held), 60.0)
    assert infeasible is not None and (infeasible.outcome, infeasible.reason) == (
        "failed",
        "api-1-a: Infeasible: Node didn't have enough capacity; 0 other pods resized",
    )
    core.read_namespaced_pod.return_value = pending("Deferred", "no room now")
    deferred = dict(held)
    assert actuator.advance(core, apps, KEY, deferred, 599.0) is None  # it may still fit
    late = actuator.advance(core, apps, KEY, deferred, 601.0)
    assert late is not None and late.reason == "api-1-a: deferred for 10 minutes: no room now"
    for condition, message in (
        (k.V1PodCondition(type="Ready", status="False"), "not Ready"),
        (k.V1PodCondition(type="PodResizeInProgress", status="True"), "in progress"),
        (k.V1PodCondition(type="Ready", status="True"), "not yet allocated"),
    ):
        p = pod("api-1-a", "api-1")
        allocated = held["requests"] if message != "not yet allocated" else {"cpu": "1"}
        p.status = k.V1PodStatus(
            conditions=[condition],
            container_statuses=[status("app", k.V1ResourceRequirements(requests=allocated))],
        )
        core.read_namespaced_pod.return_value = p
        assert actuator.advance(core, apps, KEY, dict(held), 599.0) is None
        stuck = actuator.advance(core, apps, KEY, dict(held), 700.0)
        assert stuck is not None and stuck.reason == f"api-1-a: waiting for 10 minutes: {message}"
    core.read_namespaced_pod.side_effect = ApiException(status=500)
    assert actuator.advance(core, apps, KEY, dict(held), 900.0) is None  # the API's trouble: wait
    assert len(resized(core)) == 1  # nothing else was touched


def test_a_canary_gone_or_refused_and_a_refused_next_pod() -> None:
    core, apps = cluster()
    core.patch_namespaced_pod_resize.side_effect = refusal()
    refused, held = start(core, apps, wanted())
    assert (refused.outcome, refused.pods, held["outcome"]) == ("failed", 0, "failed")
    assert refused.reason == "api-1-a: 422: Pod QoS Class may not change"
    actuator.event(core, refused)
    shown = core.create_namespaced_event.call_args.args[1]
    assert (shown.reason, shown.type) == ("SizingFailed", "Warning")
    core, apps = cluster()
    _, held = start(core, apps, wanted())
    core.read_namespaced_pod.side_effect = ApiException(status=404)  # the canary was replaced
    core.patch_namespaced_pod_resize.side_effect = refusal(403, "forbidden")
    next_refused = actuator.advance(core, apps, KEY, held, 600.0)
    assert (
        next_refused is not None and next_refused.reason == "resizing its next pod: 403: forbidden"
    )
    assert next_refused.pods == 1 and "pod" not in held


def hpa(target: str = "api", metrics: Any = "cpu") -> Any:
    """An HPA of `target`; metrics: a resource it scales on by utilization, or a list."""
    h = MagicMock()
    h.spec.scale_target_ref.kind, h.spec.scale_target_ref.name = "Deployment", target
    if isinstance(metrics, str):
        m = MagicMock(type="Resource")
        m.resource.name, m.resource.target.type = metrics, "Utilization"
        metrics = [m]
    h.spec.metrics = metrics
    return h


def test_an_hpa_keeps_the_request_it_divides_by_and_a_vpa_keeps_the_workload() -> None:
    core, apps = cluster()
    vpa = {"spec": {"targetRef": {"kind": "Deployment", "name": "api"}}}
    auto, _ = start(core, apps, wanted(), vpas=[vpa])  # no updatePolicy: Auto
    off = {"spec": {**vpa["spec"], "updatePolicy": {"updateMode": "Off"}}}
    other = {"spec": {"targetRef": {"kind": "Deployment", "name": "web"}}}
    assert auto.reason == "a VPA in mode Auto sizes it" and not resized(core)
    a, held = start(core, apps, wanted(), vpas=[off, other], hpas=[hpa(), hpa("web", "memory")])
    assert a is None and resized(core) == [("api-1-a", body(memory="96Mi"))]
    assert held["notes"] == "; cpu left to its HPA, which scales on its utilization"
    assert held["template"] == {"memory": None}
    defaults, _ = start(core, apps, wanted(memory=None), hpas=[hpa(metrics=[])])
    assert defaults.reason.startswith("nothing its HPA doesn't scale on")  # no metrics: cpu
    by_value = MagicMock(type="Resource")
    by_value.resource.name, by_value.resource.target.type = "cpu", "AverageValue"
    mine = MagicMock(type="ContainerResource")
    mine.container_resource.container, mine.container_resource.name = "app", "memory"
    mine.container_resource.target.type = "Utilization"
    sidecar = MagicMock(type="ContainerResource")
    sidecar.container_resource.container, sidecar.container_resource.name = "proxy", "cpu"
    sidecar.container_resource.target.type = "Utilization"
    core, apps = cluster()
    _, held = start(core, apps, wanted(), hpas=[hpa(metrics=[by_value, mine, sidecar])])
    assert held["requests"] == {"cpu": "115m"}  # only its own container's memory is the HPA's
    missing, _ = start(core, apps, wanted(), vpas=ApiException(status=404))  # no VPA installed
    forbidden, _ = start(core, apps, wanted(), vpas=refusal(403, "forbidden"))
    assert missing is None  # rolling: a cluster without VPAs has none to fight
    assert (forbidden.outcome, forbidden.reason) == ("failed", "checking it: 403: forbidden")


def test_a_resize_changing_the_pods_qos_class_is_skipped() -> None:
    guaranteed = {"cpu": "1", "memory": "512Mi"}
    core, apps = cluster(limits=guaranteed, requests=guaranteed)
    g, _ = start(core, apps, wanted())
    assert g.reason == "it is Guaranteed: its limits must change too"
    core, apps = cluster(limits={"cpu": "115m", "memory": "96Mi"}, requests={"cpu": "1"})
    up, _ = start(core, apps, wanted())
    assert up.reason == "it would turn its pods from Burstable to Guaranteed"
    core, apps = cluster(requests={})
    apps.read_namespaced_deployment.return_value.spec.template.spec.containers[0].resources = None
    best, _ = start(core, apps, wanted())
    assert best.reason == "it would turn its pods from BestEffort to Burstable"
    assert not resized(core)


def limit_range(**item: Any) -> Any:
    return k.V1LimitRangeList(
        items=[
            k.V1LimitRange(
                spec=k.V1LimitRangeSpec(limits=[k.V1LimitRangeItem(type="Container", **item)])
            )
        ]
    )


def quota(hard: dict[str, str], used: dict[str, str]) -> Any:
    return k.V1ResourceQuotaList(
        items=[
            k.V1ResourceQuota(
                metadata=k.V1ObjectMeta(name="team"),
                status=k.V1ResourceQuotaStatus(hard=hard, used=used),
            )
        ]
    )


def test_a_limit_range_or_a_quota_that_would_refuse_it_skips_it_never_clamped() -> None:
    def tried(**set_up: Any) -> Any:
        core, apps = cluster(limits={"memory": "1Gi"})
        for name, value in set_up.items():
            getattr(core, f"list_namespaced_{name}").return_value = value
        a, _ = start(core, apps, wanted(cpu=2.0, memory=None))
        return a.reason if a else "rolling"

    assert (
        tried(limit_range=limit_range(min={"cpu": "3"}))
        == "cpu 2000m is under its LimitRange's minimum 3"
    )
    assert (
        tried(limit_range=limit_range(max={"cpu": "1500m"}))
        == "cpu 2000m is over its LimitRange's maximum 1500m"
    )
    assert tried(resource_quota=quota({"requests.cpu": "3"}, {"requests.cpu": "2"})) == (
        "2 pods at cpu 2000m would pass ResourceQuota team's requests.cpu 3"
    )
    assert tried(resource_quota=quota({"cpu": "4"}, {"cpu": "2"})) == "rolling"  # 2 + 2 x 1 fits
    assert tried(resource_quota=quota({"cpu": "3"}, {"cpu": "2"})) == (
        "2 pods at cpu 2000m would pass ResourceQuota team's cpu 3"
    )
    pod_wide = limit_range(min={"cpu": "3"})
    pod_wide.items[0].spec.limits[0].type = "Pod"
    assert tried(limit_range=pod_wide) == "rolling"  # a Pod's limits, not a container's
    assert tried(resource_quota=quota({"memory": "1"}, {"memory": "1"})) == "rolling"
    core, apps = cluster(limits={"memory": "1Gi"})
    core.list_namespaced_limit_range.return_value = limit_range(
        max_limit_request_ratio={"memory": "4"}
    )
    ratio, _ = start(core, apps, wanted(cpu=None, memory=128 * MI))
    assert ratio.reason == "memory 128Mi under limit 1Gi passes its LimitRange's ratio 4"
    core, apps = cluster()
    core.list_namespaced_resource_quota.return_value = quota(
        {"requests.cpu": "1"}, {"requests.cpu": "3"}
    )
    lower, _ = start(core, apps, wanted())
    assert lower is None  # a decrease never passes a quota, even one already passed


def test_a_resize_that_would_restart_the_container_or_has_nothing_to_resize_is_skipped() -> None:
    policy = [k.V1ContainerResizePolicy(resource_name="memory", restart_policy="RestartContainer")]
    core, apps = cluster(policy=policy)
    restarts, _ = start(core, apps, wanted())
    assert restarts.reason == "its resizePolicy restarts the container for ['memory']"
    assert not resized(core)
    cpu_only, _ = start(core, apps, wanted(memory=None))
    assert cpu_only is None  # a cpu resize doesn't restart it: rolling
    gone = MagicMock()
    gone.read_namespaced_deployment.side_effect = ApiException(status=404)
    missing, _ = start(MagicMock(), gone, wanted())
    core, apps = cluster()
    apps.read_namespaced_deployment.return_value.spec.template.spec.containers[0].name = "web"
    renamed, _ = start(core, apps, wanted())
    core, apps = cluster()
    core.list_namespaced_pod.return_value.items = []
    idle, _ = start(core, apps, wanted())
    apps.list_namespaced_replica_set.side_effect = refusal(403, "forbidden")
    forbidden, _ = start(core, apps, wanted())
    assert [(x.outcome, x.reason) for x in (missing, renamed, idle, forbidden)] == [
        ("skipped", "no such Deployment"),
        ("skipped", "no container 'app' in its template"),
        ("skipped", "no live pods"),
        ("failed", "checking it: 403: forbidden"),
    ]


def hub_of(answers: list[Any], seen: list[httpx.Request]) -> httpx.Client:
    """The Hub: answers each GET /actuator/desired in turn, 204 to reports (or a status)."""
    pulls = iter(answers)

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/actuator/desired":
            got = next(pulls)
            return got if isinstance(got, httpx.Response) else httpx.Response(200, json=got)
        return reports.pop(0) if reports else httpx.Response(204)

    reports: list[httpx.Response] = []
    c = httpx.Client(
        base_url="https://hub", transport=httpx.MockTransport(handle), headers=as_actuator(A_TOKEN)
    )
    c.reports = reports  # type: ignore[attr-defined]
    return c


def desired(*runs: int, killed: bool = False) -> dict[str, Any]:
    return {"kill_switch": killed, "sizings": [wanted(r).model_dump() for r in runs]}


def make(http: httpx.Client, core: Any, apps: Any, **kw: Any) -> actuator.Actuator:
    autoscaling, custom = scalers()
    return actuator.Actuator(
        http, core, apps, "aiops-actuator", autoscaling=autoscaling, custom=custom, **kw
    )


def test_a_rollout_goes_on_only_while_the_hub_answers_and_the_kill_switch_is_off(
    monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    monkeypatch.setattr(actuator, "CANARY_SECONDS", 0)
    core, apps = cluster()
    seen: list[httpx.Request] = []
    answers = [desired(1), httpx.Response(503), desired(1, killed=True), desired(1)]
    a = make(
        hub_of([*answers, desired(1), desired(1), desired(1, 2, killed=True)], seen), core, apps
    )
    a.step()  # run 1: the canary
    a.step()  # the Hub is down: no further
    a.step()  # the Kill switch: no further
    assert [n for n, _ in resized(core)] == ["api-1-a"] and a.held[KEY]["outcome"] == "rolling"
    a.step()  # on: the next pod
    a.step()  # every pod done: applied, reported
    a.step()  # run 1 again: nothing new
    a.step()  # the Kill switch with a newer run: nothing applied
    assert [n for n, _ in resized(core)] == ["api-1-a", "api-1-b"] and a.killed
    posted = [json.loads(r.content) for r in seen if r.method == "POST"]
    assert [[(x["run_id"], x["outcome"], x["pods"]) for x in p] for p in posted] == [
        [(1, "applied", 2)]
    ]
    assert all(r.headers["authorization"] == f"Bearer {A_TOKEN}" for r in seen)
    held = json.loads(core.replace_namespaced_config_map.call_args.args[2].data[actuator.KEY])
    assert held[KEY]["outcome"] == "applied"
    assert core.replace_namespaced_config_map.call_count == 7  # each step while rolling or watched
    events = [c.args[1] for c in core.create_namespaced_event.call_args_list]
    assert [(e.reason, e.type, e.involved_object.name) for e in events] == [
        ("SizingApplied", "Normal", "api")
    ]
    assert events[0].message.startswith("app: cpu 115m, memory 96Mi (Approved Sizing, run 1)")
    assert "the Hub answered 503" in caplog.text and A_TOKEN not in caplog.text


def actuation(run_id: int) -> actuator.Actuation:
    return actuator.Actuation(
        namespace="shop",
        kind="Deployment",
        name="api",
        container="app",
        run_id=run_id,
        outcome="applied",
        pods=1,
        reason="",
        at=float(run_id),
    )


def test_reports_are_resent_until_the_hub_takes_them_unless_it_refuses_them(caplog: Any) -> None:
    seen: list[httpx.Request] = []
    http = hub_of([], seen)
    http.reports += [httpx.Response(502), httpx.Response(422), httpx.Response(401)]  # type: ignore[attr-defined]
    a = make(http, MagicMock(), MagicMock())
    a.unsent = [actuation(1)]
    a.report()  # 502: kept
    assert [x.run_id for x in a.unsent] == [1]
    a.report()  # 422: the Hub's verdict, dropped
    assert a.unsent == [] and "the Hub refused 1 reports (422): dropped" in caplog.text
    a.unsent = [actuation(2)]
    a.report()  # 401: a refused token may be the Hub mid-update: kept
    assert [x.run_id for x in a.unsent] == [2]
    a.report()
    posted = [json.loads(r.content) for r in seen if r.method == "POST"]
    assert [[x["run_id"] for x in p] for p in posted] == [[1], [1], [2], [2]] and a.unsent == []


def test_what_it_applied_survives_a_restart() -> None:
    core, apps = cluster()
    held = {k: {**v} for k, v in HELD.items()}
    core.read_namespaced_config_map.return_value = k.V1ConfigMap(
        data={actuator.KEY: json.dumps(held)}
    )
    a = make(hub_of([desired(1)], []), core, apps)
    a.load()
    a.step()
    assert a.held == held and not resized(core)
    fresh = MagicMock()
    fresh.read_namespaced_config_map.side_effect = ApiException(status=404)
    fresh.replace_namespaced_config_map.side_effect = ApiException(status=404)
    b = make(hub_of([desired(1)], []), fresh, apps)
    b.load()
    assert b.held == {}
    for name in ("list_namespaced_pod", "patch_namespaced_pod_resize", "read_namespaced_pod"):
        setattr(fresh, name, getattr(core, name))
    fresh.list_namespaced_limit_range = core.list_namespaced_limit_range
    fresh.list_namespaced_resource_quota = core.list_namespaced_resource_quota
    b.step()  # the first save creates the ConfigMap
    assert fresh.create_namespaced_config_map.call_args.args[0] == "aiops-actuator"


@pytest.mark.parametrize(
    ("minor", "ok"), [("32", False), ("33", True), ("33+", True), ("37", True)]
)
def test_it_refuses_a_cluster_without_in_place_resize(minor: str, ok: bool) -> None:
    version = MagicMock()
    version.get_code.return_value = MagicMock(major="1", minor=minor, git_version=f"v1.{minor}.0")
    if ok:
        actuator.check_version(version)
    else:
        with pytest.raises(SystemExit, match=r"v1\.32\.0: the Actuator needs 1\.33"):
            actuator.check_version(version)


def test_the_manifests_resize_pods_and_never_edit_a_deployment() -> None:
    docs = list(yaml.safe_load_all((ROOT / "deploy/actuator/rbac.yaml").read_text()))
    rules = [r for d in docs if d["kind"] in ("ClusterRole", "Role") for r in d["rules"]]
    writes = {
        (res, verb)
        for r in rules
        for res in r["resources"]
        for verb in r["verbs"]
        if verb not in ("get", "list")
    }
    assert writes == {
        ("pods/resize", "patch"),
        ("events", "create"),
        ("configmaps", "update"),
        ("configmaps", "create"),
        ("mutatingwebhookconfigurations", "patch"),
    }
    assert "secrets" not in str(rules)
    webhook_rbac = next(r for r in rules if "mutatingwebhookconfigurations" in r["resources"])
    assert webhook_rbac["resourceNames"] == [actuator.WEBHOOK]
    deploy, service = yaml.safe_load_all((ROOT / "deploy/actuator/deployment.yaml").read_text())
    assert deploy["spec"]["template"]["spec"]["enableServiceLinks"] is False
    assert service["metadata"]["name"] == actuator.WEBHOOK
    assert service["spec"]["ports"] == [{"name": "webhook", "port": 443, "targetPort": "webhook"}]
    (hook,) = yaml.safe_load_all((ROOT / "deploy/actuator/webhook.yaml").read_text())
    (w,) = hook["webhooks"]
    assert (w["failurePolicy"], w["timeoutSeconds"], w["sideEffects"]) == ("Ignore", 2, "None")
    assert w["clientConfig"]["service"] == {
        "name": actuator.WEBHOOK,
        "namespace": "aiops-actuator",
        "path": "/mutate",
    }
    assert w["rules"][0]["operations"] == ["CREATE"] and w["rules"][0]["resources"] == ["pods"]
    (c,) = deploy["spec"]["template"]["spec"]["containers"]
    hub_image = next(yaml.safe_load_all((ROOT / "deploy/base/deployment.yaml").read_text()))
    assert c["image"] == hub_image["spec"]["template"]["spec"]["containers"][0]["image"]
    assert c["args"] == ["actuator"] and c["securityContext"]["readOnlyRootFilesystem"] is True


# --- the pod-creation webhook (slice 12.2) ------------------------------------------------

HELD = {
    "shop/Deployment/api/app": {
        "run_id": 1,
        "outcome": "applied",
        "requests": {"cpu": "115m", "memory": "64Mi"},
        "template": {"cpu": "1", "memory": None},
    }
}


def new_pod(
    ns: str = "shop", operation: str = "CREATE", sidecar: Any = None, **resources: Any
) -> dict[str, Any]:
    """The AdmissionReview of a new pod of api's ReplicaSet api-5d8f, its container `app`."""
    if sidecar is None:  # its request keeps the pod Burstable, whatever app's are
        sidecar = {"resources": {"requests": {"cpu": "10m"}}}
    c: dict[str, Any] = {"name": "app"}
    if resources != {"none": True}:
        c["resources"] = resources or {"requests": {"cpu": "1"}, "limits": {"memory": "48Mi"}}
    return {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "request": {
            "uid": "u-1",
            "operation": operation,
            "namespace": ns,
            "object": {
                "metadata": {
                    "generateName": "api-5d8f-",
                    "labels": {"app": "api", "pod-template-hash": "5d8f"},
                    "ownerReferences": [
                        {"kind": "ReplicaSet", "name": "api-5d8f", "controller": True}
                    ],
                },
                "spec": {"containers": [{"name": "sidecar", **sidecar}, c]},
            },
        },
    }


def patched(review: Any, held: Any = HELD, killed: bool = False) -> list[Any] | None:
    answer = actuator.admit(review, held, killed, "aiops-actuator")
    response = answer["response"]
    assert response["allowed"] is True and response["uid"] == (
        review.get("request", {}).get("uid", "") if isinstance(review, dict) else ""
    )
    if "patch" not in response:
        return None
    assert response["patchType"] == "JSONPatch"
    return json.loads(base64.b64decode(response["patch"]))  # type: ignore[no-any-return]


def test_a_new_pod_gets_the_requests_applied_never_above_its_limit() -> None:
    assert patched(new_pod()) == [
        {"op": "add", "path": "/spec/containers/1/resources/requests/cpu", "value": "115m"},
        {"op": "add", "path": "/spec/containers/1/resources/requests/memory", "value": "48Mi"},
    ]
    no_resources = patched(new_pod(none=True), held=untemplated(cpu=None, memory=None))
    assert no_resources == [
        {
            "op": "add",
            "path": "/spec/containers/1/resources",
            "value": {"requests": {"cpu": "115m", "memory": "64Mi"}},
        }
    ]
    no_requests = patched(new_pod(limits={"cpu": "2"}), held=untemplated(cpu=None, memory=None))
    assert no_requests == [
        {
            "op": "add",
            "path": "/spec/containers/1/resources/requests",
            "value": {"cpu": "115m", "memory": "64Mi"},
        }
    ]
    already = new_pod(requests={"cpu": "0.115", "memory": "64Mi"})
    assert patched(already, held=untemplated(cpu="0.115", memory="64Mi")) is None


def untemplated(**template: str | None) -> Any:
    """HELD, with the template's requests as they were when it applied."""
    return {k: {**v, "template": template} for k, v in HELD.items()}


def test_a_new_pod_keeps_its_own_requests_when_the_hold_does_not_apply() -> None:
    changed = new_pod(requests={"cpu": "2"})  # a person changed the template since
    assert patched(changed) is None
    assert patched(new_pod(), killed=True) is None  # the Kill switch: pods start unchanged
    nothing = untemplated(cpu=None, memory=None)  # BestEffort would turn Burstable
    assert patched(new_pod(none=True, sidecar={}), held=nothing) is None
    pinned = {"cpu": "1", "memory": "64Mi"}  # Guaranteed would turn Burstable
    guaranteed = new_pod(requests=pinned, limits=pinned, sidecar={"resources": {"limits": pinned}})
    assert patched(guaranteed, held=untemplated(**pinned)) is None
    for ns in ("aiops-actuator", "kube-system"):
        assert (
            patched(new_pod(ns=ns), held={k.replace("shop", ns): v for k, v in HELD.items()})
            is None
        )
    assert patched(new_pod(operation="UPDATE")) is None
    assert patched(new_pod(ns="bank")) is None  # nothing held there
    gone = {k: {**v, "outcome": "handed_back"} for k, v in HELD.items()}
    assert patched(new_pod(), held=gone) is None
    before_12_2 = {k: {kk: vv for kk, vv in v.items() if kk != "template"} for k, v in HELD.items()}
    assert patched(new_pod(), held=before_12_2) is None
    assert patched(new_pod(none=True), held=before_12_2) is None
    bare = new_pod()
    bare["request"]["object"]["metadata"]["labels"].pop("pod-template-hash")  # not a Deployment's
    assert patched(bare) is None
    bare_rs = new_pod()  # a ReplicaSet of its own named api: not one of Deployment api's
    bare_rs["request"]["object"]["metadata"]["ownerReferences"][0]["name"] = "api"
    assert patched(bare_rs) is None
    assert patched(["not", "a", "review"]) is None
    broken = {k: {**v, "requests": ["cpu"]} for k, v in HELD.items()}
    assert patched(new_pod(), held=broken) is None  # whatever goes wrong, the pod is created


def test_the_webhook_answers_over_tls_with_its_own_certificate() -> None:
    cert, key = actuator.certificate("localhost")
    a = actuator.Actuator(MagicMock(), MagicMock(), MagicMock(), "aiops-actuator", held=HELD)
    server = actuator.serve(a, cert, key, port=0)
    try:
        url = f"https://localhost:{server.server_address[1]}"
        trusted = ssl.create_default_context(cadata=cert.decode())
        with httpx.Client(verify=trusted) as http:
            ok = http.post(f"{url}/mutate?timeout=2s", json=new_pod())  # as the API server calls
            a.killed = True
            killed = http.post(f"{url}/mutate", json=new_pod())
            elsewhere = http.post(f"{url}/other", json=new_pod())
            garbage = http.post(f"{url}/mutate", content=b"{not json")
        with pytest.raises(httpx.ConnectError):
            httpx.post(f"{url}/mutate", json=new_pod())  # an untrusted certificate
    finally:
        server.shutdown()
    assert ok.status_code == 200 and "patch" in ok.json()["response"]
    assert "patch" not in killed.json()["response"]
    assert (elsewhere.status_code, garbage.status_code) == (404, 400)


def test_it_puts_its_certificate_in_its_own_webhooks_ca_bundle() -> None:
    admission = MagicMock()
    actuator.trust(admission, b"PEM")
    admission.patch_mutating_webhook_configuration.assert_called_once_with(
        "aiops-actuator",
        [{"op": "replace", "path": "/webhooks/0/clientConfig/caBundle", "value": "UEVN"}],
    )


def test_a_person_changing_the_template_gets_the_container_back() -> None:
    core, apps = cluster()  # api's template asks cpu 1, as when it applied
    held = {
        **HELD,
        "shop/Deployment/gone/app": {**HELD["shop/Deployment/api/app"]},
        "shop/Deployment/other/app": {**HELD["shop/Deployment/api/app"], "outcome": "failed"},
        "shop/Deployment/old/app": {"run_id": 1, "outcome": "applied", "requests": {"cpu": "1"}},
    }
    held = {k: {**v} for k, v in held.items()}

    def read(name: str, ns: str) -> Any:
        if name == "gone":
            raise ApiException(status=404)
        return apps.read_namespaced_deployment.return_value

    apps.read_namespaced_deployment.side_effect = read
    seen: list[httpx.Request] = []
    a = actuator.Actuator(hub_of([httpx.Response(503)] * 2, seen), core, apps, "x", held=held)
    a.step()  # the Hub is down: hand-backs still happen, and are saved and reported
    assert [(k, v["outcome"]) for k, v in a.held.items()] == [
        ("shop/Deployment/api/app", "applied"),
        ("shop/Deployment/gone/app", "handed_back"),
        ("shop/Deployment/other/app", "failed"),
        ("shop/Deployment/old/app", "handed_back"),
    ]
    template = apps.read_namespaced_deployment.return_value.spec.template.spec.containers[0]
    template.resources.requests = {"cpu": "200m"}
    a.step()
    assert a.held["shop/Deployment/api/app"]["outcome"] == "handed_back"
    reports = [x for r in seen if r.method == "POST" for x in json.loads(r.content)]
    assert [(r["name"], r["outcome"], r["reason"]) for r in reports] == [
        ("gone", "handed_back", "no such Deployment"),
        ("old", "handed_back", "held without its template's requests (before slice 12.2)"),
        ("api", "handed_back", "its template's requests changed: cpu 1 to 200m"),
    ]
    events = [c.args[1] for c in core.create_namespaced_event.call_args_list]
    assert [e.reason for e in events] == ["HandedBack"] * 3
    assert events[2].message.startswith("app: back to its template (Approved Sizing, run 1)")
    assert core.replace_namespaced_config_map.call_count == 2
    template.name = "web"
    a.held["shop/Deployment/api/app"]["outcome"] = "applied"
    (renamed,) = a.hand_back()
    assert renamed.reason == "no container 'app' in its template"
    rolling = {**HELD[KEY], "outcome": "rolling", "pod": "api-1-a", "since": 0.0, "resized": 1}
    apps.read_namespaced_deployment.side_effect = None
    template.name = "app"
    a.held = {KEY: rolling}  # a rollout under way when a person changes the template
    (stopped,) = a.hand_back()
    assert stopped.reason == "its template's requests changed: cpu 1 to 200m"
    assert a.held[KEY] == {**HELD[KEY], "outcome": "handed_back"}
    apps.read_namespaced_deployment.side_effect = ApiException(status=500)
    a.held = {KEY: {**HELD[KEY]}}
    assert a.hand_back() == []  # the API server failing is no change by a person


# --- rollback (slice 12.4) ----------------------------------------------------------------


def unhealthy(
    p: Any, restarts: int = 0, oom: bool = False, ready: bool = True, since: float = 0.0
) -> Any:
    """`p` as the kubelet reports it: its container's restarts, last end, Ready since `since`."""
    ended = k.V1ContainerStateTerminated(exit_code=137, reason="OOMKilled" if oom else "Error")
    st = status("app", None)
    st.restart_count, st.last_state = restarts, k.V1ContainerState(terminated=ended)
    when = datetime.fromtimestamp(since, UTC)
    ready_now = k.V1PodCondition(
        type="Ready", status="True" if ready else "False", last_transition_time=when
    )
    p.status = k.V1PodStatus(phase="Running", conditions=[ready_now], container_statuses=[st])
    return p


def watched(core: Any, apps: Any, at: float = 1000.0) -> dict[str, Any]:
    """api's Sizing applied on both pods at `at`, each with no restart then."""
    _, h = start(core, apps, wanted(memory=None))
    actuator.advance(core, apps, KEY, h, 600.0)
    actuator.advance(core, apps, KEY, h, 660.0)
    assert h["outcome"] == "applied"
    h["pods"] = {n: {"at": at, "restarts": 0} for n in ("api-1-a", "api-1-b")}
    return h


def test_what_makes_a_sizing_unhealthy_and_what_does_not() -> None:
    core, apps = cluster()
    h = watched(core, apps)
    a, b = core.list_namespaced_pod.return_value.items[:2]

    def found(now: float = 2000.0) -> str | None:
        return actuator.trouble(core, apps, KEY, h, now)

    assert found() is None  # healthy
    unhealthy(a, restarts=1, oom=True)
    assert found() == "api-1-a: app was OOM-killed"
    unhealthy(a, restarts=1)
    assert found() == "api-1-a: app restarted"
    h["pods"]["api-1-a"]["restarts"] = 1  # it had restarted once before it was resized
    assert found() is None
    unhealthy(b, ready=False, since=1500.0)
    assert found(1619.0) is None and found(1620.0) == "api-1-b: NotReady for 2 minutes"
    unhealthy(b, ready=True, since=1500.0)  # Ready again since: fine
    assert found() is None
    unhealthy(b, ready=False, since=900.0)  # NotReady since before its resize: not its doing
    assert found() is None
    unhealthy(b)
    new = pod("api-1-c", "api-1", cpu="115m")  # created by the webhook, with its requests
    core.list_namespaced_pod.return_value.items.append(new)
    unhealthy(new, ready=False, since=0.0)
    assert found() is None  # a new pod may take its time to be Ready
    unhealthy(new, restarts=1)
    assert found() == "api-1-c: app restarted"
    other = pod("api-1-d", "api-1")  # the template's requests: not the Actuator's doing
    core.list_namespaced_pod.return_value.items[-1] = unhealthy(other, restarts=5, oom=True)
    assert found() is None
    apps.read_namespaced_deployment.side_effect = ApiException(status=500)
    assert found() is None


def test_a_rollback_puts_its_pods_back_and_backs_off_doubling() -> None:
    core, apps = cluster()
    h = watched(core, apps)
    core.patch_namespaced_pod_resize.reset_mock()
    h["template"] = {"cpu": "1"}
    first = actuator.rollback(core, apps, KEY, h, "api-1-a: app restarted", 7200.0)
    assert resized(core) == [("api-1-a", body(cpu="1")), ("api-1-b", body(cpu="1"))]
    assert (first.outcome, first.pods, first.cpu) == ("rolled_back", 2, 1.0)
    assert first.reason == (
        "api-1-a: app restarted: 2 pods back to their template's requests; "
        "no new Sizing of it until 1970-01-02 02:00 UTC"
    )
    assert h == {
        "run_id": 1,
        "outcome": "rolled_back",
        "requests": {"cpu": "115m"},
        "template": {"cpu": "1"},
        "at": 0.0,
        "rollbacks": [7200.0],
        "backoff_until": 7200.0 + 86400,
    }
    h["rollbacks"] = [0.0, 7200.0]
    later = 7 * 86400.0 + 100  # the one at 0 is over 7 days old, the one at 7200 not
    again = actuator.rollback(core, apps, KEY, h, "x", later)
    assert h["rollbacks"] == [7200.0, later]
    assert h["backoff_until"] == later + 2 * 86400  # the second in 7 days: two days
    assert again.pods == 0  # already back
    core, apps = cluster()
    h = watched(core, apps)
    h["template"] = {"cpu": None}  # the template asked no cpu: nothing to put back
    core.patch_namespaced_pod_resize.reset_mock()
    unset = actuator.rollback(core, apps, KEY, h, "x", 0.0)
    assert not resized(core) and "(['cpu'] left: the template sets none)" in unset.reason
    core, apps = cluster()
    h = watched(core, apps)
    core.patch_namespaced_pod_resize.side_effect = refusal(403, "forbidden")
    refused = actuator.rollback(core, apps, KEY, h, "x", 0.0)
    assert refused.pods == 0 and "2 refused, first api-1-a: 403: forbidden" in refused.reason
    actuator.event(core, refused)
    shown = core.create_namespaced_event.call_args.args[1]
    assert (shown.reason, shown.type) == ("SizingRolledBack", "Warning")


def test_an_unhealthy_rollout_is_rolled_back_and_the_next_approval_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(actuator, "CANARY_SECONDS", 0)
    core, apps = cluster()
    seen: list[httpx.Request] = []
    answers = [
        desired(1),  # the canary
        httpx.Response(503),  # the canary restarts: rolled back, the Hub down or not
        desired(1, 2),  # a newer approval during the backoff: skipped
        desired(2, 3),  # after the backoff: applied
    ]
    a = make(hub_of(answers, seen), core, apps)
    a.step()
    canary = core.list_namespaced_pod.return_value.items[0]
    core.read_namespaced_pod.side_effect = None
    core.read_namespaced_pod.return_value = unhealthy(canary, restarts=1, oom=True)
    a.step()
    assert a.held[KEY]["outcome"] == "rolled_back"
    assert [n for n, _ in resized(core)] == ["api-1-a", "api-1-a"]  # resized, then back
    a.step()
    assert a.held[KEY]["outcome"] == "skipped" and a.held[KEY]["rollbacks"]
    a.held[KEY]["backoff_until"] = 0.0
    unhealthy(canary)  # healthy again
    a.step()
    assert a.held[KEY]["run_id"] == 3 and a.held[KEY]["outcome"] == "rolling"
    assert a.held[KEY]["rollbacks"]  # kept for the doubling
    posted = [x for r in seen if r.method == "POST" for x in json.loads(r.content)]
    assert [(x["run_id"], x["outcome"]) for x in posted] == [(1, "rolled_back"), (2, "skipped")]
    assert posted[0]["reason"].startswith("api-1-a: app was OOM-killed: 1 pods back")
    assert posted[1]["reason"].startswith("rolled back 1 times in 7 days: no new Sizing of it")


def test_no_rollback_under_the_kill_switch_and_none_once_its_hour_is_over() -> None:
    core, apps = cluster()
    h = watched(core, apps)
    unhealthy(core.list_namespaced_pod.return_value.items[0], restarts=1)
    a = make(hub_of([desired(1, killed=True), httpx.Response(503)], []), core, apps)
    a.held = {KEY: h}
    h["watch_until"] = 10**12
    a.step()  # the Kill switch: nothing changes, not even a rollback
    assert h["outcome"] == "applied"
    h["watch_until"] = 0.0
    a.killed = False
    a.step()  # its hour is over: no longer watched
    assert h["outcome"] == "applied" and "pods" not in h and "watch_until" not in h


def test_a_rollback_reaches_the_operators_channel_once(
    settings: Settings, database_url: str
) -> None:
    from tests.test_slack import TOKEN, FakeSlack

    settings.slack_bot_token = SecretStr(TOKEN)
    slack = FakeSlack()
    channel = {"slack": {"operator_channel": "C0123456789"}}
    acme = contracts.build(
        {**actuated("acme", A_TOKEN).model_dump(mode="json", exclude_none=True), **channel},
        secrets={"act": SecretStr(A_TOKEN), "r": SecretStr("r" * 40)},
    )
    settings.database_url = SecretStr(database_url)
    settings.approver_token = SecretStr("approver-token")
    app = create_app(
        settings,
        scripted(),
        lambda c: None,
        {"acme": acme, "bank": actuated("bank", B_TOKEN)},
        slack_http=httpx.AsyncClient(transport=slack.transport()),
    )
    back = report(outcome="rolled_back", reason="api-1-a: app was OOM-killed: 2 pods back")
    with TestClient(app) as c:
        for _ in range(2):  # sent again: posted once
            c.post("/actuator/reports", json=[back, report(at=1.0)], headers=as_actuator(A_TOKEN))
        c.post("/actuator/reports", json=[back], headers=as_actuator(B_TOKEN))  # no Slack
    posts = [p for m, p, _ in slack.calls if m == "chat.postMessage"]
    assert [(p["channel"], p["text"]) for p in posts] == [
        (
            "C0123456789",
            ":rewind: acme: the Actuator rolled back test/shop/Deployment/api container app: "
            "api-1-a: app was OOM-killed: 2 pods back",
        )
    ]
