// Глобальные переменные
let isRunning = false;
let updateInterval = null;
let currentConfig = {};
let startTime = null;
let chart = null;
let candleSeries = null;
let historyData = [];
let sortConfig = { key: 'timestamp', direction: 'desc' };

const POPULAR_PAIRS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "MATICUSDT", "DOTUSDT", "LTCUSDT",
    "ATOMUSDT", "LINKUSDT", "UNIUSDT", "BCHUSDT", "ETCUSDT",
    "FILUSDT", "NEARUSDT", "ALGOUSDT", "ICPUSDT", "APEUSDT"
];

// Инициализация
document.addEventListener('DOMContentLoaded', () => {
    updateKamchatkaTime(); // Start clock IMMEDIATELY
    setInterval(updateKamchatkaTime, 1000);

    initTWA();
    fetchStatus();
    startUiUpdater();
    initDataList();
    initChart();
});

// Kamchatka Time (UTC+12)
function updateKamchatkaTime() {
    try {
        const now = new Date();
        // Get UTC time + 12 hours
        const kamchatkaOffset = 12 * 60; // minutes
        const utc = now.getTime() + (now.getTimezoneOffset() * 60000);
        const kamchatka = new Date(utc + (kamchatkaOffset * 60000));

        const timeStr = kamchatka.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const dateStr = kamchatka.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' });

        const el = document.getElementById('liveTime');
        if (el) el.textContent = `${dateStr} ${timeStr} (Камчатка)`;
    } catch (e) {
        console.error('Time update error', e);
    }
}

function initTWA() {
    if (window.Telegram && window.Telegram.WebApp) {
        const twa = window.Telegram.WebApp;
        twa.ready();
        twa.expand();

        if (twa.initData) {
            fetch('/api/auth/twa', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ initData: twa.initData })
            }).then(res => {
                if (res.ok) {
                    console.log("TWA Auth Success");
                    fetchStatus(); // Refresh status after auth
                }
            });
        }
    }
}

function initDataList() {
    const dl = document.getElementById('cryptoPairs');
    if (dl) dl.innerHTML = POPULAR_PAIRS.map(p => `<option value="${p}">`).join('');
}

function startUiUpdater() {
    // Timer update - every 1 second (smooth)
    setInterval(() => {
        if (startTime) updateTimer();
    }, 1000);

    // Status & logs - every 10 seconds
    updateInterval = setInterval(() => {
        fetchStatus();
        fetchLogs();
        fetchLLMStatus(); // Update LLM provider status
    }, 10000);

    // Heavy data - every 30 seconds
    setInterval(() => {
        fetchHistory();
        fetchAnalytics();
        fetchEquity();
        fetchBalance();
        fetchStats();
        fetchLearnings();
        if (candleSeries) loadChartData();
    }, 30000);

    // Initial load
    fetchEquity();
    fetchBalance();
    fetchStats();
    fetchLLMStatus(); // Initial LLM status
    fetchLearnings();
}

// Header Stats (Win Rate, Today PnL, Open Positions)
async function fetchStats() {
    try {
        const res = await fetch('/api/stats');
        const data = await res.json();

        const wrEl = document.getElementById('statWinRate');
        const pnlEl = document.getElementById('statTodayPnl');
        const openEl = document.getElementById('statOpenPos');

        if (wrEl && data.win_rate !== undefined) {
            wrEl.textContent = `${data.win_rate.toFixed(0)}%`;
        }

        if (pnlEl && data.today_pnl !== undefined) {
            const pnl = data.today_pnl;
            pnlEl.textContent = `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}`;
            pnlEl.style.color = pnl >= 0 ? '#22c55e' : '#ef4444';
        }

        if (openEl && data.open_positions !== undefined) {
            openEl.textContent = data.open_positions;
        }

        // Sound alert on new signal
        if (data.new_signal && window.soundEnabled !== false) {
            playSignalSound();
        }
    } catch (e) {
        console.log('Stats fetch error:', e);
    }
}

// Sound Alert
function playSignalSound() {
    try {
        const audio = new Audio('data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1fdJivrJBhNjVgodDbq2EcBj+a2teleAN');
        audio.volume = 0.5;
        audio.play().catch(() => { });
    } catch (e) { }
}

