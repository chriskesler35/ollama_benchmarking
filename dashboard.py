#!/usr/bin/env python3
"""Benchmarking Dashboard - FastAPI backend for real-time monitoring."""

import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import requests
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

# Local module — resolve_gguf returns a GGUF path for llama.cpp-compatible models
# and None for Ollama-only models (used to pick the right Phase 3 optimizer).
sys.path.insert(0, str(Path(__file__).parent))
from gguf_resolver import resolve_gguf

# Configuration
STATIC_DIR = Path(__file__).parent / "static"
STATE_FILE = Path(__file__).parent / "benchmark_state.json"
PROGRESS_FILE = Path(__file__).parent / "phase1_progress.json"
PHASE1_LOG = Path(__file__).parent / "phase1_output.log"
ACCURACY_PROGRESS_FILE = Path(__file__).parent / "accuracy_progress.json"
ACCURACY_LOG = Path(__file__).parent / "accuracy_output.log"
PHASE2_LOG = Path(__file__).parent / "phase2_output.log"
PHASE3_LOG = Path(__file__).parent / "phase3_output.log"
PHASE3_PROGRESS_FILE = Path(__file__).parent / "phase3_progress.json"
HF_DOWNLOAD_PROGRESS_FILE = Path(__file__).parent / "hf_download_progress.json"

# Phase 2/3 run as dashboard-managed child processes (not progress-file PIDs),
# so track the live child and a cancel flag to support the Stop button.
CURRENT_CHILD = {"proc": None}
CANCEL = {"flag": False}
RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# Initialize app
app = FastAPI(title="Benchmark Dashboard")

# Mount static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Global state
benchmark_state = {
    "phase": 1,
    "status": "idle",
    "models": {},
    "current_model": None,
    "progress": 0,
    "start_time": None,
    "results": {}
}

# WebSocket connections
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, data: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except Exception:
                pass


manager = ConnectionManager()


