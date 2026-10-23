"""Tests for visual memory (g1) and state-transition diagnosis (g3)."""

from __future__ import annotations

import io

import pytest

from opendesk.computer.capture import fingerprint_distance, screen_fingerprint
from opendesk.computer.a11y import ui_snapshot
from opendesk.computer.diagnostics import diagnose, step_effect_signals
from opendesk.computer.observations import ObservationStore, get_store, clear_store
from opendesk.computer.sandbox import ActionType, clear_sandbox, get_sandbox
from tests._fakes import FakeComputer
from opendesk.tools.base import ToolContext
from opendesk.tools.diagnose import DiagnoseTool


def make_png(seed: int = 0, size: tuple[int, int] = (64, 48)) -> bytes:
    """A small PNG whose content varies with *seed* (real bytes, not a stub)."""
    from PIL import Image

    img = Image.new("RGB", size)
    w, h = size
    img.putdata([
        ((x * 7 + y * 13 + seed * 97) % 256,
         (x * 3 + seed * 11) % 256,
         (y * 5 + seed * 29) % 256)
        for y in range(h) for x in range(w)
    ])
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def ctx_for(session_id: str) -> ToolContext:
    return ToolContext(session_id=session_id, computer=FakeComputer())


def entry(action: str, screen: str | None, *, error: bool = False, ts: float = 0.0) -> dict:
    return {"action": action, "screen": screen, "error": error, "timestamp": ts,
            "params": {}, "result": None}


# ---------------------------------------------------------------------------
# Screen fingerprints
# ---------------------------------------------------------------------------


class TestFingerprint:
    def test_is_stable_and_hex(self):
        png = make_png(0)
        fp = screen_fingerprint(png)
        assert fp == screen_fingerprint(png)
        assert len(fp) == 64
        int(fp, 16)  # parses as hex

    def test_identical_images_are_zero_distance(self):
        png = make_png(1)
        assert fingerprint_distance(
            screen_fingerprint(png), screen_fingerprint(png)
        ) == 0

    def test_different_images_differ(self):
        a = screen_fingerprint(make_png(1))
        b = screen_fingerprint(make_png(2))
        assert fingerprint_distance(a, b) > 0

    def test_hash_size_controls_length(self):
        fp = screen_fingerprint(make_png(3), hash_size=8)
        assert len(fp) == 16

    def test_distance_handles_missing(self):
        assert fingerprint_distance(None, "abc") == 9999
        assert fingerprint_distance("abc", None) == 9999
        assert fingerprint_distance(None, None) == 9999

    def test_distance_handles_mismatched_sizes(self):
        assert fingerprint_distance("ff", "ffff") == -1


# ---------------------------------------------------------------------------
# Pixel diff — measuring change, not a fraction of the screen
# ---------------------------------------------------------------------------


