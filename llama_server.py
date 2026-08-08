#!/usr/bin/env python3
"""Shared llama-server control: start (with accurate failure diagnosis) and stop.

Used by the speed, accuracy, and optimize phases so they all report WHY a model
failed to load - distinguishing a genuine out-of-VRAM from a build/format
incompatibility (e.g. a llama-server too old for a newer model's GGUF).
"""
import os
import subprocess
import tempfile
import time
from pathlib import Path

import requests

LLAMA_SERVER = os.environ.get(
    "LLAMA_SERVER_BIN", r"G:\llama_bin\llama-server.exe")
SERVER_HOST = "127.0.0.1"
# Benchmark uses its OWN port (overridable) so its ephemeral per-model servers
# never collide with a production llama-server (e.g. serve_qwen32b on 8080 for
# n8n). A shared port causes ConnectionReset errors and phantom 0% scores.
SERVER_PORT = int(os.environ.get("BENCH_SERVER_PORT", "8091"))
HEALTH_TIMEOUT = 240


def classify_load_failure(log_text: str):
    """Classify llama-server's death output. Returns (kind, message).

    kind is 'incompatible', 'oom', or 'unknown' - callers branch on the kind,
    never on the human-readable message (which mentions 'memory' even when it
    ISN'T a memory issue).
    """
    t = (log_text or "").lower()
    # Format / architecture incompatibility (NOT memory)
    if any(k in t for k in ("key not found", "unknown model architecture",
                            "unknown architecture", "hyperparameters",
                            "unsupported", "not supported", "unknown type",
                            "wrong number of tensors", "wrong shape",
                            "check_tensor_dims")):
        return ("incompatible",
                "Ollama's GGUF for this model isn't loadable by standard llama.cpp "
                "(missing metadata or mismatched tensor shapes - common for newer "
                "Ollama models like gemma3/glm). It runs in Ollama but not llama.cpp. "
                "To benchmark it on llama.cpp you'd need a standard GGUF (e.g. from "
                "Hugging Face). This is NOT a memory problem.")
    # Genuine out-of-VRAM
    if any(k in t for k in ("out_of_device_memory", "out of memory",
                            "failed to allocate", "cudamalloc", "ggml_backend_alloc")):
        return ("oom", "Failed to load - out of VRAM even split across both GPUs.")
    return ("unknown", "Failed to load - llama-server exited during startup. "
                       "See the phase log for the full error.")


def start_server(gguf: str, tensor_split: str, ctx: int, parallel: int = 1):
    """Start llama-server. Returns (process, None) on success, (None, reason) on failure.

    `ctx` is the total -c value (caller divides across slots if needed). Server
    output is captured to a temp file so a load failure can be diagnosed.
    """
    log_path = Path(tempfile.gettempdir()) / f"llamasrv_{os.getpid()}.log"
    try:
        logf = open(log_path, "w")
    except Exception:
        logf = subprocess.DEVNULL

    cmd = [LLAMA_SERVER, "-m", gguf, "--host", SERVER_HOST, "--port", str(SERVER_PORT),
           "--parallel", str(parallel), "-c", str(ctx), "-ngl", "999",
           "-ts", tensor_split]
    try:
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT)
    except FileNotFoundError:
        return None, {"kind": "unknown", "reason": f"llama-server not found at {LLAMA_SERVER}"}

    t0 = time.time()
    while time.time() - t0 < HEALTH_TIMEOUT:
        if proc.poll() is not None:
            # Died during load - read the captured output to find out why
            try:
                if logf not in (subprocess.DEVNULL,):
                    logf.flush()
                    logf.close()
                text = Path(log_path).read_text(errors="ignore")
            except Exception:
                text = ""
            kind, reason = classify_load_failure(text)
            return None, {"kind": kind, "reason": reason}
        try:
            r = requests.get(f"http://{SERVER_HOST}:{SERVER_PORT}/health", timeout=3)
            if r.status_code == 200 and r.json().get("status") == "ok":
                return proc, None
        except Exception:
            pass
        time.sleep(2)

    stop_server(proc)
    return None, {"kind": "unknown",
                  "reason": "Server did not become ready within the timeout."}


def stop_server(proc) -> None:
    if not proc:
        return
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
