// State
let models = [];
let selectedModels = new Set();
let isRunning = false;
let eventSource = null;

// DOM Elements
const modelsContainer = document.getElementById('models-container');
const refreshModelsBtn = document.getElementById('refresh-models');
const selectAllCheckbox = document.getElementById('select-all-models');
const runBenchmarkBtn = document.getElementById('run-benchmark');
const cancelBenchmarkBtn = document.getElementById('cancel-benchmark');
const progressSection = document.getElementById('progress-section');
const progressFill = document.getElementById('progress-fill');
const progressText = document.getElementById('progress-text');
const progressLog = document.getElementById('progress-log');
const resultsSection = document.getElementById('results-section');
const resultsContainer = document.getElementById('results-container');
const loadResultsBtn = document.getElementById('load-results');
const previousResults = document.getElementById('previous-results');
const togglePromptsBtn = document.getElementById('toggle-prompts');
const promptsContainer = document.getElementById('prompts-container');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    fetchModels();
    fetchPrompts();
});

// Fetch models
async function fetchModels() {
    try {
        modelsContainer.innerHTML = '<p class="loading">Loading models...</p>';
        
        const response = await fetch('/api/models');
        const data = await response.json();
        
        models = data.models || [];
        
        if (models.length === 0) {
            modelsContainer.innerHTML = '<p class="error-message">No models found. Install models with: <code>ollama pull &lt;model&gt;</code></p>';
            return;
        }
        
        renderModels();
    } catch (error) {
        modelsContainer.innerHTML = `<p class="error-message">Failed to load models: ${error.message}. Make sure Ollama is running.</p>`;
    }
}

// Render model checkboxes
function renderModels() {
    const html = `
        <div class="model-grid">
            ${models.map(model => `
                <div class="model-item">
                    <input type="checkbox" id="model-${escapeHtml(model)}" 
                           value="${escapeHtml(model)}" 
                           ${selectedModels.has(model) || selectedModels.size === 0 ? 'checked' : ''}
                           onchange="toggleModel('${escapeHtml(model)}', this.checked)">
                    <label for="model-${escapeHtml(model)}">${escapeHtml(model)}</label>
                </div>
            `).join('')}
        </div>
    `;
    modelsContainer.innerHTML = html;
    
    // Update selected models
    if (selectedModels.size === 0) {
        models.forEach(m => selectedModels.add(m));
    }
    
    updateSelectAllCheckbox();
}

// Toggle model selection
function toggleModel(model, checked) {
    if (checked) {
        selectedModels.add(model);
    } else {
        selectedModels.delete(model);
    }
    updateSelectAllCheckbox();
}

// Update select all checkbox state
function updateSelectAllCheckbox() {
    selectAllCheckbox.checked = selectedModels.size === models.length && models.length > 0;
}

// Select all toggle
selectAllCheckbox.addEventListener('change', (e) => {
    if (e.target.checked) {
        models.forEach(m => selectedModels.add(m));
    } else {
        selectedModels.clear();
    }
    renderModels();
});

// Refresh models
refreshModelsBtn.addEventListener('click', fetchModels);

// Run benchmark
runBenchmarkBtn.addEventListener('click', startBenchmark);
cancelBenchmarkBtn.addEventListener('click', cancelBenchmark);

async function startBenchmark() {
    if (isRunning) return;
    
    const modelsToBenchmark = Array.from(selectedModels);
    
    if (modelsToBenchmark.length === 0) {
        alert('Please select at least one model');
        return;
    }
    
    isRunning = true;
    runBenchmarkBtn.disabled = true;
    runBenchmarkBtn.style.display = 'none';
    cancelBenchmarkBtn.style.display = 'inline-flex';
    
    progressSection.style.display = 'block';
    resultsSection.style.display = 'none';
    progressLog.innerHTML = '';
    progressFill.style.width = '0%';
    progressText.textContent = 'Starting benchmark...';
    
    addLogEntry('Starting benchmark...', 'info');
    
    try {
        eventSource = new EventSource('/api/benchmark');
        
        // We need to POST the models, but EventSource is GET-only
        // So we'll use fetch with POST and handle the stream manually
        eventSource.close();
        
        const response = await fetch('/api/benchmark', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                models: modelsToBenchmark
            })
        });
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        
        let buffer = '';
        let totalModels = modelsToBenchmark.length;
        let completedModels = 0;
        let currentModelPrompts = 0;
        let totalPrompts = 10;
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            
            // Process SSE events
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const event = JSON.parse(line.slice(6));
                        handleProgressEvent(event, {
                            totalModels,
                            totalPrompts,
                            completedModels,
                            currentModelPrompts
                        });
                        
                        if (event.type === 'model_done') {
                            completedModels++;
                        }
                        if (event.type === 'prompt_done') {
                            currentModelPrompts++;
                        }
                        if (event.type === 'start') {
                            totalModels = event.data.models?.length || totalModels;
                            totalPrompts = event.data.total_prompts || totalPrompts;
                        }
                    } catch (e) {
                        console.error('Failed to parse event:', line, e);
                    }
                }
            }
        }
        
    } catch (error) {
        addLogEntry(`Error: ${error.message}`, 'error');
    } finally {
        isRunning = false;
        runBenchmarkBtn.disabled = false;
        runBenchmarkBtn.style.display = 'inline-flex';
        cancelBenchmarkBtn.style.display = 'none';
    }
}