def load_state() -> dict:
    """Load benchmark state from file."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return benchmark_state.copy()


def save_state():
    """Save benchmark state to file."""
    with open(STATE_FILE, 'w') as f:
        json.dump(benchmark_state, f, indent=2)


def discover_cloud_models() -> list:
    """Cloud-proxied (':cloud') models available for opt-in benchmarking.

    Never included in discover_local_models() or any bulk "all models" run -
    each one spends real Ollama subscription credits per request.
    """
    from ollama_backend import discover_cloud_models as _discover
    return _discover()


def discover_local_models() -> list:
    """All locally-served Ollama models suitable for text benchmarking.

    Excludes cloud proxies, embedding models, and vision models (which error on
    text-only requests) - same filtering the accuracy benchmark uses.
    """
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=10)
        r.raise_for_status()
        models = sorted(m["name"] for m in r.json().get("models", []) if m.get("name"))
    except Exception:
        return []

    def keep(n: str) -> bool:
        nl = n.lower()
        if n.endswith(":cloud") or "-cloud" in n:
            return False
        if any(s in nl for s in ("embed", "bge-", "minilm")):
            return False
        if any(s in nl for s in ("vision", "llava", "-vl", "bakllava",
                                 "moondream", "minicpm-v")):
            return False
        return True

    # Also drop models Ollama reports as non-generative (e.g. 'decision'- or
    # 'embedding'-only), which 400 on /api/generate and can't be benchmarked.
    from ollama_backend import supports_generate
    return [m for m in models if keep(m) and supports_generate(m)]


def is_pid_alive(pid) -> bool:
    """Check whether a process ID belongs to a running process.

    On Windows, os.kill(pid, 0) would TERMINATE the process, so we must
    query via the Win32 API instead.
    """
    if not pid:
        return False
    pid = int(pid)
    if sys.platform == "win32":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def terminate_pid(pid) -> bool:
    """Terminate a process by PID. Returns True if a kill was attempted.

    On Windows os.kill(pid, SIGTERM) maps to TerminateProcess; on POSIX it
    sends SIGTERM. Errors (already dead, no permission) are swallowed.
    """
    if not pid or not is_pid_alive(pid):
        return False
    try:
        os.kill(int(pid), signal.SIGTERM)
        return True
    except Exception:
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(int(pid))],
                           capture_output=True)
            return True
        except Exception:
            return False


def stop_running_benchmarks() -> list:
    """Stop any running benchmark and mark its state stopped. Returns labels stopped."""
    stopped = []
    # Phase 1 / Accuracy run as detached processes that write progress files
    for progress_file, label in ((PROGRESS_FILE, "Phase 1"),
                                 (ACCURACY_PROGRESS_FILE, "Accuracy")):
        p = read_progress(progress_file)
        if p and p.get("status") == "running" and is_pid_alive(p.get("pid")):
            if terminate_pid(p.get("pid")):
                stopped.append(label)
            # Mark the file so monitors/reconnect see it's no longer running
            p["status"] = "stopped"
            try:
                with open(progress_file, "w") as f:
                    json.dump(p, f, indent=2)
            except Exception:
                pass

    # Phase 2 / 3 run as dashboard-managed children - cancel the loop and kill
    # the current child.
    CANCEL["flag"] = True
    proc = CURRENT_CHILD.get("proc")
    if proc is not None and proc.returncode is None:
        try:
            proc.terminate()
            stopped.append("Phase 2/3")
        except Exception:
            terminate_pid(proc.pid)

    # Phase 3 spawns llama-server children that won't die with the optimizer on
    # Windows - reap any orphans so they don't keep holding GPU VRAM.
    try:
        subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"],
                       capture_output=True)
    except Exception:
        pass

    return stopped


def read_progress(progress_file: Path = PROGRESS_FILE) -> Optional[dict]:
    """Read a progress file written by a benchmark script."""
    if progress_file.exists():
        try:
            with open(progress_file) as f:
                return json.load(f)
        except Exception:
            pass
    return None


def progress_percent(p: dict) -> int:
    """Compute overall percent from model + prompt counts."""
    total = p.get("models_total", 0) * max(p.get("prompts_per_model", 1), 1)
    if total <= 0:
        return 0
    done = (p.get("models_done", 0) * max(p.get("prompts_per_model", 1), 1)
            + p.get("current_prompt", 0))
    return min(100, int(done / total * 100))


def apply_progress_to_state(p: dict, phase: int = 1):
    """Map benchmark progress-file contents onto the dashboard state."""
    benchmark_state["phase"] = phase
    benchmark_state["current_model"] = p.get("current_model")
    benchmark_state["progress"] = progress_percent(p)
    benchmark_state["models"] = {
        "completed": p.get("completed_models", []),
        "failed": p.get("failed_models", []),
        "done": p.get("models_done", 0),
        "total": p.get("models_total", 0),
    }
    if p.get("started_at"):
        benchmark_state["start_time"] = p["started_at"]


async def monitor_progress(progress_file: Path = PROGRESS_FILE, phase: int = 1):
    """Watch a benchmark progress file until the run finishes or its process dies.

    This is decoupled from the subprocess handle on purpose: it works the same
    whether we launched the benchmark ourselves or reconnected to one that was
    already running before the dashboard (re)started.
    """
    missing_checks = 0
    while True:
        p = read_progress(progress_file)
        if not p:
            # Tolerate a slow-starting benchmark before giving up (~30s)
            missing_checks += 1
            if missing_checks > 15:
                benchmark_state["status"] = "idle"
                break
            await asyncio.sleep(2)
            continue
        missing_checks = 0

        apply_progress_to_state(p, phase)

        if p.get("status") == "completed":
            benchmark_state["status"] = "completed"
            benchmark_state["progress"] = 100
            benchmark_state["current_model"] = None
            break
        if p.get("status") == "failed":
            benchmark_state["status"] = "failed"
            break
        if p.get("status") == "stopped":
            # Deliberately stopped by the user - not a crash
            benchmark_state["status"] = "stopped"
            benchmark_state["current_model"] = None
            break
        if not is_pid_alive(p.get("pid")):
            # Process died without writing a final status
            benchmark_state["status"] = "interrupted"
            break

        benchmark_state["status"] = "running"
        save_state()
        await broadcast_update()
        await asyncio.sleep(2)

    save_state()
    await broadcast_update()


def load_results() -> dict:
    """Load all results from files."""
    results = {}
    for phase in range(1, 4):
        pattern = f"results_phase{phase}_*.json"
        # Newest file wins
        files = sorted(RESULTS_DIR.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
        for file in files:
            try:
                with open(file) as f:
                    results[f"phase{phase}"] = json.load(f)
                break
            except Exception:
                pass
    return results


async def broadcast_update():
    """Broadcast current state to all connected clients."""
    await manager.broadcast({
        "type": "state_update",
        "data": benchmark_state,
        "timestamp": datetime.now().isoformat()
    })


@app.on_event("startup")
async def startup():
    """Load initial state and reconnect to any benchmark already in flight."""
    global benchmark_state
    benchmark_state = load_state()

    # Reconnect to whichever benchmark is in flight (phase 1 = speed, 4 = accuracy)
    for progress_file, phase in ((PROGRESS_FILE, 1), (ACCURACY_PROGRESS_FILE, 4)):
        p = read_progress(progress_file)
        if not p:
            continue
        if p.get("status") == "running" and is_pid_alive(p.get("pid")):
            # Benchmark survived a dashboard/browser restart - re-attach
            apply_progress_to_state(p, phase)
            benchmark_state["status"] = "running"
            asyncio.create_task(monitor_progress(progress_file, phase))
            break
        elif p.get("status") == "running":
            # Progress file says running but the process is gone - it crashed
            apply_progress_to_state(p, phase)
            benchmark_state["status"] = "interrupted"
        elif p.get("status") == "completed" and benchmark_state.get("phase", 1) == phase:
            apply_progress_to_state(p, phase)
            benchmark_state["status"] = "completed"
            benchmark_state["progress"] = 100

    save_state()


@app.get("/")
async def root():
    """Serve the dashboard HTML."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Dashboard ready"}


