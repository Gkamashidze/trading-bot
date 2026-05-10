"""Unit tests for the Paper Testing Evidence Store.

Tests cover:
- Session start/resume/end behavior
- Idempotent inserts (ON CONFLICT DO NOTHING)
- UTC timestamp validation
- Daily summary generation
- Weekly summary generation
- Export JSON/CSV
- Final report recommendation logic
- Startup resume behavior with same/different config hash
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from trading_bot.evidence.models import (
    DailyEvidenceSummary,
    MicroLiveRecommendation,
    PaperSession,
    PortfolioEvidenceSnapshot,
    SessionStatus,
    TCAEvidenceRecord,
)
from trading_bot.evidence.reporter import EvidenceReporter
from trading_bot.evidence.store import EvidenceStore, _hash_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pool(
    fetchrow_result: Any = None,
    fetch_result: list[Any] | None = None,
    fetchval_result: Any = 0,
    execute_result: str = "INSERT 0 1",
) -> MagicMock:
    """Build a minimal asyncpg pool mock."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=execute_result)
    mock_conn.fetchrow = AsyncMock(return_value=fetchrow_result)
    mock_conn.fetch = AsyncMock(return_value=fetch_result or [])
    mock_conn.fetchval = AsyncMock(return_value=fetchval_result)
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return mock_pool


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_date() -> date:
    return datetime.now(UTC).date()


# ---------------------------------------------------------------------------
# UTC timestamp validation
# ---------------------------------------------------------------------------


class TestUTCValidation:
    def test_paper_session_rejects_naive_datetime(self) -> None:
        with pytest.raises(ValidationError):
            PaperSession(
                started_at=datetime(2026, 1, 1),  # noqa: DTZ001 — intentionally naive for test
                environment="test",
                config_snapshot_hash="abc",
                paper_capital=Decimal("10000"),
            )

    def test_paper_session_accepts_utc_datetime(self) -> None:
        session = PaperSession(
            started_at=_utc_now(),
            environment="test",
            config_snapshot_hash="abc",
            paper_capital=Decimal("10000"),
        )
        assert session.started_at.tzinfo is not None

    def test_portfolio_snapshot_rejects_naive_datetime(self) -> None:
        with pytest.raises(ValidationError):
            PortfolioEvidenceSnapshot(
                session_id=uuid.uuid4(),
                captured_at=datetime(2026, 1, 1),  # noqa: DTZ001 — intentionally naive for test
                cash_balance=Decimal("1000"),
                total_equity=Decimal("1000"),
                daily_pnl=Decimal("0"),
                daily_drawdown_pct=Decimal("0"),
                idempotency_key="test",
            )

    def test_daily_summary_rejects_naive_datetime(self) -> None:
        with pytest.raises(ValidationError):
            DailyEvidenceSummary(
                session_id=uuid.uuid4(),
                summary_date=_utc_date(),
                starting_equity=Decimal("10000"),
                ending_equity=Decimal("10100"),
                pnl=Decimal("100"),
                pnl_pct=Decimal("1"),
                generated_at=datetime(2026, 1, 1),  # noqa: DTZ001 — intentionally naive for test
                idempotency_key="test",
            )


# ---------------------------------------------------------------------------
# Config hash stability
# ---------------------------------------------------------------------------


