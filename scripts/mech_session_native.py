#!/usr/bin/env python3
"""Read native agy goal snapshots; never write to source SQLite files.
Minimal protobuf wire reader, constrained to installed schema fields and public text.
"""

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path.home() / ".gemini/antigravity-cli"
ANY_TYPE = b"type.googleapis.com/exa.cortex_pb.GoalState"


def varint(b, i):
    n = 0
    for shift in range(0, 70, 7):
        v = b[i]
        i += 1
        n |= (v & 127) << shift
        if not v & 128:
            return n, i
    raise ValueError("oversized varint")


def fields(b):
    out = []
    i = 0
    while i < len(b):
        tag, i = varint(b, i)
        num, wire = tag >> 3, tag & 7
        if num < 1:
            raise ValueError("invalid field")
        if wire == 0:
            v, i = varint(b, i)
        elif wire == 2:
            size, i = varint(b, i)
            if i + size > len(b):
                raise ValueError("overflow")
            v = b[i : i + size]
            i += size
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            v = b[i : i + size]
            i += size
            if i > len(b):
                raise ValueError("overflow")
        else:
            raise ValueError("unsupported wire")
        out.append((num, wire, v))
    return out


def one(b, n, default=None):
    return next((v for k, w, v in fields(b) if k == n), default)


def text(b):
    return b.decode("utf-8") if isinstance(b, bytes) else b


def stamp(b):
    if not b:
        return None
    sec = one(b, 1, 0)
    ns = one(b, 2, 0)
    return datetime.fromtimestamp(sec + ns / 1e9, timezone.utc).isoformat()


def goal(b):
    return {
        "goal_text": text(one(b, 1, b"")),
        "started_at": stamp(one(b, 2)),
        "start_step_index": one(b, 3, 0),
        "continuation_count": one(b, 4, 0),
        "state_number": one(b, 5, 0),
        "state": {0: "unknown", 1: "active", 2: "completed", 3: "cancelled"}.get(
            one(b, 5, 0), "unrecognized"
        ),
    }


def find_goals(b, path=()):
    if ANY_TYPE not in b:
        return []
    try:
        f = fields(b)
    except (ValueError, IndexError):
        return []
    if any(n == 1 and v == ANY_TYPE for n, w, v in f):
        return [
            dict(goal(next(v for n, w, v in f if n == 2)), protobuf_path=list(path))
        ]
    out = []
    for n, w, v in f:
        if w == 2 and ANY_TYPE in v:
            out += find_goals(v, path + (n,))
    return out


@contextmanager
def snapshot(p):
    # Copy database and any WAL/SHM, verify stable sizes and mtimes across copy.
    # Retry active writes; no native SQLite connection, therefore no sidecar writes.
    def source_files():
        result = {}
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(p) + suffix)
            try:
                stat = path.stat()
            except FileNotFoundError:
                if not suffix:
                    raise
                continue
            result[str(path)] = (
                stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns
            )
        return result

    for attempt in range(5):
        # Every exit path removes private copies, including copying, connecting,
        # PRAGMA setup, and exceptions raised by the reader using the snapshot.
        with tempfile.TemporaryDirectory(prefix="agy-goal-read-") as directory:
            td = Path(directory)
            try:
                before = source_files()
                for source in before:
                    shutil.copy2(source, td / Path(source).name)
                after = source_files()
            except FileNotFoundError:
                # SQLite may remove a WAL/SHM between stat and copy/checkpoint.
                continue
            if before != after:
                continue
            c = sqlite3.connect(str(td / p.name))
            try:
                c.execute("PRAGMA query_only=ON")
                yield c, {
                    "snapshot_stable": True,
                    "native_files": before,
                    "attempts": attempt + 1,
                }
                return
            finally:
                c.close()
    raise RuntimeError("native database changed or disappeared during every snapshot attempt")


STATUS_NAMES = {
    0: "unspecified",
    1: "pending",
    2: "running",
    3: "done",
    4: "invalid",
    5: "cleared",
    6: "cancelled",
    7: "error",
    8: "generating",
    9: "waiting",
    11: "queued",
    12: "interrupted",
}
GOAL_DECLARATION = b"The user has marked this task with /goal"
COMPLETE = "<!-- GOAL_COMPLETE -->"
CANCELLED = "<!-- GOAL_CANCELLED -->"


def metadata_times(payload):
    md = one(payload, 5, b"")
    return {"created_at": stamp(one(md, 1)), "completed_at": stamp(one(md, 8))}


def public_response(payload):
    body = one(payload, 20, b"")
    return text(one(body, 8) or one(body, 1, b""))


def user_parts(payload):
    body = one(payload, 19, b"")
    parts = []
    for n, w, item in fields(body):
        if n == 3 and w == 2:
            value = one(item, 1)
            if isinstance(value, bytes):
                try:
                    parts.append(value.decode("utf-8"))
                except UnicodeError:
                    pass
    legacy = one(body, 1)
    if legacy:
        parts.append(text(legacy))
    return parts


