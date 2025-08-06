"""
Zerodha Kite API Client for trading operations
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import json

try:
    from kiteconnect import KiteConnect, KiteTicker
except ImportError:
    print("kiteconnect library not installed. Run: pip install kiteconnect")
    KiteConnect = None
    KiteTicker = None

from src.utils.helpers import get_next_expiry, get_atm_strike

class KiteClient:
    """Wrapper class for Kite API operations"""
    
    def __init__(self, api_key: str, api_secret: str, access_token: str = None, 
                 redirect_url: str = None, paper_trading: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = access_token
        self.redirect_url = redirect_url
        self.paper_trading = paper_trading
        self.logger = logging.getLogger(__name__)
        
        if KiteConnect is None:
            raise ImportError("kiteconnect library not available")
            
        self.kite = KiteConnect(api_key=api_key)
        if access_token:
            self.kite.set_access_token(access_token)
        
        # WebSocket ticker
        self.ticker = None
        self.subscribed_tokens = set()
        self.price_callbacks = {}
        
        # Cache for instrument data
        self.instruments = {}
        self.nifty_token = None
        
        # Paper trading simulation
        self.paper_trades = {}
        self.paper_order_id = 1000
        
    def generate_session(self, request_token: str) -> str:
        """
        Generate access token using request token
        
        Args:
            request_token: Request token from Kite login
            
        Returns:
            Access token
        """
        try:
            data = self.kite.generate_session(request_token, api_secret=self.api_secret)
            self.access_token = data["access_token"]
            self.kite.set_access_token(self.access_token)
            self.logger.info("Successfully generated access token")
            return self.access_token
        except Exception as e:
            self.logger.error(f"Error generating session: {e}")
            raise
    
    def get_login_url(self) -> str:
        """Get Kite login URL"""
        if self.redirect_url:
            return f"https://kite.trade/connect/login?api_key={self.api_key}&redirect_params=state"
        return self.kite.login_url()
    
    async def initialize_instruments(self):
        """Load and cache instrument data"""
        try:
            self.logger.info("Loading instrument data...")
            instruments = self.kite.instruments("NFO")  # NSE F&O segment
            
            # Cache instruments by symbol
            for instrument in instruments:
                symbol = instrument['tradingsymbol']
                self.instruments[symbol] = instrument
                
                # Find NIFTY spot token for price monitoring
                if symbol == "NIFTY 50":
                    self.nifty_token = instrument['instrument_token']
            
            # Also get NIFTY index from NSE
            nse_instruments = self.kite.instruments("NSE")
            for instrument in nse_instruments:
                if instrument['name'] == 'NIFTY 50':
                    self.nifty_token = instrument['instrument_token']
                    break
                    
            self.logger.info(f"Loaded {len(self.instruments)} instruments")
            
        except Exception as e:
            self.logger.error(f"Error loading instruments: {e}")
            raise
    
    def get_previous_day_data(self) -> Tuple[float, float]:
        """
        Get previous day's high and low for NIFTY
        
        Returns:
            Tuple of (previous_high, previous_low)
        """
        try:
            # Get historical data for yesterday
            from_date = datetime.now() - timedelta(days=2)
            to_date = datetime.now() - timedelta(days=1)
            
            historical_data = self.kite.historical_data(
                instrument_token=self.nifty_token,
                from_date=from_date,
                to_date=to_date,
                interval="day"
            )
            
            if historical_data:
                last_day = historical_data[-1]
                prev_high = last_day['high']
                prev_low = last_day['low']
                
                self.logger.info(f"Previous day: High={prev_high}, Low={prev_low}")
                return prev_high, prev_low
            else:
                raise ValueError("No historical data available")
                
        except Exception as e:
            self.logger.error(f"Error fetching previous day data: {e}")
            raise
    
    def get_current_price(self, instrument_token: int) -> float:
        """
        Get current price for an instrument
        
        Args:
            instrument_token: Instrument token
            
        Returns:
            Current price
        """
        try:
            quote = self.kite.quote([instrument_token])
            token_str = str(instrument_token)
            if token_str in quote:
                return quote[token_str]['last_price']
            else:
                raise ValueError(f"No quote data for token {instrument_token}")
        except Exception as e:
            self.logger.error(f"Error getting current price: {e}")
            raise
    
    def get_option_chain(self, expiry: str = None) -> Dict:
        """
        Get option chain for NIFTY
        
        Args:
            expiry: Expiry date in YYMMDD format
            
        Returns:
            Dictionary with CE and PE option data
        """
        if not expiry:
            expiry = get_next_expiry()
        
        try:
            option_chain = {'CE': {}, 'PE': {}}
            
            for symbol, instrument in self.instruments.items():
                if 'NIFTY' in symbol and expiry in symbol:
                    if symbol.endswith('CE'):
                        strike = int(symbol.split(expiry)[1].replace('CE', ''))
                        option_chain['CE'][strike] = instrument
                    elif symbol.endswith('PE'):
                        strike = int(symbol.split(expiry)[1].replace('PE', ''))
                        option_chain['PE'][strike] = instrument
            
            return option_chain
        except Exception as e:
            self.logger.error(f"Error getting option chain: {e}")
            return {'CE': {}, 'PE': {}}
    
    def place_order(self, tradingsymbol: str, transaction_type: str, 
                   quantity: int, order_type: str = "MARKET", 
                   product: str = "MIS") -> str:
        """
        Place an order
        
        Args:
            tradingsymbol: Trading symbol
            transaction_type: BUY or SELL
            quantity: Number of shares/contracts
            order_type: Order type (MARKET, LIMIT, etc.)
            product: Product type (MIS, CNC, NRML)
            
        Returns:
            Order ID
        """
        try:
            if self.paper_trading:
                # Simulate order placement
                order_id = f"PAPER_{self.paper_order_id}"
                self.paper_order_id += 1
                
                # Store paper trade details
                self.paper_trades[order_id] = {
                    'tradingsymbol': tradingsymbol,
                    'transaction_type': transaction_type,
                    'quantity': quantity,
                    'order_type': order_type,
                    'product': product,
                    'status': 'COMPLETE',
                    'timestamp': datetime.now()
                }
                
                self.logger.info(f"📝 PAPER TRADE - Order placed: {order_id} for {tradingsymbol} ({transaction_type})")
                return order_id
            else:
                # Real order placement
                order_id = self.kite.place_order(
                    variety=self.kite.VARIETY_REGULAR,
                    exchange=self.kite.EXCHANGE_NFO,
                    tradingsymbol=tradingsymbol,
                    transaction_type=transaction_type,
                    quantity=quantity,
                    product=product,
                    order_type=order_type
                )
                
                self.logger.info(f"💰 LIVE TRADE - Order placed: {order_id} for {tradingsymbol}")
                return order_id
            
        except Exception as e:
            self.logger.error(f"Error placing order: {e}")
            raise
    
    def get_orders(self) -> List[Dict]:
        """Get all orders for the day"""
        try:
            return self.kite.orders()
        except Exception as e:
            self.logger.error(f"Error getting orders: {e}")
            return []
    
    def get_positions(self) -> List[Dict]:
        """Get current positions"""
        try:
            positions = self.kite.positions()
            return positions['net']  # Return net positions
        except Exception as e:
            self.logger.error(f"Error getting positions: {e}")
            return []
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order"""
        try:
            self.kite.cancel_order(
                variety=self.kite.VARIETY_REGULAR,
                order_id=order_id
            )
            self.logger.info(f"Order cancelled: {order_id}")
            return True
        except Exception as e:
            self.logger.error(f"Error cancelling order: {e}")
            return False
    
    # WebSocket methods for real-time data
    def start_websocket(self):
        """Start WebSocket connection for real-time data"""
        if KiteTicker is None:
            self.logger.error("KiteTicker not available")
            return
            
        try:
            self.ticker = KiteTicker(self.api_key, self.access_token)
            self.ticker.on_ticks = self._on_ticks
            self.ticker.on_connect = self._on_connect
            self.ticker.on_close = self._on_close
            self.ticker.on_error = self._on_error
            
            self.ticker.connect(threaded=True)
            self.logger.info("WebSocket connection started")
            
        except Exception as e:
            self.logger.error(f"Error starting WebSocket: {e}")
    
    def subscribe_price_updates(self, tokens: List[int], callback=None):
        """Subscribe to price updates for given tokens"""
        if self.ticker:
            self.ticker.subscribe(tokens)
            self.subscribed_tokens.update(tokens)
            
            if callback:
                for token in tokens:
                    self.price_callbacks[token] = callback
    
    def _on_ticks(self, ws, ticks):
        """Handle incoming tick data"""
        for tick in ticks:
            token = tick['instrument_token']
            if token in self.price_callbacks:
                self.price_callbacks[token](tick)
    
    def _on_connect(self, ws, response):
        """Handle WebSocket connection"""
        self.logger.info("WebSocket connected")
        if self.nifty_token:
            self.subscribe_price_updates([self.nifty_token])
    
    def _on_close(self, ws, code, reason):
        """Handle WebSocket close"""
        self.logger.warning(f"WebSocket closed: {code} - {reason}")
    
    def _on_error(self, ws, code, reason):
        """Handle WebSocket error"""
        self.logger.error(f"WebSocket error: {code} - {reason}")
    
    def stop_websocket(self):
        """Stop WebSocket connection"""
        if self.ticker:
            self.ticker.close()
            self.logger.info("WebSocket connection closed")
