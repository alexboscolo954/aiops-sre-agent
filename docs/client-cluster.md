# The client's cluster: Relay and Actuator

Two optional parts run inside a client's cluster, from the Hub's own image. Each dials out to the Hub over HTTPS, so the client opens no inbound port.

- **Relay**: for a cluster the Hub can't reach. It carries the Hub's reads (and, only if the client allows it, the two gated actions) and the cluster's alerts.
- **Actuator**: applies the Sizings an Operator approved, in place, and rolls one back if it hurt the pods.

## What each one may do

| | Relay | Actuator |
|---|---|---|
| Namespace | `squero-relay` | `squero-actuator` |
| Reads | read-only ServiceAccount, bound per namespace, like the Hub's own | pods, Deployments, ReplicaSets, HPAs, VPAs, LimitRanges and ResourceQuotas in the Contract's namespaces |
| Writes | none, unless the client also applies `deploy/relay-actions`: evict pods and scale deployments only | resize pods (`pods/resize`, a RoleBinding per namespace), create Events, read and replace its own ConfigMap, patch its own webhook's `caBundle` |
| Token | `relay_token_secret` | `actuator_token_secret`, never a Relay's |
| Talks to | `wss://<the Hub's domain>/relay` | `GET /actuator/desired`, `POST /actuator/reports` |

Neither can change an image or a command. The full table is in [safety.md](safety.md).

## A cluster behind a Relay

A cluster in a client network the Hub can't reach sets `via: relay` and `relay_token_secret` (a secret in the Contract's SOPS file, 32 characters or more; the client puts the same value in its Relay's Secret). The Relay inside that network holds the cluster's credentials and dials the Hub's `/relay` websocket with that token, which binds it to this Contract's cluster and nothing else. Such a cluster names no `context`, kubeconfig, `in_cluster`, `allow_exec` or Prometheus URL or token here: the Hub never reaches it Direct, and refuses to start if a Relay token is another Relay's or equals the approver, MCP or a webhook token. The agent names it like any other cluster: its Kubernetes and Prometheus calls go to the Relay after the Hub's own cluster and namespace check, through the Hub's own tools (list, schemas, approval gate), so nothing else a Relay offers reaches the agent. A Run that calls it while its Relay is offline, or gets no answer within `SQUERO_RELAY_CALL_SECONDS`, ends Failed ("Relay offline"). `recent_changes` takes no namespace, so the Hub keeps only the changes in the Contract's namespaces (a GitOps notice: its GitOps namespaces), however many the Relay allows. The Hub's own reads go through it too: its hourly Sizings and node facts and the Bill check's node-hours, as the Relay's `hub_promql_*`, when the Contract has a `prometheus` integration. Health shows each Relay connected (since when, and the version it reports) or offline (since when), with the Kubernetes and Prometheus checks made through it; the Agenda lists an offline Relay as data the Hub can't read. Its cluster's alerts come through it as well: the Hub takes them as from the Contract's own alert route, with the same webhook token, and nothing about them differs from there on.

```yaml
clusters:
  - name: edge
    namespaces: [shop]
    via: relay
    relay_token_secret: edge-relay-token
```

## Running a Relay

The client applies `deploy/relay` in its own cluster (namespace `squero-relay`): a read-only ServiceAccount bound per namespace, like the Hub's own, and one `squero relay` pod from the same image, with its token from a Secret they create (`kubectl -n squero-relay create secret generic squero-relay --from-literal=SQUERO_RELAY_TOKEN=...`). It serves the Hub's own tool names for its one cluster, so the Hub's allowlist and approval gate apply unchanged, plus `hub_promql_instant` and `hub_promql_range` for the Hub's own Sizing and Health queries, which the agent never gets. Write tools don't exist on it unless the client also applies `deploy/relay-actions`, which turns `SQUERO_RELAY_WRITES` on and adds RBAC for evicting pods and scaling deployments only; the Contract's `enable_actions` and your approval still apply on top. It dials `wss://<the Hub's domain>/relay`, a public route like the alert routes and the Actuator's two (Caddy passes only a websocket upgrade there). It dials again after any drop, waiting 1 s, doubling to a minute, and back to 1 s once a connection has held; a refused token logs "check the token" and keeps trying.

## Alerts through a Relay

The Relay's Service (`squero-relay.squero-relay:8080`) takes the cluster's own Alertmanager webhook at `POST /alertmanager`, with the Contract's webhook token as its bearer credentials, exactly as a Direct cluster's Alertmanager posts to the Hub. The Relay keeps no queue and no secret of its own for it: it sends each alert group over its connection to the Hub, which checks the token against the Relay's own Contract (never another's) and answers once the alert is stored. Alertmanager gets the Hub's answer: 202, 401 for a wrong token, 422 for something that isn't an alert group; 503 when the Relay has no connection to the Hub or no answer within 10 s, and 502 when the Hub failed to take it, so Alertmanager sends it again. A receiver for it:

```yaml
receivers:
  - name: squero
    webhook_configs:
      - url: http://squero-relay.squero-relay:8080/alertmanager
        send_resolved: true
        http_config:
          authorization:
            credentials_file: /etc/alertmanager/secrets/squero-webhook/token   # the Contract's webhook token
```

