from __future__ import annotations

import argparse
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from resource_filter.tools.migrate_review_queue import (
    fetch_queue_items,
    filter_items,
    normalize_base_url,
    optional_text,
    parse_datetime,
    request_json,
)


def build_match_key(item: Dict[str, Any]) -> Tuple[str, str, str]:
    return (
        optional_text(item.get("site_name")) or "",
        optional_text(item.get("external_item_id")) or "",
        optional_text(item.get("detail_url")) or "",
    )


def build_target_lookup(items: Sequence[Dict[str, Any]]) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    lookup: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for item in items:
        key = build_match_key(item)
        if key == ("", "", ""):
            continue
        lookup[key] = item
    return lookup


def load_filtered_items(
    *,
    base_url: str,
    api_key: str,
    statuses: Sequence[str],
    page_size: int,
    site_name: Optional[str],
    created_after: Optional[datetime],
) -> List[Dict[str, Any]]:
    source_items = fetch_queue_items(
        source_base=base_url,
        api_key=api_key,
        statuses=statuses,
        page_size=page_size,
    )
    return filter_items(
        source_items,
        site_name=site_name,
        created_after=created_after,
    )


def cleanup_items(
    *,
    source_base: str,
    target_base: str,
    api_key: str,
    statuses: Sequence[str],
    page_size: int,
    site_name: Optional[str],
    created_after: Optional[datetime],
    require_target_match: bool,
    dry_run: bool,
) -> int:
    source_items = load_filtered_items(
        base_url=source_base,
        api_key=api_key,
        statuses=statuses,
        page_size=page_size,
        site_name=site_name,
        created_after=created_after,
    )
    target_items = load_filtered_items(
        base_url=target_base,
        api_key=api_key,
        statuses=statuses,
        page_size=page_size,
        site_name=site_name,
        created_after=created_after,
    )
    target_lookup = build_target_lookup(target_items)

    matched_items: List[Dict[str, Any]] = []
    unmatched_items: List[Dict[str, Any]] = []
    for item in source_items:
        if build_match_key(item) in target_lookup:
            matched_items.append(item)
        else:
            unmatched_items.append(item)

    print(
        f"旧审核池匹配到 {len(source_items)} 条，"
        f"新审核池匹配到 {len(target_items)} 条，"
        f"可删除 {len(matched_items)} 条，未匹配 {len(unmatched_items)} 条；"
        f" source={normalize_base_url(source_base)} target={normalize_base_url(target_base)}"
    )

    if unmatched_items:
        for item in unmatched_items[:20]:
            print(
                f"UNMATCHED source_id={item.get('id')} site={item.get('site_name')} "
                f"external_item_id={item.get('external_item_id')} detail={item.get('detail_url')}"
            )
        if require_target_match and not dry_run:
            print("存在未在新审核池找到匹配项的记录，已停止删除。")
            return 1

    if dry_run:
        for item in matched_items[:20]:
            target_item = target_lookup.get(build_match_key(item)) or {}
            print(
                f"DRY-RUN delete source_id={item.get('id')} -> target_id={target_item.get('id')} "
                f"detail={item.get('detail_url')}"
            )
        return 0

    deleted_count = 0
    failed_count = 0
    for index, item in enumerate(matched_items, start=1):
        try:
            response = request_json(
                base_url=source_base,
                path=f"/review/{int(item['id'])}",
                api_key=api_key,
                method="DELETE",
            )
            if response.get("code") != 0:
                raise RuntimeError(response.get("message") or "删除失败")
            deleted_count += 1
            print(
                f"[{index}/{len(matched_items)}] deleted source_id={item.get('id')} "
                f"detail={item.get('detail_url')}"
            )
        except Exception as exc:
            failed_count += 1
            print(f"[{index}/{len(matched_items)}] failed source_id={item.get('id')} err={exc}")

    print(f"清理完成：deleted={deleted_count}, failed={failed_count}, total={len(matched_items)}")
    return 0 if failed_count == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="清理误同步到旧审核池的抓取项")
    parser.add_argument("--source-base", required=True, help="旧审核池 API base，例如 http://host/lunarsand-api")
    parser.add_argument("--target-base", required=True, help="正确审核池 API base，例如 http://host/api")
    parser.add_argument("--api-key", required=True, help="图库 API Key")
    parser.add_argument("--site-name", default="", help="可选：只清理某个站点，例如 jimeng")
    parser.add_argument("--created-after", default="", help="可选：只清理不早于该时间的记录，例如 2026-04-20")
    parser.add_argument("--page-size", type=int, default=100, help="分页大小")
    parser.add_argument("--dry-run", action="store_true", help="只打印待删除记录，不执行删除")
    parser.add_argument(
        "--allow-unmatched",
        action="store_true",
        help="允许存在未在新审核池匹配到的旧记录时继续删除；默认会中止，避免误删",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    created_after = parse_datetime(args.created_after) if optional_text(args.created_after) else None
    return cleanup_items(
        source_base=args.source_base,
        target_base=args.target_base,
        api_key=args.api_key,
        statuses=("pending", "deferred"),
        page_size=max(1, int(args.page_size)),
        site_name=optional_text(args.site_name),
        created_after=created_after,
        require_target_match=not bool(args.allow_unmatched),
        dry_run=bool(args.dry_run),
    )


if __name__ == "__main__":
    raise SystemExit(main())
