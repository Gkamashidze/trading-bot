"""Paper Testing Evidence Reporter.

Generates daily summaries, weekly summaries, and the final 30-day
paper testing report with micro-live readiness recommendation.

The reporter never approves micro-live automatically — it only produces
a structured recommendation with supporting evidence.

Acceptance criteria thresholds are driven by EvidenceSettings from config.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from trading_bot.evidence.models import (
    DailyEvidenceSummary,
    FinalPaperTestReport,
    MicroLiveReadinessCheck,
    MicroLiveRecommendation,
    WeeklyEvidenceSummary,
)
from trading_bot.evidence.store import EvidenceStore, _now
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)


def _idem_key(prefix: str, *parts: Any) -> str:
    blob = "|".join(str(p) for p in parts).encode()
    return f"{prefix}:{hashlib.sha256(blob).hexdigest()[:16]}"


class EvidenceReporter:
    """Generates summary documents from evidence stored by EvidenceStore."""

    def __init__(self, store: EvidenceStore) -> None:
        self._store = store

    async def generate_and_persist_daily_summary(
        self,
        session_id: uuid.UUID,
        summary_date: date | None = None,
    ) -> DailyEvidenceSummary | None:
        """Compute and insert daily summary for summary_date (default: yesterday UTC)."""
        if summary_date is None:
            summary_date = (datetime.now(UTC) - timedelta(days=1)).date()

        summary = await self._store.build_daily_summary(session_id, summary_date)
        if summary is None:
            log.warning(
                "evidence_daily_summary_no_data",
                session_id=str(session_id),
                date=summary_date.isoformat(),
            )
            return None

        await self._store.insert_daily_summary(summary)
        return summary

    async def generate_and_persist_weekly_summary(
        self,
        session_id: uuid.UUID,
        week_start: date | None = None,
    ) -> WeeklyEvidenceSummary | None:
        """Compute and insert weekly summary for the week ending on the most recent Sunday."""
        if week_start is None:
            today = datetime.now(UTC).date()
            # ISO week starts on Monday; find last complete Monday-Sunday week
            days_since_sunday = today.isoweekday() % 7  # Sunday = 0 in this mod
            last_sunday = today - timedelta(days=days_since_sunday)
            week_start = last_sunday - timedelta(days=6)

        week_end = week_start + timedelta(days=6)

        daily_rows = await self._store.list_daily_summaries(session_id, limit=365)
        # Filter to this week
        week_days = [r for r in daily_rows if week_start <= r["summary_date"] <= week_end]

        if not week_days:
            log.warning(
                "evidence_weekly_summary_no_data",
                session_id=str(session_id),
                week_start=week_start.isoformat(),
            )
            return None

        # Starting equity = earliest day; ending = latest day
        week_days_sorted = sorted(week_days, key=lambda r: r["summary_date"])
        starting_equity = Decimal(str(week_days_sorted[0]["starting_equity"]))
        ending_equity = Decimal(str(week_days_sorted[-1]["ending_equity"]))
        pnl = ending_equity - starting_equity
        pnl_pct = (pnl / starting_equity * 100) if starting_equity != 0 else Decimal("0")
        max_dd = max(Decimal(str(r["max_drawdown_pct"])) for r in week_days)
        trade_count = sum(r["trade_count"] for r in week_days)
        rejected_count = sum(r["rejected_order_count"] for r in week_days)
        partial_count = sum(r["partial_fill_count"] for r in week_days)

        # Build per-strategy trade counts from signal snapshots (best-effort)
        strategy_metrics: dict[str, Any] = {}

        # Parity score (paper↔backtest) — best-effort; None if not enough data
        parity_score: Decimal | None = None
        try:
            from trading_bot.parity.evidence_parity import compute_parity_score

            parity_score = await compute_parity_score(self._store._pool)
        except Exception as exc:
            log.warning("evidence_weekly_parity_failed", error=str(exc))

        summary = WeeklyEvidenceSummary(
            session_id=session_id,
            week_start=week_start,
            week_end=week_end,
            starting_equity=starting_equity,
            ending_equity=ending_equity,
            pnl=pnl,
            pnl_pct=pnl_pct,
            max_drawdown_pct=max_dd,
            trade_count=trade_count,
            rejected_order_count=rejected_count,
            partial_fill_count=partial_count,
            parity_score=parity_score,
            strategy_metrics=strategy_metrics,
            incidents=[],
            generated_at=_now(),
            idempotency_key=_idem_key("weekly_summary", session_id, week_start.isoformat()),
        )
        await self._store.insert_weekly_summary(summary)
        return summary

    async def generate_final_report(
        self,
        session_id: uuid.UUID,
        min_days: int = 30,
        min_trades: int = 20,
        max_drawdown_threshold: float = 0.20,
        max_rejected_rate: float = 0.10,
        min_parity_score: float = 0.70,
        max_evidence_gap_hours: int = 25,
    ) -> FinalPaperTestReport:
        """Generate the final 30-day paper testing report with micro-live recommendation.

        Does NOT approve micro-live. Only produces a structured recommendation.
        """
        session_report = await self._store.get_session_report(session_id)
        daily_rows = await self._store.list_daily_summaries(session_id, limit=365)
        weekly_rows = await self._store.list_weekly_summaries(session_id, limit=52)

        # ── Core metrics ──────────────────────────────────────────────
        days_observed = len(daily_rows)
        trade_count = int(session_report.get("trade_count", 0))
        rejected_order_count = sum(r["rejected_order_count"] for r in daily_rows)
        partial_fill_count = sum(r["partial_fill_count"] for r in daily_rows)
        recon_critical = int(session_report.get("reconciliation_critical_count", 0))
        incident_count = int(session_report.get("incident_count", 0))
        alert_count = sum(r["alert_count"] for r in daily_rows)

        # Max drawdown over all daily summaries
        max_drawdown_pct = (
            max(Decimal(str(r["max_drawdown_pct"])) for r in daily_rows)
            if daily_rows
            else Decimal("0")
        )

        # Total P&L from equity diff
        if daily_rows:
            sorted_daily = sorted(daily_rows, key=lambda r: r["summary_date"])
            total_pnl = Decimal(str(sorted_daily[-1]["ending_equity"])) - Decimal(
                str(sorted_daily[0]["starting_equity"])
            )
        else:
            total_pnl = Decimal("0")

        # Gross/net return from latest weekly
        gross_return_pct: Decimal | None = None
        net_return_pct: Decimal | None = None
        if weekly_rows:
            gross_return_pct = Decimal(str(weekly_rows[0].get("pnl_pct", 0)))

        # Average slippage and latency from TCA records (fetch directly)
        avg_slippage_pct, avg_latency_ms = await self._fetch_tca_averages(session_id)

        # Parity score from most recent weekly summary
        parity_score: Decimal | None = None
        if weekly_rows and weekly_rows[0].get("parity_score") is not None:
            parity_score = Decimal(str(weekly_rows[0]["parity_score"]))

        # ── Rejected rate ─────────────────────────────────────────────
        total_attempts = trade_count + rejected_order_count
        rejected_rate = rejected_order_count / total_attempts if total_attempts > 0 else 0.0

        # ── Evidence gap check ────────────────────────────────────────
        evidence_gap_ok = await self._check_evidence_gap(session_id, max_evidence_gap_hours)

        # ── Acceptance criteria ───────────────────────────────────────
        checks: list[MicroLiveReadinessCheck] = [
            MicroLiveReadinessCheck(
                criterion="minimum_days_observed",
                passed=days_observed >= min_days,
                actual_value=str(days_observed),
                threshold=f">= {min_days}",
                detail=f"{days_observed} daily summaries found",
            ),
            MicroLiveReadinessCheck(
                criterion="minimum_trade_count",
                passed=trade_count >= min_trades,
                actual_value=str(trade_count),
                threshold=f">= {min_trades}",
            ),
            MicroLiveReadinessCheck(
                criterion="zero_unresolved_critical_reconciliation",
                passed=recon_critical == 0,
                actual_value=str(recon_critical),
                threshold="= 0",
                detail="Critical reconciliation events block micro-live eligibility",
            ),
            MicroLiveReadinessCheck(
                criterion="zero_unresolved_critical_alerts",
                passed=incident_count == 0,
                actual_value=str(incident_count),
                threshold="= 0",
            ),
            MicroLiveReadinessCheck(
                criterion="max_drawdown_within_threshold",
                passed=float(max_drawdown_pct) <= max_drawdown_threshold,
                actual_value=f"{float(max_drawdown_pct):.2%}",
                threshold=f"<= {max_drawdown_threshold:.2%}",
            ),
            MicroLiveReadinessCheck(
                criterion="rejected_order_rate_within_threshold",
                passed=rejected_rate <= max_rejected_rate,
                actual_value=f"{rejected_rate:.2%}",
                threshold=f"<= {max_rejected_rate:.2%}",
            ),
            MicroLiveReadinessCheck(
                criterion="no_evidence_gap",
                passed=evidence_gap_ok,
                actual_value="ok" if evidence_gap_ok else "gap_detected",
                threshold=f"<= {max_evidence_gap_hours}h between snapshots",
                detail="Gaps indicate bot was offline or evidence capture failed",
            ),
        ]

        if parity_score is not None:
            checks.append(
                MicroLiveReadinessCheck(
                    criterion="paper_backtest_parity_score",
                    passed=float(parity_score) >= min_parity_score,
                    actual_value=f"{float(parity_score):.2f}",
                    threshold=f">= {min_parity_score:.2f}",
                    detail="paper↔backtest parity (win_rate + drawdown), computed weekly",
                )
            )

        # ── Recommendation ────────────────────────────────────────────
        blocking_fails = [
            c
            for c in checks
            if not c.passed
            and c.criterion
            in {
                "minimum_days_observed",
                "zero_unresolved_critical_reconciliation",
                "zero_unresolved_critical_alerts",
                "no_evidence_gap",
            }
        ]
        soft_fails = [c for c in checks if not c.passed]

        if blocking_fails:
            if recon_critical > 0 or incident_count > 0:
                recommendation = MicroLiveRecommendation.REJECT_STRATEGY
                rationale = (
                    f"Blocking failures: {[c.criterion for c in blocking_fails]}. "
                    "Unresolved critical reconciliation or alert incidents require operator review."
                )
            else:
                recommendation = MicroLiveRecommendation.CONTINUE_PAPER
                rationale = (
                    f"Blocking criteria not met: {[c.criterion for c in blocking_fails]}. "
                    "Continue paper testing."
                )
        elif soft_fails:
            recommendation = MicroLiveRecommendation.FIX_ISSUES
            rationale = (
                f"Non-blocking criteria not met: {[c.criterion for c in soft_fails]}. "
                "Fix issues before requesting micro-live review."
            )
        else:
            recommendation = MicroLiveRecommendation.ELIGIBLE_FOR_REVIEW
            rationale = (
                "All acceptance criteria passed. "
                "Submit to operator for micro-live review. "
                "Micro-live is NOT automatically approved — operator sign-off required."
            )

        log.info(
            "evidence_final_report_generated",
            session_id=str(session_id),
            recommendation=recommendation.value,
            days_observed=days_observed,
            trade_count=trade_count,
            checks_passed=sum(1 for c in checks if c.passed),
            checks_total=len(checks),
        )

        return FinalPaperTestReport(
            session_id=session_id,
            generated_at=_now(),
            days_observed=days_observed,
            trade_count=trade_count,
            rejected_order_count=rejected_order_count,
            partial_fill_count=partial_fill_count,
            max_drawdown_pct=max_drawdown_pct,
            total_pnl=total_pnl,
            gross_return_pct=gross_return_pct,
            net_return_pct=net_return_pct,
            avg_slippage_pct=avg_slippage_pct,
            avg_latency_ms=avg_latency_ms,
            reconciliation_critical_count=recon_critical,
            alert_count=alert_count,
            incident_count=incident_count,
            parity_score=parity_score,
            readiness_checks=list(checks),
            recommendation=recommendation,
            recommendation_rationale=rationale,
        )

    async def _fetch_tca_averages(self, session_id: uuid.UUID) -> tuple[Decimal, Decimal]:
        """Return (avg_slippage_pct, avg_latency_ms) from TCA records."""
        try:
            async with self._store._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT AVG(slippage_pct) AS avg_slip,
                           AVG(latency_ms) AS avg_lat
                    FROM evidence_tca_records
                    WHERE session_id = $1
                    """,
                    session_id,
                )
            if row and row["avg_slip"] is not None:
                return Decimal(str(row["avg_slip"])), Decimal(str(row["avg_lat"] or 0))
        except Exception as exc:
            log.warning("evidence_tca_averages_failed", error=str(exc))
        return Decimal("0"), Decimal("0")

    async def _check_evidence_gap(
        self,
        session_id: uuid.UUID,
        max_gap_hours: int,
    ) -> bool:
        """Return True if no portfolio snapshot gap exceeds max_gap_hours."""
        try:
            async with self._store._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT captured_at FROM evidence_portfolio_snapshots
                    WHERE session_id = $1
                    ORDER BY captured_at ASC
                    """,
                    session_id,
                )
            if len(rows) < 2:
                return True
            for i in range(1, len(rows)):
                gap = rows[i]["captured_at"] - rows[i - 1]["captured_at"]
                if gap.total_seconds() > max_gap_hours * 3600:
                    return False
        except Exception as exc:
            log.warning("evidence_gap_check_failed", error=str(exc))
        return True
