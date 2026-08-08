import os
from pathlib import Path

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ollama Bench</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
    <div class="topbar">
        <div class="topbar-content">
            <div class="logo">🦙 Ollama Bench</div>
            <div class="subtitle">Benchmark your local models</div>
        </div>
    </div>

    <div class="app-layout">
        <aside class="sidebar">
            <!-- Settings Section -->
            <section class="card">
                <div class="card-header">
                    <h2>⚙️ Settings</h2>
                </div>
                <div class="settings-group">
                    <div class="setting-item">
                        <label for="ollama-url">Ollama Server URL</label>
                        <input type="text" id="ollama-url" value="localhost:11434" placeholder="localhost:11434">
                    </div>
                    <div class="setting-item">
                        <label for="output-path">Output JSON File</label>
                        <input type="text" id="output-path" placeholder="Default: results.json">
                    </div>
                    <div class="setting-actions">
                        <button id="test-connection" class="btn btn-secondary btn-sm">🔌 Test Connection</button>
                        <span id="connection-status" class="connection-status"></span>
                    </div>
                </div>
            </section>

            <!-- Models Section -->
            <section class="card flex-fill">
                <div class="card-header">
                    <h2>📦 Models</h2>
                    <button id="refresh-models" class="btn btn-icon" title="Refresh Models">🔄</button>
                </div>
                <div class="models-toolbar">
                    <label class="checkbox-label">
                        <input type="checkbox" id="select-all-models" checked>
                        <span class="text-sm font-medium">Select All</span>
                    </label>
                </div>
                <div id="models-container" class="models-container">
                    <div class="empty-state">
                        <span class="empty-icon">⏳</span>
                        <p>Loading models...</p>
                    </div>
                </div>
            </section>
        </aside>

        <main class="main-content">
            <!-- Run Benchmark -->
            <section class="card run-card">
                <button id="run-benchmark" class="btn btn-run" disabled>▶️ Start Benchmark</button>
                <button id="cancel-benchmark" class="btn btn-run btn-danger" style="display: none;">⏹️ Cancel Benchmark</button>
            </section>

            <!-- Progress Section -->
            <section class="card" id="progress-section" style="display: none;">
                <div class="card-header">
                    <h2>⏳ Progress</h2>
                    <span id="progress-text" class="text-sm text-muted">Ready</span>
                </div>
                <div class="progress-bar">
                    <div id="progress-fill" class="progress-fill"></div>
                </div>
                <p id="current-model" class="text-accent font-medium mb-4"></p>
                <div id="progress-log" class="log-container"></div>
            </section>

            <!-- Results Section -->
            <section class="card" id="results-section">
                <div class="card-header">
                    <h2>🏆 Results</h2>
                </div>
                <div id="results-container">
                    <div class="empty-state">
                        <span class="empty-icon">📊</span>
                        <p>No results yet</p>
                        <span class="text-muted text-sm">Run a benchmark to see results here</span>
                    </div>
                </div>
                
                <div class="save-section" id="save-section" style="display: none;">
                    <div class="save-row">
                        <input type="text" id="save-path" class="input-field flex-1" placeholder="Save path (optional)">
                        <button id="save-results" class="btn btn-secondary">💾 Save to Server</button>
                        <button id="download-results" class="btn btn-primary">⬇️ Download</button>
                    </div>
                    <p id="save-status" class="save-status text-sm mt-2"></p>
                </div>
            </section>

            <!-- Prompts Section -->
            <section class="card">
                <div class="card-header">
                    <h2>📝 Test Prompts</h2>
                    <button id="toggle-prompts" class="btn btn-secondary btn-sm">👁️ Show Prompts</button>
                </div>
                <div id="prompts-container" style="display: none;" class="prompts-grid"></div>
            </section>
        </main>
    </div>

    <script src="/static/js/app.js"></script>
