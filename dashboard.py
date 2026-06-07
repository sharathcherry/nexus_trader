"""
dashboard.py -- nexus_trader HTML dashboard generator.
Reads portfolio.db and writes a self-contained HTML report to logs/dashboard.html and logs/index.html.
Usage: python dashboard.py

Design: Matches the nexus_trader wireframe page-map --
  Single vertical scroll page with tab navigation for
  starred deep-dive sections (Trade Ledger, Log Viewer).
  Colour system: Purple=brand, Green=profit/buys, Red=loss/sells, Amber=charges.
"""
from __future__ import annotations

import argparse
import html
import json
import sqlite3
import webbrowser
from datetime import datetime
from pathlib import Path

import pytz

DB_PATH  = Path("execution/portfolio.db")
PERF_DIR = Path("logs/performance")
LOG_PATH = Path("logs/nexus_trader.log")
OUT_PATH = Path("logs/dashboard.html")
IDX_PATH = Path("logs/index.html")
IST      = pytz.timezone("Asia/Kolkata")


def _esc(val) -> str:
    return html.escape(str(val)) if val is not None else ""

def _load_trades() -> list[dict]:
    if not DB_PATH.exists(): return []
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM trades ORDER BY exit_time DESC").fetchall()
    conn.close(); return [dict(r) for r in rows]

def _load_positions() -> list[dict]:
    if not DB_PATH.exists(): return []
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM positions ORDER BY entry_time DESC").fetchall()
    conn.close(); return [dict(r) for r in rows]

def _load_meta() -> dict:
    if not DB_PATH.exists(): return {}
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT key, value FROM meta").fetchall()
    conn.close(); return {k: v for k, v in rows}

def _load_latest_review() -> dict | None:
    if not PERF_DIR.exists(): return None
    files = sorted(PERF_DIR.glob("review_*.json"), reverse=True)
    for f in files:
        if "partial" in f.name or "failed" in f.name: continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            dp = f.name.replace("review_","").replace(".json","")
            data["review_date"] = f"{dp[:4]}-{dp[4:6]}-{dp[6:]}" if len(dp)==8 else dp
            if "summary" in data and "overall_assessment" not in data:
                data["overall_assessment"] = data["summary"]
            if "recommendations" not in data:
                recs = []
                for a in data.get("parameter_adjustments", []):
                    recs.append(f"{a.get('param_name')}: {a.get('current_value')} to {a.get('suggested_value')} -- {a.get('reason')}")
                w = data.get("tomorrow_watch", [])
                if w: recs.append(f"Watch tomorrow: {', '.join(w)}")
                data["recommendations"] = recs
            return data
        except Exception: continue
    return None

def _load_log_lines(n: int = 80) -> list[str]:
    if not LOG_PATH.exists(): return []
    try:
        text = LOG_PATH.read_text(encoding="utf-8", errors="replace")
        lines = text.strip().splitlines()
        return lines[-n:]
    except Exception:
        return []

