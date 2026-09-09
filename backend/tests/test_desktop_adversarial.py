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
    LocalBuildBridge,
    NavigationPolicy,
    WindowController,
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
    ) -> None:
        self.native = native if native is not None else _FaultyNative()
        self.on_top = False
        self.width = 1280
        self.height = 800
        self.x = 100
        self.y = 150
        self.fail_resize = fail_resize
        self.fail_move = fail_move
        self.fail_destroy = fail_destroy
        self.destroyed = False

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

    def test_native_mutation_exceptions_do_not_crash_controller(self) -> None:
        """When native window methods raise during dispatch, controller state remains consistent."""
        faulty_native = _FaultyNative(fail_set_decorated=True)
        win = _FaultyWindow(native=faulty_native, fail_resize=True, fail_move=True)
        wc = WindowController(window=win)

        # Dispatched action fails silently in _dispatch_main_loop
        r = wc.set_presence_mode(True)
        assert r["ok"] is True
        assert wc.window_state()["mode"] == "presence"

        exit_r = wc.set_presence_mode(False)
        assert exit_r["ok"] is True
        assert wc.window_state()["mode"] == "companion"


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


class TestNavigationFailClosedSecurityForWindowOps:
    """Verify that NavigationPolicy and LocalBuildBridge lock down all 4 window ops."""

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

        for op in ("window_state", "close_window"):
            res = getattr(local_bridge, op)()
            assert res["ok"] is False
            assert res["code"] == "bridge_unavailable"
