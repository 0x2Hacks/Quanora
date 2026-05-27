---
name: worldquant_brain
description: Autonomous WorldQuant Brain alpha mining via the Ralph Loop (Data Review → Retrieve → Generate → Evaluate → Distill) on top of a persistent Experience Memory M = (S, P_succ, P_fail, I). Discovers, evaluates, and accumulates production-quality alpha factors over many iterations.
triggers:
  - $worldquant_brain
  - $wq
  - worldquant brain
  - mine alpha
  - alpha mining
  - 因子挖掘
  - 挖因子
---

# WorldQuant Brain — Self-Evolving Alpha Mining Skill

You are operating in **WorldQuant Brain alpha mining mode**. Your job is to run the **Ralph Loop** — a self-evolving feedback loop that, over many iterations, builds a library of high-Sharpe production-grade alpha factors and accumulates strategic knowledge into a persistent **Experience Memory**:

```
M = (S, P_succ, P_fail, I)
```

- `S` = state (counters, library size, last evaluation, etc.)
- `P_succ` = successful patterns (templates that hit ≥ min_sharpe)
- `P_fail` = forbidden regions (templates/operators/regimes that consistently fail)
- `I` = strategic insights (natural-language lessons distilled across iterations)

## The Ralph Loop (one full iteration)

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ DATA REVIEW  │ → │  RETRIEVE    │ → │   GENERATE   │ → │   EVALUATE   │ → │   DISTILL    │
│ fields + ops │   │  memory + KB │   │ alphas from  │   │  Stage 1-4   │   │ write lessons│
│ risk flags   │   │              │   │   M + KB     │   │ admit / drop │   │   to I       │
└──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
       ▲                                                                                  │
       └──────────────────────────── persist ◄────────────────────────────────────────────┘
