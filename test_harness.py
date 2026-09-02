"""Deterministic offline tests for the frozen-contract invariants.

Run: python -m unittest -v test_harness

No Gemini call, no network, no API key, no committed runtime artifacts --
evidence tests use a temporary directory, and contract-integrity failures are
simulated by injection rather than by touching the frozen artifacts.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import experiment_config
import harness

# Placeholder inputs only. This synthetic token cap is not a benchmark decision.
VIDEO = "https://www.youtube.com/watch?v=PLACEHOLDER"
PROMPT = "placeholder question text"
FIXTURE_MAX_OUTPUT_TOKENS = 4096

CONTRACT_DIGEST = harness.verify_contract()


def make_pair(test_id="T001", repeat_id="R1"):
    return harness.build_pair(
        test_id,
        repeat_id,
        video_uri=VIDEO,
        prompt=PROMPT,
        max_output_tokens=FIXTURE_MAX_OUTPUT_TOKENS,
    )


def ok_verify():
    """Stand-in for contract verification, so pair tests isolate the pair."""
    return CONTRACT_DIGEST


class TestContractIntegrity(unittest.TestCase):
    def test_frozen_contract_hash_passes(self):
        digest = harness.verify_contract()
        self.assertEqual(len(digest), 64)
        recorded = harness.CONTRACT_SHA_PATH.read_text(encoding="utf-8").split()[0]
        self.assertEqual(digest, recorded)

    def test_mismatched_hash_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            contract = Path(tmp) / "CONTRACT.md"
            sha = Path(tmp) / "CONTRACT.sha256"
            contract.write_bytes(b"tampered contract\n")
            sha.write_text("%s  CONTRACT.md\n" % ("0" * 64), encoding="utf-8")
            with self.assertRaises(harness.ContractIntegrityError):
                harness.verify_contract(contract, sha)

    def test_missing_and_malformed_records_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            contract = Path(tmp) / "CONTRACT.md"
            sha = Path(tmp) / "CONTRACT.sha256"
            contract.write_bytes(b"x\n")
            with self.assertRaises(harness.ContractIntegrityError):
                harness.verify_contract(contract, sha)  # sha file missing
            sha.write_text("not-a-digest CONTRACT.md\n", encoding="utf-8")
            with self.assertRaises(harness.ContractIntegrityError):
                harness.verify_contract(contract, sha)
            with self.assertRaises(harness.ContractIntegrityError):
                harness.verify_contract(Path(tmp) / "nope.md", sha)

    def test_verification_does_not_modify_frozen_artifacts(self):
        before = (harness.CONTRACT_PATH.read_bytes(), harness.CONTRACT_SHA_PATH.read_bytes())
        harness.verify_contract()
        after = (harness.CONTRACT_PATH.read_bytes(), harness.CONTRACT_SHA_PATH.read_bytes())
        self.assertEqual(before, after)


class TestGenerationConfigPolicy(unittest.TestCase):
    def derive(self, test_id="T001", repeat_id="R1"):
        return experiment_config.derive_seed(
            contract_sha256=CONTRACT_DIGEST,
            test_id=test_id,
            repeat_id=repeat_id,
        )

    def config(self, test_id="T001", repeat_id="R1"):
        return experiment_config.build_generation_config(
            contract_sha256=CONTRACT_DIGEST,
            test_id=test_id,
            repeat_id=repeat_id,
            max_output_tokens=FIXTURE_MAX_OUTPUT_TOKENS,
        )

    def assert_invalid(self, config, test_id="T001", repeat_id="R1"):
        with self.assertRaises(experiment_config.GenerationConfigError):
            experiment_config.validate_generation_config(
                config,
                contract_sha256=CONTRACT_DIGEST,
                test_id=test_id,
                repeat_id=repeat_id,
            )

    def test_same_identity_produces_same_seed(self):
        self.assertEqual(self.derive(), self.derive())

    def test_benchmark_repeat_seeds_differ(self):
        seeds = {self.derive("T001", repeat) for repeat in ("R1", "R2", "R3")}
        self.assertEqual(len(seeds), 3)

    def test_seeds_differ_across_test_ids(self):
        seeds = {
            self.derive(test_id, "R1") for test_id in experiment_config.ALLOWED_REPEATS
        }
        self.assertEqual(len(seeds), 4)

    def test_all_registered_pair_seeds_are_unique(self):
        seeds = {
            self.derive(test_id, repeat_id)
            for test_id, repeats in experiment_config.ALLOWED_REPEATS.items()
            for repeat_id in repeats
        }
        self.assertEqual(len(seeds), 10)

    def test_t004_r1_works_and_is_signed_32_bit_compatible(self):
        seed = self.derive("T004", "R1")
        self.assertGreaterEqual(seed, 0)
        self.assertLess(seed, 2**31)

    def test_invalid_test_and_repeat_fail_closed(self):
        for test_id, repeat_id in (
            ("T005", "R1"),
            ("T004", "R2"),
            ("T001", "R4"),
        ):
            with self.subTest(test_id=test_id, repeat_id=repeat_id):
                with self.assertRaises(experiment_config.GenerationConfigError):
                    self.derive(test_id, repeat_id)

    def test_seed_matches_canonical_sha256_material_without_randomness(self):
        material = f"{CONTRACT_DIGEST}|T001|R1".encode("utf-8")
        expected = int.from_bytes(hashlib.sha256(material).digest(), "big") % (2**31)
        self.assertEqual(self.derive(), expected)

    def test_valid_config_has_exactly_four_approved_keys_and_values(self):
        config = self.config()
        self.assertEqual(set(config), experiment_config.GENERATION_CONFIG_KEYS)
        self.assertEqual(config["thinking_level"], "medium")
        self.assertEqual(config["thinking_summaries"], "none")
        self.assertEqual(config["max_output_tokens"], FIXTURE_MAX_OUTPUT_TOKENS)
        self.assertEqual(config["seed"], self.derive())

    def test_max_output_tokens_is_required(self):
        with self.assertRaises(TypeError):
            experiment_config.build_generation_config(
                contract_sha256=CONTRACT_DIGEST,
                test_id="T001",
                repeat_id="R1",
            )

    def test_invalid_max_output_tokens_fail(self):
        for value in (
            None,
            "4096",
            True,
            0,
            -1,
            experiment_config.MODEL_MAX_OUTPUT_TOKENS + 1,
        ):
            with self.subTest(value=value):
                config = self.config()
                config["max_output_tokens"] = value
                self.assert_invalid(config)

    def test_wrong_or_manually_substituted_seed_fails(self):
        for seed in (self.derive() + 1, 42):
            with self.subTest(seed=seed):
                config = self.config()
                config["seed"] = seed
                self.assert_invalid(config)

    def test_wrong_thinking_level_including_minimal_fails(self):
        for level in ("low", "high", "minimal"):
            with self.subTest(level=level):
                config = self.config()
                config["thinking_level"] = level
                self.assert_invalid(config)

    def test_auto_thinking_summaries_fails(self):
        config = self.config()
        config["thinking_summaries"] = "auto"
        self.assert_invalid(config)

    def test_unexpected_and_missing_keys_fail(self):
        unexpected = self.config() | {"temperature": 0}
        self.assert_invalid(unexpected)
        for key in experiment_config.GENERATION_CONFIG_KEYS:
            with self.subTest(missing=key):
                config = self.config()
                del config[key]
                self.assert_invalid(config)


class TestPairConstruction(unittest.TestCase):
    def test_valid_pair_passes_preflight(self):
        digest = harness.preflight("T001", "R1", make_pair())
        self.assertEqual(digest, harness.verify_contract())

    def test_processing_is_exactly_static_vs_agentic(self):
        pair = make_pair()
        self.assertEqual(pair["STATIC"]["input"][0]["processing"], "static")
        self.assertEqual(pair["AGENTIC"]["input"][0]["processing"], "agentic")

    def test_resolution_is_low_in_both_arms(self):
        pair = make_pair()
        for arm in pair:
            self.assertEqual(pair[arm]["input"][0]["resolution"], "low")

    def test_shared_fields_are_identical(self):
        pair = make_pair()
        self.assertEqual(harness.diff_paths(pair["STATIC"], pair["AGENTIC"]), ["input[0].processing"])
        for arm in pair:
            self.assertEqual(pair[arm]["model"], "gemini-3.7-flash")
            self.assertEqual(pair[arm]["input"][0]["uri"], VIDEO)
            self.assertEqual(pair[arm]["input"][1]["text"], PROMPT)
            self.assertEqual(
                pair[arm]["generation_config"],
                experiment_config.build_generation_config(
                    contract_sha256=CONTRACT_DIGEST,
                    test_id="T001",
                    repeat_id="R1",
                    max_output_tokens=FIXTURE_MAX_OUTPUT_TOKENS,
                ),
            )

    def test_pair_uses_the_same_derived_seed_in_both_arms(self):
        pair = make_pair()
        self.assertEqual(
            pair["STATIC"]["generation_config"]["seed"],
            pair["AGENTIC"]["generation_config"]["seed"],
        )

    def test_generation_config_is_required_not_defaulted(self):
        for bad in ({}, None, "high"):
            with self.assertRaises(ValueError):
                harness.build_payload("STATIC", video_uri=VIDEO, prompt=PROMPT, generation_config=bad)

    def test_thinking_level_minimal_is_rejected_during_construction(self):
        with self.assertRaises(ValueError):
            harness.build_payload(
                "STATIC",
                video_uri=VIDEO,
                prompt=PROMPT,
                generation_config={"thinking_level": "minimal"},
            )

    def test_each_valid_arm_reports_no_shape_violation(self):
        pair = make_pair()
        for arm, payload in pair.items():
            self.assertEqual(harness.validate_arm(arm, payload), [])


class PreflightRejectionMixin:
    def assert_rejected(self, pair, expected_path, expected_category):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(harness.PreflightError) as ctx:
                harness.preflight(
                    "T001", "R1", pair, evidence_dir=Path(tmp), verify=ok_verify
                )
            record = ctx.exception.record
            self.assertEqual(record["stage"], "PRE-FLIGHT")
            self.assertEqual(record["failure_class"], "HARNESS")
            self.assertIs(record["request_made"], False)
            self.assertEqual(record["invariant_category"], expected_category)
            self.assertEqual(record["failed_invariant"], harness.FAILED_INVARIANT[expected_category])
            self.assertIn(expected_path, " ".join(record["violations"]))
            written = json.loads((Path(tmp) / "preflight_failure.json").read_text(encoding="utf-8"))
            self.assertIs(written["request_made"], False)
            self.assertEqual(written["invariant_category"], expected_category)
            return record


class TestPairDifferenceRejection(PreflightRejectionMixin, unittest.TestCase):
    """Each arm is individually valid; the arms disagree beyond the treatment."""

    def test_changed_prompt_fails(self):
        pair = make_pair()
        pair["AGENTIC"]["input"][1]["text"] = "a different question"
        self.assert_rejected(pair, "input[1].text", harness.PAIR_DIFFERENCE)

    def test_changed_video_uri_fails(self):
        pair = make_pair()
        pair["AGENTIC"]["input"][0]["uri"] = "https://www.youtube.com/watch?v=OTHER"
        self.assert_rejected(pair, "input[0].uri", harness.PAIR_DIFFERENCE)

    def test_changed_generation_config_field_fails_policy(self):
        pair = make_pair()
        pair["AGENTIC"]["generation_config"]["thinking_level"] = "low"
        self.assert_rejected(
            pair, "generation_config.thinking_level", harness.GENERATION_CONFIG
        )

    def test_different_seed_between_arms_blocks_preflight(self):
        pair = make_pair()
        pair["AGENTIC"]["generation_config"]["seed"] = 7
        self.assert_rejected(pair, "generation_config.seed", harness.GENERATION_CONFIG)

    def test_failure_record_identifies_every_structured_path(self):
        pair = make_pair()
        pair["AGENTIC"]["input"][0]["uri"] = "https://www.youtube.com/watch?v=OTHER"
        pair["AGENTIC"]["input"][1]["text"] = "other"
        record = self.assert_rejected(pair, "input[1].text", harness.PAIR_DIFFERENCE)
        self.assertIn("input[0].uri", record["violations"])
        self.assertIn("input[1].text", record["violations"])
        self.assertEqual(record["differing_values"]["input[1].text"]["STATIC"], PROMPT)
        self.assertEqual(sorted(record["payload_sha256"]), ["AGENTIC", "STATIC"])


class TestRequestShapeRejection(PreflightRejectionMixin, unittest.TestCase):
    """Per-arm validation: identically malformed arms must not pass."""

    def test_changed_model_fails(self):
        pair = make_pair()
        pair["AGENTIC"]["model"] = "gemini-3.8-flash"
        self.assert_rejected(pair, "model", harness.REQUEST_SHAPE)

    def test_changed_resolution_fails(self):
        pair = make_pair()
        pair["AGENTIC"]["input"][0]["resolution"] = "high"
        self.assert_rejected(pair, "input[0].resolution", harness.REQUEST_SHAPE)

    def test_resolution_changed_in_both_arms_still_fails(self):
        pair = make_pair()
        for arm in pair:
            pair[arm]["input"][0]["resolution"] = "high"
        record = self.assert_rejected(pair, "input[0].resolution", harness.REQUEST_SHAPE)
        self.assertIn("STATIC:input[0].resolution", " ".join(record["violations"]))
        self.assertIn("AGENTIC:input[0].resolution", " ".join(record["violations"]))

    def test_model_changed_in_both_arms_still_fails(self):
        pair = make_pair()
        for arm in pair:
            pair[arm]["model"] = "gemini-3.8-flash"
        self.assert_rejected(pair, "model", harness.REQUEST_SHAPE)

    def test_generation_config_missing_in_both_arms_fails(self):
        pair = make_pair()
        for arm in pair:
            del pair[arm]["generation_config"]
        self.assert_rejected(pair, "generation_config (missing)", harness.REQUEST_SHAPE)

    def test_generation_config_empty_in_both_arms_fails(self):
        pair = make_pair()
        for arm in pair:
            pair[arm]["generation_config"] = {}
        self.assert_rejected(pair, "generation_config", harness.REQUEST_SHAPE)

    def test_thinking_level_minimal_in_both_arms_fails(self):
        pair = make_pair()
        for arm in pair:
            pair[arm]["generation_config"]["thinking_level"] = "minimal"
        self.assert_rejected(
            pair, "generation_config.thinking_level", harness.GENERATION_CONFIG
        )

    def test_wrong_video_type_in_both_arms_fails(self):
        pair = make_pair()
        for arm in pair:
            pair[arm]["input"][0]["type"] = "image"
        self.assert_rejected(pair, "input[0].type", harness.REQUEST_SHAPE)

    def test_wrong_text_type_in_both_arms_fails(self):
        pair = make_pair()
        for arm in pair:
            pair[arm]["input"][1]["type"] = "video"
        self.assert_rejected(pair, "input[1].type", harness.REQUEST_SHAPE)

    def test_swapped_block_order_fails(self):
        pair = make_pair()
        for arm in pair:
            pair[arm]["input"] = list(reversed(pair[arm]["input"]))
        self.assert_rejected(pair, "input[0]", harness.REQUEST_SHAPE)

    def test_wrong_input_length_fails(self):
        pair = make_pair()
        for arm in pair:
            pair[arm]["input"] = pair[arm]["input"][:1]
        self.assert_rejected(pair, "input (expected a two-item list", harness.REQUEST_SHAPE)

    def test_empty_uri_and_prompt_fail(self):
        pair = make_pair()
        for arm in pair:
            pair[arm]["input"][0]["uri"] = ""
            pair[arm]["input"][1]["text"] = ""
        record = self.assert_rejected(pair, "input[0].uri", harness.REQUEST_SHAPE)
        self.assertIn("input[1].text", " ".join(record["violations"]))

    def test_symmetric_static_only_field_cannot_sneak_through(self):
        for field, value in (("fps", 0.5), ("start_offset", "10.5s"), ("end_offset", "20s")):
            with self.subTest(field=field):
                pair = make_pair()
                for arm in pair:
                    pair[arm]["input"][0][field] = value
                record = self.assert_rejected(pair, f"input[0].{field}", harness.REQUEST_SHAPE)
                self.assertIn("static-only control", " ".join(record["violations"]))

    def test_asymmetric_static_only_field_fails(self):
        pair = make_pair()
        pair["STATIC"]["input"][0]["fps"] = 0.5
        self.assert_rejected(pair, "input[0].fps", harness.REQUEST_SHAPE)

    def test_unexpected_top_level_field_fails(self):
        pair = make_pair()
        for arm in pair:
            pair[arm]["service_tier"] = "priority"
        self.assert_rejected(pair, "service_tier", harness.REQUEST_SHAPE)

    def test_identical_arms_fail_no_experimental_variable(self):
        pair = make_pair()
        pair["AGENTIC"]["input"][0]["processing"] = "static"
        self.assert_rejected(pair, "input[0].processing", harness.REQUEST_SHAPE)

    def test_missing_arm_fails(self):
        pair = make_pair()
        del pair["AGENTIC"]
        self.assert_rejected(pair, "pair must contain exactly", harness.REQUEST_SHAPE)


class TestPreflightRequiresContractIntegrity(unittest.TestCase):
    def test_successful_preflight_verifies_the_contract(self):
        calls = []

        def spy():
            calls.append("verified")
            return CONTRACT_DIGEST

        digest = harness.preflight("T001", "R1", make_pair(), verify=spy)
        self.assertEqual(calls, ["verified"])
        self.assertEqual(digest, CONTRACT_DIGEST)

    def test_default_preflight_returns_the_real_frozen_digest(self):
        recorded = harness.CONTRACT_SHA_PATH.read_text(encoding="utf-8").split()[0]
        self.assertEqual(harness.preflight("T001", "R1", make_pair()), recorded)

    def test_contract_failure_blocks_before_config_acceptance(self):
        def broken():
            raise harness.ContractIntegrityError("simulated hash mismatch")

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(harness.PreflightError) as ctx:
                pair = make_pair()
                pair["STATIC"]["generation_config"]["thinking_level"] = "high"
                harness.preflight(
                    "T001", "R1", pair, evidence_dir=Path(tmp), verify=broken
                )
            record = ctx.exception.record
            self.assertEqual(record["invariant_category"], harness.CONTRACT_INTEGRITY)
            self.assertEqual(record["stage"], "PRE-FLIGHT")
            self.assertEqual(record["failure_class"], "HARNESS")
            self.assertIs(record["request_made"], False)
            self.assertIn("simulated hash mismatch", " ".join(record["violations"]))
            written = json.loads((Path(tmp) / "preflight_failure.json").read_text(encoding="utf-8"))
            self.assertIs(written["request_made"], False)
            self.assertEqual(written["invariant_category"], harness.CONTRACT_INTEGRITY)


class TestEvidencePersistence(unittest.TestCase):
    """Fake response/error objects only -- no SDK, no client, no network."""

    class FakeResponse:
        """Stands in for an SDK response object with a nested usage object."""

        def __init__(self):
            self.id = "interaction_fake"
            self.status = "completed"
            self.model = "gemini-3.7-flash"
            self.steps = [{"type": "processing_call", "id": "c1"}]
            self.usage = {"total_tokens": 123, "total_thought_tokens": 45}

    class FakeDumpable:
        """Stands in for an SDK object exposing a structured serializer."""

        def model_dump(self):
            return {"status": "completed", "usage": {"total_tokens": 7}}

    class Opaque:
        """No structured serializer and no instance __dict__: unserializable."""

        __slots__ = ("hidden",)

        def __init__(self):
            self.hidden = "state that repr() would silently drop"

    class FakeApiError(Exception):
        def __init__(self):
            super().__init__("fake transport failure")
            self.status_code = 503
            self.request_id = "req_fake"

    def test_raw_response_written_before_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            attempt = Path(tmp) / "attempt1"
            with self.assertRaises(FileNotFoundError):
                harness.load_raw_response(attempt)  # nothing to parse yet
            answer = "  line one\nline two  "
            paths = harness.persist_response(attempt, self.FakeResponse(), answer)
            self.assertTrue(paths["raw_response"].is_file())
            self.assertEqual(paths["answer_text"].read_text(encoding="utf-8"), answer)
            parsed = harness.load_raw_response(attempt)
            self.assertEqual(parsed["usage"]["total_tokens"], 123)
            self.assertEqual(parsed["steps"][0]["type"], "processing_call")
            self.assertEqual(parsed["status"], "completed")

    def test_structured_serializer_is_used_whole(self):
        with tempfile.TemporaryDirectory() as tmp:
            attempt = Path(tmp) / "attempt1"
            harness.persist_response(attempt, self.FakeDumpable(), "answer")
            self.assertEqual(
                harness.load_raw_response(attempt),
                {"status": "completed", "usage": {"total_tokens": 7}},
            )

    def test_unserializable_response_fails_closed_instead_of_repr(self):
        with tempfile.TemporaryDirectory() as tmp:
            attempt = Path(tmp) / "attempt1"
            with self.assertRaises(harness.EvidenceSerializationError):
                harness.persist_response(attempt, self.Opaque(), "answer")
            self.assertFalse((attempt / "raw_response.json").exists())
            self.assertFalse((attempt / "answer.txt").exists())

    def test_nested_unserializable_value_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            attempt = Path(tmp) / "attempt1"
            response = self.FakeResponse()
            response.usage = {"total_tokens": self.Opaque()}
            with self.assertRaises(harness.EvidenceSerializationError):
                harness.persist_response(attempt, response, "answer")
            self.assertFalse((attempt / "raw_response.json").exists())
            self.assertFalse((attempt / "answer.txt").exists())

    def test_failing_structured_serializer_is_loud_not_lossy(self):
        class Exploding:
            def model_dump(self):
                raise RuntimeError("serializer blew up")

        with tempfile.TemporaryDirectory() as tmp:
            attempt = Path(tmp) / "attempt1"
            with self.assertRaises(harness.EvidenceSerializationError):
                harness.persist_response(attempt, Exploding(), "answer")
            self.assertFalse((attempt / "raw_response.json").exists())

    def test_error_persisted_without_fabricating_a_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            attempt = Path(tmp) / "attempt1"
            path = harness.persist_error(attempt, self.FakeApiError(), attempt=1)
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(record["exception_type"], "FakeApiError")
            self.assertEqual(record["http_status"], 503)
            self.assertEqual(record["request_id"], "req_fake")
            self.assertFalse((attempt / "raw_response.json").exists())
            self.assertFalse((attempt / "answer.txt").exists())

    def test_existing_evidence_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            attempt = Path(tmp) / "attempt1"
            harness.persist_response(attempt, self.FakeResponse(), "first")
            with self.assertRaises(harness.EvidenceExistsError):
                harness.persist_response(attempt, self.FakeResponse(), "second")
            self.assertEqual((attempt / "answer.txt").read_text(encoding="utf-8"), "first")

    def test_preflight_record_is_not_overwritten(self):
        pair = make_pair()
        pair["AGENTIC"]["model"] = "gemini-3.8-flash"
        with tempfile.TemporaryDirectory() as tmp:
            for expected in (harness.PreflightError, harness.EvidenceExistsError):
                with self.assertRaises(expected):
                    harness.preflight(
                        "T001", "R1", pair, evidence_dir=Path(tmp), verify=ok_verify
                    )


if __name__ == "__main__":
    unittest.main()
