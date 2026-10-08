from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


# Query keys that do not identify the resource. utm_* is matched by prefix.
_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "gclsrc",
    "dclid",
    "gbraid",
    "wbraid",
    "msclkid",
    "mc_eid",
    "mc_cid",
    "igshid",
    "igsh",
    "twclid",
    "ttclid",
    "yclid",
    "_hsenc",
    "_hsmi",
    "mkt_tok",
    "vero_id",
    "vero_conv",
    "oly_anon_id",
    "oly_enc_id",
    "rb_clickid",
    "s_cid",
}


def _is_tracking_query_param(name: str) -> bool:
    key = (name or "").strip().lower()
    return key.startswith("utm_") or key in _TRACKING_QUERY_KEYS


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _canonical_bookmark_identity(url: str, text: str) -> str:
    """Stable identity for a bookmark.

    Keeps the query string (sorted) so distinct resources that share a path
    do not collide, but drops the fragment and well-known tracking params.
    X/Twitter status URLs still collapse to the numeric status id.
    """
    raw_url = (url or "").strip()
    raw_text = (text or "").strip()

    if raw_url:
        parts = urlsplit(raw_url)
        host = parts.netloc.lower()
        path = parts.path.rstrip("/")

        status_match = re.search(r"/(?:i/web/)?status/(\d+)$", path)
        if host in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"} and status_match:
            return f"x-status:{status_match.group(1)}"

        kept = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not _is_tracking_query_param(key)
        ]
        kept.sort()
        query = urlencode(kept, doseq=True)
        normalized_url = urlunsplit((parts.scheme.lower(), host, path, query, ""))
        return normalized_url or raw_text

    return raw_text


def stable_bookmark_id(url: str, text: str) -> str:
    identity = _canonical_bookmark_identity(url, text)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"bookmark_{digest}"


def clamp_score(value: float, lower: float = 0.0, upper: float = 10.0) -> float:
    return max(lower, min(upper, round(float(value), 2)))


def strip_json_fences(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = strip_json_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def compact_text(value: str, limit: int = 220) -> str:
    collapsed = " ".join(value.split())
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[: limit - 3].rstrip()}..."


def safe_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []
