"""
api/services/note_store.py — Bed notes (§11.12).

Simple in-memory store with optional JSONL persistence.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("sentinel.audit")

_NOTE_LOG = Path("data/notes_log.jsonl")


@dataclass
class BedNote:
    note_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    bed_id: str = ""
    text: str = ""
    created_at: float = field(default_factory=time.time)


class NoteStore:
    """Per-bed rolling note store. Persisted to JSONL file."""

    MAX_PER_BED = 100

    def __init__(self, log_path: Path = _NOTE_LOG) -> None:
        self._notes: dict[str, list[BedNote]] = {}   # bed_id → list[BedNote]
        self._lock = threading.Lock()
        self._log_path = log_path
        self._load_from_file()

    def add(self, note: BedNote) -> BedNote:
        with self._lock:
            bucket = self._notes.setdefault(note.bed_id, [])
            if len(bucket) >= self.MAX_PER_BED:
                bucket.pop(0)
            bucket.append(note)
        self._append_to_file(note)
        audit_logger.info("NOTE | bed=%s | text=%.80s", note.bed_id, note.text)
        return note

    def get(self, bed_id: str, last_n: int = 50) -> list[BedNote]:
        with self._lock:
            return list(self._notes.get(bed_id, []))[-last_n:]

    def _append_to_file(self, note: BedNote) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(dataclasses.asdict(note)) + "\n")
        except OSError as exc:
            logger.warning("Note log write failed: %s", exc)

    def _load_from_file(self) -> None:
        if not self._log_path.exists():
            return
        try:
            with open(self._log_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        note = BedNote(**d)
                        self._notes.setdefault(note.bed_id, []).append(note)
                    except Exception:
                        pass
        except OSError:
            pass
