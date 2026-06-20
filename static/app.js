/* ═══════════════════════════════════════════════════════════════════
   HALAL SCAN AI PRO ULTIMATE — app.js
   All frontend logic: tabs, API calls, table rendering, watchlist
   ═══════════════════════════════════════════════════════════════════ */

'use strict';

// ── State ──────────────────────────────────────────────────────────────────
let _allSignals = [];   // full signal list from last fetch

// ── Initialisation ─────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  checkStatus();
  loadSignals();
  loadHistory();
  loadWatchlist();
  setInterval(checkStatus, 30_000);   // poll status every 30s
});

// ── Tab Switching ──────────────────────────────────────────────────────────
function showTab(name) {
  document.querySelectorAll('.tab').forEach(t => {
    t.classList.remove('active');
    t.classList.add('hidden');
  });
  document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));

  const tab = document.getElementById(`tab-${name}`);
  if (tab) { tab.classList.remove('hidden'); tab.classList.add('active'); }

  const link = document.querySelector(`.nav-link[href="#${name}"]`);
  if (link) link.classList.add('active');
}

// ── Status Check ───────────────────────────────────────────────────────────
async function checkStatus() {
  const dot  = document.getElementById('status-dot');
  const text = document.getElementById('status-text');
  try {
    const res  = await fetch('/api/status');
    const data = await res.json();
    if (data.status === 'ok') {
      dot.className  = 'status-dot ' + (data.model_ready ? 'online' : 'offline');
      text.textContent = data.model_ready ? 'Model Ready' : 'No Model (run train_model.py)';
    }
  } catch {
    dot.className    = 'status-dot error';
    text.textContent = 'Server Offline';
  }
}

// ── Probability → colour ───────────────────────────────────────────────────
function probColor(p) {
  if (p >= 85) return '#f97316';   // orange — strong buy
  if (p >= 70) return '#22c55e';   // green  — buy
  if (p >= 50) return '#eab308';   // yellow — watch
  return '#ef4444';                 // red    — avoid
}

function verdictClass(verdict) {
  return 'verdict verdict-' + (verdict || 'AVOID').replace(/\s+/g, '-');
}

// ── Probability Bar HTML ────────────────────────────────────────────────────
function probBarHTML(prob) {
  const color = probColor(prob);
  return `
    <div class="prob-bar-wrap">
      <div class="prob-bar-bg">
        <div class="prob-bar-fill" style="width:${prob}%;background:${color}"></div>
      </div>
      <span class="prob-value" style="color:${color}">${prob.toFixed(1)}%</span>
    </div>`;
}

// ── Return cell HTML ────────────────────────────────────────────────────────
function retHTML(val) {
  if (val == null || isNaN(val)) return '<span class="text-muted">—</span>';
  const cls = val >= 0 ? 'positive' : 'negative';
  return `<span class="${cls}">${val >= 0 ? '+' : ''}${val.toFixed(2)}%</span>`;
}

// ── RSI colour ─────────────────────────────────────────────────────────────
function rsiColor(rsi) {
  if (rsi >= 70) return '#ef4444';
  if (rsi <= 30) return '#22c55e';
  return '#e2e8f0';
}

// ═══════════════════════════════════════════════════════════════════
//  TOP SIGNALS TAB
// ═══════════════════════════════════════════════════════════════════

async function loadSignals(minProb = 60) {
  try {
    const res  = await fetch(`/api/signals?min_prob=${minProb}&limit=100`);
    const data = await res.json();
    _allSignals = data.signals || [];
    renderSignalsTable(_allSignals);
    updateStatsBar(_allSignals);

    const count = document.getElementById('signals-count');
    const ts    = document.getElementById('signals-time');
    if (count) count.textContent = `${_allSignals.length} signals`;
    if (ts)    ts.textContent    = data.timestamp ? fmtTime(data.timestamp) : 'Cached';
  } catch (e) {
    console.error('loadSignals error:', e);
    showToast('Failed to load signals — is the server running?', 'error');
  }
}

