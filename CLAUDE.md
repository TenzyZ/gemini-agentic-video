# Gemini STATIC vs AGENTIC Video Evaluation — Claude Code

@AGENTS.md

The import above carries the shared operating map: objective, read order, source authority, agent routing, safety boundaries, phase discipline, evidence labels. Read `CONTRACT.md` for methodology and `docs/API_VERIFICATION.md` for recorded API facts. This file adds only what is specific to Claude Code.

## Claude's role here

Read-only experiment researcher and planner, architecture/specification agent, independent PR/code auditor — and **later, a fresh-context provisional blind evaluator when explicitly authorized**. Claude is not the normal implementation agent or experiment operator.

- Claude proposes scores. Claude never finalizes one. `final_score` stays `null` until a human sets it, and no code path Claude writes may set it or mark `human_status: APPROVED`.
- When acting as evaluator, work from the blind packet **only**, in a fresh context with no run history. Do not open the sealed A/B key, do not consult run artifacts, and do not use prior repository context to infer arm identity.
- Ambiguity is marked `NEEDS_HUMAN_REVIEW` with its reason — never resolved by preference.

## Subagents

Do not spawn subagents unless the human asks for one. The one anticipated exception is the blind evaluation, where a fresh-context agent is the mechanism that makes blinding real — and even that runs only when the human authorizes that phase.

Any agent given a task here inherits the same boundaries; a delegated action is still an action taken by Claude.

## API key

When execution is eventually authorized, read `GEMINI_API_KEY` from the environment at the point of use. Never echo it into output, logs, error messages, committed files, or a subagent prompt.

## Accepted decisions Claude must not re-litigate

- **Media resolution — ACCEPTED DECISION.** The Interactions API video field is `resolution` (not `media_resolution`, which belongs to the `generateContent` surface). The experiment sets `resolution = "low"` explicitly in **both** arms. Established in `docs/API_VERIFICATION.md` item 5b; frozen in `CONTRACT.md` §4. Do not reopen it, and do not carry the `generateContent` spelling into an Interactions request.
- **Generation-config policy — ACCEPTED DECISION.** Scored pairs use `thinking_level = "medium"`, `thinking_summaries = "none"`, `max_output_tokens = 20000`, and a deterministic contract/test/repeat-derived seed. `max_output_tokens` remains a required explicit input.

## Deferred website

The private **AI Eval Lab** site is built only after evaluation completes and final human-approved scores exist. It is a read-only presentation layer over frozen artifacts; raw artifacts, manifests and Git history remain the source of truth, and the site never becomes the authoritative scoring store. Do not let anticipated site requirements shape the benchmark data model.

## Current project state

- `AGENTS.md`, `CLAUDE.md`, `CONTRACT.md` and `docs/API_VERIFICATION.md` exist.
- `CONTRACT.md` REV 1 is **HUMAN APPROVED — FROZEN**, hashed in `CONTRACT.sha256`, and committed. `CONTRACT.md` remains authoritative for methodology.
- `docs/API_VERIFICATION.md` has passed human review sufficiently to continue.
- Foundational Harness v1 exists; `harness.py`, `test_harness.py`, and `.gitignore` are tracked.
- The 44-test Foundational Harness v1 baseline passes; this policy phase extends the deterministic offline suite to 59 passing tests.
- No test videos have been selected.
- No ground truth or rubric has been locked.
- No Gemini experiment has run; no scored evidence exists.
- No final scores exist.
- Billing has not been authorized.

Keep this section accurate — it is the fastest way for a new session to know what has and has not happened.
