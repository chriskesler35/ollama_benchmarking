#!/usr/bin/env python3
"""Web UI for Ollama Benchmark Tool."""

import json
import os
import signal
import socket
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import aiofiles
import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from bench import (
    DEFAULT_OLLAMA_HOST,
    DEFAULT_OLLAMA_PORT,
    discover_models,
    parse_ollama_url,
    run_prompt,
)
from prompts import TEST_PROMPTS
from report import ModelResult, PromptResult, calculate_model_result

app = FastAPI(title="Ollama Benchmark")

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

benchmark_results_store: dict[str, List[ModelResult]] = {}


def safe_print(message: str) -> None:
    """Print safely on consoles that may not support Unicode."""
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        fallback = message.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(fallback)


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Return True if TCP port is currently in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def kill_process_on_port(port: int) -> bool:
    """
    Try to kill the process using a given port.
    Works on macOS/Linux via lsof and on Windows via netstat/taskkill.
    Returns True if at least one process was terminated.
    """
    killed_any = False

    if os.name == "nt":
        try:
            output = subprocess.check_output(["netstat", "-ano"], text=True, stderr=subprocess.DEVNULL)
            pids = set()
            for line in output.splitlines():
                line = line.strip()
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if parts:
                        pids.add(parts[-1])

            for pid in pids:
                if pid and pid != "0":
                    subprocess.run(
                        ["taskkill", "/PID", pid, "/F"],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    killed_any = True
        except Exception:
            return False
    else:
        try:
            output = subprocess.check_output(["lsof", "-ti", f":{port}"], text=True, stderr=subprocess.DEVNULL)
            pids = {pid.strip() for pid in output.splitlines() if pid.strip()}
            for pid in pids:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                    killed_any = True
                except Exception:
                    pass
        except subprocess.CalledProcessError:
            return False
        except FileNotFoundError:
            return False

    return killed_any


class SaveRequest(BaseModel):
    """Request to save benchmark results."""

    results_id: str
    filepath: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the main UI."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/models")
async def get_models(host: str = DEFAULT_OLLAMA_HOST, port: int = DEFAULT_OLLAMA_PORT):
    """Get list of available models."""
    try:
        models = discover_models(host, port)
        return {"models": models, "error": None, "host": host, "port": port}
    except SystemExit:
        return {"models": [], "error": f"Cannot connect to Ollama at {host}:{port}", "host": host, "port": port}
    except Exception as exc:
        return {"models": [], "error": str(exc), "host": host, "port": port}


@app.get("/api/prompts")
async def get_prompts():
    """Get benchmark prompts."""
    categories = sorted({p.category for p in TEST_PROMPTS})
    return {
        "prompts": [{"category": p.category, "text": p.text} for p in TEST_PROMPTS],
        "categories": categories,
    }


@app.post("/api/save")
async def save_results(request: SaveRequest):
    """Save benchmark results to a file on the server."""
    if request.results_id not in benchmark_results_store:
        raise HTTPException(status_code=404, detail="Results not found")

    results = benchmark_results_store[request.results_id]

    if request.filepath:
        filepath = Path(request.filepath)
        if filepath.suffix != ".json":
            filepath = filepath.with_suffix(".json")
        filepath.parent.mkdir(parents=True, exist_ok=True)
    else:
        filepath = BASE_DIR / "results.json"

    output = {
        "timestamp": datetime.now().isoformat(),
        "total_models": len(results),
        "results": [r.to_dict() for r in results],
    }

    async with aiofiles.open(filepath, "w", encoding="utf-8") as handle:
        await handle.write(json.dumps(output, indent=2))

    return {"success": True, "filepath": str(filepath)}


