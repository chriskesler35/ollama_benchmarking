#!/usr/bin/env python3
"""Context Window Profiler - Find max safe context for models without OoM/slowdown."""

import argparse
import json
import sys
import time
from typing import List, Dict, Optional, Tuple
import requests

try:
    import pynvml
    PYNVML_AVAILABLE = True
except ImportError:
    PYNVML_AVAILABLE = False

from prompts import TEST_PROMPTS, Prompt

# Ollama settings
DEFAULT_OLLAMA_HOST = "localhost"
DEFAULT_OLLAMA_PORT = 11434
OLLAMA_TIMEOUT = 180
# Fixed, modest generation length so throughput is comparable across context
# sizes and reasoning models can't runaway-generate (which would hit timeouts).
PROFILE_NUM_PREDICT = 128

# Context window sizes to test
CONTEXT_SIZES = [512, 1024, 2048, 4096, 8192, 16384]

# Thresholds
SLOWDOWN_THRESHOLD = 0.5  # 50% drop in throughput = unsafe
MAX_VRAM_PERCENT = 0.95   # Use up to 95% of GPU VRAM


def get_gpu_memory():
    """Get current GPU memory usage for both GPUs."""
    if not PYNVML_AVAILABLE:
        return None

    try:
        pynvml.nvmlInit()
        gpu_info = {}
        for i in range(2):
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                gpu_info[f'gpu{i}'] = {
                    'used_mb': mem_info.used / (1024 ** 2),
                    'total_mb': mem_info.total / (1024 ** 2),
                    'free_mb': mem_info.free / (1024 ** 2),
                }
            except pynvml.NVMLError:
                pass
        pynvml.nvmlShutdown()
        return gpu_info
    except Exception:
        return None


def run_context_test(
    model: str,
    context_size: int,
    host: str = DEFAULT_OLLAMA_HOST,
    port: int = DEFAULT_OLLAMA_PORT,
    verbose: bool = False
) -> Optional[Dict]:
    """Test a model at a specific context window size."""

    if verbose:
        print(f"    Testing context={context_size}...", end=" ", flush=True)

    # Use a prompt that fits in the context
    test_prompt = TEST_PROMPTS[0].text

    payload = {
        "model": model,
        "prompt": test_prompt,
        "stream": False,
        "options": {
            "num_ctx": context_size,
            "num_predict": PROFILE_NUM_PREDICT,
        }
    }

    # Measure GPU before
    gpu_before = get_gpu_memory()

    start_time = time.perf_counter()

    try:
        response = requests.post(
            f"http://{host}:{port}/api/generate",
            json=payload,
            timeout=OLLAMA_TIMEOUT
        )
        response.raise_for_status()

        end_time = time.perf_counter()
        elapsed_ms = (end_time - start_time) * 1000

        data = response.json()
        eval_count = data.get("eval_count", 0)
        eval_ms = data.get("eval_duration", 0) / 1_000_000

        tokens_per_sec = eval_count / (eval_ms / 1000) if eval_ms > 0 else 0

        # Measure GPU after
        gpu_after = get_gpu_memory()

        gpu_peak = None
        if gpu_after:
            gpu_peak = {
                'gpu0_used_mb': gpu_after.get('gpu0', {}).get('used_mb', 0),
                'gpu1_used_mb': gpu_after.get('gpu1', {}).get('used_mb', 0),
                'gpu0_total_mb': gpu_after.get('gpu0', {}).get('total_mb', 0),
                'gpu1_total_mb': gpu_after.get('gpu1', {}).get('total_mb', 0),
            }

        if verbose:
            print(f"[OK] {tokens_per_sec:.2f} tok/s, {elapsed_ms:.0f}ms")

        return {
            "context_size": context_size,
            "response_time_ms": elapsed_ms,
            "tokens_generated": eval_count,
            "tokens_per_sec": tokens_per_sec,
            "gpu_memory": gpu_peak,
            "status": "success"
        }

    except requests.exceptions.Timeout:
        if verbose:
            print("[TIMEOUT]")
        return {
            "context_size": context_size,
            "status": "timeout",
            "error": "Request timeout"
        }
    except requests.exceptions.RequestException as e:
        if "out of memory" in str(e).lower() or "cuda" in str(e).lower():
            if verbose:
                print("[OOM]")
            return {
                "context_size": context_size,
                "status": "oom",
                "error": str(e)
            }
        else:
            if verbose:
                print(f"[ERROR]")
            return {
                "context_size": context_size,
                "status": "error",
                "error": str(e)
            }
    except Exception as e:
        if verbose:
            print(f"[ERROR]")
        return {
            "context_size": context_size,
            "status": "error",
            "error": str(e)
        }


