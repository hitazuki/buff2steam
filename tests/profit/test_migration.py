import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from steam_skin_ops.profit.migration import migrate_legacy_cache


class ProfitCacheMigrationTestCase(unittest.TestCase):
    def test_copies_known_files_without_overwrite_or_delete(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "data"
            target = legacy / "profit"
            legacy.mkdir()
            source = legacy / "steam_sales.json"
            source.write_text('[{"legacy": true}]', encoding="utf-8")
            target.mkdir()
            destination = target / "steam_sales.json"
            destination.write_text('[{"new": true}]', encoding="utf-8")

            copied = migrate_legacy_cache(target, legacy)

            self.assertEqual(copied, [])
            self.assertTrue(source.exists())
            self.assertEqual(destination.read_text(encoding="utf-8"), '[{"new": true}]')

    def test_migration_is_idempotent(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "data"
            target = legacy / "profit"
            legacy.mkdir()
            (legacy / "buff_csgo_orders.json").write_text("[]", encoding="utf-8")

            first = migrate_legacy_cache(target, legacy)
            second = migrate_legacy_cache(target, legacy)

            self.assertEqual(len(first), 1)
            self.assertEqual(second, [])
