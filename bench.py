#!/usr/bin/env python3
"""Ollama Benchmark CLI Tool - Benchmark all locally installed Ollama models."""

import argparse
import json
import sys
import time
from typing import List, Dict, Any, Optional

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


# Default Ollama settings
DEFAULT_OLLAMA_HOST = "localhost"
DEFAULT_OLLAMA_PORT = 11434
OLLAMA_TIMEOUT = 300  # 5 minutes max per request


def get_ollama_tags_url(host: str = DEFAULT_OLLAMA_HOST, port: int = DEFAULT_OLLAMA_PORT) -> str:
    """Get the Ollama tags API URL."""
    return f"http://{host}:{port}/api/tags"


def get_ollama_generate_url(host: str = DEFAULT_OLLAMA_HOST, port: int = DEFAULT_OLLAMA_PORT) -> str:
    """Get the Ollama generate API URL."""
    return f"http://{host}:{port}/api/generate"


def parse_ollama_url(url: str) -> tuple:
    """Parse an Ollama URL into host and port.

    Accepts formats like:
    - localhost:11434
    - 192.168.1.100:11434
    - http://localhost:11434
    - http://192.168.1.100:11434
    """
    url = url.strip()

    # Remove protocol prefix if present
    if url.startswith("http://"):
        url = url[7:]
    elif url.startswith("https://"):
        url = url[8:]

    # Remove trailing slash
    url = url.rstrip("/")

    # Split host and port
    if ":" in url:
        parts = url.rsplit(":", 1)
        host = parts[0]
        try:
            port = int(parts[1])
        except ValueError:
            port = DEFAULT_OLLAMA_PORT
    else:
        host = url
        port = DEFAULT_OLLAMA_PORT

    return host, port


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
        print(f"❌ Error: Cannot connect to Ollama at http://{host}:{port}")
        print("   Make sure Ollama is running: ollama serve")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"❌ Error discovering models: {e}")
        sys.exit(1)


def run_prompt(model: str, prompt: Prompt, verbose: bool = False,
               host: str = DEFAULT_OLLAMA_HOST, port: int = DEFAULT_OLLAMA_PORT) -> PromptResult:
    """Run a single prompt against a model and measure response time."""
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

        return PromptResult(
            category=prompt.category,
            prompt=prompt.text,
            response_time_ms=elapsed_ms,
            response=result_text
        )
    except requests.exceptions.Timeout:
        print(f"    ⚠️  Timeout for {model} on {prompt.category} prompt")
        return PromptResult(
            category=prompt.category,
            prompt=prompt.text,
            response_time_ms=OLLAMA_TIMEOUT * 1000,
            response="[TIMEOUT]"
        )
    except requests.exceptions.RequestException as e:
        print(f"    ⚠️  Error: {e}")
        return PromptResult(
            category=prompt.category,
            prompt=prompt.text,
            response_time_ms=0,
            response=f"[ERROR: {e}]"
        )


def benchmark_model(model: str, verbose: bool = False,
                    host: str = DEFAULT_OLLAMA_HOST, port: int = DEFAULT_OLLAMA_PORT) -> ModelResult:
    """Run all test prompts against a single model."""
    print(f"\n🔄 Benchmarking model: {model}")

    results: List[PromptResult] = []

    for i, prompt in enumerate(TEST_PROMPTS, 1):
        if verbose:
            print(f"  [{i}/{len(TEST_PROMPTS)}] ", end="")
        result = run_prompt(model, prompt, verbose, host, port)
        results.append(result)

        if not verbose:
            print(".", end="", flush=True)

    if not verbose:
        print(" ✓")

    return calculate_model_result(model, results)


def run_benchmark(
    models: Optional[List[str]] = None,
    verbose: bool = False,
    detailed: bool = False,
    output_file: str = "results.json",
    host: str = DEFAULT_OLLAMA_HOST,
    port: int = DEFAULT_OLLAMA_PORT
) -> List[ModelResult]:
    """Run the full benchmark suite."""
    # Discover models if not provided
    if models is None:
        models = discover_models(host, port)

    if not models:
        print("❌ No models found. Install models with: ollama pull <model>")
        sys.exit(1)

    print(f"\n📋 Found {len(models)} model(s): {', '.join(models)}")
    print(f"🚀 Running {len(TEST_PROMPTS)} prompts per model...\n")

    results: List[ModelResult] = []
    failed_models: List[str] = []

    for model in models:
        try:
            result = benchmark_model(model, verbose, host, port)
            results.append(result)
        except Exception as e:
            # Keep benchmark running even if one model fails hard
            print(f"\n⚠️  Failed benchmarking model '{model}': {e}")
            print("   Skipping and continuing with remaining models...")
            failed_models.append(model)

    if not results:
        print("❌ All selected models failed to benchmark. No results to display/save.")
        return []

    # Display results
    display_results_table(results)

    if detailed:
        display_detailed_table(results)

    # Save to JSON
    saved_file = save_results_to_json(results, output_file)
    print(f"💾 Results saved to: {saved_file}")

    if failed_models:
        print(f"⚠️  Skipped {len(failed_models)} model(s) due to errors: {', '.join(failed_models)}")

    return results


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Benchmark Ollama models with various test prompts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ollama-bench                    # Benchmark all installed models
  ollama-bench -m llama2 mistral  # Benchmark specific models
  ollama-bench -v                 # Verbose output
  ollama-bench -d                 # Show detailed per-prompt results
  ollama-bench -o my_results.json # Save to custom output file
  ollama-bench --host 192.168.1.100 --port 11434  # Custom Ollama server
        """
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
        "--url",
        metavar="URL",
        help="Ollama server URL (e.g., localhost:11434 or http://192.168.1.100:11434)"
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List all installed models and exit"
    )

    args = parser.parse_args()

    # Parse URL if provided
    host = args.host
    port = args.port
    if args.url:
        host, port = parse_ollama_url(args.url)

    # List models mode
    if args.list_models:
        models = discover_models(host, port)
        if models:
            print(f"\n📦 Installed models on {host}:{port}:")
            for model in models:
                print(f"  - {model}")
        else:
            print(f"\n❌ No models installed on {host}:{port}")
        return

    # Run benchmark
    run_benchmark(
        models=args.models,
        verbose=args.verbose,
        detailed=args.detailed,
        output_file=args.output,
        host=host,
        port=port
    )


if __name__ == "__main__":
    main()
