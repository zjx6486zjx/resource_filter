from __future__ import annotations

import copy
import json
import re
import time
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from resource_filter.models import ScrapeItemPayload
from resource_filter.utils import normalize_text


class LunarsandApiRequestError(RuntimeError):
    def __init__(self, message: str, *, status_code: Optional[int] = None, detail: Optional[str] = None, url: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail
        self.url = url


class LunarsandApiClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_seconds: float = 120,
        retry_attempts: int = 0,
        retry_delay_seconds: float = 2,
    ):
        self.base_url = normalize_text(base_url).rstrip("/")
        self.api_key = normalize_text(api_key)
        self.timeout_seconds = max(float(timeout_seconds), 1)
        self.retry_attempts = max(int(retry_attempts), 0)
        self.retry_delay_seconds = max(float(retry_delay_seconds), 0)
        if not self.base_url:
            raise ValueError("LUNARSAND_API_BASE 不能为空")

    def import_item(self, payload: ScrapeItemPayload) -> Dict[str, Any]:
        request_bodies = self._build_import_request_bodies(payload)
        last_source_error: LunarsandApiRequestError | None = None

        for index, request_body in enumerate(request_bodies):
            try:
                return self._import_request_body(request_body)
            except LunarsandApiRequestError as exc:
                if self._should_retry_source_image_download(exc) and index + 1 < len(request_bodies):
                    last_source_error = exc
                    self._print_source_image_retry(request_bodies[index + 1])
                    continue
                raise

        if last_source_error is not None:
            raise last_source_error
        raise RuntimeError("未找到可用的 Lunarsand 导入接口")

    def _import_request_body(self, request_body: Dict[str, Any]) -> Dict[str, Any]:
        last_error: Exception | None = None
        attempted_urls: list[str] = []

        for index, url in enumerate(self._build_import_urls(), start=1):
            attempted_urls.append(url)
            try:
                return self._request_url(url=url, method="POST", body=request_body)
            except LunarsandApiRequestError as exc:
                last_error = exc
                if not self._should_retry_import(exc):
                    raise
                if index == 1:
                    print(f"导入接口已迁移，尝试兼容新路径：{exc}")
                continue

        if last_error is not None:
            if isinstance(last_error, LunarsandApiRequestError):
                raise self._format_import_endpoint_error(last_error, attempted_urls) from last_error
            raise last_error
        raise RuntimeError("未找到可用的 Lunarsand 导入接口")

    def _build_import_request_bodies(self, payload: ScrapeItemPayload) -> list[Dict[str, Any]]:
        base_body = payload.to_api_dict(include_source_image_data=False)
        request_bodies = [base_body]
        original_url = normalize_text(payload.source_image_url)

        for candidate_url in self._midjourney_source_image_candidates(original_url):
            request_bodies.append(self._replace_request_source_image_url(base_body, candidate_url, previous_url=original_url))

        if normalize_text(payload.source_image_data_url):
            data_body = payload.to_api_dict(include_source_image_data=True)
            raw_payload = data_body.get("raw_payload")
            if isinstance(raw_payload, dict):
                raw_payload["source_image_transfer_mode"] = "browser_data_url"
            request_bodies.append(data_body)

        return request_bodies

    def _replace_request_source_image_url(
        self,
        request_body: Dict[str, Any],
        source_image_url: str,
        *,
        previous_url: str,
    ) -> Dict[str, Any]:
        updated = copy.deepcopy(request_body)
        updated["source_image_url"] = source_image_url
        raw_payload = updated.get("raw_payload")
        if isinstance(raw_payload, dict):
            raw_payload["source_image_url_retry_from"] = previous_url
            raw_payload["source_image_url_retry_to"] = source_image_url
            detail_payload = raw_payload.get("detail")
            if isinstance(detail_payload, dict):
                detail_payload["source_image_url"] = source_image_url
                detail_payload["source_image_url_retry_from"] = previous_url
        return updated

    def _midjourney_source_image_candidates(self, source_image_url: str) -> list[str]:
        normalized_url = normalize_text(source_image_url)
        if not normalized_url:
            return []

        parsed = urlsplit(normalized_url)
        if parsed.netloc.lower() != "cdn.midjourney.com":
            return []
        if parsed.path.lower().startswith("/video/"):
            return []

        match = re.match(
            r"^(?P<directory>/[0-9a-fA-F-]{32,}/)(?P<variant>\d+_\d+)(?:_\d+_N)?\.(?P<extension>jpe?g|png|webp)$",
            parsed.path,
            re.IGNORECASE,
        )
        if not match:
            return []

        original_clean_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        original_extension = match.group("extension").lower()
        extension_order = [extension for extension in ("jpeg", "png", "webp", "jpg") if extension != original_extension]

        candidates: list[str] = []
        variant = match.group("variant")
        for extension in extension_order:
            candidate = urlunsplit(
                (
                    parsed.scheme,
                    parsed.netloc,
                    f"{match.group('directory')}{variant}.{extension}",
                    "",
                    "",
                )
            )
            if candidate != original_clean_url and candidate not in candidates:
                candidates.append(candidate)
        return candidates

    def _should_retry_source_image_download(self, exc: LunarsandApiRequestError) -> bool:
        if exc.status_code != 502:
            return False
        detail = f"{normalize_text(exc.detail)} {normalize_text(str(exc))}"
        return "下载源图片失败" in detail and ("HTTP 404" in detail or "HTTP 403" in detail)

    def _print_source_image_retry(self, next_body: Dict[str, Any]) -> None:
        if normalize_text(next_body.get("source_image_data_url")):
            print("后端下载源图片失败，改用浏览器已加载图片数据提交。", flush=True)
            return
        next_url = normalize_text(next_body.get("source_image_url"))
        if next_url:
            print(f"后端下载源图片失败，尝试备用 Midjourney 图片地址：{next_url}", flush=True)

    def _build_import_urls(self) -> list[str]:
        base = self.base_url.rstrip("/")
        parsed = urlparse(base)
        origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else base
        base_path = parsed.path.rstrip("/")
        candidates: list[str] = []
        seen: set[str] = set()

        def add(url: str) -> None:
            normalized = normalize_text(url).rstrip("/")
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            candidates.append(normalized)

        if base_path.endswith("/api/v1/gallery") or base_path.endswith("/lunarsand-api/v1/gallery"):
            add(f"{base}/scrape-items/import")
        elif base_path.endswith("/api/v1") or base_path.endswith("/lunarsand-api/v1"):
            add(f"{base}/gallery/scrape-items/import")
            add(f"{base}/scrape-items/import")
        elif base_path.endswith("/api"):
            add(f"{base}/v1/gallery/scrape-items/import")
            add(f"{base}/v1/scrape-items/import")
            add(f"{base}/gallery/scrape-items/import")
            add(f"{base}/scrape-items/import")
        elif base_path.endswith("/lunarsand-api"):
            add(f"{base}/v1/gallery/scrape-items/import")
            add(f"{base}/v1/scrape-items/import")
            add(f"{base}/gallery/scrape-items/import")
            add(f"{base}/scrape-items/import")
            add(f"{origin}/api/v1/gallery/scrape-items/import")
            add(f"{origin}/api/v1/scrape-items/import")
            add(f"{origin}/api/gallery/scrape-items/import")
            add(f"{origin}/api/scrape-items/import")
        else:
            if base_path:
                add(f"{base}/v1/gallery/scrape-items/import")
                add(f"{base}/v1/scrape-items/import")
                add(f"{base}/gallery/scrape-items/import")
                add(f"{base}/scrape-items/import")
            add(f"{origin}/api/v1/gallery/scrape-items/import")
            add(f"{origin}/api/v1/scrape-items/import")
            add(f"{origin}/api/gallery/scrape-items/import")
            add(f"{origin}/api/scrape-items/import")
            add(f"{origin}/lunarsand-api/v1/gallery/scrape-items/import")
            add(f"{origin}/lunarsand-api/v1/scrape-items/import")
            add(f"{origin}/lunarsand-api/gallery/scrape-items/import")
            add(f"{origin}/lunarsand-api/scrape-items/import")

        return candidates

    def _format_import_endpoint_error(
        self,
        exc: LunarsandApiRequestError,
        attempted_urls: list[str],
    ) -> LunarsandApiRequestError:
        attempted = ", ".join(attempted_urls)
        detail = normalize_text(exc.detail)
        nginx_hint = ""
        if exc.status_code == 404 and "nginx" in detail.lower():
            nginx_hint = (
                "；所有候选都返回 nginx 404 时，通常是 LUNARSAND_API_BASE 指到了未接入后端的域名/IP，"
                "或 Nginx 没有把 /api 转发到 Lunarsand 后端。请改成实际可访问的后端地址，"
                "例如本机后端常见为 http://127.0.0.1:8000/api，生产环境应使用已配置反代的域名。"
            )
        message = f"{exc}；已尝试导入接口：{attempted}{nginx_hint}"
        return LunarsandApiRequestError(
            message,
            status_code=exc.status_code,
            detail=exc.detail,
            url=exc.url,
        )

    def _should_retry_import(self, exc: LunarsandApiRequestError) -> bool:
        status_code = exc.status_code or 0
        if status_code in {404, 405, 410}:
            return True
        detail = normalize_text(exc.detail).lower()
        if status_code == 503 and "legacy" in detail and "导入接口" in detail:
            return True
        return "旧图库 api" in detail or "/api/v1/gallery" in detail or "已下线" in detail

    def _request(self, path: str, method: str = "GET", body: Dict[str, Any] | None = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        return self._request_url(url=url, method=method, body=body)

    def _request_url(self, url: str, method: str = "GET", body: Dict[str, Any] | None = None) -> Dict[str, Any]:
        encoded_body = None
        headers: Dict[str, str] = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if body is not None:
            encoded_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(url=url, data=encoded_body, headers=headers, method=method.upper())
        last_error: Exception | None = None
        for attempt in range(self.retry_attempts + 1):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="ignore")
                detail_preview = detail if len(detail) <= 500 else f"{detail[:500]}..."
                size_hint = ""
                if exc.code == 413:
                    size_hint = "；请求体过大，如已启用浏览器图片数据兜底，请调大后端/Nginx 的上传体积限制"
                raise LunarsandApiRequestError(
                    f"Lunarsand API 请求失败：HTTP {exc.code} url={url} {detail_preview}{size_hint}",
                    status_code=exc.code,
                    detail=detail,
                    url=url,
                ) from exc
            except URLError as exc:
                last_error = exc
                if attempt < self.retry_attempts:
                    self._sleep_before_retry(attempt, exc)
                    continue
                raise RuntimeError("Lunarsand API 不可达，请确认后端已启动") from exc
            except OSError as exc:
                last_error = exc
                if attempt < self.retry_attempts:
                    self._sleep_before_retry(attempt, exc)
                    continue
                raise RuntimeError(f"Lunarsand API 连接被重置或中断：{exc}") from exc
        else:
            raise RuntimeError(f"Lunarsand API 请求失败：{last_error}")

        if payload.get("code") != 0:
            raise RuntimeError(payload.get("message") or "Lunarsand API 返回错误")
        return payload.get("data") or {}

    def _sleep_before_retry(self, attempt: int, exc: Exception) -> None:
        delay = self.retry_delay_seconds * (attempt + 1)
        if delay > 0:
            print(f"Lunarsand API 连接异常，{delay:.1f}s 后重试：{exc}", flush=True)
            time.sleep(delay)
