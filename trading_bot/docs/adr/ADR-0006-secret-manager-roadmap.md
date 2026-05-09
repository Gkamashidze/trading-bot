# ADR-0006: Secret Manager Roadmap — .env dev → Vault prod

**Status:** Accepted
**Date:** 2024-01-01
**Deciders:** Architecture team

---

## Context

API keys and credentials are the most sensitive assets in the system.
A leaked API key with trade permissions can drain the entire account.
A leaked API key with withdrawal permissions can permanently lose funds.

The secret management strategy must evolve with the system's production readiness:
- Stage 0-4 (dev/paper): simple .env is acceptable (no real money)
- Stage 5+ (live trading): .env is unacceptable — requires proper secret management

---

## Decision

**Three-phase migration:**

### Phase 1 (Stage 0-4): .env file
- `.env` is in `.gitignore` — never committed
- `python-dotenv` loads at startup
- `verify_environment.py` checks all required vars at startup
- `detect-secrets` pre-commit hook prevents accidental secret commit

### Phase 2 (Stage 5): Doppler or AWS Secrets Manager
- Replace `.env` with Doppler for production (simpler than Vault)
- Secrets injected as environment variables by Doppler agent
- Rotation supported natively

### Phase 3 (Stage 7+): HashiCorp Vault
- Full audit trail per secret access
- Fine-grained policies (CI can read, trader can't rotate, etc.)
- Dynamic secrets (Vault generates Postgres credentials on-demand)
- Migration guide documented before cutover

**API Key Segregation (mandatory from Stage 0):**
- Read-only key: market data, balance queries (no trade, no withdraw)
- Trade-only key: order submission (no withdraw, no account management)
- Withdraw-enabled key: NEVER in the bot — operator holds this key offline

---

## Consequences

### Positive

- No real money at risk until Phase 2 (Stage 5)
- Secret rotation policy is documented before it's needed
- Key segregation limits blast radius of any key compromise

### Negative

- Phase 1 is not acceptable for production — must migrate before live trading
- Three separate API keys requires three separate exchange key configurations

### Risks

- Key leaked before Phase 2: revoke immediately, rotate all keys
- Vault upgrade path: document migration procedure before Phase 2 is needed
- Withdrawal key: must be stored in hardware wallet or offline — NEVER in code

---

## Alternatives Considered

| Option | Reason Rejected |
|--------|-----------------|
| Vault from Stage 0 | Massive ops overhead for dev environment |
| AWS Parameter Store | AWS lock-in; Vault is cloud-agnostic |
| Kubernetes secrets | Requires Kubernetes (Stage 7+) |
| Encrypted .env | False security — still file-based, no rotation, no audit |

---

## References

- HashiCorp Vault: https://www.vaultproject.io/
- Doppler: https://www.doppler.com/
- Binance API key permissions: https://www.binance.com/en/support/faq/api
