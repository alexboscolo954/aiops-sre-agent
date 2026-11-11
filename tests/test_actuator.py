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

from squero import actuator, contracts
from squero.api import create_app
from squero.config import Settings
from squero.store import Store, connect
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
            approve("acme", 1, name="db", kind="StatefulSet"),  # slice 12.8a
            approve("acme", 1, name="agent", kind="DaemonSet"),
            approve("acme", 1, name="web", kind="Rollout"),  # Argo Rollouts: slice 12.8b
            approve("acme", 1, name="nightly", kind="CronJob"),  # no Actuator resizes one
            approve("acme", 1, cluster="edge"),  # another cluster of acme's
            approve("acme", 1, ns="old"),  # no longer one of its namespaces
            approve("bank", 1, name="ledger"),
        )
        kinds = {"kinds": "Deployment,StatefulSet,DaemonSet,Rollout,CronJob"}
        mine = c.get("/actuator/desired", headers=as_actuator(A_TOKEN), params=kinds)
        three = {"kinds": "Deployment,StatefulSet,DaemonSet"}  # 0.44.0: no Rollouts
        before = c.get("/actuator/desired", headers=as_actuator(A_TOKEN), params=three)
        old = c.get("/actuator/desired", headers=as_actuator(A_TOKEN))  # 0.43.0: names none
        theirs = c.get("/actuator/desired", headers=as_actuator(B_TOKEN))
        wrong = c.get("/actuator/desired", headers=as_actuator(A_TOKEN + "x"))
        none = c.get("/actuator/desired")
    wanted = {"run_id": 1, "namespace": "shop", "kind": "Deployment", "container": "app"}
    assert mine.json() == {
        "kill_switch": False,
        "sizings": [
            {**wanted, "kind": "DaemonSet", "name": "agent", "cpu": 0.115, "memory": None},
            {**wanted, "name": "api", "cpu": 0.115, "memory": None},
            {**wanted, "kind": "Rollout", "name": "web", "cpu": 0.115, "memory": None},
            {**wanted, "kind": "StatefulSet", "name": "db", "cpu": 0.115, "memory": None},
        ],
        "automated": [],
        "reverts": [],
        "eviction": "off",
    }
    assert old.json()["sizings"] == [{**wanted, "name": "api", "cpu": 0.115, "memory": None}]
    assert before.json()["sizings"] == [x for x in mine.json()["sizings"] if x["kind"] != "Rollout"]
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
    assert killed == {
        "kill_switch": True,
        "sizings": [],
        "automated": [],
        "reverts": [],
        "eviction": "off",
    }
    assert superseded == {
        "kill_switch": False,
        "sizings": [],
        "automated": [],
        "reverts": [],
        "eviction": "off",
    }


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
        from squero import relay

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
    meta = k.V1ObjectMeta(
        name=name, labels={"app": "api"}, owner_references=[owner("ReplicaSet", rs)]
    )
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
            replicas=2,
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
        live = core.list_namespaced_pod.return_value.items  # pods added later included
        c = next(p for p in live if p.metadata.name == name).spec.containers[0]
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


def budgets(*selectors: Any) -> Any:
    """A PolicyV1Api mock: a PodDisruptionBudget per selector (an exception: raised)."""
    policy = MagicMock()
    if selectors and isinstance(selectors[0], Exception):
        policy.list_namespaced_pod_disruption_budget.side_effect = selectors[0]
        return policy
    items = [
        k.V1PodDisruptionBudget(spec=k.V1PodDisruptionBudgetSpec(selector=s)) for s in selectors
    ]
    policy.list_namespaced_pod_disruption_budget.return_value = MagicMock(items=items)
    return policy


PDB = budgets(k.V1LabelSelector(match_labels={"app": "api"}))  # covers api's pods


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
    kw.setdefault("policy", PDB)
    return actuator.Actuator(
        http, core, apps, "squero-actuator", autoscaling=autoscaling, custom=custom, **kw
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
    pulls = [r.url.params.get("kinds") for r in seen if r.method == "GET"]
    assert set(pulls) == {"Deployment,StatefulSet,DaemonSet,Rollout"}  # what it resizes (12.8b)
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
    for p in core.list_namespaced_pod.return_value.items:  # as it left them
        p.spec.containers[0].resources.requests = dict(held[KEY]["requests"])
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
    assert fresh.create_namespaced_config_map.call_args.args[0] == "squero-actuator"


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
        ("pods/eviction", "create"),  # slice 12.7, the Eviction API: PDBs hold
        ("events", "create"),
        ("configmaps", "update"),
        ("configmaps", "create"),
        ("mutatingwebhookconfigurations", "patch"),
    }
    assert "secrets" not in str(rules)
    apps_reads = ["deployments", "replicasets", "statefulsets", "daemonsets"]  # slice 12.8a
    assert {"apiGroups": ["apps"], "resources": apps_reads, "verbs": ["get", "list"]} in rules
    assert {
        "apiGroups": ["policy"],
        "resources": ["poddisruptionbudgets"],
        "verbs": ["get", "list"],
    } in rules
    argo = {"apiGroups": ["argoproj.io"], "resources": ["rollouts"], "verbs": ["get", "list"]}
    assert argo in rules  # slice 12.8b: read only
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
        "namespace": "squero-actuator",
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
    answer = actuator.admit(review, held, killed, "squero-actuator")
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
    for ns in ("squero-actuator", "kube-system"):
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
    a = actuator.Actuator(MagicMock(), MagicMock(), MagicMock(), "squero-actuator", held=HELD)
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
        "squero-actuator",
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
        "api-1-a: app restarted: 2 pods back from cpu 115m to their template's cpu 1; "
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
    assert not resized(core)
    assert unset.reason.startswith("x: 0 pods back from cpu 115m (['cpu'] left: the template sets")
    core, apps = cluster()
    h = watched(core, apps)
    core.patch_namespaced_pod_resize.side_effect = refusal(403, "forbidden")
    refused = actuator.rollback(core, apps, KEY, h, "x", 0.0)
    assert refused.pods == 0 and "2 refused, first api-1-a: 403: forbidden" in refused.reason
    actuator.event(core, refused)
    shown = core.create_namespaced_event.call_args.args[1]
    assert (shown.reason, shown.type) == ("SizingRolledBack", "Warning")
    # what it went back to is in the reason; the values never read as the ones approved
    assert shown.message.startswith("app: back to its template (Approved Sizing, run 1): x: 0 pods")


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