class TestScreenshotDiff:
    """``diff_screenshots`` decides "did pixels change" — it must measure them.

    The verdict used to require ≥ 0.1% of the *whole screen*, which a small
    edit on a large display never reaches, so real edits were reported as "no
    change".  ``screen_changed`` and goal-state similarity read that verdict.
    """

    @staticmethod
    def _solid(size=(800, 600), color=(240, 240, 240)) -> bytes:
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", size, color).save(buf, format="PNG")
        return buf.getvalue()

    @staticmethod
    def _patch(png: bytes, box, color=(10, 10, 10)) -> bytes:
        from PIL import Image, ImageDraw

        img = Image.open(io.BytesIO(png)).convert("RGB")
        ImageDraw.Draw(img).rectangle(box, fill=color)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def test_identical_screens_report_no_change(self):
        from opendesk.computer.capture import diff_screenshots

        png = self._solid()
        report = diff_screenshots(png, png)
        assert report["changed"] is False
        assert report["changed_pixels"] == 0
        assert report["changed_region"] is None

    def test_small_local_edit_is_detected(self):
        """A 20x20 edit is 0.083% of an 800x600 screen — under the old floor."""
        from opendesk.computer.capture import diff_screenshots

        before = self._solid()
        after = self._patch(before, [100, 100, 119, 119])
        report = diff_screenshots(before, after)
        assert report["change_fraction"] < 0.001      # a tiny fraction...
        assert report["changed"] is True              # ...but still a change
        assert report["changed_pixels"] == 400
        assert report["changed_region"] == [100, 100, 20, 20]
        assert report["region_density"] == pytest.approx(1.0)

    def test_scattered_speckle_is_not_a_change(self):
        """Diffuse pixels span a wide box while filling little of it."""
        from PIL import Image

        from opendesk.computer.capture import diff_screenshots

        before = self._solid()
        img = Image.open(io.BytesIO(before)).convert("RGB")
        px = img.load()
        for i in range(100):
            px[(i * 37) % 800, (i * 91) % 600] = (0, 0, 0)
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        report = diff_screenshots(before, buf.getvalue())
        assert report["changed_pixels"] >= 24         # past the absolute floor
        assert report["region_density"] < 0.02        # but not concentrated
        assert report["changed"] is False

    def test_min_pixels_is_overridable(self):
        from opendesk.computer.capture import diff_screenshots

        before = self._solid()
        after = self._patch(before, [10, 10, 29, 29])
        assert diff_screenshots(before, after)["changed"] is True
        assert diff_screenshots(before, after, min_pixels=100_000)["changed"] is False

    def test_resolution_change_is_a_change(self):
        from opendesk.computer.capture import diff_screenshots

        report = diff_screenshots(self._solid((800, 600)), self._solid((1024, 768)))
        assert report["changed"] is True
        assert report["change_fraction"] == 1.0
        assert report["changed_pixels"] is None       # no comparable grid

    def test_report_shape_is_stable(self):
        from opendesk.computer.capture import diff_screenshots

        keys = {"changed", "changed_pixels", "change_fraction", "changed_region",
                "region_area", "region_density", "suppressed_pixels",
                "ignored_regions", "summary"}
        report = diff_screenshots(self._solid(), self._patch(self._solid(), [1, 1, 5, 5]))
        assert keys <= set(report)
        assert isinstance(report["summary"], str) and report["summary"]

    # -- ignoring ambient churn -----------------------------------------

    def test_change_inside_an_ignored_region_is_not_a_change(self):
        """A ticking clock is real pixels; excluding where it lives is the fix."""
        from opendesk.computer.capture import diff_screenshots

        before = self._solid()
        after = self._patch(before, [700, 10, 759, 39])       # "clock" top-right
        assert diff_screenshots(before, after)["changed"] is True

        report = diff_screenshots(before, after, ignore_regions=[[700, 0, 60, 60]])
        assert report["changed"] is False
        assert report["changed_pixels"] == 0
        assert report["suppressed_pixels"] == 60 * 30
        assert report["ignored_regions"] == [[700, 0, 60, 60]]

    def test_change_outside_an_ignored_region_still_counts(self):
        from opendesk.computer.capture import diff_screenshots

        before = self._solid()
        after = self._patch(before, [100, 400, 139, 439])      # real edit, elsewhere
        report = diff_screenshots(before, after, ignore_regions=[[700, 0, 60, 60]])
        assert report["changed"] is True
        assert report["changed_pixels"] == 40 * 40
        assert report["suppressed_pixels"] == 0

    def test_ignored_regions_do_not_leak_into_the_reported_region(self):
        from opendesk.computer.capture import diff_screenshots

        before = self._solid()
        after = self._patch(self._patch(before, [700, 10, 759, 39]), [100, 100, 119, 119])
        report = diff_screenshots(before, after, ignore_regions=[[700, 0, 60, 60]])
        assert report["changed"] is True
        # bbox must point at the real edit, not the excluded clock.
        assert report["changed_region"] == [100, 100, 20, 20]

    def test_ignored_regions_are_clamped_and_validated(self):
        from opendesk.computer.capture import diff_screenshots

        before = self._solid()
        after = self._patch(before, [700, 10, 759, 39])
        report = diff_screenshots(
            before, after,
            ignore_regions=[
                [700, 0, 60, 60],       # fine
                [-50, -50, 100, 100],   # starts off-screen, still usable
                [5000, 5000, 10, 10],   # entirely off-screen -> dropped
                [10, 10, 0, 40],        # zero width -> dropped
                "nonsense",             # malformed -> dropped
            ],
        )
        assert report["changed"] is False
        assert report["ignored_regions"] == [[700, 0, 60, 60], [0, 0, 50, 50]]

    def test_absent_ignore_regions_keeps_old_behaviour(self):
        from opendesk.computer.capture import diff_screenshots

        before = self._solid()
        after = self._patch(before, [700, 10, 759, 39])
        for regions in (None, []):
            report = diff_screenshots(before, after, ignore_regions=regions)
            assert report["changed"] is True
            assert report["suppressed_pixels"] == 0
            assert report["ignored_regions"] is None


