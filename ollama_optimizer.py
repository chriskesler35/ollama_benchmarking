#!/usr/bin/env python3
"""Ollama Optimizer — sweep num_ctx × concurrency for Ollama-only models.

Mirrors llama_cpp_optimizer.py's JSON output format exactly so all downstream
consumers (Phase 3 tab, _promote_phase3_to_speed, dashboard merge) work without
any changes.

What we can actually tune for Ollama:
  num_ctx    — set per-request via options.num_ctx; no Ollama restart needed.
               Most models default to 2048 even if they support 128k+.
  concurrency — OLLAMA_NUM_PARALLEL is server-wide (requires restart), but we
               fire concurrent requests and detect whether they run in true
               parallel or queue, then recommend the right value.
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, List, Optional

import requests

try:
    import pynvml
    PYNVML_AVAILABLE = True
except ImportError:
    PYNVML_AVAILABLE = False

from prompts import TEST_PROMPTS

OLLAMA_HOST = "http://localhost:11434"
REQUEST_TIMEOUT = 300
NUM_PREDICT = 128

# Wider ctx range than llama.cpp optimizer — Ollama models often support 128k+
# and default to only 2048, so this is where most of the value is.
CONTEXT_SIZES   = [4096, 8192, 16384, 32768]
PARALLEL_VALUES = [1, 2, 4]


# ── helpers ──────────────────────────────────────────────────────────────────

def write_progress(progress_file: Optional[str], data: dict) -> None:
    if not progress_file:
        return
    try:
        tmp = str(progress_file) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, progress_file)
    except Exception:
        pass


def gpu_mem() -> Optional[Dict]:
    if not PYNVML_AVAILABLE:
        return None
    try:
        pynvml.nvmlInit()
        out = {}
        for i in range(2):
            try:
                h = pynvml.nvmlDeviceGetHandleByIndex(i)
                m = pynvml.nvmlDeviceGetMemoryInfo(h)
                out[f"gpu{i}_used_mb"] = round(m.used / (1024 ** 2))
            except pynvml.NVMLError:
                pass
        pynvml.nvmlShutdown()
        return out or None
    except Exception:
        return None


def one_completion(model: str, num_ctx: int) -> Dict:
    """Single generate call through Ollama /api/generate."""
    try:
        r = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json={
                "model": model,
                "prompt": TEST_PROMPTS[0].text,
                "stream": False,
                "options": {
                    "temperature": 0,
                    "num_predict": NUM_PREDICT,
                    "num_ctx": num_ctx,
                },
            },
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        d = r.json()
        return {"tokens": d.get("eval_count", 0), "ok": True}
    except Exception as e:
        return {"tokens": 0, "ok": False, "error": str(e)[:120]}


def measure(model: str, parallel: int, num_ctx: int) -> Dict:
    """Fire `parallel` concurrent completions; return aggregate throughput."""
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = [pool.submit(one_completion, model, num_ctx) for _ in range(parallel)]
        results = [f.result() for f in futures]
    elapsed = time.perf_counter() - start
    ok = [r for r in results if r["ok"]]
    total_tokens = sum(r["tokens"] for r in ok)
    return {
        "aggregate_tokens_per_sec": round(total_tokens / elapsed, 1) if elapsed > 0 and ok else 0.0,
        "successful_requests": len(ok),
        "elapsed_sec": round(elapsed, 2),
    }


# ── per-configuration test ────────────────────────────────────────────────────

def test_configuration(model: str, parallel: int, num_ctx: int, verbose: bool) -> Dict:
    """Warmup (to absorb any ctx-size reload) then measure one configuration."""
    # Changing num_ctx causes Ollama to reload the model; warmup absorbs that cost
    # so it doesn't inflate the timed measurement.
    warmup = one_completion(model, num_ctx)
    if not warmup["ok"]:
        if verbose:
            print(f"    parallel={parallel} ctx={num_ctx}: WARMUP FAILED — {warmup.get('error', '?')}")
        return {
            "concurrency": parallel, "ctx_size": num_ctx,
            "aggregate_tokens_per_sec": 0.0, "successful_requests": 0,
            "total_requests": parallel, "status": "warmup_failed",
            "note": warmup.get("error", "warmup failed"), "gpu_memory": None,
        }

    gpu_loaded = gpu_mem()
    m = measure(model, parallel, num_ctx)

    if verbose:
        gpu_str = (f"GPU0={gpu_loaded.get('gpu0_used_mb')}MB "
                   f"GPU1={gpu_loaded.get('gpu1_used_mb')}MB"
                   if gpu_loaded else "GPU n/a")
        print(f"    parallel={parallel} ctx={num_ctx}: "
              f"{m['aggregate_tokens_per_sec']} tok/s aggregate "
              f"({m['successful_requests']}/{parallel} ok, {m['elapsed_sec']}s)  {gpu_str}")

    return {
        "concurrency": parallel, "ctx_size": num_ctx,
        "aggregate_tokens_per_sec": m["aggregate_tokens_per_sec"],
        "successful_requests": m["successful_requests"],
        "total_requests": parallel, "status": "ok",
        "gpu_memory": gpu_loaded,
    }


# ── parallel-mode detection ───────────────────────────────────────────────────

def detect_parallel_mode(results: List[Dict]) -> str:
    """Detect whether Ollama is serving requests concurrently or serialising them.

    At concurrency=1 vs concurrency=2:
      - True parallel: wall-clock ≈ same → aggregate TPS ≈ 2x single → ratio >= 1.5
      - Queued (OLLAMA_NUM_PARALLEL=1): wall-clock ≈ 2x → aggregate TPS ≈ same → ratio < 1.5
    """
    for ctx in sorted(set(r["ctx_size"] for r in results)):
        p1 = next((r for r in results if r["concurrency"] == 1 and r["ctx_size"] == ctx
                   and r["successful_requests"] > 0), None)
        p2 = next((r for r in results if r["concurrency"] == 2 and r["ctx_size"] == ctx
                   and r["successful_requests"] > 0), None)
        if p1 and p2 and p1["aggregate_tokens_per_sec"] > 0:
            ratio = p2["aggregate_tokens_per_sec"] / p1["aggregate_tokens_per_sec"]
            return "parallel" if ratio >= 1.5 else "queued"
    return "unknown"


# ── main optimise loop ────────────────────────────────────────────────────────

def optimize_model(model: str, verbose: bool,
                   parallel_values: Optional[List[int]] = None,
                   context_sizes: Optional[List[int]] = None,
                   progress_file: Optional[str] = None) -> Dict:
    parallel_values = parallel_values or PARALLEL_VALUES
    context_sizes   = context_sizes   or CONTEXT_SIZES

    print(f"\n[*] Optimizing (Ollama) for: {model}")
    print(f"    Sweeping ctx={context_sizes}  parallel={parallel_values}")

    progress = {
        "pid": os.getpid(), "status": "running", "kind": "ollama_optimize",
        "current_model": model, "started_at": datetime.now().isoformat(),
    }
    write_progress(progress_file, progress)

    results       = []
    total_configs = len(context_sizes) * len(parallel_values)
    done          = 0

    for ctx in context_sizes:
        for par in parallel_values:
            if verbose:
                print(f"  [{done + 1}/{total_configs}] ctx={ctx} parallel={par}")
            results.append(test_configuration(model, par, ctx, verbose))
            done += 1
            progress["progress"] = round(done / total_configs * 100)
            write_progress(progress_file, progress)

    usable = [r for r in results if r["successful_requests"] > 0]

    if not usable:
        note = next((r.get("note") for r in results if r.get("note")),
                    "All configurations failed.")
        analysis = {
            "status": "load_failed", "note": note,
            "engine": "ollama", "recommendation": note,
        }
    else:
        # Optimal single-request ctx: largest ctx within 10% of peak single-req TPS.
        # Prefer a large ctx (more usable window) unless it costs significant speed.
        p1_rows = [r for r in usable if r["concurrency"] == 1]
        if p1_rows:
            peak_p1_tps = max(r["aggregate_tokens_per_sec"] for r in p1_rows)
            within_range = sorted(
                [r for r in p1_rows if r["aggregate_tokens_per_sec"] >= peak_p1_tps * 0.90],
                key=lambda r: r["ctx_size"], reverse=True,
            )
            best_p1_row = within_range[0] if within_range else max(p1_rows, key=lambda r: r["aggregate_tokens_per_sec"])
        else:
            best_p1_row = max(usable, key=lambda r: r["aggregate_tokens_per_sec"])

        optimal_ctx    = best_p1_row["ctx_size"]
        optimal_p1_tps = best_p1_row["aggregate_tokens_per_sec"]

        # Best aggregate TPS across all concurrency levels
        best_overall  = max(usable, key=lambda r: r["aggregate_tokens_per_sec"])
        parallel_mode = detect_parallel_mode(results)

        if parallel_mode == "parallel":
            par_note = "OLLAMA_NUM_PARALLEL is active (concurrent requests detected)"
        elif parallel_mode == "queued":
            par_note = (f"requests are queuing (serial). "
                        f"Set OLLAMA_NUM_PARALLEL={best_overall['concurrency']} "
                        f"to reach {best_overall['aggregate_tokens_per_sec']} tok/s aggregate")
        else:
            par_note = "concurrency behaviour unknown"

        gm = best_overall.get("gpu_memory") or {}
        analysis = {
            "optimal_parallel":       best_overall["concurrency"],
            "optimal_ctx_size":       optimal_ctx,
            "optimal_aggregate_tps":  best_overall["aggregate_tokens_per_sec"],
            "engine":                 "ollama",
            "parallel_mode":          parallel_mode,
            "gpu0_used_mb":           gm.get("gpu0_used_mb"),
            "gpu1_used_mb":           gm.get("gpu1_used_mb"),
            "recommendation": (
                f"num_ctx {optimal_ctx} "
                f"({optimal_p1_tps} tok/s single-req)  |  {par_note}"
            ),
        }

    progress["status"] = "completed"
    progress["finished_at"] = datetime.now().isoformat()
    write_progress(progress_file, progress)

    return {
        "model":        model,
        "engine":       "ollama",
        "tensor_split": None,
        "all_results":  results,
        "analysis":     analysis,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Optimize Ollama model settings (num_ctx × concurrency)"
    )
    p.add_argument("model",           help="Ollama model name, e.g. gemma3:12b")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("-o", "--output",  help="Output JSON file")
    p.add_argument("--parallel",  nargs="+", type=int, default=PARALLEL_VALUES)
    p.add_argument("--ctx-size",  nargs="+", type=int, default=CONTEXT_SIZES)
    p.add_argument("--progress-file", default=None)
    args = p.parse_args()

    result = optimize_model(
        args.model, args.verbose,
        parallel_values=args.parallel,
        context_sizes=args.ctx_size,
        progress_file=args.progress_file,
    )

    a = result["analysis"]
    print(f"\n[RESULTS] {args.model}")
    print(f"  {a.get('recommendation', 'No recommendation')}")
    if a.get("gpu0_used_mb") is not None:
        print(f"  VRAM at optimal: GPU0={a['gpu0_used_mb']}MB  GPU1={a['gpu1_used_mb']}MB")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"[OK] Saved to: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