def test_pods_that_missed_the_held_requests_get_them_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pod started from its template while the Kill switch was on (or the webhook down)
    gets the Sizing again once the Actuator may change things: the pre-checks, a canary,
    and the pods it already watched stay watched (found live, 2026-11-10)."""
    monkeypatch.setattr(actuator, "CANARY_SECONDS", 0)
    core, apps = cluster()
    h = watched(core, apps)
    h["watch_until"], h["rollbacks"] = 10**12, [5.0]
    seen: list[httpx.Request] = []
    a = make(hub_of([desired(1, killed=True), *[desired(1)] * 6], seen), core, apps)
    a.held = {KEY: h}
    core.patch_namespaced_pod_resize.reset_mock()
    late = pod("api-1-c", "api-1")  # from the template: cpu 1
    late.metadata.namespace = "shop"
    core.list_namespaced_pod.return_value.items.append(late)
    a.step()  # the Kill switch: left as it is
    assert not resized(core) and a.held[KEY]["outcome"] == "applied"
    a.step()  # off: it catches up, as a canary
    assert resized(core) == [("api-1-c", body(cpu="115m"))]
    now = a.held[KEY]
    assert (now["outcome"], now["pod"], now["watch_until"]) == ("rolling", "api-1-c", 10**12)
    assert set(now["pods"]) == {"api-1-a", "api-1-b", "api-1-c"}  # still watched
    assert now["rollbacks"] == [5.0]  # kept for the doubling
    a.step()  # allocated: applied again
    a.step()  # nothing behind: nothing to do
    assert len(resized(core)) == 1 and a.held[KEY]["outcome"] == "applied"
    posted = [x for r in seen if r.method == "POST" for x in json.loads(r.content)]
    assert [(x["run_id"], x["outcome"], x["pods"]) for x in posted] == [(1, "applied", 1)]
    # A pre-check that fails now (a VPA since) ends the hold: reported, never resized.
    behind = pod("api-1-d", "api-1")
    behind.metadata.namespace = "shop"
    core.list_namespaced_pod.return_value.items.append(behind)
    vpa = {"spec": {"targetRef": {"kind": "Deployment", "name": "api"}}}
    a.custom = scalers(vpas=[vpa])[1]
    a.step()
    assert len(resized(core)) == 1 and a.held[KEY]["outcome"] == "skipped"
    last = json.loads([r for r in seen if r.method == "POST"][-1].content)[0]
    assert (last["outcome"], last["reason"]) == ("skipped", "a VPA in mode Auto sizes it")
    a.custom = scalers()[1]
    a.step()  # no longer held: never caught up
    a.held[KEY]["outcome"] = "rolled_back"
    a.step()  # rolled back: never caught up either
    assert len(resized(core)) == 1


# --- Automation (slice 12.5) --------------------------------------------------------------


def automating(cid: str, token: str, *rules: dict[str, Any], **more: Any) -> contracts.Contract:
    """actuated(), with these Sizing rules."""
    data = actuated(cid, token).model_dump(mode="json", exclude_none=True)
    return contracts.build(
        {**data, "sizing": {"rules": list(rules)}, **more},
        secrets={"act": SecretStr(token), "r": SecretStr("r" * 40)},
    )


AUTO = {"namespace": "shop", "container": "app", "policy": "production", "automate": True}


def test_automate_needs_an_actuator_and_a_policy_and_the_first_matching_rule_decides() -> None:
    with pytest.raises(ValueError, match="policy off has no Sizings to apply"):
        automating("acme", A_TOKEN, {**AUTO, "policy": "off"})
    with pytest.raises(ValueError, match="rule 1 automates: cluster 'edge' has no actuator"):
        automating("acme", A_TOKEN, {**AUTO, "cluster": "edge"})
    plain = actuated("acme", A_TOKEN).model_dump(mode="json", exclude_none=True)
    plain["clusters"][0].pop("actuator_token_secret")
    with pytest.raises(ValueError, match="rule 1 automates: no cluster has no actuator"):
        contracts.build({**plain, "sizing": {"rules": [AUTO]}}, secrets={})
    c = automating(
        "acme",
        A_TOKEN,
        {"namespace": "shop", "name": "db", "policy": "production"},  # first: not automated
        {**AUTO, "cluster": "test"},
    )
    assert c.sizing.automated("test", "shop", "Deployment", "api", "app")
    assert not c.sizing.automated("test", "shop", "Deployment", "db", "app")
    assert not c.sizing.automated("test", "shop", "Deployment", "api", "sidecar")
    assert not c.sizing.automated("edge", "shop", "Deployment", "api", "app")
    assert not actuated("acme", A_TOKEN).sizing.automated(
        "test", "shop", "Deployment", "api", "app"
    )


def sized(cid: str, run_id: int, name: str = "api", **row: Any) -> Any:
    """A stored Sizing of test/shop/<kind>/<name>/<container> in run `run_id`."""
    r = {
        "cluster": "test",
        "namespace": "shop",
        "kind": "Deployment",
        "name": name,
        "container": "app",
        "state": "ready",
        "cpu": {"action": "lower", "current": 1.0, "target": 0.115},
        "memory": {"action": "keep", "current": 1.0, "target": 1.0},
    } | row
    keys = [r[k] for k in ("cluster", "namespace", "kind", "name", "container")]
    return ("insert into sizings values (%s, %s, %s, %s, %s, %s, %s, %s)",
            (run_id, cid, *keys, json.dumps(r)))  # fmt: skip


def rolled_back(
    cid: str, at: float, cluster: str = "test", name: str = "api", outcome: str = "rolled_back"
) -> Any:
    return (
        "insert into actuations values (%s, %s, 'shop', 'Deployment', %s, 'app', 1, "
        "%s, null, null, 1, 'x', %s, %s)",
        (cid, cluster, name, outcome, at, at),
    )


def test_an_actuator_gets_the_newest_sizings_of_what_its_contract_automates(
    settings: Settings, database_url: str
) -> None:
    import time

    now = time.time()
    gone = {**AUTO, "namespace": "old"}  # a namespace the cluster no longer has
    acme = automating("acme", A_TOKEN, AUTO, gone)
    bank = automating("bank", B_TOKEN, {**AUTO, "name": "ledger"})
    app = hub(settings, database_url, acme, bank)
    with TestClient(app) as c:
        sql(
            database_url,
            run("acme", '{"test": null}'),  # run 1
            run("acme", '{"test": null}'),  # run 2: the newest
            sized("acme", 1, cpu={"action": "raise", "current": 0.1, "target": 0.5}),
            sized("acme", 2),
            sized("acme", 2, "learning", state="learning"),
            sized("acme", 2, "steady", cpu={"action": "keep", "current": 1.0, "target": 1.0}),
            sized("acme", 2, "db", kind="StatefulSet"),  # slice 12.8a
            sized("acme", 2, "web", kind="Rollout"),  # Argo Rollouts: slice 12.8b
            sized("acme", 2, "side", container="sidecar"),  # no rule automates it
            sized("acme", 2, "approved"),
            approve("acme", 2, name="approved"),  # the approval goes as approved, once
            sized("acme", 2, "broken"),
            sized("acme", 2, "twice"),
            sized("acme", 2, "elsewhere"),
            sized("acme", 2, "moved", namespace="old"),
            *(rolled_back("acme", now - d * 86400, name="broken") for d in (1, 2, 3)),  # ended
            *(rolled_back("acme", now - d * 86400, name="twice") for d in (1, 2, 7.5)),  # 7.5: old
            *(rolled_back("acme", now - d * 86400, "edge", "elsewhere") for d in (1, 2, 3)),
            *(rolled_back("bank", now - d * 86400) for d in (1, 2, 3)),  # bank's api, not acme's
            *(rolled_back("acme", now - d, outcome="applied") for d in (1, 2, 3)),  # no rollback
            run("bank", '{"test": null}'),  # run 3, bank's
            sized("bank", 3, "ledger"),
        )
        kinds = {"kinds": ",".join(actuator.KINDS)}
        mine = c.get("/actuator/desired", headers=as_actuator(A_TOKEN), params=kinds).json()
        old = c.get("/actuator/desired", headers=as_actuator(A_TOKEN)).json()
        theirs = c.get("/actuator/desired", headers=as_actuator(B_TOKEN)).json()
        sql(database_url, ("insert into kill_switches values ('acme', 't', 1)", ()))
        killed = c.get("/actuator/desired", headers=as_actuator(A_TOKEN)).json()
    one = {"run_id": 2, "namespace": "shop", "kind": "Deployment", "container": "app"}
    assert [w["name"] for w in mine["sizings"]] == ["approved"]
    assert mine["automated"] == [
        {**one, "name": n, "cpu": 0.115, "memory": None} for n in ("api", "elsewhere", "twice")
    ] + [
        {**one, "kind": "Rollout", "name": "web", "cpu": 0.115, "memory": None},
        {**one, "kind": "StatefulSet", "name": "db", "cpu": 0.115, "memory": None},
    ]
    assert old["automated"] == mine["automated"][:-2]  # an Actuator naming no kinds: no db, web
    assert theirs["automated"] == [{**one, "run_id": 3, "name": "ledger", "cpu": 0.115,
                                    "memory": None}]  # fmt: skip
    assert killed == {
        "kill_switch": True,
        "sizings": [],
        "automated": [],
        "reverts": [],
        "eviction": "off",
    }


def test_the_rollback_that_ends_automation_reaches_the_operator_once(
    settings: Settings, database_url: str
) -> None:
    from tests.test_slack import TOKEN, FakeSlack

    settings.slack_bot_token = SecretStr(TOKEN)
    slack = FakeSlack()
    channel = {"slack": {"operator_channel": "C0123456789"}}
    acme = automating("acme", A_TOKEN, AUTO, **channel)
    settings.database_url = SecretStr(database_url)
    settings.approver_token = SecretStr("approver-token")
    app = create_app(
        settings,
        scripted(),
        lambda c: None,
        {"acme": acme, "bank": automating("bank", B_TOKEN, AUTO)},
        slack_http=httpx.AsyncClient(transport=slack.transport()),
    )
    day = 86400.0
    import time

    now = time.time()

    def back(at: float, **more: Any) -> dict[str, Any]:
        return report(outcome="rolled_back", reason="r", at=at, **more)

    with TestClient(app) as c:
        sql(
            database_url,
            run("acme", '{"test": null}'),
            *(sized("acme", 1, n) for n in ("api", "web")),
            sized("acme", 1, "db", container="sidecar"),  # no container of db is automated
        )
        post = lambda *rs: c.post(  # noqa: E731
            "/actuator/reports", json=list(rs), headers=as_actuator(A_TOKEN)
        )
        post(back(now - 3 * day), back(now - 2 * day))  # two: Automation goes on
        post(back(now - day, container="sidecar"))  # the third, of api's other container
        post(back(now - day + 1))  # the fourth in 7 days: it was already over
        post(back(now - 4 * day, name="web"))
        post(back(now - 2 * day, name="web"), back(now - day, name="web"), back(now, name="web"))
        post(back(now, name="web"))  # sent again: nothing new
        post(*(back(now - d * day, name="db", container="sidecar") for d in (1, 2, 3)))
        c.post("/actuator/reports", json=[back(now - d * day) for d in (1, 2, 3)],
               headers=as_actuator(B_TOKEN))  # bank: no channel  # fmt: skip
    ended = [
        p["text"] for m, p, _ in slack.calls if m == "chat.postMessage" and "ended" in p["text"]
    ]
    until = datetime.fromtimestamp(now - 3 * day + 7 * day, UTC)
    web = datetime.fromtimestamp(now - 2 * day + 7 * day, UTC)
    assert ended == [
        f":octagonal_sign: acme: Automation of test/shop/Deployment/api ended: 3 rollbacks in "
        f"7 days. It resumes on {until:%Y-%m-%d %H:%M} UTC unless more follow; remove "
        "`automate` from its rule to end it for good.",
        f":octagonal_sign: acme: Automation of test/shop/Deployment/web ended: 4 rollbacks in "
        f"7 days. It resumes on {web:%Y-%m-%d %H:%M} UTC unless more follow; remove "
        "`automate` from its rule to end it for good.",
    ]


def applied(core: Any, apps: Any, w: Any) -> dict[str, Any]:
    """`w` applied on both of api's pods; its hold."""
    _, h = start(core, apps, w)
    actuator.advance(core, apps, KEY, h, 600.0)
    actuator.advance(core, apps, KEY, h, 660.0)
    assert h["outcome"] == "applied"
    return h


def test_a_sizing_that_leaves_a_resource_alone_keeps_what_is_held_of_it() -> None:
    core, apps = cluster()  # the template asks cpu 1, no memory
    h = applied(core, apps, wanted())  # cpu 115m, memory 96Mi
    _, new = actuator.apply(core, apps, wanted(2, cpu=None, memory=64 * MI), 700.0, *scalers(), h)
    assert new["requests"] == {"cpu": "115m", "memory": "64Mi"}
    assert new["template"] == {"cpu": "1", "memory": None}
    assert new["lowered_at"] == 700.0  # memory went down
    _, up = actuator.apply(core, apps, wanted(3, cpu=0.2, memory=None), 700.0, *scalers(), h)
    assert up["requests"] == {"cpu": "200m", "memory": "96Mi"} and "lowered_at" not in up
    core, apps = cluster()
    _, caught = start(core, apps, wanted())  # catching up (no hold replaced): not a decrease
    assert "lowered_at" not in caught


def test_automation_ignores_small_changes_and_lowers_at_most_once_a_day() -> None:
    core, apps = cluster()
    h = applied(core, apps, wanted(memory=100 * MI))  # cpu 115m, memory 100Mi

    def auto(at: float = 10**6, old: Any = h, **values: float | None) -> Any:
        w = wanted(2, **({"cpu": None, "memory": None} | values))
        return actuator.apply(core, apps, w, at, *scalers(), old, True)

    assert auto(cpu=0.120) == (None, {})  # 4% up
    assert auto(memory=91 * MI) == (None, {})  # 9% down
    _, ten = auto(memory=110 * MI)  # 10% exactly: applied
    assert ten["requests"] == {"cpu": "115m", "memory": "110Mi"}
    _, first = auto(memory=64 * MI)  # the first decrease
    assert first["requests"]["memory"] == "64Mi" and first["lowered_at"] == 10**6
    recent = {**h, "lowered_at": 10**6 - 86399}
    assert auto(old=recent, memory=64 * MI) == (None, {})  # lowered under a day ago
    _, mixed = auto(old=recent, cpu=0.2, memory=64 * MI)  # the increase goes, memory waits
    assert mixed["requests"] == {"cpu": "200m", "memory": "100Mi"} and "lowered_at" not in mixed
    assert mixed["deferred"] == ["memory"] and "deferred" not in ten  # for an approval of it
    _, day = auto(old={**h, "lowered_at": 10**6 - 86400}, memory=64 * MI)
    assert day["requests"]["memory"] == "64Mi"
    core, apps = cluster()  # nothing held: from the template's cpu 1, no memory
    assert auto(old={}, cpu=0.95) == (None, {})
    _, unset = auto(old={}, memory=50 * MI)  # no request now: set
    assert unset["requests"] == {"memory": "50Mi"}
    _, approved = actuator.apply(core, apps, wanted(cpu=0.95, memory=None), 0.0, *scalers(), {})
    assert approved["requests"] == {"cpu": "950m"}  # an approval is never under the rule


def wants(*runs: Any, approved: tuple[Any, ...] = (), killed: bool = False) -> dict[str, Any]:
    """The Hub's answer: these Automation Sizings, and these approved."""
    return {
        "kill_switch": killed,
        "sizings": [w.model_dump() for w in approved],
        "automated": [w.model_dump() for w in runs],
    }


