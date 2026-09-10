"""Parse semantic hints from WeChat type-47 emoji XML."""
from __future__ import annotations

import html
import base64
import re
import xml.etree.ElementTree as ET


_HINT_FIELDS = ("desc", "attachedtext", "meaning", "name", "title")
_META_WORDS = {"default", "zh_cn", "zh_tw", "en", "cn", "tw"}


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data) and shift < 70:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
    raise ValueError("invalid protobuf varint")


def _protobuf_strings(data: bytes, depth: int = 0) -> list[str]:
    """Extract UTF-8 strings from an unknown, nested protobuf payload."""
    if depth > 5:
        return []
    values: list[str] = []
    offset = 0
    try:
        while offset < len(data):
            key, offset = _read_varint(data, offset)
            wire = key & 7
            if wire == 0:
                _, offset = _read_varint(data, offset)
            elif wire == 1:
                offset += 8
            elif wire == 5:
                offset += 4
            elif wire == 2:
                size, offset = _read_varint(data, offset)
                part = data[offset:offset + size]
                offset += size
                if len(part) != size:
                    break
                try:
                    text = part.decode("utf-8")
                    if text and all(ch.isprintable() for ch in text):
                        values.append(text)
                except UnicodeDecodeError:
                    pass
                values.extend(_protobuf_strings(part, depth + 1))
            else:
                break
    except (ValueError, IndexError):
        pass
    return values


def decode_emoji_hint(value: str) -> str:
    """Decode direct text or WeChat's Base64 protobuf localized caption."""
    value = html.unescape(value or "").strip()
    if not value:
        return ""
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error):
        return value
    candidates = [item.strip() for item in _protobuf_strings(raw)]
    candidates = [item for item in candidates if item.lower() not in _META_WORDS]
    semantic = [item for item in candidates if re.search(r"[\u4e00-\u9fff]", item)]
    if not semantic:
        semantic = [item for item in candidates if len(item) <= 32]
    return max(semantic, key=len, default="")


def parse_emoji_metadata(content: str | bytes | None) -> dict:
    """Return non-secret identity/meaning fields from a type-47 payload.

    CDN URLs, AES keys and auth tokens are deliberately not returned.
    """
    if not content:
        return {"hint": "", "hint_source": "", "md5": "", "product_id": ""}
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="ignore")
    try:
        root = ET.fromstring(content.strip())
    except ET.ParseError:
        return {"hint": "", "hint_source": "", "md5": "", "product_id": ""}
    emoji = root if root.tag == "emoji" else root.find(".//emoji")
    if emoji is None:
        return {"hint": "", "hint_source": "", "md5": "", "product_id": ""}
    attrs = emoji.attrib
    hint = ""
    source = ""
    for field in _HINT_FIELDS:
        value = decode_emoji_hint(attrs.get(field, ""))
        if value:
            hint, source = value, field
            break
    return {
        "hint": hint,
        "hint_source": source,
        "md5": attrs.get("md5", "").lower(),
        "product_id": attrs.get("productid", ""),
        "width": attrs.get("width", ""),
        "height": attrs.get("height", ""),
    }
