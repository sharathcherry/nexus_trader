"""
utils/telegram_bot.py -- Legacy chatbot wrapper for nexus_trader.

Consolidated into utils/telegram.py. Delegates directly to it to maintain
backwards compatibility.
"""

from utils.telegram import bot, TelegramCommandBot