class TestRegionsForRoles:
    """Deriving exclusion boxes from the accessibility tree, not hardcoded pixels."""

    @staticmethod
    def _tree():
        return {
            "role": "window",
            "name": "Invoices",
            "bounds": {"x": 0, "y": 0, "width": 1920, "height": 1080},
            "children": [
                {"role": "AXMenuBar", "name": "",
                 "bounds": {"x": 0, "y": 0, "width": 1920, "height": 24}},
                {"role": "AXMenuBarItem", "name": "File",
                 "bounds": {"x": 12, "y": 2, "width": 40, "height": 20}},
                {"role": "AXStaticText", "name": "09:41",
                 "bounds": {"x": 1800, "y": 4, "width": 60, "height": 18}},
                {"role": "AXButton", "name": "Save",
                 "bounds": {"x": 100, "y": 900, "width": 80, "height": 30}},
                {"role": "AXImage", "name": "logo"},          # no bounds -> skipped
            ],
        }

    def test_matches_role_by_case_insensitive_substring(self):
        from opendesk.computer.capture import regions_for_roles

        boxes = regions_for_roles(self._tree(), "menubar")
        assert {"x": 0, "y": 0, "width": 1920, "height": 24} in [
            {"x": b[0], "y": b[1], "width": b[2], "height": b[3]} for b in boxes
        ]

    def test_accepts_a_list_of_roles(self):
        from opendesk.computer.capture import regions_for_roles

        boxes = regions_for_roles(self._tree(), ["MenuBar", "StaticText"])
        assert len(boxes) == 3          # menubar, menubar item, clock text

    def test_skips_elements_without_usable_geometry(self):
        from opendesk.computer.capture import regions_for_roles

        assert regions_for_roles(self._tree(), "image") == []

    def test_unmatched_roles_yield_nothing(self):
        from opendesk.computer.capture import regions_for_roles

        assert regions_for_roles(self._tree(), "AXSheet") == []
        assert regions_for_roles(self._tree(), "") == []

    def test_works_with_objects_not_just_dicts(self):
        from opendesk.computer.capture import regions_for_roles
        from opendesk.computer.types import Rect, UIElement

        tree = UIElement(
            role="window", name="w",
            children=[UIElement(role="AXMenuBar", name="",
                                bounds=Rect(x=0, y=0, width=1920, height=24))],
        )
        assert regions_for_roles(tree, "menubar") == [[0, 0, 1920, 24]]

    def test_boxes_feed_straight_into_a_diff(self):
        """The two functions compose: locate the churn, then exclude it."""
        from opendesk.computer.capture import diff_screenshots, regions_for_roles
        from PIL import Image, ImageDraw

        buf = io.BytesIO()
        Image.new("RGB", (1920, 1080), (240, 240, 240)).save(buf, format="PNG")
        before = buf.getvalue()
        img = Image.open(io.BytesIO(before)).convert("RGB")
        ImageDraw.Draw(img).rectangle([1800, 4, 1859, 21], fill=(0, 0, 0))
        buf2 = io.BytesIO()
        img.save(buf2, format="PNG")

        regions = regions_for_roles(self._tree(), ["MenuBar", "StaticText"])
        report = diff_screenshots(before, buf2.getvalue(), ignore_regions=regions)
        assert report["changed"] is False
        assert report["suppressed_pixels"] > 0


# ---------------------------------------------------------------------------
# Observation store
# ---------------------------------------------------------------------------


