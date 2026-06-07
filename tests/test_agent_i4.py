"""
Tests for AgentI4 - signal engine (AGNT-09, AGNT-10, AGNT-11).

Covers:
  - __init__ state setup
  - _fetch_batch: single vs multi ticker, rate limit sleep
  - _maybe_apply_orb_override: fires once, respects time gate
  - force_squareoff_all: idempotency
  - _check_entries: time gates, 4 strategy signals, symbol removal, circuit skip
"""
from __future__ import annotations

import datetime
import asyncio
from unittest.mock import MagicMock, patch

import pandas as pd
import pytz
import pytest

from agents.agent_i4 import AgentI4
from tests.helpers import make_candles, make_entry, mock_portfolio_factory

IST = pytz.timezone("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_ist(hour: int, minute: int) -> datetime.datetime:
    return datetime.datetime.now(IST).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )


def _make_agent(strategies=None):
    """Return an AgentI4 with a minimal watchlist."""
    if strategies is None:
        strategies = [("RELIANCE.NS", "GAP_AND_GO", 1480, 1465, 1510)]
    watchlist = [
        make_entry(sym, strat, trig, sl, tgt)
        for sym, strat, trig, sl, tgt in strategies
    ]
    return AgentI4(watchlist)


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestInit:
    def test_watchlist_map_keyed_by_symbol(self):
        """watchlist_map is a dict keyed by symbol."""
        agent = _make_agent([("RELIANCE.NS", "GAP_AND_GO", 1480, 1465, 1510)])
        assert "RELIANCE.NS" in agent.watchlist_map

    def test_initial_flags(self):
        """_squaredoff, _orb_set start False; circuit_set starts empty."""
        agent = _make_agent()
        assert agent._squaredoff is False
        assert agent._orb_set is False
        assert agent.circuit_set == set()

    def test_monitor_is_agent_i6(self):
        """monitor attribute is an AgentI6 instance."""
        from agents.agent_i6 import AgentI6
        agent = _make_agent()
        assert isinstance(agent.monitor, AgentI6)


# ---------------------------------------------------------------------------
# _fetch_batch
# ---------------------------------------------------------------------------

class TestFetchBatch:
    def test_empty_symbols_returns_empty_dict(self):
        agent = _make_agent()
        result = agent._fetch_batch([])
        assert result == {}

    @patch("agents.agent_i4.time.sleep")
    @patch("agents.agent_i4.yf.download")
    def test_sleep_called_before_download(self, mock_dl, mock_sleep):
        """Rate-limit guard: time.sleep(0.2) always called before download."""
        mock_dl.return_value = pd.DataFrame()
        agent = _make_agent()
        agent._fetch_batch(["RELIANCE.NS"])
        mock_sleep.assert_called_once_with(0.2)

    @patch("agents.agent_i4.time.sleep")
    @patch("agents.agent_i4.yf.download")
    def test_single_ticker_returns_flat_df(self, mock_dl, mock_sleep):
        """Single ticker: returned DataFrame is stored directly (no .xs)."""
        df = make_candles([1480.0, 1490.0])
        mock_dl.return_value = df
        agent = _make_agent()
        result = agent._fetch_batch(["RELIANCE.NS"])
        assert "RELIANCE.NS" in result
        assert not result["RELIANCE.NS"].empty

    @patch("agents.agent_i4.time.sleep")
    @patch("agents.agent_i4.yf.download")
    def test_empty_download_returns_empty_dfs(self, mock_dl, mock_sleep):
        """Empty download result maps each symbol to an empty DataFrame."""
        mock_dl.return_value = pd.DataFrame()
        agent = _make_agent()
        result = agent._fetch_batch(["RELIANCE.NS", "TCS.NS"])
        assert result["RELIANCE.NS"].empty
        assert result["TCS.NS"].empty


# ---------------------------------------------------------------------------
# _maybe_apply_orb_override
# ---------------------------------------------------------------------------

class TestOrbOverride:
    def _orb_agent(self):
        return _make_agent([("TCS.NS", "ORB_BREAKOUT", 3500, 3450, 3600)])

    def test_does_not_fire_before_0930(self):
        """ORB override must not run before 09:30 IST."""
        agent = self._orb_agent()
        df = make_candles([3500.0, 3510.0, 3520.0])
        candles_map = {"TCS.NS": df}
        agent._maybe_apply_orb_override(candles_map, _now_ist(9, 15))
        assert agent._orb_set is False

    def test_fires_at_0930(self):
        """ORB override fires and sets _orb_set at exactly 09:30."""
        agent = self._orb_agent()
        df = make_candles([3500.0, 3510.0, 3520.0])
        candles_map = {"TCS.NS": df}
        with patch("agents.agent_i4.Indicators.orb", return_value=(3525.0, 3490.0)):
            agent._maybe_apply_orb_override(candles_map, _now_ist(9, 30))
        assert agent._orb_set is True

    def test_fires_only_once(self):
        """Second call after _orb_set=True is a no-op."""
        agent = self._orb_agent()
        df = make_candles([3500.0, 3510.0, 3520.0])
        candles_map = {"TCS.NS": df}
        with patch("agents.agent_i4.Indicators.orb", return_value=(3525.0, 3490.0)) as mock_orb:
            agent._maybe_apply_orb_override(candles_map, _now_ist(9, 30))
            agent._maybe_apply_orb_override(candles_map, _now_ist(9, 31))
        assert mock_orb.call_count == 1

    def test_updates_entry_trigger(self):
        """entry_trigger is updated to orb_high."""
        agent = self._orb_agent()
        original_trigger = agent.watchlist_map["TCS.NS"].entry_trigger
        df = make_candles([3500.0, 3510.0, 3520.0])
        candles_map = {"TCS.NS": df}
        with patch("agents.agent_i4.Indicators.orb", return_value=(3600.0, 3450.0)):
            agent._maybe_apply_orb_override(candles_map, _now_ist(9, 30))
        assert agent.watchlist_map["TCS.NS"].entry_trigger == 3600.0
        assert agent.watchlist_map["TCS.NS"].entry_trigger != original_trigger


