import unittest
from pathlib import Path
import tempfile

from resource_filter.scraper import PlaywrightSiteCrawler


class PlaywrightSiteCrawlerProfileCopyTest(unittest.TestCase):
    def test_ignore_builder_covers_large_cache_directories(self):
        crawler = PlaywrightSiteCrawler(adapter=None, api_client=None)

        ignored = {
            name
            for name in [
                "Cache",
                "Code Cache",
                "GPUCache",
                "BrowserMetrics",
                "LOCK",
                "SingletonLock",
                "Cookies",
                "Local Storage",
                "IndexedDB",
            ]
            if (
                name in crawler.PROFILE_TRANSIENT_NAMES
                or name in crawler.PROFILE_IGNORED_DIR_NAMES
                or name.endswith(".lock")
            )
        }

        self.assertIn("Cache", ignored)
        self.assertIn("Code Cache", ignored)
        self.assertIn("GPUCache", ignored)
        self.assertIn("BrowserMetrics", ignored)
        self.assertIn("LOCK", ignored)
        self.assertIn("SingletonLock", ignored)
        self.assertNotIn("Cookies", ignored)
        self.assertNotIn("Local Storage", ignored)
        self.assertNotIn("IndexedDB", ignored)

    def test_proxy_server_without_scheme_defaults_to_http(self):
        crawler = PlaywrightSiteCrawler(adapter=None, api_client=None, proxy_server="127.0.0.1:7890")

        self.assertEqual(crawler.proxy_server, "http://127.0.0.1:7890")

    def test_cdp_url_is_normalized(self):
        crawler = PlaywrightSiteCrawler(adapter=None, api_client=None, cdp_url="  http://127.0.0.1:9222  ")

        self.assertEqual(crawler.cdp_url, "http://127.0.0.1:9222")

    def test_browser_closed_error_is_detected(self):
        crawler = PlaywrightSiteCrawler(adapter=None, api_client=None)

        self.assertTrue(crawler._is_browser_closed_error(Exception("Target page, context or browser has been closed")))
        self.assertTrue(crawler._is_browser_closed_error(Exception("Target closed")))
        self.assertFalse(crawler._is_browser_closed_error(Exception("Locator.wait_for: Timeout exceeded")))

    def test_incremental_adapter_flag_is_detected(self):
        adapter = type("Adapter", (), {"collect_feed_incrementally": True})()
        crawler = PlaywrightSiteCrawler(adapter=adapter, api_client=None)

        self.assertTrue(crawler._adapter_collects_incrementally())

    def test_format_total_label_for_incremental_unknown_total(self):
        crawler = PlaywrightSiteCrawler(adapter=None, api_client=None)

        self.assertEqual(crawler._format_total_label(5, True), "?")

    def test_sync_runtime_profile_back_keeps_login_state_files(self):
        crawler = PlaywrightSiteCrawler(
            adapter=None,
            api_client=None,
            user_data_dir="",
        )

        with tempfile.TemporaryDirectory() as source_dir_raw, tempfile.TemporaryDirectory() as runtime_root_raw:
            source_dir = Path(source_dir_raw)
            runtime_dir = Path(runtime_root_raw) / "xhs_profile"
            runtime_dir.mkdir(parents=True, exist_ok=True)

            crawler.user_data_dir = str(source_dir)

            source_cookie_path = source_dir / "Default" / "Cookies"
            source_cache_path = source_dir / "Default" / "Cache" / "cache.bin"
            source_cookie_path.parent.mkdir(parents=True, exist_ok=True)
            source_cache_path.parent.mkdir(parents=True, exist_ok=True)
            source_cookie_path.write_text("old-cookie", encoding="utf-8")
            source_cache_path.write_text("source-cache", encoding="utf-8")

            runtime_cookie_path = runtime_dir / "Default" / "Cookies"
            runtime_local_storage_path = runtime_dir / "Default" / "Local Storage" / "leveldb" / "000001.log"
            runtime_indexed_db_path = runtime_dir / "Default" / "IndexedDB" / "db.leveldb" / "MANIFEST-000001"
            runtime_cache_path = runtime_dir / "Default" / "Cache" / "cache.bin"
            runtime_cookie_path.parent.mkdir(parents=True, exist_ok=True)
            runtime_local_storage_path.parent.mkdir(parents=True, exist_ok=True)
            runtime_indexed_db_path.parent.mkdir(parents=True, exist_ok=True)
            runtime_cache_path.parent.mkdir(parents=True, exist_ok=True)
            runtime_cookie_path.write_text("new-cookie", encoding="utf-8")
            runtime_local_storage_path.write_text("new-local-storage", encoding="utf-8")
            runtime_indexed_db_path.write_text("new-indexed-db", encoding="utf-8")
            runtime_cache_path.write_text("runtime-cache", encoding="utf-8")

            crawler._sync_runtime_user_data_dir_back(runtime_dir)

            self.assertEqual(source_cookie_path.read_text(encoding="utf-8"), "new-cookie")
            self.assertEqual(
                (source_dir / "Default" / "Local Storage" / "leveldb" / "000001.log").read_text(encoding="utf-8"),
                "new-local-storage",
            )
            self.assertEqual(
                (source_dir / "Default" / "IndexedDB" / "db.leveldb" / "MANIFEST-000001").read_text(encoding="utf-8"),
                "new-indexed-db",
            )
            self.assertEqual(source_cache_path.read_text(encoding="utf-8"), "source-cache")


if __name__ == "__main__":
    unittest.main()
