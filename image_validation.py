from __future__ import annotations

import base64
from dataclasses import dataclass
import re
import struct
from typing import Optional
from urllib.parse import urlparse, urlsplit, urlunsplit

from resource_filter.utils import normalize_text


MIN_IMAGE_WIDTH = 300
MIN_IMAGE_HEIGHT = 300
MAX_IMAGE_BYTES_TO_INSPECT = 12 * 1024 * 1024


@dataclass(frozen=True)
class ImageValidationResult:
    ok: bool
    reason: str = ""
    width: Optional[int] = None
    height: Optional[int] = None


def validate_image_bytes(image_bytes: bytes, *, min_width: int = MIN_IMAGE_WIDTH, min_height: int = MIN_IMAGE_HEIGHT) -> ImageValidationResult:
    size = read_image_size(image_bytes)
    if size is None:
        return ImageValidationResult(ok=False, reason="无法识别图片尺寸")

    width, height = size
    if width < min_width or height < min_height:
        return ImageValidationResult(ok=False, reason=f"图片尺寸过小：{width}x{height}", width=width, height=height)

    return ImageValidationResult(ok=True, width=width, height=height)


def validate_data_image_url(data_url: str) -> ImageValidationResult:
    normalized = normalize_text(data_url)
    header, separator, payload = normalized.partition(",")
    if not separator or ";base64" not in header.lower():
        return ImageValidationResult(ok=False, reason="data 图片不是 base64 格式")
    try:
        image_bytes = base64.b64decode(payload, validate=True)
    except Exception:
        return ImageValidationResult(ok=False, reason="data 图片解码失败")
    return validate_image_bytes(image_bytes)


def read_image_size(image_bytes: bytes) -> Optional[tuple[int, int]]:
    if len(image_bytes) < 10:
        return None
    return (
        _read_png_size(image_bytes)
        or _read_jpeg_size(image_bytes)
        or _read_webp_size(image_bytes)
        or _read_gif_size(image_bytes)
    )


def looks_like_thumbnail_url(image_url: Optional[str]) -> bool:
    normalized = normalize_text(image_url).lower()
    if not normalized:
        return False

    parsed = urlparse(normalized)
    path = parsed.path or normalized
    if any(token in normalized for token in ("thumbnail", "thumb", "avatar", "placeholder", "loading.png")):
        return True

    if "cdn.midjourney.com" in parsed.netloc and "_n.webp" in path:
        return True

    if any(token in path for token in ("s160x160_", "s240x240_", "100x100", "160x160", "240x240")):
        return True

    return False


