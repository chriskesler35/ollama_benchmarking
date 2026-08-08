# Local LLM Benchmark Report
**Hardware:** Dual RTX 3060 (12 GB each, 24 GB total VRAM) | **Models tested:** 28 | **Date:** 2026-06-17  
**Inference engine:** llama.cpp (tensor-split dual-GPU) — Ollama fallback for 4 models whose GGUFs lack llama.cpp metadata

---

## Composite Score Methodology

```
Score = (Accuracy% × 0.65) + (min(TPS / 80, 1.0) × 100 × 0.35)
```

- **65% Accuracy** (30-task suite: coding, math, multiple-choice, instruction-following)  
- **35% Speed** (tokens/sec, capped at 80 TPS — beyond that speed is rarely the bottleneck)  
- Phase 2 (context profiling) and Phase 3 (server optimization) not yet run — no context/parallel data available

---

## Full Ranked Table

| # | Model | Engine | TPS | Avg Latency | Accuracy | Coding | Math | M/C | Inst | **Score** |
|---|-------|--------|-----|-------------|----------|--------|------|-----|------|-----------|
| 1 | gemma3:latest | Ollama† | 75.9 | 1.1s | 96.7% | 100% | 100% | 100% | 83% | **96.1** |
| 2 | glm-4.7-flash:hf-q4km | llama.cpp | 75.4 | 1.7s | 96.7% | 88% | 100% | 100% | 100% | **95.9** |
| 3 | dolphin-llama3:8b-v2.9 | llama.cpp | 64.4 | 2.0s | 93.3% | 100% | 100% | 88% | 83% | **95.6** |
| 3 | dolphin-llama3:latest | llama.cpp | 64.3 | 2.0s | 93.3% | 100% | 100% | 88% | 83% | **95.6** |
| 5 | metal-muse-v2:latest | llama.cpp | 62.9 | 2.0s | 100.0% | 100% | 100% | 100% | 100% | **92.5** |
| 6 | qwen2.5-coder:7b | llama.cpp | 62.6 | 2.0s | 100.0% | 100% | 100% | 100% | 100% | **92.4** |
| 7 | llama3.1:latest | llama.cpp | 60.2 | 2.1s | 100.0% | 100% | 100% | 100% | 100% | **91.4** |
| 8 | upcycled-qwen-coder-v1:latest | llama.cpp | 62.6 | 2.0s | 96.7% | 100% | 88% | 100% | 100% | **90.3** |
| 9 | qwen3:0.6b | llama.cpp | 239.1 | 0.5s | 83.3% | 50% | 88% | 100% | 100% | **89.2** |
| 10 | dolphin-llama3:8b | llama.cpp | 63.9 | 2.0s | 93.3% | 100% | 100% | 88% | 83% | **88.6** |
| 11 | metal-muse-v1:latest | llama.cpp | 62.7 | 2.0s | 93.3% | 75% | 100% | 100% | 100% | **88.1** |
| 12 | llama3.1:8b | llama.cpp | 52.2 | 2.5s | 100.0% | 100% | 100% | 100% | 100% | **87.9** |
| 13 | qwen2.5:14b-instruct-q4_K_M | llama.cpp | 33.8 | 3.8s | 96.7% | 88% | 100% | 100% | 100% | **77.7** |
| 14 | mistral-nemo:12b-instruct-2407-q4_K_M | llama.cpp | 40.8 | 3.1s | 90.0% | 88% | 75% | 100% | 100% | **76.4** |
| 15 | qwen2.5-coder:14b | llama.cpp | 33.8 | 3.8s | 93.3% | 88% | 88% | 100% | 100% | **75.4** |
| 16 | gemma3:27b | Ollama† | 17.2 | 6.6s | 100.0% | 100% | 100% | 100% | 100% | **72.5** |
| 17 | qwen2.5-coder:32b-instruct-q4_K_M | llama.cpp | 15.8 | 8.1s | 100.0% | 100% | 100% | 100% | 100% | **71.9** |
| 17 | qwen2.5-coder:32b | llama.cpp | 15.8 | 8.1s | 100.0% | 100% | 100% | 100% | 100% | **71.9** |
| 19 | gemma4:31b-it-qat | llama.cpp | 17.0 | 7.5s | 96.7% | 88% | 100% | 100% | 100% | **70.3** |
| 20 | mistral-small3.2:24b | Ollama† | 21.0 | 6.1s | 93.3% | 100% | 88% | 100% | 83% | **69.8** |
| — | deepseek-coder:33b-instruct-q4_K_M | llama.cpp | 15.9 | 8.1s | 70.0% | 100% | 50% | 75% | 50% | **52.4** |
| — | tinyllama:1.1b | llama.cpp | 285.9 | 0.4s | 30.0% | 25% | 25% | 38% | 33% | **54.5** |
| — | glm-4.7-flash:latest ⚠️ | Ollama† | 63.8 | 2.0s | 30.0% | 0% | 13% | 88% | 17% | **47.4** |
| — | *upcycled-coder-v1:latest* | llama.cpp | 59.9 | 2.1s | 13.3% | 13% | 0% | 38% | 0% | **17.5** |
| — | *upcycled-coder-v2:latest* | llama.cpp | 60.0 | 2.1s | 6.7% | 25% | 0% | 0% | 0% | **16.7** |
| — | *travel-advisor:latest* ★ | llama.cpp | 21.4 | 6.0s | 3.3% | 0% | 0% | 13% | 0% | **8.5** |
| — | *ski-expert-v3:latest* ★ | llama.cpp | 60.1 | 2.1s | 0.0% | 0% | 0% | 0% | 0% | **0** |
| — | *travel-ai:latest* ★ | llama.cpp | 21.4 | 6.0s | 0.0% | 0% | 0% | 0% | 0% | **0** |

