# Task-Profile Model Selection — Design

**Date:** 2026-10-12
**Status:** Approved, pending implementation plan
**Revision:** 2 — reworked after spec review found the tier design silently changed the
meaning of `accuracy`, and that the proposed data loader cannot read Phase 2/3 files.

## Problem

The benchmark can rank models overall but cannot answer "which model should I use for
*this* activity." Two separate defects block it.

### 1. The accuracy suite is saturated

Measured across 51 scored models in `results/`:

| Category | Models at exactly 100% | Distinct values across fleet |
|---|---|---|
| coding | 27 / 51 | 9 |
| math | 30 / 51 | 6 |
| multiple_choice | 41 / 51 | 4 |
| instruction | 24 / 51 | 7 |

Ten models tie at 100% overall. `phi4:latest` and `qwen3.8:latest` both score
100/100/100/100.

A picker built on this data cannot discriminate. Asked for the best coding model it
would find 27 models tied at 100% and fall through to "whichever is fastest" — a
defensible deployment choice, but it measures speed among models that cleared a low
bar, not coding ability. `multiple_choice` is effectively dead weight at four distinct
values.

The remedy is harder tasks inside existing categories, not more categories.

### 2. Recommendations are hardcoded

`_reportUseCaseGuide()` in `static/app.js` derives six fixed cards from five numbers
per model (`score`, `tps`, `coding`, `inst`, `math`) using inline heuristics such as
"best agentic = whichever model scored `inst === 100`". Activities cannot be added
without editing rendering code, and nothing is queryable by a program.

## Goals

- Discriminate between top-tier models within a category.
- Define activities as data, in one place, consumed by both UI and API.
- Expose selection programmatically so agent spin-ups can query it.
- Report honestly when an activity's capability is unmeasured, rather than inferring
  it from unrelated scores.

## Non-goals

- Scoring creative quality subjectively. A later `creative` category will score
  verifiable craft constraints (rhyme scheme, syllable range, section tags, theme
  adherence), not artistic merit. Out of scope here.
- LLM-as-judge grading. Deferred until judge reliability is itself measured.
- Changing the composite score, tier groupings, or any existing displayed figure. This
  is now a hard constraint, enforced by the field design below rather than merely
  intended.

---

## Unit A — Difficulty tiers

Independently shippable and testable. Touches scoring only; no API or UI change.

### The field-meaning constraint

Hard tasks go *inside* existing categories, so a naive implementation changes what
`accuracy` means: a model scoring `8/8 = 100%` becomes `11/12 = 91.7%` with no change
in ability. Because the fleet is re-scored incrementally, the heatmap and accuracy
table would then show core-only and blended figures side by side with nothing
distinguishing them, and the top-level `accuracy` shift would move every composite
score and tier assignment.

**Therefore `accuracy` is defined as core-tasks-only, at both levels.** It keeps
exactly the value it has today, permanently. The hard tier is purely additive.

```json
"accuracy": 96.9,            // core tasks only - unchanged meaning, unchanged value
"hard_accuracy": 58.3,       // new, absent until re-scored
"has_hard_tier": true,       // provenance marker
"by_category": {
  "coding": {
    "accuracy": 100.0,       // core only
    "passed": 8, "total": 8, // core only, matching today's shape
    "hard_accuracy": 75.0,
    "hard_passed": 3, "hard_total": 4
  }
}
```

This makes every existing reader correct by construction rather than by inspection:

| Reader | Location | Effect |
|---|---|---|
| Accuracy tab table | `static/app.js:471` | None — same values |
| Report assembly → heatmap, use-case guide | `static/app.js:759-762` | None |
| `/api/results/combined` → scatter plot | `dashboard.py:765,783` | None |
| CLI table print | `accuracy_bench.py:261` | None |
| Composite → tier cards | `_COMPOSITE` / `_TIER_OF` | None — `accuracy` stable |

`has_hard_tier` exists so Unit B can report "hard tier not yet measured" for a given
model instead of silently falling back to the core score and producing a confident
wrong answer.

### Task definition

Add `difficulty: str = "core"` to `AccuracyTask` in `accuracy_prompts.py`. Its current
fields are `id, category, prompt, scorer, expected, tests` with all trailing fields
defaulted, so appending a defaulted field is safe. The existing 32 tasks need no edit.

**Committed counts: 4 hard tasks per category, 16 total, suite grows 32 → 48.** Four is
the floor for usable granularity — a single hard task makes `hard_accuracy` a
0%-or-100% coin flip, reproducing the exact defect this unit exists to fix.

