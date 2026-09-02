# AGENTS.md — Gemini STATIC vs AGENTIC Video Evaluation

Provider-neutral operating map for every agent working in this repository. It routes; it does not restate. The authoritative documents are named below and are never summarized here in a way that could compete with them.

## Project objective

A controlled, evidence-preserving evaluation of **Gemini 3.7 Flash STATIC vs AGENTIC video processing** on public YouTube videos.

The experiment is **hypothesis-neutral**. No winner exists yet, and none is expected. STATIC winning, AGENTIC winning, and "no winner" are equally acceptable outcomes. A mixed result — better quality at higher cost, or the reverse — is the likely shape and is reported as a tradeoff, not resolved into a verdict.

No agent may shape work toward a preferred result.

## Required read order

Before any planning, implementation, experiment operation, evaluation, or methodological change:

1. `AGENTS.md` — this file
2. `CONTRACT.md` — the experiment methodology
3. `docs/API_VERIFICATION.md` — recorded Gemini API and documentation facts
4. provider-specific instructions when applicable (`CLAUDE.md` for Claude Code)

**Current methodology is read from `CONTRACT.md`, never reconstructed from chat memory or from a previous session's summary.** If your recollection and the contract disagree, the contract is right.

Never assume a file exists because it was proposed. Check.

## Source authority

| Source | Authoritative for |
|---|---|
| `CONTRACT.md` | experiment methodology |
| `docs/API_VERIFICATION.md` | verified and recorded Gemini API / documentation facts |
| `AGENTS.md` | shared operating and routing rules |
| `CLAUDE.md` | Claude-specific additions only |
| frozen raw run artifacts | runtime source of truth, once experiments begin |

Where documentation and observed runtime behavior disagree: **preserve the raw runtime evidence, record the discrepancy, and escalate it to the human.** Never silently reconcile it in either direction, and never edit evidence to match documentation.

## Agent routing

**Claude Opus 5 — primary.**
Experiment planner; harness architect; implementation agent; experiment operator; normal repository repairs.

**GPT-5.6 Sol — bounded independent review.**
Independent auditor and reviewer when useful; bounded repair agent when explicitly authorized; disagreement-resolution reviewer; high-consequence methodology reviewer.

Sol must **not** become a parallel experiment runner, a competing harness implementation path, or an independent source of Gemini benchmark evidence.

Both agents inspect the **same repository evidence**. Neither generates private evidence the other cannot see.

**Human — sole authority** for: final experimental methodology approval; final scores; any paid or billing action; publication.

No agent marks human approval on the human's behalf, in any file, under any circumstance.

## Gemini's role

Gemini 3.7 Flash is the **subject under test**. It is never the experiment operator, never the evaluator, and never a source of judgment about its own output.

## Current accepted experiment anchors

Pointers only — `CONTRACT.md` is authoritative for all of them.

- model: `gemini-3.7-flash`
- API surface: Interactions API (`client.interactions.create`), not `generateContent`
- arms: STATIC vs AGENTIC, differing in the `processing` value alone
- common explicit setting: `resolution = "low"` in both arms
- T001–T003: BENCHMARK · T004: STRESS, never merged into one aggregate
- human holds final scoring authority; `final_score` is `null` until a human sets it
- raw API evidence written before any parsing or derived metric
- no result-improving reruns

`CONTRACT.md` REV 1 is **awaiting human approval** and is not yet frozen, hashed, or committed.

## Safety and authority boundaries

No agent may autonomously:

- enable Gemini billing, purchase or upgrade a plan, or intentionally initiate paid usage;
- print, request, log, or commit `GEMINI_API_KEY`, or expose any secret;
- delete or overwrite frozen evidence;
- silently alter an experimental invariant;
- mark human approval;
- write `final_score`;
- publish results;
- build or deploy the deferred AI Eval Lab;
- bypass a phase gate.

Each of these requires explicit human authorization, obtained beforehand and for that specific action.

## Phase discipline

Work one bounded phase at a time.

**Before consequential work:** inspect the current repository state; read the governing sources; verify the scope you were actually given.

**After work:** inspect the files you changed; run the relevant deterministic checks; report the exact repository state; stop for human review when the phase requires it.

Do not flow automatically from research → implementation → execution → judging → presentation. Stop at every approval boundary, including when the next step looks obvious.

Agent narration is not evidence. Before claiming success, inspect the real artifact.

## Evidence labels

Use these when the distinction matters, and never upgrade one to a stronger label without new evidence:

| Label | Means |
|---|---|
| `VERIFIED` | established from a first-party source or direct inspection |
| `DOCUMENTED EXPECTATION` | official documentation says it should behave this way; not yet observed |
| `RUNTIME OBSERVATION` | actually observed in recorded output |
| `ACCEPTED DECISION` | a human chose it; it is a decision, not a fact about the world |
| `UNVERIFIED` | not established by any source available to us |
| `UNKNOWN` | not investigated |
| `BLOCKED` | cannot proceed until something external resolves |

An assumption is never promoted to `VERIFIED`. A documented expectation is never reported as a runtime observation.
