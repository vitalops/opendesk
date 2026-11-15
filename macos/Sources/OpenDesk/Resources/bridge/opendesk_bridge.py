#!/usr/bin/env python3
"""OpenDesk Swift <-> Python bridge.

The macOS app calls this script once per tool invocation. It reads a JSON
request from stdin and writes one JSON response to stdout. Stays small and
synchronous so it's predictable from Swift's `Process` API.

Request shape:
  { "tool": "screenshot", "params": {"marks": true} }

Response shape (success):
  { "ok": true, "result": <tool result>, "image_b64": "<base64 png>" }

Response shape (failure):
  { "ok": false, "error": "<message>", "kind": "<exception class>" }
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import sys
import traceback
from typing import Any


def _ensure_path() -> None:
    """Allow Swift to point at a checked-out opendesk source tree via env."""
    import os
    extra = os.environ.get("OPENDESK_SOURCE")
    if extra and extra not in sys.path:
        sys.path.insert(0, extra)


def _to_jsonable(value: Any) -> Any:
    """Coerce opendesk result objects into plain JSON."""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _extract_image(result: Any) -> str | None:
    """If result contains a PNG image, return it base64-encoded."""
    img = None
    if hasattr(result, "image"):
        img = result.image
    elif isinstance(result, dict) and "image" in result:
        img = result["image"]
    if img is None:
        return None
    try:
        if hasattr(img, "save"):
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("ascii")
        if isinstance(img, (bytes, bytearray)):
            return base64.b64encode(bytes(img)).decode("ascii")
        if isinstance(img, str):
            return img
    except Exception:
        return None
    return None


async def _dispatch(tool: str, params: dict) -> dict:
    from opendesk import create_registry, allow_all_context

    registry = create_registry()
    ctx = allow_all_context()
    spec = registry.get(tool)
    if spec is None:
        raise ValueError(f"Unknown tool: {tool}")

    parsed = spec.Params(**params)
    raw = await spec.execute(ctx, parsed)
    image_b64 = _extract_image(raw)
    payload = _to_jsonable(raw)
    # Don't ship raw PIL image bytes inside the JSON result.
    if isinstance(payload, dict) and "image" in payload:
        payload["image"] = "<png omitted; see image_b64>"
    return {"ok": True, "result": payload, "image_b64": image_b64}


def main() -> None:
    _ensure_path()
    try:
        raw = sys.stdin.read()
        req = json.loads(raw) if raw.strip() else {}
        tool = req.get("tool")
        params = req.get("params") or {}
        if not tool:
            raise ValueError("missing 'tool' in request")
        resp = asyncio.run(_dispatch(tool, params))
    except Exception as e:
        resp = {
            "ok": False,
            "error": str(e),
            "kind": type(e).__name__,
            "trace": traceback.format_exc(limit=4),
        }
    sys.stdout.write(json.dumps(resp))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
