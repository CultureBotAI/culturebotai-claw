"""Scaffold and locate append-only history records.

Kept dependency-light (stdlib + PyYAML) so CI needs no repo-specific env.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import secrets
from pathlib import Path
from typing import Any

import yaml

# Maps a target kind onto the directory under history/. `other` still needs an
# explicit --path, because its target cannot be derived from a slug.
KIND_DIRS: dict[str, str] = {
    "record": "records",
    "schema": "schema",
    "mapping": "mappings",
    "report": "reports",
    "infrastructure": "infrastructure",
    "other": "other",
}

EVENT_TYPES = ("GENERAL", "CREATE", "EDIT", "REVIEW", "AUDIT")
OUTCOMES = ("changed", "no_change", "needs_followup", "blocked")
ACTOR_TYPES = ("human", "ai_agent", "automation", "other")


def _actor_slug(name: str) -> str:
    """Collapse an actor name to a filename-safe token."""
    token = re.sub(r"[^A-Za-z0-9]+", "-", (name or "").lower()).strip("-")
    return token or "actor"


def _slug_token(value: str) -> str:
    """Filename-safe directory token for a target slug.

    Dots are preserved (real slugs contain them), so a dot-only token such as
    `..` would survive and walk out of the kind directory. Reject those rather
    than silently rewriting them, so the caller learns the slug was unusable.
    """
    token = re.sub(r"[^A-Za-z0-9._-]+", "-", (value or "").strip()).strip("-")
    if not token:
        return "unknown"
    if set(token) <= {"."}:
        raise ValueError(
            f"slug {value!r} reduces to {token!r}, which would escape the kind "
            "directory; give the target a real slug"
        )
    return token


def utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def new_history_path(
    history_root: Path,
    kind: str,
    slug: str,
    actor_name: str,
    *,
    now: _dt.datetime | None = None,
    shortid: str | None = None,
    kind_dir: str | None = None,
) -> tuple[Path, str, str]:
    """Return (path, session_id, iso_timestamp) for a new record.

    The filename stem IS the session id, so a record can be found from its id
    alone. `shortid` defaults to 3 random bytes; combined with a
    second-resolution timestamp and the per-slug directory, collisions between
    concurrent writers are not a practical concern.
    """
    now = now or utc_now()
    shortid = shortid or secrets.token_hex(3)
    file_ts = now.strftime("%Y-%m-%dT%H%M%SZ")
    iso_ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    session_id = f"{file_ts}-{_actor_slug(actor_name)}-{shortid}"
    directory = kind_dir or KIND_DIRS.get(kind, "other")
    path = history_root / directory / _slug_token(slug) / f"{session_id}.yaml"
    return path, session_id, iso_ts


def build_record(
    *,
    kind: str,
    slug: str,
    target_path: str,
    session_id: str,
    timestamp: str,
    summary: str,
    details: str,
    event: str = "EDIT",
    outcome: str = "changed",
    sections: list[str] | None = None,
    actor_name: str = "claude-code",
    actor_type: str = "ai_agent",
    model: str | None = None,
    agent_tool: str | None = None,
    agent_version: str | None = None,
    issues: list[str] | None = None,
    prs: list[str] | None = None,
    urls: list[str] | None = None,
) -> dict[str, Any]:
    """Build a schema-valid record dict. Validation proper is linkml's job."""
    if event not in EVENT_TYPES:
        raise ValueError(f"event must be one of {EVENT_TYPES}, got {event!r}")
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}, got {outcome!r}")
    if actor_type not in ACTOR_TYPES:
        raise ValueError(f"actor_type must be one of {ACTOR_TYPES}, got {actor_type!r}")
    if kind not in KIND_DIRS:
        raise ValueError(f"kind must be one of {tuple(sorted(KIND_DIRS))}, got {kind!r}")
    if not summary.strip():
        raise ValueError("summary must be non-empty")
    if not details.strip():
        raise ValueError(
            "details must be non-empty — a record without it is just a timestamp"
        )

    actor: dict[str, Any] = {"type": actor_type, "name": actor_name}
    for key, value in (
        ("model", model),
        ("agent_tool", agent_tool),
        ("agent_version", agent_version),
    ):
        if value:
            actor[key] = value

    target: dict[str, Any] = {"kind": kind, "path": target_path}
    if slug:
        # Record the sanitised token, not the raw input: the schema defines slug
        # as also being the directory name, so storing the raw value would make a
        # target's history unfindable from its own record.
        target["slug"] = _slug_token(slug)

    event_obj: dict[str, Any] = {"type": event, "outcome": outcome}
    if sections:
        event_obj["sections"] = list(sections)
    event_obj["summary"] = summary.strip()
    event_obj["details"] = details

    record: dict[str, Any] = {
        "history_version": 1,
        "target": target,
        "session": {"id": session_id, "timestamp": timestamp, "actors": [actor]},
    }
    links = {
        key: list(value)
        for key, value in (("issues", issues), ("prs", prs), ("urls", urls))
        if value
    }
    if links:
        record["links"] = links
    record["events"] = [event_obj]
    return record


class _BlockDumper(yaml.SafeDumper):
    """Emit multi-line strings as literal blocks so `details` stays readable."""


def _str_representer(dumper: yaml.SafeDumper, data: str):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_BlockDumper.add_representer(str, _str_representer)


def write_record(path: Path, record: dict[str, Any], *, force: bool = False) -> Path:
    """Write a record atomically. Refuses to clobber unless `force`.

    Records are append-only, so two properties matter. The no-clobber check uses
    O_EXCL rather than a prior exists() test, making it a real guarantee instead
    of a race the shortid merely makes unlikely. And the write goes to a temp
    file then os.replace, so a process killed mid-write cannot leave a truncated
    record that fails validation for everyone else.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.dump(
        record,
        Dumper=_BlockDumper,
        sort_keys=False,
        allow_unicode=True,
        width=88,
    )
    if not force:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            raise FileExistsError(
                f"{path} already exists (use --force to overwrite)"
            ) from None
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    tmp = path.with_name(path.name + f".tmp-{secrets.token_hex(4)}")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path
