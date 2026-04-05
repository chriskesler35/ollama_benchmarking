let ws = null;
let availableModels = [];
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
const ollamaUrlInput = document.getElementById('ollama-url');
const outputPathInput = document.getElementById('output-path');
const testConnectionBtn = document.getElementById('test-connection');
const connectionStatus = document.getElementById('connection-status');

document.addEventListener('DOMContentLoaded', () => {
    loadSettings();
    setupEventListeners();
    ensureToast();
    loadPrompts();
    loadModels();
});

function ensureToast() {
    toastEl = document.getElementById('benchmark-toast');
    if (toastEl) return;

    toastEl = document.createElement('div');
    toastEl.id = 'benchmark-toast';
    toastEl.className = 'benchmark-toast hidden';
    toastEl.innerHTML = '<span id="benchmark-toast-text">Ready</span>';
    document.body.appendChild(toastEl);
}

function showToast(message, type = 'info') {
    ensureToast();
    toastEl.className = `benchmark-toast ${type}`;
    const text = document.getElementById('benchmark-toast-text');
    if (text) text.textContent = message;
}

function hideToast() {
    if (toastEl) {
        toastEl.className = 'benchmark-toast hidden';
    }
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
    const lastColon = cleaned.lastIndexOf(':');

    if (lastColon === -1) {
        return { host: cleaned || 'localhost', port: 11434 };
    }

    const host = cleaned.slice(0, lastColon) || 'localhost';
    const port = Number.parseInt(cleaned.slice(lastColon + 1), 10);

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

    ollamaUrlInput.addEventListener('change', async () => {
        saveSettings();
        await testConnection();
        await loadModels();
    });

    outputPathInput.addEventListener('change', () => {
        saveSettings();
        savePathInput.value = getOutputPath();
    });
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
            availableModels = [];
            selectedModels.clear();
            modelsContainer.innerHTML = `<p class="error-message">Error: ${escapeHtml(data.error)}</p>`;
            updateSelectAllState();
            updateRunButton();
            return;
        }

        availableModels = data.models || [];

        if (availableModels.length === 0) {
            selectedModels.clear();
            modelsContainer.innerHTML = '<p class="error-message">No models found. Install models with: <code>ollama pull &lt;model&gt;</code></p>';
            updateSelectAllState();
            updateRunButton();
            return;
        }

        selectedModels = new Set(availableModels);
        renderModels();
        updateRunButton();
        log('info', `Loaded ${availableModels.length} model(s) from ${host}:${port}`);
    } catch (error) {
        availableModels = [];
        selectedModels.clear();
        modelsContainer.innerHTML = `<p class="error-message">Failed to load models: ${escapeHtml(error.message)}</p>`;
        updateSelectAllState();
        updateRunButton();
    }
}

function renderModels() {
    modelsContainer.innerHTML = `
        <div class="model-grid">
            ${availableModels.map(model => `
                <div class="model-item">
                    <input
                        type="checkbox"
                        id="model-${escapeHtml(model)}"
                        value="${escapeHtml(model)}"
                        ${selectedModels.has(model) ? 'checked' : ''}
                    >
                    <label for="model-${escapeHtml(model)}">${escapeHtml(model)}</label>
                </div>
            `).join('')}
        </div>
    `;

    const checkboxes = modelsContainer.querySelectorAll('input[type="checkbox"]');
    checkboxes.forEach((checkbox) => {
        checkbox.addEventListener('change', (event) => {
            const model = event.target.value;
            if (event.target.checked) selectedModels.add(model);
            else selectedModels.delete(model);

            updateSelectAllState();
            updateRunButton();
        });
    });

    updateSelectAllState();
}

function toggleSelectAll() {
    const shouldSelectAll = selectAllCheckbox.checked;
    const checkboxes = modelsContainer.querySelectorAll('input[type="checkbox"]');

    selectedModels.clear();

    checkboxes.forEach((checkbox) => {
        checkbox.checked = shouldSelectAll;
        if (shouldSelectAll) {
            selectedModels.add(checkbox.value);
        }
    });

    updateRunButton();
}

function updateSelectAllState() {
    const total = availableModels.length;
    selectAllCheckbox.checked = total > 0 && selectedModels.size === total;
}

function updateRunButton() {
    runBtn.disabled = selectedModels.size === 0 || (ws && ws.readyState === WebSocket.OPEN);
}

async function loadPrompts() {
    try {
        const response = await fetch('/api/prompts');
        const data = await response.json();

        promptsContainer.innerHTML = `
            <div class="prompt-list">
                ${data.prompts.map(prompt => `
                    <div class="prompt-item">
                        <div class="prompt-category ${escapeHtml(prompt.category)}">${escapeHtml(prompt.category)}</div>
                        <div class="prompt-text">${escapeHtml(prompt.text)}</div>
                    </div>
                `).join('')}
            </div>
        `;
    } catch (error) {
        promptsContainer.innerHTML = `<p class="error-message">Failed to load prompts: ${escapeHtml(error.message)}</p>`;
    }
}

function togglePrompts() {
    const isHidden = promptsContainer.style.display === 'none' || !promptsContainer.style.display;
    promptsContainer.style.display = isHidden ? 'block' : 'none';
    togglePromptsBtn.textContent = isHidden ? '🙈 Hide Prompts' : '👁️ Show Prompts';
}

