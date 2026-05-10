"""Binance WebSocket client — real-time 24hr mini-ticker stream.

Connects to Binance's miniTicker stream and calls on_tick for each price update.
Reconnects automatically with exponential backoff on disconnect or error.

Usage:
    from trading_bot.websocket.client import BinanceWebSocketClient
    from trading_bot.websocket.price_cache import get_price_cache

    cache = get_price_cache()
    client = BinanceWebSocketClient(symbols=["BTCUSDT"], on_tick=cache.update)
    task = client.start()   # background asyncio.Task
    # on shutdown:
    client.stop()
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal

from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from trading_bot.core.models import PriceTick
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

_WS_BASE = "wss://stream.binance.com:9443/ws"
_WS_COMBINED = "wss://stream.binance.com:9443/stream?streams={streams}"
_INITIAL_BACKOFF = 1.0
_MAX_BACKOFF = 60.0


class BinanceWebSocketClient:
    """Streams 24hr miniTicker updates for the given symbols.

    Symbols are normalised: "BTC/USDT" → "btcusdt".
    on_tick is called for every valid price update.
    """

    def __init__(
        self,
        symbols: list[str],
        on_tick: Callable[[PriceTick], Awaitable[None]],
    ) -> None:
        self._streams = [s.lower().replace("/", "") for s in symbols]
        self._on_tick = on_tick
        self._running = False
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> asyncio.Task[None]:
        """Start streaming in a background task. Call once."""
        self._running = True
        self._task = asyncio.create_task(self._run(), name="binance_ws")
        return self._task

    def stop(self) -> None:
        """Signal the loop to exit and cancel the background task."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def _run(self) -> None:
        backoff = _INITIAL_BACKOFF
        if len(self._streams) == 1:
            url = f"{_WS_BASE}/{self._streams[0]}@miniTicker"
        else:
            streams = "/".join(f"{s}@miniTicker" for s in self._streams)
            url = _WS_COMBINED.format(streams=streams)

        while self._running:
            try:
                async with ws_connect(url, ping_interval=20, ping_timeout=10) as ws:
                    backoff = _INITIAL_BACKOFF
                    log.info("ws_connected", symbols=self._streams)
                    async for raw in ws:
                        if not self._running:
                            break
                        await self._handle(raw)
            except asyncio.CancelledError:
                break
            except (ConnectionClosed, WebSocketException) as e:
                log.warning("ws_disconnected", reason=str(e), backoff_s=backoff)
            except Exception as e:
                log.error("ws_error", error=str(e), backoff_s=backoff)

            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF)

        log.info("ws_stopped")

    async def _handle(self, raw: str | bytes) -> None:
        try:
            data = json.loads(raw)
            # Combined stream wraps payload: {"stream": "...", "data": {...}}
            if "data" in data:
                data = data["data"]
            if data.get("e") != "24hrMiniTicker":
                return
            tick = PriceTick(
                symbol=data["s"],
                price=Decimal(data["c"]),
                open_24h=Decimal(data["o"]),
                high_24h=Decimal(data["h"]),
                low_24h=Decimal(data["l"]),
                volume_24h=Decimal(data["v"]),
                timestamp=datetime.fromtimestamp(data["E"] / 1000, tz=UTC),
            )
            await self._on_tick(tick)
        except Exception as e:
            log.warning("ws_parse_error", error=str(e), raw=str(raw)[:120])
