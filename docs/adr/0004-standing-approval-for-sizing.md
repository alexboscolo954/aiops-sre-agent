---
status: accepted
---

# An in-cluster Actuator may apply Sizings under a standing approval

The Hub becomes a resource optimizer as well as an SRE agent (Phases 9 to 19, inspired by ScaleOps and Kubex: their ideas, not their code). Continuous rightsizing and the reflexes that make it safe (an OOM step-up at 3 a.m.) cannot wait for a click on every change. So a Contract may turn on **Automation** for chosen workloads: the Operator approves a Sizing policy once, and from then on the Actuator applies the Sizings that policy produces without asking again.

The brain stays in the Hub: metrics aggregates, the recommender and the Sizing policies (from the contracts repo) live there, as for every other Investigation. The hands live in the client cluster: an **Actuator**, a new role in the same image (`aiops actuator`), pulls approved Sizings from the Hub over the Contract's Relay connection and applies them, in place first (Kubernetes 1.33+), with a pod-creation webhook and PDB-safe eviction only behind a per-Contract flag. It never writes to client Git repositories: it changes pods, not manifests.

## What this supersedes

- ADR 0002's rule that every write is a Proposed action approved per call. That rule still holds for everything the agent proposes. It no longer holds for Sizings under Automation, which the Operator approved as a policy.
- ADR 0002's "Relays only run tools". The Relay connection now also carries approved Sizings to the Actuator, and the Actuator's events back to the Hub. The Relay itself still only runs tools.
- The roadmap's deferred row "Actions that run without approval: never by default". Automation is still never on by default.

## Guardrails

- Off by default. Automation is opt-in per Contract and then per workload, and only the Operator turns it on, in the contracts repo.
- Every applied Sizing is bounded by its policy's minimums and maximums, recorded in the Hub's audit trail and as a Kubernetes event, and can be rolled back. Auto-rollback undoes a Sizing that made pods unhealthy.
- Reflexes (OOM memory step-up, burst CPU headroom, startup CPU boost, auto-rollback) act unattended, but each is capped per Contract and expires.
- The webhook fails open: if the Actuator is down, pods are created unchanged. A per-Contract kill switch stops all Automation at once.
- The agent cannot widen any of this. A Triage may propose a Sizing, which stays an ordinary Proposed action.

## Consequences

A client running the Actuator grants it write RBAC on its workloads and, with the eviction flag, a mutating webhook. Each client must agree to that; a Contract that doesn't keeps read-only Sizings. Writes need the Relay, so Phase 3 becomes a hard prerequisite of Phase 12. The README's safety model changes when Phase 12 ships, not before.

## Considered Options

- **Keep per-change approval for every Sizing.** Safest, but continuous rightsizing becomes a queue of clicks and reflexes become impossible.
- **Everything in the client cluster** (recommender, metrics and UI per cluster, as ScaleOps ships). Works with the Hub down, but N copies of the brain to upgrade and per-workload data spread across sites. Held back: the Hub already holds every Contract's other state.
- **Pull requests to the client's Git repositories.** Fully reviewable, but needs client Git credentials and is too slow for reflexes.
