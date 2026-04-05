#!/usr/bin/env python3
"""Web UI for Ollama Benchmark Tool."""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import aiofiles

from bench import discover_models, OLLAMA_TIMEOUT
from prompts import TEST_PROMPTS
from report import PromptResult, ModelResult, calculate_model_result
import requests


app = FastAPI(title="Ollama Bench", description="Web UI for benchmarking Ollama models")

# Mount static files
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

RESULTS_DIR = Path(__file__).parent


class BenchmarkRequest(BaseModel):
    models: Optional[List[str]] = None
    verbose: bool = False


class ProgressUpdate(BaseModel):
    type: str  # "start", "model_progress", "model_done", "complete", "error"
    data: dict


async def run_prompt_async(model: str, prompt_text: str, category: str) -> PromptResult:
    """Run a single prompt asynchronously."""
    payload = {
        "model": model,
        "prompt": prompt_text,
        "stream": False
    }
    
    loop = asyncio.get_event_loop()
    
    try:
        response = await loop.run_in_executor(
            None,
            lambda: requests.post(
                "http://localhost:11434/api/generate",
                json=payload,
                timeout=OLLAMA_TIMEOUT
            )
        )
        response.raise_for_status()
        
        data = response.json()
        result_text = data.get("response", "")
        
        return PromptResult(
            category=category,
            prompt=prompt_text,
            response_time_ms=0,  # Will be set by caller
            response=result_text
        )
    except requests.exceptions.Timeout:
        return PromptResult(
            category=category,
            prompt=prompt_text,
            response_time_ms=OLLAMA_TIMEOUT * 1000,
            response="[TIMEOUT]"
        )
    except requests.exceptions.RequestException as e:
        return PromptResult(
            category=category,
            prompt=prompt_text,
            response_time_ms=0,
            response=f"[ERROR: {e}]"
        )


async def benchmark_stream_generator(models: Optional[List[str]] = None):
    """Generate SSE events for benchmark progress."""
    import time
    
    try:
        # Discover models if not provided
        if models is None:
            try:
                models = discover_models()
            except SystemExit:
                yield f"data: {json.dumps({'type': 'error', 'data': {'message': 'Cannot connect to Ollama'}})}\n\n"
                return
        
        if not models:
            yield f"data: {json.dumps({'type': 'error', 'data': {'message': 'No models found'}})}\n\n"
            return
        
        yield f"data: {json.dumps({'type': 'start', 'data': {'models': models, 'total_prompts': len(TEST_PROMPTS)}})}\n\n"
        
        results: List[ModelResult] = []
        
        for model_idx, model in enumerate(models):
            yield f"data: {json.dumps({'type': 'model_start', 'data': {'model': model, 'index': model_idx}})}\n\n"
            
            model_results: List[PromptResult] = []
            
            for prompt_idx, prompt in enumerate(TEST_PROMPTS):
                start_time = time.perf_counter()
                
                result = await run_prompt_async(model, prompt.text, prompt.category)
                
                end_time = time.perf_counter()
                result.response_time_ms = (end_time - start_time) * 1000
                
                model_results.append(result)
                
                yield f"data: {json.dumps({'type': 'prompt_done', 'data': {'model': model, 'prompt_index': prompt_idx, 'total_prompts': len(TEST_PROMPTS), 'category': prompt.category, 'time_ms': result.response_time_ms}})}\n\n"
            
            model_result = calculate_model_result(model, model_results)
            results.append(model_result)
            
            yield f"data: {json.dumps({'type': 'model_done', 'data': {'model': model, 'avg_time_ms': model_result.avg_time_ms, 'total_time_ms': model_result.total_time_ms}})}\n\n"
        
        # Save results
        output = {
            "timestamp": datetime.now().isoformat(),
            "total_models": len(results),
            "results": [r.to_dict() for r in results]
        }
        
        output_file = RESULTS_DIR / "results.json"
        async with aiofiles.open(output_file, "w") as f:
            await f.write(json.dumps(output, indent=2))
        
        # Sort by avg time for final results
        sorted_results = sorted(results, key=lambda r: r.avg_time_ms)
        
        yield f"data: {json.dumps({'type': 'complete', 'data': {'results': [r.to_dict() for r in sorted_results], 'saved_to': str(output_file)}})}\n\n"
        
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'data': {'message': str(e)}})}\n\n"


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main web UI."""
    template_path = Path(__file__).parent / "templates" / "index.html"
    async with aiofiles.open(template_path, "r") as f:
        content = await f.read()
    return HTMLResponse(content=content)


@app.get("/api/models")
async def list_models():
    """List all installed Ollama models."""
    try:
        models = discover_models()
        return {"models": models}
    except SystemExit:
        raise HTTPException(status_code=503, detail="Cannot connect to Ollama")


@app.post("/api/benchmark")
async def run_benchmark(request: BenchmarkRequest):
    """Run benchmark with SSE progress updates."""
    return StreamingResponse(
        benchmark_stream_generator(request.models),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.get("/api/results")
async def get_results():
    """Get the latest results from JSON file."""
    results_file = RESULTS_DIR / "results.json"
    
    if not results_file.exists():
        return {"results": None, "message": "No results file found"}
    
    async with aiofiles.open(results_file, "r") as f:
        content = await f.read()
    
    return json.loads(content)


@app.get("/api/prompts")
async def get_prompts():
    """Get all test prompts."""
    return {
        "prompts": [
            {"category": p.category, "text": p.text}
            for p in TEST_PROMPTS
        ],
        "categories": list(set(p.category for p in TEST_PROMPTS))
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
