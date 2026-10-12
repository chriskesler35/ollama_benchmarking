# Task-Profile Model Selection — Design

**Date:** 2026-10-12
**Status:** Approved, pending implementation plan

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
- Replacing the composite score or tier groupings in the Report tab.

## Design

### Difficulty tiers

Add `difficulty: str = "core"` to `AccuracyTask` in `accuracy_prompts.py`. The existing
32 tasks become `core` unchanged — they remain a useful floor check for whether a model
functions at all. A new `hard` tier does the discriminating.

Hard tasks must still be objectively auto-scorable with the existing scorers. They earn
difficulty from edge cases and multi-step reasoning, not from subjective judgement.
Representative examples:

| Category | Hard task | Why top models fail it |
|---|---|---|
| coding | `merge_intervals` where `[1,2],[2,3]` must merge to `[1,3]` | Touching-but-not-overlapping is widely mishandled |
| coding | `eval_expr("3+4*2")` without `eval()` | Requires real precedence handling |
| math | Population grows 8%/yr from 25000 — first whole year above 40000 | Needs iteration or logs, not one operation |
| math | Bag of 3 red / 5 blue, draw 2 without replacement, P(same colour) as `a/b`, give `a+b` | Multi-step probability with a reduction step |
| multiple_choice | "Which is NOT true about Python's GIL" with plausible distractors | Current MC distractors are obviously wrong |
| instruction | JSON with exactly keys `a,b,c` where `c` is 3 integers summing to 10, no prose | Multiple interacting constraints |

Scoring gains a per-tier breakdown. `by_category.<cat>` keeps `accuracy` with its
current meaning and adds `core_accuracy` and `hard_accuracy`:

```json
"by_category": {
  "coding": { "accuracy": 91.7, "passed": 11, "total": 12,
              "core_accuracy": 100.0, "hard_accuracy": 75.0 }
}
```

`accuracy` stays the all-tasks figure, so existing consumers — the Report tab heatmap,
the scatter plot, `get_accuracy_results` — keep working untouched. A result file written
before this change simply lacks the tier keys; consumers must treat them as absent
rather than zero.

### Selection engine

A new `task_profiles.py` holds every activity definition:

```python
PROFILES = {
    "coding": {
        "label": "Writing code",
        "requires": {"coding": 90, "status": "ok"},
        "weights": {"coding": 0.55, "instruction": 0.15, "speed": 0.30},
        "speed_cap": 80,
    },
    "agentic": {
        "label": "Agent spin-ups",
        "requires": {"instruction": 90, "min_context": 8192},
        "weights": {"instruction": 0.50, "coding": 0.15, "speed": 0.35},
        "speed_cap": 80,
    },
    "lyrics":  {"label": "Music lyrics",  "status": "unmeasured",
                "needs_category": "creative"},
    "judging": {"label": "Judging output", "status": "unmeasured",
                "needs_category": "judging"},
}
```

`select_best(activity)` in the same module:

1. Builds the model table by reusing `dashboard._merge_results` over the phase 1,
   accuracy, phase 2 and phase 3 patterns.
2. Applies `requires` as gates, collecting each exclusion with its reason.
3. Scores survivors as the weighted sum of the named signals, each normalised to
   0–100. `speed` normalises as `min(tps / speed_cap, 1.0) * 100`, matching the
   convention already used by the Report tab's composite.
4. Prefers `hard_accuracy` for a category when present, falling back to `accuracy`.
5. Returns winner, runner-up, full ranking, and the excluded list.

Gates may reference accuracy categories, `speed`, `min_context` (from Phase 2
`analysis.max_safe_context`) and `status`. Phase 2 and Phase 3 data exist for 40 models
already, so context headroom is a usable signal rather than aspirational.

A profile carrying `status: "unmeasured"` short-circuits: the engine returns that status
and the category it awaits, and never guesses from unrelated scores.

### API

- `GET /api/profiles` — enumerates activities with labels and measured status.
- `GET /api/best-for/{activity}` — returns:

```json
{
  "activity": "coding",
  "label": "Writing code",
  "winner": { "model": "qwen2.5-coder:7b", "score": 87.3,
              "why": "100% core / 75% hard coding, 62 tok/s" },
  "runner_up": { "model": "deepseek-coder:33b-instruct-q4_K_M", "score": 81.0 },
  "qualified": 7,
  "excluded": [ { "model": "gemma3:1b", "why": "coding 50% < required 90%" } ]
}
```

Unknown activity returns 404 listing valid names. An unmeasured activity returns 200
with `{"status": "unmeasured", "needs_category": "creative"}` — a known gap is not an
error.

### UI

`_reportUseCaseGuide()` is rewritten to fetch `/api/profiles` and render one card per
profile from returned data, replacing the inline heuristics. Each card shows winner,
runner-up, the `why` string, and a count of models excluded by gates. Unmeasured
profiles render greyed with the category they await, so the gap is visible rather than
silently absent.

The heatmap gains an optional hard-tier column per category when tier data is present.

## Testing

- Unit: `select_best` against a fixture model table — gates exclude with correct
  reasons, weights produce expected ordering, ties break deterministically, an
  unmeasured profile short-circuits.
- Unit: tier aggregation — a result mixing core and hard tasks produces correct
  `core_accuracy` / `hard_accuracy`, and a tier-less legacy record yields absent keys
  rather than zeros.
- Each new hard task is verified end-to-end against a known-good and a known-bad
  response, confirming the scorer actually separates them. A hard task that every model
  passes or every model fails is worthless and must be replaced.
- Endpoint: all profiles return 200 against real `results/` data; unknown activity 404s.

## Sequencing

1. Difficulty tiers plus the hard task set, with tier aggregation in
   `accuracy_llamacpp.py`.
2. `task_profiles.py` and `select_best`, with unit tests against fixtures.
3. API endpoints.
4. Report tab rewiring.
5. Re-run accuracy across the fleet to populate hard scores (machine time).

Steps 2–4 work against existing data and can be verified before the re-run. The picker
only becomes genuinely discriminating after step 5.

## Risks

- **Hard tasks land saturated or impossible.** Mitigated by the end-to-end check in
  testing; any task with no spread across the fleet gets replaced.
- **Weights encode the wrong priorities.** They live in one dict and are cheap to
  revise; the `why` string exposes the reasoning so a wrong answer is diagnosable.
- **Re-run cost.** Adding roughly a dozen hard tasks grows a full-fleet accuracy run
  proportionally. Partial runs merge per model, so the fleet can be re-scored
  incrementally.
