import unittest
from pathlib import Path
import tempfile
import json
import os
import time
from unittest.mock import Mock
from src.currency_converter import CurrencyConverter

class TestCurrencyConverter(unittest.TestCase):
    def setUp(self):
        self.fallback_rates = {
            "USD": 7.2,
            "HKD": 0.9,
            "TWD": 0.22,
        }

    def test_convert_to_cny_with_fallback(self):
        # Test basic conversion using fallback rates (since API call is mocked or skipped)
        # We can bypass online fetch by using a converter with a valid cache
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "rates.json"
            
            # Save mock cache
            cache_data = {
                "fetched_at": time.time(),
                "base": "CNY",
                "rates": {
                    "USD": 7.25,
                    "HKD": 0.93,
                    "CNY": 1.0
                }
            }
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f)
                
            converter = CurrencyConverter(
                fallback_rates=self.fallback_rates,
                cache_path=cache_file,
                cache_ttl_hours=1.0
            )
            
            self.assertEqual(converter.convert_to_cny(100, "USD"), 725.0)
            self.assertEqual(converter.convert_to_cny(100, "HKD"), 93.0)
            self.assertEqual(converter.convert_to_cny(100, "CNY"), 100.0)
            self.assertEqual(converter.convert_to_cny(100, "TWD"), 22.0) # falls back to fallback_rates

    def test_cache_expiration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "rates.json"
            
            # Expired cache (2 hours ago, TTL is 1 hour)
            cache_data = {
                "fetched_at": time.time() - 7200,
                "base": "CNY",
                "rates": {
                    "USD": 7.5,
                }
            }
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f)
            # Backdate the file modification time by 2 hours (7200 seconds)
            now = time.time()
            os.utime(cache_file, (now - 7200, now - 7200))
                
            converter = CurrencyConverter(
                fallback_rates=self.fallback_rates,
                cache_path=cache_file,
                cache_ttl_hours=1.0
            )
            
            # Since online API fetch will run and might fail/succeed, let's mock it
            # or verify that it doesn't crash.
            # To avoid real API requests during unit tests, we mock _fetch_online_rates
            converter._fetch_online_rates = lambda: {"USD": 7.15, "CNY": 1.0}
            
            self.assertEqual(converter.convert_to_cny(100, "USD"), 715.0)
            # Check cache got updated
            self.assertTrue(cache_file.exists())
            with open(cache_file, encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["rates"]["USD"], 7.15)

    def test_offline_mode_uses_expired_cache_without_network(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "rates.json"
            cache_file.write_text(
                json.dumps({"rates": {"USD": 7.1, "CNY": 1.0}}),
                encoding="utf-8",
            )
            old = time.time() - 7200
            os.utime(cache_file, (old, old))
            converter = CurrencyConverter(
                fallback_rates=self.fallback_rates,
                cache_path=cache_file,
                cache_ttl_hours=1.0,
                allow_online=False,
            )
            converter._fetch_online_rates = Mock()

            self.assertEqual(converter.convert_to_cny(1, "USD"), 7.1)
            converter._fetch_online_rates.assert_not_called()
