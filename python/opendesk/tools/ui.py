"""UITool — accessibility-tree based UI interaction via the active
:class:`~opendesk.computer.Computer`.

Prefer this tool over raw mouse clicks: it resolves elements by their visible
name, so it works at any window position / screen resolution.  Internally it
queries :meth:`Computer.ui_tree` to find a target, invokes the element's
native accessibility action, and only falls back to clicking the element's
logical bounds.center.

Backends that hand out element refs (the native macOS helper) show them in
``get_tree`` output as ``[ref]``; passing ``ref=`` acts on exactly that
element with no name matching.  With ``OPENDESK_BACKGROUND=1`` the tool never
moves the user's cursor and types / presses keys by posting events straight
to the target app.

The UI tool itself is platform-agnostic — all platform-specific accessibility
behaviour lives in the active :class:`Computer` backend.
"""

from __future__ import annotations

import asyncio
from typing import Any, List, Literal, Optional

from pydantic import Field

from opendesk.computer.base import CapabilityUnsupported
from opendesk.computer.types import Capability, Modifier, Point, UIElement
from opendesk.tools.base import Tool, ToolContext, ToolResult
from opendesk.tools.mouse import background_default


_MODIFIER_NAMES: dict[str, Modifier] = {
    "command": Modifier.META, "cmd": Modifier.META, "meta": Modifier.META,
    "win": Modifier.META, "super": Modifier.META,
    "ctrl": Modifier.CTRL, "control": Modifier.CTRL,
    "shift": Modifier.SHIFT,
    "alt": Modifier.ALT, "option": Modifier.ALT,
    "fn": Modifier.FN,
}


def _to_modifiers(names: list[str]) -> list[Modifier]:
    out: list[Modifier] = []
    for n in names:
        mod = _MODIFIER_NAMES.get(n.lower())
        if mod is not None and mod not in out:
            out.append(mod)
    return out


def _flatten_tree(root: UIElement) -> list[UIElement]:
    """Depth-first flatten of a UIElement tree."""
    out: list[UIElement] = [root]
    for child in root.children:
        out.extend(_flatten_tree(child))
    return out


def _find_by_ref(root: UIElement, ref: str) -> Optional[UIElement]:
    for node in _flatten_tree(root):
        if node.ref == ref:
            return node
    return None


def _hash_tree(tree: Any) -> Optional[str]:
    """Content digest of an accessibility tree, or ``None`` if it cannot be taken.

    Never raises: the digest is a side benefit of an action, and a tree shape it
    cannot digest must not fail the action itself.
    """
    try:
        from opendesk.computer.a11y import content_hash

        return content_hash(tree)
    except Exception:
        return None


def _find_element(
    root: UIElement, *, title: Optional[str], role: Optional[str],
) -> Optional[UIElement]:
    title_l = title.lower() if title else None
    role_l = role.lower() if role else None
    for node in _flatten_tree(root):
        name_match = not title_l or (node.name and title_l in node.name.lower())
        role_match = not role_l or role_l in node.role.lower()
        if name_match and role_match and (title_l or role_l):
            if node.bounds is not None or node.actions:
                return node
    return None


async def _try_perform_action(
    comp, element: UIElement, action: str, app: Optional[str],
) -> bool:
    """Try the native a11y action path; return True on success, False otherwise.

    Used by the UI tool to prefer high-fidelity native a11y invocation
    (AppleScript ``click elem``, pyatspi ``doAction``, pywinauto
    ``click_input``) and degrade gracefully to a pointer click at the
    element's bounds.center when the backend doesn't support it.
    """
    try:
        manifest = comp.capabilities()
    except Exception:
        return False
    if not manifest.has(Capability.UI_ACTIONS):
        return False
    try:
        await comp.perform_ui_action(element, action, app=app)
        return True
    except CapabilityUnsupported:
        return False
    except (RuntimeError, ValueError):
        return False


# Unlabelled layout containers add nesting but nothing to act on.
_LAYOUT_ROLES = {"AXGroup", "AXScrollArea", "AXSplitGroup", "AXLayoutArea", "AXUnknown"}


def _is_layout_noise(node: UIElement) -> bool:
    return node.role in _LAYOUT_ROLES and not node.name and not node.value


