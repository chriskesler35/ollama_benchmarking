# llama.cpp Server Optimization Guide

## Overview

The **llama.cpp Server Optimizer** tests different `--parallel` and `--ctx-size` settings to find the optimal configuration for your dual RTX 3060 setup.

It tests combinations and measures:
- **Throughput** (tokens/sec with concurrent requests)
- **Per-GPU VRAM usage** (ensure no OoM)
- **Latency** (time to generate tokens)
- **Best configuration** for your hardware

## Prerequisites

### 1. Get llama.cpp (if you don't have it)

**Option A: Using llama-cpp-python with server support**
```bash
pip install llama-cpp-python[server]
```

**Option B: Using llama.cpp standalone**
Download from: https://github.com/ggerganov/llama.cpp
- Get `llama-server` binary for Windows
- Add to PATH or specify full path

**Option C: Using your existing llama.cpp**
If you already have `llama.cpp/main.exe`, you may need to build with server support:
```bash
cd llama.cpp
mkdir build
cd build
cmake .. -DBUILD_SHARED_LIBS=ON
cmake --build . --config Release
```

### 2. Verify llama-server is available
```bash
where llama-server
# or
Get-Command llama-server
```

## Usage

### Basic optimization of a model

```bash
# Optimize Mistral 7B (from earlier download)
python llama_cpp_server_optimizer.py "E:\ollama-bench-models\mistral-7b-instruct-v0.2.Q4_K_M.gguf"

# With verbose output to see each test
python llama_cpp_server_optimizer.py "E:\ollama-bench-models\mistral-7b-instruct-v0.2.Q4_K_M.gguf" -v

# Save results for comparison
python llama_cpp_server_optimizer.py "E:\ollama-bench-models\mistral-7b-instruct-v0.2.Q4_K_M.gguf" -o mistral_optimization.json
```

### Test specific settings

```bash
# Test only parallel=1,2,3 (faster)
python llama_cpp_server_optimizer.py model.gguf --parallel 1 2 3

# Test only ctx_size=2048,4096 (skip 8192)
python llama_cpp_server_optimizer.py model.gguf --ctx-size 2048 4096

# Combine: test parallel 2-4 with ctx 2048-4096
python llama_cpp_server_optimizer.py model.gguf --parallel 2 3 4 --ctx-size 2048 4096
```

### Workflow example

```bash
# 1. After Phase 1/2 completes, optimize your top models:
python llama_cpp_server_optimizer.py "E:\ollama-bench-models\mistral-7b-instruct-v0.2.Q4_K_M.gguf" -o results/mistral_opt.json
python llama_cpp_server_optimizer.py "E:\ollama-bench-models\llama-2-7b-chat.Q4_K_M.gguf" -o results/llama2_opt.json

# 2. Check recommended settings
cat results/mistral_opt.json | jq '.recommendation'
# Output: "--parallel 3 --ctx-size 4096"

# 3. Use in your server
llama-server -m mistral-7b.gguf --parallel 3 --ctx-size 4096 -ngl 999
```

## Understanding Results

### Example output:

```
================================================================================
OPTIMIZATION RESULTS
================================================================================
Model: mistral-7b-instruct-v0.2
Optimal --parallel: 3
Optimal --ctx-size: 4096
Throughput: 87.50 tok/s
GPU Memory: {'gpu0_used_gb': 9.2, 'gpu1_used_gb': 6.8, 'gpu0_used_pct': 76.7, 'gpu1_used_pct': 56.7}

Recommended command:
  llama-server -m model.gguf --parallel 3 --ctx-size 4096
```

**What this means:**
- Running with `--parallel 3` (3 concurrent requests) gives best throughput
- Using `--ctx-size 4096` is safe with that parallel setting
- Achieves 87.5 tokens/sec across all requests
- GPU0: 9.2GB / 12GB (76.7%)
- GPU1: 6.8GB / 12GB (56.7%)
- Well-balanced across both GPUs with good headroom

### JSON output includes:

```json
{
  "model": "mistral-7b-instruct-v0.2",
  "optimal_parallel": 3,
  "optimal_ctx_size": 4096,
  "optimal_throughput": 87.50,
  "gpu_memory_at_optimal": {
    "gpu0_used_gb": 9.2,
    "gpu1_used_gb": 6.8,
    "gpu0_used_pct": 76.7,
    "gpu1_used_pct": 56.7
  },
  "recommendation": "--parallel 3 --ctx-size 4096",
  "all_results": [
    {
      "parallel": 1,
      "ctx_size": 2048,
      "best_throughput": 45.2,
      "gpu_memory": {...}
    },
    ...
  ]
}
```

## Key Metrics

| Metric | What It Means | Optimal Value |
|--------|--------------|---------------|
| `optimal_parallel` | Best number of concurrent requests | Higher = better throughput (if no OoM) |
| `optimal_ctx_size` | Best context window | Larger = more context, higher VRAM |
| `optimal_throughput` | Tokens/sec at best settings | Higher = faster inference |
| `gpu0_used_pct` / `gpu1_used_pct` | GPU utilization | 70-85% is good (leaves headroom) |

## Tradeoffs

### High Parallel, Large Context
- **Pro:** Maximum throughput
- **Con:** High VRAM usage, higher latency per request, OoM risk
- **When:** Running batch inference, non-interactive workloads

### Low Parallel, Small Context
- **Pro:** Low latency, stable, no OoM risk
- **Con:** Lower throughput, underutilizes hardware
- **When:** Interactive apps, single-user deployments

### Recommended Balance for Dual RTX 3060
- **GPU usage:** Keep under 85% per GPU (leave 15% buffer)
- **Parallel:** 2-3 for 7B models, 1-2 for 13B+
- **Context:** Use max safe from context profiler

## Expected Times

- Optimization with default settings (5 parallel × 3 contexts): 20-30 minutes per model
- Quick optimization (2 parallel × 2 contexts): 10-15 minutes per model
- Use `--parallel 1 2 3` for faster initial testing

## Troubleshooting

**"llama-server not found"**
- Install: `pip install llama-cpp-python[server]`
- Or specify full path to your llama.cpp binary

**"CUDA out of memory"**
- Model + settings too large for your VRAM
- Try smaller parallel value or context size
- Use context profiler first to find limits

**"Server failed to start"**
- Check model path exists
- Verify llama-server is properly installed
- Try with `-v` for more debug info

**Very slow testing**
- Use smaller --parallel and --ctx-size for quick initial test
- Example: `--parallel 1 2 3 --ctx-size 2048 4096`

## Integration with Your Workflow

### 1. Phase 1: Benchmark all models (Ollama API)
→ Results in results_phase1.json

### 2. Phase 2: Profile context limits (Context Profiler)
→ Results in profile_*.json (max safe context per model)

### 3. Phase 3: Optimize server settings (llama.cpp Server Optimizer)
→ Results in optimization_results.json (best parallel/context per model)

### Final Outcome

You'll have per-model configurations like:

```
llama3.1:
  Command: llama-server -m llama3.1.gguf --parallel 3 --ctx-size 4096 -ngl 999
  Throughput: 92 tok/s
  GPU util: 78%/59%

upcycled-coder-v2:
  Command: llama-server -m upcycled-coder-v2.gguf --parallel 2 --ctx-size 8192 -ngl 999
  Throughput: 85 tok/s
  GPU util: 85%/68%

dolphin-mixtral (GGUF):
  Command: llama-server -m dolphin-mixtral.gguf --parallel 1 --ctx-size 4096 -ngl 999
  Throughput: 45 tok/s
  GPU util: 92%/88%
```

These are production-ready, empirically tested settings for your specific hardware!
