"""Accessibility-tree content diffing — the semantic channel.

The point of this module is a distinction pixels cannot make: a ticking clock and
a one-glyph edit are both a few dozen changed pixels, so only *content* separates
them.  These tests pin that behaviour down, plus the matching rules that keep a
structural shift from being reported as a wholesale delete-and-add.
"""

from __future__ import annotations

import pytest

from opendesk.computer.a11y import (
    PROMPT_NODE_BUDGET,
    content_hash,
    diff_snapshots,
    element_content,
    filter_snapshot,
    find_elements,
    flatten_nodes,
    ui_diff,
    ui_snapshot,
    walk_nodes,
)
from opendesk.computer.sandbox import clear_sandbox, get_sandbox
from opendesk.tools.base import ToolContext
from opendesk.tools.ui import UITool
from tests._fakes import FakeComputer


def node(role: str, name: str = "", *, value=None, bounds=None, children=None):
    n = {"role": role, "name": name, "children": list(children or [])}
    if value is not None:
        n["value"] = value
    if bounds is not None:
        x, y, w, h = bounds
        n["bounds"] = {"x": x, "y": y, "width": w, "height": h}
    return n


def window(*children):
    return node("window", "Invoices", bounds=(0, 0, 1920, 1080), children=list(children))


# ---------------------------------------------------------------------------
# Content extraction and flattening
# ---------------------------------------------------------------------------


class TestElementContent:
    def test_value_wins_over_name(self):
        """A text field keeps its contents in ``value`` and its label in ``name``."""
        assert element_content({"role": "AXTextField", "name": "Amount", "value": "150"}) == "150"

    def test_falls_back_to_name(self):
        """A label keeps its text in ``name`` — there is no value to read."""
        assert element_content({"role": "AXStaticText", "name": "Total: 100"}) == "Total: 100"

    def test_blank_value_falls_back_to_name(self):
        assert element_content({"name": "Amount", "value": "   "}) == "Amount"

    def test_missing_everything_is_empty(self):
        assert element_content({}) == ""

    def test_title_is_accepted_as_a_name(self):
        """Linux backends report ``title`` where macOS reports ``name``."""
        assert element_content({"title": "gedit"}) == "gedit"


class TestFlattenNodes:
    def test_walks_the_tree_in_order_with_paths(self):
        tree = window(node("AXStaticText", "Total: 100"), node("AXButton", "Save"))
        nodes = flatten_nodes(tree)
        assert [n.role for n in nodes] == ["window", "AXStaticText", "AXButton"]
        assert nodes[0].path == "window[0]"
        assert nodes[1].path == "window[0]/AXStaticText[0]"
        assert nodes[2].path == "window[0]/AXButton[1]"

    def test_depth_is_tracked(self):
        tree = window(node("group", "", children=[node("AXButton", "Save")]))
        assert [n.depth for n in flatten_nodes(tree)] == [0, 1, 2]

    def test_reads_objects_as_well_as_dicts(self):
        from opendesk.computer.types import Rect, UIElement

        tree = UIElement(
            role="window", name="w",
            children=[UIElement(role="AXButton", name="Save",
                                bounds=Rect(x=10, y=20, width=80, height=30))],
        )
        nodes = flatten_nodes(tree)
        assert nodes[1].content == "Save"
        assert nodes[1].bounds == (10, 20, 80, 30)

    def test_bounds_are_optional_and_degenerate_ones_are_dropped(self):
        found = flatten_nodes(window(
            node("AXStaticText", "no geometry"),
            node("AXStaticText", "zero size", bounds=(5, 5, 0, 10)),
        ))
        assert found[1].bounds is None
        assert found[2].bounds is None

    def test_ignore_roles_prunes_a_whole_subtree(self):
        """Ignoring the menu bar is how a live clock is excluded semantically."""
        tree = window(
            node("AXMenuBar", "", children=[node("AXStaticText", "09:41:00")]),
            node("AXStaticText", "Total: 100"),
        )
        roles = [n.role for n in flatten_nodes(tree, ignore_roles="menubar")]
        assert "AXMenuBar" not in roles
        assert "09:41:00" not in [n.content for n in flatten_nodes(tree, ignore_roles="menubar")]
        assert "Total: 100" in [n.content for n in flatten_nodes(tree, ignore_roles="menubar")]

    def test_ignore_roles_is_case_insensitive_and_accepts_a_list(self):
        tree = window(node("AXMenuBar"), node("AXStatusBar"), node("AXStaticText", "keep"))
        kept = [n.role for n in flatten_nodes(tree, ignore_roles=["MENUBAR", "statusbar"])]
        assert kept == ["window", "AXStaticText"]

    def test_node_and_depth_limits_bound_the_walk(self):
        tree = window(*[node("AXStaticText", f"row {i}") for i in range(50)])
        assert len(flatten_nodes(tree, max_nodes=5)) == 5

        deep = node("group", "", children=[node("group", "", children=[
            node("group", "", children=[node("AXButton", "Save")])])])
        assert len(flatten_nodes(deep, max_depth=1)) == 2


