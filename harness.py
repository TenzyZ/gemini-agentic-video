"""Offline foundation for the Gemini STATIC vs AGENTIC video benchmark.

Enforces the frozen contract (`CONTRACT.md` REV 1) before any Gemini request
exists. Everything here is offline and deterministic: stdlib only, no network
call, no Gemini client, no read of `GEMINI_API_KEY`.

Scope is deliberately the mechanisms CONTRACT.md requires up front:

* contract integrity, fail closed                              -- CONTRACT.md preamble
* resolved STATIC / AGENTIC payload construction               -- CONTRACT.md section 4
* per-arm validation of the complete frozen request shape      -- CONTRACT.md section 4
* deterministic generation-config policy and seed schedule     -- approved phase policy
* structured pair invariant: arms differ only at `processing`  -- CONTRACT.md section 4
* PRE-FLIGHT / HARNESS failure evidence, `request_made=false`  -- CONTRACT.md sections 4, 16
* raw-response-first persistence, no overwrite, no lossy write -- CONTRACT.md sections 10, 11

Two independent guarantees, both required before a pair is accepted:

1. each arm on its own matches the frozen request shape and approved generation
   policy, so two identically malformed arms cannot pass by agreeing;
2. the two arms differ only at the treatment field.

Values that are still a human decision -- the video URIs, the prompts, and
`max_output_tokens` -- are inputs to this module. It never supplies a default
for one.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path

import experiment_config

REPO_ROOT = Path(__file__).resolve().parent
CONTRACT_PATH = REPO_ROOT / "CONTRACT.md"
CONTRACT_SHA_PATH = REPO_ROOT / "CONTRACT.sha256"

CONTRACT_REV = "REV 1"

# Frozen by CONTRACT.md sections 2-4. Not configurable.
MODEL = "gemini-3.7-flash"
RESOLUTION = "low"
ARMS = {"STATIC": "static", "AGENTIC": "agentic"}

# The frozen request shape: exactly these keys, in this structure.
TOP_LEVEL_KEYS = {"model", "input", "generation_config"}
VIDEO_BLOCK_KEYS = {"type", "uri", "processing", "resolution"}
TEXT_BLOCK_KEYS = {"type", "text"}
#: Static-only controls. CONTRACT.md section 4: not set, in either arm.
STATIC_ONLY_KEYS = ("fps", "start_offset", "end_offset")

#: The single field the two arms of a pair are permitted to differ at.
PAIR_VARIABLE_PATH = "input[0].processing"
PAIR_INVARIANT = f"arms of a pair differ only at {PAIR_VARIABLE_PATH}"

# Failure categories. Small on purpose: enough to reconstruct what failed.
CONTRACT_INTEGRITY = "CONTRACT_INTEGRITY"
REQUEST_SHAPE = "REQUEST_SHAPE"
GENERATION_CONFIG = "GENERATION_CONFIG"
PAIR_DIFFERENCE = "PAIR_DIFFERENCE"

FAILED_INVARIANT = {
    CONTRACT_INTEGRITY: "CONTRACT.md matches the hash recorded in CONTRACT.sha256",
    REQUEST_SHAPE: "each arm matches the frozen request shape (CONTRACT.md section 4)",
    GENERATION_CONFIG: "each arm matches the approved scored generation-config policy",
    PAIR_DIFFERENCE: PAIR_INVARIANT,
}


class ContractIntegrityError(Exception):
    """The frozen contract is missing, unreadable, or does not match its hash."""


class InvariantViolation(Exception):
    """A pair violated a frozen invariant. Carries its category and details."""

    def __init__(self, category: str, violations: list[str]):
        super().__init__(FAILED_INVARIANT[category])
        self.category = category
        self.violations = violations


class PreflightError(Exception):
    """Preflight rejected a pair. Carries the failure record."""

    def __init__(self, record: dict):
        super().__init__(record["failed_invariant"])
        self.record = record


class EvidenceExistsError(Exception):
    """Refused to overwrite an already-written evidence artifact."""


class EvidenceSerializationError(Exception):
    """Refused to write incomplete evidence for an object we cannot serialize."""


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


def build_pair(
    test_id: str,
    repeat_id: str,
    *,
    video_uri: str,
    prompt: str,
    max_output_tokens: int,
) -> dict[str, dict]:
    """Build both arms with one policy-derived config from the verified contract."""
    generation_config = experiment_config.build_generation_config(
        contract_sha256=verify_contract(),
        test_id=test_id,
        repeat_id=repeat_id,
        max_output_tokens=max_output_tokens,
    )
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
# per-arm frozen request shape (CONTRACT.md section 4)
# --------------------------------------------------------------------------


def _nonempty_str(value) -> bool:
    return isinstance(value, str) and value != ""


def validate_arm(arm: str, payload) -> list[str]:
    """Return every way one resolved payload departs from the frozen shape.

    Checked per arm, independently of the other arm, so two identically
    malformed payloads cannot pass by agreeing with each other.
    """
    bad: list[str] = []

    def flag(path: str, reason: str) -> None:
        bad.append(f"{arm}:{path} ({reason})")

    if not isinstance(payload, dict):
        return [f"{arm}: payload is not a mapping"]

    for key in sorted(TOP_LEVEL_KEYS - set(payload)):
        flag(key, "missing")
    for key in sorted(set(payload) - TOP_LEVEL_KEYS):
        flag(key, "unexpected top-level field")

    if payload.get("model") != MODEL:
        flag("model", f"expected {MODEL!r}, got {payload.get('model')!r}")

    blocks = payload.get("input")
    if not isinstance(blocks, list) or len(blocks) != 2:
        flag("input", "expected a two-item list in the frozen order")
        blocks = None

    if blocks is not None:
        video, text = blocks
        if not isinstance(video, dict):
            flag("input[0]", "expected the video block mapping")
        else:
            for key in sorted(VIDEO_BLOCK_KEYS - set(video)):
                flag(f"input[0].{key}", "missing")
            for key in sorted(set(video) - VIDEO_BLOCK_KEYS):
                reason = (
                    "static-only control, not set in either arm"
                    if key in STATIC_ONLY_KEYS
                    else "unexpected field on the video block"
                )
                flag(f"input[0].{key}", reason)
            if video.get("type") != "video":
                flag("input[0].type", f"expected 'video', got {video.get('type')!r}")
            if not _nonempty_str(video.get("uri")):
                flag("input[0].uri", "expected a non-empty string")
            if video.get("processing") != ARMS[arm]:
                flag(
                    "input[0].processing",
                    f"expected {ARMS[arm]!r}, got {video.get('processing')!r}",
                )
            if video.get("resolution") != RESOLUTION:
                flag(
                    "input[0].resolution",
                    f"expected {RESOLUTION!r}, got {video.get('resolution')!r}",
                )

        if not isinstance(text, dict):
            flag("input[1]", "expected the text block mapping")
        else:
            for key in sorted(TEXT_BLOCK_KEYS - set(text)):
                flag(f"input[1].{key}", "missing")
            for key in sorted(set(text) - TEXT_BLOCK_KEYS):
                flag(f"input[1].{key}", "unexpected field on the text block")
            if text.get("type") != "text":
                flag("input[1].type", f"expected 'text', got {text.get('type')!r}")
            if not _nonempty_str(text.get("text")):
                flag("input[1].text", "expected a non-empty string")

    config = payload.get("generation_config")
    if "generation_config" in payload:
        if not isinstance(config, dict) or not config:
            flag("generation_config", "expected a non-empty mapping, explicitly set")

    return bad


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


def check_pair(
    test_id: str,
    repeat_id: str,
    pair: dict[str, dict],
    *,
    contract_sha256: str,
) -> None:
    """Verify both frozen guarantees. Raises `InvariantViolation` on failure."""
    if set(pair) != set(ARMS):
        raise InvariantViolation(
            REQUEST_SHAPE, [f"pair must contain exactly {sorted(ARMS)}; got {sorted(pair)}"]
        )

    shape = [v for arm in sorted(pair) for v in validate_arm(arm, pair[arm])]
    if shape:
        raise InvariantViolation(REQUEST_SHAPE, shape)

    config_violations = []
    for arm in sorted(pair):
        try:
            experiment_config.validate_generation_config(
                pair[arm]["generation_config"],
                contract_sha256=contract_sha256,
                test_id=test_id,
                repeat_id=repeat_id,
            )
        except experiment_config.GenerationConfigError as exc:
            config_violations.extend(f"{arm}:{violation}" for violation in exc.violations)
    if config_violations:
        raise InvariantViolation(GENERATION_CONFIG, config_violations)

    differing = diff_paths(pair["STATIC"], pair["AGENTIC"])
    if differing != [PAIR_VARIABLE_PATH]:
        raise InvariantViolation(
            PAIR_DIFFERENCE, differing or ["<arms are identical: no experimental variable>"]
        )


# --------------------------------------------------------------------------
# preflight
# --------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_sha(payload) -> str:
    try:
        return payload_sha256(payload)
    except (TypeError, ValueError):
        return "UNSERIALIZABLE"


def preflight(
    test_id: str,
    repeat_id: str,
    pair: dict[str, dict],
    evidence_dir: Path | None = None,
    *,
    verify=verify_contract,
) -> str:
    """Verify the frozen contract and the pair before any request is made.

    Returns the verified contract digest when the pair is valid, so later
    provenance code can record what it ran under. Otherwise records a
    PRE-FLIGHT / HARNESS failure with `request_made = false` and raises
    `PreflightError`. No API function is invoked on either path.

    `verify` is injectable so tests can simulate a contract-integrity
    failure without touching the frozen artifacts.
    """
    record = {
        "stage": "PRE-FLIGHT",
        "failure_class": "HARNESS",
        "request_made": False,
        "timestamp": None,
        "pair_id": f"{test_id}/{repeat_id}",
        "contract_rev": CONTRACT_REV,
    }

    try:
        digest = verify()
    except ContractIntegrityError as exc:
        record |= {
            "timestamp": _now(),
            "invariant_category": CONTRACT_INTEGRITY,
            "failed_invariant": FAILED_INVARIANT[CONTRACT_INTEGRITY],
            "violations": [f"CONTRACT.md integrity: {exc}"],
        }
        _record_preflight_failure(record, evidence_dir)

    try:
        check_pair(test_id, repeat_id, pair, contract_sha256=digest)
        return digest
    except InvariantViolation as exc:
        record |= {
            "timestamp": _now(),
            "contract_sha256": digest,
            "invariant_category": exc.category,
            "failed_invariant": FAILED_INVARIANT[exc.category],
            "violations": exc.violations,
            "payload_sha256": {arm: _safe_sha(payload) for arm, payload in pair.items()},
        }
        if exc.category == PAIR_DIFFERENCE:
            flat = {arm: _flatten(payload) for arm, payload in pair.items()}
            record["differing_values"] = {
                path: {arm: flat[arm].get(path) for arm in pair} for path in exc.violations
            }
        _record_preflight_failure(record, evidence_dir)


def _record_preflight_failure(record: dict, evidence_dir: Path | None) -> None:
    if evidence_dir is not None:
        write_evidence(Path(evidence_dir), "preflight_failure.json", record)
    raise PreflightError(record)


# --------------------------------------------------------------------------
# evidence persistence (CONTRACT.md sections 10-11)
# --------------------------------------------------------------------------


def _json_default(obj):
    """Serialize an object whole, or fail. Never a lossy stand-in.

    Structured serializers are accepted in order; anything we cannot
    reconstruct completely raises rather than writing a `repr()` string
    into evidence that claims to be raw.
    """
    for attr in ("model_dump", "to_dict", "dict"):
        method = getattr(obj, attr, None)
        if callable(method):
            try:
                return method()
            except Exception as exc:  # noqa: BLE001 - loud, not lossy
                raise EvidenceSerializationError(
                    f"{type(obj).__name__}.{attr}() failed: {exc!r}"
                ) from exc
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    state = getattr(obj, "__dict__", None)
    if state:
        return dict(state)
    raise EvidenceSerializationError(
        f"cannot serialize {type(obj).__name__} completely: no model_dump/to_dict/dict, "
        "not a dataclass, no instance __dict__"
    )


def write_evidence(attempt_dir: Path, name: str, data) -> Path:
    """Write one evidence artifact. Never overwrites, never writes partial JSON.

    Serialization happens before the file is created, so a serialization
    failure leaves no artifact behind at all.
    """
    payload = data if isinstance(data, str) else json.dumps(data, indent=2, default=_json_default)
    attempt_dir = Path(attempt_dir)
    attempt_dir.mkdir(parents=True, exist_ok=True)
    path = attempt_dir / name
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
    uncleaned, unformatted, untrimmed. If the response cannot be serialized
    completely, `EvidenceSerializationError` is raised and neither artifact
    is created.
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