@app.get("/api/state")
async def get_state():
    """Get current benchmark state."""
    return {
        **benchmark_state,
        "results": load_results()
    }


@app.get("/api/models")
async def get_models():
    """Get all available models (from analyze_models.py)."""
    from analyze_models import OLLAMA_MODELS
    return {
        model: {
            "name": model,
            "size_gb": size,
            "base_model": base,
            "note": note
        }
        for model, (size, base, note) in OLLAMA_MODELS.items()
    }


@app.get("/api/models/cloud")
async def get_cloud_models():
    """Cloud models available for opt-in inclusion in Speed/Accuracy runs."""
    return {"models": discover_cloud_models()}


@app.get("/api/models/local")
async def get_local_models():
    """All locally-served models eligible for benchmarking, live from Ollama.

    Used by the model picker so a just-added model (e.g. via the HF GGUF
    download) shows up immediately, without needing any hand-maintained list.
    """
    return {"models": discover_local_models()}


@app.get("/api/hf/search")
async def hf_search(q: str):
    """Live Hugging Face search for GGUF files matching a model name.

    Never guesses a repo - only returns what HF's API actually has, so the
    user picks the exact file before anything downloads. Runs the blocking
    HTTP calls in a thread so it doesn't stall the event loop (and any
    benchmark currently being monitored).
    """
    from hf_gguf import search_hf_gguf
    results = await asyncio.to_thread(search_hf_gguf, q)
    return {"results": results}


@app.post("/api/hf/download")
async def hf_download(background_tasks: BackgroundTasks,
                       model: str = Body(...), repo_id: str = Body(...),
                       filename: str = Body(...)):
    """Download one GGUF from HF into the local cache, then register it as the
    override gguf_resolver uses for `model` from now on instead of Ollama's
    own (incompatible) conversion.
    """
    existing = read_progress(HF_DOWNLOAD_PROGRESS_FILE)
    if existing and existing.get("status") == "downloading":
        return {"error": f"A download is already in progress ({existing.get('filename')})"}

    background_tasks.add_task(run_hf_download, model, repo_id, filename)
    return {"status": f"Downloading {filename} from {repo_id}..."}


@app.get("/api/hf/download-status")
async def hf_download_status():
    return read_progress(HF_DOWNLOAD_PROGRESS_FILE) or {"status": "idle"}


def _write_hf_progress(data: dict) -> None:
    try:
        tmp = str(HF_DOWNLOAD_PROGRESS_FILE) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, HF_DOWNLOAD_PROGRESS_FILE)
    except Exception:
        pass


async def run_hf_download(model: str, repo_id: str, filename: str):
    """Background task: stream the GGUF down, tracking progress on disk so the
    dashboard can poll it the same way it polls benchmark progress."""
    from hf_gguf import download_gguf, register_override

    progress = {"status": "downloading", "model": model, "repo_id": repo_id,
                "filename": filename, "bytes_done": 0, "bytes_total": 0,
                "percent": 0, "started_at": datetime.now().isoformat()}
    _write_hf_progress(progress)

    def on_progress(done, total):
        progress["bytes_done"] = done
        progress["bytes_total"] = total
        progress["percent"] = int(done / total * 100) if total else 0
        _write_hf_progress(progress)

    try:
        dest = await asyncio.to_thread(download_gguf, repo_id, filename, on_progress)
        register_override(model, dest)
        progress["status"] = "completed"
        progress["dest_path"] = str(dest)
        progress["percent"] = 100
        progress["finished_at"] = datetime.now().isoformat()
    except Exception as e:
        progress["status"] = "error"
        progress["note"] = str(e)[:300]
    _write_hf_progress(progress)