class TestWalkBounds:
    """A bound is a budget a caller opts into, and it says when it bit.

    Measured on a real Windows desktop: a Cursor window carried 442 elements, and
    a walk that stopped at 400 without saying so made ``find_elements`` answer
    *absent* for an element that was on screen and ``content_hash`` answer
    *unchanged* for a state that had changed.  Both are worse than a slow answer,
    because both are wrong in the direction of "nothing to see here".
    """

    def test_the_walk_is_unbounded_by_default(self):
        tree = window(*[node("AXStaticText", f"row {i}") for i in range(1200)])
        assert len(flatten_nodes(tree)) == 1201  # the window plus 1200 rows

    def test_a_budget_is_reported_rather_than_silent(self):
        tree = window(*[node("AXStaticText", f"row {i}") for i in range(50)])
        walk = walk_nodes(tree, max_nodes=5)
        assert len(walk.nodes) == 5
        assert walk.truncated is True
        assert walk.reason == "nodes"

    def test_a_complete_walk_says_so(self):
        tree = window(node("AXStaticText", "Total: 100"))
        walk = walk_nodes(tree, max_nodes=PROMPT_NODE_BUDGET)
        assert walk.truncated is False
        assert walk.reason is None

    def test_the_depth_bound_is_reported_too(self):
        deep = node("group", "", children=[node("group", "", children=[
            node("group", "", children=[node("AXButton", "Save")])])])
        walk = walk_nodes(deep, max_depth=1)
        assert len(walk.nodes) == 2
        assert walk.truncated is True
        assert walk.reason == "depth"

    def test_a_pruned_role_does_not_count_as_truncation(self):
        """Furniture dropped on purpose is not a walk that fell short."""
        tree = window(node("AXMenuBar"), node("AXStaticText", "keep"))
        walk = walk_nodes(tree, max_nodes=PROMPT_NODE_BUDGET, ignore_roles="menubar")
        assert [n.content for n in walk.nodes] == ["Invoices", "keep"]
        assert walk.truncated is False

    def test_an_element_past_the_old_cap_is_still_found(self):
        """Position 401 is not absent — the bug this class exists for."""
        rows = [node("AXStaticText", f"row {i}") for i in range(500)]
        tree = window(*(rows + [node("AXStaticText", "Total: 100")]))
        assert [n.name for n in find_elements(tree, name_regex=r"Total")] == ["Total: 100"]

    def test_a_capped_digest_cannot_be_mistaken_for_a_full_one(self):
        tree = window(*[node("AXStaticText", f"row {i}") for i in range(500)])
        full = content_hash(tree, ignore_roles=None)
        capped = content_hash(tree, ignore_roles=None, max_nodes=PROMPT_NODE_BUDGET)
        assert full != capped

    def test_a_change_past_the_budget_is_flagged_not_reported_as_nothing(self):
        """The dangerous shape, and the reason ``truncated`` is on the diff.

        The edit lands past the budget, so the diff genuinely saw no difference.
        Reporting a bare "no change" would assert something about a window it
        never read.
        """
        rows = [node("AXStaticText", f"row {i}") for i in range(500)]
        before = window(*rows)
        after = window(*(rows + [node("AXStaticText", "Total: 300")]))

        diff = ui_diff(before, after, max_nodes=PROMPT_NODE_BUDGET)
        assert diff.changed is False  # the edit sits past the budget
        assert diff.truncated is True  # ... and the diff admits it
        assert "truncated" in diff.summary()

    def test_an_unbudgeted_diff_sees_the_whole_window(self):
        rows = [node("AXStaticText", f"row {i}") for i in range(500)]
        before = window(*rows)
        after = window(*(rows + [node("AXStaticText", "Total: 300")]))

        diff = ui_diff(before, after)
        assert diff.truncated is False
        assert diff.changed is True
        assert "truncated" not in diff.summary()