def test_automation_applies_unasked_and_waits_while_its_container_rolls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(actuator, "CANARY_SECONDS", 0)
    core, apps = cluster()
    seen: list[httpx.Request] = []
    up = wanted(3, cpu=0.5)
    a = make(hub_of([wants(wanted(2)), wants(up), wants(up)], seen), core, apps)
    a.step()  # run 2: the canary
    assert a.held[KEY]["automated"] is True
    a.step()  # the next pod; run 3 waits for the rollout
    assert a.held[KEY]["run_id"] == 2
    a.step()  # run 2 applied, then run 3's canary
    assert [(n, b["spec"]["containers"][0]["resources"]["requests"]["cpu"])
            for n, b in resized(core)] == [("api-1-a", "115m"), ("api-1-b", "115m"),
                                           ("api-1-a", "500m")]  # fmt: skip
    events = [c.args[1] for c in core.create_namespaced_event.call_args_list]
    assert events[0].message.startswith("app: cpu 115m, memory 96Mi (Automation, run 2)")
    posted = [x for r in seen if r.method == "POST" for x in json.loads(r.content)]
    assert [(x["run_id"], x["outcome"]) for x in posted] == [(2, "applied")]


def test_automation_says_a_skip_once_keeps_its_hold_and_backs_off_unsaid() -> None:
    core, apps = cluster()
    h = applied(core, apps, wanted())
    h["automated"] = True
    vpa = {"spec": {"targetRef": {"kind": "Deployment", "name": "api"}}}
    seen: list[httpx.Request] = []
    answers = [
        wants(wanted(4, cpu=0.5)),  # a VPA since: skipped, said
        wants(wanted(5, cpu=0.6)),  # the same reason: unsaid
        wants(wanted(6, cpu=0.12)),  # under 10%: ignored, unsaid
        wants(wanted(6, cpu=0.12)),  # the same run: not even looked at again
        wants(wanted(7, cpu=0.6)),  # backing off: unsaid
        wants(approved=(wanted(8, cpu=0.6),)),  # an approval backing off: said
    ]
    a = make(hub_of(answers, seen), core, apps)
    a.custom = scalers(vpas=[vpa])[1]
    a.held = {KEY: h}
    a.step()
    a.step()
    assert a.held[KEY]["outcome"] == "applied" and a.held[KEY]["requests"]["cpu"] == "115m"
    assert a.held[KEY]["seen"] == 5 and a.held[KEY]["run_id"] == 1  # still holding run 1
    a.custom = scalers()[1]
    a.step()
    assert a.held[KEY]["seen"] == 6 and not resized(core)[2:]
    reads = apps.read_namespaced_deployment.call_count
    a.step()
    assert apps.read_namespaced_deployment.call_count == reads + 2  # hand_back, catch_up
    a.held[KEY]["backoff_until"] = 4e9  # 2096
    a.step()
    a.step()
    posted = [x for r in seen if r.method == "POST" for x in json.loads(r.content)]
    assert [(x["run_id"], x["outcome"], x["reason"][:20]) for x in posted] == [
        (4, "skipped", "a VPA in mode Auto s"),
        (8, "skipped", "rolled back 0 times "),
    ]
    assert len(resized(core)) == 2  # api's two pods, before


def test_an_approval_of_the_run_automation_applied_is_applied_as_approved() -> None:
    core, apps = cluster()
    h = applied(core, apps, wanted(2))
    a = make(hub_of([wants(approved=(wanted(2, cpu=0.12),)), wants(approved=(wanted(2),))], []),
             core, apps)  # fmt: skip
    a.held = {KEY: {**h, "automated": True, "deferred": ["cpu"]}}  # cpu: under the churn rule
    a.step()  # what the churn rule left out still applies once approved
    assert resized(core)[-1] == ("api-1-a", body(cpu="120m", memory="96Mi"))
    assert "automated" not in a.held[KEY]
    a.step()  # the same approval again: once
    assert len(resized(core)) == 3


def paused(apps: Any, *names: str) -> None:
    deployments = [
        MagicMock(metadata=k.V1ObjectMeta(name=n, annotations={actuator.PAUSE: "true"}))
        for n in names
    ]
    apps.list_namespaced_deployment.return_value = MagicMock(items=deployments)


def test_a_paused_deployment_is_left_alone_as_under_the_kill_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(actuator, "CANARY_SECONDS", 0)
    core, apps = cluster()
    paused(apps, "api")
    apps.list_namespaced_deployment.return_value.items.append(
        MagicMock(metadata=k.V1ObjectMeta(name="web", annotations={actuator.PAUSE: "false"}))
    )
    a = make(hub_of([desired(1)] * 7, []), core, apps)
    a.step()  # paused: not applied, not used up
    assert not resized(core) and KEY not in a.held and a.paused == {"shop/Deployment/api"}
    assert actuator.mutation(new_pod()["request"], HELD, "x", a.paused) == []
    assert actuator.mutation(new_pod()["request"], HELD, "x", frozenset({"shop/Deployment/web"}))
    assert actuator.mutation(new_pod()["request"], HELD, "x", frozenset({"shop/StatefulSet/api"}))
    paused(apps)
    a.step()  # lifted: the approval applies
    assert [n for n, _ in resized(core)] == ["api-1-a"]
    paused(apps, "api")
    a.step()  # paused mid-rollout: it stops there
    assert [n for n, _ in resized(core)] == ["api-1-a"]
    apps.list_namespaced_deployment.side_effect = ApiException(status=500)
    a.step()  # its Deployments unreadable: still paused
    assert a.paused == {"shop/Deployment/api"} and len(resized(core)) == 1
    apps.list_namespaced_deployment.side_effect = None
    paused(apps)
    a.step()
    assert [n for n, _ in resized(core)] == ["api-1-a", "api-1-b"]
    a.step()  # applied
    late = pod("api-1-c", "api-1")  # from its template
    late.metadata.namespace = "shop"
    core.list_namespaced_pod.return_value.items.append(late)
    paused(apps, "api")
    a.step()  # paused: no catching up either
    assert a.held[KEY]["outcome"] == "applied" and len(resized(core)) == 2


def test_the_hub_unanswered_15_minutes_is_said_once_in_an_event() -> None:
    core = MagicMock()
    a = make(hub_of([], []), core, MagicMock())
    for at in (0.0, 899.0):
        a.answered(False, at)
    assert not core.create_namespaced_event.called
    for at in (900.0, 2000.0):
        a.answered(False, at)
    a.answered(True, 2001.0)
    for at in (2002.0, 2901.0, 2902.0):  # once more, after it answered in between
        a.answered(False, at)
    events = [c.args for c in core.create_namespaced_event.call_args_list]
    assert [(ns, e.reason, e.type, e.involved_object.kind, e.involved_object.name)
            for ns, e in events] == [
        ("squero-actuator", "HubUnreachable", "Warning", "ConfigMap", "squero-actuator")
    ] * 2  # fmt: skip
    assert events[0][1].message == (
        "the Hub has not answered for 15 minutes: holding what it applied, changing nothing new"
    )


def test_approving_what_automation_already_applied_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(actuator, "CANARY_SECONDS", 0)
    for rolling, deferred in ((False, False), (True, False), (True, True)):
        core, apps = cluster()
        steps = 1 if rolling else 3  # Automation's canary; then the next pod; then applied
        answers = [wants(wanted(2))] * steps + [wants(approved=(wanted(2),))]
        a = make(hub_of(answers, []), core, apps)
        for _ in range(steps):
            a.step()
        assert a.held[KEY]["outcome"] == ("rolling" if rolling else "applied")
        if deferred:  # the churn rule left one out: it waits for this rollout to end
            a.held[KEY]["deferred"] = ["memory"]
        moving = ("automated", "since", "resized", "pod")  # a rollout moves on by itself
        before = {k: v for k, v in a.held[KEY].items() if k not in moving}
        count = len(resized(core))
        a.step()  # the Operator approves the same run
        assert {k: v for k, v in a.held[KEY].items() if k not in moving} == before
        assert ("automated" in a.held[KEY]) == deferred
        assert len(resized(core)) == count + rolling
        if not rolling:
            assert actuator.mutation(new_pod()["request"], a.held, "x")  # still held


def test_a_reason_is_the_same_whatever_its_numbers() -> None:
    quota = "3 pods at cpu 500m would pass ResourceQuota q's requests.cpu 2"
    assert actuator.gist(quota) == actuator.gist(quota.replace("500m", "600m").replace("3", "4"))
    assert actuator.gist(quota) != actuator.gist("a VPA in mode Auto sizes it")


# --- Revert (slice 12.6a) -----------------------------------------------------------------


def revert(
    cid: str, at: float, name: str = "api", ns: str = "shop", kind: str = "Deployment"
) -> Any:
    return (
        "insert into reverts (contract_id, cluster, namespace, kind, name, container, "
        "asked_by, asked_at) values (%s, 'test', %s, %s, %s, 'app', 'mcp:x', %s)",
        (cid, ns, kind, name, at),
    )


def test_an_actuator_gets_its_own_pending_reverts_and_automation_stops_until_an_approval(
    settings: Settings, database_url: str
) -> None:
    import time

    now = time.time()
    app = hub(settings, database_url, automating("acme", A_TOKEN, AUTO), actuated("bank", B_TOKEN))
    with TestClient(app) as c:
        sql(
            database_url,
            run("acme", '{"test": null}'),
            sized("acme", 1),
            sized("acme", 1, "web"),
            revert("acme", now - 60),
            revert("acme", now - 60, "web"),
            revert("acme", now - 60, ns="old"),  # no longer one of the cluster's namespaces
            revert("acme", now - 60, "db", kind="StatefulSet"),  # to an Actuator that names it
            revert("bank", now - 60, "ledger"),
            # none of these closes api's Revert or resumes its Automation: from before it
            rolled_back("acme", now - 120, outcome="reverted"),
            (
                "insert into approved_sizings values ('acme', 0, 'test', 'shop', 'Deployment', "
                "'api', 'app', 1, null, 't', %s)",
                (now - 120,),
            ),
            approve("acme", 1),  # current, but older than api's Revert: never applied now
        )
        applied = report(name="api", reason="applied", at=now)  # nor an Actuation not a Revert
        c.post("/actuator/reports", json=[applied], headers=as_actuator(A_TOKEN))
        first = c.get("/actuator/desired", headers=as_actuator(A_TOKEN)).json()
        kinds = {"kinds": "Deployment,StatefulSet"}
        named = c.get("/actuator/desired", headers=as_actuator(A_TOKEN), params=kinds).json()
        done = report(outcome="reverted", name="web", reason="reverted", at=now)
        c.post("/actuator/reports", json=[done], headers=as_actuator(A_TOKEN))
        # web is approved since its Revert: Automation of it goes on
        sql(database_url, ("insert into approved_sizings values ('acme', 0, 'test', 'shop', "
                           "'Deployment', 'web', 'app', 1, null, 't', %s)", (now,)))  # fmt: skip
        after = c.get("/actuator/desired", headers=as_actuator(A_TOKEN)).json()
        sql(database_url, ("insert into kill_switches values ('acme', 't', 1)", ()))
        killed = c.get("/actuator/desired", headers=as_actuator(A_TOKEN)).json()
    undo = {"namespace": "shop", "kind": "Deployment", "container": "app"}
    assert [{k: r[k] for k in ("namespace", "kind", "name", "container")} for r in
            first["reverts"]] == [{**undo, "name": "api"}, {**undo, "name": "web"}]  # fmt: skip
    assert [r["name"] for r in named["reverts"]] == ["api", "web", "db"]
    assert first["automated"] == [] and first["sizings"] == []  # reverted, unapproved since
    assert [r["name"] for r in after["reverts"]] == ["api"]  # web's is done
    assert [w["name"] for w in after["automated"]] == ["web"]
    assert killed["reverts"] == []