# ---------------------------------------------------------------------------
# force_squareoff_all
# ---------------------------------------------------------------------------

class TestForceSquareoff:
    def test_calls_sell_for_each_position(self):
        """Sell is called once per open position."""
        agent = _make_agent()
        positions = [
            {"symbol": "RELIANCE.NS", "entry_price": 1480, "qty": 5},
            {"symbol": "TCS.NS",      "entry_price": 3500, "qty": 2},
        ]
        portfolio = mock_portfolio_factory(positions=positions)
        agent.force_squareoff_all(portfolio, {})
        assert portfolio.sell.call_count == 2

    def test_uses_current_price_if_available(self):
        """Exit price comes from current_prices dict when present."""
        agent = _make_agent()
        pos = {"symbol": "RELIANCE.NS", "entry_price": 1480, "qty": 5}
        portfolio = mock_portfolio_factory(positions=[pos])
        agent.force_squareoff_all(portfolio, {"RELIANCE.NS": 1500.0})
        call_args = portfolio.sell.call_args[0]
        assert call_args[1] == 1500.0

    def test_falls_back_to_entry_price(self):
        """Falls back to entry_price when symbol not in current_prices."""
        agent = _make_agent()
        pos = {"symbol": "RELIANCE.NS", "entry_price": 1480, "qty": 5}
        portfolio = mock_portfolio_factory(positions=[pos])
        agent.force_squareoff_all(portfolio, {})
        call_args = portfolio.sell.call_args[0]
        assert call_args[1] == 1480

    def test_idempotent_second_call_is_noop(self):
        """Second call to force_squareoff_all must not call sell again."""
        agent = _make_agent()
        pos = {"symbol": "RELIANCE.NS", "entry_price": 1480, "qty": 5}
        portfolio = mock_portfolio_factory(positions=[pos])
        agent.force_squareoff_all(portfolio, {})
        agent.force_squareoff_all(portfolio, {})
        assert portfolio.sell.call_count == 1


# ---------------------------------------------------------------------------
# _check_entries - time gates
# ---------------------------------------------------------------------------

class TestCheckEntriesTimeGates:
    def test_no_buy_before_0930(self):
        """Price at trigger before 09:30 -> no buy."""
        agent = _make_agent([("RELIANCE.NS", "GAP_AND_GO", 1480, 1465, 1510)])
        portfolio = mock_portfolio_factory()
        candles_map = {"RELIANCE.NS": make_candles([1490.0])}
        agent._check_entries(candles_map, portfolio, _now_ist(9, 15), None)
        portfolio.buy.assert_not_called()

    def test_no_buy_after_1400(self):
        """Price at trigger after 14:00 -> no buy."""
        agent = _make_agent([("RELIANCE.NS", "GAP_AND_GO", 1480, 1465, 1510)])
        portfolio = mock_portfolio_factory()
        candles_map = {"RELIANCE.NS": make_candles([1490.0])}
        agent._check_entries(candles_map, portfolio, _now_ist(14, 1), None)
        portfolio.buy.assert_not_called()

    def test_buy_allowed_at_0930(self):
        """Price at trigger exactly at 09:30 -> buy attempted."""
        agent = _make_agent([("RELIANCE.NS", "GAP_AND_GO", 1480, 1465, 1510)])
        portfolio = mock_portfolio_factory()
        candles_map = {"RELIANCE.NS": make_candles([1490.0])}
        agent._check_entries(candles_map, portfolio, _now_ist(9, 30), None)
        portfolio.buy.assert_called_once()

    def test_buy_allowed_at_1400(self):
        """Price at trigger exactly at 14:00 -> buy attempted."""
        agent = _make_agent([("RELIANCE.NS", "GAP_AND_GO", 1480, 1465, 1510)])
        portfolio = mock_portfolio_factory()
        candles_map = {"RELIANCE.NS": make_candles([1490.0])}
        agent._check_entries(candles_map, portfolio, _now_ist(14, 0), None)
        portfolio.buy.assert_called_once()


