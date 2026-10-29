"""Typed, versioned, freshness-aware household facts layer."""
from .models import Fact, Source, Unit
from .store import FactStore
from .freshness import (
    check_freshness, FreshnessResult, StaleFact,
    DEFAULT_FRESHNESS_DAYS, max_age_for,
)

__all__ = [
    "Fact", "Source", "Unit", "FactStore",
    "check_freshness", "FreshnessResult", "StaleFact",
    "DEFAULT_FRESHNESS_DAYS", "max_age_for",
]
