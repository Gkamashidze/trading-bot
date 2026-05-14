"""Exchange adapter factory.

Returns the correct ExchangeInterface implementation based on ExchangeId.
Concrete adapters are only imported inside the factory function to avoid
loading CCXT / Alpaca SDKs unless they're actually needed.
"""

from __future__ import annotations

from trading_bot.config import get_settings
from trading_bot.core.contracts import ExchangeInterface
from trading_bot.core.models import ExchangeId


def get_exchange(exchange_id: ExchangeId | str) -> ExchangeInterface:
    """Factory: return the exchange adapter for the given exchange ID."""
    exchange_id = ExchangeId(exchange_id)
    settings = get_settings()

    if exchange_id == ExchangeId.BINANCE:
        from trading_bot.exchange.binance import BinanceExchange

        return BinanceExchange(
            api_key=settings.binance.api_key,
            api_secret=settings.binance.api_secret,
            testnet=settings.binance.testnet,
            timeout_ms=settings.binance.timeout_seconds * 1000,
            retry_attempts=settings.binance.retry_attempts,
            retry_backoff_base=settings.binance.retry_backoff_base,
        )

    if exchange_id == ExchangeId.ALPACA:
        from trading_bot.exchange.alpaca import AlpacaExchange

        return AlpacaExchange(
            api_key=settings.alpaca.api_key,
            secret_key=settings.alpaca.secret_key,
            paper=settings.alpaca.paper,
            allowed_symbols=frozenset(settings.alpaca.allowed_etf_symbols),
            timeout_seconds=settings.alpaca.timeout_seconds,
            retry_attempts=settings.alpaca.retry_attempts,
            allow_live_trading=settings.alpaca.allow_live_trading,
        )

    raise NotImplementedError(
        f"Exchange adapter for '{exchange_id}' is not yet implemented. "
        "See the roadmap: Coinbase → Stage 5b."
    )