# ---------------------------------------------------------------------------
# The diff
# ---------------------------------------------------------------------------


class TestUiDiff:
    def test_identical_trees_do_not_differ(self):
        tree = window(node("AXStaticText", "Total: 100"))
        diff = ui_diff(tree, tree)
        assert diff.changed is False
        assert diff.count == 0
        assert diff.matched == 2
        assert "No accessibility change" in diff.summary()

    def test_a_single_glyph_edit_is_a_modification(self):
        """The case pixels cannot see, and the reason this module exists.

        Keying on structure rather than on the text is what makes this ``modified``
        instead of a removal plus an addition.
        """
        before = window(node("AXStaticText", "Total: 100"))
        after = window(node("AXStaticText", "Total: 150"))
        diff = ui_diff(before, after)

        assert diff.changed is True
        assert diff.modified[0].before == "Total: 100"
        assert diff.modified[0].after == "Total: 150"
        assert diff.added == [] and diff.removed == []
        assert diff.content_changes == 1

    def test_a_field_value_edit_is_a_modification(self):
        before = window(node("AXTextField", "Amount", value="100"))
        after = window(node("AXTextField", "Amount", value="150"))
        diff = ui_diff(before, after)
        assert [c.after for c in diff.modified] == ["150"]
        assert diff.modified[0].label == "Amount"

    def test_a_dialog_opening_is_an_addition(self):
        before = window(node("AXStaticText", "Idle"))
        after = window(node("AXStaticText", "Idle"), node("AXSheet", "Confirm", children=[
            node("AXButton", "OK")]))
        diff = ui_diff(before, after)
        assert {c.role for c in diff.added} == {"AXSheet", "AXButton"}
        assert diff.removed == []
        assert diff.matched == 2

    def test_a_dismissed_dialog_is_a_removal(self):
        before = window(node("AXSheet", "Confirm", children=[node("AXButton", "OK")]))
        after = window()
        diff = ui_diff(before, after)
        assert {c.role for c in diff.removed} == {"AXSheet", "AXButton"}
        assert diff.added == []

    def test_a_clock_tick_is_not_a_change_unless_the_raw_tree_is_asked_for(self):
        """A diff answers *did this change*, so ambient churn must not count.

        Getting this wrong is not cosmetic: ``ui_diff`` backs the ``ui_changed``
        reward check, and a predicate that reports a change because a clock
        ticked is a verifiable reward reporting a change that never happened.
        """
        def frame(clock: str):
            return window(
                node("AXMenuBar", "", children=[node("AXStaticText", clock)]),
                node("AXStaticText", "Total: 100"),
            )

        assert ui_diff(frame("09:41:00"), frame("09:41:01")).changed is False
        # The furniture is still reachable, just not by default.
        assert ui_diff(frame("09:41:00"), frame("09:41:01"),
                       ignore_roles=None).changed is True

    def test_a_glyph_edit_survives_the_default_pruning(self):
        def frame(clock: str, total: str):
            return window(
                node("AXMenuBar", "", children=[node("AXStaticText", clock)]),
                node("AXStaticText", total),
            )

        diff = ui_diff(frame("09:41:00", "Total: 100"), frame("09:41:01", "Total: 150"))
        assert diff.changed is True
        assert [c.after for c in diff.modified] == ["Total: 150"]

    # -- structural churn ------------------------------------------------

    def test_an_inserted_row_does_not_make_the_tail_a_rewrite(self):
        """Ordinals shift, positions do not — the positional fallback earns its keep.

        Without it, inserting one row renumbers every sibling below and the whole
        tail reads as removed-and-added, which is both noisy and misleading.
        """
        def rows(*labels):
            return window(*[
                node("AXRow", f"row {i}", bounds=(100, 200 + i * 40, 400, 30),
                     children=[node("AXStaticText", label,
                                    bounds=(110, 205 + i * 40, 300, 20))])
                for i, label in enumerate(labels)
            ])

        before = rows("alpha", "beta")
        after = rows("new", "alpha", "beta")
        diff = ui_diff(before, after)

        # The two pre-existing rows are recognised as having moved, not rewritten.
        moved_labels = {c.label for c in diff.moved}
        assert {"alpha", "beta"} <= moved_labels or {
            c.after for c in diff.moved
        } >= {"alpha", "beta"}

    def test_a_reordering_is_reported_but_carries_no_new_information(self):
        def frame(*labels):
            return window(*[
                node("AXStaticText", label, bounds=(100, 200 + i * 40, 200, 20))
                for i, label in enumerate(labels)
            ])

        diff = ui_diff(frame("alpha", "beta"), frame("beta", "alpha"))
        assert diff.changed is True          # something did happen on screen
        assert diff.content_changes == 0     # but no content is new
        assert len(diff.moved) == 2

    def test_a_shifted_element_with_new_text_is_modified_not_replaced(self):
        """Position survives where an ordinal does not, so pair them and compare."""
        before = window(node("AXRow", "", bounds=(100, 200, 400, 30), children=[
            node("AXStaticText", "100", bounds=(110, 205, 300, 20))]))
        after = window(node("AXBanner", ""), node("AXRow", "", bounds=(100, 200, 400, 30),
                       children=[node("AXStaticText", "150", bounds=(110, 205, 300, 20))]))
        diff = ui_diff(before, after)
        assert [c.after for c in diff.modified] == ["150"]
        assert diff.added and diff.added[0].role == "AXBanner"

    def test_to_dict_shape(self):
        diff = ui_diff(window(node("AXStaticText", "a")), window(node("AXStaticText", "b")))
        d = diff.to_dict()
        assert d["changed"] is True
        assert d["content_changes"] == 1
        assert d["modified"][0]["before"] == "a"
        assert d["modified"][0]["after"] == "b"
        assert d["added"] == [] and d["removed"] == []

    def test_diff_accepts_stored_snapshots(self):
        """So a caller can keep the cheap snapshot and never re-read the tree."""
        before = ui_snapshot(window(node("AXStaticText", "100")))
        after = ui_snapshot(window(node("AXStaticText", "150")))
        diff = ui_diff(before, after)
        assert [c.after for c in diff.modified] == ["150"]

    def test_ignore_roles_applies_to_a_stored_snapshot_too(self):
        """A snapshot must not be filterable differently from a live tree."""
        def frame(clock: str):
            return ui_snapshot(window(
                node("AXMenuBar", "", children=[node("AXStaticText", clock)]),
                node("AXStaticText", "Total: 100"),
            ))

        assert ui_diff(frame("09:41:00"), frame("09:41:01"),
                       ignore_roles="menubar").changed is False

    def test_ignoring_a_container_drops_its_children(self):
        """Prefix pruning: the clock is a *child* of the menu bar."""
        tree = window(
            node("AXMenuBar", "", children=[node("AXStaticText", "09:41:00")]),
            node("AXStaticText", "Total: 100"),
        )
        assert [n.role for n in flatten_nodes(tree, ignore_roles="menubar")] == [
            "window", "AXStaticText"
        ]
        kept = filter_snapshot(ui_snapshot(tree), "menubar")
        assert "09:41:00" not in [n.content for n in kept.values()]
        assert "Total: 100" in [n.content for n in kept.values()]

    def test_diff_snapshots_is_the_same_thing(self):
        before = ui_snapshot(window(node("AXStaticText", "100")))
        after = ui_snapshot(window(node("AXStaticText", "150")))
        assert diff_snapshots(before, after).content_changes == 1


