"""Inbox polling: stability detection, SHA-256 dedup, doc_id assignment, filing.

Never logs a filename or path - only doc_id, status and byte counts.
"""
from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from vault import db

SUPPORTED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".txt"}


def sha256_of(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def make_doc_id(sha256_hex: str, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%S%f")[:-3] + "Z"
    return f"{ts}-{sha256_hex[:8]}"


@dataclass
class StabilityTracker:
    """Tracks per-file (size, consecutive-poll count) across polls.

    A file counts as stable once its size has been identical for
    `stable_polls` consecutive polls. State is in-memory only, scoped to one
    daemon process lifetime - that matches the brief's "stable for two
    polls" check, which only needs to survive between polls, not restarts.
    """

    stable_polls: int = 2
    _seen: dict[str, tuple[int, int]] = field(default_factory=dict)

    def poll(self, inbox_dir: Path) -> list[Path]:
        current: dict[str, tuple[int, int]] = {}
        stable: list[Path] = []
        for p in sorted(Path(inbox_dir).iterdir()):
            if not p.is_file():
                continue
            try:
                size = p.stat().st_size
            except FileNotFoundError:
                continue
            key = str(p)
            prev = self._seen.get(key)
            count = prev[1] + 1 if prev and prev[0] == size else 1
            current[key] = (size, count)
            if count >= self.stable_polls:
                stable.append(p)
        self._seen = current
        return stable


@dataclass
class IngestResult:
    outcome: str  # "new" | "duplicate" | "unsupported"
    doc_id: str | None


def ingest_one(conn, path: Path, store_root: Path) -> IngestResult:
    """Files one stable inbox entry. Never deletes the source file itself -
    a duplicate or unsupported file is left exactly where it was found."""
    ext = path.suffix.lower()
    sha256 = sha256_of(path)

    existing = db.get_doc_by_sha256(conn, sha256)
    if existing is not None:
        return IngestResult("duplicate", existing["id"])

    if ext not in SUPPORTED_EXTS:
        doc_id = make_doc_id(sha256)
        db.insert_doc(
            conn,
            doc_id=doc_id,
            sha256=sha256,
            original_ext=ext or "",
            status="unsupported",
            store_path=str(path),
        )
        return IngestResult("unsupported", doc_id)

    doc_id = make_doc_id(sha256)
    year = datetime.now(timezone.utc).strftime("%Y")
    dest_dir = Path(store_root) / year
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{doc_id}{ext}"
    shutil.move(str(path), str(dest))

    db.insert_doc(
        conn,
        doc_id=doc_id,
        sha256=sha256,
        original_ext=ext,
        status="new",
        store_path=str(dest),
    )
    return IngestResult("new", doc_id)


def ingest_pass(conn, tracker: StabilityTracker, inbox_dir: Path, store_root: Path) -> list[IngestResult]:
    """One polling pass: finds stable files and files each of them."""
    results = []
    for path in tracker.poll(inbox_dir):
        if not path.exists():
            continue
        results.append(ingest_one(conn, path, store_root))
    return results
