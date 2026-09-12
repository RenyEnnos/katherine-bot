"""Adversarial stress tests for Issue #342 (Floating presence mode).

Tests concurrency, rapid mode switching, boundary inputs, type attacks,
native GTK exception handling, and fail-closed navigation security.
"""

from __future__ import annotations

import concurrent.futures
import json
import random
import threading
from typing import Any
import pytest

from backend.desktop.api import (
    DESKTOP_API_METHODS,
    DesktopApi,
    DesktopBridge,
    make_js_api,
)
from backend.desktop.app import (
    ClampedGeometry,
    LocalBuildBridge,
    NavigationPolicy,
    WindowController,
    WorkArea,
    clamp_window_geometry,
)
from backend.desktop.build_resolver import ResolvedBuild


class _FaultyNative:
    """Mock GTK native widget that can inject faults on demand."""

    def __init__(
        self,
        x: int = 100,
        y: int = 150,
        w: int = 1280,
        h: int = 800,
        fail_get_pos: bool = False,
        fail_get_size: bool = False,
        fail_set_decorated: bool = False,
    ) -> None:
        self.decorated = True
        self.position = (x, y)
        self.size = (w, h)
        self.fail_get_pos = fail_get_pos
        self.fail_get_size = fail_get_size
        self.fail_set_decorated = fail_set_decorated

    def set_decorated(self, val: bool) -> None:
        if self.fail_set_decorated:
            raise RuntimeError("GTK X11 error: set_decorated failed")
        self.decorated = val

    def get_position(self) -> tuple[int, int]:
        if self.fail_get_pos:
            raise RuntimeError("GTK X11 error: BadWindow on get_position")
        return self.position

    def get_size(self) -> tuple[int, int]:
        if self.fail_get_size:
            raise RuntimeError("GTK X11 error: BadWindow on get_size")
        return self.size


class _FaultyWindow:
    """Mock pywebview window with configurable fault injection."""

    def __init__(
        self,
        native: Any = None,
        fail_resize: bool = False,
        fail_move: bool = False,
        fail_destroy: bool = False,
        fail_on_top: bool = False,
        fail_minimize: bool = False,
    ) -> None:
        self.native = native if native is not None else _FaultyNative()
        self._on_top = False
        self.width = 1280
        self.height = 800
        self.x = 100
        self.y = 150
        self.fail_resize = fail_resize
        self.fail_move = fail_move
        self.fail_destroy = fail_destroy
        self.fail_on_top = fail_on_top
        self.fail_minimize = fail_minimize
        self.destroyed = False
        self.minimized = False

    @property
    def on_top(self) -> bool:
        return self._on_top

    @on_top.setter
    def on_top(self, val: bool) -> None:
        if self.fail_on_top:
            raise RuntimeError("Always on top fault")
        self._on_top = val

    def resize(self, w: int, h: int) -> None:
        if self.fail_resize:
            raise RuntimeError("Window resize fault")
        self.width = w
        self.height = h
        if self.native:
            self.native.size = (w, h)

    def move(self, x: int, y: int) -> None:
        if self.fail_move:
            raise RuntimeError("Window move fault")
        self.x = x
        self.y = y
        if self.native:
            self.native.position = (x, y)

    def minimize(self) -> None:
        if self.fail_minimize:
            raise RuntimeError("Window minimize fault")
        self.minimized = True

    def destroy(self) -> None:
        if self.fail_destroy:
            raise RuntimeError("Window destroy fault")
        self.destroyed = True