</body>
</html>
"""

CSS = """/* Modern Zinc/Slate Dark Theme */
:root {
    --bg-base: #09090b;
    --bg-card: #18181b;
    --bg-hover: #27272a;
    --border: #3f3f46;
    --border-light: #27272a;
    
    --text-main: #f4f4f5;
    --text-muted: #a1a1aa;
    
    --accent: #3b82f6;
    --accent-hover: #2563eb;
    --accent-glow: rgba(59, 130, 246, 0.2);
    
    --success: #10b981;
    --warning: #f59e0b;
    --danger: #ef4444;
    --danger-hover: #dc2626;
    
    --radius-sm: 6px;
    --radius-md: 12px;
    --radius-lg: 16px;
    
    --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    --font-mono: 'JetBrains Mono', 'Monaco', 'Consolas', monospace;
}

*, *::before, *::after {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

body {
    font-family: var(--font-sans);
    background-color: var(--bg-base);
    color: var(--text-main);
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
    min-height: 100vh;
}

/* Typography Utilities */
.text-sm { font-size: 0.875rem; }
.text-muted { color: var(--text-muted); }
.text-accent { color: var(--accent); }
.font-medium { font-weight: 500; }
.font-semibold { font-weight: 600; }
.font-mono { font-family: var(--font-mono); font-size: 0.9em; }
.text-right { text-align: right; }
.mb-4 { margin-bottom: 1rem; }
.mt-2 { margin-top: 0.5rem; }
.flex-1 { flex: 1; }

/* Layout */
.topbar {
    background: rgba(24, 24, 27, 0.8);
    backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--border-light);
    position: sticky;
    top: 0;
    z-index: 50;
}

.topbar-content {
    max-width: 1400px;
    margin: 0 auto;
    padding: 1rem 2rem;
    display: flex;
    align-items: baseline;
    gap: 1rem;
}

.logo {
    font-size: 1.5rem;
    font-weight: 700;
    letter-spacing: -0.025em;
}

.subtitle {
    color: var(--text-muted);
    font-size: 0.9rem;
}

.app-layout {
    display: flex;
    gap: 2rem;
    max-width: 1400px;
    margin: 0 auto;
    padding: 2rem;
    align-items: flex-start;
}

.sidebar {
    width: 320px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
    position: sticky;
    top: 6rem;
    max-height: calc(100vh - 8rem);
}

.main-content {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
    min-width: 0;
}

@media (max-width: 900px) {
    .app-layout { flex-direction: column; }
    .sidebar { width: 100%; position: static; max-height: none; }
}

/* Cards */
.card {
    background: var(--bg-card);
    border: 1px solid var(--border-light);
    border-radius: var(--radius-md);
    padding: 1.5rem;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -2px rgba(0, 0, 0, 0.1);
    display: flex;
    flex-direction: column;
}

.card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.25rem;
}

.card-header h2 {
    font-size: 1.125rem;
    font-weight: 600;
}

.flex-fill {
    flex: 1;
    min-height: 0;
}

/* Buttons & Inputs */
.btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    padding: 0.625rem 1rem;
    font-size: 0.875rem;
    font-weight: 500;
    border-radius: var(--radius-sm);
    border: 1px solid transparent;
    cursor: pointer;
    transition: all 0.15s ease;
    font-family: inherit;
}

.btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

.btn-sm {
    padding: 0.375rem 0.75rem;
    font-size: 0.8125rem;
}

.btn-primary {
    background: var(--accent);
    color: white;
}

.btn-primary:hover:not(:disabled) {
    background: var(--accent-hover);
}

.btn-secondary {
    background: var(--bg-hover);
    color: var(--text-main);
    border-color: var(--border);
}

.btn-secondary:hover:not(:disabled) {
    border-color: var(--text-muted);
}

.btn-danger {
    background: var(--danger);
    color: white;
}

.btn-danger:hover:not(:disabled) {
    background: var(--danger-hover);
}

.btn-icon {
    background: transparent;
    border: none;
    color: var(--text-muted);
    padding: 0.25rem;
    border-radius: var(--radius-sm);
    cursor: pointer;
    font-size: 1.1rem;
}

.btn-icon:hover {
    color: var(--text-main);
    background: var(--bg-hover);
}

