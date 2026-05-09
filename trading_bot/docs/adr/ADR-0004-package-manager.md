# ADR-0004: Package Manager — uv

**Status:** Accepted
**Date:** 2024-01-01
**Deciders:** Architecture team

---

## Context

Python package management is critical for reproducibility. The system requires:
- Deterministic dependency resolution (same packages across all environments)
- Fast installs (CI speed matters)
- Lock file support (uv.lock committed to git)
- Python version management
- Support for extras/optional dependencies (dev, research)

---

## Decision

**uv** (by Astral, the makers of ruff)

uv provides:
- 10-100× faster installs than pip
- Deterministic uv.lock file (committed to git)
- Drop-in pip compatibility
- Built-in Python version management
- Workspace support (future monorepo)
- Written in Rust — native Apple Silicon M4 performance

---

## Consequences

### Positive

- Dramatically faster CI (installs in seconds, not minutes)
- uv.lock guarantees exact same environment in dev, CI, and production
- No virtual env management complexity — uv handles it
- pyproject.toml is the single source of truth

### Negative

- uv is newer (2024) — some edge cases still being ironed out
- Team must use `uv run` instead of `python` for reproducibility

### Risks

- uv project could be abandoned (low risk — backed by Astral, strong adoption)
- uv.lock format is not pip-compatible (cannot `pip install -r uv.lock`)

---

## Alternatives Considered

| Option | Reason Rejected |
|--------|-----------------|
| pip + pip-tools | Slow, verbose lock files, no Python version management |
| poetry | Slower than uv, complex config, occasional resolver issues |
| conda | Too heavy, overkill for pure Python, not Apple Silicon native |
| pdm | Smaller community, less battle-tested |

---

## References

- uv: https://docs.astral.sh/uv/
- uv lock format: https://docs.astral.sh/uv/concepts/resolution/
