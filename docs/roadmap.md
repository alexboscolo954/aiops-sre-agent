# Roadmap

The goal is one Hub that lets the Operator run SRE for several Contracts at once. It answers alerts, answers questions and runs checks, and it never lets one Contract's data reach another. From Phase 9 it also optimizes each Contract's resources: Sizings for every Workload, cost, horizontal scaling, nodes, spot and GPUs, applied under the Operator's Automation. HolmesGPT, OpenSRE and IncidentFox inspire the agent; ScaleOps (first) and Kubex inspire the optimizer. We take their ideas, not their code.

Terms are defined in [`CONTEXT.md`](../CONTEXT.md). The decisions behind the shape are in [ADR 0002](adr/0002-hub-and-relay.md) (Hub and Relay), [ADR 0003](adr/0003-contract-data-in-private-git.md) (Contract data in a private repo) and [ADR 0004](adr/0004-standing-approval-for-sizing.md) (an in-cluster Actuator applies Sizings under a standing approval).

## Where we start

| Today | Needed |
|---|---|
| `Settings` is global: one kube context, one namespace list, one Runbooks dir, one Slack webhook, one pair of tokens | Everything except Hub settings is set per Contract |
| `triages` and `recent` live in memory. Dedup is keyed by `groupKey` alone | Postgres, keyed by Contract. Two Contracts can send the same `groupKey` |
| `InMemorySaver` checkpointer. A restart loses pending approvals | Postgres checkpointer. Pending approvals survive a restart |
| `read_only(tool)` trusted the server's `readOnlyHint` | Done in 0.2: the Hub's own list decides read or write, and a server can only make a tool stricter |
| `replay_server` builds tools from our in-process servers | Replay also builds them from saved schema snapshots of vendor servers |
| Alerts only, Slack webhook only, API for approvals | Triage, Question and Check, with Slack and a web console |

## How every slice ships

A slice is one commit-sized change, about one working session (1 to 3 hours).

1. **Glossary first.** New terms go in `CONTEXT.md` before code. Add an ADR only when the decision is hard to reverse, would surprise a reader, and came from a real trade-off.
2. **Tests for every branch of new logic.** Mutation-check each new test: remove the logic, and the test must fail.
3. **An isolation test** for anything that stores, reads or sends Contract data. It uses the two demo Contracts and proves Contract A's data never reaches Contract B, whether in prompts, tools, storage or notifications.
4. **Rerun the real eval suite** when anything the model sees changes: the prompt, tool names, descriptions or schemas, or the Report schema. Commit the results under `evals/results/`. No Scenario may regress.
5. **Keep lint and the full suite green.** Update the README and config table.
6. **Write a one-line commit subject.** CI must be green before moving on.

**Where checks run.**
- **CI**, in the public repo: lint, unit and isolation tests, the kind demo integration and the deploy smoke test. These run on the two synthetic demo Contracts only.
- **Locally:** the real-LLM evals (they need the API key), and Contract Scenarios from the private contracts repo.

## Decisions

| Topic | Decision |
|---|---|
| Who works | One Operator. The Operator receives every Report and makes every Approval decision |
| Reaching a Contract | **Direct** (the Hub holds the credentials) or **Relay** (dials out from the client network) |
| Hub | Any machine you own, a VM or a laptop: docker compose with the Hub and Postgres |
| Operator interfaces | Your own Slack workspace, one channel per Contract, with approve buttons. Also a web console |
| Client delivery | Optional per Contract. A Client report goes when the Operator clicks Send, never with approval controls |
| Data policy | Set per Contract. Default: no restrictions |
| Integrations | Hybrid: vendor MCP servers where they're good, our own where they're missing |
| Contract config | YAML per Contract in one private repo, with SOPS secrets and an age key per Contract |
| Console | View and act. It shows config read-only and is reachable only over Tailscale |
| Investigations | Triage, then Question, then Check |
| Knowledge | Similar incidents and Teachings stay in their own Contract. Teachings need review. Shared knowledge is written by the Operator |
| Optimizer shape (2026-10-21) | The brain in the Hub (metrics aggregates, recommender, Sizing policies), the hands in the client cluster (an Actuator that pulls approved Sizings over the Relay). [ADR 0004](adr/0004-standing-approval-for-sizing.md) |
| Writes under Automation | Allowed, opt-in per Contract and per Workload, read-only by default, audited and reversible. Reflexes (OOM step-up, burst CPU, startup boost, auto-rollback) act unattended, capped and expiring |
| Metrics for Sizings | Each Contract's own Prometheus; the Hub keeps per-Workload aggregates in Postgres, never raw series. A bundled collector only where a cluster has none |
| Sizing policies | In the contracts repo (`contract.yaml`), validated by `aiops contracts validate`; the Actuator renders them in the cluster |
| Applying Sizings | In-place resize first (Kubernetes 1.33+); webhook plus PDB-safe eviction only behind a per-Contract flag. Never Git write-back to client repos |
| Actuator | Python, same image as the Hub (`aiops actuator`); revisit only if webhook latency shows up in tests |
| Scope | Everything both products do: Workloads, horizontal, node and Karpenter, spot, cloud billing, JVM, Spark and batch, GPU and LLM inference, and as many integrations as possible |
| Testing | kind, KWOK and fake metrics for everything; paid write sandboxes (Karpenter, spot, GPU) small, time-boxed and approved by the Operator per phase |
| Vendor trials | Only after our part of a phase is built, to compare; read the terms first |
| Console (2026-10-21) | A React single-page app for the whole console, served by the Hub, replacing the Jinja pages once each is rebuilt. Same Tailscale identity and approver cookie, same-origin JSON API, strict CSP, model-written text rendered as text (no raw HTML, no live links), built in the image's Docker build with a pinned toolchain, nothing loaded from a CDN |
| Test lab | A persistent kind lab on the Operator's Mac: Prometheus, kube-state-metrics and load generators (diurnal, spikes, leaks, OOMs) running continuously so real history builds up, plus synthetic backfill for weeks of data |
| Usage aggregates | Kept 90 days per Contract |
| Hub MCP server | The Operator only, over Tailscale. Reads, plus Approval decisions on Proposed actions and single Sizings, the kill switch, and pull requests to the contracts repo for Automation and policy changes, which the Operator merges. Every write is audited as made through MCP. The Investigation agent never gets these tools |

## Defaults you can veto

| Choice | Default | Why |
|---|---|---|
| Persistence | Postgres 17, `langgraph-checkpoint-postgres`, psycopg 3, numbered `.sql` migrations | One database for state, checkpoints and knowledge |
| Secrets | `sops -d` at load. The Hub holds age keys for Direct Contracts only | No new library. A Relay Contract's credentials never reach the Hub |
| Many clusters | One kubernetes server per Contract, with a `cluster` argument limited to that Contract's clusters | A Contract can have dozens of clusters, and one server per cluster would multiply the tool count |
| Slack | Web API over httpx; Socket Mode over `websockets` (1.2), not slack-bolt | No public Slack endpoint, and no framework for one socket and a few calls |
| Console stack | FastAPI + Jinja + HTMX, with no JS build, until Phase 9.5; then a React app (see Decisions) | The optimizer's charts outgrew server-rendered pages |
| Console login | Tailscale identity headers from `tailscale serve`, with the console on `127.0.0.1`, plus an Operator allowlist | No passwords to manage. `serve` strips a client's copy of the header, but anything else that can reach the port (local processes, other containers on the compose network) could send it |
| Jira | An issue is created only when the Operator clicks | Never write to a client's tracker unasked |
| Budget | Monthly per Contract. Warn at 80%. At 100%, refuse new Investigations but still notify | An alert is never silently dropped |
| Model | One Hub default, overridable per Contract | |
| Similar incidents | Postgres full-text search, merged with pgvector when `AIOPS_EMBEDDING_MODEL` is set (7.4) | Unset, no embedding calls |
| Kubernetes versions | Find out each Contract's before Phase 12; the kind matrix covers 1.33+ for in-place resize | Sets what Phase 12 can rely on |
| Sizing data and Data policy | Per-Workload aggregates count as tool output under each Contract's Data policy and 6.4 masking | They leave the client network |
| Automation granularity | Per Workload, Operator only, in the contracts repo | One clear audit trail |
| In-cluster state | CRDs with our own names and schemas, rendered by the Actuator | Validation and scale over ConfigMaps |
| Clouds and distributions | Follow the Contracts' stacks; manual unit prices for on-prem | No cloud bill on RKE2 |
| Node autoscalers | Recommendations first, NodePool patches later | Patches need write access to node config |
| Cost source | List prices first; billing exports where a client grants read access | Billing needs extra permissions |

## Phases

Phases 0 to 8 were about 36 slices; Phases 9 to 19 add about 65. Phase 3 (Relay) is now a hard prerequisite of Phase 12, because every write to a client cluster goes through the Actuator, and it comes earlier if a new Contract can be reached only through a Relay. Phases 9 to 19 are outlines: each is grilled just before it is built, like every phase before it.

### Phase 0: Foundation: many Contracts, durable state (5 slices)

**0.1 Contract config.** Done.
- A pydantic schema and a loader for a contracts directory (`src/aiops_agent/contracts.py`), with `aiops contracts validate <dir>`.
- A Contract file holds:
  - its id and name;
  - its clusters: name, namespaces, and a context with an optional kubeconfig file or secret, or `in_cluster`;
  - its integrations, as a list of entries. `kubernetes` (`enable_actions`, `max_replicas`), `prometheus` (`url`, `token_secret`) and `runbooks` are builtin entries, so Phase 4 needs no migration.
