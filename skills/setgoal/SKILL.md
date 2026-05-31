---
name: setgoal
description: Durable questline workflow for Codex. Use when the user invokes the /questline slash command, asks to set a large goal, wants ambiguous prompts clarified into subgoals, or wants autonomous chaining with critic validation until a final goal is reached.
---

# Questline Setgoal

Run a durable "questline" from a vague prompt to a verified outcome.

Invocation forms:

```text
/questline <prompt>
/questline resume
setgoal <prompt>
start a questline for <prompt>
```

## Core Contract

Use Questline to turn one broad user prompt into:

- a clarified top-level goal;
- explicit constraints and out-of-scope items;
- workflow-sized subgoals;
- verification gates for each subgoal;
- critic subagent review when objective verification is weak;
- durable runtime state namespaced by session and quest instance.

Do not treat Codex native goals as a tree. The active runtime supports one Codex goal at a time. Model subgoals in Questline state, and use Codex `create_goal` only for the top-level quest when the user has explicitly invoked `/questline` or asked to set a goal and no active goal already exists.

## State

Never store active quest state directly at `.questline/<quest-slug>`. A single workspace can run multiple Codex sessions and multiple questlines in parallel, so state must be namespaced.

First try to load Questline MCP tools through tool discovery. Questline MCP is the required runtime surface for state changes:

- `questline_create`
- `questline_get`
- `questline_append_event`
- `questline_list`
- `questline_record_clarification`
- `questline_set_plan`
- `questline_start_subgoal`
- `questline_record_check_result`
- `questline_record_critic_result`
- `questline_complete_subgoal`
- `questline_block_subgoal`
- `questline_complete_quest`

If the MCP tools are unavailable, stop and tell the user Questline runtime is unavailable. Do not directly create, edit, or overwrite `.questline/**/quest.json`, `.questline/**/events.jsonl`, or `.questline/index.json` unless the user explicitly requests an unsafe file-based fallback for that session.

Create or resolve a `session_id` for this Codex session:

1. Use an explicit user-provided session name if present.
2. Else use a runtime-provided session/conversation id if available.
3. Else create a local id: `session-<yyyyMMdd-HHmmss>-<6 random hex chars>`.

Create a separate `quest_instance_id` for every `/questline` invocation:

```text
<quest-slug>-<yyyyMMdd-HHmmss>-<6 random hex chars>
```

Create and maintain this file:

```text
<cwd>/.questline/sessions/<session-id>/<quest-instance-id>/quest.json
```

Also append events to:

```text
<cwd>/.questline/sessions/<session-id>/<quest-instance-id>/events.jsonl
```

Maintain a lightweight discovery index:

```text
<cwd>/.questline/index.json
```

The index maps session ids and quest instance ids to their state paths. It is for discovery only; the quest instance file remains the source of truth.

Load [runtime-schema.md](references/runtime-schema.md) before creating or editing the state file.

Persist state after every material transition: clarification answer, analysis, subgoal start, validation result, critic result, completion, or blockage.

Non-skippable runtime rules:

- Use `questline_create` to create the ledger.
- Use `questline_record_clarification` after every clarification round.
- Use `questline_set_plan` to commit the clarified goal and subgoals.
- Use `questline_start_subgoal` before doing subgoal work.
- Use `questline_record_check_result` for every acceptance check.
- Use `questline_record_critic_result` for every critic verdict.
- Use `questline_complete_subgoal`; never mark a subgoal complete by editing JSON.
- Use `questline_block_subgoal` for blocked subgoals.
- Use `questline_complete_quest`; never mark a quest complete by editing JSON.
- Use `questline_append_event` for audit-only events.
- Use `questline_list` before resuming.
- Use `questline_get` to reload state after context loss or before critical transitions.

## Step 1: Clarify

Measure ambiguity before planning. Track these dimensions from 0 to 3:

- `goal`: desired end state;
- `scope`: included work;
- `non_goals`: explicitly excluded work;
- `constraints`: technical, business, time, style, safety, or process limits;
- `acceptance`: observable success criteria;
- `environment`: repo, runtime, tools, APIs, deployment, data;
- `risk`: unknowns that could change implementation.

