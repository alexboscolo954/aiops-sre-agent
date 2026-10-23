"""Sizing policies (slice 9.3): built-ins, your own on a base, the rules that pick one,
validation, and `aiops sizing show` under them."""

import json
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from aiops_agent import cli, contracts, sizing, usage
from aiops_agent.contracts import BUILTIN, Policy, SizingConfig
from aiops_agent.sizing import Risk
from aiops_agent.usage import ContainerUsage, Workload
from tests.conftest import make_contract
from tests.fake_prometheus import FakePrometheus
from tests.test_usage import _prom, cpu, deployment, mem, owner

H = 3600
DAY = 24 * H
MI = 2**20
NOW = 30 * DAY


def config(**data: Any) -> SizingConfig:
    return SizingConfig.model_validate(data)


def custom(**changes: Any) -> Policy:
    return config(policies={"mine": {"base": "production", **changes}}).policies["mine"]


# --- built-ins -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "window", "half_life", "history", "pct", "cpu_head", "mem_head", "floors"),
    [
        ("production", 7 * DAY, 24 * H, 24 * H, 0.95, 0.15, 0.20, (0.010, 32 * MI)),
        ("high-availability", 14 * DAY, 72 * H, 72 * H, 0.99, 0.30, 0.35, (0.050, 64 * MI)),
        ("batch", 14 * DAY, 24 * H, 24 * H, 0.90, 0.10, 0.15, (0.010, 32 * MI)),
    ],
)
def test_the_built_in_policies(
    name: str,
    window: int,
    half_life: int,
    history: int,
    pct: float,
    cpu_head: float,
    mem_head: float,
    floors: tuple[float, float],
) -> None:
    p = BUILTIN[name]
    assert (p.window, p.half_life, p.history, p.threshold) == (window, half_life, history, 0.10)
    assert (p.cpu.percentile, p.cpu.headroom, p.memory.headroom) == (pct, cpu_head, mem_head)
    assert (p.cpu.floor, p.memory.floor) == floors
    assert p.cpu.max is None and p.memory.max is None and p.limits == "keep"


# --- your own policies ---------------------------------------------------------------


def test_a_policy_is_its_base_with_the_named_settings_replaced() -> None:
    p = config(
        policies={
            "lean": {
                "base": "high-availability",
                "window": "3d",
                "cpu": {"headroom": 0.1, "max": "2"},
                "memory": {"floor": "128Mi", "max": "4Gi"},
            }
        }
    ).policies["lean"]
    ha = BUILTIN["high-availability"]
    assert p.window == 3 * DAY and p.half_life == ha.half_life and p.history == ha.history
    assert (p.cpu.headroom, p.cpu.max, p.cpu.percentile) == (0.1, 2.0, ha.cpu.percentile)
    assert (p.memory.floor, p.memory.max, p.memory.headroom) == (128 * MI, 4 * 2**30, 0.35)


def test_quantities_and_durations_take_kubernetes_and_short_forms() -> None:
    p = custom(cpu={"floor": "500m"}, memory={"floor": "1.5Gi"}, half_life="90m")
    assert (p.cpu.floor, p.memory.floor, p.half_life) == (0.5, 1.5 * 2**30, 5400)


@pytest.mark.parametrize("base", [None, "mine", "Production", "off"])
def test_the_base_must_be_a_built_in(base: str | None) -> None:
    other = {"mine": {"base": "production"}}
    with pytest.raises(ValidationError, match="base must be one of"):
        config(policies={**other, "yours": {"base": base}})


@pytest.mark.parametrize("name", ["production", "batch", "high-availability", "off"])
def test_built_in_names_and_off_are_taken(name: str) -> None:
    with pytest.raises(ValidationError, match="taken by the built-ins"):
        config(policies={name: {"base": "production"}})


@pytest.mark.parametrize(
    "data",
    [
        {"default": "lean"},
        {"rules": [{"namespace": "web", "policy": "lean"}]},
    ],
)
def test_an_unknown_policy_is_refused(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="unknown policy 'lean'"):
        config(**data)


def test_a_rule_must_match_on_something() -> None:
    with pytest.raises(ValidationError, match="a rule needs"):
        config(rules=[{"policy": "batch"}])