@app.get("/api/download/{results_id}")
async def download_results(results_id: str):
    """Download results as a JSON file."""
    if results_id not in benchmark_results_store:
        raise HTTPException(status_code=404, detail="Results not found")

    results = benchmark_results_store[results_id]
    output = {
        "timestamp": datetime.now().isoformat(),
        "total_models": len(results),
        "results": [r.to_dict() for r in results],
    }

    temp_file = BASE_DIR / f"temp_{results_id}.json"
    async with aiofiles.open(temp_file, "w", encoding="utf-8") as handle:
        await handle.write(json.dumps(output, indent=2))

    filename = f"benchmark_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    return FileResponse(path=temp_file, filename=filename, media_type="application/json")


@app.websocket("/ws/benchmark")
async def websocket_benchmark(websocket: WebSocket):
    """Run benchmark with real-time progress updates via WebSocket."""
    await websocket.accept()

    try:
        raw = await websocket.receive_text()
        config = json.loads(raw)

        models = config.get("models", [])
        ollama_url = config.get("ollama_url", f"{DEFAULT_OLLAMA_HOST}:{DEFAULT_OLLAMA_PORT}")
        host, port = parse_ollama_url(ollama_url)

        if not models:
            await websocket.send_json({"type": "error", "message": "No models selected"})
            return

        await websocket.send_json(
            {
                "type": "start",
                "models": models,
                "total_prompts": len(TEST_PROMPTS),
                "ollama_host": host,
                "ollama_port": port,
            }
        )

        results: List[ModelResult] = []
        failed_models: List[str] = []

        for model_idx, model in enumerate(models):
            await websocket.send_json(
                {
                    "type": "model_start",
                    "model": model,
                    "model_index": model_idx,
                    "total_models": len(models),
                }
            )

            model_results: List[PromptResult] = []

            for prompt_idx, prompt in enumerate(TEST_PROMPTS):
                result = run_prompt(model, prompt, False, host, port)
                model_results.append(result)

                await websocket.send_json(
                    {
                        "type": "prompt_done",
                        "model": model,
                        "prompt_index": prompt_idx,
                        "total_prompts": len(TEST_PROMPTS),
                        "category": prompt.category,
                        "time_ms": result.response_time_ms,
                    }
                )

            try:
                model_result = calculate_model_result(model, model_results)
                results.append(model_result)

                await websocket.send_json(
                    {
                        "type": "model_done",
                        "model": model,
                        "avg_time_ms": model_result.avg_time_ms,
                        "total_time_ms": model_result.total_time_ms,
                    }
                )
            except Exception as exc:
                failed_models.append(model)
                await websocket.send_json(
                    {
                        "type": "model_error",
                        "model": model,
                        "message": str(exc),
                    }
                )

        sorted_results = sorted(results, key=lambda item: item.avg_time_ms)
        results_id = uuid.uuid4().hex
        benchmark_results_store[results_id] = sorted_results

        output_path = config.get("output_path")
        if output_path:
            filepath = Path(output_path)
            if filepath.suffix != ".json":
                filepath = filepath.with_suffix(".json")
            filepath.parent.mkdir(parents=True, exist_ok=True)

            output = {
                "timestamp": datetime.now().isoformat(),
                "total_models": len(sorted_results),
                "results": [r.to_dict() for r in sorted_results],
            }

            async with aiofiles.open(filepath, "w", encoding="utf-8") as handle:
                await handle.write(json.dumps(output, indent=2))

        await websocket.send_json(
            {
                "type": "complete",
                "results": [r.to_dict() for r in sorted_results],
                "results_id": results_id,
                "failed_models": failed_models,
                "saved_to": output_path or None,
            }
        )

    except WebSocketDisconnect:
        safe_print("WebSocket disconnected")
    except Exception as exc:
        safe_print(f"Benchmark websocket error: {exc}")
        await websocket.send_json({"type": "error", "message": str(exc)})


if __name__ == "__main__":
    port = 8000
    host = "127.0.0.1"

    if is_port_in_use(port, host):
        safe_print(f"Port {port} is in use on {host}. Attempting to free it...")
        if kill_process_on_port(port):
            safe_print(f"Freed port {port}.")
        else:
            safe_print(f"Could not free port {port}. Start manually on another port if needed.")
    safe_print(f"Starting Ollama Benchmark UI at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