# ---------------------------------------------------------------------------
# Content queries
# ---------------------------------------------------------------------------


class TestFindElements:
    @staticmethod
    def tree():
        return window(
            node("AXStaticText", "Total", bounds=(10, 10, 50, 20)),
            node("AXTextField", "Total", value="300", bounds=(70, 10, 80, 20)),
            node("AXButton", "Save", bounds=(10, 50, 80, 30)),
        )

    def test_role_matches_as_a_case_insensitive_substring(self):
        found = find_elements(self.tree(), role="button")
        assert [n.content for n in found] == ["Save"]

    def test_value_regex_reaches_the_field_contents(self):
        """The verifiable-assertion primitive: the field now reads 300."""
        found = find_elements(self.tree(), name_regex="^Total$", value_regex=r"^300$")
        assert len(found) == 1
        assert found[0].role == "AXTextField"

    def test_a_stale_value_does_not_match(self):
        assert find_elements(self.tree(), value_regex=r"^999$") == []

    def test_content_regex_matches_either_field(self):
        found = find_elements(self.tree(), content_regex="^Total$")
        assert found[0].role == "AXStaticText"

    def test_criteria_combine_with_and(self):
        # A button does not carry the value, so the pair cannot both hold.
        assert find_elements(self.tree(), role="button", value_regex="300") == []

    def test_limit_is_honoured(self):
        wide = window(*[node("AXStaticText", "row") for _ in range(30)])
        assert len(find_elements(wide, limit=4)) == 4

    def test_ignore_roles_applies(self):
        tree = window(node("AXMenuBar", ""), node("AXButton", "Save"))
        assert [n.content for n in find_elements(tree, role="button",
                                                ignore_roles="menubar")] == ["Save"]
        assert find_elements(tree, ignore_roles="menubar", role="menubar") == []

    def test_accepts_a_snapshot(self):
        snap = ui_snapshot(self.tree())
        assert find_elements(snap, value_regex="300")[0].value == "300"


