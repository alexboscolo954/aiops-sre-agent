# ruff: noqa: S310, S311 - a fixed http endpoint, and randomness only for realism
"""Synthetic telemetry for the Grafana Scenarios, sent as OTLP/HTTP JSON to the
LGTM stack with the standard library only. MODE picks the failure:

payments: some charges fail because a dependency refuses connections. Only the
  logs say which, buried among noisier lines: log patterns show it at once.
storefront: some product pages are slow. The logs say only "200, slow"; the
  traces show which downstream span takes the time, and why.
"""

import json
import os
import random
import secrets
import time
import urllib.request

OTLP = os.environ.get("OTLP_ENDPOINT", "http://lgtm.observability:4318")
MODE = os.environ["MODE"]


def post(path: str, body: dict) -> None:
    req = urllib.request.Request(
        OTLP + path, json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except OSError as e:
        print(f"otlp {path}: {e}", flush=True)


def attrs(d: dict) -> list:
    return [
        {"key": k, "value": {"intValue": v} if isinstance(v, int) else {"stringValue": str(v)}}
        for k, v in d.items()
    ]


def resource(service: str) -> dict:
    return {"attributes": attrs({"service.name": service, "service.namespace": "shop"})}


def logs(service: str, records: list[tuple[str, str, str, str]]) -> None:
    """records: (severity, body, trace_id, span_id)."""
    now = time.time_ns()
    out = [
        {
            "timeUnixNano": str(now + i * 50_000_000),  # spread over the second it covers
            "severityText": sev,
            "severityNumber": {"DEBUG": 5, "INFO": 9, "WARN": 13, "ERROR": 17}[sev],
            "body": {"stringValue": body},
            **({"traceId": trace, "spanId": span} if trace else {}),
        }
        for i, (sev, body, trace, span) in enumerate(records)
    ]
    body = {"resourceLogs": [{"resource": resource(service), "scopeLogs": [{"logRecords": out}]}]}
    post("/v1/logs", body)


def span(trace, parent, name, start, ms, kind=2, error=None, **a) -> dict:
    s = {
        "traceId": trace,
        "spanId": secrets.token_hex(8),
        "name": name,
        "kind": kind,
        "startTimeUnixNano": str(start),
        "endTimeUnixNano": str(start + int(ms * 1e6)),
        "attributes": attrs(a),
        "status": {"code": 2, "message": error} if error else {"code": 1},
    }
    if parent:
        s["parentSpanId"] = parent
    return s


def traces(by_service: dict[str, list[dict]]) -> None:
    body = {
        "resourceSpans": [
            {"resource": resource(svc), "scopeSpans": [{"spans": spans}]}
            for svc, spans in by_service.items()
        ]
    }
    post("/v1/traces", body)


NOISE = [
    ("DEBUG", lambda: f"cache refresh key=card-bin:{random.randint(400000, 499999)} ttl=300s"),
    ("DEBUG", lambda: f"pool stats active={random.randint(1, 9)} idle={random.randint(0, 5)}"),
    ("INFO", lambda: f"webhook delivered merchant=m-{random.randint(100, 999)} attempt=1"),
    (
        "WARN",
        lambda: f"slow serializer {random.randint(51, 90)}ms for receipt r-{secrets.token_hex(3)}",
    ),
    ("DEBUG", lambda: f"feature flag smart-retry evaluated={random.choice(['on', 'off'])}"),
    ("INFO", lambda: f"settlement batch b-{random.randint(1000, 9999)} queued"),
]


def payments() -> None:
    records = []
    for _ in range(12):
        order, trace = f"o-{secrets.token_hex(4)}", secrets.token_hex(16)
        roll = random.random()
        if roll < 0.08:
            records.append(
                (
                    "ERROR",
                    f"charge order={order} failed status=502: risk check unavailable: "
                    "dial tcp fraud-check.risk.svc.cluster.local:8443: connect: connection refused",
                    trace,
                    secrets.token_hex(8),
                )
            )
        elif roll < 0.45:
            ms = random.randint(30, 140)
            records.append(
                (
                    "INFO",
                    f"charge order={order} status=200 latency_ms={ms}",
                    trace,
                    secrets.token_hex(8),
                )
            )
        else:
            sev, make = random.choice(NOISE)
            records.append((sev, make(), "", ""))
    logs("payments", records)


def storefront() -> None:
    sku = f"sku-{random.randint(1000, 1099)}"
    trace, start = secrets.token_hex(16), time.time_ns()
    slow = random.random() < 0.35
    lock_ms = random.randint(2400, 3300) if slow else random.randint(2, 9)
    root = span(
        trace,
        None,
        "GET /product/{sku}",
        start,
        0,
        kind=2,
        **{"http.route": "/product/{sku}", "http.response.status_code": 200},
    )
    catalog = span(
        trace,
        root["spanId"],
        "GET /items/{sku}",
        start + int(2e6),
        14,
        kind=2,
        **{"http.route": "/items/{sku}"},
    )
    pricing = span(
        trace,
        root["spanId"],
        "GET /quote",
        start + int(18e6),
        21,
        kind=2,
        **{"http.route": "/quote"},
    )
    inv_start = start + int(41e6)
    inv = span(
        trace,
        root["spanId"],
        "GET /stock/{sku}",
        inv_start,
        lock_ms + 6,
        kind=2,
        **{"http.route": "/stock/{sku}"},
    )
    query = span(
        trace,
        inv["spanId"],
        "SELECT stock",
        inv_start + int(3e6),
        lock_ms,
        kind=3,
        **{
            "db.system": "postgresql",
            "db.namespace": "inventory",
            "db.query.text": "SELECT qty FROM stock WHERE sku = $1 FOR UPDATE",
            "db.wait_event": "Lock:tuple" if slow else "",
            "server.address": "inventory-db.shop.svc",
        },
    )
    total = 41 + lock_ms + 12
    root["endTimeUnixNano"] = str(start + int(total * 1e6))
    traces(
        {
            "storefront": [root],
            "catalog": [catalog],
            "pricing": [pricing],
            "inventory": [inv, query],
        }
    )
    note = "slow" if total > 1000 else "ok"
    logs(
        "storefront", [("INFO", f"GET /product/{sku} 200 {total}ms {note}", trace, root["spanId"])]
    )


if __name__ == "__main__":
    step = {"payments": payments, "storefront": storefront}[MODE]
    while True:
        step()
        time.sleep(1 if MODE == "payments" else 0.5)