class TestObservationStore:
    def test_record_and_lookup(self):
        s = ObservationStore("t", cap=10)
        a = s.record(make_png(0), width=10, height=10, fingerprint="aa", app="App1")
        b = s.record(make_png(1), width=10, height=10, fingerprint="bb", app="App2")
        assert len(s) == 2
        assert s.latest() is b
        assert s.previous() is a
        assert s.first() is a
        assert s.get(0) is a
        assert s.get(1) is b
        assert s.get(99) is None

    def test_indices_are_absolute_across_eviction(self):
        s = ObservationStore("t", cap=2)
        for i in range(5):
            s.record(make_png(i), fingerprint=f"f{i}")
        assert [o.index for o in s.all()] == [3, 4]
        assert s.evicted == 3
        assert s.get(3) is not None
        assert s.get(0) is None

    def test_resolve_accepts_names_and_offsets(self):
        s = ObservationStore("t", cap=10)
        for i in range(4):
            s.record(make_png(i), fingerprint=f"f{i}")
        assert s.resolve("latest").index == 3
        assert s.resolve(None).index == 3
        assert s.resolve("first").index == 0
        assert s.resolve("previous").index == 2
        assert s.resolve(1).index == 1
        assert s.resolve("1").index == 1
        assert s.resolve(-1).index == 3
        assert s.resolve(-2).index == 2
        assert s.resolve(-99) is None
        assert s.resolve("nonsense") is None

    def test_find_filters(self):
        s = ObservationStore("t")
        s.record(make_png(0), fingerprint="a", app="Chrome", window="Invoices")
        s.record(make_png(1), fingerprint="b", app="Finder", window="Downloads")
        s.record(make_png(2), fingerprint="c", app="Chrome", window="Settings")
        assert len(s.find(app="chrome")) == 2
        assert len(s.find(text="invoices")) == 1
        assert len(s.find(app="chrome", limit=1)) == 1
        assert s.find(app="nope") == []

    def test_stats_and_clear(self):
        s = ObservationStore("t", cap=3)
        for i in range(5):
            s.record(make_png(i), fingerprint=f"f{i}")
        st = s.stats()
        assert st["held"] == 3 and st["evicted"] == 2
        assert st["lossless"] is True
        assert st["distinct_screens"] == 3
        assert s.clear() == 3
        assert len(s) == 0

    def test_timeline_limit(self):
        s = ObservationStore("t")
        for i in range(5):
            s.record(make_png(i), fingerprint=f"f{i}")
        assert len(s.timeline(2)) == 2
        assert s.timeline()[0].index == 0

    def test_session_registry(self):
        clear_store("reg-1")
        a = get_store("reg-1")
        b = get_store("reg-1")
        assert a is b
        assert get_store("reg-1", cap=5).cap == 5


# ---------------------------------------------------------------------------
# MemoryTool
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------


FP0 = "0000000000000000"
FP1 = "000000000000ffff"   # 16 bits from FP0 — safely beyond tolerance
FP2 = "ffffffffffff0000"   # 16 bits from FP0, 64 from FP1
FP_NEAR = "0000000000000001"  # 1 bit from FP0 — the same functional screen


