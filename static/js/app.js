// Ollama Bench Web UI - single source of truth (templates/index.html + /static/js/app.js)

let ws = null;
let selectedModels = new Set();
let benchmarkResults = null;
let currentResultsId = null;
let toastEl = null;

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
const savePathInput = document.getElementById('save-path');
const saveBtn = document.getElementById('save-results');
const downloadBtn = document.getElementById('download-results');
const togglePromptsBtn = document.getElementById('toggle-prompts');
const promptsContainer = document.getElementById('prompts-container');
const saveStatus = document.getElementById('save-status');

// Settings elements
const ollamaUrlInput = document.getElementById('ollama-url');
const outputPathInput = document.getElementById('output-path');
const testConnectionBtn = document.getElementById('test-connection');
const connectionStatus = document.getElementById('connection-status');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadSettings();
    loadPrompts();
    setupEventListeners();
    loadModels();
    ensureToast();
});

function ensureToast() {
    toastEl = document.getElementById('benchmark-toast');
    if (toastEl) return;

    toastEl = document.createElement('div');
    toastEl.id = 'benchmark-toast';
    toastEl.className = 'benchmark-toast hidden';
    toastEl.innerHTML = `<span id="benchmark-toast-text">Ready</span>`;
    document.body.appendChild(toastEl);
}

function showToast(message, type = 'info') {
    ensureToast();
    toastEl.className = `benchmark-toast ${type}`;
    const text = document.getElementById('benchmark-toast-text');
    if (text) text.textContent = message;
}

function hideToast() {
    if (!toastEl) return;
    toastEl.className = 'benchmark-toast hidden';
}

function loadSettings() {
    const savedUrl = localStorage.getItem('ollama_url');
    const savedPath = localStorage.getItem('output_path');

    if (savedUrl) ollamaUrlInput.value = savedUrl;
    if (savedPath) {
        outputPathInput.value = savedPath;
        savePathInput.value = savedPath;
    }
}

function saveSettings() {
    localStorage.setItem('ollama_url', getOllamaUrl());
    localStorage.setItem('output_path', getOutputPath());
}

function getOllamaUrl() {
    return (ollamaUrlInput.value || '').trim() || 'localhost:11434';
}

function getOutputPath() {
    return (outputPathInput.value || '').trim();
}