// Real Balance from Bybit API
async function fetchBalance() {
    try {
        const res = await fetch('/api/balance');
        const data = await res.json();

        const balanceEl = document.getElementById('realBalance');
        const pnlEl = document.getElementById('unrealizedPnl');
        const modeEl = document.getElementById('balanceMode');

        if (balanceEl && data.balance !== undefined) {
            balanceEl.textContent = `$${data.balance.toFixed(2)}`;
            balanceEl.style.color = data.balance >= 0 ? '#22c55e' : '#ef4444';
        }

        if (pnlEl && data.unrealized_pnl !== undefined) {
            const pnl = data.unrealized_pnl;
            pnlEl.textContent = `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}`;
            pnlEl.style.color = pnl >= 0 ? '#22c55e' : '#ef4444';
        }

        if (modeEl && data.mode) {
            modeEl.textContent = data.mode === 'demo' ? '🧪 DEMO' : '⚡ REAL';
        }

        const openEl = document.getElementById('statOpenPos');
        if (openEl && data.open_positions !== undefined) {
            openEl.textContent = data.open_positions;
        }

        // Update Exposure Protection
        const exposureEl = document.getElementById('totalExposure');
        if (exposureEl && data.positions) {
            const totalVal = data.positions.reduce((acc, p) => acc + (p.size * p.mark_price), 0);
            exposureEl.textContent = `$${totalVal.toFixed(2)}`;
        }

        // Рендерим таблицу открытых позиций
        const positionsList = document.getElementById('activePositionsList');
        if (positionsList && data.positions) {
            if (data.positions.length === 0) {
                positionsList.innerHTML = '<tr><td colspan="6" style="text-align:center; padding: 20px; color: #64748b;">Нет открытых сделок</td></tr>';
            } else {
                positionsList.innerHTML = data.positions.map(p => {
                    const sideClass = p.side.toLowerCase() === 'buy' ? 'badge-buy' : 'badge-sell';
                    const pnlColor = p.unrealised_pnl >= 0 ? '#22c55e' : '#ef4444';
                    const pnlSymbol = p.unrealised_pnl >= 0 ? '+' : '';
                    return `
                        <tr>
                            <td><b>${p.symbol}</b></td>
                            <td><span class="badge ${sideClass}">${p.side}</span></td>
                            <td>${p.size}</td>
                            <td>$${p.entry_price.toFixed(p.entry_price < 1 ? 4 : 2)}</td>
                            <td>$${p.mark_price.toFixed(p.entry_price < 1 ? 4 : 2)}</td>
                            <td style="color: ${pnlColor}; font-weight: bold;">${pnlSymbol}$${p.unrealised_pnl.toFixed(2)}</td>
                        </tr>
                    `;
                }).join('');
            }
        }
    } catch (e) {
        console.log('Balance fetch error:', e);
    }
}

async function fetchLearnings() {
    try {
        const res = await fetch('/api/ai/learnings');
        const data = await res.json();
        const el = document.getElementById('aiLearnings');
        if (el && data.learned_context) {
            el.textContent = data.learned_context;
        }
    } catch (e) {
        console.log('Learnings fetch error:', e);
    }
}

// Equity Curve Chart
async function fetchEquity() {
    try {
        const res = await fetch('/api/equity');
        const data = await res.json();

        if (data.curve && data.curve.length > 0) {
            renderEquityChart(data.curve, data.current);
        }
    } catch (e) {
        console.log('Equity fetch error:', e);
    }
}

function renderEquityChart(curve, current) {
    const container = document.getElementById('equityChart');
    if (!container) return;

    // Simple bar visualization
    const maxVal = Math.max(...curve.map(p => p.value), 100);
    const minVal = Math.min(...curve.map(p => p.value), 0);
    const range = maxVal - minVal || 1;

    let html = `<div style="display:flex; align-items:flex-end; height:100%; gap:2px;">`;

    curve.slice(-20).forEach((p, i) => {
        const height = ((p.value - minVal) / range) * 100;
        const color = p.value >= 100 ? '#22c55e' : '#ef4444';
        const tooltip = `$${p.value.toFixed(2)}${p.pnl ? ' (PnL: $' + p.pnl.toFixed(2) + ')' : ''}`;
        html += `<div style="flex:1; height:${height}%; background:${color}; border-radius:2px 2px 0 0; min-width:8px;" title="${tooltip}"></div>`;
    });

    html += `</div>`;
    html += `<div style="text-align:center; margin-top:5px; font-size:1.2em; font-weight:bold; color:${current >= 100 ? '#22c55e' : '#ef4444'};">$${current.toFixed(2)}</div>`;

    container.innerHTML = html;
}

// === API CALLS ===

async function fetchStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();

        // Обновляем состояние UI
        if (data.running !== isRunning) {
            isRunning = data.running;
            updateRunState(isRunning);
        }

        // Sync Timer with Server
        if (data.start_time) {
            startTime = new Date(data.start_time);
        } else if (isRunning && !startTime) {
            startTime = new Date();
        } else if (!isRunning) {
            startTime = null;
        }

        // Обновляем конфиг
        if (JSON.stringify(data.config) !== JSON.stringify(currentConfig)) {
            // Обновляем поля только если не в фокусе пользователя, чтобы не сбивать ввод
            // Для упрощения, обновляем при первой загрузке или если данные пустые
            if (Object.keys(currentConfig).length === 0) {
                fillForm(data.config);
            }
            currentConfig = data.config;
        }

        // Update UI Status (Sentiment, PID, etc)
        updateStatus(data);

        updateConnectionStatus(true);

    } catch (e) {
        console.error('Status fetch error', e);
        updateConnectionStatus(false);
    }
}