# ---------------------------------------------------------------------------
# _check_entries - signal conditions
# ---------------------------------------------------------------------------

class TestCheckEntriesSignals:
    """Each strategy fires when price crosses the trigger in the correct direction."""

    def _run(self, strategy, trig, sl, tgt, price):
        agent = _make_agent([("SYM.NS", strategy, trig, sl, tgt)])
        portfolio = mock_portfolio_factory()
        candles_map = {"SYM.NS": make_candles([price])}
        agent._check_entries(candles_map, portfolio, _now_ist(10, 0), None)
        return portfolio.buy

    def test_gap_and_go_fires_at_or_above_trigger(self):
        """GAP_AND_GO: price >= trigger -> buy."""
        mock_buy = self._run("GAP_AND_GO", 1480, 1465, 1510, 1480.0)
        mock_buy.assert_called_once()

    def test_gap_and_go_no_signal_below_trigger(self):
        """GAP_AND_GO: price < trigger -> no buy."""
        mock_buy = self._run("GAP_AND_GO", 1480, 1465, 1510, 1479.0)
        mock_buy.assert_not_called()

    def test_orb_breakout_fires_at_or_above_trigger(self):
        """ORB_BREAKOUT: price >= trigger -> buy."""
        mock_buy = self._run("ORB_BREAKOUT", 3500, 3450, 3600, 3500.0)
        mock_buy.assert_called_once()

    def test_vwap_reclaim_fires_at_or_above_trigger(self):
        """VWAP_RECLAIM: price >= trigger -> buy."""
        mock_buy = self._run("VWAP_RECLAIM", 2000, 1970, 2060, 2000.0)
        mock_buy.assert_called_once()

    def test_gap_fill_fires_at_or_below_trigger(self):
        """GAP_FILL: price <= trigger -> buy."""
        mock_buy = self._run("GAP_FILL", 1450, 1430, 1410, 1450.0)
        mock_buy.assert_called_once()

    def test_gap_fill_no_signal_above_trigger(self):
        """GAP_FILL: price > trigger -> no buy."""
        mock_buy = self._run("GAP_FILL", 1450, 1430, 1410, 1455.0)
        mock_buy.assert_not_called()


# ---------------------------------------------------------------------------
# _check_entries - symbol removal and circuit skip
# ---------------------------------------------------------------------------

class TestCheckEntriesSymbolHandling:
    def test_symbol_removed_after_successful_buy(self):
        """Symbol added to bought_symbols after successful buy."""
        agent = _make_agent([("RELIANCE.NS", "GAP_AND_GO", 1480, 1465, 1510)])
        portfolio = mock_portfolio_factory()
        portfolio.buy.return_value = True
        candles_map = {"RELIANCE.NS": make_candles([1490.0])}
        agent._check_entries(candles_map, portfolio, _now_ist(10, 0), None)
        assert "RELIANCE.NS" in agent.bought_symbols

    def test_symbol_retained_after_failed_buy(self):
        """Symbol stays in watchlist_map when buy returns False."""
        agent = _make_agent([("RELIANCE.NS", "GAP_AND_GO", 1480, 1465, 1510)])
        portfolio = mock_portfolio_factory()
        portfolio.buy.return_value = False
        candles_map = {"RELIANCE.NS": make_candles([1490.0])}
        agent._check_entries(candles_map, portfolio, _now_ist(10, 0), None)
        assert "RELIANCE.NS" in agent.watchlist_map

    def test_circuit_symbol_skipped(self):
        """Symbol in circuit_set is not evaluated for entry."""
        agent = _make_agent([("RELIANCE.NS", "GAP_AND_GO", 1480, 1465, 1510)])
        agent.circuit_set.add("RELIANCE.NS")
        portfolio = mock_portfolio_factory()
        candles_map = {"RELIANCE.NS": make_candles([1490.0])}
        agent._check_entries(candles_map, portfolio, _now_ist(10, 0), None)
        portfolio.buy.assert_not_called()


# ---------------------------------------------------------------------------
# run method and force squareoff
# ---------------------------------------------------------------------------

class TestRunMethod:
    @pytest.mark.asyncio
    async def test_run_loop_terminates_and_calls_force_squareoff(self):
        """run() should exit the loop and call force_squareoff_all at session end."""
        agent = _make_agent([("RELIANCE.NS", "GAP_AND_GO", 1480, 1465, 1510)])
        portfolio = mock_portfolio_factory()
        portfolio.get_portfolio_summary.return_value = {"positions": []}
        portfolio.get_daily_report.return_value = {"trades": []}

        # Mock event
        event = asyncio.Event()
        event.set()

        # Mock _fetch_batch to avoid yfinance downloads in test
        agent._fetch_batch = MagicMock(return_value={"RELIANCE.NS": make_candles([1490.0])})

        # Mock datetime to return past 15:15
        mock_now = _now_ist(15, 20)
        with patch("agents.agent_i4.datetime.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now

            # Call run
            await agent.run([], portfolio, event)

        # Assert force_squareoff_all was called
        assert agent._squaredoff is True