class TestWindowControllerAdversarialConcurrency:
    """Adversarial concurrent stress testing on WindowController."""

    def test_rapid_concurrent_mode_switching(self) -> None:
        """50 concurrent worker threads rapidly invoking mode changes and queries."""
        win = _FaultyWindow()
        wc = WindowController(window=win)

        errors: list[Exception] = []
        states_seen: list[dict[str, Any]] = []

        def worker(thread_id: int) -> None:
            try:
                for i in range(50):
                    action = i % 5
                    if action == 0:
                        res = wc.set_presence_mode(True)
                        assert res["ok"] is True
                        assert res["mode"] == "presence"
                        assert res["width"] == 200
                        assert res["height"] == 200
                    elif action == 1:
                        res = wc.set_presence_mode(False)
                        assert res["ok"] is True
                        assert res["mode"] == "companion"
                        assert res["width"] > 0
                        assert res["height"] > 0
                    elif action == 2:
                        res = wc.set_always_on_top(bool(i % 2))
                        assert res["ok"] is True
                    elif action == 3:
                        s = wc.window_state()
                        assert s["ok"] is True
                        assert s["mode"] in ("presence", "companion")
                        assert isinstance(s["on_top"], bool)
                        states_seen.append(s)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        assert not errors, f"Concurrent execution produced errors: {errors}"
        final_state = wc.window_state()
        assert final_state["ok"] is True
        assert final_state["mode"] in ("presence", "companion")

    def test_geometry_preservation_under_repeated_presence_calls(self) -> None:
        """Calling set_presence_mode(True) repeatedly must NOT overwrite saved companion geometry."""
        win = _FaultyWindow()
        win.native.position = (250, 350)
        win.native.size = (1400, 900)
        wc = WindowController(window=win)

        # First enter presence: should record (250, 350, 1400, 900)
        r1 = wc.set_presence_mode(True)
        assert r1["ok"] is True
        assert r1["mode"] == "presence"

        # Repeated calls to enter presence while ALREADY in presence
        for _ in range(10):
            r = wc.set_presence_mode(True)
            assert r["ok"] is True
            assert r["mode"] == "presence"

        # Now exit presence: should restore (250, 350, 1400, 900), NOT (200, 200)!
        exit_res = wc.set_presence_mode(False)
        assert exit_res["ok"] is True
        assert exit_res["mode"] == "companion"
        assert exit_res["width"] == 1400
        assert exit_res["height"] == 900
        assert win.native.position == (250, 350)
        assert win.native.size == (1400, 900)

    def test_geometry_preservation_when_companion_moves_between_sessions(self) -> None:
        """When companion moves while in companion mode, next presence captures updated position."""
        win = _FaultyWindow()
        wc = WindowController(window=win)

        # 1. First presence roundtrip
        wc.set_presence_mode(True)
        wc.set_presence_mode(False)

        # User moves companion window to new location
        win.native.position = (500, 600)
        win.native.size = (1100, 750)

        # 2. Enter presence again
        wc.set_presence_mode(True)
        # 3. Exit presence
        wc.set_presence_mode(False)

        # Verify it restored the NEW location, not the original (100, 150)
        assert win.native.position == (500, 600)
        assert win.native.size == (1100, 750)


