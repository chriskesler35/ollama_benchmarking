#!/usr/bin/env python3
"""llama.cpp Server Optimizer - dual-GPU, real models from Ollama's GGUF blobs.

Phase 3 done right: for each model it launches llama-server with the weights
SPLIT ACROSS BOTH GPUs (--tensor-split) and sweeps --parallel x --ctx-size,
sending genuinely concurrent requests and measuring aggregate throughput plus
per-GPU VRAM. That tells you the best --parallel / --ctx-size for serving each
model on your dual 3060s, and confirms both cards are actually used.

Models are resolved from Ollama's blob store, so it works on every model you
already have - no separate GGUF downloads.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import requests

try:
    import pynvml
    PYNVML_AVAILABLE = True
except ImportError:
    PYNVML_AVAILABLE = False

from prompts import TEST_PROMPTS
from gguf_resolver import resolve_gguf
from gpu_split import optimal_tensor_split, check_fit
from llama_server import start_server as _start_server, stop_server, SERVER_HOST, SERVER_PORT

REQUEST_TIMEOUT = 300
NUM_PREDICT = 128

PARALLEL_VALUES = [1, 2, 4]
CONTEXT_SIZES = [4096, 8192]
DEFAULT_TENSOR_SPLIT = "auto"  # "auto" = weight by free VRAM (see gpu_split.py)


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
        return out
    except Exception:
        return None


def start_server(gguf: str, parallel: int, ctx_per_slot: int, tensor_split: str):
    """Start llama-server split across both GPUs. Returns (proc, error_reason).

    -c is the TOTAL context shared across --parallel slots, so we set it to
    ctx_per_slot * parallel to give each concurrent slot the target window.
    """
    total_ctx = ctx_per_slot * parallel
    return _start_server(gguf, tensor_split, total_ctx, parallel)


def one_completion() -> Dict:
    try:
        r = requests.post(
            f"http://{SERVER_HOST}:{SERVER_PORT}/completion",
            json={"prompt": TEST_PROMPTS[0].text, "n_predict": NUM_PREDICT,
                  "temperature": 0, "ignore_eos": True},
            timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        d = r.json()
        tokens = (d.get("tokens_predicted")
                  or d.get("timings", {}).get("predicted_n")
                  or len(d.get("content", "").split()))
        return {"tokens": tokens, "ok": True}
    except Exception as e:
        return {"tokens": 0, "ok": False, "error": str(e)[:120]}


def measure(parallel: int) -> Dict:
    """Fire `parallel` concurrent completions; aggregate throughput + GPU VRAM."""
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        results = list(pool.map(lambda _: one_completion(), range(parallel)))
    elapsed = time.perf_counter() - start
    ok = [r for r in results if r["ok"]]
    total_tokens = sum(r["tokens"] for r in ok)
    return {
        "aggregate_tokens_per_sec": round(total_tokens / elapsed, 1) if elapsed > 0 else 0,
        "successful_requests": len(ok),
        "elapsed_sec": round(elapsed, 2),
    }


def test_configuration(gguf: str, parallel: int, ctx: int,
                       tensor_split: str, verbose: bool) -> Optional[Dict]:
    server, err = start_server(gguf, parallel, ctx, tensor_split)
    if not server:
        reason = err["reason"]
        if verbose:
            print(f"    parallel={parallel} ctx={ctx}: {reason}")
        return {
            "concurrency": parallel, "ctx_size": ctx,
            "aggregate_tokens_per_sec": 0, "successful_requests": 0,
            "total_requests": parallel, "status": "server_failed",
            "note": reason, "gpu_memory": None,
        }
    try:
        one_completion()  # warm up the slots so load time doesn't pollute timing
        gpu_loaded = gpu_mem()
        m = measure(parallel)
        if verbose:
            print(f"    parallel={parallel} ctx={ctx}: "
                  f"{m['aggregate_tokens_per_sec']} tok/s aggregate "
                  f"({m['successful_requests']}/{parallel} ok)  "
                  f"GPU0={gpu_loaded.get('gpu0_used_mb') if gpu_loaded else '?'}MB "
                  f"GPU1={gpu_loaded.get('gpu1_used_mb') if gpu_loaded else '?'}MB")
        return {
            "concurrency": parallel, "ctx_size": ctx,
            "aggregate_tokens_per_sec": m["aggregate_tokens_per_sec"],
            "successful_requests": m["successful_requests"],
            "total_requests": parallel, "status": "ok",
            "gpu_memory": gpu_loaded,
        }
    finally:
        stop_server(server)
        time.sleep(2)  # let VRAM free before the next config


def optimize_model(model: str, tensor_split: str, verbose: bool,
                   parallel_values=None, context_sizes=None,
                   progress_file: Optional[str] = None) -> Dict:
    parallel_values = parallel_values or PARALLEL_VALUES
    context_sizes = context_sizes or CONTEXT_SIZES

    gguf = resolve_gguf(model)
    if not gguf:
        return {"model": model, "all_results": [],
                "analysis": {"recommendation": f"Could not resolve GGUF for {model}"}}

    # Won't-fit pre-check
    fit = check_fit(gguf)
    if fit.get("checked") and not fit["fits"]:
        print(f"\n[WON'T FIT] {model}: {fit['reason']}")
        return {"model": model, "gguf": gguf, "all_results": [],
                "analysis": {"status": "too_large", "note": fit["reason"],
                             "model_gb": fit["model_gb"], "budget_gb": fit["budget_gb"],
                             "recommendation": f"Won't fit: {fit['reason']}"}}

    # "auto" -> weight the split by each GPU's free VRAM (GPU0 has display overhead)
    if tensor_split in (None, "auto"):
        tensor_split = optimal_tensor_split()

    print(f"\n[*] Optimizing (llama.cpp, dual-GPU) for: {model}")
    print(f"    GGUF: {gguf}")
    print(f"    tensor-split: {tensor_split} (weighted by free VRAM)")

    results = []
    progress = {"pid": os.getpid(), "status": "running", "kind": "llama_optimize",
                "current_model": model, "started_at": datetime.now().isoformat()}
    write_progress(progress_file, progress)

    for ctx in context_sizes:
        for par in parallel_values:
            results.append(test_configuration(gguf, par, ctx, tensor_split, verbose))

    usable = [r for r in results if r["successful_requests"] > 0]
    if not usable:
        # Surface the actual reason from a failed config (e.g. build incompatibility)
        note = next((r.get("note") for r in results if r.get("note")),
                    "All configs failed to run.")
        analysis = {"status": "load_failed", "note": note,
                    "recommendation": note}
    else:
        best = max(usable, key=lambda r: r["aggregate_tokens_per_sec"])
        gm = best.get("gpu_memory") or {}
        analysis = {
            "optimal_parallel": best["concurrency"],
            "optimal_ctx_size": best["ctx_size"],
            "optimal_aggregate_tps": best["aggregate_tokens_per_sec"],
            "tensor_split": tensor_split,
            "gpu0_used_mb": gm.get("gpu0_used_mb"),
            "gpu1_used_mb": gm.get("gpu1_used_mb"),
            "recommendation": (f"--parallel {best['concurrency']} "
                               f"--ctx-size {best['ctx_size']} -ts {tensor_split} "
                               f"({best['aggregate_tokens_per_sec']} tok/s aggregate)"),
        }

    progress["status"] = "completed"
    progress["finished_at"] = datetime.now().isoformat()
    write_progress(progress_file, progress)

    return {"model": model, "gguf": gguf, "tensor_split": tensor_split,
            "all_results": results, "analysis": analysis}


def main():
    p = argparse.ArgumentParser(description="Optimize llama.cpp dual-GPU server settings")
    p.add_argument("model", help="Ollama model name or path to a .gguf file")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("-o", "--output", help="Output JSON file")
    p.add_argument("--tensor-split", default=DEFAULT_TENSOR_SPLIT,
                   help="Proportion per GPU, e.g. 0.5,0.5 (default) or 0.45,0.55")
    p.add_argument("--parallel", nargs="+", type=int, default=PARALLEL_VALUES)
    p.add_argument("--ctx-size", nargs="+", type=int, default=CONTEXT_SIZES)
    p.add_argument("--progress-file", default=None)
    args = p.parse_args()

    result = optimize_model(args.model, args.tensor_split, args.verbose,
                            parallel_values=args.parallel,
                            context_sizes=args.ctx_size,
                            progress_file=args.progress_file)

    print(f"\n[RESULTS] {args.model}")
    print(f"  {result['analysis']['recommendation']}")
    a = result["analysis"]
    if a.get("gpu0_used_mb") is not None:
        print(f"  GPU split at optimal: GPU0={a['gpu0_used_mb']}MB  GPU1={a['gpu1_used_mb']}MB")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"[OK] Saved to: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
