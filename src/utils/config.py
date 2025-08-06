"""
Configuration Management for Trading Bot
"""

import os
import yaml
from typing import Dict, Any
from dataclasses import dataclass

def load_env_file(env_file_path=".env"):
    """Load environment variables from .env file"""
    if not os.path.exists(env_file_path):
        return False
    
    with open(env_file_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"\'')
                os.environ[key] = value
    return True

def validate_required_vars():
    """Validate that all required environment variables are set"""
    required_vars = ["KITE_API_KEY", "KITE_API_SECRET", "KITE_USER_ID", "ALPHA_VANTAGE_API_KEY"]
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    
    if missing_vars:
        print(f"❌ Missing environment variables: {', '.join(missing_vars)}")
        # Debug: Show what env vars are actually set
        available_vars = [var for var in required_vars if os.environ.get(var)]
        print(f"✅ Available environment variables: {', '.join(available_vars)}")
        
    return len(missing_vars) == 0

class ConfigManager:
    """Configuration manager with environment variable support"""
    
    @staticmethod
    def load_config(config_file: str = "config/config.yaml") -> Dict[str, Any]:
        """Load configuration from YAML file with environment variable substitution"""
        with open(config_file, 'r') as file:
            config_data = yaml.safe_load(file)
        
        # Substitute environment variables
        def substitute_env_vars(obj):
            if isinstance(obj, dict):
                return {k: substitute_env_vars(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [substitute_env_vars(item) for item in obj]
            elif isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
                env_var = obj[2:-1]
                return os.environ.get(env_var, obj)
            else:
                return obj
        
        return substitute_env_vars(config_data)

@dataclass
class TradingConfig:
    """Trading configuration parameters"""
    capital_per_trade: int = 15000
    max_trades_per_day: int = 4
    stop_loss_percent: float = 20.0
    target_percent: float = 60.0
    trailing_sl_percent: float = 20.0
    paper_trading: bool = True
    
@dataclass
class KiteConfig:
    """Kite API configuration"""
    api_key: str = ""
    api_secret: str = ""
    request_token: str = ""
    access_token: str = ""
    redirect_url: str = ""
    postback_url: str = ""

@dataclass
class TelegramConfig:
    """Telegram bot configuration"""
    bot_token: str = ""
    chat_id: str = ""

class Config:
    """Main configuration class"""
    
    def __init__(self, config_file: str = "config/config.yaml"):
        self.config_file = config_file
        self.trading = TradingConfig()
        self.kite = KiteConfig()
        self.telegram = TelegramConfig()
        
        # Load configuration if file exists
        if os.path.exists(config_file):
            self.load_config()
        else:
            self.create_default_config()
    
    def load_config(self):
        """Load configuration from YAML file"""
        try:
            with open(self.config_file, 'r') as file:
                config_data = yaml.safe_load(file)
                
            # Update trading config
            if 'trading' in config_data:
                trading_data = config_data['trading']
                self.trading.capital_per_trade = trading_data.get('capital_per_trade', 15000)
                self.trading.max_trades_per_day = trading_data.get('max_trades_per_day', 4)
                self.trading.stop_loss_percent = trading_data.get('stop_loss_percent', 20.0)
                self.trading.target_percent = trading_data.get('target_percent', 60.0)
                self.trading.trailing_sl_percent = trading_data.get('trailing_sl_percent', 20.0)
                self.trading.paper_trading = trading_data.get('paper_trading', True)
            
            # Update Kite config
            if 'kite' in config_data:
                kite_data = config_data['kite']
                self.kite.api_key = kite_data.get('api_key', '')
                self.kite.api_secret = kite_data.get('api_secret', '')
                self.kite.request_token = kite_data.get('request_token', '')
                self.kite.access_token = kite_data.get('access_token', '')
                self.kite.redirect_url = kite_data.get('redirect_url', '')
                self.kite.postback_url = kite_data.get('postback_url', '')
            
            # Update Telegram config
            if 'telegram' in config_data:
                telegram_data = config_data['telegram']
                self.telegram.bot_token = telegram_data.get('bot_token', '')
                self.telegram.chat_id = telegram_data.get('chat_id', '')
                
        except Exception as e:
            print(f"Error loading config: {e}")
            self.create_default_config()
    
    def create_default_config(self):
        """Create default configuration file"""
        default_config = {
            'trading': {
                'capital_per_trade': 15000,
                'max_trades_per_day': 4,
                'stop_loss_percent': 20.0,
                'target_percent': 60.0,
                'trailing_sl_percent': 20.0,
                'paper_trading': True
            },
            'kite': {
                'api_key': 'your_kite_api_key_here',
                'api_secret': 'your_kite_api_secret_here',
                'request_token': '',
                'access_token': '',
                'redirect_url': '',
                'postback_url': ''
            },
            'telegram': {
                'bot_token': 'your_telegram_bot_token_here',
                'chat_id': 'your_telegram_chat_id_here'
            }
        }
        
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        
        with open(self.config_file, 'w') as file:
            yaml.dump(default_config, file, default_flow_style=False, indent=2)
        
        print(f"Created default config file: {self.config_file}")
        print("Please update the configuration with your API credentials.")
    
    def save_config(self):
        """Save current configuration to file"""
        config_data = {
            'trading': {
                'capital_per_trade': self.trading.capital_per_trade,
                'max_trades_per_day': self.trading.max_trades_per_day,
                'stop_loss_percent': self.trading.stop_loss_percent,
                'target_percent': self.trading.target_percent,
                'trailing_sl_percent': self.trading.trailing_sl_percent,
                'paper_trading': self.trading.paper_trading
            },
            'kite': {
                'api_key': self.kite.api_key,
                'api_secret': self.kite.api_secret,
                'request_token': self.kite.request_token,
                'access_token': self.kite.access_token,
                'redirect_url': self.kite.redirect_url,
                'postback_url': self.kite.postback_url
            },
            'telegram': {
                'bot_token': self.telegram.bot_token,
                'chat_id': self.telegram.chat_id
            }
        }
        
        with open(self.config_file, 'w') as file:
            yaml.dump(config_data, file, default_flow_style=False, indent=2)
