# Copilot Instructions for NIFTY Options Trading Bot

<!-- Use this file to provide workspace-specific custom instructions to Copilot. For more details, visit https://code.visualstudio.com/docs/copilot/copilot-customization#_use-a-githubcopilotinstructionsmd-file -->

## Project Overview
This is a Python-based automated trading bot for NIFTY 50 options using the Zerodha Kite API. The bot implements a day high/low breakout strategy with specific risk management rules.

## Key Technologies
- **Python 3.8+**: Main programming language
- **kiteconnect**: Zerodha Kite API for trading operations
- **SQLite**: Database for trade and market data storage
- **python-telegram-bot**: For trade notifications
- **asyncio**: For asynchronous operations and real-time data handling
- **PyYAML**: Configuration management
- **pandas/numpy**: Data manipulation

## Project Structure Guidelines
- `src/core/`: Main business logic (bot, strategy)
- `src/data/`: Data access layer (API clients, database)
- `src/notifications/`: Communication modules
- `src/utils/`: Utility functions and configuration
- `config/`: Configuration files
- `logs/`: Application logs
- `data/`: SQLite database files

## Trading Strategy Rules
1. **Entry**: Buy CE on breakout above prev day high, PE on breakout below prev day low
2. **Gap trades**: Immediate entry at market open if gap up/down
3. **Exits**: 20% SL, 60% target, 20% trailing SL
4. **Limits**: Max 4 trades/day, ₹15k per trade
5. **Reentry**: Allowed if price returns to exit level
6. **Time**: Only during market hours (9:15 AM - 3:30 PM)

## Code Style Preferences
- Use async/await for I/O operations
- Comprehensive error handling with logging
- Type hints for function parameters and returns
- Dataclasses for data structures
- Clear variable names related to trading terminology
- Separate concerns: strategy logic, API calls, database operations

## Important Constants
- Capital per trade: ₹15,000
- Maximum trades per day: 4
- Stop loss: 20%
- Target: 60%
- Trailing SL: 20%
- Trading hours: 9:15 AM - 3:30 PM IST

## Error Handling
- All API calls should have try-catch blocks
- Log errors with appropriate severity levels
- Send critical errors to Telegram if configured
- Graceful degradation when services are unavailable

## Security Considerations
- API credentials stored in config files (not in code)
- Sensitive data not logged
- Proper authentication handling for Kite API
- Safe database operations

## Testing Approach
- Test with paper trading before live deployment
- Mock external API calls for unit tests
- Validate all trading calculations
- Test error scenarios and recovery

When suggesting code changes:
1. Follow the existing project structure
2. Maintain consistency with trading terminology
3. Include proper error handling and logging
4. Consider async operations for I/O
5. Add appropriate type hints
6. Ensure thread safety for shared data structures
