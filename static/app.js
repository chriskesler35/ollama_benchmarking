// Tab switching
document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', function() {
        document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        this.classList.add('active');
        const tabId = this.getAttribute('data-tab');
        const tab = document.getElementById(tabId);
        if (tab) tab.classList.add('active');
        if (tabId === 'scatter') renderScatter();
        if (tabId === 'phase2') loadPhase2Results();
        if (tabId === 'phase3') loadPhase3Results();
        if (tabId === 'report') renderReport();
    });
});

// WebSocket connection for real-time updates
let ws;
function connectWebSocket() {
    ws = new WebSocket(`ws://${window.location.host}/ws`);
    ws.onmessage = function(event) {
        try {
            const message = JSON.parse(event.data);
            if (message.type === 'state_update') {
                updateDashboard(message.data);
            }
        } catch(e) {
            console.error('Error parsing message:', e);
        }
    };
    ws.onerror = function(error) {
        console.error('WebSocket error:', error);
    };
    ws.onclose = function() {
        setTimeout(connectWebSocket, 3000);
    };
}

// Which progress bar / status line belongs to which phase
const PHASE_ELEMENTS = {
    1: { bar: 'p1-progress', status: 'p1-status' },
    2: { bar: 'p2-progress', status: 'p2-status' },
    3: { bar: 'p3-progress', status: 'p3-status' },
    4: { bar: 'p4-progress', status: 'p4-status' },
};

let lastModelsDone = -1;
let lastPhase = -1;

function updateDashboard(state) {
    const progress = Math.min(state.progress || 0, 100);
    const phase = state.phase || 1;

    // Route progress to the bar for the active phase
    const els = PHASE_ELEMENTS[phase];
    if (els) {
        document.getElementById(els.bar).style.width = progress + '%';
        document.getElementById(els.status).textContent = state.status || 'Idle';
    }

    // Current activity card
    document.getElementById('current-status').textContent = state.status || 'Idle';
    const modelCount = (state.models && state.models.total)
        ? ` (${state.models.done}/${state.models.total} models)` : '';
    document.getElementById('current-model').textContent = (state.current_model || 'None') + modelCount;
    document.getElementById('current-progress').textContent = progress + '%';

    // Show the Stop button only while something is actually running
    const stopBtn = document.getElementById('stop-btn');
    if (stopBtn) stopBtn.style.display = (state.status === 'running') ? 'block' : 'none';

    // Phase 2/3 are available whenever speed DATA exists (not just right after
    // a live run finishes) - updatePhaseButtons() checks the saved results.

    // Refresh result tables whenever another model finishes
    // (results are saved to disk after every model, not just at the end)
    const done = state.models ? state.models.done : 0;
    if (done !== lastModelsDone || phase !== lastPhase || state.status === 'completed') {
        lastModelsDone = done;
        lastPhase = phase;
        if (phase === 1) { loadPhase1Results(); updatePhaseButtons(); }
        if (phase === 2) loadPhase2Results();
        if (phase === 3) loadPhase3Results();
        if (phase === 4) loadAccuracyResults();
        // Keep live tabs fresh if they're the visible tab
        if (document.getElementById('scatter').classList.contains('active')) renderScatter();
        if (document.getElementById('report').classList.contains('active')) renderReport();
    }
}

function startPhase1() {
    if (confirm('Start Phase 1 speed benchmark? This can take several hours for all models.')) {
        fetch('/api/start-phase1', { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                console.log('Phase 1:', data);
                if (data.error) alert(data.error);
            });
    }
}

function startAccuracy() {
    if (confirm('Start accuracy benchmark? 30 tasks per model at temperature 0. Cloud models are excluded unless added via "+ Cloud Models".')) {
        fetch('/api/start-accuracy', { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                console.log('Accuracy:', data);
                if (data.error) alert(data.error);
            });
    }
}

function updatePhaseButtons() {
    // Phase 2/3 now discover and run all local models themselves, so they no
    // longer depend on Phase 1 data - keep them enabled.
    const p2 = document.getElementById('p2-btn');
    const p3 = document.getElementById('p3-btn');
    if (p2) p2.disabled = false;
    if (p3) p3.disabled = false;
}

function resetPhase(phase, label) {
    if (!confirm(`Clear ALL ${label} results and start over? This permanently deletes the saved result files for this phase.`)) {
        return;
    }
    fetch('/api/reset/' + phase, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.error) { alert(data.error); return; }
            console.log('Reset:', data);
            // Refresh whatever the reset cleared
            if (phase === 'speed') { loadPhase1Results(); renderScatter(); }
            if (phase === 'accuracy') { loadAccuracyResults(); renderScatter(); }
            if (phase === 'context') loadPhase2Results();
            if (phase === 'optimize') loadPhase3Results();
        });
}

function stopBenchmark() {
    if (confirm('Stop the current run? Completed models keep their results.')) {
        fetch('/api/stop', { method: 'POST' })
            .then(r => r.json())
            .then(data => console.log('Stop:', data));
    }
}

function startPhase2() {
    if (confirm('Profile context windows for ALL local models? Runs through each one automatically.')) {
        fetch('/api/start-phase2', { method: 'POST' })
            .then(r => r.json())
            .then(data => { console.log('Phase 2:', data); if (data.error) alert(data.error); });
    }
}

function startPhase3() {
    if (confirm('Optimize llama.cpp settings for ALL local models? This restarts a GPU server per setting, so it is slow on large models — you can Stop anytime.')) {
        fetch('/api/start-phase3', { method: 'POST' })
            .then(r => r.json())
            .then(data => { console.log('Phase 3:', data); if (data.error) alert(data.error); });
    }
}

const _PHASE_RESULTS_URL = {
    '1m': '/api/results/phase1',
    '4m': '/api/results/accuracy',
    '2': '/api/results/phase2',
    '3': '/api/results/phase3',
};

