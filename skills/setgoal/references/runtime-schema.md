# Questline Runtime Schema

Store Questline state as JSON. Use stable ids, session namespace isolation, quest instance ids, and append-only event logging so work can resume after context loss without colliding with parallel goals in the same workspace.

```json
{
  "schema_version": 1,
  "quest": {
    "id": "quest-instance-id",
    "slug": "quest-slug",
    "session_id": "session-id",
    "state_path": ".questline/sessions/session-id/quest-instance-id/quest.json",
    "created_at": "ISO-8601 timestamp",
    "updated_at": "ISO-8601 timestamp",
    "status": "clarifying | planned | running | validating | complete | blocked",
    "prompt": "original user prompt",
    "clarified_goal": "one sentence",
    "codex_goal_id": null
  },
  "clarification": {
    "ambiguity": {
      "goal": 0,
      "scope": 0,
      "non_goals": 0,
      "constraints": 0,
      "acceptance": 0,
      "environment": 0,
      "risk": 0
    },
    "assumptions": [],
    "constraints": [],
    "non_goals": [],
    "acceptance_criteria": [],
    "open_questions": []
  },
  "runtime": {
    "active_subgoal": null,
    "completed_subgoals": [],
    "blocked_subgoals": []
  },
  "subgoals": [
    {
      "id": "subgoal-id",
      "title": "Human-readable title",
      "objective": "Workflow-sized objective",
      "depends_on": [],
      "status": "pending | active | validating | critic_review | complete | blocked",
      "deliverables": [],
      "acceptance_checks": [
        {
          "kind": "command | test | file | behavior | screenshot | critic",
          "description": "What proves this worked",
          "command": null,
          "result": "pending | pass | fail | skipped",
          "evidence": null
        }
      ],
      "non_goals": [],
      "needs_critic": false,
      "critic_policy": {
        "persona": null,
        "required": false,
        "last_verdict": null
      },
      "notes": []
    }
  ],
  "final_verification": {
    "status": "pending | pass | fail",
    "evidence": []
  }
}
```

Create or update `.questline/index.json` for discovery:

```json
{
  "schema_version": 1,
  "workspace": "absolute workspace path",
  "sessions": {
    "session-id": {
      "created_at": "ISO-8601 timestamp",
      "updated_at": "ISO-8601 timestamp",
      "quests": [
        {
          "quest_instance_id": "quest-slug-20260531-141522-a1b2c3",
          "slug": "quest-slug",
          "status": "running",
          "state_path": ".questline/sessions/session-id/quest-slug-20260531-141522-a1b2c3/quest.json",
          "clarified_goal": "one sentence"
        }
      ]
    }
  }
}
```

Index rules:

- Treat `quest.json` as the source of truth.
- Use `index.json` only to list and resume quests.
- Update the index after every quest status transition.
- If two sessions use the same slug, keep both because `quest_instance_id` is unique.
- Never infer active quest from slug alone.

Append one JSON object per line to `events.jsonl`:

```json
{
  "timestamp": "ISO-8601 timestamp",
  "type": "clarification_answer | plan_created | subgoal_started | check_passed | check_failed | critic_passed | critic_failed | subgoal_completed | quest_completed | blocked",
  "subgoal_id": null,
  "summary": "short human-readable event",
  "data": {}
}
```

Status transition rules:

- `clarifying -> planned` only after ambiguity is low enough and the clarified goal is restated.
- `planned -> running` when the first dependency-ready subgoal starts.
- `running -> validating` only for final top-level verification.
- `validating -> complete` only when every subgoal is complete and final verification passes.
- Any state may move to `blocked` with a blocker note, but only when no meaningful autonomous progress remains.
