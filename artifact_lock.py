"""Exact-byte hash-lock and duplicate-safe JSON loading for offline artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def _is_digest(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def load_hash_locked_json(
    artifact_path: Path,
    *,
    artifact_label: str,
    lock_label: str,
    error_type,
    canonical_lock: bool = False,
):
    """Return parsed JSON and its verified exact-byte SHA-256 digest."""
    artifact_path = Path(artifact_path)
    lock_path = artifact_path.with_suffix(".sha256")
    if not artifact_path.is_file():
        raise error_type([f"{artifact_label}: file not found: {artifact_path}"])
    if not lock_path.is_file():
        raise error_type([f"{lock_label}: file not found: {lock_path}"])

    try:
        raw = artifact_path.read_bytes()
    except OSError as exc:
        raise error_type([f"{artifact_label}: unreadable: {exc}"]) from exc
    try:
        lock_text = lock_path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise error_type([f"{lock_label}: unreadable: {exc}"]) from exc

    if canonical_lock:
        match = re.fullmatch(
            rf"([0-9a-f]{{64}})  {re.escape(artifact_path.name)}\n", lock_text
        )
        if match is None:
            raise error_type([f"{lock_label}: malformed record: {lock_path}"])
        recorded = match.group(1)
    else:
        fields = lock_text.split()
        if (
            len(fields) != 2
            or not _is_digest(fields[0].lower())
            or fields[1].lstrip("*") != artifact_path.name
        ):
            raise error_type([f"{lock_label}: malformed record: {lock_path}"])
        recorded = fields[0].lower()

    computed = hashlib.sha256(raw).hexdigest()
    if computed != recorded:
        raise error_type(
            [f"{lock_label}: mismatch: computed {computed}, recorded {recorded}"]
        )

    def reject_duplicate_keys(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise error_type([f"json: duplicate key {key!r}"])
            value[key] = item
        return value

    try:
        parsed = json.loads(
            raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys
        )
    except error_type:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise error_type([f"{artifact_label}: invalid UTF-8 JSON: {exc}"]) from exc
    return parsed, computed
