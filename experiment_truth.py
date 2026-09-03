"""Offline validation for frozen truth, rubric, and scored-input bindings."""

from __future__ import annotations

import math
import re
from pathlib import Path

import artifact_lock
import experiment_config
import experiment_spec
import harness

TRUTH_VERSION = 1
RUBRIC_VERSION = 1
VERDICTS = (
    "CORRECT",
    "PARTIAL",
    "INCORRECT",
    "UNSUPPORTED",
    "NOT_ANSWERED",
)

TRUTH_KEYS = {
    "truth_version",
    "test_id",
    "test_class",
    "contract_rev",
    "contract_sha256",
    "spec_sha256",
    "rubric_sha256",
    "items",
}
TRUTH_ITEM_KEYS = {
    "question_id",
    "category",
    "expects_absence",
    "evidence_spans",
    "authoring_note",
}
COMPONENT_KEYS = {"component_id", "description", "essential", "match"}
RUBRIC_KEYS = {
    "rubric_version",
    "contract_rev",
    "contract_sha256",
    "verdicts",
    "escalation_state",
    "timestamp_tolerance_s",
    "timestamp_reference",
    "timestamp_answer_format",
    "evidence_span_required",
    "verdict_rules",
    "escalation_rule",
}


class TruthValidationError(ValueError):
    """A truth artifact or one of its exact-byte bindings is invalid."""

    def __init__(self, violations: list[str]):
        super().__init__("; ".join(violations))
        self.violations = violations


class RubricValidationError(ValueError):
    """A rubric artifact or its exact-byte hash lock is invalid."""

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