class TestConfigHash:
    def test_same_dict_produces_same_hash(self) -> None:
        cfg = {"environment": "test", "capital": 10000}
        assert _hash_config(cfg) == _hash_config(cfg)

    def test_different_dict_produces_different_hash(self) -> None:
        cfg_a = {"environment": "test", "capital": 10000}
        cfg_b = {"environment": "production", "capital": 10000}
        assert _hash_config(cfg_a) != _hash_config(cfg_b)

    def test_key_order_does_not_matter(self) -> None:
        cfg_a = {"a": 1, "b": 2}
        cfg_b = {"b": 2, "a": 1}
        assert _hash_config(cfg_a) == _hash_config(cfg_b)


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    @pytest.mark.asyncio
    async def test_start_session_inserts_row(self) -> None:
        pool = _make_pool()
        store = EvidenceStore(pool)
        with patch("trading_bot.evidence.store._audit", AsyncMock()):
            session = await store.start_session(
                environment="test",
                config_snapshot={"k": "v"},
                paper_capital=Decimal("10000"),
                symbols=["BTC/USDT"],
                strategies=["sma"],
            )
        assert session.status == SessionStatus.RUNNING
        assert session.environment == "test"
        conn = pool.acquire.return_value.__aenter__.return_value
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_current_session_returns_none_when_no_rows(self) -> None:
        pool = _make_pool(fetchrow_result=None)
        store = EvidenceStore(pool)
        result = await store.get_current_session()
        assert result is None

    @pytest.mark.asyncio
    async def test_ensure_session_starts_new_when_none_exists(self) -> None:
        pool = _make_pool(fetchrow_result=None)
        store = EvidenceStore(pool)
        with patch("trading_bot.evidence.store._audit", AsyncMock()):
            session = await store.ensure_session(
                environment="test",
                config_snapshot={"k": "v"},
                paper_capital=Decimal("10000"),
                symbols=["BTC/USDT"],
                strategies=[],
            )
        assert session.status == SessionStatus.RUNNING

    @pytest.mark.asyncio
    async def test_ensure_session_resumes_when_hash_matches(self) -> None:
        cfg = {"k": "v"}
        config_hash = _hash_config(cfg)
        existing_row = {
            "session_id": uuid.uuid4(),
            "started_at": _utc_now(),
            "ended_at": None,
            "environment": "test",
            "git_commit": None,
            "config_snapshot_hash": config_hash,
            "paper_capital": Decimal("10000"),
            "symbols": json.dumps(["BTC/USDT"]),
            "strategies": json.dumps([]),
            "status": "running",
            "notes": "",
        }
        pool = _make_pool(fetchrow_result=existing_row)
        store = EvidenceStore(pool)

        # Patch get_current_session to return existing session
        existing = PaperSession(
            session_id=existing_row["session_id"],
            started_at=existing_row["started_at"],
            environment="test",
            config_snapshot_hash=config_hash,
            paper_capital=Decimal("10000"),
        )
        with patch.object(store, "get_current_session", AsyncMock(return_value=existing)):
            result = await store.ensure_session(
                environment="test",
                config_snapshot=cfg,
                paper_capital=Decimal("10000"),
                symbols=["BTC/USDT"],
                strategies=[],
            )
        assert result.session_id == existing.session_id

    @pytest.mark.asyncio
    async def test_ensure_session_closes_and_starts_new_when_hash_differs(self) -> None:
        old_hash = "oldhash1234"
        existing = PaperSession(
            started_at=_utc_now(),
            environment="test",
            config_snapshot_hash=old_hash,
            paper_capital=Decimal("10000"),
        )
        pool = _make_pool()
        store = EvidenceStore(pool)
        with (
            patch.object(store, "get_current_session", AsyncMock(return_value=existing)),
            patch.object(store, "end_session", AsyncMock()) as mock_end,
            patch.object(store, "start_session", AsyncMock(return_value=existing)) as mock_start,
            patch("trading_bot.evidence.store._audit", AsyncMock()),
        ):
            await store.ensure_session(
                environment="test",
                config_snapshot={"k": "NEW"},  # different hash
                paper_capital=Decimal("10000"),
                symbols=[],
                strategies=[],
            )
        mock_end.assert_called_once_with(existing.session_id, SessionStatus.COMPLETED)
        mock_start.assert_called_once()


# ---------------------------------------------------------------------------
# Idempotent inserts
# ---------------------------------------------------------------------------