function renderSignalsTable(signals) {
  const tbody = document.getElementById('signals-body');
  if (!tbody) return;

  if (!signals || signals.length === 0) {
    tbody.innerHTML = '<tr><td colspan="10" class="empty-row">No signals found. Run a scan first.</td></tr>';
    return;
  }

  tbody.innerHTML = signals.map((s, i) => `
    <tr>
      <td><span style="color:var(--text-muted)">${i + 1}</span></td>
      <td><strong>${s.symbol}</strong></td>
      <td>${probBarHTML(s.probability)}</td>
      <td><span class="${verdictClass(s.verdict)}">${s.verdict}</span></td>
      <td style="font-family:var(--mono);font-size:.8rem">${fmtPrice(s.price)}</td>
      <td style="color:${rsiColor(s.rsi)}">${fmtNum(s.rsi)}</td>
      <td>${fmtNum(s.adx)}</td>
      <td>${fmtNum(s.volume_ratio, 2)}</td>
      <td>${retHTML(s.return_24h)}</td>
      <td>
        <button class="btn btn-sm" onclick="addToWatchlistQuick('${s.symbol}')">★</button>
        <button class="btn btn-sm" onclick="quickAnalyzeNav('${s.symbol}')">→</button>
      </td>
    </tr>`).join('');
}

function updateStatsBar(signals) {
  const total  = signals.length;
  const strong = signals.filter(s => s.verdict === 'STRONG BUY').length;
  const buy    = signals.filter(s => s.verdict === 'BUY').length;
  const avgP   = total > 0 ? signals.reduce((a, s) => a + s.probability, 0) / total : 0;

  setText('stat-total',    total);
  setText('stat-strong',   strong);
  setText('stat-buy',      buy);
  setText('stat-avg-prob', avgP.toFixed(1) + '%');
}

// ═══════════════════════════════════════════════════════════════════
//  FULL SCAN (triggers backend scan)
// ═══════════════════════════════════════════════════════════════════

async function runFullScan() {
  const modal = document.getElementById('scan-modal');
  modal.classList.remove('hidden');

  try {
    const res  = await fetch('/api/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ min_prob: 60, top_n: 50 }),
    });
    const data = await res.json();

    if (data.success) {
      _allSignals = data.signals || [];
      renderSignalsTable(_allSignals);
      updateStatsBar(_allSignals);
      showToast(`✅ Scan complete — ${data.count} signals found`);
    } else {
      showToast('Scan failed: ' + (data.error || 'Unknown error'), 'error');
    }
  } catch (e) {
    showToast('Scan request failed — check server logs', 'error');
  } finally {
    modal.classList.add('hidden');
  }
}

// ═══════════════════════════════════════════════════════════════════
//  COIN ANALYZER TAB
// ═══════════════════════════════════════════════════════════════════

async function analyzeCoin() {
  const input   = document.getElementById('coin-input');
  const loading = document.getElementById('analyzer-loading');
  const result  = document.getElementById('analyzer-result');
  const errBox  = document.getElementById('analyzer-error');

  const coin = (input?.value || '').trim().toUpperCase();
  if (!coin) { showToast('Enter a coin symbol first'); return; }

  loading.classList.remove('hidden');
  result.classList.add('hidden');
  errBox.classList.add('hidden');

  try {
    const res  = await fetch(`/api/analyze/${coin}`);
    const data = await res.json();

    if (res.ok && !data.error) {
      renderAnalyzerResult(data);
      result.classList.remove('hidden');
    } else {
      errBox.textContent = data.error || `Could not analyse ${coin}`;
      errBox.classList.remove('hidden');
    }
  } catch (e) {
    errBox.textContent = 'Request failed — is the server running?';
    errBox.classList.remove('hidden');
  } finally {
    loading.classList.add('hidden');
  }
}

function quickAnalyze(coin) {
  const input = document.getElementById('coin-input');
  if (input) input.value = coin;
  showTab('analyzer');
  analyzeCoin();
}

function quickAnalyzeNav(coin) {
  showTab('analyzer');
  const input = document.getElementById('coin-input');
  if (input) input.value = coin;
  analyzeCoin();
}

