from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def normalize_base_url(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def optional_text(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def parse_datetime(value: Any) -> Optional[datetime]:
    raw = optional_text(value)
    if not raw:
        return None
    normalized = raw.replace(" ", "T")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def request_json(
    *,
    base_url: str,
    path: str,
    api_key: str,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    url = f"{normalize_base_url(base_url)}{path}"
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
    }
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url=url, headers=headers, data=body, method=method.upper())
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_queue_items(
    *,
    source_base: str,
    api_key: str,
    statuses: Iterable[str],
    page_size: int,
) -> List[Dict[str, Any]]:
    normalized_statuses = [str(status).strip().lower() for status in statuses if str(status).strip()]
    page = 1
    items: List[Dict[str, Any]] = []

    while True:
        query = urlencode(
            [("page", str(page)), ("page_size", str(page_size))]
            + [("statuses", status) for status in normalized_statuses]
        )
        response = request_json(
            base_url=source_base,
            path=f"/review/queue?{query}",
            api_key=api_key,
        )
        if response.get("code") != 0:
            raise RuntimeError(response.get("message") or "读取源审核池失败")

        data = response.get("data") or {}
        page_items = data.get("items") or []
        items.extend(page_items)
        total_pages = int(data.get("total_pages") or 0)
        if page >= total_pages or not page_items:
            break
        page += 1

    return items


def build_import_payload(item: Dict[str, Any]) -> Dict[str, Any]:
    author = item.get("author") or {}
    return {
        "site_name": item.get("site_name"),
        "external_item_id": item.get("external_item_id"),
        "detail_url": item.get("detail_url"),
        "source_image_url": item.get("source_image_url"),
        "prompt_text": item.get("prompt_text"),
        "like_count": item.get("like_count"),
        "author": {
            "uid": author.get("uid"),
            "name": author.get("name"),
            "url": author.get("url"),
            "avatar_url": author.get("avatar_url"),
        }
        if author
        else None,
        "raw_payload": item.get("raw_payload"),
    }


def filter_items(
    items: Iterable[Dict[str, Any]],
    *,
    site_name: Optional[str],
    created_after: Optional[datetime],
) -> List[Dict[str, Any]]:
    normalized_site = optional_text(site_name)
    filtered: List[Dict[str, Any]] = []
    for item in items:
        if normalized_site and optional_text(item.get("site_name")) != normalized_site:
            continue
        if created_after is not None:
            item_created_at = parse_datetime(item.get("created_at"))
            if item_created_at is None or item_created_at < created_after:
                continue
        filtered.append(item)
    return filtered


def migrate_items(
    *,
    source_base: str,
    target_base: str,
    api_key: str,
    statuses: Iterable[str],
    page_size: int,
    site_name: Optional[str],
    created_after: Optional[datetime],
    dry_run: bool,
) -> int:
    source_items = fetch_queue_items(
        source_base=source_base,
        api_key=api_key,
        statuses=statuses,
        page_size=page_size,
    )
    filtered_items = filter_items(
        source_items,
        site_name=site_name,
        created_after=created_after,
    )

    print(
        f"源审核池共读取 {len(source_items)} 条，过滤后待迁移 {len(filtered_items)} 条；"
        f" source={normalize_base_url(source_base)} -> target={normalize_base_url(target_base)}"
    )

    if dry_run:
        for item in filtered_items[:20]:
            print(
                f"DRY-RUN item_id={item.get('id')} site={item.get('site_name')} "
                f"created_at={item.get('created_at')} detail={item.get('detail_url')}"
            )
        return 0

    created_count = 0
    reused_count = 0
    failed_count = 0
    for index, item in enumerate(filtered_items, start=1):
        payload = build_import_payload(item)
        try:
            response = request_json(
                base_url=target_base,
                path="/scrape-items/import",
                api_key=api_key,
                method="POST",
                payload=payload,
            )
            if response.get("code") != 0:
                raise RuntimeError(response.get("message") or "导入失败")
            data = response.get("data") or {}
            target_id = data.get("id")
            created = bool(data.get("created", False))
            storage_reused = bool(data.get("storage_reused", False))
            if created:
                created_count += 1
            else:
                reused_count += 1
            print(
                f"[{index}/{len(filtered_items)}] migrated source_id={item.get('id')} "
                f"-> target_id={target_id} created={created} storage_reused={storage_reused}"
            )
        except Exception as exc:
            failed_count += 1
            print(f"[{index}/{len(filtered_items)}] failed source_id={item.get('id')} err={exc}")

    print(
        f"迁移完成：created={created_count}, reused={reused_count}, failed={failed_count}, total={len(filtered_items)}"
    )
    return 0 if failed_count == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="把旧审核池的抓取项迁移到新的审核池")
    parser.add_argument("--source-base", required=True, help="源审核池 API base，例如 http://host/lunarsand-api")
    parser.add_argument("--target-base", required=True, help="目标审核池 API base，例如 http://host/api")
    parser.add_argument("--api-key", required=True, help="图库 API Key")
    parser.add_argument("--site-name", default="", help="可选：只迁移某个站点，例如 jimeng")
    parser.add_argument("--created-after", default="", help="可选：只迁移不早于该时间的记录，例如 2026-04-20 或 2026-04-20T21:40:00")
    parser.add_argument("--page-size", type=int, default=100, help="源审核池分页大小")
    parser.add_argument("--dry-run", action="store_true", help="只打印待迁移记录，不执行写入")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    created_after = parse_datetime(args.created_after) if optional_text(args.created_after) else None
    return migrate_items(
        source_base=args.source_base,
        target_base=args.target_base,
        api_key=args.api_key,
        statuses=("pending", "deferred"),
        page_size=max(1, int(args.page_size)),
        site_name=optional_text(args.site_name),
        created_after=created_after,
        dry_run=bool(args.dry_run),
    )


if __name__ == "__main__":
    raise SystemExit(main())
