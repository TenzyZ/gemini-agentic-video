# API Verification — Gemini STATIC vs AGENTIC Video Benchmark

Pre-implementation verification gate for the approved evaluation contract.

- **Verification date:** 2026-09-02
- **Verified by:** Claude Opus 5 (experiment operator), from official Google documentation only
- **Authoritative sources:** `ai.google.dev` (Gemini API docs), `blog.google` (Google announcement)
- **Rule applied:** anything not established verbatim by an official Google source is marked `UNVERIFIED`. No API field has been invented. Vendor performance claims are labeled as claims, not as verified behavior.
- **Status of this file:** blocking gate. Harness implementation may not begin until this file is reviewed by the human.

Legend: `CONFIRMED` = stated in official Google documentation. `PARTIAL` = partly documented, with a named gap. `UNVERIFIED` = not established by official documentation.

---

## Correction Log

Corrections are recorded rather than applied silently.

**2026-09-02 — correction pass 1** (human cross-check against official sources, two items corrected):

1. **A1 corrected from `UNVERIFIED — blocking` to `CONFIRMED`.** The original pass fetched the September 1, 2026 announcement but did not request its code blocks, so the YouTube + agentic example on that page was missed. The example was re-fetched and verified verbatim before this correction was applied. Consequence: the blocker is removed and no API probe is needed for this question.
2. **Item 5 corrected.** The original pass concluded that `media_resolution` should be dropped from the locked set. The video-understanding guide in fact states explicitly that `media_resolution` and `processing` are independent and can both be set on the same video input. Compatibility is CONFIRMED; only the exact Interactions API field syntax remains UNVERIFIED. Consequence: inclusion is **deferred pending syntax confirmation**, not removed.

**2026-09-02 — SDK inspection pass** (read-only inspection of the installed `google-genai` package; no network call, no API key read, nothing installed or upgraded):

3. **Item 5b resolved to CONFIRMED.** The installed SDK's generated Interactions types establish the exact field, placement and value set. Headline: on the Interactions surface the field is named **`resolution`**, not `media_resolution`. Item 5 as a whole moves from PARTIAL to CONFIRMED.
4. **Item 3's open sub-question resolved.** The bare object form `{"type": "static"}` with no sub-fields is valid in the SDK type, as is the bare string `"static"`. No fallback path is needed.
5. **Item 12(a) updated** to reflect that media resolution is now controllable, which makes the static ceiling a choice rather than an unknown.

**2026-09-02 — cross-agent synchronization pass** (documentation only; no API call, no network experiment):

6. **Item 10's agentic token-accounting sub-item moved from `UNVERIFIED` to `DOCUMENTED EXPECTATION — RUNTIME OBSERVATION PENDING`.** Official Video Understanding documentation maps navigation reasoning to `total_thought_tokens` and on-demand frame/audio/transcript loads to `total_tool_use_tokens`. Item 10's overall status stays CONFIRMED — the counters themselves were never in doubt. Per-`processing_call` attribution remains UNVERIFIED. The runtime-evidence boundary is unchanged: documentation states an expectation, the recorded usage object states the fact.

---

## Summary Table

| # | Item | Status |
|---|---|---|
| 1 | exact model id | CONFIRMED |
| 2 | exact Interactions API request schema | CONFIRMED |
| 3 | STATIC / default processing behavior | CONFIRMED |
| 4 | AGENTIC `processing` field | CONFIRMED |
| 5 | supported common media settings | CONFIRMED (5b resolved from installed SDK 2026-09-02) |
| 6 | actual response / usage field names | CONFIRMED |
| 7 | `interaction.steps` | CONFIRMED |
| 8 | `processing_call` | CONFIRMED |
| 9 | `processing_result` | CONFIRMED |
| 10 | exposed token counters | CONFIRMED |
| 11 | public YouTube limitations | CONFIRMED |
| 12 | context / video-duration limits per mode | PARTIAL — agentic undocumented |
| 13 | Free Tier daily YouTube-input limit | CONFIRMED |
| 14 | how repeated submissions of same URI count | UNVERIFIED |
| A1 | AGENTIC processing combined with a **YouTube URI** | CONFIRMED (corrected 2026-09-02) |
| A2 | Free Tier RPM/TPM/RPD numeric limits | UNVERIFIED |
| A3 | error code for quota exhaustion | PARTIAL |