def test_a_rule_names_a_cluster_of_the_contract() -> None:
    data = make_contract().model_dump()
    data["sizing"] = {"rules": [{"cluster": "prod", "policy": "batch"}]}
    with pytest.raises(ValidationError, match="sizing rule 1: no cluster 'prod'"):
        contracts.build(data)
    data["sizing"]["rules"][0]["cluster"] = "test"
    assert contracts.build(data).sizing.rules[0].cluster == "test"


def test_off_written_bare_in_yaml_means_off() -> None:
    data = yaml.safe_load("default: off\nrules: [{namespace: web, policy: off}]")
    c = config(**data)
    assert c.default == "off" and c.rules[0].policy == "off"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"cpu": {"percentile": 0.49}}, "greater than or equal to 0.5"),
        ({"cpu": {"percentile": 1.01}}, "less than or equal to 1"),
        ({"cpu": {"headroom": -0.01}}, "greater than or equal to 0"),
        ({"memory": {"headroom": 3.01}}, "less than or equal to 3"),
        ({"window": "59m"}, "from 1h to 90d"),
        ({"window": "91d"}, "from 1h to 90d"),
        ({"half_life": "59m"}, "from 1h to 30d"),
        ({"half_life": "31d"}, "from 1h to 30d"),
        ({"history": "59m"}, "from 1h to 90d"),
        ({"history": "8d"}, "history must fit in the window"),
        ({"threshold": 0.51}, "less than or equal to 0.5"),
        ({"threshold": -0.01}, "greater than or equal to 0"),
        ({"cpu": {"floor": 0}}, "greater than 0"),
        ({"memory": {"max": "0"}}, "greater than 0"),
        ({"cpu": {"floor": "2", "max": "1"}}, "cpu floor is above its max"),
        ({"memory": {"max": "16Mi"}}, "memory floor is above its max"),
        ({"memory": {"floor": "lots"}}, "not a Kubernetes quantity"),
        ({"window": "1w"}, "use a number and m, h or d"),
        ({"limits": "remove"}, "keep"),
        ({"cpu": {"basis": "peak"}}, "Extra inputs"),
        ({"throttled": 0.5}, "Extra inputs"),
    ],
)
def test_validation_refuses(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        custom(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"cpu": {"percentile": 0.5}},
        {"cpu": {"percentile": 1.0}},
        {"cpu": {"headroom": 0}, "memory": {"headroom": 3}},
        {"window": "1h", "history": "1h", "half_life": "1h"},
        {"window": "90d", "history": "90d", "half_life": "30d"},
        {"threshold": 0},
        {"threshold": 0.5},
        {"cpu": {"floor": "1", "max": "1"}},
    ],
)
def test_validation_accepts_the_edges(changes: dict[str, Any]) -> None:
    custom(**changes)


# --- rules ---------------------------------------------------------------------------


def pick(c: SizingConfig, kind: str = "Deployment", name: str = "checkout", **at: str) -> str:
    where = {"cluster": "eu", "namespace": "web", "container": "app", **at}
    return c.policy_for(where["cluster"], where["namespace"], kind, name, where["container"])


def test_rules_run_top_to_bottom_and_the_first_match_wins() -> None:
    c = config(
        rules=[
            {"namespace": "web", "name": "checkout", "policy": "high-availability"},
            {"namespace": "web", "policy": "off"},
        ]
    )
    assert pick(c) == "high-availability"
    assert pick(c, name="cart") == "off"
    assert pick(c, namespace="api") == "production"


def test_every_field_a_rule_sets_must_match() -> None:
    rule = {
        "cluster": "eu",
        "namespace": "web",
        "kind": "Deployment",
        "name": "checkout",
        "container": "app",
        "policy": "high-availability",
    }
    c = config(rules=[rule])
    assert pick(c) == "high-availability"
    for field, other in [
        ("cluster", "us"),
        ("namespace", "api"),
        ("kind", "StatefulSet"),
        ("name", "cart"),
        ("container", "sidecar"),
    ]:
        if field == "kind":
            assert pick(c, kind=other) == "production", field
        elif field == "name":
            assert pick(c, name=other) == "production", field
        else:
            assert pick(c, **{field: other}) == "production", field