async function fetchLogs() {
    try {
        const response = await fetch('/api/logs');
        const data = await response.json();

        const consoleEl = document.getElementById('logConsole');
        const wasScrolledBottom = consoleEl.scrollHeight - consoleEl.scrollTop === consoleEl.clientHeight;

        consoleEl.innerHTML = data.logs.map(line => `<div class="log-line">${line}</div>`).join('');

        if (wasScrolledBottom) {
            consoleEl.scrollTop = consoleEl.scrollHeight;
        }
    } catch (e) {
        console.error('Logs fetch error', e);
    }
}

async function fetchHistory() {
    try {
        const response = await fetch('/api/history');
        const data = await response.json();

        if (data.trades) {
            historyData = data.trades;
            renderHistory();
        }
    } catch (e) {
        console.error("Fetch History Error:", e);
    }
}

function sortHistory(key) {
    if (sortConfig.key === key) {
        sortConfig.direction = sortConfig.direction === 'asc' ? 'desc' : 'asc';
    } else {
        sortConfig.key = key;
        sortConfig.direction = 'desc';
    }
    renderHistory();
    updateSortIcons();
}

function updateSortIcons() {
    const headers = document.querySelectorAll('#historyTable th');
    headers.forEach(th => {
        const icon = th.querySelector('i');
        if (icon) {
            icon.className = 'fa-solid fa-sort'; // Reset
            if (th.getAttribute('onclick') && th.getAttribute('onclick').includes(sortConfig.key)) {
                icon.className = sortConfig.direction === 'asc' ? 'fa-solid fa-sort-up' : 'fa-solid fa-sort-down';
            }
        }
    });
}

function renderHistory() {
    const tbody = document.querySelector('#historyTable tbody');
    if (!historyData || historyData.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding: 2rem; color: #64748b;">Истории пока нет</td></tr>';
        return;
    }

    const sorted = [...historyData].sort((a, b) => {
        let valA = a[sortConfig.key];
        let valB = b[sortConfig.key];

        // Handle specific fields
        if (sortConfig.key === 'pnl') {
            valA = parseFloat(a.pnl) || 0;
            valB = parseFloat(b.pnl) || 0;
        } else if (sortConfig.key === 'price') {
            valA = parseFloat(a.entry_price) || 0;
            valB = parseFloat(b.entry_price) || 0;
        } else if (sortConfig.key === 'qty') {
            valA = parseFloat(a.qty) || 0;
            valB = parseFloat(b.qty) || 0;
        } else if (sortConfig.key === 'timestamp') {
            valA = new Date(a.timestamp).getTime();
            valB = new Date(b.timestamp).getTime();
        }

        if (valA < valB) return sortConfig.direction === 'asc' ? -1 : 1;
        if (valA > valB) return sortConfig.direction === 'asc' ? 1 : -1;
        return 0;
    });

    tbody.innerHTML = sorted.map(t => {
        const date = new Date(t.timestamp).toLocaleString('ru-RU', {
            day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'
        });
        const sideBadge = t.side.toUpperCase() === 'BUY' ? 'badge-buy' : 'badge-sell';
        let statusBadge = 'badge-open';
        if (t.status === 'WIN') statusBadge = 'badge-win';
        else if (t.status === 'LOSS') statusBadge = 'badge-loss';

        return `
            <tr>
                <td style="color: #94a3b8; font-size: 0.85rem;">${date}</td>
                <td><b style="color: #f8fafc;">${t.symbol}</b></td>
                <td><span class="badge ${sideBadge}">${t.side}</span></td>
                <td>
                    ${t.confluence_score ? `<span style="color:${t.confluence_score >= 80 ? '#22c55e' : (t.confluence_score >= 50 ? '#facc15' : '#94a3b8')}; font-weight:bold;">${t.confluence_score}%</span>` : '<span style="color:#64748b;">-</span>'}
                </td>
                <td>
                    <div style="display:flex; flex-direction:column; font-size:0.9em;">
                        <span>Op: $${t.entry_price ? t.entry_price.toFixed(t.entry_price < 1 ? 4 : 2) : '0.00'}</span>
                        ${t.exit_price ? `<span style="color:#64748b; font-size:0.8em;">Cl: $${t.exit_price.toFixed(t.exit_price < 1 ? 4 : 2)}</span>` : ''}
                    </div>
                </td>
                <td>${t.qty}</td>
                <td>
                    <span style="font-weight:bold; color: ${t.pnl > 0 ? '#22c55e' : (t.pnl < 0 ? '#ef4444' : '#94a3b8')}">
                        ${t.pnl > 0 ? '+' : ''}${t.pnl ? '$' + t.pnl.toFixed(2) : '-'}
                    </span>
                    ${t.pnl_percent ? `<div style="font-size:0.75em; color:${t.pnl_percent > 0 ? '#22c55e' : '#ef4444'}">${t.pnl_percent > 0 ? '+' : ''}${t.pnl_percent.toFixed(2)}%</div>` : ''}
                </td>
                <td><span class="badge ${statusBadge}">${t.status}</span></td>
            </tr>
        `;
    }).join('');

    updateSortIcons();
}

