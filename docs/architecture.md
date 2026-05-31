# Questline Architecture

Questline is designed as a Codex plugin that turns one vague user prompt into a durable, verifiable chain of subgoals. The main design constraint is that Codex's native goal runtime does not expose a durable subgoal tree. Questline therefore separates the workflow into three layers:

```text
Skill instructions -> MCP state machine -> JSON ledger
```

The skill tells Codex how to behave. The MCP server enforces state transitions. The JSON ledger stores the durable state on disk.

## Goals

Questline should:

- clarify ambiguity before planning;
- record explicit constraints, non-goals, and acceptance criteria;
- decompose a large goal into workflow-sized subgoals;
- require objective checks before completion;
- require critic review for subjective or hard-to-verify subgoals;
- survive context compaction and new Codex sessions;
- support multiple questlines running in the same workspace without path collisions.

Questline should not:

- pretend Codex native goals support nested subgoals;
- rely only on conversational memory for runtime state;
- infer the active quest from a slug alone;
- allow unchecked direct edits to mark work complete.

## Components

### Plugin Manifest

`.codex-plugin/plugin.json` declares the plugin, skill directory, and MCP configuration:

```text
.codex-plugin/plugin.json
.mcp.json
```

The manifest wires the plugin into Codex. `.mcp.json` starts `scripts/questline_mcp.py` as the Questline MCP server.

### Skill Layer

`skills/setgoal/SKILL.md` is the prompt-level control plane.

It defines:

- `/questline` invocation behavior;
- clarification policy;
- ambiguity scoring;
- subgoal planning rules;
- critic persona defaults;
- non-skippable runtime rules.

The skill is intentionally not the source of durable truth. It tells Codex to use Questline MCP tools for state changes and to stop if those tools are unavailable, unless the user explicitly allows an unsafe file-based fallback.

### MCP Runtime

`scripts/questline_mcp.py` is the runtime surface.

It exposes guarded tools:

```text
questline_create
questline_get
questline_list
questline_append_event
questline_record_clarification
questline_set_plan
questline_start_subgoal
questline_record_check_result
questline_record_critic_result
questline_complete_subgoal
questline_block_subgoal
questline_complete_quest
```

The MCP runtime owns state mutation. It writes ledger files atomically, appends events, updates the discovery index, and rejects invalid transitions.

### JSON Ledger

The ledger is the durable storage layer under the current workspace:

```text
.questline/sessions/<session-id>/<quest-instance-id>/quest.json
.questline/sessions/<session-id>/<quest-instance-id>/events.jsonl
.questline/index.json
```

`quest.json` is the source of truth for one quest instance.

`events.jsonl` is an append-only audit log for that instance.

`index.json` is a discovery index used for listing and resuming quests. It is not the source of truth.

## Session And Instance Model

Questline state is namespaced by both session and quest instance:

```text
session-id
  quest-instance-id
    quest.json
    events.jsonl
```

This prevents collisions when multiple Codex sessions run in the same workspace. A quest slug is human-readable but not unique. A quest instance id includes the slug, timestamp, and random suffix:

```text
payment-refactor-20260531-141522-a1b2c3
```

Rules:

- never infer the active quest from slug alone;
- resume automatically only when the current session has exactly one incomplete quest;
- ask the user to choose when multiple incomplete quests exist;
- keep separate quest instances even when they share the same slug.

## State Lifecycle

The high-level quest lifecycle is:

```text
clarifying -> planned -> running -> validating -> complete
                                  \-> blocked
```

`clarifying` starts when `questline_create` creates a ledger.

`planned` starts when `questline_set_plan` accepts the clarified goal and subgoal plan.

`running` starts when `questline_start_subgoal` activates a dependency-ready subgoal.

`complete` is only allowed through `questline_complete_quest`.

`blocked` is used only when no meaningful autonomous progress remains.

## Clarification

Questline scores ambiguity from 0 to 3 across:

```text
goal
scope
non_goals
constraints
acceptance
environment
risk
```

`questline_set_plan` rejects planning while any ambiguity score is greater than 1. This forces clarification before decomposition.

The clarification state records:

- assumptions;
- constraints;
- non-goals;
- acceptance criteria;
- open questions.

This is where "what not to do" is captured before work begins.

## Subgoal Planning

A subgoal is a workflow-sized unit, not a tiny task. Each subgoal includes:

```text
id
title
objective
depends_on
deliverables
acceptance_checks
non_goals
needs_critic
critic_policy
status
notes
```

The MCP runtime validates that:

- every subgoal has an id;
- ids are unique;
- dependencies point to known subgoals;
- every subgoal has at least one acceptance check.

## Transition Enforcement

Questline uses explicit transition tools instead of a generic "update JSON" surface. This is the main enforcement mechanism.

The runtime rejects:

- setting a plan while ambiguity scores exceed 1;
- starting a subgoal with incomplete dependencies;
- starting a second subgoal while another is active;
- completing a subgoal before all acceptance checks pass or are explicitly skipped;
- completing a critic-required subgoal before critic verdict is `pass`;
- completing the quest while any subgoal is incomplete;
- completing the quest without final verification evidence.

This makes the prompt guidance harder to accidentally bypass. The skill can still be ignored by an agent, but the MCP tools will not accept invalid state transitions.

## Critic Gate

Some work cannot be verified by commands alone. Questline marks those subgoals with:

```json
{
  "needs_critic": true,
  "critic_policy": {
    "required": true,
    "last_verdict": null
  }
}
```

The skill instructs Codex to spawn a skeptical critic subagent for these subgoals. The critic returns blocking findings, non-blocking risks, missing verification, and a pass/fail verdict.

The runtime records that verdict with `questline_record_critic_result`. A required critic gate must pass before `questline_complete_subgoal` succeeds.

## Persistence And Concurrency

Questline uses:

- atomic JSON writes via temporary file replacement;
- append-only JSONL event logs;
- lock files around state writes;
- separate state directories per session and quest instance.

This is intended to reduce accidental corruption and cross-session collisions. It is not a distributed database. If multiple processes intentionally mutate the same quest instance at the same time, the file lock serializes writes on the local filesystem, but higher-level merge semantics remain simple last-transition-wins state updates.

## Resume Behavior

To resume work:

1. call `questline_list`;
2. identify incomplete quests for the current session;
3. if exactly one exists, call `questline_get`;
4. if more than one exists, ask the user which quest instance to resume;
5. continue from `runtime.active_subgoal` or the next dependency-ready subgoal.

Context compaction should not matter as long as the ledger is intact. The ledger is the recovery surface.

## Enforcement Boundaries

Questline can enforce state transitions only when Codex uses the MCP tools. The skill therefore says to stop if MCP tools are unavailable.

What is enforced:

- state transition validity;
- state persistence;
- dependency ordering;
- completion checks;
- critic gate completion;
- quest completion requirements.

What is not fully enforced:

- whether the actual implementation work truly satisfies a subjective requirement;
- whether a command result was honestly summarized by the agent;
- whether external systems changed after verification;
- whether a user intentionally edits ledger files by hand.

The critic gate exists to reduce the first risk. The event log exists to make the rest auditable.

## Future Extensions

Potential improvements:

- add a dedicated `questline_next` tool to select the next dependency-ready subgoal;
- add JSON Schema validation for the ledger;
- add event replay to reconstruct `quest.json` from `events.jsonl`;
- add stricter optimistic concurrency with revision ids;
- add a generated status report command;
- support named critic personas stored in plugin config.
