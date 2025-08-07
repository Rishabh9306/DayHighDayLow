"""
Helper utility functions for the trading bot
"""

from datetime import datetime, time
from typing import Optional, Tuple
import math

def is_trading_hours(current_time: Optional[time] = None) -> bool:
    """
    Check if current time is within trading hours (9:15 AM - 3:30 PM)
    
    Args:
        current_time: Time to check (default: current time)
    
    Returns:
        True if within trading hours, False otherwise
    """
    if current_time is None:
        current_time = datetime.now().time()
    
    market_start = time(9, 15)  # 9:15 AM
    market_end = time(15, 30)   # 3:30 PM
    
    return market_start <= current_time <= market_end

def get_atm_strike(spot_price: float, strike_difference: int = 50) -> int:
    """
    Get the nearest ATM (At The Money) strike price
    
    Args:
        spot_price: Current Nifty spot price
        strike_difference: Strike price difference (default 50)
        
    Returns:
        Nearest ATM strike price
    """
    return round(spot_price / strike_difference) * strike_difference

def get_option_symbol(strike: int, option_type: str, expiry_date: str) -> str:
    """
    Generate option symbol for Kite API
    
    Args:
        strike: Strike price
        option_type: 'CE' for Call or 'PE' for Put
        expiry_date: Expiry date in format 'YYMMDD'
        
    Returns:
        Option symbol string
    """
    return f"NIFTY{expiry_date}{strike}{option_type}"

def calculate_stop_loss(entry_price: float, sl_percent: float) -> float:
    """
    Calculate stop loss price
    
    Args:
        entry_price: Entry price of the option
        sl_percent: Stop loss percentage as decimal (e.g., 0.20 for 20%)
        
    Returns:
        Stop loss price
    """
    return entry_price * (1 - sl_percent)

def calculate_target(entry_price: float, target_percent: float) -> float:
    """
    Calculate target price
    
    Args:
        entry_price: Entry price of the option
        target_percent: Target percentage as decimal (e.g., 0.60 for 60%)
        
    Returns:
        Target price
    """
    return entry_price * (1 + target_percent)

def calculate_trailing_sl(current_price: float, highest_price: float, 
                         entry_price: float, trailing_percent: float) -> float:
    """
    Calculate trailing stop loss
    
    Args:
        current_price: Current option price
        highest_price: Highest achieved price since entry
        entry_price: Original entry price
        trailing_percent: Trailing SL percentage as decimal (e.g., 0.20 for 20%)
        
    Returns:
        New trailing stop loss price
    """
    # Calculate SL based on highest achieved price
    trailing_sl = highest_price * (1 - trailing_percent)
    
    # Ensure trailing SL is never below original SL
    original_sl = calculate_stop_loss(entry_price, trailing_percent)
    
    return max(trailing_sl, original_sl)

def format_currency(amount: float) -> str:
    """
    Format amount as Indian currency
    
    Args:
        amount: Amount to format
        
    Returns:
        Formatted currency string
    """
    return f"₹{amount:,.2f}"

def get_next_expiry() -> str:
    """
    Get next Thursday (weekly expiry) in YYMMDD format
    
    Returns:
        Next expiry date string
    """
    from datetime import datetime, timedelta
    
    today = datetime.now()
    days_ahead = 3 - today.weekday()  # Thursday is 3
    
    if days_ahead <= 0:  # Target day already happened this week
        days_ahead += 7
    
    expiry_date = today + timedelta(days_ahead)
    return expiry_date.strftime("%y%m%d")

def validate_price(price: float) -> bool:
    """
    Validate if price is reasonable for options trading
    
    Args:
        price: Option price to validate
        
    Returns:
        True if price is valid, False otherwise
    """
    return 0.05 <= price <= 1000  # Reasonable range for option prices
