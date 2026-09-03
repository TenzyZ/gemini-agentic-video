"""Deterministic offline tests for truth/rubric freeze validation."""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

import experiment_spec
import experiment_truth
import harness
from test_experiment_spec import make_spec, write_spec

CONTRACT_DIGEST = harness.verify_contract()


def write_locked(directory, name, value=None, *, raw=None, write_hash=True):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    if raw is None:
        raw = (json.dumps(value, indent=2) + "\n").encode("utf-8")
    path.write_bytes(raw)
    if write_hash:
        digest = hashlib.sha256(raw).hexdigest()
        path.with_suffix(".sha256").write_bytes(
            f"{digest}  {path.name}\n".encode("utf-8")
        )
    return path


def rewrite_locked(path, value=None, *, raw=None):
    path = Path(path)
    if raw is None:
        raw = (json.dumps(value, indent=2) + "\n").encode("utf-8")
    path.write_bytes(raw)
    path.with_suffix(".sha256").write_bytes(
        f"{hashlib.sha256(raw).hexdigest()}  {path.name}\n".encode("utf-8")
    )


def make_rubric(tolerance=2.0):
    verdicts = list(experiment_truth.VERDICTS)
    return {
        "rubric_version": 1,
        "contract_rev": harness.CONTRACT_REV,
        "contract_sha256": CONTRACT_DIGEST,
        "verdicts": verdicts,
        "escalation_state": "NEEDS_HUMAN_REVIEW",
        "timestamp_tolerance_s": tolerance,
        "timestamp_reference": "player_time_from_zero",
        "timestamp_answer_format": "HH:MM:SS",
        "evidence_span_required": {
            verdict: verdict != "NOT_ANSWERED" for verdict in verdicts
        },
        "verdict_rules": {
            verdict: f"Synthetic structural rule for {verdict}." for verdict in verdicts
        },
        "escalation_rule": "Synthetic structural escalation rule.",
    }


def make_truth(spec, *, spec_sha256, rubric_sha256):
    items = []
    for index, question in enumerate(spec["questions"]):
        item = {
            "question_id": question["question_id"],
            "category": question["category"],
            "expects_absence": question["expects_absence"],
            "evidence_spans": [[index * 10, index * 10 + 2]],
            "authoring_note": "  Synthetic fixture note; preserve spaces.  ",
        }
        if question["expects_absence"]:
            item["absent_claim"] = "Synthetic absent-event claim."
        else:
            item["required_components"] = [
                {
                    "component_id": "C1",
                    "description": "Synthetic required component.",
                    "essential": True,
                    "match": "semantic",
                }
            ]
            if question["category"] == "localized":
                item["reference_timestamp_s"] = index * 10 + 1
        items.append(item)
    return {
        "truth_version": 1,
        "test_id": spec["test_id"],
        "test_class": spec["test_class"],
        "contract_rev": harness.CONTRACT_REV,
        "contract_sha256": CONTRACT_DIGEST,
        "spec_sha256": spec_sha256,
        "rubric_sha256": rubric_sha256,
        "items": items,
    }


def make_bundle(root, test_id="T001"):
    root = Path(root)
    spec_path = write_spec(root / "specs", make_spec(test_id))
    spec, spec_digest = experiment_spec.load_spec_with_digest(spec_path)
    rubric_path = write_locked(root / "truth", "rubric.json", make_rubric())
    rubric = experiment_truth.load_rubric(rubric_path)
    rubric_digest = hashlib.sha256(rubric_path.read_bytes()).hexdigest()
    truth = make_truth(
        spec, spec_sha256=spec_digest, rubric_sha256=rubric_digest
    )
    truth_path = write_locked(root / "truth", f"{test_id}.json", truth)
    return {
        "spec_path": spec_path,
        "spec": spec,
        "rubric_path": rubric_path,
        "rubric": rubric,
        "truth_path": truth_path,
        "truth": truth,
    }


def load_bundle_truth(bundle, *, evidence_dir=None, truth_path=None):
    return experiment_truth.load_truth(
        truth_path or bundle["truth_path"],
        spec=bundle["spec"],
        spec_path=bundle["spec_path"],
        rubric=bundle["rubric"],
        rubric_path=bundle["rubric_path"],
        evidence_dir=evidence_dir,
    )


