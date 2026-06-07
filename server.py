"""
server.py -- nexus_trader live dashboard server.
Run: python3 server.py
"""
from __future__ import annotations
import json, sqlite3, threading, time
from datetime import datetime
from pathlib import Path

import pytz, yfinance as yf
from flask import Flask, jsonify, render_template_string, request

app     = Flask(__name__)
IST     = pytz.timezone("Asia/Kolkata")
DB_PATH = Path("execution/portfolio.db")
LOG_DIR = Path("logs")
ANLY    = Path("logs/analytics/analytics.json")

_pcache: dict[str, float] = {}
_pcache_ts: float = 0.0
_plock = threading.Lock()
_PTTL  = 18

def _conn():
    c = sqlite3.connect(DB_PATH, timeout=5.0, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.row_factory = sqlite3.Row
    return c

def _portfolio():
    if not DB_PATH.exists():
        return {"capital":100000,"daily_pnl":0,"trade_count":0,"is_halted":False,"positions":[],"today_trades":[],"all_trades":[]}
    c = _conn()
    meta = {r["key"]:r["value"] for r in c.execute("SELECT key,value FROM meta").fetchall()}
    pos  = [dict(r) for r in c.execute("SELECT * FROM positions ORDER BY entry_time DESC").fetchall()]
    today = datetime.now(IST).strftime("%Y-%m-%d")
    all_trades = [dict(r) for r in c.execute(
        "SELECT symbol,strategy,entry_price,exit_price,qty,entry_time,exit_time,gross_pnl,brokerage,stt,exchange_charges,gst,total_charges,net_pnl,exit_reason FROM trades ORDER BY exit_time DESC LIMIT 100"
    ).fetchall()]
    c.close()
    return {"capital":round(float(meta.get("capital",100000)),2),"daily_pnl":round(float(meta.get("daily_pnl",0)),2),
            "trade_count":int(meta.get("trade_count",0)),"is_halted":meta.get("is_halted","0")=="1",
            "positions":pos,"all_trades":all_trades}

def _prices(syms):
    if not syms: return {}
    global _pcache, _pcache_ts
    with _plock:
        if time.time()-_pcache_ts < _PTTL and _pcache: return _pcache.copy()
        try:
            p = {}
            for s in syms:
                df = yf.download(s, period="1d", interval="1m", progress=False, auto_adjust=False)
                if df is not None and not df.empty: p[s] = round(float(df["Close"].iloc[-1]),2)
                time.sleep(0.15)
            _pcache = p; _pcache_ts = time.time(); return p
        except: return _pcache.copy()

def _logtail(n=150):
    fs = sorted(LOG_DIR.glob("nexus_trader_*.log"), reverse=True)
    if not fs: return ["No log file found."]
    try: return fs[0].read_text(encoding="utf-8",errors="replace").splitlines()[-n:]
    except Exception as e: return [f"Log error: {e}"]

@app.route("/api/portfolio")
def api_portfolio(): return jsonify(_portfolio())

@app.route("/api/prices")
def api_prices():
    d = _portfolio()
    syms = [p["symbol"] for p in d["positions"]]
    prices = _prices(syms)
    enriched = []
    for p in d["positions"]:
        s = p["symbol"]; cp = prices.get(s)
        up = round((cp - p["entry_price"]) * p["qty"], 2) if cp else None
        enriched.append({**p, "current_price":cp, "unrealized_pnl":up})
    return jsonify({"positions":enriched})

@app.route("/api/logs")
def api_logs(): return jsonify({"lines":_logtail(int(request.args.get("n",150)))})

@app.route("/api/analytics")
def api_analytics():
    try: return jsonify(json.loads(ANLY.read_text(encoding="utf-8"))) if ANLY.exists() else jsonify({})
    except: return jsonify({})

@app.route("/api/trades/ledger")
def api_ledger():
    if not DB_PATH.exists(): return jsonify([])
    c = _conn()
    rows = [dict(r) for r in c.execute(
        "SELECT symbol,strategy,entry_price,exit_price,qty,entry_time,exit_time,gross_pnl,brokerage,stt,exchange_charges,gst,total_charges,net_pnl,exit_reason FROM trades ORDER BY exit_time DESC LIMIT 200"
    ).fetchall()]
    c.close()
    for r in rows:
        r["amount_invested"] = round(r["entry_price"]*r["qty"],2)
        r["sale_proceeds"]   = round(r["exit_price"] *r["qty"],2)
        for k in ("gross_pnl","brokerage","stt","exchange_charges","gst","total_charges","net_pnl","amount_invested","sale_proceeds"):
            r[k] = round(r[k],2)
    return jsonify(rows)

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>nexus_trader</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{
  --bg:#080808;--s:#111;--b:#1e1e1e;--b2:#161616;
  --t:#e4e4e4;--m:#555;--m2:#333;
  --acc:#6366f1;--pos:#22c55e;--neg:#ef4444;--amb:#f59e0b;
  --pos-bg:#0d2e18;--neg-bg:#2e0d0d;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scrollbar-width:thin;scrollbar-color:var(--m2) var(--bg)}
body{background:var(--bg);color:var(--t);font-family:system-ui,-apple-system,sans-serif;font-size:13.5px;line-height:1.5}
.page{max-width:1280px;margin:0 auto;padding:22px 20px 60px}

/* header */
header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:24px;padding-bottom:16px;border-bottom:1px solid var(--b)}
.logo{font-size:1rem;font-weight:700;letter-spacing:-.3px}
.logo .und{color:var(--acc)}
.logo .sub{display:block;font-size:11px;color:var(--m);font-weight:400;margin-top:3px;letter-spacing:.02em}
.hdr-right{text-align:right;font-size:11px;color:var(--m)}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--pos);animation:pulse 2s infinite;margin-right:4px;vertical-align:middle}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
#live-lbl{color:var(--pos);font-weight:600}

