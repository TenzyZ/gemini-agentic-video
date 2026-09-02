# Experiment Contract — Gemini STATIC vs AGENTIC Video Processing

**Revision:** REV 1
**Status:** HUMAN APPROVED — FROZEN
**Approved:** 2026-09-02
**Freeze:** in force from the approval date; material invariants may not change silently thereafter (§22)
**Authoritative for:** experiment methodology. Verified and recorded Gemini API facts live in `docs/API_VERIFICATION.md`; shared, provider-neutral operating and routing rules live in `AGENTS.md`; Claude-specific additions live in `CLAUDE.md`.

Every run records `contract_rev` and `contract_sha256` in its `run_config.json`. Evidence produced under one revision stays tagged with that revision, permanently.

---

## 1. Objective and framing

Determine, from recorded evidence, how Gemini 3.7 Flash's **agentic** video processing compares to its **static** video processing on identical inputs, across answer quality, timestamp accuracy, unsupported-claim behavior, token cost, latency, and observable navigation behavior.

The framing is hypothesis-neutral. This contract does not predict a winner and is not built to produce one.

- STATIC winning is a fully acceptable outcome.
- "No winner" is a fully acceptable outcome.
- A mixed result (one arm better on quality, worse on cost) is the expected shape and must be reported as a tradeoff, not resolved into a verdict.
- Vendor performance claims recorded in `docs/API_VERIFICATION.md` §A4 are hypotheses under test, never expectations. An observation contradicting them is a valid finding.
- No result may be discarded, softened, or re-run because it is unfavorable.

## 2. Subject model

`gemini-3.7-flash` — pinned exactly. The model id returned by the API is recorded alongside the requested id; any difference sets `MODEL_MISMATCH` and routes the trial to `NEEDS_HUMAN_REVIEW`.

API surface: the **Interactions API**, `client.interactions.create(...)`. Not `generateContent`. The two surfaces use different field names for the same concepts (§4), and mixing them would produce a silently wrong request.

## 3. Arms

Exactly two, differing in exactly one key:

| Arm | `processing` |
|---|---|
| STATIC | `"static"` |
| AGENTIC | `"agentic"` |

## 4. Video-input invariants

Frozen request shape for every trial:

```python
client.interactions.create(
    model="gemini-3.7-flash",
    input=[
        {
            "type": "video",
            "uri": "<public YouTube URL from the test spec>",
            "processing": "static",   # or "agentic" — the only difference between arms
            "resolution": "low",      # identical in both arms, always set explicitly
        },
        {"type": "text", "text": "<frozen prompt from the test spec>"},
    ],
    generation_config={ ... },        # identical in both arms, from the test spec
)
```

**`resolution = "low"`, set explicitly in both arms.** The field on the Interactions surface is `resolution`, not `media_resolution` — established from the installed `google-genai` 2.21.0 generated types (`docs/API_VERIFICATION.md` item 5b). The locally installed SDK's client-side accepted type is `"low" | "medium" | "high" | "ultra_high"`; this does not establish server-side video support for every member. Current Google media-resolution documentation marks `ultra_high` as unavailable for video. The experiment uses `"low"` only.

The reason for locking it is **experimental reproducibility and configuration invariance**: an explicitly set, identical value makes the request payload self-documenting and removes any possibility that an unstated default differs between the two processing modes or shifts between runs. It is not locked on the basis of a token-cost argument, and this contract makes no claim about per-frame token tiers.

**Locked identically across both arms of a pair:**

| Locked | Source |
|---|---|
| `model` | this contract |
| video `uri` | test spec |
| prompt text (byte-identical, sha256 recorded) | test spec |
| `resolution` = `"low"` | this contract |
| `generation_config` in full — including `thinking_level` and `thinking_summaries` | test spec |
| SDK + SDK version | recorded from environment |
| ground truth | `truth/` |
| rubric | `truth/rubric.json` |

