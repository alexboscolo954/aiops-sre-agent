---
status: accepted
---

# Reflexes may raise limits, Sizings never do

A Sizing changes requests only. A container's limit is its owner's statement of how much it may ever use, so a Sizing keeps it and flags a conflict as a risk ([ADR 0004](0004-standing-approval-for-sizing.md)). That leaves one failure no Sizing can fix: a container OOM-killed at its memory limit keeps being killed, at 3 a.m. as at noon, until a person raises the limit in its manifest.

So a **Reflex** may raise a limit, where a Sizing never does. The first is the memory step-up (Phase 13): after an OOM kill at a memory limit, the Actuator raises that container's memory limit and its request together, by the same factor so the pod's QoS class stays, on every pod of the Workload in place and on new pods through its webhook. Burst CPU and the startup CPU boost raise a CPU limit under the same rule.

## Guardrails

- Off by default, and twice opt-in: the Contract sets `actuator: reflexes`, and only Workloads under Automation (`automate: true`) are touched. The Operator turns both on, in the contracts repo.
- Bounded: never past `max` times the limit in the Workload's template (2 by default), nor past a LimitRange or a ResourceQuota. One step a container every 10 minutes, and step-ups and bursts together at most 10 a cluster an hour.
- Expiring: a step-up ends after `expires` unless the need is still measured (slice 13.1c). It never becomes the Workload's new normal by itself.
- Never under the Kill switch, on a paused Workload, for one a VPA sizes, for a container whose memory an HPA scales on, or while the Hub is unreachable (a step-up is a new change, and the Kill switch can't be heard then). Never an eviction.
- The Actuator's writes stay what they were: `pods/resize`, which already carries limits, and its webhook at a pod's creation. It still never patches a Workload, so nothing drifts from Git: the manifest's limit is unchanged, and the Operator is told what to change in it.
- Every step is an Actuation in the Hub's audit trail and a Kubernetes Event, and a Revert drops it.

## What the Actuator can and can't know

The pod reads the same (`OOMKilled`, exit code 137) whichever memory limit caused the kill: the container's own, its pod's, or the one the kubelet sets on all pods together (the node's allocatable memory). The kubelet's `SystemOOM` Event on the Node marks only a kill no limit caused. So "container-limit" means "a memory limit was reached and the node was not out of memory", and a step-up may raise a limit that was not the one reached.

That is accepted, with one rule. Erring the other way leaves a container at its own limit crash-looping, the case the Reflex exists for; and the step raises the request with the limit, which is also what a container killed over its request needs. But while a Sizing that lowered that container's memory request is in its watch hour, an OOM kill of it is a Rollback, never a step-up: a lowered request makes a container the likelier victim of a kill above its own limit.

## Consequences

Under Automation with Reflexes on, a container's limit in its manifest is no longer the most it can use: `max` times that limit is. A client must agree to that, as to Automation itself. A Guaranteed pod stays Guaranteed (request and limit move together), and a Workload nobody automates is never touched.

## Considered Options

- **Never touch a limit: roll the Sizing back and tell the Operator.** A Rollback restores requests, which does nothing for a container at its limit. The kills go on until someone edits the manifest.
- **Let a Sizing raise limits.** It would make every Sizing a possible change of the owner's ceiling, and need the same bounds on all of them. Keeping limits to Reflexes keeps the standing approval of ADR 0004 narrow.
- **Patch the Workload's limit.** Argo CD or Flux would put it back, and the Actuator would gain a permission that can change more than resources.
- **Have the Hub confirm from Prometheus that the container was at its own limit.** A 30-second sample can miss the spike, and the step would come a minute or two late.
