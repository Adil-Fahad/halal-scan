/* ═══════════════════════════════════════════════════════════════════
   HALAL SCAN AI PRO ULTIMATE — app.js v2 (Mobile-First)
   ═══════════════════════════════════════════════════════════════════ */
'use strict';

let _allSignals = [];

// ── Init ───────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  checkStatus();
  loadSignals();
  loadHistory();
  loadWatchlist();
  setInterval(checkStatus, 30_000);
});

// ── Tab Switching ──────────────────────────────────────────────────────────
function showTab(name) {
  document.querySelectorAll('.tab').forEach(t => {
    t.classList.remove('active'); t.classList.add('hidden');
  });
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

  const tab = document.getElementById(`tab-${name}`);
  if (tab) { tab.classList.remove('hidden'); tab.classList.add('active'); }

  const nav = document.getElementById(`nav-${name}`);
  if (nav) nav.classList.add('active');
}

// ── Status ─────────────────────────────────────────────────────────────────
async function checkStatus() {
  const dot  = document.getElementById('status-dot');
  const text = document.getElementById('status-text');
  try {
    const data = await fetchJSON('/api/status');
    dot.className  = 'status-dot ' + (data.model_ready ? 'online' : 'offline');
    text.textContent = data.model_ready ? 'Model Ready' : 'No Model';
  } catch {
    dot.className    = 'status-dot error';
    text.textContent = 'Offline';
  }
}

// ── Helpers ────────────────────────────────────────────────────────────────
async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  return r.json();
}

function probColor(p) {
  if (p >= 85) return '#f97316';
  if (p >= 70) return '#22c55e';
  if (p >= 50) return '#eab308';
  return '#ef4444';
}

function verdictClass(v) {
  return 'verdict verdict-' + (v || 'AVOID').replace(/\s+/g, '-');
}

function fmtNum(v, d = 1) {
  if (v == null || isNaN(v)) return '—';
  return parseFloat(v).toFixed(d);
}

function fmtPrice(v) {
  if (v == null || isNaN(v)) return '—';
  const n = parseFloat(v);
  if (n >= 1000) return n.toLocaleString('en', { maximumFractionDigits: 2 });
  if (n >= 1)    return n.toFixed(4);
  if (n >= 0.0001) return n.toFixed(6);
  return n.toExponential(3);
}

function fmtTime(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('en-GB', {
      month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit'
    });
  } catch { return iso; }
}

function retHTML(val) {
  if (val == null || isNaN(val)) return '<span style="color:var(--text-muted)">—</span>';
  const cls = val >= 0 ? 'positive' : 'negative';
  return `<span class="${cls}">${val >= 0 ? '+' : ''}${val.toFixed(2)}%</span>`;
}

function rsiColor(r) {
  if (r >= 70) return '#ef4444';
  if (r <= 30) return '#22c55e';
  return '#e2e8f0';
}

function cardClass(verdict) {
  const v = (verdict || '').toLowerCase().replace(/\s+/g, '-');
  if (v.includes('strong')) return 'strong-buy';
  if (v === 'buy')          return 'buy';
  if (v === 'watch')        return 'watch';
  return 'avoid';
}

// ── Prob Ring SVG ──────────────────────────────────────────────────────────
function probRingSM(prob) {
  const color = probColor(prob);
  const deg   = Math.round(Math.min(prob, 100) * 3.6);
  return `
    <div class="prob-ring-sm" style="background:conic-gradient(${color} ${deg}deg, rgba(255,255,255,.07) ${deg}deg)">
      <span class="prob-ring-val" style="color:${color}">${prob.toFixed(0)}%</span>
      <span class="prob-ring-lbl">AI</span>
    </div>`;
}

function probRingLG(prob) {
  const color = probColor(prob);
  const deg   = Math.round(Math.min(prob, 100) * 3.6);
  return `
    <div class="prob-ring-lg" style="background:conic-gradient(${color} ${deg}deg, rgba(255,255,255,.07) ${deg}deg)">
      <span class="val" style="color:${color}">${prob.toFixed(1)}%</span>
      <span class="lbl">AI Score</span>
    </div>`;
}