async function syncHistory() {
    try {
        const btn = document.querySelector('button[onclick="syncHistory()"]');
        const originalText = btn.innerHTML;
        if (btn) {
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> ...';
            btn.disabled = true;
        }

        const res = await fetch('/api/history/sync', { method: 'POST' });
        const data = await res.json();

        if (data.status === 'ok') {
            await fetchHistory();
            if (btn) {
                btn.innerHTML = `<i class="fa-solid fa-check"></i> +${data.synced}`;
                setTimeout(() => {
                    btn.innerHTML = originalText;
                    btn.disabled = false;
                }, 3000);
            }
        } else {
            alert('Синхронизация не удалась: ' + data.message);
            if (btn) {
                btn.innerHTML = originalText;
                btn.disabled = false;
            }
        }
    } catch (e) {
        console.error(e);
        alert('Ошибка соединения при синхронизации');
        const btn = document.querySelector('button[onclick="syncHistory()"]');
        if (btn) btn.disabled = false;
    }
}

async function fetchAnalytics() {
    try {
        const response = await fetch('/api/analytics');
        const data = await response.json();

        const m = data.metrics;
        if (!m) return;

        // Safely set text content (elements may be removed)
        const setMetric = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.textContent = val;
        };

        setMetric('metricSharpe', m.sharpe_ratio);
        setMetric('metricPF', m.profit_factor);
        setMetric('metricDD', m.max_drawdown + '%');
        setMetric('metricWR', m.win_rate + '%');

        // Advanced Section
        setMetric('statProfitFactor', m.profit_factor);
        setMetric('statExpectancy', (m.expectancy >= 0 ? '+' : '') + '$' + m.expectancy);
        setMetric('statAvgWin', '$' + m.avg_win);
        setMetric('statAvgLoss', '$' + m.avg_loss);

        // Optional: Color DD red if high
        const ddEl = document.getElementById('metricDD');
        if (ddEl) ddEl.style.color = (m.max_drawdown < -15) ? '#ef4444' : '#f59e0b';

        const expEl = document.getElementById('statExpectancy');
        if (expEl) expEl.style.color = m.expectancy >= 0 ? '#22c55e' : '#ef4444';

        // Equity Curve Visualization (if container exists)
        if (document.getElementById('equityChart')) {
            renderEquityLine(data.equity_curve);
        }
    } catch (e) {
        console.log("Analytics not available");
    }
}

function renderEquityLine(points) {
    const container = document.getElementById('equityChart');
    if (!container || !points || points.length < 2) return;

    // Clear previous
    container.innerHTML = '<canvas id="equityCanvas" style="width:100%; height:100%;"></canvas>';
    const canvas = document.getElementById('equityCanvas');
    const ctx = canvas.getContext('2d');

    // Setup dimensions
    canvas.width = container.clientWidth * window.devicePixelRatio;
    canvas.height = container.clientHeight * window.devicePixelRatio;

    const margin = 20;
    const w = canvas.width - margin * 2;
    const h = canvas.height - margin * 2;

    const balances = points.map(p => p.balance);
    const min = Math.min(...balances) * 0.99;
    const max = Math.max(...balances) * 1.01;
    const range = max - min;

    ctx.strokeStyle = '#6366f1';
    ctx.lineWidth = 3 * window.devicePixelRatio;
    ctx.lineJoin = 'round';
    ctx.beginPath();

    points.forEach((p, i) => {
        const x = margin + (i / (points.length - 1)) * w;
        const y = canvas.height - (margin + ((p.balance - min) / range) * h);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });

    ctx.stroke();

    // Gradient fill
    const grad = ctx.createLinearGradient(0, 0, 0, canvas.height);
    grad.addColorStop(0, 'rgba(99, 102, 241, 0.2)');
    grad.addColorStop(1, 'rgba(99, 102, 241, 0)');
    ctx.fillStyle = grad;
    ctx.lineTo(margin + w, canvas.height);
    ctx.lineTo(margin, canvas.height);
    ctx.closePath();
    ctx.fill();
}

function exportTrades() {
    window.location.href = '/api/export/trades';
}

