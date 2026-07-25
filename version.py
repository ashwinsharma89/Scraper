"""Single source of truth for the MarketLens version.

The version is shown in the UI footer and stamped into every Excel export so that
any client-facing report is traceable to the exact tool build that produced it.
"""

__version__ = "0.1.0"

# Schema version is managed independently by migrations.py (PRAGMA user_version).
# Bumping __version__ does NOT require a schema migration and vice-versa.