class TestDiagnose:
    def test_empty_input(self):
        report = diagnose([])
        assert report.state_count == 0
        assert report.step_count == 0

    def test_skips_entries_without_screen(self):
        report = diagnose([entry("mouse_click", None), entry("mouse_click", None)])
        assert report.skipped == 2
        assert report.state_count == 0

    def test_builds_states_and_transitions(self):
        report = diagnose([
            entry("mouse_click", FP0),
            entry("keyboard_type", FP1),
            entry("ui_action", FP2),
        ])
        assert report.state_count == 3
        assert report.step_count == 3
        edges = {(t.src, t.dst, t.action) for t in report.transitions}
        assert ("S0", "S1", "mouse_click") in edges
        assert ("S1", "S2", "keyboard_type") in edges

    def test_near_identical_screens_merge(self):
        # FP0 and FP_NEAR differ by 1 bit — one functional state.
        report = diagnose([entry("ui_action", FP0), entry("ui_action", FP_NEAR)])
        assert report.state_count == 1
        assert report.fused_count == 1
        assert report.nodes["S0"].visits == 2
        assert report.nodes["S0"].screens == {FP0, FP_NEAR}

    def test_tolerance_zero_keeps_them_apart(self):
        report = diagnose(
            [entry("ui_action", FP0), entry("ui_action", FP_NEAR)], tolerance=0
        )
        assert report.state_count == 2

    def test_errors_land_in_bottlenecks(self):
        report = diagnose([
            entry("mouse_click", FP0),
            entry("ui_action", FP1),
            entry("ui_action", FP2, error=True),
            entry("ui_action", FP2, error=True),
        ])
        assert report.error_count == 2
        assert report.bottlenecks
        assert report.bottlenecks[0]["state"] == "S2"
        assert report.bottlenecks[0]["errors"] == 2

    def test_bottleneck_concentration(self):
        report = diagnose([
            entry("ui_action", FP0, error=True),
            entry("ui_action", FP1),
            entry("ui_action", FP2),
            entry("ui_action", FP0, error=True),
        ])
        # One of three states holds every error.
        assert report.bottleneck_concentration() == pytest.approx(1.0)

    def test_detects_no_effect_inertia(self):
        report = diagnose([
            entry("ui_action", FP0),
            entry("ui_action", FP2),
            entry("ui_action", FP2),
            entry("ui_action", FP2),
        ])
        # three consecutive actions from the same state, changing nothing
        assert report.no_effect_count == 2
        assert report.inertia
        assert report.inertia[0]["length"] == 2
        assert report.inertia[0]["action"] == "ui_action"

    def test_single_no_effect_is_not_inertia(self):
        report = diagnose([entry("ui_action", FP0), entry("ui_action", FP0)])
        assert report.no_effect_count == 1
        assert report.inertia == []

    def test_detects_self_loop(self):
        report = diagnose([
            entry("ui_action", FP0),
            entry("ui_action", FP2),
            entry("ui_action", FP2),
        ])
        assert report.loops
        assert report.loops[0]["from"] == "S1"
        assert report.loops[0]["to"] == "S1"

    def test_detects_dead_end(self):
        report = diagnose([
            entry("mouse_click", FP0),
            entry("ui_action", FP2),
        ])
        assert [d["state"] for d in report.dead_ends] == ["S1"]

    def test_passive_actions_do_not_create_edges(self):
        report = diagnose([
            entry("screenshot", FP0),
            entry("mouse_click", FP1),
        ])
        assert all(t.action != "screenshot" for t in report.transitions)

    def test_step_effect_signals(self):
        steps = step_effect_signals([
            entry("ui_action", FP0),
            entry("ui_action", FP0),
            entry("ui_action", FP2),
        ])
        assert [s["effect"] for s in steps] == ["same", "changed", "none"]

    def test_as_dict_and_summary_shape(self):
        report = diagnose([entry("ui_action", FP0), entry("ui_action", FP2)])
        d = report.as_dict()
        assert d["metrics"]["steps"] == 2
        assert d["metrics"]["states"] == 2
        assert isinstance(d["states"], list)
        assert "State-transition diagnosis" in report.summary_text()


class TestDiagnoseTool:
    def fresh_session(self, sid: str):
        clear_sandbox(sid)
        return get_sandbox(sid), ctx_for(sid)

    @pytest.mark.asyncio
    async def test_empty_session(self):
        sb, ctx = self.fresh_session("dt-1")
        tool = DiagnoseTool()
        r = await tool.execute(ctx, tool.parse_params({}))
        assert "nothing to diagnose" in r.output.lower()

    @pytest.mark.asyncio
    async def test_reports_on_recorded_actions(self):
        sb, ctx = self.fresh_session("dt-2")
        sb.current_screen = FP0
        await sb.record_action(ActionType.UI_ACTION, {})
        sb.current_screen = FP2
        await sb.record_action(ActionType.UI_ACTION, {})

        tool = DiagnoseTool()
        r = await tool.execute(ctx, tool.parse_params({"action": "report"}))
        assert not r.error
        assert "State-transition diagnosis" in r.output
        assert r.metadata["states"] == 2

    @pytest.mark.asyncio
    async def test_json_output_parses(self):
        import json

        sb, ctx = self.fresh_session("dt-3")
        sb.current_screen = FP0
        await sb.record_action(ActionType.UI_ACTION, {})

        tool = DiagnoseTool()
        r = await tool.execute(ctx, tool.parse_params({"action": "json"}))
        assert json.loads(r.output)["metrics"]["states"] == 1

    @pytest.mark.asyncio
    async def test_warns_when_no_fingerprints(self):
        sb, ctx = self.fresh_session("dt-4")
        await sb.record_action(ActionType.UI_ACTION, {})
        tool = DiagnoseTool()
        r = await tool.execute(ctx, tool.parse_params({}))
        assert "no state graph" in r.output.lower()


# ---------------------------------------------------------------------------
# Accessibility content in the observation memory
# ---------------------------------------------------------------------------


def a11y_tree(*children):
    from opendesk.computer.types import UIElement

    return UIElement(role="window", name="Invoices", children=list(children))


