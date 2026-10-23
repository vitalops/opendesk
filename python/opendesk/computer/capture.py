"""Screen-capture helpers using *mss* and *Pillow*.

All functions are synchronous; run them in a thread pool when called from
async code.

Example::

    png_bytes, w, h = capture_screen()
    png_bytes, w, h = capture_screen(region=(100, 100, 800, 600))
    b64, w, h = capture_screen_b64()
    report = diff_screenshots(before_png, after_png)
"""

from __future__ import annotations

import base64
import io
import os
import platform
from typing import Any

_PLATFORM = platform.system()
_MAX_WIDTH = 1920  # downscale Retina / 4K screens to stay under API size limits


def capture_screen(
    region: tuple[int, int, int, int] | None = None,
) -> tuple[bytes, int, int]:
    """Capture a screenshot and return ``(png_bytes, width, height)``.

    Parameters
    ----------
    region:
        Optional ``(x, y, width, height)`` in *logical* screen coordinates.
        ``None`` captures the entire primary monitor.

    Raises
    ------
    ImportError
        When ``mss`` or ``Pillow`` are not installed.
    RuntimeError
        When the captured data length doesn't match expectations.  On macOS
        this usually means Screen Recording permission has not been granted
        (System Settings → Privacy & Security → Screen Recording).
    """
    try:
        from PIL import Image  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(
            "Pillow is required for screen capture: pip install 'opendesk[core]'"
        ) from exc

    # macOS fast path: the system `screencapture` tool uses ScreenCaptureKit
    # and returns in ~0.3 s, whereas mss's CGWindowListCreateImage path can
    # stall for ~30 s per grab on macOS 15+/26.  Falls back to mss on any
    # failure.  Set OPENDESK_CAPTURE=mss to force the mss path.
    if _PLATFORM == "Darwin" and os.environ.get("OPENDESK_CAPTURE", "").lower() != "mss":
        img = _macos_screencapture(region)
        if img is not None:
            return _encode(img)

    # Wayland: X11 grabbers see nothing (or only XWayland windows); use
    # grim / the xdg-desktop-portal / gnome-screenshot instead.
    if _PLATFORM == "Linux":
        from opendesk.computer import wayland
        if wayland.is_wayland():
            return _encode(wayland.capture(region))

    try:
        import mss  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(
            "mss is required for screen capture: pip install 'opendesk[core]'"
        ) from exc

    with mss.mss() as sct:
        if region is not None:
            x, y, w, h = region
            monitor: dict[str, int] = {"left": x, "top": y, "width": w, "height": h}
        else:
            monitor = dict(sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0])

        sct_img = sct.grab(monitor)

        # mss returns a memoryview — materialise to bytes before PIL decode.
        # The "BGRX" raw decoder reorders channels B→R G→G R→B correctly.
        raw_bgra = bytes(sct_img.bgra)

        expected = sct_img.width * sct_img.height * 4
        if len(raw_bgra) != expected:
            raise RuntimeError(
                f"Screen capture data size mismatch: got {len(raw_bgra)} bytes, "
                f"expected {expected} ({sct_img.width}×{sct_img.height}×4 BGRA). "
                "On macOS: grant Screen Recording permission in System Settings → "
                "Privacy & Security → Screen Recording."
            )

        img = Image.frombytes(
            "RGB",
            (sct_img.width, sct_img.height),
            raw_bgra,
            "raw",
            "BGRX",
        )

    return _encode(img)


