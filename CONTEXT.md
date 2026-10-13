# Alert triage

An agent investigates Kubernetes alerts and reports a root cause backed by evidence. It changes the cluster only after a human approves.

## Language

### Input

**Alert**:
One firing instance of an alerting rule, identified by its labels.
_Avoid_: Using "alert" for a whole notification

**Alert group**:
One Alertmanager notification, holding one or more Alerts that Alertmanager grouped together. The Alert group is the unit that gets triaged. A re-sent Alert group starts a new Triage only when an Alert not seen before starts firing. A group that shrinks, or comes back unchanged, is a duplicate.
_Avoid_: Notification, alert batch

**Alert severity**:
The severity label the rule author set on an Alert. The agent never changes it.

### Investigation

**Triage**:
The whole investigation of one Alert group, from receipt to final Report, including any pauses for approval.
_Avoid_: Using "triage" for a single agent invocation

**Run**:
One uninterrupted stretch of agent work inside a Triage. A Triage without a Proposed action has one Run. Each Approval decision or Stale rejection starts another Run.

**Report**:
The structured result of a Triage: summary, Category, root cause, Evidence, Assessed severity and Recommendations.
_Avoid_: Triage (for the output)

**Failed triage**:
A Triage that ended without a Report because the agent could not finish. On-call is told explicitly. There is no partial Report.

**Evidence**:
A finding from a tool result that supports the root cause. A claim in a Report without Evidence is not allowed.

**Runbook**:
A team-written procedure mapped to one or more alert names. One alert name can map to several Runbooks.

**Category**:
The class of the root cause, not the failure mode (the alert name already says how it fails). When a rollout introduced the fault after an earlier revision that worked, the Category is `bad_rollout`, even if the fault itself is bad config or a bad image. A workload broken since its first revision has no rollout to blame.
Values: `bad_rollout`, `bad_config` (wrong or missing config, command or probe), `app_error` (a bug in the code, including memory leaks), `resource_limits` (limits too low for a healthy workload), `image_unavailable`, `capacity` (the cluster can't fit the workload), `node_problem`, `dependency_failure`, `unknown`.

**Assessed severity**:
The agent's judgment of actual impact, backed by evidence. It can disagree with the Alert severity.

### Acting

**Recommendation**:
A next step written for a human. It is advice and never runs.
_Avoid_: Action, recommended action

**Proposed action**:
A cluster-changing tool call the agent wants to make, paused until a human approves or rejects it.
_Avoid_: Pending action, write

**Stale**:
A Proposed action is Stale once its Alert group resolves, or when no Approval decision arrives within the decision timeout. A Stale action is rejected automatically, and the Triage finishes with a Report.

**Approval decision**:
A human's approve or reject, covering every Proposed action in one pause together. A rejection can carry a reason, and the agent can propose a narrower action in the next Run.

**Executed action**:
A Proposed action that a human approved and that the system then ran against the cluster. The system records it from the tool calls that actually ran, marked as failed when the call errored. The agent never reports it.
_Avoid_: Action taken

### Evaluation

**Scenario**:
A recorded Alert group, the tool results captured from a real cluster, and the Expectation a correct Triage must meet.

**Expectation**:
What a passing Triage must contain: an allowed Category, root-cause keywords, a tool-call budget, and the Proposed actions it may make (none, by default).
