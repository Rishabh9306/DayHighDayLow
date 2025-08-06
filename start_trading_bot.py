#!/usr/bin/env python3
"""
Production-ready NIFTY Options Trading Bot Startup Script
Complete with real data validation and error handling
"""
import sys
import os
import asyncio
import logging
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Load environment variables from .env file
from src.utils.config import load_env_file, validate_required_vars, ConfigManager
from src.data.market_data_client import MarketDataClient
from src.utils.logger import setup_logger

async def validate_real_data():
    """Validate that we can get real market data before starting"""
    try:
        config = ConfigManager.load_config()
        
        # Test Alpha Vantage (with Yahoo Finance fallback)
        alpha_client = MarketDataClient(config['alpha_vantage']['api_key'])
        prev_high, prev_low = alpha_client.get_previous_day_high_low()
        current_price = alpha_client.get_current_price()
        
        if prev_high is None or prev_low is None:
            return False, "❌ Failed to get previous day high/low data"
        
        if current_price is None:
            return False, "❌ Failed to get current price data"
        
        return True, {
            'prev_high': prev_high,
            'prev_low': prev_low,
            'current_price': current_price,
            'range': prev_high - prev_low
        }
        
    except Exception as e:
        return False, f"❌ Data validation error: {e}"

async def startup_validation():
    """Complete startup validation with real data"""
    print("🚀 NIFTY Options Trading Bot - Production Startup")
    print("=" * 60)
    print("⚠️  REAL MONEY TRADING - NO MOCK DATA")
    print("=" * 60)
    
    # Load environment variables
    print("\n🔑 Loading environment variables...")
    if not load_env_file():
        print("❌ Failed to load .env file")
        return False
    
    if not validate_required_vars():
        print("❌ Missing required environment variables")
        return False
    
    # Setup logging
    logger = setup_logger("trading_bot", logging.INFO)
    logger.info("🔥 Starting NIFTY Options Trading Bot...")
    
    try:
        # Load configuration  
        print("\n🔧 Loading configuration...")
        config = ConfigManager.load_config()
        print("   ✅ Configuration loaded successfully")
        
        # Validate real data availability
        print("\n📊 Validating real market data...")
        is_valid, data_or_error = await validate_real_data()
        
        if not is_valid:
            print(f"   {data_or_error}")
            print("\n🚨 CRITICAL: Cannot start bot without real market data!")
            print("   💡 Check network connectivity and API access")
            logger.error(f"Data validation failed: {data_or_error}")
            return False
        
        # Show validated data
        data = data_or_error
        print("   ✅ Real market data validated:")
        print(f"      📈 Previous high: {data['prev_high']:.2f}")
        print(f"      📉 Previous low: {data['prev_low']:.2f}")
        print(f"      💰 Current price: {data['current_price']:.2f}")
        print(f"      📊 Day range: {data['range']:.2f} points")
        
        # Determine market state
        if data['current_price'] > data['prev_high']:
            gap = data['current_price'] - data['prev_high']
            print(f"      🔥 GAP UP: +{gap:.2f} points (CE signal active)")
        elif data['current_price'] < data['prev_low']:
            gap = data['prev_low'] - data['current_price']
            print(f"      💥 GAP DOWN: -{gap:.2f} points (PE signal active)")
        else:
            print(f"      📊 Within range (waiting for breakout)")
        
        # Show trading parameters (FIXED DISPLAY)
        print("\n🎯 Trading Parameters:")
        print(f"   💰 Capital per trade: ₹{config['trading']['capital_per_trade']:,}")
        print(f"   📊 Max trades per day: {config['trading']['max_trades_per_day']}")
        print(f"   🛡️ Stop loss: {config['trading']['stop_loss_percent'] * 100:.0f}%")
        print(f"   🎯 Target: {config['trading']['target_percent'] * 100:.0f}%")
        print(f"   📱 Paper trading: {config.get('paper_trading', True)}")
        
        # Final confirmation for live trading
        if not config.get('paper_trading', True):
            print("\n" + "=" * 60)
            print("🚨 LIVE TRADING CONFIRMATION REQUIRED")
            print("=" * 60)
            print("This bot will execute REAL trades with REAL money on Zerodha Kite")
            print("\n⚠️  Type 'START' to begin live trading or 'CTRL+C' to abort")
            
            try:
                confirmation = input("Confirmation: ").strip().upper()
                if confirmation != "START":
                    print("🛑 Trading bot startup cancelled by user")
                    return False
            except KeyboardInterrupt:
                print("\n🛑 Trading bot startup cancelled")
                return False
        
        print("\n🚀 Bot is ready to start...")
        
        # Initialize and start the bot
        print("\n🤖 Initializing trading bot...")
        from src.core.bot import TradingBot
        
        bot = TradingBot(config)
        
        # Initialize the bot
        await bot.initialize()
        print("   ✅ Bot initialization successful")
        
        # Test connections
        print("\n🔌 Testing trading API connections...")
        connections_ok = await bot.test_connections()
        if not connections_ok:
            print("❌ API connection tests failed")
            return False
        print("   ✅ All API connections successful")
        
        # Start trading
        print("\n🚀 Starting trading bot main loop...")
        await bot.start()
        
        return True
        
    except KeyboardInterrupt:
        print("\n🛑 Startup interrupted by user")
        return False
    except Exception as e:
        print(f"\n❌ Startup failed: {e}")
        logger.error(f"Startup error: {e}")
        return False

async def main():
    """Main entry point"""
    try:
        success = await startup_validation()
        if success:
            print("\n✅ Startup validation complete")
        else:
            print("\n❌ Startup validation failed")
            sys.exit(1)
    except Exception as e:
        print(f"\n💥 Critical startup error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
