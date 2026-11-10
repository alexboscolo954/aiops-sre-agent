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

Thin on purpose: Deployments only, every pod at once, and "applied" means the API server
took the new requests (whether the kubelet could is slice 12.3).
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

log = logging.getLogger("aiops.actuator")

CONFIGMAP = "aiops-actuator"  # in its own namespace: what it applied, by container
KEY = "applied.json"
MAX_REPORTS = 1000  # per POST, and kept unsent while the Hub is unreachable
MIN_MINOR = 33  # Kubernetes 1.33: in-place pod resize on by default
MI = 2**20
WEBHOOK = "aiops-actuator"  # its MutatingWebhookConfiguration and its Service, by name
WEBHOOK_PORT = 8443
MAX_REVIEW = 1024 * 1024  # bytes: an AdmissionReview of one pod is far smaller
Outcome = Literal["applied", "skipped", "failed", "handed_back"]


class ActuatorSettings(BaseSettings):
    """The Actuator's own configuration, set by the client in its manifest. No field may
    be named like a Service link (`port`, `service_host`): see RelaySettings."""

    model_config = SettingsConfigDict(env_prefix="AIOPS_ACTUATOR_")

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
    sizings: list[Wanted]


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


def apply(core: Any, apps: Any, w: Wanted, at: float) -> tuple[Actuation, dict[str, Any]]:
    """Resize `w`'s container in place on every pod of its Deployment, never above its
    limit: the Actuation, and what to remember of it."""
    set_to: dict[str, str] = {}
    template_had: dict[str, str | None] = {}  # its template's requests then: a change hands back

    def done(outcome: Outcome, pods: int, reason: str) -> tuple[Actuation, dict[str, Any]]:
        values = {r: float(qty(q)) for r, q in set_to.items()}
        a = Actuation(
            **w.model_dump(exclude={"cpu", "memory"}),
            outcome=outcome,
            pods=pods,
            reason=reason[:1000],
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
    template = next((c for c in d.spec.template.spec.containers if c.name == w.container), None)
    if template is None:
        return done("skipped", 0, f"no container {w.container!r} in its template")
    limits = (template.resources.limits if template.resources else None) or {}
    asked = (template.resources.requests if template.resources else None) or {}
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
    restarts = sorted(
        p.resource_name
        for p in template.resize_policy or []
        if p.restart_policy == "RestartContainer" and p.resource_name in set_to
    )
    if restarts:
        return done("skipped", 0, f"its resizePolicy restarts the container for {restarts}")
    try:
        pods = pods_of(core, apps, d)
    except ApiException as e:  # a namespace its RoleBinding misses: the others still go on
        return done("failed", 0, f"listing its pods: {why(e)}")
    if not pods:
        return done("skipped", 0, "no live pods")
    resized, failures = 0, []
    for p in pods:
        c = next((c for c in p.spec.containers if c.name == w.container), None)
        now = (c.resources.requests if c and c.resources else None) or {}
        if all(r in now and qty(now[r]) == qty(q) for r, q in set_to.items()):
            continue
        body = {"spec": {"containers": [{"name": w.container, "resources": {"requests": set_to}}]}}
        try:
            core.patch_namespaced_pod_resize(p.metadata.name, w.namespace, body)
            resized += 1
        except ApiException as e:
            failures.append(f"{p.metadata.name}: {why(e)}")
    note = f"; capped at its limit: {capped}" if capped else ""
    if failures:
        note += f"; {len(failures)} refused, first {failures[0]}"
    if resized:
        return done("applied", resized, f"{resized} of {len(pods)} pods resized in place{note}")
    if failures:
        return done("failed", 0, f"no pod resized{note}")
    return done("skipped", 0, f"all {len(pods)} pods already have these requests{note}")


EVENTS = {
    "applied": "SizingApplied",
    "skipped": "SizingSkipped",
    "failed": "SizingFailed",
    "handed_back": "HandedBack",
}


GONE = {"handed_back": "back to its template"}


def event(core: Any, a: Actuation) -> None:
    """A Kubernetes Event on the Deployment, so `kubectl describe` shows what was done."""
    now = datetime.now(UTC)
    values = ", ".join(
        f"{r} {text(v)}"
        for r, v, text in (("cpu", a.cpu, cpu_text), ("memory", a.memory, memory_text))
        if v is not None
    )
    body = client.CoreV1Event(
        metadata=client.V1ObjectMeta(name=f"{a.name}.{uuid.uuid4().hex[:16]}"),
        involved_object=client.V1ObjectReference(
            api_version="apps/v1", kind=a.kind, name=a.name, namespace=a.namespace
        ),
        reason=EVENTS[a.outcome],
        message=f"{a.container}: {values or GONE.get(a.outcome, 'no change')} "
        f"(Approved Sizing, run {a.run_id}): "
        f"{a.reason}"[:1024],
        type="Warning" if a.outcome == "failed" else "Normal",
        source=client.V1EventSource(component="aiops-actuator"),
        reporting_component="aiops-actuator",
        first_timestamp=now,
        last_timestamp=now,
        count=1,
    )
    try:
        core.create_namespaced_event(a.namespace, body)
    except ApiException as e:
        log.warning("event on %s/%s: %s", a.namespace, a.name, why(e))


def check_version(version: Any) -> None:
    """Refuse a cluster without in-place pod resize on by default."""
    v = version.get_code()
    minor = re.match(r"\d+", v.minor or "")
    if (int(v.major), int(minor.group()) if minor else 0) < (1, MIN_MINOR):
        raise SystemExit(f"Kubernetes {v.git_version}: the Actuator needs 1.{MIN_MINOR} or later")


# --- the pod-creation webhook (slice 12.2) ------------------------------------------------


def mutation(req: dict[str, Any], held: dict[str, dict[str, Any]], own: str) -> list[Any]:
    """The JSON Patch giving a new pod of a Deployment the requests applied to it: only
    where its container still asks what the template asked then (a person's change wins),
    never above its limit, never in kube-* or the Actuator's own namespace."""
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
        if not new:
            continue
        at = f"/spec/containers/{i}/resources"
        if "resources" not in c:
            ops.append({"op": "add", "path": at, "value": {"requests": new}})
        elif "requests" not in resources:
            ops.append({"op": "add", "path": f"{at}/requests", "value": new})
        else:
            ops += [{"op": "add", "path": f"{at}/requests/{r}", "value": q} for r, q in new.items()]
    return ops


def admit(review: Any, held: dict[str, dict[str, Any]], killed: bool, own: str) -> dict[str, Any]:
    """The AdmissionReview answer: always allowed; a patch unless the Kill switch is on."""
    req = review.get("request") if isinstance(review, dict) else None
    req = req if isinstance(req, dict) else {}
    answer: dict[str, Any] = {"uid": req.get("uid", ""), "allowed": True}
    try:
        ops = [] if killed else mutation(req, held, own)
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
            body = json.dumps(admit(review, a.held, a.killed, a.namespace)).encode()
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
        if desired is not None:
            if desired.kill_switch != self.killed:
                self.killed = desired.kill_switch
                log.warning("the Kill switch is %s", "on" if self.killed else "off")
            done = [] if self.killed else self.act(desired.sizings)
        else:
            done = []
        done += self.hand_back()
        if done:
            self.save()
            self.unsent += done
        self.report()

    def hand_back(self) -> list[Actuation]:
        """Each container it holds whose Deployment's template now asks other requests than
        when it applied (a person's change), or that is gone: its own again, never held."""
        out = []
        for key, h in self.held.items():
            if h.get("outcome") == "applied":
                reason = self.changed(key, h)
                if reason is None:
                    continue
                ns, kind, name, container = key.split("/")
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
                event(self.core, a)
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

    def act(self, sizings: list[Wanted]) -> list[Actuation]:
        """Each Approved Sizing newer than what it applied to that container: applied once,
        whatever its outcome (a refused one waits for the next approval)."""
        out = []
        for w in sizings:
            key = "/".join((w.namespace, w.kind, w.name, w.container))
            if self.held.get(key, {}).get("run_id", -1) >= w.run_id:
                continue
            a, self.held[key] = apply(self.core, self.apps, w, time.time())
            log.info("%s %s: %s", a.outcome, key, a.reason)
            event(self.core, a)
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
