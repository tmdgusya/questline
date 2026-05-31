---
name: questline
description: Start or resume a Questline durable goal chain with clarification, subgoals, guarded runtime state, and critic validation.
---

# Questline

The user invoked this command with: $ARGUMENTS

Use this command to start or resume a durable Questline run.

## Required Runtime

Questline requires its MCP runtime tools. Before doing Questline work, confirm the Questline MCP tools are available:

- `questline_create`
- `questline_get`
- `questline_list`
- `questline_append_event`
- `questline_record_clarification`
- `questline_set_plan`
- `questline_start_subgoal`
- `questline_record_check_result`
- `questline_record_critic_result`
- `questline_complete_subgoal`
- `questline_block_subgoal`
- `questline_complete_quest`

If these tools are unavailable, stop and report that the Questline runtime is unavailable. Do not directly edit `.questline/**` files unless the user explicitly asks for unsafe file-based fallback.

## Skill Instructions

Load and follow `skills/setgoal/SKILL.md`. It is the policy layer for:

- clarification;
- ambiguity scoring;
- constraints and non-goals;
- subgoal planning;
- critic validation;
- completion rules.

Also load `skills/setgoal/references/runtime-schema.md` before creating or interpreting ledger state.

## Command Behavior

If `$ARGUMENTS` is empty, ask the user for the goal they want Questline to manage.

If `$ARGUMENTS` asks to resume, continue an existing quest:

1. call `questline_list`;
2. if exactly one incomplete quest exists for the current session, call `questline_get` and continue;
3. if multiple incomplete quests exist, ask the user which quest instance to resume.

Otherwise start a new quest:

1. call `questline_create` with `$ARGUMENTS` as the original prompt;
2. clarify ambiguity until all scores are 1 or lower;
3. record clarification with `questline_record_clarification`;
4. create a subgoal plan with `questline_set_plan`;
5. execute dependency-ready subgoals with the guarded transition tools;
6. use critic review for subjective or hard-to-verify subgoals;
7. complete the quest only through `questline_complete_quest`.

## Output

Keep user-facing updates concise. Always mention the active quest id and active subgoal when work starts or resumes.
