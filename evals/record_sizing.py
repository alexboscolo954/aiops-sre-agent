"""Record the oom-killed-sizing Scenario (slice 9.6a) from the kind lab's `leaky`
Workload, which is OOM-killed about hourly, through the Hub image: its real
kubernetes tools and its real stored Sizings, refreshed first so they hold limits.

    make image
    cd ~/aiops-hub && AIOPS_IMAGE=aiops-sre-agent:ci docker compose run --rm --no-deps \\
      -T --entrypoint python hub - --contract demo-shop \\
      < ~/aiops-sre-agent/evals/record_sizing.py \\
      > ~/aiops-sre-agent/evals/scenarios/oom-killed-sizing.yaml

Writes nothing (exit 1) unless leaky's last termination is an OOM kill and its
Sizing suggests memory. Lab data is synthetic; the YAML is still checked for the
Operator's names before it is printed.
"""

import argparse
import asyncio
import json
import re
import sys
import time
from typing import Any

import yaml
from fastmcp import Client
from kubernetes.utils import parse_quantity

from aiops_agent import agent, contracts, sizing
from aiops_agent.config import Settings
from aiops_agent.contracts import Kubernetes
from aiops_agent.servers import sizing as sizing_tool
from aiops_agent.store import Store, connect

CLUSTER, NAMESPACE, APP = "kind", "lab", "leaky"
PRIVATE = re.compile(r"tail[0-9a-f]{6}|endwar|alex|/Users/|ts\.net", re.IGNORECASE)


async def call(client: Client, tool: str, args: dict[str, Any]) -> Any:
    r = await client.call_tool(tool, args, raise_on_error=False)
    if r.is_error:
        return {"error": r.content[0].text if r.content else "error"}  # type: ignore[union-attr]
    data = r.structured_content
    return data["result"] if isinstance(data, dict) and set(data) == {"result"} else data


async def main(contract_id: str) -> int:
    settings = Settings()
    assert settings.contracts_dir and settings.database_url
    c = contracts.load(settings.contracts_dir)[contract_id]
    k8s = next(i for i in c.integrations if isinstance(i, Kubernetes))
    where = {"cluster": CLUSTER, "namespace": NAMESPACE}
    async with connect(settings.database_url.get_secret_value()) as pool:
        store = Store(pool)
        await sizing.store_run(store, c, time.time(), every=0)  # rows with limits
        async with Client(agent.integration_server(c, k8s, settings)[0]) as kube:
            pods = await call(kube, "list_pods", where)
            pod = next(p["name"] for p in pods if p["name"].startswith(APP + "-"))
            described = await call(kube, "describe_pod", {**where, "name": pod})
            tools: dict[str, Any] = {
                "kubernetes_list_pods": pods,
                "kubernetes_list_deployments": await call(kube, "list_deployments", where),
                "kubernetes_get_events": await call(kube, "get_events", where),
                "kubernetes_recent_changes": [
                    e
                    for e in await call(kube, "recent_changes", {"cluster": CLUSTER})
                    if e.get("namespace") == NAMESPACE
                ],
                "kubernetes_describe_pod": [{"match": {"name": pod}, "result": described}],
                "kubernetes_describe_deployment": [
                    {
                        "match": {"name": APP},
                        "result": await call(kube, "describe_deployment", {**where, "name": APP}),
                    }
                ],
                "kubernetes_pod_logs": [],
            }
            for previous in (True, False):
                logs = await call(kube, "pod_logs", {**where, "name": pod, "previous": previous})
                match = {"name": pod, "previous": previous}
                tools["kubernetes_pod_logs"].append({"match": match, "result": logs})
                if not previous:
                    tools["kubernetes_pod_logs"].append({"match": {"name": pod}, "result": logs})
        async with Client(sizing_tool.build_server(c, store)) as sz:
            sized = await call(sz, "for_workload", {**where, "name": pod})
    tools["sizing_for_workload"] = [  # another name gets "no recorded data", as for real
        {"match": {"name": pod}, "result": sized},
        {"match": {"name": APP}, "result": sized},
    ]
    if "OOMKilled" not in json.dumps(described):
        print(f"{pod}: no OOM kill in describe_pod; wait for the next one", file=sys.stderr)
        return 1
    (w,) = sized["workloads"]
    (row,) = [x for x in w["containers"] if "suggested" in x] or [None]
    if row is None:
        print(f"no suggestion in the Sizing: {json.dumps(sized)}", file=sys.stderr)
        return 1
    killed_at = row["memory"]["limit"] or row["memory"]["peak"]
    scenario = {
        "description": "The lab's leaky Workload leaks memory (its LEAK_MIB_PER_MIN env var "
        "says so) and is OOM-killed at its limit about hourly: a leak is app_error, a limit "
        "too low resource_limits, and either reading is fair. The Report must recommend a "
        f"memory request above what it was killed at ({killed_at}) and cite the Hub's Sizing.",
        "namespace": NAMESPACE,
        "integrations": ["kubernetes", "sizing"],
        "alert": {
            "status": "firing",
            "commonLabels": {"alertname": "KubePodCrashLooping", "namespace": NAMESPACE},
            "alerts": [
                {
                    "status": "firing",
                    "labels": {
                        "alertname": "KubePodCrashLooping",
                        "namespace": NAMESPACE,
                        "pod": pod,
                        "severity": "warning",
                    },
                    "annotations": {"summary": "Pod is crash looping."},
                }
            ],
        },
        "expect": {
            "category": ["app_error", "resource_limits"],
            "keywords": ["memory"],
            "memory_above": killed_at,
            "evidence": ["sizing_for_workload"],
            "max_tool_calls": 10,
        },
        "tools": tools,
    }
    assert float(parse_quantity(killed_at)) > 0  # type: ignore[no-untyped-call]
    text = yaml.safe_dump(scenario, sort_keys=False, width=100)
    if found := sorted(set(PRIVATE.findall(text))):
        print(f"refusing to write: private values {found}", file=sys.stderr)
        return 1
    print(text, end="")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True)
    sys.exit(asyncio.run(main(parser.parse_args().contract)))