def test_a_revert_puts_the_pods_back_and_holds_them_no_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(actuator, "CANARY_SECONDS", 0)
    core, apps = cluster()
    undo = {"id": 7, "namespace": "shop", "kind": "Deployment", "name": "api", "container": "app"}

    def undoing(*ids: int, **more: Any) -> dict[str, Any]:
        return {**desired(1), "reverts": [{**undo, "id": i, **more} for i in ids]}

    seen: list[httpx.Request] = []
    answers = [desired(1), desired(1), desired(1), undoing(7), undoing(7),
               undoing(8, name="web"), undoing(9)]  # fmt: skip
    a = make(hub_of(answers, seen), core, apps)
    for _ in range(3):
        a.step()  # run 1 applied on both pods
    assert a.held[KEY]["outcome"] == "applied"
    core.patch_namespaced_pod_resize.reset_mock()
    a.step()  # Revert 7
    assert resized(core) == [("api-1-a", body(cpu="1")), ("api-1-b", body(cpu="1"))]
    assert a.held[KEY]["outcome"] == "reverted" and a.held[KEY]["revert"] == 7
    assert actuator.mutation(new_pod()["request"], a.held, "x") == []  # held no more
    a.step()  # Revert 7 again, and run 1 again: nothing
    a.step()  # a Revert of what it never held: said so
    paused(apps, "api")
    a.step()  # paused: Revert 9 waits
    assert len(resized(core)) == 2 and a.held[KEY]["revert"] == 7
    posted = [x for r in seen if r.method == "POST" for x in json.loads(r.content)]
    assert [(x["name"], x["outcome"], x["pods"], x["reason"]) for x in posted[1:]] == [
        ("api", "reverted", 2,
         "reverted by the Operator (7): 2 pods back from cpu 115m, memory 96Mi to their "
         "template's cpu 1 (['memory'] left: the template sets none)"),
        ("web", "reverted", 0, "reverted by the Operator (8): nothing held"),
    ]  # fmt: skip
    events = [c.args[1] for c in core.create_namespaced_event.call_args_list]
    assert (events[1].reason, events[1].type) == ("SizingReverted", "Normal")
    assert events[1].message.startswith("app: back to its template (Approved Sizing, run 1)")


def test_approving_after_a_revert_applies_and_a_revert_seen_again_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(actuator, "CANARY_SECONDS", 0)
    core, apps = cluster()
    undo = {"id": 7, "namespace": "shop", "kind": "Deployment", "name": "api", "container": "app"}
    answers = [
        *[wants(wanted(2))] * 3,  # Automation applies run 2
        {**wants(), "reverts": [undo]},  # the Operator reverts it
        wants(approved=(wanted(2),)),  # then approves that same run: it applies again
        {**wants(approved=(wanted(2),)), "reverts": [undo]},  # its report not taken yet
    ]
    a = make(hub_of(answers, []), core, apps)
    for _ in range(4):
        a.step()
    assert a.held[KEY]["outcome"] == "reverted"
    count = len(resized(core))
    a.step()
    assert len(resized(core)) == count + 1 and a.held[KEY]["outcome"] == "rolling"
    assert a.held[KEY]["revert"] == 7  # kept across the new hold
    a.step()  # Revert 7 again: done already
    assert a.held[KEY]["outcome"] == "rolling"


def test_a_catch_up_keeps_the_last_revert_it_did() -> None:
    core, apps = cluster()
    h = applied(core, apps, wanted(memory=None))
    late = pod("api-1-c", "api-1")  # from its template: behind
    late.metadata.namespace = "shop"
    core.list_namespaced_pod.return_value.items.append(late)
    a = make(hub_of([], []), core, apps)
    a.held = {KEY: {**h, "revert": 7}}
    a.catch_up()
    assert a.held[KEY]["outcome"] == "rolling" and a.held[KEY]["revert"] == 7


# --- the console's Automation view (slice 12.6b) ------------------------------------------


def test_the_automation_view_shows_the_contracts_own_containers_and_reverts_one(
    settings: Settings, database_url: str
) -> None:
    import time

    from tests.test_console import AS_OPERATOR, OPERATOR, VIEW

    settings.console_operators = {OPERATOR}
    now = time.time()
    app = hub(settings, database_url, automating("acme", A_TOKEN, AUTO), actuated("bank", B_TOKEN))
    path, same = "/api/v1/contracts/acme/automation", {**VIEW, "Sec-Fetch-Site": "same-origin"}
    with TestClient(app) as c:
        sql(
            database_url,
            rolled_back("acme", now - 3000, name="api", outcome="skipped"),
            rolled_back("acme", now - 2000, name="api", outcome="applied"),  # api's last
            *(rolled_back("acme", now - d * 86400, name="web") for d in (1, 2, 3)),
            rolled_back("acme", now - 100, name="db", outcome="applied"),
            revert("acme", now - 50, "db"),  # pending, and stops db's Automation
            rolled_back("acme", now - 100, "edge", "api", "skipped"),  # edge runs no Actuator
            (
                "insert into actuations values ('acme', 'test', 'old', 'Deployment', 'x', 'app', "
                "1, 'applied', null, null, 1, 'x', 1, 1)",
                (),
            ),  # no longer one of its namespaces
            rolled_back("bank", now - 100, name="ledger", outcome="applied"),
            (
                "insert into actuations values ('acme', 'test', 'shop', 'Deployment', 'side', "
                "'sidecar', 1, 'applied', null, null, 1, 'x', 1, 1)",
                (),
            ),  # no rule automates it
        )
        page = c.get(path, headers=VIEW).json()
        what = {"cluster": "test", "namespace": "shop", "name": "api", "container": "app"}
        cross, no_token = {**VIEW, "Sec-Fetch-Site": "cross-site"}, {**AS_OPERATOR, **same}
        no_token.pop("Cookie")
        refused = [
            c.post(f"{path}/revert", json=what, headers=h).status_code for h in (cross, no_token)
        ]
        done = c.post(f"{path}/revert", json=what, headers=same)
        never = c.post(f"{path}/revert", json={**what, "name": "ledger"}, headers=same)
        sql(database_url, ("insert into kill_switches values ('acme', 't', 1)", ()))
        killed = c.post(f"{path}/revert", json=what, headers=same)
        shows_killed = c.get(path, headers=VIEW).json()["kill_switch"]
        theirs = c.get("/api/v1/contracts/bank/automation", headers=VIEW).json()
        no_cookie = c.get(path, headers=AS_OPERATOR).status_code
    assert refused == [403, 401] and no_cookie == 401
    (cluster,) = page["clusters"]
    assert cluster["cluster"] == "test" and not page["kill_switch"]
    shown = {h["name"]: h for h in cluster["containers"]}
    assert list(shown) == ["api", "db", "side", "web"] and shows_killed
    assert not shown["side"]["automated"]
    assert shown["api"]["outcome"] == "applied" and shown["api"]["automated"]
    assert shown["api"]["resumes"] is None and not shown["api"]["stopped"]
    assert shown["db"]["stopped"] and shown["db"]["reverting"]
    assert shown["web"]["resumes"] == pytest.approx(now - 3 * 86400 + 7 * 86400)
    assert done.status_code == 200
    assert next(h for h in done.json()["clusters"][0]["containers"] if h["name"] == "api")[
        "reverting"
    ]
    assert never.status_code == 409 and "reported nothing" in never.json()["detail"]
    assert killed.status_code == 409 and "Kill switch is on" in killed.json()["detail"]
    assert [h["name"] for h in theirs["clusters"][0]["containers"]] == ["ledger"]
    rows = sql(database_url, ("select name, asked_by from reverts order by id", ()))
    assert rows == [("db", "mcp:x"), ("api", f"console:{OPERATOR}")]


# --- eviction in windows (slice 12.7) --------------------------------------------------------


def evicting(cid: str, token: str, block: dict[str, Any]) -> contracts.Contract:
    data = actuated(cid, token).model_dump(mode="json", exclude_defaults=True)
    data["actuator"] = block
    return contracts.build(data, secrets={"act": SecretStr(token)})


NIGHTS = {"days": ["fri", "sat"], "start": "22:00", "end": "02:00"}


def test_a_window_opens_on_its_days_in_its_timezone_a_night_belonging_to_its_start() -> None:
    rome = contracts.ActuatorConfig(eviction=True, timezone="Europe/Rome", windows=[NIGHTS])
    at = lambda s: datetime.fromisoformat(s)  # noqa: E731
    assert rome.evicting(at("2026-11-13T21:00:00+00:00")) == "open"  # Friday 22:00 in Rome
    assert rome.evicting(at("2026-11-13T20:59:00+00:00")) == "closed"  # 21:59
    assert rome.evicting(at("2026-11-14T00:59:00+00:00")) == "open"  # Saturday 01:59: Friday's
    assert rome.evicting(at("2026-11-14T01:00:00+00:00")) == "closed"  # 02:00: ended
    assert rome.evicting(at("2026-11-15T00:30:00+00:00")) == "open"  # Sunday 01:30: Saturday's
    assert rome.evicting(at("2026-11-16T00:30:00+00:00")) == "closed"  # Monday 01:30: Sunday's
    assert rome.evicting(at("2026-11-12T21:30:00+00:00")) == "closed"  # Thursday 22:30
    day = contracts.Window(days=["sun"], start="00:00", end="24:00")
    assert day.holds(6, 0) and day.holds(6, 1439) and not day.holds(0, 0) and not day.holds(5, 1439)
    off = contracts.ActuatorConfig(windows=[NIGHTS])  # windows alone evict nothing
    assert off.evicting(at("2026-11-13T21:00:00+00:00")) == "off"
    utc = contracts.ActuatorConfig(
        eviction=True, windows=[{"days": ["fri"], "start": "22:00", "end": "23:00"}]
    )
    assert utc.evicting(at("2026-11-13T22:00:00+00:00")) == "open"  # UTC unless it says
    assert utc.evicting(at("2026-11-13T23:00:00+00:00")) == "closed"  # its end: closed