// ── Flow badge ──────────────────────────────────────────────────────────────
function flowBadgeHTML(signal, score) {
  if (!signal) return '';
  const cls = signal === 'BUYING PRESSURE' ? 'flow-buying'
            : signal === 'SELLING PRESSURE' ? 'flow-selling'
            : 'flow-neutral';
  const icon = signal === 'BUYING PRESSURE' ? '📈'
             : signal === 'SELLING PRESSURE' ? '📉' : '➡️';
  return `<span class="flow-badge ${cls}">${icon} ${signal}</span>`;
}

// ─────────────────────────────────────────────────────────────────────────────
//  SIGNALS TAB
// ─────────────────────────────────────────────────────────────────────────────

async function loadSignals() {
  try {
    const data = await fetchJSON('/api/signals?min_prob=60&limit=100');
    _allSignals = data.signals || [];
    renderSignalCards(_allSignals, 'signals-list');
    updateStats(_allSignals);

    const c = document.getElementById('signals-count');
    const t = document.getElementById('signals-time');
    if (c) c.textContent = `${_allSignals.length}`;
    if (t) t.textContent = data.timestamp ? fmtTime(data.timestamp) : '';
  } catch (e) {
    document.getElementById('signals-list').innerHTML =
      '<div class="error-box">Failed to load signals. Is the server running?</div>';
  }
}

function renderSignalCards(signals, containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;

  if (!signals || signals.length === 0) {
    el.innerHTML = '<div class="glass-card" style="text-align:center;color:var(--text-muted);padding:2rem">No signals found. Tap ⚡ Scan Market Now.</div>';
    return;
  }

  el.innerHTML = signals.map((s, i) => {
    const verdict  = s.combined_verdict || s.verdict || 'AVOID';
    const flowHTML = s.flow_signal
      ? `<div class="card-flow">
           ${flowBadgeHTML(s.flow_signal, s.flow_score)}
           ${s.taker_buy_ratio != null
             ? `<span class="flow-mini">Buy ratio <span>${fmtNum(s.taker_buy_ratio)}%</span></span>`
             : ''}
           ${s.whale_net != null
             ? `<span class="flow-mini">Whales <span style="color:${s.whale_net >= 0 ? 'var(--green)' : 'var(--red)'}">
                  ${s.whale_net >= 0 ? '+' : ''}${s.whale_net}
                </span></span>`
             : ''}
         </div>`
      : '';

    return `
      <div class="signal-card ${cardClass(verdict)}">
        <div class="card-row1">
          <span class="card-symbol">${s.symbol}</span>
          <span class="${verdictClass(verdict)}">${verdict}</span>
          <span class="card-price">${fmtPrice(s.price)}</span>
        </div>
        <div class="card-row2">
          ${probRingSM(s.probability)}
          <div class="card-stats">
            <div class="mini-stat">
              <div class="mini-stat-lbl">RSI</div>
              <div class="mini-stat-val" style="color:${rsiColor(s.rsi)}">${fmtNum(s.rsi)}</div>
            </div>
            <div class="mini-stat">
              <div class="mini-stat-lbl">ADX</div>
              <div class="mini-stat-val">${fmtNum(s.adx)}</div>
            </div>
            <div class="mini-stat">
              <div class="mini-stat-lbl">24h</div>
              <div class="mini-stat-val">${retHTML(s.return_24h)}</div>
            </div>
            <div class="mini-stat">
              <div class="mini-stat-lbl">Vol</div>
              <div class="mini-stat-val">${fmtNum(s.volume_ratio, 2)}x</div>
            </div>
            <div class="mini-stat">
              <div class="mini-stat-lbl">72h</div>
              <div class="mini-stat-val">${retHTML(s.return_72h)}</div>
            </div>
            ${s.flow_score != null
              ? `<div class="mini-stat">
                   <div class="mini-stat-lbl">Flow</div>
                   <div class="mini-stat-val" style="color:${probColor(s.flow_score)}">${fmtNum(s.flow_score)}%</div>
                 </div>`
              : '<div class="mini-stat"></div>'}
          </div>
        </div>
        ${flowHTML}
        <div class="card-actions">
          <button class="card-btn" onclick="addToWatchlistQuick('${s.symbol}')">★ Watch</button>
          <button class="card-btn primary" onclick="goAnalyze('${s.symbol}')">🔬 Analyze</button>
        </div>
      </div>`;
  }).join('');
}

