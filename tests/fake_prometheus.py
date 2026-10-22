"""A Prometheus HTTP API over fixture series, for Sizing tests without a cluster.

It applies every label matcher in the query (=, !=, =~, !~) exactly as Prometheus
would, so a query that forgets its namespace or cluster matcher returns other
Contracts' series and the isolation tests catch it. PromQL functions around the
selector (rate, max_over_time, increase, last_over_time) are ignored: a fixture
series holds the values that query would return. `count(...)` counts matches.
"""

import re
from dataclasses import dataclass, field
from typing import Any

import httpx

SELECTOR = re.compile(r"([a-zA-Z_:][a-zA-Z0-9_:]*)\{([^}]*)\}")
MATCHER = re.compile(r'\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*(=~|!~|!=|=)\s*"((?:[^"\\]|\\.)*)"\s*,?')


def _unquote(value: str) -> str:
    return re.sub(r"\\(.)", lambda m: {"n": "\n"}.get(m.group(1), m.group(1)), value)


def _matches(labels: dict[str, str], op: str, name: str, value: str) -> bool:
    have = labels.get(name, "")
    if op == "=":
        return have == value
    if op == "!=":
        return have != value
    hit = re.fullmatch(value, have) is not None
    return hit if op == "=~" else not hit


@dataclass
class FakePrometheus:
    series: list[dict[str, Any]] = field(default_factory=list)  # {"__name__", labels..., values}
    queries: list[str] = field(default_factory=list)
    status: int = 200

    def add(self, metric: str, values: list[float] | float, **labels: str) -> None:
        self.series.append({"__name__": metric, **labels, "_values": values})

    def select(self, promql: str) -> list[dict[str, Any]]:
        m = SELECTOR.search(promql)
        assert m, f"no selector in {promql!r}"
        name, body = m.groups()
        matchers = [(n, op, _unquote(v)) for n, op, v in MATCHER.findall(body)]
        assert "".join(MATCHER.sub("", body).split()) == "", f"unparsed matchers in {body!r}"
        return [
            s
            for s in self.series
            if s["__name__"] == name and all(_matches(s, op, n, v) for n, op, v in matchers)
        ]

    def handler(self, request: httpx.Request) -> httpx.Response:
        promql = request.url.params["query"]
        self.queries.append(promql)
        if self.status != 200:
            return httpx.Response(self.status, json={"status": "error", "error": "boom"})
        found = self.select(promql)

        def labels(s: dict[str, Any]) -> dict[str, str]:
            return {k: v for k, v in s.items() if not k.startswith("_") and k != "__name__"}

        if request.url.path.endswith("/query_range"):
            start, step = float(request.url.params["start"]), float(request.url.params["step"])
            result: list[dict[str, Any]] = [
                {
                    "metric": labels(s),
                    "values": [[start + i * step, str(v)] for i, v in enumerate(s["_values"])],
                }
                for s in found
            ]
        elif promql.startswith("count("):
            result = [{"metric": {}, "value": [0, str(len(found))]}] if found else []
        else:
            result = [
                {
                    "metric": labels(s),
                    "value": [
                        0,
                        str(s["_values"][-1] if isinstance(s["_values"], list) else s["_values"]),
                    ],
                }
                for s in found
            ]
        kind = "matrix" if request.url.path.endswith("/query_range") else "vector"
        return httpx.Response(
            200, json={"status": "success", "data": {"resultType": kind, "result": result}}
        )

    def client(self) -> httpx.Client:
        return httpx.Client(
            base_url="http://prometheus", transport=httpx.MockTransport(self.handler)
        )
