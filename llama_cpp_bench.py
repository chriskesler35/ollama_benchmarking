#!/usr/bin/env python3
"""Llama.cpp Benchmark CLI Tool - Benchmark GGUF models with GPU splitting."""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from llama_cpp import Llama

from prompts import TEST_PROMPTS, Prompt
from gpu_utils import get_gpu_split, get_available_gguf_models, parse_model_size
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

# Default settings
DEFAULT_GGUF_DIR = r"E:\ollama\models"
DEFAULT_N_THREADS = 8
DEFAULT_N_CTX = 2048


def find_models(models_dir: Path) -> List[Path]:
    """Discover all GGUF models in a directory."""
    exts = (".gguf", ".bin", ".ggml")
    models = [p for p in models_dir.rglob("*") if p.suffix.lower() in exts]
    models.sort()
    return models


def load_model_with_gpu_split(
    model_path: str,
    gpu_split: Optional[Tuple[int, int]] = None,
    n_threads: int = DEFAULT_N_THREADS,
    n_ctx: int = DEFAULT_N_CTX,
    verbose: bool = False
) -> Tuple[Llama, float]:
    """Load a model with GPU splitting.

    Args:
        model_path: Path to GGUF file
        gpu_split: Tuple of (gpu0_layers, gpu1_layers). If None, auto-detect.
        n_threads: Number of CPU threads
        n_ctx: Context window size
        verbose: Verbose output

    Returns:
        Tuple of (Llama model instance, load_time_ms)
    """
    if not os.path.isfile(model_path):
        raise FileNotFoundError(f"Model not found: {model_path}")

    # Auto-detect split if not provided
    if gpu_split is None:
        file_size_mb = os.path.getsize(model_path) / (1024 * 1024)
        if file_size_mb < 5000:
            total_layers = 32
        elif file_size_mb < 9000:
            total_layers = 40
        else:
            total_layers = 60

        gpu_split = get_gpu_split(os.path.basename(model_path), total_layers)

    gpu0_layers, gpu1_layers = gpu_split

    if verbose:
        print(f"  Loading with GPU split: GPU0={gpu0_layers} layers, GPU1={gpu1_layers} layers")

    start_time = time.perf_counter()

    try:
        llm = Llama(
            model_path=model_path,
            n_threads=n_threads,
            n_ctx=n_ctx,
            n_gpu_layers=gpu0_layers + gpu1_layers,
            main_gpu=0,
            tensor_split=[
                gpu0_layers / (gpu0_layers + gpu1_layers),
                gpu1_layers / (gpu0_layers + gpu1_layers)
            ],
            verbose=False
        )

        load_time_ms = (time.perf_counter() - start_time) * 1000

        if verbose:
            print(f"  [OK] Model loaded in {load_time_ms:.1f}ms")

        return llm, load_time_ms

    except Exception as e:
        raise RuntimeError(f"Failed to load model {model_path}: {e}")


def run_prompt(
    llm: Llama,
    prompt: Prompt,
    max_tokens: int = 256,
    verbose: bool = False
) -> PromptResult:
    """Run a single prompt against a model and measure metrics."""
    if verbose:
        print(f"    Running [{prompt.category}] prompt...")

    start_time = time.perf_counter()

    try:
        response = llm(
            prompt.text,
            max_tokens=max_tokens,
            temperature=0.7,
            top_p=0.95,
            echo=False
        )

        end_time = time.perf_counter()
        elapsed_ms = (end_time - start_time) * 1000

        result_text = response.get('choices', [{}])[0].get('text', '')

        usage = response.get('usage', {})
        tokens_generated = usage.get('completion_tokens', 0)
        tokens_per_sec = tokens_generated / (elapsed_ms / 1000) if elapsed_ms > 0 else 0

        return PromptResult(
            category=prompt.category,
            prompt=prompt.text,
            response_time_ms=elapsed_ms,
            response=result_text,
            tokens_generated=tokens_generated,
            tokens_per_sec=tokens_per_sec
        )

    except Exception as e:
        print(f"    [WARN] Error: {e}")
        return PromptResult(
            category=prompt.category,
            prompt=prompt.text,
            response_time_ms=0,
            response=f"[ERROR: {e}]",
            tokens_generated=0,
            tokens_per_sec=0
        )