function parseHostPort(rawUrl) {
    const cleaned = rawUrl.replace(/^https?:\/\//, '').replace(/\/$/, '');
    const [hostPart, portPart] = cleaned.split(':');
    const host = hostPart || 'localhost';
    const port = Number.parseInt(portPart, 10);
    return {
        host,
        port: Number.isInteger(port) ? port : 11434
    };
}

function setupEventListeners() {
    refreshBtn.addEventListener('click', loadModels);
    selectAllCheckbox.addEventListener('change', toggleSelectAll);
    runBtn.addEventListener('click', startBenchmark);
    cancelBtn.addEventListener('click', cancelBenchmark);
    saveBtn.addEventListener('click', saveResults);
    downloadBtn.addEventListener('click', downloadResults);
    togglePromptsBtn.addEventListener('click', togglePrompts);
    testConnectionBtn.addEventListener('click', async () => {
        await testConnection();
        await loadModels();
    });

    ollamaUrlInput.addEventListener('change', () => {
        saveSettings();
        testConnection();
    });
    outputPathInput.addEventListener('change', saveSettings);
}

async function testConnection() {
    const { host, port } = parseHostPort(getOllamaUrl());

    testConnectionBtn.disabled = true;
    connectionStatus.textContent = `Testing ${host}:${port}...`;
    connectionStatus.className = 'connection-status testing';

    try {
        const res = await fetch(`/api/models?host=${encodeURIComponent(host)}&port=${port}`);
        const data = await res.json();

        if (data.error) {
            connectionStatus.textContent = `❌ ${data.error}`;
            connectionStatus.className = 'connection-status error';
            return false;
        }

        connectionStatus.textContent = `✅ Connected to ${host}:${port} (${data.models.length} model(s))`;
        connectionStatus.className = 'connection-status success';
        return true;
    } catch (err) {
        connectionStatus.textContent = `❌ Connection failed: ${err.message}`;
        connectionStatus.className = 'connection-status error';
        return false;
    } finally {
        testConnectionBtn.disabled = false;
    }
}

async function loadModels() {
    modelsContainer.innerHTML = '<p class="loading">Loading models...</p>';

    const { host, port } = parseHostPort(getOllamaUrl());

    try {
        const response = await fetch(`/api/models?host=${encodeURIComponent(host)}&port=${port}`);
        const data = await response.json();

        if (data.error) {
            modelsContainer.innerHTML = `<p class="error-message">Error: ${escapeHtml(data.error)}</p>`;
            runBtn.disabled = true;
            return;
        }

        const models = data.models || [];
        if (models.length === 0) {
            modelsContainer.innerHTML = '<p class="error-message">No models found. Install models with: <code>ollama pull &lt;model&gt;</code></p>';
            runBtn.disabled = true;
            return;
        }

        renderModels(models);
        log('info', `Loaded ${models.length} model(s) from ${host}:${port}`);
    } catch (error) {
        modelsContainer.innerHTML = `<p class="error-message">Failed to load models: ${escapeHtml(error.message)}</p>`;
        runBtn.disabled = true;
    }
}

function renderModels(models) {
    selectedModels = new Set(models);

    modelsContainer.innerHTML = `
        <div class="model-grid">
            ${models.map(model => `
                <div class="model-item">
                    <input type="checkbox" id="model-${escapeHtml(model)}"
                           value="${escapeHtml(model)}" checked
                           onchange="toggleModel('${escapeJs(model)}', this.checked)">
                    <label for="model-${escapeHtml(model)}">${escapeHtml(model)}</label>
                </div>
            `).join('')}
        </div>
    `;

    updateSelectAllState();
    updateRunButton();
}

window.toggleModel = function (model, checked) {
    if (checked) selectedModels.add(model);
    else selectedModels.delete(model);

    updateSelectAllState();
    updateRunButton();
};

function toggleSelectAll() {
    const checkboxes = modelsContainer.querySelectorAll('input[type="checkbox"]');
    selectedModels.clear();

    checkboxes.forEach(cb => {
        cb.checked = selectAllCheckbox.checked;
        if (selectAllCheckbox.checked) selectedModels.add(cb.value);
    });

    updateRunButton();
}

function updateSelectAllState() {
    const checkboxes = modelsContainer.querySelectorAll('input[type="checkbox"]');
    selectAllCheckbox.checked = checkboxes.length > 0 && selectedModels.size === checkboxes.length;
}

function updateRunButton() {
    runBtn.disabled = selectedModels.size === 0 || (ws && ws.readyState === WebSocket.OPEN);
}

async function loadPrompts() {
    try {
        const response = await fetch('/api/prompts');
        const data = await response.json();

        if (!data.prompts) {
            promptsContainer.innerHTML = '<p class="error-message">No prompts available</p>';
            return;
        }

        promptsContainer.innerHTML = `
            <div class="prompt-list">
                ${data.prompts.map(p => `
                    <div class="prompt-item">
                        <span class="prompt-category ${p.category}">${escapeHtml(p.category)}</span>
                        <p class="prompt-text">${escapeHtml(p.text)}</p>
                    </div>
                `).join('')}
            </div>
        `;
    } catch (error) {
        promptsContainer.innerHTML = '<p class="error-message">Failed to load prompts</p>';
    }
}

function togglePrompts() {
    const hidden = promptsContainer.style.display === 'none' || !promptsContainer.style.display;
    promptsContainer.style.display = hidden ? 'block' : 'none';
    togglePromptsBtn.textContent = hidden ? '🙈 Hide Prompts' : '👁️ Show Prompts';
}

function startBenchmark() {
    if (ws && ws.readyState === WebSocket.OPEN) return;

    const models = Array.from(selectedModels);
    if (models.length === 0) {
        alert('Pick at least one model first.');
        return;
    }

    const ollamaUrl = getOllamaUrl();
    const outputPath = getOutputPath();
    saveSettings();

    progressSection.style.display = 'block';
    resultsSection.style.display = 'none';
    progressFill.style.width = '0%';
    progressText.textContent = 'Starting benchmark...';
    currentModel.textContent = '';
    progressLog.innerHTML = '';

    runBtn.style.display = 'none';
    cancelBtn.style.display = 'inline-flex';
    updateRunButton();

    showToast(`🚀 Benchmark started (${models.length} model(s))`, 'info');
    log('info', `Starting benchmark for ${models.length} model(s)`);

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws/benchmark`);

    ws.onopen = () => {
        ws.send(JSON.stringify({
            models,
            ollama_url: ollamaUrl,
            output_path: outputPath || null
        }));
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleWsEvent(data, models.length);
    };

    ws.onerror = () => {
        log('error', 'WebSocket error during benchmark');
        showToast('❌ Benchmark connection error', 'error');
    };

    ws.onclose = () => {
        runBtn.style.display = 'inline-flex';
        cancelBtn.style.display = 'none';
        updateRunButton();
    };
}

function cancelBenchmark() {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.close();
        log('warning', 'Benchmark canceled by user');
        showToast('⏹️ Benchmark canceled', 'warning');
    }
}

function handleWsEvent(msg, fallbackModelCount) {
    if (msg.type === 'start') {
        progressText.textContent = `Running ${msg.total_prompts} prompts per model...`;
        showToast(`Running benchmark on ${msg.models?.length || fallbackModelCount} model(s)...`, 'info');
        return;
    }

    if (msg.type === 'model_start') {
        currentModel.textContent = `Current: ${msg.model}`;
        log('info', `🔄 ${msg.model}`);
        showToast(`Testing ${msg.model}...`, 'info');
        return;
    }

    if (msg.type === 'prompt_done') {
        const totalModels = msg.total_models || fallbackModelCount;
        const totalPrompts = msg.total_prompts || 10;
        const completedBefore = msg.model_index * totalPrompts + msg.prompt_index;
        const doneNow = completedBefore + 1;
        const totalUnits = totalModels * totalPrompts;
        const pct = Math.min(100, (doneNow / totalUnits) * 100);

        progressFill.style.width = `${pct.toFixed(1)}%`;
        progressText.textContent = `${pct.toFixed(1)}% complete`;
        log('success', `✓ ${msg.model} [${msg.category}] ${Number(msg.time_ms || 0).toFixed(0)}ms`);
        showToast(`⏳ ${pct.toFixed(1)}% complete`, 'info');
        return;
    }

    if (msg.type === 'model_done') {
        log('success', `✅ ${msg.model} complete (avg ${Number(msg.avg_time_ms || 0).toFixed(1)}ms)`);
        return;
    }

    if (msg.type === 'complete') {
        benchmarkResults = msg.results || [];
        currentResultsId = msg.results_id || null;
        progressFill.style.width = '100%';
        progressText.textContent = 'Benchmark complete';
        currentModel.textContent = '';
        renderResults(benchmarkResults);
        resultsSection.style.display = 'block';
        showToast('🎉 Benchmark complete', 'success');
        if (ws && ws.readyState === WebSocket.OPEN) ws.close();
        return;
    }

    if (msg.type === 'error') {
        log('error', msg.message || 'Unknown benchmark error');
        showToast(`❌ ${msg.message || 'Benchmark failed'}`, 'error');
        if (ws && ws.readyState === WebSocket.OPEN) ws.close();
    }
}

function renderResults(results) {
    if (!results || results.length === 0) {
        resultsContainer.innerHTML = '<p class="error-message">No results available</p>';
        return;
    }

    const sorted = [...results].sort((a, b) => a.avg_time_ms - b.avg_time_ms);

    resultsContainer.innerHTML = `
        <table class="results-table">
            <thead>
                <tr>
                    <th>Rank</th>
                    <th>Model</th>
                    <th>Avg (ms)</th>
                    <th>Total (ms)</th>
                    <th>Reasoning</th>
                    <th>Coding</th>
                    <th>Creative</th>
                    <th>Factual</th>
                </tr>
            </thead>
            <tbody>
                ${sorted.map((r, i) => {
                    const rank = i + 1;
                    const rankLabel = rank === 1 ? '🥇' : rank === 2 ? '🥈' : rank === 3 ? '🥉' : String(rank);
                    return `
                        <tr>
                            <td class="${rank <= 3 ? `rank-${rank}` : ''}">${rankLabel}</td>
                            <td>${escapeHtml(r.model_name)}</td>
                            <td class="time-cell">${Number(r.avg_time_ms).toFixed(1)}</td>
                            <td class="time-cell">${Number(r.total_time_ms).toFixed(1)}</td>
                            <td class="time-cell">${Number(r.category_times?.reasoning || 0).toFixed(1)}</td>
                            <td class="time-cell">${Number(r.category_times?.coding || 0).toFixed(1)}</td>
                            <td class="time-cell">${Number(r.category_times?.creative || 0).toFixed(1)}</td>
                            <td class="time-cell">${Number(r.category_times?.factual || 0).toFixed(1)}</td>
                        </tr>
                    `;
                }).join('')}
            </tbody>
        </table>
    `;
}

async function saveResults() {
    if (!currentResultsId) {
        saveStatus.textContent = 'No benchmark results available yet.';
        saveStatus.className = 'save-status error';
        return;
    }

    try {
        const response = await fetch('/api/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                results_id: currentResultsId,
                filepath: savePathInput.value.trim() || null
            })
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.detail || 'Failed to save results');
        }

        saveStatus.textContent = `Saved to ${data.filepath}`;
        saveStatus.className = 'save-status success';
    } catch (err) {
        saveStatus.textContent = `Save failed: ${err.message}`;
        saveStatus.className = 'save-status error';
    }
}

function downloadResults() {
    if (!currentResultsId) {
        alert('No benchmark results to download yet.');
        return;
    }
    window.location.href = `/api/download/${encodeURIComponent(currentResultsId)}`;
}

function log(type, message) {
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    entry.textContent = message;
    progressLog.appendChild(entry);
    progressLog.scrollTop = progressLog.scrollHeight;
}

function escapeHtml(str) {
    return String(str)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

function escapeJs(str) {
    return String(str).replaceAll('\\', '\\\\').replaceAll("'", "\\'");
}