---

## Item 1 — Exact model id

**Status:** CONFIRMED

**Finding (verbatim):** Model id string is `gemini-3.7-flash`. Listed as `Stable: gemini-3.7-flash`, described as "Our previous-generation Flash model for complex coding, agentic workflows, and reliable multi-step execution." Model card: "Input token limit: 1,048,576", "Output token limit: 65,536", supported inputs "Text, Image, Video, Audio, and PDF", thinking levels "low, medium, high" with `minimal` documented to return an error.

Other Flash ids present on the models page (not used): `gemini-3.8-flash`, `gemini-3.6-flash`, `gemini-3.5-flash`, `gemini-3.5-flash-lite`.

**Sources:**
- https://ai.google.dev/gemini-api/docs/models
- https://ai.google.dev/gemini-api/docs/models/gemini-3.7-flash

**Implementation consequence:** pin `model = "gemini-3.7-flash"` exactly. Knowledge cutoff is not stated in the model card, so it is not recorded as a fact. The harness must record the model id echoed back in the response and flag `MODEL_MISMATCH` on any difference.

---

## Item 2 — Exact Interactions API request schema

**Status:** CONFIRMED

**Finding:** `POST https://generativelanguage.googleapis.com/v1beta/interactions`

Top-level request fields (verbatim from the reference): `model`, `agent`, `input` (required), `system_instruction`, `tools`, `response_format`, `stream`, `store`, `background`, `generation_config`, `agent_config`, `environment`, `labels`, `previous_interaction_id`, `safety_settings`, `service_tier`, `webhook_config`, `user_metadata`.

`input` accepts `Content | Content[] | Step[] | string`. Video is supplied as an input part object of `{"type": "video", ...}` with `uri` (File API uri or YouTube URL) or `data` + `mime_type`.

**Source:** https://ai.google.dev/api/interactions-api

**Implementation consequence:** the harness targets the Interactions API, not the legacy `generateContent` API. `store` / `background` / `stream` are left at defaults and recorded in `run_config.json`. `service_tier` is not set, since setting it could interact with quota behavior.

---

## Item 3 — STATIC / default processing behavior

**Status:** CONFIRMED

**Finding (verbatim):** Static is "the default for all models". Frames are "extracted at 1 FPS and placed into context"; video is "stored at 1 frame per second (FPS) and audio processed at 1Kbps (single channel)". Documented as "Best for short clips or when every frame matters". Documented caveat: 1 FPS sampling may "miss details in videos with rapid motion or quick scene changes".

Static token cost (verbatim): "approximately 300 tokens per second at default resolution, or 100 tokens per second at low resolution"; "66 tokens per frame" (low) or "258 tokens per frame" (default), plus "32 tokens per second" audio.

**Sources:**
- https://ai.google.dev/gemini-api/docs/interactions/video-understanding
- https://ai.google.dev/gemini-api/docs/video-understanding

**Implementation consequence:** the STATIC arm may be expressed either by omitting `processing` (the documented default) or by setting it explicitly. **Recommendation: set it explicitly** (`{"type": "static"}`) so the recorded request payload states the arm rather than relying on a default holding. The bare object form `{"type": "static"}` with no sub-fields is **valid in the installed SDK** — `StaticMediaProcessingParam` requires only the constant `type`, with `fps` / `start_offset` / `end_offset` all `NotRequired` — and the bare string `"static"` is equally valid via `ProcessingEnum`. See item 5b. No fallback path is needed; the harness sets the static arm explicitly.

---

## Item 4 — AGENTIC `processing` field

**Status:** CONFIRMED

**Finding:** `processing` is a key **inside the video input part object**, sibling to `type` / `uri` / `mime_type` — not in `generation_config`. Verbatim documented forms:

```python
interaction = client.interactions.create(
    model="gemini-3.7-flash",
    input=[
        {
            "type": "video",
            "uri": video_file.uri,
            "mime_type": video_file.mime_type,
            "processing": "agentic"
        },
        {"type": "text", "text": "What are the three main arguments presented?"}
    ]
)
```

