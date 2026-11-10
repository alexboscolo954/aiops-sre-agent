"""The Actuator (slice 12.1): the Hub's two routes for it, bound by its token to one
Contract's cluster, and the Actuator resizing a Deployment's pods in place."""

import asyncio
import json
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
        later = report(outcome="skipped", at=160.0, pods=0)
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
    assert rows == [("acme", "test", "applied", 2, 100.0), ("bank", "test", "skipped", 0, 160.0)]


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


def cluster(limits: dict[str, str] | None = None, policy: Any = None) -> tuple[Any, Any]:
    """api (uid u1) with ReplicaSet api-1; another Deployment's api-x shares its labels."""
    core, apps = MagicMock(), MagicMock()
    apps.read_namespaced_deployment.return_value = k.V1Deployment(
        metadata=k.V1ObjectMeta(name="api", namespace="shop", uid="u1"),
        spec=k.V1DeploymentSpec(
            selector=k.V1LabelSelector(match_labels={"app": "api"}),
            template=k.V1PodTemplateSpec(
                spec=k.V1PodSpec(containers=[container({"cpu": "1"}, limits, policy)])
            ),
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
    core.list_namespaced_pod.return_value = k.V1PodList(
        items=[
            pod("api-1-a", "api-1"),
            pod("api-1-b", "api-1"),
            pod("api-1-done", "api-1", phase="Succeeded"),
            pod("api-1-gone", "api-1", deleting=True),
            pod("api-x-a", "api-x"),
        ]
    )
    return core, apps


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


def test_only_its_deployments_live_pods_are_resized_and_never_above_the_limit() -> None:
    core, apps = cluster(limits={"memory": "64Mi"})
    a, held = actuator.apply(core, apps, wanted(), at=5.0)
    assert resized(core) == [
        ("api-1-a", body(cpu="115m", memory="64Mi")),
        ("api-1-b", body(cpu="115m", memory="64Mi")),
    ]
    assert (a.outcome, a.pods, a.cpu, a.memory) == ("applied", 2, 0.115, 64.0 * MI)
    assert a.reason == "2 of 2 pods resized in place; capped at its limit: ['memory']"
    assert held == {
        "run_id": 1,
        "outcome": "applied",
        "requests": {"cpu": "115m", "memory": "64Mi"},
        "at": 5.0,
    }
    labels = apps.list_namespaced_replica_set.call_args.kwargs["label_selector"]
    assert labels == "app=api" == core.list_namespaced_pod.call_args.kwargs["label_selector"]


def test_a_request_left_as_it_is_and_pods_that_already_match_are_not_touched() -> None:
    core, apps = cluster(limits={"cpu": "2"})
    core.list_namespaced_pod.return_value.items[1] = pod("api-1-b", "api-1", cpu="115m")
    a, _ = actuator.apply(core, apps, wanted(memory=None), at=5.0)
    assert resized(core) == [("api-1-a", body(cpu="115m"))]  # memory untouched, b already 115m
    assert (a.outcome, a.pods, a.memory) == ("applied", 1, None)
    core.list_namespaced_pod.return_value.items[0] = pod("api-1-a", "api-1", cpu="0.115")
    again, _ = actuator.apply(core, apps, wanted(memory=None), at=6.0)
    assert (again.outcome, again.reason) == ("skipped", "all 2 pods already have these requests")


def refusal(status: int = 422, message: str = "Pod QoS Class may not change") -> ApiException:
    e = ApiException(status=status, reason="Unprocessable Entity")
    e.body = json.dumps({"message": message})
    return e


def test_a_refused_resize_is_reported_and_one_refusal_does_not_stop_the_rest() -> None:
    core, apps = cluster()
    core.patch_namespaced_pod_resize.side_effect = [refusal(), None]
    partly, _ = actuator.apply(core, apps, wanted(), at=5.0)
    assert partly.outcome == "applied" and partly.pods == 1
    assert partly.reason.endswith("1 refused, first api-1-a: 422: Pod QoS Class may not change")
    core.patch_namespaced_pod_resize.side_effect = refusal()
    failed, held = actuator.apply(core, apps, wanted(), at=6.0)
    assert (failed.outcome, failed.pods, held["outcome"]) == ("failed", 0, "failed")
    assert failed.reason.startswith("no pod resized; 2 refused")
    actuator.event(core, failed)
    shown = core.create_namespaced_event.call_args.args[1]
    assert (shown.reason, shown.type) == ("SizingFailed", "Warning")


def test_a_resize_that_would_restart_the_container_or_has_nothing_to_resize_is_skipped() -> None:
    policy = [k.V1ContainerResizePolicy(resource_name="memory", restart_policy="RestartContainer")]
    core, apps = cluster(policy=policy)
    restarts, _ = actuator.apply(core, apps, wanted(), at=5.0)
    cpu_only, _ = actuator.apply(core, apps, wanted(memory=None), at=5.0)
    assert restarts.reason == "its resizePolicy restarts the container for ['memory']"
    assert cpu_only.outcome == "applied"  # a cpu resize doesn't restart it
    gone = MagicMock()
    gone.read_namespaced_deployment.side_effect = ApiException(status=404)
    missing, _ = actuator.apply(MagicMock(), gone, wanted(), at=5.0)
    core, apps = cluster()
    apps.read_namespaced_deployment.return_value.spec.template.spec.containers[0].name = "web"
    renamed, _ = actuator.apply(core, apps, wanted(), at=5.0)
    core, apps = cluster()
    core.list_namespaced_pod.return_value.items = []
    idle, _ = actuator.apply(core, apps, wanted(), at=5.0)
    apps.list_namespaced_replica_set.side_effect = refusal(403, "forbidden")
    forbidden, _ = actuator.apply(core, apps, wanted(), at=5.0)
    assert [(x.outcome, x.reason) for x in (missing, renamed, idle, forbidden)] == [
        ("skipped", "no such Deployment"),
        ("skipped", "no container 'app' in its template"),
        ("skipped", "no live pods"),
        ("failed", "listing its pods: 403: forbidden"),
    ]
    assert restarts.outcome == "skipped" and not resized(core)


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


def test_each_approved_sizing_is_applied_once_and_reported_until_the_hub_has_it(
    caplog: Any,
) -> None:
    core, apps = cluster()
    seen: list[httpx.Request] = []
    http = hub_of(
        [desired(1), desired(1), httpx.Response(503), desired(1, 2), desired(2, 3, killed=True)],
        seen,
    )
    http.reports.append(httpx.Response(502))  # type: ignore[attr-defined]  # the first report
    a = actuator.Actuator(http, core, apps, "aiops-actuator")
    a.step()  # applies run 1; its report fails and is kept
    assert len(resized(core)) == 2 and len(a.unsent) == 1
    a.step()  # run 1 again: nothing to do; the kept report goes
    a.step()  # the Hub is down: nothing changes, nothing breaks
    a.step()  # run 2 is newer: applied
    core.patch_namespaced_pod_resize.reset_mock()
    a.step()  # the Kill switch: nothing applied, whatever the Hub lists
    assert not resized(core) and a.killed
    posted = [json.loads(r.content) for r in seen if r.method == "POST"]
    assert [[x["run_id"] for x in p] for p in posted] == [[1], [1], [2]]
    assert all(r.headers["authorization"] == f"Bearer {A_TOKEN}" for r in seen)
    held = json.loads(core.replace_namespaced_config_map.call_args.args[2].data[actuator.KEY])
    assert held["shop/Deployment/api/app"]["run_id"] == 2
    events = [c.args[1] for c in core.create_namespaced_event.call_args_list]
    assert [(e.reason, e.type, e.involved_object.name) for e in events] == [
        ("SizingApplied", "Normal", "api")
    ] * 2
    assert events[0].message.startswith("app: cpu 115m, memory 96Mi (Approved Sizing, run 1)")
    assert "the Hub answered 503" in caplog.text and A_TOKEN not in caplog.text


def test_reports_the_hub_refuses_are_dropped_and_the_next_ones_go(caplog: Any) -> None:
    core, apps = cluster()
    seen: list[httpx.Request] = []
    http = hub_of([desired(1), desired(1, 2), desired(1, 2)], seen)
    http.reports += [httpx.Response(422), httpx.Response(401)]  # type: ignore[attr-defined]
    a = actuator.Actuator(http, core, apps, "aiops-actuator")
    a.step()
    assert a.unsent == [] and "the Hub refused 1 reports (422): dropped" in caplog.text
    a.step()  # a refused token may be the Hub mid-update: run 2's report is kept
    assert [x.run_id for x in a.unsent] == [2]
    a.step()
    posted = [json.loads(r.content) for r in seen if r.method == "POST"]
    assert [[x["run_id"] for x in p] for p in posted] == [[1], [2], [2]]


def test_what_it_applied_survives_a_restart() -> None:
    core, apps = cluster()
    held = {"shop/Deployment/api/app": {"run_id": 1, "outcome": "applied"}}
    core.read_namespaced_config_map.return_value = k.V1ConfigMap(
        data={actuator.KEY: json.dumps(held)}
    )
    a = actuator.Actuator(hub_of([desired(1)], []), core, apps, "aiops-actuator")
    a.load()
    a.step()
    assert a.held == held and not resized(core)
    fresh = MagicMock()
    fresh.read_namespaced_config_map.side_effect = ApiException(status=404)
    fresh.replace_namespaced_config_map.side_effect = ApiException(status=404)
    b = actuator.Actuator(hub_of([desired(1)], []), fresh, apps, "aiops-actuator")
    b.load()
    assert b.held == {}
    fresh.list_namespaced_pod = core.list_namespaced_pod
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
    }
    assert "secrets" not in str(rules)
    (deploy,) = yaml.safe_load_all((ROOT / "deploy/actuator/deployment.yaml").read_text())
    (c,) = deploy["spec"]["template"]["spec"]["containers"]
    hub_image = next(yaml.safe_load_all((ROOT / "deploy/base/deployment.yaml").read_text()))
    assert c["image"] == hub_image["spec"]["template"]["spec"]["containers"][0]["image"]
    assert c["args"] == ["actuator"] and c["securityContext"]["readOnlyRootFilesystem"] is True
