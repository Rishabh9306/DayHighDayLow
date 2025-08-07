"""
NIFTY Options Trading Strategy
Implements day high/low breakout strategy with risk management
"""

import logging
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import asyncio

from ..data.kite_client import KiteClient
from ..data.market_data_client import MarketDataClient
from ..data.database import Database
from ..notifications.telegram_bot import TelegramNotifier
from ..utils.helpers import (
    get_atm_strike, calculate_stop_loss, calculate_target,
    calculate_trailing_sl, get_next_expiry, is_trading_hours
)

@dataclass
@dataclass
class Trade:
    """Trade data structure"""
    timestamp: datetime
    symbol: str
    action: str  # 'BUY' or 'SELL'
    price: float
    quantity: int
    trade_type: str  # 'ENTRY', 'EXIT', 'SL', 'TARGET'
    option_type: str  # 'CE' or 'PE'
    strike: float
    entry_price: float = 0.0
    exit_price: float = 0.0
    stop_loss: float = 0.0
    target: float = 0.0
    pnl: float = 0.0
    reason: str = ""
    status: str = "OPEN"  # 'OPEN', 'CLOSED'
    order_id: str = ""
    highest_price: float = 0.0

@dataclass
class SignalCooldown:
    """Signal cooldown tracking"""
    signal_type: str  # 'gap_up', 'gap_down', 'breakout_high', 'breakout_low', 'reentry'
    timestamp: datetime
    price: float
    symbol: str

class SignalType(Enum):
    """Trading signal types"""
    NO_SIGNAL = "NO_SIGNAL"
    BUY_CE_BREAKOUT = "BUY_CE_BREAKOUT"
    BUY_PE_BREAKOUT = "BUY_PE_BREAKOUT"
    BUY_CE_GAP = "BUY_CE_GAP"
    BUY_PE_GAP = "BUY_PE_GAP"
    BUY_CE_REENTRY = "BUY_CE_REENTRY"
    BUY_PE_REENTRY = "BUY_PE_REENTRY"

