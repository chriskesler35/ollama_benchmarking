#!/usr/bin/env python3
"""Analyze Ollama models and recommend benchmark strategy."""

import json
from pathlib import Path
from typing import List, Dict, Tuple

# Model info: name -> (size_gb, base_model, note)
OLLAMA_MODELS = {
    "dolphin-mixtral": (24.63, "Mixtral 8x7B", "RISK: Very large, may OoM"),
    "glm-4.7-flash": (17.71, "GLM 4.7B", "Borderline, test carefully"),
    "travel-advisor": (14.97, "Unknown", "Should work, limited headroom"),
    "travel-ai": (14.97, "Unknown", "Should work, limited headroom"),
    "llama3.1": (4.58, "Llama 3.1 8B", "Safe, ~1GB headroom"),
    "ski-expert-v3": (4.58, "Unknown 7B", "Safe"),
    "upcycled-coder-v1": (4.58, "Llama 3.1 8B", "Safe - your fine-tune"),
    "upcycled-coder-v2": (4.58, "Llama 3.1 8B", "Safe - your fine-tune"),
    "metal-muse-v1": (4.36, "Unknown 7B", "Safe"),
    "metal-muse-v2": (4.36, "Unknown 7B", "Safe"),
    "upcycled-qwen-coder-v1": (4.36, "Qwen 2.5 7B", "Safe - your fine-tune"),
    "dolphin-llama3": (4.34, "Llama 3 8B", "Safe"),
    "gemma3": (3.11, "Gemma 3 7B", "Safe"),
}

VRAM_TOTAL_GB = 24  # Dual RTX 3060
SAFE_THRESHOLD = 18  # Leave 6GB buffer for context + computation
RISKY_THRESHOLD = 20  # Might work but tight


def categorize_models() -> Tuple[List[str], List[str], List[str]]:
    """Categorize models by safety for Ollama API benchmark."""
    safe = []
    risky = []
    export_to_gguf = []

    for model_name, (size_gb, base, note) in OLLAMA_MODELS.items():
        if size_gb <= SAFE_THRESHOLD:
            safe.append((model_name, size_gb))
        elif size_gb <= RISKY_THRESHOLD:
            risky.append((model_name, size_gb))
        else:
            export_to_gguf.append((model_name, size_gb))

    return safe, risky, export_to_gguf


def print_report():
    """Print benchmark strategy report."""
    safe, risky, export = categorize_models()

    print("\n" + "="*80)
    print("OLLAMA MODEL BENCHMARK STRATEGY")
    print("="*80)
    print(f"\nTotal VRAM: {VRAM_TOTAL_GB}GB (dual RTX 3060 @ 12GB each)")
    print(f"Safe threshold: <= {SAFE_THRESHOLD}GB (leaves 6GB buffer)")
    print(f"Risky threshold: <= {RISKY_THRESHOLD}GB (tight but may work)")
    print(f"Export threshold: > {RISKY_THRESHOLD}GB (recommend GGUF + multi-GPU)")

    print("\n" + "-"*80)
    print(f"PHASE 1: OLLAMA API BENCHMARK ({len(safe)} models - SAFE)")
    print("-"*80)

    if safe:
        total_size = 0
        for model, size in safe:
            print(f"  [SAFE] {model:30} {size:6.2f}GB")
            total_size += size
        print(f"\n  Total size: {total_size:.2f}GB")
        print(f"  Estimated time: {len(safe) * 5}-{len(safe) * 10} minutes")
        print(f"  Command: python ollama_api_bench.py --skip-errors -d")

    print("\n" + "-"*80)
    print(f"PHASE 2: REVIEW RISKY MODELS ({len(risky)} models - OPTIONAL)")
    print("-"*80)

    if risky:
        for model, size in risky:
            print(f"  [RISKY] {model:30} {size:6.2f}GB - May hit OoM, use with caution")
        print(f"\n  Option A: Try with Ollama API (may fail)")
        print(f"  Option B: Skip and export to GGUF for safer multi-GPU")
    else:
        print("  (None)")

    print("\n" + "-"*80)
    print(f"PHASE 3: EXPORT TO GGUF & BENCHMARK ({len(export)} models - RECOMMENDED)")
    print("-"*80)

    if export:
        for model, size in export:
            print(f"  [EXPORT] {model:30} {size:6.2f}GB - Export to GGUF + llama.cpp")
        print(f"\n  Why: These models need GPU splitting across both 3060s")
        print(f"  Commands to export (requires Ollama running):")
        for model, _ in export:
            print(f"    ollama pull {model}")
            print(f"    # Then manually export: ollama convert models/{model} output.gguf")
    else:
        print("  (None - all models fit or are risky)")

    print("\n" + "="*80)
    print("RECOMMENDED EXECUTION ORDER:")
    print("="*80)
    print("""
1. Start Ollama server: ollama serve
2. Run Phase 1 benchmark (safe models):
   python ollama_api_bench.py --skip-errors -d -o results_phase1.json

3. Check results for Phase 1, then decide on Phase 2/3
4. For Phase 3 models, export to GGUF and benchmark with llama.cpp:
   python llama_cpp_bench.py --gguf-dir <export_dir> -d
    """)

    print("="*80 + "\n")


if __name__ == "__main__":
    print_report()