@pytest.mark.parametrize(
    ("block", "error"),
    [
        ({"eviction": True}, "eviction needs at least one window"),
        ({"timezone": "Mars/Olympus"}, "no timezone 'Mars/Olympus'"),
        ({"windows": [{**NIGHTS, "end": "22:00"}]}, "from 22:00 to 22:00 is no window"),
        ({"windows": [{**NIGHTS, "start": "24:00"}]}, "from 24:00 to 02:00 is no window"),
        ({"windows": [{**NIGHTS, "end": "25:00"}]}, "String should match pattern"),
        ({"windows": [{**NIGHTS, "days": []}]}, "at least 1 item"),
        ({"windows": [{**NIGHTS, "days": ["fry"]}]}, "Input should be 'mon'"),
    ],
)
def test_an_actuator_block_that_cannot_work_is_refused(block: dict[str, Any], error: str) -> None:
    with pytest.raises(ValueError, match=error):
        evicting("acme", A_TOKEN, block)


def test_eviction_needs_a_cluster_that_runs_an_actuator() -> None:
    data = actuated("acme", A_TOKEN).model_dump(mode="json", exclude_defaults=True)
    data["clusters"][0].pop("actuator_token_secret")
    data["actuator"] = {"eviction": True, "windows": [NIGHTS]}
    with pytest.raises(ValueError, match="eviction, but no cluster has an actuator_token_secret"):
        contracts.build(data, secrets={})


def test_an_actuator_hears_only_its_own_contracts_eviction_window(
    settings: Settings, database_url: str
) -> None:
    today = datetime.now(UTC).weekday()
    always = {"days": list(contracts.DAYS), "start": "00:00", "end": "24:00"}
    never = {"days": [d for i, d in enumerate(contracts.DAYS) if (i - today) % 7 not in (0, 1, 6)]}
    never |= {"start": "00:00", "end": "24:00"}  # not today, nor a day whose night runs into it
    acme = evicting("acme", A_TOKEN, {"eviction": True, "windows": [always]})
    bank = actuated("bank", B_TOKEN)
    shut = evicting("shut", "c" * 40, {"eviction": True, "windows": [never]})
    app = hub(settings, database_url, acme, bank, shut)
    with TestClient(app) as c:
        seen = [
            c.get("/actuator/desired", headers=as_actuator(t)).json()["eviction"]
            for t in (A_TOKEN, B_TOKEN, "c" * 40)
        ]
        sql(database_url, ("insert into kill_switches values ('acme', 't', 1)", ()))
        killed = c.get("/actuator/desired", headers=as_actuator(A_TOKEN)).json()["eviction"]
    assert seen == ["open", "off", "closed"] and killed == "off"


def infeasible(core: Any) -> None:
    """api-1-a's resize Infeasible from now on."""
    core.read_namespaced_pod.side_effect = None
    core.read_namespaced_pod.return_value = pending("Infeasible", "Node didn't have enough")


def up(name: str, ready: bool = True, phase: str = "Running", **requests: str) -> Any:
    """A new pod of api-1 (a replacement), Ready or not."""
    p = pod(name, "api-1", phase=phase, **requests)
    p.metadata.namespace = "shop"
    p.status.conditions = [k.V1PodCondition(type="Ready", status="True" if ready else "False")]
    allocated = k.V1ResourceRequirements(requests=p.spec.containers[0].resources.requests)
    p.status.container_statuses = [status("app", allocated)]
    return p


def evicted(core: Any) -> list[tuple[str, str, str]]:
    return [
        (c.args[0], c.args[1], c.args[2].metadata.name)
        for c in core.create_namespaced_pod_eviction.call_args_list
    ]


def reasons(core: Any) -> list[str]:
    return [c.args[1].reason for c in core.create_namespaced_event.call_args_list]


def test_an_infeasible_pod_waits_for_the_window_then_is_evicted_and_replaced() -> None:
    core, apps = cluster()
    _, held = start(core, apps, wanted())
    infeasible(core)
    for at in (60.0, 120.0, 5000.0):  # no 10 minutes' limit while it waits
        assert actuator.advance(core, apps, KEY, held, at, "closed", PDB) is None
    assert reasons(core) == ["EvictionWaiting"] and held["waiting"] == "window"
    assert not core.create_namespaced_pod_eviction.called
    message = core.create_namespaced_event.call_args.args[1].message
    assert message.startswith("api-1-a: Infeasible: Node didn't have enough; it waits")
    assert actuator.advance(core, apps, KEY, held, 6000.0, "open", PDB) is None
    assert evicted(core) == [("api-1-a", "shop", "api-1-a")]
    assert held["evicted"] == {"pod": "api-1-a", "at": 6000.0, "before": ["api-1-a", "api-1-b"]}
    assert held["evicted_at"] == 6000.0 and "waiting" not in held
    assert reasons(core) == ["EvictionWaiting", "PodEvicted"]
    assert "its replacement starts with cpu 115m, memory 96Mi" in (
        core.create_namespaced_event.call_args.args[1].message
    )
    pods = core.list_namespaced_pod.return_value.items
    pods[0].metadata.deletion_timestamp = datetime.now(UTC)  # api-1-a goes
    pods[1] = up("api-1-b")  # Ready, but no replacement: it was there before
    pods.append(up("api-1-c", ready=False, cpu="115m", memory="96Mi"))
    assert actuator.advance(core, apps, KEY, held, 6060.0, "open", PDB) is None  # not Ready yet
    assert "evicted" in held and len(evicted(core)) == 1
    pods[-1] = up("api-1-c", cpu="115m", memory="96Mi")  # the webhook gave it the requests
    assert actuator.advance(core, apps, KEY, held, 6120.0, "open", PDB) is None
    assert "evicted" not in held and (held["pod"], held["since"]) == ("api-1-c", 6120.0)
    assert held["canary_until"] == 6120.0 + 600  # the canary's 10 minutes, again
    assert held["pods"]["api-1-c"] == {"at": 6120.0, "restarts": 0}
    core.read_namespaced_pod.side_effect = lambda name, ns: up(name, cpu="115m", memory="96Mi")
    assert actuator.advance(core, apps, KEY, held, 6719.0, "open", PDB) is None
    assert actuator.advance(core, apps, KEY, held, 6720.0, "open", PDB) is None  # the next: b
    assert resized(core)[-1] == ("api-1-b", body(cpu="115m", memory="96Mi"))
    done = actuator.advance(core, apps, KEY, held, 6780.0, "open", PDB)
    assert done is not None and (done.outcome, done.pods) == ("applied", 2)
    assert done.reason == (
        "2 of 2 pods resized in place, one at a time; api-1-a evicted, its resize Infeasible"
    )
    assert held["evicted_at"] == 6000.0  # kept: the next eviction 5 minutes after


def test_a_disruption_budget_holds_an_eviction_and_other_refusals_fail_the_rollout() -> None:
    core, apps = cluster()
    _, held = start(core, apps, wanted())
    infeasible(core)
    core.create_namespaced_pod_eviction.side_effect = refusal(429, "would violate the budget")
    for at in (60.0, 120.0):
        assert actuator.advance(core, apps, KEY, held, at, "open", PDB) is None
        assert "evicted" not in held  # refused: nothing to wait for
    assert held["waiting"] == "budget" and "evicted" not in held and "evicted_at" not in held
    assert reasons(core) == ["EvictionWaiting"]
    assert "a PodDisruptionBudget allows no eviction now" in (
        core.create_namespaced_event.call_args.args[1].message
    )
    core.create_namespaced_pod_eviction.side_effect = refusal(403, "forbidden")
    failed = actuator.advance(core, apps, KEY, held, 180.0, "open", PDB)
    assert failed is not None and failed.outcome == "failed"
    assert failed.reason == "evicting api-1-a: 403: forbidden"
    assert "evicted" not in held and "waiting" not in held
    off = start(core, apps, wanted())[1]
    gone = actuator.advance(core, apps, KEY, off, 60.0, "off")  # as before slice 12.7
    assert gone is not None and gone.outcome == "failed" and "Infeasible" in gone.reason


def test_a_replacement_the_webhook_missed_ends_the_rollout() -> None:
    core, apps = cluster()
    _, held = start(core, apps, wanted())
    infeasible(core)
    actuator.advance(core, apps, KEY, held, 60.0, "open", PDB)
    core.list_namespaced_pod.return_value.items.append(up("api-1-c"))  # its template's cpu 1
    failed = actuator.advance(core, apps, KEY, held, 120.0, "open", PDB)
    assert failed is not None and failed.outcome == "failed"
    assert failed.reason == (
        "api-1-c, replacing evicted api-1-a, started from its template; "
        "api-1-a evicted, its resize Infeasible"
    )
    assert "evicted" not in held and len(evicted(core)) == 1  # never again, in a loop


def test_a_replacement_not_ready_in_10_minutes_is_rolled_back_and_evicted_if_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(actuator.time, "time", lambda: 660.0)
    core, apps = cluster()
    _, held = start(core, apps, wanted())
    infeasible(core)
    actuator.advance(core, apps, KEY, held, 60.0, "open", PDB)
    pods = core.list_namespaced_pod.return_value.items
    pods[0].metadata.deletion_timestamp = datetime.now(UTC)
    pods[1] = up("api-1-b", phase="Pending")  # Ready or not, there before: not a replacement
    pods[1].status.conditions[0].status = "True"
    stuck = up("api-1-c", ready=False, phase="Pending", cpu="115m", memory="96Mi")
    pods.append(stuck)
    assert actuator.trouble(core, apps, KEY, held, 659.0) is None  # 10 minutes not yet
    assert actuator.trouble(core, apps, KEY, held, 660.0) == (
        "api-1-a evicted: no replacement Ready in 10 minutes"
    )
    pods[-1] = up("api-1-c", cpu="115m", memory="96Mi")  # up, though advance() never saw it
    assert actuator.trouble(core, apps, KEY, held, 660.0) is None
    pods[-1] = stuck
    pods.append(up("api-1-d", ready=False, cpu="115m", memory="96Mi"))  # running: in place
    held_then: list[bool] = []
    core.create_namespaced_pod_eviction.side_effect = lambda *_: held_then.append("evicted" in held)
    a = actuator.Actuator(MagicMock(), core, apps, "x", held={KEY: held})
    (back,) = a.watch()
    assert held_then == [False]  # let go first: the webhook gives its replacement nothing
    assert [n for n, _ in resized(core)][-1] == "api-1-d"
    assert back.outcome == "rolled_back"
    assert "; 1 Pending replacement evicted to start from its template" in back.reason
    assert evicted(core)[1:] == [("api-1-c", "shop", "api-1-c")]  # nor api-1-b, Pending
    assert all(n != "api-1-c" for n, _ in resized(core))  # evicted, never resized
    assert "evicted" not in held and held["outcome"] == "rolled_back"


def test_the_webhook_sizes_a_replacement_only_while_its_eviction_is_outstanding() -> None:
    rolling = {k: {**v, "outcome": "rolling"} for k, v in HELD.items()}
    assert patched(new_pod(), held=rolling) is None  # a rollout's new pods: from the template
    out = {
        k: {**v, "evicted": {"pod": "api-1-a", "at": 0.0, "before": []}} for k, v in rolling.items()
    }
    assert patched(new_pod(), held=out) == patched(new_pod())


