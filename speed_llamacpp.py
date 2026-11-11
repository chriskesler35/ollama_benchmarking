#!/usr/bin/env python3
"""Speed benchmark via llama.cpp (dual-GPU), not Ollama.

Measures single-stream generation throughput (tokens/sec) for each model served
by llama-server with its weights split across both GPUs. This reflects real
serving speed - notably faster than Ollama for large models, which Ollama tends
to partly spill to CPU.

Outputs the same shape as the Ollama speed phase (results_phase1_*.json), so the
scatter and Phase 1 table work unchanged; results merge newest-per-model.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from typing import List, Optional
import requests

from gguf_resolver import resolve_gguf
from gpu_split import optimal_tensor_split, check_fit
from llama_server import start_server, stop_server, SERVER_HOST, SERVER_PORT
from ollama_backend import ollama_speed, ollama_unload, supports_generate

VERSION = "1.0.0"

SERVER_CTX = 4096
N_PREDICT = 128
SAMPLES = 3              # timed generations to average
HEALTH_TIMEOUT = 240
REQUEST_TIMEOUT = 180


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


def discover_models(host: str, port: int) -> List[str]:
    try:
        r = requests.get(f"http://{host}:{port}/api/tags", timeout=10)
        r.raise_for_status()
        names = sorted(m["name"] for m in r.json().get("models", []) if m.get("name"))
    except requests.exceptions.RequestException as e:
        print(f"[ERR] Cannot reach Ollama at {host}:{port}: {e}")
        sys.exit(1)

    def keep(n: str) -> bool:
        nl = n.lower()
        if n.endswith(":cloud") or "-cloud" in n:
            return False
        if any(s in nl for s in ("embed", "bge-", "minilm")):
            return False
        if any(s in nl for s in ("vision", "llava", "-vl", "bakllava",
                                 "moondream", "minicpm-v")):
            return False
        return True

    # Also drop models Ollama reports as non-generative (e.g. 'decision'- or
    # 'embedding'-only), which 400 on /api/generate and can't be benchmarked.
    return [n for n in names if keep(n) and supports_generate(n, host, port)]


def gen_sample():
    """One generation; return (tokens_per_sec, generation_ms) from llama.cpp timings.

    ignore_eos forces the model to emit the full N_PREDICT tokens - otherwise a
    model that stops after 1 token (e.g. tinyllama) yields a bogus rate like
    1,000,000 tok/s. Samples with too few tokens are discarded as unreliable.
    """
    try:
        r = requests.post(
            f"http://{SERVER_HOST}:{SERVER_PORT}/completion",
            json={"prompt": "Write a short paragraph about the ocean.",
                  "n_predict": N_PREDICT, "temperature": 0, "ignore_eos": True},
            timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        t = r.json().get("timings", {})
        if (t.get("predicted_n") or 0) < 8:
            return None, None  # too few tokens -> rate is meaningless
        return t.get("predicted_per_second"), t.get("predicted_ms")
    except Exception:
        return None, None


def measure_speed(model: str, gguf: str, verbose: bool, progress_cb=None) -> dict:
    fit = check_fit(gguf)
    if fit.get("checked") and not fit["fits"]:
        print(f"    [WON'T FIT] {fit['reason']}")
        return {"model_name": model, "engine": "llama.cpp", "status": "too_large",
                "note": fit["reason"], "avg_tokens_per_sec": None,
                "model_gb": fit["model_gb"], "budget_gb": fit["budget_gb"]}

    tensor_split = optimal_tensor_split()
    print(f"    tensor-split {tensor_split}")
    t_load = time.perf_counter()
    server, err = start_server(gguf, tensor_split, SERVER_CTX, 1)
    load_ms = round((time.perf_counter() - t_load) * 1000)
    if not server:
        kind = err["kind"]
        reason = err["reason"]
        if kind == "oom":
            # Passed the size pre-check but OOM'd with KV-cache overhead included.
            # Don't fall back to Ollama - report it as too_large so the user knows.
            print(f"    [OOM] {reason}")
            return {"model_name": model, "engine": "llama.cpp", "status": "too_large",
                    "avg_tokens_per_sec": None,
                    "note": "Passed size pre-check but OOM'd during load (KV cache overhead). "
                            "Won't fit on this hardware."}
        # Incompatible GGUF (or unknown) -> fall back to Ollama
        print(f"    [llama.cpp failed: {reason[:60]}...] -> falling back to Ollama")
        try:
            s = ollama_speed(model)
            print(f"    {s['tps']} tok/s (via Ollama fallback)")
            return {"model_name": model, "engine": "ollama", "status": "ok",
                    "avg_tokens_per_sec": s["tps"], "avg_time_ms": s["avg_time_ms"],
                    "load_time_ms": s["load_time_ms"],
                    "note": "Measured via Ollama - GGUF not loadable by llama.cpp."}
        except Exception as e:
            return {"model_name": model, "engine": "ollama", "status": "failed",
                    "avg_tokens_per_sec": None,
                    "note": f"llama.cpp failed ({reason[:80]}); Ollama also failed: {e}"}
        finally:
            ollama_unload(model)  # free VRAM before the next model loads
    try:
        gen_sample()  # warm up (load + first-token cost excluded from samples)
        rates, times = [], []
        for i in range(SAMPLES):
            rt, ms = gen_sample()
            if rt:
                rates.append(rt)
            if ms:
                times.append(ms)
            if progress_cb:
                progress_cb(i + 1)
        avg = round(sum(rates) / len(rates), 1) if rates else 0
        avg_ms = round(sum(times) / len(times)) if times else None
        print(f"    {avg} tok/s (single stream, avg of {len(rates)})")
    finally:
        stop_server(server)
        time.sleep(2)

    return {"model_name": model, "engine": "llama.cpp", "status": "ok",
            "tensor_split": tensor_split, "avg_tokens_per_sec": avg,
            "avg_time_ms": avg_ms, "load_time_ms": load_ms}


def measure_speed_cloud(model: str, verbose: bool) -> dict:
    """Cloud model: no GGUF, no VRAM, no llama.cpp attempt - measured straight
    through Ollama's cloud proxy. Speed reflects network + hosted throughput,
    not this rig's hardware, and every call here spends subscription credits.
    """
    print(f"    (cloud) measuring via Ollama proxy")
    try:
        s = ollama_speed(model)
        print(f"    {s['tps']} tok/s (cloud, from {s.get('timing_basis')})")
        # Cloud responses omit eval_duration, so tok/s is derived from
        # total_duration - i.e. end-to-end wall clock, not pure generation rate.
        basis_note = (" Derived from total request time (cloud responses omit "
                      "per-stage timings), so it includes network and queueing."
                      if s.get("timing_basis") == "total_duration" else "")
        return {"model_name": model, "engine": "ollama-cloud", "status": "ok",
                "avg_tokens_per_sec": s["tps"], "avg_time_ms": s["avg_time_ms"],
                "load_time_ms": s["load_time_ms"],
                "timing_basis": s.get("timing_basis"),
                "note": "Cloud model - speed reflects network + hosted throughput, "
                        "not local hardware." + basis_note}
    except Exception as e:
        return {"model_name": model, "engine": "ollama-cloud", "status": "error",
                "avg_tokens_per_sec": None, "note": f"Cloud request failed: {e}"}


def _spd_key(r):
    v = r.get("avg_tokens_per_sec")
    return v if v is not None else -1


def save_results(results: List[dict], output_file: str) -> str:
    output = {"timestamp": datetime.now().isoformat(), "engine": "llama.cpp",
              "total_models": len(results),
              "results": sorted(results, key=_spd_key, reverse=True)}
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2)
    return output_file


def load_completed(resume_file: Optional[str]) -> List[dict]:
    if not resume_file or not os.path.exists(resume_file):
        return []
    try:
        with open(resume_file) as f:
            return json.load(f).get("results", [])
    except Exception:
        return []


def run(models, verbose, output_file, host, port, progress_file, resume_file,
        cloud_models=None, cloud_only=False):
    if models is None:
        # cloud_only: score ONLY the named cloud models. Without this, an
        # unspecified --models means "discover every local model", which turns
        # a quick 3-cloud-model check into a full multi-hour local sweep.
        models = [] if cloud_only else discover_models(host, port)
    cloud_models = cloud_models or []
    cloud_set = set(cloud_models)
    # Cloud models are explicit opt-in only - never pulled in by discovery.
    all_models = list(models) + [m for m in cloud_models if m not in models]
    if not all_models:
        print("[ERR] No models to test.")
        sys.exit(1)

    results = load_completed(resume_file)
    done = {r["model_name"] for r in results}
    if done:
        all_models = [m for m in all_models if m not in done]
        print(f"[INFO] Resume: {len(done)} already measured, {len(all_models)} remaining")
    if not all_models:
        save_results(results, output_file)
        return results

    n_cloud = len([m for m in all_models if m in cloud_set])
    print(f"\n[INFO] Speed via llama.cpp (dual-GPU) for {len(all_models) - n_cloud} model(s)"
          + (f", + {n_cloud} cloud model(s)" if n_cloud else "") + "\n")

    total_all = len(done) + len(all_models)
    progress = {"pid": os.getpid(), "status": "running", "kind": "speed_llamacpp",
                "engine": "llama.cpp", "started_at": datetime.now().isoformat(),
                "models": all_models, "models_total": total_all, "models_done": len(done),
                "current_model": None, "current_prompt": 0, "prompts_per_model": SAMPLES,
                "completed_models": list(done), "failed_models": [],
                "output_file": output_file}
    write_progress(progress_file, progress)

    for model in all_models:
        progress["current_model"] = model
        progress["current_prompt"] = 0
        write_progress(progress_file, progress)

        def on_sample(i, _p=progress):
            _p["current_prompt"] = i
            write_progress(progress_file, _p)

        if model in cloud_set:
            print(f"\n[*] Speed (cloud) for: {model}")
            results.append(measure_speed_cloud(model, verbose))
        else:
            print(f"\n[*] Speed (llama.cpp) for: {model}")
            gguf = resolve_gguf(model)
            if not gguf:
                print(f"    [WARN] No GGUF for {model} - skipping")
                results.append({"model_name": model, "engine": "llama.cpp",
                                "status": "no_gguf", "note": "Could not resolve GGUF",
                                "avg_tokens_per_sec": None})
            else:
                try:
                    results.append(measure_speed(model, gguf, verbose, on_sample))
                except Exception as e:
                    print(f"    [WARN] Failed {model}: {e}")
                    results.append({"model_name": model, "engine": "llama.cpp",
                                    "status": "error", "note": str(e)[:160],
                                    "avg_tokens_per_sec": None})

        progress["completed_models"].append(model)
        progress["models_done"] += 1
        progress["current_prompt"] = 0
        write_progress(progress_file, progress)
        try:
            save_results(results, output_file)
        except Exception:
            pass

    progress["status"] = "completed"
    progress["current_model"] = None
    progress["finished_at"] = datetime.now().isoformat()
    write_progress(progress_file, progress)

    print(f"\n{'SPEED (llama.cpp)':^56}")
    for r in sorted(results, key=_spd_key, reverse=True):
        if r.get("avg_tokens_per_sec") is None:
            print(f"  {r['model_name']:<40} {'--':>6}  ({r.get('status')})")
        else:
            print(f"  {r['model_name']:<40} {r['avg_tokens_per_sec']:>6.1f} tok/s")
    save_results(results, output_file)
    print(f"\n[OK] Saved to: {output_file}")
    return results


def main():
    p = argparse.ArgumentParser(description="Speed benchmark via llama.cpp dual-GPU")
    p.add_argument("--version", action="store_true")
    p.add_argument("-m", "--models", nargs="+")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("-o", "--output", default="speed_llamacpp_results.json")
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=11434)
    p.add_argument("--progress-file", default=None)
    p.add_argument("--resume", default=None)
    p.add_argument("--cloud-models", nargs="+", default=None,
                   help="Explicit opt-in: also measure these ':cloud' models via "
                        "Ollama's hosted proxy. Spends subscription credits.")
    p.add_argument("--cloud-only", action="store_true",
                   help="Measure ONLY --cloud-models; skip local model discovery.")
    args = p.parse_args()
    if args.version:
        print(f"speed-llamacpp {VERSION}")
        sys.exit(0)
    run(args.models, args.verbose, args.output, args.host, args.port,
        args.progress_file, args.resume, cloud_models=args.cloud_models,
        cloud_only=args.cloud_only)


if __name__ == "__main__":
    main()
