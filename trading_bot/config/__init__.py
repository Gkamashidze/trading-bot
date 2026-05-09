"""Hierarchical configuration system.

Merge order (later wins):
  base.yaml → {environment}.yaml → environment variables

Secrets are ONLY accepted via environment variables — never in YAML.
Config schema is validated on startup via pydantic-settings.
A config snapshot is attached to every audit log event for replay correctness.
"""

from trading_bot.config.settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