def test_one_eviction_at_a_time_and_five_minutes_apart(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(actuator.time, "time", lambda: clock[0])
    core, apps = cluster()
    _, first = start(core, apps, wanted())
    other = {**first, "pod": "api-1-b"}
    infeasible(core)
    a = actuator.Actuator(
        MagicMock(),
        core,
        apps,
        "x",
        held={KEY: first, "shop/Deployment/api/side": other},
        policy=PDB,
    )
    a.advance("open")
    assert evicted(core) == [("api-1-a", "shop", "api-1-a")]  # the second waits: one at a time
    assert a.held["shop/Deployment/api/side"]["waiting"] == "window"
    del first["evicted"]  # its replacement up
    clock[0] = 1299.0
    a.advance("open")
    assert len(evicted(core)) == 1  # 5 minutes not yet
    clock[0] = 1300.0
    a.advance("open")
    assert len(evicted(core)) == 2
    a.advance("closed")
    assert len(evicted(core)) == 2
    first["evicted"] = {"pod": "api-1-a", "at": 0.0, "before": ["api-1-a", "api-1-b"]}
    core.list_namespaced_pod.return_value.items[0].metadata.deletion_timestamp = datetime.now(UTC)
    first["evicted_at"] = 0.0
    a.held["shop/Deployment/api/side"].pop("evicted", None)
    a.held["shop/Deployment/api/side"]["evicted_at"] = 0.0
    clock[0] = 9000.0
    a.advance("open")
    assert len(evicted(core)) == 2  # one replacement still awaited: no other eviction


def test_each_minute_passes_the_hubs_eviction_word_to_the_rollouts() -> None:
    core, apps = cluster()
    open_ = {**desired(1), "eviction": "open"}
    a = make(hub_of([open_, open_], []), core, apps)
    a.step()  # the canary
    infeasible(core)
    a.step()
    assert evicted(core) == [("api-1-a", "shop", "api-1-a")]


def test_a_newer_automation_sizing_replaces_a_rollout_waiting_to_evict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(actuator.time, "time", lambda: 100.0)
    core, apps = cluster()
    a = make(MagicMock(), core, apps)
    a.act([], [wanted(1, memory=None)])
    assert a.held[KEY]["outcome"] == "rolling"
    a.act([], [wanted(2, cpu=0.5, memory=None)])
    assert a.held[KEY]["run_id"] == 1  # rolling: waits, unsaid
    a.held[KEY] |= {"waiting": "window", "evicted_at": 50.0}
    a.act([], [wanted(3, cpu=0.5, memory=None)])
    assert a.held[KEY]["run_id"] == 3 and a.held[KEY]["outcome"] == "rolling"
    assert a.held[KEY]["evicted_at"] == 50.0 and "waiting" not in a.held[KEY]
    a.held[KEY] = {**a.held[KEY], "outcome": "applied", "pods": {}}
    core.list_namespaced_pod.return_value.items.append(up("api-1-c"))  # behind its hold
    a.catch_up()
    assert a.held[KEY]["evicted_at"] == 50.0  # kept through a catch-up too


def test_a_deployment_scaled_down_after_an_eviction_owes_no_replacement() -> None:
    core, apps = cluster()
    _, held = start(core, apps, wanted())
    infeasible(core)
    actuator.advance(core, apps, KEY, held, 60.0, "open", PDB)
    core.list_namespaced_pod.return_value.items[0].metadata.deletion_timestamp = datetime.now(UTC)
    assert actuator.trouble(core, apps, KEY, held, 660.0) is not None  # 1 of 2: one owed
    apps.read_namespaced_deployment.return_value.spec.replicas = 1  # its HPA scaled it down
    assert actuator.trouble(core, apps, KEY, held, 660.0) is None  # no Rollback for that
    assert actuator.advance(core, apps, KEY, held, 120.0, "open", PDB) is None
    assert "evicted" not in held  # the rollout goes on with the pods it has


def test_no_sizing_replaces_a_hold_while_its_evicted_pods_replacement_is_awaited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(actuator.time, "time", lambda: 100.0)
    core, apps = cluster()
    a = make(MagicMock(), core, apps)
    a.act([wanted(1)])
    a.held[KEY]["evicted"] = {"pod": "api-1-a", "at": 90.0, "before": ["api-1-a", "api-1-b"]}
    a.act([wanted(2, cpu=0.5)], [wanted(3, cpu=0.6)])
    assert a.held[KEY]["run_id"] == 1 and "evicted" in a.held[KEY]  # both wait
    del a.held[KEY]["evicted"]
    a.act([wanted(2, cpu=0.5)])
    assert a.held[KEY]["run_id"] == 2


ROOMLESS = 'pods "api-1-a" is forbidden: node didn\'t have enough allocatable resources: cpu'


def test_a_resize_the_api_server_refuses_for_want_of_room_is_evicted_as_infeasible() -> None:
    """Kubernetes 1.35+ refuses at once a resize its node can never fit, where 1.33 marks
    the pod's resize Infeasible (found in the live check on 1.37)."""
    core, apps = cluster()
    core.patch_namespaced_pod_resize.side_effect = refusal(403, ROOMLESS)
    off, _ = actuator.apply(core, apps, wanted(), 0.0, *scalers())  # off: failed, as before
    assert off is not None and off.outcome == "failed" and "enough allocatable" in off.reason
    other = refusal(403, "forbidden: something else")
    core.patch_namespaced_pod_resize.side_effect = other
    a, _ = actuator.apply(core, apps, wanted(), 0.0, *scalers(), eviction="open")
    assert a is not None and a.outcome == "failed"  # only want of room is evicted
    core.patch_namespaced_pod_resize.side_effect = refusal(403, ROOMLESS)
    a, held = actuator.apply(core, apps, wanted(), 0.0, *scalers(), eviction="closed")
    assert a is None and held["outcome"] == "rolling" and held["no_room"] == ROOMLESS
    assert actuator.advance(core, apps, KEY, held, 6000.0, "closed", PDB) is None  # no 10 minutes
    assert reasons(core) == ["EvictionWaiting"]
    assert actuator.advance(core, apps, KEY, held, 6060.0, "open", PDB) is None
    assert evicted(core) == [("api-1-a", "shop", "api-1-a")]
    pods = core.list_namespaced_pod.return_value.items
    pods[0].metadata.deletion_timestamp = datetime.now(UTC)
    pods.append(up("api-1-c", cpu="115m", memory="96Mi"))
    assert actuator.advance(core, apps, KEY, held, 6120.0, "open", PDB) is None
    assert "no_room" not in held and held["pod"] == "api-1-c"
    core.patch_namespaced_pod_resize.side_effect = refusal(403, ROOMLESS)  # b: no room either
    core.read_namespaced_pod.side_effect = lambda name, ns: up(name, cpu="115m", memory="96Mi")
    off = json.loads(json.dumps(held))
    assert actuator.advance(core, apps, KEY, held, 6720.0, "open", PDB) is None
    assert (held["pod"], held["no_room"], held["resized"]) == ("api-1-b", ROOMLESS, 2)
    ended = actuator.advance(core, apps, KEY, off, 6720.0, "off")  # off meanwhile: as before
    assert ended is not None and ended.outcome == "failed"
    assert ended.reason.startswith("resizing its next pod: 403: ")


def test_the_actuator_keeps_the_hubs_eviction_word_for_new_rollouts() -> None:
    core, apps = cluster()
    core.patch_namespaced_pod_resize.side_effect = refusal(403, ROOMLESS)
    closed = {**desired(1), "eviction": "closed"}
    a = make(hub_of([closed], []), core, apps)
    a.step()
    assert a.eviction == "closed" and a.held[KEY]["no_room"] == ROOMLESS
    assert a.held[KEY]["outcome"] == "rolling"  # waits for a window, not failed


def test_a_pod_without_a_disruption_budget_or_a_second_replica_is_never_evicted() -> None:
    other = k.V1LabelSelector(match_labels={"app": "web"})
    none = "no PodDisruptionBudget covers it, so it is never evicted"
    one = "it has one replica, so it is never evicted"
    for policy, replicas, eviction, why_ in (
        (budgets(), 2, "closed", none),  # no wait for a window that changes nothing
        (budgets(other, None), 2, "open", none),
        (budgets(refusal(403, "forbidden")), 2, "open", "not evicted: checking it: 403: forbidden"),
        (PDB, 1, "open", one),
        (PDB, None, "closed", one),
    ):
        core, apps = cluster()
        apps.read_namespaced_deployment.return_value.spec.replicas = replicas
        _, held = start(core, apps, wanted())
        infeasible(core)
        failed = actuator.advance(core, apps, KEY, held, 60.0, eviction, policy)
        assert failed is not None and failed.outcome == "failed"
        assert failed.reason == (
            f"api-1-a: Infeasible: Node didn't have enough; 0 other pods resized; {why_}"
        )
        assert "waiting" not in held and not core.create_namespaced_pod_eviction.called
    core, apps = cluster()
    _, held = start(core, apps, wanted())
    infeasible(core)
    off = actuator.advance(core, apps, KEY, held, 60.0, "off", None)  # nothing read
    assert off is not None and off.reason.endswith("0 other pods resized")


@pytest.mark.parametrize(
    ("selector", "matches"),
    [
        (None, False),
        (k.V1LabelSelector(), True),
        (k.V1LabelSelector(match_labels={"app": "api"}), True),
        (k.V1LabelSelector(match_labels={"app": "api", "tier": "x"}), False),
        *[
            (
                k.V1LabelSelector(
                    match_expressions=[k.V1LabelSelectorRequirement(key=key, operator=op, values=v)]
                ),
                m,
            )
            for key, op, v, m in (
                ("app", "In", ["web", "api"], True),
                ("app", "In", ["web"], False),
                ("tier", "In", ["x"], False),
                ("app", "NotIn", ["api"], False),
                ("app", "NotIn", ["web"], True),
                ("tier", "NotIn", ["x"], True),
                ("app", "Exists", None, True),
                ("tier", "Exists", None, False),
                ("tier", "DoesNotExist", None, True),
                ("app", "DoesNotExist", None, False),
                ("app", "Bogus", None, False),
            )
        ],
    ],
)
def test_a_disruption_budgets_selector_matches_as_kubernetes_does(
    selector: Any, matches: bool
) -> None:
    assert actuator.selects(selector, {"app": "api"}) is matches


# --- StatefulSets and DaemonSets (slice 12.8a) ---------------------------------------------


def kinded(kind: str, **kw: Any) -> tuple[Any, Any]:
    """cluster(), api a `kind` (uid u1) owning api-1's pods itself; api-x-a another's."""
    core, apps = cluster(**kw)
    d = apps.read_namespaced_deployment.return_value
    on = {"selector": d.spec.selector, "template": d.spec.template}
    getattr(apps, f"read_namespaced_{actuator.KINDS[kind]}").return_value = (
        k.V1StatefulSet(metadata=d.metadata, spec=k.V1StatefulSetSpec(**on, replicas=2))
        if kind == "StatefulSet"
        else k.V1DaemonSet(metadata=d.metadata, spec=k.V1DaemonSetSpec(**on))  # no replicas
    )
    apps.read_namespaced_deployment.side_effect = ApiException(status=404)
    for p in core.list_namespaced_pod.return_value.items:
        mine = p.metadata.owner_references[0].name == "api-1"
        p.metadata.owner_references = [
            owner(kind, "api" if mine else "api-old", "u1" if mine else "u2")
        ]
    return core, apps


def of(kind: str, **more: Any) -> Any:
    return wanted(**more).model_copy(update={"kind": kind})


@pytest.mark.parametrize("kind", ["StatefulSet", "DaemonSet"])
def test_a_statefulset_or_daemonset_is_resized_on_its_own_pods(kind: str) -> None:
    core, apps = kinded(kind)
    a, held = start(core, apps, of(kind))
    assert a is None and resized(core) == [("api-1-a", body(cpu="115m", memory="96Mi"))]
    key = f"shop/{kind}/api/app"
    assert actuator.advance(core, apps, key, held, 600.0) is None  # the next: b
    done = actuator.advance(core, apps, key, held, 660.0)
    assert done is not None and (done.outcome, done.kind, done.pods) == ("applied", kind, 2)
    assert [n for n, _ in resized(core)] == ["api-1-a", "api-1-b"]  # not api-x-a, another's
    assert not apps.list_namespaced_replica_set.called


def test_an_hpa_or_a_vpa_counts_only_for_its_own_kind() -> None:
    core, apps = kinded("StatefulSet")
    deployments = {"spec": {"targetRef": {"kind": "Deployment", "name": "api"}}}
    a, held = start(core, apps, of("StatefulSet"), vpas=[deployments], hpas=[hpa()])
    assert a is None and held["requests"] == {"cpu": "115m", "memory": "96Mi"}
    own = {"spec": {"targetRef": {"kind": "StatefulSet", "name": "api"}}}
    vpa, _ = start(core, apps, of("StatefulSet"), vpas=[own])
    assert vpa.reason == "a VPA in mode Auto sizes it"
    scaler = hpa()
    scaler.spec.scale_target_ref.kind = "StatefulSet"
    core, apps = kinded("StatefulSet")
    _, held = start(core, apps, of("StatefulSet"), hpas=[scaler])
    assert held["requests"] == {"memory": "96Mi"}


@pytest.mark.parametrize("kind", ["StatefulSet", "Rollout"])  # a DaemonSet's is left as it runs
def test_a_statefulsets_or_rollouts_pod_is_never_evicted(kind: str) -> None:
    core, apps = rolled() if kind == "Rollout" else kinded(kind)
    _, held = start(core, apps, of(kind))
    infeasible(core)
    failed = actuator.advance(core, apps, f"shop/{kind}/api/app", held, 60.0, "open", PDB)
    assert failed is not None and failed.outcome == "failed"
    assert failed.reason.endswith(f"; a {kind}'s pod is never evicted")
    assert not core.create_namespaced_pod_eviction.called


def owned_by(kind: str, name: str, **resources: Any) -> dict[str, Any]:
    review = new_pod(**resources)
    meta = review["request"]["object"]["metadata"]
    meta["labels"] = {"app": name}
    meta["ownerReferences"] = [{"kind": kind, "name": name, "controller": True}]
    return review


def test_the_webhook_sizes_statefulset_pods_and_only_lowers_daemonset_pods() -> None:
    def hold(kind: str, **requests: str) -> Any:
        return {f"shop/{kind}/db/app": {**HELD["shop/Deployment/api/app"], "requests": requests}}

    cpu = "/spec/containers/1/resources/requests/cpu"
    memory = "/spec/containers/1/resources/requests/memory"
    lower = {"cpu": "115m", "memory": "64Mi"}  # cpu under the template's 1, memory unset there
    assert patched(owned_by("StatefulSet", "db"), hold("StatefulSet", **lower)) == [
        {"op": "add", "path": cpu, "value": "115m"},
        {"op": "add", "path": memory, "value": "48Mi"},  # its limit
    ]
    assert patched(owned_by("DaemonSet", "db"), hold("DaemonSet", **lower)) == [
        {"op": "add", "path": cpu, "value": "115m"}  # memory: a raise from none
    ]
    assert patched(owned_by("DaemonSet", "db"), hold("DaemonSet", cpu="2")) is None  # a raise
    assert patched(owned_by("DaemonSet", "db"), hold("DaemonSet", cpu="1")) is None  # the same
    assert patched(owned_by("StatefulSet", "db"), hold("DaemonSet", **lower)) is None
    assert patched(owned_by("StatefulSet", "db"), hold("Deployment", **lower)) is None
    held = hold("StatefulSet", **lower)
    req = owned_by("StatefulSet", "db")["request"]
    assert actuator.mutation(req, held, "x", frozenset({"shop/StatefulSet/db"})) == []
    assert actuator.mutation(req, held, "x", frozenset({"shop/Deployment/db"}))
    lone = owned_by("ReplicaSet", "db-5d8f")  # a ReplicaSet of no Deployment: no hash label
    assert patched(lone, {"shop/Deployment/db/app": HELD["shop/Deployment/api/app"]}) is None


def test_pauses_are_read_for_each_kind_it_holds() -> None:
    apps = MagicMock()
    note = {actuator.PAUSE: "true"}
    apps.list_namespaced_deployment.return_value = MagicMock(
        items=[MagicMock(metadata=k.V1ObjectMeta(name="db", annotations=note))]
    )
    apps.list_namespaced_stateful_set.return_value = MagicMock(
        items=[MagicMock(metadata=k.V1ObjectMeta(name="api", annotations=note))]
    )
    apps.list_namespaced_rollout.return_value = MagicMock(
        items=[MagicMock(metadata=k.V1ObjectMeta(name="web", annotations=note))]
    )
    a = make(hub_of([], []), MagicMock(), apps)
    keys = {"shop/StatefulSet/api/app", "shop/Deployment/api/app", "shop/Rollout/web/app"}
    a.pauses(keys)
    assert a.paused == {"shop/Deployment/db", "shop/StatefulSet/api", "shop/Rollout/web"}
    assert a.is_paused("shop/StatefulSet/api/app") and not a.is_paused("shop/Deployment/api/app")
    assert not apps.list_namespaced_daemon_set.called
    apps.list_namespaced_stateful_set.side_effect = ApiException(status=500)
    apps.list_namespaced_deployment.return_value = MagicMock(items=[])
    apps.list_namespaced_rollout.side_effect = ApiException(status=404)  # Argo uninstalled
    a.pauses(keys)  # its StatefulSets and Rollouts unreadable: they keep what it knew
    assert a.paused == {"shop/StatefulSet/api", "shop/Rollout/web"}


def test_a_statefulset_is_read_as_one_for_its_hand_back_catch_up_and_a_kind_it_skips() -> None:
    core, apps = kinded("DaemonSet")
    a, held = start(core, apps, of("DaemonSet"))
    for at in (600.0, 660.0):
        a = actuator.advance(core, apps, "shop/DaemonSet/api/app", held, at)
    assert a is not None and a.outcome == "applied"
    act = make(hub_of([], []), core, apps, held={"shop/DaemonSet/api/app": held})
    late = pod("api-1-c", "api-1")  # a new node's pod, from its template
    late.metadata.namespace = "shop"
    late.metadata.owner_references = [owner("DaemonSet", "api", "u1")]
    core.list_namespaced_pod.return_value.items.append(late)
    act.catch_up()
    assert resized(core)[-1] == ("api-1-c", body(cpu="115m", memory="96Mi"))  # in place
    assert act.changed("shop/DaemonSet/api/app", held) is None
    apps.read_namespaced_daemon_set.side_effect = ApiException(status=404)
    assert act.changed("shop/DaemonSet/api/app", held) == "no such DaemonSet"
    gone, _ = start(core, apps, of("DaemonSet"))
    assert (gone.outcome, gone.reason) == ("skipped", "no such DaemonSet")
    apps.read_namespaced_daemon_set.side_effect = ApiException(status=500, reason="boom")
    broken, _ = start(core, apps, of("DaemonSet"))
    assert (broken.outcome, broken.reason) == ("failed", "reading the DaemonSet: 500: boom")
    cronjob, _ = start(core, apps, of("CronJob"))
    assert (cronjob.outcome, cronjob.reason) == ("skipped", "a CronJob is not resized")


def stuck(core: Any, *names: str, reason: str = "Infeasible") -> None:
    """These pods' resizes held back by the kubelet: allocated as they started."""
    normal = core.read_namespaced_pod.side_effect

    def read(name: str, ns: str) -> Any:
        p = normal(name, ns)
        if name in names:
            p.status.conditions = [
                k.V1PodCondition(type="PodResizePending", status="True", reason=reason,
                                 message="Node didn't have enough")
            ]  # fmt: skip
            was = k.V1ResourceRequirements(requests={"cpu": "1", "memory": "512Mi"})
            p.status.container_statuses = [status("app", was)]
        return p

    core.read_namespaced_pod.side_effect = read


DS = "shop/DaemonSet/api/app"
NONE = "left without its raise: its node has no room"
FULL = body(cpu="4000m", memory="96Mi")  # a raise of cpu (from 1), memory lowered (512Mi)
TEMPLATE = {"cpu": "1", "memory": "512Mi"}


def raised() -> Any:
    return of("DaemonSet", cpu=4.0)


def test_a_daemonsets_pod_its_node_has_no_room_for_is_left_and_the_canary_moves_on() -> None:
    core, apps = kinded("DaemonSet")
    _, held = start(core, apps, raised())  # the canary: api-1-a
    stuck(core, "api-1-a")
    assert actuator.advance(core, apps, DS, held, 60.0, "open", PDB) is None  # never evicted
    assert not core.create_namespaced_pod_eviction.called
    assert held["left"] == ["api-1-a"] and "api-1-a" not in held["pods"]
    assert (held["pod"], held["resized"], held["canary_until"]) == ("api-1-b", 1, 660.0)
    assert resized(core) == [
        ("api-1-a", FULL),
        ("api-1-a", body(cpu="1", memory="96Mi")),  # its raise undone, its lowering kept
        ("api-1-b", FULL),  # the canary now
    ]
    event = core.create_namespaced_event.call_args.args[1]
    assert (event.reason, event.type) == ("PodLeft", "Normal")
    assert event.message == (
        f"api-1-a {NONE} for cpu 4000m, memory 96Mi (Node didn't have enough); "
        "lowered in place to memory 96Mi"
    )
    assert actuator.advance(core, apps, DS, held, 659.0) is None  # its 10 minutes
    done = actuator.advance(core, apps, DS, held, 660.0)
    assert done is not None and (done.outcome, done.pods) == ("applied", 1)
    assert done.reason == f"1 of 2 pods resized in place, one at a time; api-1-a {NONE}"
    assert held["left"] == ["api-1-a"]  # kept: never caught up


def test_a_daemonset_whose_nodes_all_lack_room_fails_and_deferred_or_refused_pods_are_left(
) -> None:  # fmt: skip
    core, apps = kinded("DaemonSet")
    _, held = start(core, apps, raised())
    stuck(core, "api-1-a", "api-1-b")
    assert actuator.advance(core, apps, DS, held, 60.0) is None  # a left, b resized
    failed = actuator.advance(core, apps, DS, held, 120.0)
    assert failed is not None and (failed.outcome, failed.pods) == ("failed", 0)
    assert failed.reason == (
        f"no node of its 2 pods has room for them; api-1-a {NONE}; api-1-b {NONE}"
    )
    core, apps = kinded("DaemonSet")
    _, held = start(core, apps, raised())
    stuck(core, "api-1-a", reason="Deferred")  # full now: 10 minutes, then left
    assert actuator.advance(core, apps, DS, held, 599.0) is None and "left" not in held
    assert actuator.advance(core, apps, DS, held, 600.0) is None and held["left"] == ["api-1-a"]
    core, apps = kinded("DaemonSet")
    patch = core.patch_namespaced_pod_resize.side_effect
    core.patch_namespaced_pod_resize.side_effect = refusal(403, ROOMLESS)  # Kubernetes 1.35+
    a, held = start(core, apps, raised())  # eviction off: left all the same
    core.patch_namespaced_pod_resize.side_effect = patch  # b's node has room
    assert actuator.advance(core, apps, DS, held, 60.0) is None
    assert held["left"] == ["api-1-a"] and "no_room" not in held  # b's resize is its own
    assert resized(core) == [
        ("api-1-a", FULL),  # refused: nothing pending to undo
        ("api-1-a", body(memory="96Mi")),  # its lowering alone, which fits
        ("api-1-b", FULL),
    ]
    done = actuator.advance(core, apps, DS, held, 660.0)
    assert done is not None and (done.outcome, done.pods) == ("applied", 1)
    core, apps = kinded("DaemonSet")
    core.patch_namespaced_pod_resize.side_effect = refusal(403, ROOMLESS)
    a, held = start(core, apps, raised())
    assert a is None and "enough allocatable" in held["no_room"]
    assert actuator.advance(core, apps, DS, held, 60.0) is None  # a left, b refused too
    assert held["left"] == ["api-1-a"] and (held["pod"], held["resized"]) == ("api-1-b", 1)
    assert "enough allocatable" in held["no_room"]
    refused = actuator.advance(core, apps, DS, held, 120.0)
    assert refused is not None and refused.outcome == "failed" and "no_room" not in held


def test_a_new_nodes_pod_with_no_room_is_left_and_the_daemonset_keeps_its_requests() -> None:
    core, apps = kinded("DaemonSet", requests=TEMPLATE)
    _, held = start(core, apps, raised())
    for at in (600.0, 660.0):
        actuator.advance(core, apps, DS, held, at)
    act = make(hub_of([], []), core, apps, held={DS: held})
    late = pod("api-1-c", "api-1")  # a new node's pod, from its template
    late.metadata.namespace = "shop"
    late.metadata.owner_references = [owner("DaemonSet", "api", "u1")]
    core.list_namespaced_pod.return_value.items.append(late)
    act.catch_up()
    assert resized(core)[-1] == ("api-1-c", FULL)
    stuck(core, "api-1-c")
    (done,) = act.advance("off")
    assert (done.outcome, done.pods) == ("applied", 0)
    assert done.reason == f"0 of 3 pods resized in place, one at a time; api-1-c {NONE}"
    assert act.held[DS]["outcome"] == "applied" and act.held[DS]["left"] == ["api-1-c"]
    assert resized(core)[-1] == ("api-1-c", body(cpu="1", memory="96Mi"))
    new = owned_by("DaemonSet", "api", requests=TEMPLATE)["request"]
    assert actuator.mutation(new, act.held, "x") == [  # still held: new pods lowered
        {"op": "add", "path": "/spec/containers/1/resources/requests/memory", "value": "96Mi"}
    ]
    count = len(resized(core))
    assert act.catch_up() == [] and len(resized(core)) == count  # api-1-c not tried again
    later = pod("api-1-d", "api-1")  # another new node's: caught up, api-1-c still left
    later.metadata.namespace = "shop"
    later.metadata.owner_references = [owner("DaemonSet", "api", "u1")]
    core.list_namespaced_pod.return_value.items.append(later)
    act.catch_up()
    assert [n for n, _ in resized(core)[count:]] == ["api-1-d"]
    assert act.held[DS]["left"] == ["api-1-c"] and act.held[DS]["pod"] == "api-1-d"


# --- Argo Rollouts (slice 12.8b) -----------------------------------------------------------


def rolled(**kw: Any) -> tuple[Any, Any]:
    """cluster(), api an Argo Rollout (uid u1) owning ReplicaSet api-1; api-x another's."""
    core, apps = cluster(**kw)
    apps.read_namespaced_rollout.return_value = apps.read_namespaced_deployment.return_value
    apps.read_namespaced_deployment.side_effect = ApiException(status=404)
    for rs in apps.list_namespaced_replica_set.return_value.items:
        rs.metadata.owner_references[0].kind = "Rollout"
    return core, apps


def test_an_argo_rollout_is_resized_on_its_own_replicasets_pods() -> None:
    core, apps = rolled()
    a, held = start(core, apps, of("Rollout"))
    assert a is None and resized(core) == [("api-1-a", body(cpu="115m", memory="96Mi"))]
    key = "shop/Rollout/api/app"
    assert actuator.advance(core, apps, key, held, 600.0) is None  # the next: b
    done = actuator.advance(core, apps, key, held, 660.0)
    assert done is not None and (done.outcome, done.kind, done.pods) == ("applied", "Rollout", 2)
    assert [n for n, _ in resized(core)] == ["api-1-a", "api-1-b"]  # not api-x-a, another's
    actuator.event(core, done)
    on = core.create_namespaced_event.call_args.args[1].involved_object
    assert (on.api_version, on.kind, on.name) == ("argoproj.io/v1alpha1", "Rollout", "api")
    gone, _ = start(*rolled(), of("Deployment"))  # a Deployment of its name: none
    assert (gone.outcome, gone.reason) == ("skipped", "no such Deployment")


def test_the_webhook_tells_an_argo_rollouts_pod_by_its_hash_label() -> None:
    review = new_pod()
    labels = review["request"]["object"]["metadata"]["labels"]
    del labels["pod-template-hash"]
    labels["rollouts-pod-template-hash"] = "5d8f"
    held = {"shop/Rollout/api/app": HELD["shop/Deployment/api/app"]}
    assert patched(review, held) == patched(new_pod()) is not None  # as a Deployment's
    assert patched(review) is None  # a Deployment of its name holds nothing for it
    assert patched(new_pod(), held) is None  # nor it for a Deployment's pod
    labels["rollouts-pod-template-hash"] = "9999"  # not its ReplicaSet's hash
    assert patched(review, held) is None
    db = owned_by("StatefulSet", "db")  # a StatefulSet's pod, whatever its labels say
    db["request"]["object"]["metadata"]["labels"]["rollouts-pod-template-hash"] = "5d8f"
    assert patched(db, {"shop/StatefulSet/db/app": HELD["shop/Deployment/api/app"]})


def test_a_rollout_is_read_as_a_deployment_its_template_its_own_or_its_workload_refs() -> None:
    custom, apps = MagicMock(), MagicMock()
    template = {"metadata": {"labels": {"app": "web"}}, "spec": {"containers": [
        {"name": "app", "image": "x", "resources": {"requests": {"cpu": "100m"}},
         "resizePolicy": [{"resourceName": "cpu", "restartPolicy": "NotRequired"}]}]}}  # fmt: skip
    meta = {
        "name": "web",
        "namespace": "shop",
        "uid": "u9",
        "annotations": {actuator.PAUSE: "true"},
    }
    own = {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Rollout",
        "metadata": meta,
        "spec": {
            "replicas": 3,
            "selector": {"matchLabels": {"app": "web"}},
            "strategy": {"canary": {"steps": [{"setWeight": 20}]}},  # not a Deployment's
            "template": template,
        },
        "status": {"phase": "Healthy", "conditions": [{"type": "Progressing", "status": "True"}]},
    }
    custom.get_namespaced_custom_object.return_value = own
    d = actuator.Apps(apps, custom).read_namespaced_rollout("web", "shop")
    assert custom.get_namespaced_custom_object.call_args.args == (
        "argoproj.io",
        "v1alpha1",
        "shop",
        "rollouts",
        "web",
    )
    c = d.spec.template.spec.containers[0]
    assert (d.metadata.uid, d.spec.replicas, d.spec.selector.match_labels) == (
        "u9",
        3,
        {"app": "web"},
    )
    assert (c.resources.requests, c.resize_policy[0].restart_policy) == (
        {"cpu": "100m"},
        "NotRequired",
    )
    base = k.V1Deployment(
        spec=k.V1DeploymentSpec(
            selector=k.V1LabelSelector(match_labels={"app": "base"}),
            template=k.V1PodTemplateSpec(spec=k.V1PodSpec(containers=[container({"cpu": "7m"})])),
        )
    )
    apps.read_namespaced_deployment.return_value = base
    ref = {"apiVersion": "apps/v1", "kind": "Deployment", "name": "web-base"}
    reffed = {"metadata": meta, "spec": {"replicas": 2, "workloadRef": ref}}
    custom.get_namespaced_custom_object.return_value = reffed
    d = actuator.Apps(apps, custom).read_namespaced_rollout("web", "shop")
    assert apps.read_namespaced_deployment.call_args.args == ("web-base", "shop")
    assert d.spec.template.spec.containers[0].resources.requests == {"cpu": "7m"}
    assert d.spec.selector.match_labels == {"app": "base"}
    reffed["spec"]["selector"] = {"matchLabels": {"app": "web"}}  # as Argo's examples give it
    d = actuator.Apps(apps, custom).read_namespaced_rollout("web", "shop")
    assert d.spec.selector.match_labels == {"app": "web"}  # its own, not the Deployment's
    assert (
        actuator.Apps(apps, custom).list_namespaced_replica_set is apps.list_namespaced_replica_set
    )


def test_a_rollout_it_cant_read_as_a_deployment_fails_and_never_hides_anothers_pause() -> None:
    custom, apps = MagicMock(), MagicMock()
    meta = {"name": "web", "namespace": "shop", "uid": "u9"}
    other = {"apiVersion": "v1", "kind": "PodTemplate", "name": "web-template"}
    custom.get_namespaced_custom_object.return_value = {
        "metadata": meta,
        "spec": {"selector": {"matchLabels": {"app": "web"}}, "workloadRef": other},
    }
    core, _ = cluster()
    a, _ = start(core, actuator.Apps(apps, custom), of("Rollout"))
    assert a.outcome == "failed"
    assert a.reason.startswith("reading the Rollout: 422: not read as a Deployment")
    paused = {"name": "db", "namespace": "shop", "annotations": {actuator.PAUSE: "true"}}
    custom.list_namespaced_custom_object.return_value = {
        "items": [custom.get_namespaced_custom_object.return_value, {"metadata": paused}]
    }
    act = make(hub_of([], []), core, actuator.Apps(apps, custom))
    act.pauses({"shop/Rollout/web/app", "shop/Rollout/db/app"})
    assert act.paused == {"shop/Rollout/db"} and not apps.read_namespaced_deployment.called