def _format_tree(root: UIElement, max_lines: int = 250) -> str:
    """Indented outline: ``[ref] [role] label = "value"`` per element."""
    lines: list[str] = []
    if root.name or root.role:
        head = f"Window: {root.name or root.role}"
        lines.append(head + (f"  [{root.ref}]" if root.ref else ""))
    clipped = False

    def visit(node: UIElement, depth: int) -> None:
        nonlocal clipped
        if len(lines) >= max_lines:
            clipped = True
            return
        shown = node is not root and bool(node.name or node.role) and not _is_layout_noise(node)
        if shown:
            indent = "  " * depth
            ref = f"[{node.ref}] " if node.ref else ""
            label = node.name or "(unnamed)"
            value = ""
            if node.value and node.value != node.name:
                v = node.value.replace("\n", " ")
                value = f' = "{v[:60]}{"…" if len(v) > 60 else ""}"'
            lines.append(f"{indent}{ref}[{node.role}] {label}{value}")
        for child in node.children:
            visit(child, depth + (1 if shown or node is root else 0))

    visit(root, 0)
    if len(lines) <= 1:
        return ""
    if clipped or root.metadata.get("truncated"):
        lines.append("… (more elements not shown — narrow with title/role, or act by ref)")
    return "\n".join(lines)