def benchmark_model(
    model_path: str,
    model_name: str,
    gpu_split: Optional[Tuple[int, int]] = None,
    verbose: bool = False
) -> ModelResult:
    """Run all test prompts against a single model."""
    print(f"\n[*] Benchmarking model: {model_name}")

    try:
        llm, load_time_ms = load_model_with_gpu_split(model_path, gpu_split, verbose=verbose)

        results: List[PromptResult] = []

        for i, prompt in enumerate(TEST_PROMPTS, 1):
            if verbose:
                print(f"  [{i}/{len(TEST_PROMPTS)}] ", end="")
            result = run_prompt(llm, prompt, verbose=verbose)
            results.append(result)

            if not verbose:
                print(".", end="", flush=True)

        if not verbose:
            print(" [OK]")

        del llm

        model_result = calculate_model_result(model_name, results)
        model_result.load_time_ms = load_time_ms
        return model_result

    except Exception as e:
        print(f"\n[FAIL] Failed benchmarking model '{model_name}': {e}")
        raise


def run_benchmark(
    models: Optional[List[str]] = None,
    gguf_dir: str = DEFAULT_GGUF_DIR,
    gpu_splits: Optional[Dict[str, Tuple[int, int]]] = None,
    verbose: bool = False,
    detailed: bool = False,
    output_file: str = "results.json"
) -> List[ModelResult]:
    """Run the full benchmark suite."""

    # Discover models if not provided
    if models is None:
        models_dir = Path(gguf_dir)
        if not models_dir.exists():
            print(f"[ERR] Models directory not found: {models_dir}")
            sys.exit(1)

        model_paths = find_models(models_dir)
        if not model_paths:
            print(f"[ERR] No GGUF models found in {models_dir}")
            sys.exit(1)

        models = [p.name for p in model_paths]

    if not models:
        print("[ERR] No models specified or found.")
        sys.exit(1)

    print(f"\n[INFO] Found {len(models)} model(s): {', '.join(models)}")
    print(f"[INFO] Running {len(TEST_PROMPTS)} prompts per model...\n")

    results: List[ModelResult] = []
    failed_models: List[str] = []

    for model_name in models:
        try:
            # Resolve model path
            models_dir = Path(gguf_dir)
            model_path = None
            for p in models_dir.rglob("*"):
                if p.name == model_name:
                    model_path = str(p)
                    break

            if model_path is None:
                print(f"\n[WARN] Model not found: {model_name}")
                failed_models.append(model_name)
                continue

            # Get GPU split for this model
            gpu_split = None
            if gpu_splits and model_name in gpu_splits:
                gpu_split = gpu_splits[model_name]

            # Run benchmark
            result = benchmark_model(model_path, model_name, gpu_split, verbose)
            results.append(result)

        except Exception as e:
            print(f"\n[FAIL] Failed benchmarking model '{model_name}': {e}")
            failed_models.append(model_name)

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
        description="Benchmark GGUF models with GPU splitting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  llama-cpp-bench                                # Benchmark all GGUF models
  llama-cpp-bench -m llama2-7b mistral-7b       # Benchmark specific models
  llama-cpp-bench -v                             # Verbose output
  llama-cpp-bench -d                             # Show detailed per-prompt results
  llama-cpp-bench --gguf-dir /path/to/models    # Custom GGUF directory
  llama-cpp-bench --gpu-split llama2-7b:1,1 mistral-14b:1,3  # Custom GPU splits
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
        help="Specific models to benchmark (default: all GGUF files in gguf_dir)"
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
        "--gguf-dir",
        default=DEFAULT_GGUF_DIR,
        metavar="DIR",
        help=f"Directory containing GGUF files (default: {DEFAULT_GGUF_DIR})"
    )
    parser.add_argument(
        "--gpu-split",
        nargs="+",
        metavar="MODEL:GPU0,GPU1",
        help="Custom GPU layer splits (e.g., llama2-7b:16,16 mistral-14b:10,30)"
    )

    args = parser.parse_args()

    # Handle --version flag early
    if args.version:
        print(f"llama-cpp-bench {VERSION}")
        sys.exit(0)

    # Parse custom GPU splits
    gpu_splits = {}
    if args.gpu_split:
        for split_spec in args.gpu_split:
            if ":" in split_spec:
                model, split = split_spec.split(":", 1)
                try:
                    gpu0, gpu1 = map(int, split.split(","))
                    gpu_splits[model] = (gpu0, gpu1)
                except ValueError:
                    print(f"❌ Invalid GPU split format: {split_spec}")
                    print("   Use format: model_name:gpu0_layers,gpu1_layers")
                    sys.exit(1)

    # Run benchmark
    run_benchmark(
        models=args.models,
        gguf_dir=args.gguf_dir,
        gpu_splits=gpu_splits,
        verbose=args.verbose,
        detailed=args.detailed,
        output_file=args.output
    )


if __name__ == "__main__":
    main()
