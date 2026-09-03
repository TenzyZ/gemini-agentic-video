"""Offline loader and validator for hash-locked experiment test specs."""

from __future__ import annotations

import hashlib
from pathlib import Path

import artifact_lock
import experiment_config
import harness

SPEC_VERSION = 1
QUESTION_IDS = tuple(f"Q{i:03d}" for i in range(1, 13))
QUESTION_MIX = {"global": 6, "localized": 6, "absence_probes": 2}

TOP_LEVEL_KEYS = {
    "spec_version",
    "test_id",
    "test_class",
    "contract_rev",
    "contract_sha256",
    "video",
    "prompt",
    "question_mix",
    "questions",
    "arms",
    "repeats",
}
VIDEO_KEYS = {"uri", "video_duration_s", "resolution"}
PROMPT_KEYS = {"text", "sha256"}
QUESTION_KEYS = {
    "question_id",
    "category",
    "requires_timestamp",
    "expects_absence",
}
REPEAT_KEYS = {"arm_order", "generation_config"}


class SpecValidationError(ValueError):
    """A test spec or one of its byte-level bindings is invalid."""

    def __init__(self, violations: list[str]):
        super().__init__("; ".join(violations))
        self.violations = violations


def _exact_mapping(value, path: str, keys: set[str], violations: list[str]) -> bool:
    if not isinstance(value, dict):
        violations.append(f"{path}: expected a mapping")
        return False
    violations.extend(f"{path}.{key}: missing" for key in sorted(keys - set(value)))
    violations.extend(f"{path}.{key}: unexpected" for key in sorted(set(value) - keys))
    return True


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_digest(value) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def _validate_video(spec: dict, violations: list[str]) -> None:
    video = spec.get("video")
    if not _exact_mapping(video, "video", VIDEO_KEYS, violations):
        return
    if not isinstance(video.get("uri"), str) or not video.get("uri"):
        violations.append("video.uri: expected a non-empty string")
    duration = video.get("video_duration_s")
    if not _is_int(duration) or duration <= 0:
        violations.append("video.video_duration_s: expected a positive integer")
    if video.get("resolution") != harness.RESOLUTION:
        violations.append(
            f"video.resolution: expected {harness.RESOLUTION!r}, "
            f"got {video.get('resolution')!r}"
        )


def _validate_prompt(spec: dict, violations: list[str]) -> str | None:
    prompt = spec.get("prompt")
    if not _exact_mapping(prompt, "prompt", PROMPT_KEYS, violations):
        return None
    text = prompt.get("text")
    if not isinstance(text, str) or not text:
        violations.append("prompt.text: expected a non-empty string")
        return None
    recorded = prompt.get("sha256")
    if not _is_digest(recorded):
        violations.append("prompt.sha256: expected a lowercase SHA-256 digest")
    else:
        try:
            computed = hashlib.sha256(text.encode("utf-8")).hexdigest()
        except UnicodeEncodeError:
            violations.append("prompt.text: expected UTF-8-encodable text")
        else:
            if computed != recorded:
                violations.append(
                    f"prompt.sha256: mismatch: computed {computed}, recorded {recorded}"
                )
    return text


def _validate_question_mix(spec: dict, violations: list[str]) -> None:
    mix = spec.get("question_mix")
    if not _exact_mapping(mix, "question_mix", set(QUESTION_MIX), violations):
        return
    for key, expected in QUESTION_MIX.items():
        value = mix.get(key)
        if not _is_int(value):
            violations.append(f"question_mix.{key}: expected an integer")
        elif value != expected:
            violations.append(
                f"question_mix.{key}: expected {expected}, got {value}"
            )


