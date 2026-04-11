"""Session Persistence — Append-Only JSONL (Claude Code Architecture Ep.09).

Every conversation turn persists to append-only JSONL files.
Resume via parent-UUID chain walks.
Lazy materialization, write coalescing, 64KB lite reads.

Path layout:
    ~/.clow/sessions_jsonl/{sanitized-project}/{session-id}.jsonl

Each JSONL line is a self-contained entry:
    {"uuid":"a1b2","type":"user","parentUuid":"","timestamp":1718000000,...}

Entry types mirror Claude Code's taxonomy:
    user / assistant / system — conversation messages
    tool_use / tool_result    — tool call round-trips
    compact-boundary          — compaction markers (chain resets after)
    summary                   — compacted context summaries
    attachment                — file/image attachments
    custom-title / ai-title   — session titles (user-set / LLM-generated)
    last-prompt               — last user prompt (for session picker)
    tag                       — user-applied tags
    agent-name / agent-setting— subagent identity
    mode                      — plan / act / auto mode switches
    metadata                  — generic key-value metadata
    content-replacement       — edited message content

Design decisions (from Claude Code Ep.09):
    - Append-only: never rewrite history, only append new entries
    - Parent-UUID chain: each entry references its predecessor
    - Lazy materialization: file not created until first real message
    - Write coalescing: 100ms batching via threaded write queue
    - Lite reads: 64KB head + tail for session picker (no full parse)
    - Stat-pass listing: Phase 1 stat() for sort, Phase 2 lite read top-N
    - Re-append metadata: titles/tags re-appended at EOF for tail window
    - Subagent isolation: per-file queues keyed by path
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import re
import time
import uuid
import hashlib
import threading
from pathlib import Path
from typing import Any

from . import config

logger = logging.getLogger("clow.session_jsonl")


# ==============================================================
#  Constants
# ==============================================================

SESSIONS_BASE = config.CLOW_HOME / "sessions_jsonl"
SESSIONS_BASE.mkdir(parents=True, exist_ok=True)

LITE_READ_BUF_SIZE = 65_536                    # 64 KB for head/tail reads
MAX_TRANSCRIPT_READ_BYTES = 50 * 1024 * 1024   # 50 MB safety cap
WRITE_COALESCE_MS = 100                         # Batch writes every 100 ms
SESSION_LIST_DEFAULT_LIMIT = 20                 # Default number of sessions to list

# Recognised entry types (for validation / filtering)
ENTRY_TYPES = frozenset({
    "user", "assistant", "system",
    "tool_use", "tool_result",
    "attachment", "summary",
    "compact-boundary",
    "custom-title", "ai-title", "last-prompt",
    "tag",
    "agent-name", "agent-setting", "mode",
    "metadata", "content-replacement",
})

# Types that represent actual conversation messages
MESSAGE_TYPES = frozenset({"user", "assistant", "system"})

# Types that represent tool interactions
TOOL_TYPES = frozenset({"tool_use", "tool_result"})

# Metadata types that get re-appended at EOF
METADATA_TYPES = frozenset({
    "custom-title", "ai-title", "last-prompt", "tag",
    "agent-name", "agent-setting", "mode",
})


# ==============================================================
#  Path Management
# ==============================================================

def sanitize_path(cwd: str) -> str:
    """Sanitize CWD to a safe directory name.

    Non-alphanumeric characters become hyphens.
    Paths longer than 200 chars are truncated with an MD5 suffix to
    prevent collisions.
    """
    sanitized = re.sub(r"[^a-zA-Z0-9]", "-", cwd)
    # Collapse runs of hyphens
    sanitized = re.sub(r"-{2,}", "-", sanitized).strip("-")
    if len(sanitized) > 200:
        h = hashlib.md5(cwd.encode()).hexdigest()[:8]
        sanitized = sanitized[:192] + "-" + h
    return sanitized or "default"


def get_project_dir(cwd: str = "") -> Path:
    """Return (and ensure existence of) the project session directory."""
    if not cwd:
        cwd = os.getcwd()
    project = SESSIONS_BASE / sanitize_path(cwd)
    project.mkdir(parents=True, exist_ok=True)
    return project


def get_session_path(session_id: str, cwd: str = "") -> Path:
    """Return the path to a session JSONL file."""
    return get_project_dir(cwd) / f"{session_id}.jsonl"


# ==============================================================
#  Entry Factory
# ==============================================================

def make_entry(
    entry_type: str,
    uuid_str: str = "",
    parent_uuid: str = "",
    **data: Any,
) -> dict:
    """Create a JSONL entry dict with UUID chain link.

    Parameters
    ----------
    entry_type : str
        One of ENTRY_TYPES (not enforced -- unknown types are allowed for
        forward-compat but logged as warnings).
    uuid_str : str, optional
        Explicit UUID; auto-generated if empty.
    parent_uuid : str
        UUID of the preceding entry in the chain (empty for first entry
        or after a compact-boundary).
    **data
        Arbitrary payload merged into the entry.
    """
    if entry_type not in ENTRY_TYPES:
        logger.debug("Unknown entry type %r -- accepting for forward-compat", entry_type)
    return {
        "uuid": uuid_str or uuid.uuid4().hex[:12],
        "type": entry_type,
        "parentUuid": parent_uuid,
        "timestamp": time.time(),
        **data,
    }


# ==============================================================
#  Write Queue -- 100 ms coalescing (Claude Code pattern)
# ==============================================================

class WriteQueue:
    """Async write queue that batches rapid-fire appends.

    Per-file queues support subagent transcript isolation -- each file
    path accumulates its own buffer, and a single drain pass flushes
    all of them in one go.

    Thread-safe: a background ``threading.Timer`` fires after
    ``WRITE_COALESCE_MS`` to drain.  ``flush_sync()`` is available for
    deterministic shutdown.
    """

    def __init__(self) -> None:
        self._queues: dict[str, list[dict]] = {}  # path -> [entries]
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._pending_count: int = 0

    # -- Public API --

    def enqueue(self, path: str, entry: dict) -> None:
        """Add *entry* to the write queue for *path*."""
        with self._lock:
            self._queues.setdefault(path, []).append(entry)
            self._pending_count += 1
            self._schedule_drain()

    def flush_sync(self) -> None:
        """Synchronous flush -- call on exit / before assertions."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._drain()

    @property
    def pending(self) -> int:
        """Number of entries waiting to be written."""
        with self._lock:
            return self._pending_count

    # -- Internal --

    def _schedule_drain(self) -> None:
        """Start the coalesce timer if not already ticking."""
        if self._timer is None or not self._timer.is_alive():
            self._timer = threading.Timer(WRITE_COALESCE_MS / 1000.0, self._drain)
            self._timer.daemon = True
            self._timer.start()

    def _drain(self) -> None:
        """Flush all queued writes to disk.

        Atomicity: each file gets a single write() call so that
        concurrent readers see complete lines (POSIX append semantics
        for writes <= PIPE_BUF).
        """
        with self._lock:
            queues = dict(self._queues)
            self._queues.clear()
            self._pending_count = 0
            self._timer = None

        for path, entries in queues.items():
            try:
                blob = "".join(
                    json.dumps(e, ensure_ascii=False) + "\n" for e in entries
                )
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(blob)
            except Exception:
                logger.exception("Write queue drain error for %s", path)


