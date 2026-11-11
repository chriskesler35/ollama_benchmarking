# Context Window Profiling Guide

## Overview

After Phase 1 benchmark completes, you can use the **Context Profiler** to determine the maximum safe context window for each model without hitting OoM or severe slowdown.

This tool:
- Tests each model at context windows: 512, 1024, 2048, 4096, 8192, 16384 tokens
- Tracks **per-GPU VRAM usage** during inference
- Measures **throughput (tokens/sec)** at each context level
- Identifies the point where slowdown (>50% drop) or OoM occurs
- Recommends max safe context for your dual RTX 3060s (24GB)

## When to Run

1. **Phase 1 benchmark completes** (all 12 models benchmarked)
2. **Review Phase 1 results** to identify top performers
3. **Profile top 3-5 models** individually with context profiler
4. Get detailed context/VRAM data for your workflow

## Usage

### Profile a single model

```bash
# Basic - test against default context sizes
python context_profiler.py llama3.1

# Verbose - see each test as it runs
python context_profiler.py llama3.1 -v

# Save detailed results
python context_profiler.py llama3.1 -v -o profile_llama3.1.json

# Limit testing to smaller contexts (faster)
python context_profiler.py llama3.1 --max-context 8192
```

### Example workflow

```bash
# 1. After Phase 1 completes, profile your top 3 models:
python context_profiler.py llama3.1 -v -o profile_llama3.1.json
python context_profiler.py upcycled-coder-v2 -v -o profile_upcycled.json
python context_profiler.py dolphin-llama3 -v -o profile_dolphin.json

# 2. Check results
cat profile_llama3.1.json | jq '.analysis'

# 3. Use max context in your applications
# Results show: "Max safe context: 4096 tokens"
# → Use that as your inference context limit
```

## Understanding Results

### Example output:

```
[RESULTS] Context Profiling for llama3.1
  Baseline throughput: 125.50 tok/s
  Max safe context: 4096 tokens
  Slowdown detected at: 8192 tokens
  Recommendation: Max 4096 tokens (slowdown at 8192)
```

**Interpretation:**
- At context 512-4096: stable performance (~125 tok/s)
- At context 8192: throughput drops >50% (indicates slowdown)
- **Safe limit: 4096 tokens** for this model on your hardware

### JSON output includes:

```json
{
  "model": "llama3.1",
  "test_results": [
    {
      "context_size": 512,
      "tokens_per_sec": 125.50,
      "response_time_ms": 400,
      "gpu_memory": {
        "gpu0_used_mb": 6500,
        "gpu1_used_mb": 4200
      }
    },
    ...
  ],
  "analysis": {
    "baseline_tokens_per_sec": 125.50,
    "max_safe_context": 4096,
    "slowdown_point": 8192,
    "oom_point": null,
    "recommendation": "Max 4096 tokens (slowdown at 8192)"
  }
}
```

## Key Metrics to Watch

| Metric | What It Means | Action |
|--------|--------------|--------|
| `baseline_tokens_per_sec` | Throughput at smallest context | Reference for comparison |
| `max_safe_context` | Largest context without slowdown | Use this as limit |
| `slowdown_point` | Where performance degrades 50% | Avoid exceeding this |
| `oom_point` | Where model runs out of memory | Hard limit |
| `gpu0_used_mb` / `gpu1_used_mb` | Per-GPU VRAM usage | Monitor GPU balance |

## Tips

1. **Start with top performers** from Phase 1 (highest throughput)
2. **Use `--max-context 8192`** for faster profiling initially (tests up to 8K tokens)
3. **Use `-v` flag** to watch progress in real-time
4. **Save JSON output** with `-o` for record keeping
5. **Compare multiple models** to see which gives best throughput/context tradeoff

## Expected Times

- Per model profile: 10-20 minutes (depending on context sizes tested)
- Full profile (all 6 context sizes): ~20 minutes
- Profile with `--max-context 8192`: ~15 minutes
- Profile with `--max-context 4096`: ~10 minutes

## After Profiling

Use your results to:

1. **Set inference context limits** in your applications
2. **Choose models** based on context/throughput needs
3. **Optimize batch sizes** knowing how much VRAM each context uses
4. **Plan multi-model serving** (e.g., small model at 8K context + large model at 2K)

## Troubleshooting

**"Connection refused" error:**
- Ollama not running: `ollama serve` in another terminal

**"OOM at context 512":**
- Model is too large for your VRAM at any context
- Try a smaller model or export to GGUF with GPU splitting

**Timeout errors:**
- Model is slow at that context
- Try smaller context sizes with `--max-context 4096`

**Missing GPU data:**
- pynvml not installed: `pip install pynvml`
- Some GPU info still available without it, just not detailed VRAM tracking