function handleProgressEvent(event, state) {
    const { type, data } = event;
    
    switch (type) {
        case 'start':
            addLogEntry(`Benchmarking ${data.models.length} model(s)...`, 'info');
            break;
            
        case 'model_start':
            addLogEntry(`🔄 Benchmarking: ${data.model}`, 'info');
            progressText.textContent = `Benchmarking ${data.model}...`;
            state.currentModelPrompts = 0;
            break;
            
        case 'prompt_done':
            const promptProgress = ((data.prompt_index + 1) / state.totalPrompts) * 100;
            const overallProgress = ((state.completedModels + (data.prompt_index + 1) / state.totalPrompts) / state.totalModels) * 100;
            progressFill.style.width = `${overallProgress}%`;
            addLogEntry(`  ✓ [${data.category}] ${data.time_ms.toFixed(0)}ms`, 'success');
            break;
            
        case 'model_done':
            addLogEntry(`✅ ${data.model} - Avg: ${data.avg_time_ms.toFixed(0)}ms`, 'success');
            break;
            
        case 'complete':
            addLogEntry('Benchmark complete!', 'success');
            progressText.textContent = 'Complete!';
            progressFill.style.width = '100%';
            renderResults(data.results);
            break;
            
        case 'error':
            addLogEntry(`Error: ${data.message}`, 'error');
            progressText.textContent = 'Error occurred';
            break;
    }
}

function addLogEntry(message, type = 'info') {
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    entry.textContent = message;
    progressLog.appendChild(entry);
    progressLog.scrollTop = progressLog.scrollHeight;
}

function cancelBenchmark() {
    if (eventSource) {
        eventSource.close();
    }
    isRunning = false;
    runBenchmarkBtn.disabled = false;
    runBenchmarkBtn.style.display = 'inline-flex';
    cancelBenchmarkBtn.style.display = 'none';
    progressText.textContent = 'Cancelled';
    addLogEntry('Benchmark cancelled', 'error');
}

// Render results
function renderResults(results) {
    if (!results || results.length === 0) {
        resultsContainer.innerHTML = '<p>No results to display</p>';
        resultsSection.style.display = 'block';
        return;
    }
    
    const html = `
        <table class="results-table">
            <thead>
                <tr>
                    <th>Rank</th>
                    <th>Model</th>
                    <th>Avg Time (ms)</th>
                    <th>Total Time (ms)</th>
                    <th>Reasoning</th>
                    <th>Coding</th>
                    <th>Creative</th>
                    <th>Factual</th>
                </tr>
            </thead>
            <tbody>
                ${results.map((r, i) => `
                    <tr>
                        <td class="rank-${i + 1}">${getRankEmoji(i + 1)}</td>
                        <td>${escapeHtml(r.model_name)}</td>
                        <td class="time-cell">${r.avg_time_ms.toFixed(1)}</td>
                        <td class="time-cell">${r.total_time_ms.toFixed(1)}</td>
                        <td class="time-cell">${(r.category_times?.reasoning || 0).toFixed(1)}</td>
                        <td class="time-cell">${(r.category_times?.coding || 0).toFixed(1)}</td>
                        <td class="time-cell">${(r.category_times?.creative || 0).toFixed(1)}</td>
                        <td class="time-cell">${(r.category_times?.factual || 0).toFixed(1)}</td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
    
    resultsContainer.innerHTML = html;
    resultsSection.style.display = 'block';
}

function getRankEmoji(rank) {
    switch (rank) {
        case 1: return '🥇';
        case 2: return '🥈';
        case 3: return '🥉';
        default: return rank;
    }
}

// Load previous results
loadResultsBtn.addEventListener('click', async () => {
    try {
        const response = await fetch('/api/results');
        const data = await response.json();
        
        if (!data.results || data.results.length === 0) {
            previousResults.innerHTML = '<p>No previous results found</p>';
            previousResults.style.display = 'block';
            return;
        }
        
        previousResults.innerHTML = `
            <p style="margin-bottom: 1rem; color: var(--text-secondary);">
                Last run: ${new Date(data.timestamp).toLocaleString()}
            </p>
        `;
        renderResults(data.results);
        previousResults.style.display = 'block';
    } catch (error) {
        previousResults.innerHTML = `<p class="error-message">Failed to load results: ${error.message}</p>`;
        previousResults.style.display = 'block';
    }
});

// Fetch and display prompts
async function fetchPrompts() {
    try {
        const response = await fetch('/api/prompts');
        const data = await response.json();
        
        const html = data.prompts.map(p => `
            <div class="prompt-item">
                <span class="prompt-category ${p.category}">${p.category}</span>
                <p class="prompt-text">${escapeHtml(p.text)}</p>
            </div>
        `).join('');
        
        promptsContainer.innerHTML = html;
    } catch (error) {
        promptsContainer.innerHTML = '<p class="error-message">Failed to load prompts</p>';
    }
}

// Toggle prompts visibility
togglePromptsBtn.addEventListener('click', () => {
    const isVisible = promptsContainer.style.display !== 'none';
    promptsContainer.style.display = isVisible ? 'none' : 'block';
    togglePromptsBtn.textContent = isVisible ? '👁️ Show Prompts' : '👁️ Hide Prompts';
});

// Utility: escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