Every `generation_config` value must be **explicitly set** rather than defaulted, identical in both arms, and frozen in the hash-locked test spec before scored execution. `thinking_level` must not be `minimal` — that value is documented to error on this model.

**Not set, in either arm:** `fps`, `start_offset`, `end_offset`. These exist only inside the static form of `processing` and have no agentic counterpart, so setting them would introduce a second experimental variable.

**Recorded but not controlled:** the model's internal sampling, adaptive frame rate and resolution decisions, and its navigation behavior. These are part of the treatment (§5), not confounds to be equalized.

Before any Gemini/API request, the harness diffs the two resolved request payloads of a pair. If the diff contains anything other than the `processing` value, no Gemini/API request is made and no model-quality evidence exists. The harness records a `PRE-FLIGHT` / `HARNESS` invariant failure containing the failed invariant, differing fields, timestamp, relevant configuration and run identifier, and `request_made = false`; it then blocks experiment execution until the configuration or harness is repaired. The failure record is retained rather than silently discarded.

## 5. Processing-mode distinction

The treatment is the processing mode **plus the behavior that mode inherently causes**.

- **STATIC** — fixed-rate frame extraction; all frames placed in context. Documented as the model default; set explicitly here regardless.
- **AGENTIC** — model-driven dynamic navigation; transcript, frames and audio loaded on demand; internal frame rate and resolution adapted by the API.

No attempt is made to equalize the internal behavior of the two modes. Doing so would either be impossible or would remove the thing being measured.

## 6. Test classification

| id | length | class |
|---|---|---|
| T001 | ~1 h | BENCHMARK |
| T002 | ~2 h | BENCHMARK |
| T003 | ~3 h | BENCHMARK |
| T004 | ~4 h | STRESS |

`test_class` is a required field in every test spec, every trial record, and every report row.

T004 is a capability and limit probe, not a BENCHMARK aggregate observation. Static success on T004 is not assumed — the documented static ceiling is below 4 hours, and no agentic duration ceiling is documented at all (`docs/API_VERIFICATION.md` item 12).

## 7. Repetition counts

| test | class | STATIC | AGENTIC |
|---|---|---|---|
| T001 | BENCHMARK | 3 | 3 |
| T002 | BENCHMARK | 3 | 3 |
| T003 | BENCHMARK | 3 | 3 |
| T004 | STRESS | 1 | 1 |

`repeats` is an explicit recorded config value. The harness never adjusts it — not for quota, not for elapsed time, not for convenience. Changing it is a contract revision (§22).

Quota context: the free tier is documented at 8 hours of YouTube video input per day, and whether repeated submissions of the same URI each consume the full duration is unverified. Worst case this suite is ~44 video-hours, so multi-day execution is expected and planned for. The schedule bends around the quota; the design does not.

## 8. Counterbalanced arm order

Within each test, arm order alternates across repeats:

| repeat | order |
|---|---|
| 1 | STATIC → AGENTIC |
| 2 | AGENTIC → STATIC |
| 3 | STATIC → AGENTIC |

T004 (single repeat) uses STATIC → AGENTIC.

The realized order is recorded per pair. Counterbalancing reduces systematic order effects and prevents arm identity from being permanently confounded with first-vs-second execution. Caching, backend drift, queueing, network conditions and temporal variation may still affect observations; none is assumed to favor the second call.

## 9. Paired-run timing

Both arms of a pair execute in the same session window, target **≤ 30 minutes apart**. Actual elapsed separation is recorded. A pair exceeding the target is flagged, not discarded.

Each `test_id` / `repeat_id` defines one `pair_id`, and **the pair is the primary matched comparison unit**. Primary latency comparisons use the within-pair difference and/or within-pair ratio. Absolute latency is still recorded and shown, but cross-day absolute latency comparisons carry an explicit caveat because backend load, network conditions, routing and queueing may differ.

Token and quality measurements may be summarized across the pre-registered repetitions. Every observation and summary keeps visible its `test_id`, `repeat_id`, `pair_id`, execution date/time and arm. Token metrics are not treated as having the same network confounding as latency. No statistical-significance claim is permitted (§20).