def native_goal_declaration(payload):
    # Installed schema: UserInput.items[3] -> TextOrScopeItem.item[2] ->
    # ContextScopeItem.slash_command[27] -> SlashCommandScopeItem.info[1].
    # SlashCommandInfo: name[1], model_facing_text[2], type[3] (SYSTEM=1).
    # Public text and attached files may quote the same words without /goal.
    for number, wire, item in fields(one(payload, 19, b"")):
        if number != 3 or wire != 2:
            continue
        scope = one(item, 2, b"")
        command = one(scope, 27, b"")
        info = one(command, 1, b"")
        if (
            one(info, 1) == b"goal"
            and one(info, 3) == 1
            and one(info, 2, b"").startswith(GOAL_DECLARATION)
        ):
            return True
    return False


def terminal_marker(visible):
    """Accept only a column-zero native marker outside recognized code fences.

    Trailing horizontal whitespace and blank lines are harmless. Indented or
    container-prefixed marker lines are never control messages, including those
    inside list-item fences. This intentionally accepts less than general
    Markdown: ambiguous fence/container combinations remain nonterminal.
    """
    lines = visible.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return None
    marker = re.fullmatch(r"(<!-- GOAL_(?:COMPLETE|CANCELLED) -->)[ \t]*", lines[-1])
    if not marker:
        return None
    fence = None
    for line in lines[:-1]:
        delimiter = re.match(r" {0,3}(`{3,}|~{3,})(.*)$", line)
        if not delimiter:
            continue
        run, trailing = delimiter.groups()
        if fence:
            if run[0] == fence[0] and len(run) >= fence[1] and not trailing.strip():
                fence = None
        elif run[0] != "`" or "`" not in trailing:
            fence = (run[0], len(run))
    return None if fence else marker[1]


def select_current_goal(
    checkpoint_goals, checkpoint_idx, declarations, terminal_events
):
    goals = {}
    for g in checkpoint_goals:
        key = g["start_step_index"]
        if key in goals:
            for field in ["goal_text", "started_at", "state"]:
                if goals[key].get(field) != g.get(field):
                    raise ValueError("conflicting duplicate goal state in checkpoint")
        goals[key] = dict(g)
    for g in declarations:
        goals[g["start_step_index"]] = dict(g)
    if not goals:
        return None
    current = dict(goals[max(goals)])
    current["goal_id"] = "goal-" + str(current["start_step_index"])
    current["checkpoint_state"] = current["state"]
    cutoff = max(checkpoint_idx, current["start_step_index"])
    current["replay_after_step_index"] = cutoff
    current["state_evidence"] = "checkpoint_snapshot_or_native_declaration"
    eligible = sorted(
        (e for e in terminal_events if e["step_index"] > cutoff),
        key=lambda e: e["step_index"],
    )
    # A later authoritative active checkpoint can represent a resumed goal. Older markers must not override it.
    # Once native goal reaches a terminal state, ordinary later replies cannot reopen or cancel it.
    if current["state"] == "active" and eligible:
        event = eligible[0]
        current["state"] = event["event"]
        current["state_number"] = 2 if event["event"] == "completed" else 3
        current["state_evidence"] = "completed_assistant_marker_after_checkpoint"
        current["completion_event"] = event
    elif current["state"] in {"completed", "cancelled"}:
        prior = [
            e
            for e in terminal_events
            if current["start_step_index"] < e["step_index"] <= checkpoint_idx
            and e["event"] == current["state"]
        ]
        if prior:
            current["completion_event"] = dict(
                max(prior, key=lambda e: e["step_index"]), historical_marker=True
            )
    return current