# ---------------------------------------------------------------------------
# Content identity
# ---------------------------------------------------------------------------


class TestContentHash:
    def test_stable_for_the_same_content(self):
        tree = window(node("AXStaticText", "Total: 100"))
        assert content_hash(tree) == content_hash(tree)

    def test_a_glyph_edit_changes_it(self):
        """What a perceptual fingerprint cannot do."""
        a = content_hash(window(node("AXStaticText", "Total: 100")))
        b = content_hash(window(node("AXStaticText", "Total: 150")))
        assert a != b

    def test_geometry_is_excluded(self):
        """A window nudged, or a layout reflowed, is not a new state."""
        a = content_hash(window(node("AXStaticText", "Total", bounds=(10, 10, 50, 20))))
        b = content_hash(window(node("AXStaticText", "Total", bounds=(37, 61, 50, 20))))
        assert a == b

    def test_a_reorder_is_a_new_state_but_carries_no_new_content(self):
        """Position on screen is discarded; order of content is not.

        Reordering a list is something that happened, so it is a new state — but
        it carries no *new* content, which is what ``content_changes`` reports.
        """
        def frame(*labels):
            return window(*[
                node("AXStaticText", label, bounds=(100, 200 + i * 40, 200, 20))
                for i, label in enumerate(labels)
            ])

        assert content_hash(frame("alpha", "beta")) != content_hash(frame("beta", "alpha"))
        assert ui_diff(frame("alpha", "beta"), frame("beta", "alpha")).content_changes == 0

    def test_a_clock_tick_is_not_a_new_state_by_default(self):
        """The default has to prune ambient churn or the digest is useless.

        A menu-bar clock changes every second.  If that counted, a ten-step
        episode would produce ten states on a real desktop and the transition
        graph would say nothing — the digest would be *worse* than a pixel hash,
        since the pixel hash ignores a clock tick and this would not.
        """
        def frame(clock: str):
            return window(
                node("AXMenuBar", "", children=[node("AXStaticText", clock)]),
                node("AXStaticText", "Total: 100"),
            )

        assert content_hash(frame("09:41:00")) == content_hash(frame("09:41:01"))

    def test_ambient_churn_is_still_there_when_asked_for_raw(self):
        """Pruning is a default, not a blindfold.

        ``ignore_roles=None`` means "everything", so a caller who genuinely wants
        the raw content — to prove the clock moved, say — can still get it.
        """
        def frame(clock: str):
            return window(
                node("AXMenuBar", "", children=[node("AXStaticText", clock)]),
                node("AXStaticText", "Total: 100"),
            )

        assert content_hash(frame("09:41:00"), ignore_roles=None) != \
            content_hash(frame("09:41:01"), ignore_roles=None)

    def test_an_open_menu_is_not_pruned(self):
        """"menubar" must not swallow a dropdown ▸ item.

        An open File menu is interface the agent is interacting with; only the
        bar itself is furniture.
        """
        def frame(menu_open: bool):
            bar = node("AXMenuBar", "", children=[node("AXStaticText", "09:41:00")])
            kids = [bar]
            if menu_open:
                kids.append(node("AXMenu", "File", children=[
                    node("AXMenuItem", "Save"),
                ]))
            return window(*kids)

        assert content_hash(frame(False)) != content_hash(frame(True))

    def test_length_is_short_enough_for_a_log(self):
        assert len(content_hash(window(node("AXStaticText", "x")))) == 12


