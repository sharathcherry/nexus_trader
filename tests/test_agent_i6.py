"""
Tests for AgentI6 — stateful position monitor (AGNT-12).

portfolio.sell() signature:         sell(symbol, exit_price, qty, exit_reason)
portfolio.partial_exit() signature: partial_exit(symbol, exit_price, exit_qty, exit_reason)
portfolio.update_stop_loss():       update_stop_loss(symbol, new_stop_loss)
"""
import datetime

import pytz
import pytest
from unittest.mock import MagicMock

from agents.agent_i6 import AgentI6
from tests.helpers import make_candles, make_entry, mock_portfolio_factory

IST = pytz.timezone("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_ist(hour: int, minute: int) -> datetime.datetime:
    return datetime.datetime.now(IST).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )


def _make_position(
    symbol: str,
    entry_price: float,
    stop_loss: float,
    target: float,
    strategy: str,
    qty: int = 5,
    partial_exited: bool = False,
) -> dict:
    return {
        "symbol": symbol,
        "entry_price": entry_price,
        "qty": qty,
        "stop_loss": stop_loss,
        "target": target,
        "strategy": strategy,
        "entry_time": "2026-06-06 09:30:00",
        "partial_exited": partial_exited,
    }


# ---------------------------------------------------------------------------
# Circuit detection
# ---------------------------------------------------------------------------

class TestCircuitDetection:
    def test_circuit_detection(self):
        """Three polling cycles with identical price -> symbol added to circuit_set."""
        agent = AgentI6()
        circuit_set = set()

        sym = "RELIANCE.NS"
        pos = _make_position(sym, 1480, 1465, 1510, "GAP_AND_GO", qty=5)
        portfolio = mock_portfolio_factory(positions=[pos])
        portfolio._get_position.return_value = None   # skip trailing SL cleanly

        # Price below partial-exit threshold (1495) and below trail threshold (1500)
        # so only circuit detection logic runs.
        candles_map = {sym: make_candles([1490.0])}
        watchlist_map = {sym: make_entry(sym, "GAP_AND_GO", 1480, 1465, 1510, atr=20.0)}

        for _ in range(3):
            agent.monitor_positions(
                portfolio, watchlist_map, candles_map, _now_ist(10, 0), circuit_set
            )

        assert sym in circuit_set

    def test_circuit_skip_on_subsequent_call(self):
        """Symbol already in circuit_set -> portfolio.sell NOT called."""
        agent = AgentI6()
        sym = "RELIANCE.NS"
        circuit_set = {sym}   # pre-populated

        pos = _make_position(sym, 1480, 1465, 1510, "GAP_AND_GO", qty=5)
        portfolio = mock_portfolio_factory(positions=[pos])

        candles_map = {sym: make_candles([1460.0])}
        watchlist_map = {sym: make_entry(sym, "GAP_AND_GO", 1480, 1465, 1510)}

        agent.monitor_positions(
            portfolio, watchlist_map, candles_map, _now_ist(10, 0), circuit_set
        )

        portfolio.sell.assert_not_called()


# ---------------------------------------------------------------------------
# Hard exits
# ---------------------------------------------------------------------------

class TestHardExits:
    def test_hard_exit_sl_hit(self):
        """Price <= stop_loss -> sell called with reason SL_HIT."""
        agent = AgentI6()
        sym = "RELIANCE.NS"
        circuit_set = set()

        pos = _make_position(sym, 1480, 1465, 1510, "GAP_AND_GO", qty=5)
        portfolio = mock_portfolio_factory(positions=[pos])

        candles_map = {sym: make_candles([1460.0])}
        watchlist_map = {sym: make_entry(sym, "GAP_AND_GO", 1480, 1465, 1510)}

        agent.monitor_positions(
            portfolio, watchlist_map, candles_map, _now_ist(10, 0), circuit_set
        )

        portfolio.sell.assert_called_once_with(sym, 1460.0, 5, "SL_HIT")

    def test_hard_exit_target_hit(self):
        """Price >= target -> sell called with reason TARGET_HIT."""
        agent = AgentI6()
        sym = "RELIANCE.NS"
        circuit_set = set()

        pos = _make_position(sym, 1480, 1465, 1510, "GAP_AND_GO", qty=5)
        portfolio = mock_portfolio_factory(positions=[pos])

        candles_map = {sym: make_candles([1515.0])}
        watchlist_map = {sym: make_entry(sym, "GAP_AND_GO", 1480, 1465, 1510)}

        agent.monitor_positions(
            portfolio, watchlist_map, candles_map, _now_ist(10, 0), circuit_set
        )

        portfolio.sell.assert_called_once_with(sym, 1515.0, 5, "TARGET_HIT")

    def test_no_hard_exit_normal_price(self):
        """Price strictly between SL and target -> sell NOT called."""
        agent = AgentI6()
        sym = "RELIANCE.NS"
        circuit_set = set()

        pos = _make_position(sym, 1480, 1465, 1510, "GAP_AND_GO", qty=5)
        portfolio = mock_portfolio_factory(positions=[pos])
        portfolio._get_position.return_value = None   # skip trailing SL

        candles_map = {sym: make_candles([1490.0])}
        watchlist_map = {sym: make_entry(sym, "GAP_AND_GO", 1480, 1465, 1510)}

        agent.monitor_positions(
            portfolio, watchlist_map, candles_map, _now_ist(10, 0), circuit_set
        )

        portfolio.sell.assert_not_called()