```python
            "processing": {
                "type": "static",
                "start_offset": 1200,
                "end_offset": 1500,
            },
```

```python
            "processing": {
                "type": "static",
                "fps": 0.5,
            },
```

Supported models (verbatim): "Gemini 3.7 Flash, 3.6 Flash, and 3.5 Flash Lite models also support agentic video understanding". Documented behavior: "The model dynamically navigates the video, loading transcript and/or frames and/or audio on demand"; the model "dynamically explores the video timeline, selectively inspecting transcripts and adaptively adjusting frame rates and resolution on the fly based on the prompt".

**Sources:**
- https://ai.google.dev/gemini-api/docs/interactions/video-understanding
- https://ai.google.dev/gemini-api/docs/video-understanding
- https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-agentic-video-in-gemini/

Input sources: agentic processing is documented for both File API uploads and YouTube URIs — see A1.

**UNVERIFIED sub-items:** whether an object form `{"type": "agentic", ...}` exists; whether agentic accepts any sub-fields (for example a navigation or step budget). Only the bare string `"agentic"` is documented.

**Implementation consequence:** the experimental variable is exactly this one key. `fps`, `start_offset` and `end_offset` are documented **only inside the static form** — see item 5.

---

## Item 5 — Supported common media settings

**Status:** CONFIRMED *(5b resolved 2026-09-02 from the installed SDK; this item was previously PARTIAL)*

**Finding:**

Split into three questions, because they were established from different evidence.

**5a — Capability and compatibility with `processing`: CONFIRMED.**

Verbatim: "The `media_resolution` and `processing` parameters are independent: you can set both on the same video input."

Also verbatim: "Gemini 3 introduces granular control over multimodal vision processing with the `media_resolution` parameter"; "The `media_resolution` parameter determines the maximum number of tokens allocated per input image or video frame. Higher resolutions improve the model's ability to read fine text or identify small details, but increase token usage and latency."

This establishes that `media_resolution` is a genuinely **common** setting: it is not static-only, and setting it does not conflict with either arm's `processing` value. It is therefore a legitimate candidate for the locked set.

**5b — Exact Interactions API field syntax and location: CONFIRMED** *(resolved 2026-09-02 from the installed SDK; previously UNVERIFIED)*

Official documentation still shows no code example — not on the video-understanding page, not on the interactions video-understanding page, not on the interactions image-understanding page — and no such field appears in the documented `GenerationConfig`. The question is instead settled by the **generated type definitions in the installed first-party SDK**, which are authoritative for what the client library will send.

**Installed SDK:** `google-genai` **2.21.0** (`C:\Users\hp\AppData\Roaming\Python\Python314\site-packages\google\genai`), Python 3.14.5. Nothing was installed, upgraded or called.

**Finding — on the Interactions surface the field is named `resolution`, not `media_resolution`.**

Local source: `google/genai/_gaos/types/interactions/videocontent.py`

```python
class VideoContentParam(TypedDict):
    r"""A video content block."""

    data: NotRequired[Union[str, Base64FileInput]]
    mime_type: NotRequired[VideoContentMimeType]
    name: NotRequired[str]
    processing: NotRequired[ProcessingParam]
    r"""How the model processes this video for understanding."""
    resolution: NotRequired[MediaResolution]
    type: Literal["video"]
    uri: NotRequired[str]
```

Runtime confirmation of the model fields: `['data', 'mime_type', 'name', 'processing', 'resolution', 'type', 'uri']`.

| Question | Answer |
|---|---|
| exact Python field name | `resolution` |
| placement | a key on the **video content block** inside `input`, sibling to `type` / `uri` / `processing` |
| accepted value type | `MediaResolution = Union[Literal["low", "medium", "high", "ultra_high"], UnrecognizedStr]` (`_gaos/types/interactions/mediaresolution.py`) |
| serialized wire key | `resolution` — `VideoContent.serialize_model` emits `f.alias or n`, and no alias is declared |
| in Interactions `generation_config`? | **No.** `GenerationConfig` fields are `image_config`, `max_output_tokens`, `seed`, `speech_config`, `stop_sequences`, `thinking_level`, `thinking_summaries`, `tool_choice`, `transcription_config`, `video_config`. No resolution field of any name. |
| does `interactions.create()` accept `generation_config`? | Yes — `createmodelinteraction.py`, `generation_config: NotRequired[GenerationConfigParam]`. It is simply not where resolution lives. |