function updateStats(signals) {
  const total  = signals.length;
  const strong = signals.filter(s => (s.combined_verdict || s.verdict) === 'STRONG BUY').length;
  const buy    = signals.filter(s => (s.combined_verdict || s.verdict) === 'BUY').length;
  const avg    = total > 0 ? signals.reduce((a, s) => a + s.probability, 0) / total : 0;

  setText('stat-total',  total);
  setText('stat-strong', strong);
  setText('stat-buy',    buy);
  setText('stat-avg',    avg.toFixed(1) + '%');
}

// ─────────────────────────────────────────────────────────────────────────────
//  FULL SCAN
// ─────────────────────────────────────────────────────────────────────────────

async function runFullScan() {
  document.getElementById('scan-modal').classList.remove('hidden');
  try {
    const data = await fetchJSON('/api/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ min_prob: 60, top_n: 50 }),
    });
    if (data.success) {
      _allSignals = data.signals || [];
      renderSignalCards(_allSignals, 'signals-list');
      updateStats(_allSignals);
      showToast(`✅ ${data.count} signals found`);
    } else {
      showToast('Scan failed: ' + (data.error || 'Unknown'), 'error');
    }
  } catch {
    showToast('Scan request failed', 'error');
  } finally {
    document.getElementById('scan-modal').classList.add('hidden');
  }
}

// ─────────────────────────────────────────────────────────────────────────────
//  ANALYZER TAB
// ─────────────────────────────────────────────────────────────────────────────

async function analyzeCoin() {
  const input   = document.getElementById('coin-input');
  const loading = document.getElementById('analyzer-loading');
  const result  = document.getElementById('analyzer-result');
  const errBox  = document.getElementById('analyzer-error');

  const coin = (input?.value || '').trim().toUpperCase();
  if (!coin) { showToast('Enter a symbol first'); return; }

  loading.classList.remove('hidden');
  result.innerHTML = '';
  errBox.classList.add('hidden');

  try {
    const data = await fetchJSON(`/api/analyze/${coin}`);
    if (data.error) {
      errBox.textContent = data.error;
      errBox.classList.remove('hidden');
    } else {
      result.innerHTML = buildAnalyzerCard(data);
    }
  } catch {
    errBox.textContent = 'Request failed — is the server running?';
    errBox.classList.remove('hidden');
  } finally {
    loading.classList.add('hidden');
  }
}

