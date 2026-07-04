"""Render a WalkForwardResult into an honest Markdown + HTML report.

No plotting dependencies: the equity curve is an inline SVG so the HTML report
is fully self-contained. The Markdown summary states plainly whether the
out-of-sample result beat buy-and-hold — losses are reported, not hidden.
"""
# ruff: noqa: E501 — this module emits HTML/SVG markup; long template lines are intentional

from __future__ import annotations

from pathlib import Path

import pandas as pd

from trading_bot.backtesting.result import BacktestMetrics
from trading_bot.backtesting.walk_forward import WalkForwardResult


def _verdict(result: WalkForwardResult) -> str:
    oos = result.oos_metrics
    bench = result.benchmark_metrics
    delta = oos.net_total_return_pct - bench.total_return_pct
    if result.beats_benchmark and oos.sharpe_ratio > bench.sharpe_ratio:
        return (
            f"✅ Beat buy-and-hold out-of-sample by {delta:+.1f} pts of return "
            f"AND on Sharpe ({oos.sharpe_ratio:.2f} vs {bench.sharpe_ratio:.2f})."
        )
    if result.beats_benchmark:
        return (
            f"⚠️ Higher OOS return than buy-and-hold ({delta:+.1f} pts) but NOT on a "
            f"risk-adjusted basis (Sharpe {oos.sharpe_ratio:.2f} vs {bench.sharpe_ratio:.2f}). "
            "Not a clear edge."
        )
    return (
        f"❌ No demonstrated edge. Out-of-sample the strategy returned "
        f"{oos.net_total_return_pct:+.1f}% vs buy-and-hold {bench.total_return_pct:+.1f}% "
        f"({delta:+.1f} pts). It did not beat simply holding the asset after costs."
    )


def _metrics_table(oos: BacktestMetrics, bench: BacktestMetrics) -> str:
    rows = [
        ("Net return %", f"{oos.net_total_return_pct:+.2f}", f"{bench.total_return_pct:+.2f}"),
        ("CAGR %", f"{oos.cagr_pct:+.2f}", f"{bench.cagr_pct:+.2f}"),
        ("Sharpe", f"{oos.sharpe_ratio:.2f}", f"{bench.sharpe_ratio:.2f}"),
        ("Sortino", f"{oos.sortino_ratio:.2f}", f"{bench.sortino_ratio:.2f}"),
        ("Max drawdown %", f"{oos.max_drawdown_pct:.2f}", f"{bench.max_drawdown_pct:.2f}"),
        ("Calmar", f"{oos.calmar_ratio:.2f}", f"{bench.calmar_ratio:.2f}"),
        ("Win rate %", f"{oos.win_rate:.1f}", f"{bench.win_rate:.1f}"),
        ("Profit factor", f"{oos.profit_factor:.2f}", "—"),
        ("Trades", str(oos.total_trades), str(bench.total_trades)),
        ("Exposure %", f"{oos.exposure_time_pct:.1f}", "100.0"),
        ("Fees paid ($)", f"{oos.total_fees_paid:.2f}", "—"),
    ]
    out = ["| Metric | Strategy (OOS) | Buy & Hold |", "|---|---|---|"]
    out += [f"| {name} | {a} | {b} |" for name, a, b in rows]
    return "\n".join(out)


def _windows_table(result: WalkForwardResult, limit: int = 60) -> str:
    out = ["| # | Test window | Chosen params | Train Sharpe |", "|---|---|---|---|"]
    for w in result.windows[:limit]:
        params = ", ".join(f"{k}={v}" for k, v in w.best_params.items())
        out.append(
            f"| {w.index} | {w.test_start} → {w.test_end} | {params} | {w.train_sharpe:.2f} |"
        )
    if len(result.windows) > limit:
        out.append(f"| … | ({len(result.windows) - limit} more windows) | | |")
    return "\n".join(out)


def render_markdown(result: WalkForwardResult, *, generated_at: str) -> str:
    return f"""# Walk-Forward Backtest — {result.strategy_id} on {result.symbol}

_Generated: {generated_at} · Out-of-sample span: {result.oos_start} → {result.oos_end} · \
{len(result.windows)} walk-forward windows_

## Verdict

{_verdict(result)}

> **Methodology.** Parameters are grid-searched on each rolling *train* window and
> applied only to the following *test* window it never saw. Every test segment's
> signals are concatenated and executed once through the realistic fill model
> (taker fees + spread/slippage), so this is a true out-of-sample result with no
> look-ahead and no in-sample curve-fitting. The benchmark is buy-and-hold over
> the identical out-of-sample span (one entry fee).

## Out-of-sample vs buy-and-hold

{_metrics_table(result.oos_metrics, result.benchmark_metrics)}

## Per-window parameter selection

{_windows_table(result)}

---
_Reproduce: `python scripts/run_walk_forward.py`. Results are not curve-fit; if the
strategy loses to buy-and-hold, this report says so._
"""