async function startBot() {
    await saveConfig(false); // Сначала сохраняем настройки

    try {
        const response = await fetch('/api/start', { method: 'POST' });
        const data = await response.json();

        if (data.status === 'ok') {
            isRunning = true;
            updateRunState(true);
            showToast('Bot Started Successfully', 'success');
            startTime = new Date();
        } else {
            showToast('Error: ' + data.message, 'error');
        }
    } catch (e) {
        showToast('Connection Error', 'error');
    }
}

async function stopBot() {
    try {
        const response = await fetch('/api/stop', { method: 'POST' });
        const data = await response.json();

        if (data.status === 'ok') {
            isRunning = false;
            updateRunState(false);
            showToast('Bot Stopped', 'warning');
            startTime = null;
        }
    } catch (e) {
        showToast('Connection Error', 'error');
    }
}

async function saveConfig(showNotification = true) {
    // Helper to safely get value
    const getVal = (id, def = '') => {
        const el = document.getElementById(id);
        return el ? el.value : def;
    };
    const getChecked = (id, def = false) => {
        const el = document.getElementById(id);
        return el ? el.checked : def;
    };

    // Merge with current config to preserve hidden fields like max_symbols
    // CRITICAL: Preserve API keys from server config, NOT from form (prevents accidental overwrites)
    const config = {
        ...currentConfig,
        // api_key and api_secret are managed via .env - don't overwrite from form!
        api_key: currentConfig.api_key || '',
        api_secret: currentConfig.api_secret || '',
        mode: getVal('modeSelect', 'demo'),
        risk_percent: parseFloat(getVal('riskPercent', '4')) || 4,
        max_daily_loss: parseFloat(getVal('maxDailyLoss', '20')) || 20,
        stop_loss_atr: parseFloat(getVal('stopLossAtr', '2')) || 2,
        take_profit_ratio: parseFloat(getVal('takeProfitRatio', '4')) || 4,
        auto_trade: getChecked('autoTradeCheck'),
        // symbols: [], // Removed symbols section, using AI Selector
        telegram_token: getVal('telegramToken'),
        telegram_channel: getVal('telegramChannel'),
        strategy: getVal('strategySelect', 'mean_reversion'),
        min_probability: parseInt(getVal('minProbability', '85')) || 85
    };

    try {
        const response = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        if (showNotification) showToast('Settings Saved', 'success');
    } catch (e) {
        if (showNotification) showToast('Save Failed', 'error');
    }
}

// === UI HELPERS ===

function updateRunState(running) {
    const btnStart = document.getElementById('btnStart');
    const btnStop = document.getElementById('btnStop');
    const statusText = document.getElementById('statusText');
    const indicator = document.querySelector('.status-indicator');

    if (running) {
        btnStart.classList.add('hidden');
        btnStop.classList.remove('hidden');
        statusText.textContent = 'SYSTEM ACTIVE';
        statusText.style.color = '#10b981';
        indicator.classList.add('connected');
    } else {
        btnStart.classList.remove('hidden');
        btnStop.classList.add('hidden');
        statusText.textContent = 'SYSTEM STOPPED';
        statusText.style.color = '#ef4444';
        indicator.classList.remove('connected');
    }
}

function updateConnectionStatus(connected) {
    const statusText = document.getElementById('statusText');
    if (!connected) {
        statusText.textContent = 'DISCONNECTED';
        statusText.style.color = '#94a3b8';
    } else if (!isRunning) {
        statusText.textContent = 'READY';
        statusText.style.color = '#94a3b8';
    }
}

function fillForm(config) {
    if (!config) return;

    // Helper to safely set value
    const setVal = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.value = val || '';
    };
    const setChecked = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.checked = !!val;
    };

    setVal('apiKey', config.api_key);
    setVal('apiSecret', config.api_secret);
    setVal('modeSelect', config.mode || 'demo');
    setVal('riskPercent', config.risk_percent || 4);
    setVal('maxDailyLoss', config.max_daily_loss || 20);
    setVal('stopLossAtr', config.stop_loss_atr || 2);
    setVal('takeProfitRatio', config.take_profit_ratio || 4);
    setChecked('autoTradeCheck', config.auto_trade);
    setVal('telegramToken', config.telegram_token);
    setVal('telegramChannel', config.telegram_channel);
    setVal('strategySelect', config.strategy || 'mean_reversion');
    setVal('minProbability', config.min_probability || 85);
}

function updateRangeVal(input, targetId) {
    document.getElementById(targetId).textContent = input.value + '%';
}

// Symbols Management
function renderSymbols(symbols) {
    const container = document.getElementById('symbolsList');
    container.innerHTML = '';

    symbols.forEach(sym => {
        const chip = document.createElement('div');
        chip.className = 'chip';
        chip.innerHTML = `${sym} <i class="fa-solid fa-xmark" onclick="removeSymbol('${sym}')"></i>`;
        container.appendChild(chip);
    });

    document.getElementById('activePairsCount').textContent = symbols.length;
}

