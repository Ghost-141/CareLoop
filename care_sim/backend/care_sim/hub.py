"""Per-case CareLoop service construction; no application state is shared."""
from __future__ import annotations

from pathlib import Path

from care_loop.core import CareLoopService
from care_loop.storage import CareLoopStorage

from .config import FixedClock


def create_service(database: Path, clock: FixedClock) -> CareLoopService:
    return CareLoopService(CareLoopStorage(database, clock=clock), clock=clock)
