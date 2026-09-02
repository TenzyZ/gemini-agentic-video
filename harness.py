"""Offline foundation for the Gemini STATIC vs AGENTIC video benchmark.

Enforces the frozen contract (`CONTRACT.md` REV 1) before any Gemini request
exists. Everything here is offline and deterministic: stdlib only, no network
call, no Gemini client, no read of `GEMINI_API_KEY`.

Scope is deliberately the mechanisms CONTRACT.md requires up front:

* contract integrity (fail closed)                            -- CONTRACT.md preamble
* resolved STATIC / AGENTIC payload construction              -- CONTRACT.md section 4
* structured pair invariant: arms differ only at `processing` -- CONTRACT.md section 4
* PRE-FLIGHT / HARNESS failure evidence, `request_made=false` -- CONTRACT.md sections 4, 16
* raw-response-first persistence, no overwrite                -- CONTRACT.md sections 10, 11

Values that are still a human decision -- the video URIs, the prompts, the
concrete `generation_config` -- are inputs to this module. It never supplies
a default for one.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
CONTRACT_PATH = REPO_ROOT / "CONTRACT.md"
CONTRACT_SHA_PATH = REPO_ROOT / "CONTRACT.sha256"

CONTRACT_REV = "REV 1"

# Frozen by CONTRACT.md sections 2-4. Not configurable.
MODEL = "gemini-3.7-flash"
RESOLUTION = "low"
ARMS = {"STATIC": "static", "AGENTIC": "agentic"}

#: The single field the two arms of a pair are permitted to differ at.
PAIR_VARIABLE_PATH = "input[0].processing"
PAIR_INVARIANT = f"arms of a pair differ only at {PAIR_VARIABLE_PATH}"


class ContractIntegrityError(Exception):
    """The frozen contract is missing, unreadable, or does not match its hash."""


class PreflightError(Exception):
    """A pair violated a frozen invariant. Carries the failure record."""

    def __init__(self, record: dict):
        super().__init__(record["failed_invariant"])
        self.record = record


class EvidenceExistsError(Exception):
    """Refused to overwrite an already-written evidence artifact."""


# --------------------------------------------------------------------------
# contract integrity
# --------------------------------------------------------------------------


def verify_contract(
    contract_path: Path = CONTRACT_PATH,
    sha_path: Path = CONTRACT_SHA_PATH,
) -> str:
    """Verify `CONTRACT.md` against `CONTRACT.sha256`; return the digest.

    Fails closed: any missing file, malformed record or mismatch raises.
    Reads bytes, so no newline translation can alter the digest. Neither
    frozen artifact is ever written.
    """
    if not contract_path.is_file():
        raise ContractIntegrityError(f"contract not found: {contract_path}")
    if not sha_path.is_file():
        raise ContractIntegrityError(f"recorded hash not found: {sha_path}")

    fields = sha_path.read_bytes().decode("utf-8").split()
    if not fields:
        raise ContractIntegrityError(f"recorded hash is empty: {sha_path}")
    recorded = fields[0].lower()
    if len(recorded) != 64 or any(c not in "0123456789abcdef" for c in recorded):
        raise ContractIntegrityError(f"recorded hash is not a sha256 digest: {fields[0]!r}")

    computed = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    if computed != recorded:
        raise ContractIntegrityError(
            f"contract hash mismatch: computed {computed}, recorded {recorded}"
        )
    return computed


# --------------------------------------------------------------------------
# payload construction
# --------------------------------------------------------------------------


def build_payload(arm: str, *, video_uri: str, prompt: str, generation_config: dict) -> dict:
    """Build one resolved Interactions request payload in the frozen shape."""
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}; expected one of {sorted(ARMS)}")
    if not video_uri or not prompt:
        raise ValueError("video_uri and prompt are required and must be non-empty")
    if not isinstance(generation_config, dict) or not generation_config:
        raise ValueError("generation_config must be a non-empty mapping, explicitly set")
    if generation_config.get("thinking_level") == "minimal":
        # CONTRACT.md section 4: documented to error on this model.
        raise ValueError("thinking_level must not be 'minimal'")

    return {
        "model": MODEL,
        "input": [
            {
                "type": "video",
                "uri": video_uri,
                "processing": ARMS[arm],
                "resolution": RESOLUTION,
            },
            {"type": "text", "text": prompt},
        ],
        "generation_config": deepcopy(generation_config),
    }


def build_pair(*, video_uri: str, prompt: str, generation_config: dict) -> dict[str, dict]:
    """Build both arms of one pair from a single set of inputs."""
    return {
        arm: build_payload(
            arm, video_uri=video_uri, prompt=prompt, generation_config=generation_config
        )
        for arm in ARMS
    }


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def payload_sha256(payload: dict) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# structured pair comparison
# --------------------------------------------------------------------------


def _flatten(obj, prefix: str = "") -> dict[str, object]:
    """Flatten nested data to {leaf path: value}, e.g. 'input[0].processing'."""
    out: dict[str, object] = {}
    if isinstance(obj, dict) and obj:
        for key, value in obj.items():
            out.update(_flatten(value, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(obj, list) and obj:
        for i, value in enumerate(obj):
            out.update(_flatten(value, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj  # scalar, or an empty container as its own leaf
    return out


def diff_paths(a: dict, b: dict) -> list[str]:
    """Sorted leaf paths where two payloads differ, structurally not textually."""
    flat_a, flat_b = _flatten(a), _flatten(b)
    missing = object()
    return sorted(
        path
        for path in set(flat_a) | set(flat_b)
        if flat_a.get(path, missing) != flat_b.get(path, missing)
    )


def _frozen_field_violations(pair: dict[str, dict]) -> list[str]:
    """Paths where a payload departs from a value CONTRACT.md freezes outright."""
    bad = []
    for arm, payload in pair.items():
        flat = _flatten(payload)
        if flat.get("model") != MODEL:
            bad.append(f"{arm}:model")
        if flat.get("input[0].resolution") != RESOLUTION:
            bad.append(f"{arm}:input[0].resolution")
        if flat.get("input[0].processing") != ARMS[arm]:
            bad.append(f"{arm}:input[0].processing")
    return sorted(bad)


def check_pair(pair: dict[str, dict]) -> None:
    """Raise ValueError listing every frozen-invariant violation in a pair."""
    if set(pair) != set(ARMS):
        raise ValueError(f"pair must contain exactly {sorted(ARMS)}; got {sorted(pair)}")

    problems = _frozen_field_violations(pair)
    differing = diff_paths(pair["STATIC"], pair["AGENTIC"])
    if differing != [PAIR_VARIABLE_PATH]:
        problems.extend(differing or ["<arms are identical: no experimental variable>"])
    if problems:
        raise ValueError(sorted(set(problems)))


# --------------------------------------------------------------------------
# preflight
# --------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat()


def preflight(pair_id: str, pair: dict[str, dict], evidence_dir: Path | None = None) -> None:
    """Verify a pair before any request is made.

    Returns None when the pair is valid. Otherwise records a PRE-FLIGHT /
    HARNESS failure with `request_made = false` and raises `PreflightError`.
    No API function is invoked on either path.
    """
    try:
        check_pair(pair)
        return
    except ValueError as exc:
        problems = exc.args[0] if isinstance(exc.args[0], list) else [str(exc)]

    flat = {arm: _flatten(payload) for arm, payload in pair.items()}
    record = {
        "stage": "PRE-FLIGHT",
        "failure_class": "HARNESS",
        "request_made": False,
        "timestamp": _now(),
        "pair_id": pair_id,
        "contract_rev": CONTRACT_REV,
        "failed_invariant": PAIR_INVARIANT,
        "differing_paths": problems,
        "differing_values": {
            path: {arm: flat[arm].get(path.split(":")[-1]) for arm in pair}
            for path in problems
        },
        "payload_sha256": {arm: payload_sha256(payload) for arm, payload in pair.items()},
    }
    if evidence_dir is not None:
        write_evidence(Path(evidence_dir), "preflight_failure.json", record)
    raise PreflightError(record)


# --------------------------------------------------------------------------
# evidence persistence (CONTRACT.md sections 10-11)
# --------------------------------------------------------------------------


def _json_default(obj):
    """Serialize SDK-shaped objects without hand-picking a subset of fields."""
    for attr in ("model_dump", "to_dict", "dict"):
        method = getattr(obj, attr, None)
        if callable(method):
            try:
                return method()
            except Exception:  # noqa: BLE001 - evidence must still be written
                pass
    if hasattr(obj, "__dict__"):
        return vars(obj)
    return repr(obj)


def write_evidence(attempt_dir: Path, name: str, data) -> Path:
    """Write one evidence artifact. Never overwrites an existing one."""
    attempt_dir = Path(attempt_dir)
    attempt_dir.mkdir(parents=True, exist_ok=True)
    path = attempt_dir / name
    payload = data if isinstance(data, str) else json.dumps(data, indent=2, default=_json_default)
    try:
        with open(path, "x", encoding="utf-8", newline="") as fh:
            fh.write(payload)
    except FileExistsError as exc:
        raise EvidenceExistsError(f"refusing to overwrite existing evidence: {path}") from exc
    return path


def persist_response(attempt_dir: Path, response, answer_text: str) -> dict[str, Path]:
    """Write raw response then exact answer text, before anything parses either.

    `response` is serialized whole -- steps, status, errors and the entire
    usage object as-is. `answer_text` is written verbatim: unedited,
    uncleaned, unformatted, untrimmed.
    """
    raw = write_evidence(attempt_dir, "raw_response.json", response)
    answer = write_evidence(attempt_dir, "answer.txt", answer_text)
    return {"raw_response": raw, "answer_text": answer}


def persist_error(attempt_dir: Path, error: BaseException, attempt: int = 1) -> Path:
    """Write raw error evidence before any classification or retry decision.

    No response or answer artifact is fabricated for an attempt that never
    produced one.
    """
    record = {
        "timestamp": _now(),
        "attempt": attempt,
        "request_made": True,
        "exception_type": type(error).__name__,
        "message": str(error),
        "http_status": getattr(error, "status_code", None),
        "request_id": getattr(error, "request_id", None),
        "raw": repr(error),
    }
    return write_evidence(attempt_dir, f"raw_error_attempt{attempt}.json", record)


def load_raw_response(attempt_dir: Path) -> dict:
    """Read persisted raw evidence. Parsers read the file, never a live object."""
    path = Path(attempt_dir) / "raw_response.json"
    if not path.is_file():
        raise FileNotFoundError(f"no persisted raw response to parse: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
