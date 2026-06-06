# Phase 1: Foundation - Research

**Researched:** 2026-06-06
**Phase:** 01-foundation

## RESEARCH COMPLETE

---

## 1. python-dotenv + plain Config class

**Pattern:** `load_dotenv()` must be called before `Config()` is instantiated. Standard approach:

```python
# config.py
from dotenv import load_dotenv
load_dotenv()          # loads .env into os.environ at import time

class Config:
    def __init__(self):
        self.GEMINI_API_KEY = self._require("GEMINI_API_KEY")
        self.ANTHROPIC_API_KEY = self._require("ANTHROPIC_API_KEY")
        ...
    def _require(self, key):
        val = os.getenv(key)
        if not val:
            raise ValueError(f"Required env var {key} is missing. Check .env file.")
        return val

config = Config()
```

`load_dotenv()` is a no-op when the keys are already in the environment (CI/production safe). No ordering issues because the module-level call runs before `Config.__init__`.

---

## 2. colorlog — dual handler setup

colorlog `ColoredFormatter` only works on the StreamHandler (terminal). File handlers need a plain `logging.Formatter` — otherwise ANSI escape codes are written to the log file.

```python
import logging
import colorlog
from logging.handlers import TimedRotatingFileHandler

def setup_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:          # idempotent — don't add handlers twice
        return logger
    logger.setLevel(logging.DEBUG)

    # Terminal: colored
    ch = logging.StreamHandler()
    ch.setFormatter(colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s [%(name)s] %(levelname)s%(reset)s %(message)s",
        log_colors={"DEBUG": "white", "INFO": "green", "WARNING": "yellow", "ERROR": "red", "CRITICAL": "bold_red"}
    ))
    logger.addHandler(ch)

    # File: plain
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    fh = TimedRotatingFileHandler(
        logs_dir / f"nexus_{datetime.now().strftime('%Y-%m-%d')}.log",
        when="midnight", backupCount=30
    )
    fh.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s"))
    logger.addHandler(fh)

    return logger
```

The `if logger.handlers` guard is critical — without it, importing a module twice (or in tests) doubles log output.

---

## 3. RotatingFileHandler vs TimedRotatingFileHandler

**Decision: `TimedRotatingFileHandler` with `when="midnight"`.**

Reasoning for a daily trading system:
- Logs naturally segment by trading day — one file per day is the right granularity
- `RotatingFileHandler` rolls on size; a busy day with many trades could mid-session roll and split one day's logs across two files
- `TimedRotatingFileHandler` at midnight aligns with the NSE trading calendar
- The `backupCount=30` keeps one month of logs

The filename date stamp in the CONTEXT.md decision (`logs/nexus_YYYY-MM-DD.log`) already implies per-day files, confirming this choice.

---

## 4. requirements.txt version compatibility

Verified pin strategy from CONTEXT.md D-10 + D-11:

| Package | Pin | Compatibility Notes |
|---------|-----|---------------------|
| `yfinance==0.2.40` | Exact | Pinned to avoid breaking changes in 0.2.x series |
| `pandas>=2.0,<3.0` | Range | Required by yfinance; upper bound prevents pandas 3.x breakage |
| `numpy>=1.24` | Lower bound | Supports pandas 2.x; numpy 2.x is fine |
| `APScheduler==3.10.4` | Exact | 4.x has breaking API changes; 3.10.4 is latest 3.x stable |
| `anthropic>=0.40.0` | Lower bound | Structured outputs API available from 0.40.0+ |
| `google-genai>=2.0.0` | Lower bound | Replaces deprecated google-generativeai |
| `colorlog>=6.7` | Lower bound | Stable API since 6.x |
| `tabulate>=0.9` | Lower bound | No known breaking changes |
| `pytz>=2024.1` | Lower bound | Timezone data updates only |
| `python-dotenv>=1.0` | Lower bound | Stable API |
| `pybroker>=1.0.0` | Lower bound | Pinned here, used Phase 6 |

**No conflicts detected.** All packages support Python 3.11+. The `pandas>=2.0,<3.0` range is the critical constraint — yfinance 0.2.40 requires pandas 2.x.

**`google-generativeai` must be ABSENT** — the CI success criterion checks for this.

---

## 5. Folder scaffold — idempotent creation

Standard Python pattern for creating directory stubs:

```python
# In a setup script or verified during execution
from pathlib import Path

dirs = ["agents", "data", "execution", "utils", "logs"]
for d in dirs:
    Path(d).mkdir(exist_ok=True)
    init = Path(d) / "__init__.py"
    if not init.exists():
        init.touch()
```

For Phase 1, the scaffold is created once as static files — not by a script. The planner should create each `__init__.py` as an empty file. `logs/` gets a `.gitkeep` (empty dir must be tracked in git, but logs themselves are gitignored).

---

## Validation Architecture

| Success Criterion | Test Command |
|-------------------|-------------|
| requirements.txt installable, google-generativeai absent | `pip install -r requirements.txt && python -c "import pkg_resources; assert 'google-generativeai' not in {p.key for p in pkg_resources.working_set}"` |
| Config loads from .env | `python -c "from config import config; print(config.CAPITAL)"` must print `100000` |
| Logger emits colored output + creates log file | `python -c "from utils.logger import setup_logger; l=setup_logger('test'); l.info('ok'); l.warning('ok'); l.error('ok')"` + check `logs/` directory |
| .env in .gitignore | `grep -n "^\.env$" .gitignore` must match |
| .env.example has 4 keys | `grep -c "API_KEY\|TOKEN\|CHAT_ID" .env.example` must equal 4 |
