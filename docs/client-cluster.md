# The client's cluster: Relay and Actuator

Two optional parts run inside a client's cluster, from the Hub's own image. Each dials out to the Hub over HTTPS, so the client opens no inbound port.

- **Relay**: for a cluster the Hub can't reach. It carries the Hub's reads (and, only if the client allows it, the two gated actions) and the cluster's alerts.
- **Actuator**: applies the Sizings an Operator approved, in place, and rolls one back if it hurt the pods.

## What each one may do

| | Relay | Actuator |
|---|---|---|
| Namespace | `squero-relay` | `squero-actuator` |
| Reads | read-only ServiceAccount, bound per namespace, like the Hub's own | pods, Deployments, ReplicaSets, StatefulSets, DaemonSets, Argo Rollouts, HPAs, VPAs, PodDisruptionBudgets, LimitRanges and ResourceQuotas in the Contract's namespaces |
| Writes | none, unless the client also applies `deploy/relay-actions`: evict pods and scale deployments only | resize pods (`pods/resize`, a RoleBinding per namespace), evict pods (`pods/eviction`, only with the Contract's eviction on), create Events, read and replace its own ConfigMap, patch its own webhook's `caBundle` |
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

A cluster whose Approved Sizings should be applied sets `actuator_token_secret` (a secret in the Contract's SOPS file, 32 characters or more, never a Relay's token; Direct and Relay clusters alike). The client applies `deploy/actuator` in that cluster (namespace `squero-actuator`): one `squero actuator` pod from the same image, a ServiceAccount that can read pods, Deployments, ReplicaSets, StatefulSets, DaemonSets, Argo Rollouts, HPAs, VPAs, PodDisruptionBudgets, LimitRanges and ResourceQuotas and resize pods in the Contract's namespaces (a RoleBinding per namespace), create Events, read and replace its own ConfigMap, and patch its own webhook's `caBundle`, and a MutatingWebhookConfiguration whose `namespaceSelector` lists the same namespaces; its token comes from a Secret they create (`kubectl -n squero-actuator create secret generic squero-actuator --from-literal=SQUERO_ACTUATOR_TOKEN=...`). It refuses to start below Kubernetes 1.33. Every minute it pulls `GET https://<the Hub's domain>/actuator/desired`: its cluster's current Approved Sizings of Deployments in the cluster's namespaces, none while the Kill switch is on. Each one newer than what it applied to that container is applied once: every running pod of the Deployment gets the approved requests through the `resize` subresource, in place, never above the container's limit, and a container whose `resizePolicy` would restart for it is skipped. It keeps what it did in its ConfigMap `squero-actuator` (a restart applies nothing twice), writes an Event on the Deployment (`SizingApplied`, `SizingSkipped`, `SizingFailed`) and reports each outcome to `POST /actuator/reports`, which the Hub keeps 90 days as the Contract's `actuations`; a report the Hub didn't take is sent again, unless it refused it (a 4xx other than 401, 403 or 429: logged and dropped). The Hub takes a report only for the namespaces of the token's own cluster.

```yaml
clusters:
  - name: prod
    context: prod
    namespaces: [shop]
    actuator_token_secret: prod-actuator-token
```

It resizes the pods of Deployments, StatefulSets and DaemonSets (the last two from 0.44.0) and Argo Rollouts (from 0.45.0); CronJobs are not sent to it yet. The Actuator names the kinds it resizes on each pull, and the Hub sends it only those: one of 0.43.0 or older names none and gets Deployments only, one of 0.44.0 no Rollouts, so such an approval waits for its upgrade (re-apply `deploy/actuator/rbac.yaml` too: it reads StatefulSets, DaemonSets and, read only, `rollouts.argoproj.io`). A Rollout's pods are those of its own ReplicaSets, its stable and canary ones alike, resized in place as a Deployment's, never evicted; its template is its own, or its `workloadRef` Deployment's. Argo Rollouts not installed is none.

| Actuator setting | Default | What it is |
|---|---|---|
| `SQUERO_ACTUATOR_HUB` | (required) | the Hub's `https://<domain>` |
| `SQUERO_ACTUATOR_TOKEN` | (required) | the value of the Contract's `actuator_token_secret` |
| `SQUERO_ACTUATOR_NAMESPACE` | (required) | its own namespace, for its ConfigMap (the manifest sets it) |
| `SQUERO_ACTUATOR_INTERVAL` | `60` | seconds between pulls |

## Holding requests: the webhook

What it applied it holds: its webhook gives a new pod of that Workload (a rollout, an Argo Rollout's canary step, a reschedule, a scale-up, a new node's DaemonSet pod) the same requests, never above the pod's limit, as long as the container still asks what its template asked when the Actuator applied. When a person changes those requests in the template, or the Deployment or its container goes, the Actuator hands the container back: a `HandedBack` Event, an Actuation `handed_back`, and new pods keep the template's requests from then on. A DaemonSet's new pod gets only the requests lower than its template's, since it must start on whatever node it lands: a raise reaches it in place once it runs (caught up as below), where its node has room. Where it has none (the resize `Infeasible`, refused by the API server, or `Deferred` for 10 minutes), that pod is left without its raise: its pending resize undone, the requests it lowers still set in place (a lowering always fits), and a `PodLeft` Event. The others keep the requests, new pods still get the lowered ones, and that pod isn't tried again until the next Sizing. The same goes for a DaemonSet's pods during a rollout (a canary left, the next pod is the canary); only when no pod's node has room does it fail. The webhook serves TLS with a certificate the Actuator makes at each start and puts in its webhook's `caBundle` (no cert-manager). It fails open: with the Actuator down, slow or scaled to zero, pods start from their template; while the Kill switch is on it changes no pod. Such a pod catches up once the Actuator may change things again (the Hub reachable, the Kill switch off): the pre-checks again, then a canary and one pod at a time, as for a new approval, ending in another `SizingApplied` (a pre-check that fails now ends the hold, `SizingSkipped`).

## Pre-checks and the rollout

Before a resize it skips, with the reason in its Event and Actuation, a change that would change the pods' QoS class (a Guaranteed container's limits would have to change too), a Workload a VPA sizes (any mode but `Off`), requests outside the namespace's LimitRange (minimum, maximum, limit-to-request ratio) and an increase that would pass a ResourceQuota; it never clamps. A resource an HPA of the Workload scales on by utilization (cpu for an HPA without metrics) is left to it, the other one still sized. Then it resizes one canary pod and watches it 10 minutes, then the others one at a time, each once the kubelet allocated the last one and it is Ready (one per minute). A resize the kubelet calls `Infeasible`, or one not done in 10 minutes (`Deferred` included), stops it there as failed, unless the Contract turns eviction on ([Eviction](#eviction)); it never evicts another pod to make room. "Applied" is reported when every live pod has the new requests. The rollout goes on only while the Hub answers and the Kill switch is off. Only Deployments, for now.

