from __future__ import annotations

import json
import os
import random
import re
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("questline")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def rand_hex(n: int = 6) -> str:
    return "".join(random.choice("0123456789abcdef") for _ in range(n))


def slugify(value: str, fallback: str = "quest") -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    return (slug or fallback)[:64]


def workspace_root(cwd: str) -> Path:
    return Path(cwd).expanduser().resolve()


def questline_root(cwd: str) -> Path:
    return workspace_root(cwd) / ".questline"


@contextmanager
def file_lock(path: Path, timeout_s: float = 10.0):
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    fd = None
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
            break
        except FileExistsError:
            if time.time() - start > timeout_s:
                raise TimeoutError(f"Timed out waiting for lock: {lock_path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.{rand_hex()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def append_jsonl(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def index_path(cwd: str) -> Path:
    return questline_root(cwd) / "index.json"


def default_index(cwd: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "workspace": str(workspace_root(cwd)),
        "sessions": {},
    }


def quest_paths(cwd: str, session_id: str, quest_instance_id: str) -> tuple[Path, Path]:
    base = questline_root(cwd) / "sessions" / session_id / quest_instance_id
    return base / "quest.json", base / "events.jsonl"


def update_index(cwd: str, quest: dict[str, Any]) -> None:
    path = index_path(cwd)
    with file_lock(path):
        index = read_json(path, default_index(cwd))
        session_id = quest["quest"]["session_id"]
        session = index.setdefault("sessions", {}).setdefault(
            session_id,
            {"created_at": now_iso(), "updated_at": now_iso(), "quests": []},
        )
        session["updated_at"] = now_iso()
        entry = {
            "quest_instance_id": quest["quest"]["id"],
            "slug": quest["quest"]["slug"],
            "status": quest["quest"]["status"],
            "state_path": quest["quest"]["state_path"],
            "clarified_goal": quest["quest"].get("clarified_goal"),
        }
        quests = [q for q in session.get("quests", []) if q.get("quest_instance_id") != entry["quest_instance_id"]]
        quests.append(entry)
        session["quests"] = quests
        write_json_atomic(path, index)


def load_state(cwd: str, session_id: str, quest_instance_id: str) -> tuple[dict[str, Any], Path, Path]:
    quest_path, events_path = quest_paths(cwd, session_id, quest_instance_id)
    state = read_json(quest_path, None)
    if state is None:
        raise FileNotFoundError(str(quest_path))
    return state, quest_path, events_path


def save_transition(
    cwd: str,
    state: dict[str, Any],
    quest_path: Path,
    events_path: Path,
    event_type: str,
    summary: str,
    data: dict[str, Any] | None = None,
    subgoal_id: str | None = None,
) -> dict[str, Any]:
    state["quest"]["updated_at"] = now_iso()
    write_json_atomic(quest_path, state)
    append_jsonl(events_path, {
        "timestamp": now_iso(),
        "type": event_type,
        "subgoal_id": subgoal_id,
        "summary": summary,
        "data": data or {},
    })
    update_index(cwd, state)
    return {"state": state, "quest_path": str(quest_path)}


def find_subgoal(state: dict[str, Any], subgoal_id: str) -> dict[str, Any]:
    for subgoal in state.get("subgoals", []):
        if subgoal.get("id") == subgoal_id:
            return subgoal
    raise ValueError(f"Unknown subgoal: {subgoal_id}")


def completed_subgoal_ids(state: dict[str, Any]) -> set[str]:
    return {s["id"] for s in state.get("subgoals", []) if s.get("status") == "complete"}


def validate_subgoals(subgoals: list[dict[str, Any]]) -> None:
    ids = [s.get("id") for s in subgoals]
    if not ids or any(not i for i in ids):
        raise ValueError("Plan must include at least one subgoal and every subgoal needs an id")
    if len(set(ids)) != len(ids):
        raise ValueError("Subgoal ids must be unique")
    known = set(ids)
    for subgoal in subgoals:
        for dep in subgoal.get("depends_on", []):
            if dep not in known:
                raise ValueError(f"Subgoal {subgoal.get('id')} depends on unknown subgoal {dep}")
        checks = subgoal.get("acceptance_checks", [])
        if not checks:
            raise ValueError(f"Subgoal {subgoal.get('id')} must include acceptance_checks")
        subgoal.setdefault("status", "pending")
        subgoal.setdefault("deliverables", [])
        subgoal.setdefault("non_goals", [])
        subgoal.setdefault("needs_critic", False)
        subgoal.setdefault("notes", [])
        subgoal.setdefault("critic_policy", {
            "persona": None,
            "required": bool(subgoal.get("needs_critic")),
            "last_verdict": None,
        })
        subgoal["critic_policy"]["required"] = bool(subgoal.get("needs_critic") or subgoal["critic_policy"].get("required"))
        for check in checks:
            check.setdefault("result", "pending")
            check.setdefault("evidence", None)


def checks_satisfied(subgoal: dict[str, Any]) -> bool:
    checks = subgoal.get("acceptance_checks", [])
    return bool(checks) and all(c.get("result") in {"pass", "skipped"} for c in checks)


def critic_satisfied(subgoal: dict[str, Any]) -> bool:
    policy = subgoal.get("critic_policy", {})
    return not policy.get("required") or policy.get("last_verdict") == "pass"


def make_session_id(session_id: str | None) -> str:
    if session_id:
        return slugify(session_id, "session")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"session-{stamp}-{rand_hex()}"


def make_quest_instance_id(slug: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{slug}-{stamp}-{rand_hex()}"


@mcp.tool()
def questline_create(cwd: str, prompt: str, session_id: str | None = None, slug: str | None = None) -> dict[str, Any]:
    """Create a session-scoped Questline ledger and return its paths."""
    resolved_session_id = make_session_id(session_id)
    quest_slug = slugify(slug or prompt[:48])
    quest_instance_id = make_quest_instance_id(quest_slug)
    quest_path, events_path = quest_paths(cwd, resolved_session_id, quest_instance_id)
    rel_state_path = str(quest_path.relative_to(workspace_root(cwd))).replace("\\", "/")
    created = now_iso()
    state = {
        "schema_version": 1,
        "quest": {
            "id": quest_instance_id,
            "slug": quest_slug,
            "session_id": resolved_session_id,
            "state_path": rel_state_path,
            "created_at": created,
            "updated_at": created,
            "status": "clarifying",
            "prompt": prompt,
            "clarified_goal": None,
            "codex_goal_id": None,
        },
        "clarification": {
            "ambiguity": {
                "goal": 3,
                "scope": 3,
                "non_goals": 3,
                "constraints": 3,
                "acceptance": 3,
                "environment": 3,
                "risk": 3,
            },
            "assumptions": [],
            "constraints": [],
            "non_goals": [],
            "acceptance_criteria": [],
            "open_questions": [],
        },
        "runtime": {
            "active_subgoal": None,
            "completed_subgoals": [],
            "blocked_subgoals": [],
        },
        "subgoals": [],
        "final_verification": {
            "status": "pending",
            "evidence": [],
        },
    }
    with file_lock(quest_path):
        write_json_atomic(quest_path, state)
        append_jsonl(events_path, {
            "timestamp": created,
            "type": "quest_created",
            "subgoal_id": None,
            "summary": "Questline ledger created",
            "data": {"prompt": prompt},
        })
    update_index(cwd, state)
    return {"state": state, "quest_path": str(quest_path), "events_path": str(events_path)}


@mcp.tool()
def questline_get(cwd: str, session_id: str, quest_instance_id: str) -> dict[str, Any]:
    """Read a Questline ledger by session id and quest instance id."""
    quest_path, events_path = quest_paths(cwd, session_id, quest_instance_id)
    return {
        "state": read_json(quest_path, None),
        "quest_path": str(quest_path),
        "events_path": str(events_path),
    }


def questline_update(cwd: str, session_id: str, quest_instance_id: str, patch: dict[str, Any], event_type: str = "state_updated", summary: str = "Questline state updated") -> dict[str, Any]:
    """Internal escape hatch. Do not expose as an MCP tool."""
    quest_path, events_path = quest_paths(cwd, session_id, quest_instance_id)
    with file_lock(quest_path):
        state = read_json(quest_path, None)
        if state is None:
            raise FileNotFoundError(str(quest_path))
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(state.get(key), dict):
                state[key].update(value)
            else:
                state[key] = value
        state["quest"]["updated_at"] = now_iso()
        write_json_atomic(quest_path, state)
        append_jsonl(events_path, {
            "timestamp": now_iso(),
            "type": event_type,
            "subgoal_id": patch.get("runtime", {}).get("active_subgoal") if isinstance(patch.get("runtime"), dict) else None,
            "summary": summary,
            "data": {"patch": patch},
        })
    update_index(cwd, state)
    return {"state": state, "quest_path": str(quest_path)}


@mcp.tool()
def questline_record_clarification(
    cwd: str,
    session_id: str,
    quest_instance_id: str,
    ambiguity: dict[str, int],
    assumptions: list[str] | None = None,
    constraints: list[str] | None = None,
    non_goals: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    open_questions: list[str] | None = None,
) -> dict[str, Any]:
    """Record clarified scope and ambiguity scores."""
    required = {"goal", "scope", "non_goals", "constraints", "acceptance", "environment", "risk"}
    if set(ambiguity) != required:
        raise ValueError(f"Ambiguity must include exactly: {sorted(required)}")
    for key, value in ambiguity.items():
        if not isinstance(value, int) or value < 0 or value > 3:
            raise ValueError(f"Ambiguity score for {key} must be an integer from 0 to 3")
    quest_path, events_path = quest_paths(cwd, session_id, quest_instance_id)
    with file_lock(quest_path):
        state, quest_path, events_path = load_state(cwd, session_id, quest_instance_id)
        if state["quest"]["status"] not in {"clarifying", "planned"}:
            raise ValueError("Clarification can only be recorded before the quest is running")
        state["clarification"] = {
            "ambiguity": ambiguity,
            "assumptions": assumptions or [],
            "constraints": constraints or [],
            "non_goals": non_goals or [],
            "acceptance_criteria": acceptance_criteria or [],
            "open_questions": open_questions or [],
        }
        return save_transition(
            cwd,
            state,
            quest_path,
            events_path,
            "clarification_answer",
            "Clarification state recorded",
            {"ambiguity": ambiguity},
        )


@mcp.tool()
def questline_set_plan(
    cwd: str,
    session_id: str,
    quest_instance_id: str,
    clarified_goal: str,
    subgoals: list[dict[str, Any]],
    codex_goal_id: str | None = None,
) -> dict[str, Any]:
    """Set the clarified goal and validated subgoal plan."""
    validate_subgoals(subgoals)
    quest_path, events_path = quest_paths(cwd, session_id, quest_instance_id)
    with file_lock(quest_path):
        state, quest_path, events_path = load_state(cwd, session_id, quest_instance_id)
        if state["quest"]["status"] not in {"clarifying", "planned"}:
            raise ValueError("Plan can only be set before the quest is running")
        ambiguity = state.get("clarification", {}).get("ambiguity", {})
        too_ambiguous = {k: v for k, v in ambiguity.items() if v > 1}
        if too_ambiguous:
            raise ValueError(f"Cannot set plan while ambiguity scores exceed 1: {too_ambiguous}")
        state["quest"]["clarified_goal"] = clarified_goal
        state["quest"]["codex_goal_id"] = codex_goal_id
        state["quest"]["status"] = "planned"
        state["subgoals"] = subgoals
        state["runtime"] = {
            "active_subgoal": None,
            "completed_subgoals": [],
            "blocked_subgoals": [],
        }
        return save_transition(
            cwd,
            state,
            quest_path,
            events_path,
            "plan_created",
            "Validated subgoal plan created",
            {"subgoal_ids": [s["id"] for s in subgoals]},
        )


@mcp.tool()
def questline_start_subgoal(cwd: str, session_id: str, quest_instance_id: str, subgoal_id: str) -> dict[str, Any]:
    """Start a dependency-ready subgoal."""
    quest_path, events_path = quest_paths(cwd, session_id, quest_instance_id)
    with file_lock(quest_path):
        state, quest_path, events_path = load_state(cwd, session_id, quest_instance_id)
        if state["quest"]["status"] not in {"planned", "running"}:
            raise ValueError("Subgoals can only start from planned or running quests")
        active = state.get("runtime", {}).get("active_subgoal")
        if active and active != subgoal_id:
            raise ValueError(f"Another subgoal is already active: {active}")
        subgoal = find_subgoal(state, subgoal_id)
        if subgoal.get("status") not in {"pending", "active"}:
            raise ValueError(f"Subgoal {subgoal_id} cannot be started from status {subgoal.get('status')}")
        missing = [dep for dep in subgoal.get("depends_on", []) if dep not in completed_subgoal_ids(state)]
        if missing:
            raise ValueError(f"Subgoal {subgoal_id} has incomplete dependencies: {missing}")
        state["quest"]["status"] = "running"
        state["runtime"]["active_subgoal"] = subgoal_id
        subgoal["status"] = "active"
        return save_transition(cwd, state, quest_path, events_path, "subgoal_started", f"Started subgoal {subgoal_id}", subgoal_id=subgoal_id)


@mcp.tool()
def questline_record_check_result(
    cwd: str,
    session_id: str,
    quest_instance_id: str,
    subgoal_id: str,
    check_index: int,
    result: str,
    evidence: str,
) -> dict[str, Any]:
    """Record an acceptance check result for a subgoal."""
    if result not in {"pass", "fail", "skipped"}:
        raise ValueError("result must be pass, fail, or skipped")
    quest_path, events_path = quest_paths(cwd, session_id, quest_instance_id)
    with file_lock(quest_path):
        state, quest_path, events_path = load_state(cwd, session_id, quest_instance_id)
        subgoal = find_subgoal(state, subgoal_id)
        checks = subgoal.get("acceptance_checks", [])
        if check_index < 0 or check_index >= len(checks):
            raise IndexError(f"check_index out of range for {subgoal_id}")
        checks[check_index]["result"] = result
        checks[check_index]["evidence"] = evidence
        event_type = "check_passed" if result in {"pass", "skipped"} else "check_failed"
        return save_transition(
            cwd,
            state,
            quest_path,
            events_path,
            event_type,
            f"Acceptance check {check_index} for {subgoal_id}: {result}",
            {"check_index": check_index, "result": result, "evidence": evidence},
            subgoal_id=subgoal_id,
        )


@mcp.tool()
def questline_record_critic_result(
    cwd: str,
    session_id: str,
    quest_instance_id: str,
    subgoal_id: str,
    verdict: str,
    findings: list[str],
    persona: str | None = None,
) -> dict[str, Any]:
    """Record critic verdict and findings for a subgoal."""
    if verdict not in {"pass", "fail"}:
        raise ValueError("verdict must be pass or fail")
    quest_path, events_path = quest_paths(cwd, session_id, quest_instance_id)
    with file_lock(quest_path):
        state, quest_path, events_path = load_state(cwd, session_id, quest_instance_id)
        subgoal = find_subgoal(state, subgoal_id)
        policy = subgoal.setdefault("critic_policy", {"persona": None, "required": True, "last_verdict": None})
        policy["required"] = True
        if persona:
            policy["persona"] = persona
        policy["last_verdict"] = verdict
        subgoal.setdefault("notes", []).append({"critic_verdict": verdict, "findings": findings, "timestamp": now_iso()})
        if verdict == "fail":
            subgoal["status"] = "active"
        event_type = "critic_passed" if verdict == "pass" else "critic_failed"
        return save_transition(
            cwd,
            state,
            quest_path,
            events_path,
            event_type,
            f"Critic verdict for {subgoal_id}: {verdict}",
            {"findings": findings, "persona": persona},
            subgoal_id=subgoal_id,
        )


@mcp.tool()
def questline_complete_subgoal(cwd: str, session_id: str, quest_instance_id: str, subgoal_id: str) -> dict[str, Any]:
    """Complete a subgoal only when checks and required critic gates pass."""
    quest_path, events_path = quest_paths(cwd, session_id, quest_instance_id)
    with file_lock(quest_path):
        state, quest_path, events_path = load_state(cwd, session_id, quest_instance_id)
        subgoal = find_subgoal(state, subgoal_id)
        if not checks_satisfied(subgoal):
            raise ValueError(f"Subgoal {subgoal_id} cannot complete until all acceptance checks pass or are skipped")
        if not critic_satisfied(subgoal):
            raise ValueError(f"Subgoal {subgoal_id} requires a passing critic verdict")
        subgoal["status"] = "complete"
        runtime = state["runtime"]
        runtime["active_subgoal"] = None if runtime.get("active_subgoal") == subgoal_id else runtime.get("active_subgoal")
        if subgoal_id not in runtime["completed_subgoals"]:
            runtime["completed_subgoals"].append(subgoal_id)
        return save_transition(cwd, state, quest_path, events_path, "subgoal_completed", f"Completed subgoal {subgoal_id}", subgoal_id=subgoal_id)


@mcp.tool()
def questline_block_subgoal(cwd: str, session_id: str, quest_instance_id: str, subgoal_id: str, reason: str) -> dict[str, Any]:
    """Mark a subgoal blocked with a concrete reason."""
    quest_path, events_path = quest_paths(cwd, session_id, quest_instance_id)
    with file_lock(quest_path):
        state, quest_path, events_path = load_state(cwd, session_id, quest_instance_id)
        subgoal = find_subgoal(state, subgoal_id)
        subgoal["status"] = "blocked"
        subgoal.setdefault("notes", []).append({"blocked_reason": reason, "timestamp": now_iso()})
        runtime = state["runtime"]
        runtime["active_subgoal"] = None if runtime.get("active_subgoal") == subgoal_id else runtime.get("active_subgoal")
        if subgoal_id not in runtime["blocked_subgoals"]:
            runtime["blocked_subgoals"].append(subgoal_id)
        if not any(s.get("status") in {"pending", "active"} for s in state.get("subgoals", [])):
            state["quest"]["status"] = "blocked"
        return save_transition(cwd, state, quest_path, events_path, "blocked", f"Blocked subgoal {subgoal_id}", {"reason": reason}, subgoal_id=subgoal_id)


@mcp.tool()
def questline_complete_quest(cwd: str, session_id: str, quest_instance_id: str, evidence: list[str]) -> dict[str, Any]:
    """Complete a quest only when all subgoals are complete and final evidence is present."""
    if not evidence:
        raise ValueError("Final verification evidence is required")
    quest_path, events_path = quest_paths(cwd, session_id, quest_instance_id)
    with file_lock(quest_path):
        state, quest_path, events_path = load_state(cwd, session_id, quest_instance_id)
        incomplete = [s["id"] for s in state.get("subgoals", []) if s.get("status") != "complete"]
        if incomplete:
            raise ValueError(f"Cannot complete quest with incomplete subgoals: {incomplete}")
        state["quest"]["status"] = "complete"
        state["final_verification"] = {"status": "pass", "evidence": evidence}
        return save_transition(cwd, state, quest_path, events_path, "quest_completed", "Quest completed", {"evidence": evidence})


@mcp.tool()
def questline_append_event(cwd: str, session_id: str, quest_instance_id: str, event_type: str, summary: str, data: dict[str, Any] | None = None, subgoal_id: str | None = None) -> dict[str, Any]:
    """Append an event without changing quest state."""
    _, events_path = quest_paths(cwd, session_id, quest_instance_id)
    event = {
        "timestamp": now_iso(),
        "type": event_type,
        "subgoal_id": subgoal_id,
        "summary": summary,
        "data": data or {},
    }
    append_jsonl(events_path, event)
    return {"event": event, "events_path": str(events_path)}


@mcp.tool()
def questline_list(cwd: str, session_id: str | None = None, include_completed: bool = False) -> dict[str, Any]:
    """List known Questline ledgers in this workspace."""
    index = read_json(index_path(cwd), default_index(cwd))
    sessions = index.get("sessions", {})
    if session_id:
        sessions = {session_id: sessions.get(session_id, {"quests": []})}
    if not include_completed:
        filtered = {}
        for sid, session in sessions.items():
            quests = [q for q in session.get("quests", []) if q.get("status") != "complete"]
            if quests:
                filtered[sid] = {**session, "quests": quests}
        sessions = filtered
    return {"workspace": index.get("workspace"), "sessions": sessions}


if __name__ == "__main__":
    mcp.run()