@app.post("/api/start-phase1")
async def start_phase1(background_tasks: BackgroundTasks,
                       models: Optional[List[str]] = Body(default=None),
                       cloud_models: Optional[List[str]] = Body(default=None),
                       cloud_only: bool = Body(default=False)):
    """Start Phase 1 benchmark, or reconnect to one that's already running.

    models, if given, restricts the run to just those local models (e.g. a
    single newly-added one) instead of all of them - results still MERGE with
    prior runs (see get_phase1_results), so this only adds/updates those
    models without touching anyone else's scores.

    cloud_models is an explicit opt-in list of ':cloud' models to measure -
    never auto-included, since each one spends real Ollama subscription credits.

    cloud_only restricts the run to JUST those cloud models, skipping local
    discovery entirely. Without it, an empty models list means "every local
    model", which turns a quick cloud comparison into a multi-hour local sweep.
    """
    p = read_progress()
    if p and p.get("status") == "running" and is_pid_alive(p.get("pid")):
        # A benchmark is already in flight - attach to it instead of refusing
        apply_progress_to_state(p, 1)
        benchmark_state["status"] = "running"
        background_tasks.add_task(monitor_progress, PROGRESS_FILE, 1)
        await broadcast_update()
        return {"status": "Phase 1 already running - reconnected to it"}

    acc = read_progress(ACCURACY_PROGRESS_FILE)
    if acc and acc.get("status") == "running" and is_pid_alive(acc.get("pid")):
        return {"error": "Accuracy benchmark is running - wait for it to finish first"}

    if benchmark_state["status"] == "running":
        # State file says running but no live process exists - stale, reset it
        benchmark_state["status"] = "idle"

    benchmark_state["status"] = "running"
    benchmark_state["phase"] = 1
    benchmark_state["start_time"] = datetime.now().isoformat()
    benchmark_state["progress"] = 0

    # Start benchmark in background
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"results_phase1_{timestamp}.json"

    background_tasks.add_task(
        run_phase1_benchmark,
        output_file,
        cloud_models,
        models,
        cloud_only
    )

    await broadcast_update()
    if cloud_only:
        return {"status": f"Phase 1 starting for "
                          f"{len(cloud_models or [])} cloud model(s) only..."}
    scope = f"{len(models)} model(s)" if models else "all local models"
    cloud_note = f" + {len(cloud_models)} cloud model(s)" if cloud_models else ""
    return {"status": f"Phase 1 starting for {scope}...{cloud_note}"}


@app.post("/api/start-phase2")
async def start_phase2(background_tasks: BackgroundTasks,
                       models: Optional[List[str]] = Body(default=None)):
    """Start Phase 2 context profiling. With no model list, runs ALL local models."""
    if not models:
        models = discover_local_models()
    if not models:
        return {"error": "No local models found"}

    benchmark_state["status"] = "running"
    benchmark_state["phase"] = 2
    benchmark_state["start_time"] = datetime.now().isoformat()

    background_tasks.add_task(run_phase2_profiling, models)

    await broadcast_update()
    return {"status": f"Phase 2 starting for {len(models)} models..."}


@app.post("/api/start-phase3")
async def start_phase3(background_tasks: BackgroundTasks,
                       models: Optional[List[str]] = Body(default=None)):
    """Start Phase 3 optimization. With no model list, runs ALL local models."""
    if not models:
        models = discover_local_models()
    if not models:
        return {"error": "No local models found"}

    benchmark_state["status"] = "running"
    benchmark_state["phase"] = 3
    benchmark_state["start_time"] = datetime.now().isoformat()

    background_tasks.add_task(run_phase3_optimization, models)

    await broadcast_update()
    return {"status": f"Phase 3 starting for {len(models)} models..."}


@app.post("/api/start-accuracy")
async def start_accuracy(background_tasks: BackgroundTasks,
                         models: Optional[List[str]] = Body(default=None),
                         cloud_models: Optional[List[str]] = Body(default=None),
                         cloud_only: bool = Body(default=False)):
    """Start the accuracy benchmark, or reconnect to one already running.

    models, if given, restricts the run to just those local models (e.g. a
    single newly-added one) instead of all of them - results still MERGE with
    prior runs (see get_accuracy_results), so this only adds/updates those
    models without touching anyone else's scores.

    cloud_models is an explicit opt-in list of ':cloud' models to ALSO score
    (in addition to the local models being run) - each one spends real
    subscription credits, so it's never auto-included.
    """
    acc = read_progress(ACCURACY_PROGRESS_FILE)
    if acc and acc.get("status") == "running" and is_pid_alive(acc.get("pid")):
        apply_progress_to_state(acc, 4)
        benchmark_state["status"] = "running"
        background_tasks.add_task(monitor_progress, ACCURACY_PROGRESS_FILE, 4)
        await broadcast_update()
        return {"status": "Accuracy benchmark already running - reconnected to it"}

    # Don't double-load Ollama while another benchmark is running
    p = read_progress()
    if p and p.get("status") == "running" and is_pid_alive(p.get("pid")):
        return {"error": "Phase 1 is still running - wait for it to finish first"}

    benchmark_state["status"] = "running"
    benchmark_state["phase"] = 4
    benchmark_state["start_time"] = datetime.now().isoformat()
    benchmark_state["progress"] = 0
    benchmark_state["current_model"] = None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    background_tasks.add_task(run_accuracy_benchmark, f"results_accuracy_{timestamp}.json",
                              cloud_models, models, cloud_only)

    await broadcast_update()
    if cloud_only:
        return {"status": f"Accuracy benchmark starting for "
                          f"{len(cloud_models or [])} cloud model(s) only..."}
    scope = f"{len(models)} model(s)" if models else "all local models"
    cloud_note = f" + {len(cloud_models)} cloud model(s)" if cloud_models else ""
    return {"status": f"Accuracy benchmark starting for {scope}...{cloud_note}"}