† Ollama fallback — GGUF missing metadata required by llama.cpp  
★ Domain-specific fine-tunes — scores not meaningful for general benchmarks (see Domain Models section)  
*Italics* = fine-tuned models expected to score low on general tasks

---

## Tier Breakdown

### S-Tier — Best All-Rounders (Score 90+)

**`gemma3:latest`** · Score 96.1 · 96.7% acc · 75.9 TPS  
The fastest high-accuracy model in the fleet. Runs via Ollama (llama.cpp can't load this GGUF), which costs a few TPS vs native, but still tops the chart. Perfect coding and math; one instruction-following fail keeps it from 100%. **Best single model to use when you want maximum throughput with near-perfect quality.**

**`glm-4.7-flash:hf-q4km`** · Score 95.9 · 96.7% acc · 75.4 TPS  
Essentially tied with gemma3 in composite. Runs natively on llama.cpp (unlike `:latest` which is the broken Ollama conversion at 30% accuracy). Perfect instruction-following and math. **Best for agentic pipelines that need fast, reliable tool-calling responses** — 100% on instruction format means it won't hallucinate tool call syntax.

**`dolphin-llama3:8b-v2.9` / `dolphin-llama3:latest`** · Score 95.6 · 93.3% acc · ~64 TPS  
The Dolphin uncensored fine-tune of Llama 3. Excellent all-around quality. Three identical variants (`8b-v2.9`, `latest`, `8b`) score identically — pick `latest` for fastest load time (4.5s vs 8.6s for `8b`). **Best uncensored general-purpose model; useful when you need a model that won't refuse edge-case creative or technical requests.**

**`metal-muse-v2:latest`** · Score 92.5 · 100% acc · 62.9 TPS  
Perfect score on every category despite being a music-domain fine-tune — the base model quality shines through. v2 edges out v1 on coding (100% vs 75%). **Best custom fine-tune overall; if you're building Forge Music Studio workflows that also need general reasoning, this is your model.**

**`qwen2.5-coder:7b`** · Score 92.4 · 100% acc · 62.6 TPS  
Perfect accuracy across all four categories. Runs fast at 7B. The most reliable small coding model in the fleet — every coding task passed, math perfect, instructions followed. **Best coding agent for high-frequency agentic spin-ups where load time and throughput matter** (6.6s load, 62.6 TPS).

**`llama3.1:latest`** · Score 91.4 · 100% acc · 60.2 TPS  
The vanilla Llama 3.1 8B. Perfect across all categories. Slightly slower than qwen2.5-coder:7b and slightly worse at coding-specific tasks, but strongest general-purpose baseline. **Best drop-in general-purpose agent** — widely understood behavior, reliable, fast.

---

### A-Tier — Strong Performers (Score 85–90)

**`upcycled-qwen-coder-v1:latest`** · Score 90.3 · 96.7% acc · 62.6 TPS  
Your own Qwen 2.5 Coder 7B fine-tune. Matches the base model almost exactly (96.7% vs 100% — one math slip). At the same speed. **Worth using over base for domain-aware coding tasks; for pure general benchmarks the base wins by a hair.**

**`qwen3:0.6b`** · Score 89.2 · 83.3% acc · 239 TPS  
The outlier. At 239 TPS it's roughly 4× faster than any other model. Accuracy drops to 83% (weak on coding: 50%) but math/MC/instructions are strong. **Best for ultra-low-latency routing, classification, intent detection, or any task where you need a sub-second decision before handing off to a heavier model.**

**`dolphin-llama3:8b`** · Score 88.6 · 93.3% acc · 63.9 TPS  
Third dolphin variant — same quality, slightly slower load. Use `dolphin-llama3:latest` instead unless you specifically pinned `:8b`.

**`metal-muse-v1:latest`** · Score 88.1 · 93.3% acc · 62.7 TPS  
One coding failure vs v2. Everything else identical. Upgrade to v2 unless you need v1's specific style.

**`llama3.1:8b`** · Score 87.9 · 100% acc · 52.2 TPS  
Same model as `:latest`, different Ollama tag. Slightly slower (different tensor-split during this run: `0.709/0.291` vs `0.491/0.509`). Use `:latest`.

---

### B-Tier — Capable Mid-Range (Score 70–85)

**`qwen2.5:14b-instruct-q4_K_M`** · Score 77.7 · 96.7% acc · 33.8 TPS  
Best general-purpose 14B option. Excellent instruction following and math. One coding slip. Good balance of quality and VRAM headroom. **Use when you need a step up in reasoning quality over 7B models and can accept ~3.8s latency.**

**`mistral-nemo:12b-instruct-2407-q4_K_M`** · Score 76.4 · 90.0% acc · 40.8 TPS  
Faster than the 14B models due to smaller size. 90% accuracy with math being the weak spot (75%). **Best when you need 12B-class reasoning at moderate speed** — good alternative to the Qwen 14B if latency matters more than math precision.

**`qwen2.5-coder:14b`** · Score 75.4 · 93.3% acc · 33.8 TPS  
Coding-specialist 14B. Same speed as the 14B instruct. One coding and one math slip. **Use over `qwen2.5-coder:7b` only when you have longer context or harder tasks that need 14B reasoning — the 7B is faster with equal accuracy for standard work.**

**`gemma3:27b`** · Score 72.5 · 100% acc · 17.2 TPS  
Perfect accuracy — the only 100% model besides the 8B models. But slow. Runs via Ollama. **Use for high-stakes single-shot tasks where correctness trumps latency** (reviewing a PR, auditing logic, writing a spec). Not suitable for agentic loops at 17 TPS.

**`qwen2.5-coder:32b` / `qwen2.5-coder:32b-instruct-q4_K_M`** · Score 71.9 · 100% acc · 15.8 TPS  
Perfect accuracy, painfully slow (8.1s avg). These are the same model under two Ollama tags — `q4_K_M` loads faster (14.6s vs 26.7s) due to a better blob layout. **Use `qwen2.5-coder:32b-instruct-q4_K_M` for the hardest coding tasks where you need 32B reasoning power and can wait** (complex algorithm design, multi-file refactors, system design).

**`gemma4:31b-it-qat`** · Score 70.3 · 96.7% acc · 17.0 TPS  
The newest model in the fleet, now working via llama.cpp after switching from the broken Ollama conversion (was `status: too_large`). Near-perfect accuracy, better than gemma3:27b in instruction-following. Slow at 31B. **Best large-model for instruction-heavy tasks** (code review with specific format requirements, structured output generation). One coding truncation is a known llama.cpp token-limit edge case.

---

### C-Tier — Limited / Specialized General Use (Score 50–70)

**`mistral-small3.2:24b`** · Score 69.8 · 93.3% acc · 21.0 TPS  
Solid 93.3% accuracy but constrained by Ollama fallback (llama.cpp incompatibility) and slow TPS for a 24B. Strong coding (100%) and reasoning; weak on instructions (83%). **Reasonable choice for coding tasks if the B-tier options are busy, but gemma4:31b-it-qat now beats it in most dimensions.**

**`deepseek-coder:33b-instruct-q4_K_M`** · Score 52.4 · 70.0% acc · 15.9 TPS  
The disappointment of the fleet. 100% coding accuracy but terrible math (50%) and instruction-following (50%). Slow. **Only justifiable if you have a pure code-generation task with no reasoning or format requirements** — and even then, qwen2.5-coder:32b does it better.

**`tinyllama:1.1b`** · Score 54.5 · 30.0% acc · 285.9 TPS  
285 TPS — the fastest model by far. But 30% general accuracy makes it unsuitable for any task requiring reasoning. **Only viable for tokenization tests, streaming demos, or latency profiling. Do not use in production pipelines.**

---

### Domain-Specific Fine-Tunes (Not General-Purpose)

These models score near-zero on the general benchmark **by design** — they're fine-tuned for narrow domains and shouldn't be evaluated on general tasks.

| Model | Domain | TPS | Notes |
|-------|--------|-----|-------|
| `ski-expert-v3:latest` | Ski/outdoor advice | 60.1 | 0% general acc — dedicated persona model |
| `travel-advisor:latest` | Travel planning | 21.4 | 3.3% general acc — 32B base, slow for its use case |
| `travel-ai:latest` | Travel planning | 21.4 | 0% general acc — same base as travel-advisor |
| `upcycled-coder-v1:latest` | Coding (v1) | 59.9 | 13.3% general — fine-tune artifacts present |
| `upcycled-coder-v2:latest` | Coding (v2) | 60.0 | 6.7% general — v2 reduced repetition, accuracy still low |

> The `upcycled-coder` models show the benchmark suite is harder than the upcycle training data. These models excel at their training distribution (code continuation, specific chat templates) but regress on unfamiliar formats.

---

### ⚠️ Broken / Redundant (Do Not Use)

**`glm-4.7-flash:latest`** — 30% accuracy despite 63.8 TPS. This is the **Ollama-converted GGUF which fails at instruction-following and coding** (0%). The working version is `glm-4.7-flash:hf-q4km`. Keep `:latest` installed for Ollama compatibility but never route agentic tasks to it.

---

## Decision Guide: Best Model for Each Use Case

### Agentic Spin-Ups (fast, reliable, many parallel agents)
**Primary → `qwen2.5-coder:7b`** · 100% accuracy, 100% instruction-following, 6.6s load, 62.6 TPS  
**Fallback → `llama3.1:latest`** · Same quality, broader training distribution, 4.5s load

### Coding Assistant (single-shot code generation, review, debugging)
**Fast → `qwen2.5-coder:7b`** · handles ~80% of coding tasks perfectly  
**Hard problems → `qwen2.5-coder:32b-instruct-q4_K_M`** · 100% accuracy, accepts slower response  
**Deep review/refactor → `gemma3:27b`** · 100% accuracy, excellent reasoning at 27B context

### General Chat / Q&A
**Best → `gemma3:latest`** · fastest high-accuracy model, natural conversational output  
**Alternative → `glm-4.7-flash:hf-q4km`** · tied speed, better instruction format compliance

### Math / Reasoning
**→ `gemma3:27b`** · 100% math accuracy, formal proof-style responses  
**Fast alternative → `qwen2.5-coder:7b` or `llama3.1:latest`** · also 100% math, much faster

### Routing / Triage / Classification (sub-second)
**→ `qwen3:0.6b`** · 239 TPS, 0.5s latency, 100% on MC and instruction tasks — perfect for deciding which heavier model to invoke

### Creative / Music-Adjacent / Uncensored
**→ `metal-muse-v2:latest`** · 100% accuracy + music-domain fine-tune  
**Uncensored fallback → `dolphin-llama3:latest`** · 93.3% acc, 4.5s load

### Long Context / Document Analysis
**→ Run Phase 2 (Context Profiling) first** — max safe context windows not yet measured  
Likely best candidates: `gemma3:27b`, `gemma4:31b-it-qat`, `qwen2.5-coder:32b` based on architecture context limits

### Instruction-Following / Structured Output (JSON, tool calls)
**→ `glm-4.7-flash:hf-q4km`** · 100% instruction accuracy + 75.4 TPS  
**→ `qwen2.5-coder:7b`** · also 100% instructions, same speed band

### Agentic Orchestrator (routes sub-agents, reads results, decides next step)
**→ `gemma4:31b-it-qat`** · 31B reasoning, 100% instruction-following, now working via llama.cpp  
**→ `gemma3:27b`** · perfect accuracy, established model

---

## Pending Data (Run These Next)

| Phase | What it measures | Best candidates to profile |
|-------|-----------------|---------------------------|
| Phase 2: Context | Max safe context window per model | `qwen2.5-coder:32b`, `gemma3:27b`, `gemma4:31b-it-qat` |
| Phase 3: Optimize | Best `--parallel` and `--ctx-size` settings | All S/A-tier models |

Once Phase 3 completes, the optimal `--parallel` count per model will enable properly-tuned agentic concurrency limits (e.g., how many simultaneous `qwen2.5-coder:7b` agents can run before VRAM pressure degrades throughput).

---

## Load Time Reference (for Agentic Cold-Start Planning)

| Load time | Models |
|-----------|--------|
| < 5s | `qwen2.5-coder:7b` (6.6s), `llama3.1:latest` (4.5s), `dolphin-llama3:latest` (4.5s), `qwen3:0.6b` (2.5s) |
| 5–10s | `dolphin-llama3:8b-v2.9` (6.6s), `metal-muse-v2` (6.6s), `gemma3:latest` (6.9s) |
| 10–15s | `mistral-nemo:12b` (10.6s), `qwen2.5-coder:14b` (12.6s), `qwen2.5-coder:32b-instruct` (14.6s) |
| 15–20s | `gemma3:27b` (20.4s), `gemma4:31b-it-qat` (17.2s), `glm-4.7-flash:hf-q4km` (20.2s) |
| 20s+ | `qwen2.5-coder:32b` (26.7s), `deepseek-coder:33b` (24.7s) |

> For agentic workflows that spin up and teardown models frequently, keep `qwen2.5-coder:7b` or `llama3.1:latest` as the default — their sub-7s cold-start is half that of the 14B models.