**Relationship to `processing` (same file):**

```python
ProcessingEnum = Union[Literal["static", "agentic"], UnrecognizedStr]
Processing = TypeAliasType("Processing", Union[MediaProcessing, ProcessingEnum])
```

`processing` and `resolution` are independent optional siblings on the same `VideoContent` object. No validator, discriminator or type constraint links them, so `resolution` is settable identically whether `processing` is `"static"`, `"agentic"`, or absent. This matches the documented statement in 5a.

`MediaProcessing` resolves to `StaticMediaProcessing` (`staticmediaprocessing.py`), whose fields are `end_offset`, `fps`, `start_offset` — all `NotRequired` — and a constant `type: Literal["static"]`. **There is no agentic object form**: agentic is expressible only as the bare string `"agentic"`. This also confirms item 3's open sub-question — `{"type": "static"}` with no sub-fields is valid, as is the bare string `"static"`.

**Naming caution for future sessions:** `media_resolution` *is* a real field name, but on the **generateContent** surface — `google/genai/types.py`, class `Part`, `media_resolution: Optional[PartMediaResolution]` with a nested `level` of `MEDIA_RESOLUTION_LOW|MEDIUM|HIGH|ULTRA_HIGH`, alongside a sibling `media_processing: Optional[MediaProcessing]` enum. That is a different API surface with a different field name and a different value shape. **This experiment uses the Interactions surface: the field is `resolution` and the values are lowercase short strings.** Do not carry the `generateContent` spelling across.

**Scope limit — what the SDK does not establish:** the generated types show what the client library will construct and serialize. They do **not** establish that the server accepts any particular combination, nor what it does with it. Server behavior remains runtime evidence, to be recorded from the first real responses, never assumed from the type definitions.

**Minor discrepancy observed, recorded not resolved:** the documented static-clipping example passes integers (`"start_offset": 1200`), while the SDK types declare `start_offset` / `end_offset` as `str` in the `"10.5s"` form. This concerns fields the benchmark deliberately does not set, so it does not affect the design. Recorded here so a future session does not treat either form as verified.

**5c — `fps`, `start_offset`, `end_offset`: CONFIRMED but static-only.**

Documented **only as sub-fields of `processing` with `"type": "static"`**. There is no documented agentic equivalent.

**Sources:**
- https://ai.google.dev/gemini-api/docs/video-understanding
- https://ai.google.dev/gemini-api/docs/interactions/video-understanding
- https://ai.google.dev/gemini-api/docs/interactions/image-understanding
- https://ai.google.dev/api/interactions-api

**Implementation consequence.** The approved contract locks a "common media-resolution setting where supported and applicable to both". That setting exists (5a), is applicable to both arms, and its exact syntax is now established (5b). It therefore **enters the locked set** rather than being deferred or dropped.

- `fps`, `start_offset` and `end_offset` remain excluded: static-only, so setting them would introduce a second experimental variable with no agentic counterpart.
- `resolution` is **locked identically across both arms**, set explicitly rather than left to a default, so the recorded request payload states it. The value is a human decision (see the recommendation below); whatever is chosen must be byte-identical in both arms of a pair and recorded in `run_config.json`.

Locked set for implementation: model, video URI, prompt, `resolution`, generation parameters (including `thinking_level` and `thinking_summaries`), SDK version, ground truth, rubric. The only intended difference between arms remains the `processing` key.

**Recommendation: option A — LOCK `resolution` identically for STATIC and AGENTIC, at `"low"`.**

Reasoning, strictly from established evidence: `resolution` is a genuinely common, controllable, documented-independent setting, which is exactly what the contract wants locked; leaving it unset would hand control of a token- and ceiling-determining variable to an undocumented default that could differ per processing mode, reintroducing the confound the contract exists to remove. `"low"` specifically, because the documented static ceiling at low resolution is 3 hours versus 1 hour at high — that is the only setting under which T002 and T003 are within documented static reach at all, so it gives the STATIC arm its fairest run and keeps the benchmark class meaningful.