async def run_accuracy_benchmark(output_file: str, cloud_models: Optional[List[str]] = None,
                                 models: Optional[List[str]] = None,
                                 cloud_only: bool = False):
    """Launch the accuracy benchmark as a detached process and monitor it."""
    try:
        cmd = [
            sys.executable, "-u", "accuracy_llamacpp.py",
            "-o", str(RESULTS_DIR / output_file),
            "--progress-file", str(ACCURACY_PROGRESS_FILE),
        ]
        if models:
            cmd += ["--models"] + models
        if cloud_models:
            cmd += ["--cloud-models"] + cloud_models
        if cloud_only:
            cmd += ["--cloud-only"]

        ACCURACY_PROGRESS_FILE.unlink(missing_ok=True)

        log_handle = open(ACCURACY_LOG, "a")
        log_handle.write(f"\n=== Accuracy benchmark started {datetime.now().isoformat()} ===\n")
        log_handle.flush()

        await asyncio.create_subprocess_exec(
            *cmd,
            stdout=log_handle,
            stderr=asyncio.subprocess.STDOUT,
            cwd=Path(__file__).parent
        )

        await asyncio.sleep(3)
        await monitor_progress(ACCURACY_PROGRESS_FILE, 4)

    except Exception as e:
        benchmark_state["status"] = f"error: {str(e)}"
        save_state()
        await broadcast_update()


@app.get("/api/results/accuracy")
async def get_accuracy_results():
    """Get accuracy results, MERGED across runs (newest per model), dropping
    vision models whose text-API errors produce meaningless 0% scores.

    Like the speed endpoint, merging keeps each model's score until that model
    is re-run, so a partial re-run never hides the rest of the field.
    """
    merged = _merge_results("results_accuracy_*.json")
    results = [r for m, r in merged.items() if not _is_vision(m)]
    if not results:
        return None
    # accuracy is None for models that never actually answered (billing
    # rejection, auth failure, outage) - those are unmeasured, not zero, so
    # sort them below every real score rather than letting None hit the
    # comparison and raise TypeError.
    results.sort(key=lambda r: (r.get("accuracy") is not None, r.get("accuracy") or 0),
                 reverse=True)
    return {"total_models": len(results), "results": results}