class TestWindowControllerFaultTolerance:
    """Stress tests on native GTK failures and fault injection."""

    def test_native_position_and_size_exceptions_handled_gracefully(self) -> None:
        """When GTK throws BadWindow on get_position/get_size, fallbacks are used."""
        faulty_native = _FaultyNative(fail_get_pos=True, fail_get_size=True)
        win = _FaultyWindow(native=faulty_native)
        win.x = 80
        win.y = 90
        win.width = 1200
        win.height = 700
        wc = WindowController(window=win)

        # Should not raise despite native exceptions
        r = wc.set_presence_mode(True)
        assert r["ok"] is True
        assert r["mode"] == "presence"

        exit_r = wc.set_presence_mode(False)
        assert exit_r["ok"] is True
        assert exit_r["width"] == 1200
        assert exit_r["height"] == 700

    def test_set_decorated_failure_returns_error_and_preserves_companion_state(self) -> None:
        """When set_decorated fails, mode transition fails and state remains companion."""
        faulty_native = _FaultyNative(fail_set_decorated=True)
        win = _FaultyWindow(native=faulty_native)
        wc = WindowController(window=win)

        res = wc.set_presence_mode(True)
        assert res["ok"] is False
        assert res["code"] == "window_mutation_failed"
        assert res["message"] == "The window operation could not be completed."
        assert wc.window_state()["mode"] == "companion"

    def test_resize_failure_on_presence_rolls_back_decoration_and_preserves_mode(self) -> None:
        """When resize fails entering presence, decoration is rolled back and mode remains companion."""
        faulty_native = _FaultyNative()
        win = _FaultyWindow(native=faulty_native, fail_resize=True)
        wc = WindowController(window=win)

        res = wc.set_presence_mode(True)
        assert res["ok"] is False
        assert res["code"] == "window_mutation_failed"
        assert res["message"] == "The window operation could not be completed."
        assert wc.window_state()["mode"] == "companion"
        assert win.native.decorated is True

    def test_resize_failure_on_companion_preserves_presence_mode(self) -> None:
        """When resize fails returning to companion, state remains presence and decoration is rolled back."""
        win = _FaultyWindow()
        wc = WindowController(window=win)

        enter_res = wc.set_presence_mode(True)
        assert enter_res["ok"] is True
        assert wc.window_state()["mode"] == "presence"
        assert win.native.decorated is False

        win.fail_resize = True
        exit_res = wc.set_presence_mode(False)
        assert exit_res["ok"] is False
        assert exit_res["code"] == "window_mutation_failed"
        assert wc.window_state()["mode"] == "presence"
        assert win.native.decorated is False

    def test_move_failure_on_companion_preserves_presence_mode(self) -> None:
        """When move fails returning to companion, state remains presence and decoration/size are rolled back."""
        win = _FaultyWindow()
        wc = WindowController(window=win)

        enter_res = wc.set_presence_mode(True)
        assert enter_res["ok"] is True
        assert wc.window_state()["mode"] == "presence"
        assert win.native.decorated is False

        win.fail_move = True
        exit_res = wc.set_presence_mode(False)
        assert exit_res["ok"] is False
        assert exit_res["code"] == "window_mutation_failed"
        assert wc.window_state()["mode"] == "presence"
        assert win.native.decorated is False
        assert (win.width, win.height) == (200, 200)

    def test_companion_mutation_failure_rolls_back_decoration(self) -> None:
        """BUG-M1-01 regression: resize or move failure when returning to companion rolls back decoration to False."""
        for failure_attr in ("fail_resize", "fail_move"):
            win = _FaultyWindow()
            wc = WindowController(window=win)

            enter_res = wc.set_presence_mode(True)
            assert enter_res["ok"] is True
            assert wc.window_state()["mode"] == "presence"
            assert win.native.decorated is False

            setattr(win, failure_attr, True)
            exit_res = wc.set_presence_mode(False)
            assert exit_res["ok"] is False
            assert exit_res["code"] == "window_mutation_failed"
            assert exit_res["message"] == "The window operation could not be completed."
            assert wc.window_state()["mode"] == "presence"
            assert win.native.decorated is False, (
                f"Decoration was left as True after {failure_attr} failure returning to companion"
            )

    def test_presence_move_failure_rolls_back_resize_and_decoration(self) -> None:
        """Compound rollback: When move fails entering presence, resize and decoration are rolled back."""
        win = _FaultyWindow(fail_move=True)
        win.width, win.height = 1280, 800
        win.x, win.y = 5000, 5000
        win.native.position = (5000, 5000)
        wc = WindowController(window=win, workareas=[WorkArea(0, 0, 1920, 1080)])

        res = wc.set_presence_mode(True)
        assert res["ok"] is False
        assert res["code"] == "window_mutation_failed"
        assert (win.width, win.height) == (1280, 800)
        assert win.native.decorated is True
        assert wc.window_state()["mode"] == "companion"

    def test_companion_move_failure_rolls_back_resize_and_decoration(self) -> None:
        """Compound rollback: When move fails returning to companion, resize and decoration are rolled back."""
        win = _FaultyWindow()
        win.x, win.y = 5000, 5000
        win.native.position = (5000, 5000)
        wc = WindowController(window=win, workareas=[WorkArea(0, 0, 1920, 1080)])

        enter_res = wc.set_presence_mode(True)
        assert enter_res["ok"] is True
        assert (win.width, win.height) == (200, 200)
        assert win.native.decorated is False

        win.fail_move = True
        exit_res = wc.set_presence_mode(False)
        assert exit_res["ok"] is False
        assert exit_res["code"] == "window_mutation_failed"
        assert (win.width, win.height) == (200, 200)
        assert win.native.decorated is False
        assert wc.window_state()["mode"] == "presence"

    def test_set_always_on_top_failure_preserves_state(self) -> None:
        """When setting always_on_top raises natively, state is not committed."""
        win = _FaultyWindow(fail_on_top=True)
        wc = WindowController(window=win)

        res = wc.set_always_on_top(True)
        assert res["ok"] is False
        assert res["code"] == "window_mutation_failed"
        assert wc.window_state()["on_top"] is False

    def test_close_window_failure_returns_error(self) -> None:
        """When window destroy raises natively, sanitized error is returned."""
        win = _FaultyWindow(fail_destroy=True)
        wc = WindowController(window=win)

        res = wc.close_window()
        assert res["ok"] is False
        assert res["code"] == "window_mutation_failed"

    def test_minimize_window_failure_returns_error(self) -> None:
        """When window minimize raises natively, sanitized error is returned."""
        win = _FaultyWindow(fail_minimize=True)
        wc = WindowController(window=win)

        res = wc.minimize_window()
        assert res["ok"] is False
        assert res["code"] == "window_mutation_failed"

    def test_reconcile_geometry_move_failure_preserves_state_and_clears_guard(self) -> None:
        """When native move fails during reconciliation in presence mode,

        state does NOT advance to unapplied coordinates, native geometry is untouched,
        sanitized error is returned, and reentrancy guard is released.
        """
        win = _FaultyWindow()
        win.native.position = (100, 150)
        win.native.size = (200, 200)
        wc = WindowController(window=win, workareas=[WorkArea(0, 0, 1920, 1080)])

        # Enter presence mode: initial state committed
        r = wc.set_presence_mode(True)
        assert r["ok"] is True
        st_before = wc.window_state()
        assert st_before["x"] == 100
        assert st_before["y"] == 150
        assert st_before["width"] == 200
        assert st_before["height"] == 200

        # Inject failure on move
        win.fail_move = True

        # Attempt to reconcile out-of-bounds coords (e.g. -400, -400)
        res = wc.reconcile_geometry(x=-400, y=-400)
        assert res["ok"] is False
        assert res["code"] == "window_mutation_failed"
        assert res["message"] == "The window operation could not be completed."

        # Native geometry must remain untouched
        assert win.native.position == (100, 150)
        assert win.x == 100
        assert win.y == 150

        # Logical window_state must NOT advance to clamped (0, 0)
        st_after = wc.window_state()
        assert st_after["x"] == 100
        assert st_after["y"] == 150
        assert st_after["width"] == 200
        assert st_after["height"] == 200

        # Reentrancy guard must be cleared
        assert wc._is_reconciling is False

        # Clear fault and verify subsequent reconciliation succeeds
        win.fail_move = False
        res_recovered = wc.reconcile_geometry(x=-400, y=-400)
        assert res_recovered["ok"] is True
        assert res_recovered["clamped"] is True
        assert res_recovered["x"] == 0
        assert res_recovered["y"] == 0
        assert win.native.position == (0, 0)
        st_final = wc.window_state()
        assert st_final["x"] == 0
        assert st_final["y"] == 0

    def test_reconcile_geometry_resize_failure_preserves_state_and_clears_guard(self) -> None:
        """When native resize fails during reconciliation, state does not advance and guard is cleared."""
        win = _FaultyWindow()
        win.native.position = (100, 150)
        win.native.size = (200, 200)
        wc = WindowController(window=win, workareas=[WorkArea(0, 0, 1920, 1080)])

        r = wc.set_presence_mode(True)
        assert r["ok"] is True

        win.fail_resize = True
        win.native.size = (80, 80)  # less than min_size 120, requiring resize to 120
        win.width = 80
        res = wc.reconcile_geometry(x=100, y=150)
        assert res["ok"] is False
        assert res["code"] == "window_mutation_failed"
        assert res["message"] == "The window operation could not be completed."
        assert wc._is_reconciling is False

    def test_dispatch_sync_timeout_returns_timeout_code(self, monkeypatch) -> None:
        """When an operation exceeds timeout, code 'timeout' is returned."""
        class FakeMainContext:
            def is_owner(self) -> bool:
                return False

        class FakeGLib:
            class MainContext:
                @staticmethod
                def default():
                    return FakeMainContext()

            @staticmethod
            def idle_add(cb: Any) -> Any:
                return False

        import types
        import sys

        fake_gi_repo = types.ModuleType("gi.repository")
        fake_gi_repo.GLib = FakeGLib  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "gi.repository", fake_gi_repo)

        fake_wgtk = types.ModuleType("webview.platforms.gtk")
        fake_wgtk._app = object()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "webview.platforms.gtk", fake_wgtk)

        win = _FaultyWindow()
        wc = WindowController(window=win, dispatch_timeout=0.05)
        res = wc.set_presence_mode(True)
        assert res["ok"] is False
        assert res["code"] == "timeout"
        assert res["message"] == "The window operation could not be completed."

    def test_delayed_glib_callback_after_timeout_does_not_mutate_native_window(
        self, monkeypatch
    ) -> None:
        """BUG-M1-02 regression: Delayed GLib callback after timeout must not execute native mutations.

        When _dispatch_sync times out on a worker thread, the queued GLib callback
        must be cancelled. When the main loop later drains idle sources, the callback
        must return False immediately without mutating native window state (decorations,
        geometry, or size).
        """
        idle_queue: list[Any] = []

        class FakeMainContext:
            def is_owner(self) -> bool:
                return False

        class FakeGLib:
            class MainContext:
                @staticmethod
                def default() -> FakeMainContext:
                    return FakeMainContext()

            @staticmethod
            def idle_add(cb: Any) -> int:
                idle_queue.append(cb)
                return len(idle_queue)

            @staticmethod
            def source_remove(source_id: int) -> bool:
                return True

        import sys
        import types

        fake_gi_repo = types.ModuleType("gi.repository")
        fake_gi_repo.GLib = FakeGLib  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "gi.repository", fake_gi_repo)

        fake_wgtk = types.ModuleType("webview.platforms.gtk")
        fake_wgtk._app = object()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "webview.platforms.gtk", fake_wgtk)

        win = _FaultyWindow()
        wc = WindowController(window=win, dispatch_timeout=0.05)

        res = wc.set_presence_mode(True)
        assert res["ok"] is False
        assert res["code"] == "timeout"
        assert res["message"] == "The window operation could not be completed."
        assert wc.window_state()["mode"] == "companion"
        assert len(idle_queue) == 1

        # Simulate GTK main loop resuming and draining delayed callbacks
        for cb in idle_queue:
            ret = cb()
            assert ret is False, "Cancelled callback must return False to unregister from GLib"

        # CRITICAL: Native window must not have been modified by the delayed callback
        assert win.native.decorated is True, (
            "BUG-M1-02 regression: Delayed callback undecorated native window after timeout"
        )
        assert (win.width, win.height) == (1280, 800), (
            f"BUG-M1-02 regression: Delayed callback resized native window to ({win.width}, {win.height})"
        )
        assert (win.x, win.y) == (100, 150)
        assert wc.window_state()["mode"] == "companion"

    @pytest.mark.parametrize(
        ("op_name", "action_fn", "mutation_check"),
        [
            (
                "on_top",
                lambda wc: wc.set_always_on_top(True),
                lambda win: win.on_top is False,
            ),
            (
                "minimize",
                lambda wc: wc.minimize_window(),
                lambda win: win.minimized is False,
            ),
            (
                "close",
                lambda wc: wc.close_window(),
                lambda win: win.destroyed is False,
            ),
        ],
    )
    def test_delayed_glib_callbacks_all_mutations_cancelled_after_timeout(
        self, monkeypatch, op_name: str, action_fn: Any, mutation_check: Any
    ) -> None:
        """BUG-M1-02 regression: All native mutators must cancel delayed callbacks on timeout."""
        idle_queue: list[Any] = []

        class FakeMainContext:
            def is_owner(self) -> bool:
                return False

        class FakeGLib:
            class MainContext:
                @staticmethod
                def default() -> FakeMainContext:
                    return FakeMainContext()

            @staticmethod
            def idle_add(cb: Any) -> int:
                idle_queue.append(cb)
                return len(idle_queue)

            @staticmethod
            def source_remove(source_id: int) -> bool:
                return True

        import sys
        import types

        fake_gi_repo = types.ModuleType("gi.repository")
        fake_gi_repo.GLib = FakeGLib  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "gi.repository", fake_gi_repo)

        fake_wgtk = types.ModuleType("webview.platforms.gtk")
        fake_wgtk._app = object()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "webview.platforms.gtk", fake_wgtk)

        win = _FaultyWindow()
        wc = WindowController(window=win, dispatch_timeout=0.05)

        res = action_fn(wc)
        assert res["ok"] is False
        assert res["code"] == "timeout"
        assert len(idle_queue) == 1

        for cb in idle_queue:
            ret = cb()
            assert ret is False

        assert mutation_check(win), f"Delayed mutation occurred for operation '{op_name}' after timeout!"

    def test_window_controller_fails_closed_when_native_capability_missing(self) -> None:
        """Verify set_always_on_top, minimize_window, close_window fail closed if native capability missing."""
        class BareWindow:
            pass

        win = BareWindow()
        wc = WindowController(window=win)

        res_on_top = wc.set_always_on_top(True)
        assert res_on_top["ok"] is False
        assert res_on_top["code"] == "window_mutation_failed"
        assert wc.window_state()["on_top"] is False

        res_min = wc.minimize_window()
        assert res_min["ok"] is False
        assert res_min["code"] == "window_mutation_failed"

        res_close = wc.close_window()
        assert res_close["ok"] is False
        assert res_close["code"] == "window_mutation_failed"

    def test_bridge_exception_containment(self) -> None:
        """Verify no unhandled exceptions cross the DesktopBridge boundary to JS."""
        faulty_win = _FaultyWindow(
            fail_resize=True,
            fail_move=True,
            fail_destroy=True,
            fail_on_top=True,
            fail_minimize=True,
        )
        wc = WindowController(window=faulty_win)
        bridge = make_js_api(window_controller=wc)

        for call, kwargs in [
            (bridge.set_presence_mode, {"args": (True,)}),
            (bridge.set_always_on_top, {"args": (True,)}),
            (bridge.minimize_window, {"args": ()}),
            (bridge.close_window, {"args": ()}),
        ]:
            res = call(*kwargs["args"])
            assert isinstance(res, dict)
            assert res["ok"] is False
            assert res["code"] == "window_mutation_failed"


