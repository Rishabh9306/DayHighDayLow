"""
Simple health check web server for Render.com deployment
Prevents the service from sleeping during market hours
"""

from flask import Flask, jsonify
import threading
import asyncio
import os
from datetime import datetime, time
from start_trading_bot import main

app = Flask(__name__)

# Global bot status
bot_status = {
    "running": False,
    "last_heartbeat": None,
    "trades_today": 0,
    "current_price": 0,
    "status": "initializing"
}

@app.route('/health')
def health_check():
    """Health check endpoint for Render.com"""
    current_time = datetime.now()
    market_start = time(9, 15)  # 9:15 AM IST
    market_end = time(15, 30)   # 3:30 PM IST
    
    is_market_hours = market_start <= current_time.time() <= market_end
    
    return jsonify({
        "status": "healthy",
        "timestamp": current_time.isoformat(),
        "market_hours": is_market_hours,
        "bot_running": bot_status["running"],
        "last_heartbeat": bot_status["last_heartbeat"],
        "trades_today": bot_status["trades_today"],
        "current_price": bot_status["current_price"],
        "version": "1.0.0"
    })

@app.route('/')
def root():
    """Root endpoint"""
    return jsonify({
        "message": "NIFTY Options Trading Bot",
        "status": "running",
        "health_check": "/health"
    })

@app.route('/status')
def status():
    """Detailed bot status"""
    return jsonify(bot_status)

def update_bot_status(running=None, trades=None, price=None, status=None):
    """Update bot status from trading bot"""
    if running is not None:
        bot_status["running"] = running
    if trades is not None:
        bot_status["trades_today"] = trades
    if price is not None:
        bot_status["current_price"] = price
    if status is not None:
        bot_status["status"] = status
    
    bot_status["last_heartbeat"] = datetime.now().isoformat()

def run_trading_bot():
    """Run the trading bot in a separate thread"""
    try:
        update_bot_status(running=True, status="starting")
        asyncio.run(main())
    except Exception as e:
        print(f"Trading bot error: {e}")
        update_bot_status(running=False, status=f"error: {e}")

if __name__ == '__main__':
    # Start trading bot in background thread
    bot_thread = threading.Thread(target=run_trading_bot, daemon=True)
    bot_thread.start()
    
    # Start Flask web server for health checks
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