def a11y_node(role: str, name: str = "", *, value=None, children=None):
    from opendesk.computer.types import UIElement

    return UIElement(role=role, name=name, value=value, children=list(children or []))


class TestObservationAccessibilityContent:
    """The tree snapshot is what a content assertion reads later."""

    def test_snapshot_round_trips_through_the_store(self):

        clear_store("obs-ui-1")
        store = get_store("obs-ui-1")
        snap = ui_snapshot(a11y_tree(a11y_node("AXStaticText", "Total: 100")))
        obs = store.record(make_png(0), width=64, height=48, ui_snapshot=snap)

        assert obs.ui_snapshot is not None
        assert len(obs.ui_snapshot) == len(snap)
        assert store.latest().ui_snapshot is not None

    def test_summary_counts_the_elements(self):

        clear_store("obs-ui-2")
        snap = ui_snapshot(a11y_tree(a11y_node("AXStaticText", "a"),
                                    a11y_node("AXStaticText", "b")))
        obs = get_store("obs-ui-2").record(make_png(0), width=64, height=48,
                                           ui_snapshot=snap)
        assert obs.summary()["ui_elements"] == 3

    def test_an_observation_without_a_tree_says_nothing_extra(self):
        clear_store("obs-ui-3")
        obs = get_store("obs-ui-3").record(make_png(0), width=64, height=48)
        assert obs.ui_snapshot is None
        assert "ui_elements" not in obs.summary()

    def test_find_reaches_the_content_a_screen_merely_showed(self):
        """Free-text search over what the screen *said*, not just its labels."""

        clear_store("obs-ui-4")
        store = get_store("obs-ui-4")
        store.record(make_png(0), width=64, height=48, app="Numbers",
                     ui_snapshot=ui_snapshot(a11y_tree(
                         a11y_node("AXTextField", "Amount", value="1234.56"))))
        assert len(store.find(text="1234.56")) == 1
        assert store.find(text="9999.99") == []

    def test_snapshots_stored_as_dicts_are_also_searchable(self):
        clear_store("obs-ui-5")
        store = get_store("obs-ui-5")
        store.record(make_png(0), width=64, height=48, ui_snapshot={
            "window[0]": {"role": "AXButton", "name": "Reconcile"},
        })
        assert len(store.find(text="reconcile")) == 1


class PngComputer(FakeComputer):
    """A fake whose capture returns bytes Pillow can actually open."""

    def __init__(self, tree=None) -> None:
        super().__init__()
        self._tree = tree

    async def capture(self, *, display_id=None, region=None, downscale=True):
        from opendesk.computer.types import Pixmap, PixmapFormat

        return Pixmap(
            data=make_png(3), format=PixmapFormat.PNG,
            width=64, height=48, logical_width=64, logical_height=48,
        )

    async def ui_tree(self, *, window_id=None, app=None, max_depth=8):
        return self._tree if self._tree is not None else await super().ui_tree(
            window_id=window_id, app=app, max_depth=max_depth
        )


