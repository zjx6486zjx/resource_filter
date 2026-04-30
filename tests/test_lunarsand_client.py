from __future__ import annotations

import unittest
from unittest import mock

from resource_filter.lunarsand_client import LunarsandApiClient, LunarsandApiRequestError
from resource_filter.models import ScrapeItemPayload


class LunarsandApiClientTests(unittest.TestCase):
    def test_init_allows_empty_api_key(self) -> None:
        client = LunarsandApiClient(base_url="http://127.0.0.1:8000/lunarsand-api", api_key="")
        self.assertEqual(client.api_key, "")

    def test_build_import_urls_covers_legacy_and_v1_candidates(self) -> None:
        client = LunarsandApiClient(base_url="http://127.0.0.1:8000/lunarsand-api", api_key="")

        urls = client._build_import_urls()

        self.assertIn("http://127.0.0.1:8000/lunarsand-api/scrape-items/import", urls)
        self.assertIn("http://127.0.0.1:8000/lunarsand-api/v1/gallery/scrape-items/import", urls)
        self.assertIn("http://127.0.0.1:8000/api/v1/gallery/scrape-items/import", urls)

    def test_build_import_urls_prefers_v1_gallery_for_api_base(self) -> None:
        client = LunarsandApiClient(base_url="http://120.26.238.116/api", api_key="secret")

        urls = client._build_import_urls()

        self.assertEqual(urls[0], "http://120.26.238.116/api/v1/gallery/scrape-items/import")
        self.assertIn("http://120.26.238.116/api/scrape-items/import", urls)

    def test_import_item_retries_on_legacy_410(self) -> None:
        client = LunarsandApiClient(base_url="http://127.0.0.1:8000/lunarsand-api", api_key="")
        item = ScrapeItemPayload(site_name="pose", source_image_url="https://example.com/a.png")
        attempts: list[str] = []

        def fake_request(*, url: str, method: str = "GET", body=None):
            attempts.append(url)
            if len(attempts) == 1:
                raise LunarsandApiRequestError(
                    "Lunarsand API 请求失败：HTTP 410",
                    status_code=410,
                    detail='{"detail":"旧图库 API /api/scrape-items/import 已下线，请迁移到 /api/v1/gallery"}',
                    url=url,
                )
            return {"created": True, "id": 123}

        with mock.patch.object(client, "_request_url", side_effect=fake_request):
            result = client.import_item(item)

        self.assertEqual(result["id"], 123)
        self.assertGreaterEqual(len(attempts), 2)
        self.assertEqual(attempts[0], "http://127.0.0.1:8000/lunarsand-api/v1/gallery/scrape-items/import")

    def test_import_item_retries_on_disabled_legacy_503(self) -> None:
        client = LunarsandApiClient(base_url="http://120.26.238.116/api", api_key="secret")
        item = ScrapeItemPayload(site_name="pose", source_image_url="https://example.com/a.png")
        attempts: list[str] = []

        def fake_request(*, url: str, method: str = "GET", body=None):
            attempts.append(url)
            if len(attempts) == 1:
                raise LunarsandApiRequestError(
                    "Lunarsand API 请求失败：HTTP 503",
                    status_code=503,
                    detail='{"detail":"Legacy 导入接口未启用，请先配置 API_KEY"}',
                    url=url,
                )
            return {"created": True, "id": 456}

        with mock.patch.object(client, "_request_url", side_effect=fake_request):
            result = client.import_item(item)

        self.assertEqual(result["id"], 456)
        self.assertEqual(attempts[0], "http://120.26.238.116/api/v1/gallery/scrape-items/import")
        self.assertEqual(attempts[1], "http://120.26.238.116/api/v1/scrape-items/import")

    def test_import_item_reports_all_attempted_urls_for_nginx_404(self) -> None:
        client = LunarsandApiClient(base_url="http://120.26.238.116/api", api_key="secret")
        item = ScrapeItemPayload(site_name="jimeng", source_image_url="https://example.com/a.png")

        def fake_request(*, url: str, method: str = "GET", body=None):
            raise LunarsandApiRequestError(
                f"Lunarsand API 请求失败：HTTP 404 url={url} <html><center>nginx</center></html>",
                status_code=404,
                detail="<html><center>nginx</center></html>",
                url=url,
            )

        with mock.patch.object(client, "_request_url", side_effect=fake_request):
            with self.assertRaises(LunarsandApiRequestError) as ctx:
                client.import_item(item)

        message = str(ctx.exception)
        self.assertIn("已尝试导入接口", message)
        self.assertIn("http://120.26.238.116/api/v1/gallery/scrape-items/import", message)
        self.assertIn("http://120.26.238.116/api/scrape-items/import", message)
        self.assertIn("LUNARSAND_API_BASE", message)

    def test_import_item_retries_midjourney_source_candidates_on_backend_download_404(self) -> None:
        client = LunarsandApiClient(base_url="https://app.lunarsand.art/api", api_key="secret")
        item = ScrapeItemPayload(
            site_name="mj",
            source_image_url="https://cdn.midjourney.com/a0de1c47-d3b5-4501-87ff-834eb8ef6a96/0_0.jpeg",
            detail_url="https://www.midjourney.com/jobs/a0de1c47-d3b5-4501-87ff-834eb8ef6a96?index=0",
            raw_payload={"detail": {"source_image_url": "https://cdn.midjourney.com/a0de1c47-d3b5-4501-87ff-834eb8ef6a96/0_0.jpeg"}},
        )
        attempted_image_urls: list[str] = []

        def fake_request(*, url: str, method: str = "GET", body=None):
            attempted_image_urls.append(body["source_image_url"])
            if len(attempted_image_urls) == 1:
                raise LunarsandApiRequestError(
                    "Lunarsand API 请求失败：HTTP 502",
                    status_code=502,
                    detail='{"detail":"下载源图片失败：HTTP 404"}',
                    url=url,
                )
            return {"created": True, "id": 321}

        with mock.patch.object(client, "_request_url", side_effect=fake_request):
            result = client.import_item(item)

        self.assertEqual(result["id"], 321)
        self.assertEqual(
            attempted_image_urls[:2],
            [
                "https://cdn.midjourney.com/a0de1c47-d3b5-4501-87ff-834eb8ef6a96/0_0.jpeg",
                "https://cdn.midjourney.com/a0de1c47-d3b5-4501-87ff-834eb8ef6a96/0_0.png",
            ],
        )

    def test_import_item_uses_browser_data_url_after_midjourney_candidates_fail(self) -> None:
        client = LunarsandApiClient(base_url="https://app.lunarsand.art/api", api_key="secret")
        item = ScrapeItemPayload(
            site_name="mj",
            source_image_url="https://cdn.midjourney.com/a0de1c47-d3b5-4501-87ff-834eb8ef6a96/0_0.jpeg",
            source_image_data_url="data:image/jpeg;base64,/9j/4AAQSkZJRg==",
            source_image_filename="a0de1c47-d3b5-4501-87ff-834eb8ef6a96.jpg",
            source_image_content_type="image/jpeg",
        )
        data_url_attempted = False

        def fake_request(*, url: str, method: str = "GET", body=None):
            nonlocal data_url_attempted
            if body.get("source_image_data_url"):
                data_url_attempted = True
                return {"created": True, "id": 654}
            raise LunarsandApiRequestError(
                "Lunarsand API 请求失败：HTTP 502",
                status_code=502,
                detail='{"detail":"下载源图片失败：HTTP 404"}',
                url=url,
            )

        with mock.patch.object(client, "_request_url", side_effect=fake_request):
            result = client.import_item(item)

        self.assertEqual(result["id"], 654)
        self.assertTrue(data_url_attempted)

    def test_request_url_uses_configured_timeout(self) -> None:
        client = LunarsandApiClient(base_url="http://127.0.0.1:8000/api", api_key="", timeout_seconds=88)

        with mock.patch("resource_filter.lunarsand_client.urlopen", return_value=_FakeResponse()) as mocked_urlopen:
            result = client._request_url(url="http://127.0.0.1:8000/api/demo", body={"ok": True})

        self.assertEqual(result["id"], 789)
        self.assertEqual(mocked_urlopen.call_args.kwargs["timeout"], 88)

    def test_request_url_retries_os_errors(self) -> None:
        client = LunarsandApiClient(
            base_url="http://127.0.0.1:8000/api",
            api_key="",
            timeout_seconds=88,
            retry_attempts=1,
            retry_delay_seconds=0.1,
        )

        with mock.patch(
            "resource_filter.lunarsand_client.urlopen",
            side_effect=[OSError("timed out"), _FakeResponse()],
        ) as mocked_urlopen:
            with mock.patch("resource_filter.lunarsand_client.time.sleep") as mocked_sleep:
                result = client._request_url(url="http://127.0.0.1:8000/api/demo", body={"ok": True})

        self.assertEqual(result["id"], 789)
        self.assertEqual(mocked_urlopen.call_count, 2)
        mocked_sleep.assert_called_once_with(0.1)

    def test_request_url_does_not_retry_by_default(self) -> None:
        client = LunarsandApiClient(base_url="http://127.0.0.1:8000/api", api_key="", timeout_seconds=88)

        with mock.patch("resource_filter.lunarsand_client.urlopen", side_effect=OSError("timed out")) as mocked_urlopen:
            with mock.patch("resource_filter.lunarsand_client.time.sleep") as mocked_sleep:
                with self.assertRaisesRegex(RuntimeError, "连接被重置或中断"):
                    client._request_url(url="http://127.0.0.1:8000/api/demo", body={"ok": True})

        self.assertEqual(mocked_urlopen.call_count, 1)
        mocked_sleep.assert_not_called()


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return b'{"code": 0, "data": {"created": true, "id": 789}}'


if __name__ == "__main__":
    unittest.main()