def test_namespace_and_name_take_globs_the_others_do_not() -> None:
    c = config(
        rules=[
            {"namespace": "team-*", "name": "checkout-?", "policy": "high-availability"},
            {"kind": "Cron*", "policy": "off"},
            {"container": "istio-*", "policy": "off"},
        ]
    )
    assert pick(c, namespace="team-a", name="checkout-1") == "high-availability"
    assert pick(c, namespace="team-a", name="checkout-12") == "production"
    assert pick(c, namespace="TEAM-a", name="checkout-1") == "production"  # case counts
    assert pick(c, kind="CronJob") == "batch"
    assert pick(c, container="istio-proxy") == "production"


def test_jobs_and_cronjobs_get_batch_unless_a_rule_says_otherwise() -> None:
    c = config(default="high-availability", rules=[{"name": "nightly", "policy": "production"}])
    assert pick(c, kind="CronJob") == "batch"
    assert pick(c, kind="Job") == "batch"
    assert pick(c, kind="CronJob", name="nightly") == "production"
    assert pick(c, kind="StatefulSet") == "high-availability"


def test_a_container_rule_sizes_a_sidecar_apart() -> None:
    c = config(rules=[{"container": "istio-proxy", "policy": "off"}])
    assert pick(c, container="istio-proxy") == "off"
    assert pick(c) == "production"


def test_windows_are_the_ones_a_container_can_get() -> None:
    assert config().windows() == [7 * DAY, 14 * DAY]  # production and batch
    lean = {
        "lean": {"base": "production", "window": "3d"},
        "spare": {"base": "batch", "window": "30d"},
    }
    c = config(
        default="off",
        policies=lean,
        rules=[{"namespace": "web", "policy": "lean"}, {"namespace": "x", "policy": "off"}],
    )
    assert c.windows() == [3 * DAY, 14 * DAY]  # spare is named by no rule


def test_a_contract_without_sizing_gets_production_and_batch() -> None:
    c = make_contract().sizing
    assert c.default == "production" and c.rules == [] and c.policies == {}


# --- the Sizing under a policy ---------------------------------------------------------


def use(
    cpu_values: list[float] | None = None,
    memory: list[float] | None = None,
    hours: float = 48,
    requests: dict[str, float] | None = None,
    limits: dict[str, float] | None = None,
) -> ContainerUsage:
    u = ContainerUsage(Workload("shop", "Deployment", "web"), "app")
    n = max(len(cpu_values or []), len(memory or []), 2)
    times = [NOW - hours * H + i * hours * H / (n - 1) for i in range(n)]
    u.cpu = list(zip(times, cpu_values or [], strict=False))
    u.memory = list(zip(times, memory or [], strict=False))
    u.requests = requests if requests is not None else {"cpu": 4.0, "memory": 8 * 2**30}
    u.limits = limits or {}
    return u


def test_the_percentile_and_headroom_come_from_the_policy() -> None:
    spiky = [1.0] * 3 + [0.1] * 97  # 3% of the time at a full core, the oldest
    s = sizing.size(use(spiky), NOW, BUILTIN["production"])
    assert s.cpu and s.cpu.target == 0.115  # p95 is 0.1
    s = sizing.size(use(spiky, hours=96), NOW, BUILTIN["high-availability"])
    assert s.cpu and s.cpu.target == 1.3  # p99 is 1.0, +30%


def test_the_half_life_comes_from_the_policy() -> None:
    u = ContainerUsage(Workload("shop", "Deployment", "web"), "app")
    u.cpu = [(NOW - 5 * DAY, 1.0)] * 50 + [(NOW - H, 0.1)] * 50
    u.requests = {"cpu": 4.0}
    assert (s := sizing.size(u, NOW, custom(half_life="24h"))).cpu and s.cpu.basis == 0.1
    assert (s := sizing.size(u, NOW, custom(half_life="30d"))).cpu and s.cpu.basis == 1.0


def test_the_history_needed_comes_from_the_policy() -> None:
    u = use([0.1, 0.1], hours=48)
    assert sizing.size(u, NOW, BUILTIN["production"]).state == "ready"
    assert sizing.size(u, NOW, BUILTIN["high-availability"]).state == "learning"
    assert sizing.size(u, NOW, custom(history="49h")).state == "learning"


def test_the_change_threshold_comes_from_the_policy() -> None:
    u = use([0.87, 0.87], requests={"cpu": 1.1})  # 0.87 + 15% = 1.0005 -> 1001m, 9% off
    assert (s := sizing.size(u, NOW)).cpu and s.cpu.action == "keep"
    assert (s := sizing.size(u, NOW, custom(threshold=0.05))).cpu and s.cpu.action == "lower"