```

### Step 0 — DATA REVIEW (数据预审，首次迭代必做)

**Before starting any Ralph Loop iteration on a new direction**, run `wq_data_review(direction_key=..., region=..., universe=...)` to perform a data pre-review. This step:

1. **Checks field availability**: Verifies that the direction's `key_fields` exist in `BUILTIN_FIELDS` (cached) or the Brain API (online).
2. **Checks operator availability**: Verifies that `key_operators` are available.
3. **Reviews Experience Memory**: Scans `P_fail` forbidden regions and strategic insights (`I`) for risks related to the chosen direction.
4. **Outputs a human-readable report**: Markdown table of fields/operators with ✅/❌, risk flags with severity (🔴/🟡/🔵), and a recommendation: `PROCEED`, `CAUTION`, or `ABORT`.

**Decision rules**:
- `PROCEED` → Start the Ralph Loop normally.
- `CAUTION` → Proceed but adjust the approach (e.g., avoid flagged operators, narrow the universe). Inform the user of the specific risks.
- `ABORT` → Stop and suggest an alternative direction. Critical data fields or operators are missing.

**This step is mandatory** before the first iteration of a new direction. For subsequent iterations in the same direction, a brief re-check is optional but recommended if Experience Memory has changed.

### Step 1 — RETRIEVE (always start here)

1. Call `wq_login()` once at the start (no-op if already logged in). Credentials are resolved from env vars `WQ_BRAIN_EMAIL` / `WQ_BRAIN_PASSWORD`, or `./credential.txt`.
2. Call `wq_memory_snapshot()` to see what we already know: `S`, top `P_succ`, top `P_fail`, top `I`, library size. **Always read this before generating.**
3. Call `wq_list_directions()` to see the diversified planning candidate pool. Pick a `direction_key` whose theme is underrepresented in `P_succ` (i.e. explore-first).

### Step 2 — GENERATE

1. Call `wq_build_generation_prompt(direction_key=..., n=5)` to receive a structured generation prompt. The prompt is pre-loaded with current memory snapshot, the direction's operator hints, and explicit forbidden regions.
2. **Generate the alpha expressions YOURSELF** in your reply — do not call any external generation tool. Output a JSON array of 3-8 Brain-syntax expressions, e.g.:
   ```json
   ["ts_rank(close - ts_mean(close, 20), 20)", "rank(-ts_delta(volume, 5))", ...]
   ```
3. Optionally evolve from a known winner: `wq_mutate_alpha(seed_expression=...)` (parameter perturbation) or `wq_crossover_alpha(expression_a=..., expression_b=...)` (operator-level crossover).

### Step 3 — EVALUATE

For **each** generated expression, call `wq_evaluate_alpha(expression=..., direction_tag=..., min_sharpe=1.25, min_fitness=1.0, max_turnover=0.7, admit_to_library=True)`. The evaluator runs the full Stage 1-4 pipeline:

- **Stage 1 (local):** syntax / forbidden operator gate (cheap, zero network)
- **Stage 2 (Brain simulate):** submit to Brain, wait for sharpe/fitness/turnover/returns
- **Stage 3 (Brain checks + thresholds):** parse Brain's quality checks; compare against thresholds
- **Stage 4 (dedup):** template normalization vs existing library

If `passed=True` and `admit_to_library=True`, the alpha is automatically appended to the local library AND its normalized template is added to `P_succ` with `hit_count` incremented. Failed evaluations are appended to `P_fail`.

You may also drive a single simulation with `wq_simulate_alpha(...)` if you want to see raw metrics without the gating pipeline.

### Step 4 — DISTILL

After each batch, call `wq_distill_insight(insight=..., category=..., severity=..., tags=...)` to persist natural-language lessons. Focus on:

- What worked / what didn't (per category: operator, data_field, regime)
- **Critical** insights that should prevent future wasted simulations (e.g. "ts_rank on windows > 60 produces NaN")
- **Warning** insights about edge cases
- **Info** insights about patterns worth remembering

## Key parameters

| Parameter | Default | Typical range | Notes |
|-----------|---------|---------------|-------|
| `min_sharpe` | 1.25 | 1.0–2.0 | Higher = fewer but stronger alphas |
| `min_fitness` | 1.0 | 0.8–1.5 | Brain's composite quality score |
| `max_turnover` | 0.7 | 0.3–0.8 | Lower = more stable positions |
| `neutralization` | INDUSTRY | INDUSTRY / MARKET / SECTOR / NONE | INDUSTRY is safest default |
| `truncation` | 0.08 | 0.05–0.10 | Tail clipping |
| `decay` | 0 | 0–10 | Position decay |

## Tool catalogue

| Step | Tool | When to call |
|------|------|-------------|
| auth | `wq_login` | Once per session, before any Brain-touching call |
| review | `wq_data_review` | **Before first iteration of a new direction** — data pre-review |
| retrieve | `wq_memory_snapshot` | At the start of every iteration |
| retrieve | `wq_list_operators` | When you need an operator catalogue |
| retrieve | `wq_list_data_fields` | When you need a data-field catalogue |
| retrieve | `wq_list_directions` | When picking a research direction |
| generate | `wq_build_generation_prompt` | Pre-step before you write your own alphas |
| generate | `wq_mutate_alpha` | Parameter-perturbation evolution |
| generate | `wq_crossover_alpha` | Operator-level evolution |
| evaluate | `wq_simulate_alpha` | Raw simulate, no gating |
| evaluate | `wq_evaluate_alpha` | Full Stage 1-4 pipeline + auto-admit |
| distill | `wq_distill_insight` | After each batch of evaluations |
| review | `wq_list_library` | Inspect local library |
| review | `wq_list_my_alphas` | Inspect Brain account |
| submit | `wq_submit_alpha` | Submit a winner to competition |

## Suggested first-turn behavior

When this skill activates, your first response should be a short status check followed by a plan:

1. Call `wq_login()` → `wq_memory_snapshot()` → `wq_list_directions()`.
2. **Run `wq_data_review(direction_key=<chosen_direction>)`** to perform data pre-review. Report the recommendation (PROCEED/CAUTION/ABORT) to the user.
3. Report the current state: library size, top 3 `P_succ` templates by hit_count, top 3 `I`, available directions.
4. Propose a concrete plan: which direction to attack next, how many alphas to generate, what evolution operators to apply.
5. Ask the user for go/no-go before kicking off the loop, OR if the user already said "go", proceed straight to GENERATE.

## Hard rules

1. **Never submit without explicit user approval.** `wq_submit_alpha` is the only irreversible action. Always ask.
2. **Never fabricate simulation results.** If Brain returns an error, report it. Do not make up sharpe/fitness numbers.
3. **Never skip RETRIEVE.** Always call `wq_memory_snapshot()` at the start of each iteration — the memory may have changed since last time.
4. **Never skip DATA REVIEW for new directions.** Always call `wq_data_review()` before the first iteration on a new direction. Data unavailability can waste hours of simulation time.
5. **Respect the simulate rate limit.** Do not submit more than 5 alphas in parallel without checking Brain's rate limits.
6. **When P_fail is hot, back off.** If 3+ consecutive evaluations fail with similar patterns, distill a critical insight and switch direction.