function showModelModal(phase, title) {
    // Lets you run a phase against just one or a few models (e.g. a model you
    // just added) instead of all of them. Sourced live from Ollama so a
    // brand-new model shows up immediately. Models that already have a
    // result for THIS phase are unchecked by default - models that don't
    // (new ones) are pre-checked, since that's the common case.
    const modal = document.getElementById('modal');
    const modalTitle = document.getElementById('modal-title');
    const modalModels = document.getElementById('modal-models');
    modalTitle.textContent = title;

    const resultsUrl = _PHASE_RESULTS_URL[phase];

    Promise.all([
        fetch('/api/models/local').then(r => r.json()),
        fetch(resultsUrl).then(r => r.json()).catch(() => null)
    ]).then(([localData, resultsData]) => {
        const models = (localData && localData.models) || [];
        if (!models.length) {
            modalModels.innerHTML = '<p>No local models found.</p>';
            modal.style.display = 'block';
            modal.dataset.phase = phase;
            return;
        }

        const done = new Set();
        if (resultsData) {
            if (Array.isArray(resultsData.results)) {
                resultsData.results.forEach(r => done.add(r.model_name));
            } else if (typeof resultsData === 'object') {
                Object.keys(resultsData).forEach(k => done.add(k));
            }
        }

        let html = '<p class="phase-desc">Pre-checked models have no result yet for this phase. Uncheck/check as needed, then Start.</p>';
        models.forEach(m => {
            const hasResult = done.has(m);
            const checkedAttr = hasResult ? '' : 'checked';
            const note = hasResult ? ' <span style="color:var(--color-text-secondary);font-size:11px;">(already has results)</span>' : '';
            html += `<label style="display:block; padding:4px 0;"><input type="checkbox" value="${m}" ${checkedAttr}> ${m}${note}</label>`;
        });
        modalModels.innerHTML = html;
        modal.style.display = 'block';
        modal.dataset.phase = phase;
    });
}

function showCloudModal(kind) {
    // kind is 'speed' or 'accuracy' - opt-in picker for ':cloud' models. These
    // run on Ollama's hosted infrastructure and spend real subscription
    // credits per request, so this is deliberately separate from the normal
    // Start button and never auto-includes anything.
    const modal = document.getElementById('modal');
    const modalTitle = document.getElementById('modal-title');
    const modalModels = document.getElementById('modal-models');
    modalTitle.textContent = 'Include Cloud Models?';

    fetch('/api/models/cloud')
        .then(r => r.json())
        .then(data => {
            const models = (data && data.models) || [];
            if (!models.length) {
                modalModels.innerHTML = '<p>No cloud models found (none tagged ":cloud" in your local Ollama).</p>';
            } else {
                let html = '<p class="phase-desc" style="color: var(--color-text-danger, #c0392b);">'
                    + '&#9888; Each checked model runs against Ollama\'s cloud API and spends your subscription credits.</p>';
                models.forEach(m => {
                    html += `<label style="display:block; padding:4px 0;"><input type="checkbox" value="${m}"> ${m}</label>`;
                });
                // Default ON: "+ Cloud Models" should mean "test these", not
                // "test these AND re-run every local model" (hours of GPU time).
                html += '<hr style="margin:14px 0; border:none; border-top:1px solid #eee;">'
                    + '<label style="display:block; padding:4px 0; font-weight:600;">'
                    + '<input type="checkbox" id="cloud-only-toggle" checked> '
                    + 'Run ONLY these cloud models</label>'
                    + '<p class="phase-desc" style="font-size:11px; margin-top:2px;">'
                    + 'Uncheck to also re-run every local model in the same pass. '
                    + 'Results merge either way, so local scores are kept.</p>';
                modalModels.innerHTML = html;
            }
            modal.style.display = 'block';
            modal.dataset.phase = kind === 'speed' ? '1c' : '4c';
        });
}

function submitModels() {
    const modal = document.getElementById('modal');
    const phase = modal.dataset.phase;
    const selected = Array.from(document.querySelectorAll('#modal-models input[type="checkbox"]:checked'))
        .map(cb => cb.value);

    if (phase === '1c' || phase === '4c') {
        modal.style.display = 'none';
        if (!selected.length) {
            // Nothing picked - just run the normal local-only start
            if (phase === '1c') startPhase1(); else startAccuracy();
            return;
        }
        const cloudOnlyEl = document.getElementById('cloud-only-toggle');
        const cloudOnly = cloudOnlyEl ? cloudOnlyEl.checked : false;
        const scopeMsg = cloudOnly
            ? `Run ${selected.length} cloud model(s) only?`
            : `Run ${selected.length} cloud model(s) PLUS every local model?`;
        if (!confirm(`${scopeMsg} This spends your Ollama cloud subscription credits.`)) {
            return;
        }
        const url = phase === '1c' ? '/api/start-phase1' : '/api/start-accuracy';
        fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ cloud_models: selected, cloud_only: cloudOnly })
        }).then(r => r.json()).then(data => {
            console.log('Start with cloud models:', data);
            if (data.error) alert(data.error);
        });
        return;
    }

    if (!selected.length) {
        alert('Please select at least one model');
        return;
    }

    if (phase === '1m' || phase === '4m') {
        const url = phase === '1m' ? '/api/start-phase1' : '/api/start-accuracy';
        fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ models: selected })
        }).then(r => r.json()).then(data => {
            console.log(`Start specific models (${phase}):`, data);
            if (data.error) alert(data.error);
            modal.style.display = 'none';
        });
        return;
    }

    const url = phase === '2' ? '/api/start-phase2' : '/api/start-phase3';
    fetch(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(selected)
    }).then(r => r.json()).then(data => {
        console.log(`Phase ${phase}:`, data);
        if (data.error) alert(data.error);
        modal.style.display = 'none';
    });
}

function engineBadge(engine) {
    if (engine === 'ollama-cloud') {
        return ' <span style="color:#d6a000;font-size:12px;">&#9729; Cloud</span>';
    }
    if (engine === 'ollama') {
        return ' <span style="color:var(--color-text-secondary);font-size:12px;">(Ollama)</span>';
    }
    return '';
}