def test_the_floors_come_from_the_policy() -> None:
    s = sizing.size(use([0.001] * 2, [MI] * 2, hours=96), NOW, BUILTIN["high-availability"])
    assert s.cpu and s.cpu.target == 0.050
    assert s.memory and s.memory.target == 64 * MI


def test_memory_headroom_comes_from_the_policy() -> None:
    s = sizing.size(use(memory=[100 * MI] * 2), NOW, BUILTIN["batch"])
    assert s.memory and s.memory.target == 115 * MI


def test_the_max_caps_the_sizing_and_says_so() -> None:
    p = custom(cpu={"max": "2"}, memory={"max": "1Gi"})
    s = sizing.size(use([3.0] * 2, [2 * 2**30] * 2), NOW, p)
    assert s.cpu and s.cpu.target == 2.0 and s.cpu.action == "lower"
    assert s.memory and s.memory.target == 2**30
    assert Risk("capped_by_policy", "cpu capped at 2000m by the policy: it needs 3450m") in s.risks
    assert (
        Risk("capped_by_policy", "memory capped at 1024Mi by the policy: it needs 2458Mi")
        in s.risks
    )


def test_under_the_max_nothing_is_capped() -> None:
    s = sizing.size(use([1.0] * 2), NOW, custom(cpu={"max": "2"}))
    assert s.cpu and s.cpu.target == 1.15 and not s.risks


def test_the_limit_still_wins_below_the_max() -> None:
    u = use([3.0] * 2, limits={"cpu": 1.5})
    s = sizing.size(u, NOW, custom(cpu={"max": "2"}))
    assert s.cpu and s.cpu.target == 1.5
    assert any(r.text.startswith("cpu capped at 2000m") for r in s.risks)
    assert Risk("limit_below_need", "cpu limit 1500m is below the 2000m it needs") in s.risks


# --- aiops sizing show ---------------------------------------------------------------


def requests(fake: FakePrometheus, pod: str, cpu_cores: float, memory: float) -> None:
    for res, value in (("cpu", cpu_cores), ("memory", memory)):
        fake.add(
            "kube_pod_container_resource_requests",
            value,
            namespace="shop",
            pod=pod,
            container="app",
            resource=res,
        )


def run_show(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    fake: FakePrometheus,
    sizing_config: dict[str, Any] | None = None,
    as_json: bool = False,
) -> str:
    data = make_contract().model_dump()
    data["integrations"].append({"name": "prometheus", "url": "http://prometheus"})
    if sizing_config is not None:
        data["sizing"] = sizing_config
    monkeypatch.setattr(cli, "contract", lambda settings, cid: contracts.build(data))
    monkeypatch.setattr(usage, "Prom", lambda t: _prom(fake, t))
    argv = ["sizing", "show", "--contract", "acme"] + (["--json"] if as_json else [])
    assert cli.main(argv) == 0
    return capsys.readouterr().out


def lab(fake: FakePrometheus) -> None:
    """A Deployment, a CronJob's pod, a database and an idle one, two days of usage."""
    for name in ("api", "db", "idle"):
        (p,) = deployment(fake, name, pods=1)
        cpu(fake, p, [0.1] * 1441)
        mem(fake, p, [80 * MI] * 1441)
        requests(fake, p, 1.0, 2**30)
    fake.add(
        "kube_job_owner",
        1,
        namespace="shop",
        job_name="report-1",
        owner_kind="CronJob",
        owner_name="report",
    )
    owner(fake, "report-1-x", "Job", "report-1")
    cpu(fake, "report-1-x", [0.5] * 1441)
    mem(fake, "report-1-x", [100 * MI] * 1441)


