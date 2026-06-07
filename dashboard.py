"""
dashboard.py — nexus_trader HTML dashboard generator.

Reads execution/portfolio.db and logs/performance/ review JSONs,
then writes a self-contained HTML report to logs/dashboard.html.

Usage:
    python dashboard.py             # generates logs/dashboard.html
    python dashboard.py --open      # generates and opens in default browser
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sqlite3
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

import pytz

DB_PATH = Path("execution/portfolio.db")
PERF_DIR = Path("logs/performance")
OUT_PATH = Path("logs/dashboard.html")
IST = pytz.timezone("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _esc(val) -> str:
    """Escape HTML special characters to prevent XSS."""
    return html.escape(str(val)) if val is not None else ""


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_trades() -> list[dict]:
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM trades ORDER BY exit_time DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _load_positions() -> list[dict]:
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM positions ORDER BY entry_time DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _load_meta() -> dict:
    if not DB_PATH.exists():
        return {}
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT key, value FROM meta").fetchall()
    conn.close()
    return {k: v for k, v in rows}


def _load_latest_review() -> dict | None:
    if not PERF_DIR.exists():
        return None
    files = sorted(PERF_DIR.glob("review_*.json"), reverse=True)
    for f in files:
        if "partial" in f.name or "failed" in f.name:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            date_part = f.name.replace("review_", "").replace(".json", "")
            if len(date_part) == 8:
                data["review_date"] = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:]}"
            else:
                data["review_date"] = date_part

            if "summary" in data and "overall_assessment" not in data:
                data["overall_assessment"] = data["summary"]

            if "recommendations" not in data:
                recs = []
                adjustments = data.get("parameter_adjustments", [])
                for adj in adjustments:
                    recs.append(
                        f"Parameter Adjustment: {adj.get('param_name')} "
                        f"({adj.get('current_value')} → {adj.get('suggested_value')}) — {adj.get('reason')}"
                    )
                watch = data.get("tomorrow_watch", [])
                if watch:
                    recs.append(f"Watch tomorrow: {', '.join(watch)}")
                data["recommendations"] = recs

            return data
        except Exception:
            continue
    return None


def _compute_stats(trades: list[dict]) -> dict:
    if not trades:
        return {
            "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
            "total_net_pnl": 0.0, "gross_wins": 0.0, "gross_losses": 0.0,
            "profit_factor": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "best_trade": 0.0, "worst_trade": 0.0,
        }
    pnls = [t["net_pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_wins = sum(wins)
    gross_losses = abs(sum(losses))
    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades) * 100,
        "total_net_pnl": sum(pnls),
        "gross_wins": gross_wins,
        "gross_losses": gross_losses,
        "profit_factor": gross_wins / gross_losses if gross_losses else 0.0,
        "avg_win": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss": sum(losses) / len(losses) if losses else 0.0,
        "best_trade": max(pnls),
        "worst_trade": min(pnls),
    }


def _equity_curve(trades: list[dict], starting_capital: float) -> list[dict]:
    """Cumulative equity after each closed trade (chronological order)."""
    capital = starting_capital
    curve = [{"label": "Start", "value": capital}]
    for t in reversed(trades):   # trades loaded newest-first; reverse for chron order
        capital += t["net_pnl"]
        label = f"{t['symbol']} {t['exit_time'][:10]}"
        curve.append({"label": label, "value": round(capital, 2)})
    return curve


def _daily_pnl_bars(trades: list[dict]) -> list[dict]:
    """Aggregate net_pnl by exit date."""
    by_date: dict[str, float] = {}
    for t in trades:
        d = t["exit_time"][:10]
        by_date[d] = by_date.get(d, 0.0) + t["net_pnl"]
    return [{"date": d, "pnl": round(v, 2)} for d, v in sorted(by_date.items())]


def _strategy_breakdown(trades: list[dict]) -> list[dict]:
    """Win/loss count per strategy."""
    data: dict[str, dict] = {}
    for t in trades:
        s = t.get("strategy", "UNKNOWN")
        if s not in data:
            data[s] = {"wins": 0, "losses": 0, "pnl": 0.0}
        if t["net_pnl"] > 0:
            data[s]["wins"] += 1
        else:
            data[s]["losses"] += 1
        data[s]["pnl"] += t["net_pnl"]
    return [{"strategy": k, **v} for k, v in data.items()]


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def _pnl_color(v: float) -> str:
    return "#16a34a" if v >= 0 else "#dc2626"


def _fmt_inr(v: float) -> str:
    return f"₹{v:+,.2f}"


def _trades_table_rows(trades: list[dict]) -> str:
    rows = []
    for t in trades[:50]:   # cap at 50 most recent
        color = _pnl_color(t["net_pnl"])
        rows.append(
            f"<tr>"
            f"<td>{_esc(t['symbol'])}</td>"
            f"<td>{_esc(t.get('strategy',''))}</td>"
            f"<td>₹{t['entry_price']:,.2f}</td>"
            f"<td>₹{t['exit_price']:,.2f}</td>"
            f"<td>{t['qty']}</td>"
            f"<td>{_esc(t.get('exit_reason',''))}</td>"
            f"<td style='color:{color};font-weight:600'>{_fmt_inr(t['net_pnl'])}</td>"
            f"<td>{t['exit_time'][:16]}</td>"
            f"</tr>"
        )
    return "\n".join(rows) or "<tr><td colspan='8' style='text-align:center;color:#888'>No closed trades yet</td></tr>"


def _positions_table_rows(positions: list[dict]) -> str:
    rows = []
    for p in positions:
        rows.append(
            f"<tr>"
            f"<td>{_esc(p['symbol'])}</td>"
            f"<td>{_esc(p.get('strategy',''))}</td>"
            f"<td>₹{p['entry_price']:,.2f}</td>"
            f"<td>{p['qty']}</td>"
            f"<td>₹{p.get('stop_loss',0):,.2f}</td>"
            f"<td>₹{p.get('target',0):,.2f}</td>"
            f"<td>{p.get('entry_time','')[:16]}</td>"
            f"</tr>"
        )
    return "\n".join(rows) or "<tr><td colspan='7' style='text-align:center;color:#888'>No open positions</td></tr>"


def generate_html(starting_capital: float = 100_000.0) -> str:
    trades = _load_trades()
    positions = _load_positions()
    meta = _load_meta()
    review = _load_latest_review()
    stats = _compute_stats(trades)
    equity = _equity_curve(trades, starting_capital)
    daily = _daily_pnl_bars(trades)
    strategy_data = _strategy_breakdown(trades)
    capital = float(meta.get("capital", starting_capital))
    generated_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")

    equity_labels = json.dumps([e["label"] for e in equity])
    equity_values = json.dumps([e["value"] for e in equity])
    daily_labels = json.dumps([d["date"] for d in daily])
    daily_values = json.dumps([d["pnl"] for d in daily])
    daily_colors = json.dumps(["#16a34a" if d["pnl"] >= 0 else "#dc2626" for d in daily])
    strategy_labels = json.dumps([s["strategy"] for s in strategy_data])
    strategy_wins = json.dumps([s["wins"] for s in strategy_data])
    strategy_losses = json.dumps([s["losses"] for s in strategy_data])

    review_html = ""
    if review:
        rec_rows = ""
        for r in review.get("recommendations", []):
            rec_rows += f"<li>{_esc(r)}</li>"
        review_html = f"""
        <div class="card">
            <h2>Latest AI Review — {_esc(review.get('review_date',''))}</h2>
            <p style="color:#888;margin-bottom:12px">{_esc(review.get('overall_assessment',''))}</p>
            <b>Recommendations:</b>
            <ul style="margin-top:8px;padding-left:20px;line-height:1.8">{rec_rows}</ul>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>nexus_trader — Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;padding:24px}}
  h1{{font-size:1.6rem;font-weight:700;color:#f8fafc}}
  h2{{font-size:1.1rem;font-weight:600;color:#cbd5e1;margin-bottom:16px}}
  .header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:28px}}
  .subtitle{{color:#64748b;font-size:0.85rem;margin-top:4px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:28px}}
  .stat{{background:#1e293b;border-radius:12px;padding:20px;border:1px solid #334155}}
  .stat .label{{color:#64748b;font-size:0.78rem;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px}}
  .stat .value{{font-size:1.5rem;font-weight:700;color:#f8fafc}}
  .stat .value.pos{{color:#16a34a}}
  .stat .value.neg{{color:#dc2626}}
  .card{{background:#1e293b;border-radius:12px;padding:24px;border:1px solid #334155;margin-bottom:24px}}
  .chart-wrap{{position:relative;height:260px}}
  table{{width:100%;border-collapse:collapse;font-size:0.85rem}}
  th{{text-align:left;color:#64748b;font-weight:500;padding:8px 12px;border-bottom:1px solid #334155}}
  td{{padding:8px 12px;border-bottom:1px solid #1e293b}}
  tr:hover td{{background:#263348}}
  .badge{{display:inline-block;padding:2px 8px;border-radius:999px;font-size:0.75rem;font-weight:600}}
  .badge.pos{{background:#14532d;color:#4ade80}}
  .badge.neg{{background:#7f1d1d;color:#f87171}}
  .footer{{color:#475569;font-size:0.78rem;text-align:center;margin-top:32px}}
  .two-col{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}
  @media(max-width:700px){{.two-col{{grid-template-columns:1fr}}}}
  .refresh-btn{{background:#334155;color:#e2e8f0;border:none;border-radius:8px;padding:8px 16px;cursor:pointer;font-size:0.85rem}}
  .refresh-btn:hover{{background:#475569}}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>nexus_trader</h1>
    <div class="subtitle">Paper Trading Dashboard · Generated {generated_at}</div>
  </div>
  <button class="refresh-btn" onclick="location.reload()">⟳ Refresh</button>
</div>

<!-- KPI stats -->
<div class="grid">
  <div class="stat">
    <div class="label">Capital</div>
    <div class="value">₹{capital:,.0f}</div>
  </div>
  <div class="stat">
    <div class="label">Total Net P&L</div>
    <div class="value {'pos' if stats['total_net_pnl']>=0 else 'neg'}">{_fmt_inr(stats['total_net_pnl'])}</div>
  </div>
  <div class="stat">
    <div class="label">Total Trades</div>
    <div class="value">{stats['total_trades']}</div>
  </div>
  <div class="stat">
    <div class="label">Win Rate</div>
    <div class="value">{stats['win_rate']:.1f}%</div>
  </div>
  <div class="stat">
    <div class="label">Profit Factor</div>
    <div class="value {'pos' if stats['profit_factor']>=1 else 'neg'}">{stats['profit_factor']:.2f}</div>
  </div>
  <div class="stat">
    <div class="label">Best Trade</div>
    <div class="value pos">{_fmt_inr(stats['best_trade'])}</div>
  </div>
  <div class="stat">
    <div class="label">Worst Trade</div>
    <div class="value neg">{_fmt_inr(stats['worst_trade'])}</div>
  </div>
  <div class="stat">
    <div class="label">Open Positions</div>
    <div class="value">{len(positions)}</div>
  </div>
</div>

<!-- Charts row -->
<div class="two-col">
  <div class="card">
    <h2>Equity Curve</h2>
    <div class="chart-wrap"><canvas id="equityChart"></canvas></div>
  </div>
  <div class="card">
    <h2>Daily P&L</h2>
    <div class="chart-wrap"><canvas id="dailyChart"></canvas></div>
  </div>
</div>

<!-- Strategy breakdown -->
<div class="card">
  <h2>Strategy Breakdown</h2>
  <div class="chart-wrap" style="height:200px"><canvas id="strategyChart"></canvas></div>
</div>

<!-- Open positions -->
<div class="card">
  <h2>Open Positions ({len(positions)})</h2>
  <div style="overflow-x:auto">
  <table>
    <thead><tr><th>Symbol</th><th>Strategy</th><th>Entry</th><th>Qty</th><th>SL</th><th>Target</th><th>Time</th></tr></thead>
    <tbody>{_positions_table_rows(positions)}</tbody>
  </table>
  </div>
</div>

<!-- Trade history -->
<div class="card">
  <h2>Trade History (last 50)</h2>
  <div style="overflow-x:auto">
  <table>
    <thead><tr><th>Symbol</th><th>Strategy</th><th>Entry</th><th>Exit</th><th>Qty</th><th>Reason</th><th>Net P&L</th><th>Exit Time</th></tr></thead>
    <tbody>{_trades_table_rows(trades)}</tbody>
  </table>
  </div>
</div>

{review_html}

<div class="footer">nexus_trader · 100% paper trading · zero real money · data via yfinance (15-min delayed)</div>

<script>
const chartDefaults = {{
  plugins: {{ legend: {{ labels: {{ color: '#94a3b8' }} }} }},
  scales: {{
    x: {{ ticks: {{ color: '#64748b' }}, grid: {{ color: '#1e293b' }} }},
    y: {{ ticks: {{ color: '#64748b' }}, grid: {{ color: '#1e293b' }} }}
  }}
}};

// Equity curve
new Chart(document.getElementById('equityChart'), {{
  type: 'line',
  data: {{
    labels: {equity_labels},
    datasets: [{{
      label: 'Capital (₹)',
      data: {equity_values},
      borderColor: '#3b82f6',
      backgroundColor: 'rgba(59,130,246,0.08)',
      fill: true,
      tension: 0.3,
      pointRadius: 3,
    }}]
  }},
  options: {{ ...chartDefaults, maintainAspectRatio: false }}
}});

// Daily P&L bars
new Chart(document.getElementById('dailyChart'), {{
  type: 'bar',
  data: {{
    labels: {daily_labels},
    datasets: [{{
      label: 'Net P&L (₹)',
      data: {daily_values},
      backgroundColor: {daily_colors},
    }}]
  }},
  options: {{ ...chartDefaults, maintainAspectRatio: false }}
}});

// Strategy breakdown
new Chart(document.getElementById('strategyChart'), {{
  type: 'bar',
  data: {{
    labels: {strategy_labels},
    datasets: [
      {{ label: 'Wins', data: {strategy_wins}, backgroundColor: '#16a34a' }},
      {{ label: 'Losses', data: {strategy_losses}, backgroundColor: '#dc2626' }},
    ]
  }},
  options: {{ ...chartDefaults, maintainAspectRatio: false, plugins: {{ ...chartDefaults.plugins }} }}
}});
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="nexus_trader — dashboard generator")
    p.add_argument("--open", action="store_true", help="Open dashboard in browser after generating")
    p.add_argument("--capital", type=float, default=100_000.0, help="Starting capital (default: 100000)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    html = generate_html(starting_capital=args.capital)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"Dashboard written → {OUT_PATH.resolve()}")
    if args.open:
        webbrowser.open(OUT_PATH.resolve().as_uri())


if __name__ == "__main__":
    main()