def _validate_questions(spec: dict, prompt_text: str | None, violations: list[str]) -> None:
    questions = spec.get("questions")
    if not isinstance(questions, list):
        violations.append("questions: expected a list")
        return
    if len(questions) != len(QUESTION_IDS):
        violations.append(f"questions: expected 12 items, got {len(questions)}")

    ids = []
    categories = []
    absence_categories = []
    for index, question in enumerate(questions):
        path = f"questions[{index}]"
        if not _exact_mapping(question, path, QUESTION_KEYS, violations):
            continue

        question_id = question.get("question_id")
        if not isinstance(question_id, str):
            violations.append(f"{path}.question_id: expected a string")
        else:
            ids.append(question_id)
            if prompt_text is not None and question_id not in prompt_text:
                violations.append(f"{path}.question_id: absent from prompt.text")

        category = question.get("category")
        if category not in ("global", "localized"):
            violations.append(
                f"{path}.category: expected 'global' or 'localized'"
            )
            category = None
        else:
            categories.append(category)

        requires_timestamp = question.get("requires_timestamp")
        if not isinstance(requires_timestamp, bool):
            violations.append(f"{path}.requires_timestamp: expected a boolean")
        elif category is not None and requires_timestamp != (category == "localized"):
            violations.append(
                f"{path}.requires_timestamp: must be {category == 'localized'} "
                f"for {category} questions"
            )

        expects_absence = question.get("expects_absence")
        if not isinstance(expects_absence, bool):
            violations.append(f"{path}.expects_absence: expected a boolean")
        elif expects_absence and category is not None:
            absence_categories.append(category)

    if len(set(ids)) != len(ids):
        violations.append("questions.question_id: duplicate")
    if tuple(ids) != QUESTION_IDS:
        violations.append("questions.question_id: expected Q001..Q012 in order without gaps")
    for category in ("global", "localized"):
        count = categories.count(category)
        if count != QUESTION_MIX[category]:
            violations.append(
                f"questions.category: expected {QUESTION_MIX[category]} {category}, got {count}"
            )
    if len(absence_categories) != QUESTION_MIX["absence_probes"]:
        violations.append(
            "questions.expects_absence: expected 2 true values, "
            f"got {len(absence_categories)}"
        )
    elif sorted(absence_categories) != ["global", "localized"]:
        violations.append(
            "questions.expects_absence: expected one global and one localized probe"
        )


def _validate_arms(spec: dict, violations: list[str]) -> None:
    arms = spec.get("arms")
    if not _exact_mapping(arms, "arms", set(harness.ARMS), violations):
        return
    for arm, processing in harness.ARMS.items():
        value = arms.get(arm)
        path = f"arms.{arm}"
        if not _exact_mapping(value, path, {"processing"}, violations):
            continue
        if value.get("processing") != processing:
            violations.append(
                f"{path}.processing: expected {processing!r}, "
                f"got {value.get('processing')!r}"
            )


def _arm_order(repeat_id: str) -> list[str]:
    return ["AGENTIC", "STATIC"] if repeat_id == "R2" else ["STATIC", "AGENTIC"]


def _validate_repeats(spec: dict, test_id: str | None, contract_sha256: str, violations: list[str]) -> None:
    repeats = spec.get("repeats")
    if not isinstance(repeats, dict):
        violations.append("repeats: expected a mapping")
        return
    if test_id not in experiment_config.ALLOWED_REPEATS:
        return

    expected_repeats = experiment_config.ALLOWED_REPEATS[test_id]
    for repeat_id in sorted(expected_repeats - set(repeats)):
        violations.append(f"repeats.{repeat_id}: missing")
    for repeat_id in sorted(set(repeats) - expected_repeats):
        violations.append(f"repeats.{repeat_id}: unexpected")

    for repeat_id in sorted(expected_repeats & set(repeats)):
        repeat = repeats[repeat_id]
        path = f"repeats.{repeat_id}"
        if not _exact_mapping(repeat, path, REPEAT_KEYS, violations):
            continue
        if repeat.get("arm_order") != _arm_order(repeat_id):
            violations.append(
                f"{path}.arm_order: expected {_arm_order(repeat_id)!r}, "
                f"got {repeat.get('arm_order')!r}"
            )

        config = repeat.get("generation_config")
        try:
            experiment_config.validate_generation_config(
                config,
                contract_sha256=contract_sha256,
                test_id=test_id,
                repeat_id=repeat_id,
            )
        except experiment_config.GenerationConfigError as exc:
            violations.extend(f"{path}.{item}" for item in exc.violations)
        else:
            expected_seed = experiment_config.derive_seed(
                contract_sha256=contract_sha256,
                test_id=test_id,
                repeat_id=repeat_id,
            )
            if config["seed"] != expected_seed:
                violations.append(f"{path}.generation_config.seed: wrong derived seed")

        if isinstance(config, dict) and config.get("max_output_tokens") != (
            experiment_config.SCORED_MAX_OUTPUT_TOKENS
        ):
            violations.append(
                f"{path}.generation_config.max_output_tokens: expected "
                f"{experiment_config.SCORED_MAX_OUTPUT_TOKENS}"
            )