function getSymbolsFromChips() {
    const chips = document.querySelectorAll('#symbolsList .chip');
    return Array.from(chips).map(c => c.textContent.trim());
}

function addSymbol() {
    const input = document.getElementById('newSymbol');
    let sym = input.value.toUpperCase().trim();
    if (!sym) return;

    const current = getSymbolsFromChips();
    if (!current.includes(sym)) {
        current.push(sym);
        renderSymbols(current);
        saveConfig(false);
    }
    input.value = '';
}

function removeSymbol(sym) {
    const current = getSymbolsFromChips();
    const filtered = current.filter(s => s !== sym);
    renderSymbols(filtered);
    saveConfig(false);
}

function updateTimer() {
    if (!isRunning || !startTime) {
        document.getElementById('runningTime').textContent = '00:00:00';
        return;
    }

    const now = new Date();
    const diff = now - startTime;

    const hh = Math.floor(diff / 3600000).toString().padStart(2, '0');
    const mm = Math.floor((diff % 3600000) / 60000).toString().padStart(2, '0');
    const ss = Math.floor((diff % 60000) / 1000).toString().padStart(2, '0');

    document.getElementById('runningTime').textContent = `${hh}:${mm}:${ss}`;
}

// === SCANNER ===

async function runScanner() {
    const btn = document.getElementById('btnScan');
    const status = document.getElementById('scannerStatus');
    const container = document.getElementById('scannerResults');
    const tbody = document.querySelector('#scannerTable tbody');

    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Scanning...';
    status.textContent = 'Сканирование топ-30 пар... (это займет 10-20 сек)';
    status.style.display = 'block';
    container.style.display = 'none';

    try {
        const response = await fetch('/api/scan');
        const data = await response.json();

        if (data.status === 'ok') {
            tbody.innerHTML = '';

            if (data.results.length === 0) {
                status.textContent = 'Сигналов не найдено (проверьте настройки)';
            } else {
                status.style.display = 'none';
                container.style.display = 'block';

                data.results.forEach(r => {
                    const row = document.createElement('tr');
                    const color = r.type === 'LONG' ? '#10b981' : '#ef4444';
                    row.innerHTML = `
                        <td><b>${r.symbol}</b></td>
                        <td style="color:${color}">${r.type}</td>
                        <td>${r.strength}</td>
                        <td>${r.score}/100</td>
                        <td>
                            <button class="btn btn-secondary" style="padding: 4px 8px; font-size: 0.8rem;" onclick="addFoundPair('${r.symbol}')">
                                <i class="fa-solid fa-plus"></i>
                            </button>
                        </td>
                    `;
                    tbody.appendChild(row);
                });
            }
        } else {
            status.textContent = 'Ошибка: ' + data.message;
        }
    } catch (e) {
        status.textContent = 'Ошибка соединения';
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-satellite-dish"></i> SCAN';
    }
}

// This function seems to be intended for a different context, likely an `updateStatus` function
// that was not provided in the original document. I'm placing it here as a new function
// based on the instruction's content, assuming it's meant to be a separate utility.
function updateStatus(data) {
    const statusDot = document.getElementById('statusDot');
    const statusText = document.getElementById('statusText');

    if (data.status === 'running') {
        if (statusDot) statusDot.className = 'dot dot-green';
        if (statusText) statusText.textContent = 'Активен (PID: ' + data.pid + ')';

        // Update Stats
        const regimeEl = document.getElementById('marketRegime');
        if (regimeEl && data.regime) regimeEl.textContent = data.regime;

        // Update Sentiment
        const sentBox = document.getElementById('sentimentBox');
        const sentReason = document.getElementById('sentimentReason');
        if (sentBox && data.sentiment_regime) {
            let color = '#888';
            let icon = 'fa-circle-question';
            if (data.sentiment_regime === 'RISK_ON') { color = '#22c55e'; icon = 'fa-arrow-trend-up'; }
            if (data.sentiment_regime === 'RISK_OFF') { color = '#ef4444'; icon = 'fa-shield-halved'; }
            if (data.sentiment_regime === 'NEUTRAL') { color = '#eab308'; icon = 'fa-scale-balanced'; }

            sentBox.innerHTML = `<span style="color: ${color}; font-weight: bold; font-size: 1.1em;">
                                    <i class="fa-solid ${icon}"></i> ${data.sentiment_regime}
                                 </span>`;
            if (sentReason) sentReason.textContent = data.sentiment_reason;
        }

        // Update Top Coins
        const updateList = (id, list) => {
            const el = document.getElementById(id);
            if (el && list) {
                if (list.length === 0) el.innerHTML = '<li style="color: #64748b;">Ничего не найдено</li>';
                else el.innerHTML = list.map(s => `<li style="cursor:pointer; padding: 2px 5px; border-radius: 4px;" class="coin-item" onclick="selectChartSymbol('${s}')"><b>${s}</b></li>`).join('');
            }
        };
        updateList('topLongsList', data.top_longs);
        updateList('topShortsList', data.top_shorts);

        // Update Guardian Services
        const hedgeEl = document.getElementById('hedgeStatus');
        if (hedgeEl && data.hedge_status) {
            hedgeEl.textContent = data.hedge_status.toUpperCase();
            if (data.hedge_status.includes('Active')) {
                hedgeEl.style.background = 'rgba(251, 191, 36, 0.2)';
                hedgeEl.style.color = '#fbbf24';
            } else {
                hedgeEl.style.background = 'rgba(100, 116, 139, 0.2)';
                hedgeEl.style.color = '#94a3b8';
            }
        }

        const newsEl = document.getElementById('newsShieldStatus');
        if (newsEl && data.news_danger) {
            if (data.news_danger !== "None") {
                newsEl.textContent = "DANGER: " + data.news_danger;
                newsEl.style.background = 'rgba(239, 68, 68, 0.2)';
                newsEl.style.color = '#ef4444';
            } else {
                newsEl.textContent = "ACTIVE (SAFE)";
                newsEl.style.background = 'rgba(34, 197, 94, 0.2)';
                newsEl.style.color = '#4ade80';
            }
        }

    } else {
        if (statusDot) statusDot.className = 'dot dot-red';
        if (statusText) statusText.textContent = 'Остановлен';
    }
}