Hard tasks must remain objectively auto-scorable with existing scorers, earning
difficulty from edge cases and multi-step reasoning rather than subjective judgement.
Representative examples:

| Category | Hard task | Why top models fail it |
|---|---|---|
| coding | `merge_intervals` where `[1,2],[2,3]` must merge to `[1,3]` | Touching-but-not-overlapping is widely mishandled |
| coding | `eval_expr("3+4*2")` without `eval()` | Requires real precedence handling |
| math | Population grows 8%/yr from 25000 — first whole year above 40000 | Needs iteration or logs, not one operation |
| math | 3 red / 5 blue, draw 2 without replacement, P(same colour) as `a/b`, give `a+b` | Multi-step probability with a reduction step |
| multiple_choice | "Which is NOT true about Python's GIL" with plausible distractors | Current MC distractors are obviously wrong |
| instruction | JSON with exactly keys `a,b,c` where `c` is 3 integers summing to 10, no prose | Multiple interacting constraints |

### Aggregation sites

Tier aggregation is duplicated across **three** sites, all of which must be updated or
cloud-scored and bench-scored models will silently lack tier keys:

1. `accuracy_llamacpp.py:170` — local llama.cpp path
2. `accuracy_llamacpp.py:209` — cloud path (duplicate logic, same file)
3. `accuracy_bench.py:127` — separate Ollama-based bench, own copy

Extracting a shared `aggregate_by_category(task_results)` helper is preferred over
editing three copies, and removes the existing duplication between sites 1 and 2.

---

## Unit B — Selection engine, API, UI

Depends on Unit A only for `hard_accuracy` to be populated; builds and tests against
existing data without it.

### Data loading

`dashboard._merge_results(pattern)` iterates `data.get("results", [])` and keys on
`r["model_name"]`. Phase 2 and Phase 3 files have no `results` list — their top level
is `{model, engine, …, analysis}` — so `_merge_results` returns an **empty dict for
them, raising nothing**. Verified yields:

| Pattern | `_merge_results` yields |
|---|---|
| `results_phase1_*.json` | 54 models |
| `results_accuracy_*.json` | 54 models |
| `profile_*.json` (40 files) | **0** |
| `optimization_*.json` (40 files) | **0** |

A second loader is required: `_merge_single_model_results(pattern)`, keyed on
`data.get("model")`, factored out of the existing newest-per-model loops in
`get_phase2_results` / `get_phase3_results` (`dashboard.py:1126-1156`). All 40 Phase 2
`model` values match accuracy `model_name` values exactly, so no name normalisation is
needed.

### Handling absent and unmeasured data

The engine must treat missing data as unmeasured, never as zero and never as a
comparison against `None`. Verified hazards in live data:

| Hazard | Count | Required handling |
|---|---|---|
| `status` key absent | 51 / 54 | Absent means OK. Gate on explicit `error`/`too_large` only |
| `accuracy: None` | 3 / 54 | Skip gate, report model as unmeasured |
| `max_safe_context: None` | 1 / 40 | Skip that gate for the model |
| `tps` null or 0 | cloud proxies | Report unmeasured, not a low score |
| Vision models | — | Apply `_is_vision()` as both existing endpoints do |

Any gate evaluated against absent data excludes the model with reason
`"unmeasured: <signal>"`, which is distinguishable from
`"coding 50% < required 90%"`.

### Profiles

A new `task_profiles.py` holds every activity definition:

```python
PROFILES = {
    "coding": {
        "label": "Writing code",
        "requires": {"coding": 90},
        "weights": {"coding": 0.55, "instruction": 0.15, "speed": 0.30},
        "speed_cap": 80,
    },
    "agentic": {
        "label": "Agent spin-ups",
        "requires": {"instruction": 90},
        "weights": {"instruction": 0.50, "coding": 0.15, "speed": 0.35},
        "speed_cap": 80,
    },
    "lyrics":  {"label": "Music lyrics",   "status": "unmeasured",
                "needs_category": "creative"},
    "judging": {"label": "Judging output", "status": "unmeasured",
                "needs_category": "judging"},
}
```

No profile ships a `min_context` gate. `max_safe_context` has three distinct values
across 40 models — `16384` (37), `8192` (2), `None` (1) — so a `>= 8192` gate excludes
nobody while adding a crash path and the appearance of discrimination. The gate
*mechanism* is implemented and tested because the future `lyrics` profile will need
long-context filtering, but no current profile uses it.

`speed_cap: 80` matches the existing `_COMPOSITE` convention already shown in the
Report tab footer.

### Scoring

`select_best(activity)`:

1. Loads the model table via both loaders.
2. Short-circuits if the profile carries `status: "unmeasured"`, returning that status
   and the awaited category.