# ---------------------------------------------------------------------------
# Partial exits
# ---------------------------------------------------------------------------
# entry_price=1480, original_sl (from WatchlistEntry)=1465, risk=15,
# partial_exit_threshold = entry_price + risk = 1480 + 15 = 1495
# exit_qty = qty // 2 = 10 // 2 = 5

class TestPartialExits:
    def _run(self, strategy: str, current_price: float, partial_exited: bool):
        agent = AgentI6()
        sym = "TEST.NS"
        circuit_set = set()

        pos = _make_position(sym, 1480, 1465, 1600, strategy,
                             qty=10, partial_exited=partial_exited)
        portfolio = mock_portfolio_factory(positions=[pos])
        portfolio._get_position.return_value = pos

        candles_map = {sym: make_candles([current_price])}
        watchlist_map = {sym: make_entry(sym, strategy, 1480, 1465, 1600, atr=20.0)}

        agent.monitor_positions(
            portfolio, watchlist_map, candles_map, _now_ist(10, 0), circuit_set
        )
        return portfolio, sym

    def test_partial_exit_gap_and_go(self):
        """GAP_AND_GO: price=1496 >= threshold=1495, not yet partial_exited -> called."""
        portfolio, sym = self._run("GAP_AND_GO", 1496.0, partial_exited=False)
        portfolio.partial_exit.assert_called_once_with(sym, 1496.0, 5, "PARTIAL_EXIT")

    def test_partial_exit_gap_and_go_already_done(self):
        """GAP_AND_GO: partial_exited=True -> partial_exit NOT called again."""
        portfolio, sym = self._run("GAP_AND_GO", 1496.0, partial_exited=True)
        portfolio.partial_exit.assert_not_called()

    def test_partial_exit_orb_breakout(self):
        """ORB_BREAKOUT: price=1496 >= threshold=1495, not yet partial_exited -> called."""
        portfolio, sym = self._run("ORB_BREAKOUT", 1496.0, partial_exited=False)
        portfolio.partial_exit.assert_called_once_with(sym, 1496.0, 5, "PARTIAL_EXIT")

    def test_no_partial_exit_gap_fill(self):
        """GAP_FILL strategy -> partial_exit NOT called regardless of price."""
        portfolio, _ = self._run("GAP_FILL", 1496.0, partial_exited=False)
        portfolio.partial_exit.assert_not_called()

    def test_no_partial_exit_vwap_reclaim(self):
        """VWAP_RECLAIM strategy -> partial_exit NOT called."""
        portfolio, _ = self._run("VWAP_RECLAIM", 1496.0, partial_exited=False)
        portfolio.partial_exit.assert_not_called()


# ---------------------------------------------------------------------------
# Trailing stop loss
# ---------------------------------------------------------------------------