| Relay setting | Default | What it is |
|---|---|---|
| `SQUERO_RELAY_HUB` | (required) | the Hub's `wss://<domain>/relay` |
| `SQUERO_RELAY_TOKEN` | (required) | the value of the Contract's `relay_token_secret` |
| `SQUERO_RELAY_CLUSTER` | (required) | the cluster's `name` in the Contract |
| `SQUERO_RELAY_NAMESPACES` | (required) | JSON list, as the RoleBindings grant |
| `SQUERO_RELAY_GITOPS_NAMESPACES` | `[]` | where Argo CD or Flux objects live (needs their read RBAC too: `kubectl apply -f deploy/relay/rbac-gitops.yaml`) |
| `SQUERO_RELAY_PROMETHEUS_URL` | none | the cluster's Prometheus inside the client's network |
| `SQUERO_RELAY_PROMETHEUS_TOKEN` | none | its bearer token |
| `SQUERO_RELAY_WRITES` | `false` | the client's switch for the two write tools |
| `SQUERO_RELAY_ALERTS_PORT` | `8080` | its Alertmanager receiver |

## Running an Actuator

A cluster whose Approved Sizings should be applied sets `actuator_token_secret` (a secret in the Contract's SOPS file, 32 characters or more, never a Relay's token; Direct and Relay clusters alike). The client applies `deploy/actuator` in that cluster (namespace `squero-actuator`): one `squero actuator` pod from the same image, a ServiceAccount that can read pods, Deployments, ReplicaSets, HPAs, VPAs, LimitRanges and ResourceQuotas and resize pods in the Contract's namespaces (a RoleBinding per namespace), create Events, read and replace its own ConfigMap, and patch its own webhook's `caBundle`, and a MutatingWebhookConfiguration whose `namespaceSelector` lists the same namespaces; its token comes from a Secret they create (`kubectl -n squero-actuator create secret generic squero-actuator --from-literal=SQUERO_ACTUATOR_TOKEN=...`). It refuses to start below Kubernetes 1.33. Every minute it pulls `GET https://<the Hub's domain>/actuator/desired`: its cluster's current Approved Sizings of Deployments in the cluster's namespaces, none while the Kill switch is on. Each one newer than what it applied to that container is applied once: every running pod of the Deployment gets the approved requests through the `resize` subresource, in place, never above the container's limit, and a container whose `resizePolicy` would restart for it is skipped. It keeps what it did in its ConfigMap `squero-actuator` (a restart applies nothing twice), writes an Event on the Deployment (`SizingApplied`, `SizingSkipped`, `SizingFailed`) and reports each outcome to `POST /actuator/reports`, which the Hub keeps 90 days as the Contract's `actuations`; a report the Hub didn't take is sent again, unless it refused it (a 4xx other than 401, 403 or 429: logged and dropped). The Hub takes a report only for the namespaces of the token's own cluster.

```yaml
clusters:
  - name: prod
    context: prod
    namespaces: [shop]
    actuator_token_secret: prod-actuator-token
```

| Actuator setting | Default | What it is |
|---|---|---|
| `SQUERO_ACTUATOR_HUB` | (required) | the Hub's `https://<domain>` |
| `SQUERO_ACTUATOR_TOKEN` | (required) | the value of the Contract's `actuator_token_secret` |
| `SQUERO_ACTUATOR_NAMESPACE` | (required) | its own namespace, for its ConfigMap (the manifest sets it) |
| `SQUERO_ACTUATOR_INTERVAL` | `60` | seconds between pulls |

## Holding requests: the webhook

What it applied it holds: its webhook gives a new pod of that Deployment (a rollout, a reschedule, a scale-up) the same requests, never above the pod's limit, as long as the container still asks what its template asked when the Actuator applied. When a person changes those requests in the template, or the Deployment or its container goes, the Actuator hands the container back: a `HandedBack` Event, an Actuation `handed_back`, and new pods keep the template's requests from then on. The webhook serves TLS with a certificate the Actuator makes at each start and puts in its webhook's `caBundle` (no cert-manager). It fails open: with the Actuator down, slow or scaled to zero, pods start from their template; while the Kill switch is on it changes no pod.

## Pre-checks and the rollout

Before a resize it skips, with the reason in its Event and Actuation, a change that would change the pods' QoS class (a Guaranteed container's limits would have to change too), a Deployment a VPA sizes (any mode but `Off`), requests outside the namespace's LimitRange (minimum, maximum, limit-to-request ratio) and an increase that would pass a ResourceQuota; it never clamps. A resource an HPA of the Deployment scales on by utilization (cpu for an HPA without metrics) is left to it, the other one still sized. Then it resizes one canary pod and watches it 10 minutes, then the others one at a time, each once the kubelet allocated the last one and it is Ready (one per minute). A resize the kubelet calls `Infeasible`, or one not done in 10 minutes (`Deferred` included), stops it there as failed; it never evicts to make room. "Applied" is reported when every live pod has the new requests. The rollout goes on only while the Hub answers and the Kill switch is off. Only Deployments, for now.

## Rollback

From its first resize until an hour after the rollout ends, the Actuator watches the pods with its requests: a container that restarts (an OOM kill named as one) since it got them, or a pod it resized that stays NotReady for 2 minutes, rolls the Sizing back. Every pod with its requests goes back to the template's, in place and at once (a request the template doesn't set stays), with a `SizingRolledBack` Event, an Actuation `rolled_back`, and a message in the Contract's operator channel (once, however often the report is resent). Then it applies no new Sizing of that container for 24 hours, 48 after a second rollback within 7 days, 96 after a third: an approval meanwhile is skipped with the date. CPU throttling is no reason (it is already a Sizing's risk). It rolls back with the Hub unreachable too, never while the Kill switch is on.
