---
wave: 1
plan_id: "01-PLAN"
phase: "01"
phase_name: "Foundation"
objective: "Create project scaffold — requirements.txt, config.py, utils/logger.py, folder structure, .env.example, .gitignore"
depends_on: []
files_modified:
  - requirements.txt
  - config.py
  - utils/__init__.py
  - utils/logger.py
  - agents/__init__.py
  - data/__init__.py
  - execution/__init__.py
  - logs/.gitkeep
  - .env.example
  - .gitignore
  - main.py
autonomous: true
requirements_addressed:
  - SCAF-01
  - SCAF-02
  - SCAF-03
  - SCAF-04
  - SCAF-05
must_haves:
  truths:
    - "`pip install -r requirements.txt` completes without error"
    - "`google-generativeai` is absent from requirements.txt"
    - "`google-genai>=2.0.0` is present in requirements.txt"
    - "`pybroker>=1.0.0` is present in requirements.txt"
    - "`python -c 'from config import config; print(config.CAPITAL)'` prints 100000"
    - "Running logger emits INFO (green), WARNING (yellow), ERROR (red) to terminal"
    - "Running logger creates a dated file under logs/"
    - "`.env` appears in `.gitignore`"
    - "`.env.example` contains all 4 keys: GEMINI_API_KEY, ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID"
---

# Phase 1: Foundation — Plan

## Tasks

### Task 1: Create requirements.txt

<read_first>
- .planning/phases/01-foundation/01-CONTEXT.md (D-08 through D-11 — exact pins)
- CLAUDE.md §"Full Dependency List with Version Pins"
</read_first>

<action>
Create `requirements.txt` at project root with these exact pins:

```
# Data
yfinance==0.2.40
pandas>=2.0,<3.0
numpy>=1.24

# Scheduling
APScheduler==3.10.4

# AI SDKs
anthropic>=0.40.0
google-genai>=2.0.0

# Technical Analysis (inline pandas — no ta library)

# Backtesting
pybroker>=1.0.0

# Data processing / output / logging
colorlog>=6.7
tabulate>=0.9

# Environment
python-dotenv>=1.0
pytz>=2024.1
```

`google-generativeai` and `ta` must be ABSENT — their presence is a test failure.
</action>

<acceptance_criteria>
- `requirements.txt` exists at project root
- `grep "google-generativeai" requirements.txt` returns no match
- `grep "^ta" requirements.txt` returns no match
- `grep "google-genai>=2.0.0" requirements.txt` matches
- `grep "pybroker>=1.0.0" requirements.txt` matches
- `grep "yfinance==0.2.40" requirements.txt` matches
- `grep "APScheduler==3.10.4" requirements.txt` matches
</acceptance_criteria>

---

### Task 2: Create .env.example and .gitignore

<read_first>
- .planning/phases/01-foundation/01-CONTEXT.md (D-03 — required keys, specifics section)
- .planning/REQUIREMENTS.md (SCAF-04, SCAF-05)
</read_first>

<action>
Create `.env.example` at project root:

```
# nexus_trader environment variables
# Copy this file to .env and fill in your actual values

# Gemini Flash API key (pre-market agents I0, I2, I3)
GEMINI_API_KEY=your_gemini_api_key_here

# Anthropic API key (post-market agent I9 — Claude Sonnet)
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Telegram bot token (for trade alerts — v2 feature, keys required now)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here

# Telegram chat ID (your personal or group chat ID)
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
```

Create/update `.gitignore` at project root to include at minimum:

```
.env
__pycache__/
*.pyc
*.pyo
logs/
*.egg-info/
.pytest_cache/
```
</action>