3. Applies `requires` as gates, collecting exclusions with reasons.
4. Scores survivors as the weighted sum of named signals, each normalised to 0–100.
   `speed` normalises as `min(tps / speed_cap, 1.0) * 100`.
5. Prefers `hard_accuracy` for a category when `has_hard_tier` is true, else uses
   `accuracy` and marks the result `"tier": "core"` so a pre-re-run answer is
   self-labelling.
6. Returns winner, runner-up, full ranking, and exclusions.

**Tie-breaking is on the main path, not an edge case** — 27 models tie at 100% coding
today. Deterministic order: weighted score desc, then `hard_accuracy` desc (absent
sorts last), then `tps` desc, then model name ascending.

### API

One call returns everything the UI needs, avoiding an N+1 fan-out:

- `GET /api/best-for` — every activity resolved.
- `GET /api/best-for/{activity}` — one activity.

```json
{
  "activity": "coding",
  "label": "Writing code",
  "tier": "core",
  "winner": { "model": "qwen2.5-coder:7b", "score": 87.3,
              "why": "100% coding (core only), 62 tok/s" },
  "runner_up": { "model": "deepseek-coder:33b-instruct-q4_K_M", "score": 81.0 },
  "ranking": [ { "model": "...", "score": 87.3 } ],
  "qualified": 7,
  "excluded": [ { "model": "gemma3:1b", "why": "coding 50% < required 90%" },
                { "model": "kimi-k3:cloud", "why": "unmeasured: accuracy" } ]
}
```

Unknown activity returns 404 listing valid names. An unmeasured activity returns 200
with `{"status": "unmeasured", "needs_category": "creative"}` — a known gap is not an
error.

### UI

Files that change, stated explicitly rather than claimed untouched:

- `_reportUseCaseGuide()` — rewritten to render from `GET /api/best-for` instead of
  inline heuristics. Its call contract changes from receiving a prepared array
  synchronously to being fetch-driven, so `renderReport()`'s call site changes too.
- `_reportHeatmap()` and the shared model-assembly block at `static/app.js:759-762` —
  gain `hard_accuracy` plumbing and an optional hard column per category, shown only
  where `has_hard_tier` is true.

Cards show winner, runner-up, the `why` string, a count of gate exclusions, and a
"core only" badge where the hard tier is not yet measured. Unmeasured profiles render
greyed with the category they await, so the gap is visible rather than silently absent.

---

## Testing

**Unit A**
- Tier aggregation: a mixed core/hard result yields core-only `accuracy` and separate
  `hard_accuracy`; a tier-less legacy record yields absent hard keys and
  `has_hard_tier: false`, never zeros.
- All three aggregation sites produce identical output for identical input.
- Each hard task is verified against a known-good and known-bad response, confirming
  the scorer separates them. **A hard task that every model passes or every model fails
  is worthless and must be replaced** — that is how `multiple_choice` reached four
  distinct values across 51 models.

**Unit B**
- Gates exclude with correct, distinguishable reasons; absent data yields
  `"unmeasured: <signal>"` and never a `TypeError`.
- Each verified hazard above has a regression test: absent `status`, `accuracy: None`,
  `max_safe_context: None`, `tps` of 0 and `None`, a vision model.
- Tie-breaking is deterministic across repeated runs on a fixture with ties.
- `_merge_single_model_results` returns 40 models for `profile_*.json`, guarding the
  silent-empty regression.
- Endpoints: every profile returns 200 against real `results/`; unknown activity 404s;
  pre-re-run answers carry `"tier": "core"`.

## Sequencing

1. **Unit A** — `difficulty` field, 16 hard tasks, shared `aggregate_by_category` across
   all three sites.
2. **Unit B** — loaders, `task_profiles.py`, `select_best`, unit tests on fixtures.
3. API endpoints.
4. Report tab rewiring.
5. Re-run accuracy across the fleet to populate `hard_accuracy` (machine time).

Steps 2–4 are verifiable before the re-run; answers self-label as `"tier": "core"`
until step 5 completes. Partial runs merge per model, so the fleet re-scores
incrementally without the core figures ever becoming incomparable.

## Risks

- **Hard tasks land saturated or impossible.** Mitigated by the per-task
  known-good/known-bad check; any task without spread across the fleet is replaced.
- **Weights encode the wrong priorities.** They live in one dict and are cheap to
  revise; the `why` string exposes the reasoning so a wrong answer is diagnosable.
- **Re-run cost.** 16 added tasks grow a full-fleet accuracy run by roughly half.
  Incremental per-model merging means it need not happen in one sitting.