This is a configuration decision, so it is the human's to freeze. It must be frozen before the first scored trial, since changing it mid-suite makes earlier and later runs incomparable.

---

## Item 6 — Actual response / usage field names

**Status:** CONFIRMED

**Finding:** Interaction resource fields: `id`, `object`, `status` (`in_progress | requires_action | completed | failed | cancelled | incomplete | budget_exceeded | queued`), `created`, `updated`, `model`, `agent`, `steps`, `input`, `environment_id`, `errors`.

`usage` object:

```
usage: {
  input_tokens_by_modality: ModalityTokens[]
  output_tokens_by_modality: ModalityTokens[]
  cached_tokens_by_modality: ModalityTokens[]
  tool_use_tokens_by_modality: ModalityTokens[]
  grounding_tool_count: GroundingToolCount[]
  total_input_tokens: integer
  total_output_tokens: integer
  total_cached_tokens: integer
  total_thought_tokens: integer
  total_tool_use_tokens: integer
  total_tokens: integer
}
```

`ModalityTokens`: `modality` (`text | image | audio | video | document`), `tokens` (integer).

**Source:** https://ai.google.dev/api/interactions-api

**Implementation consequence:** the harness still serializes the entire response and usage object verbatim; the reporter maps these documented names and prints `UNAVAILABLE` for any that are absent. Field names are documented, but **their presence on a given call is not guaranteed by documentation** — presence is a runtime fact, recorded, never assumed.

---

## Item 7 — `interaction.steps`

**Status:** CONFIRMED

**Finding:** `steps` (`Step[]`, optional) on the Interaction resource. Documented step types include: `model_output`, `user_input`, `function_call`, `function_result`, `code_execution_call`, `code_execution_result`, `file_search_call`, `file_search_result`, `google_search_call`, `google_search_result`, `google_maps_call`, `google_maps_result`, `url_context_call`, `url_context_result`, `mcp_server_tool_call`, `mcp_server_tool_result` — plus `processing_call` / `processing_result` (items 8–9).

**Source:** https://ai.google.dev/api/interactions-api

**Implementation consequence:** navigation and processing behavior (contract objective 9) is measured by counting typed entries in `steps`. Prose in the answer describing navigation is never counted as evidence of navigation.

---

## Item 8 — `processing_call`

**Status:** CONFIRMED

**Finding (verbatim):** "Agentic processing adds two new step types to the `steps` array: `processing_call`: the model requested a video segment or audio transcript, identified by `id`." It also appears in the API reference as a streaming `StepDeltaData` type carrying an optional `signature` and a fixed `type` discriminator.

**Sources:**
- https://ai.google.dev/gemini-api/docs/interactions/video-understanding
- https://ai.google.dev/api/interactions-api

**UNVERIFIED:** the full field list of a non-streaming `processing_call` step — for example whether the requested time range or modality is exposed. The documentation names only `id`.

**Implementation consequence:** count `processing_call` steps as the navigation-call metric. Whether we can report *which* segments were fetched is unknown until first observed. Record raw, report only what is present.

---

## Item 9 — `processing_result`

**Status:** CONFIRMED

**Finding (verbatim):** "`processing_result`: the result of that load, linked by `call_id`. These appear interleaved with `thought` steps (when summaries are enabled) and precede the final `model_output` step." It also appears as a streaming `StepDeltaData` type.

**Sources:** as item 8.

**Implementation consequence:** pair `processing_call.id` with `processing_result.call_id` to derive per-call navigation. Thought summaries are documented as conditional ("when summaries are enabled"), so the harness must record whether summaries were enabled and must use the same setting for both arms.

---

## Item 10 — Exposed token counters

**Status:** CONFIRMED

**Finding:** all of the contract's token objectives map to documented fields:

| Contract objective | Documented field |
|---|---|
| input tokens | `total_input_tokens` |
| media tokens | `input_tokens_by_modality[modality="video"].tokens` (and `audio`) |
| thought tokens | `total_thought_tokens` |
| tool-use tokens | `total_tool_use_tokens` / `tool_use_tokens_by_modality` |
| output tokens | `total_output_tokens` |
| cached tokens | `total_cached_tokens` |
| total tokens | `total_tokens` |