<acceptance_criteria>
- `.env.example` exists and contains exactly these 4 keys: `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `grep "^\.env$" .gitignore` matches (`.env` on its own line, not `*.env`)
- `grep "GEMINI_API_KEY" .env.example` matches
- `grep "ANTHROPIC_API_KEY" .env.example` matches
- `grep "TELEGRAM_BOT_TOKEN" .env.example` matches
- `grep "TELEGRAM_CHAT_ID" .env.example` matches
</acceptance_criteria>

---

### Task 3: Create folder scaffold with __init__.py stubs

<read_first>
- .planning/phases/01-foundation/01-CONTEXT.md (D-06, D-07 — package structure)
- .planning/REQUIREMENTS.md (SCAF-01)
</read_first>

<action>
Create these directories and files (all `__init__.py` are empty files):

```
agents/__init__.py          # empty
data/__init__.py            # empty
execution/__init__.py       # empty
utils/__init__.py           # empty
logs/.gitkeep               # empty — tracks the dir in git; logs/ itself is gitignored
```

`logs/` directory must exist on disk. `.gitkeep` ensures git tracks it. The `logs/` pattern in `.gitignore` should ignore log files but NOT the directory itself — use `logs/*.log` pattern instead of `logs/` to keep `.gitkeep` tracked.

Update `.gitignore` to use `logs/*.log` not `logs/`.
</action>

<acceptance_criteria>
- `agents/__init__.py`, `data/__init__.py`, `execution/__init__.py`, `utils/__init__.py` all exist and are empty
- `logs/.gitkeep` exists
- `python -c "from agents import *; from data import *; from execution import *; from utils import *"` exits 0 (no import errors from empty packages)
</acceptance_criteria>

---

### Task 4: Create config.py

<read_first>
- .planning/phases/01-foundation/01-CONTEXT.md (D-01 through D-03 — Config class pattern)
- .planning/phases/01-foundation/01-RESEARCH.md §"python-dotenv + plain Config class"
- CLAUDE.md §"Project Constraints" (capital, risk, gap filters, entry window)
</read_first>

<action>
Create `config.py` at project root. Pattern:
- `load_dotenv()` called at module level before `class Config`
- `Config.__init__` calls `self._require(key)` for all 4 API keys — raises `ValueError` with clear message if absent
- All trading parameters as class attributes with values from CLAUDE.md constraints
- Module ends with `config = Config()` singleton

Required parameters to include:
- `CAPITAL = 100_000` (paper capital in rupees)
- `RISK_PER_TRADE_PCT = 0.01` (1% risk per trade)
- `MAX_OPEN_POSITIONS = 5`
- `MAX_TRADES_PER_DAY = 15`
- `DAILY_LOSS_LIMIT_PCT = 0.02` (halt trading if daily P&L < -2%)
- `MIN_RISK_REWARD = 1.5`
- `GAP_MIN_PCT = 1.5`
- `GAP_MAX_PCT = 8.0`
- `MIN_PREV_VOLUME = 500_000`
- `MIN_PRICE = 50`
- `MAX_PRICE = 5_000`
- `ENTRY_CUTOFF_HOUR = 14` (no new entries after 14:00 IST)
- `ENTRY_START_HOUR = 9`
- `ENTRY_START_MINUTE = 30` (no entries before 09:30 IST)
- `ORB_MINUTES = 15`
- `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — all via `_require()`
</action>

<acceptance_criteria>
- `config.py` exists at project root
- `python -c "from config import config; print(config.CAPITAL)"` prints `100000`
- `python -c "from config import config; print(config.MIN_RISK_REWARD)"` prints `1.5`
- When `.env` is absent or GEMINI_API_KEY is missing, importing config raises `ValueError` with a message containing the missing key name
- `config.py` contains `load_dotenv()` before the `class Config:` definition
- `config.py` ends with `config = Config()`
- No pydantic, no dataclass decorators anywhere in config.py
</acceptance_criteria>

---

### Task 5: Create utils/logger.py

<read_first>
- .planning/phases/01-foundation/01-CONTEXT.md (D-04, D-05 — logger scope)
- .planning/phases/01-foundation/01-RESEARCH.md §"colorlog — dual handler setup" and §"RotatingFileHandler vs TimedRotatingFileHandler"
</read_first>

<action>
Create `utils/logger.py`. Requirements:
- `setup_logger(name: str) -> logging.Logger` function
- Guard: `if logger.handlers: return logger` — idempotent, safe to call multiple times
- StreamHandler with `colorlog.ColoredFormatter`: INFO=green, WARNING=yellow, ERROR=red
- `TimedRotatingFileHandler` with `when="midnight"`, `backupCount=30`
- File handler uses plain `logging.Formatter` (no ANSI codes in file)
- Log filename: `logs/nexus_{YYYY-MM-DD}.log` using today's date at logger creation
- Creates `logs/` directory if missing (`Path("logs").mkdir(exist_ok=True)`)
- Logger level: `logging.DEBUG` (handlers control what's shown)

Do NOT add custom TRADE or P&L levels — those are Phase 5.
</action>

<acceptance_criteria>
- `utils/logger.py` exists
- `python -c "from utils.logger import setup_logger; l=setup_logger('test'); l.info('INFO ok'); l.warning('WARN ok'); l.error('ERR ok')"` exits 0 and prints 3 colored lines to terminal
- A file matching `logs/nexus_*.log` is created after running the above command
- Calling `setup_logger('test')` twice returns a logger with exactly 2 handlers (not 4)
- No `RotatingFileHandler` import — only `TimedRotatingFileHandler`
- No custom log levels defined
</acceptance_criteria>

---

### Task 6: Create main.py placeholder

<read_first>
- .planning/phases/01-foundation/01-CONTEXT.md (D-06 — flat imports from root)
- .planning/ROADMAP.md §"Phase 5" (NEXUS ASCII banner — reminder it goes in main.py)
</read_first>

<action>
Create `main.py` at project root as a minimal placeholder:

```python
from config import config
from utils.logger import setup_logger

logger = setup_logger(__name__)

def main():
    logger.info("nexus_trader starting up (placeholder — Phase 5 adds full orchestrator)")
    logger.info(f"Capital: ₹{config.CAPITAL:,}")

if __name__ == "__main__":
    main()
```

This is a placeholder only. The full orchestrator, ASCII banner, and APScheduler wiring are Phase 5.
</action>

<acceptance_criteria>
- `main.py` exists at project root
- `python main.py` exits 0 and logs at least 2 INFO lines to terminal
- `python main.py` creates/appends to `logs/nexus_*.log`
- `main.py` contains `from config import config` and `from utils.logger import setup_logger`
</acceptance_criteria>

---

## Verification

Run these commands in sequence after all tasks complete:

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Check google-generativeai is absent
python -c "import pkg_resources; pkgs={p.key for p in pkg_resources.working_set}; assert 'google-generativeai' not in pkgs, f'FAIL: google-generativeai found in installed packages'"

# 3. Config loads correctly (requires .env with valid keys)
python -c "from config import config; assert config.CAPITAL == 100000; print(config.CAPITAL)"

# 4. Logger works
python -c "from utils.logger import setup_logger; l=setup_logger('verify'); l.info('INFO'); l.warning('WARN'); l.error('ERR')"

# 5. Log file created
ls logs/nexus_*.log

# 6. .env in .gitignore
grep "^\.env$" .gitignore

# 7. .env.example has 4 keys
grep -c "GEMINI_API_KEY\|ANTHROPIC_API_KEY\|TELEGRAM_BOT_TOKEN\|TELEGRAM_CHAT_ID" .env.example

# 8. Empty packages importable
python -c "from agents import *; from data import *; from execution import *; from utils import *"

# 9. main.py runs
python main.py
```

All 9 commands must exit 0 with expected output.
