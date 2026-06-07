"""
dashboard.py -- nexus_trader HTML dashboard generator.
Reads portfolio.db and writes a self-contained HTML report to logs/dashboard.html and logs/index.html.
Usage: python dashboard.py
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

def _stats(trades):
    if not trades:
        return {"total":0,"wins":0,"losses":0,"win_rate":0.0,"net_pnl":0.0,"profit_factor":0.0,"best":0.0,"worst":0.0}
    pnls = [t["net_pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]; losses = [p for p in pnls if p <= 0]
    gw = sum(wins); gl = abs(sum(losses))
    return {"total":len(trades),"wins":len(wins),"losses":len(losses),
            "win_rate":len(wins)/len(trades)*100,"net_pnl":sum(pnls),
            "profit_factor":gw/gl if gl else 0.0,"best":max(pnls),"worst":min(pnls)}

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

def _weekly(trades):
    d = {}
    for t in trades:
        k = t["exit_time"][:10]
        if k not in d: d[k] = {"trades":0,"wins":0,"pnl":0.0}
        d[k]["trades"] += 1; d[k]["pnl"] += t["net_pnl"]
        if t["net_pnl"] > 0: d[k]["wins"] += 1
    return [{"date":k,**v} for k,v in sorted(d.items(),reverse=True)][:7]

def _strategy(trades):
    d = {}
    for t in trades:
        s = t.get("strategy","UNKNOWN")
        if s not in d: d[s] = {"wins":0,"losses":0,"pnl":0.0}
        if t["net_pnl"] > 0: d[s]["wins"] += 1
        else: d[s]["losses"] += 1
        d[s]["pnl"] += t["net_pnl"]
    return [{"strategy":k,**v} for k,v in d.items()]

def generate_html(starting_capital: float = 100_000.0) -> str:
    trades    = _load_trades()
    positions = _load_positions()
    meta      = _load_meta()
    review    = _load_latest_review()
    st        = _stats(trades)
    equity    = _equity(trades, starting_capital)
    daily     = _daily(trades)
    strat     = _strategy(trades)
    weekly    = _weekly(trades)
    capital   = float(meta.get("capital", starting_capital))
    gen_at    = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")

    eq_labels = json.dumps([e["l"] for e in equity])
    eq_values = json.dumps([e["v"] for e in equity])
    dl_labels = json.dumps([d["date"] for d in daily])
    dl_values = json.dumps([d["pnl"]  for d in daily])
    dl_colors = json.dumps(["#22c55e" if d["pnl"]>=0 else "#ef4444" for d in daily])
    st_labels = json.dumps([s["strategy"] for s in strat])
    st_wins   = json.dumps([s["wins"]     for s in strat])
    st_losses = json.dumps([s["losses"]   for s in strat])

    pnl_cls  = "pos" if st["net_pnl"] >= 0 else "neg"
    pf_cls   = "pos" if st["profit_factor"] >= 1 else "neg"
    is_halt  = meta.get("is_halted","0") == "1"
    halt_bar = '<div class="halt-banner">TRADING HALTED -- Daily loss limit reached</div>' if is_halt else ""

    def pos_rows():
        if not positions:
            return "<tr><td colspan='6' class='empty'>No open positions</td></tr>"
        r = ""
        for p in positions:
            r += (f"<tr><td><b>{_esc(p['symbol'])}</b></td>"
                  f"<td class='tag'>{_esc(p.get('strategy',''))}</td>"
                  f"<td>Rs{p['entry_price']:,.2f}</td>"
                  f"<td>{p['qty']}</td>"
                  f"<td class='neg'>Rs{p.get('stop_loss',0):,.2f}</td>"
                  f"<td class='pos'>Rs{p.get('target',0):,.2f}</td></tr>")
        return r

    def trade_rows():
        if not trades:
            return "<tr><td colspan='7' class='empty'>No trades yet</td></tr>"
        r = ""
        for t in trades[:30]:
            pnl = t["net_pnl"]; cls = "pos" if pnl>=0 else "neg"
            r += (f"<tr><td><b>{_esc(t['symbol'])}</b></td>"
                  f"<td class='tag'>{_esc(t.get('strategy',''))}</td>"
                  f"<td>Rs{t['entry_price']:,.2f}</td>"
                  f"<td>Rs{t['exit_price']:,.2f}</td>"
                  f"<td class='dim'>{_esc(t.get('exit_reason',''))}</td>"
                  f"<td class='{cls}'><b>Rs{pnl:+,.2f}</b></td>"
                  f"<td class='dim'>{t['exit_time'][:16]}</td></tr>")
        return r

    def weekly_rows():
        if not weekly:
            return "<tr><td colspan='4' class='empty'>No trade history yet</td></tr>"
        r = ""
        for w in weekly:
            wr = int(w["wins"]/w["trades"]*100) if w["trades"] else 0
            cls = "pos" if w["pnl"]>=0 else "neg"
            r += (f"<tr><td>{w['date']}</td><td>{w['trades']}</td>"
                  f"<td>{w['wins']}W / {w['trades']-w['wins']}L &nbsp;<span class='dim'>({wr}%)</span></td>"
                  f"<td class='{cls}'><b>Rs{w['pnl']:+,.2f}</b></td></tr>")
        return r

    def strat_rows():
        if not strat:
            return "<tr><td colspan='5' class='empty'>No trade history yet</td></tr>"
        r = ""
        for s in strat:
            tot = s["wins"]+s["losses"]; wr = int(s["wins"]/tot*100) if tot else 0
            avg = round(s["pnl"]/tot,2) if tot else 0; cls = "pos" if s["pnl"]>=0 else "neg"
            r += (f"<tr><td><b>{_esc(s['strategy'])}</b></td>"
                  f"<td>{s['wins']}W / {s['losses']}L</td><td>{wr}%</td>"
                  f"<td class='{cls}'><b>Rs{s['pnl']:+,.2f}</b></td>"
                  f"<td class='dim'>Rs{avg:+,.2f}</td></tr>")
        return r

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
<style>
:root {{
  --bg:      #080808;
  --surface: #111111;
  --border:  #1e1e1e;
  --text:    #e4e4e4;
  --muted:   #555;
  --pos:     #22c55e;
  --neg:     #ef4444;
  --accent:  #6366f1;
}}
* {{ box-sizing:border-box; margin:0; padding:0 }}
body {{ background:var(--bg); color:var(--text); font-family:system-ui,-apple-system,sans-serif; font-size:14px; line-height:1.5 }}
a {{ color:inherit; text-decoration:none }}

/* Layout */
.page {{ max-width:1200px; margin:0 auto; padding:28px 20px }}
header {{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:32px }}
.logo {{ font-size:1.1rem; font-weight:700; letter-spacing:.5px; color:#fff }}
.logo span {{ color:var(--accent) }}
.meta {{ font-size:12px; color:var(--muted); margin-top:4px }}
.refresh {{ font-size:12px; color:var(--muted); text-align:right }}

/* Halt banner */
.halt-banner {{ background:#7f1d1d; color:#fca5a5; padding:10px 16px; border-radius:6px; margin-bottom:24px; font-weight:600; font-size:13px }}

/* KPI row */
.kpi-row {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:1px; background:var(--border); border:1px solid var(--border); border-radius:8px; overflow:hidden; margin-bottom:24px }}
.kpi {{ background:var(--surface); padding:18px 20px }}
.kpi-label {{ font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; margin-bottom:6px }}
.kpi-value {{ font-size:1.5rem; font-weight:700; color:#fff }}
.kpi-value.pos {{ color:var(--pos) }}
.kpi-value.neg {{ color:var(--neg) }}

/* Cards */
.card {{ background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:20px; margin-bottom:20px }}
.card-head {{ font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); margin-bottom:16px; display:flex; justify-content:space-between; align-items:center }}
.two-col {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:20px }}
@media(max-width:700px){{ .two-col{{ grid-template-columns:1fr }} }}
.chart-wrap {{ height:220px; position:relative }}

/* Tables */
.tbl-wrap {{ overflow-x:auto }}
table {{ width:100%; border-collapse:collapse }}
th {{ font-size:11px; font-weight:500; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); padding:8px 12px; text-align:left; border-bottom:1px solid var(--border) }}
td {{ padding:9px 12px; border-bottom:1px solid #161616; vertical-align:middle }}
tr:last-child td {{ border-bottom:none }}
tr:hover td {{ background:#161616 }}
.tag {{ font-size:11px; color:var(--muted) }}
.dim {{ color:var(--muted) }}
.pos {{ color:var(--pos) }}
.neg {{ color:var(--neg) }}
.empty {{ color:var(--muted); text-align:center; padding:24px }}

/* Review */
.review-summary {{ color:var(--muted); font-size:13px; margin-bottom:12px; line-height:1.6 }}
.recs {{ padding-left:18px; color:var(--muted); font-size:13px; line-height:1.8 }}

/* Footer */
footer {{ text-align:center; font-size:11px; color:var(--muted); margin-top:32px; padding-top:16px; border-top:1px solid var(--border) }}
</style>
</head>
<body>
<div class="page">

<header>
  <div>
    <div class="logo">nexus<span>_</span>trader</div>
    <div class="meta">NSE paper trading &nbsp;|&nbsp; Rs1,00,000 capital &nbsp;|&nbsp; Nifty 100 universe</div>
  </div>
  <div class="refresh">Updated {gen_at}<br><span style="font-size:11px">auto-refreshes every 60s</span></div>
</header>

{halt_bar}

<div class="kpi-row">
  <div class="kpi"><div class="kpi-label">Capital</div><div class="kpi-value">Rs{capital:,.0f}</div></div>
  <div class="kpi"><div class="kpi-label">Net P&L</div><div class="kpi-value {pnl_cls}">Rs{st['net_pnl']:+,.2f}</div></div>
  <div class="kpi"><div class="kpi-label">Trades</div><div class="kpi-value">{st['total']}</div></div>
  <div class="kpi"><div class="kpi-label">Win Rate</div><div class="kpi-value">{st['win_rate']:.1f}%</div></div>
  <div class="kpi"><div class="kpi-label">Profit Factor</div><div class="kpi-value {pf_cls}">{st['profit_factor']:.2f}</div></div>
  <div class="kpi"><div class="kpi-label">Best Trade</div><div class="kpi-value pos">Rs{st['best']:+,.2f}</div></div>
  <div class="kpi"><div class="kpi-label">Worst Trade</div><div class="kpi-value neg">Rs{st['worst']:+,.2f}</div></div>
  <div class="kpi"><div class="kpi-label">Open Positions</div><div class="kpi-value">{len(positions)}</div></div>
</div>

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

<div class="card">
  <div class="card-head">Strategy Breakdown</div>
  <div class="chart-wrap" style="height:180px"><canvas id="stChart"></canvas></div>
</div>

<div class="card">
  <div class="card-head">Open Positions <span class="dim">{len(positions)} active</span></div>
  <div class="tbl-wrap"><table>
    <thead><tr><th>Symbol</th><th>Strategy</th><th>Entry</th><th>Qty</th><th>Stop Loss</th><th>Target</th></tr></thead>
    <tbody>{pos_rows()}</tbody>
  </table></div>
</div>

<div class="two-col">
  <div class="card">
    <div class="card-head">Weekly P&L</div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Date</th><th>Trades</th><th>W/L</th><th>Net P&L</th></tr></thead>
      <tbody>{weekly_rows()}</tbody>
    </table></div>
  </div>
  <div class="card">
    <div class="card-head">Strategy Performance</div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Strategy</th><th>W/L</th><th>WR</th><th>Total P&L</th><th>Avg</th></tr></thead>
      <tbody>{strat_rows()}</tbody>
    </table></div>
  </div>
</div>

<div class="card">
  <div class="card-head">Trade History <span class="dim">last 30</span></div>
  <div class="tbl-wrap"><table>
    <thead><tr><th>Symbol</th><th>Strategy</th><th>Entry</th><th>Exit</th><th>Reason</th><th>Net P&L</th><th>Time</th></tr></thead>
    <tbody>{trade_rows()}</tbody>
  </table></div>
</div>

{review_block}

<footer>nexus_trader &nbsp;|&nbsp; 100% paper trading &nbsp;|&nbsp; yfinance 15-min delayed data &nbsp;|&nbsp; zero real money</footer>
</div>

<script>
const C = Chart.defaults;
C.color = '#555';
C.borderColor = '#1e1e1e';
C.font.family = 'system-ui,-apple-system,sans-serif';

const axes = {{
  x: {{ grid:{{ color:'#161616' }}, ticks:{{ color:'#555', maxTicksLimit:8 }} }},
  y: {{ grid:{{ color:'#161616' }}, ticks:{{ color:'#555' }} }}
}};

new Chart('eqChart', {{
  type:'line',
  data:{{ labels:{eq_labels}, datasets:[{{ label:'Capital', data:{eq_values},
    borderColor:'#6366f1', backgroundColor:'rgba(99,102,241,0.06)',
    fill:true, tension:0.35, pointRadius:0, borderWidth:2 }}] }},
  options:{{ maintainAspectRatio:false, plugins:{{ legend:{{ display:false }} }}, scales:axes }}
}});

new Chart('dlChart', {{
  type:'bar',
  data:{{ labels:{dl_labels}, datasets:[{{ label:'P&L', data:{dl_values},
    backgroundColor:{dl_colors}, borderRadius:3, borderSkipped:false }}] }},
  options:{{ maintainAspectRatio:false, plugins:{{ legend:{{ display:false }} }}, scales:axes }}
}});

new Chart('stChart', {{
  type:'bar',
  data:{{ labels:{st_labels}, datasets:[
    {{ label:'Wins', data:{st_wins}, backgroundColor:'#22c55e', borderRadius:3 }},
    {{ label:'Losses', data:{st_losses}, backgroundColor:'#ef4444', borderRadius:3 }}
  ] }},
  options:{{ maintainAspectRatio:false, scales:axes,
    plugins:{{ legend:{{ labels:{{ color:'#555', boxWidth:12 }} }} }} }}
}});
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
    # Also write as index.html so http://IP:8080 lands on dashboard directly
    IDX_PATH.write_text(html_content, encoding="utf-8")
    print(f"Dashboard written -> {OUT_PATH} and {IDX_PATH}")
    if args.open:
        webbrowser.open(OUT_PATH.resolve().as_uri())

if __name__ == "__main__":
    main()
