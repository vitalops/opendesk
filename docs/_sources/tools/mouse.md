# `mouse` — Mouse Control

```python
from opendesk.tools.mouse import MouseTool
tool = MouseTool()
```

**Always provide `image_width` and `image_height` from the screenshot tool.** This ensures correct coordinate translation on Retina / HiDPI displays.

Prefer the [`ui` tool](ui.md) whenever the target has an accessible label — it
is faster, exact, and never moves the cursor.

## Actions

| Action | Parameters | Description |
|--------|-----------|-------------|
| `click` | `x, y` | Left-click |
| `double_click` | `x, y` | Double left-click |
| `triple_click` | `x, y` | Triple-click (select word/line) |
| `right_click` | `x, y` | Right-click |
| `middle_click` | `x, y` | Middle-click (open link in new tab) |
| `move` | `x, y` | Move without clicking |
| `scroll` | `x, y, direction, amount` | Scroll up/down/left/right |
| `drag` | `x, y, end_x, end_y` | Click-and-drag |
| `left_down` | `x, y` | Press and hold left button |
| `left_up` | `x, y` | Release left button |
| `cursor_position` | — | Return current cursor location |

## Background clicks

`background=true` (click actions only, macOS) clicks **without moving the
user's cursor or activating the app**:

1. The accessible element under the point is found
   (`AXUIElementCopyElementAtPosition`). If it — or the button around a label —
   supports `AXPress`, it is pressed through accessibility.
2. Otherwise the click is posted straight to the owning process with
   `CGEvent.postToPid`.

Step 2 is best-effort: many apps ignore synthetic clicks while inactive or on
another Space. Step 1 is reliable for buttons, checkboxes, links, menu items
and tabs.

```python
await tool.execute(ctx, params(action="click", x=400, y=300, background=True,
                               image_width=w, image_height=h))
```

Set `OPENDESK_BACKGROUND=1` to make background the default for every click.
In that mode `move`, `drag`, `scroll`, `left_down` and `left_up` are refused
with an error pointing the agent at `ui get_tree` + `ui click ref=...`, so a
long-running agent can share the machine with a person.

## Ask Claude

> "Click the Save button"

> "Right-click on the Desktop"

> "Scroll down on the page"

> "Drag the window from the left side to the right"

> "Where is the cursor right now?"

Claude will take a screenshot first to get the dimensions, then click the right spot automatically.

---

## SDK examples

```python
params = MouseTool.Params

# Always get screenshot dimensions first
shot = await registry.get("screenshot").execute(ctx, ScreenshotTool.Params())
w = shot.metadata["width"]
h = shot.metadata["height"]

# Click at image coordinates (auto-scaled to logical coords)
await tool.execute(ctx, params(action="click", x=400, y=300, image_width=w, image_height=h))

# Scroll down
await tool.execute(ctx, params(action="scroll", x=760, y=400, direction="down", amount=5,
                               image_width=w, image_height=h))

# Drag
await tool.execute(ctx, params(action="drag", x=100, y=100, end_x=500, end_y=300,
                               image_width=w, image_height=h))
```

## Wayland

On Linux Wayland sessions (`WAYLAND_DISPLAY` set) X11 input tools can't reach
native windows, so pointer and keyboard input go through
[`ydotool`](https://github.com/ReimuNotMoe/ydotool) v1.0+:

```bash
sudo apt install ydotool          # or build from source
systemctl --user enable --now ydotool   # or: sudo ydotoold
sudo usermod -aG input "$USER"    # access to /dev/uinput (log out and back in)
```

Without it, input fails with these instructions. Screenshots on Wayland use
`grim` (Sway, Hyprland and other wlroots compositors), the xdg-desktop-portal
Screenshot API via `gdbus` (GNOME, KDE), or `gnome-screenshot`, in that order.
Set `OPENDESK_FORCE_X11=1` to use the X11 path under XWayland instead.

---

Next: [keyboard →](keyboard.md)