function startBenchmark() {
    if (selectedModels.size === 0) {
        showToast('Select at least one model', 'warning');
        return;
    }

    saveSettings();
    benchmarkResults = null;
    currentResultsId = null;
    saveStatus.textContent = '';
    resultsSection.style.display = 'none';
    progressSection.style.display = 'block';
    progressFill.style.width = '0%';
    progressText.textContent = 'Connecting...';
    currentModel.textContent = '';
    progressLog.innerHTML = '';

    runBtn.disabled = true;
    cancelBtn.style.display = 'inline-flex';

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws/benchmark`);

    ws.onopen = () => {
        log('info', 'Benchmark started');
        showToast('Benchmark started', 'info');

        ws.send(JSON.stringify({
            models: Array.from(selectedModels),
            ollama_url: getOllamaUrl(),
            output_path: getOutputPath() || null
        }));
    };

    ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        handleBenchmarkMessage(message);
    };

    ws.onerror = () => {
        log('error', 'WebSocket connection error');
        showToast('WebSocket connection error', 'error');
    };

    ws.onclose = () => {
        runBtn.disabled = false;
        cancelBtn.style.display = 'none';
        updateRunButton();
    };
}

function cancelBenchmark() {
    if (ws) {
        ws.close();
        ws = null;
    }

    progressText.textContent = 'Benchmark cancelled';
    currentModel.textContent = '';
    log('warning', 'Benchmark cancelled');
    showToast('Benchmark cancelled', 'warning');
    runBtn.disabled = false;
    cancelBtn.style.display = 'none';
    updateRunButton();
}

function handleBenchmarkMessage(message) {
    switch (message.type) {
        case 'start':
            progressText.textContent = `Running ${message.total_prompts} prompts per model`;
            log('info', `Benchmarking ${message.models.length} model(s) on ${message.ollama_host}:${message.ollama_port}`);
            break;

        case 'model_start':
            currentModel.textContent = `Current model: ${message.model}`;
            log('info', `Starting ${message.model}`);
            break;

        case 'prompt_done': {
            const overallPromptIndex = (message.model ? 0 : 0);
            const completedBeforeThisModel = getCompletedModelsCount();
            const totalModels = Math.max(selectedModels.size, 1);
            const progress = ((completedBeforeThisModel + ((message.prompt_index + 1) / message.total_prompts)) / totalModels) * 100;

            progressFill.style.width = `${Math.min(progress, 100)}%`;
            progressText.textContent = `${message.model} — prompt ${message.prompt_index + 1}/${message.total_prompts}`;
            log('success', `[${message.category}] ${message.model} ${message.time_ms.toFixed(0)}ms`);
            break;
        }

        case 'model_done':
            markModelComplete(message.model);
            progressFill.style.width = `${(getCompletedModelsCount() / Math.max(selectedModels.size, 1)) * 100}%`;
            log('success', `Finished ${message.model} — avg ${message.avg_time_ms.toFixed(1)}ms`);
            break;

        case 'model_error':
            log('error', `${message.model}: ${message.message}`);
            break;

        case 'complete':
            benchmarkResults = message.results || [];
            currentResultsId = message.results_id || null;
            currentModel.textContent = '';
            progressFill.style.width = '100%';
            progressText.textContent = 'Benchmark complete';
            renderResults(benchmarkResults);
            resultsSection.style.display = 'block';

            if (message.saved_to) {
                saveStatus.textContent = `Auto-saved to ${message.saved_to}`;
            }

            if (message.failed_models && message.failed_models.length > 0) {
                log('warning', `Failed models: ${message.failed_models.join(', ')}`);
            }

            showToast('Benchmark complete', 'success');

            if (ws) {
                ws.close();
                ws = null;
            }
            break;

        case 'error':
            log('error', message.message || 'Unknown benchmark error');
            progressText.textContent = 'Benchmark failed';
            showToast(message.message || 'Benchmark failed', 'error');
            if (ws) {
                ws.close();
                ws = null;
            }
            break;

        default:
            log('warning', `Unhandled event: ${message.type}`);
    }
}

const completedModels = new Set();

function markModelComplete(model) {
    completedModels.add(model);
}

function getCompletedModelsCount() {
    return completedModels.size;
}

function renderResults(results) {
    if (!results || results.length === 0) {
        resultsContainer.innerHTML = '<p class="error-message">No results available.</p>';
        return;
    }

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
                ${results.map((result, index) => `
                    <tr>
                        <td class="${index === 0 ? 'rank-1' : index === 1 ? 'rank-2' : index === 2 ? 'rank-3' : ''}">
                            ${index === 0 ? '🥇' : index === 1 ? '🥈' : index === 2 ? '🥉' : index + 1}
                        </td>
                        <td>${escapeHtml(result.model_name)}</td>
                        <td>${Number(result.avg_time_ms).toFixed(1)}</td>
                        <td>${Number(result.total_time_ms).toFixed(1)}</td>
                        <td>${Number(result.category_times.reasoning || 0).toFixed(1)}</td>
                        <td>${Number(result.category_times.coding || 0).toFixed(1)}</td>
                        <td>${Number(result.category_times.creative || 0).toFixed(1)}</td>
                        <td>${Number(result.category_times.factual || 0).toFixed(1)}</td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
}

async function saveResults() {
    if (!currentResultsId) {
        showToast('No benchmark results to save', 'warning');
        return;
    }

    try {
        const response = await fetch('/api/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                results_id: currentResultsId,
                filepath: (savePathInput.value || '').trim() || null
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Failed to save results');
        }

        saveStatus.textContent = `Saved to ${data.filepath}`;
        showToast('Results saved', 'success');
    } catch (error) {
        saveStatus.textContent = `Save failed: ${error.message}`;
        showToast(`Save failed: ${error.message}`, 'error');
    }
}

function downloadResults() {
    if (!currentResultsId) {
        showToast('No benchmark results to download', 'warning');
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

function escapeHtml(value) {
    return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}
