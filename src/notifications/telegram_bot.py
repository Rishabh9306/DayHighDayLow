"""
Telegram bot integration for trading notifications
"""

import asyncio
import logging
from typing import Optional
import json

try:
    import telegram
    from telegram import Bot
except ImportError:
    print("python-telegram-bot library not installed. Run: pip install python-telegram-bot")
    telegram = None
    Bot = None

from src.data.database import Trade, DayData
from src.utils.helpers import format_currency

class TelegramNotifier:
    """Telegram bot for sending trading notifications"""
    
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.logger = logging.getLogger(__name__)
        
        if Bot is None:
            raise ImportError("python-telegram-bot library not available")
        
        self.bot = Bot(token=bot_token)
    
    async def initialize(self):
        """Initialize the Telegram bot connection"""
        try:
            # Test the bot connection
            me = await self.bot.get_me()
            self.logger.info(f"✅ Telegram bot connected: @{me.username}")
            return True
        except Exception as e:
            self.logger.error(f"❌ Telegram bot initialization failed: {e}")
            return False
    
    async def send_message(self, message: str, parse_mode: str = "HTML"):
        """
        Send a message to Telegram
        
        Args:
            message: Message to send
            parse_mode: Parsing mode (HTML, Markdown, etc.)
        """
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=parse_mode
            )
            self.logger.info("Telegram message sent successfully")
        except Exception as e:
            self.logger.error(f"Error sending Telegram message: {e}")
    
    async def send_bot_started(self):
        """Send bot startup notification"""
        message = """
🤖 <b>NIFTY Options Trading Bot Started</b>

✅ Bot is now active and monitoring the market
📊 Strategy: Previous Day High/Low Breakout
⏰ Market Hours: 9:15 AM - 3:30 PM
💰 Capital per trade: ₹15,000
🎯 Target: 60% | Stop Loss: 20%

Bot will notify you of all trading activities.
        """
        await self.send_message(message.strip())
    
    async def send_daily_setup(self, day_data: DayData):
        """Send daily market setup information"""
        message = f"""
📅 <b>Daily Market Setup</b>

📈 Previous Day High: <b>{day_data.prev_high:.2f}</b>
📉 Previous Day Low: <b>{day_data.prev_low:.2f}</b>

🎯 <b>Strategy Rules:</b>
• Buy CE if price crosses above {day_data.prev_high:.2f}
• Buy PE if price crosses below {day_data.prev_low:.2f}

{'🟢 Gap Up detected - Will buy CE at open' if day_data.gap_up else ''}
{'🔴 Gap Down detected - Will buy PE at open' if day_data.gap_down else ''}
        """
        await self.send_message(message.strip())
    
    async def send_trade_entry(self, trade: Trade):
        """Send trade entry notification"""
        entry_emoji = "🟢" if trade.option_type == "CE" else "🔴"
        reason_text = {
            "BREAKOUT_HIGH": "Breakout above previous day high",
            "BREAKOUT_LOW": "Breakout below previous day low", 
            "GAP_UP": "Gap up at market open",
            "GAP_DOWN": "Gap down at market open"
        }.get(trade.entry_reason, trade.entry_reason)
        
        message = f"""
{entry_emoji} <b>TRADE ENTRY</b>

📊 <b>{trade.symbol}</b>
🎯 Type: <b>{trade.option_type}</b> (Strike: {trade.strike})
💰 Entry Price: <b>{format_currency(trade.entry_price)}</b>
📦 Quantity: <b>{trade.quantity}</b>
💸 Investment: <b>{format_currency(trade.entry_price * trade.quantity)}</b>

📍 Stop Loss: <b>{format_currency(trade.stop_loss)}</b>
🎯 Target: <b>{format_currency(trade.target)}</b>

📝 Reason: {reason_text}
⏰ Time: {trade.timestamp.strftime('%H:%M:%S')}
        """
        await self.send_message(message.strip())
    
    async def send_trade_exit(self, trade: Trade):
        """Send trade exit notification"""
        exit_emoji = "✅" if trade.pnl > 0 else "❌"
        pnl_emoji = "💰" if trade.pnl > 0 else "💸"
        
        exit_reason_text = {
            "TARGET": "Target achieved",
            "STOP_LOSS": "Stop loss hit",
            "TRAILING_SL": "Trailing stop loss hit",
            "MANUAL": "Manual exit"
        }.get(trade.exit_reason, trade.exit_reason)
        
        message = f"""
{exit_emoji} <b>TRADE EXIT</b>

📊 <b>{trade.symbol}</b>
🎯 Type: <b>{trade.option_type}</b> (Strike: {trade.strike})
💰 Entry: <b>{format_currency(trade.entry_price)}</b>
🚪 Exit: <b>{format_currency(trade.exit_price)}</b>

{pnl_emoji} <b>P&L: {format_currency(trade.pnl)}</b>
📈 Return: <b>{((trade.exit_price - trade.entry_price) / trade.entry_price * 100):+.2f}%</b>

📝 Exit Reason: {exit_reason_text}
⏰ Time: {trade.timestamp.strftime('%H:%M:%S')}
        """
        await self.send_message(message.strip())
    
    async def send_trailing_sl_update(self, trade: Trade, new_sl: float, current_price: float):
        """Send trailing stop loss update notification"""
        message = f"""
📈 <b>TRAILING SL UPDATE</b>

📊 <b>{trade.symbol}</b> ({trade.option_type})
💰 Current Price: <b>{format_currency(current_price)}</b>
🛡️ New Stop Loss: <b>{format_currency(new_sl)}</b>
📊 Unrealized P&L: <b>{format_currency((current_price - trade.entry_price) * trade.quantity)}</b>
        """
        await self.send_message(message.strip())
    
    async def send_daily_summary(self, trades, total_pnl: float):
        """Send end of day trading summary"""
        total_trades = len(trades)
        winning_trades = len([t for t in trades if t.pnl > 0])
        losing_trades = len([t for t in trades if t.pnl < 0])
        
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        summary_emoji = "🎉" if total_pnl > 0 else "😔"
        
        message = f"""
{summary_emoji} <b>DAILY TRADING SUMMARY</b>

📊 <b>Performance Overview:</b>
💼 Total Trades: <b>{total_trades}</b>
✅ Winning Trades: <b>{winning_trades}</b>
❌ Losing Trades: <b>{losing_trades}</b>
📈 Win Rate: <b>{win_rate:.1f}%</b>

💰 <b>Total P&L: {format_currency(total_pnl)}</b>

📋 <b>Trade Details:</b>
        """
        
        for i, trade in enumerate(trades, 1):
            pnl_emoji = "✅" if trade.pnl > 0 else "❌"
            message += f"\n{i}. {pnl_emoji} {trade.symbol} {trade.option_type}: {format_currency(trade.pnl)}"
        
        await self.send_message(message.strip())
    
    async def send_error_notification(self, error_msg: str):
        """Send error notification"""
        message = f"""
⚠️ <b>TRADING BOT ERROR</b>

🚨 Error Details:
<code>{error_msg}</code>

Please check the bot logs for more information.
        """
        await self.send_message(message.strip())
    
    async def send_market_status(self, status: str, details: str = ""):
        """Send market status updates"""
        status_emoji = {
            "OPEN": "🟢",
            "CLOSED": "🔴", 
            "PRE_MARKET": "🟡",
            "POST_MARKET": "🟠"
        }.get(status, "ℹ️")
        
        message = f"""
{status_emoji} <b>MARKET STATUS: {status}</b>

{details}
        """
        await self.send_message(message.strip())
    
    async def test_connection(self) -> bool:
        """Test Telegram bot connection"""
        try:
            await self.send_message("🤖 Trading Bot Connection Test - Success!")
            return True
        except Exception as e:
            self.logger.error(f"Telegram connection test failed: {e}")
            return False
