#!/usr/bin/env python3
"""Ollama API Benchmark - Benchmark all Ollama models with improved metrics."""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import List, Dict, Optional
import requests

from prompts import TEST_PROMPTS, Prompt
from report import (
    PromptResult,
    ModelResult,
    calculate_model_result,
    display_results_table,
    display_detailed_table,
    save_results_to_json,
)

# Version
VERSION = "2.0.0"

# Default Ollama settings
DEFAULT_OLLAMA_HOST = "localhost"
DEFAULT_OLLAMA_PORT = 11434
OLLAMA_TIMEOUT = 600  # 10 minutes max per request


def write_progress(progress_file: Optional[str], data: dict) -> None:
    """Atomically write progress to a JSON file so external monitors can track us.

    Progress writing must never break the benchmark itself, so all errors
    are swallowed. Atomic via write-to-temp + os.replace so a monitor never
    reads a half-written file.
    """
    if not progress_file:
        return
    try:
        tmp = str(progress_file) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, progress_file)
    except Exception:
        pass


def get_ollama_tags_url(host: str = DEFAULT_OLLAMA_HOST, port: int = DEFAULT_OLLAMA_PORT) -> str:
    """Get the Ollama tags API URL."""
    return f"http://{host}:{port}/api/tags"


def get_ollama_generate_url(host: str = DEFAULT_OLLAMA_HOST, port: int = DEFAULT_OLLAMA_PORT) -> str:
    """Get the Ollama generate API URL."""
    return f"http://{host}:{port}/api/generate"


def discover_models(host: str = DEFAULT_OLLAMA_HOST, port: int = DEFAULT_OLLAMA_PORT) -> List[str]:
    """Discover all locally installed Ollama models."""
    tags_url = get_ollama_tags_url(host, port)

    try:
        response = requests.get(tags_url, timeout=10)
        response.raise_for_status()
        data = response.json()

        models = []
        for model in data.get("models", []):
            name = model.get("name", "")
            if name:
                models.append(name)

        return sorted(models)
    except requests.exceptions.ConnectionError:
        print(f"[ERR] Cannot connect to Ollama at http://{host}:{port}")
        print("      Make sure Ollama is running: ollama serve")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"[ERR] Error discovering models: {e}")
        sys.exit(1)


def run_prompt(
    model: str,
    prompt: Prompt,
    host: str = DEFAULT_OLLAMA_HOST,
    port: int = DEFAULT_OLLAMA_PORT,
    verbose: bool = False
) -> PromptResult:
    """Run a single prompt against a model via Ollama API."""
    generate_url = get_ollama_generate_url(host, port)

    payload = {
        "model": model,
        "prompt": prompt.text,
        "stream": False
    }

    if verbose:
        print(f"    Running [{prompt.category}] prompt...")

    start_time = time.perf_counter()

    try:
        response = requests.post(
            generate_url,
            json=payload,
            timeout=OLLAMA_TIMEOUT
        )
        response.raise_for_status()

        end_time = time.perf_counter()
        elapsed_ms = (end_time - start_time) * 1000

        data = response.json()
        result_text = data.get("response", "")

        # Extract token info from Ollama response
        eval_count = data.get("eval_count", 0)
        prompt_eval_ms = data.get("prompt_eval_duration", 0) / 1_000_000  # Convert ns to ms
        eval_ms = data.get("eval_duration", 0) / 1_000_000

        # Calculate tokens per second (eval tokens / eval time)
        tokens_per_sec = eval_count / (eval_ms / 1000) if eval_ms > 0 else 0

        return PromptResult(
            category=prompt.category,
            prompt=prompt.text,
            response_time_ms=elapsed_ms,
            response=result_text,
            tokens_generated=eval_count,
            tokens_per_sec=tokens_per_sec
        )

    except requests.exceptions.Timeout:
        print(f"    [WARN] Timeout for {model} on {prompt.category} prompt")
        return PromptResult(
            category=prompt.category,
            prompt=prompt.text,
            response_time_ms=OLLAMA_TIMEOUT * 1000,
            response="[TIMEOUT]",
            tokens_generated=0,
            tokens_per_sec=0
        )
    except requests.exceptions.RequestException as e:
        print(f"    [FAIL] Error: {e}")
        return PromptResult(
            category=prompt.category,
            prompt=prompt.text,
            response_time_ms=0,
            response=f"[ERROR: {e}]",
            tokens_generated=0,
            tokens_per_sec=0
        )


def benchmark_model(
    model: str,
    verbose: bool = False,
    host: str = DEFAULT_OLLAMA_HOST,
    port: int = DEFAULT_OLLAMA_PORT,
    progress_cb=None
) -> ModelResult:
    """Run all test prompts against a single model."""
    print(f"\n[*] Benchmarking model: {model}")

    load_start = time.perf_counter()

    # Try to load the model by running a simple prompt
    try:
        response = requests.post(
            get_ollama_generate_url(host, port),
            json={"model": model, "prompt": "test", "stream": False},
            timeout=OLLAMA_TIMEOUT
        )
        response.raise_for_status()
    except Exception as e:
        print(f"\n[FAIL] Failed to load model '{model}': {e}")
        raise

    load_time_ms = (time.perf_counter() - load_start) * 1000

    results: List[PromptResult] = []

    for i, prompt in enumerate(TEST_PROMPTS, 1):
        if verbose:
            print(f"  [{i}/{len(TEST_PROMPTS)}] ", end="")
        result = run_prompt(model, prompt, host, port, verbose)
        results.append(result)

        if progress_cb:
            progress_cb(i)

        if not verbose:
            print(".", end="", flush=True)

    if not verbose:
        print(" [OK]")

    model_result = calculate_model_result(model, results)
    model_result.load_time_ms = load_time_ms
    return model_result