def promoted_image_url_candidates(image_url: Optional[str]) -> list[str]:
    normalized = normalize_text(image_url)
    if not normalized or not normalized.startswith(("http://", "https://")):
        return []

    candidates: list[str] = []

    def add(candidate: Optional[str]) -> None:
        if candidate and candidate != normalized and candidate not in candidates:
            candidates.append(candidate)

    parsed = urlsplit(normalized)
    path = parsed.path
    netloc = parsed.netloc.lower()
    path_lower = path.lower()

    if "cdn.midjourney.com" in netloc:
        match = re.match(r"(?P<prefix>.+)_\d+_N\.webp$", path, re.IGNORECASE)
        if match:
            add(urlunsplit((parsed.scheme, parsed.netloc, f"{match.group('prefix')}.jpeg", "", "")))
            add(urlunsplit((parsed.scheme, parsed.netloc, f"{match.group('prefix')}.png", "", "")))
            add(urlunsplit((parsed.scheme, parsed.netloc, f"{match.group('prefix')}.webp", "", "")))
            add(urlunsplit((parsed.scheme, parsed.netloc, f"{match.group('prefix')}.jpg", "", "")))

    if "alicdn.com" in netloc:
        clean_path = re.sub(r"(?i)(\.(?:jpg|jpeg|png|webp))(?:_[^/?#]*)+$", r"\1", path)
        add(urlunsplit((parsed.scheme, parsed.netloc, clean_path, parsed.query, parsed.fragment)))
        add(urlunsplit((parsed.scheme, parsed.netloc, clean_path, "", "")))

    if "360buyimg.com" in netloc:
        clean_path = re.sub(r"![^/?#]+$", "", path)
        add(urlunsplit((parsed.scheme, parsed.netloc, clean_path, parsed.query, parsed.fragment)))
        add(urlunsplit((parsed.scheme, parsed.netloc, clean_path, "", "")))
        match = re.search(r"/(?:mobilecms/)?s\d+x\d+_(?P<jfs>jfs/.+)$", clean_path)
        if match:
            jfs_path = f"/n0/{match.group('jfs')}"
            add(urlunsplit(("https", "img14.360buyimg.com", jfs_path, "", "")))
            add(urlunsplit(("https", "img10.360buyimg.com", jfs_path, "", "")))

    if "xhscdn.com" in netloc and "!" in path:
        clean_path = path.split("!", 1)[0]
        add(urlunsplit((parsed.scheme, parsed.netloc, clean_path, parsed.query, parsed.fragment)))

    if path_lower.endswith((".jpg", ".jpeg", ".png", ".webp")):
        clean_path = re.sub(
            r"(?i)([_-](?:thumb|thumbnail|small|middle|large|mw|fw|resize)[_-]?\d*x?\d*|[_-]\d{2,4}x\d{2,4})(?=\.(?:jpg|jpeg|png|webp)$)",
            "",
            path,
        )
        add(urlunsplit((parsed.scheme, parsed.netloc, clean_path, parsed.query, parsed.fragment)))

    return candidates


def _read_png_size(image_bytes: bytes) -> Optional[tuple[int, int]]:
    if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n") or len(image_bytes) < 24:
        return None
    return struct.unpack(">II", image_bytes[16:24])


def _read_gif_size(image_bytes: bytes) -> Optional[tuple[int, int]]:
    if not image_bytes.startswith((b"GIF87a", b"GIF89a")) or len(image_bytes) < 10:
        return None
    return struct.unpack("<HH", image_bytes[6:10])


def _read_jpeg_size(image_bytes: bytes) -> Optional[tuple[int, int]]:
    if not image_bytes.startswith(b"\xff\xd8"):
        return None

    index = 2
    while index + 9 < len(image_bytes):
        if image_bytes[index] != 0xFF:
            index += 1
            continue
        while index < len(image_bytes) and image_bytes[index] == 0xFF:
            index += 1
        if index >= len(image_bytes):
            return None

        marker = image_bytes[index]
        index += 1
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(image_bytes):
            return None

        segment_length = struct.unpack(">H", image_bytes[index:index + 2])[0]
        if segment_length < 2 or index + segment_length > len(image_bytes):
            return None

        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if segment_length < 7:
                return None
            height = struct.unpack(">H", image_bytes[index + 3:index + 5])[0]
            width = struct.unpack(">H", image_bytes[index + 5:index + 7])[0]
            return width, height

        index += segment_length
    return None


def _read_webp_size(image_bytes: bytes) -> Optional[tuple[int, int]]:
    if len(image_bytes) < 30 or not image_bytes.startswith(b"RIFF") or image_bytes[8:12] != b"WEBP":
        return None

    chunk_type = image_bytes[12:16]
    if chunk_type == b"VP8X" and len(image_bytes) >= 30:
        width = int.from_bytes(image_bytes[24:27], "little") + 1
        height = int.from_bytes(image_bytes[27:30], "little") + 1
        return width, height

    if chunk_type == b"VP8L" and len(image_bytes) >= 25:
        bits = int.from_bytes(image_bytes[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height

    if chunk_type == b"VP8 " and len(image_bytes) >= 30:
        start = image_bytes.find(b"\x9d\x01\x2a", 20)
        if start == -1 or start + 7 > len(image_bytes):
            return None
        width = struct.unpack("<H", image_bytes[start + 3:start + 5])[0] & 0x3FFF
        height = struct.unpack("<H", image_bytes[start + 5:start + 7])[0] & 0x3FFF
        return width, height

    return None