def analyze_results(results: List[Dict]) -> Dict:
    """Analyze context scaling results to find max safe context."""

    successful = [r for r in results if r.get("status") == "success"]

    if not successful:
        return {
            "max_safe_context": None,
            "reason": "No successful tests",
            "recommendation": "Model failed at all tested context sizes"
        }

    # Find baseline throughput (smallest context)
    baseline_tps = successful[0]["tokens_per_sec"]

    max_safe = successful[0]["context_size"]
    slowdown_point = None

    for result in successful:
        ctx = result["context_size"]
        tps = result["tokens_per_sec"]

        # Check for slowdown (>50% drop in throughput)
        if tps < (baseline_tps * (1 - SLOWDOWN_THRESHOLD)):
            slowdown_point = ctx
            break

        max_safe = ctx

    # Find OOM point
    oom_point = None
    for result in results:
        if result.get("status") == "oom":
            oom_point = result["context_size"]
            break

    analysis = {
        "baseline_tokens_per_sec": baseline_tps,
        "max_safe_context": max_safe,
        "slowdown_threshold": SLOWDOWN_THRESHOLD,
        "slowdown_point": slowdown_point,
        "oom_point": oom_point,
    }

    # Generate recommendation
    if slowdown_point:
        analysis["recommendation"] = f"Max {max_safe} tokens (slowdown at {slowdown_point})"
    elif oom_point:
        analysis["recommendation"] = f"Max {max_safe} tokens (OOM at {oom_point})"
    else:
        analysis["recommendation"] = f"Max {max_safe} tokens (no slowdown detected)"

    return analysis


def profile_model(
    model: str,
    context_sizes: Optional[List[int]] = None,
    verbose: bool = False,
    host: str = DEFAULT_OLLAMA_HOST,
    port: int = DEFAULT_OLLAMA_PORT
) -> Dict:
    """Profile a model across multiple context window sizes."""

    if context_sizes is None:
        context_sizes = CONTEXT_SIZES

    print(f"\n[*] Profiling context windows for: {model}")
    print(f"    Testing: {context_sizes}")

    results = []
    for ctx_size in context_sizes:
        result = run_context_test(model, ctx_size, host, port, verbose)
        results.append(result)

        # Stop if we hit OOM
        if result.get("status") == "oom":
            print(f"    Hit OOM at {ctx_size} tokens, stopping tests")
            break

    analysis = analyze_results(results)

    return {
        "model": model,
        "test_results": results,
        "analysis": analysis
    }


def main():
    """Main entry point for context profiler."""
    parser = argparse.ArgumentParser(
        description="Profile context window limits for Ollama models",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  context-profiler llama2                           # Profile llama2
  context-profiler mistral -v                       # Verbose output
  context-profiler glm-4.7-flash --max-context 8192  # Custom max context
  context-profiler llama3.1 -o profile_llama3.json  # Save results
        """
    )

    parser.add_argument(
        "model",
        help="Model to profile (Ollama model name)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "-o", "--output",
        metavar="FILE",
        help="Output JSON file"
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_OLLAMA_HOST,
        help=f"Ollama host (default: {DEFAULT_OLLAMA_HOST})"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_OLLAMA_PORT,
        help=f"Ollama port (default: {DEFAULT_OLLAMA_PORT})"
    )
    parser.add_argument(
        "--max-context",
        type=int,
        default=16384,
        help="Maximum context to test up to (default: 16384)"
    )

    args = parser.parse_args()

    # Limit context sizes based on --max-context
    context_sizes = [s for s in CONTEXT_SIZES if s <= args.max_context]

    # Profile the model
    profile_result = profile_model(
        args.model,
        context_sizes=context_sizes,
        verbose=args.verbose,
        host=args.host,
        port=args.port
    )

    # Print summary
    analysis = profile_result["analysis"]
    print(f"\n[RESULTS] Context Profiling for {args.model}")
    print(f"  Baseline throughput: {analysis.get('baseline_tokens_per_sec', 0):.2f} tok/s")
    print(f"  Max safe context: {analysis.get('max_safe_context', 'N/A')} tokens")
    if analysis.get("slowdown_point"):
        print(f"  Slowdown detected at: {analysis['slowdown_point']} tokens")
    if analysis.get("oom_point"):
        print(f"  OOM detected at: {analysis['oom_point']} tokens")
    print(f"  Recommendation: {analysis.get('recommendation', 'N/A')}")

    # Save results if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(profile_result, f, indent=2)
        print(f"\n[OK] Results saved to: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
