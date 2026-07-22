from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATION_MARKER = ".legacy-cache-copied-v3"
LEGACY_FIXED_FILES = (
    "c5_buy_orders.json",
    "steam_sales.json",
    "exchange_rates.json",
)


def migrate_legacy_cache(target_dir: Path, legacy_dir: Path = Path("data")) -> list[Path]:
    """Copy known v2 profit caches once without overwriting or deleting source data."""
    target_dir = Path(target_dir)
    legacy_dir = Path(legacy_dir)
    marker = target_dir / MIGRATION_MARKER
    if marker.exists() or target_dir.resolve() == legacy_dir.resolve():
        return []

    target_dir.mkdir(parents=True, exist_ok=True)
    candidates = [legacy_dir / name for name in LEGACY_FIXED_FILES]
    candidates.extend(sorted(legacy_dir.glob("buff_*_orders.json")))
    copied: list[Path] = []
    for source in candidates:
        destination = target_dir / source.name
        if source.is_file() and not destination.exists():
            shutil.copy2(source, destination)
            copied.append(destination)
            logger.info("已安全复制旧收益缓存：%s → %s", source, destination)
    marker.write_text("v3\n", encoding="utf-8")
    return copied