**Source:** https://ai.google.dev/api/interactions-api

**Agentic token accounting — DOCUMENTED EXPECTATION, RUNTIME OBSERVATION PENDING** *(updated 2026-09-02; previously recorded as wholly UNVERIFIED)*

Current official Google Video Understanding documentation maps agentic behavior to top-level counters as follows:

| Agentic behavior | Expected counter |
|---|---|
| navigation reasoning | `total_thought_tokens` |
| frames / audio / transcript loaded on demand | `total_tool_use_tokens` |

This is a **documented expectation about top-level accounting**, not evidence about what any particular trial returns. It is not a runtime observation and must never be presented as one.

**Still UNVERIFIED:** fine-grained attribution of tokens to an individual `processing_call` step. No official documentation establishes it, and it remains unverified unless the API exposes it directly at runtime.

**Source:** https://ai.google.dev/gemini-api/docs/video-understanding

**Implementation consequence:** contract objectives 4–7 are answerable from documented fields. The evidence boundary is unchanged and binding:

- documentation describes the *expected* accounting; the recorded runtime usage object controls what is actually reported;
- the harness persists the complete returned usage object and reports the fields actually present;
- a field that is absent or null is reported as `null` / `UNAVAILABLE`;
- **never** infer a missing value, estimate a missing bucket, or back-compute a token count by subtraction;
- a documented expectation never substitutes for a recorded value, and a runtime result contradicting the expectation is a valid finding to record and escalate, not to reconcile.

Aligned with `CONTRACT.md` §15 and §21.3.

---

## Item 11 — Public YouTube limitations

**Status:** CONFIRMED

**Finding (verbatim):** "For the free tier, you can't upload more than 8 hours of YouTube video per day. For the paid tier, there is no limit based on video length. For models prior to Gemini 2.5, you can upload only 1 video per request. For Gemini 2.5 and later models, you can upload a maximum of 10 videos per request. You can only upload public videos (not private or unlisted videos)."

Additional documented caveats: the YouTube URL feature is "in preview"; "Use only one video per prompt request for optimal results".

**Source:** https://ai.google.dev/gemini-api/docs/interactions/video-understanding

**Implementation consequence:** all four benchmark videos must be public. One video per request matches the design. "In preview" is a stability risk to record in the run config, since feature behavior may change mid-benchmark.

---

## Item 12 — Context and video-duration limits per mode

**Status:** PARTIAL

**Finding (verbatim):** "Models with a 1M context window can process videos up to 3 hours long by default (at low media resolution), or up to 1 hour long at high media resolution." `gemini-3.7-flash` has a 1,048,576-token input limit, so it is a 1M-context model.

**No maximum video duration is documented for agentic processing.** The announcement describes effectiveness as "especially pronounced on long-form video (from 10-minute how-to guides to 90-minute lectures and multi-hour recordings)" but states no absolute maximum. Whether agentic can exceed the static 1 h / 3 h ceilings is **UNVERIFIED**.

**Sources:**
- https://ai.google.dev/gemini-api/docs/interactions/video-understanding
- https://ai.google.dev/gemini-api/docs/models/gemini-3.7-flash
- https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-agentic-video-in-gemini/

**Implementation consequence — contract correction required.** Against the documented static ceiling:

| test | length | static feasibility per documentation |
|---|---|---|
| T001 | ~1 h | within the 1 h high-resolution ceiling; within 3 h low-resolution |
| T002 | ~2 h | exceeds the 1 h high-resolution ceiling; within 3 h low-resolution |
| T003 | ~3 h | at the documented 3 h low-resolution ceiling |
| T004 | ~4 h | **exceeds every documented static ceiling** |

Two consequences:

(a) Which static ceiling applies — 1 h or 3 h — depends on `resolution`, which item 5b now establishes as settable and lockable. With `resolution="low"` the documented static ceiling is 3 h, so T001–T003 are within documented static reach and only T004 exceeds it. With a high setting the ceiling drops to 1 h and a STATIC `REFUSED_LIMIT` would become plausible from T002 onward. This is now a **choice we control and record**, not an unknown — which is the main reason to lock it (item 5).