function buildAnalyzerCard(d) {
  const prob    = d.probability || 0;
  const verdict = d.combined_verdict || d.verdict || 'AVOID';
  const strength = d.signal_strength || 1;
  const pips = [1,2,3,4].map(n =>
    `<div class="strength-pip ${n <= strength ? 'on' : ''}"></div>`
  ).join('');

  // Order flow section
  const hasFlow = d.flow_score != null;
  const flowSection = hasFlow ? `
    <div class="flow-section">
      <div class="flow-title">⚡ Order Flow Analysis</div>
      <div class="flow-grid">
        <div class="flow-item">
          <div class="flow-item-lbl">Flow Score</div>
          <div class="flow-item-val" style="color:${probColor(d.flow_score)}">${fmtNum(d.flow_score)}%</div>
        </div>
        <div class="flow-item">
          <div class="flow-item-lbl">Signal</div>
          <div class="flow-item-val" style="font-size:.8rem">${d.flow_signal || '—'}</div>
        </div>
        <div class="flow-item">
          <div class="flow-item-lbl">Buy Ratio</div>
          <div class="flow-item-val" style="color:${d.taker_buy_ratio >= 50 ? 'var(--green)' : 'var(--red)'}">
            ${fmtNum(d.taker_buy_ratio)}%
          </div>
        </div>
        <div class="flow-item">
          <div class="flow-item-lbl">OB Imbalance</div>
          <div class="flow-item-val" style="color:${d.ob_imbalance_pct >= 0 ? 'var(--green)' : 'var(--red)'}">
            ${d.ob_imbalance_pct != null ? (d.ob_imbalance_pct >= 0 ? '+' : '') + fmtNum(d.ob_imbalance_pct) + '%' : '—'}
          </div>
        </div>
        <div class="flow-item">
          <div class="flow-item-lbl">Whale Buys</div>
          <div class="flow-item-val" style="color:var(--green)">${d.whale_buys ?? '—'}</div>
        </div>
        <div class="flow-item">
          <div class="flow-item-lbl">Whale Sells</div>
          <div class="flow-item-val" style="color:var(--red)">${d.whale_sells ?? '—'}</div>
        </div>
      </div>
      <!-- Buy/Sell pressure bar -->
      <div class="flow-bar-wrap">
        <div class="flow-bar-label">
          <span>Sell ${fmtNum(100 - (d.taker_buy_ratio || 50))}%</span>
          <span>Buy ${fmtNum(d.taker_buy_ratio || 50)}%</span>
        </div>
        <div class="flow-bar-track">
          <div class="flow-bar-fill" style="width:100%"></div>
          <div class="flow-bar-marker" style="left:${d.taker_buy_ratio || 50}%"></div>
        </div>
      </div>
    </div>` : '<div class="error-box" style="margin-bottom:1rem">Order flow unavailable for this coin.</div>';

  return `
    <div class="analyzer-card">
      <div class="analyzer-hero">
        ${probRingLG(prob)}
        <div class="analyzer-info">
          <div class="analyzer-sym">${d.symbol}</div>
          <div class="analyzer-price">${fmtPrice(d.price)} USDT</div>
          <div style="margin-top:.5rem;display:flex;align-items:center;gap:.5rem">
            <span class="${verdictClass(verdict)}">${verdict}</span>
          </div>
          <div class="strength-row">${pips}</div>
        </div>
        <button class="card-btn" style="align-self:flex-start"
                onclick="addToWatchlistQuick('${d.symbol}')">★</button>
      </div>

      ${flowSection}

      <div class="metrics-grid">
        <div class="metric-box">
          <div class="metric-lbl">RSI (14)</div>
          <div class="metric-val" style="color:${rsiColor(d.rsi)}">${fmtNum(d.rsi)}</div>
        </div>
        <div class="metric-box">
          <div class="metric-lbl">ADX</div>
          <div class="metric-val">${fmtNum(d.adx)}</div>
        </div>
        <div class="metric-box">
          <div class="metric-lbl">Vol Ratio</div>
          <div class="metric-val">${fmtNum(d.volume_ratio, 2)}x</div>
        </div>
        <div class="metric-box">
          <div class="metric-lbl">Return 24h</div>
          <div class="metric-val">${retHTML(d.return_24h)}</div>
        </div>
        <div class="metric-box">
          <div class="metric-lbl">Return 72h</div>
          <div class="metric-val">${retHTML(d.return_72h)}</div>
        </div>
        <div class="metric-box">
          <div class="metric-lbl">MACD</div>
          <div class="metric-val" style="font-size:.78rem">${fmtNum(d.macd, 6)}</div>
        </div>
        <div class="metric-box">
          <div class="metric-lbl">EMA 20</div>
          <div class="metric-val" style="font-size:.78rem">${fmtPrice(d.ema20)}</div>
        </div>
        <div class="metric-box">
          <div class="metric-lbl">EMA 50</div>
          <div class="metric-val" style="font-size:.78rem">${fmtPrice(d.ema50)}</div>
        </div>
        <div class="metric-box">
          <div class="metric-lbl">Scanned</div>
          <div class="metric-val" style="font-size:.72rem;color:var(--text-muted)">${fmtTime(d.scanned_at)}</div>
        </div>
      </div>
    </div>`;
}

function quickAnalyze(coin) {
  const input = document.getElementById('coin-input');
  if (input) input.value = coin;
  showTab('analyzer');
  analyzeCoin();
}

function goAnalyze(coin) {
  showTab('analyzer');
  const input = document.getElementById('coin-input');
  if (input) input.value = coin;
  analyzeCoin();
}

// ─────────────────────────────────────────────────────────────────────────────
//  SCANNER FILTER TAB
// ─────────────────────────────────────────────────────────────────────────────

function updateProbLabel(val) {
  const el = document.getElementById('prob-label');
  if (el) el.textContent = val + '%';
}

