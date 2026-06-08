"""
server.py -- nexus_trader live HTML dashboard server.
Provides dynamic updates and live stock prices without page reloads.
Usage: python server.py [port]
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
from flask import Flask, jsonify

import dashboard

app = Flask(__name__)
IST = dashboard.IST
DB_PATH = dashboard.DB_PATH

# Shared in-memory cache for live position prices
_latest_prices: dict[str, float] = {}
_latest_prices_lock = threading.Lock()

def _conn():
    c = sqlite3.connect(DB_PATH, timeout=5.0)
    c.execute("PRAGMA journal_mode=WAL")
    c.row_factory = sqlite3.Row
    return c

def _price_poller_loop():
    """Background thread to fetch yfinance prices for open positions every 10 seconds."""
    while True:
        try:
            if DB_PATH.exists():
                conn = _conn()
                rows = conn.execute("SELECT symbol FROM positions").fetchall()
                conn.close()
                symbols = [r["symbol"] for r in rows]
                
                if symbols:
                    raw = yf.download(
                        tickers=" ".join(symbols),
                        period="1d",
                        interval="1m",
                        progress=False,
                        auto_adjust=False,
                    )
                    prices = {}
                    if not raw.empty:
                        if len(symbols) == 1:
                            try:
                                # For a single symbol, Close is a Series
                                prices[symbols[0]] = round(float(raw["Close"].iloc[-1]), 2)
                            except Exception:
                                pass
                        else:
                            for s in symbols:
                                try:
                                    # For multiple symbols, Close is a DataFrame with multi-columns
                                    prices[s] = round(float(raw["Close"][s].iloc[-1]), 2)
                                except Exception:
                                    pass
                    
                    if prices:
                        with _latest_prices_lock:
                            _latest_prices.update(prices)
        except Exception:
            pass
        time.sleep(10)

# Start the background poller thread
poller_thread = threading.Thread(target=_price_poller_loop, daemon=True)
poller_thread.start()

@app.route("/")
def index():
    # Dynamically serve the latest formatted dashboard HTML
    return dashboard.generate_html()

@app.route("/api/live-html")
def api_live_html():
    try:
        trades = dashboard._load_trades()
        positions = dashboard._load_positions()
        meta = dashboard._load_meta()
        st = dashboard._stats(trades)
        
        # 1. Calculate positions HTML and live unrealised P&L
        total_upnl = 0.0
        pos_rows_html = ""
        if not positions:
            pos_rows_html = '<tr><td colspan="8" class="empty">No open positions</td></tr>'
        else:
            with _latest_prices_lock:
                prices = _latest_prices.copy()
            for p in positions:
                sym = p["symbol"]
                cp = prices.get(sym, p["entry_price"])
                upnl = (cp - p["entry_price"]) * p["qty"]
                total_upnl += upnl
                
                upnl_cls = "pos" if upnl >= 0 else "neg"
                upnl_str = f"{'+' if upnl>=0 else ''}{upnl:,.0f}"
                
                pos_rows_html += (f'<tr>'
                                  f'<td><b>{dashboard._esc(sym)}</b></td>'
                                  f'<td class="dim">{dashboard._esc(p.get("strategy",""))}</td>'
                                  f'<td>{p["entry_price"]:,.0f}</td>'
                                  f'<td><b>{cp:,.2f}</b></td>'
                                  f'<td class="{upnl_cls}">{upnl_str}</td>'
                                  f'<td class="neg">{p.get("stop_loss",0):,.0f}</td>'
                                  f'<td class="pos">{p.get("target",0):,.0f}</td>'
                                  f'<td>{p.get("qty",0)}</td>'
                                  f'</tr>')
                                  
        # 2. Calculate live daily P&L (closed trades today + current unrealised positions P&L)
        today = datetime.now(IST).strftime("%Y-%m-%d")
        today_trades = [t for t in trades if t.get("exit_time", "")[:10] == today]
        closed_pnl = sum(t["net_pnl"] for t in today_trades)
        live_daily_pnl = closed_pnl + total_upnl
        
        dpnl_cls = "pos" if live_daily_pnl >= 0 else "neg"
        alltime_cls = "pos" if st["net_pnl"] >= 0 else "neg"
        
        # 3. Format trades history rows
        trade_rows_html = ""
        if not trades:
            trade_rows_html = '<tr><td colspan="7" class="empty">No trades yet</td></tr>'
        else:
            for t in trades[:50]:
                pnl = t["net_pnl"]
                cls = "pos" if pnl >= 0 else "neg"
                time_str = t.get("exit_time","")[:5] if t.get("exit_time") else ""
                trade_rows_html += (f'<tr>'
                                    f'<td class="dim">{time_str}</td>'
                                    f'<td><b>{dashboard._esc(t["symbol"])}</b></td>'
                                    f'<td class="dim">{dashboard._esc(t.get("strategy",""))}</td>'
                                    f'<td>{t["entry_price"]:,.0f}</td>'
                                    f'<td>{t["exit_price"]:,.0f}</td>'
                                    f'<td class="dim">{dashboard._esc(t.get("exit_reason",""))}</td>'
                                    f'<td class="{cls}"><b>{"+" if pnl>=0 else ""}{pnl:,.0f}</b></td>'
                                    f'</tr>')
                                    
        # 4. Format ledger rows
        ledger_rows_html = ""
        if not trades:
            ledger_rows_html = '<tr><td colspan="16" class="empty">No trades yet</td></tr>'
        else:
            for t in trades[:50]:
                pnl = t["net_pnl"]
                cls = "pos" if pnl >= 0 else "neg"
                entry_p = t.get("entry_price", 0)
                exit_p = t.get("exit_price", 0)
                qty = t.get("qty", 0)
                invested = round(entry_p * qty, 2)
                proceeds = round(exit_p * qty, 2)
                gross = round(proceeds - invested, 2)
                gross_cls = "pos" if gross >= 0 else "neg"
                brk = t.get("brokerage", round(max(invested, proceeds) * 0.0003, 2))
                stt = t.get("stt", round(proceeds * 0.00025, 2))
                exch = t.get("exchange_charges", round(max(invested, proceeds) * 0.0000345, 2))
                gst = t.get("gst", round(brk * 0.18, 2))
                charges = round(brk + stt + exch + gst, 2)
                time_str = t.get("exit_time","")[:5] if t.get("exit_time") else ""
                reason = t.get("exit_reason","")
                ledger_rows_html += (f'<tr data-pnl="{pnl}">'
                                     f'<td class="dim">{time_str}</td>'
                                     f'<td><b>{dashboard._esc(t["symbol"])}</b></td>'
                                     f'<td class="dim">{dashboard._esc(t.get("strategy",""))}</td>'
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
                                     f'<td class="dim">{dashboard._esc(reason)}</td></tr>')

        # 5. Fetch logs
        log_lines = dashboard._load_log_lines(80)
        
        capital = float(meta.get("capital", 100000.0))
        
        return jsonify({
            "capital": f"{capital:,.0f}",
            "daily_pnl": f"{'+' if live_daily_pnl>=0 else ''}{live_daily_pnl:,.0f}",
            "dpnl_cls": dpnl_cls,
            "trades": str(st['total']),
            "open": str(len(positions)),
            "all_time": f"{'+' if st['net_pnl']>=0 else ''}{st['net_pnl']:,.0f}",
            "alltime_cls": alltime_cls,
            "win_rate": f"{st['win_rate']:.0f}",
            "profit_factor": f"{st['profit_factor']:.1f}",
            "avg_rr": f"{st['avg_rr']:.1f}",
            "positions_html": pos_rows_html,
            "trades_html": trade_rows_html,
            "ledger_html": ledger_rows_html,
            "log_lines": log_lines,
            "gen_at": datetime.now(IST).strftime("%H:%M:%S")
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)