def _newest_result(pattern: str) -> Optional[dict]:
    files = sorted(RESULTS_DIR.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
    for file in files:
        try:
            with open(file) as f:
                return json.load(f)
        except Exception:
            pass
    return None


# Vision models error on the text API; never plot them
_VISION_MARKERS = ("vision", "llava", "-vl", "bakllava", "moondream", "minicpm-v")


def _is_vision(name: str) -> bool:
    return any(s in name.lower() for s in _VISION_MARKERS)


def _merge_results(pattern: str) -> dict:
    """Merge every matching result file into {model_name: result}, newest wins.

    Lets a small supplemental run (e.g. speed for a few models) ADD to the set
    instead of a single newest file replacing everything.
    """
    files = sorted(RESULTS_DIR.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
    merged = {}
    for file in files:
        try:
            with open(file) as f:
                data = json.load(f)
        except Exception:
            continue
        for r in data.get("results", []):
            merged.setdefault(r["model_name"], r)
    return merged


@app.get("/api/results/combined")
async def get_combined_results():
    """Join speed (Phase 1) and accuracy by model name for the scatter plot.

    Only models that have BOTH a speed and an accuracy score are returned -
    a point needs both coordinates. Zero-speed models (cloud proxies, which
    don't report local eval stats) are excluded.
    """
    p1 = _merge_results("results_phase1_*.json")
    acc = _merge_results("results_accuracy_*.json")

    # Sanity ceiling: no local model on this rig realistically exceeds a few
    # hundred tok/s. Sentinel/garbage values (e.g. a divide-by-near-zero that
    # saved 1e6) would otherwise blow out the x-axis and squash every real
    # point against the y-axis. Treat implausible speeds as missing.
    MAX_PLAUSIBLE_TPS = 1000.0
    speed = {m: r.get("avg_tokens_per_sec", 0) or 0 for m, r in p1.items()}

    accuracy = {}
    categories = {}
    for m, r in acc.items():
        # .get, not [] - an errored record may omit the key entirely, and a
        # KeyError here takes down the whole scatter plot for one bad row.
        accuracy[m] = r.get("accuracy")
        categories[m] = r.get("by_category", {})

    points = []
    skipped_outliers = []
    for model, acc_val in accuracy.items():
        if _is_vision(model):
            continue
        if acc_val is None:
            continue  # accuracy run still in progress for this model
        spd = speed.get(model, 0)
        if spd > MAX_PLAUSIBLE_TPS:
            skipped_outliers.append({"model": model, "tokens_per_sec": round(spd, 1)})
            continue
        if spd > 0:
            points.append({
                "model": model,
                "tokens_per_sec": round(spd, 1),
                "accuracy": acc_val,
                "by_category": categories.get(model, {}),
                "engine": acc.get(model, {}).get("engine"),
            })

    points.sort(key=lambda p: (-p["accuracy"], -p["tokens_per_sec"]))
    return {"points": points, "count": len(points), "skipped_outliers": skipped_outliers}


@app.post("/api/stop")
async def stop_benchmark():
    """Stop whatever benchmark is currently running."""
    stopped = stop_running_benchmarks()
    if stopped:
        benchmark_state["status"] = "stopped"
        benchmark_state["current_model"] = None
        save_state()
        await broadcast_update()
        return {"status": f"Stopped: {', '.join(stopped)}"}
    return {"status": "Nothing was running"}


# Per-phase reset: result-file globs + progress/log files to delete
RESET_TARGETS = {
    "speed":    {"globs": ["results_phase1_*.json"],    "extra": [PROGRESS_FILE, PHASE1_LOG]},
    "accuracy": {"globs": ["results_accuracy_*.json"],  "extra": [ACCURACY_PROGRESS_FILE, ACCURACY_LOG]},
    "context":  {"globs": ["profile_*.json"],           "extra": [PHASE2_LOG]},
    "optimize": {"globs": ["optimization_*.json"],      "extra": [PHASE3_PROGRESS_FILE, PHASE3_LOG]},
}


@app.post("/api/reset/{phase}")
async def reset_phase(phase: str):
    """Delete all saved results for one phase so it can be re-run from scratch."""
    if phase not in RESET_TARGETS:
        return {"error": f"Unknown phase '{phase}'"}

    # Never wipe results out from under a live run. Check ACTUAL live processes
    # (not benchmark_state, which can be a stale 'running' after an external kill).
    if _any_benchmark_running():
        return {"error": "A run is in progress - stop it first, then reset."}

    t = RESET_TARGETS[phase]
    removed = 0
    for pattern in t["globs"]:
        for f in RESULTS_DIR.glob(pattern):
            try:
                f.unlink()
                removed += 1
            except Exception:
                pass
    for f in t["extra"]:
        try:
            Path(f).unlink(missing_ok=True)
        except Exception:
            pass

    benchmark_state["status"] = "idle"
    benchmark_state["progress"] = 0
    benchmark_state["current_model"] = None
    benchmark_state["models"] = {}
    save_state()
    await broadcast_update()
    return {"status": f"Reset {phase}: removed {removed} result file(s)"}


def _any_benchmark_running() -> bool:
    """True if any phase's process is actually alive (guards against stale state)."""
    for pf in (PROGRESS_FILE, ACCURACY_PROGRESS_FILE, PHASE3_PROGRESS_FILE):
        p = read_progress(pf)
        if p and p.get("status") == "running" and is_pid_alive(p.get("pid")):
            return True
    proc = CURRENT_CHILD.get("proc")
    return proc is not None and proc.returncode is None


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await manager.connect(websocket)
    try:
        while True:
            # Send current state every second
            await asyncio.sleep(1)
            await websocket.send_json({
                "type": "state_update",
                "data": benchmark_state,
                "timestamp": datetime.now().isoformat()
            })
    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def run_phase1_benchmark(output_file: str, cloud_models: Optional[List[str]] = None,
                               models: Optional[List[str]] = None,
                               cloud_only: bool = False):
    """Launch Phase 1 benchmark as a detached process and monitor its progress file.

    Output goes to a log file, never a pipe - an unread pipe fills up and
    freezes the child process. Progress comes from the progress file the
    benchmark writes, so monitoring survives dashboard restarts.
    """
    try:
        cmd = [
            sys.executable, "-u", "speed_llamacpp.py",
            "-o", str(RESULTS_DIR / output_file),
            "--progress-file", str(PROGRESS_FILE),
        ]
        if models:
            cmd += ["--models"] + models
        if cloud_models:
            cmd += ["--cloud-models"] + cloud_models
        if cloud_only:
            cmd += ["--cloud-only"]

        # Remove any progress file from a previous run so the monitor doesn't
        # read a stale "completed" status before the new run writes its first entry
        PROGRESS_FILE.unlink(missing_ok=True)

        log_handle = open(PHASE1_LOG, "a")
        log_handle.write(f"\n=== Phase 1 started {datetime.now().isoformat()} ===\n")
        log_handle.flush()

        await asyncio.create_subprocess_exec(
            *cmd,
            stdout=log_handle,
            stderr=asyncio.subprocess.STDOUT,
            cwd=Path(__file__).parent
        )

        # Give the benchmark a moment to write its first progress entry
        await asyncio.sleep(3)
        await monitor_progress(PROGRESS_FILE, 1)

    except Exception as e:
        benchmark_state["status"] = f"error: {str(e)}"
        save_state()
        await broadcast_update()


async def run_phase2_profiling(models: List[str]):
    """Run Phase 2 context profiling, one model at a time."""
    try:
        CANCEL["flag"] = False
        total = len(models)
        log_handle = open(PHASE2_LOG, "a")
        log_handle.write(f"\n=== Phase 2 started {datetime.now().isoformat()} ===\n")
        log_handle.flush()

        for i, model in enumerate(models):
            if CANCEL["flag"]:
                benchmark_state["status"] = "stopped"
                break

            benchmark_state["current_model"] = model
            benchmark_state["progress"] = int((i / total) * 100)
            benchmark_state["models"] = {"done": i, "total": total}
            await broadcast_update()

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # Model names contain ':' and '/' which are illegal in Windows
            # filenames - sanitize for the path (the JSON still stores the real name).
            safe = re.sub(r'[:\\/*?"<>|]', "-", model)
            output_file = str(RESULTS_DIR / f"profile_{safe}_{timestamp}.json")

            cmd = [sys.executable, "-u", "context_llamacpp.py", model, "-v",
                   "-o", output_file]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=log_handle, stderr=asyncio.subprocess.STDOUT,
                cwd=Path(__file__).parent)
            CURRENT_CHILD["proc"] = process
            await process.wait()
            CURRENT_CHILD["proc"] = None
            await broadcast_update()

        if not CANCEL["flag"]:
            benchmark_state["status"] = "completed"
            benchmark_state["progress"] = 100
            benchmark_state["models"] = {"done": total, "total": total}
        benchmark_state["current_model"] = None
        save_state()
        await broadcast_update()

    except Exception as e:
        benchmark_state["status"] = f"error: {str(e)}"
        save_state()
        await broadcast_update()


def _promote_phase3_to_speed(model: str, optimization_file: str) -> None:
    """Write a Phase 1-format speed record promoted from Phase 3 optimization data.

    Phase 3 sweeps ctx-size × parallel. The concurrency=1 result at the
    optimal ctx-size is the best single-request throughput measured with
    properly tuned settings — more accurate than Phase 1's default run.
    Writing it as results_phase1_*_p3.json lets _merge_results pick it up
    (newest-per-model wins), so the Phase 1 tab always shows the number
    that was measured at the right context size without requiring a separate
    Phase 1 re-run.
    """
    try:
        with open(optimization_file) as f:
            data = json.load(f)
    except Exception:
        return

    analysis = data.get("analysis", {})
    if not analysis or analysis.get("status") in ("too_large", "load_failed"):
        return

    all_results = data.get("all_results", [])
    optimal_ctx = analysis.get("optimal_ctx_size")
    tensor_split = data.get("tensor_split", "")

    # Prefer concurrency=1 at the optimal ctx; fall back to any successful one
    p1_row = next(
        (r for r in all_results
         if r.get("concurrency") == 1
         and r.get("ctx_size") == optimal_ctx
         and r.get("successful_requests", 0) > 0),
        None
    ) or next(
        (r for r in all_results
         if r.get("concurrency") == 1
         and r.get("successful_requests", 0) > 0),
        None
    )

    if not p1_row:
        return

    tps = p1_row.get("aggregate_tokens_per_sec")
    if not tps:
        return

    ctx_used = p1_row.get("ctx_size", optimal_ctx)
    # Phase 3 fires 128 predict tokens at concurrency=1; back-calculate avg response time
    avg_ms = round((128 / tps) * 1000) if tps else None

    promoted = {
        "model_name": model,
        "engine": "llama.cpp",
        "status": "ok",
        "tensor_split": tensor_split,
        "avg_tokens_per_sec": round(tps, 2),
        "avg_time_ms": avg_ms,
        "load_time_ms": None,
        "source": "phase3_promotion",
        "note": f"Speed at concurrency=1, ctx={ctx_used} — optimal settings from Phase 3",
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r'[:\\/*?"<>|]', "-", model)
    out_path = RESULTS_DIR / f"results_phase1_{safe}_{timestamp}_p3.json"

    record = {
        "timestamp": datetime.now().isoformat(),
        "engine": "llama.cpp",
        "total_models": 1,
        "note": "Promoted from Phase 3 — speed at optimal ctx settings, concurrency=1",
        "results": [promoted],
    }

    try:
        tmp = str(out_path) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(record, f, indent=2)
        os.replace(tmp, str(out_path))
        print(f"[Phase3→Speed] {model}: {tps:.1f} tok/s @ ctx={ctx_used} → {out_path.name}")
    except Exception as e:
        print(f"[Phase3→Speed] Failed to write promoted result for {model}: {e}")


async def run_phase3_optimization(models: List[str]):
    """Run Phase 3 Ollama optimization (concurrency + context), one model at a time."""
    try:
        CANCEL["flag"] = False
        total = len(models)
        log_handle = open(PHASE3_LOG, "a")
        log_handle.write(f"\n=== Phase 3 started {datetime.now().isoformat()} ===\n")
        log_handle.flush()

        for i, model in enumerate(models):
            if CANCEL["flag"]:
                benchmark_state["status"] = "stopped"
                break

            benchmark_state["current_model"] = model
            benchmark_state["progress"] = int((i / total) * 100)
            benchmark_state["models"] = {"done": i, "total": total}
            await broadcast_update()

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe = re.sub(r'[:\\/*?"<>|]', "-", model)
            output_file = str(RESULTS_DIR / f"optimization_{safe}_{timestamp}.json")

            # Route to the right optimizer: llama.cpp for models with a GGUF,
            # Ollama for everything else (gemma3, glm, etc. that only run via Ollama).
            gguf = resolve_gguf(model)
            optimizer = "llama_cpp_optimizer.py" if gguf else "ollama_optimizer.py"
            cmd = [sys.executable, "-u", optimizer, model, "-v",
                   "-o", output_file, "--progress-file", str(PHASE3_PROGRESS_FILE)]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=log_handle, stderr=asyncio.subprocess.STDOUT,
                cwd=Path(__file__).parent)
            CURRENT_CHILD["proc"] = process
            await process.wait()
            CURRENT_CHILD["proc"] = None
            _promote_phase3_to_speed(model, output_file)
            await broadcast_update()

        if not CANCEL["flag"]:
            benchmark_state["status"] = "completed"
            benchmark_state["progress"] = 100
            benchmark_state["models"] = {"done": total, "total": total}
        benchmark_state["current_model"] = None
        save_state()
        await broadcast_update()

    except Exception as e:
        benchmark_state["status"] = f"error: {str(e)}"
        save_state()
        await broadcast_update()


