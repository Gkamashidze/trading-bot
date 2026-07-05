# Trend Pullback — Walk-Forward Out-of-Sample Report

**Date:** 2026-07-05
**Strategy:** Trend Pullback (STRATEGY_ROADMAP.md §3.2, BTC/USDT variant)
**Harness:** `scripts/research_trend_pullback.py` (event-driven bracket engine —
`trading_bot/backtesting/event_engine.py`)
**Data:** BTC/USDT 1h, 2022-01-01 → 2026-06-30 (39,407 bars)

> ⚠️ **Not directly comparable to the SMA/RSI/Donchian/MACD reports.** Those use
> the vectorized signal engine (`scripts/run_walk_forward.py`). This one uses the
> new bracket engine (intrabar ATR stops/targets, risk-based sizing) and a
> different OOS window, so its buy-and-hold baseline reads **+219.6% / Sharpe
> 1.24** rather than +192.6% / 0.80. Compare each strategy to the buy-and-hold
> figure **in its own report**, not across reports.

## Design tested

- **Trend filter (daily, lagged 1 day — no look-ahead):** price > SMA200 AND
  SMA50 > SMA200. No entries unless the regime is `TREND_UP`.
- **Entry (1h):** RSI(14) dipped below oversold within the last 5 bars, then
  crossed back above the recovery level; price above the daily SMA50; volume
  not abnormally low.
- **Bracket:** stop = entry − sl×ATR(14); target = entry + tp×ATR(14); trailing
  stop after +1R; 48h max hold; exit on regime break. Pessimistic intrabar
  fills (stop assumed first when a bar spans both).
- **Sizing:** 1% equity risk / stop distance, no leverage.
- **Costs:** 0.1% taker fee + 0.05% adverse slippage per side.

**Walk-forward:** parameters (`oversold_level`, `sl_atr_mult`, `tp_atr_mult`)
optimised on each 12-month train window by in-sample Sharpe (≥8 trades), applied
unseen to the next 6-month test window. OOS test segments stitched, capital
carried forward. Return-based metrics computed on daily-resampled equity.

## Out-of-sample result (stitched, 2023-07-20 → 2026-01-17)

| Metric | Trend Pullback | Buy & Hold |
|---|---|---|
| Total return % | **−11.79** | +219.63 |
| CAGR % | −4.89 | +59.13 |
| Sharpe | **−0.97** | +1.24 |
| Sortino | −0.43 | +1.91 |
| Calmar | −0.32 | +1.85 |
| Max drawdown % | −15.13 | −32.02 |
| Win rate % | 42.6 | — |
| Trades | 47 | 1 |

**Exit-reason distribution:** stop_loss 57% · trailing_stop 28% · take_profit
11% · max_holding 4%.

## Verdict: NO EDGE

The strategy **loses money out-of-sample** (−11.8%) and has a **negative Sharpe
(−0.97)**. Its only "win" — a smaller max drawdown (−15% vs −32%) — is trivial:
it is out of the market almost all the time (only 47 trades in 2.5 years), so it
avoids drawdown by avoiding participation, while still bleeding via fees and
stop-outs.

### Why the 2:1 reward:risk didn't produce positive expectancy

A 42.6% win rate at a true 2:1 payoff *should* be profitable
(0.426×2 − 0.574×1 = +0.28R). It isn't, because the realised payoff is **not**
2:1: **28% of exits are trailing stops** that cut winners well below the 3×ATR
target, and only **11% reach the full take-profit**. The trailing stop is
destroying the edge the bracket was designed to capture. Combined with 57%
full stop-outs plus per-trade costs, expectancy goes negative.

### Research follow-ups

1. **Remove the trailing stop — TESTED, did NOT help.** Letting winners run to
   the full target gave **−15.8% OOS / Sharpe −0.71** (worse on return; win rate
   fell to 28.6% as more trades hit the full stop, 70% stop-outs). This
   **refutes** the "trailing stop is killing the edge" hypothesis: the problem is
   the **entry**, not the exit. The RSI-recovery pullback simply does not produce
   enough winners in this data, regardless of exit management.
2. **4h multi-timeframe confirmation** (§4) — **TESTED, helps but no edge.**
   Requiring the last-closed 4h bar above its EMA(50) before entry (run with
   `--h4`) improved every risk metric — **−5.9% return, Sharpe −0.66, max DD
   −8.2%**, 29 trades (vs −11.8% / −0.97 / −15.1%, 47 trades base). The filter
   removes bad trades (roughly halving both the loss and the drawdown) but the
   survivors still don't have positive expectancy — it converges toward
   break-even by trading *less*, not by finding winners. Still negative.
3. **Regime-segmented evaluation** (§2.3) — the aggregate hides regime-specific
   behaviour; measure per-regime expectancy. *Not yet run.*

Every variant tested — base, no-trailing, and 4h-confirmed — loses out-of-sample.
Each added filter (structure, timeframe) improves the risk profile but converges
to break-even-minus-costs, never to positive expectancy. The RSI-recovery
pullback entry has **no demonstrated edge on BTC 2023–2026**. Until a variant
clears buy-and-hold on a **risk-adjusted** basis out-of-sample, Trend Pullback
stays research-only. `trend_pullback_enabled = false`.

Reproduce: `uv run python scripts/research_trend_pullback.py [--h4]`