# Module-level singleton
_write_queue = WriteQueue()

# Ensure pending writes are flushed when the interpreter exits
atexit.register(_write_queue.flush_sync)


# ==============================================================
#  SessionWriter -- per-session append handle
# ==============================================================

class SessionWriter:
    """Manages writes to a single session JSONL file.

    Key behaviours
    ~~~~~~~~~~~~~~
    * **Lazy materialization** -- the file is not created until the first
      message of type *user* or *assistant* is appended.  Metadata
      entries that arrive before materialization are buffered and flushed
      when the file is finally created.
    * **Parent-UUID chain** -- every entry links to the previous one via
      ``parentUuid``, enabling forward/backward chain walks.
    * **Dedup** -- duplicate message UUIDs are silently dropped.
    * **Re-append metadata** -- call ``reappend_metadata()`` at session
      end (or after compaction) to ensure titles/tags appear in the
      64 KB tail window that the session picker reads.
    """

    def __init__(self, session_id: str, cwd: str = "") -> None:
        self.session_id: str = session_id
        self.cwd: str = cwd
        self.path: Path = get_session_path(session_id, cwd)
        self.materialized: bool = self.path.exists()
        self._pending_entries: list[dict] = []
        self._last_uuid: str = ""
        self._seen_uuids: set[str] = set()
        self._metadata: dict[str, str] = {}
        self._entry_count: int = 0

        # If file already exists, recover last UUID from tail
        if self.materialized:
            self._recover_last_uuid()

    # -- Message Appenders --

    def append_message(
        self,
        role: str,
        content: str,
        tool_calls: list | None = None,
    ) -> str:
        """Append a conversation message (*user*, *assistant*, *system*).

        Returns the entry UUID.
        """
        if role not in MESSAGE_TYPES:
            logger.warning("append_message called with unexpected role %r", role)

        msg_uuid = uuid.uuid4().hex[:12]
        entry = make_entry(
            entry_type=role,
            uuid_str=msg_uuid,
            parent_uuid=self._last_uuid,
            role=role,
            content=content,
        )
        if tool_calls:
            entry["tool_calls"] = tool_calls

        self._last_uuid = msg_uuid
        self._write(entry)

        # Track for dedup
        self._seen_uuids.add(msg_uuid)

        # Update last-prompt for lite reads
        if role == "user" and isinstance(content, str):
            self.set_metadata("last-prompt", content[:200])

        return msg_uuid

    def append_tool_use(
        self,
        tool_name: str,
        tool_args: dict,
        tool_id: str,
    ) -> str:
        """Append a tool-use entry. Returns UUID."""
        entry_uuid = uuid.uuid4().hex[:12]
        entry = make_entry(
            "tool_use",
            uuid_str=entry_uuid,
            parent_uuid=self._last_uuid,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_id=tool_id,
        )
        self._last_uuid = entry_uuid
        self._write(entry)
        return entry_uuid

    def append_tool_result(
        self,
        tool_id: str,
        status: str,
        output: str,
    ) -> str:
        """Append a tool-result entry. Output is capped at 5000 chars."""
        entry_uuid = uuid.uuid4().hex[:12]
        entry = make_entry(
            "tool_result",
            uuid_str=entry_uuid,
            parent_uuid=self._last_uuid,
            tool_id=tool_id,
            status=status,
            output=output[:5000],
        )
        self._last_uuid = entry_uuid
        self._write(entry)
        return entry_uuid

    def append_attachment(
        self,
        filename: str,
        mime_type: str,
        size: int,
        summary: str = "",
    ) -> str:
        """Append an attachment reference entry."""
        entry_uuid = uuid.uuid4().hex[:12]
        entry = make_entry(
            "attachment",
            uuid_str=entry_uuid,
            parent_uuid=self._last_uuid,
            filename=filename,
            mime_type=mime_type,
            size=size,
            summary=summary[:500],
        )
        self._last_uuid = entry_uuid
        self._write(entry)
        return entry_uuid

    def append_summary(self, summary: str, token_count: int = 0) -> str:
        """Append a context summary (e.g. after compaction)."""
        entry_uuid = uuid.uuid4().hex[:12]
        entry = make_entry(
            "summary",
            uuid_str=entry_uuid,
            parent_uuid=self._last_uuid,
            summary=summary,
            token_count=token_count,
        )
        self._last_uuid = entry_uuid
        self._write(entry)
        return entry_uuid

    def append_compact_boundary(
        self,
        summary: str,
        pre_token_count: int = 0,
    ) -> None:
        """Insert a compaction boundary marker.

        After a compact-boundary the parent-UUID chain resets -- post-
        compact messages start a fresh chain from this marker.
        """
        entry = make_entry(
            "compact-boundary",
            parent_uuid="",
            summary=summary,
            pre_compact_tokens=pre_token_count,
            trigger="auto",
        )
        self._last_uuid = entry["uuid"]
        self._write(entry)

        # Re-append metadata so it is visible in the tail window
        self.reappend_metadata()

    def append_mode_switch(self, mode: str) -> None:
        """Record a mode switch (plan / act / auto)."""
        entry = make_entry("mode", parent_uuid=self._last_uuid, value=mode)
        self._write(entry)

    def append_content_replacement(
        self,
        target_uuid: str,
        new_content: str,
    ) -> str:
        """Record an edit to an earlier message (soft overwrite)."""
        entry_uuid = uuid.uuid4().hex[:12]
        entry = make_entry(
            "content-replacement",
            uuid_str=entry_uuid,
            parent_uuid=self._last_uuid,
            target_uuid=target_uuid,
            new_content=new_content,
        )
        self._last_uuid = entry_uuid
        self._write(entry)
        return entry_uuid

    # -- Metadata --

    def set_metadata(self, key: str, value: str) -> None:
        """Set metadata (title, tag, etc.).

        Stored in-memory for later ``reappend_metadata()`` calls, and
        immediately appended to the JSONL file.
        """
        self._metadata[key] = value
        entry = make_entry(key, value=value)
        self._write(entry)

    def reappend_metadata(self) -> None:
        """Re-append all stored metadata at the current EOF.

        This ensures that metadata entries (titles, tags, last-prompt)
        always appear in the 64 KB tail window that
        ``read_session_lite()`` scans.  Called automatically after
        compact boundaries, and should be called at session end.

        Uses synchronous direct-write (bypasses the queue) for
        reliability during shutdown.
        """
        if not self._metadata or not self.materialized:
            return
        try:
            blob = ""
            for key, value in self._metadata.items():
                entry = make_entry(key, value=value)
                blob += json.dumps(entry, ensure_ascii=False) + "\n"
            with open(str(self.path), "a", encoding="utf-8") as fh:
                fh.write(blob)
        except Exception:
            logger.exception("reappend_metadata failed for %s", self.session_id)

    # -- Subagent Support --

    def create_subagent_writer(
        self,
        subagent_name: str,
        subagent_id: str = "",
    ) -> "SessionWriter":
        """Create an isolated writer for a subagent transcript.

        The subagent gets its own JSONL file:
            {session-id}__sub_{subagent-name}_{sub-id}.jsonl

        This keeps the main conversation file clean while preserving
        full subagent transcripts for debugging.
        """
        sub_id = subagent_id or uuid.uuid4().hex[:8]
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", subagent_name)
        sub_session_id = f"{self.session_id}__sub_{safe_name}_{sub_id}"
        writer = SessionWriter(sub_session_id, self.cwd)
        writer.set_metadata("agent-name", subagent_name)
        writer.set_metadata("agent-setting", f"subagent-of:{self.session_id}")
        return writer

    # -- Internal --

    def _write(self, entry: dict) -> None:
        """Route an entry through lazy materialization and the write queue.

        If the file has not yet been materialized, non-message entries
        are buffered.  The first *user* or *assistant* entry triggers
        materialization and flushes the buffer.
        """
        if not self.materialized:
            # Only materialize on a real conversation message
            if entry.get("type") in MESSAGE_TYPES:
                self._materialize()
                # Flush any buffered pre-materialization entries
                for pending in self._pending_entries:
                    _write_queue.enqueue(str(self.path), pending)
                self._pending_entries.clear()
            else:
                self._pending_entries.append(entry)
                return

        # Dedup guard for conversation messages
        entry_uuid = entry.get("uuid", "")
        if entry_uuid and entry_uuid in self._seen_uuids and entry.get("type") in MESSAGE_TYPES:
            logger.debug("Duplicate message UUID %s -- skipping", entry_uuid)
            return

        _write_queue.enqueue(str(self.path), entry)
        self._entry_count += 1

    def _materialize(self) -> None:
        """Create the session file on disk (lazy -- first real message)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            # Create with restrictive permissions
            self.path.touch(mode=0o600)
            logger.debug("Materialized session file: %s", self.path)
        self.materialized = True

    def _recover_last_uuid(self) -> None:
        """Recover the last UUID from an existing session file.

        Reads the tail of the file (up to 64 KB) and parses the last
        valid JSONL line to restore chain continuity on resume.
        """
        try:
            size = self.path.stat().st_size
            if size == 0:
                return
            with open(self.path, "rb") as fh:
                fh.seek(max(0, size - LITE_READ_BUF_SIZE))
                tail = fh.read().decode("utf-8", errors="replace")
            lines = tail.strip().split("\n")
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    uid = entry.get("uuid", "")
                    if uid:
                        self._last_uuid = uid
                        return
                except json.JSONDecodeError:
                    continue
        except Exception:
            logger.debug("Could not recover last UUID for %s", self.session_id)


# ==============================================================
#  Resume Pipeline
# ==============================================================

def load_session_for_resume(session_id: str, cwd: str = "") -> dict:
    """Load a session for resume via parent-UUID chain walk.

    Pipeline stages
    ~~~~~~~~~~~~~~~
    1. **Parse** -- stream JSONL lines into a list (respecting the 50 MB
       safety cap).
    2. **Index** -- build ``Map<UUID, entry>`` for O(1) lookups.
    3. **Find leaf** -- identify the latest conversation-message entry.
    4. **Chain walk** -- follow ``parentUuid`` links from leaf to root
       (or compact-boundary), then reverse to get chronological order.
    5. **Interruption detection** -- infer whether the session was
       interrupted mid-turn.
    6. **Apply content-replacements** -- overlay any edits.
    7. **Return** -- conversation messages + metadata dict.

    Returns
    -------
    dict with keys:
        session_id, messages, metadata, interruption,
        chain_length, total_entries, compact_boundary
    """
    path = get_session_path(session_id, cwd)
    if not path.exists():
        return {"error": "Session not found", "messages": []}

    # 1. Parse
    entries = _parse_jsonl(path)
    if not entries:
        return {"error": "Empty session", "messages": []}

    # 2. Index
    by_uuid: dict[str, dict] = {}
    metadata: dict[str, str] = {}
    replacements: dict[str, str] = {}  # target_uuid -> new_content

    for entry in entries:
        uid = entry.get("uuid", "")
        if uid:
            by_uuid[uid] = entry

        etype = entry.get("type", "")

        # Collect metadata (last-wins)
        if etype in METADATA_TYPES:
            metadata[etype] = entry.get("value", "")

        # Collect content replacements
        if etype == "content-replacement":
            target = entry.get("target_uuid", "")
            if target:
                replacements[target] = entry.get("new_content", "")

    # 3. Find leaf (latest non-metadata conversation entry)
    conversation_types = MESSAGE_TYPES | TOOL_TYPES
    messages = [e for e in entries if e.get("type") in conversation_types]
    if not messages:
        return {
            "error": "No messages",
            "messages": [],
            "metadata": metadata,
        }

    leaf = messages[-1]

    # 4. Chain walk
    chain = _build_chain(by_uuid, leaf)

    # Check for compact boundary -- if the chain passes through one,
    # only keep entries after the boundary.
    compact_boundary = None
    trimmed_chain = []
    for entry in chain:
        if entry.get("type") == "compact-boundary":
            compact_boundary = entry
            trimmed_chain.clear()  # Discard pre-compact entries
            continue
        trimmed_chain.append(entry)

    if compact_boundary:
        chain = trimmed_chain

    # 5. Interruption detection
    interruption = _detect_interruption(chain)

    # 6. Apply content replacements
    for entry in chain:
        uid = entry.get("uuid", "")
        if uid in replacements:
            entry["content"] = replacements[uid]

    # 7. Convert to message dicts
    conversation = _chain_to_messages(chain)

    return {
        "session_id": session_id,
        "messages": conversation,
        "metadata": metadata,
        "interruption": interruption,
        "chain_length": len(chain),
        "total_entries": len(entries),
        "compact_boundary": compact_boundary is not None,
    }


def _build_chain(by_uuid: dict[str, dict], leaf: dict) -> list[dict]:
    """Walk the parent-UUID chain from *leaf* to root, then reverse.

    Includes cycle detection to guard against corrupt files.
    """
    chain: list[dict] = []
    current: dict | None = leaf
    seen: set[str] = set()

    while current is not None:
        uid = current.get("uuid", "")
        if uid in seen:
            logger.warning("Cycle detected in UUID chain at %s", uid)
            break
        seen.add(uid)
        chain.append(current)

        parent_uuid = current.get("parentUuid", "")
        if not parent_uuid:
            break
        current = by_uuid.get(parent_uuid)

    chain.reverse()
    return chain


def _detect_interruption(chain: list[dict]) -> str:
    """Infer whether the session was interrupted mid-turn.

    Returns one of:
        "none"                -- last entry is a complete assistant turn
        "interrupted_prompt"  -- user sent a message but got no response
        "interrupted_turn"    -- interrupted during tool execution
        "interrupted_stream"  -- assistant started but message seems truncated
        "empty"               -- no entries at all
    """
    if not chain:
        return "empty"

    last = chain[-1]
    last_type = last.get("type", last.get("role", ""))

    if last_type == "assistant":
        # Check if it looks truncated (very short or no content)
        content = last.get("content", "")
        if isinstance(content, str) and len(content) < 5 and last.get("tool_calls"):
            return "interrupted_stream"
        return "none"
    elif last_type == "user":
        return "interrupted_prompt"
    elif last_type in ("tool_use", "tool_result"):
        return "interrupted_turn"
    else:
        return "interrupted_turn"


def _chain_to_messages(chain: list[dict]) -> list[dict]:
    """Convert a chain of JSONL entries to API-style message dicts."""
    conversation: list[dict] = []

    for entry in chain:
        etype = entry.get("type", "")
        role = entry.get("role", etype)
        content = entry.get("content", "")

        if role in ("user", "assistant", "system") and content:
            msg: dict = {"role": role, "content": content}
            if entry.get("tool_calls"):
                msg["tool_calls"] = entry["tool_calls"]
            conversation.append(msg)

        elif etype == "tool_result":
            conversation.append({
                "role": "tool",
                "tool_call_id": entry.get("tool_id", ""),
                "content": entry.get("output", ""),
            })

        elif etype == "summary":
            # Inject summaries as system messages so the model sees them
            conversation.append({
                "role": "system",
                "content": "[Context summary]: " + entry.get("summary", ""),
            })

    return conversation


# ==============================================================
#  JSONL Parser
# ==============================================================

def _parse_jsonl(
    path: Path,
    max_bytes: int = MAX_TRANSCRIPT_READ_BYTES,
) -> list[dict]:
    """Parse a JSONL file into a list of entry dicts.

    Respects the safety cap: files larger than *max_bytes* are
    truncated (later lines are dropped).  Malformed lines are skipped.
    """
    entries: list[dict] = []
    try:
        size = path.stat().st_size
        if size > max_bytes:
            logger.warning(
                "Session file %s (%.1f MB) exceeds safety cap -- truncating read",
                path.name,
                size / (1024 * 1024),
            )

        bytes_read = 0
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                bytes_read += len(line.encode("utf-8"))
                if bytes_read > max_bytes:
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    entries.append(json.loads(stripped))
                except json.JSONDecodeError:
                    logger.debug("Skipping malformed JSONL line in %s", path.name)
                    continue
    except Exception:
        logger.exception("Failed to parse JSONL file %s", path.name)

    return entries


# ==============================================================
#  Lite Metadata -- 64 KB Head/Tail (Session Picker fast path)
# ==============================================================

def read_session_lite(session_id: str, cwd: str = "") -> dict:
    """Read lightweight session metadata by scanning only the first and
    last 64 KB of the file.

    This avoids parsing multi-megabyte transcripts just to populate a
    session picker list.  Metadata entries (titles, tags, last-prompt)
    are re-appended at EOF by ``SessionWriter.reappend_metadata()``
    specifically to be caught by this tail scan.

    Returns
    -------
    dict with keys:
        session_id, title, first_prompt, last_prompt, tag,
        created_at, updated_at, size, mtime, message_count_estimate
    """
    path = get_session_path(session_id, cwd)
    if not path.exists():
        return {}

    try:
        stat = path.stat()
        size = stat.st_size
        mtime = stat.st_mtime

        with open(path, "rb") as fh:
            head_bytes = fh.read(LITE_READ_BUF_SIZE)
            head = head_bytes.decode("utf-8", errors="replace")

            if size > LITE_READ_BUF_SIZE:
                fh.seek(max(0, size - LITE_READ_BUF_SIZE))
                tail = fh.read(LITE_READ_BUF_SIZE).decode("utf-8", errors="replace")
            else:
                tail = head

        # -- Extract from head --
        first_prompt = ""
        created_at = 0.0
        msg_count = 0

        for line in head.split("\n")[:50]:  # Scan up to 50 head lines
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError:
                continue

            etype = entry.get("type", "")
            if etype == "user" and not first_prompt:
                first_prompt = str(entry.get("content", ""))[:200]
            if not created_at and entry.get("timestamp"):
                created_at = float(entry["timestamp"])
            if etype in MESSAGE_TYPES:
                msg_count += 1

        # -- Extract from tail --
        title = ""
        last_prompt = ""
        tag = ""
        updated_at = 0.0

        for line in reversed(tail.split("\n")):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError:
                continue

            etype = entry.get("type", "")
            ts = entry.get("timestamp", 0)

            if not updated_at and ts:
                updated_at = float(ts)

            if etype == "custom-title" and not title:
                title = str(entry.get("value", ""))
            elif etype == "ai-title" and not title:
                title = str(entry.get("value", ""))
            elif etype == "last-prompt" and not last_prompt:
                last_prompt = str(entry.get("value", ""))
            elif etype == "tag" and not tag:
                tag = str(entry.get("value", ""))

            # Stop scanning once we have everything
            if title and last_prompt and tag and updated_at:
                break

        # Estimate total message count from file size (rough: ~200 bytes/msg)
        if size > LITE_READ_BUF_SIZE:
            msg_count_estimate = max(msg_count, size // 200)
        else:
            msg_count_estimate = msg_count

        return {
            "session_id": session_id,
            "title": title,
            "first_prompt": first_prompt,
            "last_prompt": last_prompt,
            "tag": tag,
            "created_at": created_at,
            "updated_at": updated_at or mtime,
            "size": size,
            "mtime": mtime,
            "message_count_estimate": msg_count_estimate,
        }

    except Exception:
        logger.exception("read_session_lite failed for %s", session_id)
        return {}


# ==============================================================
#  Session Listing -- Two-Phase stat-pass optimisation
# ==============================================================

def list_sessions(
    cwd: str = "",
    limit: int = SESSION_LIST_DEFAULT_LIMIT,
    include_subagents: bool = False,
) -> list[dict]:
    """List recent sessions with a two-phase approach.

    Phase 1 -- **stat pass** (~O(n) stat calls, no file reads)
        Enumerate ``*.jsonl`` files, stat each for mtime/size, sort by
        mtime descending.

    Phase 2 -- **lite read** (only top *limit* files)
        Call ``read_session_lite()`` to extract metadata from the 64 KB
        head/tail of each file.

    Parameters
    ----------
    cwd : str
        Project working directory (empty = current).
    limit : int
        Maximum sessions to return.
    include_subagents : bool
        If False (default), files matching ``*__sub_*`` are excluded.
    """
    project_dir = get_project_dir(cwd)

    # Phase 1: stat pass
    files: list[tuple[str, float, int]] = []  # (session_id, mtime, size)
    try:
        for p in project_dir.glob("*.jsonl"):
            # Skip subagent files unless requested
            if not include_subagents and "__sub_" in p.stem:
                continue
            try:
                st = p.stat()
                files.append((p.stem, st.st_mtime, st.st_size))
            except OSError:
                continue
    except OSError:
        return []

    # Sort by mtime descending (most recent first)
    files.sort(key=lambda x: x[1], reverse=True)

    # Phase 2: lite read top-N
    sessions: list[dict] = []
    for session_id, mtime, size in files[:limit]:
        lite = read_session_lite(session_id, cwd)
        if lite:
            sessions.append(lite)
        else:
            # Fallback: minimal info from stat
            sessions.append({
                "session_id": session_id,
                "title": "",
                "first_prompt": "",
                "last_prompt": "",
                "mtime": mtime,
                "size": size,
            })

    return sessions


# ==============================================================
#  Backward-Compatible Free Functions
# ==============================================================
#
# These match the old module-level API so existing callers keep working.

# Keep old SESSIONS_DIR alias for anything importing it
SESSIONS_DIR = SESSIONS_BASE


def _session_path(session_id: str) -> Path:
    """Legacy path helper (flat -- no per-project dirs)."""
    return SESSIONS_DIR / f"{session_id}.jsonl"


def append_entry(session_id: str, entry_type: str, data: dict) -> None:
    """Legacy: append a single entry to a session."""
    entry = make_entry(entry_type, **data)
    path = _session_path(session_id)
    _write_queue.enqueue(str(path), entry)


def append_message(
    session_id: str,
    role: str,
    content: str,
    parent_uuid: str = "",
) -> str:
    """Legacy: append a message entry. Returns UUID."""
    msg_uuid = uuid.uuid4().hex[:12]
    entry = make_entry(
        "message",
        uuid_str=msg_uuid,
        parent_uuid=parent_uuid,
        role=role,
        content=content,
    )
    path = _session_path(session_id)
    _write_queue.enqueue(str(path), entry)
    return msg_uuid


def append_tool_use(
    session_id: str,
    tool_name: str,
    tool_args: dict,
    tool_id: str,
    parent_uuid: str = "",
) -> str:
    """Legacy: append a tool-use entry."""
    entry_uuid = uuid.uuid4().hex[:12]
    entry = make_entry(
        "tool_use",
        uuid_str=entry_uuid,
        parent_uuid=parent_uuid,
        tool_name=tool_name,
        tool_args=tool_args,
        tool_id=tool_id,
    )
    path = _session_path(session_id)
    _write_queue.enqueue(str(path), entry)
    return entry_uuid


def append_tool_result(
    session_id: str,
    tool_id: str,
    status: str,
    output: str,
    parent_uuid: str = "",
) -> str:
    """Legacy: append a tool-result entry."""
    entry_uuid = uuid.uuid4().hex[:12]
    entry = make_entry(
        "tool_result",
        uuid_str=entry_uuid,
        parent_uuid=parent_uuid,
        tool_id=tool_id,
        status=status,
        output=output[:5000],
    )
    path = _session_path(session_id)
    _write_queue.enqueue(str(path), entry)
    return entry_uuid


def append_compact(session_id: str, summary: str) -> None:
    """Legacy: append a compaction summary."""
    append_entry(session_id, "compact-boundary", {"summary": summary})


def append_metadata(session_id: str, key: str, value: str) -> None:
    """Legacy: append metadata entry."""
    append_entry(session_id, key, {"value": value})


def load_session(session_id: str) -> list[dict]:
    """Legacy: load all entries from a session JSONL file."""
    path = _session_path(session_id)
    if not path.exists():
        # Try project-scoped path as fallback
        for candidate in SESSIONS_BASE.glob(f"*/{session_id}.jsonl"):
            path = candidate
            break
        else:
            return []
    return _parse_jsonl(path)


def build_conversation_chain(entries: list[dict]) -> list[dict]:
    """Legacy: build chain from entries via parent-UUID walk.

    Uses the new ``_build_chain`` internally.
    """
    if not entries:
        return []

    by_uuid = {e["uuid"]: e for e in entries if "uuid" in e}

    # Find latest message-type entry
    messages = [
        e for e in entries
        if e.get("type") in ("message", "user", "assistant", "system")
    ]
    if not messages:
        return []

    latest = messages[-1]
    chain = _build_chain(by_uuid, latest)
    return chain


# ==============================================================
#  Cleanup / Flush
# ==============================================================

def flush_all() -> None:
    """Flush all pending writes to disk.

    Call during shutdown or before reading back entries for assertions.
    """
    _write_queue.flush_sync()