/* halt */
.halt{background:#450a0a;border:1px solid #7f1d1d;color:#fca5a5;padding:9px 14px;border-radius:6px;margin-bottom:18px;font-size:12.5px;font-weight:600;display:none}
.halt.on{display:block}

/* KPI strip */
.kpi-strip{display:flex;border:1px solid var(--b);border-radius:6px;overflow:hidden;margin-bottom:18px;background:var(--b)}
.kpi-strip .gap{flex:1;background:var(--s);padding:14px 16px;border-right:1px solid var(--b)}
.kpi-strip .gap:last-child{border-right:none}
.kpi-label{font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--m);margin-bottom:5px}
.kpi-val{font-size:1.35rem;font-weight:700;color:#fff;font-variant-numeric:tabular-nums;transition:color .15s}
.kpi-val.pos{color:var(--pos)}.kpi-val.neg{color:var(--neg)}
@keyframes flash-pos{0%,100%{background:transparent}40%{background:var(--pos-bg)}}
@keyframes flash-neg{0%,100%{background:transparent}40%{background:var(--neg-bg)}}
.flash-pos{animation:flash-pos .6s ease}
.flash-neg{animation:flash-neg .6s ease}

/* card */
.card{background:var(--s);border:1px solid var(--b);border-radius:6px;padding:16px;margin-bottom:16px}
.card-head{font-size:10.5px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--m);margin-bottom:12px;display:flex;justify-content:space-between;align-items:center}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}
@media(max-width:700px){.two{grid-template-columns:1fr}}
.chart-wrap{height:200px;position:relative}