class TestBridgeFuzzingAndValidation:
    """Boundary, typing, and fuzzing attacks on the 4 new window bridge methods."""

    @pytest.fixture
    def bridge(self) -> DesktopBridge:
        win = _FaultyWindow()
        wc = WindowController(window=win)
        return make_js_api(window_controller=wc)

    @pytest.mark.parametrize(
        "bad_input",
        [
            1,  # int 1 must NOT be accepted as bool
            0,  # int 0 must NOT be accepted as bool
            -1,
            100,
            1.0,
            0.0,
            float("nan"),
            float("inf"),
            "true",
            "True",
            "false",
            "False",
            "",
            None,
            [],
            [True],
            {},
            {"ok": True},
            set(),
            object(),
            b"true",
        ],
    )
    def test_set_presence_mode_rejects_non_booleans(
        self, bridge: DesktopBridge, bad_input: Any
    ) -> None:
        res = bridge.set_presence_mode(bad_input)
        assert res["ok"] is False
        assert res["code"] == "invalid_input"
        payload_str = json.dumps(res)
        assert "Traceback" not in payload_str
        assert f"'{type(bad_input).__name__}'" not in payload_str or bad_input in (1, 0)

    @pytest.mark.parametrize(
        "bad_input",
        [
            1,
            0,
            "true",
            "false",
            None,
            [],
            {},
            1.5,
        ],
    )
    def test_set_always_on_top_rejects_non_booleans(
        self, bridge: DesktopBridge, bad_input: Any
    ) -> None:
        res = bridge.set_always_on_top(bad_input)
        assert res["ok"] is False
        assert res["code"] == "invalid_input"

    def test_arity_attacks_on_all_window_methods(
        self, bridge: DesktopBridge
    ) -> None:
        # set_presence_mode takes exactly 1 arg
        assert bridge.set_presence_mode()["ok"] is False
        assert bridge.set_presence_mode(True, True)["ok"] is False
        assert bridge.set_presence_mode(True, "extra", 123)["ok"] is False

        # set_always_on_top takes exactly 1 arg
        assert bridge.set_always_on_top()["ok"] is False
        assert bridge.set_always_on_top(True, False)["ok"] is False

        # window_state takes 0 args
        assert bridge.window_state(True)["ok"] is False
        assert bridge.window_state(1)["ok"] is False
        assert bridge.window_state(None)["ok"] is False

        # close_window takes 0 args
        assert bridge.close_window(True)["ok"] is False
        assert bridge.close_window("now")["ok"] is False

        # minimize_window takes 0 args
        assert bridge.minimize_window(True)["ok"] is False
        assert bridge.minimize_window("now")["ok"] is False


