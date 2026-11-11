#!/usr/bin/env python3
"""llama.cpp Server Optimizer - Find optimal --parallel and --ctx-size settings."""

import argparse
import json
import subprocess
import sys
import time
import threading
from typing import List, Dict, Optional, Tuple
import requests
from pathlib import Path

try:
    import pynvml
    PYNVML_AVAILABLE = True
except ImportError:
    PYNVML_AVAILABLE = False

from prompts import TEST_PROMPTS

# Settings to test
PARALLEL_VALUES = [1, 2, 3, 4, 5]
CONTEXT_SIZES = [2048, 4096, 8192]
DEFAULT_SERVER_HOST = "localhost"
DEFAULT_SERVER_PORT = 8000

# Server startup time
SERVER_STARTUP_DELAY = 3


def get_gpu_memory() -> Optional[Dict]:
    """Get current GPU memory usage."""
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
                    'used_gb': mem_info.used / (1024 ** 3),
                    'total_gb': mem_info.total / (1024 ** 3),
                    'free_gb': mem_info.free / (1024 ** 3),
                    'used_pct': (mem_info.used / mem_info.total) * 100,
                }
            except pynvml.NVMLError:
                pass
        pynvml.nvmlShutdown()
        return gpu_info
    except Exception:
        return None


def start_server(
    model_path: str,
    parallel: int,
    ctx_size: int,
    host: str = DEFAULT_SERVER_HOST,
    port: int = DEFAULT_SERVER_PORT,
    verbose: bool = False
) -> Optional[subprocess.Popen]:
    """Start llama.cpp server with given settings."""

    if not Path(model_path).exists():
        print(f"[ERR] Model not found: {model_path}")
        return None

    cmd = [
        "llama-server",
        "-m", model_path,
        "--host", host,
        "--port", str(port),
        "--parallel", str(parallel),
        "-c", str(ctx_size),
        "-ngl", "999",  # Offload all layers to GPU
    ]

    try:
        if verbose:
            print(f"[*] Starting server: {' '.join(cmd[1:])}")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE if not verbose else None,
            stderr=subprocess.PIPE if not verbose else None,
            text=True
        )

        # Wait for server to start
        time.sleep(SERVER_STARTUP_DELAY)

        # Check if server is responding
        try:
            requests.get(f"http://{host}:{port}/health", timeout=5)
            if verbose:
                print(f"[OK] Server started on {host}:{port}")
            return process
        except requests.exceptions.RequestException:
            print(f"[WARN] Server started but not responding yet, retrying...")
            time.sleep(2)
            try:
                requests.get(f"http://{host}:{port}/health", timeout=5)
                return process
            except:
                print(f"[ERR] Server failed to start properly")
                process.terminate()
                return None

    except FileNotFoundError:
        print("[ERR] llama-server not found. Install with:")
        print("      pip install llama-cpp-python[server]")
        print("      Or use: llama-server binary from llama.cpp project")
        return None
    except Exception as e:
        print(f"[ERR] Failed to start server: {e}")
        return None


def stop_server(process: Optional[subprocess.Popen], verbose: bool = False) -> None:
    """Stop the server."""
    if process:
        try:
            process.terminate()
            process.wait(timeout=5)
            if verbose:
                print("[OK] Server stopped")
        except subprocess.TimeoutExpired:
            process.kill()
            if verbose:
                print("[WARN] Force killed server")
        except Exception as e:
            if verbose:
                print(f"[WARN] Error stopping server: {e}")


def run_concurrent_requests(
    num_concurrent: int,
    host: str = DEFAULT_SERVER_HOST,
    port: int = DEFAULT_SERVER_PORT,
    verbose: bool = False
) -> Optional[Dict]:
    """Run concurrent requests and measure throughput."""

    if verbose:
        print(f"    Running {num_concurrent} concurrent requests...", end=" ", flush=True)

    # Measure GPU before
    gpu_before = get_gpu_memory()

    start_time = time.perf_counter()

    try:
        # Use first test prompt
        prompt = TEST_PROMPTS[0].text

        # Send concurrent requests
        requests_data = []
        for i in range(num_concurrent):
            try:
                response = requests.post(
                    f"http://{host}:{port}/completion",
                    json={
                        "prompt": prompt,
                        "n_predict": 128,
                        "temperature": 0.7,
                    },
                    timeout=300
                )
                response.raise_for_status()

                data = response.json()
                requests_data.append({
                    "tokens": len(data.get("content", "").split()),
                    "status": "success"
                })
            except Exception as e:
                requests_data.append({
                    "status": "error",
                    "error": str(e)
                })

        end_time = time.perf_counter()
        elapsed_sec = end_time - start_time

        # Measure GPU after
        gpu_after = get_gpu_memory()

        successful = [r for r in requests_data if r.get("status") == "success"]
        if not successful:
            if verbose:
                print("[FAIL]")
            return None

        total_tokens = sum(r.get("tokens", 0) for r in successful)
        throughput = total_tokens / elapsed_sec if elapsed_sec > 0 else 0

        gpu_peak = None
        if gpu_after:
            gpu_peak = {
                'gpu0_used_gb': gpu_after.get('gpu0', {}).get('used_gb', 0),
                'gpu1_used_gb': gpu_after.get('gpu1', {}).get('used_gb', 0),
                'gpu0_used_pct': gpu_after.get('gpu0', {}).get('used_pct', 0),
                'gpu1_used_pct': gpu_after.get('gpu1', {}).get('used_pct', 0),
            }

        if verbose:
            print(f"[OK] {throughput:.2f} tok/s")

        return {
            "num_concurrent": num_concurrent,
            "total_time_sec": elapsed_sec,
            "total_tokens": total_tokens,
            "throughput_tokens_per_sec": throughput,
            "successful_requests": len(successful),
            "gpu_memory": gpu_peak,
        }

    except Exception as e:
        if verbose:
            print(f"[ERROR] {e}")
        return None