## 10. Raw-response-first persistence

For every API attempt that returns an SDK response, in this order:

1. Serialize the complete SDK response object — all steps, all content, status, errors, and the **entire usage object as-is**, never a hand-picked subset — and write it to disk.
2. Write the answer text exactly as returned: unedited, uncleaned, unformatted, untrimmed.
3. Only then parse anything or derive any metric.

For an exception with no SDK response, the raw error and attempt record are persisted before classification or retry; no response or answer artifact is fabricated. A preflight invariant failure makes no API attempt and follows §4.

Also recorded per trial: the request payload actually sent plus its sha256; `test_class`; `outcome`; `video_duration_s`; `submitted_at`; latency (§15); SDK version, Python version, OS; the requested and returned model ids; and for failures, the full exception type, message, HTTP status and request id.

Parsers read from the written file, never from an in-memory object. If the process dies between the API returning and the parse, the raw evidence still exists.

## 11. Evidence immutability

- Every trial attempt gets its own directory. Nothing is ever overwritten.
- When a run is formally closed as complete, partial or abandoned, a freeze step writes `MANIFEST.sha256` over an explicit immutable **source-evidence scope**. The manifest does not hash itself and does not implicitly cover every file later added to the run directory.
- The source-evidence scope contains every artifact required to reconstruct each recorded trial or preflight failure, as applicable to its outcome: run configuration; contract revision and hash; resolved request payload and its hash; trial and attempt metadata; raw API response; exact returned answer text; raw error evidence; retry and attempt records; SDK, runtime and environment provenance; and frozen truth/rubric hashes or provenance references.
- Nothing covered by the frozen evidence manifest may later be overwritten. Scoring verifies the manifest before consuming source evidence; a missing or mismatched hash blocks scoring and requires human review.
- Blind packets, provisional evaluator outputs, human score/approval files, reports, visualizations and other derived summaries are post-freeze derived artifacts outside the source-evidence manifest. Producing them after source-evidence freeze does not invalidate that manifest.
- No trial is deleted — not failures, not refusals, not quota errors, not unfavorable answers.
- If a run is abandoned for a harness defect, its directory stays in the repository with a file naming the reason. History is never rewritten.

## 12. Ground-truth freeze

- Ground truth is authored **from the video alone**, before any model output exists for that test.
- It is hash-locked and committed **before** the first scored trial for that test. The harness refuses to run a scored trial against an unlocked or hash-mismatched truth file.
- The question mix per test declares its ratio of global-comprehension to localized-timestamp questions in advance, so the suite is not unconsciously weighted toward navigation-favoring queries.
- The rubric, including the timestamp tolerance, is frozen at the same time.

Anything added after the freeze is labeled EXPLORATORY and reported separately from the pre-registered result.

## 13. Blind evaluation protocol

1. After source-evidence freeze and manifest verification, one blind packet is built per paired repeat containing only `RESPONSE_A`, `RESPONSE_B`, the questions, the frozen ground truth and the rubric. The blind comparison units are:

   ```text
   T001/R1 → RESPONSE_A vs RESPONSE_B
   T001/R2 → RESPONSE_A vs RESPONSE_B
   T001/R3 → RESPONSE_A vs RESPONSE_B
   T002/R1 → RESPONSE_A vs RESPONSE_B
   T002/R2 → RESPONSE_A vs RESPONSE_B
   T002/R3 → RESPONSE_A vs RESPONSE_B
   T003/R1 → RESPONSE_A vs RESPONSE_B
   T003/R2 → RESPONSE_A vs RESPONSE_B
   T003/R3 → RESPONSE_A vs RESPONSE_B
   T004/R1 → RESPONSE_A vs RESPONSE_B
   ```

