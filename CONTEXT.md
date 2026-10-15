# Alert triage

An agent investigates alerts, questions and scheduled checks for several Contracts, and backs every conclusion with evidence. It changes a Contract's systems only after the Operator approves.

## Language

### Contracts

**Contract**:
One client engagement the agent works for: its clusters and integrations, its credentials, its Runbooks, its Data policy and where its Reports go. Nothing from one Contract (Alerts, tool results, Reports, knowledge) is ever visible while working on another.
_Avoid_: Client, tenant, customer

**Operator**:
The person who runs the agent across all Contracts. The Operator receives every Report and makes every Approval decision. A Contract can also send its Reports to the client team's own channel, but that is optional.
_Avoid_: User, admin

**Data policy**:
A Contract's rules on what may be sent to the LLM. A Contract has no restrictions unless its Data policy says otherwise.

**Hub**:
The one always-on service that runs every Investigation for every Contract. It receives alerts and serves the Operator in Slack and the web console.
_Avoid_: Server, backend

**Direct**:
A way to reach a Contract where the Hub holds the Contract's credentials and calls its APIs itself.

**Relay**:
A small process inside a client's network that holds that Contract's credentials and runs its tools. It connects out to the Hub, so the client network accepts no inbound connections. The agent's reasoning stays in the Hub. Only tool calls and their results pass through the Relay.
_Avoid_: Satellite, agent

### Input

**Alert**:
One firing instance of an alerting rule, identified by its labels.
_Avoid_: Using "alert" for a whole notification

**Alert group**:
One Alertmanager notification, holding one or more Alerts that Alertmanager grouped together. The Alert group is the unit that gets triaged. It belongs to exactly one Contract, so two Contracts never share an Alert group. A re-sent Alert group starts a new Triage only when an Alert not seen before starts firing. A group that shrinks, or comes back unchanged, is a duplicate.
_Avoid_: Notification, alert batch

**Alert severity**:
The severity label the rule author set on an Alert. The agent never changes it.

### Investigation

**Investigation**:
Work the agent does for one Contract. It is one of three kinds: a Triage, a Question or a Check.

**Triage**:
The Investigation of one Alert group, from receipt to final Report, including any pauses for approval.
_Avoid_: Using "triage" for a single agent invocation

**Question**:
An Investigation the Operator asks for in their own words, in Slack or the web console.

**Check**:
An Investigation that runs on a schedule or after a deploy, without an alert. A passing Check is recorded quietly. A failing Check produces a Report and notifies the Operator like a Triage does.

**Run**:
One uninterrupted stretch of agent work inside an Investigation. An Investigation without a Proposed action has one Run. Each Approval decision or Stale rejection starts another Run.

**Report**:
The structured result of a Triage, a failing Check, or a Question that turns into a hunt for a fault: summary, Category, root cause, Evidence, Assessed severity and Recommendations.
_Avoid_: Triage (for the output)

**Answer**:
The result of a Question: a direct reply backed by Evidence, with no Category or Assessed severity. A Question that turns into a hunt for a fault ends with a Report instead.

**Failed investigation**:
An Investigation that ended without its Report or Answer because the agent could not finish. The Operator is told explicitly. Nothing partial is delivered.
_Avoid_: Failed triage

**Evidence**:
A finding from a tool result that supports a conclusion. A claim in a Report or an Answer without Evidence is not allowed.

**Runbook**:
A written procedure mapped to one or more alert names. One alert name can map to several Runbooks. A Runbook belongs to one Contract, or is part of Shared knowledge.

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
A tool call that would change a Contract's systems, paused until the Operator approves or rejects it.
_Avoid_: Pending action, write

**Stale**:
A Proposed action is Stale once its Alert group resolves, or when no Approval decision arrives within the decision timeout. A Stale action is rejected automatically, and the Investigation still finishes.

**Approval decision**:
The Operator's approve or reject, covering every Proposed action in one pause together. A rejection can carry a reason, and the agent can propose a narrower action in the next Run.

**Executed action**:
A Proposed action that the Operator approved and that the system then ran. The system records it from the tool calls that actually ran, marked as failed when the call errored. The agent never reports it.
_Avoid_: Action taken

### Knowledge

**Similar incident**:
A past Report from the same Contract that the agent finds and uses as a lead. It never comes from another Contract.

**Teaching**:
A lesson the agent proposes after an Investigation or from the Operator's feedback. It is used only after the Operator approves it, and it always stays in its own Contract.
_Avoid_: Memory, learning (for a single lesson)

**Shared knowledge**:
Knowledge the Operator writes that holds no client data, such as general SRE lessons and generic Runbooks. Every Contract can use it. The agent never writes to it.

### Evaluation

**Scenario**:
A recorded Alert group, the tool results captured from a real cluster, and the Expectation a correct Triage must meet.

**Expectation**:
What a passing Triage must contain: an allowed Category, root-cause keywords, a tool-call budget, and the Proposed actions it may make (none, by default).