function renderAnalyzerResult(d) {
  const container = document.getElementById('analyzer-result');
  const prob      = d.probability || 0;
  const color     = probColor(prob);
  const pct       = Math.min(prob, 100);

  // Build conic-gradient for ring
  const deg = Math.round(pct * 3.6);
  const ringStyle = `background: conic-gradient(${color} ${deg}deg, rgba(255,255,255,.07) ${deg}deg)`;

  // Signal strength pips
  const strength = d.signal_strength || 1;
  const pips = [1,2,3,4].map(n =>
    `<div class="strength-pip ${n <= strength ? 'active' : ''}"></div>`
  ).join('');

  container.innerHTML = `
    <div class="analyzer-top">
      <div class="analyzer-prob-ring" style="${ringStyle}">
        <span class="analyzer-prob-val" style="color:${color}">${prob.toFixed(1)}%</span>
        <span class="analyzer-prob-lbl">AI Score</span>
      </div>
      <div>
        <div class="analyzer-symbol">${d.symbol} <span style="color:var(--text-muted);font-size:1rem">/ USDT</span></div>
        <div class="analyzer-price">Price: ${fmtPrice(d.price)} USDT</div>
        <div style="margin-top:.6rem">
          <span class="${verdictClass(d.verdict)}" style="font-size:.85rem">${d.verdict}</span>
        </div>
        <div class="strength-bar" style="margin-top:.6rem">${pips}</div>
        <div style="font-size:.7rem;color:var(--text-muted);margin-top:.3rem">Signal Strength</div>
      </div>
      <div style="margin-left:auto">
        <button class="btn btn-ghost" onclick="addToWatchlistQuick('${d.symbol}')">★ Watchlist</button>
      </div>
    </div>

    <div class="analyzer-grid">
      ${metric('RSI (14)',       fmtNum(d.rsi),            rsiColor(d.rsi))}
      ${metric('ADX',           fmtNum(d.adx))}
      ${metric('Volume Ratio',  fmtNum(d.volume_ratio, 2))}
      ${metric('MACD',          fmtNum(d.macd, 6))}
      ${metric('MACD Signal',   fmtNum(d.macd_signal, 6))}
      ${metric('EMA 20',        fmtPrice(d.ema20))}
      ${metric('EMA 50',        fmtPrice(d.ema50))}
      ${metric('Return 24h',    retDisplay(d.return_24h))}
      ${metric('Return 72h',    retDisplay(d.return_72h))}
      ${metric('Scanned',       fmtTime(d.scanned_at))}
    </div>
  `;
}

function metric(label, value, color) {
  return `
    <div class="analyzer-metric">
      <div class="analyzer-metric-lbl">${label}</div>
      <div class="analyzer-metric-val" ${color ? `style="color:${color}"` : ''}>${value}</div>
    </div>`;
}

function retDisplay(val) {
  if (val == null || isNaN(val)) return '—';
  const sign = val >= 0 ? '+' : '';
  return `<span style="color:${val >= 0 ? '#22c55e' : '#ef4444'}">${sign}${val.toFixed(2)}%</span>`;
}

// ═══════════════════════════════════════════════════════════════════
//  PROBABILITY SCANNER TAB
// ═══════════════════════════════════════════════════════════════════

function updateProbLabel(val) {
  const lbl = document.getElementById('prob-label');
  if (lbl) lbl.textContent = val + '%';
}

