#!/usr/bin/env python3
"""Search Hugging Face for GGUF files and download one into a local cache.

For Ollama models llama.cpp can't load directly (gemma3/gemma4/glm/mistral-
small3.2 - Ollama's own GGUF conversion is missing metadata llama.cpp needs),
a standard community GGUF from Hugging Face usually loads fine. This never
guesses a repo name - it always searches HF's live API and lets the caller
pick from real results, so a stale/wrong guess never silently downloads the
wrong weights.
"""
import json
import os
import re
from pathlib import Path
from typing import List, Optional
import requests

_HERE = os.path.dirname(os.path.abspath(__file__))
# Model weights go on the NVMe drive (G:), same convention as OLLAMA_MODELS
# and the Hugging Face hub cache - large files benefit from it, the project
# folder on E: doesn't need to hold multi-GB blobs.
CACHE_DIR = Path(os.environ.get("HF_GGUF_CACHE_DIR", r"G:\AI_Models\hf_gguf_cache"))
MAP_FILE = Path(_HERE) / "hf_gguf_map.json"
HF_API = "https://huggingface.co/api"
REQUEST_TIMEOUT = 20

# Preferred quant ordering when a repo offers many - mid-range quants first,
# skip past huge f16/f32 files and very low quality IQ1/IQ2 ones.
_PREFERRED_QUANTS = ["q4_k_m", "q4_k_s", "q5_k_m", "q5_k_s", "q6_k", "q8_0",
                     "q4_0", "q3_k_m"]


def _quant_rank(filename: str) -> int:
    fl = filename.lower()
    for i, q in enumerate(_PREFERRED_QUANTS):
        if q in fl:
            return i
    return len(_PREFERRED_QUANTS)


def _search_repos(query: str, limit: int) -> List[str]:
    """Repo IDs matching the query, filtered to ones tagged with the GGUF library."""
    r = requests.get(f"{HF_API}/models", params={
        "search": query, "filter": "gguf", "limit": limit,
        "sort": "downloads", "direction": -1,
    }, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return [m["id"] for m in r.json() if m.get("id")]


def _is_aux_file(name: str) -> bool:
    """Companion files that aren't standalone model weights: vision-projector
    (mmproj) and speculative-decoding draft heads (MTP) - llama.cpp can't load
    either of these alone as the main model."""
    nl = name.lower()
    return "mmproj" in nl or "/mtp/" in nl or "-mtp" in nl


def _repo_gguf_files(repo_id: str) -> List[dict]:
    """GGUF files in a repo, with size in bytes where the API reports it."""
    r = requests.get(f"{HF_API}/models/{repo_id}", params={"blobs": "true"},
                      timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    siblings = r.json().get("siblings", [])
    files = []
    for s in siblings:
        name = s.get("rfilename", "")
        if name.lower().endswith(".gguf") and not _is_aux_file(name):
            files.append({"filename": name, "size_bytes": s.get("size")})
    return files


def search_hf_gguf(model_name: str, repo_limit: int = 5, files_per_repo: int = 6) -> List[dict]:
    """Live HF search for GGUF files matching an Ollama model name.

    Strips the ':tag' so the search term reads like a model family name (e.g.
    "gemma3:27b" -> "gemma 3"). Returns a flat list of
    {repo_id, filename, size_gb}, most-downloaded repos first, each capped to
    a few representative quants so the picker stays short.
    """
    base = model_name.split(":")[0]
    query = re.sub(r"(?<=[a-zA-Z])(?=\d)", " ", base)
    try:
        repo_ids = _search_repos(query, repo_limit)
    except Exception:
        return []

    results = []
    for repo_id in repo_ids:
        try:
            files = _repo_gguf_files(repo_id)
        except Exception:
            continue
        files.sort(key=lambda f: _quant_rank(f["filename"]))
        for f in files[:files_per_repo]:
            results.append({
                "repo_id": repo_id,
                "filename": f["filename"],
                "size_gb": (f["size_bytes"] / 1e9) if f.get("size_bytes") else None,
            })
    return results


def _sanitize(s: str) -> str:
    return re.sub(r'[:\\/*?"<>|]', "-", s)


def local_path_for(repo_id: str, filename: str) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    return CACHE_DIR / f"{_sanitize(repo_id)}__{_sanitize(filename)}"


def download_gguf(repo_id: str, filename: str, progress_cb=None) -> Path:
    """Stream a GGUF from HF into the cache dir. progress_cb(bytes_done, bytes_total)."""
    dest = local_path_for(repo_id, filename)
    if dest.exists():
        return dest
    url = f"https://huggingface.co/{repo_id}/resolve/main/{filename}"
    tmp = dest.with_name(dest.name + ".part")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        done = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)
    os.replace(tmp, dest)
    return dest


def load_map() -> dict:
    try:
        with open(MAP_FILE) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def register_override(model: str, gguf_path) -> None:
    """Record model -> downloaded-GGUF path so gguf_resolver prefers it over
    Ollama's own (incompatible) conversion on future runs."""
    m = load_map()
    m[model] = str(gguf_path)
    tmp = str(MAP_FILE) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(m, f, indent=2)
    os.replace(tmp, MAP_FILE)


def resolve_override(model: str) -> Optional[str]:
    path = load_map().get(model)
    if path and Path(path).exists():
        return path
    return None


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "gemma3"
    for r in search_hf_gguf(q):
        size = f"{r['size_gb']:.1f} GB" if r["size_gb"] else "?"
        print(f"{r['repo_id']:50} {r['filename']:40} {size}")