function addFoundPair(symbol) {
    const input = document.getElementById('newSymbol');
    input.value = symbol;
    addSymbol();
    showToast(`${symbol} добавлен в наблюдение`, 'success');
}

function showToast(msg, type = 'info') {
    // User requested to hide popups -> Only console log
    console.log(`[${type.toUpperCase()}] ${msg}`);
}

// === LLM PROVIDER MANAGEMENT ===

async function fetchLLMStatus() {
    try {
        const response = await fetch('/api/llm/status');
        const data = await response.json();

        const nameEl = document.getElementById('llmProviderName');
        const modelEl = document.getElementById('llmProviderModel');
        const selectEl = document.getElementById('llmProviderSelect');
        const warningEl = document.getElementById('llmExhaustedWarning');
        const exhaustedEl = document.getElementById('exhaustedList');

        if (nameEl) {
            nameEl.textContent = data.current_provider || 'Unknown';
            // Color based on provider
            if (data.current_provider === 'NONE') {
                nameEl.style.color = '#ef4444';
            } else if (data.current_provider.includes('GROQ')) {
                nameEl.style.color = '#22c55e';
            } else if (data.current_provider === 'OpenRouter') {
                nameEl.style.color = '#f59e0b'; // Yellow for paid
            }
        }

        if (modelEl) {
            modelEl.textContent = data.current_model ? `(${data.current_model})` : '';
        }

        // Update dropdown selection
        if (selectEl && data.current_provider) {
            for (let opt of selectEl.options) {
                if (opt.value === data.current_provider || data.current_provider.includes(opt.value)) {
                    selectEl.value = opt.value;
                    break;
                }
            }
        }

        // Show warning if any providers exhausted
        if (warningEl && exhaustedEl) {
            if (data.exhausted && data.exhausted.length > 0) {
                warningEl.style.display = 'flex';
                exhaustedEl.textContent = 'Exhausted: ' + data.exhausted.join(', ');
            } else {
                warningEl.style.display = 'none';
            }
        }

    } catch (e) {
        console.error('LLM Status fetch error:', e);
    }
}

async function switchLLMProvider() {
    const selectEl = document.getElementById('llmProviderSelect');
    if (!selectEl) return;

    const provider = selectEl.value;

    try {
        const response = await fetch(`/api/llm/switch?provider=${encodeURIComponent(provider)}`, {
            method: 'POST'
        });
        const data = await response.json();

        if (data.status === 'ok') {
            showToast(`Switched to ${provider}`, 'success');
            fetchLLMStatus(); // Refresh display
        } else {
            showToast('Switch failed: ' + data.message, 'error');
        }
    } catch (e) {
        showToast('Connection error', 'error');
    }
}

async function resetLLMProviders() {
    try {
        const response = await fetch('/api/llm/reset', { method: 'POST' });
        const data = await response.json();

        if (data.status === 'ok') {
            showToast('All LLM providers reset', 'success');
            fetchLLMStatus(); // Refresh display
        } else {
            showToast('Reset failed: ' + data.message, 'error');
        }
    } catch (e) {
        showToast('Connection error', 'error');
    }
}

// === HELP MODAL ===

function openHelp() {
    document.getElementById('helpModal').classList.add('active');
}

function closeHelp() {
    document.getElementById('helpModal').classList.remove('active');
}

