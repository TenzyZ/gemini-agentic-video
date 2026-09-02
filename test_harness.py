"""Deterministic offline tests for the frozen-contract invariants.

Run: python -m unittest -v test_harness

No Gemini call, no network, no API key, no committed runtime artifacts --
evidence tests use a temporary directory.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import harness

# Placeholder inputs. The real video URIs, prompts and generation_config
# values are human decisions that are NOT made here.
VIDEO = "https://www.youtube.com/watch?v=PLACEHOLDER"
PROMPT = "placeholder question text"
GEN_CONFIG = {"thinking_level": "high", "thinking_summaries": True, "max_output_tokens": 4096}


def make_pair():
    return harness.build_pair(video_uri=VIDEO, prompt=PROMPT, generation_config=GEN_CONFIG)


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


class TestPairConstruction(unittest.TestCase):
    def test_valid_pair_passes_preflight(self):
        self.assertIsNone(harness.preflight("T001/R1", make_pair()))

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
            self.assertEqual(pair[arm]["generation_config"], GEN_CONFIG)

    def test_generation_config_is_required_not_defaulted(self):
        for bad in ({}, None, "high"):
            with self.assertRaises(ValueError):
                harness.build_payload("STATIC", video_uri=VIDEO, prompt=PROMPT, generation_config=bad)

    def test_thinking_level_minimal_is_rejected(self):
        with self.assertRaises(ValueError):
            harness.build_payload(
                "STATIC",
                video_uri=VIDEO,
                prompt=PROMPT,
                generation_config={"thinking_level": "minimal"},
            )


class TestPreflightRejection(unittest.TestCase):
    """Any difference other than input[0].processing must block execution."""

    def assert_rejected(self, pair, expected_path):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(harness.PreflightError) as ctx:
                harness.preflight("T001/R1", pair, evidence_dir=Path(tmp))
            record = ctx.exception.record
            self.assertEqual(record["stage"], "PRE-FLIGHT")
            self.assertEqual(record["failure_class"], "HARNESS")
            self.assertFalse(record["request_made"])
            self.assertIn(expected_path, " ".join(record["differing_paths"]))
            written = json.loads((Path(tmp) / "preflight_failure.json").read_text(encoding="utf-8"))
            self.assertIs(written["request_made"], False)
            return record

    def test_changed_prompt_fails(self):
        pair = make_pair()
        pair["AGENTIC"]["input"][1]["text"] = "a different question"
        self.assert_rejected(pair, "input[1].text")

    def test_changed_video_uri_fails(self):
        pair = make_pair()
        pair["AGENTIC"]["input"][0]["uri"] = "https://www.youtube.com/watch?v=OTHER"
        self.assert_rejected(pair, "input[0].uri")

    def test_changed_resolution_fails(self):
        pair = make_pair()
        pair["AGENTIC"]["input"][0]["resolution"] = "high"
        self.assert_rejected(pair, "input[0].resolution")

    def test_resolution_changed_in_both_arms_still_fails(self):
        pair = make_pair()
        for arm in pair:
            pair[arm]["input"][0]["resolution"] = "high"
        self.assert_rejected(pair, "input[0].resolution")

    def test_changed_model_fails(self):
        pair = make_pair()
        pair["AGENTIC"]["model"] = "gemini-3.8-flash"
        self.assert_rejected(pair, "model")

    def test_changed_generation_config_field_fails(self):
        pair = make_pair()
        pair["AGENTIC"]["generation_config"]["thinking_level"] = "low"
        self.assert_rejected(pair, "generation_config.thinking_level")

    def test_added_generation_config_field_fails(self):
        pair = make_pair()
        pair["AGENTIC"]["generation_config"]["seed"] = 7
        self.assert_rejected(pair, "generation_config.seed")

    def test_static_only_field_fails(self):
        pair = make_pair()
        pair["STATIC"]["input"][0]["fps"] = 0.5
        self.assert_rejected(pair, "input[0].fps")

    def test_identical_arms_fail_no_experimental_variable(self):
        pair = make_pair()
        pair["AGENTIC"]["input"][0]["processing"] = "static"
        record = self.assert_rejected(pair, "input[0].processing")
        self.assertEqual(record["failed_invariant"], harness.PAIR_INVARIANT)

    def test_failure_record_identifies_structured_paths(self):
        pair = make_pair()
        pair["AGENTIC"]["model"] = "gemini-3.8-flash"
        pair["AGENTIC"]["input"][1]["text"] = "other"
        record = self.assert_rejected(pair, "input[1].text")
        joined = " ".join(record["differing_paths"])
        self.assertIn("model", joined)
        self.assertIn("input[1].text", joined)
        self.assertEqual(sorted(record["payload_sha256"]), ["AGENTIC", "STATIC"])


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
                    harness.preflight("T001/R1", pair, evidence_dir=Path(tmp))


if __name__ == "__main__":
    unittest.main()