class TestIdempotentInserts:
    @pytest.mark.asyncio
    async def test_portfolio_snapshot_returns_false_on_duplicate(self) -> None:
        pool = _make_pool(execute_result="INSERT 0 0")  # conflict — no row inserted
        store = EvidenceStore(pool)
        snap = PortfolioEvidenceSnapshot(
            session_id=uuid.uuid4(),
            captured_at=_utc_now(),
            cash_balance=Decimal("1000"),
            total_equity=Decimal("1000"),
            daily_pnl=Decimal("0"),
            daily_drawdown_pct=Decimal("0"),
            idempotency_key="dup_key",
        )
        result = await store.insert_portfolio_snapshot(snap)
        assert result is False

    @pytest.mark.asyncio
    async def test_portfolio_snapshot_returns_true_on_first_insert(self) -> None:
        pool = _make_pool(execute_result="INSERT 0 1")
        store = EvidenceStore(pool)
        snap = PortfolioEvidenceSnapshot(
            session_id=uuid.uuid4(),
            captured_at=_utc_now(),
            cash_balance=Decimal("1000"),
            total_equity=Decimal("1000"),
            daily_pnl=Decimal("0"),
            daily_drawdown_pct=Decimal("0"),
            idempotency_key="new_key",
        )
        result = await store.insert_portfolio_snapshot(snap)
        assert result is True

    @pytest.mark.asyncio
    async def test_tca_record_idempotent_insert(self) -> None:
        pool = _make_pool(execute_result="INSERT 0 0")
        store = EvidenceStore(pool)
        rec = TCAEvidenceRecord(
            session_id=uuid.uuid4(),
            captured_at=_utc_now(),
            order_id="ord-001",
            symbol="BTC/USDT",
            side="BUY",
            signal_price=Decimal("50000"),
            fill_price=Decimal("50000"),
            quantity=Decimal("0.01"),
            outcome="filled",
            idempotency_key="tca_dup",
        )
        result = await store.insert_tca_record(rec)
        assert result is False

    @pytest.mark.asyncio
    async def test_daily_summary_idempotent_insert(self) -> None:
        pool = _make_pool(execute_result="INSERT 0 0")
        store = EvidenceStore(pool)
        summary = DailyEvidenceSummary(
            session_id=uuid.uuid4(),
            summary_date=_utc_date(),
            starting_equity=Decimal("10000"),
            ending_equity=Decimal("10100"),
            pnl=Decimal("100"),
            pnl_pct=Decimal("1"),
            generated_at=_utc_now(),
            idempotency_key="daily_dup",
        )
        result = await store.insert_daily_summary(summary)
        assert result is False


# ---------------------------------------------------------------------------
# Daily and weekly summary generation
# ---------------------------------------------------------------------------


class TestSummaryGeneration:
    @pytest.mark.asyncio
    async def test_build_daily_summary_returns_none_when_no_snapshots(self) -> None:
        pool = _make_pool(fetchrow_result=None)
        store = EvidenceStore(pool)
        result = await store.build_daily_summary(uuid.uuid4(), date(2026, 5, 1))
        assert result is None

    @pytest.mark.asyncio
    async def test_build_daily_summary_computes_pnl(self) -> None:
        session_id = uuid.uuid4()
        first_row = {"total_equity": Decimal("10000")}
        last_row = {"total_equity": Decimal("10500"), "daily_drawdown_pct": Decimal("0.01")}

        # Sequence of calls: first_snap, last_snap, then 5 COUNT queries
        pool = _make_pool()
        conn = pool.acquire.return_value.__aenter__.return_value
        conn.fetchrow = AsyncMock(side_effect=[first_row, last_row])
        conn.fetchval = AsyncMock(return_value=5)

        store = EvidenceStore(pool)
        summary = await store.build_daily_summary(session_id, date(2026, 5, 1))

        assert summary is not None
        assert summary.pnl == Decimal("500")
        assert summary.starting_equity == Decimal("10000")
        assert summary.ending_equity == Decimal("10500")

    @pytest.mark.asyncio
    async def test_reporter_generates_weekly_from_daily_rows(self) -> None:
        session_id = uuid.uuid4()
        monday = date(2026, 5, 4)  # Monday
        sunday = date(2026, 5, 10)  # Sunday

        daily_rows = [
            {
                "summary_date": monday + timedelta(days=i),
                "starting_equity": Decimal("10000"),
                "ending_equity": Decimal("10100"),
                "pnl": Decimal("100"),
                "pnl_pct": Decimal("1.0"),
                "max_drawdown_pct": Decimal("0.5"),
                "trade_count": 2,
                "rejected_order_count": 0,
                "partial_fill_count": 0,
                "signal_count": 4,
                "reconciliation_critical_count": 0,
                "alert_count": 0,
                "incident_count": 0,
            }
            for i in range(7)
        ]

        pool = _make_pool()
        store = EvidenceStore(pool)
        with patch.object(store, "list_daily_summaries", AsyncMock(return_value=daily_rows)):
            with patch.object(store, "insert_weekly_summary", AsyncMock(return_value=True)):
                reporter = EvidenceReporter(store)
                summary = await reporter.generate_and_persist_weekly_summary(
                    session_id, week_start=monday
                )

        assert summary is not None
        assert summary.trade_count == 14  # 2 per day x 7
        assert summary.week_start == monday
        assert summary.week_end == sunday


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


