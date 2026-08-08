#!/usr/bin/env python3
"""Accuracy benchmark via llama.cpp (dual-GPU), not Ollama.

Same tasks and scorers as accuracy_bench.py, but each model is served by
llama-server with its weights SPLIT ACROSS BOTH GPUs (--tensor-split). Prompts
go through the OpenAI-compatible /v1/chat/completions endpoint so llama.cpp
applies the model's chat template (raw /completion would skip templating and
tank the scores).

Scores should match the Ollama run (same weights/engine); the wins are a single
consistent engine and big models running fully on GPU instead of spilling to CPU.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from typing import List, Dict, Optional
import requests

from accuracy_prompts import ACCURACY_TASKS, CATEGORIES, score_task, clean_response
from gguf_resolver import resolve_gguf
from gpu_split import optimal_tensor_split, check_fit
from llama_server import start_server, stop_server, SERVER_HOST, SERVER_PORT
from ollama_backend import ollama_generate_text, ollama_unload

VERSION = "1.0.0"

SERVER_CTX = 4096
MAX_TOKENS = 1024  # caps runaway reasoning models
# Cloud reasoning models spend this budget on `thinking` BEFORE emitting
# `response`, and only `response` is scored - so a budget that runs out
# mid-thought returns an empty string and scores 0, indistinguishable from a
# wrong answer. Local models are capped lower because their cost is wall-clock
# across ~29 models; cloud cost is per-token and a higher ceiling is only
# charged if actually used (well-behaved models stop at done_reason=stop).
CLOUD_MAX_TOKENS = 4096
HEALTH_TIMEOUT = 240
REQUEST_TIMEOUT = 180

# Models that fail to benchmark are blacklisted (skipped on future runs) and
# flagged for deletion. Files live next to this script.
_HERE = os.path.dirname(os.path.abspath(__file__))
BLACKLIST_FILE = os.path.join(_HERE, "blacklist.json")
TO_DELETE_FILE = os.path.join(_HERE, "to_delete.txt")


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


def load_blacklist() -> Dict[str, dict]:
    """Return {model_name: {reason, blacklisted_at}} of models to skip."""
    try:
        with open(BLACKLIST_FILE) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def add_to_blacklist(model: str, reason: str) -> None:
    """Blacklist a failed model and append a reviewable 'ollama rm' line.

    Idempotent — re-blacklisting an existing model just refreshes its reason
    and won't add a duplicate deletion line.
    """
    bl = load_blacklist()
    is_new = model not in bl
    bl[model] = {"reason": reason[:200], "blacklisted_at": datetime.now().isoformat()}
    try:
        tmp = BLACKLIST_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(bl, f, indent=2)
        os.replace(tmp, BLACKLIST_FILE)
    except Exception as e:
        print(f"[WARN] Could not write blacklist: {e}")
        return
    if is_new:
        try:
            with open(TO_DELETE_FILE, "a", encoding="utf-8") as f:
                f.write(f"ollama rm {model}    # {reason[:80]}\n")
        except Exception:
            pass
    print(f"    [blacklisted] {model} -> {reason[:60]}")


def discover_models(host: str, port: int) -> List[str]:
    """Local Ollama models that resolve to a GGUF, minus cloud/embed/vision."""
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

    return [n for n in names if keep(n)]


def ask_model(prompt: str) -> str:
    """Chat-completions request - applies the model's template via llama.cpp."""
    r = requests.post(
        f"http://{SERVER_HOST}:{SERVER_PORT}/v1/chat/completions",
        json={"messages": [{"role": "user", "content": prompt}],
              "temperature": 0, "max_tokens": MAX_TOKENS},
        timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def benchmark_model_accuracy(model: str, gguf: str, verbose: bool, progress_cb=None) -> Optional[dict]:
    print(f"\n[*] Accuracy (llama.cpp) for: {model}")

    # Won't-fit pre-check: don't waste time loading a model that can't fit on GPU.
    fit = check_fit(gguf)
    if fit.get("checked") and not fit["fits"]:
        print(f"    [WON'T FIT] {fit['reason']}")
        return {"model_name": model, "engine": "llama.cpp", "status": "too_large",
                "note": fit["reason"], "accuracy": None,
                "model_gb": fit["model_gb"], "budget_gb": fit["budget_gb"],
                "by_category": {}, "task_results": []}

    tensor_split = optimal_tensor_split()
    print(f"    tensor-split {tensor_split} (weighted by free VRAM)")
    server, err = start_server(gguf, tensor_split, SERVER_CTX, 1)

    engine = "llama.cpp"
    note = None
    if server:
        ask = ask_model  # llama.cpp chat-completions
    else:
        # llama.cpp can't run it - fall back to Ollama (which can)
        print(f"    [llama.cpp failed: {err['reason'][:60]}...] -> falling back to Ollama")
        engine = "ollama"
        note = "Scored via Ollama - GGUF not loadable by llama.cpp."
        ask = lambda prompt: ollama_generate_text(model, prompt, MAX_TOKENS)

    try:
        task_results = run_tasks(ask, verbose, progress_cb)
    finally:
        if server:
            stop_server(server)
            time.sleep(2)
        else:
            ollama_unload(model)  # free VRAM before the next model loads

    by_category = {}
    for cat in CATEGORIES:
        cr = [r for r in task_results if r["category"] == cat]
        if cr:
            p = sum(r["passed"] for r in cr)
            by_category[cat] = {"passed": p, "total": len(cr),
                                "accuracy": round(100 * p / len(cr), 1)}
    total_passed = sum(r["passed"] for r in task_results)
    result = {"model_name": model, "engine": engine, "tensor_split": tensor_split,
              "accuracy": round(100 * total_passed / len(task_results), 1),
              "passed": total_passed, "total": len(task_results),
              "by_category": by_category, "task_results": task_results}
    if note:
        result["note"] = note
        result.pop("tensor_split", None)
    return result


def benchmark_model_accuracy_cloud(model: str, verbose: bool, progress_cb=None) -> dict:
    """Cloud model: no GGUF, no VRAM, scored straight through Ollama's cloud proxy.
    Every task here spends subscription credits, not local compute."""
    print(f"\n[*] Accuracy (cloud) for: {model}")
    ask = lambda prompt: ollama_generate_text(model, prompt, CLOUD_MAX_TOKENS)
    task_results = run_tasks(ask, verbose, progress_cb)

    by_category = {}
    for cat in CATEGORIES:
        cr = [r for r in task_results if r["category"] == cat]
        if cr:
            p = sum(r["passed"] for r in cr)
            by_category[cat] = {"passed": p, "total": len(cr),
                                "accuracy": round(100 * p / len(cr), 1)}
    total_passed = sum(r["passed"] for r in task_results)
    return {"model_name": model, "engine": "ollama-cloud",
            "accuracy": round(100 * total_passed / len(task_results), 1),
            "passed": total_passed, "total": len(task_results),
            "by_category": by_category, "task_results": task_results,
            "note": "Scored via Ollama's cloud proxy - spent subscription credits, "
                    "not local compute."}


def run_tasks(ask, verbose: bool, progress_cb=None) -> list:
    """Run all accuracy tasks using the given ask(prompt)->text function."""
    task_results = []
    for i, task in enumerate(ACCURACY_TASKS, 1):
        try:
            raw = ask(task.prompt)
            passed, detail = score_task(task, raw)
        except Exception as e:
            raw, passed, detail = f"[ERROR: {e}]", False, str(e)[:160]
        task_results.append({"task_id": task.id, "category": task.category,
                             "passed": passed, "detail": detail,
                             "response": clean_response(raw)[:4000]})
        if progress_cb:
            progress_cb(i)
        if verbose:
            print(f"  [{i}/{len(ACCURACY_TASKS)}] {task.id}: {'PASS' if passed else 'FAIL'}")
        else:
            print("P" if passed else "F", end="", flush=True)
    if not verbose:
        print(" [OK]")
    return task_results


def _acc_key(r):
    a = r.get("accuracy")
    return a if a is not None else -1  # oversized/failed models sort to the bottom


def save_results(results: List[dict], output_file: str) -> str:
    output = {"timestamp": datetime.now().isoformat(), "engine": "llama.cpp",
              "total_models": len(results), "tasks_per_model": len(ACCURACY_TASKS),
              "results": sorted(results, key=_acc_key, reverse=True)}
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
    # Cloud models are explicit opt-in only - never pulled in by discovery, and
    # never blacklisted (blacklisting is for "doesn't run on my hardware").
    all_models = list(models) + [m for m in cloud_models if m not in models]
    if not all_models:
        print("[ERR] No models to test.")
        sys.exit(1)

    blacklist = load_blacklist()
    if blacklist:
        skipped = [m for m in all_models if m in blacklist and m not in cloud_set]
        if skipped:
            all_models = [m for m in all_models if m not in skipped]
            print(f"[INFO] Skipping {len(skipped)} blacklisted model(s): {', '.join(skipped)}")

    results = load_completed(resume_file)
    done = {r["model_name"] for r in results}
    if done:
        all_models = [m for m in all_models if m not in done]
        print(f"[INFO] Resume: {len(done)} already scored, {len(all_models)} remaining")
    if not all_models:
        save_results(results, output_file)
        return results

    n_cloud = len([m for m in all_models if m in cloud_set])
    print(f"\n[INFO] Accuracy via llama.cpp (dual-GPU) for {len(all_models) - n_cloud} model(s)"
          + (f", + {n_cloud} cloud model(s)" if n_cloud else "")
          + f", {len(ACCURACY_TASKS)} tasks each\n")

    total_all = len(done) + len(all_models)
    progress = {"pid": os.getpid(), "status": "running", "kind": "accuracy_llamacpp",
                "engine": "llama.cpp", "started_at": datetime.now().isoformat(),
                "models": all_models, "models_total": total_all, "models_done": len(done),
                "current_model": None, "current_prompt": 0,
                "prompts_per_model": len(ACCURACY_TASKS),
                "completed_models": list(done), "failed_models": [],
                "output_file": output_file}
    write_progress(progress_file, progress)

    for model in all_models:
        progress["current_model"] = model
        progress["current_prompt"] = 0
        write_progress(progress_file, progress)

        def on_task(idx, _p=progress):
            _p["current_prompt"] = idx
            write_progress(progress_file, _p)

        result = None
        fail_reason = None
        if model in cloud_set:
            try:
                result = benchmark_model_accuracy_cloud(model, verbose, on_task)
            except Exception as e:
                fail_reason = str(e)
                print(f"\n[WARN] Cloud request failed for {model}: {e}")
        else:
            gguf = resolve_gguf(model)
            if not gguf:
                fail_reason = "no GGUF resolved"
                print(f"\n[WARN] No GGUF for {model} - skipping")
            else:
                try:
                    result = benchmark_model_accuracy(model, gguf, verbose, on_task)
                except Exception as e:
                    fail_reason = str(e)
                    print(f"\n[WARN] Failed {model}: {e}")

        if result:
            results.append(result)
            progress["completed_models"].append(model)
            try:
                save_results(results, output_file)
            except Exception:
                pass
        else:
            progress["failed_models"].append(model)
            if model not in cloud_set:
                add_to_blacklist(model, fail_reason or "benchmark returned no result")
        progress["models_done"] += 1
        progress["current_prompt"] = 0
        write_progress(progress_file, progress)

    progress["status"] = "completed"
    progress["current_model"] = None
    progress["finished_at"] = datetime.now().isoformat()
    write_progress(progress_file, progress)

    if results:
        print(f"\n{'ACCURACY (llama.cpp)':^60}")
        for r in sorted(results, key=_acc_key, reverse=True):
            if r.get("accuracy") is None:
                print(f"  {r['model_name']:<40} {'--':>6}  ({r.get('status', 'n/a')})")
            else:
                print(f"  {r['model_name']:<40} {r['accuracy']:>6.1f}%")
        save_results(results, output_file)
        print(f"\n[OK] Saved to: {output_file}")
    return results


def main():
    p = argparse.ArgumentParser(description="Accuracy benchmark via llama.cpp dual-GPU")
    p.add_argument("--version", action="store_true")
    p.add_argument("-m", "--models", nargs="+")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("-o", "--output", default="accuracy_llamacpp_results.json")
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=11434)
    p.add_argument("--progress-file", default=None)
    p.add_argument("--resume", default=None)
    p.add_argument("--cloud-models", nargs="+", default=None,
                   help="Explicit opt-in: also score these ':cloud' models via "
                        "Ollama's hosted proxy. Spends subscription credits.")
    p.add_argument("--cloud-only", action="store_true",
                   help="Score ONLY --cloud-models; skip local model discovery.")
    args = p.parse_args()
    if args.version:
        print(f"accuracy-llamacpp {VERSION}")
        sys.exit(0)
    run(args.models, args.verbose, args.output, args.host, args.port,
        args.progress_file, args.resume, cloud_models=args.cloud_models,
        cloud_only=args.cloud_only)


if __name__ == "__main__":
    main()
