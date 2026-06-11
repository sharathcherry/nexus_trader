"""
utils/event_timeline.py — Activity timeline builder for nexus_trader dashboard.

Parses today's logs + decision log + DB trades and returns a sorted list of
timestamped events for display on the dashboard.

Each event is a dict:
  {
    "time":     "HH:MM:SS",          # display time
    "sort_key": datetime,            # for ordering
    "icon":     "🟢",                # unicode icon
    "category": "TRADE",             # LIFECYCLE | SCAN | TRADE | RISK | REVIEW
    "cat_class": "cat-trade",        # CSS class
    "text":     "BUY RELIANCE.NS ...",
  }

Never raises — all errors are swallowed and return empty list.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Any

import pytz

IST = pytz.timezone("Asia/Kolkata")

# ── Paths ────────────────────────────────────────────────────────────────────
_LOG_PATH     = Path("logs/nexus.log")
_DEC_DIR      = Path("logs/decisions")
_DB_PATH      = Path("execution/portfolio.db")

# ── Category metadata ────────────────────────────────────────────────────────
_CATEGORIES: dict[str, dict[str, str]] = {
    "LIFECYCLE": {"icon": "⚙",  "cls": "cat-lifecycle"},
    "SCAN":      {"icon": "🔍", "cls": "cat-scan"},
    "TRADE":     {"icon": "📈", "cls": "cat-trade"},
    "RISK":      {"icon": "⚠",  "cls": "cat-risk"},
    "REVIEW":    {"icon": "📊", "cls": "cat-review"},
    "INFO":      {"icon": "•",  "cls": "cat-info"},
}

# ── Log-line pattern for nexus.log ──────────────────────────────────────────
# Format: "YYYY-MM-DD HH:MM:SS [LEVEL] module — message"
_LOG_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})\s+"
    r"(?:\[?\w+\]?\s+)?"          # optional [LEVEL]
    r"(?:[\w.]+\s+[—\-]+\s+)?"   # optional module —
    r"(.+)$"
)

# Keyword → (category, icon, text_transform)
_LOG_RULES: list[tuple[re.Pattern, str, str | None]] = [
    # Lifecycle phase starts
    (re.compile(r"upstox.*token.*refresh|token.*refresh.*upstox", re.I),
     "LIFECYCLE", None),
    (re.compile(r"pre.?market.*prep|run_pre_market|AgentI0|AgentI1|market bias", re.I),
     "LIFECYCLE", None),
    (re.compile(r"provisional.*scan|gap.*scan|AgentI[12].*scan", re.I),
     "SCAN", None),
    (re.compile(r"watchlist.*confirm|confirm.*watchlist|AgentI3|AgentI4", re.I),
     "SCAN", None),
    (re.compile(r"morning.*brief|briefing", re.I),
     "LIFECYCLE", None),
    (re.compile(r"market.*session.*start|session.*start|scheduler.*start", re.I),
     "LIFECYCLE", None),
    (re.compile(r"force.*square|squareoff|square.*off", re.I),
     "TRADE", None),
    (re.compile(r"post.?market.*review|daily.*review|review.*complete", re.I),
     "REVIEW", None),
    (re.compile(r"trading halt|HALT|daily loss limit", re.I),
     "RISK", None),
    # Trades
    (re.compile(r"\bBUY\b.*\bqty\b|\bBOUGHT\b", re.I),
     "TRADE", None),
    (re.compile(r"\bSELL\b.*\bqty\b|\bSOLD\b|\bPARTIAL", re.I),
     "TRADE", None),
    # Risk
    (re.compile(r"BUY REJECTED|SELL REJECTED|position limit|capital.*insufficient", re.I),
     "RISK", None),
    (re.compile(r"trailing.*SL|stop.*loss.*update|TRAIL", re.I),
     "RISK", None),
]


def _today() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def _make_event(
    ts: datetime,
    category: str,
    text: str,
    icon_override: str | None = None,
) -> dict[str, Any]:
    cat_meta = _CATEGORIES.get(category, _CATEGORIES["INFO"])
    icon = icon_override or cat_meta["icon"]
    # BUY → green, SELL → red, others keep category icon
    if re.search(r"\bBUY\b", text, re.I) and category == "TRADE":
        icon = "🟢"
    elif re.search(r"\bSELL\b|\bSQUAREOFF\b", text, re.I) and category == "TRADE":
        icon = "🔴"
    elif re.search(r"\bPARTIAL", text, re.I) and category == "TRADE":
        icon = "🟡"
    elif category == "REVIEW" and re.search(r"PROFITABLE|profit", text, re.I):
        icon = "✅"
    elif category == "REVIEW":
        icon = "📊"
    elif category == "LIFECYCLE" and re.search(r"start|refresh|active", text, re.I):
        icon = "⚙"
    elif category == "LIFECYCLE" and re.search(r"end|close|stop", text, re.I):
        icon = "⏹"
    elif category == "RISK" and re.search(r"halt|HALT", text, re.I):
        icon = "🛑"
    return {
        "time":      ts.strftime("%H:%M:%S"),
        "sort_key":  ts,
        "icon":      icon,
        "category":  category,
        "cat_class": cat_meta["cls"],
        "text":      text[:200],
    }


def _classify_log_line(message: str) -> tuple[str, str | None]:
    """Return (category, icon_override) for a log message."""
    for pattern, cat, icon in _LOG_RULES:
        if pattern.search(message):
            return cat, icon
    return "INFO", None


# ── Main log parser ──────────────────────────────────────────────────────────

def _parse_nexus_log(today: str) -> list[dict]:
    events: list[dict] = []
    if not _LOG_PATH.exists():
        return events
    try:
        text = _LOG_PATH.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if not line or today not in line:
                continue
            # Try full timestamp parse
            m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
            if not m:
                continue
            try:
                ts = IST.localize(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                continue

            # Strip timestamp + level + module prefix to get clean message
            msg = line[len(m.group(1)):].strip()
            msg = re.sub(r"^\s*\[?\w+\]?\s*", "", msg).strip()  # strip [LEVEL]
            msg = re.sub(r"^[\w.]+\s*[—\-]+\s*", "", msg).strip()  # strip module

            if not msg:
                continue

            cat, icon = _classify_log_line(msg)
            # Skip pure DEBUG/trace noise
            if cat == "INFO" and re.search(r"DEBUG|debug|heartbeat|polling", line, re.I):
                continue

            events.append(_make_event(ts, cat, msg, icon))
    except Exception:
        pass
    return events


# ── Decision log parser ──────────────────────────────────────────────────────

_DEC_TS_RE = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) IST\]\s+(\w+)")

def _parse_decision_log(today: str) -> list[dict]:
    events: list[dict] = []
    dec_path = _DEC_DIR / f"decisions_{today}.log"
    if not dec_path.exists():
        return events
    try:
        text = dec_path.read_text(encoding="utf-8", errors="replace")
        # Split into blocks at separator lines
        blocks = re.split(r"={60,}", text)
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            m = _DEC_TS_RE.search(block)
            if not m:
                continue
            try:
                ts = IST.localize(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                continue
            event_type = m.group(2)

            # Map decision type → category + summary
            if event_type == "MARKET_BIAS":
                bias_m = re.search(r"Bias determined\s*:\s*(.+)", block)
                bias = bias_m.group(1).strip() if bias_m else "?"
                text_out = f"Market bias: {bias}"
                cat = "LIFECYCLE"
            elif event_type == "SCAN_RESULT":
                cand_m = re.search(r"Candidates found\s*:\s*(\d+)", block)
                scan_m = re.search(r"Universe scanned\s*:\s*(\d+)", block)
                n = cand_m.group(1) if cand_m else "?"
                total = scan_m.group(1) if scan_m else "?"
                text_out = f"{n} gap candidates found (scanned {total} stocks)"
                cat = "SCAN"
            elif event_type == "WATCHLIST_ENTRY":
                sym_m = re.search(r"WATCHLIST_ENTRY -- (\S+)", block)
                strat_m = re.search(r"Strategy\s*:\s*(.+)", block)
                sym = sym_m.group(1) if sym_m else "?"
                strat = strat_m.group(1).strip() if strat_m else "?"
                text_out = f"Watchlist: {sym} → {strat}"
                cat = "SCAN"
            elif event_type == "BUY_DECISION":
                sym_m = re.search(r"BUY_DECISION -- (\S+)", block)
                price_m = re.search(r"Entry price\s*:\s*Rs([\d.]+)", block)
                qty_m = re.search(r"Qty\s*:\s*(\d+)", block)
                strat_m = re.search(r"Strategy\s*:\s*(.+)", block)
                sym = sym_m.group(1) if sym_m else "?"
                price = price_m.group(1) if price_m else "?"
                qty = qty_m.group(1) if qty_m else "?"
                strat = strat_m.group(1).strip() if strat_m else "?"
                text_out = f"BUY {sym} x{qty} @ ₹{price} ({strat})"
                cat = "TRADE"
            elif event_type == "SELL_DECISION":
                sym_m = re.search(r"SELL_DECISION -- (\S+)", block)
                reason_m = re.search(r"Exit reason\s*:\s*(.+)", block)
                exit_p_m = re.search(r"Exit price\s*:\s*Rs([\d.]+)", block)
                pnl_m = re.search(r"Net P&L\s*:\s*Rs([+\-]?[\d.]+)", block)
                sym = sym_m.group(1) if sym_m else "?"
                reason = reason_m.group(1).strip() if reason_m else "?"
                exit_p = exit_p_m.group(1) if exit_p_m else "?"
                pnl = pnl_m.group(1) if pnl_m else "?"
                text_out = f"SELL {sym} @ ₹{exit_p} | Net ₹{pnl} ({reason})"
                cat = "TRADE"
            elif event_type == "PARTIAL_EXIT":
                sym_m = re.search(r"PARTIAL_EXIT -- (\S+)", block)
                pnl_m = re.search(r"P&L on exit\s*:\s*Rs([+\-]?[\d.]+)", block)
                sym = sym_m.group(1) if sym_m else "?"
                pnl = pnl_m.group(1) if pnl_m else "?"
                text_out = f"PARTIAL EXIT {sym} | P&L ₹{pnl}"
                cat = "TRADE"
            elif event_type == "SL_UPDATE":
                sym_m = re.search(r"SL_UPDATE -- (\S+)", block)
                new_m = re.search(r"New stop loss\s*:\s*Rs([\d.]+)", block)
                sym = sym_m.group(1) if sym_m else "?"
                new_sl = new_m.group(1) if new_m else "?"
                text_out = f"Trailing SL → {sym} new SL ₹{new_sl}"
                cat = "RISK"
            elif event_type == "REVIEW_COMPLETE":
                verdict_m = re.search(r"Verdict\s*:\s*(.+)", block)
                verdict = verdict_m.group(1).strip() if verdict_m else "?"
                text_out = f"Post-market review: {verdict}"
                cat = "REVIEW"
            elif event_type == "SESSION_START" or "SESSION START" in block:
                text_out = "Trading session started"
                cat = "LIFECYCLE"
            elif event_type == "SESSION_END" or "SESSION END" in block:
                pnl_m = re.search(r"Daily P&L\s+Rs([+\-]?[\d.]+)", block)
                pnl = pnl_m.group(1) if pnl_m else "?"
                text_out = f"Session ended | Daily P&L ₹{pnl}"
                cat = "LIFECYCLE"
            else:
                # Unknown decision type — include as INFO
                first_line = block.splitlines()[1].strip() if len(block.splitlines()) > 1 else block[:80]
                text_out = first_line
                cat = "INFO"

            events.append(_make_event(ts, cat, text_out))
    except Exception:
        pass
    return events


# ── DB trade events ──────────────────────────────────────────────────────────

def _parse_db_trades(today: str) -> list[dict]:
    """Read today's closed trades from the DB and generate trade events."""
    events: list[dict] = []
    if not _DB_PATH.exists():
        return events
    try:
        conn = sqlite3.connect(_DB_PATH, timeout=3.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        rows = conn.execute(
            "SELECT * FROM trades WHERE exit_time LIKE ? ORDER BY exit_time",
            (f"{today}%",),
        ).fetchall()
        conn.close()
        for r in rows:
            try:
                ts_str = r["exit_time"][:19]
                ts = IST.localize(datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S"))
            except Exception:
                continue
            pnl = r["net_pnl"]
            pnl_str = f"{'+'if pnl>=0 else ''}{pnl:,.0f}"
            reason = r.get("exit_reason", "")
            text_out = (
                f"{'SELL' if pnl < 0 else 'SOLD'} {r['symbol']} "
                f"x{r['qty']} @ ₹{r['exit_price']:,.2f} "
                f"| Net ₹{pnl_str} ({reason})"
            )
            events.append(_make_event(ts, "TRADE", text_out))
    except Exception:
        pass
    return events


# ── Scheduler job lifecycle events (synthetic if only logs missing) ──────────

_SCHED_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?"
    r"(upstox_auth|pre_market|run_pre_market|provisional_scan|run_provisional|"
    r"confirm_watchlist|run_confirm|morning_briefing|market_session|post_market|"
    r"force_squareoff|HALT|BUY |SELL |PARTIAL)",
    re.I
)

# ── Public API ───────────────────────────────────────────────────────────────

def get_timeline(today: str | None = None) -> list[dict]:
    """
    Return a sorted list of event dicts for today's activity timeline.

    Safe to call at any time — missing files produce empty lists.
    De-duplicates events that appear in both nexus.log and decision log.
    """
    if today is None:
        today = _today()

    events: list[dict] = []

    # 1. Parse main nexus.log
    events.extend(_parse_nexus_log(today))

    # 2. Parse decision log (more structured)
    dec_events = _parse_decision_log(today)

    # De-duplicate: if decision log has a BUY/SELL for a symbol within ±2s of
    # a nexus.log event, prefer the decision-log version (richer).
    dec_texts = {e["text"] for e in dec_events}
    filtered_main = []
    for e in events:
        # Keep event if it's not a trade or not redundant
        if e["category"] not in ("TRADE",):
            filtered_main.append(e)
            continue
        # Check if decision log has a richer event nearby
        dup = False
        for de in dec_events:
            if abs((e["sort_key"] - de["sort_key"]).total_seconds()) <= 5:
                if e["category"] == de["category"]:
                    dup = True
                    break
        if not dup:
            filtered_main.append(e)

    events = filtered_main + dec_events

    # 3. Merge DB trade events (avoid duplicates already covered by decision log)
    if not dec_events:
        events.extend(_parse_db_trades(today))

    # 4. Sort chronologically
    events.sort(key=lambda x: x["sort_key"])

    # 5. Drop sort_key (not JSON-safe) — keep only display fields
    for e in events:
        e.pop("sort_key", None)

    # Limit to last 200 events for display
    return events[-200:]


# ── HTML renderer ────────────────────────────────────────────────────────────

def render_timeline_html(events: list[dict] | None = None) -> str:
    """Render the activity timeline as an HTML fragment (no outer card)."""
    if events is None:
        events = get_timeline()

    if not events:
        return '<div class="tl-empty">No activity yet today. Waiting for market open...</div>'

    parts: list[str] = []
    for e in events:
        cat_cls = e.get("cat_class", "cat-info")
        icon = e.get("icon", "•")
        time_str = e.get("time", "")
        text = e.get("text", "")
        # HTML-escape text
        import html
        text_esc = html.escape(text)
        parts.append(
            f'<div class="tl-row {cat_cls}">'
            f'<span class="tl-time">{time_str}</span>'
            f'<span class="tl-icon">{icon}</span>'
            f'<span class="tl-text">{text_esc}</span>'
            f'</div>'
        )
    return "\n".join(parts)
