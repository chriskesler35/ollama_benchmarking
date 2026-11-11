#!/usr/bin/env python3
"""Accuracy Benchmark - scores model output correctness, not just speed.

Every task has an objectively checkable answer (executed unit tests, exact
numbers, multiple choice letters, structural checks). Runs at temperature 0
for reproducibility. Writes live progress to a JSON file and saves partial
results after every model, so nothing is lost on a crash.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import List, Dict, Optional
import requests

from accuracy_prompts import ACCURACY_TASKS, CATEGORIES, score_task, clean_response

VERSION = "1.0.0"

DEFAULT_OLLAMA_HOST = "localhost"
DEFAULT_OLLAMA_PORT = 11434
OLLAMA_TIMEOUT = 180  # backstop; the token cap below is the real limiter
MAX_OUTPUT_TOKENS = 1024  # caps runaway generations (reasoning models loop without this)


def write_progress(progress_file: Optional[str], data: dict) -> None:
    """Atomically write progress so external monitors can track us."""
    if not progress_file:
        return
    try:
        tmp = str(progress_file) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, progress_file)
    except Exception:
        pass


def discover_models(host: str, port: int, include_cloud: bool = False) -> List[str]:
    """Discover local Ollama models. Cloud-proxied models are excluded by
    default - they aren't local inference and burn remote quota."""
    try:
        response = requests.get(f"http://{host}:{port}/api/tags", timeout=10)
        response.raise_for_status()
        models = sorted(m["name"] for m in response.json().get("models", []) if m.get("name"))
    except requests.exceptions.RequestException as e:
        print(f"[ERR] Cannot reach Ollama at {host}:{port}: {e}")
        sys.exit(1)

    if not include_cloud:
        skipped = [m for m in models if m.endswith(":cloud") or "-cloud" in m]
        if skipped:
            print(f"[INFO] Excluding {len(skipped)} cloud model(s): {', '.join(skipped)}")
        models = [m for m in models if m not in skipped]

    # Embedding models can't generate text
    embed_markers = ("embed", "bge-", "minilm")
    skipped = [m for m in models if any(s in m.lower() for s in embed_markers)]
    if skipped:
        print(f"[INFO] Excluding {len(skipped)} embedding model(s): {', '.join(skipped)}")
    models = [m for m in models if m not in skipped]

    # Vision models error on the text-only /api/generate endpoint (500s),
    # producing meaningless 0% scores - exclude them.
    vision_markers = ("vision", "llava", "-vl", "bakllava", "moondream", "minicpm-v")
    skipped = [m for m in models if any(s in m.lower() for s in vision_markers)]
    if skipped:
        print(f"[INFO] Excluding {len(skipped)} vision model(s): {', '.join(skipped)}")
    models = [m for m in models if m not in skipped]

    return models


def ask_model(model: str, prompt: str, host: str, port: int) -> str:
    """Run one prompt at temperature 0, return the response text."""
    response = requests.post(
        f"http://{host}:{port}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0, "num_predict": MAX_OUTPUT_TOKENS},
        },
        timeout=OLLAMA_TIMEOUT,
    )
    response.raise_for_status()
    return response.json().get("response", "")


def benchmark_model_accuracy(model: str, host: str, port: int,
                             verbose: bool = False, progress_cb=None) -> dict:
    """Run all accuracy tasks against one model and score them."""
    print(f"\n[*] Testing accuracy: {model}")

    task_results = []
    for i, task in enumerate(ACCURACY_TASKS, 1):
        try:
            raw = ask_model(model, task.prompt, host, port)
            passed, detail = score_task(task, raw)
        except requests.exceptions.Timeout:
            raw, passed, detail = "[TIMEOUT]", False, "request timed out"
        except requests.exceptions.RequestException as e:
            raw, passed, detail = f"[ERROR: {e}]", False, str(e)[:200]

        task_results.append({
            "task_id": task.id,
            "category": task.category,
            "passed": passed,
            "detail": detail,
            "response": clean_response(raw)[:4000],
        })

        if progress_cb:
            progress_cb(i)
        if verbose:
            print(f"  [{i}/{len(ACCURACY_TASKS)}] {task.id}: {'PASS' if passed else 'FAIL'} ({detail})")
        else:
            print("P" if passed else "F", end="", flush=True)

    if not verbose:
        print(" [OK]")

    # Aggregate
    by_category = {}
    for cat in CATEGORIES:
        cat_results = [r for r in task_results if r["category"] == cat]
        if cat_results:
            by_category[cat] = {
                "passed": sum(r["passed"] for r in cat_results),
                "total": len(cat_results),
                "accuracy": round(100 * sum(r["passed"] for r in cat_results) / len(cat_results), 1),
            }

    total_passed = sum(r["passed"] for r in task_results)
    return {
        "model_name": model,
        "accuracy": round(100 * total_passed / len(task_results), 1),
        "passed": total_passed,
        "total": len(task_results),
        "by_category": by_category,
        "task_results": task_results,
    }


def save_results(results: List[dict], output_file: str) -> str:
    output = {
        "timestamp": datetime.now().isoformat(),
        "total_models": len(results),
        "tasks_per_model": len(ACCURACY_TASKS),
        "results": sorted(results, key=lambda r: r["accuracy"], reverse=True),
    }
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2)
    return output_file


