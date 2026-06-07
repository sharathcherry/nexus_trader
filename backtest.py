from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from config import config
from execution.backtester import NexusBacktester
from utils.logger import setup_logger

logger = setup_logger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="nexus_trader — NSE intraday paper trading backtester"
    )
    parser.add_argument("--start", required=True, metavar="YYYY-MM-DD",
                        help="Backtest start date (inclusive)")
    parser.add_argument("--end", required=True, metavar="YYYY-MM-DD",
                        help="Backtest end date (inclusive)")
    parser.add_argument("--capital", type=float, default=None,
                        help=f"Starting capital in INR (default: {config.CAPITAL:,.0f})")
    return parser.parse_args()


def validate_dates(start_str: str, end_str: str) -> tuple[datetime, datetime]:
    try:
        start = datetime.strptime(start_str, "%Y-%m-%d")
        end = datetime.strptime(end_str, "%Y-%m-%d")
    except ValueError as e:
        print(f"Error: Invalid date format — {e}. Use YYYY-MM-DD.", file=sys.stderr)
        sys.exit(1)
    if start > end:
        print(f"Error: --start {start_str} must be before or equal to --end {end_str}.", file=sys.stderr)
        sys.exit(1)
    return start, end


def print_banner() -> None:
    print()
    print("  nexus_trader — Backtest Engine")
    print("  Rule-based daily OHLC simulation | NSE Nifty 100")
    print()


def _print_report(results: dict) -> None:
    from tabulate import tabulate

    summary_rows = [
        ["Total Trades", str(results["total_trades"])],
        ["Win Rate", f"{results['win_rate']:.1%}"],
        ["Total Net P&L", f"₹{results['total_net_pnl']:,.2f}"],
        ["Total Return", f"{results['total_return_pct']:.2%}"],
        ["Sharpe Ratio", f"{results['sharpe_ratio']:.3f}"],
        ["Max Drawdown", f"{results['max_drawdown_pct']:.2%}"],
        ["Profit Factor", f"{results['profit_factor']:.2f}" if results['profit_factor'] != float('inf') else "∞"],
    ]
    print(tabulate(summary_rows, headers=["Metric", "Value"], tablefmt="rounded_outline"))

    monthly = results.get("monthly_returns", [])
    if monthly:
        monthly_rows = [[m["month"], m["trades"], f"₹{m['pnl']:,.2f}"] for m in monthly]
        print()
        print(tabulate(monthly_rows, headers=["Month", "Trades", "Net P&L"], tablefmt="rounded_outline"))


def _save_results(results: dict, start_str: str, end_str: str, capital: float) -> None:
    Path("logs/backtest").mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = Path("logs/backtest") / f"backtest_{ts}.json"
    payload = {**results, "start_date": start_str, "end_date": end_str, "capital": capital}
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    logger.info("Results saved to %s", filepath)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args()
    print_banner()
    validate_dates(args.start, args.end)

    capital = args.capital if args.capital is not None else config.CAPITAL
    bt = NexusBacktester(start_date=args.start, end_date=args.end, capital=capital)

    logger.info("Running backtest %s → %s, capital=₹%.0f", args.start, args.end, capital)
    results = bt.run()
    _print_report(results)
    _save_results(results, args.start, args.end, capital)


if __name__ == "__main__":
    main()
