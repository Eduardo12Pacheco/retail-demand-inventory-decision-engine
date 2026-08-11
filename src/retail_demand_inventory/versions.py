"""Central version identifiers for artifacts produced by this package.

Every report, manifest, forecast, and simulation run records these identifiers
so a reader can trace a number back to the exact code and protocol that made it.
"""

from __future__ import annotations

PACKAGE_VERSION = "0.1.0"

# Version of the canonical DemandRecord / DemandTable schema.
SCHEMA_VERSION = "1.0"

# Version of docs/evaluation-protocol.md implemented by evaluation/.
PROTOCOL_VERSION = "1.0"
