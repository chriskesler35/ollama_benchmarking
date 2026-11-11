#!/usr/bin/env python3
"""Compute an optimal llama.cpp --tensor-split from live per-GPU free VRAM.

A naive 0.5,0.5 split is wrong on this machine: GPU0 drives the Windows display
(~1GB overhead), so it has less free VRAM and becomes the OOM bottleneck under an
even split. Splitting PROPORTIONAL to each GPU's free memory fills both cards
evenly, which lets the largest models fit and run fully on GPU.
"""
import os
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message=".*pynvml package is deprecated.*")

try:
    import pynvml
    PYNVML_AVAILABLE = True
except ImportError:
    PYNVML_AVAILABLE = False

# Headroom (display + compute/KV buffers) subtracted from TOTAL GPU capacity to
# get the largest model we'll attempt. Only models clearly above this are
# pre-rejected; borderline ones are attempted and fall back if they OOM.
FIT_MARGIN_GB = 2.5

# Keep a little headroom per GPU for compute buffers / fragmentation.
RESERVE_MB = 512


def gpu_free_mb():
    """Free VRAM per GPU in MB, or None if unavailable."""
    if not PYNVML_AVAILABLE:
        return None
    try:
        pynvml.nvmlInit()
        free = []
        for i in range(pynvml.nvmlDeviceGetCount()):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            m = pynvml.nvmlDeviceGetMemoryInfo(h)
            free.append(m.free / (1024 ** 2))
        pynvml.nvmlShutdown()
        return free
    except Exception:
        return None


def gpu_total_mb():
    """Total VRAM capacity summed across GPUs, in MB (0 if unavailable)."""
    if not PYNVML_AVAILABLE:
        return 0
    try:
        pynvml.nvmlInit()
        total = 0
        for i in range(pynvml.nvmlDeviceGetCount()):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            total += pynvml.nvmlDeviceGetMemoryInfo(h).total / (1024 ** 2)
        pynvml.nvmlShutdown()
        return total
    except Exception:
        return 0


def gpu_used_mb() -> dict:
    """Used VRAM per GPU as {'gpu0_used_mb': .., 'gpu1_used_mb': ..}, or {}."""
    if not PYNVML_AVAILABLE:
        return {}
    try:
        pynvml.nvmlInit()
        out = {}
        for i in range(pynvml.nvmlDeviceGetCount()):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            m = pynvml.nvmlDeviceGetMemoryInfo(h)
            out[f"gpu{i}_used_mb"] = round(m.used / (1024 ** 2))
        pynvml.nvmlShutdown()
        return out
    except Exception:
        return {}


def optimal_tensor_split() -> str:
    """Return a --tensor-split string weighted by each GPU's free VRAM.

    Falls back to an even split if VRAM can't be read. An env override
    (LLAMA_TENSOR_SPLIT) always wins, for manual control.
    """
    override = os.environ.get("LLAMA_TENSOR_SPLIT")
    if override:
        return override

    free = gpu_free_mb()
    if not free or len(free) < 2:
        return "0.5,0.5"

    usable = [max(0.0, f - RESERVE_MB) for f in free]
    total = sum(usable)
    if total <= 0:
        return ",".join("0.5" for _ in free)

    return ",".join(f"{u / total:.3f}" for u in usable)


def check_fit(gguf_path: str) -> dict:
    """Will this GGUF plausibly fit on the GPUs (split across both)?

    Budgets against TOTAL GPU capacity minus headroom - NOT transient free VRAM,
    which dips while a previous model unloads and would falsely reject models.
    Only pre-rejects models clearly too big; borderline ones are attempted and
    fall back to Ollama if they actually OOM at load.

    Returns {checked, fits, model_gb, budget_gb, total_vram_gb, reason}.
    """
    try:
        model_gb = Path(gguf_path).stat().st_size / 1e9
    except Exception:
        return {"checked": False}

    total_mb = gpu_total_mb()
    if not total_mb:
        return {"checked": False, "model_gb": round(model_gb, 1)}

    total_gb = total_mb / 1024
    budget_gb = total_gb - FIT_MARGIN_GB
    fits = model_gb <= budget_gb
    reason = None
    if not fits:
        reason = (f"This model is {model_gb:.1f} GB, but only ~{budget_gb:.1f} GB is "
                  f"usable across both GPUs ({total_gb:.0f} GB total, minus room for "
                  f"display/context/compute). It won't fit on GPU no matter how it's "
                  f"split - you'd need a smaller quant or more VRAM.")
    return {"checked": True, "fits": fits, "model_gb": round(model_gb, 1),
            "budget_gb": round(budget_gb, 1), "total_vram_gb": round(total_gb, 1),
            "reason": reason}


if __name__ == "__main__":
    free = gpu_free_mb()
    print(f"Free VRAM per GPU (MB): {[round(f) for f in free] if free else 'n/a'}")
    print(f"Optimal tensor-split:   {optimal_tensor_split()}")
