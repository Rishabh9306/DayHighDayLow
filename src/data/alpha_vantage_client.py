"""
Alpha Vantage API client for fetching previous day NIFTY data
With Yahoo Finance and NSE Official API fallbacks for reliable Indian market data
Priority: Yahoo Finance → NSE Official → Alpha Vantage
"""

import requests
import logging
import time
from datetime import datetime, date, timedelta
from typing import Tuple, Optional
import json

class AlphaVantageClient:
    """Client for fetching NIFTY data with multiple fallback sources"""
    
    def __init__(self, api_key: str, logger=None):
        """Initialize Alpha Vantage client with Yahoo Finance and NSE fallbacks"""
        self.api_key = api_key
        self.base_url = "https://www.alphavantage.co/query"
        self.logger = logger or logging.getLogger(__name__)
        
        # Rate limiting and caching
        self.last_request_time = 0
        self.min_request_interval = 15  # 15 seconds between requests
        self.price_cache = {}
        self.price_cache_duration = 30  # Cache price for 30 seconds
        
        # Initialize fallback clients (lazy loading)
        self._yahoo_client = None
        self._nse_client = None
        
        # NIFTY symbols to try for Alpha Vantage
        self.nifty_symbols = [
            "NSEI.BSE",    # BSE NIFTY
            "^NSEI",       # Yahoo Finance format
            "NSEI",        # NSE NIFTY
            "NSE:NIFTY",   # Alternative format
            "NIFTY 50",    # Long form
            "INDA",        # iShares MSCI India ETF (US-listed proxy)
            "MINDX"        # VanEck Vectors India Small-Cap Index ETF
        ]
    
    def _get_yahoo_client(self):
        """Lazy load Yahoo Finance client"""
        if self._yahoo_client is None:
            try:
                from .yahoo_finance_client import YahooFinanceClient
                self._yahoo_client = YahooFinanceClient()
            except ImportError as e:
                self.logger.error(f"Failed to import Yahoo Finance client: {e}")
                self._yahoo_client = None
        return self._yahoo_client
    
    def _get_nse_client(self):
        """Lazy load NSE Official API client"""
        if self._nse_client is None:
            try:
                from .nse_client import NSEClient
                self._nse_client = NSEClient()
            except ImportError as e:
                self.logger.error(f"Failed to import NSE client: {e}")
                self._nse_client = None
        return self._nse_client
    
    def fetch_daily_data(self, symbol: str) -> Optional[dict]:
        """Fetch daily OHLC data from Alpha Vantage for a given symbol"""
        functions = ['TIME_SERIES_DAILY', 'GLOBAL_QUOTE']
        
        try:
            for function in functions:
                params = {
                    'function': function,
                    'symbol': symbol,
                    'apikey': self.api_key,
                    'outputsize': 'compact'
                }
                
                response = requests.get(self.base_url, params=params, timeout=15)
                response.raise_for_status()
                
                data = response.json()
                
                # Check for API errors
                if 'Error Message' in data:
                    self.logger.error(f"Alpha Vantage API Error for {symbol}: {data['Error Message']}")
                    continue
                
                if 'Note' in data:
                    self.logger.warning(f"Alpha Vantage API Note for {symbol}: {data['Note']}")
                    continue
                
                # Handle different response formats
                if function == 'GLOBAL_QUOTE' and 'Global Quote' in data:
                    # Convert GLOBAL_QUOTE format to TIME_SERIES_DAILY format
                    quote = data['Global Quote']
                    if quote and '02. open' in quote:
                        # Create a single day entry in TIME_SERIES format
                        date_key = quote.get('07. latest trading day', '')
                        if date_key:
                            converted_data = {
                                date_key: {
                                    '1. open': quote.get('02. open', '0'),
                                    '2. high': quote.get('03. high', '0'),
                                    '3. low': quote.get('04. low', '0'),
                                    '4. close': quote.get('05. price', '0'),
                                    '5. volume': quote.get('06. volume', '0')
                                }
                            }
                            self.logger.info(f"✅ Found GLOBAL_QUOTE data for {symbol}")
                            return converted_data
                
                elif 'Time Series (Daily)' in data:
                    self.logger.info(f"✅ Found TIME_SERIES_DAILY data for {symbol}")
                    return data['Time Series (Daily)']
                
                elif 'Time Series (Daily) (Adjusted)' in data:
                    # Use adjusted data if available
                    self.logger.info(f"✅ Found adjusted daily data for {symbol}")
                    return data['Time Series (Daily) (Adjusted)']
            
            self.logger.warning(f"No data found for {symbol} with any function")
            return None
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Network error fetching data for {symbol}: {e}")
            return None
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON decode error for {symbol}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error fetching data for {symbol}: {e}")
            return None
    
    def get_previous_day_high_low(self) -> Tuple[Optional[float], Optional[float]]:
        """
        Get previous trading day's high and low prices
        Priority: Yahoo Finance → NSE Official → Alpha Vantage
        """
        try:
            # Try Yahoo Finance FIRST (fastest and most reliable)
            self.logger.info("🚀 Fetching previous day data from Yahoo Finance (primary)...")
            yahoo_client = self._get_yahoo_client()
            
            if yahoo_client:
                high, low = yahoo_client.get_previous_day_high_low()
                if high is not None and low is not None:
                    self.logger.info(f"✅ Yahoo Finance: Previous day data - High: {high}, Low: {low}")
                    return high, low
                else:
                    self.logger.warning("⚠️ Yahoo Finance failed to fetch previous day data")
            else:
                self.logger.warning("⚠️ Yahoo Finance client not available")
            
            # Try NSE Official API SECOND (Indian market specific)
            self.logger.info("🇮🇳 Yahoo Finance failed, trying NSE Official API...")
            nse_client = self._get_nse_client()
            
            if nse_client:
                # NSE doesn't provide previous day high/low directly, but we can try current data
                nse_data = nse_client.get_nifty_data()
                if nse_data and 'prev_close' in nse_data:
                    # For NSE, we might need to use current day data as approximation
                    # This is a limitation of NSE API for historical data
                    self.logger.info("⚠️ NSE: Previous day high/low not available via current API")
                    # Fall through to Alpha Vantage for historical data
                else:
                    self.logger.warning("⚠️ NSE failed to fetch market data")
            else:
                self.logger.warning("⚠️ NSE client not available")
            
            # Try Alpha Vantage as FINAL fallback
            self.logger.info("📈 Trying Alpha Vantage for previous day data...")
            for symbol in self.nifty_symbols:
                daily_data = self.fetch_daily_data(symbol)
                
                if daily_data:
                    # Get most recent trading day (skip today if it's partial)
                    sorted_dates = sorted(daily_data.keys(), reverse=True)
                    
                    if len(sorted_dates) >= 2:
                        # Use second most recent date (yesterday)
                        yesterday = sorted_dates[1]
                        day_data = daily_data[yesterday]
                        high = float(day_data['2. high'])
                        low = float(day_data['3. low'])
                        
                        self.logger.info(f"✅ Alpha Vantage: Previous day data for {symbol} ({yesterday}) - High: {high}, Low: {low}")
                        return high, low
                    elif len(sorted_dates) >= 1:
                        # Use most recent date if only one available
                        latest_date = sorted_dates[0]
                        day_data = daily_data[latest_date]
                        high = float(day_data['2. high'])
                        low = float(day_data['3. low'])
                        
                        self.logger.info(f"✅ Alpha Vantage: Using latest data for {symbol} ({latest_date}) - High: {high}, Low: {low}")
                        return high, low
            
            # All sources failed
            self.logger.error("❌ CRITICAL: Failed to fetch previous day data from ALL sources (Yahoo Finance, NSE, Alpha Vantage)")
            return None, None
            
        except Exception as e:
            self.logger.error(f"Error getting previous day high/low: {e}")
            return None, None
    
    def get_current_price(self) -> Optional[float]:
        """
        Get current NIFTY price with enhanced fallback chain
        Priority: Yahoo Finance → NSE Official → Alpha Vantage
        """
        try:
            current_time = time.time()
            
            # Check cache first
            if 'current_price' in self.price_cache:
                cache_time, cached_price = self.price_cache['current_price']
                if current_time - cache_time < self.price_cache_duration:
                    self.logger.info(f"📋 Using cached current price: {cached_price}")
                    return cached_price
            
            # Rate limiting check
            if current_time - self.last_request_time < self.min_request_interval:
                wait_time = self.min_request_interval - (current_time - self.last_request_time)
                self.logger.info(f"⏸️ Rate limiting: waiting {wait_time:.1f}s before next request")
                time.sleep(wait_time)
            
            # 1. Try Yahoo Finance FIRST (fastest and most reliable)
            self.logger.info("🚀 Fetching current price from Yahoo Finance (primary)...")
            yahoo_client = self._get_yahoo_client()
            
            if yahoo_client:
                current_price = yahoo_client.get_current_price()
                if current_price is not None:
                    self.logger.info(f"✅ Yahoo Finance: Current price: {current_price}")
                    # Cache the result
                    self.price_cache['current_price'] = (current_time, current_price)
                    self.last_request_time = current_time
                    return current_price
                else:
                    self.logger.warning("⚠️ Yahoo Finance returned None for current price")
            else:
                self.logger.warning("⚠️ Yahoo Finance client not available")
            
            # 2. Try NSE Official API SECOND (Indian market specific and reliable)
            self.logger.info("🇮🇳 Yahoo Finance failed, trying NSE Official API (secondary)...")
            nse_client = self._get_nse_client()
            
            if nse_client:
                current_price = nse_client.get_current_price()
                if current_price is not None:
                    self.logger.info(f"✅ NSE Official: Current price: {current_price}")
                    # Cache the result
                    self.price_cache['current_price'] = (current_time, current_price)
                    self.last_request_time = current_time
                    return current_price
                else:
                    self.logger.warning("⚠️ NSE Official API returned None for current price")
            else:
                self.logger.warning("⚠️ NSE client not available")
            
            # 3. Try Alpha Vantage as FINAL fallback
            self.logger.info("📈 NSE failed, trying Alpha Vantage as final fallback...")
            for symbol in self.nifty_symbols[:2]:  # Only try first 2 symbols to save API calls
                daily_data = self.fetch_daily_data(symbol)
                
                if daily_data:
                    # Get most recent date
                    sorted_dates = sorted(daily_data.keys(), reverse=True)
                    if sorted_dates:
                        latest_date = sorted_dates[0]
                        latest_data = daily_data[latest_date]
                        close_price = float(latest_data['4. close'])
                        
                        self.logger.info(f"✅ Alpha Vantage: Current price from {symbol} ({latest_date}): {close_price}")
                        # Cache the result
                        self.price_cache['current_price'] = (current_time, close_price)
                        self.last_request_time = current_time
                        return close_price
            
            # All sources failed
            self.logger.error("❌ CRITICAL: Failed to fetch current price from ALL sources (Yahoo Finance, NSE Official, Alpha Vantage)")
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting current price: {e}")
            return None
    
    def test_connection(self) -> bool:
        """Test API connection and fallback chain"""
        try:
            self.logger.info("🔌 Testing data source connections...")
            
            # Test Yahoo Finance
            yahoo_client = self._get_yahoo_client()
            if yahoo_client and yahoo_client.test_connection():
                self.logger.info("✅ Yahoo Finance connection successful")
            else:
                self.logger.warning("⚠️ Yahoo Finance connection failed")
            
            # Test NSE Official API
            nse_client = self._get_nse_client()
            if nse_client and nse_client.test_connection():
                self.logger.info("✅ NSE Official API connection successful")
            else:
                self.logger.warning("⚠️ NSE Official API connection failed")
            
            # Test Alpha Vantage
            prev_high, prev_low = self.get_previous_day_high_low()
            if prev_high is None or prev_low is None:
                self.logger.error("❌ All data source connections failed")
                return False
            
            self.logger.info("✅ At least one data source connection successful")
            return True
            
        except Exception as e:
            self.logger.error(f"Connection test failed: {e}")
            return False