function hfFixButton(modelName, engine) {
    // Only shown for the Ollama-fallback case: llama.cpp couldn't load this
    // model's GGUF, so offer to fetch a standard one from Hugging Face instead.
    if (engine !== 'ollama') return '';
    const safe = modelName.replace(/'/g, "\\'");
    return ` <button class="btn btn-secondary" style="width:auto; padding:2px 8px; font-size:11px; margin-left:6px;" onclick="openHfSearch('${safe}')">Get llama.cpp GGUF</button>`;
}

function openHfSearch(modelName) {
    const modal = document.getElementById('hf-modal');
    const title = document.getElementById('hf-modal-title');
    const desc = document.getElementById('hf-modal-desc');
    const body = document.getElementById('hf-modal-body');
    title.textContent = `Find a GGUF for ${modelName}`;
    desc.textContent = 'Searching Hugging Face...';
    body.innerHTML = '';
    modal.style.display = 'block';

    fetch('/api/hf/search?q=' + encodeURIComponent(modelName))
        .then(r => r.json())
        .then(data => {
            const results = (data && data.results) || [];
            if (!results.length) {
                desc.textContent = `No GGUF files found on Hugging Face for "${modelName}". Try searching huggingface.co directly.`;
                return;
            }
            desc.innerHTML = `Pick a file to download into the local GGUF cache. Once it finishes, ${modelName} will use llama.cpp on its next run instead of falling back to Ollama. <strong>This downloads real data over your connection.</strong>`;
            let html = '<table class="results-table"><thead><tr><th>Repo</th><th>File</th><th>Size</th><th></th></tr></thead><tbody>';
            results.forEach(r => {
                const repoSafe = r.repo_id.replace(/'/g, "\\'");
                const fileSafe = r.filename.replace(/'/g, "\\'");
                const sizeGb = r.size_gb || 0;
                html += `<tr>
                    <td>${r.repo_id}</td>
                    <td>${r.filename}</td>
                    <td>${r.size_gb != null ? r.size_gb.toFixed(1) + ' GB' : '?'}</td>
                    <td><button class="btn btn-primary" style="width:auto;" onclick="startHfDownload('${modelName.replace(/'/g, "\\'")}', '${repoSafe}', '${fileSafe}', ${sizeGb})">Download</button></td>
                </tr>`;
            });
            html += '</tbody></table>';
            body.innerHTML = html;
        })
        .catch(() => { desc.textContent = 'Search failed - check the dashboard log.'; });
}

function startHfDownload(modelName, repoId, filename, sizeGb) {
    const sizeNote = sizeGb ? `~${sizeGb.toFixed(1)} GB` : 'an unknown size';
    if (!confirm(`Download ${filename} (${sizeNote}) from ${repoId}? This uses real bandwidth and disk space.`)) {
        return;
    }
    fetch('/api/hf/download', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ model: modelName, repo_id: repoId, filename: filename })
    }).then(r => r.json()).then(data => {
        if (data.error) { alert(data.error); return; }
        pollHfDownload();
    });
}

let hfPollTimer = null;
function pollHfDownload() {
    const desc = document.getElementById('hf-modal-desc');
    const body = document.getElementById('hf-modal-body');
    if (hfPollTimer) clearInterval(hfPollTimer);
    hfPollTimer = setInterval(() => {
        fetch('/api/hf/download-status').then(r => r.json()).then(p => {
            if (!p || !p.status) return;
            if (p.status === 'downloading') {
                const pct = p.percent != null ? p.percent : 0;
                const doneGb = (p.bytes_done / 1e9).toFixed(2);
                const totalGb = p.bytes_total ? (p.bytes_total / 1e9).toFixed(2) : '?';
                desc.textContent = `Downloading ${p.filename}...`;
                body.innerHTML = `<div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
                    <p class="progress-text">${doneGb} / ${totalGb} GB (${pct}%)</p>`;
            } else if (p.status === 'completed') {
                clearInterval(hfPollTimer);
                desc.textContent = `Done. ${p.model} will use llama.cpp on its next Speed/Accuracy/Context run.`;
                body.innerHTML = `<p class="phase-desc">Saved to ${p.dest_path}</p>`;
            } else if (p.status === 'error') {
                clearInterval(hfPollTimer);
                desc.textContent = `Download failed: ${p.note || 'unknown error'}`;
            }
        });
    }, 1500);
}

function closeHfModal() {
    document.getElementById('hf-modal').style.display = 'none';
    if (hfPollTimer) { clearInterval(hfPollTimer); hfPollTimer = null; }
}

function loadPhase1Results() {
    fetch('/api/results/phase1')
        .then(r => r.json())
        .then(data => {
            if (!data || !data.results) return;
            const tbody = document.getElementById('phase1-body');
            tbody.innerHTML = '';
            // Fastest first
            const sorted = [...data.results].sort((a, b) =>
                (b.avg_tokens_per_sec || 0) - (a.avg_tokens_per_sec || 0));
            sorted.forEach(result => {
                const row = document.createElement('tr');
                if (result.avg_tokens_per_sec == null && result.note) {
                    // Oversized / failed-to-load model - show the reason
                    row.innerHTML = `
                        <td>${result.model_name}</td>
                        <td colspan="3" style="color: var(--color-text-danger, #c0392b);">⚠ ${result.note}</td>`;
                } else {
                    const eng = engineBadge(result.engine);
                    const fix = hfFixButton(result.model_name, result.engine);
                    const p3b = result.source === 'phase3_promotion'
                        ? ' <span title="Speed measured at optimal ctx/parallel from Phase 3" style="font-size:10px;background:#e8f0fe;color:#667eea;border-radius:4px;padding:1px 5px;font-weight:600;vertical-align:middle;">P3✓</span>'
                        : '';
                    row.innerHTML = `
                        <td>${result.model_name}${eng}${fix}${p3b}</td>
                        <td>${result.avg_tokens_per_sec != null ? result.avg_tokens_per_sec.toFixed(1) : 'N/A'}</td>
                        <td>${result.avg_time_ms != null ? result.avg_time_ms.toFixed(0) : 'N/A'}</td>
                        <td>${result.load_time_ms != null ? result.load_time_ms.toFixed(0) : 'N/A'}</td>`;
                }
                tbody.appendChild(row);
            });
        });
}

