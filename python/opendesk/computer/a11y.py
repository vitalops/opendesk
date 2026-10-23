"""Accessibility-tree content diffing — the semantic channel.

Pixels answer "did anything on screen change".  They cannot answer "did the
*content* change": a ticking clock and a one-glyph edit are both a few dozen
pixels of difference, and the two differ in meaning rather than magnitude, so no
threshold separates them.  Global perceptual hashes are no better — they encode
layout, so a dialog opening moves them ~26 bits while a single glyph moves them
zero.

The accessibility tree has no such problem, because it is **text**.  A field
editing from ``100`` to ``150`` is the string change ``"100" → "150"`` — exact,
free of sensor noise, and requiring no model call.  This module makes that the
primary channel for *what* changed, leaving the pixel channel (see
:mod:`opendesk.computer.capture`) to answer *whether* anything changed at all.

Two views, deliberately separate
--------------------------------

* :func:`ui_diff` — a **structural** diff keyed by position in the tree.  It
  answers "what changed", and because the key is structural rather than
  name-derived, a label whose text changed in place is reported as *modified*
  rather than as a removal plus an addition.
* :func:`find_elements` — a **content** query.  It answers "does this element now
  say X", which is what a verifiable reward actually needs: ``Total`` reads
  ``300``, not "the screen looks different".

Example::

    from opendesk.computer.a11y import ui_diff, find_elements

    diff = ui_diff(before_tree, after_tree)
    diff.changed          # True
    diff.modified         # [total: 'Total: 100' -> 'Total: 150']
    diff.summary()        # '1 element(s) changed: ...'

    find_elements(after_tree, name_regex="Total", value_regex=r"^150$")
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

#: A node budget a caller can opt into — a result headed for a model's context
#: cannot be unbounded, and accessibility trees on real desktops do run long
#: (a 441-element window was measured on Windows).
#:
#: Nothing in this module applies it by default, and that is deliberate.  A walk
#: that quietly stopped at a boundary would answer "did the content change" and
#: "is this element present" from a window it only partly read — reporting
#: *unchanged* for an edit past the cut, and *absent* for an element sitting at
#: position 401.  Callers that want a budget pass one and read
#: :attr:`Walk.truncated` back, so a short answer says it is short.
PROMPT_NODE_BUDGET = 400

#: Recursion bound for the walk.  Reported rather than silent when it bites.
_DEFAULT_MAX_DEPTH = 12

#: Cell size, in pixels, for the positional fallback that matches an element
#: across a structural shift.  Coarse enough to absorb a small reflow, fine
#: enough that two distinct controls rarely share a cell.
_POSITION_BUCKET = 16


def node_get(node: Any, key: str, default: Any = None) -> Any:
    """Read *key* from an object or a dict, tolerating both.

    The accessibility tree arrives as :class:`~opendesk.computer.types.UIElement`
    objects from a live backend and as plain dicts once deserialised.  Every
    walker in the codebase goes through this so both work.
    """
    if isinstance(node, dict):
        return node.get(key, default)
    return getattr(node, key, default)


def element_content(node: Any) -> str:
    """The text an element carries — its ``value`` if set, else its ``name``.

    Which field holds content depends on the widget: a text field keeps its
    contents in ``value`` and its label in ``name``, while a label keeps its
    text in ``name``.  Preferring ``value`` and falling back to ``name`` matches
    how both behave, so a caller comparing "what does this element say" does not
    have to know which widget it is.
    """
    value = node_get(node, "value")
    if value is not None:
        text = str(value).strip()
        if text:
            return text
    return str(node_get(node, "name", "") or node_get(node, "title", "") or "").strip()


def _role_ignored(role: str, needles: Optional[list[str]]) -> bool:
    if not needles:
        return False
    low = role.lower()
    return any(n in low for n in needles)


#: Roles whose content changes *on its own* — a clock, a status readout tracking
#: the cursor.  Pruned by default from the operations that answer "is this the
#: same state" and "did this change", because ambient churn is not a change to
#: the task's state and treating it as one poisons the state graph: on a desktop
#: with a menu-bar clock, an unpruned digest splits a new state on every tick, so
#: a ten-step episode produces ten states and the transition graph says nothing.
#:
#: These are containers, matched case-insensitively as substrings, so pruning one
#: drops its whole subtree — the clock lives *inside* the menu bar.  Note that
#: ``"menubar"`` deliberately does not match a dropdown ``AXMenu``: an open
#: File ▸ Save menu is real interface, not furniture.
#:
#: The names are each *platform's*, not a shared vocabulary, and a name no
#: backend emits is a name that never fires.  Measured on Windows, where the
#: backend reports Win32 class names: ``"statusbar"`` matches a window's
#: ``StatusBar`` control and ``"menubar"`` matches a real ``MenuBar``, but
#: ``"taskbar"`` matches nothing — the shell taskbar surfaces as ``Pane``, so it
#: cannot be named by role at all.  That is tolerable because the taskbar is a
#: separate top-level window that an application capture does not contain; the
#: macOS case is different precisely because the menu bar *is* part of the app's
#: own tree.  Do not read this tuple as a promise that every entry fires
#: everywhere.
#:
#: Pass ``ignore_roles=None`` to any of these functions to get the raw digest
#: back, furniture included.
AMBIENT_ROLES: tuple[str, ...] = (
    "menubar", "menu bar",
    "statusbar", "status bar",
    "taskbar", "task bar",
)


def _normalise_roles(ignore_roles: Any) -> Optional[list[str]]:
    if not ignore_roles:
        return None
    if isinstance(ignore_roles, str):
        ignore_roles = [ignore_roles]
    needles = [str(r).strip().lower() for r in ignore_roles if str(r).strip()]
    return needles or None


@dataclass(frozen=True)
class A11yNode:
    """One accessibility element, flattened out of the tree."""

    role: str
    name: str
    value: str
    content: str
    #: Position in the tree, as ``role[index]`` segments joined by ``/``.  The
    #: index is the ordinal among *all* siblings, which makes it deterministic
    #: without any heuristics; see :func:`ui_diff` for what that costs.
    path: str
    depth: int
    #: Raw screen coordinates ``(x, y, w, h)``, or ``None`` when the backend
    #: reported no geometry.
    bounds: Optional[tuple[int, int, int, int]] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "role": self.role,
            "name": self.name,
            "path": self.path,
        }
        if self.value:
            d["value"] = self.value
        if self.bounds is not None:
            d["bounds"] = list(self.bounds)
        return d


@dataclass(frozen=True)
class Walk:
    """A tree walk's nodes, plus whether the walk actually finished.

    ``truncated`` is the important half.  Everything downstream of this module
    scores something on the list it gets back — a verifiable reward, a state
    graph, an assertion about what is on screen — so a list that stops early
    without saying so makes a claim about a window that was never read.
    """

    nodes: list[A11yNode]
    truncated: bool = False
    #: Which bound bit — ``"nodes"``, ``"depth"``, or ``None`` when complete.
    reason: Optional[str] = None

    def __iter__(self):
        return iter(self.nodes)

    def __len__(self) -> int:
        return len(self.nodes)


def walk_nodes(
    root: Any,
    *,
    max_nodes: Optional[int] = None,
    max_depth: int = _DEFAULT_MAX_DEPTH,
    ignore_roles: Any = None,
) -> Walk:
    """Walk an accessibility tree in tree order and report how the walk ended.

    *max_nodes* defaults to ``None`` — no budget.  Pass
    :data:`PROMPT_NODE_BUDGET` (or your own number) when the result is headed
    into a prompt, and check ``truncated`` before treating the list as the whole
    window.

    *ignore_roles* prunes whole subtrees whose role matches (case-insensitive
    substring) — the semantic counterpart to excluding a pixel region.  Use it
    for furniture that changes on its own: ignoring ``"menubar"`` drops the
    status-bar clock without dropping anything the task cares about.  It is not
    a way to ignore all text; ignoring ``"static text"`` would discard the
    content you came for.
    """
    needles = _normalise_roles(ignore_roles)
    out: list[A11yNode] = []
    stopped: dict[str, str] = {}

    def visit(node: Any, depth: int, prefix: str, index: int) -> None:
        if node is None:
            return
        role = str(node_get(node, "role", "") or "")
        if _role_ignored(role, needles):
            return
        if max_nodes is not None and len(out) >= max_nodes:
            # Checked before the depth bound so a node budget is reported as
            # itself rather than as the bound that happens to sit behind it.
            stopped.setdefault("reason", "nodes")
            return
        if depth > max_depth:
            stopped.setdefault("reason", "depth")
            return
        segment = f"{role or '?'}[{index}]"
        path = f"{prefix}/{segment}" if prefix else segment

        name = str(node_get(node, "name", "") or node_get(node, "title", "") or "").strip()
        value_raw = node_get(node, "value")
        value = "" if value_raw is None else str(value_raw).strip()
        bounds = _read_bounds(node)

        out.append(A11yNode(
            role=role,
            name=name,
            value=value,
            content=element_content(node),
            path=path,
            depth=depth,
            bounds=bounds,
        ))

        children = node_get(node, "children", []) or []
        for i, child in enumerate(children):
            visit(child, depth + 1, path, i)

    visit(root, 0, "", 0)
    reason = stopped.get("reason")
    return Walk(nodes=out, truncated=reason is not None, reason=reason)


def flatten_nodes(
    root: Any,
    *,
    max_nodes: Optional[int] = None,
    max_depth: int = _DEFAULT_MAX_DEPTH,
    ignore_roles: Any = None,
) -> list[A11yNode]:
    """Walk a tree and return its elements in tree order.

    **Unbounded by default**, because the callers that score something on the
    result need the whole screen: a budget here is a silently wrong answer to
    "is this element present" or "did the content change".  Use
    :func:`walk_nodes` when you pass a budget and need to know it bit.
    """
    return walk_nodes(
        root, max_nodes=max_nodes, max_depth=max_depth, ignore_roles=ignore_roles,
    ).nodes


def _read_bounds(node: Any) -> Optional[tuple[int, int, int, int]]:
    bounds = node_get(node, "bounds")
    if bounds is None:
        return None
    try:
        x = int(node_get(bounds, "x", 0) or 0)
        y = int(node_get(bounds, "y", 0) or 0)
        w = int(node_get(bounds, "width", 0) or 0)
        h = int(node_get(bounds, "height", 0) or 0)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return (x, y, w, h)


def ui_snapshot(root: Any, **kwargs: Any) -> dict[str, A11yNode]:
    """Flatten a tree into a ``{path: node}`` mapping for comparison or storage.

    The mapping is the serialisable form of a screen's content: keep it and you
    can later say exactly what changed, with no screenshot and no re-capture.
    """
    return {n.path: n for n in flatten_nodes(root, **kwargs)}


def filter_snapshot(
    snapshot: dict[str, A11yNode], ignore_roles: Any
) -> dict[str, A11yNode]:
    """Drop snapshot entries whose role should be ignored, *and their subtrees*.

    Pruning is by path prefix on purpose.  The thing worth ignoring is usually a
    container — the status bar whose *child* text is the clock — so dropping only
    the matching node would leave the churn exactly where it was.

    Kept here rather than at the call sites so that a stored snapshot cannot be
    filtered differently from a live tree, which would let the same ``ignore_roles``
    mean two things depending on where the tree came from.
    """
    needles = _normalise_roles(ignore_roles)
    if not needles:
        return snapshot

    pruned = [
        path for path, node in snapshot.items()
        if _role_ignored(str(node_get(node, "role", "") or ""), needles)
    ]
    if not pruned:
        return snapshot
    return {
        path: node for path, node in snapshot.items()
        if not any(path == p or path.startswith(p + "/") for p in pruned)
    }


# ---------------------------------------------------------------------------
# Diffing
# ---------------------------------------------------------------------------

@dataclass
class UiChange:
    """One element that differs between two states."""

    kind: str  # "added" | "removed" | "modified" | "moved"
    role: str
    path: str
    label: str = ""
    before: Optional[str] = None
    after: Optional[str] = None
    before_path: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind, "role": self.role, "path": self.path}
        if self.label:
            d["label"] = self.label
        if self.before is not None:
            d["before"] = self.before
        if self.after is not None:
            d["after"] = self.after
        if self.before_path is not None and self.before_path != self.path:
            d["before_path"] = self.before_path
        return d

    def describe(self) -> str:
        # The label is only worth printing when it says something the before and
        # after values do not — for a static label it *is* the content, and
        # repeating it reads as noise.
        where = f"[{self.role}]"
        if self.label and self.label not in (self.before, self.after):
            where += f" {self.label!r}"
        if self.kind == "modified":
            return f"{where} {self.before!r} \u2192 {self.after!r}"
        if self.kind == "added":
            return f"{where} added" + (f" as {self.after!r}" if self.after else "")
        if self.kind == "removed":
            return f"{where} removed" + (f" was {self.before!r}" if self.before else "")
        return f"{where} moved"


@dataclass
class UiDiff:
    """What changed between two accessibility states."""

    added: list[UiChange] = field(default_factory=list)
    removed: list[UiChange] = field(default_factory=list)
    modified: list[UiChange] = field(default_factory=list)
    moved: list[UiChange] = field(default_factory=list)
    matched: int = 0
    #: True when a node budget cut one of the walks short.  ``changed == False``
    #: then means "nothing changed in the part of the window that was read",
    #: which is not the same claim.
    truncated: bool = False

    @property
    def changed(self) -> bool:
        """Any difference at all, including a pure reordering."""
        return bool(self.added or self.removed or self.modified or self.moved)

    @property
    def content_changes(self) -> int:
        """Changes that carry new information — reordering does not count."""
        return len(self.added) + len(self.removed) + len(self.modified)

    @property
    def count(self) -> int:
        return len(self.added) + len(self.removed) + len(self.modified) + len(self.moved)

    def summary(self) -> str:
        note = " (walk truncated - not the whole window)" if self.truncated else ""
        if not self.changed:
            return (
                f"No accessibility change{note} "
                f"({self.matched} element(s) unchanged)."
            )
        parts = []
        if self.modified:
            parts.append(f"{len(self.modified)} changed")
        if self.added:
            parts.append(f"{len(self.added)} added")
        if self.removed:
            parts.append(f"{len(self.removed)} removed")
        if self.moved:
            parts.append(f"{len(self.moved)} moved")
        return f"{', '.join(parts)} ({self.matched} unchanged){note}."

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed": self.changed,
            "content_changes": self.content_changes,
            "matched": self.matched,
            "added": [c.to_dict() for c in self.added],
            "removed": [c.to_dict() for c in self.removed],
            "modified": [c.to_dict() for c in self.modified],
            "moved": [c.to_dict() for c in self.moved],
        }


def diff_snapshots(before: dict[str, A11yNode], after: dict[str, A11yNode]) -> UiDiff:
    """Compare two :func:`ui_snapshot` mappings.

    Matching runs in three passes, ordered by how much each one can be trusted,
    because a single pass gets an obvious case wrong at each extreme:

    1. **Same role and same content.**  This is the element itself, wherever it
       now sits.  Matching here first is what keeps an inserted row or a
       reordering from being reported as a wholesale rewrite of everything below
       it — an ordinal shifts, but the element does not become a different
       element.  Only elements that actually carry content take part; pairing
       anonymous containers on an empty string would be guesswork.
    2. **Same position in the tree.**  What pass 1 could not claim is compared
       where it stands.  This is the pass that catches text edited *in place*,
       and it reports it as ``modified`` rather than as a removal plus an
       addition, precisely because the key is the structural position and not
       the (changed) text.
    3. **Same role, same place on screen.**  What is left has both shifted and
       changed.  A position survives a structural shift in a way an ordinal does
       not, so pairing on it recovers a genuine edit that passes 1 and 2 each
       miss for opposite reasons.
    """
    diff = UiDiff()
    pool_before = dict(before)
    pool_after = dict(after)

    def center(node: A11yNode) -> Optional[tuple[int, int]]:
        if node.bounds is None:
            return None
        x, y, w, h = node.bounds
        return (x + w // 2, y + h // 2)

    # --- pass 1: same role + content, nearest instance -------------------
    by_content: dict[tuple[str, str], list[str]] = {}
    for path, node in pool_before.items():
        if node.content:
            by_content.setdefault((node.role.lower(), node.content), []).append(path)

    for path in list(pool_after):
        node = pool_after[path]
        if not node.content:
            continue
        candidates = by_content.get((node.role.lower(), node.content))
        if not candidates:
            continue
        pick = _nearest(path, candidates, pool_before, node, center)
        original = pool_before.pop(pick)
        pool_after.pop(path)
        candidates.remove(pick)
        if not candidates:
            by_content.pop((node.role.lower(), node.content), None)

        if pick == path:
            diff.matched += 1
        else:
            diff.moved.append(UiChange(
                kind="moved", role=node.role, path=path,
                label=node.name or original.name,
                before=original.content, after=node.content,
                before_path=pick,
            ))

    # --- pass 2: same position in the tree -------------------------------
    for path in list(pool_after):
        original = pool_before.pop(path, None)
        if original is None:
            continue
        node = pool_after.pop(path)
        if original.content == node.content:
            # An anonymous container the first pass deliberately skipped.
            diff.matched += 1
        else:
            diff.modified.append(UiChange(
                kind="modified", role=node.role, path=path,
                label=node.name or original.name,
                before=original.content, after=node.content,
                before_path=path,
            ))

    # --- pass 3: same role + place on screen -----------------------------
    by_place: dict[tuple[str, int, int], list[str]] = {}
    for path, node in pool_before.items():
        spot = center(node)
        if spot is not None:
            by_place.setdefault(
                (node.role.lower(), spot[0] // _POSITION_BUCKET,
                 spot[1] // _POSITION_BUCKET), []
            ).append(path)

    for path in list(pool_after):
        node = pool_after[path]
        spot = center(node)
        if spot is None:
            continue
        key = (node.role.lower(), spot[0] // _POSITION_BUCKET, spot[1] // _POSITION_BUCKET)
        candidates = by_place.get(key)
        if not candidates:
            continue
        pick = candidates.pop(0)
        if not candidates:
            by_place.pop(key, None)
        original = pool_before.pop(pick)
        pool_after.pop(path)
        change = UiChange(
            kind="modified" if original.content != node.content else "moved",
            role=node.role, path=path,
            label=node.name or original.name,
            before=original.content, after=node.content,
            before_path=pick,
        )
        (diff.modified if change.kind == "modified" else diff.moved).append(change)

    # --- leftovers -------------------------------------------------------
    for path, node in pool_after.items():
        diff.added.append(UiChange(
            kind="added", role=node.role, path=path, label=node.name,
            after=node.content or None,
        ))
    for path, node in pool_before.items():
        diff.removed.append(UiChange(
            kind="removed", role=node.role, path=path, label=node.name,
            before=node.content or None,
        ))
    return diff


def _nearest(
    path: str,
    candidates: list[str],
    pool: dict[str, A11yNode],
    node: A11yNode,
    center: Any,
) -> str:
    """Pick the candidate that is the same element, not merely the same text.

    Staying at the same path is decisive when possible.  Otherwise the nearest
    instance wins, which keeps two identical labels in different parts of the
    screen from being cross-paired.
    """
    if path in candidates:
        return path
    spot = center(node)
    if spot is None:
        return candidates[0]
    best, best_delta = candidates[0], None
    for candidate in candidates:
        other = center(pool[candidate])
        if other is None:
            continue
        delta = abs(other[0] - spot[0]) + abs(other[1] - spot[1])
        if best_delta is None or delta < best_delta:
            best, best_delta = candidate, delta
    return best


def ui_diff(before_tree: Any, after_tree: Any, **kwargs: Any) -> UiDiff:
    """Diff two accessibility trees directly.

    Accepts :func:`ui_snapshot` mappings as well as raw trees, so a caller can
    keep the cheap snapshot rather than the whole tree and still diff later.
    ``ignore_roles`` applies either way, and defaults to :data:`AMBIENT_ROLES`:
    a diff exists to answer *did this change*, so a clock tick must not count as
    one.  That matters most where this feeds a reward — a ``ui_changed`` check
    that fired on the clock would be a verifiable predicate reporting a change
    that never happened.
    """
    ignore_roles = kwargs.get("ignore_roles", AMBIENT_ROLES)
    kwargs = {**kwargs, "ignore_roles": ignore_roles}
    before, before_short = _as_snapshot(before_tree, kwargs, ignore_roles)
    after, after_short = _as_snapshot(after_tree, kwargs, ignore_roles)
    diff = diff_snapshots(before, after)
    diff.truncated = before_short or after_short
    return diff


def _as_snapshot(
    state: Any, kwargs: dict[str, Any], ignore_roles: Any = None
) -> tuple[dict[str, A11yNode], bool]:
    """A ``{path: node}`` view of *state*, and whether that view is short.

    A mapping that is already a snapshot came from a walk that is already over,
    so its completeness cannot be recovered here and is reported as complete —
    the walk that produced it is the only place that knew.
    """
    if isinstance(state, dict) and all(
        isinstance(v, A11yNode) for v in state.values()
    ):
        return filter_snapshot(state, ignore_roles), False
    walk = walk_nodes(state, **kwargs)
    return {n.path: n for n in walk.nodes}, walk.truncated


# ---------------------------------------------------------------------------
# Content queries — the verifiable-assertion primitive
# ---------------------------------------------------------------------------

def find_elements(
    root: Any,
    *,
    role: Optional[str] = None,
    name_regex: Optional[str] = None,
    value_regex: Optional[str] = None,
    content_regex: Optional[str] = None,
    ignore_roles: Any = None,
    limit: int = 20,
    **kwargs: Any,
) -> list[A11yNode]:
    """Return elements matching every supplied criterion.

    Criteria are combined with AND, and each is a case-insensitive substring test
    for ``role`` or a regular expression for the rest.  This is the check a
    verifiable reward actually wants: *this field now reads that value*, rather
    than "the screen is different from before".
    """
    if isinstance(root, dict) and all(isinstance(v, A11yNode) for v in root.values()):
        nodes: Iterable[A11yNode] = filter_snapshot(root, ignore_roles).values()
    else:
        nodes = flatten_nodes(root, ignore_roles=ignore_roles, **kwargs)

    role_needle = str(role).lower() if role else None
    name_re = _compile(name_regex)
    value_re = _compile(value_regex)
    content_re = _compile(content_regex)

    out: list[A11yNode] = []
    for node in nodes:
        if role_needle and role_needle not in node.role.lower():
            continue
        if name_re and not name_re.search(node.name):
            continue
        if value_re and not value_re.search(node.value):
            continue
        if content_re and not content_re.search(node.content):
            continue
        out.append(node)
        if len(out) >= limit:
            break
    return out


def _compile(pattern: Optional[str]) -> Optional["re.Pattern[str]"]:
    if pattern is None:
        return None
    return re.compile(str(pattern), re.IGNORECASE)


# ---------------------------------------------------------------------------
# Content identity — for the state graph
# ---------------------------------------------------------------------------

def content_hash(
    root: Any, *, ignore_roles: Any = AMBIENT_ROLES, **kwargs: Any
) -> str:
    """A short digest of a tree's *content*, for cheap equality comparison.

    Two states hash equal exactly when they present the same roles and the same
    text in the same order.  Deliberately **excludes geometry**, so a window
    nudged three pixels or a reflowed layout is not a new state, but a single
    edited glyph is.  That is the distinction the perceptual fingerprint cannot
    make, and it is why a state graph can be built on this where it could not be
    built on pixels.

    Ambient churn — the menu-bar clock, a status bar — is pruned by default, so
    a tick is not a state transition.  Without that the digest would be *worse*
    than a pixel hash on a real desktop, where a clock showing seconds changes
    every second; see :data:`AMBIENT_ROLES`.  Pass ``ignore_roles=None`` for the
    raw digest over everything, or your own list to prune something else.

    Order is kept, so reordering a list *is* a new state — the list got sorted,
    which is something that happened.  Only position on screen is discarded.

    The walk is unbounded by default, so the digest covers the whole tree rather
    than a leading slice of it.  Pass ``max_nodes`` to cap it; the result then
    carries a truncation marker, so a capped digest can never compare equal to a
    complete one.
    """
    digest = hashlib.sha256()
    walk = walk_nodes(root, ignore_roles=ignore_roles, **kwargs)
    for node in walk.nodes:
        digest.update(node.role.encode("utf-8", "replace"))
        digest.update(b"\x1f")
        digest.update(node.content.encode("utf-8", "replace"))
        digest.update(b"\x1e")
    if walk.truncated:
        # A capped digest must never be mistakable for a complete one: two
        # states differing only past the cut would otherwise read as the same
        # state, which is the failure the ambient pruning exists to avoid and
        # this would reintroduce from the other end.
        digest.update(b"\x00truncated:" + (walk.reason or "").encode("ascii"))
    return digest.hexdigest()[:12]