def _encode(img: "Any") -> tuple[bytes, int, int]:
    """Downscale to ``_MAX_WIDTH`` if needed and PNG-encode."""
    from PIL import Image  # type: ignore[import-not-found]

    if img.mode != "RGB":
        img = img.convert("RGB")
    if img.width > _MAX_WIDTH:
        scale = _MAX_WIDTH / img.width
        new_h = max(1, int(img.height * scale))
        img = img.resize((_MAX_WIDTH, new_h), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    png_bytes = buf.getvalue()

    if not png_bytes:
        raise RuntimeError("PNG encoding produced empty output.")

    return png_bytes, img.width, img.height


def _macos_screencapture(
    region: tuple[int, int, int, int] | None,
) -> "Any | None":
    """Capture the main display via ``/usr/sbin/screencapture``.

    Returns a PIL image, or ``None`` when the tool is missing or fails (the
    caller then falls back to mss).  ``-x`` silences the shutter sound,
    ``-D 1`` selects the main display, ``-R`` takes logical coordinates.
    """
    import subprocess
    import tempfile

    from PIL import Image  # type: ignore[import-not-found]

    exe = "/usr/sbin/screencapture"
    if not os.path.exists(exe):
        return None
    cmd = [exe, "-x", "-D", "1", "-t", "png"]
    if region is not None:
        x, y, w, h = region
        cmd += ["-R", f"{x},{y},{w},{h}"]
    fd, tmp = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        r = subprocess.run(cmd + [tmp], capture_output=True, timeout=15)
        if r.returncode != 0 or not os.path.getsize(tmp):
            return None
        with Image.open(tmp) as im:
            im.load()
            return im.convert("RGB")
    except Exception:
        return None
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def capture_screen_b64(
    region: tuple[int, int, int, int] | None = None,
) -> tuple[str, int, int]:
    """Like :func:`capture_screen` but returns base-64 encoded PNG."""
    png_bytes, w, h = capture_screen(region)
    return base64.b64encode(png_bytes).decode("ascii"), w, h


def screen_size() -> tuple[int, int]:
    """Return ``(width, height)`` of the primary monitor in logical pixels."""
    try:
        import mss  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError("mss is required: pip install 'opendesk[core]'") from exc

    with mss.mss() as sct:
        m = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        return m["width"], m["height"]


def diff_screenshots(
    before_png: bytes,
    after_png: bytes,
    threshold: int = 10,
    *,
    min_pixels: int | None = None,
    min_density: float = 0.02,
    ignore_regions: "list[list[int]] | list[tuple[int, int, int, int]] | None" = None,
) -> dict[str, object]:
    """Compare two PNG screenshots and return a change report.

    Parameters
    ----------
    before_png, after_png:
        Raw PNG bytes from :func:`capture_screen`.
    threshold:
        Per-channel intensity delta (0–255) below which a pixel is considered
        unchanged.  Default 10 filters camera / compression noise.
    min_pixels:
        Absolute number of changed pixels required to report a change.
        Defaults to a resolution-scaled value (~41 px at 1920×1080).  A
        *fraction* of the screen is the wrong unit here: a one-glyph edit on a
        4K display changes fewer pixels, proportionally, than a speck of dust
        on a phone, yet only the edit matters.
    min_density:
        Minimum share of the changed region's bounding box that must actually
        differ.  Distinct edits are compact (a glyph, a button, a dialog), so
        their changed pixels fill their bounding box; scattered sensor speckle
        spans a large box while changing few pixels inside it and is rejected.
    ignore_regions:
        Boxes to exclude from the comparison, each ``[x, y, w, h]`` in pixels.
        Ambient churn — a ticking clock, a taskbar, a notification badge — is
        genuine pixel change, so no threshold can tell it from a real edit.
        Excluding where it lives is the only reliable fix.  Build the list from
        the accessibility tree with :func:`regions_for_roles` rather than
        hardcoding coordinates.  Regions are clamped to the image and
        degenerate ones are skipped.

    Returns
    -------
    dict with keys:
        ``changed``         — bool
        ``changed_pixels``  — pixels differing by more than ``threshold``,
                              outside any ignored region
        ``change_fraction`` — ``changed_pixels`` / total pixels, 0.0–1.0
        ``changed_region``  — ``[x, y, w, h]`` bounding box or ``None``
        ``region_area``     — area of that bounding box, or ``None``
        ``region_density``  — ``changed_pixels`` / ``region_area``, or ``None``
        ``suppressed_pixels`` — changed pixels hidden by ``ignore_regions``
        ``ignored_regions`` — the regions actually applied, after clamping
        ``summary``         — human-readable string for the LLM

    Limits
    ------
    This reports *that* pixels differ, not *whether they matter*.  A live clock
    or a moved cursor is a genuine change of a few dozen pixels and will be
    reported as one; so will a one-glyph edit.  Nothing pixel-based can tell the
    two apart — that is a semantic distinction.  Pass ``ignore_regions`` for
    churn in a known place; for churn whose *meaning* you need to judge, compare
    the accessibility tree instead.
    """
    try:
        from PIL import Image, ImageChops, ImageStat  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(
            "Pillow is required for screenshot diffing: pip install 'opendesk[core]'"
        ) from exc

    before = Image.open(io.BytesIO(before_png)).convert("RGB")
    after = Image.open(io.BytesIO(after_png)).convert("RGB")

    if before.size != after.size:
        return {
            "changed": True,
            "changed_pixels": None,
            "change_fraction": 1.0,
            "changed_region": None,
            "region_area": None,
            "region_density": None,
            "suppressed_pixels": None,
            "ignored_regions": None,
            "summary": f"Screen resolution changed from {before.size} to {after.size}.",
        }

    diff = ImageChops.difference(before, after)
    gray = diff.convert("L")
    mask = gray.point(lambda p: 255 if p > threshold else 0)

    raw_changed = int(ImageStat.Stat(mask).sum[0] / 255)
    applied: list[list[int]] = []
    for x0, y0, x1, y1 in _clamp_regions(
        ignore_regions, before.width, before.height
    ):
        mask.paste(0, (x0, y0, x1, y1))
        applied.append([x0, y0, x1 - x0, y1 - y0])

    changed_pixels = int(ImageStat.Stat(mask).sum[0] / 255)
    suppressed_pixels = raw_changed - changed_pixels
    total = before.width * before.height
    fraction = changed_pixels / total if total > 0 else 0.0

    bbox = mask.getbbox()
    changed_region = None
    region_area = None
    density = 0.0
    region_str = ""
    if bbox:
        x, y, x2, y2 = bbox
        changed_region = [x, y, x2 - x, y2 - y]
        region_area = (x2 - x) * (y2 - y)
        density = changed_pixels / region_area if region_area else 0.0
        region_str = (
            f" in region [x={x}, y={y}, {x2 - x}×{y2 - y}px, {density:.0%} dense]"
        )

    if min_pixels is None:
        min_pixels = max(24, round(total * 0.00002))

    changed = changed_pixels >= min_pixels and density >= min_density

    ignored_note = (
        f" {suppressed_pixels} px in {len(applied)} ignored region(s) were excluded."
        if applied else ""
    )
    if changed:
        summary = (
            f"{changed_pixels} px changed ({fraction:.3%} of the screen)"
            f"{region_str}.{ignored_note}"
        )
    else:
        summary = (
            f"No significant change detected ({changed_pixels} px differ, below the "
            f"{min_pixels} px threshold) — the action may not have had any effect."
            f"{ignored_note}"
        )

    return {
        "changed": changed,
        "changed_pixels": changed_pixels,
        "change_fraction": fraction,
        "changed_region": changed_region,
        "region_area": region_area,
        "region_density": density,
        "suppressed_pixels": suppressed_pixels,
        "ignored_regions": applied or None,
        "summary": summary,
    }


def _clamp_regions(
    regions: object, width: int, height: int
) -> list[tuple[int, int, int, int]]:
    """Normalise ``[x, y, w, h]`` boxes to clamped ``(x0, y0, x1, y1)`` boxes.

    Tolerant by design: a malformed or off-screen region is dropped rather than
    raising, because a bad exclusion hint should not break a comparison.
    """
    out: list[tuple[int, int, int, int]] = []
    if not regions:
        return out
    for region in regions:  # type: ignore[union-attr]
        try:
            x, y, w, h = (int(v) for v in region)  # type: ignore[misc]
        except (TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(width, x + w), min(height, y + h)
        if x1 > x0 and y1 > y0:
            out.append((x0, y0, x1, y1))
    return out


def regions_for_roles(
    root: object,
    roles: "str | list[str] | tuple[str, ...] | set[str]",
    *,
    max_count: int = 16,
) -> list[list[int]]:
    """Bounding boxes of accessibility elements whose role matches *roles*.

    The companion to ``ignore_regions``: instead of hardcoding "the clock is at
    1740,8", ask the accessibility tree where the status bar and menu bar are.
    Matching is a case-insensitive substring test against each element's
    ``role``, so ``"menu bar"`` catches ``AXMenuBar`` and ``AXMenuBarItem``.

    Returns ``[x, y, w, h]`` boxes, at most *max_count* of them, skipping
    elements with no usable geometry.  Accepts objects or dicts, so it works
    against a live tree or a deserialised one.
    """
    if isinstance(roles, str):
        wanted = [roles]
    else:
        wanted = list(roles)
    needles = [str(r).strip().lower() for r in wanted if str(r).strip()]
    if not needles:
        return []

    out: list[list[int]] = []

    def visit(node: object) -> None:
        if node is None or len(out) >= max_count:
            return
        role = str(_tree_get(node, "role", "") or "").lower()
        if role and any(n in role for n in needles):
            bounds = _tree_get(node, "bounds")
            if bounds is not None:
                w = int(_tree_get(bounds, "width", 0) or 0)
                h = int(_tree_get(bounds, "height", 0) or 0)
                if w > 0 and h > 0:
                    out.append([
                        int(_tree_get(bounds, "x", 0) or 0),
                        int(_tree_get(bounds, "y", 0) or 0),
                        w,
                        h,
                    ])
        for child in (_tree_get(node, "children", []) or []):
            visit(child)

    visit(root)
    return out


def _tree_get(node: object, key: str, default: object = None) -> object:
    if isinstance(node, dict):
        return node.get(key, default)
    return getattr(node, key, default)


# ---------------------------------------------------------------------------
# Screen fingerprints — cheap screen identity for state-transition diagnosis
# ---------------------------------------------------------------------------

_DEFAULT_HASH_SIZE = 16


def screen_fingerprint(png_bytes: bytes, hash_size: int = _DEFAULT_HASH_SIZE) -> str:
    """Return a perceptual fingerprint of a screenshot as a hex string.

    Uses a difference hash (dHash): the image is reduced to a
    ``(hash_size + 1) × hash_size`` grayscale grid and each bit records whether
    a pixel is brighter than its right-hand neighbour.

    What it is actually sensitive to
    --------------------------------
    This is a **structural** signature, and the measured behaviour is narrower
    than "changes when the interface changes".  Rendering 1920×1080 frames and
    comparing against :attr:`_DEFAULT_HASH_SIZE` = 16:

    ==========================  ==================
    change                      Hamming distance
    ==========================  ==================
    identical re-render         0
    clock ticked 1 s            0
    cursor moved                1
    one glyph edited            0
    whole page switched         0
    dialog opened               26
    light → dark theme          40
    ==========================  ==================

    So the bits track layout and overall structure.  Small *content* edits move
    it no more than a cursor does, and a thin high-contrast element (a clock)
    can move it more than a real edit.  Raising ``hash_size`` does not fix this
    — at 32 the same edits read 0–2 bits — because downscaling discards the
    detail a small edit lives in.  No global perceptual hash separates a clock
    tick from a one-glyph edit; that is a semantic distinction, not a
    perceptual one.

    Consequence: use this to answer *"is this the same functional screen?"*, not
    *"did the content change?"*.  For the latter use :func:`diff_screenshots`,
    which resolves individual pixels.  Two fingerprints of the same functional
    screen differ by a few bits, so compare with a tolerance rather than for
    equality — see :func:`fingerprint_distance`.

    Parameters
    ----------
    png_bytes:
        Raw PNG bytes, as returned by :func:`capture_screen`.
    hash_size:
        Grid size. 16 yields a 64-hex-character fingerprint (256 bits).

    Raises
    ------
    ImportError
        When Pillow is not installed.
    """
    try:
        from PIL import Image  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(
            "Pillow is required for screen fingerprints: pip install 'opendesk[core]'"
        ) from exc

    img = Image.open(io.BytesIO(png_bytes)).convert("L")
    # One extra column so every cell has a right-hand neighbour to compare with.
    img = img.resize((hash_size + 1, hash_size), Image.LANCZOS)
    # tobytes() is one byte per pixel in row-major order for "L" — the same
    # layout getdata() produced, without its deprecation.
    pixels = img.tobytes()

    bits = 0
    count = 0
    for row in range(hash_size):
        base = row * (hash_size + 1)
        for col in range(hash_size):
            bits = (bits << 1) | (
                1 if pixels[base + col] > pixels[base + col + 1] else 0
            )
            count += 1

    width = (count + 3) // 4
    return f"{bits:0{width}x}"


def fingerprint_distance(a: str | None, b: str | None) -> int:
    """Hamming distance between two fingerprints (lower = more similar).

    Returns ``0`` for identical inputs and a large sentinel (``9999``) when
    either side is missing.  Returns ``-1`` when the two cannot be usefully
    compared — different lengths (a different hash size or algorithm) or
    non-hex input — rather than reporting a distance that looks meaningful.
    """
    if not a or not b:
        return 9999
    if len(a) != len(b):
        return -1
    try:
        return (int(a, 16) ^ int(b, 16)).bit_count()
    except (ValueError, TypeError):
        return -1