class TestExport:
    @pytest.mark.asyncio
    async def test_export_csv_returns_header_when_no_rows(self) -> None:
        pool = _make_pool()
        store = EvidenceStore(pool)
        with patch.object(store, "list_daily_summaries", AsyncMock(return_value=[])):
            csv = await store.export_session_csv(uuid.uuid4())
        assert csv.startswith("date,pnl")

    @pytest.mark.asyncio
    async def test_export_csv_includes_data_rows(self) -> None:
        pool = _make_pool()
        store = EvidenceStore(pool)
        rows = [
            {
                "summary_date": date(2026, 5, 1),
                "pnl": Decimal("100"),
                "pnl_pct": Decimal("1"),
                "trade_count": 3,
                "rejected_order_count": 0,
                "partial_fill_count": 0,
                "max_drawdown_pct": Decimal("0.5"),
                "reconciliation_critical_count": 0,
                "alert_count": 0,
            }
        ]
        with patch.object(store, "list_daily_summaries", AsyncMock(return_value=rows)):
            csv = await store.export_session_csv(uuid.uuid4())
        lines = csv.strip().split("\n")
        assert len(lines) == 2
        assert "2026-05-01" in lines[1]

    @pytest.mark.asyncio
    async def test_export_json_includes_session(self) -> None:
        session_id = uuid.uuid4()
        pool = _make_pool()
        store = EvidenceStore(pool)
        with (
            patch.object(
                store,
                "get_session_report",
                AsyncMock(return_value={"session": {"session_id": str(session_id)}}),
            ),
            patch.object(store, "list_daily_summaries", AsyncMock(return_value=[])),
            patch.object(store, "list_weekly_summaries", AsyncMock(return_value=[])),
            patch.object(store, "list_portfolio_snapshots", AsyncMock(return_value=[])),
            patch.object(store, "list_reconciliation_reports", AsyncMock(return_value=[])),
        ):
            result = await store.export_session_json(session_id)
        assert "session_id" in result
        assert result["session_id"] == str(session_id)


# ---------------------------------------------------------------------------
# Final report recommendation logic
# ---------------------------------------------------------------------------


