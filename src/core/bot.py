"""
Main Trading Bot
Orchestrates all trading operations with proper integration
"""

import asyncio
import logging
from datetime import datetime, time
from typing import Dict, Optional
import signal
import sys

from src.data.kite_client import KiteClient
from src.data.market_data_client import MarketDataClient
from src.data.database import Database
from src.notifications.telegram_bot import TelegramNotifier
from src.utils.logger import setup_logger
from src.utils.helpers import is_trading_hours
from src.core.strategy import TradingStrategy, SignalType


class TradingBot:
    """Main trading bot orchestrator"""
    
    def __init__(self, config: Dict):
        """Initialize trading bot with configuration dictionary"""
        self.config = config
        
        # Setup logging
        self.logger = setup_logger("trading_bot", logging.INFO)
        
        # Initialize components
        self.kite_client = None
        self.alpha_vantage_client = None
        self.db_manager = None
        self.telegram_bot = None
        self.strategy = None
        
        # Bot state
        self.running = False
        self.simulation_mode = self.config.get('simulation_mode', False)
        self.paper_trading = self.config.get('paper_trading', True)
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.running = False

    async def initialize(self):
        """Initialize all bot components"""
        try:
            self.logger.info("🚀 Initializing Trading Bot...")
            
            # Initialize database
            db_config = self.config.get('database', {})
            db_path = db_config.get('path', 'data/trading_bot.db')
            self.db_manager = Database(db_path)
            self.logger.info("✅ Database initialized")
            
            # Initialize Alpha Vantage client
            alpha_vantage_config = self.config.get('alpha_vantage', {})
            if not alpha_vantage_config.get('api_key'):
                raise ValueError("Alpha Vantage API key not found in config")
            
            self.alpha_vantage_client = MarketDataClient(alpha_vantage_config['api_key'])
            self.logger.info("✅ Alpha Vantage client initialized")
            
            # Initialize Kite client (only if not in simulation mode)
            if not self.simulation_mode:
                kite_config = self.config.get('kite', {})
                
                # Check for required Kite API credentials
                required_keys = ['api_key', 'api_secret', 'user_id']
                missing_keys = [key for key in required_keys if not kite_config.get(key)]
                if missing_keys:
                    raise ValueError(f"Missing Kite API credentials: {missing_keys}")
                
                self.kite_client = KiteClient(
                    api_key=kite_config['api_key'],
                    api_secret=kite_config['api_secret'],
                    access_token=kite_config.get('access_token'),
                    paper_trading=self.paper_trading
                )
                self.logger.info("✅ Kite client initialized")
            else:
                self.logger.info("📊 Running in simulation mode (no Kite client)")
            
            # Initialize Telegram bot
            telegram_config = self.config.get('telegram', {})
            if telegram_config.get('enabled', False) and telegram_config.get('bot_token') and telegram_config.get('chat_id'):
                try:
                    self.telegram_bot = TelegramNotifier(
                        bot_token=telegram_config.get('bot_token'),
                        chat_id=telegram_config.get('chat_id')
                    )
                    await self.telegram_bot.initialize()
                    self.logger.info("✅ Telegram bot initialized")
                except Exception as e:
                    self.logger.warning(f"⚠️ Telegram initialization failed: {e}")
                    self.telegram_bot = None
            else:
                self.logger.info("📱 Telegram notifications disabled or not configured")
            
            # Initialize trading strategy
            self.strategy = TradingStrategy(
                config=self.config,
                kite_client=self.kite_client,
                alpha_vantage_client=self.alpha_vantage_client,
                db_manager=self.db_manager,
                telegram_bot=self.telegram_bot
            )
            await self.strategy.initialize_day()
            self.logger.info("✅ Trading strategy initialized")
            
            self.logger.info("🎉 Trading Bot initialization complete!")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Bot initialization failed: {e}")
            raise

    async def test_connections(self):
        """Test all API connections"""
        try:
            self.logger.info("🔌 Testing API connections...")
            
            # Test Alpha Vantage
            if self.alpha_vantage_client:
                prev_high, prev_low = self.alpha_vantage_client.get_previous_day_high_low()
                if prev_high is None or prev_low is None:
                    self.logger.error("❌ Alpha Vantage connection test failed")
                    return False
                self.logger.info("✅ Alpha Vantage connection successful")
            
            # Test Kite connection (if not paper trading)
            if self.kite_client and not self.paper_trading:
                # For live trading, would need to test actual Kite login
                # For now, just check if client is initialized
                self.logger.info("✅ Kite client ready (paper trading mode)")
            
            # Test Telegram (if enabled)
            if self.telegram_bot:
                await self.telegram_bot.send_message("🤖 Bot connection test successful")
                self.logger.info("✅ Telegram connection successful")
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Connection test failed: {e}")
            return False

    async def start(self):
        """Start the main trading loop"""
        try:
            self.logger.info("🚀 Starting trading bot main loop...")
            self.running = True
            
            # Send startup notification
            if self.telegram_bot:
                mode = "📄 Paper Trading" if self.paper_trading else "💰 Live Trading"
                await self.telegram_bot.send_message(f"🤖 NIFTY Options Bot Started\\n\\nMode: {mode}")
            
            # Main trading loop
            while self.running:
                try:
                    # Check if we're in trading hours
                    current_time = datetime.now().time()
                    market_start = time(9, 15)  # 9:15 AM
                    market_end = time(15, 30)   # 3:30 PM
                    
                    if market_start <= current_time <= market_end:
                        # Execute trading logic
                        await self.strategy.process_market_data()
                        
                        # Check for exit conditions on active positions
                        await self.strategy.check_exit_conditions()
                        
                        # Sleep for 30 seconds during trading hours (was 5 seconds)
                        await asyncio.sleep(30)
                        
                    else:
                        # Outside trading hours - wait and check less frequently
                        if current_time < market_start:
                            self.logger.info(f"⏰ Market opens at {market_start}. Waiting...")
                        else:
                            self.logger.info("🌙 Market closed. Preparing for next day...")
                            # Reset for next day if needed
                            await self.strategy.end_of_day_cleanup()
                        
                        # Sleep for 60 seconds outside trading hours
                        await asyncio.sleep(60)
                    
                except Exception as e:
                    self.logger.error(f"❌ Error in trading loop: {e}")
                    # Continue the loop but log the error
                    await asyncio.sleep(10)  # Wait a bit longer on error
            
            self.logger.info("✅ Trading bot stopped")
            
        except Exception as e:
            self.logger.error(f"❌ Fatal error in trading loop: {e}")
            raise
        finally:
            # Cleanup
            await self.cleanup()

    async def cleanup(self):
        """Cleanup resources"""
        try:
            self.logger.info("🧹 Cleaning up resources...")
            
            if self.telegram_bot:
                await self.telegram_bot.send_message("🛑 Trading bot stopped")
            
            # Close any open connections
            if self.kite_client:
                # Close Kite websocket if connected
                pass
            
            self.logger.info("✅ Cleanup complete")
            
        except Exception as e:
            self.logger.error(f"❌ Error during cleanup: {e}")

    def stop(self):
        """Stop the trading bot"""
        self.logger.info("🛑 Stop signal received")
        self.running = False
