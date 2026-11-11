#!/usr/bin/env python3
"""Ollama inference helpers - the fallback engine for models whose GGUFs won't
load in standard llama.cpp (e.g. Ollama's gemma3/glm conversions)."""
import requests

OLLAMA_GENERATE = "http://localhost:11434/api/generate"
OLLAMA_SHOW = "http://localhost:11434/api/show"


def _ollama_error(model: str, resp) -> str:
    """Build an informative message from an Ollama error response.

    Ollama puts the real reason in the JSON body (e.g.
    `{"error": "\"clef-flash:latest\" does not support generate"}`), but
    `raise_for_status()` discards it and reports only the status line - which
    looks like a mysterious name/URL problem. Surface the body instead."""
    detail = ""
    try:
        detail = (resp.json() or {}).get("error", "")
    except Exception:
        detail = (resp.text or "").strip()
    detail = detail or f"HTTP {resp.status_code}"
    return f"Ollama rejected '{model}': {detail}"


def ollama_generate(model: str, prompt: str, num_predict: int = 1024,
                    timeout: int = 180, num_ctx: int = None) -> dict:
    options = {"temperature": 0, "num_predict": num_predict}
    if num_ctx:
        options["num_ctx"] = num_ctx
    r = requests.post(OLLAMA_GENERATE, json={
        "model": model, "prompt": prompt, "stream": False, "options": options,
    }, timeout=timeout)
    if not r.ok:
        raise RuntimeError(_ollama_error(model, r))
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
    """Single-stream speed via Ollama. Returns {tps, avg_time_ms, load_time_ms}.

    Cloud-proxied models return only `total_duration` - the granular
    `eval_duration` / `load_duration` / `prompt_eval_duration` fields are
    absent entirely. Reading eval_duration alone made every cloud model
    report 0.0 tok/s, which looks like a failed measurement rather than a
    successful one, so fall back to total_duration.

    That fallback is wall-clock (network + queueing + prompt processing +
    generation), so it slightly understates pure generation rate. For a cloud
    model that is arguably the more honest number anyway - you cannot get its
    raw generation speed from here, and end-to-end latency is what you would
    actually experience. `timing_basis` records which was used.
    """
    d = ollama_generate(model, "Write a short paragraph about the ocean.", num_predict)
    eval_count = d.get("eval_count", 0)
    eval_ns = d.get("eval_duration") or 0
    if eval_ns:
        basis_ns, basis = eval_ns, "eval_duration"
    else:
        basis_ns, basis = (d.get("total_duration") or 0), "total_duration"
    tps = round(eval_count / (basis_ns / 1e9), 1) if basis_ns > 0 else 0.0
    return {
        "tps": tps,
        "avg_time_ms": round(basis_ns / 1e6) if basis_ns else None,
        "load_time_ms": round((d.get("load_duration") or 0) / 1e6) or None,
        "timing_basis": basis,
    }


_CAPABILITY_CACHE: dict = {}


def model_capabilities(model: str, host: str = "localhost",
                       port: int = 11434) -> list:
    """Capabilities Ollama reports for a model via /api/show, e.g.
    ['completion', 'tools', 'vision']. Returns None when the lookup fails
    (server unreachable, model gone) so callers can tell 'unknown' apart from
    'known to lack a capability'. Cached per name - capabilities don't change
    for a given model, and the picker calls this for every model on each load.
    """
    if model in _CAPABILITY_CACHE:
        return _CAPABILITY_CACHE[model]
    try:
        r = requests.post(f"http://{host}:{port}/api/show",
                          json={"name": model}, timeout=10)
        r.raise_for_status()
        caps = r.json().get("capabilities") or []
    except Exception:
        caps = None
    _CAPABILITY_CACHE[model] = caps
    return caps


def supports_generate(model: str, host: str = "localhost",
                      port: int = 11434) -> bool:
    """Whether a model can serve /api/generate (and /api/chat) - i.e. it has
    the 'completion' capability. Models that expose only 'embedding',
    'decision', or 'vision' (no 'completion') return a 400 'does not support
    generate' and cannot be speed/accuracy benchmarked by this suite.

    Unknown capabilities (lookup failed, or an older Ollama that omits the
    field) return True: never silently drop a model we can't positively rule
    out - a real 400 at run time is still reported clearly via _ollama_error.
    """
    caps = model_capabilities(model, host, port)
    if not caps:            # None (error) or [] (field absent) -> keep it
        return True
    return "completion" in caps


def filter_generatable(models, host: str = "localhost",
                       port: int = 11434) -> list:
    """Keep only models that support /api/generate, preserving order."""
    return [m for m in models if supports_generate(m, host, port)]


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
