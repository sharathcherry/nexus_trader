from config import config
from utils.logger import setup_logger

logger = setup_logger(__name__)


def main():
    logger.info("nexus_trader starting up (placeholder — Phase 5 adds full orchestrator)")
    logger.info(f"Capital: ₹{config.CAPITAL:,}")


if __name__ == "__main__":
    main()