def test_configuration(
    model_path: str,
    parallel: int,
    ctx_size: int,
    host: str = DEFAULT_SERVER_HOST,
    port: int = DEFAULT_SERVER_PORT,
    verbose: bool = False
) -> Optional[Dict]:
    """Test a specific parallel/ctx-size configuration."""

    print(f"\n[TEST] parallel={parallel} ctx_size={ctx_size}")

    # Start server
    server = start_server(model_path, parallel, ctx_size, host, port, verbose)
    if not server:
        return None

    try:
        # Run tests with different concurrency levels
        test_results = []

        for concurrency in range(1, parallel + 1):
            result = run_concurrent_requests(concurrency, host, port, verbose)
            if result:
                test_results.append(result)
            else:
                print(f"    [WARN] Failed to test with concurrency={concurrency}")

        if not test_results:
            print("[FAIL] No successful tests for this configuration")
            return None

        # Find best throughput
        best_result = max(test_results, key=lambda r: r.get("throughput_tokens_per_sec", 0))

        return {
            "parallel": parallel,
            "ctx_size": ctx_size,
            "best_throughput": best_result.get("throughput_tokens_per_sec", 0),
            "best_at_concurrency": best_result.get("num_concurrent", 0),
            "gpu_memory": best_result.get("gpu_memory", {}),
            "all_results": test_results,
        }

    finally:
        stop_server(server, verbose)


def optimize_model(
    model_path: str,
    parallel_values: Optional[List[int]] = None,
    context_sizes: Optional[List[int]] = None,
    verbose: bool = False,
    host: str = DEFAULT_SERVER_HOST,
    port: int = DEFAULT_SERVER_PORT
) -> Dict:
    """Find optimal settings for a model."""

    if parallel_values is None:
        parallel_values = PARALLEL_VALUES
    if context_sizes is None:
        context_sizes = CONTEXT_SIZES

    model_name = Path(model_path).stem

    print(f"\n{'='*80}")
    print(f"OPTIMIZING: {model_name}")
    print(f"{'='*80}")
    print(f"Testing parallel: {parallel_values}")
    print(f"Testing ctx_size: {context_sizes}")

    results = []

    for parallel in parallel_values:
        for ctx_size in context_sizes:
            result = test_configuration(
                model_path, parallel, ctx_size, host, port, verbose
            )
            if result:
                results.append(result)

    if not results:
        print("[ERR] No successful optimizations")
        return {}

    # Analyze results
    best = max(results, key=lambda r: r.get("best_throughput", 0))

    analysis = {
        "model": model_name,
        "optimal_parallel": best["parallel"],
        "optimal_ctx_size": best["ctx_size"],
        "optimal_throughput": best["best_throughput"],
        "gpu_memory_at_optimal": best.get("gpu_memory", {}),
        "recommendation": f"--parallel {best['parallel']} --ctx-size {best['ctx_size']}",
        "all_results": results,
    }

    return analysis


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Optimize llama.cpp server settings for your hardware",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  llama-cpp-server-optimizer model.gguf
  llama-cpp-server-optimizer model.gguf -v
  llama-cpp-server-optimizer model.gguf --parallel 1 2 3 4
  llama-cpp-server-optimizer model.gguf --ctx-size 2048 4096
  llama-cpp-server-optimizer model.gguf -o optimization_results.json
        """
    )

    parser.add_argument(
        "model",
        help="Path to GGUF model file"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "-o", "--output",
        help="Save results to JSON file"
    )
    parser.add_argument(
        "--parallel",
        nargs="+",
        type=int,
        default=PARALLEL_VALUES,
        help="Parallel values to test"
    )
    parser.add_argument(
        "--ctx-size",
        nargs="+",
        type=int,
        default=CONTEXT_SIZES,
        help="Context sizes to test"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_SERVER_PORT,
        help="Server port"
    )

    args = parser.parse_args()

    # Run optimization
    results = optimize_model(
        args.model,
        parallel_values=args.parallel,
        context_sizes=args.ctx_size,
        verbose=args.verbose,
        port=args.port
    )

    if results:
        # Print summary
        print(f"\n{'='*80}")
        print("OPTIMIZATION RESULTS")
        print(f"{'='*80}")
        print(f"Model: {results['model']}")
        print(f"Optimal --parallel: {results['optimal_parallel']}")
        print(f"Optimal --ctx-size: {results['optimal_ctx_size']}")
        print(f"Throughput: {results['optimal_throughput']:.2f} tok/s")
        print(f"GPU Memory: {results['gpu_memory_at_optimal']}")
        print(f"\nRecommended command:")
        print(f"  llama-server -m model.gguf {results['recommendation']}")

        # Save if requested
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"\n[OK] Results saved to: {args.output}")

        return 0
    else:
        print("[ERR] Optimization failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