## Rollback

From its first resize until an hour after the rollout ends, the Actuator watches the pods with its requests: a container that restarts (an OOM kill named as one) since it got them, or a pod it resized that stays NotReady for 2 minutes, rolls the Sizing back. Every pod with its requests goes back to the template's, in place and at once (a request the template doesn't set stays), with a `SizingRolledBack` Event and an Actuation `rolled_back` that say what went back to what ("2 pods back from cpu 115m, memory 91Mi to their template's cpu 1, memory 1Gi"), and a message in the Contract's operator channel (once, however often the report is resent). Then it applies no new Sizing of that container for 24 hours, 48 after a second rollback within 7 days, 96 after a third: an approval meanwhile is skipped with the date. CPU throttling is no reason (it is already a Sizing's risk). It rolls back with the Hub unreachable too, never while the Kill switch is on.

## Eviction

A resize that can never fit its node, because the node's allocatable is smaller than the new requests, is `Infeasible`: the kubelet marks it so on Kubernetes 1.33 and 1.34, and from 1.35 the API server refuses the resize at once (403, "node didn't have enough allocatable resources"); the Actuator treats both alike (a node that is merely full now makes it `Deferred`, which waits up to 10 minutes and then fails, as before). With eviction on, the Actuator evicts that pod instead, so its ReplicaSet starts a replacement that the scheduler places on a node with room and the webhook gives the new requests. It is off unless the Contract says so, in its `actuator:` block:

```yaml
actuator:
  eviction: true
  timezone: Europe/Rome          # IANA name; UTC when left out
  windows:                       # at least one when eviction is on
    - {days: [sat, sun], start: "00:00", end: "24:00"}
    - {days: [mon, tue, wed, thu, fri], start: "22:00", end: "02:00"}   # past midnight: the night is the day it starts
```

The Hub tells each of the Contract's Actuators, in `/actuator/desired`'s `eviction`, whether eviction is `off`, or on with its window `closed` or `open` now (`off` under the Kill switch). The windows gate eviction only: resizes in place go on at any time.