2. A/B assignment is independently randomized for every paired repeat with a recorded nonce. The mapping is recorded in a sealed key outside both the blind packet and the evaluator-visible blind directory. One mapping must not be reused for all repeats of a test.
3. STATIC and AGENTIC labels remain concealed until provisional scoring is written. The packet contains **quality evidence only**. Tokens, latency, retries, navigation counts, step counts and all other machine metrics are excluded — they would de-anonymize the arms and are measured directly anyway (§15).
4. The evaluator is given only the blind directory, in a context with no run history.
5. Per response, per question, the evaluator emits a verdict — `CORRECT` / `PARTIAL` / `INCORRECT` / `UNSUPPORTED` / `NOT_ANSWERED` — and identifies the frozen ground-truth item or required answer component. For `CORRECT`, `PARTIAL`, `INCORRECT` and `UNSUPPORTED`, the evaluator records the relevant exact response evidence span wherever applicable. For `NOT_ANSWERED`, `evidence_span = null` is allowed and the evaluator must identify the question, the frozen ground-truth item or required answer component, and what the response failed to address. An empty response is validly classifiable as `NOT_ANSWERED`; no quotation may be fabricated merely to satisfy the schema. A `NOT_ANSWERED` verdict does not convert `REFUSED_LIMIT` into a numeric quality score (§17).
6. Timestamps count as correct only within the frozen tolerance of **±2.0 s**, measured against player time from 0.
7. Ambiguity is marked `NEEDS_HUMAN_REVIEW` with its reason. The evaluator may not resolve ambiguity by preference.
8. Un-blinding happens only after provisional scores are written, and the un-blinding is timestamped and recorded.

Known limitation, stated rather than solved: blinding here is procedural. Response length, formatting and timestamp-citation habits can leak arm identity to any evaluator. This must be disclosed in any published result.

## 14. Human authority over scores

Score files carry:

```json
{
  "proposed_score": { },
  "proposed_by": "claude-opus-5",
  "proposed_at": "<iso>",
  "human_status": "PENDING",
  "final_score": null,
  "human_note": null,
  "approved_by": null,
  "approved_at": null
}
```

- `human_status` ∈ `PENDING` | `APPROVED` | `REJECTED` | `NEEDS_HUMAN_REVIEW`, defaulting to `PENDING`.
- `final_score` defaults to `null` and is set only by a human.
- **No Claude, Sol, evaluator or harness code path writes `final_score` or sets `human_status` to `APPROVED`.** The guarantee is structural: that code does not exist.
- Reports print proposed scores labeled `PROVISIONAL — NOT HUMAN APPROVED`, and refuse to print any headline verdict while any test is unapproved.
- Machine metrics (§15) are reported regardless of approval status; they carry no judgment.
- Any `NEEDS_HUMAN_REVIEW` blocks the aggregate verdict until the human resolves it.

## 15. Measurements

**Quality** — human-judgeable only, from the blind protocol (§13): answer correctness, timestamp correctness, unsupported/hallucinated claims, coverage.

**Efficiency** — read directly from the recorded usage object, never inferred:

| Measure | Field |
|---|---|
| input tokens | `total_input_tokens` |
| media tokens | `input_tokens_by_modality` entries for `video` and `audio` |
| thought tokens | `total_thought_tokens` |
| tool-use tokens | `total_tool_use_tokens`, `tool_use_tokens_by_modality` |
| output tokens | `total_output_tokens` |
| cached tokens | `total_cached_tokens` |
| total tokens | `total_tokens` |

**Latency** — `time.monotonic()` around the API call only, plus ISO-8601 start and end. Setup and teardown are excluded and that exclusion is stated. Latency is the least trustworthy metric here: it includes upload, queueing and regional routing, and is reported with that caveat.

**Agentic navigation** — counted from typed entries in the response `steps` array: `processing_call` steps (the model requesting a video segment or audio transcript, identified by `id`) paired to `processing_result` steps (linked by `call_id`). Prose in the answer describing navigation is **never** counted as evidence of navigation.

