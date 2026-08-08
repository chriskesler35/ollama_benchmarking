#!/usr/bin/env python3
"""Ollama inference helpers - the fallback engine for models whose GGUFs won't
load in standard llama.cpp (e.g. Ollama's gemma3/glm conversions)."""
import requests

OLLAMA_GENERATE = "http://localhost:11434/api/generate"


def ollama_generate(model: str, prompt: str, num_predict: int = 1024,
                    timeout: int = 180, num_ctx: int = None) -> dict:
    options = {"temperature": 0, "num_predict": num_predict}
    if num_ctx:
        options["num_ctx"] = num_ctx
    r = requests.post(OLLAMA_GENERATE, json={
        "model": model, "prompt": prompt, "stream": False, "options": options,
    }, timeout=timeout)
    r.raise_for_status()
    return r.json()


def ollama_context_rate(model: str, num_ctx: int, num_predict: int = 128) -> float:
    """Generation rate (tok/s) at a given context window, via Ollama."""
    d = ollama_generate(model, "Write a short paragraph about the ocean.",
                        num_predict, num_ctx=num_ctx)
    ec, ed = d.get("eval_count", 0), d.get("eval_duration", 0)
    return round(ec / (ed / 1e9), 1) if ed > 0 else 0.0


def ollama_generate_text(model: str, prompt: str, num_predict: int = 1024) -> str:
    return ollama_generate(model, prompt, num_predict).get("response", "")


def ollama_speed(model: str, num_predict: int = 128) -> dict:
    """Single-stream speed via Ollama. Returns {tps, avg_time_ms, load_time_ms}."""
    d = ollama_generate(model, "Write a short paragraph about the ocean.", num_predict)
    eval_count = d.get("eval_count", 0)
    eval_ns = d.get("eval_duration", 0)
    tps = round(eval_count / (eval_ns / 1e9), 1) if eval_ns > 0 else 0.0
    return {
        "tps": tps,
        "avg_time_ms": round(eval_ns / 1e6) if eval_ns else None,  # generation time
        "load_time_ms": round(d.get("load_duration", 0) / 1e6) or None,
    }


def discover_cloud_models(host: str = "localhost", port: int = 11434) -> list:
    """Cloud-proxied models available via this Ollama instance (the ':cloud' tag).

    These run on Ollama's hosted infrastructure, not local hardware - every
    request against one spends real subscription credits, so callers must
    treat the result as an opt-in picker, never auto-include it in a bulk run.
    """
    try:
        r = requests.get(f"http://{host}:{port}/api/tags", timeout=10)
        r.raise_for_status()
        names = sorted(m["name"] for m in r.json().get("models", []) if m.get("name"))
    except Exception:
        return []
    return [n for n in names if n.endswith(":cloud") or "-cloud" in n.lower()]


def ollama_unload(model: str) -> None:
    """Evict a model from VRAM immediately (keep_alive=0), so it doesn't linger
    and starve the next llama.cpp model of GPU memory. Best-effort."""
    try:
        requests.post(OLLAMA_GENERATE,
                      json={"model": model, "keep_alive": 0}, timeout=30)
    except Exception:
        pass
