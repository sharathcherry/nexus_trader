"""
tests/test_agent_i9.py — Unit tests for AgentI9 (Phase 4c)

Covers AGNT-13 through AGNT-16.
All Claude API calls are mocked — no network required.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Shared sample data
# ---------------------------------------------------------------------------

SAMPLE_TRADES = [
    {
        "symbol": "RELIANCE.NS",
        "strategy": "GAP_AND_GO",
        "entry_price": 2800.0,
        "exit_price": 2850.0,
        "entry_time": "2026-06-06 09:35:00",
        "exit_time": "2026-06-06 11:20:00",
        "gross_pnl": 500.0,
        "brokerage": 20.0,
        "stt": 0.71,
        "exchange_charges": 0.17,
        "gst": 3.6,
        "total_charges": 24.48,
        "net_pnl": 475.52,
        "exit_reason": "TARGET",
    },
    {
        "symbol": "TCS.NS",
        "strategy": "ORB_BREAKOUT",
        "entry_price": 3500.0,
        "exit_price": 3460.0,
        "entry_time": "2026-06-06 09:40:00",
        "exit_time": "2026-06-06 10:55:00",
        "gross_pnl": -400.0,
        "brokerage": 20.0,
        "stt": 0.87,
        "exchange_charges": 0.21,
        "gst": 3.6,
        "total_charges": 24.68,
        "net_pnl": -424.68,
        "exit_reason": "STOP_LOSS",
    },
]

VALID_REVIEW_JSON = json.dumps(
    {
        "session_verdict": "LOSS",
        "winning_strategies": ["GAP_AND_GO"],
        "underperforming_strategies": ["ORB_BREAKOUT"],
        "parameter_adjustments": [],
        "tomorrow_watch": ["RELIANCE.NS", "INFY.NS"],
        "summary": "Mixed day: GAP_AND_GO delivered a winner but ORB_BREAKOUT hit stop loss.",
    }
)

ROLLING_STATS_EMPTY = {"strategy_breakdown": [], "totals": {}}

ROLLING_STATS_FULL = {
    "strategy_breakdown": [
        {
            "strategy": "GAP_AND_GO",
            "trade_count": 10,
            "avg_net_pnl": 250.5,
            "win_rate": 0.7,
        }
    ],
    "totals": {
        "total_trades": 10,
        "total_net_pnl": 2505.0,
        "win_rate_overall": 0.7,
    },
}


# ---------------------------------------------------------------------------
# Helpers: mock portfolio and mock stream context manager
# ---------------------------------------------------------------------------

def make_portfolio(trades=None):
    """Build a mock portfolio whose get_daily_report returns a dict with 'trades'."""
    portfolio = MagicMock()
    portfolio.get_daily_report.return_value = {
        "date": "2026-06-06",
        "total_trades": len(trades or []),
        "trades": trades or [],
    }
    return portfolio


def make_agent(portfolio=None, response_text=VALID_REVIEW_JSON, tmp_path=None,
               stream_text=None):  # stream_text kept for compat, ignored
    """
    Build an AgentI9 with a mocked Groq client.
    Groq uses a non-streaming chat.completions.create() call.
    """
    from agents.agent_i9 import AgentI9
    if portfolio is None:
        portfolio = make_portfolio(SAMPLE_TRADES)

    with patch("agents.agent_i9.Groq") as MockGroq:
        client = MagicMock()
        MockGroq.return_value = client

        # Build a mock response that looks like groq.types.chat.ChatCompletion
        mock_choice = MagicMock()
        mock_choice.message.content = response_text
        mock_usage = MagicMock()
        mock_usage.total_tokens = 700
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_resp.usage = mock_usage
        client.chat.completions.create.return_value = mock_resp

        agent = AgentI9(portfolio)
        agent._client = client
        return agent


# ---------------------------------------------------------------------------
# AGNT-13: Prompt construction
# ---------------------------------------------------------------------------

class TestPromptConstruction:
    """AGNT-13: _build_prompt must embed strategy names, symbols, and risk % form."""

    def test_prompt_construction(self):
        from agents.agent_i9 import AgentI9
        agent = make_agent()
        prompt = agent._build_prompt(SAMPLE_TRADES, ROLLING_STATS_FULL)
        assert "GAP_AND_GO" in prompt, "Expected GAP_AND_GO strategy in prompt"
        assert "RELIANCE.NS" in prompt, "Expected RELIANCE.NS symbol in prompt"
        assert "1.0%" in prompt, "Expected RISK_PER_TRADE_PCT in percentage form (1.0%)"

    def test_prompt_omit_times(self):
        from agents.agent_i9 import AgentI9
        agent = make_agent()
        prompt_with = agent._build_prompt(SAMPLE_TRADES, ROLLING_STATS_FULL, omit_times=False)
        prompt_without = agent._build_prompt(SAMPLE_TRADES, ROLLING_STATS_FULL, omit_times=True)
        assert "entry_time" in prompt_with
        assert "entry_time" not in prompt_without

    def test_prompt_no_trades(self):
        from agents.agent_i9 import AgentI9
        agent = make_agent()
        prompt = agent._build_prompt([], ROLLING_STATS_EMPTY)
        assert "No trades today" in prompt

    def test_prompt_data_delay_note(self):
        from agents.agent_i9 import AgentI9
        agent = make_agent()
        prompt = agent._build_prompt(SAMPLE_TRADES, ROLLING_STATS_FULL)
        assert "15-minute" in prompt or "15 min" in prompt, (
            "Prompt must include yfinance 15-minute delay note"
        )


# ---------------------------------------------------------------------------
# AGNT-13: Token cap / truncation
# ---------------------------------------------------------------------------

class TestTokenCapTruncation:
    """AGNT-13: Prompt truncation should log WARNING when needed."""

    def test_token_cap_truncation_warning(self, caplog):
        import logging
        from agents.agent_i9 import AgentI9, TOKEN_CAP, CHARS_PER_TOKEN

        agent = make_agent()

        # Produce a prompt that exceeds TOKEN_CAP by making rolling stats huge
        huge_stats = {
            "strategy_breakdown": [
                {
                    "strategy": f"STRAT_{i}",
                    "trade_count": 100,
                    "avg_net_pnl": 123.45,
                    "win_rate": 0.6,
                }
                for i in range(500)
            ],
            "totals": {
                "total_trades": 50000,
                "total_net_pnl": 999999.99,
                "win_rate_overall": 0.6,
            },
        }

        # Wire up Groq mock on the agent's already-set _client
        mock_choice = MagicMock()
        mock_choice.message.content = VALID_REVIEW_JSON
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]
        mock_resp.usage.total_tokens = 700
        agent._client.chat.completions.create.return_value = mock_resp

        with caplog.at_level(logging.WARNING, logger="agents.agent_i9"):
            with patch.object(agent, "_get_rolling_stats", return_value=huge_stats):
                call_count = {"n": 0}

                def fake_estimate(text):
                    call_count["n"] += 1
                    if call_count["n"] <= 3:
                        return TOKEN_CAP + 5000
                    return TOKEN_CAP - 100

                with patch.object(agent, "_estimate_tokens", side_effect=fake_estimate):
                    agent.run()

        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            any(kw in m.lower() for kw in ("token cap", "truncated", "trimmed", "dropped"))
            for m in warning_messages
        ), f"Expected truncation WARNING; got: {warning_messages}"


# ---------------------------------------------------------------------------
# AGNT-14: Parse valid response
# ---------------------------------------------------------------------------

class TestParseValidResponse:
    """AGNT-14: Successful stream with valid JSON should return a DailyReview."""

    def test_parse_valid_response(self, tmp_path):
        from agents.agent_i9 import AgentI9, DailyReview

        portfolio = make_portfolio(SAMPLE_TRADES)

        with patch("agents.agent_i9.Groq") as MockGroq:
            client = MagicMock()
            MockGroq.return_value = client
            mock_choice = MagicMock()
            mock_choice.message.content = VALID_REVIEW_JSON
            mock_resp = MagicMock()
            mock_resp.choices = [mock_choice]
            mock_resp.usage.total_tokens = 700
            client.chat.completions.create.return_value = mock_resp

            with patch("agents.agent_i9.PERF_DIR", tmp_path):
                agent = AgentI9(portfolio)
                agent._client = client

                with patch.object(agent, "_get_rolling_stats", return_value=ROLLING_STATS_FULL):
                    result = agent.run()

        assert isinstance(result, DailyReview), "Expected DailyReview instance on success"
        assert result.session_verdict == "LOSS"
        assert "GAP_AND_GO" in result.winning_strategies


# ---------------------------------------------------------------------------
# AGNT-14: Partial response saved on bad JSON
# ---------------------------------------------------------------------------

class TestPartialResponseSaved:
    """AGNT-14: Bad JSON from Claude should write partial + failed files."""

    def test_partial_response_saved(self, tmp_path):
        from agents.agent_i9 import AgentI9

        bad_json = "{ this is not valid JSON ..."
        portfolio = make_portfolio(SAMPLE_TRADES)

        with patch("agents.agent_i9.Groq") as MockGroq:
            client = MagicMock()
            MockGroq.return_value = client
            mock_choice = MagicMock()
            mock_choice.message.content = bad_json
            mock_resp = MagicMock()
            mock_resp.choices = [mock_choice]
            mock_resp.usage.total_tokens = 100
            client.chat.completions.create.return_value = mock_resp

            with patch("agents.agent_i9.PERF_DIR", tmp_path):
                agent = AgentI9(portfolio)
                agent._client = client

                with patch.object(agent, "_get_rolling_stats", return_value=ROLLING_STATS_EMPTY):
                    result = agent.run()

        assert result is None, "Partial state should return None"
        today_str = date.today().strftime("%Y%m%d")
        partial_file = tmp_path / f"review_partial_{today_str}.json"
        assert partial_file.exists(), "review_partial_*.json must be written"
        assert partial_file.read_text(encoding="utf-8") == bad_json


# ---------------------------------------------------------------------------
# AGNT-15: Parameter adjustment validation
# ---------------------------------------------------------------------------

class TestValidateParameterAdjustments:
    """AGNT-15: _validate_parameter_adjustments must reject unsafe suggestions."""

    def _make_adj(self, param_name, current_value, suggested_value):
        from agents.agent_i9 import ParameterChange
        return ParameterChange(
            param_name=param_name,
            current_value=current_value,
            suggested_value=suggested_value,
            reason="test reason",
        )

    def test_reject_max_positions_increase(self, caplog):
        import logging
        from agents.agent_i9 import AgentI9
        agent = make_agent()

        adj = self._make_adj("MAX_OPEN_POSITIONS", 5.0, 8.0)
        with caplog.at_level(logging.WARNING, logger="agents.agent_i9"):
            result = agent._validate_parameter_adjustments([adj])

        assert result == [], "MAX_OPEN_POSITIONS raise should be rejected"
        assert any("MAX_OPEN_POSITIONS" in r.message for r in caplog.records), (
            "Expected WARNING for rejected MAX_OPEN_POSITIONS"
        )

    def test_reject_min_rr_below_floor(self, caplog):
        import logging
        from agents.agent_i9 import AgentI9
        agent = make_agent()

        adj = self._make_adj("MIN_RISK_REWARD", 1.5, 1.2)
        with caplog.at_level(logging.WARNING, logger="agents.agent_i9"):
            result = agent._validate_parameter_adjustments([adj])

        assert result == [], "MIN_RISK_REWARD below 1.5 should be rejected"
        assert any("MIN_RISK_REWARD" in r.message for r in caplog.records)

    def test_reject_risk_pct_above_cap(self, caplog):
        import logging
        from agents.agent_i9 import AgentI9
        agent = make_agent()

        adj = self._make_adj("RISK_PER_TRADE_PCT", 1.0, 2.0)
        with caplog.at_level(logging.WARNING, logger="agents.agent_i9"):
            result = agent._validate_parameter_adjustments([adj])

        assert result == [], "RISK_PER_TRADE_PCT > 1.5 should be rejected"
        assert any("RISK_PER_TRADE_PCT" in r.message for r in caplog.records)

    def test_valid_adjustments_pass_through(self):
        from agents.agent_i9 import AgentI9
        agent = make_agent()

        adjs = [
            self._make_adj("MAX_OPEN_POSITIONS", 5.0, 4.0),   # reducing — ok
            self._make_adj("MIN_RISK_REWARD", 1.5, 2.0),       # raising floor — ok
            self._make_adj("RISK_PER_TRADE_PCT", 1.0, 1.0),    # same — ok
        ]
        result = agent._validate_parameter_adjustments(adjs)
        assert len(result) == 3, "All valid adjustments should pass through"


# ---------------------------------------------------------------------------
# AGNT-16: Output file writing
# ---------------------------------------------------------------------------

class TestOutputFileWriting:
    """AGNT-16: run() must write the correct output files."""

    def test_output_file_success(self, tmp_path):
        from agents.agent_i9 import AgentI9, DailyReview

        portfolio = make_portfolio(SAMPLE_TRADES)

        with patch("agents.agent_i9.Groq") as MockGroq:
            client = MagicMock()
            MockGroq.return_value = client
            mock_choice = MagicMock()
            mock_choice.message.content = VALID_REVIEW_JSON
            mock_resp = MagicMock()
            mock_resp.choices = [mock_choice]
            mock_resp.usage.total_tokens = 700
            client.chat.completions.create.return_value = mock_resp

            with patch("agents.agent_i9.PERF_DIR", tmp_path):
                agent = AgentI9(portfolio)
                agent._client = client

                with patch.object(agent, "_get_rolling_stats", return_value=ROLLING_STATS_FULL):
                    result = agent.run()

        today_str = date.today().strftime("%Y%m%d")
        out_file = tmp_path / f"review_{today_str}.json"
        assert out_file.exists(), f"review_{today_str}.json must exist on success"
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data["session_verdict"] == "LOSS"

    def test_output_file_failure(self, tmp_path):
        from agents.agent_i9 import AgentI9

        portfolio = make_portfolio(SAMPLE_TRADES)

        with patch("agents.agent_i9.Groq") as MockGroq:
            client = MagicMock()
            MockGroq.return_value = client
            client.chat.completions.create.side_effect = groq_api_error

            with patch("agents.agent_i9.PERF_DIR", tmp_path):
                agent = AgentI9(portfolio)
                agent._client = client

                with patch.object(agent, "_get_rolling_stats", return_value=ROLLING_STATS_EMPTY):
                    result = agent.run()

        assert result is None
        today_str = date.today().strftime("%Y%m%d")
        failed_file = tmp_path / f"review_failed_{today_str}.json"
        assert failed_file.exists(), "review_failed_*.json must exist when API call fails"
        data = json.loads(failed_file.read_text(encoding="utf-8"))
        assert data["error"] == "api_failure"


def groq_api_error(**kwargs):
    """Helper: raises Groq APIConnectionError as the create side_effect."""
    from groq import APIConnectionError as GroqConnError
    raise GroqConnError(request=MagicMock())


# ---------------------------------------------------------------------------
# AGNT-16: Terminal summary
# ---------------------------------------------------------------------------

class TestTerminalSummary:
    """AGNT-16: _print_summary should write correct text to stdout."""

    def test_terminal_summary_success(self, capsys):
        from agents.agent_i9 import AgentI9, DailyReview, ParameterChange

        agent = make_agent()
        review = DailyReview(
            session_verdict="PROFITABLE",
            winning_strategies=["GAP_AND_GO"],
            underperforming_strategies=[],
            parameter_adjustments=[],
            tomorrow_watch=["RELIANCE.NS"],
            summary="Good day.",
        )
        agent._print_summary(review, "success", "20260606", SAMPLE_TRADES)
        captured = capsys.readouterr()
        assert "Verdict" in captured.out
        assert "PROFITABLE" in captured.out

    def test_terminal_summary_failure(self, capsys):
        from agents.agent_i9 import AgentI9

        agent = make_agent()
        agent._print_summary(None, "failed", "20260606", [])
        captured = capsys.readouterr()
        assert "Review failed" in captured.out

    def test_terminal_summary_partial(self, capsys):
        from agents.agent_i9 import AgentI9

        agent = make_agent()
        agent._print_summary(None, "partial", "20260606", [])
        captured = capsys.readouterr()
        assert "Partial review" in captured.out
