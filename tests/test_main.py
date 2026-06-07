"""
tests/test_main.py — Tests for main.py entry point

conftest.py sets fake env vars before any module is imported.
"""

from unittest.mock import patch

import pytest


def test_print_banner_contains_mode(capsys):
    """print_banner should print the mode string and capital."""
    import main
    main.print_banner(dry_run=True)
    captured = capsys.readouterr()
    assert "DRY-RUN" in captured.out
    assert "100,000" in captured.out


def test_parse_args_defaults():
    """parse_args() with no arguments should default dry_run to False."""
    import main
    with patch("sys.argv", ["main.py"]):
        args = main.parse_args()
    assert args.dry_run is False


def test_parse_args_dry_run_flag():
    """parse_args() with --dry-run should set dry_run to True."""
    import main
    with patch("sys.argv", ["main.py", "--dry-run"]):
        args = main.parse_args()
    assert args.dry_run is True
