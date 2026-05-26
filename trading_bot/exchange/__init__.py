"""Exchange adapters — concrete implementations of ExchangeInterface.

Each exchange lives in its own module. The factory function
get_exchange() returns the correct adapter based on ExchangeId.

Only read-only operations (fetch_ohlcv, get_server_time, health_check)
are implemented in Stage 0. Trade operations are added in Stage 5.
"""

from trading_bot.exchange.alpaca import AlpacaExchange
from trading_bot.exchange.factory import get_exchange

__all__ = ["AlpacaExchange", "get_exchange"]