class UITool(Tool):
    """Interact with desktop UI elements by name — no pixel coordinates needed.

    ALWAYS try this before the mouse tool.  Use mouse clicks only for
    unlabelled canvas areas (games, video players, drawing tools) where no
    accessible elements exist.
    """

    name = "ui"
    title = "Accessibility UI Actions"
    annotations = {
        "readOnlyHint": False, "destructiveHint": True,
        "idempotentHint": False, "openWorldHint": True,
    }
    description = (
        "Interact with UI elements by name on any OS — no coordinates needed. "
        "ALWAYS try this before the mouse tool. Actions:\n"
        "  get_tree   — list all accessible elements in the app window\n"
        "  click      — click a button or element by its title\n"
        "  click_menu — click a menu item, e.g. File → Save\n"
        "  type       — type text (clipboard-paste, Unicode-safe)\n"
        "  press_key  — press a key or chord: key='return', modifiers=['command']\n"
        "  get_value  — read the current text value of a named element\n"
        "get_tree shows each element as [ref] [role] label. Pass ref=<ref> to "
        "click / type / get_value / press_key on exactly that element — fastest "
        "and most reliable; refs stay the same while the UI does.\n"
        "type / press_key accept verify=true to report whether the interface "
        "content actually changed."
    )

    class Params(Tool.Params):
        action: Literal["get_tree", "click", "click_menu", "type", "press_key", "get_value"] = Field(
            description="UI action to perform."
        )
        app: str = Field(
            description=(
                "Application name / process name. "
                "macOS: process name as in Activity Monitor, e.g. 'TextEdit', 'Safari'. "
                "Linux: process or window title, e.g. 'gedit', 'firefox'. "
                "Windows: executable name or title, e.g. 'Notepad', 'notepad.exe'."
            )
        )
        title: Optional[str] = Field(default=None, description="Title or label of the UI element.")
        ref: Optional[str] = Field(
            default=None,
            description=(
                "Element ref from get_tree output, e.g. 'k3x9q0'. Targets exactly "
                "that element for click / type / get_value / press_key."
            ),
        )
        role: Optional[str] = Field(
            default=None,
            description=(
                "Element role to narrow the search. "
                "macOS: 'button', 'text field', 'text area', 'checkbox'. "
                "Linux: 'push button', 'entry', 'text', 'check box'. "
                "Windows: 'Button', 'Edit', 'Text', 'CheckBox', 'ComboBox'."
            ),
        )
        text: Optional[str] = Field(default=None, description="Text to type. Required for action='type'.")
        menu: Optional[str] = Field(
            default=None,
            description="Menu bar menu name for click_menu, e.g. 'File', 'Edit'.",
        )
        menu_item: Optional[str] = Field(
            default=None,
            description="Menu item name for click_menu, e.g. 'Save', 'Copy'.",
        )
        key: Optional[str] = Field(
            default=None,
            description=(
                "Key for press_key: 'return', 'escape', 'tab', 'space', 'delete', "
                "'up', 'down', 'left', 'right', 'home', 'end', 'f1'–'f12', or a single char."
            ),
        )
        modifiers: List[str] = Field(
            default_factory=list,
            description=(
                "Modifier keys for press_key: 'command' (macOS), 'ctrl', 'shift', 'alt'. "
                "E.g. ['command'] for cmd+key."
            ),
        )
        window_index: int = Field(default=1, description="Window index (1 = frontmost).")
        verify: bool = Field(
            default=False,
            description=(
                "For 'type' / 'press_key': read the accessibility tree again "
                "afterwards and report whether the *content* changed. Answers "
                "'did my keystrokes land' without a follow-up get_tree, and does "
                "it by content rather than pixels, so a ticking clock does not "
                "read as success. Costs one extra tree read."
            ),
        )

    async def execute(self, ctx: ToolContext, params: "UITool.Params") -> ToolResult:
        from opendesk.computer.sandbox import ActionType, get_sandbox

        await ctx.check_permission(
            tool="ui", argument=f"{params.action} in {params.app}",
            description=f"UI accessibility action: {params.action} in '{params.app}'",
        )

        sandbox = get_sandbox(ctx.session_id)

        _summary = {"action": params.action, "app": params.app, "title": params.title}
        if params.ref:
            _summary["ref"] = params.ref
        _replay_p = {
            "action": params.action, "app": params.app, "title": params.title, "ref": params.ref,
            "role": params.role, "text": params.text, "menu": params.menu,
            "menu_item": params.menu_item, "key": params.key, "modifiers": params.modifiers,
            "window_index": params.window_index,
        }

        try:
            result_msg = await self._dispatch(ctx, params)
        except (RuntimeError, ValueError, ImportError, NotImplementedError) as exc:
            # Recorded like any other step: an expected failure (no such element,
            # app missing) is a real thing the agent did and must be visible to
            # diagnosis and to the trajectory.
            await sandbox.record_action(
                ActionType.UI_ACTION, _summary, error=str(exc), replay_params=_replay_p,
            )
            return ToolResult(
                title=f"UI error: {params.action} in {params.app}",
                output=str(exc),
                error=True,
            )
        except Exception as exc:
            # An unexpected failure is recorded too.  Swallowing it here used to
            # mean the step silently vanished from the audit log — so a run that
            # failed for a reason nobody anticipated produced a *clean-looking*
            # trajectory with the failure simply absent, which is the worst
            # possible way to lose it.
            await sandbox.record_action(
                ActionType.UI_ACTION, _summary, error=f"{type(exc).__name__}: {exc}",
                replay_params=_replay_p,
            )
            return ToolResult(
                title=f"UI error: {params.action} in {params.app}",
                output=f"{type(exc).__name__}: {exc}",
                error=True,
            )

        await sandbox.record_action(
            ActionType.UI_ACTION, _summary, result=result_msg[:200], replay_params=_replay_p,
        )
        label = params.title or params.menu_item or params.key or params.ref or ""
        return ToolResult(
            title=f"UI: {params.action} '{label}' in {params.app}",
            output=result_msg,
        )

    async def _read_tree(self, ctx: ToolContext, app: Optional[str]):
        """Read the accessibility tree and record its content digest.

        The digest lands on the sandbox, so every action recorded from here on
        carries it and state diagnosis can group states by *content* instead of
        by layout — which is the difference between noticing an edited glyph and
        not.  It is free: the tree is read anyway to resolve the target.
        """
        tree = await ctx.computer.ui_tree(app=app)
        self._record_digest(ctx, _hash_tree(tree))
        return tree

    @staticmethod
    def _record_digest(ctx: ToolContext, digest: Optional[str]) -> None:
        if digest is None:
            return
        try:
            from opendesk.computer.sandbox import get_sandbox

            get_sandbox(ctx.session_id).current_ui = digest
        except Exception:
            pass

    async def _digest(self, ctx: ToolContext, app: Optional[str]) -> Optional[str]:
        """Content digest of the interface right now, or ``None`` if unreadable.

        ``None`` means *unknown*, not *unchanged*: a host without accessibility
        or an app that renders everything itself.  Callers must not read it as
        evidence that nothing happened.
        """
        try:
            return _hash_tree(await ctx.computer.ui_tree(app=app))
        except Exception:
            return None

    async def _observe(self, ctx: ToolContext, app: Optional[str]) -> Optional[str]:
        """Stamp the current digest, swallowing a read failure.

        Used by actions that mutate the interface but do not need the tree to
        resolve a target (``type``, ``press_key``, a native ``click_menu``).
        Without this they would stamp whatever digest an *earlier* action left
        behind, so an edit they made would be credited to whichever step next
        read a tree — or to no step at all, if none did.

        A failure is not a failure of the action: a keyboard action works on
        hosts where accessibility does not, and refusing to type because the
        tree is unreadable would be a far worse trade.
        """
        digest = await self._digest(ctx, app)
        self._record_digest(ctx, digest)
        return digest

    async def _verify(
        self, ctx: ToolContext, params: "UITool.Params", before: Optional[str],
    ) -> str:
        """Report whether the interface content changed, when asked.

        Opt-in, because it costs a second tree read.  It answers the question a
        keyboard action otherwise leaves open — *did that land* — without a
        follow-up ``get_tree``, and it answers it by content rather than by
        pixels, so a caret blink or a ticking clock does not read as success.
        """
        if not params.verify:
            return ""
        after = await self._digest(ctx, params.app)
        if before is None or after is None:
            return "\n  verification: unavailable (no accessibility tree to read)"
        if before == after:
            return (
                "\n  verification: content UNCHANGED — the keystrokes may not "
                "have reached an editable target (check focus, or run get_tree)."
            )
        return f"\n  verification: content changed ({before[:8]} → {after[:8]})."

    async def _dispatch(self, ctx: ToolContext, params: "UITool.Params") -> str:
        comp = ctx.computer

        if params.action == "get_tree":
            tree = await self._read_tree(ctx, params.app)
            text = _format_tree(tree)
            return text or (
                f"No accessible elements in '{params.app}'. App may use custom "
                "rendering (Electron, games). Fall back to mouse tool with "
                "image_width/image_height."
            )

        if params.action == "click":
            if params.ref:
                direct = self._ref_element(params)
                if await _try_perform_action(comp, direct, "click", params.app):
                    return f"Clicked [{params.ref}] in {params.app} (via a11y)."
                tree = await self._read_tree(ctx, params.app)
                element = self._require_ref(tree, params)
                used_a11y = False
            else:
                if not params.title and not params.role:
                    raise ValueError("Provide 'ref', or at least 'title' or 'role', for click.")
                tree = await self._read_tree(ctx, params.app)
                element = _find_element(tree, title=params.title, role=params.role)
                if element is None:
                    raise RuntimeError(
                        f"No element title={params.title!r} role={params.role!r} in "
                        f"'{params.app}'. Run get_tree to see available elements."
                    )
                used_a11y = await _try_perform_action(comp, element, "click", params.app)
            how = "a11y"
            if not used_a11y:
                if element.bounds is None:
                    raise RuntimeError(
                        f"Element '{element.name}' has no bounds and no native a11y action — cannot click."
                    )
                if background_default():
                    await comp.background_click(element.bounds.center)
                    how = "background click"
                else:
                    await comp.click(element.bounds.center)
                    how = "bounds-center"
            ref = f" [{element.ref}]" if element.ref else ""
            return f"Clicked{ref} [{element.role}] {element.name!r} in {params.app} (via {how})."

        if params.action == "click_menu":
            if not params.menu or not params.menu_item:
                raise ValueError("Both 'menu' and 'menu_item' are required for click_menu.")
            await comp.focus_app(params.app)
            # The native-action path below reads no tree, so without this its
            # entry would carry a stale digest and the menu's effect would be
            # credited to whatever step next read a tree.
            await self._observe(ctx, params.app)
            synth = UIElement(
                role="menu item",
                name=params.menu_item,
                metadata={"menu_path": [params.menu, params.menu_item], "app": params.app},
            )
            used_a11y = await _try_perform_action(comp, synth, "click", params.app)
            if used_a11y:
                return f"Clicked {params.menu} → {params.menu_item} in {params.app} (via a11y)."

            tree = await self._read_tree(ctx, params.app)
            menu_el = _find_element(tree, title=params.menu, role=None)
            if menu_el is None or menu_el.bounds is None:
                raise RuntimeError(
                    f"Menu '{params.menu}' not found in {params.app}. Run get_tree to inspect."
                )
            await comp.click(menu_el.bounds.center)
            await asyncio.sleep(0.3)
            tree2 = await self._read_tree(ctx, params.app)
            item_el = _find_element(tree2, title=params.menu_item, role=None)
            if item_el is None or item_el.bounds is None:
                raise RuntimeError(
                    f"Menu item '{params.menu_item}' not found after opening menu '{params.menu}'."
                )
            await comp.click(item_el.bounds.center)
            return f"Clicked {params.menu} → {params.menu_item} in {params.app} (via bounds)."

        if params.action == "type":
            if not params.text:
                raise ValueError("'text' is required for action='type'.")
            preview = params.text[:60] + ("…" if len(params.text) > 60 else "")
            where = f"[{params.ref}] in {params.app}" if params.ref else params.app
            if background_default():
                # Keystrokes posted to the app's process: no activation, no
                # cursor movement, no clipboard.
                target = self._ref_element(params, value=params.text) if params.ref else UIElement(
                    role="application", name=params.app, value=params.text,
                    metadata={"app": params.app},
                )
                before = await self._observe(ctx, params.app)
                await self._background_perform(comp, target, "type", params)
                message = f"Typed {len(params.text)} chars into {where} (background): {preview!r}"
                return message + await self._verify(ctx, params, before)
            await comp.focus_app(params.app)
            await asyncio.sleep(0.2)
            if params.ref:
                await self._focus_ref(comp, params)
            before = await self._observe(ctx, params.app)
            await comp.type_text(params.text)
            message = f"Typed {len(params.text)} chars into {where}: {preview!r}"
            return message + await self._verify(ctx, params, before)

        if params.action == "press_key":
            if not params.key:
                raise ValueError("'key' is required for action='press_key'.")
            combo = ("+".join(params.modifiers) + "+" if params.modifiers else "") + params.key
            if background_default():
                meta = {"app": params.app, "key": params.key, "modifiers": list(params.modifiers)}
                target = self._ref_element(params) if params.ref else UIElement(
                    role="application", name=params.app,
                )
                target.metadata.update(meta)
                before = await self._observe(ctx, params.app)
                await self._background_perform(comp, target, "key", params)
                message = f"Pressed {combo} in {params.app} (background)."
                return message + await self._verify(ctx, params, before)
            await comp.focus_app(params.app)
            await asyncio.sleep(0.15)
            if params.ref:
                await self._focus_ref(comp, params)
            before = await self._observe(ctx, params.app)
            await comp.press(params.key, modifiers=_to_modifiers(params.modifiers))
            message = f"Pressed {combo} in {params.app}."
            return message + await self._verify(ctx, params, before)

        if params.action == "get_value":
            if params.ref:
                tree = await self._read_tree(ctx, params.app)
                element = self._require_ref(tree, params)
                return element.value or element.name or "(no value)"
            if not params.title and not params.role:
                raise ValueError("Provide 'ref', 'title' or 'role' for get_value.")
            tree = await self._read_tree(ctx, params.app)
            element = _find_element(tree, title=params.title, role=params.role)
            if element is None:
                raise RuntimeError(
                    f"No element title={params.title!r} role={params.role!r} in {params.app}."
                )
            return element.value or element.name or "(no value)"

        raise ValueError(f"Unknown action: {params.action!r}")

    @staticmethod
    def _ref_element(params: "UITool.Params", value: Optional[str] = None) -> UIElement:
        return UIElement(
            role=params.role or "", name=params.title or "", value=value,
            ref=params.ref, metadata={"app": params.app},
        )

    @staticmethod
    def _require_ref(tree: UIElement, params: "UITool.Params") -> UIElement:
        assert params.ref is not None
        element = _find_by_ref(tree, params.ref)
        if element is None:
            raise RuntimeError(
                f"No element with ref {params.ref!r} in '{params.app}'. Refs change "
                "when the UI changes — run get_tree again."
            )
        return element

    @staticmethod
    async def _background_perform(
        comp, target: UIElement, action: str, params: "UITool.Params",
    ) -> None:
        try:
            await comp.perform_ui_action(target, action, app=params.app)
        except CapabilityUnsupported as exc:
            raise RuntimeError(
                "Background mode (OPENDESK_BACKGROUND=1) delivers keystrokes straight "
                "to the app, which needs the native macOS helper (opendesk-ax) with "
                "Accessibility permission. Unset OPENDESK_BACKGROUND to type in the "
                f"foreground instead. ({exc})"
            ) from exc

    async def _focus_ref(self, comp, params: "UITool.Params") -> None:
        """Best-effort keyboard focus on the ref'd element before typing."""
        try:
            await comp.perform_ui_action(self._ref_element(params), "focus", app=params.app)
        except Exception:
            pass
