# ollama-bench

Benchmark your local LLMs on real hardware — speed, accuracy, safe context limits, and optimal
server settings — then rank them into a single report so you can pick the right model per task.

Models are served through **llama.cpp** with the weights split across multiple GPUs, and fall back
to **Ollama** for models whose GGUF conversions llama.cpp can't load. Ollama's blob store is used to
locate weights, so every model you already have works without a separate download.

---

## Table of contents

- [What it measures](#what-it-measures)
- [Requirements](#requirements)
- [Install](#install)
- [Quick start](#quick-start)
- [Using the dashboard](#using-the-dashboard)
- [Benchmarking cloud models](#benchmarking-cloud-models)
- [Command line usage](#command-line-usage)
- [Configuration](#configuration)
- [When a model won't load](#when-a-model-wont-load)
- [Understanding the results](#understanding-the-results)
- [Troubleshooting](#troubleshooting)
- [Further reading](#further-reading)

---

## What it measures

| Phase | What it answers | Runtime per model |
|---|---|---|
| **1 — Speed** | Tokens/sec, response latency, model load time | ~1 min |
| **Accuracy** | 32 auto-scored tasks: coding, math, multiple choice, instruction following | ~3–10 min |
| **2 — Context** | Largest context window that loads without OOM or a throughput collapse | ~5 min |
| **3 — Optimize** | Best `--parallel` / `--ctx-size` for serving that model | ~10 min |

Phases are independent — run any subset. Results **merge per model**, so benchmarking one new model
adds it to the table without disturbing anything already measured.

### How accuracy is scored

Every task has an objectively checkable answer. No LLM judge, no human grading.

| Category | Tasks | Scoring |
|---|---|---|
| Coding | 8 | Model's code is **executed** against assert-based unit tests in an isolated subprocess (20s timeout) |
| Math | 8 | Word problems; answer parsed from an explicit `ANSWER: <n>` marker |
| Multiple choice | 8 | Letter A–D, exact match |
| Instructions | 8 | Structural checks — exact JSON keys, bullet counts, regex, single-word answers |

Reasoning blocks (`<think>...</think>`) are stripped before scoring, so chain-of-thought models
aren't penalised for thinking out loud.

---

## Requirements

- **Python 3.10+**
- **[Ollama](https://ollama.com)** — used to locate model weights, and as a fallback inference engine
- **`llama-server`** from [llama.cpp](https://github.com/ggerganov/llama.cpp) — the primary engine
- **NVIDIA GPU(s)** with CUDA. Multi-GPU is supported and weights are split automatically
- `pynvml` for VRAM telemetry (included in `requirements.txt`; degrades gracefully if absent)

Built and tested on dual RTX 3060s (24 GB total) on Windows, but nothing is hardware-specific
beyond the defaults.

---

## Install

```bash
git clone https://github.com/chriskesler35/ollama_benchmarking.git
cd ollama_benchmarking
pip install -r requirements.txt
```

Point the suite at your `llama-server` binary if it isn't at the default path:

```bash
set LLAMA_SERVER_BIN=C:\path\to\llama-server.exe
```

Confirm Ollama is reachable and has models:

```bash
ollama list
```

---

## Quick start

Start the dashboard:

```bash
python dashboard.py
```

Then open **http://localhost:8000**.

On Windows you can instead double-click `start-dashboard.bat`, which checks dependencies, warns if
Ollama isn't running, launches the server, and opens your browser. To put a shortcut on your
desktop, run `create-shortcut.vbs`.

A sensible first pass:

1. **Phase 1 — Speed** → establishes the baseline and flags models that won't fit in VRAM
2. **Accuracy** → the slowest phase, but the one that actually tells you which model to trust
3. **Report tab** → composite ranking and per-task-type recommendations

Phases 2 and 3 are worth running once you've narrowed to the models you'll actually deploy.

---

## Using the dashboard

Each phase card has three buttons:

| Button | Behaviour |
|---|---|
| **Start** | Runs every local model |
| **+ Specific Model(s)** | Pick a subset — results merge into the existing table |
| **Reset** | Clears that phase's stored results |

Runs happen in detached processes, so **closing the browser doesn't stop a benchmark**. Reopening
the dashboard reconnects to anything in flight. The **Stop** button on the Dashboard tab cancels the
current run.

### Tabs

- **Dashboard** — launch controls and live progress
- **Phase 1: Speed** — throughput, latency, load time
- **Accuracy** — overall plus per-category breakdown
- **Speed vs Accuracy** — scatter plot; top-right is the sweet spot
- **Phase 2: Context** — max safe context per model
- **Phase 3: Optimize** — the config sweep and the winning settings
- **★ Report** — composite ranking, category heatmap, tier groupings, use-case guide

---

## Benchmarking cloud models

Models tagged `:cloud` run on Ollama's hosted infrastructure and **spend subscription credits**, so
they're never included automatically. Use **+ Cloud Models** on the Speed or Accuracy card.

The picker has a **"Run ONLY these cloud models"** checkbox, **checked by default** — otherwise
testing three cloud models would also re-run every local model, which takes hours. Uncheck it to do
both in one pass. The confirmation dialog states exactly which scope you're about to run.

Authentication is handled by your local Ollama install, not by this tool — there's no API key to
configure here. If cloud requests fail, sign in:

```bash
ollama signin
```

**Reading cloud results:** accuracy is directly comparable to local models. **Speed is not** — it
reflects network latency plus Ollama's hosted capacity, not your hardware. Cloud models render as
squares in the scatter plot for this reason.

Cloud reasoning models get a larger token budget (`CLOUD_MAX_TOKENS = 4096`) because they spend
tokens on hidden reasoning before emitting an answer, and only the answer is scored.

---

## Command line usage

Everything the dashboard does is available as a script. Results land in `results/` and the dashboard
picks them up automatically.

### Speed

```bash
python speed_llamacpp.py -o results/speed.json
```

| Flag | Purpose |
|---|---|
| `-m`, `--models` | Restrict to specific models (default: all local) |
| `--cloud-models` | Also measure these `:cloud` models |
| `--cloud-only` | Measure **only** the cloud models, skipping local discovery |
| `-o`, `--output` | Output JSON path |
| `-v`, `--verbose` | Per-request detail |
| `--resume` | Continue a partial run from its results file |
| `--host`, `--port` | Ollama location (default `localhost:11434`) |

### Accuracy

Same flags as above:

```bash
python accuracy_llamacpp.py -o results/accuracy.json -v
```

Score a single model:

```bash
python accuracy_llamacpp.py -m qwen2.5-coder:7b -o results/accuracy.json
```

Cloud models only:

```bash
python accuracy_llamacpp.py --cloud-models glm-5.2:cloud --cloud-only -o results/cloud.json
```

### Context profiling (Phase 2)

```bash
python context_llamacpp.py gemma3:27b -o results/profile_gemma3.json -v
```

### Optimization (Phase 3)

For models with a llama.cpp-loadable GGUF:

```bash
python llama_cpp_optimizer.py qwen2.5-coder:7b -o results/opt.json -v
```

For Ollama-only models:

```bash
python ollama_optimizer.py gemma3:12b -o results/opt.json -v
```

Both accept `--parallel` and `--ctx-size` to override the swept values. The dashboard picks the
right script automatically based on whether the model resolves to a usable GGUF.

Phase 3 also **promotes its best single-request speed back into Phase 1**, so the Speed tab reports
throughput measured at the optimal context size rather than at defaults. Promoted rows carry a
`P3✓` badge.

---

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `LLAMA_SERVER_BIN` | `G:\llama_bin\llama-server.exe` | Path to `llama-server` |
| `BENCH_SERVER_PORT` | `8091` | Port for the benchmark's llama.cpp instance |

The dashboard serves on port **8000**; `llama-server` is started and stopped per measurement on
port **8091**.

Tunable constants at the top of `accuracy_llamacpp.py`:

- `MAX_TOKENS` (1024) — generation cap for local models
- `CLOUD_MAX_TOKENS` (4096) — larger cap for cloud reasoning models
- `SERVER_CTX` (4096) — context size used during accuracy runs

---

## When a model won't load

Some Ollama conversions — notably certain gemma3, gemma4, and GLM builds — omit metadata that
llama.cpp requires. Those models fall back to the Ollama engine, and their row gains a
**Get llama.cpp GGUF** button. (Models reported `too_large` are a different problem — they simply
exceed available VRAM — so no button is offered.)

That button searches Hugging Face for a compatible GGUF, downloads it, and registers it in
`hf_gguf_map.json`:

```json
{
  "gemma4:31b-it-qat": "G:\\AI_Models\\hf_gguf_cache\\gemma-4-31B-it-QAT-Q4_0.gguf"
}
```

The resolver checks this map before Ollama's own manifests, so the model runs through llama.cpp from
then on. This file is gitignored — it holds absolute paths specific to your machine.

To use the downloaded GGUF as a normal Ollama model as well:

```bash
ollama create mymodel:tag -f Modelfile
```

...where the Modelfile is a single `FROM <path-to-gguf>` line.

---

## Understanding the results

The Report tab ranks models by a composite score:

```
Score = (Accuracy% × 0.65) + (min(TokensPerSec ÷ 80, 1.0) × 100 × 0.35)
```

Speed is capped at 80 tok/s on the reasoning that beyond it, throughput is rarely the bottleneck.
Models are grouped into S/A/B/C tiers, with domain-specific fine-tunes listed separately since a
general-purpose score misrepresents them.

Raw JSON lives in `results/`:

| Pattern | Contents |
|---|---|
| `results_phase1_*.json` | Speed (`*_p3.json` = promoted from Phase 3) |
| `results_accuracy_*.json` | Accuracy, including per-task detail |
| `profile_*.json` | Context profiles |
| `optimization_*.json` | Config sweeps |

Newest-per-model wins when merging, so re-running one model updates only that row. **Export All
Results** on the Dashboard tab bundles everything into one JSON.

---

## Troubleshooting

**Dashboard shows no models**
Ollama isn't reachable. Check that something is listening on 11434 — a running tray icon isn't proof:

```bash
ollama list
```

On Windows, the desktop app's model path lives in its own settings database and **overrides**
`OLLAMA_MODELS`. If the server logs a different path than you expect, change it in the app's
Settings UI rather than via environment variables.

**Code changes don't take effect**
Python loads source once at startup. Restart `dashboard.py` after editing any `.py` file, and
hard-refresh the browser (`Ctrl+Shift+R`) after editing `static/`.

**A model scores 0% but seems capable**
Likely truncation rather than incapability — it exhausted its token budget mid-reasoning and
returned an empty answer. Raise `MAX_TOKENS` or `CLOUD_MAX_TOKENS`.

**Out of memory**
Run Phase 2 to find the safe context window, then Phase 3 for the best settings within it. Models
that can't fit at all are reported as `too_large` rather than crashing the run.

**Benchmark seems stuck**
Large models can take minutes to load. Check the log files (`phase1_output.log`,
`accuracy_output.log`, `phase3_output.log`) for real progress.

---

## Further reading

| Document | Covers |
|---|---|
| [STARTUP_GUIDE.md](STARTUP_GUIDE.md) | Launch methods and first-run walkthrough |
| [DASHBOARD_README.md](DASHBOARD_README.md) | Full dashboard reference |
| [CONTEXT_PROFILING_GUIDE.md](CONTEXT_PROFILING_GUIDE.md) | Phase 2 in depth |
| [LLAMA_CPP_OPTIMIZATION_GUIDE.md](LLAMA_CPP_OPTIMIZATION_GUIDE.md) | Phase 3 in depth |
| [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md) | Example output from a full run |
