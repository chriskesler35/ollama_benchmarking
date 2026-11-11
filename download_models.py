#!/usr/bin/env python3
"""Download GGUF models from HuggingFace for benchmarking."""

import argparse
import sys
from pathlib import Path
from huggingface_hub import hf_hub_download, list_repo_files

# Recommended models: small/medium GGUF quantizations
MODELS = {
    "mistral-7b-q4": {
        "repo": "TheBloke/Mistral-7B-Instruct-v0.2-GGUF",
        "filename": "mistral-7b-instruct-v0.2.Q4_K_M.gguf",
        "size_gb": 4.58,
        "type": "7B instruction-tuned"
    },
    "llama2-7b-q4": {
        "repo": "TheBloke/Llama-2-7B-Chat-GGUF",
        "filename": "llama-2-7b-chat.Q4_K_M.gguf",
        "size_gb": 3.82,
        "type": "7B chat-tuned"
    },
    "llama2-13b-q4": {
        "repo": "TheBloke/Llama-2-13B-Chat-GGUF",
        "filename": "llama-2-13b-chat.Q4_K_M.gguf",
        "size_gb": 7.37,
        "type": "13B chat-tuned (uses 1:1 GPU split)"
    },
    "neural-chat-7b-q4": {
        "repo": "TheBloke/neural-chat-7B-v3-2-GGUF",
        "filename": "neural-chat-7b-v3-2.Q4_K_M.gguf",
        "size_gb": 3.85,
        "type": "7B instruction-tuned"
    },
}


def download_model(model_key: str, output_dir: Path):
    """Download a model from HuggingFace."""
    if model_key not in MODELS:
        print(f"Unknown model: {model_key}")
        print(f"Available: {', '.join(MODELS.keys())}")
        return False

    model_info = MODELS[model_key]
    print(f"\nDownloading {model_key} ({model_info['size_gb']}GB)")
    print(f"  Repo: {model_info['repo']}")
    print(f"  Type: {model_info['type']}")

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        path = hf_hub_download(
            repo_id=model_info["repo"],
            filename=model_info["filename"],
            local_dir=str(output_dir),
            local_dir_use_symlinks=False
        )
        print(f"[OK] Downloaded to {path}")
        return True
    except Exception as e:
        print(f"[FAIL] Failed: {e}")
        return False


def list_available():
    """List all available models."""
    print("\nAvailable GGUF models for download:\n")
    for key, info in MODELS.items():
        print(f"  {key:20} - {info['type']}")
        print(f"    Size: {info['size_gb']}GB")
        print(f"    Repo: {info['repo']}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Download GGUF models from HuggingFace for benchmarking",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python download_models.py --list                          # Show available models
  python download_models.py mistral-7b-q4                   # Download Mistral 7B
  python download_models.py mistral-7b-q4 llama2-7b-q4      # Download multiple
  python download_models.py --all                           # Download all (requires ~30GB)
  python download_models.py --output /path/to/models mistral-7b-q4  # Custom directory
        """
    )

    parser.add_argument(
        "models",
        nargs="*",
        help="Model keys to download (e.g., mistral-7b-q4)"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available models and exit"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Download all available models (requires ~30GB)"
    )
    parser.add_argument(
        "--output",
        default="E:\\ollama-bench-models",
        help="Output directory (default: E:\\ollama-bench-models)"
    )

    args = parser.parse_args()

    if args.list:
        list_available()
        return

    output_dir = Path(args.output)

    if args.all:
        failed = []
        for model_key in MODELS.keys():
            if not download_model(model_key, output_dir):
                failed.append(model_key)
        if failed:
            print(f"\nFailed to download: {', '.join(failed)}")
            sys.exit(1)
    elif args.models:
        failed = []
        for model_key in args.models:
            if not download_model(model_key, output_dir):
                failed.append(model_key)
        if failed:
            print(f"\nFailed to download: {', '.join(failed)}")
            sys.exit(1)
    else:
        print("No models specified. Use --list to see available, or specify model keys.")
        print(f"Example: python download_models.py mistral-7b-q4")
        sys.exit(1)

    print(f"\nAll models downloaded to: {output_dir}")
    print(f"\nNow you can benchmark them:")
    print(f"  python llama_cpp_bench.py --gguf-dir {output_dir}")


if __name__ == "__main__":
    main()