class TruthTestCase(unittest.TestCase):
    def assert_truth_invalid(self, bundle, truth, expected):
        rewrite_locked(bundle["truth_path"], truth)
        with self.assertRaises(experiment_truth.TruthValidationError) as ctx:
            load_bundle_truth(bundle)
        self.assertIn(expected, " ".join(ctx.exception.violations))

    def assert_rubric_invalid(self, bundle, rubric, expected):
        rewrite_locked(bundle["rubric_path"], rubric)
        with self.assertRaises(experiment_truth.RubricValidationError) as ctx:
            experiment_truth.load_rubric(bundle["rubric_path"])
        self.assertIn(expected, " ".join(ctx.exception.violations))


class TestValidArtifacts(TruthTestCase):
    def test_valid_rubric_accepts_numeric_two_and_two_point_zero(self):
        for tolerance in (2, 2.0):
            with self.subTest(tolerance=tolerance), tempfile.TemporaryDirectory() as tmp:
                path = write_locked(tmp, "rubric.json", make_rubric(tolerance))
                loaded = experiment_truth.load_rubric(path)
                self.assertEqual(loaded["timestamp_tolerance_s"], tolerance)

    def test_valid_t001_truth_loads_and_preserves_authored_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(tmp)
            loaded = load_bundle_truth(bundle)
        self.assertEqual(loaded["test_id"], "T001")
        self.assertEqual(
            loaded["items"][0]["authoring_note"],
            "  Synthetic fixture note; preserve spaces.  ",
        )

    def test_valid_t004_truth_loads_as_stress(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(tmp, "T004")
            loaded = load_bundle_truth(bundle)
        self.assertEqual(loaded["test_class"], "STRESS")

    def test_verify_scored_inputs_returns_exact_digests_and_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(tmp)
            verified = experiment_truth.verify_scored_inputs(
                spec_path=bundle["spec_path"],
                truth_path=bundle["truth_path"],
                rubric_path=bundle["rubric_path"],
            )
            self.assertEqual(verified["contract_sha256"], CONTRACT_DIGEST)
            for name in ("spec", "truth", "rubric"):
                path = bundle[f"{name}_path"]
                self.assertEqual(
                    verified[f"{name}_sha256"],
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
                self.assertEqual(verified[name], bundle[name])

    def test_exact_lf_fixture_bytes_are_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(tmp)
            before = {
                key: bundle[key].read_bytes()
                for key in ("spec_path", "truth_path", "rubric_path")
            }
            experiment_truth.verify_scored_inputs(
                spec_path=bundle["spec_path"],
                truth_path=bundle["truth_path"],
                rubric_path=bundle["rubric_path"],
            )
            for key, raw in before.items():
                self.assertNotIn(b"\r\n", raw)
                self.assertEqual(bundle[key].read_bytes(), raw)


class TestHashLockRejection(TruthTestCase):
    def _invoke(self, kind, bundle):
        if kind == "truth":
            return load_bundle_truth(bundle)
        return experiment_truth.load_rubric(bundle["rubric_path"])

    def test_truth_and_rubric_hash_lock_failures_are_exact_and_non_mutating(self):
        cases = (
            "mutation",
            "crlf_mutation",
            "missing",
            "malformed",
            "filename",
            "digest",
            "uppercase",
            "lock_crlf",
            "lock_utf8",
        )
        for kind in ("truth", "rubric"):
            for case in cases:
                with self.subTest(kind=kind, case=case), tempfile.TemporaryDirectory() as tmp:
                    bundle = make_bundle(tmp)
                    path = bundle[f"{kind}_path"]
                    lock = path.with_suffix(".sha256")
                    if case == "mutation":
                        path.write_bytes(path.read_bytes() + b" ")
                    elif case == "crlf_mutation":
                        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
                    elif case == "missing":
                        lock.unlink()
                    elif case == "malformed":
                        lock.write_bytes(b"not-a-lock\n")
                    elif case == "filename":
                        digest = hashlib.sha256(path.read_bytes()).hexdigest()
                        lock.write_bytes(f"{digest}  wrong.json\n".encode())
                    elif case == "digest":
                        lock.write_bytes(f"{'0' * 64}  {path.name}\n".encode())
                    elif case == "uppercase":
                        digest = hashlib.sha256(path.read_bytes()).hexdigest().upper()
                        lock.write_bytes(f"{digest}  {path.name}\n".encode())
                    elif case == "lock_crlf":
                        digest = hashlib.sha256(path.read_bytes()).hexdigest()
                        lock.write_bytes(f"{digest}  {path.name}\r\n".encode())
                    else:
                        lock.write_bytes(b"\xff")
                    artifact_before = path.read_bytes()
                    lock_before = lock.read_bytes() if lock.exists() else None
                    error = (
                        experiment_truth.TruthValidationError
                        if kind == "truth"
                        else experiment_truth.RubricValidationError
                    )
                    with self.assertRaises(error):
                        self._invoke(kind, bundle)
                    self.assertEqual(path.read_bytes(), artifact_before)
                    self.assertEqual(
                        lock.read_bytes() if lock.exists() else None, lock_before
                    )

    def test_truth_and_rubric_reject_invalid_utf8_and_duplicate_keys(self):
        for kind in ("truth", "rubric"):
            for case, raw, expected in (
                ("json_utf8", b"\xff", "invalid UTF-8 JSON"),
                ("invalid_json", b"{\n", "invalid UTF-8 JSON"),
                ("duplicate", b'{"x": 1, "x": 2}\n', "duplicate key"),
            ):
                with self.subTest(kind=kind, case=case), tempfile.TemporaryDirectory() as tmp:
                    bundle = make_bundle(tmp)
                    path = bundle[f"{kind}_path"]
                    rewrite_locked(path, raw=raw)
                    before = (path.read_bytes(), path.with_suffix(".sha256").read_bytes())
                    error = (
                        experiment_truth.TruthValidationError
                        if kind == "truth"
                        else experiment_truth.RubricValidationError
                    )
                    with self.assertRaises(error) as ctx:
                        self._invoke(kind, bundle)
                    self.assertIn(expected, str(ctx.exception))
                    self.assertEqual(
                        before,
                        (path.read_bytes(), path.with_suffix(".sha256").read_bytes()),
                    )

    def test_missing_truth_and_rubric_artifacts_fail_without_creating_files(self):
        for kind in ("truth", "rubric"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                bundle = make_bundle(tmp)
                path = bundle[f"{kind}_path"]
                path.unlink()
                error = (
                    experiment_truth.TruthValidationError
                    if kind == "truth"
                    else experiment_truth.RubricValidationError
                )
                with self.assertRaises(error):
                    self._invoke(kind, bundle)
                self.assertFalse(path.exists())


class TestTruthBindings(TruthTestCase):
    def test_identity_and_hash_bindings_reject_wrong_values(self):
        cases = (
            ("version_bool", lambda truth: truth.__setitem__("truth_version", True), "truth_version"),
            ("version", lambda truth: truth.__setitem__("truth_version", 2), "truth_version"),
            ("unknown", lambda truth: truth.__setitem__("test_id", "T999"), "unknown test"),
            ("class", lambda truth: truth.__setitem__("test_class", "STRESS"), "test_class"),
            ("revision", lambda truth: truth.__setitem__("contract_rev", "REV 2"), "contract_rev"),
            (
                "contract",
                lambda truth: truth.__setitem__("contract_sha256", "0" * 64),
                "contract_sha256",
            ),
            ("spec", lambda truth: truth.__setitem__("spec_sha256", "0" * 64), "spec_sha256"),
            ("rubric", lambda truth: truth.__setitem__("rubric_sha256", "0" * 64), "rubric_sha256"),
        )
        for name, mutate, expected in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                bundle = make_bundle(tmp)
                truth = deepcopy(bundle["truth"])
                mutate(truth)
                self.assert_truth_invalid(bundle, truth, expected)

    def test_truth_filename_must_match_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(tmp)
            wrong_path = write_locked(Path(tmp) / "other", "foo.json", bundle["truth"])
            with self.assertRaises(experiment_truth.TruthValidationError) as ctx:
                load_bundle_truth(bundle, truth_path=wrong_path)
            self.assertIn("filename/test_id mismatch", str(ctx.exception))

    def test_truth_top_level_shape_is_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(tmp)
            truth = deepcopy(bundle["truth"])
            truth["unexpected"] = None
            self.assert_truth_invalid(bundle, truth, "truth.unexpected: unexpected")

    def test_legitimately_changed_spec_invalidates_old_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(tmp)
            changed = deepcopy(bundle["spec"])
            changed["prompt"]["text"] += "\nSynthetic fixture change."
            changed["prompt"]["sha256"] = hashlib.sha256(
                changed["prompt"]["text"].encode()
            ).hexdigest()
            raw = json.dumps(changed, indent=2).encode()
            bundle["spec_path"].write_bytes(raw)
            bundle["spec_path"].with_suffix(".sha256").write_text(
                f"{hashlib.sha256(raw).hexdigest()}  {bundle['spec_path'].name}\n",
                encoding="utf-8",
                newline="",
            )
            with self.assertRaises(experiment_truth.TruthValidationError) as ctx:
                experiment_truth.verify_scored_inputs(
                    spec_path=bundle["spec_path"],
                    truth_path=bundle["truth_path"],
                    rubric_path=bundle["rubric_path"],
                )
            self.assertIn("spec_sha256", str(ctx.exception))

    def test_legitimately_changed_rubric_invalidates_old_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(tmp)
            changed = deepcopy(bundle["rubric"])
            changed["verdict_rules"]["CORRECT"] += " Synthetic change."
            rewrite_locked(bundle["rubric_path"], changed)
            with self.assertRaises(experiment_truth.TruthValidationError) as ctx:
                experiment_truth.verify_scored_inputs(
                    spec_path=bundle["spec_path"],
                    truth_path=bundle["truth_path"],
                    rubric_path=bundle["rubric_path"],
                )
            self.assertIn("rubric_sha256", str(ctx.exception))


class TestTruthQuestions(TruthTestCase):
    def test_item_count_ids_order_and_spec_agreement(self):
        def duplicate(truth):
            truth["items"][-1]["question_id"] = "Q011"

        def gap(truth):
            truth["items"][-1]["question_id"] = "Q013"

        def reorder(truth):
            truth["items"][1], truth["items"][2] = truth["items"][2], truth["items"][1]

        cases = (
            ("eleven", lambda truth: truth["items"].pop(), "expected 12 items, got 11"),
            ("thirteen", lambda truth: truth["items"].append(deepcopy(truth["items"][-1])), "expected 12 items, got 13"),
            ("duplicate", duplicate, "question_id: duplicate"),
            ("gap", gap, "expected Q001..Q012"),
            ("reorder", reorder, "expected Q001..Q012"),
            ("category", lambda truth: truth["items"][1].__setitem__("category", "localized"), "category: does not match bound spec"),
            ("absence", lambda truth: truth["items"][1].__setitem__("expects_absence", True), "expects_absence: does not match bound spec"),
        )
        for name, mutate, expected in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                bundle = make_bundle(tmp)
                truth = deepcopy(bundle["truth"])
                mutate(truth)
                self.assert_truth_invalid(bundle, truth, expected)

    def test_absence_probe_count_and_category_are_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(tmp)
            truth = deepcopy(bundle["truth"])
            item = truth["items"][6]
            item["expects_absence"] = False
            item.pop("absent_claim")
            item["required_components"] = [{
                "component_id": "C1",
                "description": "Synthetic.",
                "essential": True,
                "match": "semantic",
            }]
            item["reference_timestamp_s"] = 61
            self.assert_truth_invalid(bundle, truth, "expected 2 true values, got 1")
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(tmp)
            truth = deepcopy(bundle["truth"])
            truth["items"][6]["category"] = "global"
            self.assert_truth_invalid(
                bundle, truth, "expected one global and one localized probe"
            )


class TestTruthProvenance(TruthTestCase):
    def test_invalid_evidence_spans_and_authoring_notes_are_rejected(self):
        cases = (
            ("empty", [], "non-empty list"),
            ("shape", [[0, 1, 2]], "expected [start_s, end_s]"),
            ("bool", [[False, 1]], "finite JSON number"),
            ("text", [["0", 1]], "finite JSON number"),
            ("negative", [[-1, 1]], "must be >= 0"),
            ("reversed", [[2, 1]], "start_s must be <= end_s"),
            ("duration", [[0, 3601]], "within video duration"),
            ("nan", [[math.nan, 1]], "finite JSON number"),
            ("infinity", [[0, math.inf]], "finite JSON number"),
            ("negative_infinity", [[-math.inf, 1]], "finite JSON number"),
        )
        for name, spans, expected in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                bundle = make_bundle(tmp)
                truth = deepcopy(bundle["truth"])
                truth["items"][1]["evidence_spans"] = spans
                self.assert_truth_invalid(bundle, truth, expected)
        for note in ("", "  \t\n"):
            with self.subTest(note=repr(note)), tempfile.TemporaryDirectory() as tmp:
                bundle = make_bundle(tmp)
                truth = deepcopy(bundle["truth"])
                truth["items"][1]["authoring_note"] = note
                self.assert_truth_invalid(bundle, truth, "authoring_note")


class TestTruthComponents(TruthTestCase):
    def test_component_schema_is_enforced(self):
        def component(truth):
            return truth["items"][1]["required_components"][0]

        def missing(truth):
            truth["items"][1].pop("required_components")

        def duplicate_id(truth):
            truth["items"][1]["required_components"].append(deepcopy(component(truth)))

        def exact_missing(truth):
            component(truth)["match"] = "exact"

        def exact_empty(truth):
            component(truth)["match"] = "exact"
            component(truth)["accepted_forms"] = []

        def exact_duplicate(truth):
            component(truth)["match"] = "exact"
            component(truth)["accepted_forms"] = ["same", "same"]

        def semantic_forms(truth):
            component(truth)["accepted_forms"] = ["unexpected"]

        def exact_blank(truth):
            component(truth)["match"] = "exact"
            component(truth)["accepted_forms"] = ["  "]

        cases = (
            ("missing", missing, "required_components: missing"),
            (
                "empty",
                lambda truth: truth["items"][1].__setitem__(
                    "required_components", []
                ),
                "non-empty list",
            ),
            (
                "essential",
                lambda truth: component(truth).__setitem__("essential", False),
                "at least one essential",
            ),
            ("duplicate", duplicate_id, "component_id: duplicate"),
            ("id", lambda truth: component(truth).__setitem__("component_id", "component-1"), "^C[0-9]+$"),
            ("description", lambda truth: component(truth).__setitem__("description", "  "), "description"),
            ("bool", lambda truth: component(truth).__setitem__("essential", 1), "essential: expected a boolean"),
            ("match", lambda truth: component(truth).__setitem__("match", "substring"), "match: expected"),
            ("exact_missing", exact_missing, "accepted_forms: missing"),
            ("exact_empty", exact_empty, "accepted_forms: expected a non-empty list"),
            ("exact_duplicate", exact_duplicate, "accepted_forms: duplicate"),
            ("exact_blank", exact_blank, "expected a non-empty string"),
            ("semantic_forms", semantic_forms, "accepted_forms: unexpected"),
            ("extra", lambda truth: component(truth).__setitem__("other", None), "other: unexpected"),
        )
        for name, mutate, expected in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                bundle = make_bundle(tmp)
                truth = deepcopy(bundle["truth"])
                mutate(truth)
                self.assert_truth_invalid(bundle, truth, expected)


class TestTruthTimestampsAndAbsence(TruthTestCase):
    def test_timestamp_shape_and_bounds_are_enforced(self):
        def global_timestamp(truth):
            truth["items"][1]["reference_timestamp_s"] = 10

        def localized_missing(truth):
            truth["items"][7].pop("reference_timestamp_s")

        cases = (
            ("global", global_timestamp, "reference_timestamp_s: unexpected"),
            ("missing", localized_missing, "reference_timestamp_s: missing"),
            ("list", lambda truth: truth["items"][7].__setitem__("reference_timestamp_s", [71]), "finite JSON number"),
            ("string", lambda truth: truth["items"][7].__setitem__("reference_timestamp_s", "00:01:11"), "finite JSON number"),
            ("negative", lambda truth: truth["items"][7].__setitem__("reference_timestamp_s", -1), "expected 0..3600"),
            ("duration", lambda truth: truth["items"][7].__setitem__("reference_timestamp_s", 3601), "expected 0..3600"),
            ("bool", lambda truth: truth["items"][7].__setitem__("reference_timestamp_s", True), "finite JSON number"),
            ("nan", lambda truth: truth["items"][7].__setitem__("reference_timestamp_s", math.nan), "finite JSON number"),
            ("infinity", lambda truth: truth["items"][7].__setitem__("reference_timestamp_s", math.inf), "finite JSON number"),
            ("negative_infinity", lambda truth: truth["items"][7].__setitem__("reference_timestamp_s", -math.inf), "finite JSON number"),
        )
        for name, mutate, expected in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                bundle = make_bundle(tmp)
                truth = deepcopy(bundle["truth"])
                mutate(truth)
                self.assert_truth_invalid(bundle, truth, expected)

    def test_absence_items_require_claim_and_forbid_positive_answer_fields(self):
        for item_index in (0, 6):
            for field, value in (
                ("reference_timestamp_s", 1),
                ("required_components", []),
            ):
                with (
                    self.subTest(item_index=item_index, field=field),
                    tempfile.TemporaryDirectory() as tmp,
                ):
                    bundle = make_bundle(tmp)
                    truth = deepcopy(bundle["truth"])
                    truth["items"][item_index][field] = value
                    self.assert_truth_invalid(bundle, truth, f"{field}: unexpected")
        for claim in ("", " \t"):
            with self.subTest(claim=repr(claim)), tempfile.TemporaryDirectory() as tmp:
                bundle = make_bundle(tmp)
                truth = deepcopy(bundle["truth"])
                truth["items"][0]["absent_claim"] = claim
                self.assert_truth_invalid(bundle, truth, "absent_claim")


class TestRubricRejection(TruthTestCase):
    def test_rubric_identity_verdict_and_timestamp_rules(self):
        verdicts = list(experiment_truth.VERDICTS)
        cases = (
            ("version", lambda rubric: rubric.__setitem__("rubric_version", 2), "rubric_version"),
            (
                "version_bool",
                lambda rubric: rubric.__setitem__("rubric_version", True),
                "rubric_version",
            ),
            ("revision", lambda rubric: rubric.__setitem__("contract_rev", "REV 2"), "contract_rev"),
            ("contract", lambda rubric: rubric.__setitem__("contract_sha256", "0" * 64), "contract_sha256"),
            (
                "verdict_missing",
                lambda rubric: rubric.__setitem__("verdicts", verdicts[:-1]),
                "verdicts",
            ),
            ("verdict_extra", lambda rubric: rubric.__setitem__("verdicts", verdicts + ["OTHER"]), "verdicts"),
            ("verdict_reorder", lambda rubric: rubric.__setitem__("verdicts", list(reversed(verdicts))), "verdicts"),
            ("escalation_verdict", lambda rubric: rubric.__setitem__("verdicts", verdicts + ["NEEDS_HUMAN_REVIEW"]), "verdicts"),
            ("escalation", lambda rubric: rubric.__setitem__("escalation_state", "PENDING"), "escalation_state"),
            (
                "tolerance",
                lambda rubric: rubric.__setitem__("timestamp_tolerance_s", 2.5),
                "timestamp_tolerance_s",
            ),
            ("tolerance_string", lambda rubric: rubric.__setitem__("timestamp_tolerance_s", "2.0"), "timestamp_tolerance_s"),
            ("tolerance_bool", lambda rubric: rubric.__setitem__("timestamp_tolerance_s", True), "timestamp_tolerance_s"),
            ("tolerance_nan", lambda rubric: rubric.__setitem__("timestamp_tolerance_s", math.nan), "timestamp_tolerance_s"),
            ("tolerance_inf", lambda rubric: rubric.__setitem__("timestamp_tolerance_s", math.inf), "timestamp_tolerance_s"),
            ("tolerance_null", lambda rubric: rubric.__setitem__("timestamp_tolerance_s", None), "timestamp_tolerance_s"),
            ("reference", lambda rubric: rubric.__setitem__("timestamp_reference", "video_time"), "timestamp_reference"),
            ("format", lambda rubric: rubric.__setitem__("timestamp_answer_format", "seconds"), "timestamp_answer_format"),
        )
        for name, mutate, expected in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                bundle = make_bundle(tmp)
                rubric = deepcopy(bundle["rubric"])
                mutate(rubric)
                self.assert_rubric_invalid(bundle, rubric, expected)

    def test_evidence_and_prose_rules_are_exact(self):
        def missing_evidence_key(rubric):
            del rubric["evidence_span_required"]["CORRECT"]

        def extra_evidence_key(rubric):
            rubric["evidence_span_required"]["OTHER"] = True

        def missing_verdict_rule(rubric):
            del rubric["verdict_rules"]["CORRECT"]

        def extra_verdict_rule(rubric):
            rubric["verdict_rules"]["OTHER"] = "Synthetic."

        cases = (
            ("evidence_missing", missing_evidence_key, "evidence_span_required.CORRECT: missing"),
            ("evidence_extra", extra_evidence_key, "evidence_span_required.OTHER: unexpected"),
            ("evidence_bool", lambda rubric: rubric["evidence_span_required"].__setitem__("CORRECT", 1), "CORRECT: expected a boolean"),
            (
                "not_answered",
                lambda rubric: rubric["evidence_span_required"].__setitem__(
                    "NOT_ANSWERED", True
                ),
                "NOT_ANSWERED: expected False",
            ),
            ("other_false", lambda rubric: rubric["evidence_span_required"].__setitem__("PARTIAL", False), "PARTIAL: expected True"),
            ("rule_missing", missing_verdict_rule, "verdict_rules.CORRECT: missing"),
            ("rule_extra", extra_verdict_rule, "verdict_rules.OTHER: unexpected"),
            ("rule_empty", lambda rubric: rubric["verdict_rules"].__setitem__("CORRECT", "  "), "verdict_rules.CORRECT"),
            ("escalation_empty", lambda rubric: rubric.__setitem__("escalation_rule", "\t"), "escalation_rule"),
        )
        for name, mutate, expected in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                bundle = make_bundle(tmp)
                rubric = deepcopy(bundle["rubric"])
                mutate(rubric)
                self.assert_rubric_invalid(bundle, rubric, expected)

    def test_every_forbidden_or_unknown_top_level_field_is_rejected(self):
        fields = (
            "score",
            "scores",
            "points",
            "weight",
            "weights",
            "formula",
            "numeric_score",
            "aggregate_score",
            "final_score",
            "human_status",
            "approved_by",
            "approved_at",
            "other",
        )
        for field in fields:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                bundle = make_bundle(tmp)
                rubric = deepcopy(bundle["rubric"])
                rubric[field] = None
                self.assert_rubric_invalid(bundle, rubric, f"rubric.{field}: unexpected")


class TestFailureEvidence(TruthTestCase):
    def test_contract_failure_keeps_contract_integrity_category(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(Path(tmp) / "bundle")
            evidence = Path(tmp) / "evidence"
            with mock.patch.object(
                harness,
                "verify_contract",
                side_effect=harness.ContractIntegrityError("synthetic mismatch"),
            ):
                with self.assertRaises(harness.PreflightError) as ctx:
                    experiment_truth.load_rubric(
                        bundle["rubric_path"], evidence_dir=evidence
                    )
            self.assertEqual(
                ctx.exception.record["invariant_category"],
                harness.CONTRACT_INTEGRITY,
            )

    def test_truth_failure_uses_truth_preflight_category_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(Path(tmp) / "bundle")
            truth = deepcopy(bundle["truth"])
            truth["truth_version"] = 2
            rewrite_locked(bundle["truth_path"], truth)
            evidence = Path(tmp) / "evidence"
            with self.assertRaises(harness.PreflightError) as ctx:
                load_bundle_truth(bundle, evidence_dir=evidence)
            record = ctx.exception.record
            self.assertEqual(record["stage"], "PRE-FLIGHT")
            self.assertEqual(record["failure_class"], "HARNESS")
            self.assertIs(record["request_made"], False)
            self.assertEqual(record["invariant_category"], harness.TRUTH_VALIDATION)
            self.assertEqual(
                record["failed_invariant"],
                "truth artifact satisfies the frozen schema and cross-artifact hash bindings",
            )
            self.assertTrue(record["timestamp"])
            with self.assertRaises(harness.EvidenceExistsError):
                load_bundle_truth(bundle, evidence_dir=evidence)

    def test_rubric_failure_uses_rubric_preflight_category_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = make_bundle(Path(tmp) / "bundle")
            rubric = deepcopy(bundle["rubric"])
            rubric["rubric_version"] = 2
            rewrite_locked(bundle["rubric_path"], rubric)
            evidence = Path(tmp) / "evidence"
            with self.assertRaises(harness.PreflightError) as ctx:
                experiment_truth.load_rubric(
                    bundle["rubric_path"], evidence_dir=evidence
                )
            record = ctx.exception.record
            self.assertEqual(record["stage"], "PRE-FLIGHT")
            self.assertEqual(record["failure_class"], "HARNESS")
            self.assertIs(record["request_made"], False)
            self.assertEqual(record["invariant_category"], harness.RUBRIC_VALIDATION)
            self.assertEqual(
                record["failed_invariant"],
                "rubric artifact satisfies the frozen schema and hash lock",
            )
            self.assertTrue(record["timestamp"])
            with self.assertRaises(harness.EvidenceExistsError):
                experiment_truth.load_rubric(
                    bundle["rubric_path"], evidence_dir=evidence
                )


if __name__ == "__main__":
    unittest.main()
