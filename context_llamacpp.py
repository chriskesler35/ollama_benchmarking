#!/usr/bin/env python3
"""Context-window profiler via llama.cpp (dual-GPU), with Ollama fallback.

Same philosophy as the speed/accuracy/optimize phases: for each context size it
starts llama-server with that -c and the weights split across both GPUs, then
measures throughput + per-GPU VRAM. The largest -c that successfully loads is the
real max context you can SERVE that model with on this hardware - on llama.cpp a
too-big context is a hard load failure, which is exactly the ceiling we want.

- Oversized models (weights don't fit on GPU at all) -> clear "won't fit" message.
- Models whose GGUF llama.cpp can't load (gemma3/glm) -> fall back to Ollama.

Single model per invocation (the dashboard loops over the selected models), so
its CLI mirrors the old context_profiler.py: `context_llamacpp.py <model> -o out.json`.
"""
import argparse
import json
import sys
import time
from typing import Optional

from gguf_resolver import resolve_gguf
from gpu_split import optimal_tensor_split, check_fit, gpu_used_mb
from llama_server import start_server, stop_server, SERVER_HOST, SERVER_PORT
from ollama_backend import ollama_context_rate, ollama_unload
import requests

CONTEXT_SIZES = [512, 1024, 2048, 4096, 8192, 16384]
SLOWDOWN_THRESHOLD = 0.5   # >50% throughput drop vs baseline = unsafe
N_PREDICT = 96
REQUEST_TIMEOUT = 180


def llama_rate(ctx_used_for_warmup=True) -> Optional[float]:
    """One generation on the running llama-server; return tokens/sec."""
    try:
        r = requests.post(
            f"http://{SERVER_HOST}:{SERVER_PORT}/completion",
            json={"prompt": "Write a short paragraph about the ocean.",
                  "n_predict": N_PREDICT, "temperature": 0, "ignore_eos": True},
            timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        t = r.json().get("timings", {})
        if (t.get("predicted_n") or 0) < 8:
            return None
        return t.get("predicted_per_second")
    except Exception:
        return None


def analyze(test_results: list) -> dict:
    """Find the max safe context from the per-size results."""
    ok = [r for r in test_results if r.get("status") == "success"]
    if not ok:
        return {"max_safe_context": None, "recommendation": "No context size succeeded"}

    baseline = ok[0]["tokens_per_sec"] or 0
    max_safe = ok[0]["context_size"]
    slowdown_point = None
    for r in ok:
        if baseline and r["tokens_per_sec"] < baseline * (1 - SLOWDOWN_THRESHOLD):
            slowdown_point = r["context_size"]
            break
        max_safe = r["context_size"]

    oom_point = next((r["context_size"] for r in test_results
                      if r.get("status") in ("oom", "load_failed")), None)

    if slowdown_point:
        rec = f"Max ~{max_safe} tokens (throughput drops sharply at {slowdown_point})"
    elif oom_point:
        rec = f"Max {max_safe} tokens (won't load at {oom_point} - out of VRAM)"
    else:
        rec = f"Max {max_safe}+ tokens (no limit hit up to {max_safe})"

    return {"max_safe_context": max_safe, "baseline_tokens_per_sec": round(baseline, 1),
            "slowdown_point": slowdown_point, "oom_point": oom_point,
            "recommendation": rec}


def profile_llamacpp(model: str, gguf: str, tensor_split: str, verbose: bool) -> list:
    """Sweep context sizes via llama-server. Returns per-size results.

    Returns None (no list) if the very first/smallest size fails to LOAD for a
    non-OOM reason - that signals an incompatible GGUF, so the caller falls back
    to Ollama.
    """
    results = []
    for idx, ctx in enumerate(CONTEXT_SIZES):
        if verbose:
            print(f"    ctx={ctx} ...", end=" ", flush=True)
        server, err = start_server(gguf, tensor_split, ctx, 1)
        if not server:
            if err["kind"] == "incompatible":
                # GGUF llama.cpp can't load at all -> caller falls back to Ollama
                if verbose:
                    print("incompatible GGUF -> Ollama fallback")
                return None
            # ran out of VRAM at this context -> this is the ceiling
            if verbose:
                print("won't load (out of VRAM)")
            results.append({"context_size": ctx, "status": "oom",
                            "tokens_per_sec": 0, "gpu_memory": None})
            break
        try:
            llama_rate()  # warm up
            rate = llama_rate() or 0
            gpu = gpu_used_mb()
            results.append({"context_size": ctx, "status": "success",
                            "tokens_per_sec": round(rate, 1), "gpu_memory": gpu})
            if verbose:
                print(f"{round(rate,1)} tok/s  "
                      f"GPU0={gpu.get('gpu0_used_mb','?')} GPU1={gpu.get('gpu1_used_mb','?')}")
        finally:
            stop_server(server)
            time.sleep(2)
    return results


def profile_ollama(model: str, verbose: bool) -> list:
    """Fallback: sweep context sizes via Ollama (for GGUFs llama.cpp can't load)."""
    results = []
    try:
        for ctx in CONTEXT_SIZES:
            if verbose:
                print(f"    ctx={ctx} (Ollama) ...", end=" ", flush=True)
            try:
                rate = ollama_context_rate(model, ctx)
                gpu = gpu_used_mb()
                results.append({"context_size": ctx, "status": "success",
                                "tokens_per_sec": rate, "gpu_memory": gpu})
                if verbose:
                    print(f"{rate} tok/s")
            except Exception as e:
                results.append({"context_size": ctx, "status": "error",
                                "tokens_per_sec": 0, "error": str(e)[:120]})
                if verbose:
                    print("error")
    finally:
        ollama_unload(model)  # free VRAM right away
    return results


def profile_model(model: str, verbose: bool) -> dict:
    print(f"\n[*] Context profile for: {model}")
    gguf = resolve_gguf(model)
    if not gguf:
        return {"model": model, "engine": "llama.cpp", "status": "no_gguf",
                "note": "Could not resolve GGUF", "test_results": [],
                "analysis": {"recommendation": "No GGUF found"}}

    fit = check_fit(gguf)
    if fit.get("checked") and not fit["fits"]:
        print(f"    [WON'T FIT] {fit['reason']}")
        return {"model": model, "engine": "llama.cpp", "status": "too_large",
                "note": fit["reason"], "test_results": [],
                "analysis": {"status": "too_large", "note": fit["reason"],
                             "recommendation": fit["reason"]}}

    tensor_split = optimal_tensor_split()
    print(f"    tensor-split {tensor_split}")
    results = profile_llamacpp(model, gguf, tensor_split, verbose)

    engine = "llama.cpp"
    note = None
    if results is None:
        print("    -> falling back to Ollama")
        engine = "ollama"
        note = "Profiled via Ollama - GGUF not loadable by llama.cpp."
        results = profile_ollama(model, verbose)

    out = {"model": model, "engine": engine, "tensor_split": tensor_split,
           "test_results": results, "analysis": analyze(results)}
    if note:
        out["note"] = note
        out.pop("tensor_split", None)
    return out


def main():
    p = argparse.ArgumentParser(description="Context-window profiler via llama.cpp")
    p.add_argument("model", help="Ollama model name")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("-o", "--output", help="Output JSON file")
    args = p.parse_args()

    result = profile_model(args.model, args.verbose)
    print(f"\n[RESULTS] {args.model} ({result.get('engine')})")
    print(f"  {result['analysis'].get('recommendation')}")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"[OK] Saved to: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
