#!/usr/bin/env python3
"""Resolve an Ollama model name to the GGUF blob file Ollama stores on disk."""
import json
import os
from pathlib import Path

OLLAMA_MODELS = os.environ.get("OLLAMA_MODELS", r"G:\AI_Models\ollama\models")


def resolve_gguf(model: str):
    """Return the path to the GGUF weights for an Ollama model (or a .gguf path).

    Ollama stores each model as a manifest (listing layers) plus blob files.
    The layer whose mediaType is the model weights points at a sha256 blob,
    which IS a GGUF file - llama.cpp can load it directly.
    """
    # Already a GGUF path?
    if model.lower().endswith(".gguf") and Path(model).exists():
        return model

    # A standard GGUF downloaded from Hugging Face (via the dashboard's
    # "Get llama.cpp GGUF" button) takes priority over Ollama's own blob -
    # it exists specifically because Ollama's conversion didn't load.
    from hf_gguf import resolve_override
    override = resolve_override(model)
    if override:
        return override

    name, _, tag = model.partition(":")
    tag = tag or "latest"
    manifests = Path(OLLAMA_MODELS) / "manifests"

    manifest = None
    for f in manifests.rglob(tag):
        if f.is_file() and f.parent.name == name:
            manifest = f
            break
    if not manifest:
        return None

    try:
        data = json.loads(manifest.read_text())
    except Exception:
        return None

    digest = None
    for layer in data.get("layers", []):
        if "model" in layer.get("mediaType", ""):
            digest = layer.get("digest")
            break
    if not digest:
        return None

    blob = Path(OLLAMA_MODELS) / "blobs" / digest.replace(":", "-")
    return str(blob) if blob.exists() else None


if __name__ == "__main__":
    import sys
    for m in sys.argv[1:]:
        path = resolve_gguf(m)
        size = f"{Path(path).stat().st_size / 1e9:.2f} GB" if path else "-"
        print(f"{m:40} -> {path or 'NOT FOUND'}  ({size})")