**Agentic token accounting — DOCUMENTED EXPECTATION, RUNTIME OBSERVATION PENDING.** Current official Google Video Understanding documentation maps Agentic navigation reasoning to `total_thought_tokens`, and transcript, frame and audio loads made by Agentic navigation to `total_tool_use_tokens`. This is an expected top-level accounting relationship, not proof of what any particular trial returns. The harness persists the complete returned usage object, reports the fields actually present, preserves null or unavailable fields, and never estimates missing counts, infers missing buckets or back-computes token values by subtraction. Fine-grained attribution to individual `processing_call` steps remains unverified unless the API exposes it directly.

**Provenance rule.** Every derived metric names its raw source (e.g. `raw_response.json:usage.total_thought_tokens`). A metric with no raw source is recorded as `null` with `UNAVAILABLE`. Documented expectations never replace the recorded runtime usage object.

## 16. Retry and failure taxonomy

Failures are classified before anything is retried.

| Class | Examples | Policy |
|---|---|---|
| `TRANSPORT` | network error, 5xx, timeout | retry ≤ 3 with backoff; every attempt recorded |
| `QUOTA` | free-tier daily limit, rate limit, 429 | **infrastructure failure, never a quality failure.** No same-day retry. Recorded as `FAILED_QUOTA` and rescheduled to a later day as a new recorded attempt. Never counted against the model. |
| `LIMIT` | input rejected for duration, size or context | **not retried.** `outcome = REFUSED_LIMIT` (§17). This is the finding. |
| `CONTENT` | refusal, empty answer, safety block, truncated or malformed output | **not retried.** Scored as-is — this is the model's behavior. |
| `HARNESS` | our own defect, preflight invariant violation, config mismatch | before any request, record `PRE-FLIGHT` failure with `request_made = false`; otherwise preserve available raw evidence; abort, fix, restart under a new run id; the abandoned run is kept with its reason recorded |

Rules:

- Every attempt gets its own directory; nothing is overwritten.
- Every retry appends a record: timestamp, class, reason, raw error, attempt number.
- Retry budget is symmetric. If one arm needed retries and its partner did not, the pair is flagged `RETRY_ASYMMETRY` → `NEEDS_HUMAN_REVIEW`, because retries change latency and cost comparisons.
- Exhausted retries produce a recorded `FAILED` trial that appears in the report. A failure is a result.
- An error that cannot be confidently classified is recorded raw and marked `NEEDS_HUMAN_REVIEW` rather than guessed into a bucket. Misclassifying a quota error as a model-quality failure is the specific outcome this guards against.
- No quota error may be escaped by enabling billing or initiating paid usage without explicit human authorization.

## 17. `REFUSED_LIMIT` semantics

When an arm rejects an input on a documented or runtime limit:

- `outcome = REFUSED_LIMIT`
- `quality_score = null`
- the full rejection payload is preserved verbatim
- the trial is **not** retried to obtain a nicer outcome

**A capability refusal is never converted into `quality_score = 0`.** Zero means "answered, and answered badly". A refusal means "did not answer". Recording one as the other fabricates a quality claim out of an infrastructure fact.

"AGENTIC completed T004 and STATIC refused it" — or the reverse — is a legitimate, reportable finding about capability, reported separately from any quality comparison.

## 18. No result-improving reruns

A trial may be re-executed **only** under the `TRANSPORT`, `QUOTA` or `HARNESS` classes of §16, and every such re-execution is recorded with its class and reason.

A trial is never re-run because:

- the answer was wrong, weak, short, or embarrassing;
- the model refused or produced nothing;
- the result favors the arm we expected to lose;
- a nicer number seems obtainable.

The first valid response for a given trial is the result.

## 19. Aggregate separation

`BENCHMARK` and `STRESS` results are **never merged into one aggregate**.

- Headline comparisons are computed over `BENCHMARK` trials (T001–T003) only.
- T004 appears in its own section, labeled as a limit probe with n=1 per arm, and is excluded from every median, spread and comparison in the benchmark section.
- Any report row, table or chart carries its `test_class`.

## 20. Reporting rules at n=3

