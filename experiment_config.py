"""Deterministic generation policy for scored experiment pairs.

Seeds use all 256 SHA-256 bits modulo ``2**31``. The installed google-genai
2.21.0 Interactions type accepts ``int`` but documents no server-side range,
so this conservatively emits a non-negative signed-32-bit-compatible value.
"""

from __future__ import annotations

import hashlib

THINKING_LEVEL = "medium"
THINKING_SUMMARIES = "none"
# Validation ceiling from docs/API_VERIFICATION.md item 1, not a benchmark value.
MODEL_MAX_OUTPUT_TOKENS = 65_536
SEED_MODULUS = 2**31

ALLOWED_REPEATS = {
    "T001": frozenset({"R1", "R2", "R3"}),
    "T002": frozenset({"R1", "R2", "R3"}),
    "T003": frozenset({"R1", "R2", "R3"}),
    "T004": frozenset({"R1"}),
}
GENERATION_CONFIG_KEYS = {
    "thinking_level",
    "thinking_summaries",
    "max_output_tokens",
    "seed",
}


class GenerationConfigError(ValueError):
    """The pair identity or scored generation config violates policy."""

    def __init__(self, violations: list[str]):
        super().__init__("; ".join(violations))
        self.violations = violations


def _validate_identity(test_id: str, repeat_id: str) -> None:
    if not isinstance(test_id, str) or test_id not in ALLOWED_REPEATS:
        raise GenerationConfigError([f"test_id: unknown test {test_id!r}"])
    if not isinstance(repeat_id, str) or repeat_id not in ALLOWED_REPEATS[test_id]:
        raise GenerationConfigError(
            [f"repeat_id: {repeat_id!r} is not allowed for {test_id}"]
        )


def _normalize_digest(contract_sha256: str) -> str:
    digest = contract_sha256.lower() if isinstance(contract_sha256, str) else ""
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise GenerationConfigError(["contract_sha256: expected a SHA-256 digest"])
    return digest


def derive_seed(*, contract_sha256: str, test_id: str, repeat_id: str) -> int:
    """Derive the registered seed for one valid test/repeat identity."""
    _validate_identity(test_id, repeat_id)
    digest = _normalize_digest(contract_sha256)
    material = f"{digest}|{test_id}|{repeat_id}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest(), "big") % SEED_MODULUS


def validate_generation_config(
    config,
    *,
    contract_sha256: str,
    test_id: str,
    repeat_id: str,
) -> None:
    """Reject any config outside the exact scored-experiment policy."""
    _validate_identity(test_id, repeat_id)
    expected_seed = derive_seed(
        contract_sha256=contract_sha256, test_id=test_id, repeat_id=repeat_id
    )
    if not isinstance(config, dict):
        raise GenerationConfigError(["generation_config: expected a mapping"])

    violations = [
        f"generation_config.{key}: missing"
        for key in sorted(GENERATION_CONFIG_KEYS - set(config))
    ]
    violations.extend(
        f"generation_config.{key}: unexpected"
        for key in sorted(set(config) - GENERATION_CONFIG_KEYS, key=str)
    )
    if "thinking_level" in config and config["thinking_level"] != THINKING_LEVEL:
        violations.append(
            f"generation_config.thinking_level: expected {THINKING_LEVEL!r}, "
            f"got {config['thinking_level']!r}"
        )
    if (
        "thinking_summaries" in config
        and config["thinking_summaries"] != THINKING_SUMMARIES
    ):
        violations.append(
            f"generation_config.thinking_summaries: expected {THINKING_SUMMARIES!r}, "
            f"got {config['thinking_summaries']!r}"
        )
    if "max_output_tokens" in config:
        value = config["max_output_tokens"]
        if isinstance(value, bool) or not isinstance(value, int):
            violations.append(
                "generation_config.max_output_tokens: expected an integer"
            )
        elif not 1 <= value <= MODEL_MAX_OUTPUT_TOKENS:
            violations.append(
                "generation_config.max_output_tokens: "
                f"expected 1..{MODEL_MAX_OUTPUT_TOKENS}, got {value}"
            )
    if "seed" in config:
        seed = config["seed"]
        if isinstance(seed, bool) or not isinstance(seed, int):
            violations.append("generation_config.seed: expected an integer")
        elif seed != expected_seed:
            violations.append(
                f"generation_config.seed: expected derived seed {expected_seed}, got {seed}"
            )
    if violations:
        raise GenerationConfigError(violations)


def build_generation_config(
    *,
    contract_sha256: str,
    test_id: str,
    repeat_id: str,
    max_output_tokens: int,
) -> dict:
    """Build the exact four-key config; max_output_tokens has no default."""
    config = {
        "thinking_level": THINKING_LEVEL,
        "thinking_summaries": THINKING_SUMMARIES,
        "max_output_tokens": max_output_tokens,
        "seed": derive_seed(
            contract_sha256=contract_sha256,
            test_id=test_id,
            repeat_id=repeat_id,
        ),
    }
    validate_generation_config(
        config,
        contract_sha256=contract_sha256,
        test_id=test_id,
        repeat_id=repeat_id,
    )
    return config
