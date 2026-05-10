"""Tests for Feature #15: Compliance Boundary Declarations."""

from __future__ import annotations

from trading_bot.compliance.declarations import (
    ComplianceDeclaration,
    DeclarationCategory,
    get_compliance_declarations,
    get_declaration_by_id,
    get_declarations_requiring_ack,
)


class TestGetComplianceDeclarations:
    def test_returns_non_empty_list(self) -> None:
        decls = get_compliance_declarations()
        assert len(decls) > 0

    def test_filter_by_legal_category(self) -> None:
        legal = get_compliance_declarations(category=DeclarationCategory.LEGAL)
        assert all(d.category == DeclarationCategory.LEGAL for d in legal)
        assert len(legal) > 0

    def test_filter_by_operational_category(self) -> None:
        ops = get_compliance_declarations(category=DeclarationCategory.OPERATIONAL)
        assert len(ops) > 0

    def test_filter_by_data_retention(self) -> None:
        dr = get_compliance_declarations(category=DeclarationCategory.DATA_RETENTION)
        assert len(dr) > 0

    def test_filter_by_regulatory(self) -> None:
        reg = get_compliance_declarations(category=DeclarationCategory.REGULATORY)
        assert len(reg) > 0

    def test_all_declarations_have_unique_ids(self) -> None:
        decls = get_compliance_declarations()
        ids = [d.declaration_id for d in decls]
        assert len(ids) == len(set(ids))

    def test_all_declarations_have_non_empty_body(self) -> None:
        for d in get_compliance_declarations():
            assert d.body.strip() != "", f"{d.declaration_id} has empty body"

    def test_all_declarations_have_title(self) -> None:
        for d in get_compliance_declarations():
            assert d.title.strip() != "", f"{d.declaration_id} has no title"


class TestGetDeclarationById:
    def test_known_id_returns_declaration(self) -> None:
        d = get_declaration_by_id("LEGAL-001")
        assert d is not None
        assert d.declaration_id == "LEGAL-001"

    def test_unknown_id_returns_none(self) -> None:
        d = get_declaration_by_id("NONEXISTENT-999")
        assert d is None

    def test_proprietary_trading_declaration_exists(self) -> None:
        d = get_declaration_by_id("LEGAL-001")
        assert d is not None
        assert "capital" in d.body.lower() or "own" in d.body.lower()

    def test_data_retention_declaration_exists(self) -> None:
        d = get_declaration_by_id("DATA-001")
        assert d is not None
        assert "7" in d.body or "seven" in d.body.lower()


class TestDeclarationsRequiringAck:
    def test_returns_non_empty_list(self) -> None:
        ack_decls = get_declarations_requiring_ack()
        assert len(ack_decls) > 0

    def test_all_have_requires_operator_ack_true(self) -> None:
        for d in get_declarations_requiring_ack():
            assert d.requires_operator_ack is True

    def test_legal_declarations_require_ack(self) -> None:
        ack_decls = get_declarations_requiring_ack()
        legal_ack = [d for d in ack_decls if d.category == DeclarationCategory.LEGAL]
        assert len(legal_ack) > 0


class TestComplianceDeclarationModel:
    def test_frozen_dataclass_immutable(self) -> None:
        d = ComplianceDeclaration(
            declaration_id="TEST-001",
            category=DeclarationCategory.LEGAL,
            title="Test",
            body="Test body",
        )
        import pytest

        with pytest.raises((AttributeError, TypeError)):
            d.title = "Modified"  # type: ignore[misc]

    def test_default_version(self) -> None:
        d = ComplianceDeclaration(
            declaration_id="TEST-002",
            category=DeclarationCategory.OPERATIONAL,
            title="T",
            body="B",
        )
        assert d.version == "1.0"