def load_completed(resume_file: Optional[str]) -> List[dict]:
    """Load already-scored models from a prior results file (for --resume)."""
    if not resume_file or not os.path.exists(resume_file):
        return []
    try:
        with open(resume_file) as f:
            return json.load(f).get("results", [])
    except Exception:
        return []


def run_accuracy_benchmark(models: Optional[List[str]] = None,
                           verbose: bool = False,
                           output_file: str = "accuracy_results.json",
                           host: str = DEFAULT_OLLAMA_HOST,
                           port: int = DEFAULT_OLLAMA_PORT,
                           include_cloud: bool = False,
                           progress_file: Optional[str] = None,
                           resume_file: Optional[str] = None) -> List[dict]:
    if models is None:
        models = discover_models(host, port, include_cloud)

    if not models:
        print("[ERR] No models to test.")
        sys.exit(1)

    # Resume: carry over already-scored models, skip re-testing them
    results = load_completed(resume_file)
    done_names = {r["model_name"] for r in results}
    if done_names:
        models = [m for m in models if m not in done_names]
        print(f"[INFO] Resume: {len(done_names)} model(s) already scored, "
              f"{len(models)} remaining")

    if not models:
        print("[INFO] All models already scored. Nothing to do.")
        save_results(results, output_file)
        return results

    print(f"\n[INFO] Accuracy-testing {len(models)} model(s), "
          f"{len(ACCURACY_TASKS)} tasks each (temperature 0)\n")

    # Counters reflect the TRUE total (resumed + remaining) so the dashboard
    # shows real overall progress, not just this session's slice.
    total_all = len(done_names) + len(models)
    progress = {
        "pid": os.getpid(),
        "status": "running",
        "kind": "accuracy",
        "started_at": datetime.now().isoformat(),
        "models": models,
        "models_total": total_all,
        "models_done": len(done_names),
        "current_model": None,
        "current_prompt": 0,
        "prompts_per_model": len(ACCURACY_TASKS),
        "completed_models": list(done_names),
        "failed_models": [],
        "output_file": output_file,
    }
    write_progress(progress_file, progress)

    # results already holds the resumed models - keep appending to it
    for model in models:
        progress["current_model"] = model
        progress["current_prompt"] = 0
        write_progress(progress_file, progress)

        def on_task_done(task_idx, _progress=progress):
            _progress["current_prompt"] = task_idx
            write_progress(progress_file, _progress)

        try:
            result = benchmark_model_accuracy(model, host, port, verbose, on_task_done)
            results.append(result)
            progress["completed_models"].append(model)
            # Crash-safe: save after every model
            try:
                save_results(results, output_file)
            except Exception:
                pass
        except Exception as e:
            print(f"\n[WARN] Failed accuracy test for '{model}': {e}")
            progress["failed_models"].append(model)
        finally:
            progress["models_done"] += 1
            progress["current_prompt"] = 0
            write_progress(progress_file, progress)

    progress["status"] = "completed"
    progress["current_model"] = None
    progress["finished_at"] = datetime.now().isoformat()
    write_progress(progress_file, progress)

    if results:
        print(f"\n{'=' * 70}")
        print(f"{'ACCURACY RESULTS':^70}")
        print(f"{'=' * 70}")
        print(f"{'Model':<40} {'Overall':>8} {'Code':>6} {'Math':>6} {'MC':>6} {'Inst':>6}")
        print("-" * 70)
        for r in sorted(results, key=lambda x: x["accuracy"], reverse=True):
            cats = r["by_category"]
            print(f"{r['model_name']:<40} {r['accuracy']:>7.1f}% "
                  f"{cats.get('coding', {}).get('accuracy', 0):>5.0f}% "
                  f"{cats.get('math', {}).get('accuracy', 0):>5.0f}% "
                  f"{cats.get('multiple_choice', {}).get('accuracy', 0):>5.0f}% "
                  f"{cats.get('instruction', {}).get('accuracy', 0):>5.0f}%")

        saved = save_results(results, output_file)
        print(f"\n[OK] Results saved to: {saved}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Benchmark Ollama model accuracy")
    parser.add_argument("--version", action="store_true", help="Show version and exit")
    parser.add_argument("-m", "--models", nargs="+", metavar="MODEL",
                        help="Specific models to test (default: all local models)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Per-task output")
    parser.add_argument("-o", "--output", default="accuracy_results.json", metavar="FILE")
    parser.add_argument("--host", default=DEFAULT_OLLAMA_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_OLLAMA_PORT)
    parser.add_argument("--include-cloud", action="store_true",
                        help="Also test cloud-proxied models (off by default)")
    parser.add_argument("--progress-file", default=None, metavar="FILE",
                        help="Write live progress to this JSON file")
    parser.add_argument("--resume", default=None, metavar="FILE",
                        help="Skip models already scored in this prior results file")
    args = parser.parse_args()

    if args.version:
        print(f"accuracy-bench {VERSION}")
        sys.exit(0)

    run_accuracy_benchmark(
        models=args.models,
        verbose=args.verbose,
        output_file=args.output,
        host=args.host,
        port=args.port,
        include_cloud=args.include_cloud,
        progress_file=args.progress_file,
        resume_file=args.resume,
    )


if __name__ == "__main__":
    main()
