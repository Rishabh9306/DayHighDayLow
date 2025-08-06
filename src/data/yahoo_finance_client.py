"""
Yahoo Finance client for Indian market data fallback
Since Alpha Vantage free tier has limited Indian market coverage
"""

import requests
import logging
import time
from datetime import datetime, date, timedelta
from typing import Tuple, Optional
import json

class YahooFinanceClient:
    """Fallback client for Indian market data using Yahoo Finance with caching"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.base_url = "https://query1.finance.yahoo.com/v8/finance/chart"
        
        # Yahoo Finance symbols for NIFTY 50
        self.nifty_symbol = "^NSEI"  # NSE NIFTY 50 Index
        
        # Caching for rate limiting
        self.cache = {}
        self.cache_duration = 30  # Cache for 30 seconds
        self.last_request_time = 0
        self.min_request_interval = 5  # 5 seconds between requests
    
    def get_previous_trading_day(self) -> date:
        """Get the previous trading day (skip weekends)"""
        today = date.today()
        
        # Go back until we find a weekday
        days_back = 1
        while True:
            prev_date = today - timedelta(days=days_back)
            # Skip weekends (Saturday=5, Sunday=6)
            if prev_date.weekday() < 5:  # Monday=0 to Friday=4
                return prev_date
            days_back += 1
            
            # Safety check - don't go back more than 7 days
            if days_back > 7:
                break
        
        return today - timedelta(days=1)
    
    def fetch_nifty_data(self, days_back: int = 5) -> Optional[dict]:
        """
        Fetch NIFTY data from Yahoo Finance
        
        Args:
            days_back: Number of days of historical data to fetch
            
        Returns:
            Dictionary with OHLC data or None if failed
        """
        try:
            # Calculate time range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            
            # Convert to Unix timestamps
            start_timestamp = int(start_date.timestamp())
            end_timestamp = int(end_date.timestamp())
            
            # Yahoo Finance API parameters
            params = {
                'period1': start_timestamp,
                'period2': end_timestamp,
                'interval': '1d',  # Daily data
                'includePrePost': 'false',
                'events': 'div,splits'
            }
            
            url = f"{self.base_url}/{self.nifty_symbol}"
            
            self.logger.info(f"Fetching NIFTY data from Yahoo Finance: {self.nifty_symbol}")
            
            # Set headers to mimic a browser request
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            
            # Parse Yahoo Finance response
            if 'chart' not in data or not data['chart']['result']:
                self.logger.error("Invalid response format from Yahoo Finance")
                return None
            
            result = data['chart']['result'][0]
            
            if 'timestamp' not in result or not result['timestamp']:
                self.logger.error("No timestamp data in Yahoo Finance response")
                return None
            
            # Extract OHLC data
            timestamps = result['timestamp']
            indicators = result['indicators']['quote'][0]
            
            if not all(key in indicators for key in ['open', 'high', 'low', 'close']):
                self.logger.error("Missing OHLC data in Yahoo Finance response")
                return None
            
            # Convert to date-indexed format
            ohlc_data = {}
            for i, timestamp in enumerate(timestamps):
                date_str = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')
                
                # Skip entries with null values
                if (indicators['open'][i] is not None and 
                    indicators['high'][i] is not None and 
                    indicators['low'][i] is not None and 
                    indicators['close'][i] is not None):
                    
                    ohlc_data[date_str] = {
                        'open': float(indicators['open'][i]),
                        'high': float(indicators['high'][i]),
                        'low': float(indicators['low'][i]),
                        'close': float(indicators['close'][i]),
                        'volume': float(indicators.get('volume', [0])[i] or 0)
                    }
            
            self.logger.info(f"✅ Successfully fetched {len(ohlc_data)} days of NIFTY data from Yahoo Finance")
            return ohlc_data
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Network error fetching Yahoo Finance data: {e}")
            return None
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            self.logger.error(f"Error parsing Yahoo Finance data: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error fetching Yahoo Finance data: {e}")
            return None
    
    def get_previous_day_high_low(self) -> Tuple[Optional[float], Optional[float]]:
        """
        Get previous trading day's high and low for NIFTY
        
        Returns:
            Tuple of (previous_high, previous_low) or (None, None) if failed
        """
        try:
            # Get previous trading day
            prev_day = self.get_previous_trading_day()
            prev_day_str = prev_day.strftime('%Y-%m-%d')
            
            self.logger.info(f"Fetching NIFTY data for previous trading day: {prev_day_str}")
            
            # Fetch data
            ohlc_data = self.fetch_nifty_data(days_back=7)  # Get week of data to ensure we have the previous day
            
            if not ohlc_data:
                self.logger.error("Failed to fetch NIFTY data from Yahoo Finance")
                return None, None
            
            # Look for previous day's data
            if prev_day_str in ohlc_data:
                day_data = ohlc_data[prev_day_str]
                high = day_data['high']
                low = day_data['low']
                
                self.logger.info(f"✅ Found NIFTY data for {prev_day_str} - High: {high}, Low: {low}")
                return high, low
            else:
                # If exact date not found, get the most recent available date
                sorted_dates = sorted(ohlc_data.keys(), reverse=True)
                if sorted_dates:
                    latest_date = sorted_dates[0]
                    day_data = ohlc_data[latest_date]
                    high = day_data['high']
                    low = day_data['low']
                    
                    self.logger.info(f"✅ Using latest NIFTY data ({latest_date}) - High: {high}, Low: {low}")
                    return high, low
                else:
                    self.logger.error("No NIFTY data available")
                    return None, None
            
        except Exception as e:
            self.logger.error(f"Error getting previous day high/low from Yahoo Finance: {e}")
            return None, None
    
    def get_current_price(self) -> Optional[float]:
        """
        Get current NIFTY price (real-time) with caching and rate limiting
        
        Returns:
            Current price or None if failed
        """
        try:
            current_time = time.time()
            
            # Check cache first
            if 'current_price' in self.cache:
                cache_time, cached_price = self.cache['current_price']
                if current_time - cache_time < self.cache_duration:
                    self.logger.info(f"📋 Yahoo Finance: Using cached price: {cached_price}")
                    return cached_price
            
            # Rate limiting check
            if current_time - self.last_request_time < self.min_request_interval:
                wait_time = self.min_request_interval - (current_time - self.last_request_time)
                self.logger.info(f"⏸️ Yahoo Finance rate limiting: waiting {wait_time:.1f}s")
                time.sleep(wait_time)
            
            # First try to get real-time quote data
            quote_url = f"https://query1.finance.yahoo.com/v8/finance/chart/{self.nifty_symbol}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            # Parameters for real-time data
            params = {
                'interval': '1m',  # 1-minute intervals for real-time
                'range': '1d',     # Today's data
                'includePrePost': 'false'
            }
            
            response = requests.get(quote_url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if 'chart' in data and 'result' in data['chart'] and data['chart']['result']:
                result = data['chart']['result'][0]
                
                # Get meta data for current price
                if 'meta' in result and 'regularMarketPrice' in result['meta']:
                    current_price = result['meta']['regularMarketPrice']
                    self.logger.info(f"Real-time NIFTY price: {current_price}")
                    # Cache the result
                    self.cache['current_price'] = (current_time, current_price)
                    self.last_request_time = current_time
                    return current_price
                
                # Fallback: get latest close from timestamps
                if 'timestamp' in result and 'indicators' in result:
                    timestamps = result['timestamp']
                    indicators = result['indicators']
                    
                    if 'quote' in indicators and indicators['quote']:
                        quote_data = indicators['quote'][0]
                        
                        if 'close' in quote_data and quote_data['close']:
                            # Get the last non-null close price
                            closes = quote_data['close']
                            for close_price in reversed(closes):
                                if close_price is not None:
                                    self.logger.info(f"Latest NIFTY close price: {close_price}")
                                    # Cache the result
                                    self.cache['current_price'] = (current_time, close_price)
                                    self.last_request_time = current_time
                                    return close_price
            
            # If real-time fails, fallback to previous method (historical close)
            self.logger.warning("Real-time data not available, falling back to latest historical close")
            ohlc_data = self.fetch_nifty_data(days_back=2)
            
            if not ohlc_data:
                return None
            
            # Get most recent date
            sorted_dates = sorted(ohlc_data.keys(), reverse=True)
            if sorted_dates:
                latest_date = sorted_dates[0]
                latest_data = ohlc_data[latest_date]
                close_price = latest_data['close']
                
                self.logger.info(f"Historical NIFTY close ({latest_date}): {close_price}")
                # Cache the result
                self.cache['current_price'] = (current_time, close_price)
                self.last_request_time = current_time
                return close_price
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting current NIFTY price from Yahoo Finance: {e}")
            return None
    
    def test_connection(self) -> bool:
        """Test Yahoo Finance connection"""
        try:
            self.logger.info("Testing Yahoo Finance connection...")
            
            ohlc_data = self.fetch_nifty_data(days_back=1)
            
            if ohlc_data and len(ohlc_data) > 0:
                self.logger.info("✅ Yahoo Finance connection successful")
                return True
            else:
                self.logger.error("❌ Yahoo Finance connection failed - no data returned")
                return False
            
        except Exception as e:
            self.logger.error(f"❌ Yahoo Finance connection failed: {e}")
            return False