- **Outside a window** the rollout waits on that pod, without a time limit, and says so once in an `EvictionWaiting` Event. A newer Sizing, approved or under Automation, still replaces it; the pause annotation and the Kill switch stop it as any rollout. A Revert needs an Actuation of the container first, so a first rollout waiting for a window can't be reverted until it ends (a newer approval, the pause or the Kill switch can stop it).
- **Never evicted**: a StatefulSet's pod (it keeps its state; a zonal volume would pin its replacement), a DaemonSet's (it would start again on the same node), an Argo Rollout's (resized in place only), a pod of a Deployment with one replica (eviction would stop it), or one no PodDisruptionBudget in its namespace covers (nothing would keep enough pods up). Its rollout fails at once, window open or not, as with eviction off, and its Actuation says why. So does a failed read of the Deployment or its budgets.
- **Inside a window** it evicts through the Eviction API, so PodDisruptionBudgets hold: a budget that allows no disruption now keeps it waiting (one `EvictionWaiting` Event), any other refusal fails the rollout. A `PodEvicted` Event names the pod and the requests its replacement starts with.
- **Its Actuation** says so: the rollout's reason ends with `<pod> evicted, its resize Infeasible`. While a replacement is awaited, no new Sizing replaces the rollout (10 minutes at most).
- **One at a time**: never while another evicted pod's replacement is awaited, and at least 5 minutes after the last eviction, across the cluster. Only the pod whose resize is `Infeasible`, never another pod to make room.
- **The replacement** (a pod of the Deployment that wasn't there before the eviction), once Ready with the requests, stands for the evicted pod: watched for a Rollback like any pod it resized (an evicted canary's 10 minutes start again), and the rollout goes on. One that starts from its template (the webhook missed it) fails the rollout instead of evicting again. None Ready within 10 minutes is a Rollback (unless none is owed: the Deployment scaled down meanwhile and already has the pods it wants, and the rollout goes on), and a replacement still `Pending` (no node has room) is evicted again, holding nothing, so it starts from its template; a Pending pod's eviction ignores budgets.

Eviction needs a cluster with an `actuator_token_secret`, and the Actuator's RBAC in `deploy/actuator/rbac.yaml` grants `create pods/eviction` and reads `poddisruptionbudgets` per namespace (re-apply it when upgrading from 0.42.0: without that read, nothing is evicted). An Actuator of 0.42.0 or older never reads `eviction` and fails an `Infeasible` resize, as before.

## Automation

A Sizing rule with `automate: true` ([Sizing policies](optimizer.md#sizing-policies)) is the Operator's standing approval for the containers it picks (ADR 0004): `/actuator/desired` then also lists, apart from the Approved Sizings, the newest Sizing of each such container on the token's cluster that is ready and changes something, and the Actuator applies it unasked, through the same pre-checks, canary and rollback. An Approved Sizing of the same container goes first. The churn rule: a change under 10% of what its pods ask now is ignored, an increase applies at once, and a decrease at most once a day per container (an increase beside a waiting decrease goes alone). A new one waits while that container's rollout is under way or it backs off after a Rollback, without a word; one the pre-checks skip (a VPA, a quota) is said once, in its Event and Actuation, until its reason changes, and what the Actuator holds stays held. Its Events say `(Automation, run N)`. A Sizing that leaves one resource alone, approved or not, keeps the value held for it.

Three Rollbacks of one Workload in 7 days end its Automation: the Hub lists none of its Sizings until the oldest of them is 7 days old, and the operator channel hears it once, with that date. To end it for good, remove `automate` from its rule. An Actuator of 0.40.0 or older never reads Automation's list, so it applies only approvals.

## Revert

The Operator's Revert, from the console's Automation page or `revert_sizing` on the Hub MCP server ([Reverting a Sizing](running-the-hub.md#reverting-a-sizing)), reaches the Actuator in `/actuator/desired`'s `reverts` until it reports it done. It puts every pod with the requests it holds for that container back to the template's, in place and at once (a request the template doesn't set stays), as a rollback does but with no backoff, and holds that container no more: its webhook leaves new pods alone and nothing catches up. A `SizingReverted` Event and a `reverted` Actuation say what went back to what; with nothing held, the Actuation says so. A paused Deployment's Revert waits for the pause to lift. An approval applied before stays reverted; a later approval applies, and resumes Automation of that container.

## Stopping it: pause, Hub down

A person in the client's cluster stops the Actuator on one Workload (a Deployment, StatefulSet, DaemonSet or Argo Rollout) with an annotation:

```bash
kubectl -n shop annotate deployment api squero-actuator/pause=true   # --overwrite ... =false, or remove it, to lift it
```

The Actuator reads it each minute: nothing is resized on that Workload (no approval, no Automation, no catch-up, a rollout stops where it is), and its webhook lets its new pods start from their template, as under the Kill switch. A rollback still happens, and nothing is reverted at once. An approval meanwhile waits, and applies once the pause is lifted if it is still current. To stop it everywhere, scale the Actuator to zero (the webhook fails open).

While the Hub doesn't answer, the Actuator keeps what it holds and changes nothing new (rollbacks and hand-backs go on). After 15 minutes it says so once, a `HubUnreachable` Warning Event on its ConfigMap in its own namespace (`kubectl -n squero-actuator get events`).
