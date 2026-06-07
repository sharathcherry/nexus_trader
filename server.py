"""
server.py -- nexus_trader live dashboard server.

Replaces `python3 -m http.server 8080`.
Run: python3 server.py

Routes:
  GET /              -- full dashboard HTML (server-side rendered with historical data)
  GET /api/portfolio -- capital, positions, today trades, daily P&L  (DB only, fast)
  GET /api/prices    -- live yfinance prices for open positions       (20-30s latency OK)
  GET /api/logs      -- last N lines of today's log file
  GET /api/analytics -- rolling analytics.json stats
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

import pytz
import yfinance as yf
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)
IST       = pytz.timezone("Asia/Kolkata")
DB_PATH   = Path("execution/portfolio.db")
LOG_DIR   = Path("logs")
ANALYTICS = Path("logs/analytics/analytics.json")

# Simple in-memory price cache so every JS poll doesn't hammer yfinance
_price_cache: dict[str, float] = {}
_price_cache_ts: float = 0.0
_price_lock = threading.Lock()
_PRICE_TTL = 18  # seconds

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _conn():
    conn = sqlite3.connect(DB_PATH, timeout=5.0, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn

def _portfolio_data() -> dict:
    if not DB_PATH.exists():
        return {"capital": 100000, "daily_pnl": 0, "positions": [], "trades": [], "is_halted": False, "trade_count": 0}
    conn = _conn()
    meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM meta").fetchall()}
    positions = [dict(r) for r in conn.execute("SELECT * FROM positions ORDER BY entry_time DESC").fetchall()]
    today = datetime.now(IST).strftime("%Y-%m-%d")
    trades = [dict(r) for r in conn.execute(
        "SELECT * FROM trades WHERE exit_time LIKE ? ORDER BY exit_time DESC LIMIT 50",
        (f"{today}%",)
    ).fetchall()]
    all_trades = [dict(r) for r in conn.execute(
        "SELECT symbol, strategy, entry_price, exit_price, net_pnl, exit_reason, exit_time FROM trades ORDER BY exit_time DESC LIMIT 50"
    ).fetchall()]
    conn.close()
    return {
        "capital":     round(float(meta.get("capital", 100000)), 2),
        "daily_pnl":   round(float(meta.get("daily_pnl", 0)), 2),
        "trade_count": int(meta.get("trade_count", 0)),
        "is_halted":   meta.get("is_halted", "0") == "1",
        "positions":   positions,
        "today_trades": trades,
        "all_trades":  all_trades,
    }

def _live_prices(symbols: list[str]) -> dict[str, float]:
    global _price_cache, _price_cache_ts
    if not symbols:
        return {}
    with _price_lock:
        now = time.time()
        if now - _price_cache_ts < _PRICE_TTL and _price_cache:
            return _price_cache.copy()
        try:
            prices = {}
            for sym in symbols:
                df = yf.download(sym, period="1d", interval="1m", progress=False, auto_adjust=False)
                if df is not None and not df.empty:
                    prices[sym] = round(float(df["Close"].iloc[-1]), 2)
                time.sleep(0.15)
            _price_cache = prices
            _price_cache_ts = now
            return prices
        except Exception:
            return _price_cache.copy()

def _log_tail(n: int = 150) -> list[str]:
    files = sorted(LOG_DIR.glob("nexus_trader_*.log"), reverse=True)
    if not files:
        return ["No log file found."]
    try:
        lines = files[0].read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-n:]
    except Exception as e:
        return [f"Error reading log: {e}"]

# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.route("/api/portfolio")
def api_portfolio():
    return jsonify(_portfolio_data())

@app.route("/api/prices")
def api_prices():
    data = _portfolio_data()
    syms = [p["symbol"] for p in data["positions"]]
    prices = _live_prices(syms)
    enriched = []
    for p in data["positions"]:
        s = p["symbol"]
        current = prices.get(s)
        unreal = round((current - p["entry_price"]) * p["qty"], 2) if current else None
        enriched.append({**p, "current_price": current, "unrealized_pnl": unreal})
    return jsonify({"positions": enriched, "prices": prices})

@app.route("/api/logs")
def api_logs():
    n = int(request.args.get("n", 150))
    return jsonify({"lines": _log_tail(n)})

@app.route("/api/analytics")
def api_analytics():
    data = {}
    if ANALYTICS.exists():
        try:
            data = json.loads(ANALYTICS.read_text(encoding="utf-8"))
        except Exception:
            pass
    return jsonify(data)

# ---------------------------------------------------------------------------
# Dashboard HTML (server-side rendered with historical context)
# ---------------------------------------------------------------------------

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>nexus_trader</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{--bg:#080808;--surface:#111;--border:#1e1e1e;--text:#e4e4e4;--muted:#555;--pos:#22c55e;--neg:#ef4444;--accent:#6366f1;--warn:#f59e0b}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,sans-serif;font-size:14px;line-height:1.5}
.page{max-width:1280px;margin:0 auto;padding:24px 20px}
header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:28px}
.logo{font-size:1.1rem;font-weight:700;letter-spacing:.5px}
.logo span{color:var(--accent)}
.meta{font-size:12px;color:var(--muted);margin-top:3px}
.live-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--pos);margin-right:5px;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.halt-banner{background:#7f1d1d;color:#fca5a5;padding:10px 16px;border-radius:6px;margin-bottom:20px;font-weight:600;font-size:13px;display:none}
.halt-banner.show{display:block}
.kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1px;background:var(--border);border:1px solid var(--border);border-radius:8px;overflow:hidden;margin-bottom:20px}
.kpi{background:var(--surface);padding:16px 18px}
.kpi-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
.kpi-value{font-size:1.45rem;font-weight:700;color:#fff}
.kpi-value.pos{color:var(--pos)}.kpi-value.neg{color:var(--neg)}.kpi-value.warn{color:var(--warn)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:18px;margin-bottom:18px}
.card-head{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:14px;display:flex;justify-content:space-between;align-items:center}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:18px}
@media(max-width:720px){.two-col{grid-template-columns:1fr}}
.chart-wrap{height:200px;position:relative}
.tbl-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse}
th{font-size:11px;font-weight:500;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);padding:7px 10px;text-align:left;border-bottom:1px solid var(--border)}
td{padding:8px 10px;border-bottom:1px solid #161616;vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:#161616}
.tag{font-size:11px;color:var(--muted)}
.dim{color:var(--muted)}.pos{color:var(--pos)}.neg{color:var(--neg)}
.empty{color:var(--muted);text-align:center;padding:20px}
.badge{display:inline-block;font-size:10px;padding:2px 6px;border-radius:3px;font-weight:600}
.badge-pos{background:#14532d;color:var(--pos)}
.badge-neg{background:#450a0a;color:var(--neg)}
/* Log viewer */
.log-box{background:#050505;border:1px solid var(--border);border-radius:6px;height:340px;overflow-y:auto;padding:12px;font-family:'JetBrains Mono','Fira Code',monospace;font-size:12px;line-height:1.6}
.log-box::-webkit-scrollbar{width:6px}
.log-box::-webkit-scrollbar-track{background:#111}
.log-box::-webkit-scrollbar-thumb{background:#333;border-radius:3px}
.log-line{white-space:pre-wrap;word-break:break-all}
.log-line.err{color:#ef4444}.log-line.warn{color:#f59e0b}.log-line.buy{color:#22c55e}.log-line.sell{color:#fb923c}.log-line.info{color:#888}
.log-controls{display:flex;gap:8px;margin-bottom:10px;align-items:center}
.log-controls select,.log-controls button{background:#1a1a1a;border:1px solid var(--border);color:var(--text);padding:4px 10px;border-radius:4px;font-size:12px;cursor:pointer}
.log-controls button:hover{background:#222}
.filter-btn{padding:3px 8px;border-radius:3px;font-size:11px;border:1px solid var(--border);background:transparent;color:var(--muted);cursor:pointer}
.filter-btn.active{background:var(--accent);color:#fff;border-color:var(--accent)}
footer{text-align:center;font-size:11px;color:var(--muted);margin-top:28px;padding-top:14px;border-top:1px solid var(--border)}
</style>
</head>
<body>
<div class="page">

<header>
  <div>
    <div class="logo">nexus<span>_</span>trader</div>
    <div class="meta">NSE paper trading &nbsp;|&nbsp; Rs1,00,000 capital &nbsp;|&nbsp; Nifty 100</div>
  </div>
  <div style="text-align:right;font-size:12px;color:var(--muted)">
    <span class="live-dot"></span><span id="live-status">connecting...</span><br>
    <span id="last-update" style="font-size:11px"></span>
  </div>
</header>

<div id="halt-banner" class="halt-banner">TRADING HALTED -- Daily loss limit reached</div>

<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">Capital</div><div class="kpi-value" id="kpi-capital">--</div></div>
  <div class="kpi"><div class="kpi-label">Daily P&L</div><div class="kpi-value" id="kpi-dpnl">--</div></div>
  <div class="kpi"><div class="kpi-label">Trades Today</div><div class="kpi-value" id="kpi-trades">--</div></div>
  <div class="kpi"><div class="kpi-label">Open Positions</div><div class="kpi-value" id="kpi-open">--</div></div>
  <div class="kpi"><div class="kpi-label">All-time P&L</div><div class="kpi-value" id="kpi-allpnl">--</div></div>
  <div class="kpi"><div class="kpi-label">Win Rate</div><div class="kpi-value" id="kpi-wr">--</div></div>
  <div class="kpi"><div class="kpi-label">Profit Factor</div><div class="kpi-value" id="kpi-pf">--</div></div>
  <div class="kpi"><div class="kpi-label">Avg R:R</div><div class="kpi-value" id="kpi-rr">--</div></div>
</div>

<!-- Live Positions -->
<div class="card">
  <div class="card-head">Live Positions <span id="pos-updated" class="dim" style="font-size:10px"></span></div>
  <div class="tbl-wrap"><table id="pos-table">
    <thead><tr><th>Symbol</th><th>Strategy</th><th>Entry</th><th>Current</th><th>Unrealized P&L</th><th>Stop</th><th>Target</th><th>Qty</th></tr></thead>
    <tbody id="pos-body"><tr><td colspan="8" class="empty">Loading...</td></tr></tbody>
  </table></div>
</div>

<!-- Charts -->
<div class="two-col">
  <div class="card">
    <div class="card-head">Equity Curve</div>
    <div class="chart-wrap"><canvas id="eqChart"></canvas></div>
  </div>
  <div class="card">
    <div class="card-head">Daily P&L</div>
    <div class="chart-wrap"><canvas id="dlChart"></canvas></div>
  </div>
</div>

<!-- Trade History -->
<div class="card">
  <div class="card-head">Trade History <span class="dim">last 50</span></div>
  <div class="tbl-wrap"><table id="trades-table">
    <thead><tr><th>Symbol</th><th>Strategy</th><th>Entry</th><th>Exit</th><th>Reason</th><th>Net P&L</th><th>Time</th></tr></thead>
    <tbody id="trades-body"><tr><td colspan="7" class="empty">Loading...</td></tr></tbody>
  </table></div>
</div>

<!-- Analytics -->
<div class="two-col">
  <div class="card">
    <div class="card-head">By Strategy</div>
    <div class="chart-wrap" style="height:160px"><canvas id="stChart"></canvas></div>
  </div>
  <div class="card">
    <div class="card-head">By Exit Reason</div>
    <div class="tbl-wrap" id="exit-reason-table"></div>
  </div>
</div>

<!-- Log Viewer -->
<div class="card">
  <div class="card-head">
    Live Log Stream
    <span style="display:flex;gap:6px;align-items:center">
      <button class="filter-btn active" data-filter="all" onclick="setFilter('all',this)">All</button>
      <button class="filter-btn" data-filter="err" onclick="setFilter('err',this)">Errors</button>
      <button class="filter-btn" data-filter="buy" onclick="setFilter('buy',this)">Buys</button>
      <button class="filter-btn" data-filter="sell" onclick="setFilter('sell',this)">Sells</button>
      <button class="filter-btn" data-filter="warn" onclick="setFilter('warn',this)">Warnings</button>
      <button class="filter-btn" style="margin-left:8px" onclick="toggleAutoScroll()">Auto-scroll: <span id="as-label">ON</span></button>
    </span>
  </div>
  <div class="log-box" id="log-box"></div>
</div>

<footer>nexus_trader &nbsp;|&nbsp; paper trading &nbsp;|&nbsp; yfinance data &nbsp;|&nbsp; no real money</footer>
</div>

<script>
const C = Chart.defaults;
C.color = '#555'; C.borderColor = '#1e1e1e';
C.font.family = 'system-ui,-apple-system,sans-serif';
const axes = {
  x:{grid:{color:'#161616'},ticks:{color:'#555',maxTicksLimit:7}},
  y:{grid:{color:'#161616'},ticks:{color:'#555'}}
};

let eqChart, dlChart, stChart;
let allLogLines = [];
let logFilter = 'all';
let autoScroll = true;

function rs(v){return 'Rs' + v.toLocaleString('en-IN', {minimumFractionDigits:2,maximumFractionDigits:2})}
function rss(v){return (v>=0?'Rs+':'Rs') + Math.abs(v).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2})}
function cls(v){return v>0?'pos':v<0?'neg':''}

// ---- Portfolio poll (5s) ----
async function pollPortfolio(){
  try{
    const d = await fetch('/api/portfolio').then(r=>r.json());

    // KPI
    document.getElementById('kpi-capital').textContent = rs(d.capital);
    const dpEl = document.getElementById('kpi-dpnl');
    dpEl.textContent = rss(d.daily_pnl);
    dpEl.className = 'kpi-value ' + cls(d.daily_pnl);
    document.getElementById('kpi-trades').textContent = d.trade_count;
    document.getElementById('kpi-open').textContent = d.positions.length;

    // Halt
    document.getElementById('halt-banner').classList.toggle('show', d.is_halted);

    // Trades table
    const tb = document.getElementById('trades-body');
    if(d.all_trades.length===0){
      tb.innerHTML='<tr><td colspan="7" class="empty">No trades yet</td></tr>';
    } else {
      tb.innerHTML = d.all_trades.map(t=>{
        const c=cls(t.net_pnl);
        return `<tr>
          <td><b>${t.symbol}</b></td>
          <td class="tag">${t.strategy||''}</td>
          <td>Rs${t.entry_price.toFixed(2)}</td>
          <td>Rs${t.exit_price.toFixed(2)}</td>
          <td class="dim">${t.exit_reason||''}</td>
          <td class="${c}"><b>${rss(t.net_pnl)}</b></td>
          <td class="dim">${(t.exit_time||'').slice(0,16)}</td>
        </tr>`;
      }).join('');
    }

    // Equity + daily charts
    let capital = 100000;
    const eqLabels = ['Start'], eqVals = [capital];
    const dlMap = {};
    for(const t of [...d.all_trades].reverse()){
      capital += t.net_pnl;
      eqLabels.push(t.symbol);
      eqVals.push(+capital.toFixed(2));
      const dk = (t.exit_time||'').slice(0,10);
      dlMap[dk] = (dlMap[dk]||0) + t.net_pnl;
    }
    const dlLabels = Object.keys(dlMap).sort();
    const dlVals = dlLabels.map(k=>+dlMap[k].toFixed(2));
    const dlColors = dlVals.map(v=>v>=0?'#22c55e':'#ef4444');

    if(!eqChart){
      eqChart = new Chart('eqChart',{type:'line',data:{labels:eqLabels,datasets:[{label:'Capital',data:eqVals,borderColor:'#6366f1',backgroundColor:'rgba(99,102,241,0.06)',fill:true,tension:0.35,pointRadius:0,borderWidth:2}]},options:{maintainAspectRatio:false,plugins:{legend:{display:false}},scales:axes}});
      dlChart = new Chart('dlChart',{type:'bar',data:{labels:dlLabels,datasets:[{label:'P&L',data:dlVals,backgroundColor:dlColors,borderRadius:3,borderSkipped:false}]},options:{maintainAspectRatio:false,plugins:{legend:{display:false}},scales:axes}});
    } else {
      eqChart.data.labels=eqLabels; eqChart.data.datasets[0].data=eqVals; eqChart.update('none');
      dlChart.data.labels=dlLabels; dlChart.data.datasets[0].data=dlVals; dlChart.data.datasets[0].backgroundColor=dlColors; dlChart.update('none');
    }

    document.getElementById('live-status').textContent='live';
    document.getElementById('last-update').textContent='updated '+new Date().toLocaleTimeString();
  }catch(e){document.getElementById('live-status').textContent='error';}
}

// ---- Prices poll (20s) ----
async function pollPrices(){
  try{
    const d = await fetch('/api/prices').then(r=>r.json());
    const pb = document.getElementById('pos-body');
    document.getElementById('pos-updated').textContent = 'updated '+new Date().toLocaleTimeString();
    if(d.positions.length===0){
      pb.innerHTML='<tr><td colspan="8" class="empty">No open positions</td></tr>';
      return;
    }
    pb.innerHTML = d.positions.map(p=>{
      const cp = p.current_price;
      const up = p.unrealized_pnl;
      const cpStr = cp!=null ? `<b>Rs${cp.toFixed(2)}</b>` : '<span class="dim">--</span>';
      const upStr = up!=null ? `<span class="${cls(up)}">${rss(up)}</span>` : '<span class="dim">--</span>';
      return `<tr>
        <td><b>${p.symbol}</b></td>
        <td class="tag">${p.strategy||''}</td>
        <td>Rs${(+p.entry_price).toFixed(2)}</td>
        <td>${cpStr}</td>
        <td>${upStr}</td>
        <td class="neg">Rs${(+p.stop_loss).toFixed(2)}</td>
        <td class="pos">Rs${(+p.target).toFixed(2)}</td>
        <td>${p.qty}</td>
      </tr>`;
    }).join('');
  }catch(e){}
}

// ---- Analytics poll (30s) ----
async function pollAnalytics(){
  try{
    const a = await fetch('/api/analytics').then(r=>r.json());
    if(!a.total_trades) return;

    const totPnl = a.total_net_pnl||0;
    const wins = a.winners||0; const total = a.total_trades||1;
    const wr = (wins/total*100).toFixed(1);
    const gw = Object.values(a.by_exit_reason||{}).filter((_,i)=>Object.keys(a.by_exit_reason)[i]==='TARGET').reduce((s,v)=>s+v.net_pnl,0);

    document.getElementById('kpi-allpnl').textContent = rss(totPnl);
    document.getElementById('kpi-allpnl').className = 'kpi-value ' + cls(totPnl);
    document.getElementById('kpi-wr').textContent = wr + '%';
    document.getElementById('kpi-rr').textContent = (a.avg_realized_rr||0).toFixed(2);

    // Strategy chart
    const bs = a.by_strategy||{};
    const stLabels = Object.keys(bs);
    const stWins   = stLabels.map(k=>bs[k].winners||0);
    const stLosses = stLabels.map(k=>(bs[k].trades||0)-(bs[k].winners||0));
    if(!stChart){
      stChart = new Chart('stChart',{type:'bar',data:{labels:stLabels,datasets:[{label:'Wins',data:stWins,backgroundColor:'#22c55e',borderRadius:3},{label:'Losses',data:stLosses,backgroundColor:'#ef4444',borderRadius:3}]},options:{maintainAspectRatio:false,scales:axes,plugins:{legend:{labels:{color:'#555',boxWidth:10}}}}});
    } else {
      stChart.data.labels=stLabels;
      stChart.data.datasets[0].data=stWins;
      stChart.data.datasets[1].data=stLosses;
      stChart.update('none');
    }

    // Exit reason table
    const er = a.by_exit_reason||{};
    const rows = Object.entries(er).map(([k,v])=>
      `<tr><td><b>${k}</b></td><td>${v.count}</td><td class="${cls(v.net_pnl)}">${rss(v.net_pnl)}</td></tr>`
    ).join('');
    document.getElementById('exit-reason-table').innerHTML =
      `<table><thead><tr><th>Exit Reason</th><th>Count</th><th>Net P&L</th></tr></thead><tbody>${rows||'<tr><td colspan="3" class="empty">No data</td></tr>'}</tbody></table>`;
  }catch(e){}
}

// ---- Log poll (8s) ----
function classifyLine(line){
  const l = line.toLowerCase();
  if(l.includes('error') || l.includes('exception') || l.includes('traceback')) return 'err';
  if(l.includes('warning') || l.includes('warn')) return 'warn';
  if(l.includes(' buy ') || l.includes('buy ') || l.includes('bought')) return 'buy';
  if(l.includes(' sell ') || l.includes('sell ') || l.includes('squareoff')) return 'sell';
  return 'info';
}

function setFilter(f, btn){
  logFilter=f;
  document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  renderLogs();
}

function toggleAutoScroll(){
  autoScroll=!autoScroll;
  document.getElementById('as-label').textContent=autoScroll?'ON':'OFF';
}

function renderLogs(){
  const box = document.getElementById('log-box');
  const filtered = logFilter==='all' ? allLogLines : allLogLines.filter(l=>classifyLine(l)===logFilter);
  box.innerHTML = filtered.map(l=>{
    const c=classifyLine(l);
    const esc=l.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    return `<div class="log-line ${c}">${esc}</div>`;
  }).join('');
  if(autoScroll) box.scrollTop = box.scrollHeight;
}

async function pollLogs(){
  try{
    const d = await fetch('/api/logs?n=150').then(r=>r.json());
    allLogLines = d.lines||[];
    renderLogs();
  }catch(e){}
}

// ---- Boot ----
pollPortfolio();
pollPrices();
pollAnalytics();
pollLogs();
setInterval(pollPortfolio, 5000);
setInterval(pollPrices, 20000);
setInterval(pollAnalytics, 30000);
setInterval(pollLogs, 8000);
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"nexus_trader dashboard running at http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)