class TestNavigationFailClosedSecurityForWindowOps:
    """Verify that NavigationPolicy and LocalBuildBridge lock down all window ops."""

    def test_all_window_ops_fail_closed_on_untrusted_navigation(
        self, tmp_path
    ) -> None:
        dist = tmp_path / "dist"
        dist.mkdir()
        entry = dist / "index-desktop.html"
        entry.write_text("<!doctype html><title>Katherine</title>")
        build = ResolvedBuild(dist_dir=dist, index_html=entry, desktop_html=entry)

        win = _FaultyWindow()
        wc = WindowController(window=win)
        bridge = make_js_api(window_controller=wc)

        current_url = ["https://malicious-site.com/evil.html"]
        local_bridge = LocalBuildBridge(
            bridge=bridge,
            build=build,
            get_url=lambda: current_url[0],
        )

        for op in ("set_presence_mode", "set_always_on_top"):
            res = getattr(local_bridge, op)(True)
            assert res["ok"] is False
            assert res["code"] == "bridge_unavailable"

        for op in ("window_state", "close_window", "minimize_window"):
            res = getattr(local_bridge, op)()
            assert res["ok"] is False
            assert res["code"] == "bridge_unavailable"


class TestGeometryClamping:
    """Pure unit tests for clamp_window_geometry covering all 11 multi-monitor scenarios."""

    def test_scenario_1_fully_inside(self) -> None:
        """Window fully inside workarea remains unchanged."""
        wa = [WorkArea(0, 0, 1920, 1080)]
        target = (100, 100, 1280, 800)
        clamped = clamp_window_geometry(target, wa)
        assert clamped == ClampedGeometry(100, 100, 1280, 800)

    def test_scenario_2_partially_left(self) -> None:
        """Window overflowing to the left is clamped to workarea left bound."""
        wa = [WorkArea(0, 0, 1920, 1080)]
        target = (-100, 100, 1280, 800)
        clamped = clamp_window_geometry(target, wa)
        assert clamped == ClampedGeometry(0, 100, 1280, 800)

    def test_scenario_3_partially_right(self) -> None:
        """Window overflowing to the right is clamped to workarea right bound."""
        wa = [WorkArea(0, 0, 1920, 1080)]
        target = (1000, 100, 1280, 800)
        clamped = clamp_window_geometry(target, wa)
        assert clamped == ClampedGeometry(640, 100, 1280, 800)

    def test_scenario_4_partially_top_with_panel(self) -> None:
        """Window obscured by top OS panel is clamped below panel."""
        wa = [WorkArea(0, 32, 1920, 1048)]
        target = (100, 10, 1280, 800)
        clamped = clamp_window_geometry(target, wa)
        assert clamped == ClampedGeometry(100, 32, 1280, 800)

    def test_scenario_5_partially_bottom_with_dock(self) -> None:
        """Window obscured by bottom OS dock is clamped above dock."""
        wa = [WorkArea(0, 0, 1920, 1000)]
        target = (100, 400, 1280, 800)
        clamped = clamp_window_geometry(target, wa)
        assert clamped == ClampedGeometry(100, 200, 1280, 800)

    def test_scenario_6_valid_negative_x_left_monitor(self) -> None:
        """Negative X coordinates in multi-monitor left setup are preserved."""
        was = [WorkArea(0, 0, 1920, 1080), WorkArea(-1920, 0, 1920, 1080)]
        target = (-1500, 200, 1280, 800)
        clamped = clamp_window_geometry(target, was, primary_index=0)
        assert clamped == ClampedGeometry(-1500, 200, 1280, 800)

    def test_scenario_7_valid_negative_y_top_monitor(self) -> None:
        """Negative Y coordinates in multi-monitor top setup are preserved."""
        was = [WorkArea(0, 0, 1920, 1080), WorkArea(0, -1080, 1920, 1080)]
        target = (100, -800, 1280, 800)
        clamped = clamp_window_geometry(target, was, primary_index=0)
        assert clamped == ClampedGeometry(100, -800, 1280, 800)

    def test_scenario_8_vanished_monitor_recovery(self) -> None:
        """Window previously on disconnected monitor is recovered onto remaining primary."""
        wa = [WorkArea(0, 0, 1920, 1080)]
        target = (-1500, 200, 1280, 800)
        clamped = clamp_window_geometry(target, wa)
        assert clamped == ClampedGeometry(0, 200, 1280, 800)

    def test_scenario_9_reduced_resolution(self) -> None:
        """Window larger than shrunken display resolution is dimension-clamped."""
        wa = [WorkArea(0, 0, 1024, 768)]
        target = (0, 0, 1280, 800)
        clamped = clamp_window_geometry(target, wa)
        assert clamped == ClampedGeometry(0, 0, 1024, 768)

    def test_scenario_10_presence_recovery(self) -> None:
        """Presence window placed at screen boundary is fully visible with reachable controls."""
        wa = [WorkArea(0, 0, 1920, 1080)]
        target = (1900, 1000, 200, 200)
        clamped = clamp_window_geometry(target, wa)
        assert clamped == ClampedGeometry(1720, 880, 200, 200)

    def test_scenario_11_unpositioned_companion_restore_centers_on_primary(self) -> None:
        """Unpositioned window restores centered on primary workarea."""
        wa = [WorkArea(0, 0, 1920, 1080)]
        target = (None, None, 1280, 800)
        clamped = clamp_window_geometry(target, wa)
        assert clamped == ClampedGeometry(320, 140, 1280, 800)

    def test_window_controller_integrates_geometry_clamping(self) -> None:
        """WindowController clamps presence and companion mode when workareas exist."""
        win = _FaultyWindow()
        win.native.position = (1200, 1000)
        win.native.size = (1400, 900)
        wc = WindowController(
            window=win, workareas=[WorkArea(0, 0, 1280, 800)]
        )

        # Enter presence: position (1200, 1000, 200, 200) clamped to (1080, 600, 200, 200)
        r_pres = wc.set_presence_mode(True)
        assert r_pres["ok"] is True
        assert win.x == 1080
        assert win.y == 600

        # Return companion: saved (1200, 1000, 1400, 900) clamped to (0, 0, 1280, 800)
        r_comp = wc.set_presence_mode(False)
        assert r_comp["ok"] is True
        assert win.x == 0
        assert win.y == 0
        assert win.width == 1280
        assert win.height == 800