class TestScreenshotToolRecordsObservations:
    """Regression: ``_remember`` was called but never defined.

    The call sat inside ``except Exception: pass``, so every capture silently
    failed to reach the observation store — which left ``memory`` empty and
    ``screen_changed`` with no reference, in real use, with no error anywhere.
    """

    @staticmethod
    def tool_ctx(session: str, computer) -> ToolContext:
        return ToolContext(session_id=session, computer=computer)

    @pytest.mark.asyncio
    async def test_a_capture_lands_in_the_observation_store(self):
        from opendesk.tools.screenshot import ScreenshotTool

        session = "shot-1"
        clear_store(session)
        clear_sandbox(session)

        tool = ScreenshotTool()
        result = await tool.execute(
            self.tool_ctx(session, FakeComputer()), tool.parse_params({})
        )
        assert not result.error
        assert len(get_store(session)) == 1

        obs = get_store(session).latest()
        assert obs.width == 100 and obs.height == 100
        assert obs.app == "Fake.app"          # from focused_window()
        assert obs.png                          # the bytes really were kept

    @pytest.mark.asyncio
    async def test_plain_capture_records_no_tree(self):
        from opendesk.tools.screenshot import ScreenshotTool

        session = "shot-2"
        clear_store(session)
        clear_sandbox(session)

        tool = ScreenshotTool()
        await tool.execute(self.tool_ctx(session, FakeComputer()), tool.parse_params({}))
        assert get_store(session).latest().ui_snapshot is None

    @pytest.mark.asyncio
    async def test_tree_true_records_the_content_snapshot(self):
        from opendesk.computer.a11y import content_hash
        from opendesk.tools.screenshot import ScreenshotTool

        session = "shot-3"
        clear_store(session)
        clear_sandbox(session)

        computer = PngComputer()
        tool = ScreenshotTool()
        result = await tool.execute(
            self.tool_ctx(session, computer), tool.parse_params({"tree": True})
        )
        assert not result.error

        obs = get_store(session).latest()
        assert obs.ui_snapshot is not None
        assert "Save" in [n.content for n in obs.ui_snapshot.values()]

        # The digest lands on the sandbox too, so the actions that follow carry
        # it and the state graph can group by content.
        digest = get_sandbox(session).current_ui
        assert digest == content_hash(await computer.ui_tree())
        assert result.metadata["ui_elements"] == len(obs.ui_snapshot)
        assert result.metadata["ui_digest"] == digest

    @pytest.mark.asyncio
    async def test_marks_implies_tree_capture(self):
        """Marks already read the tree, so nothing extra is fetched or lost."""
        from opendesk.tools.screenshot import ScreenshotTool

        session = "shot-4"
        clear_store(session)
        clear_sandbox(session)

        computer = PngComputer()
        tool = ScreenshotTool()
        result = await tool.execute(
            self.tool_ctx(session, computer), tool.parse_params({"marks": True})
        )
        assert not result.error
        assert get_store(session).latest().ui_snapshot is not None

    @pytest.mark.asyncio
    async def test_a_snapshot_lets_ui_changed_work_end_to_end(self):
        """Capture two screens, then assert the content changed between them."""
        from opendesk.tools.screenshot import ScreenshotTool
        from opendesk.learning import rewards
        from opendesk.tools.base import ToolContext as Ctx

        session = "shot-5"
        clear_store(session)
        clear_sandbox(session)

        tool = ScreenshotTool()
        for total in ("Total: 100", "Total: 150"):
            tree = a11y_tree(a11y_node("AXStaticText", total))
            await tool.execute(
                Ctx(session_id=session, computer=PngComputer(tree)),
                tool.parse_params({"tree": True}),
            )

        assert len(get_store(session)) == 2
        report = await rewards.evaluate({"task": "t", "checks": [
            {"kind": "ui_changed", "ref": 0},
        ]}, ctx=Ctx(session_id=session, computer=PngComputer()), session_id=session)
        assert report.passed
        assert report.results[0].evidence["modified"]

    @pytest.mark.asyncio
    async def test_an_unchanged_screen_is_not_a_change(self):
        from opendesk.tools.screenshot import ScreenshotTool
        from opendesk.learning import rewards
        from opendesk.tools.base import ToolContext as Ctx

        session = "shot-6"
        clear_store(session)
        clear_sandbox(session)

        tool = ScreenshotTool()
        for _ in range(2):
            tree = a11y_tree(a11y_node("AXStaticText", "Total: 150"))
            await tool.execute(
                Ctx(session_id=session, computer=PngComputer(tree)),
                tool.parse_params({"tree": True}),
            )

        report = await rewards.evaluate({"task": "t", "checks": [
            {"kind": "ui_changed", "ref": 0},
        ]}, ctx=Ctx(session_id=session, computer=PngComputer()), session_id=session)
        assert not report.passed

    @pytest.mark.asyncio
    async def test_ui_tool_refreshes_the_content_digest(self):
        """Reading the tree for a click is enough to keep the digest current."""
        from opendesk.tools.ui import UITool

        session = "shot-7"
        clear_sandbox(session)
        sandbox = get_sandbox(session)

        tool = UITool()
        await tool.execute(
            self.tool_ctx(session, FakeComputer()),
            tool.parse_params({"action": "get_tree", "app": "TextEdit"}),
        )
        assert sandbox.current_ui is not None

        before = sandbox.current_ui
        await tool.execute(
            self.tool_ctx(session, FakeComputer()),
            tool.parse_params({"action": "click", "app": "TextEdit", "title": "Save"}),
        )
        assert sandbox.current_ui is not None
        assert len(sandbox.current_ui) == len(before)