.btn-run {
    width: 100%;
    padding: 1rem;
    font-size: 1.125rem;
    font-weight: 600;
    background: linear-gradient(135deg, var(--accent), #6366f1);
    color: white;
    border: none;
    border-radius: var(--radius-md);
    box-shadow: 0 4px 12px var(--accent-glow);
}

.btn-run:hover:not(:disabled) {
    transform: translateY(-1px);
    box-shadow: 0 6px 16px rgba(59, 130, 246, 0.3);
}

.btn-run.btn-danger {
    background: linear-gradient(135deg, var(--danger), #b91c1c);
    box-shadow: 0 4px 12px rgba(239, 68, 68, 0.2);
}

input[type="text"], .input-field {
    width: 100%;
    padding: 0.625rem 0.875rem;
    background: var(--bg-base);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text-main);
    font-family: inherit;
    font-size: 0.875rem;
    transition: border-color 0.15s;
}

input[type="text"]:focus, .input-field:focus {
    outline: none;
    border-color: var(--accent);
}

/* Settings */
.settings-group {
    display: flex;
    flex-direction: column;
    gap: 1rem;
}

.setting-item label {
    display: block;
    font-size: 0.875rem;
    font-weight: 500;
    margin-bottom: 0.375rem;
    color: var(--text-muted);
}

.setting-actions {
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-top: 0.5rem;
}

.connection-status {
    font-size: 0.875rem;
}
.connection-status.success { color: var(--success); }
.connection-status.error { color: var(--danger); }
.connection-status.testing { color: var(--warning); }

/* Models */
.models-toolbar {
    margin-bottom: 1rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid var(--border-light);
}

.models-container {
    overflow-y: auto;
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    padding-right: 0.5rem;
}

/* Custom Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 10px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

.model-item {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.75rem 1rem;
    background: var(--bg-base);
    border: 1px solid var(--border-light);
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: all 0.15s ease;
    user-select: none;
}

.model-item:hover {
    border-color: var(--border);
}

.model-item:has(input:checked) {
    border-color: var(--accent);
    background: rgba(59, 130, 246, 0.05);
}

.model-item input[type="checkbox"] {
    width: 16px;
    height: 16px;
    accent-color: var(--accent);
    cursor: pointer;
}

.model-name {
    font-size: 0.875rem;
    font-weight: 500;
    word-break: break-all;
}

/* Progress */
.progress-bar {
    width: 100%;
    height: 12px;
    background: var(--bg-base);
    border-radius: 999px;
    overflow: hidden;
    margin-bottom: 1rem;
    box-shadow: inset 0 1px 2px rgba(0,0,0,0.2);
}

.progress-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--accent), #8b5cf6);
    border-radius: 999px;
    transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1);
    position: relative;
    width: 0%;
}

.progress-fill::after {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
    animation: shimmer 1.5s infinite;
}

@keyframes shimmer {
    0% { transform: translateX(-100%); }
    100% { transform: translateX(100%); }
}

.log-container {
    background: var(--bg-base);
    border: 1px solid var(--border-light);
    border-radius: var(--radius-sm);
    padding: 1rem;
    height: 200px;
    overflow-y: auto;
    font-family: var(--font-mono);
    font-size: 0.8125rem;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
}

.log-entry {
    display: flex;
    gap: 0.75rem;
    line-height: 1.4;
}

.log-time { color: var(--text-muted); flex-shrink: 0; }
.log-msg { word-break: break-word; }
.log-entry.success .log-msg { color: var(--success); }
.log-entry.error .log-msg { color: var(--danger); }
.log-entry.info .log-msg { color: var(--accent); }
.log-entry.warning .log-msg { color: var(--warning); }

/* Results Table */
.table-responsive {
    overflow-x: auto;
    margin: 0 -1.5rem;
    padding: 0 1.5rem;
}

.results-table {
    width: 100%;
    border-collapse: collapse;
    text-align: left;
    white-space: nowrap;
}

.results-table th {
    padding: 0.75rem 1rem;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    border-bottom: 1px solid var(--border);
    background: var(--bg-card);
    position: sticky;
    top: 0;
    z-index: 10;
}

.results-table th.sortable {
    cursor: pointer;
    user-select: none;
    transition: color 0.15s;
}

