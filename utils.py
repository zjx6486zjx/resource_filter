from __future__ import annotations

import hashlib
import re
from typing import Optional


def normalize_text(value: Optional[str]) -> str:
    return str(value or "").strip()


def normalize_optional_text(value: Optional[str]) -> Optional[str]:
    normalized = normalize_text(value)
    return normalized or None


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_count(value: Optional[str]) -> Optional[int]:
    raw = normalize_text(value).replace(",", "")
    if not raw:
        return None

    match = re.match(r"^(?P<number>\d+(?:\.\d+)?)(?P<unit>[万wW]?)$", raw)
    if not match:
        digits_only = re.sub(r"[^\d]", "", raw)
        return int(digits_only) if digits_only else None

    number = float(match.group("number"))
    unit = match.group("unit").lower()
    if unit in {"万", "w"}:
        return int(number * 10000)
    return int(number)