def inspect(repo, cid):
    repo = str(repo)
    if not cid or Path(cid).name != cid or "/" in cid or "\\" in cid:
        raise ValueError("invalid native conversation ID")
    p = ROOT / "conversations" / f"{cid}.db"
    with snapshot(p) as (c, source):
        trajectory = c.execute("select * from trajectory_meta").fetchall()
        if len(trajectory) != 1 or trajectory[0][1] != cid:
            raise ValueError("native conversation identity mismatch")
        metadata = c.execute(
            "select data from trajectory_metadata_blob where id=?", ("main",)
        ).fetchone()
        workspace_uri = text(one(metadata[0], 7, b"")) if metadata else ""
        parsed = urlparse(workspace_uri)
        if (
            parsed.scheme != "file"
            or Path(unquote(parsed.path)).resolve() != Path(repo).resolve()
        ):
            raise ValueError("native workspace identity mismatch")
        latest = c.execute(
            "select idx,step_type,status,step_payload from steps order by idx desc limit 1"
        ).fetchone()
        if latest is None:
            raise ValueError("native conversation has no steps")
        last_goal = c.execute(
            "select idx,step_type,status,step_payload from steps where step_type=23 and status=3 and instr(step_payload,?)>0 order by idx desc limit 1",
            (ANY_TYPE,),
        ).fetchone()
        row = {
            "repository": Path(repo).name,
            "root": repo,
            "conversation_id": cid,
            "source_database": str(p),
            "snapshot": source,
            "trajectory": trajectory,
            "workspace_identity": {"verified": True, "uri": workspace_uri},
            "last_step": {
                "index": latest[0],
                "type_number": latest[1],
                "status_number": latest[2],
                "status": STATUS_NAMES.get(latest[2], "unrecognized"),
                **metadata_times(latest[3]),
            },
            "latest_goal_snapshot": None,
        }
        goals = {}
        if last_goal:
            gs = find_goals(last_goal[3])
            for g in gs:
                goals[g["start_step_index"]] = g
            row["latest_goal_snapshot"] = {
                "step_index": last_goal[0],
                "step_type": last_goal[1],
                "goals": gs,
            }
        # Native user goal declarations after the checkpoint may not have an accumulated snapshot yet.
        checkpoint_idx = last_goal[0] if last_goal else -1
        declarations = []
        for idx, status, payload in c.execute(
            "select idx,status,step_payload from steps where step_type=14 and status=3 and idx>? order by idx",
            (checkpoint_idx,),
        ):
            if native_goal_declaration(payload):
                parts = user_parts(payload)
                if parts:
                    goals[idx] = {
                        "goal_text": "\n".join(parts)
                        .strip()
                        .removeprefix("/goal")
                        .strip(),
                        "started_at": metadata_times(payload)["created_at"],
                        "start_step_index": idx,
                        "continuation_count": None,
                        "state": "active",
                        "state_number": 1,
                        "source": "native_user_goal_declaration",
                    }
                    declarations.append(goals[idx])
        current = dict(goals[max(goals)]) if goals else None
        row["current_goal"] = current
        if current:
            current["goal_id"] = "goal-" + str(current["start_step_index"])
            current["checkpoint_state"] = current["state"]
            # Replay only completed assistant public output, not tool results/user quotes/hidden reasoning.
            events = []
            for idx, payload in c.execute(
                "select idx,step_payload from steps where step_type=15 and status=3 and idx>? order by idx",
                (current["start_step_index"],),
            ):
                visible = public_response(payload)
                marker = terminal_marker(visible)
                if marker:
                    events.append(
                        {
                            "step_index": idx,
                            "event": "completed" if marker == COMPLETE else "cancelled",
                            "marker": marker,
                            "text_sha256": hashlib.sha256(visible.encode()).hexdigest(),
                            **metadata_times(payload),
                        }
                    )
            current = select_current_goal(
                gs if last_goal else [], checkpoint_idx, declarations, events
            )
            row["current_goal"] = current
            row["goal_terminal_events"] = events
        public = []
        for idx, st, payload in c.execute(
            "select idx,status,step_payload from steps where step_type=15 and status=3 order by idx desc limit 100"
        ):
            visible = public_response(payload)
            if visible:
                public.append(
                    {
                        "step_index": idx,
                        "kind": "assistant_public_text",
                        "text": (
                            visible
                            if len(visible) <= 5000
                            else visible[:1500]
                            + "\n[excerpt omitted]\n"
                            + visible[-2500:]
                        ),
                        "text_length": len(visible),
                        "text_sha256": hashlib.sha256(visible.encode()).hexdigest(),
                        "complete_marker": COMPLETE in visible,
                        "cancelled_marker": CANCELLED in visible,
                        **metadata_times(payload),
                    }
                )
            if len(public) >= 3:
                break
        row["latest_public_messages"] = public
        # Step completion alone does not prove session idle: background tools and queued input require live UI checks.
        state = STATUS_NAMES.get(latest[2], "unknown")
        row["native_execution_state"] = (
            "busy"
            if state in {"pending", "running", "generating", "waiting", "queued"}
            else (
                "interrupted"
                if state in {"cancelled", "error", "interrupted"}
                else "idle_candidate" if state == "done" else "unknown"
            )
        )
        md = one(latest[3], 5, b"")
        call = one(md, 4)
        if call:
            action = {"tool_name": text(one(call, 2, b""))}
            try:
                args = json.loads(text(one(call, 3, b"{}")))
                for k in ["toolAction", "toolSummary"]:
                    if k in args:
                        action[k] = args[k]
            except (ValueError, TypeError):
                pass
            row["last_action"] = action
        else:
            row["last_action"] = {
                "kind": "assistant_public_text" if latest[1] == 15 else "native_step",
                "step_index": latest[0],
            }
        row["completion_boundary_limit"] = (
            "The reader reconstructs native goal status only; completion markers do not independently prove scientific/task acceptance or PR closure. Live empty composer, no queued input, background-task completion and repository checks are separate gates."
        )
        return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="Write sanitized JSON assessment here (default: stdout)",
    )
    args = parser.parse_args()
    data = json.loads((ROOT / "cache/last_conversations.json").read_text())
    rows = []
    for repo, cid in data.items():
        if "/Mechs/" not in repo:
            continue
        try:
            rows.append(inspect(repo, cid))
        except Exception as e:
            rows.append(
                {
                    "repository": Path(repo).name,
                    "root": repo,
                    "conversation_id": cid,
                    "error": str(e),
                }
            )
    report = {"assessed_at": datetime.now(timezone.utc).isoformat(), "sessions": rows}
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