- These fields mirror today's `Settings`. Unknown keys fail, so each later field arrives in the slice that gives it behaviour, and existing files stay valid:
  - tool allowlist in YAML: 4.1, when vendor tools need it. Builtins keep their list in code;
  - notification targets: 1.1 (the client channel: 1.3);
  - Data policy: 6.4 (1.3 needed none: the Operator reviews each Client report);
  - model and budget: 2.4;
  - health probe: 2.5;
  - reach: 3.2;
  - vendor source: 4.1.
- Secrets sit in `secrets.sops.yaml` and are decrypted with the `sops` binary. The checker:
  - refuses plaintext files;
  - names a bad key without ever printing its value;
  - fails when two Contracts share an age recipient. It reads recipients from sops metadata, so it needs no key.
- Two synthetic demo Contracts live in `demo/contracts/`, each with its own test-only age key. The `two_contracts` fixture loads them for every later isolation test.

**0.2 Contract-scoped tools.** Done. Its last item, a Scenario where the Contract has two clusters and the alert's `cluster` label must pick one, is `two-clusters-alert-picks-one` (2026-10-20, passes on Haiku).
- Each Contract gets its own MCP server set. The kubernetes server takes a `cluster` argument limited to the Contract's clusters, with a namespace allowlist per cluster. Runbooks come from the Contract's directory plus Shared knowledge.
- **Part 1, done: the allowlist decides read or write.** Each builtin server declares its list in code (`ACCESS`), and `open_agent` requires it. A tool not on the list is hidden, and a server's annotation can only make a tool stricter. This closed a gap: before, a server that wrongly marked a write tool as read-only skipped approval. A server that leaves the marker out was already safe, because those tools are gated.
- *Done when:*
  - the isolation tests pass: A's agent sees only A's tools, naming B's cluster errors, and Runbook search never returns B's Runbooks;
  - a tool annotated read-only but allowlisted as `write` is gated;
  - a tool annotated as a write but allowlisted as `read` is still gated;
  - a tool not on the list is invisible.
- **Part 2, done.** `build_mcp(contract, settings)` builds one Contract's tools. Isolation tests live in `tests/test_isolation.py`. The kind demo has the `bank` namespace, and a kind-backed test shows demo-bank can't read demo-shop's namespace. Until 0.3, the API, `aiops triage` and `aiops mcp` turn the `AIOPS_*` variables into one Contract named `default`.

**0.3 Contract-scoped intake.** Done.
- `POST /contracts/{id}/alertmanager` with a webhook token per Contract. Dedup is keyed by (Contract, `groupKey`). This replaces `/alertmanager` and the global token.
- The token is stored as its SHA-256 in `contract.yaml` (`aiops contracts new-token`), so the in-cluster deploy needs no sops yet: the image gains sops in 0.5. The `AIOPS_*` cluster settings are gone; `serve`, `triage` and `mcp` refuse to start if one is still set.
- Known limit: `AIOPS_MAX_CONCURRENT_TRIAGES` is shared, so one Contract's alert storm can hold every slot. Revisit with per-Contract queues when it bites.
- *Done when:*
  - A's token can't post to B;
  - the same `groupKey` in A and B starts two Triages;
  - A's group resolving doesn't make B's Proposed actions Stale.

**0.4 Postgres state.** Done.
- Tables: Investigations (with a kind column), Proposed and Executed actions, the dedup seen-set, and the audit log. Use the LangGraph Postgres checkpointer.
- Store every tool call's args and the raw result (before the cap, after redaction) so slice 2.6 can turn it into a Scenario.
- Stale deadlines are stored in the database, and timers are re-armed at startup instead of sleeping in memory.
- Rename `Triage` in code to `Investigation` with a kind. Done (part a): the API is now `/investigations`, and each record has `kind: triage`.
- *Done when:*
  - a pending approval survives a Hub restart and can still be approved;
  - a deadline that passes while the Hub is down is made Stale at startup;
  - storage tests run against Postgres in CI.

**0.5 Hub deployment.** Done.
- `deploy/hub`: docker compose with the Hub, Postgres, Caddy and a backup job. Caddy serves TLS and passes only `POST /contracts/<id>/alertmanager` (bodies up to 1 MB); everything else is a 404 there.
- The API listens on `127.0.0.1` only, with `tailscale serve` in front. Never bind it to the Tailscale interface: any tailnet device could then connect directly and forge the identity header.
- The contracts repo reaches the VM through a read-only deploy key. `update-contracts.sh` validates every Contract in the image before restarting, and rolls the clone back if one is invalid.
- The image ships pinned `sops`, checksum-verified for amd64 and arm64.
- `make hub-smoke` in CI. CI has no model key, so instead of a Report it proves: the stack is healthy, both Contracts decrypt in the image, only the alert route is public, an alert is stored and fails the way it should without a cluster, a backup restores, and a bad update is refused.
- Not covered by CI: `tailscale serve`, real certificates, the deploy-key clone, the arm64 image.

### Phase 1: Slack (4 slices)

**1.1 Slack threads.** Done.
- Each Contract has its own channel. Each Investigation is one thread that shows its status, then the Report. This replaces `slack_webhook_url`.
- Posting needs only the Web API (`chat.postMessage`, `chat.update`) with a bot token, so 1.1 uses httpx and no Slack library. Socket Mode, which receives events, moves to 1.2 with the buttons; decide there between keeping this poster and slack-bolt's client.
- *Done when:* a fake Slack client shows A's Investigations never post to B's channel.

**1.2 Approve and reject buttons.** Done.
- The buttons use the same decision path as the API (`settle`: claim, record, resume). A reject reason is entered in a modal, and the pause is claimed only on submit, so a cancelled modal decides nothing. Only the Operator's Slack user id (`AIOPS_SLACK_OPERATOR_ID`) is accepted, and only in the Investigation's own channel.
- The buttons sit on the thread's parent, not on a reply: the parent is re-rendered on every status change, so they disappear on any decision or Stale with no extra state. Each button carries its pause's deadline, so a click from an earlier pause can't decide a later one.
- Socket Mode is a small loop over `websockets` (ack each envelope, reconnect on `disconnect`); the httpx poster stays, and slack-bolt was not needed.
- *Done when:*
  - a click from anyone but the Operator is refused;
  - a second click is refused;
  - going Stale updates the message.

**1.3 Optional client delivery.** Done.
- Per Contract, `slack.client_channel` (a Slack Connect channel). A finished Report gets a **Send to client** button in the Operator's thread, and the Client report goes once, as plain text with no controls. It holds the summary, root cause, severity, affected and Recommendations. Evidence, Executed actions, the Runbook and ids never go.
- Deviations: sent on the Operator's click, not automatically, so AI output is read before a client sees it. No Data policy field: the click is the review, and masking stays in 6.4.
- A crash between claiming the send and posting it leaves it marked sent but unsent (a `ponytail:` note in `api.py`).
- *Done when:* delivery is off by default, and the client message never contains buttons.

