"""GPU utilities for managing multi-GPU inference with llama.cpp."""

import os
from typing import Dict, List, Tuple
from dataclasses import dataclass


@dataclass
class GPUSplit:
    """GPU split configuration for a model."""
    model_name: str
    gpu0_layers: int  # Number of layers on GPU 0
    gpu1_layers: int  # Number of layers on GPU 1


# Default GPU split strategy based on model parameters
GPU_SPLIT_STRATEGY: Dict[str, Tuple[int, int]] = {
    # Format: "model_size_hint": (gpu0_layers, gpu1_layers)
    # Weights represent the proportion of layers to place on each GPU
    # For a 32-layer 7B model: 1,1 means 16 on GPU0, 16 on GPU1
    # For a 40-layer 14B model: 1,3 means 10 on GPU0, 30 on GPU1
    "7b": (1, 1),      # Equal split
    "13b": (1, 1),     # Equal split
    "14b": (1, 3),     # More on GPU1
    "34b": (1, 3),     # More on GPU1
    "70b": (1, 3),     # More on GPU1
}


def parse_model_size(filename: str) -> str:
    """Extract model size hint from filename.

    Examples:
        "llama2-7b.gguf" -> "7b"
        "mistral-7b-v0.1.gguf" -> "7b"
        "neural-chat-7b-v3-2.gguf" -> "7b"
    """
    # Common patterns: 7b, 7B, 13b, 14b, 34b, 70b
    import re
    match = re.search(r'(\d+)[bB]', filename.lower())
    if match:
        return f"{match.group(1)}b"
    return "7b"  # Default fallback


def get_gpu_split(model_name: str, total_layers: int = 32) -> Tuple[int, int]:
    """Get GPU split (layers on GPU0, layers on GPU1) for a model.

    Args:
        model_name: Model filename or name (used to extract size)
        total_layers: Total number of layers in the model (default 32 for 7B)

    Returns:
        Tuple of (gpu0_layers, gpu1_layers)
    """
    size_hint = parse_model_size(model_name)
    ratio = GPU_SPLIT_STRATEGY.get(size_hint, (1, 1))

    # Calculate layer split based on ratio
    total_ratio = ratio[0] + ratio[1]
    gpu0_layers = (total_layers * ratio[0]) // total_ratio
    gpu1_layers = total_layers - gpu0_layers

    return gpu0_layers, gpu1_layers


def get_available_gguf_models(gguf_dir: str = None) -> List[str]:
    """Discover all GGUF models in a directory.

    Args:
        gguf_dir: Directory containing GGUF files.
                 Defaults to Ollama models dir if not specified.

    Returns:
        List of absolute paths to GGUF files
    """
    if gguf_dir is None:
        # Default to Ollama models directory on this system
        gguf_dir = r"E:\ollama\models"

    if not os.path.isdir(gguf_dir):
        return []

    gguf_files = []
    for root, dirs, files in os.walk(gguf_dir):
        for file in files:
            if file.endswith('.gguf'):
                gguf_files.append(os.path.join(root, file))

    return sorted(gguf_files)


def estimate_vram_usage(model_size_mb: int, context_length: int = 2048) -> Dict[str, float]:
    """Estimate VRAM usage for a model.

    Very rough estimation:
    - Model weights: model_size_mb
    - KV cache: ~(context_length / 1024) * model_params_millions / 4 MB

    Args:
        model_size_mb: Model size in MB (from file size)
        context_length: Context window size

    Returns:
        Dict with 'weights' and 'kv_cache' estimates
    """
    # Rough estimate: 7B model is ~4GB, 13B is ~8GB, 14B is ~8-9GB
    weights_mb = model_size_mb

    # Very rough KV cache estimate (simplification)
    # Each token in context uses ~model_params * 2 * 2 bytes (2x for K and V, 2 for fp16)
    # For simplicity, assume 0.5-1MB per 1000 context tokens per billion parameters
    # This is very conservative
    model_params_b = model_size_mb / 600  # Rough 7B ~4GB file size
    kv_cache_mb = (context_length / 1000) * model_params_b * 0.5

    return {
        'weights': weights_mb,
        'kv_cache': kv_cache_mb,
        'total': weights_mb + kv_cache_mb
    }


def get_gpu_memory_info() -> Dict[str, float]:
    """Get current GPU memory usage for both GPUs.

    Returns:
        Dict with 'gpu0' and 'gpu1' keys containing available memory in GB
    """
    try:
        import pynvml
        pynvml.nvmlInit()

        info = {}
        for i in range(2):
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                info[f'gpu{i}_free_gb'] = mem_info.free / (1024**3)
                info[f'gpu{i}_used_gb'] = mem_info.used / (1024**3)
                info[f'gpu{i}_total_gb'] = mem_info.total / (1024**3)
            except pynvml.NVMLError:
                info[f'gpu{i}_free_gb'] = 0
                info[f'gpu{i}_used_gb'] = 0
                info[f'gpu{i}_total_gb'] = 0

        pynvml.nvmlShutdown()
        return info
    except ImportError:
        # pynvml not available, return zeros
        return {
            'gpu0_free_gb': 0, 'gpu0_used_gb': 0, 'gpu0_total_gb': 0,
            'gpu1_free_gb': 0, 'gpu1_used_gb': 0, 'gpu1_total_gb': 0
        }