function loadAccuracyResults() {
    fetch('/api/results/accuracy')
        .then(r => r.json())
        .then(data => {
            if (!data || !data.results) return;
            const tbody = document.getElementById('accuracy-body');
            tbody.innerHTML = '';
            data.results.forEach(result => {
                const row = document.createElement('tr');
                if (result.accuracy == null) {
                    // Oversized / failed-to-load model - show the reason, not a score
                    const note = result.note || result.status || 'not run';
                    row.innerHTML = `
                        <td>${result.model_name}</td>
                        <td colspan="5" style="color: var(--color-text-danger, #c0392b);">⚠ ${note}</td>`;
                } else {
                    const cats = result.by_category || {};
                    const pct = (cat) => cats[cat] ? cats[cat].accuracy.toFixed(0) + '%' : '-';
                    const eng = engineBadge(result.engine);
                    const fix = hfFixButton(result.model_name, result.engine);
                    row.innerHTML = `
                        <td>${result.model_name}${eng}${fix}</td>
                        <td><strong>${result.accuracy.toFixed(1)}%</strong> (${result.passed}/${result.total})</td>
                        <td>${pct('coding')}</td>
                        <td>${pct('math')}</td>
                        <td>${pct('multiple_choice')}</td>
                        <td>${pct('instruction')}</td>`;
                }
                tbody.appendChild(row);
            });
        });
}