**1.4 Questions.** Done.
- **Part a, done:** the agent answers a Question with an Answer (read tools only; write tools are hidden, not gated), a follow-up is a new message on the same thread, and the eval runner takes Question Scenarios. Two pass, with budgets set from the runs (see the README's Evals).
- **Part b, done:** an @mention in a Contract's operator channel starts a Question, and the Answer goes in the thread. A mention in the thread continues the same Investigation. Decided: only messages that @mention the bot (it never reads other channel traffic), Questions only read, and a Question always ends with an Answer.
- One Investigation per Slack thread (a unique index), so a redelivered mention can't start two. A follow-up claims a finished Question only with a newer mention, so two never run at once. Mentions from anyone but the Operator, in a client channel, or in a Triage thread are refused privately. A Question's thread root is the Operator's message, so the Hub only replies there.
- Widen Scenario and Expectation in the glossary and in the eval runner. A Scenario can start from a Question, and its Expectation checks the Answer's keywords and Evidence instead of a Category.
- *Done when:*
  - two Question Scenarios pass;
  - a Question in A's channel can't reach B's clusters.

### Phase 2: Web console, Tailscale only (6 slices)

**2.1 Skeleton and login.** Done.
- Login trusts the identity headers that `tailscale serve` sets. That is safe only because the console listens on `127.0.0.1` (slice 0.5).
- `/console` lists the Contracts for a login in `AIOPS_CONSOLE_OPERATORS`; anything else gets a 403, and with no operators set the console isn't mounted (404), so the in-cluster deploy stays closed. Jinja autoescapes everything, and pages send a CSP and `frame-ancestors 'none'`. `hub-smoke` proves `/console` is a 404 through Caddy even with a forged header, and renders on `127.0.0.1` from the image.
- Not covered by CI: a real `tailscale serve`.
- *Done when:* a request without the Operator's Tailscale identity is refused.

**2.2 Investigations.** Done.
- `/console` lists Investigations, filtered by Contract; each one's page shows the Report or Answer, the decisions and every tool call (args, and the redacted raw result).
- Approve and reject are plain forms (no HTMX needed), through the same decision path as the API and Slack. Each form names its pause (the deadline), like the buttons.
- **Acting needs more than the identity header.** `serve` only strips a *client's* copy of the header; anything else that reaches the Hub's port (local processes, the other containers on the compose network) could send it, and neither a network split nor tailscaled's `whois` stops that behind Docker's published port. So the header alone opens nothing but the token page (since 2.3: a forged header could read client data from tool results), and every page and every POST also needs the approver token (pasted once per browser, kept as an HMAC of it in a Secure, HttpOnly, SameSite=Strict cookie) and must be same-origin (`Sec-Fetch-Site`, or `Origin` against `Host`), which also stops CSRF.

**2.3 Ask a Question** from a form. Done.
- A form on `/console` (Contract and question) and **Follow up** on a Question's page, through the same Question path as Slack (`start_question`, `follow_up`). Same rules as acting: identity, the token cookie, same origin. The page reloads itself while the Question runs (a meta refresh, no script). A console Question has no Slack thread.

**2.4 Cost.** Done.
- **Part a, done:** every model call's tokens are recorded as it happens (a `wrap_model_call` middleware, so a resume never counts earlier Runs and a failed Run still counts), priced per call from `AIOPS_MODEL_PRICES` in USD, including Haiku's long-context tier. The console shows tokens and cost per Investigation and spend per Contract this month. Contracts gain `model:` (through the Hub's gateway) and `monthly_budget_usd:`; a budget needs its model priced at startup.
- **Part b, done:** budgets apply only where a new Run starts (alerts, Questions, follow-ups), never on a resume. At 100% the alert is still recorded (so repeats stay duplicates) and fails with the spend and budget, with no model call; Slack still hears of it. The 80% and 100% notices post once per Contract per month (`budget_notices`). Runs starting together can overshoot (a `ponytail:` note).
- *Done when:* at 100% budget, a new alert still notifies the Operator, and its Failed investigation names the budget as the reason.

**2.5 Health.** Done.
- Shows Relay connections, integration health probes, and the last successful Investigation per Contract. Also shows the effective config read-only, with secrets masked.
- `/console/health` runs one cheap read per integration through the Contract's own tools (`agent.probes`) on each load, with a 10 s limit each. Errors are redacted; check results are never shown. Config shows secret names and whether each decrypted, never values; Hub settings come out of pydantic with every `SecretStr` masked.
- Deviations: no `health probe` field in `contract.yaml` (the builtin probes are enough until a vendor integration needs its own, in 4.1), and Relay connections wait for Phase 3.

**2.6 Save as Scenario.** Done.
- Each Investigation stores its input at intake (migration 0008). The download (`/console/investigations/<id>/scenario.yaml`, identity plus token) builds the Scenario from the recorded tool calls, leaving out Runbook tools (replay reads the files). A saved Scenario names its `clusters` and `integrations`, and the replay builds exactly those with placeholder config, so it offers the tools production did; older Scenarios build byte-identical tools (fingerprinted). `--runbooks` repeats for shared plus the Contract's own.
- Turns a finished Investigation into a Scenario YAML for the Operator to download: the alert or Question, the recorded tool results, and a draft Expectation to edit. The Operator commits it to the contracts repo. The Hub never gets push access to a repo holding every Contract's secrets. The eval runner takes `--scenarios <contracts-repo>/<contract>/scenarios`.
- *Done when:* a saved Scenario replays to the same tool calls.

### Phase 3: Relay (4 slices)

**3.1 Reversed MCP connection.**
- The Relay dials the Hub over WSS and runs the MCP server over that socket. The Hub runs a `ClientSession` on its end. Both SDK sides take raw streams, so this is an adapter, not a new protocol. Each Relay token is bound to one Contract.
- *Done when:*
  - it works over in-memory streams and over a real websocket;
  - A's Relay token can't serve B.

**3.2 Relay process.**
- `aiops relay` ships in the same image, with manifests for the client cluster. Credentials come from a Secret in the client cluster. The Hub hides any tool the Relay offers that isn't on the Contract's allowlist.

**3.3 Hub side.**
- A registry of connected Relays, reconnect with backoff, and a timeout per call.
- *Done when:* killing the Relay mid-Run ends in a Failed investigation ("Relay offline") within the timeout, not a hang.

**3.4 Alert forwarding.**
- The Relay accepts the in-cluster Alertmanager webhook and forwards it over the same connection.
- *Done when:* on a kind cluster with no inbound route from the Hub, a full Triage through the Relay passes the demo eval.

### Phase 4: Integration framework and first integrations (4 slices)

**4.1 Vendor sources.** Done.
- Vendor servers run as pinned stdio subprocesses or remote HTTP servers, behind the same allowlist enforcement as slice 0.2.
- *Done when:* the slice 0.2 allowlist tests also pass against a vendor subprocess.
- A Contract integration `{name, vendor, env, env_secrets, tools, probe}`: `vendor` names an entry in the Hub's registry (`servers/vendors.py`), so the command never comes from the contracts repo (the ADR 0002 reasoning for kubeconfig exec plugins); each binary ships in the image, pinned. `tools` is the Hub's read/write list for it (the YAML allowlist pencilled in for 4.1). The 0.2 allowlist tests run against an in-process server and a real vendor subprocess.
- The subprocess gets MCP's safe default environment plus its own `env` and secrets, never the Hub's (tested with the demo Contracts). A Contract may set only the variables its vendor's registry entry lists (`LD_PRELOAD`, `PATH`, `NODE_OPTIONS` and the like would run code), and registry commands are absolute paths. One process per tool call, none outliving a Run; a handshake timeout drops a vendor that never answers, and the Run goes on. Health: a `probe` tool (must be listed `read`), or by default the vendor starts and offers every listed tool.
- Deviations: stdio only. Remote HTTP waits for 4.4, where the Jira choice (Atlassian's remote MCP or a builtin) decides whether it's needed. Unannotated vendor tools stay gated (Grafana annotates its reads). Replaying a Scenario with a vendor refuses until 4.2's snapshots.

**4.2 Schema snapshots.** Done.
- `aiops integrations snapshot <name>` saves a pinned vendor server's tool schemas into this repo. They hold schemas only, no data. Replay builds tools from the snapshot.
- *Done when:* a test diffs the snapshot against the real pinned server, so a vendor renaming a tool fails a test instead of silently breaking an eval.
- As built: `src/aiops_agent/servers/snapshots/<vendor>.json` keeps each tool's name, title, description, input and output schemas and annotations (what the model and the approval gate see), sorted, so a diff reads well. The vendor starts with no Contract and no variables at all: a vendor that writes its config into a description has none to write into a file this public repo commits. `--check` prints the diff and fails. A saved Scenario lists a vendor as `{name, vendor, tools}` (never its env, secrets or probe), and replay offers its tools from the snapshot without starting it.
- Deviations: the registry is still empty, so the diff test runs against the fixture vendor (`tests/fixtures/snapshots/fixture.json`, checked against the live fixture on every CI run); for a real vendor the check is `aiops integrations snapshot <name> --check`, run where its pinned binary is (4.3). A vendor saved by name only, in a draft from before 4.2, still refuses to replay. A Scenario from a Contract with no clusters now replays with none, instead of a made-up `kind` one.

**4.3 Grafana stack** through `mcp-grafana`. Done: parts a (registry, pinned binary, snapshot, CI check), b (the kind demo's LGTM stack, the two Scenarios, the prompt guide), c (deep links in Reports) and d (Grafana Alerting as an alert source).
- Part d, as built: `POST /contracts/<id>/grafana` (public through Caddy, the Contract's webhook token as Grafana's Bearer credentials). Grafana's webhook is Alertmanager's payload plus each rule's query values (`valueString`), kept as the `query_values` annotation; the rendered `title` and `message` are dropped. Fingerprints and resolved notifications are Alertmanager's, so dedup and stale-on-resolve need nothing new; group keys get a `grafana:` prefix, since an Alertmanager grouping by the same labels sends the same key and one source resolving must not stale the other's actions. Firing and resolved payloads were captured from Grafana 13.2 on the kind demo and are the test fixtures; hub-smoke posts one through Caddy. Not handled specially: Grafana's DatasourceNoData and DatasourceError alerts arrive as ordinary alerts under those names (not captured yet).
- Part c, as built: `Evidence.link`, shown after the finding in Slack and the console, never in the Client report. A registry entry names its link tools (Grafana: `generate_deeplink`, whose result is only a URL built from `GRAFANA_URL`); a middleware records what they return, where they ran, and the Hub drops any Evidence link no link tool returned exactly. A URL in a log line, a span attribute or a trace result's `grafanaUrl` is client data or another tool's, so it never shows. Scenarios can expect `links: N`; results count dropped links. On Haiku, the slow-trace Scenario first cited a trace result's link and failed; the guide now says other links are dropped, and both Grafana Scenarios pass with a kept link.
- Registry entry plus `snapshots/grafana.json`; hub-smoke runs `aiops integrations snapshot grafana --check` inside the image, where the pinned binary is, so a renamed Grafana tool fails CI.
- Checked (v2.0.2): it lists all its tools with no variables, toolsets are command flags, `--disable-write` leaves only tools that claim read-only, and Tempo is a static toolset (`tempo`). It reports usage statistics to Grafana Labs by default, so the registry passes `--usage-stats=disabled`. The original note: a snapshot is taken with no variables, so mcp-grafana must list its tools without `GRAFANA_URL`, and its toolset choice must live in the registry's command args, not in env; otherwise the snapshot won't match what a Contract's Run offers.
- Covers Prometheus/Mimir and Loki (stats and patterns before raw logs, an IncidentFox idea), plus Tempo traces, Pyroscope and dashboard deep links in Reports. Grafana Alerting becomes a second alert source, normalized into an Alert group.
- The kind demo gains a Grafana LGTM stack.
- Part b, as built: `make lgtm` (not in CI: replay needs no Grafana) runs `grafana/otel-lgtm` in namespace `observability`, with Loki's pattern ingester on, chunks flushed within minutes so log stats see them, and no WAL (nothing persists; a nearly full disk made the WAL throttle every write). `demo/telemetry.py` (standard library, OTLP/HTTP JSON) runs as `payments` and `storefront` in namespace `shop`, apart from `demo` so the Kubernetes Scenarios' recordings don't change. `evals/record_grafana.py` records through the Hub's real path (`build_mcp`), one result per tool matched on its datasource (a trace on its id too). A vendor's registry entry may carry a prompt guide, added only when it's offered. Both Scenarios pass on Haiku, calling patterns and traces first.
- Deviations in part b: deep links moved to their own part (c), since they need an `Evidence` field and a check that a link came from a tool result, which would change every Scenario's output. Grafana Alerting moved to part d. The Scenarios were recorded by a script rather than from a live Investigation, as `build_scenarios.py` records the Kubernetes ones.
- Part b, checked first: the snapshot was taken with Grafana unreachable, and mcp-grafana reads `/api/frontend/settings` at startup. Captured with the registry flags and `GRAFANA_URL` at the demo Grafana: identical to `grafana.json`, so the snapshot taken with no Grafana holds.
- *Done when:* two new recorded Scenarios pass, one with the root cause in log patterns and one in traces.

**4.4 Jira.** Done: part a (search as Evidence) and part b (the "Create Jira issue" button).
- Part b, as built: a finished Report gets the button on its Slack parent and its console page when the Contract has Jira. `file_jira` is the one path for both: claim (`jira_at`, migration 0009), create with the Contract's own Basic auth on the request alone (the HTTP client is shared with Slack), record the key, update the Slack thread. A refusal (a 4xx, with Jira's `errors` shown, or a connection that never opened) frees the claim. A timeout, a 5xx, or a 201 without a key of the project keeps it, since Jira may have created the issue, and both surfaces say to check the project; clearing `jira_at` in the database is the only reset. Empty sections are left out (ADF refuses an empty list or text); the documents were checked once against Atlassian's published ADF schema. *Decided (the Operator, 2026-10-17):* the issue holds the full Report, Evidence and executed actions included, redacted, built as ADF text nodes (markup from tool output stays inert; only kept Evidence links are links). The summary is one line of at most 255 characters; `issue_type` (default Task) is per Contract. Creating is never an agent tool. Tested against a fake Jira; no live Jira yet.
- A "Create Jira issue" button in Slack and the console puts the Report into the Contract's project. Searching past issues becomes an Evidence source.
- *Decided (the Operator, 2026-10-17):* a small builtin server with an API token, not Atlassian's remote MCP. Any Jira Cloud user can make a token, with no client admin step (the remote MCP's API-token access must be enabled by each client's org admin), it fits the Contract's static SOPS secrets, and it needs no remote-HTTP vendor transport.
- Part a, as built: integration `{name: jira, url (https), email, token_secret, project}`; tools `jira_search_issues` and `jira_get_issue`, read-only, on REST v3 (`POST /rest/api/3/search/jql`). The server writes the JQL (`project = "<KEY>" AND text ~ "<words>"`), the model passes words only (non-word characters become spaces); `get_issue` checks the project of the issue that comes back. A prompt guide is added only when the Contract has Jira; health searches one day; Save as Scenario and replay handle it. Tested against synthetic responses in the documented shapes; no live Jira yet.

### Phase 5: Clouds, read-only (3 slices)

**5.1 Azure, 5.2 AWS, 5.3 GCP**, each through its official MCP server.
- 5.1 Azure done: part a (registry, pinned binary, snapshot, CI check) and part b (a Scenario recorded from a sandbox subscription).
- 5.1b, as built: `evals/record_azure.py` runs in the Hub image (the pinned binary, `fixed_env` as in production) with a Reader service principal, and records `azure-appservice-bad-startup`: a working Linux web app whose startup command was changed to one that fails. Each tool keeps one result, matched on the resource name only. The free F1 tier was dropped: a crash-looping container used up its daily CPU quota within minutes and the app went to `QuotaExceeded`, a second cause. Basic B1 for under an hour costs cents of trial credit. A new subscription needs `Microsoft.Web`, `Microsoft.Insights` and `Microsoft.ResourceHealth` registered. Reader can't read deployments (`appservice_webapp_deployment_get` is Unauthorized), and the diagnostics detectors returned empty tables, so neither is offered. The scrub (fixed fakes for ids and names, `AIOPS_SCRUB` for the caller's identity, `claims` and `httpRequest` dropped, nothing written if a real value survives) has a test. Passes on Haiku in 4 calls.
- 5.1a, as built: `azmcp` 3.0.0 from npm's `@azure/mcp-linux-<arch>` package, sha512-verified, at `/opt/azmcp/azmcp`. `--read-only --disable-proxy-tools` and an explicit `--tool` list of 62 (not `--namespace`, which can't drop single tools): app settings and Cosmos DB documents were offered by the read-only namespaces. A registry entry can now fix variables over everything (`fixed_env`, applied to runs and snapshots alike) and mark credentials as `env_secrets`-only (`secret_env`). Azure's: telemetry off, `AZURE_TOKEN_CREDENTIALS=EnvironmentCredential` (only the Contract's service principal), `HOME=/nonexistent` (no host `~/.azure`), the .NET bundle extracted to `/tmp` (the Hub's root is read-only) and invariant globalization (the slim image has no ICU). The Contract sets only the tenant, client and subscription ids, and the secret through `env_secrets`. hub-smoke checks both vendors' snapshots inside the image, read-only. In the image (read-only root, tmpfs `/tmp`) a real tool call reaches Entra with the Contract's service principal only: the process starts in about 1 s, a call takes 2.6 to 4.7 s with the sign-in, the unpacked bundle is 6.7 MB of tmpfs, and two cold starts at once don't clash. One process per call is fine for now; keep one per Run if Azure Runs feel slow. Version 3.0.0 was 5 days old: the 2.x line is the previous major, and its snapshot would churn at the next upgrade.
- 5.2 AWS done: part a (a builtin, live check in the image) and part b (a Scenario recorded from the sandbox account).
- 5.2b, as built: `evals/record_aws.py` records `aws-lambda-timeout-cut` in the Hub image. It's a Lambda function with inline code whose timeout was cut below its run time, plus an Errors alarm. The sandbox is on AWS's Free plan: its AWS-managed organization denies Lambda and alarm writes outside us-east-2, so it ran there, and the recording names us-east-1, as a replayed aws Contract does. Always-free usage only, and everything was deleted after recording. The scrub masks every access key id: CloudTrail names session keys, and an id encodes its account. Passes on Haiku in 5 calls.
- 5.2a, as built: a builtin like Jira, not AWS's official MCP servers (the Operator's choice, against this phase's "official MCP server" plan). awslabs' `cloudwatch-mcp-server` 0.3.1 annotates none of its 19 tools, so every call would need approval, and it installs 249 MB (scipy, statsmodels, pandas). The remote AWS MCP Server (GA 2026-05) offers no `call_aws`, even signed in: its data path is `run_script`, which claims destructive. The builtin signs with SigV4 from the standard library (checked against botocore's signatures) over the JSON protocols of CloudWatch (1.0), Logs and CloudTrail (1.1). Six read tools, the Contract's regions only (the first is the default), errors with AWS's reason and never the signature. The Contract names an IAM user's key (`AKIA...`; a temporary `ASIA...` key would expire) and its regions. The health check reads alarms. The image is unchanged.
- 5.3 GCP done: part a (registry entry, snapshot, live check in the image) and part b (a Scenario recorded from the sandbox project).
- 5.3b, as built: `evals/record_gcp.py` records `gcp-cloudrun-bad-timeout` in the Hub image. It's a Cloud Run service whose new revision set a 1 ms upstream timeout, deployed from Docker Hub's `python:3.12-slim` with the server inline in its args: no build, no registry. Billing was linked only while recording, with a $1 budget alert. It cost nothing (Cloud Run's free tier), and the service was deleted and billing unlinked after. The two recorders share `evals/scrub.py`; request logs keep their status, and drop only IPs and user agents. Google's `query_range` fails with an empty message unless `location` is "global", and Cloud Run's PromQL needs a `monitored_resource` matcher; the guide says both. Passes on Haiku in 2 calls.
- 5.3a, as built: Google's remote MCP servers (Logging, Monitoring, Trace), not the local `@google-cloud/observability-mcp`. That one loads `googleapis` (194 MB) at runtime, which with Node would add about 350 MB to the image, and none of its tools claims read-only, so every call would need approval. The remote servers' 17 tools all claim read-only, and `tools/list` needs no auth, so the snapshot and its check work as for the pinned vendors. A registry entry is now a command or `urls`, merged into one server with one auth. `GoogleKey` signs a JWT with the key (RFC 7523, `cryptography`, now a direct dependency) and trades it at the pinned token URL for a read-only-scoped token, reused until a minute before it expires. Narrow scopes were tested against all three servers. A registry entry can require variables with a form (`required_env`: the project id is checked at load, since it goes in the guide) and name a default health probe, formatted with the Contract's variables. Scenarios now carry those required plain variables, so a gcp Scenario's guide names its project. A docs summary listed `roles/monitoring.admin` for Monitoring's server; viewer roles plus `roles/mcp.toolUser` read fine. Google answers a refused call (no permission, billing off) with HTTP 4xx around a JSON-RPC result that says why; the Hub's transport passes it on as 200, so the health page and the model see the reason. `list_timeseries` and `query_range` need billing on the project; logs and traces don't. The image grew by 1 MB.
- Each integration gets a documented read-only role (Reader, ReadOnlyAccess, Viewer), an allowlist, a schema snapshot, and one Scenario recorded from a sandbox account. Examples: a node pool at max, database storage full, a quota hit.
- Recording needs a sandbox account per cloud, which costs a little money.

### Phase 6: Investigation quality (4 slices)

**6.1 What changed.** Part a done: `kubernetes_recent_changes` (rollouts with their diffs, Helm chart labels; release Secrets stay unreadable) and the `dependency-bad-rollout` Scenario. Part b done: ArgoCD Applications and Flux Kustomizations and HelmReleases from a cluster's `gitops_namespaces`, shown only when they deploy wholly into the Contract's namespaces, with an opt-in RBAC file (`deploy/gitops/rbac-gitops.yaml`); tested against stand-in CRDs on kind, not the real controllers. Part c done: each cloud's guide names its activity or audit log when the Contract lists that tool. 6.1 is done.
- One timeline of rollouts, Helm releases, ArgoCD/Flux syncs and cloud activity logs before the alert.
- *Done when:* Scenarios pass where the cause is a change to a different resource.

**6.2 Large output.**
- Select fields and filter JSON at the server. Oversized results go to storage behind a `read_more` tool instead of being cut (a HolmesGPT idea).
- Done: an oversized result stays, redacted, in the Investigation's checkpointed state, and the Hub's `read_more` pages it, greps it, or picks fields of its JSON records. The filter is the Hub's, not each server's, so vendor MCP servers get it too. Scenario `gcp-who-deployed`: the answer is only past the cap.

**6.3 Alert correlation within a Contract.**
- A new Alert group that overlaps an open Investigation in time and topology joins it instead of starting a Triage. This needs a new glossary term, decided in a grilling round at slice time.
- Part a done: the term is Related alert group (a grilling round, 2026-10-19). It joins an open Triage when they share a match label and no scope label differs, within 30 minutes; it is posted in the thread and costs no investigation.
- Part b done: a "Triage separately" button on the related group's post starts its own Triage, once, within the budget; the two groups never join again.

**6.4 Masking.**
- Identifiers are replaced with stable placeholders before the LLM call and restored in the Report (an OpenSRE idea). Built when the first Contract's Data policy requires it.
- Grilled 2026-10-23 (all recommended), built ahead of a Contract that needs it, off by default: `data_policy.mask` lists terms (whole words, any case, a domain covering its subdomains) and masks emails and IPs unless turned off; Kubernetes names only when a term names them. One model-call middleware masks each request on the wire and unmasks the reply, tool-call arguments and the structured result included, so state, tool calls and Reports stay plaintext; it covers Triage, Questions, Checks and the Teaching drafter, and the Report embeddings send masked text. Placeholders are an HMAC with the Contract's own `mask-key` secret, so stable within a Contract and different across them. Values are restored everywhere but at the provider. The same middleware redacts secrets for every Contract, closing a gap for alert labels and Questions. The console counts what each Investigation masked.
- *Done when:* a fake model sees no listed term, email, IP or secret from a Triage, a Question, a Check, the Teaching drafter or an embedding, while tools, stored rows and the Report hold the real values; the same value masks differently in the two demo Contracts; a masked copy of a Scenario whose clue is a host passes on Haiku.
- Built 2026-10-23 as grilled; `dependency-bad-rollout-masked` passed on Haiku (run 1, 10 calls), its Evidence restored to `inventory.orders`, though its root cause shortened one placeholder to `<host>`, which can't be restored; a masking Contract's system prompt now says to copy placeholders whole, and run 2 passed (10 calls) with every one restored. Changed from the grilling: a placeholder hashes the value only, not its kind, which its prefix already says; a value written in two casings in one request comes back as first written; tool messages' artifacts are masked too, though the providers we use never send them; a masked term counts as one of the Contract's names for the Shared knowledge check; both demo Contracts mask (`shop.example`, `bank.example`) with their own `mask-key`.
- Checked live 2026-10-24 on the Mac Hub (v0.7.0): demo-shop masks its kind node's name, emails and IPs with its own random `mask-key`; a Triage of `lab/leaky` on Haiku masked 1 IP and 1 name (the console says so), and its Slack Report held only real values.

### Phase 7: Knowledge (4 slices)

**7.1 Similar incidents.**
- Full-text search over the same Contract's past Reports.
- *Done when:*
  - a Scenario passes where a past Report holds the decisive hint;
  - the isolation test passes.
- Done (2026-10-19): the `incidents` integration (`incidents_search`, `incidents_read`), Postgres full-text search over the Contract's own finished Triage Reports. A Triage searches once before its Report. Scenario `similar-incident-batch-size` passes on Haiku.

**7.2 Shared knowledge.**
- `shared/` in the contracts repo, mounted read-only for every Contract.
- *Done when:* tests show the agent has no write path to it.
- Done (2026-10-19): it was already `shared/runbooks/`, mounted read-only. Tests now prove no write path (read-only tools, no file paths, Runbooks by name, read-only mounts), and loading refuses a shared file that names a Contract.

**7.3 Teachings.**
- The agent proposes Teachings after an Investigation, or from the Operator's thumbs up/down and correction. Each is checked against existing Teachings for duplicates and contradictions, then goes to a review queue in Slack and the console.
- Grilled 2026-10-19: proposed only from a signal (a 👎 with a correction, or a rejected Proposed action's typed reason), never automatically after every Triage, which would mostly restate the Report that Similar incidents already finds. Part a: feedback, drafting, review queue. Part b: Teachings in the prompts, eval support, a Scenario. Part a done 2026-10-20 (`f702f4f`). Part b: approved Teachings in Triage and Question prompts, Scenario `teachings:`, Scenario `teaching-restores-from-secret`.
- *Done when:*
  - an unapproved Teaching never reaches a prompt;
  - A's Teachings never reach B.

**7.4 Embeddings** (pgvector), only if 7.1's evals show misses.
- Built on the Operator's call (2026-10-20): no eval showed a miss, and Scenarios replay recorded searches, so none can. Grilled: OpenRouter embeddings (`openai/text-embedding-3-small`, 512 dimensions); hybrid with full-text search (reciprocal rank fusion); a Contract opts out with `embeddings: false`, and embedding tokens count in its usage; embedded when a Triage Report finishes, `aiops incidents embed` for the rest.
- *Done when:* a store test finds by meaning a past Report that full-text search misses; the isolation test passes.

### Phase 8: Checks (2 slices)

**8.1 Scheduled Checks.**
- Per Contract, a cron schedule and a check prompt in YAML. A passing Check is recorded quietly. A failing one produces a Report and notifies the Operator. The schedule lives in Postgres, so a restart never fires a Check twice.
- Grilled 2026-10-20 (all recommended): a CheckResult (passed, summary, Evidence, a Report when failed); 5-field cron via `cronsim`, a per-Check time zone, at most every 15 minutes; missed fire times run once; an Open failure keeps one thread (*still failing*, *recovered*); Proposed actions as in a Triage; skipped at 100% of the budget. Part a: config, schedule, runner, Slack and console. Part b: Scenario support and two Scenarios. Both built 2026-10-20; the two Scenarios pass on Haiku.

**8.2 Deploy verification.**
- A rollout or ArgoCD sync starts a Check of the new revision after a set delay.
- Grilled 2026-10-20 (all recommended): poll the Contract's `recent_changes` every 2 minutes; opt-in `deploy_checks:` with a delay; a Hub-written prompt (only identities: object and revision) asking about the namespace too; one Run per namespace for deploys close together (capped at twice the delay); the first poll is the baseline; quiet on pass, a thread on failure, no Open failure. Built 2026-10-20. The live check showed the model can't tell what was failing before a deploy, so the Hub's poll records it and the prompt names it (the Operator chose that over a prompt-only fix). Scenarios `deploy-inventory-breaks-orders` (must fail) and `deploy-unrelated-next-to-crashloop` (must pass) pass on Haiku, and so does the live check.

### Phase 9: Read-only Sizings (6 slices)

Touches nothing in client clusters. Sizings come from each Direct Contract's Prometheus.

**9.1 Metric contract and Workloads.**
- The Prometheus queries a Sizing needs (container CPU and memory usage, requests, limits, OOM kills, throttling), checked per Contract; Workloads found through pod owners (ReplicaSet to Deployment, Jobs, StatefulSets, DaemonSets, Rollouts, ownerless pods).
- Grilled 2026-10-21: owners from kube-state-metrics, the Kubernetes API for pods it misses; a cluster's own Prometheus URL and token and label matchers, else the integration's; memory is the working set; the lab runs kube-prometheus-stack. Part a (code, fake Prometheus, `aiops sizing usage`) built 2026-10-21; part b, the persistent kind lab (`make lab`: kube-prometheus-stack and nine Workload shapes in namespace `lab`), built 2026-10-21 and read by the Mac Hub's image. Synthetic backfill of weeks of history comes with 9.2, which needs it. The agent's `prometheus` tools move to per-cluster URLs in 9.6.
- *Done when:* a fake Prometheus in the style of `fake_cluster` (CI has no kubeconfig) yields the right Workloads and usage for flat, diurnal, spike, slow-leak and OOM series.

**9.2 Recommender.**
- Percentile, window, headroom, minimum and maximum, change threshold and a node-capacity cap, per container, CPU and memory separately.
- Grilled 2026-10-21 (all recommended): CPU p95 + 15% and memory peak + 20%; recent usage counts more (24 h half-life, CPU only: a maximum can't decay); limits kept, conflicts flagged; 24 hours before a first Sizing. Added from review: CPU is never lowered while throttled over 10%, memory never after an OOM kill. Built 2026-10-21 (`aiops sizing show`). Moved out: the node-capacity cap goes to 9.3's per-policy maximum and Phase 15 (the read-only RBAC can't list nodes, and node series on a shared store without labels would cross Contracts); synthetic backfill waits for the seasonality work in Phase 14. Checked on kind 2026-10-23 00:20 UTC, after the first 24 hours: `api` (1000m and 1Gi requested) was sized 116m and 92Mi against a real p95 of 100m and a peak of 76Mi, so within its 15% and 20% headroom; `throttled` CPU and `leaky` memory went up to their limits with the risk listed.
- *Done when:* every rule has a test that fails when the rule is removed, and a 4x over-requested kind Workload gets a Sizing within headroom of its real p95.

**9.3 Sizing policies.**
- Built-in policies (production, batch, high availability) and overrides in `contract.yaml`, validated by `aiops contracts validate`.
- Grilled 2026-10-22 (all recommended): production stays 9.2; high-availability p99 + 30%, memory + 35%, 14 d window, 72 h half-life and history, floors 50m and 64 MiB; batch p90 + 10%, memory + 15%, 14 d. A policy owns window, percentile, half-life, headroom, floors, an optional max (a capped Sizing is listed as risk) and the threshold; the holds are not settings; limits only `keep` until Phase 12. Your own policies name a built-in `base:`, and built-in names can't be reused (a standing approval names a policy). Rules on cluster, namespace, kind, name and container (globs on namespace and name), first match wins, then Jobs and CronJobs get batch, then the default; `off` excludes. `sizing show` names the policy and a short history. Built 2026-10-22; `--window` left `sizing show`. Changed from the grilling: each window the Contract's policies can reach is read in full, not the longest once and trimmed, because OOM kills, throttling and requests are read over the whole window (found in review).
- *Done when:* every setting, rule and bound has a test that fails when it is removed, and on the lab `report` is batch with no rule, `db` high-availability and `agent` a Contract's own policy through rules, `idle` excluded and the rest production (checked 2026-10-22, all still learning).

**9.4 Waste and risk.**
- Per Workload: waste (requests above the Sizing) and risk (OOM kills, throttling, requests below the Sizing), stored in Postgres per Contract.
- Grilled 2026-10-22 (all recommended): a row per container per run (policy, state, current and Sizing, average pods, waste, risks), learning and excluded included; the Hub's scheduler runs each Contract with a Prometheus hourly, plus `aiops sizing refresh`; waste is the request above the Sizing times the average pods; risks are `{kind, text}` (oom_killed, throttled, under_requested, limit_below_need, capped_by_policy, request_unset); kept hourly 14 days, then the last of each day for 400; per-cluster status, so a failed cluster stays at its last good run; `aiops sizing waste` ranks Workloads (a core weighs 4 GiB until Phase 10's prices). Built 2026-10-22. Changed from the grilling: a run is due when the Contract's last run started an hour ago, read from the runs table instead of a `next_due` row; average pods counts only the steps the cluster has any sample on, because the lab's Prometheus misses scrapes while the Mac sleeps (found on the lab check, where `api` averaged 2.5 of its 3 pods). Checked on kind 2026-10-23 01:12 UTC into a scratch `aiops_lab` database: `api` tops the list at 2.63 cores and 2.70 GiB over 3 pods; `leaky` oom_killed, `throttled` throttled, `db` learning, `idle` excluded. Pods were first counted from CPU samples, which `rate` over 5 minutes keeps about 5 minutes past a pod's end, so `report` (a minute of work every 10) averaged 0.5 and ranked second on waste; on the Operator's call (2026-10-22) they come from kube-state-metrics' Running phase (CPU samples without it): `report` 0.1 pods and 0.10 cores, `leaky` 1.0. The ranking key (a core weighs 4 GiB) stays until Phase 10.
- *Done when:* the isolation test proves Contract A's Sizings never appear for B.

**9.5 Console app and Slack.**
- The React console's foundation (build, serving, login, the JSON API pattern) with its first page: Workloads per Contract (Sizing vs current over time, waste, risk). A weekly digest in the Contract's channel.
- Grilled 2026-10-23 (all recommended): two parts. 9.5a, the app: Vite, React and TypeScript (npm, Node 22 pinned, built in the Docker build, no Node at runtime), uPlot charts, served at `/app/` beside the Jinja `/console` with a JSON API at `/api/v1/` (pydantic models, TypeScript types generated from its OpenAPI with a drift check); the page needs the identity, the API the identity and the approver cookie (401 links the token page); strict CSP; text only, enforced by ESLint, a source scan and a component test; Workloads ranked by waste with a container's 14-day hourly or 400-day daily chart, from stored runs only; `make console-dev` proxies a local Hub adding the identity in development only; a live check with screenshots over `tailscale serve`, then v0.4.0. 9.5b, the weekly digest: Monday 09:00 UTC in the operator channel by default (`sizing.digest:` overrides the cron and zone, or `off`), on the Checks' schedule rows; totals and the week's change, the top 5, new risks, stale clusters, the learning count, a link when `AIOPS_CONSOLE_URL` is set; `aiops sizing digest [--post]`; a live post, then v0.5.0.
- 9.5a built 2026-10-23 and checked live over `tailscale serve`: demo-shop's table with `api` on top at 2.62 cores, `api`'s 14-day chart (request, Sizing, p95), `leaky`'s risk texts as text, no CSP errors in the browser. Changed from the grilling: the approver cookie's path is now `/` (it was `/console`, which the browser never sends to `/api/v1/`); TypeScript is 5.9, not 6, because `npm ci` refuses `openapi-typescript`'s peer range; ESLint bans raw HTML with its own `no-restricted-syntax` (`eslint-plugin-react` doesn't support ESLint 10 yet).
- 9.5b built 2026-10-23: `sizing_digests` holds a row per Contract that gets one (due time, schedule key), claimed with one conditional update before posting. Changed from the grilling: its own table instead of the Checks' rows, which the console lists as Checks and whose names a Check could take; the week's change and new risks compare with each cluster's latest run up to 7 days before (the same per-cluster rule as `sizing waste`), and with no run that old the digest says so and lists every risk under "Risks"; a Contract no longer getting one loses its row, so turning it back on starts at the next due time, not a missed one.
- *Done when:* the console tests that guard the Jinja pages (identity, token cookie, 404 through Caddy, text-only model output) pass against the app too.

**9.6 The agent uses Sizings.**
- A `sizing_for_workload` tool; a Triage of an OOM kill cites the Sizing.
- *Done when:* a new Scenario, an OOM-killed Triage whose Report recommends a memory request above the observed peak, passes on Haiku.
- Grilled 2026-10-23 (all recommended): two parts. 9.6a: a listed built-in integration `sizing` (refused without a cluster with a Prometheus; absent in the CLI, which has no database) whose `sizing_for_workload(cluster, namespace, name, kind?)` reads stored Sizings by Workload or pod name; after an OOM kill it suggests memory at the policy's headroom above the limit, or above the peak without one (a stopgap until Reflex 13.1); a Scenario recorded from the lab's `leaky` with `expect.memory_above`; one Haiku run. 9.6b: the agent's `prometheus` tools take a `cluster` and use its own URL and token, none on a cluster with `prometheus_labels` (a shared store, where free PromQL could read another Contract's series), and a Contract without clusters keeps today's tools. Then v0.6.0 and a live Triage on the Mac Hub.
- 9.6a built 2026-10-23; `oom-killed-sizing` passed on Haiku (run 2, 4 calls). Changed from the grilling: stored rows now hold each resource's limit, which the suggestion needs (older rows get none); a Triage Scenario can set `expect.evidence`, so this one must cite the Sizing as well as name the memory; it expects `app_error` or `resource_limits`, because the Haiku run called `leaky` a leak, which its env var shows and the categories define as `app_error`.
- 9.6b built 2026-10-23, as grilled, plus (the Operator's call) no PromQL on a cluster whose Prometheus another Contract also reads in other namespaces, a gap the old single-URL tools had too. No Scenario lists `prometheus`, so no eval reran. On the Mac Hub, demo-shop's agent now queries the lab's Prometheus (its cluster's `prometheus_url`) instead of the integration's `localhost:9090`, which the Hub's container never reached.

### Phase 10: Cost and Savings (5 slices, grill before building)

- 10.1 Unit prices per Contract (CPU-hour, GB-hour, GPU, spot). 10.2 Allocation by namespace, label and team. 10.3 Available and realized Savings, compare periods. 10.4 Cloud list prices. 10.5 Read-only billing readers (AWS CUR, GCP Billing Export, Azure Cost Management), recorded from the sandboxes.
- *Done when:* namespace cost on kind matches a hand computation, and one sandbox bill reconciles within a stated tolerance.
- 10.1 grilled 2026-10-24 (all recommended): CPU and memory only (GPU and spot arrive with Phases 17 and 16, which measure them); `prices: {currency, cpu, memory}` per Contract, per vCPU-hour and GiB-hour, with a cluster's own `cpu` and `memory` winning; one currency per Contract, never converted; money is a monthly run rate (730 h) from the latest run, worked out when shown, so a corrected price applies to history (accrued totals and periods are 10.3); each Workload's waste and request cost, requests counting every container with one; the console, the digest and `sizing waste` rank by the waste's cost, the agent's tool shows none; refused: a negative price, a cluster's prices without the Contract's, a currency on a cluster; no prices, no change. Done when hand-computed tests and an isolation test pass and the Mac Hub's demo-shop shows its costs, then v0.8.0.
- 10.1 built 2026-10-24. Changed from the grilling: every stored row now keeps its requests and average pods (learning ones kept no requests and excluded ones neither, so their cost couldn't be counted); rows stored before keep counting only ready containers' requests. Demo-shop is priced (USD 0.0316 and 0.0042).
- 10.1 checked live 2026-10-24 on the Mac Hub (v0.8.0): demo-shop priced at USD 0.0316 and 0.0042; `api` costs 69.46 USD/month of waste and 78.40 of requests, as a hand computation from its 2.652 cores and 2.701 GiB of waste and 3 pods asking 1 core and 1 GiB.
- 10.2 grilled 2026-10-24 (all recommended): two parts. 10.2a, by namespace: a console Cost page and `aiops sizing cost --by namespace [--json]`, each namespace's request cost (every container) and waste cost (sized ones), or cores and GiB unpriced, ranked by the requests, linking its Workloads; the digest unchanged; then v0.9.0. 10.2b, labels and teams: `allocation: {labels: [...], teams: [...]}`, label values from kube-state-metrics' `kube_pod_labels` (only the keys listed, a per-cluster warning when one isn't allowlisted), the newest pod's value when pods disagree, teams by first-match rules on cluster, namespace glob and label values, else "(no team)"; the lab allowlists `team`; then v0.10.0.
- 10.2a built 2026-10-24. Changed from the grilling: a namespace is its cluster's (`kind/lab`), so two clusters' `shop` stay apart.
- 10.2a checked live 2026-10-24 on the Mac Hub (v0.9.0): `kind/lab` requests 147.29 USD/month and waste 75.29, the waste equal to its ranked Workloads' and the requests to the ready ones' (117.32), the learning `db`'s (3.84) and the excluded `idle`'s (26.13); the namespaces add up to the Contract's 148.50.
- 10.2b built 2026-10-24. Changed from the grilling: a team rule names its team in `team:`; a team or a label value spans clusters; the newest pod is the latest `kube_pod_created` (pods without one go by name); the warning is worked out when shown, from the stored rows (a cluster where no pod has the label), on the Cost page and in `sizing cost`; `--by team` exists only with team rules; a Workload without the label goes to `(no <key>)`; team and label groups don't link to the Workloads page, which filters by namespace only. The lab's pods carry `team` (one, `idle`, none).
- 10.2b checked live 2026-10-24 on the Mac Hub (v0.10.0), with demo-shop's four team rules on the `team` label: storefront 103.00 USD/month of requests (70.25 waste, 2 Workloads), payments 9.22, data 8.61, platform 0.33 and `(no team)` 27.34 (`idle` and the 4 Workloads of `demo` and `orders`) add up to the Contract's 148.50, and their waste to the namespaces' 74.65; `--by label:team` gives the same groups, and no warning.
- 10.3 grilled 2026-10-24 (all recommended, 2 rounds): two parts. 10.3a: available Savings is the waste's cost under its glossary name (a Contract and group total on the Cost page and in the CLI; what under-sized containers need stays a risk, never netted); compare periods as snapshots, each group's monthly request and waste cost now against N days ago (7, 30, 90; `latest_sizings(before=)`), with "no run that old" and the oldest date when there is none, and runs before 0.8.0 comparing only containers whose requests are known; Cost page picker and Δ column, `aiops sizing cost --compare 30d`; then v0.11.0. 10.3b: realized Savings, found by each hourly run comparing a container with the previous run and storing a drop (migration: container, when, CPU and memory before and after; no backfill) when the new request is within 10% of a Sizing shown in the 14 days before, CPU and memory apart; worth (before - after) x the pods now x the price, priced when shown, as a monthly run rate and as accrued since the change (run rate x hours, today's prices); a later rise cancels that much and a deleted Workload ends it; fewer pods and raised requests never count; `aiops sizing savings [--json]`, the Cost page's Savings summary (available, realized), one digest line "Realized this week"; cores and GiB unpriced; the agent's tool unchanged; then v0.12.0. Live checks on the Mac Hub: 10.3a `sizing cost --compare 1d` matching a hand difference of two runs; 10.3b lab `api` set to its Sizing with `kubectl set resources` (live only), realized after the next run equal to a hand computation, and a later `make lab` cancelling it.
- 10.3a built 2026-10-24. Changed from the grilling: the picker also offers 1 day (the live check's), the CLI takes any `m`, `h` or `d` and the API 1 to 400 days; each cluster is compared on its own, and one with no run that old is left out of both sides and named with its oldest run (the comparison is never empty for the others); when the grouping reads labels (`label:<key>`, or team rules with labels), every container of a cluster where no pod had them then but some do now is left out too (stored before the Contract listed them, or before kube-state-metrics exported them), like one whose requests weren't stored, and both are listed; a group gone since stays listed with its whole drop; only the Cost page and `sizing cost` say "savings available", the Workloads page, the digest and `sizing waste` still say waste.
- 10.3a checked live 2026-10-24 on the Mac Hub (v0.11.0): `sizing cost --compare 1d` compared the 23:09 UTC run with 2026-10-23 23:45 UTC (the latest at or before 00:09), left out the 4 containers stored before 0.8.0 (`db`, `idle`, `checkout`, `reports`), and its changes equal a hand computation from both runs' rows in Postgres: `kind/lab` requests +0.00 and Savings +0.73 USD/month, `kind/demo` and `kind/orders` 0; the team comparison waits for a day of labelled runs.
- 10.3b built 2026-10-24. Changed from the grilling: requests and limits are now read from the live pods (seen in the last 5 minutes), the window's largest only for a container with none, since the window's largest across pods hid a lowered request for up to the whole window (a correction to 9.1); the matched Sizing must be below the old request (one raising it can't make a saving); a drop is stored once per previous run, so a `sizing refresh` overlapping the hourly run can't store it twice; each row says whether its requests are its live pods', and only a live row starts, takes back or ends a drop (a run with kube-state-metrics down or the Workload scaled to 0 reads the window's old request), so only drops between two 0.12.0 runs count; "the pods now" are the latest run's average pods, as its waste's; a removed request ends its drops; the digest leaves the line out while nothing was realized; the Cost page's summary comes with the cost API, with no API of its own.
- 10.3b checked live 2026-10-25 on the Mac Hub (v0.12.0): `kubectl set resources` lowered lab `api` to its Sizing (116m, 102Mi, 3 pods) and the next run stored it; `sizing savings` showed 61.18 + 8.28 = 69.46 USD/month, equal to a hand computation ((1 - 0.116) x 3 x 0.0316 x 730 and (1 GiB - 102Mi) x 3 x 0.0042 x 730), and the digest said "Realized this week: 69.46 USD/month". `make lab` raised it back to 1 core and 1Gi and the run 5 minutes later ended it ("no realized Savings").
- 10.4 grilled 2026-10-25 (all recommended, 2 rounds): the Hub reads on-demand list prices from the public APIs (AWS price list, Azure Retail Prices; GCP's catalog only when the Contract names an API key secret, else skipped with a message), refreshed daily and stored with their date, so the hourly run reads the stored copy; a cluster's provider, region and instance types come from kube-state-metrics `kube_node_labels` (no new RBAC; the KSM allowlist must expose them); a node's hourly price splits into a CPU price and a GiB price by one fixed weight (default 1 vCPU = 7 GiB, per Contract), so they sum to the node price; a cluster with mixed node types gets the capacity-weighted average (total node price over total vCPU and GiB now), one price per cluster like `prices`; an optional per-Contract `discount` factor multiplies the list price (on-demand only, spot waits for Phase 16); typed `prices` win and the list fills only the gaps, so upgrading changes no shown cost, and the console says which source a price has; a cluster without labels (kind, bare metal) or a failed fetch gets no list price and says why, keeping the last good price with its age, never a made-up one. Done when hand-computed tests (split, average, discount, precedence, fallbacks) pass, the AWS price file is parsed streaming for only the instance types in use, and the Mac Hub's kind node, labelled by hand as an m5.large in us-east-1, shows the real list price equal to a hand computation, then v0.13.0.
- 10.4 built 2026-10-25. Changed from the grilling: a cluster may declare `provider: aws|azure|gcp` (kind and bare metal have a `kind://` provider_id, and the check needs a cloud name); `list_prices: {weight, discount, gcp_key_secret}` and a Contract-level `prices` are refused together (the Contract's prices already price every cluster, so the list has nothing to fill; a cluster's own `prices` are allowed beside `list_prices`); one cluster the list can't price leaves the whole Contract in cores and GiB (money for one cluster and cores for another can't be ranked), with a note per cluster; the daily lookup rides on the hourly Sizing tick (a price is looked up again after 24 h, a failed one after 1 h) and `aiops sizing prices [--refresh]` shows or forces it; the AWS offer file is streamed to disk and parsed with `ijson` (a new dependency: the file is hundreds of MB); GCP's key goes in the `X-Goog-Api-Key` header, never the URL, and a failed lookup stores only `HTTP <status> from <host>`; a cluster on a store shared with another Contract and without labels reads no nodes; the Cost and Workloads pages, `sizing cost` and `sizing waste` say where each price comes from. GCP is checked against recorded fixtures only (no Billing API key yet).
- 10.4 checked live 2026-10-25 on the Mac Hub (the local v0.13.0 image): the kind node labelled by hand as an m5.large in us-east-1 (`aiops sizing prices --refresh` read AWS's real offer file: 0.096 USD/h, the real m5.large Linux price) with the node's real capacity of 10 vCPU and 31.29 GiB gave 0.00094776 USD per GiB-hour and 7 times that per vCPU-hour; demo-shop's total requests of 5.70 cores and 5.55 GiB cost 31.45 USD/month, equal to a hand computation ((5.7 x 7 + 5.55) x 0.00094776 x 730), and `sizing cost` printed its price line.
- 10.5 grilled 2026-10-26 (all recommended, 3 rounds): reconcile only, "estimated vs billed" per cluster and period, never changing a shown cost; three slices, one release each: 10.5a AWS, 10.5b Azure, 10.5c GCP. 10.5a reads Cost Explorer `GetCostAndUsage` with the Contract's `aws` integration key (plus `ce:GetCostAndUsage`); a cluster names its bill lines by `billing: {tag: "key=value"}` (EC2 compute, usage before credits, unblended, daily); the estimate is the cluster's node-hours from a Prometheus range query at its effective price (typed or list); the period is 7 full UTC days ending 2 days ago (`--days 1` to `30`); the bill is fetched daily on the hourly Sizing tick and stored per cluster and day (a failure retried after 1 h, `--refresh` forces); 5% is the tolerance; shown by `aiops sizing bill [--json]` and a Cost page line per cluster, with the digest and the agent unchanged; a currency that differs from the Contract's is shown without a gap, never converted. Live check: one t3.small in us-east-1 tagged `aiops-cluster=kind` for about 48 hours (about 1 USD from credits, with the Operator's yes), the kind node labelled t3.small, billed equal to 0.0208 x hours within 5% of the estimate. Then v0.14.0.
- 10.5a built 2026-10-26. Changed from the grilling: the bill has its own endpoint, `GET /contracts/{id}/billing?days=`, not a field of the cost API (it asks Prometheus for node-hours, and the Cost page's other requests shouldn't wait for that); the estimate is node capacity-hours (hourly samples of `kube_node_status_capacity`) at the cluster's unit prices, so a changing node count is counted, not only the latest nodes; `billing:` is refused without the `aws` integration or without a Prometheus; the read covers the last 30 full days and leaves today out; a failed read keeps the stored days and the last good read's time; the CLI exits 1 when any cluster is outside 5%. 964 Python tests (36 new, 27 mutations caught) and 12 console tests pass. The live check (a tagged t3.small for about 48 hours) waits for the Operator's yes; AWS GovCloud and China partitions are not read.
- 10.5a checked live 2026-10-26 against the AWS sandbox's real Cost Explorer (API only): `ce:GetCostAndUsage` added to `aiops-readonly`; `billing.fetch` with that key, signed by the Hub's own SigV4, read 30 days in USD and parsed them, an unknown tag answered with zero days and a wrong secret with `HTTP 400 from ce.us-east-1.amazonaws.com` (no secret in it). The sandbox cannot show a nonzero tagged bill: its SCP allows EC2 only in us-east-2, free-plan usage costs 0 even before credits (the Operator's one-minute instance of 2026-10-23 shows 0.0175 hours and 0 USD), and a linked account cannot activate cost-allocation tags. Phase 10's "one bill reconciles" therefore waits for an account that bills (reconciliation itself is proven by fixtures and hand computations).
- **Later slice (the Operator asked to remember it): the billed effective rate feeds prices.** After reconciliation shows the gap, a billed rate (discounts, savings plans) can replace the list price, with its own precedence rules against typed `prices` and `list_prices`.

### Phase 11: The Hub as a source, and the whole console in the app (7 slices, grill before building)

- 11.1 The Hub MCP server for the Operator: reads across Contracts, each call scoped to one. 11.2 Its writes: Approval decisions, single Sizings, the kill switch, audited as made through MCP. 11.3 Pull requests to the contracts repo for Automation and policy changes (a token limited to opening pull requests; the Operator merges). 11.4 A "what should I do now" Check ranking waste, risk and open Investigations. 11.5 to 11.7 The remaining console pages rebuilt in the app (Investigations and approvals, Teachings and Checks, Questions), then the Jinja pages deleted.
- *Done when:* Claude Code lists a Contract's top 5 Sizings and approves one through the Hub MCP server, an Automation change arrives as a pull request, and the Jinja templates are gone with every console test still passing.

### Phase 12: Actuator (9 slices, grill before building; needs Phase 3)

- 12.1 Our CRDs (policies, Sizings, Automation) and their rendering from the contracts repo. 12.2 Pulling approved Sizings over the Relay. 12.3 In-place resize. 12.4 Pre-checks (HPA, VPA, quotas, LimitRange, node headroom, PDB, readiness), each with its own test. 12.5 Windows, pause annotation, per-Contract kill switch. 12.6 Pod-creation webhook (fail open, protected namespaces) and PDB-safe eviction behind a flag. 12.7 Auto-rollback with an adoption threshold and backoff. 12.8 Kubernetes events and the Hub audit trail. 12.9 The console's Automation view.
- *Done when:* on kind 1.33+, an approved policy resizes a Deployment in place without restarts, a PDB blocks an eviction, a bad Sizing is rolled back, and pods still start with the Actuator scaled to zero. KWOK with thousands of fake Workloads for load.

### Phase 13: Reflexes (4 slices, grill before building)

- 13.1 OOM memory step-up, capped and expiring. 13.2 Node-level vs container-limit OOM attribution. 13.3 Burst CPU headroom. 13.4 Startup CPU boost. A Triage Report links any Reflex it triggered.
- *Done when:* an OOM-killed pod's next replica gets more memory within a minute, and the step-up expires on schedule.

### Phase 14: Horizontal (4 slices, grill before building)

- 14.1 HPA and KEDA minimum replicas from percentiles. 14.2 Weekly profiles with lead time. 14.3 Re-anchoring the HPA target after a Sizing changes requests. 14.4 Backtests with an error budget.
- *Done when:* backtests pre-scale before a synthetic Monday peak, and a request cut doesn't change HPA replica counts.

### Phase 15: Nodes (6 slices, grill before building)

- 15.1 What blocks scale-down (PDBs, `safe-to-evict=false`, local storage, ownerless and kube-system pods). 15.2 Placing unevictable pods together. 15.3 DaemonSet Sizing per node. 15.4 Consolidation recommendations. 15.5 Compaction with the descheduler. 15.6 Karpenter NodePool and Cluster Autoscaler proposals.
- *Done when:* on multi-node kind, placement empties a node the report named as blocked.

### Phase 16: Spot (3 slices, grill before building)

- 16.1 A spot ratio per Workload with an on-demand floor. 16.2 Placing replicas by capacity type. 16.3 Fallback on interruption.
- *Done when:* replicas keep the ratio and the floor when a "spot" kind node is deleted.

### Phase 17: GPU and LLM inference (7 slices, grill before building)

- 17.1 DCGM ingestion. 17.2 Idle GPUs and per-pod attribution with cost. 17.3 vLLM metrics and memory-reservation Sizings. 17.4 GPU replica floors from queue and KV-cache signals. 17.5 GPU node consolidation. 17.6 GPU sharing by adopting an existing scheduler (KAI or HAMi). 17.7 Batch inference.
- *Done when:* an idle synthetic GPU Workload is flagged with its cost from fixtures; real GPUs only in a paid sandbox the Operator approves.

### Phase 18: Platform (4 slices, grill before building)

- 18.1 A signed Helm chart (OCI) for the Relay and the Actuator. 18.2 OpenShift values. 18.3 A version-skew rule between Hub and cluster parts. 18.4 Fleet views across Contracts and clusters.
- *Done when:* a fresh kind cluster goes from `helm install` to a connected Relay in one command, in CI.

### Phase 19: Integrations breadth (about 8 slices, grill before building)

- PagerDuty and Opsgenie, ServiceNow, Microsoft Teams and Google Chat, generic outbound webhooks, managed Prometheus auth (AMP, Azure Monitor, GMP, Grafana Cloud), Datadog and New Relic as metric sources, JVM heap Sizing, Spark and batch sizing.
- *Done when:* each integration has a probe, a recorded Scenario and a passing eval, through the Phase 4 framework.

## Deferred

| Item | Why not now | Trigger to revisit |
|---|---|---|
| Full agent inside a client network | A Relay keeps credentials there already | A Contract forbids tool output leaving its network |
| Specialist sub-agents (IncidentFox) | Allowlists and good tools come first | Evals fail on cross-domain Scenarios |
| Anomaly detection (Prophet) | Needs history and tuning. Alerts already cover it | Repeated misses that no alert catches |
| Hierarchical retrieval (RAPTOR) | Full-text search over a small corpus is enough | Runbooks outgrow search plus embeddings |
| Multi-user RBAC, SSO | One Operator | A second person joins |
| Sandbox and credential proxy (IncidentFox, BSL) | A Relay keeps credentials out of the Hub | A Direct Contract's threat model demands it |
| Agent actions that run without approval | Not without months of evidence | Never by default. Sizings under Automation are approved as a policy ([ADR 0004](adr/0004-standing-approval-for-sizing.md)) |
| Fix PRs on GitHub/GitLab (HolmesGPT) | Needs code access per Contract | After Jira, when a Contract grants repo access |
| Splunk and other log sources | Phase 19 covers the metric and paging integrations first | After Phase 19 |

## Next

Phases 0 to 8 are done except 3 (Relay). On 2026-10-21 the Operator chose to grow the Hub into a resource optimizer as well (Phases 9 to 19, ADR 0004). 9.1 to 9.4 are built and checked on kind, and v0.3.0 (2026-10-23) stores Sizings hourly on the Mac Hub. v0.4.0 (2026-10-23) has the console app (9.5a) and v0.5.0 (2026-10-23) the weekly Sizing digest (9.5b). v0.6.0 (2026-10-23) gives the agent Sizings (9.6a) and per-cluster PromQL (9.6b). v0.7.0 (2026-10-23) has Masking (6.4), v0.8.0 (2026-10-24) unit prices (10.1), v0.9.0 (2026-10-24) cost by namespace (10.2a), v0.10.0 (2026-10-24) cost by team and label (10.2b), v0.11.0 (2026-10-24) Savings and compare periods (10.3a), v0.12.0 (2026-10-25) Realized Savings (10.3b), v0.12.1 (2026-10-25) dependency alert fixes v0.13.0 (2026-10-26) cloud list prices (10.4) and v0.14.0 (2026-10-26) the AWS bill check (10.5a); Phase 3 (Relay) is the last of Phases 0 to 8.
