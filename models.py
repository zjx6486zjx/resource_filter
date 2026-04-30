from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class AuthorPayload:
    uid: Optional[str] = None
    name: Optional[str] = None
    url: Optional[str] = None
    avatar_url: Optional[str] = None

    def to_api_dict(self) -> Dict[str, Any]:
        return {
            "uid": self.uid,
            "name": self.name,
            "url": self.url,
            "avatar_url": self.avatar_url,
        }


@dataclass
class FeedCardRef:
    index: int
    preview_image_url: Optional[str] = None
    author_name: Optional[str] = None
    like_count: Optional[int] = None
    detail_url: Optional[str] = None
    title: Optional[str] = None
    author_url: Optional[str] = None
    publish_time: Optional[str] = None
    tab_name: Optional[str] = None
    external_item_id: Optional[str] = None
    raw_payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScrapeItemPayload:
    site_name: str
    source_image_url: str
    source_image_data_url: Optional[str] = None
    source_image_filename: Optional[str] = None
    source_image_content_type: Optional[str] = None
    detail_url: Optional[str] = None
    prompt_text: Optional[str] = None
    like_count: Optional[int] = None
    external_item_id: Optional[str] = None
    author: Optional[AuthorPayload] = None
    raw_payload: Dict[str, Any] = field(default_factory=dict)

    def to_api_dict(self, *, include_source_image_data: bool = True) -> Dict[str, Any]:
        payload = {
            "site_name": self.site_name,
            "external_item_id": self.external_item_id,
            "detail_url": self.detail_url,
            "source_image_url": self.source_image_url,
            "prompt_text": self.prompt_text,
            "like_count": self.like_count,
            "author": self.author.to_api_dict() if self.author else None,
            "raw_payload": self.raw_payload or None,
        }
        if include_source_image_data:
            payload.update(
                {
                    "source_image_data_url": self.source_image_data_url,
                    "source_image_filename": self.source_image_filename,
                    "source_image_content_type": self.source_image_content_type,
                }
            )
        return {key: value for key, value in payload.items() if value is not None}
