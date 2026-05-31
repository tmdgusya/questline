# Questline

Questline is a local Codex plugin for turning vague prompts into durable, verified goal chains.

It provides:

- a `/questline` slash command backed by the `setgoal` skill;
- clarification of ambiguity, constraints, non-goals, and acceptance criteria;
- workflow-sized subgoals stored in a session-scoped ledger;
- MCP tools that enforce guarded state transitions;
- critic validation for subjective or hard-to-verify subgoals.

## Structure

```text
.codex-plugin/plugin.json
.mcp.json
scripts/questline_mcp.py
commands/questline.md
skills/setgoal/SKILL.md
skills/setgoal/references/runtime-schema.md
```

## Runtime Model

Questline separates policy, runtime, and storage:

```text
Skill instructions -> MCP state machine -> durable JSON ledger
```

State is stored per workspace, session, and quest instance:

```text
.questline/sessions/<session-id>/<quest-instance-id>/quest.json
.questline/sessions/<session-id>/<quest-instance-id>/events.jsonl
.questline/index.json
```

The MCP runtime rejects invalid transitions such as completing a subgoal before checks pass, skipping required critic review, or completing a quest while subgoals remain incomplete.

See [Architecture](docs/architecture.md) for the full runtime model, state layout, transition rules, and enforcement boundaries.

## Install

For local development with Codex:

```powershell
codex plugin add questline@personal
```

Start a new Codex thread after reinstalling so the plugin skills and MCP tools are reloaded.

## Usage

Start a new quest:

```text
/questline refactor this repository's authentication flow, but keep the existing API response shape
```

Resume an existing quest:

```text
/questline resume
```
