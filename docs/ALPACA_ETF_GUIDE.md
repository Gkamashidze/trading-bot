# Alpaca ETF Trading Guide

Complete reference for the Alpaca ETF integration: configuration, testing, and CLI usage.

---

## Supported Symbols

| Symbol | Description         | Strategy params              |
|--------|---------------------|------------------------------|
| SPY    | S&P 500 ETF         | SMA(20,50) · RSI(14, 32/68) |
| QQQ    | Nasdaq 100 ETF      | SMA(15,40) · RSI(14, 30/70) |
| SOXX   | Semiconductor ETF   | SMA(10,30) · RSI(14, 28/72) |
| IBIT   | iShares Bitcoin ETF | SMA(10,25) · RSI(14, 25/75) |

All orders go through Alpaca (commission-free US equities). Binance is not used for ETFs.

---

## Configuration

### 1. Environment variables (`.env`)

```bash
ALPACA_API_KEY=your_paper_key
ALPACA_SECRET_KEY=your_paper_secret
# Leave ALLOW_LIVE_TRADING unset (or =false) for paper trading
```

### 2. `config/base.yaml` (defaults, do not put secrets here)

```yaml
exchange:
  alpaca:
    paper: true               # always paper unless explicitly overridden
    allow_live_trading: false # requires ALLOW_LIVE_TRADING=true env var for live
    allowed_etf_symbols: [SPY, QQQ, SOXX, IBIT]
    timeout_seconds: 30
    retry_attempts: 4

    etf_strategy_params:
      SPY:  { sma_fast: 20, sma_slow: 50, rsi_period: 14, rsi_oversold: 32, rsi_overbought: 68 }
      QQQ:  { sma_fast: 15, sma_slow: 40, rsi_period: 14, rsi_oversold: 30, rsi_overbought: 70 }
      SOXX: { sma_fast: 10, sma_slow: 30, rsi_period: 14, rsi_oversold: 28, rsi_overbought: 72 }
      IBIT: { sma_fast: 10, sma_slow: 25, rsi_period: 14, rsi_oversold: 25, rsi_overbought: 75 }
```

### 3. Live trading guard

`AlpacaExchange` raises `KillSwitchError` at construction time if `paper=False` without
`allow_live_trading=True`. This is a hard guard — it cannot be bypassed at runtime.

To enable live (Stage 5+):
```bash
ALLOW_LIVE_TRADING=true  # in .env or Railway env
```

---

## CLI Usage

Install the CLI entry point (done automatically by `uv sync`):

```bash
uv sync
trading-bot-etf --help
```

### `test-synthetic` — no API calls needed

Runs deterministic sine-wave backtests to verify ≥ 5 buy/sell signal cycles per symbol:

```bash
# All 4 symbols, both strategies (default)
trading-bot-etf test-synthetic

# Specific symbols and strategy
trading-bot-etf test-synthetic --symbols SPY,QQQ --strategy sma

# Stricter cycle requirement
trading-bot-etf test-synthetic --min-cycles 8
```

Exit code 0 = all pass · Exit code 1 = at least one symbol failed.

### `backtest` — real historical data via yfinance

Downloads daily OHLCV bars and runs the BacktestEngine:

```bash
# Default: all 4 symbols, 2024 full year
trading-bot-etf backtest

# Custom date range and capital
trading-bot-etf backtest --symbols SPY --start 2023-01-01 --end 2024-01-01 --capital 50000

# RSI only
trading-bot-etf backtest --strategy rsi
```

Requires `yfinance` (already in dev dependencies). Output shows per-symbol metrics:
trades, win rate, total return %, max drawdown %, Sharpe ratio.

### `paper-execution-test` — real Alpaca paper API

Submits a live order to the Alpaca **paper** account and immediately cancels it.
Requires API keys and should never run in CI.

```bash
export ALPACA_API_KEY=your_key
export ALPACA_SECRET_KEY=your_secret

trading-bot-etf paper-execution-test --symbols SPY --qty 1
```

If the market is closed, the test prints `SKIP: market is closed` and exits cleanly.

---

## Running Tests

### Synthetic unit tests (no API, always safe)

```bash
uv run pytest tests/unit/test_synthetic_etf.py -v
uv run pytest tests/unit/test_alpaca_adapter.py -v
```

### Full unit + property suite

```bash
uv run pytest tests/unit tests/property tests/replay -v
```

### Paper execution integration tests (real Alpaca paper API)

These are **skipped by default**. Enable only with real paper API keys:

```bash
export ALPACA_API_KEY=...
export ALPACA_SECRET_KEY=...
uv run pytest tests/integration/test_alpaca_paper_execution.py --paper-execution-test -v
```

**Never pass `--paper-execution-test` in CI.** The flag is intentionally absent from all
CI configurations.

---

## Architecture

```
trading_bot/
├── exchange/
│   └── alpaca.py           # AlpacaExchange (ExchangeInterface implementation)
├── utils/
│   └── market_calendar.py  # NYSE market-hours (pandas-market-calendars)
├── config/
│   ├── settings.py         # AlpacaExchangeSettings, EtfStrategyParams
│   └── base.yaml           # exchange.alpaca defaults + per-symbol params
└── cli/
    ├── __init__.py         # main() argparse entry point
    └── etf_commands.py     # run_test_synthetic, run_backtest, run_paper_execution
```

### Key design decisions

| Decision | Rationale |
|----------|-----------|
| `asyncio.run_in_executor` for alpaca-py | alpaca-py SDK is synchronous; wrapping keeps the event loop unblocked |
| `paper=True` default | Prevents accidental live orders during development |
| `KillSwitchError` at construction | Fails loudly before any network call if live guard is missing |
| `TimeInForce.DAY` enforced | Prevents stale GTC orders from executing days later |
| `fee_paid: "0"` always | Alpaca has no commission on US equities; recorded for audit log parity |
| Per-symbol params in YAML + Python dict | YAML drives the settings model; the CLI dict must stay in sync |

---

## Logging

All order events are logged via `structlog` with these fields:

| Event | Key fields |
|-------|-----------|
| Signal generated | `symbol`, `strategy_id`, `signal` |
| Order submitted | `symbol`, `side`, `qty`, `order_type`, `broker: alpaca` |
| Order filled | `symbol`, `side`, `qty`, `fill_price`, `fee: 0` |
| Order rejected | `symbol`, `error`, `reason` |
| Market closed | `symbol`, `broker: alpaca`, `reason: market_closed` |
| Symbol not allowed | `symbol`, `allowed_symbols` |

API keys are never logged. The `api_key` and `secret_key` fields are redacted before
reaching any logger.