def validate_spec(spec, *, filename_stem: str | None = None) -> None:
    """Validate parsed spec data against every frozen structural binding."""
    violations: list[str] = []
    if not _exact_mapping(spec, "spec", TOP_LEVEL_KEYS, violations):
        raise SpecValidationError(violations)

    version = spec.get("spec_version")
    if not _is_int(version) or version != SPEC_VERSION:
        violations.append(f"spec_version: expected integer {SPEC_VERSION}")

    test_id = spec.get("test_id")
    if not isinstance(test_id, str) or test_id not in experiment_config.ALLOWED_REPEATS:
        violations.append(f"test_id: unknown test {test_id!r}")
        valid_test_id = None
    else:
        valid_test_id = test_id
    if (
        isinstance(test_id, str)
        and filename_stem is not None
        and filename_stem != test_id
    ):
        violations.append(
            "spec filename/test_id mismatch: "
            f"{filename_stem + '.json'!r} != {test_id + '.json'!r}"
        )

    expected_class = "STRESS" if test_id == "T004" else "BENCHMARK"
    if valid_test_id is not None and spec.get("test_class") != expected_class:
        violations.append(
            f"test_class: expected {expected_class!r}, got {spec.get('test_class')!r}"
        )
    elif valid_test_id is None and not isinstance(spec.get("test_class"), str):
        violations.append("test_class: expected a string")

    if spec.get("contract_rev") != harness.CONTRACT_REV:
        violations.append(
            f"contract_rev: expected {harness.CONTRACT_REV!r}, "
            f"got {spec.get('contract_rev')!r}"
        )

    try:
        contract_sha256 = harness.verify_contract()
    except harness.ContractIntegrityError as exc:
        violations.append(f"CONTRACT.md integrity: {exc}")
        contract_sha256 = ""
    if spec.get("contract_sha256") != contract_sha256:
        violations.append("contract_sha256: does not match the verified frozen contract")

    _validate_video(spec, violations)
    prompt_text = _validate_prompt(spec, violations)
    _validate_question_mix(spec, violations)
    _validate_questions(spec, prompt_text, violations)
    _validate_arms(spec, violations)
    _validate_repeats(spec, valid_test_id, contract_sha256, violations)

    if violations:
        raise SpecValidationError(violations)


def load_spec_with_digest(
    spec_path: Path, evidence_dir: Path | None = None
) -> tuple[dict, str]:
    """Verify and return one frozen test spec plus its exact-byte digest.

    When ``evidence_dir`` is supplied, failures use the harness's standard
    PRE-FLIGHT / HARNESS evidence path and its non-overwrite guarantee.
    """
    spec_path = Path(spec_path)
    test_id = spec_path.stem
    try:
        spec, digest = artifact_lock.load_hash_locked_json(
            spec_path,
            artifact_label="spec",
            lock_label="spec_sha256",
            error_type=SpecValidationError,
        )
        if isinstance(spec, dict) and isinstance(spec.get("test_id"), str):
            test_id = spec["test_id"]
        validate_spec(spec, filename_stem=spec_path.stem)
        return spec, digest
    except SpecValidationError as exc:
        if evidence_dir is not None:
            harness.record_preflight_failure(
                pair_id=f"{test_id}/SPEC",
                invariant_category=harness.SPEC_VALIDATION,
                violations=exc.violations,
                evidence_dir=evidence_dir,
                contract_rev=harness.CONTRACT_REV,
                spec_path=str(spec_path),
            )
        raise


def load_spec(spec_path: Path, evidence_dir: Path | None = None) -> dict:
    """Verify exact bytes, parse, validate, and return one frozen test spec."""
    return load_spec_with_digest(spec_path, evidence_dir=evidence_dir)[0]