@app.get("/api/results/phase1")
async def get_phase1_results():
    """Get Phase 1 speed results, MERGED across all runs (newest per model).

    Merging (rather than returning only the newest file) means each model's
    speed score persists until that specific model is re-run - a partial or
    supplemental run adds/updates models instead of hiding the rest. This is
    what keeps the data available for Phase 2/3 selection.
    """
    merged = _merge_results("results_phase1_*.json")
    if not merged:
        return None
    results = sorted(merged.values(),
                     key=lambda r: r.get("avg_tokens_per_sec", 0) or 0, reverse=True)
    return {"total_models": len(results), "results": results}


@app.get("/api/results/phase2")
async def get_phase2_results():
    """Get Phase 2 context profiles, newest-per-model."""
    results = {}
    files = sorted(RESULTS_DIR.glob("profile_*.json"),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    for file in files:
        try:
            with open(file) as f:
                data = json.load(f)
            model = data.get("model", file.stem)
            results.setdefault(model, data)
        except Exception:
            pass
    return results


@app.get("/api/results/phase3")
async def get_phase3_results():
    """Get Phase 3 optimization results, newest-per-model."""
    results = {}
    files = sorted(RESULTS_DIR.glob("optimization_*.json"),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    for file in files:
        try:
            with open(file) as f:
                data = json.load(f)
            model = data.get("model", file.stem)
            results.setdefault(model, data)
        except Exception:
            pass
    return results


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