(b) T003 sits exactly at the documented 3 h ceiling even in the favourable case, so it arguably belongs in the STRESS class alongside T004. Recommend the human either reclassify T003, or accept a STATIC limit-refusal there as an expected and legitimate outcome. No separate duration probe is proposed — the first recorded T002 pair answers this as ordinary run evidence.

---

## Item 13 — Free Tier daily YouTube-input limit

**Status:** CONFIRMED

**Finding (verbatim):** "For the free tier, you can't upload more than 8 hours of YouTube video per day."

**Source:** https://ai.google.dev/gemini-api/docs/interactions/video-understanding

**Implementation consequence:** the 8 h/day figure in the approved contract is now CONFIRMED rather than REPORTED. The worst-case budget stands at approximately 44 video-hours (36 benchmark + 8 stress), so **≥ 6 execution days** before retries. Free tier is documented as "Free of charge" for input, output (including thinking tokens), and context caching on this model.

---

## Item 14 — How repeated submissions of the same URI count toward the daily limit

**Status:** UNVERIFIED

**Finding:** no official documentation establishes whether re-submitting the same YouTube URI on the same day consumes the daily 8-hour allowance each time, once, or partially (for example via context caching). Nothing in the video-understanding, rate-limits, or pricing documentation addresses it.

**Sources checked:**
- https://ai.google.dev/gemini-api/docs/interactions/video-understanding
- https://ai.google.dev/gemini-api/docs/rate-limits
- https://ai.google.dev/gemini-api/docs/pricing

**Implementation consequence:** plan for the worst case, that every submission counts fully. Do **not** reduce `repeats` to fit an unverified assumption. The harness records `video_duration_s` and `submitted_at` per trial so the actual consumption rate can be inferred from observed quota errors — and that inference is labelled as our experimental inference, never as documented behavior.

---

## A1 — AGENTIC processing combined with a YouTube URI (additional finding)

**Status:** CONFIRMED — *corrected 2026-09-02; previously and incorrectly recorded as UNVERIFIED / blocking*

**Finding (verbatim):** "The feature is available today for video uploads and YouTube videos via the Gemini API."

The September 1, 2026 announcement carries a Python example combining `gemini-3.7-flash`, a public YouTube URI, and `"processing": "agentic"` in a single video input part:

```python
from google import genai

client = genai.Client()

interaction = client.interactions.create(
    model="gemini-3.7-flash",
    input=[
        {
            "type": "video",
            "uri": "https://youtu.be/7Z5Vy9JBANs",
            "processing": "agentic"
        },
        {
            "type": "text",
            "text": "What are the 3 most important announcements in this keynote?",
        },
    ],
)

print(interaction.output_text)
```

Note that this example supplies no `mime_type` alongside a YouTube URI, matching the YouTube examples in the developer guide.

**Source:** https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-agentic-video-in-gemini/ (published 2026-09-01, code block re-fetched and verified verbatim 2026-09-02)

**Why the original pass got this wrong:** the announcement was fetched in the original pass, but the extraction prompt asked only for duration limits, performance claims and supported models — it did not request code blocks, so the YouTube + agentic example was never surfaced. The developer-guide pages, taken alone, genuinely do not show the combination, which is what the original finding reflected. The error was one of incomplete extraction, not of the source.

**Implementation consequence:** a public YouTube URI can be used directly with `processing: "agentic"` in the Gemini Interactions API. The planned paired STATIC vs AGENTIC YouTube benchmark therefore does **not** require switching to File API uploads merely to obtain agentic support, and no API probe is required for this question. This is **no longer a blocker**. Quota accounting stays on the YouTube path (items 13–14).

---

## A2 — Free Tier numeric rate limits (additional finding)

**Status:** UNVERIFIED

**Finding:** the rate-limits documentation does not publish Free Tier RPM/TPM/RPD values. Verbatim: "Rate limits depend on a variety of factors (such as your usage tier) and can be viewed in Google AI Studio." Also documented: rate limits apply per project rather than per API key; RPD quotas reset at midnight Pacific time; "To transition from the Free tier to a paid tier, you must first set up billing in AI Studio."

**Source:** https://ai.google.dev/gemini-api/docs/rate-limits

