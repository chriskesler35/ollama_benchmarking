# Benchmark Dashboard

A web-based interface for managing and monitoring the complete 3-phase benchmarking and optimization system.

## Features

✨ **Real-time Monitoring**
- Live progress tracking for all 3 phases
- WebSocket updates every second
- Current model status display

📊 **Phase Management**
- Phase 1: Benchmark all models (Ollama API)
- Phase 2: Profile context windows per model
- Phase 3: Optimize server settings (--parallel, --ctx-size)

📈 **Results Visualization**
- Model comparison tables
- Performance charts
- GPU VRAM utilization graphs

💾 **Export & Reporting**
- Export results as JSON
- Download comparison reports
- Performance recommendations

## Installation

### 1. Install Dependencies

```bash
pip install fastapi uvicorn
```

Or add to existing installation:
```bash
pip install -r requirements.txt
```

### 2. Make sure Ollama is running

```bash
ollama serve
```

## Usage

### Start the Dashboard

```bash
cd E:\projects\ollama-bench
python dashboard.py
```

You should see:
```
Uvicorn running on http://0.0.0.0:8000
```

### Access the Dashboard

Open your browser and go to:
```
http://localhost:8000
```

## Workflow

### 1. Dashboard Tab
- View overall progress
- See current activity status
- Monitor all 3 phases

### 2. Phase 1: Benchmark
- Click "Start Phase 1" to begin
- Monitor progress in real-time
- Benchmarks all 12 safe Ollama models
- Measures throughput, latency, token counts
- **Time: 60-120 minutes**

### 3. Phase 2: Context
- Wait for Phase 1 to complete
- Click "Select Models" to choose which models to profile
- Tests context windows: 512, 1024, 2048, 4096, 8192, 16384
- Finds max safe context per GPU
- **Time: 10-15 minutes per model**

### 4. Phase 3: Optimize
- Tests different --parallel settings (1-5)
- Tests different --ctx-size values (2048, 4096, 8192)
- Finds optimal server configuration
- Measures concurrent throughput and VRAM usage
- **Time: 20-30 minutes per model**

### 5. Results
- View all results in tabular format
- Download as JSON for further analysis
- See optimization recommendations

## API Endpoints

```
GET  /api/state                    # Current benchmark state
GET  /api/models                   # Available Ollama models
GET  /api/results/phase1           # Phase 1 results
GET  /api/results/phase2           # Phase 2 results
GET  /api/results/phase3           # Phase 3 results

POST /api/start-phase1             # Start Phase 1 benchmark
POST /api/start-phase2             # Start Phase 2 profiling (with model list)
POST /api/start-phase3             # Start Phase 3 optimization (with model list)

WS   /ws                           # WebSocket for real-time updates
```

## WebSocket Messages

The dashboard receives real-time updates via WebSocket:

```json
{
  "type": "state_update",
  "data": {
    "phase": 1,
    "status": "running",
    "current_model": "llama3.1",
    "progress": 45,
    "start_time": "2026-06-12T16:00:00"
  },
  "timestamp": "2026-06-12T16:15:30"
}
```

## File Structure

```
E:\projects\ollama-bench\
├── dashboard.py              # FastAPI backend
├── static/
│   ├── index.html           # Dashboard HTML
│   ├── style.css            # Styling
│   └── app.js               # Frontend JavaScript
├── results/                 # Results JSON files
│   ├── results_phase1_*.json
│   ├── profile_*.json
│   └── optimization_*.json
└── benchmark_state.json     # Current state
```

## Troubleshooting

**"Connection refused" error**
- Dashboard not running: `python dashboard.py`
- Check Ollama: `ollama serve` in another terminal
- Try port 8000 is not in use

**WebSocket disconnects**
- Auto-reconnects every 3 seconds
- Check browser console for errors

**No models showing**
- Make sure Ollama models are installed
- Run `ollama list` to see available models

**Phase 1 taking too long**
- This is normal - 60-120 minutes for 12 models
- Each model runs 10 prompts

**Phase 2/3 buttons disabled**
- Phase 1 hasn't completed yet
- Check progress in Phase 1 tab

## Performance Tips

1. **Start Phase 1 overnight** - It takes 1-2 hours
2. **Profile top 3-5 models** in Phase 2 - Skip slow ones
3. **Optimize on GGUF models** - Use llama.cpp for larger models
4. **Monitor GPU usage** - Check nvidia-smi during tests

## Keyboard Shortcuts

- `Ctrl+S` - Save/Export results
- `Ctrl+R` - Refresh dashboard
- `Esc` - Close modal dialogs

## Integration with CLI Tools

You can also run the phases from command line:

```bash
# Phase 1 via CLI
python ollama_api_bench.py --skip-errors -d -o results_phase1.json

# Phase 2 via CLI
python context_profiler.py llama3.1 -v -o profile_llama3.1.json

# Phase 3 via CLI
python llama_cpp_server_optimizer.py model.gguf -v -o optimization.json
```

The dashboard will detect and display these results.

## Support

Check the phase-specific guides:
- `CONTEXT_PROFILING_GUIDE.md` - Phase 2 details
- `LLAMA_CPP_OPTIMIZATION_GUIDE.md` - Phase 3 details

## Architecture

```
Browser Dashboard
    ↓ (HTTP/WebSocket)
FastAPI Backend (dashboard.py)
    ↓ (subprocess)
Phase Scripts (ollama_api_bench.py, context_profiler.py, etc.)
    ↓
Ollama API / llama.cpp
    ↓
Your Models
```

Real-time updates flow back via WebSocket to keep the UI in sync with benchmark progress.