# ---------------------------------------------------------------------------
def ue(role: str, name: str = "", *, value=None, children=None):
    """A real UIElement — the ui tool walks attributes, not dict keys."""
    from opendesk.computer.types import UIElement

    return UIElement(role=role, name=name, value=value, children=list(children or []))


def uw(*children):
    return ue("window", "Invoices", children=list(children))


# The semantic channel in the ui tool — keyboard edits and their digest
# ---------------------------------------------------------------------------


class TreeComputer(FakeComputer):
    """A fake whose tree the test owns, and which mutates it on a keystroke.

    ``mutate_to`` models what the interface *becomes* once the keystrokes land.
    Leave it ``None`` to model keystrokes that reach nothing editable — the case
    an agent cannot distinguish from success without looking.
    """

    def __init__(self, tree, *, readable: bool = True) -> None:
        super().__init__()
        self.tree = tree
        self.mutate_to = None
        self.readable = readable
        self.tree_reads = 0

    async def ui_tree(self, *, window_id=None, app=None, max_depth=8):
        if not self.readable:
            raise RuntimeError("accessibility unavailable")
        self.tree_reads += 1
        return self.tree

    async def text(self, text_input) -> None:
        self._record("text", text=text_input.text)
        if self.mutate_to is not None:
            self.tree = self.mutate_to

    async def key(self, event) -> None:
        self._record("key", keysym=event.keysym)
        if self.mutate_to is not None and event.action.value == "down":
            self.tree = self.mutate_to


def ui_ctx(session: str, computer) -> ToolContext:
    clear_sandbox(session)
    return ToolContext(session_id=session, computer=computer)


def full(**kw):
    fields = {"action": "get_tree", "app": "Notes"}
    fields.update(kw)
    return UITool().parse_params(fields)