**Implementation consequence:** a requests-per-day limit may bind before the 8 h/day video limit does. The live limits are visible in AI Studio for this project, so establishing them is a human read of that page, not a documentation lookup. Until then, request-count feasibility is unknown. Third-party forum figures were found and are deliberately **not** used.

---

## A3 — Error code for quota exhaustion (additional finding)

**Status:** PARTIAL

**Finding (verbatim):** "If you hit a spend-based rate limit, the API returns a `429 RESOURCE_EXHAUSTED` error." The error code returned for non-spend-based quota exhaustion — such as the daily YouTube-hours limit — is not documented.

**Source:** https://ai.google.dev/gemini-api/docs/rate-limits

**Implementation consequence:** the harness classifies failures by observed status **and** message, and any unclassifiable error is recorded raw and marked `NEEDS_HUMAN_REVIEW` rather than guessed into the `QUOTA` or `LIMIT` bucket. Misclassifying a quota error as a model-quality failure is the specific outcome this guards against.

---

## A4 — Vendor performance claims (recorded, not verified)

These are Google's claims about the feature under test. They are the hypotheses this benchmark exists to check independently and must never be cited as findings of ours.

- "up to 88% fewer tokens for long-form content" / "token consumption by up to 88%"
- "reduce analysis costs by up to 66%"
- "improving accuracy by up to 7%"
- "navigation may slightly increase Time to First Token (TTFT) on short clips (less than 5 minutes) due to internal reasoning and tool round-trips before generation begins"

**Sources:**
- https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-agentic-video-in-gemini/
- https://ai.google.dev/gemini-api/docs/interactions/video-understanding

**Implementation consequence:** the TTFT note is a documented latency confounder. All four planned videos are far longer than 5 minutes, so it should not apply, but latency results must reference it. No claim above is pre-registered as an expected result, and an observation contradicting any of them is a valid finding.

---

## Source Index

| Source | Retrieved |
|---|---|
| https://ai.google.dev/gemini-api/docs/interactions/video-understanding | 2026-09-02 |
| https://ai.google.dev/gemini-api/docs/video-understanding | 2026-09-02 |
| https://ai.google.dev/api/interactions-api | 2026-09-02 |
| https://ai.google.dev/gemini-api/docs/models | 2026-09-02 |
| https://ai.google.dev/gemini-api/docs/models/gemini-3.7-flash | 2026-09-02 |
| https://ai.google.dev/gemini-api/docs/rate-limits | 2026-09-02 |
| https://ai.google.dev/gemini-api/docs/pricing | 2026-09-02 |
| https://ai.google.dev/gemini-api/docs/interactions/image-understanding | 2026-09-02 |
| https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-agentic-video-in-gemini/ | 2026-09-02 |

**Local first-party evidence** (SDK inspection pass, 2026-09-02) — read-only, no network request, no API key accessed, nothing installed or upgraded:

| Local source | Used for |
|---|---|
| `google-genai` **2.21.0**, Python 3.14.5, `…\site-packages\google\genai` | installed version |
| `google/genai/_gaos/types/interactions/videocontent.py` | `resolution` and `processing` fields on the video content block |
| `google/genai/_gaos/types/interactions/mediaresolution.py` | allowed value set |
| `google/genai/_gaos/types/interactions/staticmediaprocessing.py`, `mediaprocessing.py` | static object form, absence of an agentic object form |
| `google/genai/_gaos/types/interactions/generationconfig.py` | absence of any resolution field in `GenerationConfig` |
| `google/genai/_gaos/types/interactions/createmodelinteraction.py` | `generation_config` accepted by `interactions.create()` |
| `google/genai/_gaos/types/interactions/content.py` | `VideoContent` is part of the `input` content union |
| `google/genai/types.py` (class `Part`) | contrast: the `generateContent` surface's differently-named `media_resolution` |

The announcement page carries a publication date of **2026-09-01**. The developer-documentation pages do not display publication or last-updated dates, so only the retrieval date is recorded for them.

**URL re-check, correction pass 2026-09-02:** all nine URLs above were re-requested in this pass and returned live content. The announcement page and the video-understanding guide were re-fetched in full for the two corrections; the remaining seven were re-checked for reachability and continued presence of the cited sections.

No third-party source was used for any finding. Developer-forum results were encountered and deliberately excluded.
