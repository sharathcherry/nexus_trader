import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from datetime import datetime

import colorlog


# ---------------------------------------------------------------------------
# Custom log levels
# ---------------------------------------------------------------------------

TRADE_LEVEL = 25        # between INFO (20) and WARNING (30)
PNL_PROFIT_LEVEL = 26
PNL_LOSS_LEVEL = 27

logging.addLevelName(TRADE_LEVEL, "TRADE")
logging.addLevelName(PNL_PROFIT_LEVEL, "PNL_PROFIT")
logging.addLevelName(PNL_LOSS_LEVEL, "PNL_LOSS")


def _trade(self: logging.Logger, message: str, *args, **kwargs) -> None:
    if self.isEnabledFor(TRADE_LEVEL):
        self._log(TRADE_LEVEL, message, args, **kwargs)


def _pnl_profit(self: logging.Logger, message: str, *args, **kwargs) -> None:
    if self.isEnabledFor(PNL_PROFIT_LEVEL):
        self._log(PNL_PROFIT_LEVEL, message, args, **kwargs)


def _pnl_loss(self: logging.Logger, message: str, *args, **kwargs) -> None:
    if self.isEnabledFor(PNL_LOSS_LEVEL):
        self._log(PNL_LOSS_LEVEL, message, args, **kwargs)


# Bind methods to Logger class (idempotent — safe to call multiple times)
if not hasattr(logging.Logger, "trade"):
    logging.Logger.trade = _trade  # type: ignore[attr-defined]
if not hasattr(logging.Logger, "pnl_profit"):
    logging.Logger.pnl_profit = _pnl_profit  # type: ignore[attr-defined]
if not hasattr(logging.Logger, "pnl_loss"):
    logging.Logger.pnl_loss = _pnl_loss  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Logger factory
# ---------------------------------------------------------------------------


def setup_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # Terminal handler — colored output
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG)
    stream_handler.setFormatter(
        colorlog.ColoredFormatter(
            "%(log_color)s%(asctime)s [%(levelname)-9s] %(name)s — %(message)s%(reset)s",
            datefmt="%H:%M:%S",
            log_colors={
                "DEBUG": "cyan",
                "INFO": "green",
                "TRADE": "bold_green",
                "PNL_PROFIT": "bold_cyan",
                "PNL_LOSS": "bold_red",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "bold_red",
            },
        )
    )

    # File handler — plain text, rolls at midnight, 30-day retention
    Path("logs").mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = f"logs/nexus_{today}.log"

    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)-9s] %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    return logger