function renderScatter() {
    fetch('/api/results/combined')
        .then(r => r.json())
        .then(data => {
            const plot = document.getElementById('scatter-plot');
            const empty = document.getElementById('scatter-empty');
            const points = (data && data.points) || [];

            if (!points.length) {
                plot.innerHTML = '';
                empty.textContent = 'No models have both a speed and an accuracy score yet. '
                    + 'Run Phase 1 and the Accuracy benchmark, and dots will appear here.';
                return;
            }
            empty.textContent = '';

            // Layout
            const W = 760, H = 480;
            const m = { top: 30, right: 30, bottom: 55, left: 60 };
            const plotW = W - m.left - m.right;
            const plotH = H - m.top - m.bottom;

            // Scales. Speed (x) from 0 to a little above max; accuracy (y) 0-100.
            const maxSpeed = Math.max(...points.map(p => p.tokens_per_sec)) * 1.1 || 1;
            const xToPx = s => m.left + (s / maxSpeed) * plotW;
            const yToPx = a => m.top + (1 - a / 100) * plotH;

            const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

            let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="max-width:${W}px; width:100%; font-family:sans-serif;">`;

            // Sweet-spot shading (top-right quadrant: fast + accurate)
            const midX = xToPx(maxSpeed / 2), midY = yToPx(85);
            svg += `<rect x="${midX}" y="${m.top}" width="${m.left + plotW - midX}" height="${midY - m.top}" fill="#667eea" opacity="0.06"/>`;
            svg += `<text x="${m.left + plotW - 6}" y="${m.top + 16}" text-anchor="end" font-size="11" fill="#667eea" opacity="0.8">sweet spot: fast &amp; accurate</text>`;

            // Gridlines + Y axis labels (accuracy %)
            for (let a = 0; a <= 100; a += 20) {
                const y = yToPx(a);
                svg += `<line x1="${m.left}" y1="${y}" x2="${m.left + plotW}" y2="${y}" stroke="#eee" stroke-width="1"/>`;
                svg += `<text x="${m.left - 8}" y="${y + 4}" text-anchor="end" font-size="11" fill="#999">${a}%</text>`;
            }
            // X axis labels (tokens/sec)
            for (let i = 0; i <= 4; i++) {
                const s = (maxSpeed / 4) * i;
                const x = xToPx(s);
                svg += `<line x1="${x}" y1="${m.top}" x2="${x}" y2="${m.top + plotH}" stroke="#f5f5f5" stroke-width="1"/>`;
                svg += `<text x="${x}" y="${m.top + plotH + 18}" text-anchor="middle" font-size="11" fill="#999">${s.toFixed(0)}</text>`;
            }

            // Axis titles
            svg += `<text x="${m.left + plotW / 2}" y="${H - 12}" text-anchor="middle" font-size="13" fill="#333" font-weight="600">Speed (tokens/sec) →</text>`;
            svg += `<text x="16" y="${m.top + plotH / 2}" text-anchor="middle" font-size="13" fill="#333" font-weight="600" transform="rotate(-90 16 ${m.top + plotH / 2})">Accuracy →</text>`;

            // Points. Color by accuracy band. Cloud models render as squares -
            // their speed is network + hosted throughput, not this rig's hardware.
            const color = a => a >= 90 ? '#2e9e5b' : a >= 75 ? '#d6a000' : '#c0392b';
            points.forEach(p => {
                const x = xToPx(p.tokens_per_sec), y = yToPx(p.accuracy);
                const short = p.model.length > 22 ? p.model.slice(0, 21) + '…' : p.model;
                const isCloud = p.engine === 'ollama-cloud';
                const titleSuffix = isCloud ? ' (cloud - network speed)' : '';
                if (isCloud) {
                    svg += `<rect x="${x - 6}" y="${y - 6}" width="12" height="12" fill="${color(p.accuracy)}" opacity="0.85" stroke="white" stroke-width="1.5">`;
                    svg += `<title>${esc(p.model)}${titleSuffix}\n${p.accuracy}% accurate\n${p.tokens_per_sec} tokens/sec</title></rect>`;
                } else {
                    svg += `<circle cx="${x}" cy="${y}" r="7" fill="${color(p.accuracy)}" opacity="0.85" stroke="white" stroke-width="1.5">`;
                    svg += `<title>${esc(p.model)}\n${p.accuracy}% accurate\n${p.tokens_per_sec} tokens/sec</title></circle>`;
                }
                svg += `<text x="${x + 11}" y="${y + 4}" font-size="10" fill="#444">${esc(short)}</text>`;
            });

            svg += `</svg>`;
            plot.innerHTML = svg;
        });
}

function loadPhase2Results() {
    fetch('/api/results/phase2')
        .then(r => r.json())
        .then(data => {
            const body = document.getElementById('phase2-body');
            const models = data ? Object.keys(data) : [];
            if (!models.length) {
                body.innerHTML = '<p class="phase-desc">No context profiles yet. '
                    + 'Each model\'s result appears here as soon as it finishes profiling '
                    + 'all context sizes.</p>';
                return;
            }
            let html = '';
            models.forEach(m => {
                const p = data[m] || {};
                const a = p.analysis || {};
                const eng = p.engine === 'ollama'
                    ? ' <span style="color:var(--color-text-secondary);font-size:12px;">(Ollama)</span>' : '';
                const fix = hfFixButton(m, p.engine);
                // Oversized / no results: show the reason, skip the empty table
                if (a.status === 'too_large' || !(p.test_results && p.test_results.length)) {
                    html += `<div class="card" style="margin-bottom:16px;">
                        <h3>${m}${eng}${fix}</h3>
                        <p class="phase-desc" style="color: var(--color-text-danger, #c0392b);">
                            ⚠ ${a.note || a.recommendation || 'No results'}</p></div>`;
                    return;
                }
                let rows = '';
                (p.test_results || []).forEach(t => {
                    const tps = t.tokens_per_sec != null ? t.tokens_per_sec.toFixed(1) : '-';
                    const g = t.gpu_memory || {};
                    const split = (g.gpu0_used_mb != null)
                        ? `${g.gpu0_used_mb} / ${g.gpu1_used_mb} MB` : '-';
                    rows += `<tr><td>${t.context_size}</td><td>${tps}</td><td>${t.status}</td><td>${split}</td></tr>`;
                });
                html += `<div class="card" style="margin-bottom:16px;">
                    <h3>${m}${eng}${fix}</h3>
                    <p class="phase-desc"><strong>${a.recommendation || 'Analysis pending'}</strong></p>
                    <table class="results-table">
                        <thead><tr><th>Context</th><th>Tokens/sec</th><th>Status</th><th>GPU0 / GPU1</th></tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>`;
            });
            body.innerHTML = html;
        })
        .catch(() => {});
}

function loadPhase3Results() {
    fetch('/api/results/phase3')
        .then(r => r.json())
        .then(data => {
            const body = document.getElementById('phase3-body');
            const models = data ? Object.keys(data) : [];
            if (!models.length) {
                body.innerHTML = '<p class="phase-desc">No optimization results yet. '
                    + 'Each model\'s best concurrency + context settings appear here as it finishes.</p>';
                return;
            }
            let html = '';
            models.forEach(m => {
                const p = data[m] || {};
                const a = p.analysis || {};
                // Oversized model: show the reason, skip the empty results table
                if (a.status === 'too_large' || !(p.all_results && p.all_results.length)) {
                    html += `<div class="card" style="margin-bottom:16px;">
                        <h3>${m}</h3>
                        <p class="phase-desc" style="color: var(--color-text-danger, #c0392b);">
                            ⚠ ${a.note || a.recommendation || 'No results'}</p>
                    </div>`;
                    return;
                }
                const isOllama = p.engine === 'ollama';
                let rows = '';
                (p.all_results || []).forEach(t => {
                    const ok = `${t.successful_requests}/${t.total_requests}`;
                    const g = t.gpu_memory || {};
                    const split = (g.gpu0_used_mb != null)
                        ? `${g.gpu0_used_mb} / ${g.gpu1_used_mb} MB` : '-';
                    rows += `<tr><td>${t.parallel ?? t.concurrency}</td><td>${t.ctx_size}</td>`
                        + `<td>${t.aggregate_tokens_per_sec}</td><td>${ok}</td><td>${split}</td></tr>`;
                });
                const ts = p.tensor_split ? ` &middot; tensor-split ${p.tensor_split}` : '';
                const engineBadge = isOllama
                    ? ' <span style="font-size:11px;background:#fff3e7;color:#e67e22;border-radius:4px;padding:1px 6px;font-weight:600;">Ollama</span>'
                    : '';
                const parallelHdr  = isOllama ? 'Concurrency' : '--parallel';
                const ctxHdr       = isOllama ? 'num_ctx'     : '--ctx-size';
                const ollamaNote   = isOllama
                    ? `<p class="phase-desc" style="font-size:11px;margin-top:6px;">
                        &#9432;&nbsp;Concurrency reflects concurrent requests sent to Ollama.
                        If aggregate tok/s barely increases above 1, set
                        <code>OLLAMA_NUM_PARALLEL</code> in Ollama&rsquo;s env and restart.</p>`
                    : '';
                html += `<div class="card" style="margin-bottom:16px;">
                    <h3>${m}${engineBadge}${ts}</h3>
                    <p class="phase-desc"><strong>${a.recommendation || 'Analysis pending'}</strong></p>
                    ${ollamaNote}
                    <table class="results-table">
                        <thead><tr><th>${parallelHdr}</th><th>${ctxHdr}</th><th>Aggregate tok/s</th><th>OK</th><th>GPU0 / GPU1</th></tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>`;
            });
            body.innerHTML = html;
        })
        .catch(() => {});
}

function closeModal() {
    document.getElementById('modal').style.display = 'none';
}

function exportResults() {
    Promise.all([
        fetch('/api/results/phase1').then(r => r.json()),
        fetch('/api/results/accuracy').then(r => r.json()),
        fetch('/api/results/phase2').then(r => r.json()),
        fetch('/api/results/phase3').then(r => r.json())
    ]).then(([p1, acc, p2, p3]) => {
        const data = {
            timestamp: new Date().toISOString(),
            phase1_speed: p1,
            accuracy: acc,
            phase2_context: p2,
            phase3_optimization: p3
        };

        const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `benchmark-results-${new Date().getTime()}.json`;
        a.click();
    });
}

// Initialize
connectWebSocket();

// Load initial state and any existing results
fetch('/api/state')
    .then(r => r.json())
    .then(data => updateDashboard(data));
loadPhase1Results();
loadAccuracyResults();
updatePhaseButtons();

// Close modal on outside click
window.addEventListener('click', function(event) {
    const modal = document.getElementById('modal');
    if (event.target === modal) {
        modal.style.display = 'none';
    }
});

// ── Report Tab ───────────────────────────────────────────────────────────────

const _COMPOSITE = (acc, tps) => (acc * 0.65) + (Math.min(tps / 80, 1.0) * 100 * 0.35);
const _TIER_OF   = score => score >= 90 ? 'S' : score >= 85 ? 'A' : score >= 70 ? 'B' : score >= 15 ? 'C' : 'domain';

const _TIER_META = {
    S:      { label: 'S-Tier — Best All-Rounders',        color: '#2e9e5b', bg: '#e8f7ee', desc: 'Score ≥ 90 · high accuracy + strong throughput' },
    A:      { label: 'A-Tier — Strong Performers',        color: '#667eea', bg: '#eef0fd', desc: 'Score 85–89 · excellent across most categories' },
    B:      { label: 'B-Tier — Capable Mid-Range',        color: '#d6a000', bg: '#fefce7', desc: 'Score 70–84 · good quality, speed or size trade-off' },
    C:      { label: 'C-Tier — Slow or Limited',          color: '#e67e22', bg: '#fff3e7', desc: 'Score 15–69 · partial data, narrow capability, or very slow' },
    domain: { label: 'Domain / Specialized Fine-Tunes',   color: '#999',    bg: '#f5f5f5', desc: 'Score < 15 on general tasks — intentionally narrow' },
};

function renderReport() {
    Promise.all([
        fetch('/api/results/phase1').then(r => r.json()).catch(() => null),
        fetch('/api/results/accuracy').then(r => r.json()).catch(() => null),
    ]).then(([p1Data, accData]) => {
        const speedMap = {};
        (p1Data && p1Data.results || []).forEach(r => { speedMap[r.model_name] = r; });
        const accMap = {};
        (accData && accData.results || []).forEach(r => { accMap[r.model_name] = r; });

        const allNames = new Set([...Object.keys(speedMap), ...Object.keys(accMap)]);
        const models = [];
        allNames.forEach(name => {
            const s = speedMap[name] || {};
            const a = accMap[name]  || {};
            const tps = s.avg_tokens_per_sec ?? null;
            const acc = a.accuracy           ?? null;
            const score = (tps != null && acc != null) ? _COMPOSITE(acc, tps) : null;
            const approxScore = score ?? (acc != null ? acc * 0.65 : -1);
            models.push({
                name,
                engine:  s.engine || a.engine || '?',
                tps, acc, score, approxScore,
                loadMs:  s.load_time_ms ?? null,
                coding:  a.by_category?.coding?.accuracy          ?? null,
                math:    a.by_category?.math?.accuracy            ?? null,
                mc:      a.by_category?.multiple_choice?.accuracy ?? null,
                inst:    a.by_category?.instruction?.accuracy     ?? null,
                tier:    score != null ? _TIER_OF(score) : (acc != null ? _TIER_OF(acc * 0.65) : 'domain'),
            });
        });

        models.sort((a, b) => b.approxScore - a.approxScore);

        _reportSummary(models);
        _reportScoreChart(models);
        _reportHeatmap(models);
        _reportUseCaseGuide(models);
        _reportTierCards(models);

        const footer = document.getElementById('report-footer');
        if (footer) {
            footer.textContent = `Score = (accuracy% × 0.65) + (min(tok/s ÷ 80, 1) × 100 × 0.35)  ·  Last rendered: ${new Date().toLocaleTimeString()}  ·  Phase 2 context + Phase 3 optimization data will enrich this report once those phases are run.`;
        }
    });
}

// Summary stat cards
function _reportSummary(models) {
    const el = document.getElementById('report-summary');
    if (!el) return;
    const withBoth  = models.filter(m => m.score  != null);
    const perfect   = models.filter(m => m.acc    === 100);
    const fastAcc   = [...models].filter(m => m.acc != null && m.acc >= 90 && m.tps != null)
                       .sort((a, b) => b.tps - a.tps)[0];
    el.innerHTML = `
        <div class="report-stat">
            <div class="report-stat-val">${models.length}</div>
            <div class="report-stat-label">Models Benchmarked</div>
        </div>
        <div class="report-stat">
            <div class="report-stat-val">${withBoth.length}</div>
            <div class="report-stat-label">Full Score Available</div>
        </div>
        <div class="report-stat">
            <div class="report-stat-val">${perfect.length}</div>
            <div class="report-stat-label">Perfect Accuracy</div>
        </div>
        <div class="report-stat">
            <div class="report-stat-val">${fastAcc ? fastAcc.tps.toFixed(0) + ' tok/s' : '—'}</div>
            <div class="report-stat-label">Fastest ≥90% Accurate</div>
            ${fastAcc ? `<div class="report-stat-sub">${fastAcc.name}</div>` : ''}
        </div>`;
}

// Composite score bar chart (SVG)
function _reportScoreChart(models) {
    const el = document.getElementById('report-score-chart');
    if (!el) return;
    const scored = models.filter(m => m.score != null);
    if (!scored.length) {
        el.innerHTML = '<p class="phase-desc">Run Phase 1 (Speed) and Accuracy benchmarks to generate scores.</p>';
        return;
    }

    const esc  = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    const W    = 900;
    const LW   = 230;   // label column
    const BW   = 440;   // bar area
    const SW   = 230;   // stats column (score + acc + tps)
    const ROW  = 30;
    const PTOP = 28;    // space for axis labels at top
    const PBOT = 8;
    const H    = PTOP + scored.length * ROW + PBOT;

    const TIER_COLOR = { S: '#2e9e5b', A: '#667eea', B: '#d6a000', C: '#e67e22', domain: '#aaa' };

    let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg"
        style="width:100%;max-width:${W}px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">`;
    svg += `<rect width="${W}" height="${H}" fill="white"/>`;

    // Axis ticks at top
    [0, 25, 50, 75, 100].forEach(v => {
        const x = LW + (v / 100) * BW;
        svg += `<line x1="${x}" y1="${PTOP - 4}" x2="${x}" y2="${H - PBOT}" stroke="#f0f0f0" stroke-width="1"/>`;
        svg += `<text x="${x}" y="${PTOP - 8}" text-anchor="middle" font-size="10" fill="#ccc">${v}</text>`;
    });

    scored.forEach((m, i) => {
        const y   = PTOP + i * ROW;
        const mid = y + ROW / 2;
        const col = TIER_COLOR[m.tier] || '#667eea';

        // Alternating row tint
        if (i % 2 === 0) svg += `<rect x="${LW}" y="${y}" width="${BW + SW}" height="${ROW}" fill="#fafafa"/>`;

        // Model name — truncate at 31 chars
        const label = m.name.length > 31 ? m.name.slice(0, 30) + '…' : m.name;
        svg += `<text x="${LW - 10}" y="${mid + 4}" text-anchor="end" font-size="11" fill="#444">${esc(label)}</text>`;

        // Bar: accuracy portion (solid) + speed portion (faded)
        const bH    = ROW * 0.52;
        const bY    = mid - bH / 2;
        const accPx = (m.acc * 0.65 / 100) * BW;
        const spPx  = (Math.min(m.tps / 80, 1.0) * 35 / 100) * BW;

        svg += `<rect x="${LW}" y="${bY}" width="${accPx}" height="${bH}" fill="${col}" opacity="0.88" rx="2"/>`;
        svg += `<rect x="${LW + accPx}" y="${bY}" width="${spPx}" height="${bH}" fill="${col}" opacity="0.35" rx="2"/>`;

        // Tooltip
        const tip = `${m.name}&#10;Score: ${m.score.toFixed(1)}&#10;Accuracy: ${m.acc.toFixed(1)}%&#10;Speed: ${m.tps.toFixed(1)} tok/s`;
        svg += `<rect x="${LW}" y="${y}" width="${accPx + spPx}" height="${ROW}" fill="transparent"><title>${esc(tip)}</title></rect>`;

        // Stats column: score bold, then acc + tps smaller
        const sx = LW + BW + 10;
        svg += `<text x="${sx}" y="${mid + 1}" font-size="12" font-weight="700" fill="${col}">${m.score.toFixed(1)}</text>`;
        const metaStr = `${m.acc.toFixed(0)}% acc  ·  ${m.tps.toFixed(0)} tok/s`;
        svg += `<text x="${sx + 36}" y="${mid + 1}" font-size="10" fill="#999">${esc(metaStr)}</text>`;
    });

    // Legend at top-right
    const legendX = LW + BW + 10;
    svg += `<text x="${legendX}" y="${PTOP - 8}" font-size="9" fill="#bbb">SCORE  ←  acc · speed</text>`;

    svg += `</svg>`;
    el.innerHTML = svg;
}

// Category accuracy heatmap (HTML table)
function _reportHeatmap(models) {
    const el = document.getElementById('report-heatmap');
    if (!el) return;
    const withAcc = models.filter(m => m.acc != null);
    if (!withAcc.length) {
        el.innerHTML = '<p class="phase-desc">Run the Accuracy benchmark to populate this chart.</p>';
        return;
    }

    // color: 0%=red, 50%=yellow, 100%=green via HSL
    const cell = (val, label) => {
        if (val == null) return `<td style="color:#ccc;">—</td>`;
        const hue   = (val / 100) * 120;  // 0=red(0°) → 120=green(120°)
        const light = 92 - (val / 100) * 22;  // 92% at 0, 70% at 100
        const bg    = `hsl(${hue},70%,${light}%)`;
        const fg    = val >= 60 ? '#1a4a1a' : '#4a1a1a';
        return `<td style="background:${bg};color:${fg};">${val.toFixed(0)}%</td>`;
    };

    const overallCell = (acc) => {
        if (acc == null) return `<td>—</td>`;
        const hue   = (acc / 100) * 120;
        const light = 88 - (acc / 100) * 20;
        const bg    = `hsl(${hue},70%,${light}%)`;
        const fg    = acc >= 60 ? '#1a3a1a' : '#3a1a1a';
        return `<td style="background:${bg};color:${fg};font-weight:700;">${acc.toFixed(1)}%</td>`;
    };

    const engineNote = m => m.engine === 'ollama'
        ? ' <span style="font-size:10px;color:#aaa;">(Ollama)</span>' : '';

    let html = `<table class="heatmap-table">
        <thead><tr>
            <th>Model</th>
            <th>Overall</th>
            <th>Coding</th>
            <th>Math</th>
            <th>Multi-Choice</th>
            <th>Instructions</th>
        </tr></thead><tbody>`;

    withAcc.forEach(m => {
        const name = m.name.length > 34 ? m.name.slice(0, 33) + '…' : m.name;
        html += `<tr>
            <td>${name}${engineNote(m)}</td>
            ${overallCell(m.acc)}
            ${cell(m.coding)}
            ${cell(m.math)}
            ${cell(m.mc)}
            ${cell(m.inst)}
        </tr>`;
    });

    html += `</tbody></table>`;
    el.innerHTML = html;
}

// Use-case decision guide (dynamic from data)
function _reportUseCaseGuide(models) {
    const el = document.getElementById('report-usecases');
    if (!el) return;

    const scored = models.filter(m => m.score != null);
    if (!scored.length) {
        el.innerHTML = '<p class="phase-desc">Needs both speed and accuracy data.</p>';
        return;
    }

    const byScore  = [...scored].sort((a, b) => b.score  - a.score);
    const byTPS    = [...scored].sort((a, b) => b.tps    - a.tps);
    const byCoding = [...scored].filter(m => m.coding != null).sort((a, b) => b.coding - a.coding || b.score - a.score);
    const byInst   = [...scored].filter(m => m.inst   != null).sort((a, b) => b.inst   - a.inst   || b.score - a.score);
    const byMath   = [...scored].filter(m => m.math   != null).sort((a, b) => b.math   - a.math   || b.score - a.score);

    const meta = (m) => m ? `${m.score.toFixed(1)} score · ${m.acc.toFixed(0)}% acc · ${m.tps.toFixed(0)} tok/s` : '—';
    const metaTPS = (m) => m ? `${m.tps.toFixed(0)} tok/s · ${m.acc.toFixed(0)}% acc` : '—';

    // Best coding: top coding acc; heavy = highest coding acc with tps < 25
    const bestCoding = byCoding[0];
    const bestCodingHeavy = byCoding.filter(m => m.tps < 25 && m.coding != null).sort((a,b) => b.coding - a.coding)[0];

    // Best agentic: 100% instruction following, best score
    const bestAgent = byInst.find(m => m.inst === 100) || byInst[0];
    // Fallback for agentic: second best with 100% inst
    const bestAgentFallback = byInst.filter(m => m.inst === 100 && m !== bestAgent)[0];

    // Best general chat: top composite
    const bestChat = byScore[0];
    const bestChatAlt = byScore[1];

    // Ultra-fast: highest TPS with acc >= 70%
    const bestFast = byTPS.find(m => m.acc >= 70);

    // Best reasoning (math + mc + slow ok)
    const bestReason = byMath[0];

    // Best for instruction / structured output: top inst acc + fast
    const bestStruct = byInst[0];

    const card = (icon, title, desc, picks) => {
        const pickRows = picks.filter(Boolean).map(p =>
            `<div class="usecase-pick-row">
                <span class="usecase-pick-label">${p.label}</span>
                <span class="usecase-pick-model">${p.model ? p.model.name : '—'}</span>
                ${p.meta ? `<span class="usecase-pick-meta">${p.meta}</span>` : ''}
            </div>`
        ).join('');
        return `<div class="usecase-card">
            <div class="usecase-card-header">
                <span class="usecase-icon">${icon}</span>
                <span class="usecase-title">${title}</span>
            </div>
            <div class="usecase-desc">${desc}</div>
            <div class="usecase-pick">${pickRows}</div>
        </div>`;
    };

    el.innerHTML = [
        card('⚡', 'Agentic Spin-Ups',
            'Fast cold-start, reliable tool-calling format, many parallel agents',
            [
                { label: 'Primary',  model: bestAgent,         meta: meta(bestAgent) },
                { label: 'Fallback', model: bestAgentFallback, meta: meta(bestAgentFallback) },
            ]),
        card('💻', 'Coding Assistant',
            'Code generation, review, debugging — fast for routine, heavy for hard tasks',
            [
                { label: 'Fast',  model: bestCoding,      meta: `${bestCoding?.coding?.toFixed(0)}% coding · ${meta(bestCoding)}` },
                { label: 'Heavy', model: bestCodingHeavy, meta: bestCodingHeavy ? `${bestCodingHeavy.coding?.toFixed(0)}% coding · ${bestCodingHeavy.tps?.toFixed(0)} tok/s` : '—' },
            ]),
        card('💬', 'General Chat / Q&A',
            'Best overall composite — accuracy + speed balanced',
            [
                { label: 'Best',  model: bestChat,    meta: meta(bestChat) },
                { label: 'Alt',   model: bestChatAlt, meta: meta(bestChatAlt) },
            ]),
        card('🏎️', 'Ultra-Fast Routing',
            'Sub-second triage, classification, deciding which heavier model to invoke',
            [
                { label: 'Fastest', model: bestFast, meta: metaTPS(bestFast) },
            ]),
        card('🧮', 'Math & Reasoning',
            'Highest math accuracy — formal proofs, multi-step problem solving',
            [
                { label: 'Best', model: bestReason, meta: `${bestReason?.math?.toFixed(0)}% math · ${meta(bestReason)}` },
            ]),
        card('📋', 'Structured Output',
            'JSON, tool calls, strict format compliance — instruction-following accuracy is key',
            [
                { label: 'Best', model: bestStruct, meta: `${bestStruct?.inst?.toFixed(0)}% inst · ${meta(bestStruct)}` },
            ]),
    ].join('');
}

// Tier breakdown cards
function _reportTierCards(models) {
    const el = document.getElementById('report-tiers');
    if (!el) return;

    const tiers = ['S', 'A', 'B', 'C', 'domain'];
    const groups = {};
    tiers.forEach(t => { groups[t] = []; });
    models.forEach(m => { if (groups[m.tier]) groups[m.tier].push(m); });

    let html = '<div style="margin-bottom:8px;"><h2 style="color:#333;font-size:18px;margin-bottom:4px;">Model Tiers</h2><p class="phase-desc">Grouped by composite score bracket.</p></div>';

    tiers.forEach(t => {
        const grp = groups[t];
        if (!grp.length) return;
        const { label, color, bg, desc } = _TIER_META[t];

        const chips = grp.map(m => {
            const scoreStr = m.score != null ? `${m.score.toFixed(1)}` : (m.acc != null ? `${m.acc.toFixed(0)}% acc` : '?');
            const tpsStr   = m.tps  != null ? ` · ${m.tps.toFixed(0)} t/s` : '';
            return `<div class="model-chip" style="color:${color};border-color:${color};background:${bg};">
                <span class="model-chip-name">${m.name}</span>
                <span class="model-chip-meta">${scoreStr}${tpsStr}</span>
            </div>`;
        }).join('');

        html += `<div class="report-tier">
            <div class="report-tier-header">
                <div class="tier-badge" style="background:${color};">${t === 'domain' ? '★' : t}</div>
                <div>
                    <div class="report-tier-title">${label}</div>
                    <div class="report-tier-desc">${desc}</div>
                </div>
            </div>
            <div class="model-chips">${chips}</div>
        </div>`;
    });

    el.innerHTML = html;
}
