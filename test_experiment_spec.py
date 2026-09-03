"""Offline tests for hash-locked test-spec loading and validation."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import experiment_config
import experiment_spec
import harness

CONTRACT_DIGEST = harness.verify_contract()
VIDEO_URI = "https://www.youtube.com/watch?v=SPEC_FIXTURE"


def make_spec(test_id="T001"):
    questions = []
    for index, question_id in enumerate(experiment_spec.QUESTION_IDS):
        category = "global" if index < 6 else "localized"
        questions.append(
            {
                "question_id": question_id,
                "category": category,
                "requires_timestamp": category == "localized",
                "expects_absence": index in (0, 6),
            }
        )
    prompt = "\n".join(
        f"[{question_id}]\nSynthetic fixture only.\n[/{question_id}]"
        for question_id in experiment_spec.QUESTION_IDS
    )
    repeats = {}
    for repeat_id in sorted(experiment_config.ALLOWED_REPEATS[test_id]):
        repeats[repeat_id] = {
            "arm_order": (
                ["AGENTIC", "STATIC"]
                if repeat_id == "R2"
                else ["STATIC", "AGENTIC"]
            ),
            "generation_config": experiment_config.build_generation_config(
                contract_sha256=CONTRACT_DIGEST,
                test_id=test_id,
                repeat_id=repeat_id,
                max_output_tokens=experiment_config.SCORED_MAX_OUTPUT_TOKENS,
            ),
        }
    return {
        "spec_version": 1,
        "test_id": test_id,
        "test_class": "STRESS" if test_id == "T004" else "BENCHMARK",
        "contract_rev": "REV 1",
        "contract_sha256": CONTRACT_DIGEST,
        "video": {
            "uri": VIDEO_URI,
            "video_duration_s": 3600,
            "resolution": "low",
        },
        "prompt": {
            "text": prompt,
            "sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        },
        "question_mix": {"global": 6, "localized": 6, "absence_probes": 2},
        "questions": questions,
        "arms": {
            "STATIC": {"processing": "static"},
            "AGENTIC": {"processing": "agentic"},
        },
        "repeats": repeats,
    }


def write_spec(directory, spec, *, write_hash=True, filename=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (filename or f"{spec.get('test_id', 'fixture')}.json")
    raw = json.dumps(spec, indent=2).encode("utf-8")
    path.write_bytes(raw)
    if write_hash:
        digest = hashlib.sha256(raw).hexdigest()
        path.with_suffix(".sha256").write_text(
            f"{digest}  {path.name}\n", encoding="utf-8", newline=""
        )
    return path


class SpecTestCase(unittest.TestCase):
    def assert_invalid(self, spec, expected):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_spec(tmp, spec)
            with self.assertRaises(experiment_spec.SpecValidationError) as ctx:
                experiment_spec.load_spec(path)
            self.assertIn(expected, " ".join(ctx.exception.violations))


class TestValidSpecs(SpecTestCase):
    def test_scored_constant_is_distinct_from_model_ceiling(self):
        self.assertEqual(experiment_config.SCORED_MAX_OUTPUT_TOKENS, 20_000)
        self.assertEqual(experiment_config.MODEL_MAX_OUTPUT_TOKENS, 65_536)

    def test_valid_t001_routes_through_existing_harness(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = experiment_spec.load_spec(write_spec(tmp, make_spec()))
            repeat_id = "R1"
            repeat = loaded["repeats"][repeat_id]
            pair = harness.build_pair(
                loaded["test_id"],
                repeat_id,
                video_uri=loaded["video"]["uri"],
                prompt=loaded["prompt"]["text"],
                max_output_tokens=repeat["generation_config"]["max_output_tokens"],
            )
            self.assertEqual(
                pair["STATIC"]["generation_config"], repeat["generation_config"]
            )
            self.assertEqual(harness.preflight("T001", repeat_id, pair), CONTRACT_DIGEST)
            self.assertEqual(
                harness.diff_paths(pair["STATIC"], pair["AGENTIC"]),
                ["input[0].processing"],
            )
            self.assertEqual(set(loaded["repeats"]), {"R1", "R2", "R3"})

    def test_valid_t004_is_stress_with_only_static_first_r1(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = experiment_spec.load_spec(write_spec(tmp, make_spec("T004")))
        self.assertEqual(loaded["test_class"], "STRESS")
        self.assertEqual(set(loaded["repeats"]), {"R1"})
        self.assertEqual(loaded["repeats"]["R1"]["arm_order"], ["STATIC", "AGENTIC"])


class TestSpecHashRejection(SpecTestCase):
    def test_tampered_spec_bytes_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_spec(tmp, make_spec())
            path.write_bytes(path.read_bytes() + b"\n")
            with self.assertRaises(experiment_spec.SpecValidationError) as ctx:
                experiment_spec.load_spec(path)
            self.assertIn("spec_sha256: mismatch", str(ctx.exception))

    def test_missing_spec_hash_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_spec(tmp, make_spec(), write_hash=False)
            with self.assertRaises(experiment_spec.SpecValidationError) as ctx:
                experiment_spec.load_spec(path)
            self.assertIn("spec_sha256: file not found", str(ctx.exception))

    def test_malformed_spec_hash_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_spec(tmp, make_spec(), write_hash=False)
            path.with_suffix(".sha256").write_text("not-a-digest\n", encoding="utf-8")
            with self.assertRaises(experiment_spec.SpecValidationError) as ctx:
                experiment_spec.load_spec(path)
            self.assertIn("spec_sha256: malformed", str(ctx.exception))


class TestIdentityAndBindingRejection(SpecTestCase):
    def test_spec_filename_must_match_test_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_spec(tmp, make_spec(), filename="foo.json")
            with self.assertRaises(experiment_spec.SpecValidationError) as ctx:
                experiment_spec.load_spec(path)
            self.assertIn("filename/test_id mismatch", str(ctx.exception))

    def test_other_test_filename_cannot_claim_t001(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_spec(tmp, make_spec(), filename="T002.json")
            with self.assertRaises(experiment_spec.SpecValidationError) as ctx:
                experiment_spec.load_spec(path)
            self.assertIn("filename/test_id mismatch", str(ctx.exception))

    def test_wrong_spec_version_fails(self):
        spec = make_spec()
        spec["spec_version"] = 2
        self.assert_invalid(spec, "spec_version")

    def test_unknown_test_id_fails(self):
        spec = make_spec()
        spec["test_id"] = "T005"
        self.assert_invalid(spec, "test_id: unknown")

    def test_wrong_test_class_fails(self):
        spec = make_spec("T004")
        spec["test_class"] = "BENCHMARK"
        self.assert_invalid(spec, "test_class")

    def test_wrong_contract_revision_fails(self):
        spec = make_spec()
        spec["contract_rev"] = "REV 2"
        self.assert_invalid(spec, "contract_rev")

    def test_wrong_contract_digest_fails(self):
        spec = make_spec()
        spec["contract_sha256"] = "0" * 64
        self.assert_invalid(spec, "contract_sha256")

    def test_bad_prompt_hash_fails(self):
        spec = make_spec()
        spec["prompt"]["sha256"] = "0" * 64
        self.assert_invalid(spec, "prompt.sha256: mismatch")

    def test_empty_prompt_fails(self):
        spec = make_spec()
        spec["prompt"] = {
            "text": "",
            "sha256": hashlib.sha256(b"").hexdigest(),
        }
        self.assert_invalid(spec, "prompt.text")

    def test_non_utf8_encodable_prompt_fails(self):
        spec = make_spec()
        spec["prompt"]["text"] += "\ud800"
        spec["prompt"]["sha256"] = "0" * 64
        self.assert_invalid(spec, "prompt.text: expected UTF-8-encodable text")

    def test_wrong_resolution_fails(self):
        spec = make_spec()
        spec["video"]["resolution"] = "high"
        self.assert_invalid(spec, "video.resolution")

    def test_wrong_processing_value_fails(self):
        spec = make_spec()
        spec["arms"]["STATIC"]["processing"] = "agentic"
        self.assert_invalid(spec, "arms.STATIC.processing")

    def test_missing_required_field_fails(self):
        spec = make_spec()
        del spec["video"]
        self.assert_invalid(spec, "spec.video: missing")

    def test_unexpected_field_fails(self):
        spec = make_spec()
        spec["response_format"] = {"type": "json_schema"}
        self.assert_invalid(spec, "spec.response_format: unexpected")


class TestRepeatRejection(SpecTestCase):
    def test_wrong_max_output_tokens_fails(self):
        spec = make_spec()
        spec["repeats"]["R1"]["generation_config"]["max_output_tokens"] = 19_999
        self.assert_invalid(spec, "max_output_tokens: expected 20000")

    def test_wrong_seed_fails(self):
        spec = make_spec()
        spec["repeats"]["R1"]["generation_config"]["seed"] += 1
        self.assert_invalid(spec, "generation_config.seed")

    def test_extra_generation_config_key_fails(self):
        spec = make_spec()
        spec["repeats"]["R1"]["generation_config"]["temperature"] = 0
        self.assert_invalid(spec, "generation_config.temperature: unexpected")

    def test_missing_generation_config_key_fails(self):
        spec = make_spec()
        del spec["repeats"]["R1"]["generation_config"]["thinking_summaries"]
        self.assert_invalid(spec, "generation_config.thinking_summaries: missing")

    def test_t004_r2_fails(self):
        spec = make_spec("T004")
        spec["repeats"]["R2"] = deepcopy(make_spec()["repeats"]["R2"])
        self.assert_invalid(spec, "repeats.R2: unexpected")

    def test_missing_repeat_fails(self):
        spec = make_spec()
        del spec["repeats"]["R3"]
        self.assert_invalid(spec, "repeats.R3: missing")

    def test_extra_repeat_fails(self):
        spec = make_spec()
        spec["repeats"]["R4"] = deepcopy(spec["repeats"]["R1"])
        self.assert_invalid(spec, "repeats.R4: unexpected")

    def test_wrong_arm_order_fails(self):
        spec = make_spec()
        spec["repeats"]["R2"]["arm_order"] = ["STATIC", "AGENTIC"]
        self.assert_invalid(spec, "repeats.R2.arm_order")


class TestQuestionRejection(SpecTestCase):
    def test_eleven_questions_fail(self):
        spec = make_spec()
        spec["questions"].pop()
        self.assert_invalid(spec, "questions: expected 12 items, got 11")

    def test_thirteen_questions_fail(self):
        spec = make_spec()
        extra = deepcopy(spec["questions"][-1])
        extra["question_id"] = "Q013"
        spec["questions"].append(extra)
        self.assert_invalid(spec, "questions: expected 12 items, got 13")

    def test_duplicate_question_id_fails(self):
        spec = make_spec()
        spec["questions"][-1]["question_id"] = "Q011"
        self.assert_invalid(spec, "question_id: duplicate")

    def test_gap_in_question_ids_fails(self):
        spec = make_spec()
        spec["questions"][-1]["question_id"] = "Q013"
        self.assert_invalid(spec, "expected Q001..Q012")

    def test_missing_question_id_fails(self):
        spec = make_spec()
        del spec["questions"][0]["question_id"]
        self.assert_invalid(spec, "questions[0].question_id: missing")

    def test_wrong_global_localized_count_fails(self):
        spec = make_spec()
        spec["questions"][5]["category"] = "localized"
        spec["questions"][5]["requires_timestamp"] = True
        self.assert_invalid(spec, "expected 6 global, got 5")

    def test_question_mix_must_match_declared_counts(self):
        spec = make_spec()
        spec["question_mix"]["global"] = 5
        self.assert_invalid(spec, "question_mix.global: expected 6")

    def test_localized_timestamp_false_fails(self):
        spec = make_spec()
        spec["questions"][6]["requires_timestamp"] = False
        self.assert_invalid(spec, "for localized questions")

    def test_global_timestamp_true_fails(self):
        spec = make_spec()
        spec["questions"][0]["requires_timestamp"] = True
        self.assert_invalid(spec, "for global questions")

    def test_one_absence_probe_fails(self):
        spec = make_spec()
        spec["questions"][6]["expects_absence"] = False
        self.assert_invalid(spec, "expected 2 true values, got 1")

    def test_three_absence_probes_fail(self):
        spec = make_spec()
        spec["questions"][1]["expects_absence"] = True
        self.assert_invalid(spec, "expected 2 true values, got 3")

    def test_two_absence_probes_in_same_category_fail(self):
        spec = make_spec()
        spec["questions"][1]["expects_absence"] = True
        spec["questions"][6]["expects_absence"] = False
        self.assert_invalid(spec, "expected one global and one localized")

    def test_question_id_absent_from_prompt_fails(self):
        spec = make_spec()
        spec["prompt"]["text"] = spec["prompt"]["text"].replace("Q012", "MISSING")
        spec["prompt"]["sha256"] = hashlib.sha256(
            spec["prompt"]["text"].encode("utf-8")
        ).hexdigest()
        self.assert_invalid(spec, "absent from prompt.text")

    def test_non_boolean_question_flags_fail(self):
        spec = make_spec()
        spec["questions"][0]["requires_timestamp"] = 0
        self.assert_invalid(spec, "requires_timestamp: expected a boolean")

    def test_non_boolean_absence_flag_fails(self):
        spec = make_spec()
        spec["questions"][1]["expects_absence"] = 1
        self.assert_invalid(spec, "expects_absence: expected a boolean")


class TestStructuralTypeRejection(SpecTestCase):
    def test_invalid_structural_types_fail(self):
        for field, value in (
            ("video", []),
            ("prompt", []),
            ("question_mix", []),
            ("questions", {}),
            ("arms", []),
            ("repeats", []),
        ):
            with self.subTest(field=field):
                spec = make_spec()
                spec[field] = value
                self.assert_invalid(spec, f"{field}: expected")

    def test_bool_is_not_accepted_as_integer(self):
        cases = (
            ("spec_version", lambda spec: spec.__setitem__("spec_version", True)),
            (
                "video.video_duration_s",
                lambda spec: spec["video"].__setitem__("video_duration_s", True),
            ),
            (
                "question_mix.global",
                lambda spec: spec["question_mix"].__setitem__("global", True),
            ),
            (
                "max_output_tokens",
                lambda spec: spec["repeats"]["R1"]["generation_config"].__setitem__(
                    "max_output_tokens", True
                ),
            ),
            (
                "generation_config.seed",
                lambda spec: spec["repeats"]["R1"]["generation_config"].__setitem__(
                    "seed", True
                ),
            ),
        )
        for expected, mutate in cases:
            with self.subTest(expected=expected):
                spec = make_spec()
                mutate(spec)
                self.assert_invalid(spec, expected)


class TestSpecFailureEvidence(unittest.TestCase):
    def test_validation_failure_writes_standard_preflight_evidence_once(self):
        spec = make_spec()
        spec["test_id"] = "T005"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_spec(root / "spec", spec)
            evidence = root / "evidence"
            with self.assertRaises(harness.PreflightError) as ctx:
                experiment_spec.load_spec(path, evidence_dir=evidence)
            record = ctx.exception.record
            self.assertEqual(record["stage"], "PRE-FLIGHT")
            self.assertEqual(record["failure_class"], "HARNESS")
            self.assertIs(record["request_made"], False)
            self.assertEqual(record["invariant_category"], harness.SPEC_VALIDATION)
            self.assertEqual(
                record["failed_invariant"], harness.FAILED_INVARIANT[harness.SPEC_VALIDATION]
            )
            self.assertTrue(record["timestamp"])
            self.assertEqual(record["pair_id"], "T005/SPEC")
            self.assertIn("test_id: unknown", " ".join(record["violations"]))
            written = json.loads(
                (evidence / "preflight_failure.json").read_text(encoding="utf-8")
            )
            self.assertIs(written["request_made"], False)
            with self.assertRaises(harness.EvidenceExistsError):
                experiment_spec.load_spec(path, evidence_dir=evidence)


if __name__ == "__main__":
    unittest.main()
