"""
Semantic data resolution contracts (spec sections 71-76).

simsland_mw/data/resolver.py::Resolver/Resolution and data/registry.py::
Registry ALREADY implement this: dependency-waved, concurrently-resolved,
per-(character,type) TTL-cached named semantic types, with a failing
provider recorded rather than sinking the whole decision (see resolver.py's
own module docstring -- it already cites "spec section 7.2"). These
dataclasses are the canonical external shape; DataRequest/DataResponse are
thin, real adapters over the existing (types, Resolution) pair rather than
a second resolution engine -- see simsland_mw/data/resolver.py's
`as_data_response()` helper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class DataRequest:
    character_id: str
    types: Tuple[str, ...]
    tick: int
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DataResolutionError:
    type_id: str
    provider_id: Optional[str]
    code: str
    message: str
    retryable: bool = False


# Codes (spec section 74)
DATA_RESOLUTION_ERROR_CODES = (
    "NOT_FOUND", "UNAUTHORIZED", "TIMEOUT", "UPSTREAM_ERROR",
    "INVALID_RESPONSE", "UNSUPPORTED_TYPE", "DEPENDENCY_FAILED",
)


@dataclass(frozen=True)
class DataResponse:
    character_id: str
    tick: int
    data: Dict[str, Any]
    missing_types: Tuple[str, ...] = ()
    errors: Tuple[DataResolutionError, ...] = ()


@dataclass(frozen=True)
class ProviderDefinition:
    provider_id: str
    supported_types: Tuple[str, ...]
    dependencies: Tuple[str, ...] = ()
    timeout_ms: int = 5000
    cache_ttl_ticks: int = 0
    authoritative: bool = True