class TestKeyboardEditsAreObserved:
    """``type``/``press_key`` mutate the interface without reading a tree.

    Left alone they stamp whatever digest an *earlier* action happened to leave,
    so an edit they made is credited to whichever step next read a tree — or to
    no step at all, if none did.
    """

    @pytest.mark.asyncio
    async def test_type_stamps_a_digest_of_the_current_tree(self):
        total = uw(ue("AXTextField", "Total", value="100"))
        comp = TreeComputer(total)
        ctx = ui_ctx("ui-type", comp)

        r = await UITool().execute(ctx, full(action="type", text="150"))
        assert not r.error
        assert get_sandbox("ui-type").current_ui == content_hash(total)

    @pytest.mark.asyncio
    async def test_the_stamp_is_not_the_previous_actions_digest(self):
        """The failure this fixes: a stale digest makes the graph lie.

        The click read the tree before an edit; the edit changed it.  If the
        keystroke re-stamped the click's digest, the two actions would read as
        the same state and neither would get credit for the change.
        """
        first = uw(ue("AXTextField", "Total", value="100"))
        second = uw(ue("AXTextField", "Total", value="150"))

        comp = TreeComputer(first)
        ctx = ui_ctx("ui-stale", comp)
        tool = UITool()

        await tool.execute(ctx, full(action="get_tree"))
        stale = get_sandbox("ui-stale").current_ui

        comp.tree = second            # the world moved on
        await tool.execute(ctx, full(action="type", text="150"))

        fresh = get_sandbox("ui-stale").current_ui
        assert fresh == content_hash(second)
        assert fresh != stale

    @pytest.mark.asyncio
    async def test_press_key_stamps_a_digest(self):
        before = uw(ue("AXStaticText", "Untitled"))
        comp = TreeComputer(before)
        ctx = ui_ctx("ui-key", comp)

        comp.mutate_to = uw(ue("AXStaticText", "Saved"))
        r = await UITool().execute(ctx, full(action="press_key", key="return"))
        assert not r.error
        assert get_sandbox("ui-key").current_ui == content_hash(before)

    @pytest.mark.asyncio
    async def test_an_unreadable_tree_does_not_block_typing(self):
        """A keyboard action works where accessibility does not.

        Refusing to type because the tree cannot be read would trade a working
        deployment for a tidier log.
        """
        comp = TreeComputer(None, readable=False)
        ctx = ui_ctx("ui-notree", comp)

        r = await UITool().execute(ctx, full(action="type", text="hello"))
        assert not r.error
        assert "hello" in r.output
        assert ("text", {"text": "hello"}) in comp.calls
        assert get_sandbox("ui-notree").current_ui is None


class TestVerifyFlag:
    """Opt-in: did the keystrokes actually land?"""

    @pytest.mark.asyncio
    async def test_reports_a_content_change(self):
        before = uw(ue("AXTextField", "Total", value="100"))
        comp = TreeComputer(before)
        ctx = ui_ctx("ui-v-ok", comp)
        comp.mutate_to = uw(ue("AXTextField", "Total", value="150"))

        r = await UITool().execute(
            ctx, full(action="type", text="150", verify=True)
        )
        assert "content changed" in r.output

    @pytest.mark.asyncio
    async def test_reports_that_nothing_landed(self):
        """The case that matters: keystrokes into a field that is not focused."""
        before = uw(ue("AXTextField", "Total", value="100"))
        comp = TreeComputer(before)          # mutate_to stays None
        ctx = ui_ctx("ui-v-same", comp)

        r = await UITool().execute(
            ctx, full(action="type", text="150", verify=True)
        )
        assert "UNCHANGED" in r.output
        assert not r.error                   # a no-op keystroke is not a failure

    @pytest.mark.asyncio
    async def test_is_off_by_default(self):
        before = uw(ue("AXTextField", "Total", value="100"))
        comp = TreeComputer(before)
        ctx = ui_ctx("ui-v-off", comp)

        r = await UITool().execute(ctx, full(action="type", text="150"))
        assert "verification" not in r.output
        assert comp.tree_reads == 1          # only the pre-action stamp

    @pytest.mark.asyncio
    async def test_says_unavailable_rather_than_claiming_success(self):
        """Unknown is not the same as unchanged, and must not read as either."""
        comp = TreeComputer(None, readable=False)
        ctx = ui_ctx("ui-v-none", comp)

        r = await UITool().execute(
            ctx, full(action="type", text="150", verify=True)
        )
        assert "unavailable" in r.output
        assert "UNCHANGED" not in r.output and "changed" not in r.output.replace(
            "unavailable", ""
        )

    @pytest.mark.asyncio
    async def test_a_ticking_clock_does_not_read_as_a_landed_edit(self):
        """Why this is content and not pixels, and why ambient roles are pruned.

        A clock ticking between the two reads changes the screen.  It must not
        make an inert keystroke look like it worked.
        """
        def frame(clock: str):
            return uw(
                ue("AXMenuBar", "", children=[ue("AXStaticText", clock)]),
                ue("AXTextField", "Total", value="100"),
            )

        comp = TreeComputer(frame("09:41:00"))
        comp.mutate_to = frame("09:41:01")   # only the clock moved
        ctx = ui_ctx("ui-v-clock", comp)

        r = await UITool().execute(
            ctx, full(action="type", text="150", verify=True)
        )
        assert "UNCHANGED" in r.output