// Close modal on outside click
document.addEventListener('click', (e) => {
    const modal = document.getElementById('helpModal');
    if (e.target === modal) {
        closeHelp();
    }
});

// === CHAT ===

// Panic Mode Removed

// === CHARTING ===

function initChart() {
    const chartContainer = document.getElementById('tradingviewChart');
    if (!chartContainer) return;

    chart = LightweightCharts.createChart(chartContainer, {
        layout: {
            background: { color: '#0f172a' },
            textColor: '#94a3b8',
        },
        grid: {
            vertLines: { color: 'rgba(30, 41, 59, 0.5)' },
            horzLines: { color: 'rgba(30, 41, 59, 0.5)' },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
        },
        rightPriceScale: {
            borderColor: 'rgba(30, 41, 59, 1)',
        },
        timeScale: {
            borderColor: 'rgba(30, 41, 59, 1)',
            timeVisible: true,
        },
    });

    candleSeries = chart.addCandlestickSeries({
        upColor: '#10b981',
        downColor: '#ef4444',
        borderVisible: false,
        wickUpColor: '#10b981',
        wickDownColor: '#ef4444',
    });

    // Handle resizing
    window.addEventListener('resize', () => {
        chart.resize(chartContainer.clientWidth, chartContainer.clientHeight);
    });

    // Initial Load
    setTimeout(() => {
        updateChartSymbols();
        loadChartData();
    }, 1000);
}

async function updateChartSymbols() {
    const select = document.getElementById('chartSymbol');
    if (!select) return;

    try {
        const response = await fetch('/api/active_symbols');
        const symbols = await response.json();

        if (symbols && symbols.length > 0) {
            const currentVal = select.value;
            select.innerHTML = symbols.map(s => `<option value="${s}" ${s === currentVal ? 'selected' : ''}>${s}</option>`).join('');
        }
    } catch (e) {
        console.error('Symbols fetch error', e);
    }
}

async function loadChartData() {
    if (!candleSeries) return;

    const select = document.getElementById('chartSymbol');
    const symbol = select ? select.value : 'BTCUSDT';

    try {
        const response = await fetch(`/api/klines?symbol=${symbol}&interval=15`);
        const data = await response.json();

        if (data && data.length > 0) {
            candleSeries.setData(data);
            // Fetch analysis for this symbol to draw lines (Step 3)
            fetchSymbolAnalysis(symbol);
        }
    } catch (e) {
        console.error('Klines fetch error', e);
    }
}

// Visual Sniper: Drawing Price Lines (Step 3)
let activePriceLines = [];

function clearPriceLines() {
    if (!candleSeries) return;
    activePriceLines.forEach(line => candleSeries.removePriceLine(line));
    activePriceLines = [];
}

function drawPriceLine(price, color, title, style = 2) {
    if (!candleSeries || !price) return;

    const line = candleSeries.createPriceLine({
        price: price,
        color: color,
        lineWidth: 2,
        lineStyle: style, // 2 = dashed
        axisLabelVisible: true,
        title: title,
    });
    activePriceLines.push(line);
}

async function fetchSymbolAnalysis(symbol) {
    try {
        // We'll create this endpoint in server.py
        const res = await fetch(`/api/analysis/latest?symbol=${symbol}`);
        const data = await res.json();

        clearPriceLines();

        const badge = document.getElementById('activeStrategyBadge');
        const nameSpan = document.getElementById('activeStrategyName');

        if (data && data.entry_price) {
            drawPriceLine(data.entry_price, '#6366f1', 'ENTRY', 0); // Solid
            drawPriceLine(data.take_profit, '#22c55e', 'TP', 2);    // Dashed
            drawPriceLine(data.stop_loss, '#ef4444', 'SL', 2);      // Dashed

            // Update Strategy Indicator
            if (badge && nameSpan && data.strategy_name) {
                nameSpan.textContent = data.strategy_name;
                badge.style.display = 'flex';
                badge.style.alignItems = 'center';
                badge.style.gap = '5px';
            }

            console.log(`🎯 Chart: Drew sniper lines and strategy info for ${symbol}`);
        } else {
            if (badge) badge.style.display = 'none';
        }
    } catch (e) {
        // Analysis might not exist for this symbol yet
    }
}
// Helper to switch chart from other UI parts
async function selectChartSymbol(symbol) {
    const select = document.getElementById('chartSymbol');
    if (select) {
        // Ensure symbol is in the dropdown or add it
        let exists = false;
        for (let i = 0; i < select.options.length; i++) {
            if (select.options[i].value === symbol) {
                exists = true;
                break;
            }
        }
        if (!exists) {
            const opt = document.createElement('option');
            opt.value = symbol;
            opt.textContent = symbol;
            select.appendChild(opt);
        }
        select.value = symbol;
        loadChartData(); // This will also trigger fetchSymbolAnalysis
    }
}