class TestTrailingStopLoss:
    def test_trailing_sl_gap_and_go_triggered(self):
        """
        GAP_AND_GO: price=1505 >= entry(1480) + atr(20) = 1500 -> trail fires.
        new_sl = 1505 - 0.75*20 = 1490; current_sl=1465 -> update_stop_loss(sym, 1490).
        """
        agent = AgentI6()
        sym = "RELIANCE.NS"
        circuit_set = set()

        pos = _make_position(sym, 1480, 1465, 1600, "GAP_AND_GO", qty=5,
                             partial_exited=False)
        portfolio = mock_portfolio_factory(positions=[pos])
        portfolio._get_position.return_value = pos

        candles_map = {sym: make_candles([1505.0])}
        watchlist_map = {sym: make_entry(sym, "GAP_AND_GO", 1480, 1465, 1600, atr=20.0)}

        agent.monitor_positions(
            portfolio, watchlist_map, candles_map, _now_ist(10, 0), circuit_set
        )

        portfolio.update_stop_loss.assert_called_once_with(sym, 1490.0)

    def test_trailing_sl_gap_and_go_not_triggered_below_threshold(self):
        """price=1498 < 1500 -> profit threshold not met -> update_stop_loss NOT called."""
        agent = AgentI6()
        sym = "RELIANCE.NS"
        circuit_set = set()

        pos = _make_position(sym, 1480, 1465, 1600, "GAP_AND_GO", qty=5,
                             partial_exited=False)
        portfolio = mock_portfolio_factory(positions=[pos])
        portfolio._get_position.return_value = pos

        candles_map = {sym: make_candles([1498.0])}
        watchlist_map = {sym: make_entry(sym, "GAP_AND_GO", 1480, 1465, 1600, atr=20.0)}

        agent.monitor_positions(
            portfolio, watchlist_map, candles_map, _now_ist(10, 0), circuit_set
        )

        portfolio.update_stop_loss.assert_not_called()

    def test_trailing_sl_gap_and_go_no_downgrade(self):
        """
        new_sl=1490, but current_sl=1491 (new_sl <= current) -> update_stop_loss NOT called.
        atr=20, price=1505 -> new_sl = 1505 - 15 = 1490. Set current_sl=1491.
        """
        agent = AgentI6()
        sym = "RELIANCE.NS"
        circuit_set = set()

        pos = _make_position(sym, 1480, 1491, 1600, "GAP_AND_GO", qty=5,
                             partial_exited=False)
        portfolio = mock_portfolio_factory(positions=[pos])
        portfolio._get_position.return_value = pos

        candles_map = {sym: make_candles([1505.0])}
        watchlist_map = {sym: make_entry(sym, "GAP_AND_GO", 1480, 1465, 1600, atr=20.0)}

        agent.monitor_positions(
            portfolio, watchlist_map, candles_map, _now_ist(10, 0), circuit_set
        )

        portfolio.update_stop_loss.assert_not_called()

    def test_orb_breakeven_sl(self):
        """
        ORB_BREAKOUT, partial_exited=True, entry_price=1480, current_sl=1465.
        entry_price(1480) > current_sl(1465) -> update_stop_loss(sym, 1480) called.
        """
        agent = AgentI6()
        sym = "ORB.NS"
        circuit_set = set()

        pos = _make_position(sym, 1480, 1465, 1600, "ORB_BREAKOUT", qty=5,
                             partial_exited=True)
        portfolio = mock_portfolio_factory(positions=[pos])
        portfolio._get_position.return_value = pos

        candles_map = {sym: make_candles([1490.0])}
        watchlist_map = {sym: make_entry(sym, "ORB_BREAKOUT", 1480, 1465, 1600, atr=15.0)}

        agent.monitor_positions(
            portfolio, watchlist_map, candles_map, _now_ist(10, 0), circuit_set
        )

        portfolio.update_stop_loss.assert_called_once_with(sym, 1480)

    def test_gap_fill_fixed_sl(self):
        """GAP_FILL -> update_stop_loss NOT called regardless of price."""
        agent = AgentI6()
        sym = "FILL.NS"
        circuit_set = set()

        pos = _make_position(sym, 1480, 1465, 1510, "GAP_FILL", qty=5)
        portfolio = mock_portfolio_factory(positions=[pos])
        portfolio._get_position.return_value = pos

        candles_map = {sym: make_candles([1490.0])}
        watchlist_map = {sym: make_entry(sym, "GAP_FILL", 1480, 1465, 1510, atr=10.0)}

        agent.monitor_positions(
            portfolio, watchlist_map, candles_map, _now_ist(10, 0), circuit_set
        )

        portfolio.update_stop_loss.assert_not_called()

    def test_vwap_reclaim_fixed_sl(self):
        """VWAP_RECLAIM -> update_stop_loss NOT called."""
        agent = AgentI6()
        sym = "VWAP.NS"
        circuit_set = set()

        pos = _make_position(sym, 1480, 1465, 1510, "VWAP_RECLAIM", qty=5)
        portfolio = mock_portfolio_factory(positions=[pos])
        portfolio._get_position.return_value = pos

        candles_map = {sym: make_candles([1490.0])}
        watchlist_map = {sym: make_entry(sym, "VWAP_RECLAIM", 1480, 1465, 1510, atr=10.0)}

        agent.monitor_positions(
            portfolio, watchlist_map, candles_map, _now_ist(10, 0), circuit_set
        )

        portfolio.update_stop_loss.assert_not_called()