def _is_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _is_nonempty_string(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_evidence_spans(
    spans, path: str, duration: int, violations: list[str]
) -> None:
    if not isinstance(spans, list) or not spans:
        violations.append(f"{path}: expected a non-empty list")
        return
    for index, span in enumerate(spans):
        span_path = f"{path}[{index}]"
        if not isinstance(span, list) or len(span) != 2:
            violations.append(f"{span_path}: expected [start_s, end_s]")
            continue
        start, end = span
        start_valid = _is_number(start)
        end_valid = _is_number(end)
        if not start_valid:
            violations.append(f"{span_path}[0]: expected a finite JSON number")
        if not end_valid:
            violations.append(f"{span_path}[1]: expected a finite JSON number")
        if not (start_valid and end_valid):
            continue
        if start < 0:
            violations.append(f"{span_path}[0]: must be >= 0")
        if end < 0:
            violations.append(f"{span_path}[1]: must be >= 0")
        if start > end:
            violations.append(f"{span_path}: start_s must be <= end_s")
        if start > duration or end > duration:
            violations.append(f"{span_path}: must be within video duration {duration}")


def _validate_components(components, path: str, violations: list[str]) -> None:
    if not isinstance(components, list) or not components:
        violations.append(f"{path}: expected a non-empty list")
        return
    component_ids = []
    essential_count = 0
    for index, component in enumerate(components):
        item_path = f"{path}[{index}]"
        match_mode = component.get("match") if isinstance(component, dict) else None
        keys = COMPONENT_KEYS | ({"accepted_forms"} if match_mode == "exact" else set())
        if not _exact_mapping(component, item_path, keys, violations):
            continue

        component_id = component.get("component_id")
        if (
            not isinstance(component_id, str)
            or re.fullmatch(r"C[0-9]+", component_id) is None
        ):
            violations.append(f"{item_path}.component_id: expected ^C[0-9]+$")
        else:
            component_ids.append(component_id)
        if not _is_nonempty_string(component.get("description")):
            violations.append(f"{item_path}.description: expected a non-empty string")

        essential = component.get("essential")
        if not isinstance(essential, bool):
            violations.append(f"{item_path}.essential: expected a boolean")
        elif essential:
            essential_count += 1

        if match_mode not in ("semantic", "exact"):
            violations.append(f"{item_path}.match: expected 'semantic' or 'exact'")
        if match_mode == "exact":
            forms = component.get("accepted_forms")
            if not isinstance(forms, list) or not forms:
                violations.append(
                    f"{item_path}.accepted_forms: expected a non-empty list"
                )
            else:
                for form_index, form in enumerate(forms):
                    if not _is_nonempty_string(form):
                        violations.append(
                            f"{item_path}.accepted_forms[{form_index}]: "
                            "expected a non-empty string"
                        )
                unique_strings = {
                    form for form in forms if isinstance(form, str)
                }
                if len(unique_strings) != len(forms):
                    violations.append(f"{item_path}.accepted_forms: duplicate")

    if len(set(component_ids)) != len(component_ids):
        violations.append(f"{path}.component_id: duplicate")
    if essential_count == 0:
        violations.append(f"{path}: expected at least one essential component")


def _validate_truth_item(
    item,
    index: int,
    spec_item: dict,
    duration: int,
    violations: list[str],
) -> str | None:
    path = f"items[{index}]"
    category = item.get("category") if isinstance(item, dict) else None
    expects_absence = item.get("expects_absence") if isinstance(item, dict) else None
    keys = set(TRUTH_ITEM_KEYS)
    if expects_absence is True:
        keys.add("absent_claim")
    else:
        keys.add("required_components")
        if category == "localized":
            keys.add("reference_timestamp_s")
    if not _exact_mapping(item, path, keys, violations):
        return None

    for field in ("question_id", "category", "expects_absence"):
        if item.get(field) != spec_item[field]:
            violations.append(f"{path}.{field}: does not match bound spec")
    if item.get("category") not in ("global", "localized"):
        violations.append(f"{path}.category: expected 'global' or 'localized'")
    if not isinstance(expects_absence, bool):
        violations.append(f"{path}.expects_absence: expected a boolean")
    if not _is_nonempty_string(item.get("authoring_note")):
        violations.append(f"{path}.authoring_note: expected a non-empty string")
    _validate_evidence_spans(
        item.get("evidence_spans"),
        f"{path}.evidence_spans",
        duration,
        violations,
    )

    if expects_absence is True:
        if not _is_nonempty_string(item.get("absent_claim")):
            violations.append(f"{path}.absent_claim: expected a non-empty string")
        return category if category in ("global", "localized") else None

    _validate_components(
        item.get("required_components"),
        f"{path}.required_components",
        violations,
    )
    if category == "localized":
        timestamp = item.get("reference_timestamp_s")
        if not _is_number(timestamp):
            violations.append(
                f"{path}.reference_timestamp_s: expected a finite JSON number"
            )
        elif timestamp < 0 or timestamp > duration:
            violations.append(
                f"{path}.reference_timestamp_s: expected 0..{duration}"
            )
    return None


def validate_truth(
    truth,
    *,
    filename_stem: str,
    spec: dict,
    spec_sha256: str,
    rubric_sha256: str,
    contract_sha256: str,
) -> None:
    """Validate truth structure and every contract/spec/rubric binding."""
    violations: list[str] = []
    if not _exact_mapping(truth, "truth", TRUTH_KEYS, violations):
        raise TruthValidationError(violations)

    if (
        not _is_int(truth.get("truth_version"))
        or truth.get("truth_version") != TRUTH_VERSION
    ):
        violations.append(f"truth_version: expected integer {TRUTH_VERSION}")

    test_id = truth.get("test_id")
    if not isinstance(test_id, str) or test_id not in experiment_config.ALLOWED_REPEATS:
        violations.append(f"test_id: unknown test {test_id!r}")
    if isinstance(test_id, str) and filename_stem != test_id:
        violations.append(
            "truth filename/test_id mismatch: "
            f"{filename_stem + '.json'!r} != {test_id + '.json'!r}"
        )
    if test_id != spec["test_id"]:
        violations.append("test_id: does not match bound spec")

    expected_class = "STRESS" if test_id == "T004" else "BENCHMARK"
    if truth.get("test_class") != expected_class:
        violations.append(
            f"test_class: expected {expected_class!r}, got {truth.get('test_class')!r}"
        )
    if truth.get("test_class") != spec["test_class"]:
        violations.append("test_class: does not match bound spec")
    if truth.get("contract_rev") != harness.CONTRACT_REV:
        violations.append(f"contract_rev: expected {harness.CONTRACT_REV!r}")
    if truth.get("contract_sha256") != contract_sha256:
        violations.append(
            "contract_sha256: does not match the verified frozen contract"
        )
    if truth.get("spec_sha256") != spec_sha256:
        violations.append("spec_sha256: does not match exact verified spec bytes")
    if truth.get("rubric_sha256") != rubric_sha256:
        violations.append("rubric_sha256: does not match exact verified rubric bytes")

    items = truth.get("items")
    if not isinstance(items, list):
        violations.append("items: expected a list")
    else:
        if len(items) != len(experiment_spec.QUESTION_IDS):
            violations.append(f"items: expected 12 items, got {len(items)}")
        ids = []
        absence_categories = []
        for index, item in enumerate(items):
            if isinstance(item, dict) and isinstance(item.get("question_id"), str):
                ids.append(item["question_id"])
            if index < len(spec["questions"]):
                absence_category = _validate_truth_item(
                    item,
                    index,
                    spec["questions"][index],
                    spec["video"]["video_duration_s"],
                    violations,
                )
                if absence_category is not None:
                    absence_categories.append(absence_category)
        if len(set(ids)) != len(ids):
            violations.append("items.question_id: duplicate")
        if tuple(ids) != experiment_spec.QUESTION_IDS:
            violations.append(
                "items.question_id: expected Q001..Q012 in order without gaps"
            )
        if len(absence_categories) != 2:
            violations.append(
                "items.expects_absence: expected 2 true values, "
                f"got {len(absence_categories)}"
            )
        elif sorted(absence_categories) != ["global", "localized"]:
            violations.append(
                "items.expects_absence: expected one global and one localized probe"
            )

    if violations:
        raise TruthValidationError(violations)


def validate_rubric(rubric, *, contract_sha256: str) -> None:
    """Validate the suite-wide rubric structure and frozen contract binding."""
    violations: list[str] = []
    if not _exact_mapping(rubric, "rubric", RUBRIC_KEYS, violations):
        raise RubricValidationError(violations)

    if (
        not _is_int(rubric.get("rubric_version"))
        or rubric.get("rubric_version") != RUBRIC_VERSION
    ):
        violations.append(f"rubric_version: expected integer {RUBRIC_VERSION}")
    if rubric.get("contract_rev") != harness.CONTRACT_REV:
        violations.append(f"contract_rev: expected {harness.CONTRACT_REV!r}")
    if rubric.get("contract_sha256") != contract_sha256:
        violations.append(
            "contract_sha256: does not match the verified frozen contract"
        )
    if rubric.get("verdicts") != list(VERDICTS):
        violations.append(f"verdicts: expected {list(VERDICTS)!r} in order")
    if rubric.get("escalation_state") != "NEEDS_HUMAN_REVIEW":
        violations.append("escalation_state: expected 'NEEDS_HUMAN_REVIEW'")

    tolerance = rubric.get("timestamp_tolerance_s")
    if not _is_number(tolerance) or tolerance != 2.0:
        violations.append("timestamp_tolerance_s: expected numeric value 2.0")
    if rubric.get("timestamp_reference") != "player_time_from_zero":
        violations.append("timestamp_reference: expected 'player_time_from_zero'")
    if rubric.get("timestamp_answer_format") != "HH:MM:SS":
        violations.append("timestamp_answer_format: expected 'HH:MM:SS'")

    evidence_rules = rubric.get("evidence_span_required")
    if _exact_mapping(
        evidence_rules,
        "evidence_span_required",
        set(VERDICTS),
        violations,
    ):
        expected = {verdict: verdict != "NOT_ANSWERED" for verdict in VERDICTS}
        for verdict, required in expected.items():
            value = evidence_rules.get(verdict)
            if not isinstance(value, bool):
                violations.append(
                    f"evidence_span_required.{verdict}: expected a boolean"
                )
            elif value is not required:
                violations.append(
                    f"evidence_span_required.{verdict}: expected {required}"
                )

    verdict_rules = rubric.get("verdict_rules")
    if _exact_mapping(verdict_rules, "verdict_rules", set(VERDICTS), violations):
        for verdict in VERDICTS:
            if not _is_nonempty_string(verdict_rules.get(verdict)):
                violations.append(
                    f"verdict_rules.{verdict}: expected a non-empty string"
                )
    if not _is_nonempty_string(rubric.get("escalation_rule")):
        violations.append("escalation_rule: expected a non-empty string")

    if violations:
        raise RubricValidationError(violations)


def _verify_contract(*, evidence_dir: Path | None, pair_id: str) -> str:
    try:
        return harness.verify_contract()
    except harness.ContractIntegrityError as exc:
        if evidence_dir is not None:
            harness.record_preflight_failure(
                pair_id=pair_id,
                invariant_category=harness.CONTRACT_INTEGRITY,
                violations=[f"CONTRACT.md integrity: {exc}"],
                evidence_dir=evidence_dir,
                contract_rev=harness.CONTRACT_REV,
            )
        raise


def _load_rubric(
    rubric_path: Path,
    *,
    contract_sha256: str,
    evidence_dir: Path | None = None,
) -> tuple[dict, str]:
    rubric_path = Path(rubric_path)
    try:
        rubric, digest = artifact_lock.load_hash_locked_json(
            rubric_path,
            artifact_label="rubric",
            lock_label="rubric_sha256",
            error_type=RubricValidationError,
            canonical_lock=True,
        )
        validate_rubric(rubric, contract_sha256=contract_sha256)
        return rubric, digest
    except RubricValidationError as exc:
        if evidence_dir is not None:
            harness.record_preflight_failure(
                pair_id="RUBRIC",
                invariant_category=harness.RUBRIC_VALIDATION,
                violations=exc.violations,
                evidence_dir=evidence_dir,
                contract_rev=harness.CONTRACT_REV,
                rubric_path=str(rubric_path),
            )
        raise


def load_rubric(
    rubric_path: Path, *, evidence_dir: Path | None = None
) -> dict:
    """Verify exact rubric bytes, parse, validate, and return the rubric."""
    contract_digest = _verify_contract(evidence_dir=evidence_dir, pair_id="RUBRIC")
    return _load_rubric(
        rubric_path,
        contract_sha256=contract_digest,
        evidence_dir=evidence_dir,
    )[0]


def _load_truth(
    truth_path: Path,
    *,
    spec: dict,
    spec_sha256: str,
    rubric_sha256: str,
    contract_sha256: str,
    evidence_dir: Path | None = None,
) -> tuple[dict, str]:
    truth_path = Path(truth_path)
    test_id = truth_path.stem
    try:
        truth, digest = artifact_lock.load_hash_locked_json(
            truth_path,
            artifact_label="truth",
            lock_label="truth_sha256",
            error_type=TruthValidationError,
            canonical_lock=True,
        )
        if isinstance(truth, dict) and isinstance(truth.get("test_id"), str):
            test_id = truth["test_id"]
        validate_truth(
            truth,
            filename_stem=truth_path.stem,
            spec=spec,
            spec_sha256=spec_sha256,
            rubric_sha256=rubric_sha256,
            contract_sha256=contract_sha256,
        )
        return truth, digest
    except TruthValidationError as exc:
        if evidence_dir is not None:
            harness.record_preflight_failure(
                pair_id=f"{test_id}/TRUTH",
                invariant_category=harness.TRUTH_VALIDATION,
                violations=exc.violations,
                evidence_dir=evidence_dir,
                contract_rev=harness.CONTRACT_REV,
                truth_path=str(truth_path),
            )
        raise


def load_truth(
    truth_path: Path,
    *,
    spec: dict,
    spec_path: Path,
    rubric: dict,
    rubric_path: Path,
    evidence_dir: Path | None = None,
) -> dict:
    """Verify dependencies and return one bound, hash-locked truth artifact."""
    contract_digest = _verify_contract(
        evidence_dir=evidence_dir,
        pair_id=f"{Path(truth_path).stem}/TRUTH",
    )
    verified_spec, spec_digest = experiment_spec.load_spec_with_digest(
        spec_path, evidence_dir=evidence_dir
    )
    verified_rubric, rubric_digest = _load_rubric(
        rubric_path,
        contract_sha256=contract_digest,
        evidence_dir=evidence_dir,
    )
    dependency_violations = []
    if spec != verified_spec:
        dependency_violations.append(
            "spec: supplied data differs from verified spec file"
        )
    if rubric != verified_rubric:
        dependency_violations.append(
            "rubric: supplied data differs from verified rubric file"
        )
    if dependency_violations:
        error = TruthValidationError(dependency_violations)
        if evidence_dir is not None:
            harness.record_preflight_failure(
                pair_id=f"{Path(truth_path).stem}/TRUTH",
                invariant_category=harness.TRUTH_VALIDATION,
                violations=error.violations,
                evidence_dir=evidence_dir,
                contract_rev=harness.CONTRACT_REV,
                truth_path=str(truth_path),
            )
        raise error
    return _load_truth(
        truth_path,
        spec=verified_spec,
        spec_sha256=spec_digest,
        rubric_sha256=rubric_digest,
        contract_sha256=contract_digest,
        evidence_dir=evidence_dir,
    )[0]


def verify_scored_inputs(
    *,
    spec_path: Path,
    truth_path: Path,
    rubric_path: Path,
    evidence_dir: Path | None = None,
) -> dict:
    """Offline preflight gate for the four exact artifacts a scored run needs."""
    contract_digest = _verify_contract(
        evidence_dir=evidence_dir, pair_id="SCORED_INPUTS"
    )
    spec, spec_digest = experiment_spec.load_spec_with_digest(
        spec_path, evidence_dir=evidence_dir
    )
    rubric, rubric_digest = _load_rubric(
        rubric_path,
        evidence_dir=evidence_dir,
        contract_sha256=contract_digest,
    )
    truth, truth_digest = _load_truth(
        truth_path,
        spec=spec,
        spec_sha256=spec_digest,
        rubric_sha256=rubric_digest,
        contract_sha256=contract_digest,
        evidence_dir=evidence_dir,
    )
    return {
        "contract_sha256": contract_digest,
        "spec_sha256": spec_digest,
        "truth_sha256": truth_digest,
        "rubric_sha256": rubric_digest,
        "spec": spec,
        "truth": truth,
        "rubric": rubric,
    }