.results-table th.sortable:hover {
    color: var(--text-main);
}

.sort-icon {
    display: inline-block;
    margin-left: 0.25rem;
    font-size: 0.8em;
}

.results-table td {
    padding: 0.875rem 1rem;
    border-bottom: 1px solid var(--border-light);
    font-size: 0.875rem;
}

.results-table tbody tr:hover {
    background: rgba(255, 255, 255, 0.02);
}

.rank-cell { font-weight: 700; font-size: 1rem; }
.rank-1 { color: #fbbf24; } /* Gold */
.rank-2 { color: #94a3b8; } /* Silver */
.rank-3 { color: #b45309; } /* Bronze */

.save-row {
    display: flex;
    gap: 0.75rem;
    margin-top: 1.5rem;
    padding-top: 1.5rem;
    border-top: 1px solid var(--border-light);
}

/* Prompts */
.prompts-grid {
    display: grid;
    gap: 1rem;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    margin-top: 1rem;
}

.prompt-item {
    background: var(--bg-base);
    border: 1px solid var(--border-light);
    padding: 1rem;
    border-radius: var(--radius-sm);
}

.prompt-category {
    display: inline-block;
    padding: 0.125rem 0.5rem;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    margin-bottom: 0.75rem;
    background: var(--bg-hover);
}

.prompt-category.reasoning { color: #c084fc; background: rgba(192, 132, 252, 0.1); }
.prompt-category.coding { color: #60a5fa; background: rgba(96, 165, 250, 0.1); }
.prompt-category.creative { color: #fb923c; background: rgba(251, 146, 60, 0.1); }
.prompt-category.factual { color: #34d399; background: rgba(52, 211, 153, 0.1); }

/* Empty States */
.empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 3rem 1rem;
    text-align: center;
    background: var(--bg-base);
    border: 1px dashed var(--border);
    border-radius: var(--radius-sm);
    color: var(--text-muted);
}

.empty-icon {
    font-size: 2.5rem;
    margin-bottom: 1rem;
    opacity: 0.5;
}

/* Toast */
.benchmark-toast {
    position: fixed;
    bottom: 1.5rem;
    right: 1.5rem;
    z-index: 9999;
    background: var(--bg-card);
    color: var(--text-main);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 0.875rem 1.25rem;
    box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3);
    font-size: 0.875rem;
    font-weight: 500;
    transform: translateY(0);
    opacity: 1;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.benchmark-toast.hidden {
    transform: translateY(100%);
    opacity: 0;
    pointer-events: none;
}

.benchmark-toast.info { border-left: 4px solid var(--accent); }
.benchmark-toast.success { border-left: 4px solid var(--success); }
.benchmark-toast.warning { border-left: 4px solid var(--warning); }
.benchmark-toast.error { border-left: 4px solid var(--danger); }
"""

JS = """let ws = null;
let availableModels = [];
let selectedModels = new Set();
let benchmarkResults = null;
let currentResultsId = null;
let toastEl = null;

// Sorting State
let sortKey = 'avg_time_ms';
let sortAsc = true;

// DOM Elements
const modelsContainer = document.getElementById('models-container');
const refreshBtn = document.getElementById('refresh-models');
const selectAllCheckbox = document.getElementById('select-all-models');
const runBtn = document.getElementById('run-benchmark');
const cancelBtn = document.getElementById('cancel-benchmark');
const progressSection = document.getElementById('progress-section');
const progressFill = document.getElementById('progress-fill');
const progressText = document.getElementById('progress-text');
const currentModel = document.getElementById('current-model');
const progressLog = document.getElementById('progress-log');
const resultsSection = document.getElementById('results-section');
const resultsContainer = document.getElementById('results-container');
const saveSection = document.getElementById('save-section');
const savePathInput = document.getElementById('save-path');
const saveBtn = document.getElementById('save-results');
const downloadBtn = document.getElementById('download-results');
const togglePromptsBtn = document.getElementById('toggle-prompts');
const promptsContainer = document.getElementById('prompts-container');
const saveStatus = document.getElementById('save-status');
const ollamaUrlInput = document.getElementById('oll