function filterSignals() {
  const minP  = parseFloat(document.getElementById('prob-slider')?.value || 70);
  const limit = parseInt(document.getElementById('limit-select')?.value || 50);
  const filtered = _allSignals.filter(s => s.probability >= minP).slice(0, limit);
  renderSignalCards(filtered, 'scanner-list');
}

// ─────────────────────────────────────────────────────────────────────────────
//  WATCHLIST TAB
// ─────────────────────────────────────────────────────────────────────────────

async function loadWatchlist() {
  try {
    const data = await fetchJSON('/api/watchlist');
    renderWatchlist(data.watchlist || []);
  } catch { /* silent */ }
}

function renderWatchlist(items) {
  const el = document.getElementById('watchlist-grid');
  if (!el) return;

  if (!items || items.length === 0) {
    el.innerHTML = '<div class="empty-wl">No coins yet. Add one above.</div>';
    return;
  }

  el.innerHTML = items.map(item => {
    const sym  = item.symbol;
    const prob = item.probability;
    const col  = prob != null ? probColor(prob) : 'var(--text-muted)';
    const verdict = item.verdict || '';

    return `
      <div class="wl-card" onclick="goAnalyze('${sym}')">
        <div class="wl-card-top">
          <span class="wl-card-sym">${sym}</span>
          <button class="wl-remove" onclick="event.stopPropagation();removeFromWatchlist('${sym}')">✕</button>
        </div>
        <div class="wl-card-prob" style="color:${col}">
          ${prob != null ? prob.toFixed(1) + '%' : '—'}
        </div>
        ${verdict ? `<div style="margin-top:.35rem"><span class="${verdictClass(verdict)}" style="font-size:.6rem">${verdict}</span></div>` : ''}
        ${item.price ? `<div class="wl-card-price">${fmtPrice(item.price)} USDT</div>` : ''}
      </div>`;
  }).join('');
}

async function addToWatchlist() {
  const input = document.getElementById('wl-input');
  const coin  = (input?.value || '').trim().toUpperCase();
  if (!coin) return;
  await _addWL(coin);
  if (input) input.value = '';
}

async function addToWatchlistQuick(coin) {
  await _addWL(coin);
  showToast(`⭐ ${coin} added to watchlist`);
}

async function _addWL(coin) {
  try {
    const data = await fetchJSON('/api/watchlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: coin }),
    });
    renderWatchlist(data.watchlist || []);
    showToast(`⭐ ${coin} added`);
  } catch { showToast('Failed to update watchlist', 'error'); }
}

async function removeFromWatchlist(coin) {
  try {
    const data = await fetchJSON(`/api/watchlist/${coin}`, { method: 'DELETE' });
    renderWatchlist(data.watchlist || []);
    showToast(`${coin} removed`);
  } catch { showToast('Failed to remove', 'error'); }
}

// ─────────────────────────────────────────────────────────────────────────────
//  HISTORY TAB
// ─────────────────────────────────────────────────────────────────────────────

async function loadHistory() {
  try {
    const data = await fetchJSON('/api/history?limit=100');
    renderHistory(data.history || []);
  } catch { /* silent */ }
}

function renderHistory(rows) {
  const el = document.getElementById('history-list');
  if (!el) return;

  if (!rows || rows.length === 0) {
    el.innerHTML = '<div style="text-align:center;color:var(--text-muted);padding:1.5rem">No history yet.</div>';
    return;
  }

  el.innerHTML = rows.map(r => `
    <div class="history-item" onclick="goAnalyze('${r.symbol}')">
      <span class="history-sym">${r.symbol}</span>
      <span class="history-time">${fmtTime(r.scanned_at)}</span>
      <span class="${verdictClass(r.verdict)}">${r.verdict || '—'}</span>
      <span style="color:${probColor(r.probability)};font-weight:700;font-size:.82rem;min-width:42px;text-align:right">
        ${fmtNum(r.probability)}%
      </span>
    </div>`).join('');
}

// ─────────────────────────────────────────────────────────────────────────────
//  UTILITIES
// ─────────────────────────────────────────────────────────────────────────────

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

let _toastTimer = null;
function showToast(msg, type = 'info') {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.style.borderColor = type === 'error' ? 'rgba(239,68,68,.4)' : 'var(--glass-border)';
  t.classList.remove('hidden');
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => t.classList.add('hidden'), 3000);
}