/* tables */
.scroll-x{overflow-x:auto;-webkit-overflow-scrolling:touch}
.scroll-x::-webkit-scrollbar{height:5px}
.scroll-x::-webkit-scrollbar-track{background:var(--bg)}
.scroll-x::-webkit-scrollbar-thumb{background:var(--m2);border-radius:3px}
table{width:100%;border-collapse:collapse;white-space:nowrap}
thead th{font-size:10px;font-weight:500;text-transform:uppercase;letter-spacing:.05em;color:var(--m);padding:7px 10px;text-align:left;border-bottom:1px solid var(--b);position:sticky;top:0;background:var(--s)}
td{padding:7px 10px;border-bottom:1px solid var(--b2);font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:none}
tbody tr:hover td{background:#141414}
.sym{font-weight:700;color:#fff}
.tag{font-size:11px;color:var(--m);font-weight:400}
.pos{color:var(--pos)}.neg{color:var(--neg)}.amb{color:var(--amb)}.dim{color:var(--m)}
.bold{font-weight:700}
.empty-row td{text-align:center;color:var(--m);padding:22px}

/* skeleton */
.sk-cell{height:12px;background:linear-gradient(90deg,var(--b) 25%,var(--b2) 50%,var(--b) 75%);background-size:200% 100%;animation:shimmer 1.4s infinite;border-radius:3px}
@keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}

/* group header */
.grp-head th{background:#0d0d0d;font-size:10px;text-align:center !important;padding:5px 8px;border-bottom:1px solid var(--b);border-right:1px solid var(--b)}
.grp-head th:last-child{border-right:none}
.grp-sub th{border-bottom:1px solid var(--b)}
.amb-col{background:#0f0c00}

/* filter chips */
.chips{display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap}
.chip{font-size:10px;text-transform:uppercase;letter-spacing:.04em;padding:3px 10px;border:1px solid var(--b);border-radius:20px;color:var(--m);background:transparent;cursor:pointer;font-family:inherit;transition:all .12s}
.chip:hover{border-color:var(--acc);color:var(--acc)}
.chip.on{background:var(--acc);border-color:var(--acc);color:#fff}

/* log viewer */
.log-wrap{background:#050505;border:1px solid var(--b);border-radius:6px;height:340px;overflow-y:auto;padding:10px 12px;font-family:'JetBrains Mono','Fira Code','SF Mono',monospace;font-size:11.5px;line-height:1.7}
.log-wrap::-webkit-scrollbar{width:6px}
.log-wrap::-webkit-scrollbar-track{background:#0a0a0a}
.log-wrap::-webkit-scrollbar-thumb{background:var(--m2);border-radius:3px}
.log-line{white-space:pre-wrap;word-break:break-all}
.log-t{color:#444}
.log-e{color:#ef4444}.log-w{color:#f59e0b}.log-b{color:#22c55e}.log-s{color:#fb923c}.log-m{color:#4a4a4a}
.auto-btn{font-size:10px;padding:3px 10px;border:1px solid var(--b);border-radius:20px;color:var(--m);background:transparent;cursor:pointer;font-family:inherit;margin-left:auto}
.auto-btn.on{border-color:var(--pos);color:var(--pos)}

/* footer */
footer{text-align:center;font-size:11px;color:var(--m);margin-top:32px;padding-top:14px;border-top:1px solid var(--b);letter-spacing:.04em}
</style>
</head>
<body>
<div class="page">

<header>
  <div class="logo">
    nexus<span class="und">_</span>trader
    <span class="sub">NSE paper trading &nbsp;|&nbsp; Rs1,00,000 capital &nbsp;|&nbsp; Nifty 100 universe</span>
  </div>
  <div class="hdr-right">
    <span class="dot"></span><span id="live-lbl">connecting</span><br>
    <span id="last-upd" style="font-size:10.5px"></span>
  </div>
</header>

<div id="halt-bar" class="halt">TRADING HALTED &mdash; Daily loss limit reached</div>

<!-- 01 KPI strip -->
<div class="kpi-strip">
  <div class="gap"><div class="kpi-label">Capital</div><div class="kpi-val" id="k-cap">--</div></div>
  <div class="gap"><div class="kpi-label">Daily P&amp;L</div><div class="kpi-val" id="k-dpnl">--</div></div>
  <div class="gap"><div class="kpi-label">Trades today</div><div class="kpi-val" id="k-tr">--</div></div>
  <div class="gap"><div class="kpi-label">Open positions</div><div class="kpi-val" id="k-open">--</div></div>
  <div class="gap"><div class="kpi-label">All-time P&amp;L</div><div class="kpi-val" id="k-apnl">--</div></div>
  <div class="gap"><div class="kpi-label">Win rate</div><div class="kpi-val" id="k-wr">--</div></div>
  <div class="gap"><div class="kpi-label">Profit factor</div><div class="kpi-val" id="k-pf">--</div></div>
  <div class="gap"><div class="kpi-label">Avg R:R</div><div class="kpi-val" id="k-rr">--</div></div>
</div>

<!-- 02 Live positions -->
<div class="card">
  <div class="card-head">Live Positions <span id="pos-ts" class="dim" style="font-size:10px;font-weight:400;text-transform:none"></span></div>
  <div class="scroll-x">
    <table id="pos-tbl">
      <thead><tr><th>Symbol</th><th>Strategy</th><th>Entry</th><th>Current</th><th>Unrealized P&amp;L</th><th>Stop Loss</th><th>Target</th><th>Qty</th></tr></thead>
      <tbody id="pos-body">
        <tr><td><div class="sk-cell"></div></td><td><div class="sk-cell"></div></td><td><div class="sk-cell"></div></td><td><div class="sk-cell"></div></td><td><div class="sk-cell"></div></td><td><div class="sk-cell"></div></td><td><div class="sk-cell"></div></td><td><div class="sk-cell"></div></td></tr>
        <tr><td><div class="sk-cell"></div></td><td><div class="sk-cell"></div></td><td><div class="sk-cell"></div></td><td><div class="sk-cell"></div></td><td><div class="sk-cell"></div></td><td><div class="sk-cell"></div></td><td><div class="sk-cell"></div></td><td><div class="sk-cell"></div></td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- 03 Charts -->
<div class="two">
  <div class="card"><div class="card-head">Equity Curve</div><div class="chart-wrap"><canvas id="eq-chart"></canvas></div></div>
  <div class="card"><div class="card-head">Daily P&amp;L</div><div class="chart-wrap"><canvas id="dl-chart"></canvas></div></div>
</div>

<!-- 04 Trade history -->
<div class="card">
  <div class="card-head">Trade History <span class="dim" style="font-weight:400;text-transform:none;font-size:11px">last 50</span></div>
  <div class="scroll-x">
    <table><thead><tr><th>Time</th><th>Symbol</th><th>Strategy</th><th>Entry</th><th>Exit</th><th>Reason</th><th>Net P&amp;L</th></tr></thead>
    <tbody id="hist-body"><tr class="empty-row"><td colspan="7">Loading...</td></tr></tbody></table>
  </div>
</div>

<!-- 05 Analytics row -->
<div class="two">
  <div class="card"><div class="card-head">Strategy Breakdown</div><div class="chart-wrap" style="height:160px"><canvas id="st-chart"></canvas></div></div>
  <div class="card">
    <div class="card-head">Exit Reasons</div>
    <div class="scroll-x"><table><thead><tr><th>Reason</th><th>Count</th><th>Net P&amp;L</th></tr></thead><tbody id="er-body"><tr class="empty-row"><td colspan="3">No data</td></tr></tbody></table></div>
  </div>
</div>

<!-- 06 Trade ledger — Option B: two-tier grouped header -->
<div class="card">
  <div class="card-head">
    Trade Ledger
    <div class="chips" style="margin:0">
      <button class="chip on" onclick="setLedger('all',this)">All</button>
      <button class="chip" onclick="setLedger('win',this)">Winners</button>
      <button class="chip" onclick="setLedger('loss',this)">Losers</button>
    </div>
  </div>
  <div class="scroll-x">
    <table id="ledger-tbl" style="min-width:1100px">
      <thead>
        <tr class="grp-head grp-sub">
          <th colspan="3">Trade</th>
          <th colspan="5">Money</th>
          <th colspan="5" style="color:var(--amb)">Charges</th>
          <th colspan="2">Result</th>
        </tr>
        <tr class="grp-sub">
          <th>Time</th><th>Symbol</th><th>Strategy / Qty</th>
          <th>Bought at</th><th>Sold at</th><th>Invested</th><th>Proceeds</th><th>Gross P&amp;L</th>
          <th style="color:var(--amb)">Broker</th><th style="color:var(--amb)">STT</th><th style="color:var(--amb)">Exch</th><th style="color:var(--amb)">GST</th><th style="color:var(--amb)">Total</th>
          <th>Net P&amp;L</th><th>Exit</th>
        </tr>
      </thead>
      <tbody id="ledger-body"><tr class="empty-row"><td colspan="15">No trades yet</td></tr></tbody>
    </table>
  </div>
</div>

<!-- 07 Log viewer — Option A: raw terminal -->
<div class="card">
  <div class="card-head">
    Live Log Stream
    <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
      <div class="chips" style="margin:0">
        <button class="chip on" onclick="setLog('all',this)">All</button>
        <button class="chip" onclick="setLog('err',this)">Errors</button>
        <button class="chip" onclick="setLog('buy',this)">Buys</button>
        <button class="chip" onclick="setLog('sell',this)">Sells</button>
        <button class="chip" onclick="setLog('warn',this)">Warnings</button>
      </div>
      <button class="auto-btn on" id="as-btn" onclick="toggleAS()">Auto-scroll ON</button>
    </div>
  </div>
  <div class="log-wrap" id="log-box"></div>
</div>

<footer>nexus_trader &nbsp;&middot;&nbsp; paper trading &nbsp;&middot;&nbsp; yfinance 15-min delayed &nbsp;&middot;&nbsp; no real money</footer>
</div><!-- .page -->

<script>
/* ---------- helpers ---------- */
const $ = id => document.getElementById(id);
const C = Chart.defaults;
C.color = '#555'; C.borderColor = '#1e1e1e';
C.font.family = 'system-ui,-apple-system,sans-serif';

const AXES = {
  x:{grid:{color:'#161616'},ticks:{color:'#555',maxTicksLimit:7,font:{size:10}}},
  y:{grid:{color:'#161616'},ticks:{color:'#555',font:{size:10}}}
};

function rs(v){ return 'Rs' + Number(v).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2}); }
function rss(v){ return (v>=0?'Rs+':'Rs−') + Math.abs(v).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2}); }
function cls(v){ return v>0?'pos':v<0?'neg':''; }

let _prev = {};
function flashSet(id, val, isNum){
  const el = $(id); if(!el) return;
  el.textContent = val;
  if(isNum){
    const prev = _prev[id];
    if(prev !== undefined && prev !== val){
      el.classList.remove('flash-pos','flash-neg');
      void el.offsetWidth;
      el.classList.add(Number(val.replace(/[^0-9.\-]/g,'')) > Number(prev.replace(/[^0-9.\-]/g,'')) ? 'flash-pos' : 'flash-neg');
    }
    _prev[id] = val;
  }
}

/* ---------- charts ---------- */
let eqC, dlC, stC;

function initCharts(){
  eqC = new Chart('eq-chart',{type:'line',data:{labels:[],datasets:[{label:'Capital',data:[],borderColor:'#6366f1',backgroundColor:'rgba(99,102,241,0.07)',fill:true,tension:0.4,pointRadius:0,borderWidth:2}]},options:{maintainAspectRatio:false,plugins:{legend:{display:false}},scales:AXES}});
  dlC = new Chart('dl-chart',{type:'bar',data:{labels:[],datasets:[{label:'P&L',data:[],backgroundColor:[],borderRadius:3,borderSkipped:false}]},options:{maintainAspectRatio:false,plugins:{legend:{display:false}},scales:AXES}});
  stC = new Chart('st-chart',{type:'bar',data:{labels:[],datasets:[{label:'Wins',data:[],backgroundColor:'#22c55e',borderRadius:3},{label:'Losses',data:[],backgroundColor:'#ef4444',borderRadius:3}]},options:{maintainAspectRatio:false,scales:AXES,plugins:{legend:{labels:{color:'#555',boxWidth:10,font:{size:10}}}}}});
}
initCharts();

/* ---------- portfolio poll (5s) ---------- */
async function pollPortfolio(){
  try{
    const d = await fetch('/api/portfolio').then(r=>r.json());
    $('live-lbl').textContent = 'live';
    $('last-upd').textContent = 'updated '+new Date().toLocaleTimeString();
    $('halt-bar').classList.toggle('on', d.is_halted);

    flashSet('k-cap',  rs(d.capital), true);
    const dpEl = $('k-dpnl');
    dpEl.textContent = rss(d.daily_pnl);
    dpEl.className = 'kpi-val ' + cls(d.daily_pnl);
    flashSet('k-tr',   String(d.trade_count), true);
    flashSet('k-open', String(d.positions.length), true);

    /* trade history */
    const tb = $('hist-body');
    if(!d.all_trades.length){
      tb.innerHTML='<tr class="empty-row"><td colspan="7">No trades yet</td></tr>';
    } else {
      tb.innerHTML = d.all_trades.slice(0,50).map(t=>{
        const c=cls(t.net_pnl);
        return `<tr>
          <td class="dim">${(t.exit_time||'').slice(11,16)}</td>
          <td><span class="sym">${t.symbol}</span></td>
          <td><span class="tag">${t.strategy||''}</span></td>
          <td>${rs(t.entry_price)}</td>
          <td>${rs(t.exit_price)}</td>
          <td class="dim">${t.exit_reason||''}</td>
          <td class="${c} bold">${rss(t.net_pnl)}</td>
        </tr>`;
      }).join('');
    }

    /* charts from trade data */
    let cap = 100000;
    const eqL=[],eqV=[],dlMap={};
    eqL.push('Start'); eqV.push(cap);
    for(const t of [...d.all_trades].reverse()){
      cap+=t.net_pnl; eqL.push(t.symbol); eqV.push(+cap.toFixed(2));
      const dk=(t.exit_time||'').slice(0,10);
      dlMap[dk]=(dlMap[dk]||0)+t.net_pnl;
    }
    const dlL=Object.keys(dlMap).sort(), dlV=dlL.map(k=>+dlMap[k].toFixed(2));
    eqC.data.labels=eqL; eqC.data.datasets[0].data=eqV; eqC.update('none');
    dlC.data.labels=dlL; dlC.data.datasets[0].data=dlV;
    dlC.data.datasets[0].backgroundColor=dlV.map(v=>v>=0?'#22c55e':'#ef4444'); dlC.update('none');

  }catch(e){$('live-lbl').textContent='error';}
}

/* ---------- prices poll (20s) ---------- */
async function pollPrices(){
  try{
    const d = await fetch('/api/prices').then(r=>r.json());
    const pb = $('pos-body');
    $('pos-ts').textContent = 'prices at '+new Date().toLocaleTimeString();
    if(!d.positions.length){
      pb.innerHTML='<tr class="empty-row"><td colspan="8">No open positions</td></tr>'; return;
    }
    pb.innerHTML = d.positions.map(p=>{
      const cp=p.current_price, up=p.unrealized_pnl;
      return `<tr>
        <td><span class="sym">${p.symbol}</span></td>
        <td><span class="tag">${p.strategy||''}</span></td>
        <td>${rs(p.entry_price)}</td>
        <td>${cp!=null?`<b>${rs(cp)}</b>`:'<span class="dim">--</span>'}</td>
        <td class="${cls(up||0)}">${up!=null?rss(up):'--'}</td>
        <td class="neg">${rs(p.stop_loss||0)}</td>
        <td class="pos">${rs(p.target||0)}</td>
        <td>${p.qty}</td>
      </tr>`;
    }).join('');
  }catch(e){}
}

/* ---------- analytics poll (30s) ---------- */
async function pollAnalytics(){
  try{
    const a = await fetch('/api/analytics').then(r=>r.json());
    if(!a.total_trades) return;
    const totPnl=a.total_net_pnl||0, wins=a.winners||0, tot=a.total_trades||1;
    const apEl=$('k-apnl'); apEl.textContent=rss(totPnl); apEl.className='kpi-val '+cls(totPnl);
    flashSet('k-wr',  (wins/tot*100).toFixed(1)+'%', true);
    flashSet('k-pf',  '0.00', false); /* calc below */
    flashSet('k-rr',  (a.avg_realized_rr||0).toFixed(2), true);

    /* strategy chart */
    const bs=a.by_strategy||{}, sL=Object.keys(bs);
    stC.data.labels=sL;
    stC.data.datasets[0].data=sL.map(k=>bs[k].winners||0);
    stC.data.datasets[1].data=sL.map(k=>(bs[k].trades||0)-(bs[k].winners||0));
    stC.update('none');

    /* exit reason table */
    const er=a.by_exit_reason||{};
    const erb=$('er-body');
    const erRows=Object.entries(er).map(([k,v])=>
      `<tr><td class="dim">${k}</td><td>${v.count}</td><td class="${cls(v.net_pnl)}">${rss(v.net_pnl)}</td></tr>`
    ).join('');
    erb.innerHTML = erRows || '<tr class="empty-row"><td colspan="3">No data yet</td></tr>';
  }catch(e){}
}

/* ---------- ledger ---------- */
let _ledger=[], _ledgerF='all';
function setLedger(f,btn){
  _ledgerF=f;
  document.querySelectorAll('[onclick^="setLedger"]').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on'); renderLedger();
}
function renderLedger(){
  const rows = _ledgerF==='all'?_ledger:_ledgerF==='win'?_ledger.filter(r=>r.net_pnl>0):_ledger.filter(r=>r.net_pnl<=0);
  const tb=$('ledger-body');
  if(!rows.length){tb.innerHTML='<tr class="empty-row"><td colspan="15">No trades yet</td></tr>';return;}
  tb.innerHTML=rows.map(r=>{
    const c=cls(r.net_pnl);
    return `<tr>
      <td class="dim">${(r.exit_time||'').slice(0,16)}</td>
      <td><span class="sym">${r.symbol}</span></td>
      <td><span class="tag">${r.strategy||''}</span> &nbsp;<span class="dim">x${r.qty}</span></td>
      <td>${rs(r.entry_price)}</td>
      <td>${rs(r.exit_price)}</td>
      <td>${rs(r.amount_invested)}</td>
      <td>${rs(r.sale_proceeds)}</td>
      <td class="${cls(r.gross_pnl)}">${rss(r.gross_pnl)}</td>
      <td class="amb">${rs(r.brokerage)}</td>
      <td class="amb">${rs(r.stt)}</td>
      <td class="amb">${rs(r.exchange_charges)}</td>
      <td class="amb">${rs(r.gst)}</td>
      <td class="amb bold">${rs(r.total_charges)}</td>
      <td class="${c} bold">${rss(r.net_pnl)}</td>
      <td class="dim">${r.exit_reason||''}</td>
    </tr>`;
  }).join('');
}
async function pollLedger(){
  try{
    _ledger=await fetch('/api/trades/ledger').then(r=>r.json());
    renderLedger();
  }catch(e){}
}

/* ---------- log viewer — Option A: raw terminal ---------- */
let _logLines=[], _logFilter='all', _autoScroll=true;
function setLog(f,btn){
  _logFilter=f;
  document.querySelectorAll('[onclick^="setLog"]').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on'); renderLog();
}
function toggleAS(){
  _autoScroll=!_autoScroll;
  const b=$('as-btn');
  b.textContent='Auto-scroll '+(_autoScroll?'ON':'OFF');
  b.classList.toggle('on',_autoScroll);
}
function lineClass(l){
  const lo=l.toLowerCase();
  if(/error|exception|traceback/.test(lo)) return 'log-e';
  if(/warning|warn/.test(lo)) return 'log-w';
  if(/\bbuy\b|bought/.test(lo)) return 'log-b';
  if(/\bsell\b|squareoff|sold/.test(lo)) return 'log-s';
  return 'log-m';
}
function renderLog(){
  const box=$('log-box');
  const src=_logFilter==='all'?_logLines:_logLines.filter(l=>lineClass(l).endsWith(_logFilter[0]==='e'?'-e':_logFilter[0]==='w'?'-w':_logFilter==='buy'?'-b':_logFilter==='sell'?'-s':'-m'));
  box.innerHTML=src.map(l=>{
    const esc=l.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    /* split timestamp from rest */
    const m=esc.match(/^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}|\d{2}:\d{2}:\d{2})/);
    if(m) return `<div class="log-line ${lineClass(l)}"><span class="log-t">${m[0]}</span> ${esc.slice(m[0].length)}</div>`;
    return `<div class="log-line ${lineClass(l)}">${esc}</div>`;
  }).join('');
  if(_autoScroll) box.scrollTop=box.scrollHeight;
}
const logBox=$('log-box');
logBox.addEventListener('scroll',()=>{
  const atBottom=logBox.scrollHeight-logBox.scrollTop-logBox.clientHeight < 30;
  if(!atBottom && _autoScroll){ _autoScroll=false; const b=$('as-btn'); b.textContent='Auto-scroll OFF'; b.classList.remove('on'); }
});
async function pollLogs(){
  try{
    const d=await fetch('/api/logs?n=150').then(r=>r.json());
    _logLines=d.lines||[]; renderLog();
  }catch(e){}
}

/* ---------- boot ---------- */
pollPortfolio(); pollPrices(); pollAnalytics(); pollLogs(); pollLedger();
setInterval(pollPortfolio,  5000);
setInterval(pollPrices,    20000);
setInterval(pollAnalytics, 30000);
setInterval(pollLogs,       8000);
setInterval(pollLedger,    30000);
</script>
</body>
</html>"""

@app.route("/")
def index(): return render_template_string(HTML)

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv)>1 else 8080
    print(f"nexus_trader dashboard -> http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)