def _svg_equity_curve(result: WalkForwardResult, width: int = 900, height: int = 340) -> str:
    """Inline SVG of normalised OOS strategy equity vs buy-and-hold (both start at 100)."""

    def _norm(s: pd.Series, target: int = 500) -> list[float]:
        if s.empty:
            return []
        step = max(1, len(s) // target)
        sampled = s.iloc[::step]
        base = float(s.iloc[0]) or 1.0
        return [float(v) / base * 100.0 for v in sampled]

    strat = _norm(result.oos_equity_curve)
    bench = _norm(result.benchmark_equity_curve)
    if not strat or not bench:
        return "<p>No equity data.</p>"

    lo = min(min(strat), min(bench))
    hi = max(max(strat), max(bench))
    span = (hi - lo) or 1.0
    pad = 40

    def _points(series: list[float]) -> str:
        n = len(series)
        pts = []
        for i, v in enumerate(series):
            x = pad + (width - 2 * pad) * (i / max(1, n - 1))
            y = height - pad - (height - 2 * pad) * ((v - lo) / span)
            pts.append(f"{x:.1f},{y:.1f}")
        return " ".join(pts)

    base_y = height - pad - (height - 2 * pad) * ((100.0 - lo) / span)
    return f"""<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" style="max-width:100%;height:auto">
  <rect width="{width}" height="{height}" fill="#0d1117"/>
  <line x1="{pad}" y1="{base_y:.1f}" x2="{width - pad}" y2="{base_y:.1f}" stroke="#30363d" stroke-dasharray="4"/>
  <text x="{pad}" y="{base_y - 6:.1f}" fill="#8b949e" font-size="11" font-family="monospace">start = 100</text>
  <polyline fill="none" stroke="#f0883e" stroke-width="2" points="{_points(bench)}"/>
  <polyline fill="none" stroke="#3fb950" stroke-width="2" points="{_points(strat)}"/>
  <text x="{width - pad - 150}" y="24" fill="#3fb950" font-size="13" font-family="monospace">— strategy (OOS)</text>
  <text x="{width - pad - 150}" y="42" fill="#f0883e" font-size="13" font-family="monospace">— buy &amp; hold</text>
</svg>"""


def render_html(result: WalkForwardResult, *, generated_at: str) -> str:
    oos, bench = result.oos_metrics, result.benchmark_metrics
    table = _metrics_table(oos, bench).replace("| Metric", "MetricHDR").splitlines()
    body_rows = "".join(
        "<tr>" + "".join(f"<td>{c.strip()}</td>" for c in line.strip("|").split("|")) + "</tr>"
        for line in table[2:]
    )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Walk-forward — {result.strategy_id}</title>
<style>
 body{{background:#0d1117;color:#c9d1d9;font-family:system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem}}
 h1{{font-size:1.4rem}} table{{border-collapse:collapse;width:100%;margin:1rem 0}}
 td,th{{border:1px solid #30363d;padding:6px 10px;text-align:left;font-family:monospace}}
 .verdict{{padding:12px;border-left:4px solid #3fb950;background:#161b22;margin:1rem 0}}
</style></head><body>
<h1>Walk-Forward Backtest — {result.strategy_id} on {result.symbol}</h1>
<p>OOS span {result.oos_start} → {result.oos_end} · {len(result.windows)} windows · generated {generated_at}</p>
<div class="verdict">{_verdict(result)}</div>
{_svg_equity_curve(result)}
<table><tr><th>Metric</th><th>Strategy (OOS)</th><th>Buy &amp; Hold</th></tr>{body_rows}</table>
<p style="color:#8b949e">Parameters are tuned only on preceding train windows; benchmark is buy-and-hold over the identical OOS span. Realistic fees + slippage. Not curve-fit.</p>
</body></html>"""


def write_reports(result: WalkForwardResult, outdir: Path, *, generated_at: str) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    md = outdir / f"{result.strategy_id}_walk_forward.md"
    html = outdir / f"{result.strategy_id}_walk_forward.html"
    md.write_text(render_markdown(result, generated_at=generated_at))
    html.write_text(render_html(result, generated_at=generated_at))
    return [md, html]
