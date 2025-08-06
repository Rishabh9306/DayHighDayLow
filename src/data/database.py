"""
Database operations for trading bot using SQLite
"""

import sqlite3
import logging
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import json

@dataclass
class Trade:
    """Trade data structure"""
    id: Optional[int] = None
    timestamp: datetime = None
    symbol: str = ""
    option_type: str = ""  # CE or PE
    strike: int = 0
    entry_price: float = 0.0
    exit_price: float = 0.0
    quantity: int = 0
    pnl: float = 0.0
    status: str = "OPEN"  # OPEN, CLOSED, CANCELLED
    stop_loss: float = 0.0
    target: float = 0.0
    entry_reason: str = ""  # BREAKOUT_HIGH, BREAKOUT_LOW, GAP_UP, GAP_DOWN
    exit_reason: str = ""   # TARGET, STOP_LOSS, MANUAL
    order_id: str = ""

@dataclass
class DayData:
    """Daily market data structure"""
    date: date
    prev_high: float
    prev_low: float
    gap_up: bool = False
    gap_down: bool = False
    opening_price: float = 0.0

class Database:
    """Database operations for the trading bot"""
    
    def __init__(self, db_path: str = "data/trading_bot.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self.init_database()
    
    def init_database(self):
        """Initialize database and create tables"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Create trades table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    option_type TEXT NOT NULL,
                    strike INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL DEFAULT 0,
                    quantity INTEGER NOT NULL,
                    pnl REAL DEFAULT 0,
                    status TEXT DEFAULT 'OPEN',
                    stop_loss REAL NOT NULL,
                    target REAL NOT NULL,
                    entry_reason TEXT NOT NULL,
                    exit_reason TEXT DEFAULT '',
                    order_id TEXT DEFAULT '',
                    date TEXT NOT NULL
                )
            ''')
            
            # Create daily data table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS daily_data (
                    date TEXT PRIMARY KEY,
                    prev_high REAL NOT NULL,
                    prev_low REAL NOT NULL,
                    gap_up BOOLEAN DEFAULT 0,
                    gap_down BOOLEAN DEFAULT 0,
                    opening_price REAL DEFAULT 0
                )
            ''')
            
            # Create index on date for faster queries
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date)')
            
            conn.commit()
            conn.close()
            
            self.logger.info("Database initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Error initializing database: {e}")
            raise
    
    def save_daily_data(self, day_data: DayData):
        """Save daily market data"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO daily_data 
                (date, prev_high, prev_low, gap_up, gap_down, opening_price)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                day_data.date.isoformat(),
                day_data.prev_high,
                day_data.prev_low,
                day_data.gap_up,
                day_data.gap_down,
                day_data.opening_price
            ))
            
            conn.commit()
            conn.close()
            
            self.logger.info(f"Saved daily data for {day_data.date}")
            
        except Exception as e:
            self.logger.error(f"Error saving daily data: {e}")
            raise
    
    def get_daily_data(self, target_date: date = None) -> Optional[DayData]:
        """Get daily data for a specific date"""
        if not target_date:
            target_date = date.today()
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT date, prev_high, prev_low, gap_up, gap_down, opening_price
                FROM daily_data 
                WHERE date = ?
            ''', (target_date.isoformat(),))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return DayData(
                    date=datetime.fromisoformat(row[0]).date(),
                    prev_high=row[1],
                    prev_low=row[2],
                    gap_up=bool(row[3]),
                    gap_down=bool(row[4]),
                    opening_price=row[5]
                )
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting daily data: {e}")
            return None
    
    def save_trade(self, trade: Trade) -> int:
        """Save a new trade and return trade ID"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO trades 
                (timestamp, symbol, option_type, strike, entry_price, exit_price,
                 quantity, pnl, status, stop_loss, target, entry_reason, 
                 exit_reason, order_id, date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                trade.timestamp.isoformat(),
                trade.symbol,
                trade.option_type,
                trade.strike,
                trade.entry_price,
                trade.exit_price,
                trade.quantity,
                trade.pnl,
                trade.status,
                trade.stop_loss,
                trade.target,
                trade.entry_reason,
                trade.exit_reason,
                trade.order_id,
                date.today().isoformat()
            ))
            
            trade_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            self.logger.info(f"Saved trade: {trade_id}")
            return trade_id
            
        except Exception as e:
            self.logger.error(f"Error saving trade: {e}")
            raise
    
    def update_trade(self, trade_id: int, **kwargs):
        """Update an existing trade"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Build UPDATE query dynamically
            set_clauses = []
            values = []
            
            for key, value in kwargs.items():
                if key in ['exit_price', 'pnl', 'status', 'exit_reason']:
                    set_clauses.append(f"{key} = ?")
                    values.append(value)
            
            if set_clauses:
                query = f"UPDATE trades SET {', '.join(set_clauses)} WHERE id = ?"
                values.append(trade_id)
                
                cursor.execute(query, values)
                conn.commit()
            
            conn.close()
            self.logger.info(f"Updated trade: {trade_id}")
            
        except Exception as e:
            self.logger.error(f"Error updating trade: {e}")
            raise
    
    def get_today_trades(self) -> List[Trade]:
        """Get all trades for today"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            today = date.today().isoformat()
            cursor.execute('''
                SELECT id, timestamp, symbol, option_type, strike, entry_price,
                       exit_price, quantity, pnl, status, stop_loss, target,
                       entry_reason, exit_reason, order_id
                FROM trades 
                WHERE date = ?
                ORDER BY timestamp
            ''', (today,))
            
            trades = []
            for row in cursor.fetchall():
                trade = Trade(
                    id=row[0],
                    timestamp=datetime.fromisoformat(row[1]),
                    symbol=row[2],
                    option_type=row[3],
                    strike=row[4],
                    entry_price=row[5],
                    exit_price=row[6],
                    quantity=row[7],
                    pnl=row[8],
                    status=row[9],
                    stop_loss=row[10],
                    target=row[11],
                    entry_reason=row[12],
                    exit_reason=row[13],
                    order_id=row[14]
                )
                trades.append(trade)
            
            conn.close()
            return trades
            
        except Exception as e:
            self.logger.error(f"Error getting today's trades: {e}")
            return []
    
    def get_open_trades(self) -> List[Trade]:
        """Get all open trades"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, timestamp, symbol, option_type, strike, entry_price,
                       exit_price, quantity, pnl, status, stop_loss, target,
                       entry_reason, exit_reason, order_id
                FROM trades 
                WHERE status = 'OPEN'
                ORDER BY timestamp
            ''')
            
            trades = []
            for row in cursor.fetchall():
                trade = Trade(
                    id=row[0],
                    timestamp=datetime.fromisoformat(row[1]),
                    symbol=row[2],
                    option_type=row[3],
                    strike=row[4],
                    entry_price=row[5],
                    exit_price=row[6],
                    quantity=row[7],
                    pnl=row[8],
                    status=row[9],
                    stop_loss=row[10],
                    target=row[11],
                    entry_reason=row[12],
                    exit_reason=row[13],
                    order_id=row[14]
                )
                trades.append(trade)
            
            conn.close()
            return trades
            
        except Exception as e:
            self.logger.error(f"Error getting open trades: {e}")
            return []
    
    def get_trade_count_today(self) -> int:
        """Get number of completed trades today (hit SL or target)"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            today = date.today().isoformat()
            cursor.execute('''
                SELECT COUNT(*) FROM trades 
                WHERE date = ? AND status = 'CLOSED'
            ''', (today,))
            
            count = cursor.fetchone()[0]
            conn.close()
            
            return count
            
        except Exception as e:
            self.logger.error(f"Error getting trade count: {e}")
            return 0
    
    def cleanup_old_data(self, days_to_keep: int = 2):
        """Remove data older than specified days"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Calculate cutoff date
            cutoff_date = (date.today() - datetime.timedelta(days=days_to_keep)).isoformat()
            
            # Delete old trades
            cursor.execute('DELETE FROM trades WHERE date < ?', (cutoff_date,))
            trades_deleted = cursor.rowcount
            
            # Delete old daily data
            cursor.execute('DELETE FROM daily_data WHERE date < ?', (cutoff_date,))
            daily_deleted = cursor.rowcount
            
            conn.commit()
            conn.close()
            
            self.logger.info(f"Cleaned up {trades_deleted} trades and {daily_deleted} daily records")
            
        except Exception as e:
            self.logger.error(f"Error cleaning up old data: {e}")
    
    def get_daily_pnl(self, target_date: date = None) -> float:
        """Get total P&L for a specific date"""
        if not target_date:
            target_date = date.today()
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT SUM(pnl) FROM trades 
                WHERE date = ? AND status = 'CLOSED'
            ''', (target_date.isoformat(),))
            
            result = cursor.fetchone()[0]
            conn.close()
            
            return result if result else 0.0
            
        except Exception as e:
            self.logger.error(f"Error getting daily P&L: {e}")
            return 0.0