class TradingStrategy:
    """
    NIFTY Options Day Trading Strategy
    
    Rules:
    1. Buy CE on breakout above previous day high
    2. Buy PE on breakout below previous day low  
    3. Gap trades: immediate entry at market open
    4. Exits: 20% SL, 60% target, 20% trailing SL
    5. Max 4 trades/day, ₹15k per trade, fixed 150 quantity
    6. Reentry allowed if price returns to exit level (doesn't count towards limit)
    7. Signal-based cooldowns to prevent overtrading
    """
    
    def __init__(self, config: Dict, kite_client: KiteClient, 
                 alpha_vantage_client: MarketDataClient,
                 db_manager: Database, telegram_bot: TelegramNotifier):
        self.config = config
        self.kite_client = kite_client
        self.alpha_vantage_client = alpha_vantage_client
        self.db_manager = db_manager
        self.telegram_bot = telegram_bot
        self.logger = logging.getLogger(__name__)
        
        # Trading parameters - Load from config
        trading_config = config.get('trading', {})
        self.capital_per_trade = trading_config.get('capital_per_trade', 15000)
        self.fixed_quantity = trading_config.get('fixed_quantity', 150)
        self.max_trades_per_day = trading_config.get('max_trades_per_day', 4)
        # Convert percentage values to decimals for internal calculations
        self.stop_loss_percent = trading_config.get('stop_loss_percent', 20.0) / 100  # 20% -> 0.20
        self.target_percent = trading_config.get('target_percent', 60.0) / 100       # 60% -> 0.60
        self.trailing_sl_percent = trading_config.get('trailing_sl_percent', 20.0) / 100  # 20% -> 0.20
        
        # Market hours
        self.market_start = time(9, 15)
        self.market_end = time(15, 30)
        
        # State tracking
        self.daily_trades: List[Trade] = []
        self.active_positions: Dict[str, Dict] = {}
        self.previous_day_high: Optional[float] = None
        self.previous_day_low: Optional[float] = None
        self.signal_cooldowns: List[SignalCooldown] = []
        self.exit_prices: Dict[str, float] = {}  # Track exit prices for reentry
        self.reentry_trades: List[Trade] = []    # Track reentry trades separately
        
        # Cooldown periods (in minutes)
        self.cooldown_periods = {
            'gap_up': 15,
            'gap_down': 15,
            'breakout_high': 10,
            'breakout_low': 10,
            'reentry': 5
        }
        
        # Price tracking
        self.current_nifty_price = 0.0
        self.opening_price = 0.0
        self.highest_price_today = 0.0
        self.lowest_price_today = float('inf')
        self.market_opened = False
        self.gap_trades_taken = False
        
    async def initialize_day(self):
        """Initialize strategy for the trading day using Alpha Vantage data"""
        try:
            self.logger.info("Initializing trading day...")
            
            # Get previous day's data from Alpha Vantage (with Yahoo Finance fallback)
            prev_high, prev_low = self.alpha_vantage_client.get_previous_day_high_low()
            
            if prev_high is None or prev_low is None:
                self.logger.error("❌ CRITICAL: Failed to get previous day data from all sources")
                self.logger.error("❌ Cannot initialize trading strategy without previous day high/low")
                self.logger.error("❌ Check Alpha Vantage API key and network connectivity")
                raise Exception("Cannot initialize trading strategy: Previous day data unavailable")
            
            self.previous_day_high = prev_high
            self.previous_day_low = prev_low
            
            # Reset daily state
            self.daily_trades = []
            self.active_positions = {}
            self.signal_cooldowns = []
            self.exit_prices = {}
            self.reentry_trades = []
            self.market_opened = False
            self.gap_trades_taken = False
            
            # Load any existing trades from today (skip if method doesn't exist)
            try:
                if hasattr(self.db_manager, 'get_trades_today'):
                    self.daily_trades = await self.db_manager.get_trades_today()
                else:
                    self.daily_trades = []
                    self.logger.info("📝 Starting with empty trade list (database method not implemented)")
            except Exception as e:
                self.logger.warning(f"Could not load existing trades: {e}")
                self.daily_trades = []
            
            self.logger.info(f"✅ Day initialized successfully")
            self.logger.info(f"📈 Previous day high: {prev_high}")
            self.logger.info(f"📉 Previous day low: {prev_low}")
            
            # Send notification
            if self.telegram_bot:
                message = f"🌅 Trading Day Initialized\\n\\nPrevious Day:\\n📈 High: {prev_high}\\n📉 Low: {prev_low}"
                await self.telegram_bot.send_message(message)
            
        except Exception as e:
            self.logger.error(f"❌ CRITICAL: Day initialization failed: {e}")
            raise
    
    def is_signal_in_cooldown(self, signal_type: str, current_price: float) -> bool:
        """Check if a signal type is in cooldown period"""
        now = datetime.now()
        cooldown_minutes = self.cooldown_periods.get(signal_type, 5)
        
        # Clean up old cooldowns
        self.signal_cooldowns = [
            sc for sc in self.signal_cooldowns 
            if (now - sc.timestamp).total_seconds() < cooldown_minutes * 60
        ]
        
        # Check if signal type is in cooldown
        for cooldown in self.signal_cooldowns:
            if cooldown.signal_type == signal_type:
                time_diff = (now - cooldown.timestamp).total_seconds() / 60
                self.logger.info(f"Signal {signal_type} in cooldown - {time_diff:.1f}min remaining")
                return True
        
        return False
    
    def add_signal_cooldown(self, signal_type: str, price: float, symbol: str = "NIFTY"):
        """Add a signal to cooldown tracking"""
        cooldown = SignalCooldown(
            signal_type=signal_type,
            timestamp=datetime.now(),
            price=price,
            symbol=symbol
        )
        self.signal_cooldowns.append(cooldown)
        self.logger.info(f"Added {signal_type} to cooldown at price {price}")
    
    def check_gap_conditions(self, opening_price: float) -> SignalType:
        """
        Check for gap up/down conditions at market open
        
        Args:
            opening_price: Market opening price
            
        Returns:
            Signal type if gap condition detected
        """
        if not self.previous_day_high or not self.previous_day_low:
            return SignalType.NO_SIGNAL
        
        self.opening_price = opening_price
        self.current_nifty_price = opening_price
        
        # Check gap conditions
        if opening_price > self.previous_day_high:
            if not self.is_signal_in_cooldown('gap_up', opening_price):
                self.logger.info(f"🔥 Gap Up detected: Open {opening_price} > Prev High {self.previous_day_high}")
                self.add_signal_cooldown('gap_up', opening_price)
                return SignalType.BUY_CE_GAP
            
        elif opening_price < self.previous_day_low:
            if not self.is_signal_in_cooldown('gap_down', opening_price):
                self.logger.info(f"🔥 Gap Down detected: Open {opening_price} < Prev Low {self.previous_day_low}")
                self.add_signal_cooldown('gap_down', opening_price)
                return SignalType.BUY_PE_GAP
        
        return SignalType.NO_SIGNAL
    
    def check_breakout_conditions(self, current_price: float) -> SignalType:
        """
        Check for breakout conditions during trading
        
        Args:
            current_price: Current NIFTY price
            
        Returns:
            Signal type if breakout detected
        """
        if not self.previous_day_high or not self.previous_day_low:
            return SignalType.NO_SIGNAL
        
        self.current_nifty_price = current_price
        
        # Update daily high/low tracking
        self.highest_price_today = max(self.highest_price_today, current_price)
        self.lowest_price_today = min(self.lowest_price_today, current_price)
        
        # Check breakout above previous day high
        if current_price > self.previous_day_high:
            if not self.is_signal_in_cooldown('breakout_high', current_price):
                self.logger.info(f"🚀 Breakout High: {current_price} > {self.previous_day_high}")
                self.add_signal_cooldown('breakout_high', current_price)
                return SignalType.BUY_CE_BREAKOUT
        
        # Check breakout below previous day low
        elif current_price < self.previous_day_low:
            if not self.is_signal_in_cooldown('breakout_low', current_price):
                self.logger.info(f"💥 Breakout Low: {current_price} < {self.previous_day_low}")
                self.add_signal_cooldown('breakout_low', current_price)
                return SignalType.BUY_PE_BREAKOUT
        
        return SignalType.NO_SIGNAL
    
    def check_reentry_conditions(self) -> SignalType:
        """Check for reentry conditions based on exit prices"""
        if not self.exit_prices:
            return SignalType.NO_SIGNAL
        
        current_price = self.current_nifty_price
        
        for exit_key, exit_price in self.exit_prices.items():
            option_type = exit_key.split('_')[0]  # Extract CE/PE from key
            
            # Check if price has returned to exit level (with 0.2% tolerance)
            tolerance = exit_price * 0.002
            if abs(current_price - exit_price) <= tolerance:
                
                # Verify breakout condition still exists
                if option_type == "CE" and current_price > self.previous_day_high:
                    if not self.is_signal_in_cooldown('reentry', current_price):
                        self.logger.info(f"🔄 CE Reentry at {current_price} (exit was {exit_price})")
                        self.add_signal_cooldown('reentry', current_price)
                        return SignalType.BUY_CE_REENTRY
                        
                elif option_type == "PE" and current_price < self.previous_day_low:
                    if not self.is_signal_in_cooldown('reentry', current_price):
                        self.logger.info(f"🔄 PE Reentry at {current_price} (exit was {exit_price})")
                        self.add_signal_cooldown('reentry', current_price)
                        return SignalType.BUY_PE_REENTRY
        
        return SignalType.NO_SIGNAL
    
    def should_take_trade(self, signal: SignalType) -> bool:
        """
        Check if we should take a trade based on current conditions
        Issue #4 fix: Reentries don't count towards 4-trade limit
        
        Args:
            signal: Trading signal type
            
        Returns:
            True if trade should be taken
        """
        if signal == SignalType.NO_SIGNAL:
            return False
        
        # Check if we're in trading hours
        if not is_trading_hours():
            self.logger.info("⏰ Outside trading hours")
            return False
        
        # Issue #4 fix: For reentry trades, don't count towards daily limit
        is_reentry = signal in [SignalType.BUY_CE_REENTRY, SignalType.BUY_PE_REENTRY]
        
        if not is_reentry:
            # Check daily trade limit for regular trades only (excluding reentries)
            regular_trades_today = len([t for t in self.daily_trades if t not in self.reentry_trades])
            if regular_trades_today >= self.max_trades_per_day:
                self.logger.info(f"📊 Daily trade limit reached: {regular_trades_today}/{self.max_trades_per_day}")
                return False
        else:
            self.logger.info(f"🔄 Reentry trade - doesn't count towards daily limit")
        
        # For gap trades, check if already taken
        if signal in [SignalType.BUY_CE_GAP, SignalType.BUY_PE_GAP]:
            if self.gap_trades_taken:
                self.logger.info("🚫 Gap trades already taken")
                return False
        
        # Check for existing position in same direction
        option_type = "CE" if "CE" in signal.value else "PE"
        
        for symbol, position in self.active_positions.items():
            if position.get('option_type') == option_type and position.get('status') == "OPEN":
                self.logger.info(f"🚫 Already have open {option_type} position: {symbol}")
                return False
        
        # Capital validation - ensure we have enough capital
        required_capital = self.fixed_quantity * 100  # Approximate capital needed (will be refined with actual premium)
        if required_capital > self.capital_per_trade:
            self.logger.warning(f"💰 Insufficient capital: need ~{required_capital}, have {self.capital_per_trade}")
            # Continue anyway as we'll use fixed quantity
        
        return True
    
    async def execute_trade(self, signal: SignalType) -> Optional[Trade]:
        """
        Execute a trade based on the signal with fixed quantity
        
        Args:
            signal: Trading signal
            
        Returns:
            Trade object if successful, None otherwise
        """
        try:
            # Determine option type
            option_type = "CE" if "CE" in signal.value else "PE"
            
            # Get ATM strike
            strike = get_atm_strike(self.current_nifty_price)
            expiry = get_next_expiry()
            
            self.logger.info(f"🎯 Executing {signal.value}: {option_type} {strike} strike")
            
            # Get option chain and find the best strike
            option_chain = await self.kite_client.get_option_chain(expiry)
            
            # Try exact strike first, then nearby strikes
            selected_strike = None
            instrument = None
            
            for try_strike in [strike, strike - 50, strike + 50, strike - 100, strike + 100]:
                if option_type == "CE" and try_strike in option_chain.get('CE', {}):
                    selected_strike = try_strike
                    instrument = option_chain['CE'][try_strike]
                    break
                elif option_type == "PE" and try_strike in option_chain.get('PE', {}):
                    selected_strike = try_strike
                    instrument = option_chain['PE'][try_strike]
                    break
            
            if not instrument:
                self.logger.error(f"❌ No suitable {option_type} option found near strike {strike}")
                return None
            
            # Get current option price
            option_price = await self.kite_client.get_ltp(instrument['instrument_token'])
            
            if option_price <= 0:
                self.logger.error(f"❌ Invalid option price: {option_price}")
                return None
            
            # Use FIXED quantity - 150 units as specified
            quantity = self.fixed_quantity
            
            # Calculate actual capital required
            actual_capital = quantity * option_price
            
            # Log capital usage but proceed with fixed quantity
            self.logger.info(f"💰 Capital usage: {actual_capital} (allocated: {self.capital_per_trade})")
            
            if actual_capital > self.capital_per_trade * 1.1:  # 10% buffer
                self.logger.warning(f"⚠️ Capital usage ({actual_capital}) exceeds allocation ({self.capital_per_trade})")
            
            # Calculate stop loss and target
            stop_loss = calculate_stop_loss(option_price, self.stop_loss_percent)
            target = calculate_target(option_price, self.target_percent)
            
            # Place order (in paper trading mode, this will be simulated)
            symbol = instrument['tradingsymbol']
            
            if self.config.get('paper_trading', True):
                order_id = f"PAPER_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                self.logger.info(f"📝 Paper trade: {symbol} {quantity} @ {option_price}")
            else:
                order_id = await self.kite_client.place_order(
                    tradingsymbol=symbol,
                    transaction_type="BUY",
                    quantity=quantity,
                    order_type="MARKET",
                    product="MIS"
                )
            
            # Create trade record
            entry_reason = {
                SignalType.BUY_CE_BREAKOUT: "BREAKOUT_HIGH",
                SignalType.BUY_PE_BREAKOUT: "BREAKOUT_LOW",
                SignalType.BUY_CE_GAP: "GAP_UP",
                SignalType.BUY_PE_GAP: "GAP_DOWN",
                SignalType.BUY_CE_REENTRY: "REENTRY_CE",
                SignalType.BUY_PE_REENTRY: "REENTRY_PE"
            }[signal]
            
            trade = Trade(
                timestamp=datetime.now(),
                symbol=symbol,
                action="BUY",
                price=option_price,
                quantity=quantity,
                trade_type="ENTRY",
                option_type=option_type,
                strike=selected_strike,
                entry_price=option_price,
                stop_loss=stop_loss,
                target=target,
                reason=entry_reason,
                status="OPEN",
                order_id=order_id,
                highest_price=option_price
            )
            
            # Save to database
            await self.db_manager.save_trade(trade)
            
            # Add to tracking
            self.daily_trades.append(trade)
            self.active_positions[symbol] = {
                'trade': trade,
                'option_type': option_type,
                'status': 'OPEN'
            }
            
            # Track reentry trades separately
            if signal in [SignalType.BUY_CE_REENTRY, SignalType.BUY_PE_REENTRY]:
                self.reentry_trades.append(trade)
                # Remove from exit prices as we've re-entered
                exit_key = f"{option_type}_{selected_strike}"
                if exit_key in self.exit_prices:
                    del self.exit_prices[exit_key]
            
            # Mark gap trades as taken
            if signal in [SignalType.BUY_CE_GAP, SignalType.BUY_PE_GAP]:
                self.gap_trades_taken = True
            
            self.logger.info(f"✅ Trade executed: {symbol} {option_type} qty:{quantity} @ ₹{option_price}")
            
            # Send notification
            if self.telegram_bot:
                message = (f"🚀 Trade Executed\\n\\n"
                          f"Symbol: {symbol}\\n"
                          f"Type: {option_type}\\n"
                          f"Strike: {selected_strike}\\n"
                          f"Entry: ₹{option_price}\\n"
                          f"Quantity: {quantity}\\n"
                          f"Capital: ₹{actual_capital:,.0f}\\n"
                          f"Target: ₹{target}\\n"
                          f"SL: ₹{stop_loss}\\n"
                          f"Reason: {entry_reason}")
                await self.telegram_bot.send_message(message)
            
            return trade
            
        except Exception as e:
            self.logger.error(f"❌ Error executing trade: {e}")
            return None
    
    def get_strategy_status(self) -> dict:
        """Get current strategy status"""
        regular_trades = len([t for t in self.daily_trades if t not in self.reentry_trades])
        reentry_count = len(self.reentry_trades)
        active_count = len([p for p in self.active_positions.values() if p.get('status') == 'OPEN'])
        
        return {
            "day_initialized": self.previous_day_high is not None,
            "market_opened": self.market_opened,
            "gap_trades_taken": self.gap_trades_taken,
            "active_positions": active_count,
            "regular_trades_today": regular_trades,
            "reentry_trades_today": reentry_count,
            "total_trades_today": len(self.daily_trades),
            "current_nifty_price": self.current_nifty_price,
            "prev_high": self.previous_day_high or 0,
            "prev_low": self.previous_day_low or 0,
            "cooldowns_active": len(self.signal_cooldowns),
            "exit_prices_tracked": len(self.exit_prices)
        }
    
    async def process_price_update(self, current_price: float) -> Optional[SignalType]:
        """
        Process a price update and return any signals
        
        Args:
            current_price: Current NIFTY price
            
        Returns:
            Signal type if any signal is detected
        """
        self.current_nifty_price = current_price
        
        # Check different signal types in order of priority
        
        # 1. Gap conditions (only at market open)
        if not self.market_opened:
            signal = self.check_gap_conditions(current_price)
            if signal != SignalType.NO_SIGNAL:
                self.market_opened = True
                return signal
        
        # 2. Reentry conditions (high priority)
        signal = self.check_reentry_conditions()
        if signal != SignalType.NO_SIGNAL:
            return signal
        
        # 3. Breakout conditions
        signal = self.check_breakout_conditions(current_price)
        if signal != SignalType.NO_SIGNAL:
            return signal
        
        return SignalType.NO_SIGNAL
    
    def verify_signal_logic(self, signal: SignalType, current_price: float) -> bool:
        """
        Issue #5: Verify CE/PE Signal Logic
        Buy CE if today's price crosses above yesterday's High.
        Buy PE if today's price crosses below yesterday's Low.
        Gap Up: Buy CE immediately at open.
        Gap Down: Buy PE immediately at open.
        """
        if not self.previous_day_high or not self.previous_day_low:
            self.logger.error("❌ Cannot verify signal - missing previous day data")
            return False
        
        # Verify CE signals (Call Entry)
        if signal in [SignalType.BUY_CE_BREAKOUT, SignalType.BUY_CE_GAP, SignalType.BUY_CE_REENTRY]:
            if current_price > self.previous_day_high:
                self.logger.info(f"✅ CE Signal VERIFIED: {current_price} > {self.previous_day_high} (prev high)")
                return True
            else:
                self.logger.error(f"❌ CE Signal INVALID: {current_price} <= {self.previous_day_high} (prev high)")
                return False
        
        # Verify PE signals (Put Entry) 
        elif signal in [SignalType.BUY_PE_BREAKOUT, SignalType.BUY_PE_GAP, SignalType.BUY_PE_REENTRY]:
            if current_price < self.previous_day_low:
                self.logger.info(f"✅ PE Signal VERIFIED: {current_price} < {self.previous_day_low} (prev low)")
                return True
            else:
                self.logger.error(f"❌ PE Signal INVALID: {current_price} >= {self.previous_day_low} (prev low)")
                return False
        
        return True
    
    async def generate_signal(self, current_price: float) -> Optional[SignalType]:
        """
        Main signal generation method with verification
        
        Args:
            current_price: Current NIFTY price
            
        Returns:
            Verified signal or None
        """
        # Update price tracking
        self.current_nifty_price = current_price
        
        # Process price update to get potential signal
        signal = await self.process_price_update(current_price)
        
        if signal == SignalType.NO_SIGNAL:
            return None
        
        # Issue #5: Verify the signal logic before proceeding
        if not self.verify_signal_logic(signal, current_price):
            self.logger.error(f"❌ Signal {signal.value} failed verification at price {current_price}")
            return None
        
        # Check if we should take the trade
        if not self.should_take_trade(signal):
            return None
        
        return signal

    async def process_market_data(self):
        """Main method to process current market conditions and generate signals"""
        try:
            self.logger.info("🔄 Processing market data...")
            
            # Get current NIFTY price with timeout
            self.logger.info("📊 Fetching current price...")
            current_price = self.alpha_vantage_client.get_current_price()
            
            if current_price is None:
                self.logger.warning("⚠️ Could not get current price - skipping this cycle")
                return
            
            self.logger.info(f"💰 Current NIFTY: {current_price}")
            self.current_nifty_price = current_price
            
            # Update price tracking
            if self.highest_price_today < current_price:
                self.highest_price_today = current_price
            if self.lowest_price_today > current_price:
                self.lowest_price_today = current_price
            
            # Log current status vs previous day levels
            self.logger.info(f"📈 Prev High: {self.previous_day_high} | 📉 Prev Low: {self.previous_day_low}")
            
            # Check if this is market open (first price update)
            if not self.market_opened:
                self.opening_price = current_price
                self.market_opened = True
                self.logger.info(f"📊 Market opened at {current_price}")
                
                # Check for gap conditions at market open
                gap_signal = self.check_gap_conditions(current_price)
                if gap_signal != SignalType.NO_SIGNAL:
                    self.logger.info(f"🎯 Gap signal detected: {gap_signal}")
                    await self.execute_signal(gap_signal, current_price, "GAP")
                    self.gap_trades_taken = True
                else:
                    self.logger.info("📊 No gap signal detected")
            
            # Only check for breakout signals if no gap trades taken
            if not self.gap_trades_taken:
                self.logger.info("🔍 Checking breakout conditions...")
                # Check for breakout signals
                breakout_signal = self.check_breakout_conditions(current_price)
                if breakout_signal != SignalType.NO_SIGNAL:
                    self.logger.info(f"🚀 Breakout signal detected: {breakout_signal}")
                    await self.execute_signal(breakout_signal, current_price, "BREAKOUT")
                else:
                    self.logger.info("📊 No breakout signal - price within range")
            else:
                self.logger.info("⏭️ Gap trades taken - skipping breakout checks")
            
            # Check for reentry opportunities
            self.logger.info("🔄 Checking reentry conditions...")
            reentry_signal = self.check_reentry_conditions()
            if reentry_signal != SignalType.NO_SIGNAL:
                self.logger.info(f"↩️ Reentry signal detected: {reentry_signal}")
                await self.execute_signal(reentry_signal, current_price, "REENTRY")
            
            self.logger.info("✅ Market data processing complete")
                
        except Exception as e:
            self.logger.error(f"❌ Error processing market data: {e}")
            import traceback
            self.logger.error(f"Stack trace: {traceback.format_exc()}")

    async def check_exit_conditions(self):
        """Check exit conditions for all active positions"""
        try:
            if not self.active_positions:
                return
            
            current_price = self.current_nifty_price
            if current_price == 0:
                return
            
            positions_to_close = []
            
            for position_id, position in self.active_positions.items():
                # Get current option price (would use Kite API in real implementation)
                current_option_price = self._get_current_option_price(position)
                
                if current_option_price is None:
                    continue
                
                entry_price = position['entry_price']
                stop_loss = position['stop_loss']
                target = position['target']
                
                # Check stop loss
                if current_option_price <= stop_loss:
                    await self.exit_position(position_id, current_option_price, "STOP_LOSS")
                    positions_to_close.append(position_id)
                
                # Check target
                elif current_option_price >= target:
                    await self.exit_position(position_id, current_option_price, "TARGET")
                    positions_to_close.append(position_id)
                
                # Check trailing stop loss
                elif position.get('highest_price', entry_price) > 0:
                    trailing_sl = position['highest_price'] * (1 - self.trailing_sl_percent)
                    if current_option_price <= trailing_sl:
                        await self.exit_position(position_id, current_option_price, "TRAILING_SL")
                        positions_to_close.append(position_id)
            
            # Remove closed positions
            for position_id in positions_to_close:
                del self.active_positions[position_id]
                
        except Exception as e:
            self.logger.error(f"Error checking exit conditions: {e}")

    def _get_current_option_price(self, position):
        """Get current price for an option position"""
        # In real implementation, this would use Kite API to get current option price
        # For now, simulate based on NIFTY movement
        try:
            if self.kite_client and not self.kite_client.paper_trading:
                # Use real Kite API
                return self.kite_client.get_ltp(position['symbol'])
            else:
                # Simulate price movement for paper trading
                nifty_move_percent = (self.current_nifty_price - position['nifty_price']) / position['nifty_price']
                option_move = position['entry_price'] * (1 + nifty_move_percent * 3)  # Options move ~3x NIFTY
                return max(0.5, option_move)  # Minimum 0.5 rupees
        except Exception as e:
            self.logger.error(f"Error getting option price: {e}")
            return None

    async def execute_signal(self, signal_type: SignalType, current_price: float, signal_source: str):
        """Execute a trading signal"""
        try:
            # Check if we've reached daily trade limit
            regular_trades_today = len([t for t in self.daily_trades if t not in self.reentry_trades])
            if regular_trades_today >= self.max_trades_per_day and signal_source != "REENTRY":
                self.logger.info(f"Daily trade limit reached ({self.max_trades_per_day})")
                return
            
            # Determine option type and strike
            if signal_type in [SignalType.BUY_CE_BREAKOUT, SignalType.BUY_CE_GAP, SignalType.BUY_CE_REENTRY]:
                option_type = "CE"
            else:
                option_type = "PE"
            
            # Get ATM strike (would implement proper strike selection)
            strike = round(current_price / 50) * 50  # Round to nearest 50
            
            # Create trade record
            trade = Trade(
                timestamp=datetime.now(),
                symbol=f"NIFTY{strike}{option_type}",
                action="BUY",
                price=0.0,  # Will be filled by order execution
                quantity=self.fixed_quantity,
                trade_type="ENTRY",
                option_type=option_type,
                strike=strike,
                reason=signal_source
            )
            
            # Execute the trade
            if await self.place_order(trade):
                self.daily_trades.append(trade)
                if signal_source == "REENTRY":
                    self.reentry_trades.append(trade)
                
                # Add signal cooldown
                cooldown_type = signal_source.lower()
                self.add_signal_cooldown(cooldown_type, current_price)
                
                self.logger.info(f"✅ {signal_type.value} executed at {current_price}")
                
                # Send notification
                if self.telegram_bot:
                    message = f"🚀 TRADE EXECUTED\\n\\nSignal: {signal_type.value}\\nPrice: {current_price}\\nStrike: {strike}{option_type}"
                    await self.telegram_bot.send_message(message)
            
        except Exception as e:
            self.logger.error(f"Error executing signal: {e}")

    async def place_order(self, trade: Trade):
        """Place an order through Kite API or paper trading"""
        try:
            if self.kite_client and not self.kite_client.paper_trading:
                # Live trading through Kite
                order_id = await self.kite_client.place_order(
                    symbol=trade.symbol,
                    quantity=trade.quantity,
                    order_type="MARKET",
                    transaction_type=trade.action
                )
                trade.order_id = order_id
                return True
            else:
                # Paper trading
                trade.order_id = f"PAPER_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                trade.price = 100.0  # Simulated option price
                
                # Calculate stop loss and target
                trade.stop_loss = calculate_stop_loss(trade.price, self.stop_loss_percent)
                trade.target = calculate_target(trade.price, self.target_percent)
                
                # Add to active positions
                position = {
                    'trade_id': trade.order_id,
                    'symbol': trade.symbol,
                    'entry_price': trade.price,
                    'quantity': trade.quantity,
                    'stop_loss': trade.stop_loss,
                    'target': trade.target,
                    'nifty_price': self.current_nifty_price,
                    'highest_price': trade.price
                }
                self.active_positions[trade.order_id] = position
                
                self.logger.info(f"📄 Paper trade executed: {trade.symbol} at {trade.price}")
                return True
                
        except Exception as e:
            self.logger.error(f"Error placing order: {e}")
            return False

    async def exit_position(self, position_id: str, exit_price: float, exit_reason: str):
        """Exit a position"""
        try:
            position = self.active_positions.get(position_id)
            if not position:
                return
            
            # Extract position details
            if 'trade' in position:
                # New position format with trade object
                trade_obj = position['trade']
                symbol = trade_obj.symbol
                option_type = trade_obj.option_type
                strike = trade_obj.strike
                entry_price = trade_obj.entry_price
                quantity = trade_obj.quantity
            else:
                # Fallback for older position format
                symbol = position.get('symbol', '')
                option_type = position.get('option_type', 'CE')
                strike = position.get('strike', 0.0)
                entry_price = position.get('entry_price', 0.0)
                quantity = position.get('quantity', 0)
            
            # Calculate P&L
            pnl = (exit_price - entry_price) * quantity
            
            # Create exit trade record
            exit_trade = Trade(
                timestamp=datetime.now(),
                symbol=symbol,
                action="SELL",
                price=exit_price,
                quantity=quantity,
                trade_type="EXIT",
                option_type=option_type,
                strike=strike,
                entry_price=entry_price,
                exit_price=exit_price,
                pnl=pnl,
                reason=exit_reason,
                status="CLOSED"
            )
            
            # Record exit price for potential reentry
            self.exit_prices[symbol] = exit_price
            
            self.logger.info(f"📤 Position exited: {position['symbol']} at {exit_price} ({exit_reason}) P&L: ₹{pnl:.2f}")
            
            # Send notification
            if self.telegram_bot:
                profit_emoji = "📈" if pnl > 0 else "📉"
                message = f"📤 POSITION CLOSED\\n\\n{profit_emoji} {position['symbol']}\\nExit: {exit_price}\\nReason: {exit_reason}\\nP&L: ₹{pnl:.2f}"
                await self.telegram_bot.send_message(message)
            
        except Exception as e:
            self.logger.error(f"Error exiting position: {e}")

    async def end_of_day_cleanup(self):
        """End of day cleanup and preparation for next day"""
        try:
            self.logger.info("🌙 End of day cleanup...")
            
            # Close any remaining positions (if configured to do so)
            # Reset daily state
            # Prepare for next trading day
            
            # Save daily summary to database
            if self.db_manager:
                await self.db_manager.save_daily_summary(self.daily_trades)
            
            self.logger.info("✅ End of day cleanup complete")
            
        except Exception as e:
            self.logger.error(f"Error in end of day cleanup: {e}")

# Alias for backward compatibility
Strategy = TradingStrategy