function filterSignals() {
  const slider = document.getElementById('prob-slider');
  const select = document.getElementById('limit-select');
  const minP   = parseFloat(slider?.value || 70);
  const limit  = parseInt(select?.value || 50);

  const filtered = _allSignals
    .filter(s => s.probability >= minP)
    .slice(0, limit);

  const tbody = document.getElementById('scanner-body');
  if (!tbody) return;

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-row">No signals above ${minP}%. Try lowering the threshold or running a fresh scan.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map((s, i) => `
    <tr>
      <td>${i + 1}</td>
      <td><strong>${s.symbol}</strong></td>
      <td>${probBarHTML(s.probability)}</td>
      <td><span class="${verdictClass(s.verdict)}">${s.verdict}</span></td>
      <td style="font-family:var(--mono);font-size:.8rem">${fmtPrice(s.price)}</td>
      <td style="color:${rsiColor(s.rsi)}">${fmtNum(s.rsi)}</td>
      <td>${fmtNum(s.adx)}</td>
      <td>${fmtNum(s.volume_ratio, 2)}</td>
    </tr>`).join('');
}

// ═══════════════════════════════════════════════════════════════════
//  WATCHLIST TAB
// ═══════════════════════════════════════════════════════════════════

async function loadWatchlist() {
  try {
    const res  = await fetch('/api/watchlist');
    const data = await res.json();
    renderWatchlist(data.watchlist || []);
  } catch { /* silent */ }
}

function renderWatchlist(items) {
  const container = document.getElementById('watchlist-container');
  if (!container) return;

  if (!items || items.length === 0) {
    container.innerHTML = '<div class="empty-wl">No coins in watchlist yet. Add one above.</div>';
    return;
  }

  container.innerHTML = items.map(item => {
    const sym  = item.symbol;
    const prob = item.probability;
    const col  = prob != null ? probColor(prob) : 'var(--text-muted)';

    return `
      <div class="wl-card" onclick="quickAnalyzeNav('${sym}')">
        <div class="wl-card-header">
          <span class="wl-card-symbol">${sym}</span>
          <button class="wl-remove" onclick="event.stopPropagation(); removeFromWatchlist('${sym}')">✕</button>
        </div>
        <div class="wl-card-prob" style="color:${col}">
          ${prob != null ? prob.toFixed(1) + '%' : '—'}
        </div>
        ${item.verdict ? `<div style="margin-top:.4rem"><span class="${verdictClass(item.verdict)}" style="font-size:.65rem">${item.verdict}</span></div>` : ''}
        ${item.price   ? `<div style="font-size:.75rem;color:var(--text-muted);margin-top:.3rem">${fmtPrice(item.price)} USDT</div>` : ''}
      </div>`;
  }).join('');
}

async function addToWatchlist() {
  const input = document.getElementById('wl-input');
  const coin  = (input?.value || '').trim().toUpperCase();
  if (!coin) return;

  await _addWatchlistSymbol(coin);
  if (input) input.value = '';
}

async function addToWatchlistQuick(coin) {
  await _addWatchlistSymbol(coin);
}

async function _addWatchlistSymbol(coin) {
  try {
    const res  = await fetch('/api/watchlist', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ symbol: coin }),
    });
    const data = await res.json();
    renderWatchlist(data.watchlist || []);
    showToast(`⭐ ${coin} added to watchlist`);
  } catch {
    showToast('Failed to update watchlist', 'error');
  }
}

async function removeFromWatchlist(coin) {
  try {
    const res  = await fetch(`/api/watchlist/${coin}`, { method: 'DELETE' });
    const data = await res.json();
    renderWatchlist(data.watchlist || []);
    showToast(`${coin} removed from watchlist`);
  } catch {
    showToast('Failed to remove from watchlist', 'error');
  }
}

// ═══════════════════════════════════════════════════════════════════
//  SIGNAL HISTORY TAB
// ═══════════════════════════════════════════════════════════════════

async function loadHistory() {
  try {
    const res  = await fetch('/api/history?limit=200');
    const data = await res.json();
    renderHistory(data.history || []);
  } catch { /* silent */ }
}

function renderHistory(rows) {
  const tbody = document.getElementById('history-body');
  if (!tbody) return;

  if (!rows || rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-row">No history yet. Run a scan to populate.</td></tr>';
    return;
  }

  tbody.innerHTML = rows.map(r => `
    <tr>
      <td style="font-size:.75rem;color:var(--text-muted)">${fmtTime(r.scanned_at)}</td>
      <td><strong>${r.symbol}</strong></td>
      <td>${probBarHTML(r.probability)}</td>
      <td><span class="${verdictClass(r.verdict)}">${r.verdict}</span></td>
      <td style="font-family:var(--mono);font-size:.78rem">${fmtPrice(r.price)}</td>
      <td style="color:${rsiColor(r.rsi)}">${fmtNum(r.rsi)}</td>
      <td>${fmtNum(r.adx)}</td>
    </tr>`).join('');
}

// ═══════════════════════════════════════════════════════════════════
//  UTILITIES
// ═══════════════════════════════════════════════════════════════════

function fmtNum(val, decimals = 1) {
  if (val == null || isNaN(val)) return '—';
  return parseFloat(val).toFixed(decimals);
}

function fmtPrice(val) {
  if (val == null || isNaN(val)) return '—';
  const n = parseFloat(val);
  if (n >= 1000)     return n.toLocaleString('en', { maximumFractionDigits: 2 });
  if (n >= 1)        return n.toFixed(4);
  if (n >= 0.0001)   return n.toFixed(6);
  return n.toExponential(4);
}

function fmtTime(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString('en-GB', {
      month: 'short', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
    });
  } catch { return iso; }
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

let _toastTimer = null;
function showToast(msg, type = 'info') {
  const toast = document.getElementById('toast');
  if (!toast) return;
  toast.textContent = msg;
  toast.style.borderColor = type === 'error' ? 'rgba(239,68,68,.4)' : 'var(--glass-border)';
  toast.classList.remove('hidden');
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => toast.classList.add('hidden'), 3500);
}
