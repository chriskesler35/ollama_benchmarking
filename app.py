#!/usr/bin/env python3
"""Web UI for Ollama Benchmark Tool."""

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
import aiofiles

from bench import discover_models, run_prompt, parse_ollama_url, DEFAULT_OLLAMA_HOST, DEFAULT_OLLAMA_PORT
from prompts import TEST_PROMPTS
from report import PromptResult, ModelResult, calculate_model_result, save_results_to_json

app = FastAPI(title="Ollama Benchmark")

# Mount static files and templates
BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Store for completed results (for download)
benchmark_results_store = {}


def safe_print(message: str) -> None:
    """Print safely on consoles that may not support Unicode (e.g. cp1252)."""
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = (sys.stdout.encoding or "utf-8")
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
        return {"models": [], "error": f"Cannot connect to Ollama at {host}:{port}"}
    except Exception as e:
        return {"models": [], "error": str(e)}


@app.get("/api/prompts")
async def get_prompts():
    """Get list of test prompts."""
    return {
        "prompts": [{"category": p.category, "text": p.text} for p in TEST_PROMPTS],
        "categories": list(set(p.category for p in TEST_PROMPTS)),
    }


class SaveRequest(BaseModel):
    """Request to save results to a file."""

    results_id: str
    filepath: Optional[str] = None


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

    async with aiofiles.open(filepath, "w") as f:
        await f.write(json.dumps(output, indent=2))

    return {"success": True, "filepath": str(filepath)}


@app.get("/api/download/{results_id}")
async def download_results(results_id: str):
    """Download results as a JSON file to the browser."""
    if results_id not in benchmark_results_store:
        raise HTTPException(status_code=404, detail="Results not found")

    results = benchmark_results_store[results_id]

    output = {
        "timestamp": datetime.now().isoformat(),
        "total_models": len(results),
        "results": [r.to_dict() for r in results],
    }

    temp_file = BASE_DIR / f"temp_{results_id}.json"
    async with aiofiles.open(temp_file, "w") as f:
        await f.write(json.dumps(output, indent=2))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"benchmark_results_{timestamp}.json"

    return FileResponse(path=temp_file, filename=filename, media_type="application/json")


class ConnectionManager:
    """Manage WebSocket connections for real-time updates."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)


manager = ConnectionManager()


@app.websocket("/ws/benchmark")
async def websocket_benchmark(websocket: WebSocket):
    """Run benchmark with real-time progress updates via WebSocket."""
    await manager.connect(websocket)

    try:
        data = await websocket.receive_text()
        config = json.loads(data)
        models = config.get("models", [])
        ollama_url = config.get("ollama_url", f"{DEFAULT_OLLAMA_HOST}:{DEFAULT_OLLAMA_PORT}")
        output_path = config.get("output_path", None)
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

        for model_idx, model in enumerate(models):
            model_results: List[PromptResult] = []

            await websocket.send_json(
                {
                    "type": "model_start",
                    "model": model,
                    "model_index": model_idx,
                    "total_models": len(models),
                }
            )

            for prompt_idx, prompt in enumerate(TEST_PROMPTS):
                await websocket.send_json(
                    {
                        "type": "prompt_start",
                        "model": model,
                        "prompt_index": prompt_idx,
                        "prompt_category": prompt.category,
                        "total_prompts": len(TEST_PROMPTS),
                    }
                )

                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, run_prompt, model, prompt, False, host, port)
                model_results.append(result)

                await websocket.send_json(
                    {
                        "type": "prompt_complete",
                        "model": model,
                        "prompt_index": prompt_idx,
                        "prompt_category": prompt.category,
                        "response_time_ms": result.response_time_ms,
                        "response_preview": (
                            result.response[:200] + "..." if len(result.response) > 200 else result.response
                        ),
                    }
                )

            model_result = calculate_model_result(model, model_results)
            results.append(model_result)

            await websocket.send_json(
                {
                    "type": "model_complete",
                    "model": model,
                    "avg_time_ms": model_result.avg_time_ms,
                    "total_time_ms": model_result.total_time_ms,
                    "category_times": model_result.category_times,
                }
            )

        results.sort(key=lambda x: x.avg_time_ms)
        results_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        benchmark_results_store[results_id] = results

        if output_path:
            try:
                save_results_to_json(results, output_path)
            except Exception:
                pass

        await websocket.send_json({"type": "complete", "results_id": results_id, "results": [r.to_dict() for r in results]})

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        await websocket.send_json({"type": "error", "message": str(e)})
    finally:
        manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn

    HOST = "0.0.0.0"
    PORT = 8000

    if is_port_in_use(PORT):
        safe_print(f"Port {PORT} is already in use. Attempting to kill the process...")
        killed = kill_process_on_port(PORT)
        if killed:
            safe_print(f"Process on port {PORT} terminated. Waiting 3 seconds...")
            time.sleep(3)
        else:
            safe_print(f"Could not terminate process using port {PORT}. Exiting.")
            raise SystemExit(1)

    if is_port_in_use(PORT):
        safe_print(f"Port {PORT} is still in use after cleanup attempt. Exiting.")
        raise SystemExit(1)

    safe_print(f"Starting Ollama Benchmark UI at http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT)
