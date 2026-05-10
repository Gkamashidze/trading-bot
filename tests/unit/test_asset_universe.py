"""Unit tests for the asset universe registry.

Tests:
- AssetSpec validation (capital cap hard limit, field constraints)
- AssetUniverseRegistry helpers (is_tradeable, is_data_eligible, filters)
- Production YAML correctness (all assets, status rules, cap rules)
- Feature flag gating invariants
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from trading_bot.asset_universe import (
    AssetSpec,
    AssetStatus,
    AssetUniverseRegistry,
    get_asset_registry,
)
from trading_bot.core.models import AssetClass, ExchangeId

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_spec(
    symbol: str = "BTC/USDT",
    status: AssetStatus = AssetStatus.PAPER,
    asset_class: AssetClass = AssetClass.CRYPTO,
    phase: int = 1,
    max_capital_pct: float = 0.20,
) -> AssetSpec:
    return AssetSpec(
        symbol=symbol,
        venue=ExchangeId.BINANCE,
        asset_class=asset_class,
        status=status,
        phase=phase,
        max_capital_pct=max_capital_pct,
        max_order_notional_usd=5000,
        min_24h_volume_usd=1_000_000,
        max_spread_bps=5.0,
        required_history_days=30,
    )


def _make_registry(*specs: AssetSpec) -> AssetUniverseRegistry:
    return AssetUniverseRegistry(assets=list(specs))


# ---------------------------------------------------------------------------
# AssetSpec validation
# ---------------------------------------------------------------------------


class TestAssetSpec:
    def test_valid_spec_accepted(self) -> None:
        spec = _make_spec()
        assert spec.symbol == "BTC/USDT"
        assert spec.status == AssetStatus.PAPER

    def test_max_capital_pct_hard_limit_rejected(self) -> None:
        with pytest.raises(ValueError, match="hard limit"):
            _make_spec(max_capital_pct=0.51)

    def test_max_capital_pct_at_limit_accepted(self) -> None:
        spec = _make_spec(max_capital_pct=0.50)
        assert spec.max_capital_pct == 0.50

    def test_zero_capital_pct_rejected(self) -> None:
        with pytest.raises(ValueError):
            _make_spec(max_capital_pct=0.0)

    def test_phase_out_of_range_rejected(self) -> None:
        with pytest.raises(ValueError):
            AssetSpec(
                symbol="X",
                venue=ExchangeId.BINANCE,
                asset_class=AssetClass.CRYPTO,
                status=AssetStatus.DISABLED,
                phase=6,  # max is 5
                max_capital_pct=0.10,
                max_order_notional_usd=1000,
                min_24h_volume_usd=0,
                max_spread_bps=5.0,
                required_history_days=1,
            )

    def test_spec_is_immutable(self) -> None:
        spec = _make_spec()
        with pytest.raises(ValidationError):
            spec.symbol = "ETH/USDT"  # type: ignore[misc]

    def test_experimental_flag_default_false(self) -> None:
        spec = _make_spec()
        assert spec.experimental is False


# ---------------------------------------------------------------------------
# AssetUniverseRegistry helpers
# ---------------------------------------------------------------------------


class TestAssetUniverseRegistry:
    def test_disabled_asset_is_not_tradeable(self) -> None:
        reg = _make_registry(_make_spec("BTC/USDT", AssetStatus.DISABLED))
        assert not reg.is_tradeable("BTC/USDT")

    def test_research_asset_is_not_tradeable(self) -> None:
        reg = _make_registry(_make_spec("SOL/USDT", AssetStatus.RESEARCH))
        assert not reg.is_tradeable("SOL/USDT")

    def test_paper_asset_is_tradeable(self) -> None:
        reg = _make_registry(_make_spec("BTC/USDT", AssetStatus.PAPER))
        assert reg.is_tradeable("BTC/USDT")

    def test_micro_live_candidate_is_tradeable(self) -> None:
        reg = _make_registry(_make_spec("BTC/USDT", AssetStatus.MICRO_LIVE_CANDIDATE))
        assert reg.is_tradeable("BTC/USDT")

    def test_unknown_symbol_is_not_tradeable(self) -> None:
        reg = _make_registry(_make_spec("BTC/USDT", AssetStatus.PAPER))
        assert not reg.is_tradeable("UNKNOWN/USDT")

    def test_disabled_asset_is_not_data_eligible(self) -> None:
        reg = _make_registry(_make_spec("DOGE/USDT", AssetStatus.DISABLED))
        assert not reg.is_data_eligible("DOGE/USDT")

    def test_research_asset_is_data_eligible(self) -> None:
        reg = _make_registry(_make_spec("SOL/USDT", AssetStatus.RESEARCH))
        assert reg.is_data_eligible("SOL/USDT")

    def test_paper_asset_is_data_eligible(self) -> None:
        reg = _make_registry(_make_spec("BTC/USDT", AssetStatus.PAPER))
        assert reg.is_data_eligible("BTC/USDT")

    def test_tradeable_returns_only_paper_and_above(self) -> None:
        reg = _make_registry(
            _make_spec("BTC/USDT", AssetStatus.PAPER),
            _make_spec("SOL/USDT", AssetStatus.RESEARCH),
            _make_spec("BNB/USDT", AssetStatus.DISABLED),
        )
        symbols = {a.symbol for a in reg.tradeable()}
        assert symbols == {"BTC/USDT"}
        assert "SOL/USDT" not in symbols
        assert "BNB/USDT" not in symbols

    def test_research_and_above_excludes_disabled(self) -> None:
        reg = _make_registry(
            _make_spec("BTC/USDT", AssetStatus.PAPER),
            _make_spec("SOL/USDT", AssetStatus.RESEARCH),
            _make_spec("BNB/USDT", AssetStatus.DISABLED),
        )
        symbols = {a.symbol for a in reg.research_and_above()}
        assert "BTC/USDT" in symbols
        assert "SOL/USDT" in symbols
        assert "BNB/USDT" not in symbols

    def test_by_status_filters_correctly(self) -> None:
        reg = _make_registry(
            _make_spec("BTC/USDT", AssetStatus.PAPER),
            _make_spec("ETH/USDT", AssetStatus.PAPER),
            _make_spec("SOL/USDT", AssetStatus.RESEARCH),
        )
        assert len(reg.by_status(AssetStatus.PAPER)) == 2
        assert len(reg.by_status(AssetStatus.RESEARCH)) == 1
        assert len(reg.by_status(AssetStatus.DISABLED)) == 0

    def test_by_phase_filters_correctly(self) -> None:
        reg = _make_registry(
            _make_spec("BTC/USDT", phase=1),
            _make_spec("ETH/USDT", phase=1),
            _make_spec("SOL/USDT", phase=2),
        )
        assert len(reg.by_phase(1)) == 2
        assert len(reg.by_phase(2)) == 1

    def test_crypto_symbols_excludes_disabled(self) -> None:
        reg = _make_registry(
            _make_spec("BTC/USDT", AssetStatus.PAPER, AssetClass.CRYPTO),
            _make_spec("BNB/USDT", AssetStatus.DISABLED, AssetClass.CRYPTO),
        )
        symbols = reg.crypto_symbols()
        assert "BTC/USDT" in symbols
        assert "BNB/USDT" not in symbols

    def test_crypto_symbols_tradeable_only(self) -> None:
        reg = _make_registry(
            _make_spec("BTC/USDT", AssetStatus.PAPER, AssetClass.CRYPTO),
            _make_spec("SOL/USDT", AssetStatus.RESEARCH, AssetClass.CRYPTO),
        )
        tradeable = reg.crypto_symbols(tradeable_only=True)
        assert "BTC/USDT" in tradeable
        assert "SOL/USDT" not in tradeable

    def test_get_returns_none_for_unknown_symbol(self) -> None:
        reg = _make_registry(_make_spec("BTC/USDT"))
        assert reg.get("NOTEXIST") is None

    def test_all_symbols_includes_research_excludes_disabled(self) -> None:
        reg = _make_registry(
            _make_spec("BTC/USDT", AssetStatus.PAPER),
            _make_spec("SOL/USDT", AssetStatus.RESEARCH),
            _make_spec("BNB/USDT", AssetStatus.DISABLED),
        )
        symbols = reg.all_symbols(tradeable_only=False)
        assert "BTC/USDT" in symbols
        assert "SOL/USDT" in symbols
        assert "BNB/USDT" not in symbols

    def test_all_symbols_tradeable_only(self) -> None:
        reg = _make_registry(
            _make_spec("BTC/USDT", AssetStatus.PAPER),
            _make_spec("SOL/USDT", AssetStatus.RESEARCH),
        )
        symbols = reg.all_symbols(tradeable_only=True)
        assert "BTC/USDT" in symbols
        assert "SOL/USDT" not in symbols

    def test_empty_registry_is_valid(self) -> None:
        reg = AssetUniverseRegistry(assets=[])
        assert reg.tradeable() == []
        assert not reg.is_tradeable("BTC/USDT")
        assert reg.all_symbols() == set()


# ---------------------------------------------------------------------------
# Production YAML — correctness tests (uses the real asset_universe.yaml)
# ---------------------------------------------------------------------------


class TestProductionRegistry:
    """Validate the shipped asset_universe.yaml against business invariants."""

    def test_registry_loads_without_error(self) -> None:
        reg = get_asset_registry()
        assert len(reg.assets) > 0

    def test_btc_and_eth_are_paper_status(self) -> None:
        reg = get_asset_registry()
        btc = reg.get("BTC/USDT")
        eth = reg.get("ETH/USDT")
        assert btc is not None, "BTC/USDT missing from registry"
        assert eth is not None, "ETH/USDT missing from registry"
        assert btc.status == AssetStatus.PAPER
        assert eth.status == AssetStatus.PAPER

    def test_sol_is_research_not_paper(self) -> None:
        """SOL (phase 2) must be research; not yet promoted to paper."""
        reg = get_asset_registry()
        sol = reg.get("SOL/USDT")
        assert sol is not None, "SOL/USDT missing from registry"
        assert sol.status == AssetStatus.RESEARCH
        assert sol.phase == 2

    def test_no_live_candidates_exist(self) -> None:
        """No asset must reach live_candidate status while live trading is disabled."""
        reg = get_asset_registry()
        live = [a.symbol for a in reg.assets if a.status == AssetStatus.LIVE_CANDIDATE]
        assert live == [], f"Unexpected live_candidates: {live}"

    def test_doge_is_experimental_and_disabled(self) -> None:
        reg = get_asset_registry()
        doge = reg.get("DOGE/USDT")
        assert doge is not None, "DOGE/USDT missing from registry"
        assert doge.experimental is True
        assert doge.status == AssetStatus.DISABLED

    def test_bnb_cap_at_most_15_pct(self) -> None:
        """BNB must have a lower cap due to Binance ecosystem concentration risk."""
        reg = get_asset_registry()
        bnb = reg.get("BNB/USDT")
        assert bnb is not None, "BNB/USDT missing from registry"
        assert bnb.max_capital_pct <= 0.15, (
            f"BNB cap {bnb.max_capital_pct:.0%} exceeds 15% ecosystem-risk ceiling"
        )

    def test_xrp_cap_at_most_15_pct(self) -> None:
        """XRP must have a lower cap due to regulatory sensitivity."""
        reg = get_asset_registry()
        xrp = reg.get("XRP/USDT")
        assert xrp is not None, "XRP/USDT missing from registry"
        assert xrp.max_capital_pct <= 0.15, (
            f"XRP cap {xrp.max_capital_pct:.0%} exceeds 15% regulatory-risk ceiling"
        )

    def test_no_asset_exceeds_50pct_cap(self) -> None:
        """Hard limit: no asset may exceed 50 % capital allocation."""
        reg = get_asset_registry()
        over = [a.symbol for a in reg.assets if a.max_capital_pct > 0.50]
        assert over == [], f"Assets exceeding 50% cap: {over}"

    def test_all_etf_assets_are_disabled(self) -> None:
        """ETFs must remain disabled until Alpaca Stage 5 integration is complete."""
        reg = get_asset_registry()
        active_etfs = [
            a.symbol
            for a in reg.assets
            if a.asset_class == AssetClass.ETF and a.status != AssetStatus.DISABLED
        ]
        assert active_etfs == [], f"ETFs not disabled: {active_etfs}"

    def test_all_etf_assets_use_alpaca_venue(self) -> None:
        reg = get_asset_registry()
        wrong_venue = [
            a.symbol
            for a in reg.assets
            if a.asset_class == AssetClass.ETF and a.venue != ExchangeId.ALPACA
        ]
        assert wrong_venue == [], f"ETFs not on Alpaca: {wrong_venue}"

    def test_phase3_and_above_not_in_paper(self) -> None:
        """Phase 3+ assets must not be promoted to paper yet."""
        reg = get_asset_registry()
        premature = [a.symbol for a in reg.assets if a.phase >= 3 and a.status == AssetStatus.PAPER]
        assert premature == [], f"Phase 3+ assets in paper: {premature}"

    def test_all_assets_have_feature_flag(self) -> None:
        """Every asset must be gated by a feature flag."""
        reg = get_asset_registry()
        missing = [a.symbol for a in reg.assets if not a.feature_flag]
        assert missing == [], f"Assets with no feature_flag: {missing}"

    def test_all_assets_have_required_history_days_gt_zero(self) -> None:
        reg = get_asset_registry()
        bad = [a.symbol for a in reg.assets if a.required_history_days < 1]
        assert bad == [], f"Assets with invalid required_history_days: {bad}"

    def test_phase1_crypto_on_binance(self) -> None:
        reg = get_asset_registry()
        for sym in ("BTC/USDT", "ETH/USDT"):
            spec = reg.get(sym)
            assert spec is not None
            assert spec.venue == ExchangeId.BINANCE
            assert spec.asset_class == AssetClass.CRYPTO
            assert spec.phase == 1

    def test_expected_etf_symbols_present(self) -> None:
        reg = get_asset_registry()
        expected = {"SPY", "QQQ", "SOXX", "IWM", "TLT", "GLD"}
        registered = {a.symbol for a in reg.assets}
        missing = expected - registered
        assert missing == set(), f"Expected ETF symbols missing: {missing}"

    def test_expected_crypto_symbols_present(self) -> None:
        reg = get_asset_registry()
        expected = {
            "BTC/USDT",
            "ETH/USDT",
            "SOL/USDT",
            "BNB/USDT",
            "XRP/USDT",
            "LINK/USDT",
            "DOGE/USDT",
        }
        registered = {a.symbol for a in reg.assets}
        missing = expected - registered
        assert missing == set(), f"Expected crypto symbols missing: {missing}"

    def test_paper_assets_have_sma_strategy(self) -> None:
        """All paper assets must have at least one enabled strategy."""
        reg = get_asset_registry()
        paper_no_strategy = [
            a.symbol for a in reg.by_status(AssetStatus.PAPER) if not a.enabled_strategies
        ]
        assert paper_no_strategy == [], f"Paper assets with no strategies: {paper_no_strategy}"
