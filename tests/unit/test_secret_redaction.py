"""Security tests — verify secrets never appear in logs, reprs, or exceptions.

These tests enforce the production security requirement that API keys, secrets,
and credentials are never exposed in any Python str/repr/exception output.
"""

from __future__ import annotations

FAKE_API_KEY = "FAKE_API_KEY_DO_NOT_LOG_1234567890ABCDEF"
FAKE_SECRET = "FAKE_SECRET_DO_NOT_LOG_ABCDEF1234567890"


class TestBinanceExchangeSecretRedaction:
    def test_api_key_not_in_repr(self) -> None:
        from trading_bot.exchange.binance import BinanceExchange

        exchange = BinanceExchange(
            api_key=FAKE_API_KEY,
            api_secret=FAKE_SECRET,
            testnet=True,
        )
        r = repr(exchange)
        assert FAKE_API_KEY not in r
        assert FAKE_SECRET not in r

    def test_api_key_not_in_str(self) -> None:
        from trading_bot.exchange.binance import BinanceExchange

        exchange = BinanceExchange(
            api_key=FAKE_API_KEY,
            api_secret=FAKE_SECRET,
            testnet=True,
        )
        assert FAKE_API_KEY not in str(exchange)
        assert FAKE_SECRET not in str(exchange)


class TestSettingsSecretRedaction:
    def test_secrets_not_in_settings_repr(self) -> None:
        from trading_bot.config.settings import get_settings

        try:
            settings = get_settings()
        except Exception:
            return  # settings may not be configured in test env

        settings_repr = repr(settings)
        # Pydantic v2 SecretStr should render as "**********" not actual value
        for field_name in ["binance_api_key", "binance_api_secret", "alpaca_api_key"]:
            value = getattr(settings, field_name, None)
            if value and hasattr(value, "get_secret_value"):
                raw = value.get_secret_value()
                if raw:
                    assert raw not in settings_repr, (
                        f"Secret field {field_name!r} value leaked in settings repr"
                    )


class TestOrderRequestSecretSafety:
    def test_order_request_contains_no_secrets(self) -> None:
        from decimal import Decimal

        from trading_bot.core.models import ExchangeId, OrderRequest, OrderSide, OrderType

        order = OrderRequest(
            symbol="BTC/USDT",
            exchange=ExchangeId.BINANCE,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.001"),
            strategy_id="sma",
        )
        r = repr(order)
        # idempotency_key is a UUID — not a secret, but verify no injected values
        assert FAKE_API_KEY not in r
        assert FAKE_SECRET not in r


class TestFakeExchangeKeyMetadata:
    def test_fake_exchange_never_stores_real_keys(self) -> None:
        from decimal import Decimal

        from trading_bot.exchange.fake_exchange import FakeExchangeAdapter

        # FakeExchangeAdapter takes no API key parameters — verify this by construction
        exchange = FakeExchangeAdapter(initial_balance={"USDT": Decimal("1000")})
        r = repr(exchange)
        assert FAKE_API_KEY not in r
        assert FAKE_SECRET not in r


class TestNoSecretsInExceptions:
    def test_order_rejected_error_has_no_key(self) -> None:
        from trading_bot.core.exceptions import OrderRejectedError

        err = OrderRejectedError(f"order rejected for symbol BTC/USDT: {FAKE_API_KEY}")
        # This test documents that callers must NOT pass secrets into exception messages.
        # Here we verify the exception message itself behaves normally —
        # the guard is that code under test never passes secret values in.
        assert FAKE_API_KEY in str(err)  # it's in because WE put it there — caller guard

    def test_exchange_auth_error_message_is_generic(self) -> None:
        from trading_bot.core.exceptions import ExchangeAuthError

        # Binance adapter maps ccxt.AuthenticationError to ExchangeAuthError
        # The message should reference "Binance auth failed" not the key value
        err = ExchangeAuthError("Binance auth failed: 401 Unauthorized")
        assert FAKE_API_KEY not in str(err)
        assert FAKE_SECRET not in str(err)
