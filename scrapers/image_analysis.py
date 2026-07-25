"""Image analysis: EXIF (Pillow) + Claude-vision reading of product imagery.

Runs on image URLs already collected by the e-commerce channel (the runner gathers them
and passes them in ``params['image_urls']``). Extracts EXIF metadata and, when an
Anthropic key is present, uses Claude vision to read packaging text, on-pack claims, and
visible prices. Never fabricates: if vision or download fails it is logged.
"""
from __future__ import annotations

import base64
from typing import Any, Callable, Dict, List, Optional

from scrapers.base import ScrapeResult

CHANNEL = "image_analysis"

_VISION_PROMPT = (
    "You are reading a product image for market research. Report ONLY what is visibly "
    "present. Return concise findings for: brand/product name on pack, on-pack claims "
    "(e.g. 'sugar-free', 'no preservatives'), any visible price, pack size/format, and "
    "language(s) of the packaging text. If something is not visible, say 'not visible'. "
    "Do not guess."
)


def _default_fetch(url: str):
    from http_client import get_session

    return get_session().get(url)


def read_exif(image_bytes: bytes) -> Dict[str, Any]:
    try:
        import io

        from PIL import ExifTags, Image

        img = Image.open(io.BytesIO(image_bytes))
        exif = img.getexif()
        out: Dict[str, Any] = {"format": img.format, "size": list(img.size)}
        for tag_id, value in (exif or {}).items():
            tag = ExifTags.TAGS.get(tag_id, str(tag_id))
            out[tag] = str(value)[:200]
        return out
    except Exception as exc:
        return {"exif_error": str(exc)}


def _vision_read(image_bytes: bytes, media_type: str, model: str, api_key: str) -> str:
    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    b64 = base64.standard_b64encode(image_bytes).decode("ascii")
    msg = client.messages.create(
        model=model,
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": _VISION_PROMPT},
            ],
        }],
    )
    return "".join(block.text for block in msg.content if getattr(block, "type", "") == "text")


def collect(cfg: Dict[str, Any], params: Optional[Dict[str, Any]] = None,
            *, fetch_fn: Optional[Callable[[str], Any]] = None) -> ScrapeResult:
    from settings import settings

    params = params or {}
    fetch = fetch_fn or _default_fetch
    result = ScrapeResult(CHANNEL)

    image_urls: List[str] = params.get("image_urls", [])
    if not image_urls:
        result.error("No image URLs supplied — run the e-commerce channel first to collect images.")
        return result

    api_key = settings.anthropic_api_key
    model = settings.vision_model
    max_images = int(params.get("max_images", 20))

    for url in image_urls[:max_images]:
        try:
            resp = fetch(url)
            if getattr(resp, "status_code", 200) >= 400:
                result.error(f"Image download {url} -> HTTP {resp.status_code}")
                continue
            content = getattr(resp, "content", b"") or b""
            media_type = getattr(resp, "headers", {}).get("content-type", "image/jpeg").split(";")[0]
        except Exception as exc:
            result.error(f"Image download failed ({url}): {exc}")
            continue

        exif = read_exif(content)
        vision_text = ""
        if api_key:
            try:
                vision_text = _vision_read(content, media_type, model, api_key)
            except Exception as exc:
                result.error(f"Claude vision failed ({url}): {exc}")
        else:
            result.error("ANTHROPIC_API_KEY not set — EXIF captured but vision reading skipped.")

        result.add(
            {
                "title": f"Image analysis: {url.split('/')[-1][:60]}",
                "text": vision_text or "(EXIF only — no vision reading)",
                "link": url,
                "published": exif.get("DateTimeOriginal", ""),
                "extra": {"type": "image_analysis", "exif": exif, "vision_model": model if vision_text else None},
            }
        )
    return result