def _stats(trades):
    if not trades:
        return {"total":0,"wins":0,"losses":0,"win_rate":0.0,"net_pnl":0.0,
                "profit_factor":0.0,"best":0.0,"worst":0.0,"avg_rr":0.0}
    pnls = [t["net_pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]; losses = [p for p in pnls if p <= 0]
    gw = sum(wins); gl = abs(sum(losses))
    avg_win = (gw / len(wins)) if wins else 0
    avg_loss = (gl / len(losses)) if losses else 0
    avg_rr = (avg_win / avg_loss) if avg_loss else 0
    return {"total":len(trades),"wins":len(wins),"losses":len(losses),
            "win_rate":len(wins)/len(trades)*100,"net_pnl":sum(pnls),
            "profit_factor":gw/gl if gl else 0.0,"best":max(pnls),"worst":min(pnls),
            "avg_rr": round(avg_rr, 2)}

def _daily_pnl(trades):
    today = datetime.now(IST).strftime("%Y-%m-%d")
    return sum(t["net_pnl"] for t in trades if t["exit_time"][:10] == today)

def _equity(trades, cap):
    curve = [{"l":"Start","v":cap}]
    for t in reversed(trades):
        cap += t["net_pnl"]
        curve.append({"l":f"{t['symbol']} {t['exit_time'][:10]}","v":round(cap,2)})
    return curve

def _daily(trades):
    d = {}
    for t in trades:
        k = t["exit_time"][:10]; d[k] = d.get(k,0.0) + t["net_pnl"]
    return [{"date":k,"pnl":round(v,2)} for k,v in sorted(d.items())]

def _strategy(trades):
    d = {}
    for t in trades:
        s = t.get("strategy","UNKNOWN")
        if s not in d: d[s] = {"wins":0,"losses":0,"pnl":0.0}
        if t["net_pnl"] > 0: d[s]["wins"] += 1
        else: d[s]["losses"] += 1
        d[s]["pnl"] += t["net_pnl"]
    return [{"strategy":k,**v} for k,v in d.items()]

def _exit_reasons(trades):
    d = {}
    for t in trades:
        r = t.get("exit_reason","unknown")
        if r not in d: d[r] = {"count":0,"pnl":0.0}
        d[r]["count"] += 1
        d[r]["pnl"] += t["net_pnl"]
    return [{"reason":k,**v} for k,v in d.items()]

def generate_html(starting_capital: float = 100_000.0) -> str:
    trades    = _load_trades()
    positions = _load_positions()
    meta      = _load_meta()
    review    = _load_latest_review()
    st        = _stats(trades)
    equity    = _equity(trades, starting_capital)
    daily     = _daily(trades)
    strat     = _strategy(trades)
    exits     = _exit_reasons(trades)
    log_lines = _load_log_lines(80)
    capital   = float(meta.get("capital", starting_capital))
    today_pnl = _daily_pnl(trades)
    gen_at    = datetime.now(IST).strftime("%H:%M:%S")
    gen_full  = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")

    eq_labels = json.dumps([e["l"] for e in equity])
    eq_values = json.dumps([e["v"] for e in equity])
    dl_labels = json.dumps([d["date"] for d in daily])
    dl_values = json.dumps([d["pnl"]  for d in daily])
    dl_colors = json.dumps(["#22c55e" if d["pnl"]>=0 else "#ef4444" for d in daily])
    st_labels = json.dumps([s["strategy"] for s in strat])
    st_wins   = json.dumps([s["wins"]     for s in strat])
    st_losses = json.dumps([s["losses"]   for s in strat])

    dpnl_cls = "pos" if today_pnl >= 0 else "neg"
    alltime_cls = "pos" if st["net_pnl"] >= 0 else "neg"
    pf_cls   = "pos" if st["profit_factor"] >= 1 else "neg"
    is_halt  = meta.get("is_halted","0") == "1"
    halt_bar = '<div class="halt-banner">⚠ TRADING HALTED — Daily loss limit reached</div>' if is_halt else ""

    # ── Positions rows (02) ──
    def pos_rows():
        if not positions:
            return '<tr><td colspan="8" class="empty">No open positions</td></tr>'
        r = ""
        for p in positions:
            r += (f'<tr>'
                  f'<td><b>{_esc(p["symbol"])}</b></td>'
                  f'<td class="dim">{_esc(p.get("strategy",""))}</td>'
                  f'<td>{p["entry_price"]:,.0f}</td>'
                  f'<td><b>—</b></td>'
                  f'<td class="dim">—</td>'
                  f'<td class="neg">{p.get("stop_loss",0):,.0f}</td>'
                  f'<td class="pos">{p.get("target",0):,.0f}</td>'
                  f'<td>{p.get("qty",0)}</td>'
                  f'</tr>')
        return r

    # ── Trade history rows (04) — simple 7-col ──
    def trade_rows():
        if not trades:
            return '<tr><td colspan="7" class="empty">No trades yet</td></tr>'
        r = ""
        for t in trades[:50]:
            pnl = t["net_pnl"]; cls = "pos" if pnl >= 0 else "neg"
            time_str = t.get("exit_time","")[:5] if t.get("exit_time") else ""
            r += (f'<tr>'
                  f'<td class="dim">{time_str}</td>'
                  f'<td><b>{_esc(t["symbol"])}</b></td>'
                  f'<td class="dim">{_esc(t.get("strategy",""))}</td>'
                  f'<td>{t["entry_price"]:,.0f}</td>'
                  f'<td>{t["exit_price"]:,.0f}</td>'
                  f'<td class="dim">{_esc(t.get("exit_reason",""))}</td>'
                  f'<td class="{cls}"><b>{"+" if pnl>=0 else ""}{pnl:,.0f}</b></td>'
                  f'</tr>')
        return r

    # ── Exit reasons rows (05) ──
    def exit_rows():
        if not exits:
            return '<tr><td colspan="3" class="empty">No data</td></tr>'
        r = ""
        for e in exits:
            cls = "pos" if e["pnl"] >= 0 else "neg"
            r += (f'<tr><td>{_esc(e["reason"])}</td>'
                  f'<td><b>{e["count"]}</b></td>'
                  f'<td class="{cls}">{"+" if e["pnl"]>=0 else ""}{e["pnl"]:+,.0f}</td></tr>')
        return r

    # ── Full ledger rows (16-col, for TAB) ──
    def ledger_rows():
        if not trades:
            return '<tr><td colspan="16" class="empty">No trades yet</td></tr>'
        r = ""
        for t in trades[:50]:
            pnl = t["net_pnl"]; cls = "pos" if pnl >= 0 else "neg"
            entry_p = t.get("entry_price", 0); exit_p = t.get("exit_price", 0); qty = t.get("qty", 0)
            invested = round(entry_p * qty, 2); proceeds = round(exit_p * qty, 2)
            gross = round(proceeds - invested, 2); gross_cls = "pos" if gross >= 0 else "neg"
            brk = t.get("brokerage", round(max(invested, proceeds) * 0.0003, 2))
            stt = t.get("stt", round(proceeds * 0.00025, 2))
            exch = t.get("exchange_charges", round(max(invested, proceeds) * 0.0000345, 2))
            gst = t.get("gst", round(brk * 0.18, 2))
            charges = round(brk + stt + exch + gst, 2)
            time_str = t.get("exit_time","")[:5] if t.get("exit_time") else ""
            reason = _esc(t.get("exit_reason",""))
            r += (f'<tr data-pnl="{pnl}">'
                  f'<td class="dim">{time_str}</td>'
                  f'<td><b>{_esc(t["symbol"])}</b></td>'
                  f'<td class="dim">{_esc(t.get("strategy",""))}</td>'
                  f'<td>{qty}</td>'
                  f'<td>{entry_p:,.0f}</td><td>{exit_p:,.0f}</td>'
                  f'<td>{invested:,.0f}</td><td>{proceeds:,.0f}</td>'
                  f'<td class="{gross_cls}">{"+" if gross>=0 else ""}{gross:,.0f}</td>'
                  f'<td class="amber">{brk:,.0f}</td>'
                  f'<td class="amber">{stt:,.0f}</td>'
                  f'<td class="amber">{exch:,.0f}</td>'
                  f'<td class="amber">{gst:,.0f}</td>'
                  f'<td class="amber">{charges:,.0f}</td>'
                  f'<td class="{cls}"><b>{"+" if pnl>=0 else ""}{pnl:,.0f}</b></td>'
                  f'<td class="dim">{reason}</td></tr>')
        return r

    log_json = json.dumps(log_lines)

    # ── Review block ──
    review_block = ""
    if review:
        recs = "".join(f"<li>{_esc(r)}</li>" for r in review.get("recommendations",[])[:5])
        review_block = f"""
<section class="card">
  <div class="card-head">AI Review <span class="dim">{_esc(review.get('review_date',''))}</span></div>
  <p class="review-summary">{_esc(review.get('overall_assessment',''))}</p>
  <ul class="recs">{recs}</ul>
</section>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>nexus_trader</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
/* ═══════════════════════════════════════════
   COLOUR SYSTEM  (from wireframe spec)
   Purple — brand, equity line, active state
   Green  — profit / buys
   Red    — loss / sells / halt
   Amber  — charges & warnings
   ═══════════════════════════════════════════ */
:root {{
  --bg:       #0a0a0a;
  --surface:  #111111;
  --surface2: #161616;
  --border:   #1e1e1e;
  --border2:  #2a2a2a;
  --text:     #e4e4e4;
  --muted:    #777;
  --dim:      #555;
  --purple:   #6366f1;
  --purple2:  #818cf8;
  --purple-bg:rgba(99,102,241,0.08);
  --green:    #22c55e;
  --green-bg: rgba(34,197,94,0.08);
  --red:      #ef4444;
  --red-bg:   rgba(239,68,68,0.08);
  --amber:    #d97706;
  --amber-bg: rgba(217,119,6,0.08);
  --mono:     'JetBrains Mono', 'Cascadia Code', 'Fira Code', monospace;
  --sans:     'Inter', system-ui, -apple-system, sans-serif;
  --radius:   8px;
}}
* {{ box-sizing:border-box; margin:0; padding:0 }}
body {{ background:var(--bg); color:var(--text); font-family:var(--sans); font-size:14px; line-height:1.5 }}
a {{ color:inherit; text-decoration:none }}
::selection {{ background:var(--purple); color:#fff }}

/* ──── LAYOUT ──── */
.page {{ max-width:1280px; margin:0 auto; padding:24px 24px 40px }}

/* ──── 00 · HEADER ──── */
header {{ display:flex; justify-content:space-between; align-items:center; background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:16px 24px; margin-bottom:16px }}
.logo {{ font-family:var(--mono); font-size:1.2rem; font-weight:700; color:#fff }}
.logo span {{ color:var(--purple) }}
.sub {{ font-size:12px; color:var(--muted); margin-top:2px; font-family:var(--mono) }}
.live-badge {{ display:flex; align-items:center; gap:8px; font-family:var(--mono); font-size:12px; color:var(--muted) }}
.live-dot {{ width:8px; height:8px; border-radius:50%; background:var(--green); animation:pulse 2s infinite }}
@keyframes pulse {{ 0%,100%{{ opacity:1 }} 50%{{ opacity:.3 }} }}

/* ──── HALT BANNER ──── */
.halt-banner {{ background:rgba(127,29,29,0.5); border:1px solid #7f1d1d; color:#fca5a5; padding:10px 16px; border-radius:var(--radius); margin-bottom:16px; font-weight:600; font-size:13px; font-family:var(--mono) }}

/* ──── TAB NAV ──── */
.tabs {{ display:flex; gap:8px; margin-bottom:20px; flex-wrap:wrap }}
.tab {{ font-family:var(--mono); font-size:13px; padding:8px 18px; border:1px solid var(--border2); border-radius:6px; cursor:pointer; transition:all .15s; color:var(--muted); background:transparent; user-select:none }}
.tab:hover {{ border-color:var(--text); color:var(--text) }}
.tab.active {{ background:var(--purple); color:#fff; border-color:var(--purple); font-weight:600 }}
.tab .star {{ color:var(--purple2); margin-right:4px }}
.tab.active .star {{ color:#fff }}

/* ──── SECTION LABEL ──── */
.section-label {{ font-family:var(--mono); font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.1em; color:var(--dim); margin-bottom:8px; display:flex; justify-content:space-between; align-items:center }}
.section-label .right {{ font-size:10px; color:var(--dim) }}
.tab-badge {{ display:inline-block; font-family:var(--mono); font-size:10px; font-weight:700; padding:3px 10px; border-radius:4px; background:var(--purple); color:#fff; letter-spacing:.06em; cursor:pointer; text-decoration:none }}
.tab-badge:hover {{ background:var(--purple2) }}

/* ──── PANELS ──── */
.panel {{ display:none }}
.panel.active {{ display:block }}

/* ──── 01 · KPI STRIP — 8 connected tiles ──── */
.kpi-strip {{ display:grid; grid-template-columns:repeat(8, 1fr); gap:1px; background:var(--border); border:1px solid var(--border); border-radius:var(--radius); overflow:hidden; margin-bottom:20px }}
.kpi {{ background:var(--surface); padding:14px 16px }}
.kpi .label {{ font-size:10px; text-transform:uppercase; letter-spacing:.08em; color:var(--dim); font-family:var(--mono); margin-bottom:4px; white-space:nowrap }}
.kpi .value {{ font-size:1.15rem; font-weight:700; font-family:var(--mono); color:#fff; white-space:nowrap }}
.kpi .value.pos {{ color:var(--green) }}
.kpi .value.neg {{ color:var(--red) }}

/* ──── CARDS ──── */
.card {{ background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:20px; margin-bottom:20px }}
.card-head {{ font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.08em; color:var(--dim); font-family:var(--mono); margin-bottom:14px; display:flex; justify-content:space-between; align-items:center }}
.two-col {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:20px }}
@media(max-width:768px){{ .two-col{{ grid-template-columns:1fr }} }}
.chart-wrap {{ height:200px; position:relative }}

/* ──── FILTER TABS ──── */
.filters {{ display:flex; gap:6px; margin-bottom:14px }}
.fbtn {{ font-family:var(--mono); font-size:11px; padding:4px 12px; border:1px solid var(--border2); border-radius:4px; cursor:pointer; color:var(--muted); background:transparent; transition:all .12s }}
.fbtn:hover {{ border-color:var(--text); color:var(--text) }}
.fbtn.active {{ background:var(--text); color:var(--bg); border-color:var(--text) }}

/* ──── TABLES ──── */
.tbl-wrap {{ overflow-x:auto }}
.tbl-wrap::-webkit-scrollbar {{ height:6px }}
.tbl-wrap::-webkit-scrollbar-track {{ background:var(--surface2) }}
.tbl-wrap::-webkit-scrollbar-thumb {{ background:var(--border2); border-radius:3px }}
table {{ width:100%; border-collapse:collapse; font-family:var(--mono); font-size:12px }}
th {{ font-size:10px; font-weight:500; text-transform:uppercase; letter-spacing:.06em; color:var(--dim); padding:8px 10px; text-align:left; border-bottom:1px solid var(--border); white-space:nowrap }}
td {{ padding:8px 10px; border-bottom:1px solid #161616; vertical-align:middle; white-space:nowrap }}
tr:last-child td {{ border-bottom:none }}
tr:hover td {{ background:var(--surface2) }}
.dim {{ color:var(--muted) }}
.pos {{ color:var(--green) }}
.neg {{ color:var(--red) }}
.amber {{ color:var(--amber) }}
.empty {{ color:var(--dim); text-align:center; padding:32px; font-style:italic }}

/* ──── GROUPED HEADERS (ledger) ──── */
.group-header th {{ text-align:center; font-size:10px; font-weight:600; letter-spacing:.1em; border-bottom:2px solid var(--border2); padding:6px 10px }}
.group-header .g-trade {{ background:var(--purple-bg); color:var(--purple2) }}
.group-header .g-money {{ background:var(--green-bg); color:var(--green) }}
.group-header .g-charges {{ background:var(--amber-bg); color:var(--amber) }}
.group-header .g-result {{ background:rgba(255,255,255,0.03); color:var(--text) }}

/* ──── 07 · LOG VIEWER ──── */
.log-terminal {{ background:#0b0b0b; border:1px solid var(--border); border-radius:var(--radius); height:340px; overflow-y:auto; padding:16px 18px; font-family:var(--mono); font-size:12px; line-height:1.7 }}
.log-terminal::-webkit-scrollbar {{ width:6px }}
.log-terminal::-webkit-scrollbar-track {{ background:#0b0b0b }}
.log-terminal::-webkit-scrollbar-thumb {{ background:#333; border-radius:3px }}
.log-line {{ white-space:pre-wrap; word-wrap:break-word }}
.log-line .ts {{ color:var(--dim) }}
.log-line.buy {{ color:var(--green) }}
.log-line.sell {{ color:#60a5fa }}
.log-line.warn {{ color:#fbbf24 }}
.log-line.err {{ color:var(--red) }}
.log-line.info {{ color:var(--muted) }}
.log-auto {{ font-family:var(--mono); font-size:11px; color:var(--dim); display:flex; align-items:center; gap:6px }}

/* ──── VALUE FLASH ──── */
@keyframes flash-pos {{ 0%{{ background:var(--green-bg) }} 100%{{ background:transparent }} }}
@keyframes flash-neg {{ 0%{{ background:var(--red-bg) }} 100%{{ background:transparent }} }}

/* ──── REVIEW ──── */
.review-summary {{ color:var(--muted); font-size:13px; margin-bottom:12px; line-height:1.6 }}
.recs {{ padding-left:18px; color:var(--muted); font-size:13px; line-height:1.8 }}

/* ──── 08 · FOOTER (dashed border) ──── */
footer {{ text-align:center; font-size:11px; color:var(--dim); font-family:var(--mono); margin-top:28px; padding:14px 20px; border:2px dashed var(--border2); border-radius:var(--radius) }}

/* ──── RESPONSIVE ──── */
@media(max-width:1024px) {{
  .kpi-strip {{ grid-template-columns:repeat(4, 1fr) }}
}}
@media(max-width:600px) {{
  .page {{ padding:12px 12px 32px }}
  .kpi-strip {{ grid-template-columns:repeat(2, 1fr) }}
  .tabs {{ gap:4px }}
  .tab {{ font-size:11px; padding:6px 10px }}
}}
</style>
</head>
<body>
<div class="page">

<!-- ═══════ 00 · HEADER ═══════ -->
<header>
  <div>
    <div class="logo">nexus<span>_</span>trader</div>
    <div class="sub">NSE paper trading · Rs1,00,000 capital · Nifty 100 universe</div>
  </div>
  <div class="live-badge">
    <span class="live-dot"></span>
    LIVE · UPDATED {gen_at}
  </div>
</header>

{halt_bar}

<!-- ═══════ TAB NAV ═══════ -->
<div class="tabs">
  <button class="tab active" onclick="showPanel('main')">Page map</button>
  <button class="tab" onclick="showPanel('ledger')"><span class="star">★</span>Trade ledger</button>
  <button class="tab" onclick="showPanel('log')"><span class="star">★</span>Log viewer</button>
</div>

<!-- ═══════════════════════════════════════════════════ -->
<!--  MAIN PANEL — single vertical scroll               -->
<!-- ═══════════════════════════════════════════════════ -->
<div class="panel active" id="panel-main">

  <!-- 01 · KPI STRIP — 8 connected tiles -->
  <div class="section-label">KPI STRIP — 8 CONNECTED TILES</div>
  <div class="kpi-strip">
    <div class="kpi"><div class="label">Capital</div><div class="value">{capital:,.0f}</div></div>
    <div class="kpi"><div class="label">Daily P&amp;L</div><div class="value {dpnl_cls}">{"+" if today_pnl>=0 else ""}{today_pnl:,.0f}</div></div>
    <div class="kpi"><div class="label">Trades</div><div class="value">{st['total']}</div></div>
    <div class="kpi"><div class="label">Open</div><div class="value">{len(positions)}</div></div>
    <div class="kpi"><div class="label">All-time</div><div class="value {alltime_cls}">{"+" if st['net_pnl']>=0 else ""}{st['net_pnl']:,.0f}</div></div>
    <div class="kpi"><div class="label">Win %</div><div class="value">{st['win_rate']:.0f}</div></div>
    <div class="kpi"><div class="label">P. Factor</div><div class="value">{st['profit_factor']:.1f}</div></div>
    <div class="kpi"><div class="label">Avg R:R</div><div class="value">{st['avg_rr']:.1f}</div></div>
  </div>

  <!-- 02 · LIVE POSITIONS — TABLE -->
  <div class="section-label">LIVE POSITIONS — TABLE <span class="right">LAST PX {gen_at}</span></div>
  <div class="card" style="padding:0">
    <div class="tbl-wrap"><table>
      <thead><tr>
        <th>Symbol</th><th>Strat</th><th>Entry</th><th>Now</th><th>UPnL</th><th>SL</th><th>TGT</th><th>QTY</th>
      </tr></thead>
      <tbody>{pos_rows()}</tbody>
    </table></div>
  </div>

  <!-- 03 · CHART ROW — Equity Curve · Daily P&L -->
  <div class="section-label">CHART ROW — EQUITY CURVE · DAILY P&amp;L</div>
  <div class="two-col">
    <div class="card">
      <div class="card-head">Equity Curve</div>
      <div class="chart-wrap"><canvas id="eqChart"></canvas></div>
    </div>
    <div class="card">
      <div class="card-head">Daily P&amp;L</div>
      <div class="chart-wrap"><canvas id="dlChart"></canvas></div>
    </div>
  </div>

  <!-- 04 · TRADE HISTORY — LAST 50 -->
  <div class="section-label">TRADE HISTORY — LAST 50</div>
  <div class="card" style="padding:0">
    <div class="tbl-wrap"><table>
      <thead><tr>
        <th>Time</th><th>Symbol</th><th>Strat</th><th>Entry</th><th>Exit</th><th>Reason</th><th>Net</th>
      </tr></thead>
      <tbody>{trade_rows()}</tbody>
    </table></div>
  </div>

  <!-- 05 · ANALYTICS ROW — Strategy Breakdown · Exit Reasons -->
  <div class="section-label">ANALYTICS ROW — STRATEGY BREAKDOWN · EXIT REASONS</div>
  <div class="two-col">
    <div class="card">
      <div class="card-head">Strategy Breakdown</div>
      <div class="chart-wrap" style="height:180px"><canvas id="stChart"></canvas></div>
    </div>
    <div class="card">
      <div class="card-head">Exit Reasons</div>
      <div class="tbl-wrap"><table>
        <thead><tr><th>Exit Reason</th><th>Count</th><th>Net P&amp;L</th></tr></thead>
        <tbody>{exit_rows()}</tbody>
      </table></div>
    </div>
  </div>

  <!-- 06 · TRADE LEDGER (preview + link) -->
  <div class="section-label">TRADE LEDGER — FULL FINANCIAL BREAKDOWN <a class="tab-badge" onclick="showPanel('ledger');document.querySelector('[data-panel=ledger]').click()">TAB ↗</a></div>
  <div class="card" style="background:var(--surface2); border-style:dashed; padding:16px 20px">
    <div style="font-family:var(--mono); font-size:12px; color:var(--dim)">
      16 COLS · CHARGES GROUPED IN AMBER · FILTER: ALL / WINNERS / LOSERS
    </div>
    <div style="margin-top:8px; display:flex; gap:4px; flex-wrap:wrap">
      {"".join('<span style="display:inline-block;width:14px;height:10px;background:var(--border2);border-radius:2px"></span>' for _ in range(80))}
    </div>
  </div>

  <!-- 07 · LIVE LOG VIEWER (preview + link) -->
  <div class="section-label">LIVE LOG VIEWER — TERMINAL <a class="tab-badge" onclick="showPanel('log');document.querySelector('[data-panel=log]').click()">TAB ↗</a></div>
  <div class="log-terminal" id="logPreview" style="height:160px"></div>

  {review_block}

</div>

<!-- ═══════════════════════════════════════════════════ -->
<!--  TRADE LEDGER TAB (★)                              -->
<!-- ═══════════════════════════════════════════════════ -->
<div class="panel" id="panel-ledger">

  <div class="filters">
    <button class="fbtn active" onclick="filterTrades('all',this)">ALL</button>
    <button class="fbtn" onclick="filterTrades('winners',this)">WINNERS</button>
    <button class="fbtn" onclick="filterTrades('losers',this)">LOSERS</button>
  </div>

  <div class="tbl-wrap">
  <table id="ledger-table">
    <thead>
      <tr class="group-header">
        <th colspan="4" class="g-trade">TRADE</th>
        <th colspan="5" class="g-money">MONEY</th>
        <th colspan="5" class="g-charges">CHARGES</th>
        <th colspan="2" class="g-result">RESULT</th>
      </tr>
      <tr>
        <th>Time</th><th>Symbol</th><th>Strat</th><th>Qty</th>
        <th>Bought</th><th>Sold</th><th>Invested</th><th>Proceeds</th><th>Gross</th>
        <th>BRK</th><th>STT</th><th>EXCH</th><th>GST</th><th>Total</th>
        <th>Net</th><th>Reason</th>
      </tr>
    </thead>
    <tbody>{ledger_rows()}</tbody>
  </table>
  </div>
</div>

<!-- ═══════════════════════════════════════════════════ -->
<!--  LOG VIEWER TAB (★)                                -->
<!-- ═══════════════════════════════════════════════════ -->
<div class="panel" id="panel-log">

  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px">
    <div class="filters" style="margin-bottom:0">
      <button class="fbtn active" onclick="filterLog('all',this)">ALL</button>
      <button class="fbtn" onclick="filterLog('err',this)">ERR</button>
      <button class="fbtn" onclick="filterLog('buy',this)">BUY</button>
      <button class="fbtn" onclick="filterLog('sell',this)">SELL</button>
      <button class="fbtn" onclick="filterLog('warn',this)">WARN</button>
    </div>
    <div class="log-auto"><span class="live-dot"></span> AUTO</div>
  </div>

  <div class="log-terminal" id="logTerminal" style="height:340px"></div>
</div>

<!-- ═══════ 08 · FOOTER ═══════ -->
<footer>NEXUS_TRADER · PAPER TRADING · YFINANCE DATA · NO REAL MONEY</footer>

</div><!-- .page -->

<script>
/* ──── Tab switching ──── */
function showPanel(id) {{
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('panel-' + id).classList.add('active');
  // find the matching tab button
  document.querySelectorAll('.tab').forEach(t => {{
    if ((id==='main' && t.textContent.includes('Page map')) ||
        (id==='ledger' && t.textContent.includes('Trade ledger')) ||
        (id==='log' && t.textContent.includes('Log viewer')))
      t.classList.add('active');
  }});
  if (id === 'main') initCharts();
}}

/* ──── Trade ledger filter ──── */
function filterTrades(mode, btn) {{
  btn.parentElement.querySelectorAll('.fbtn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('#ledger-table tbody tr').forEach(tr => {{
    const pnl = parseFloat(tr.dataset.pnl || '0');
    if (mode === 'all') tr.style.display = '';
    else if (mode === 'winners') tr.style.display = pnl > 0 ? '' : 'none';
    else if (mode === 'losers') tr.style.display = pnl <= 0 ? '' : 'none';
  }});
}}

/* ──── Log viewer ──── */
const RAW_LINES = {log_json};
let logFilter = 'all';

function classifyLine(line) {{
  const up = line.toUpperCase();
  if (up.includes('ERROR') || up.includes('TRACEBACK') || up.includes('EXCEPTION')) return 'err';
  if (up.includes('BUY ') || up.includes('BOUGHT')) return 'buy';
  if (up.includes('SELL ') || up.includes('SOLD') || up.includes('SQUAREOFF')) return 'sell';
  if (up.includes('WARN') || up.includes('SLIPPAGE') || up.includes('TIMEOUT')) return 'warn';
  return 'info';
}}

function renderLog(targetId) {{
  const el = document.getElementById(targetId);
  if (!el) return;
  let h = '';
  RAW_LINES.forEach(line => {{
    const cls = classifyLine(line);
    if (logFilter !== 'all' && cls !== logFilter && targetId === 'logTerminal') return;
    const tsMatch = line.match(/^(\\d{{2}}:\\d{{2}}:\\d{{2}}|\\d{{4}}-\\d{{2}}-\\d{{2}}[T ]\\d{{2}}:\\d{{2}}:\\d{{2}})/);
    if (tsMatch) {{
      const ts = tsMatch[1];
      const msg = line.slice(ts.length);
      h += '<div class="log-line ' + cls + '"><span class="ts">' + ts + '</span>' + escHtml(msg) + '</div>';
    }} else {{
      h += '<div class="log-line ' + cls + '">' + escHtml(line) + '</div>';
    }}
  }});
  if (!h) h = '<div class="log-line info" style="color:var(--dim);text-align:center;padding:40px">No log lines</div>';
  el.innerHTML = h;
  el.scrollTop = el.scrollHeight;
}}

function filterLog(mode, btn) {{
  btn.parentElement.querySelectorAll('.fbtn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  logFilter = mode;
  renderLog('logTerminal');
}}

function escHtml(s) {{
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

// Render log in both preview and full terminal
renderLog('logPreview');
renderLog('logTerminal');

/* ──── Charts (purple equity line) ──── */
let chartsInit = false;
function initCharts() {{
  if (chartsInit) return;
  chartsInit = true;

  const C = Chart.defaults;
  C.color = '#555';
  C.borderColor = '#1e1e1e';
  C.font.family = "'JetBrains Mono', monospace";

  const axes = {{
    x: {{ grid:{{ color:'#161616' }}, ticks:{{ color:'#555', maxTicksLimit:8, font:{{ size:10 }} }} }},
    y: {{ grid:{{ color:'#161616' }}, ticks:{{ color:'#555', font:{{ size:10 }} }} }}
  }};

  /* Equity Curve — PURPLE line (brand colour) */
  new Chart('eqChart', {{
    type:'line',
    data:{{ labels:{eq_labels}, datasets:[{{ label:'Capital', data:{eq_values},
      borderColor:'#6366f1', backgroundColor:'rgba(99,102,241,0.06)',
      fill:true, tension:0.35, pointRadius:0, borderWidth:2 }}] }},
    options:{{ maintainAspectRatio:false, plugins:{{ legend:{{ display:false }} }}, scales:axes }}
  }});

  /* Daily P&L — GREEN/RED bars */
  new Chart('dlChart', {{
    type:'bar',
    data:{{ labels:{dl_labels}, datasets:[{{ label:'P&L', data:{dl_values},
      backgroundColor:{dl_colors}, borderRadius:3, borderSkipped:false }}] }},
    options:{{ maintainAspectRatio:false, plugins:{{ legend:{{ display:false }} }}, scales:axes }}
  }});

  /* Strategy — GREEN wins, RED losses */
  new Chart('stChart', {{
    type:'bar',
    data:{{ labels:{st_labels}, datasets:[
      {{ label:'Wins', data:{st_wins}, backgroundColor:'#22c55e', borderRadius:3 }},
      {{ label:'Losses', data:{st_losses}, backgroundColor:'#ef4444', borderRadius:3 }}
    ] }},
    options:{{ maintainAspectRatio:false, scales:axes,
      plugins:{{ legend:{{ labels:{{ color:'#555', boxWidth:12 }} }} }} }}
  }});
}}

// Init charts immediately for main panel
initCharts();
</script>
</body>
</html>"""

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--capital", type=float, default=100_000.0)
    p.add_argument("--open", action="store_true")
    args = p.parse_args()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    html_content = generate_html(starting_capital=args.capital)
    OUT_PATH.write_text(html_content, encoding="utf-8")
    IDX_PATH.write_text(html_content, encoding="utf-8")
    print(f"Dashboard written -> {OUT_PATH} and {IDX_PATH}")
    if args.open:
        webbrowser.open(OUT_PATH.resolve().as_uri())

if __name__ == "__main__":
    main()
