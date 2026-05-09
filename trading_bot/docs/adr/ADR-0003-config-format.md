# ADR-0003: Configuration Format — YAML + pydantic-settings

**Status:** Accepted
**Date:** 2024-01-01
**Deciders:** Architecture team

---

## Context

The system needs a hierarchical, type-safe configuration system that:
- Supports multiple environments (development, staging, production)
- Validates schema at startup (no silent misconfiguration)
- Keeps secrets out of config files (env vars only)
- Is versionable (YAML in git, with PR review)
- Can snapshot config state for audit log and replay

---

## Decision

**YAML for non-secret configuration + pydantic-settings for validation**

Merge order: `base.yaml → {environment}.yaml → environment variables`

- YAML is human-readable, widely understood, supports comments
- pydantic-settings provides type validation, env var override, nested models
- Secrets are NEVER in YAML — only in environment variables
- Config snapshot is attached to every audit event (replay correctness)

---

## Consequences

### Positive

- Startup validation catches misconfiguration before the first trade
- Type hints on config fields prevent runtime type errors
- YAML files are diff-able in PRs (config-as-code)
- pydantic-settings auto-reads env vars (12-factor app compliance)

### Negative

- YAML is more verbose than TOML for simple configs
- Nested env var override requires `__` separator (slightly awkward)

### Risks

- YAML is sensitive to indentation — CI YAML linting is mandatory
- Config schema changes require migration path for existing deployments

---

## Alternatives Considered

| Option | Reason Rejected |
|--------|-----------------|
| TOML only | No env var override out of the box, less ecosystem support |
| JSON | No comments, no environment-specific inheritance |
| Python config files | Security risk (executable config), not auditable |
| Consul/etcd | Massive ops overhead for Stage 0 |

---

## References

- pydantic-settings: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
- 12-factor app config: https://12factor.net/config
