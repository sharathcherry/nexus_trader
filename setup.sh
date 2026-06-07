#!/usr/bin/env bash
# nexus_trader VM setup script
# Tested on Ubuntu 22.04 LTS (Azure Standard_B1ls -- 1 vCPU, 0.5 GiB RAM)
# Run once after cloning: bash setup.sh
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[setup]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
error() { echo -e "${RED}[error]${NC} $*"; exit 1; }

# ── 1. Swap (critical for 512MB RAM) ──────────────────────────────────────────
info "Checking swap..."
if free | awk '/^Swap:/ {exit !$2}'; then
    info "Swap already configured -- skipping"
else
    info "Adding 1GB swap file..."
    sudo fallocate -l 1G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    info "Swap enabled: $(free -h | awk '/^Swap:/ {print $2}')"
fi

# ── 2. System packages ─────────────────────────────────────────────────────────
info "Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq software-properties-common curl git

# ── 3. Python 3.11 ─────────────────────────────────────────────────────────────
if ! command -v python3.11 &>/dev/null; then
    info "Installing Python 3.11..."
    sudo add-apt-repository ppa:deadsnakes/ppa -y
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3.11 python3.11-venv python3.11-dev
fi
PYTHON=$(command -v python3.11)
info "Python: $($PYTHON --version)"

# ── 4. Virtual environment ─────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d "venv" ]; then
    info "Creating virtual environment..."
    $PYTHON -m venv venv
fi
source venv/bin/activate

# ── 5. Dependencies ────────────────────────────────────────────────────────────
info "Installing Python dependencies (this takes 2-4 minutes)..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
info "Dependencies installed"

# ── 6. .env file ───────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    cp .env.example .env
    warn ".env created from template -- EDIT IT NOW with your real API keys:"
    warn "  nano .env"
else
    info ".env already exists"
fi

# ── 7. Required directories ────────────────────────────────────────────────────
mkdir -p logs/performance logs/backtest execution

# ── 8. Database ────────────────────────────────────────────────────────────────
if [ ! -f "execution/portfolio.db" ]; then
    info "Initialising portfolio database (capital: Rs1,00,000)..."
    python -c "from execution.portfolio import PaperPortfolio; p = PaperPortfolio(); print('  Capital:', p.capital)"
else
    info "Database already exists"
fi

# ── 9. Systemd service ─────────────────────────────────────────────────────────
SERVICE_FILE="/etc/systemd/system/nexus_trader.service"
CURRENT_USER=$(whoami)

if [ ! -f "$SERVICE_FILE" ]; then
    info "Installing systemd service..."
    sudo tee "$SERVICE_FILE" > /dev/null << UNIT
[Unit]
Description=nexus_trader NSE paper trading
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=$SCRIPT_DIR/venv/bin/python main.py
Restart=on-failure
RestartSec=60
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT
    sudo systemctl daemon-reload
    sudo systemctl enable nexus_trader
    info "Systemd service installed and enabled"
else
    info "Systemd service already installed"
fi

# ── 10. Validate ───────────────────────────────────────────────────────────────
info "Validating installation..."
python -c "
from config import config
print(f'  Capital:          Rs{config.CAPITAL:,.0f}')
print(f'  Max positions:    {config.MAX_OPEN_POSITIONS}')
print(f'  Max per position: Rs{config.CAPITAL * config.MAX_POSITION_PCT:,.0f}')
print(f'  Min R:R:          {config.MIN_RISK_REWARD}')
" 2>&1 | grep -v "^$" || warn "Config validation skipped (fill .env first)"

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN} Setup complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Next steps:"
echo "  1. Add your API keys:    nano .env"
echo "  2. Test the pipeline:    bash run.sh --dry-run"
echo "  3. Start live trading:   sudo systemctl start nexus_trader"
echo "  4. View logs:            sudo journalctl -u nexus_trader -f"
echo ""