def run_benchmark(
    models: Optional[List[str]] = None,
    verbose: bool = False,
    detailed: bool = False,
    output_file: str = "results.json",
    host: str = DEFAULT_OLLAMA_HOST,
    port: int = DEFAULT_OLLAMA_PORT,
    skip_errors: bool = True,
    progress_file: Optional[str] = None
) -> List[ModelResult]:
    """Run the full benchmark suite."""

    # Discover models if not provided
    if models is None:
        models = discover_models(host, port)

    if not models:
        print("[ERR] No models found. Pull models with: ollama pull <model>")
        sys.exit(1)

    print(f"\n[INFO] Found {len(models)} model(s): {', '.join(models)}")
    print(f"[INFO] Running {len(TEST_PROMPTS)} prompts per model...\n")

    # Progress state for external monitors (e.g. the dashboard). The PID lets
    # a monitor distinguish "still running" from "crashed mid-run".
    progress = {
        "pid": os.getpid(),
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "models": models,
        "models_total": len(models),
        "models_done": 0,
        "current_model": None,
        "current_prompt": 0,
        "prompts_per_model": len(TEST_PROMPTS),
        "completed_models": [],
        "failed_models": [],
        "output_file": output_file,
    }
    write_progress(progress_file, progress)

    results: List[ModelResult] = []
    failed_models: List[str] = []

    for model in models:
        progress["current_model"] = model
        progress["current_prompt"] = 0
        write_progress(progress_file, progress)

        def on_prompt_done(prompt_idx, _progress=progress):
            _progress["current_prompt"] = prompt_idx
            write_progress(progress_file, _progress)

        try:
            result = benchmark_model(model, verbose, host, port, progress_cb=on_prompt_done)
            results.append(result)
            progress["completed_models"].append(model)
            # Save partial results after every model so a crash mid-run
            # doesn't lose everything benchmarked so far
            try:
                save_results_to_json(results, output_file)
            except Exception:
                pass
        except Exception as e:
            print(f"\n[WARN] Failed benchmarking model '{model}': {e}")
            failed_models.append(model)
            progress["failed_models"].append(model)
            if not skip_errors:
                progress["status"] = "failed"
                write_progress(progress_file, progress)
                sys.exit(1)
        finally:
            progress["models_done"] += 1
            progress["current_prompt"] = 0
            write_progress(progress_file, progress)

    progress["status"] = "completed"
    progress["current_model"] = None
    progress["finished_at"] = datetime.now().isoformat()
    write_progress(progress_file, progress)

    if not results:
        print("[ERR] All selected models failed to benchmark. No results to display/save.")
        return []

    # Display results
    display_results_table(results)

    if detailed:
        display_detailed_table(results)

    # Save to JSON
    saved_file = save_results_to_json(results, output_file)
    print(f"[OK] Results saved to: {saved_file}")

    if failed_models:
        print(f"[WARN] Skipped {len(failed_models)} model(s) due to errors: {', '.join(failed_models)}")

    return results


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Benchmark Ollama models with improved metrics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ollama-api-bench                              # Benchmark all installed models
  ollama-api-bench -m llama2 mistral            # Benchmark specific models
  ollama-api-bench -v                           # Verbose output
  ollama-api-bench -d                           # Show detailed per-prompt results
  ollama-api-bench -o my_results.json           # Save to custom file
  ollama-api-bench --host 192.168.1.100 --port 11434  # Custom Ollama server
        """
    )

    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version number and exit"
    )
    parser.add_argument(
        "-m", "--models",
        nargs="+",
        metavar="MODEL",
        help="Specific models to benchmark (default: all installed)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show verbose output during benchmarking"
    )
    parser.add_argument(
        "-d", "--detailed",
        action="store_true",
        help="Show detailed per-prompt results table"
    )
    parser.add_argument(
        "-o", "--output",
        default="results.json",
        metavar="FILE",
        help="Output JSON file (default: results.json)"
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_OLLAMA_HOST,
        metavar="HOST",
        help=f"Ollama server host (default: {DEFAULT_OLLAMA_HOST})"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_OLLAMA_PORT,
        metavar="PORT",
        help=f"Ollama server port (default: {DEFAULT_OLLAMA_PORT})"
    )
    parser.add_argument(
        "--skip-errors",
        action="store_true",
        default=True,
        help="Skip models that fail to load (default: True)"
    )
    parser.add_argument(
        "--progress-file",
        default=None,
        metavar="FILE",
        help="Write live progress to this JSON file (for external monitors)"
    )

    args = parser.parse_args()

    # Handle --version flag early
    if args.version:
        print(f"ollama-api-bench {VERSION}")
        sys.exit(0)

    # Run benchmark
    run_benchmark(
        models=args.models,
        verbose=args.verbose,
        detailed=args.detailed,
        output_file=args.output,
        host=args.host,
        port=args.port,
        skip_errors=args.skip_errors,
        progress_file=args.progress_file
    )


if __name__ == "__main__":
    main()