def test_show_sizes_each_workload_under_its_policy(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakePrometheus()
    lab(fake)
    rules = [
        {"name": "db", "policy": "high-availability"},
        {"name": "idle", "policy": "off"},
    ]
    out = run_show(monkeypatch, capsys, fake, {"rules": rules})
    assert (
        "test/shop/Deployment/api/app (production): cpu lower 1000m -> 115m, memory lower "
        "1024Mi -> 96Mi | history 2.0d of 7d" in out
    )
    # 14 d windows step every 3 minutes: 1441 samples are three days, enough for 72 h
    assert (
        "test/shop/Deployment/db/app (high-availability): cpu lower 1000m -> 130m, memory "
        "lower 1024Mi -> 108Mi | history 3.0d of 14d" in out
    )
    assert "test/shop/Deployment/idle/app (off): excluded" in out
    assert "test/shop/CronJob/report/app (batch): cpu set unset -> 550m" in out


def test_a_short_history_is_learning_against_the_policys_own_need(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakePrometheus()
    (p,) = deployment(fake, "db", pods=1)
    cpu(fake, p, [0.1] * 600)  # 600 steps of 3 minutes: 30 h
    out = run_show(
        monkeypatch, capsys, fake, {"rules": [{"name": "db", "policy": "high-availability"}]}
    )
    assert "test/shop/Deployment/db/app (high-availability): learning (29.9 h of 72 h)" in out


def test_a_full_window_has_no_history_note(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakePrometheus()
    (p,) = deployment(fake, "api", pods=1)
    cpu(fake, p, [0.1] * 5041)  # 7 d at 2-minute steps
    requests(fake, p, 1.0, 2**30)
    out = run_show(monkeypatch, capsys, fake)
    assert "test/shop/Deployment/api/app (production): cpu lower 1000m -> 115m\n" in out


def test_each_policy_reads_oom_kills_over_its_own_window(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An OOM kill 10 days ago is outside production's 7 days: its memory may go down.
    The same kill holds a batch Workload's (14 days). Production stays 9.2's Sizing
    whether the Contract also has a 14-day policy or not."""
    fake = FakePrometheus()
    for name in ("api", "nightly"):
        (p,) = deployment(fake, name, pods=1)
        cpu(fake, p, [0.1] * 1441)
        mem(fake, p, [80 * MI] * 1441)
        requests(fake, p, 1.0, 2**30)
        fake.add(
            "kube_pod_container_status_last_terminated_reason",
            1,
            ago=10 * DAY,
            namespace="shop",
            pod=p,
            container="app",
            reason="OOMKilled",
        )
    rules = [{"name": "nightly", "policy": "batch"}]
    out = run_show(monkeypatch, capsys, fake, {"rules": rules})
    assert "Deployment/api/app (production): cpu lower 1000m -> 115m, memory lower" in out
    batch = next(line for line in out.splitlines() if "/nightly/" in line)
    assert "(batch): cpu lower 1000m -> 110m, memory keep 1024Mi -> 1024Mi" in batch
    assert "memory kept: OOM kills hide how much it needs" in batch
    assert "OOM" not in next(line for line in out.splitlines() if "/api/" in line)
    alone = run_show(
        monkeypatch,
        capsys,
        fake,
        {"default": "production", "rules": [{"name": "nightly", "policy": "off"}]},
    )
    api = [line for line in out.splitlines() if "/api/" in line]
    assert api and api[0] in alone.splitlines()


def test_show_json_names_the_policy(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakePrometheus()
    lab(fake)
    rows = json.loads(
        run_show(
            monkeypatch, capsys, fake, {"rules": [{"name": "idle", "policy": "off"}]}, as_json=True
        )
    )
    by = {r["workload"].split("/")[3]: r for r in rows}
    assert by["api"]["policy"] == "production" and by["api"]["window_h"] == 168
    assert by["report"]["policy"] == "batch" and by["report"]["needs_h"] == 24
    idle = by["idle"]
    assert (idle["workload"], idle["policy"], idle["state"]) == (
        "test/shop/Deployment/idle/app",
        "off",
        "excluded",
    )
    assert "cpu" not in idle and "waste" not in idle


def test_show_queries_only_the_windows_the_rules_can_reach(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakePrometheus()
    lab(fake)
    run_show(
        monkeypatch,
        capsys,
        fake,
        {"policies": {"lean": {"base": "production", "window": "3d"}}, "default": "lean"},
    )
    owners = [q for q in fake.queries if q.startswith("last_over_time(kube_pod_owner")]
    assert sorted(q.rsplit("[", 1)[1] for q in owners) == [f"{14 * DAY}s])", f"{3 * DAY}s])"]


def test_a_contract_with_policies_survives_a_round_trip() -> None:
    data = make_contract().model_dump()
    data["sizing"] = {"policies": {"lean": {"base": "batch", "window": "3d"}}}
    c = contracts.build(data)
    again = contracts.build(c.model_dump())
    assert again.sizing == c.sizing and again.sizing.policies["lean"].base == "batch"