- **List every individual observation.** Per-trial values are always shown, never only a summary, with `test_id`, `repeat_id`, `pair_id`, execution date/time and arm visible.
- For each BENCHMARK test, report **median plus full spread** (min–max) across its pre-registered repetitions per metric per arm. Token and quality measurements may be summarized this way. Primary latency comparisons use within-pair differences and/or ratios; absolute latency is also shown with the cross-day caveat in §9.
- **No statistical-significance claim.** No p-values, no confidence intervals, no "significantly better". At n=3 on a single video per length, the honest verb is "observed".
- Scope every claim to its evidence: "on this video, under these settings, we observed…". No scaling laws from four length points; four videos, one per length, confounds length with content, and that is stated.
- Report the tradeoff shape rather than a manufactured winner.
- Partial execution is reported as partial execution, naming what did not run and why.

## 21. Explicit unknowns and the runtime-evidence boundary

Established from documentation and the installed SDK; **not** established about a particular runtime response. Local SDK types establish what the client library constructs and sends. They do not establish what the server accepts or does. Runtime evidence controls every recorded trial result; documented expectations remain labeled as such rather than promoted to observations.

1. **Server acceptance of `resolution` together with each `processing` value.** Client-side validity is confirmed; server acceptance must be observed before scored execution.
2. **Agentic maximum video duration** — undocumented. Bears directly on T003 and T004.
3. **Agentic top-level token accounting — DOCUMENTED EXPECTATION, RUNTIME OBSERVATION PENDING.** Navigation reasoning is expected in `total_thought_tokens`; transcript, frame and audio loads are expected in `total_tool_use_tokens`. The complete runtime usage object controls what is actually recorded (§15).
4. **Per-`processing_call` token attribution** — not documented; only `id` is documented on the step.
5. **Whether repeated submissions of the same YouTube URI each consume the full daily allowance.**
6. **Free-tier RPM/TPM/RPD numeric limits** — not published in documentation; visible to the human in AI Studio. May bind before the video-hours limit does.
7. **Error code for non-spend quota exhaustion** — undocumented; classification must key on observed status *and* message.
8. **Documentation/SDK discrepancy on static clipping offsets** — the documented example passes integers, the SDK types declare `"10.5s"`-style strings. Concerns fields this contract does not set; recorded so neither form is treated as verified.
9. **Recorded discrepancy on per-frame token tiers.** `docs/API_VERIFICATION.md` item 3 records one set of per-frame figures from the developer guide; a later human cross-check reported a different tier structure. This contract depends on neither: `resolution` is locked identically across arms for reproducibility (§4), so no result turns on the figure. Flagged for human resolution rather than silently reconciled.

Where documentation and observed runtime behavior conflict, the raw runtime evidence is preserved and the discrepancy is escalated to the human. It is never silently resolved in either direction.

## 22. Contract-change procedure

Once this contract is frozen, **no material experimental invariant may change silently.**

Material invariants include: the subject model, the two arms and their distinguishing key, the locked request fields and their values (including `resolution = "low"`), repetition counts, arm ordering, test classification, the retry taxonomy, `REFUSED_LIMIT` semantics, the blind protocol, the human-approval gate, and the reporting rules.

To change one, before any new scored evidence is produced:

1. **Document** the proposed change in a new revision section appended to this file.
2. **State why** the existing contract cannot be followed — what evidence or constraint makes it unworkable.
3. **Obtain explicit human approval.** No revision takes effect without it.
4. **Increment the revision** (REV 2, REV 3, …) with its date, so the change is identifiable at a glance.

Then:

- Evidence already produced keeps the `contract_rev` it was produced under. It is never re-tagged, re-scored under new rules, or deleted.
- Results produced under different revisions are never silently merged; any report spanning revisions says so.
- History is never rewritten and frozen evidence is never mutated.

Typos, clarifications and formatting that do not alter a material invariant may be corrected in place without a revision bump, provided the correction changes no experimental meaning.