Ask focused questions until no dimension is above 1, or until the remaining uncertainty can be recorded as an assumption without risking the outcome. Prefer one compact batch of questions, but continue asking if a material ambiguity remains.

Question rules:

- Ask for "do not do" boundaries explicitly.
- Separate facts from decisions. Inspect local files for facts before asking the user.
- For free-text answers, restate the structured interpretation and ask the user to correct missing constraints or non-goals before proceeding.
- Keep an ambiguity ledger visible in state and in brief user updates.

## Step 2: Analyze

Produce a quest plan with workflow-sized subgoals. A subgoal should be large enough to represent meaningful progress, not a tiny implementation step.

Each subgoal must include:

- `id`: stable kebab-case id;
- `title`;
- `objective`;
- `depends_on`;
- `deliverables`;
- `acceptance_checks`;
- `non_goals`;
- `critic_policy`;
- `status`.

Acceptance checks should be executable when possible: commands, tests, file existence, exact behavior, screenshots, type checks, or structured review criteria.

Mark a subgoal as `needs_critic: true` when acceptance is subjective, architectural, design-heavy, strategy-heavy, or otherwise not directly executable.

## Step 3: Initialize Goal Runtime

If no active Codex goal exists and the user explicitly invoked `/questline`, create one top-level Codex goal after the clarified goal is accepted:

```text
Complete questline: <one-sentence clarified goal>
```

Do not try to create Codex goals for every subgoal. Record subgoals in Questline state instead.

Record the current `session_id`, `quest_instance_id`, and state path through `questline_create` before starting work. If multiple quest states exist in the same workspace, only resume one automatically when the current session has exactly one incomplete quest. Otherwise ask the user which quest instance to resume.

Commit subgoals with `questline_set_plan`, then move the first dependency-ready subgoal to `active` with `questline_start_subgoal`.

## Step 4: Progress

Run subgoals in dependency order.

For each active subgoal:

1. State the subgoal being worked on.
2. Implement or perform the work.
3. Run its acceptance checks.
4. Record every check with `questline_record_check_result`.
5. If checks pass and no critic is needed, call `questline_complete_subgoal`.
6. If checks fail, keep the subgoal active and fix.
7. If blocked, call `questline_block_subgoal` and either choose an unblocked subgoal or ask the user only when no meaningful progress remains.

After each completed subgoal, activate the next dependency-ready subgoal. Continue until all subgoals are complete or the quest is blocked.

## Critic Gate

When a subgoal has `needs_critic: true`, spawn a critic subagent after implementation and before completion.

Persona selection:

- If the user provided a critic persona, use it verbatim unless unsafe.
- Otherwise use: "Skeptical senior reviewer. Prioritize gaps, regressions, unverifiable claims, hidden assumptions, and missing tests. Do not praise. Return blocking findings first."

Critic prompt shape:

```text
You are the critic for Questline subgoal <id>.

Persona:
<persona>

Objective:
<subgoal objective>

Deliverables:
<deliverables>

Acceptance checks:
<checks and results>

State file:
<quest.json path>

Review the result critically. Return:
- blocking findings;
- non-blocking risks;
- missing verification;
- verdict: pass or fail.
```

Record the critic verdict with `questline_record_critic_result`. If the critic returns `fail`, do not mark the subgoal complete. Address blocking findings, persist the result, and run the critic gate again when appropriate.

## Completion

The quest is complete only when:

- all subgoals are `complete`;
- all required critic gates have verdict `pass`;
- final top-level acceptance criteria are satisfied;
- final state is persisted.

Call `questline_complete_quest` with final evidence. Then mark the Codex goal `complete` if the active Codex goal corresponds to this quest.

## User Interaction Policy

The user should primarily participate in Step 1. After clarification and restatement, proceed autonomously through analysis, subgoal initialization, progress, and validation.

Ask the user later only when:

- a decision cannot be inferred safely;
- every available path is blocked;
- the requested work would exceed or violate clarified constraints;
- a critic finding exposes a product or scope decision that only the user can make.
