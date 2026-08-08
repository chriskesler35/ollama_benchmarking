# Dashboard Startup Guide

## Quick Start - 3 Ways to Launch

### Method 1: Double-Click the Batch File (Easiest) ⭐

1. Navigate to: `E:\projects\ollama-bench\`
2. Double-click: `start-dashboard.bat`
3. **Done!** Dashboard opens automatically in your browser

### Method 2: Desktop Shortcut (Fastest)

**First time setup:**
1. Open File Explorer
2. Navigate to: `E:\projects\ollama-bench\`
3. Right-click `create-shortcut.vbs`
4. Click "Run with CScript"
5. Shortcut appears on your desktop!

**After setup:**
- Just double-click the "Benchmark Dashboard" shortcut on your desktop

### Method 3: Command Line

```bash
cd E:\projects\ollama-bench
python dashboard.py
```

Then manually open: http://localhost:8000

---

## What the Batch File Does

The `start-dashboard.bat` script automatically:

✅ Checks if Python is installed  
✅ Checks if required packages are installed (auto-installs if needed)  
✅ Verifies Ollama server is running  
✅ Starts the FastAPI backend  
✅ Waits 3 seconds for server to start  
✅ Opens http://localhost:8000 in your browser  
✅ Shows you a confirmation message  

---

## First-Time Setup

### 1. Install Dependencies (one-time only)

```bash
pip install fastapi uvicorn websockets llama-cpp-python pynvml
```

Or if you already have everything:
```bash
pip install -r requirements.txt
```

### 2. Make Sure Ollama is Running

Open a terminal and run:
```bash
ollama serve
```

**Important:** Keep Ollama running in the background while using the dashboard.

### 3. Create Desktop Shortcut (optional)

```bash
# In PowerShell or Command Prompt
cd E:\projects\ollama-bench
create-shortcut.vbs
```

Or manually create a shortcut:
- Right-click desktop → New → Shortcut
- Target: `E:\projects\ollama-bench\start-dashboard.bat`
- Name: `Benchmark Dashboard`

---

## Troubleshooting

### "Python not found"
- Install Python 3.10+: https://www.python.org/downloads/
- Add to PATH during installation

### "FastAPI not found" 
- Automatically installs on first run
- Or manually: `pip install fastapi uvicorn websockets`

### "Port 8000 already in use"
- Another app is using port 8000
- Change in `dashboard.py` line: `port=8000`
- Or kill the process: `netstat -ano | findstr :8000`

### "Ollama not responding"
- Start Ollama: `ollama serve`
- Keep it running in background
- Benchmark still works, but Phase 1 may fail

### Browser doesn't open
- Dashboard is still running on http://localhost:8000
- Open manually in your browser

### Dashboard starts but no connection
- Wait 5 seconds (server takes time to initialize)
- Refresh browser (F5)
- Check browser console for errors (F12)

---

## What Happens When You Start

**Terminal Window:**
```
====================================================
     Benchmark Dashboard - Starting...
====================================================

Checking Ollama server...
Starting FastAPI server...
Waiting for server to start...
Opening dashboard in browser...

====================================================
Dashboard is running!
- Server: http://localhost:8000
- Close the command window to stop the dashboard
====================================================
```

**Browser Opens:**
- Dashboard UI loads at http://localhost:8000
- Real-time WebSocket connection established
- Ready to start Phase 1 benchmark

---

## During Operation

### Keep These Running:
- ✅ Ollama server (separate terminal: `ollama serve`)
- ✅ Dashboard server (the command window from batch file)
- ✅ Browser tab (http://localhost:8000)

### What You Can Do:
- ✅ Monitor Phase 1 progress in real-time
- ✅ Switch between tabs while waiting
- ✅ Select models for Phase 2 & 3 after Phase 1 completes
- ✅ Export results while running

### When Phase 1 is Running:
- Phase 1 is running in the background
- Dashboard updates every second
- You can switch to other windows
- Don't close the command window!

---

## Stopping the Dashboard

**To stop the dashboard:**
1. Close the command window (the one showing FastAPI logs)
2. Or press `Ctrl+C` in that window

**To pause a benchmark:**
- Phase 1: Close the window, restart later (results saved)
- Phase 2/3: Same - results are saved and can be resumed

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `F5` | Refresh dashboard |
| `Ctrl+W` | Close browser tab (also stops connection) |
| `Ctrl+Shift+Delete` | Open browser DevTools (debug) |

---

## After First Startup

### Subsequent startups are instant:
1. Double-click `start-dashboard.bat` (or use shortcut)
2. Browser opens immediately
3. You're connected and ready to go!

---

## Advanced: Customize the Batch File

Edit `start-dashboard.bat` to:

**Change port (if 8000 is in use):**
```batch
python dashboard.py --port 8001
```

**Run in specific Python venv:**
```batch
call venv\Scripts\activate.bat
python dashboard.py
```

**Add logging to file:**
```batch
python dashboard.py > dashboard.log 2>&1
```

---

## Production Tip

If you want the dashboard to run in the background:

**Create a Scheduled Task:**
1. Open Task Scheduler (Ctrl+Shift+Esc)
2. Create Basic Task
3. Name: "Benchmark Dashboard"
4. Trigger: At startup
5. Action: Run `start-dashboard.bat`
6. Check "Run with highest privileges"

Then the dashboard auto-starts when you boot up!

---

## Next Steps

1. **Click start-dashboard.bat** 🚀
2. **Phase 1 starts automatically** (or press button)
3. **Monitor progress in real-time** 📊
4. **When done, select models for Phase 2** 🎯
5. **Get production-ready configs** ⚙️

---

**Ready? Double-click `start-dashboard.bat` and let's go!** 🎉