class TestFinalReportRecommendation:
    def _make_daily_rows(self, n: int, trade_count: int = 2) -> list[dict[str, Any]]:
        return [
            {
                "summary_date": date(2026, 4, 1) + timedelta(days=i),
                "starting_equity": Decimal("10000"),
                "ending_equity": Decimal("10100"),
                "pnl": Decimal("100"),
                "pnl_pct": Decimal("1.0"),
                "max_drawdown_pct": Decimal("0.05"),
                "trade_count": trade_count,
                "rejected_order_count": 0,
                "partial_fill_count": 0,
                "signal_count": 4,
                "reconciliation_critical_count": 0,
                "alert_count": 0,
                "incident_count": 0,
            }
            for i in range(n)
        ]

    @pytest.mark.asyncio
    async def test_recommendation_continue_paper_when_not_enough_days(self) -> None:
        pool = _make_pool()
        store = EvidenceStore(pool)
        reporter = EvidenceReporter(store)

        daily = self._make_daily_rows(10)  # only 10 days, need 30
        with (
            patch.object(
                store,
                "get_session_report",
                AsyncMock(
                    return_value={
                        "trade_count": 20,
                        "reconciliation_critical_count": 0,
                        "incident_count": 0,
                    }
                ),
            ),
            patch.object(store, "list_daily_summaries", AsyncMock(return_value=daily)),
            patch.object(store, "list_weekly_summaries", AsyncMock(return_value=[])),
            patch.object(
                reporter,
                "_fetch_tca_averages",
                AsyncMock(return_value=(Decimal("0"), Decimal("0"))),
            ),
            patch.object(reporter, "_check_evidence_gap", AsyncMock(return_value=True)),
        ):
            report = await reporter.generate_final_report(uuid.uuid4(), min_days=30)

        assert report.recommendation == MicroLiveRecommendation.CONTINUE_PAPER

    @pytest.mark.asyncio
    async def test_recommendation_fix_issues_when_trade_count_low(self) -> None:
        pool = _make_pool()
        store = EvidenceStore(pool)
        reporter = EvidenceReporter(store)

        daily = self._make_daily_rows(30, trade_count=0)  # 30 days but 0 trades
        with (
            patch.object(
                store,
                "get_session_report",
                AsyncMock(
                    return_value={
                        "trade_count": 0,
                        "reconciliation_critical_count": 0,
                        "incident_count": 0,
                    }
                ),
            ),
            patch.object(store, "list_daily_summaries", AsyncMock(return_value=daily)),
            patch.object(store, "list_weekly_summaries", AsyncMock(return_value=[])),
            patch.object(
                reporter,
                "_fetch_tca_averages",
                AsyncMock(return_value=(Decimal("0"), Decimal("0"))),
            ),
            patch.object(reporter, "_check_evidence_gap", AsyncMock(return_value=True)),
        ):
            report = await reporter.generate_final_report(uuid.uuid4(), min_days=30, min_trades=20)

        assert report.recommendation == MicroLiveRecommendation.FIX_ISSUES

    @pytest.mark.asyncio
    async def test_recommendation_eligible_when_all_pass(self) -> None:
        pool = _make_pool()
        store = EvidenceStore(pool)
        reporter = EvidenceReporter(store)

        daily = self._make_daily_rows(30, trade_count=2)  # 30 days x 2 = 60 trades
        with (
            patch.object(
                store,
                "get_session_report",
                AsyncMock(
                    return_value={
                        "trade_count": 60,
                        "reconciliation_critical_count": 0,
                        "incident_count": 0,
                    }
                ),
            ),
            patch.object(store, "list_daily_summaries", AsyncMock(return_value=daily)),
            patch.object(store, "list_weekly_summaries", AsyncMock(return_value=[])),
            patch.object(
                reporter,
                "_fetch_tca_averages",
                AsyncMock(return_value=(Decimal("0"), Decimal("0"))),
            ),
            patch.object(reporter, "_check_evidence_gap", AsyncMock(return_value=True)),
        ):
            report = await reporter.generate_final_report(
                uuid.uuid4(),
                min_days=30,
                min_trades=20,
                max_drawdown_threshold=0.20,
                max_rejected_rate=0.10,
                max_evidence_gap_hours=25,
            )

        assert report.recommendation == MicroLiveRecommendation.ELIGIBLE_FOR_REVIEW
        assert report.days_observed == 30
        assert report.trade_count == 60

    @pytest.mark.asyncio
    async def test_recommendation_reject_when_critical_reconciliation(self) -> None:
        pool = _make_pool()
        store = EvidenceStore(pool)
        reporter = EvidenceReporter(store)

        daily = self._make_daily_rows(5)
        with (
            patch.object(
                store,
                "get_session_report",
                AsyncMock(
                    return_value={
                        "trade_count": 10,
                        "reconciliation_critical_count": 3,  # blocking
                        "incident_count": 0,
                    }
                ),
            ),
            patch.object(store, "list_daily_summaries", AsyncMock(return_value=daily)),
            patch.object(store, "list_weekly_summaries", AsyncMock(return_value=[])),
            patch.object(
                reporter,
                "_fetch_tca_averages",
                AsyncMock(return_value=(Decimal("0"), Decimal("0"))),
            ),
            patch.object(reporter, "_check_evidence_gap", AsyncMock(return_value=True)),
        ):
            report = await reporter.generate_final_report(uuid.uuid4(), min_days=30)

        assert report.recommendation == MicroLiveRecommendation.REJECT_STRATEGY
        assert report.reconciliation_critical_count == 3

    @pytest.mark.asyncio
    async def test_final_report_live_trading_not_enabled(self) -> None:
        """Confirm recommendation never says 'approved' — only eligible_for_review at best."""
        pool = _make_pool()
        store = EvidenceStore(pool)
        reporter = EvidenceReporter(store)

        daily = self._make_daily_rows(30, trade_count=3)
        with (
            patch.object(
                store,
                "get_session_report",
                AsyncMock(
                    return_value={
                        "trade_count": 90,
                        "reconciliation_critical_count": 0,
                        "incident_count": 0,
                    }
                ),
            ),
            patch.object(store, "list_daily_summaries", AsyncMock(return_value=daily)),
            patch.object(store, "list_weekly_summaries", AsyncMock(return_value=[])),
            patch.object(
                reporter,
                "_fetch_tca_averages",
                AsyncMock(return_value=(Decimal("0"), Decimal("0"))),
            ),
            patch.object(reporter, "_check_evidence_gap", AsyncMock(return_value=True)),
        ):
            report = await reporter.generate_final_report(uuid.uuid4(), min_days=30, min_trades=20)

        # Best outcome is "eligible_for_review" — never "approved" or "live_trading_enabled"
        assert report.recommendation in {
            MicroLiveRecommendation.ELIGIBLE_FOR_REVIEW,
            MicroLiveRecommendation.CONTINUE_PAPER,
            MicroLiveRecommendation.FIX_ISSUES,
            MicroLiveRecommendation.REJECT_STRATEGY,
        }
        assert "approved" not in report.recommendation.value
        assert "live_trading" not in report.recommendation.value
