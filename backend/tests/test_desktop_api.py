"""Tests for the sanitized desktop bridge delivered to pywebview (#334).

Contract under test (review blocker B1): the object *actually handed to
pywebview's ``js_api``* sanitizes every call — the tests exercise the
real boundary object (``make_js_api()`` / ``LocalBuildBridge``), not an
auxiliary helper disconnected from the exposed path.

* ``health()`` returns a stable, structured, JSON-serializable payload;
* the exposed surface is an explicit allowlist and matches exactly what
  pywebview's ``get_functions`` walk would expose (no extra attributes);
* no exposed method ever raises: pywebview 6.2.1 converts uncaught
  ``js_api`` exceptions into a JS ``Error`` carrying ``message``/``name``
  /``stack``; the bridge makes that path unreachable, returning
  sanitized structured payloads instead;
* invalid input is rejected with sanitized errors (no tracebacks, no
  internal details), both on the facade and through the full
  navigation-policy wrapper;
* importing the module has no side effects (no window, no threads, no
  env reads at import time).

These tests run headless: they never create a pywebview window.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import backend.desktop.api as desktop_api_module
from backend.desktop.api import (
    DESKTOP_API_METHODS,
    DESKTOP_API_VERSION,
    DesktopApi,
    DesktopApiError,
    make_js_api,
)
from backend.desktop.app import LocalBuildBridge, WindowController, is_local_build_url
from backend.desktop.build_resolver import ResolvedBuild


def _make_build(tmp_path: Path) -> ResolvedBuild:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    (dist / "desktop.html").write_text("<html></html>", encoding="utf-8")
    return ResolvedBuild(
        dist_dir=dist,
        index_html=dist / "index.html",
        desktop_html=dist / "desktop.html",
    )


def _pywebview_exposed_names(obj: object) -> set[str]:
    """Mirror pywebview's ``get_functions`` public-attribute walk."""
    return {name for name in dir(obj) if not name.startswith("_")}


class TestHealthContract:
    def test_health_returns_ok_payload_with_api_version(self) -> None:
        bridge = make_js_api()
        payload = bridge.health()
        assert payload == {"ok": True, "api_version": DESKTOP_API_VERSION}
        # Payload must be JSON-serializable as-is (bridge returns plain data).
        json.dumps(payload)

    def test_health_is_deterministic(self) -> None:
        assert make_js_api().health() == make_js_api().health()


class TestRealBoundarySanitization:
    """The object given to ``js_api`` must sanitize, never raise."""

    def test_exposed_methods_are_exactly_the_allowlist(self) -> None:
        # pywebview exposes every public attribute; the facade must keep
        # the exposed surface equal to the allowlist and nothing else.
        bridge = make_js_api()
        assert _pywebview_exposed_names(bridge) == set(DESKTOP_API_METHODS)

    def test_local_build_bridge_exposes_only_the_allowlist(self, tmp_path: Path) -> None:
        from backend.desktop.api import DESKTOP_API_METHODS as METHODS

        build = _make_build(tmp_path)
        url = build.index_html.as_uri()
        wrapper = LocalBuildBridge(
            make_js_api(runtime=_StubRuntime()), build, lambda: url
        )
        assert _pywebview_exposed_names(wrapper) == set(METHODS)

    def test_bridge_health_never_raises_on_invalid_input(self) -> None:
        # pywebview would convert an exception into a JS Error with a
        # stacktrace; the facade returns data instead.
        bridge = make_js_api()
        result = bridge.health("unexpected")  # type: ignore[arg-type]
        assert result == {
            "ok": False,
            "code": "invalid_input",
            "message": "health() takes no arguments.",
        }

    def test_invalid_input_payload_is_sanitized(self) -> None:
        result = make_js_api().health(None)  # type: ignore[arg-type]
        serialized = json.dumps(result)
        assert "NoneType" not in serialized
        assert "Traceback" not in serialized
        assert "<" not in serialized  # no repr markers

    def test_implementation_errors_collapse_to_sanitized_internal_error(
        self, tmp_path: Path
    ) -> None:
        # Simulate an unexpected bug inside the implementation: the
        # facade must still return data, never raise (pywebview would
        # leak a JS Error with stacktrace otherwise).
        build = _make_build(tmp_path)

        class FakeBridge:
            def health(self, *args: object) -> dict[str, object]:
                raise RuntimeError("secret internal detail /path/to/x")

        from backend.desktop.app import BuildTrust

        trust = BuildTrust(build)
        trust.commit_if_local(build.index_html.as_uri())
        wrapper = LocalBuildBridge(
            FakeBridge(), build, lambda: build.index_html.as_uri(), trust
        )
        result = wrapper.health()
        assert result["ok"] is False
        assert result["code"] == "internal_error"
        serialized = json.dumps(result)
        assert "secret" not in serialized
        assert "/path/to/x" not in serialized
        assert "Traceback" not in serialized
        assert "RuntimeError" not in serialized

    def test_allowlist_is_the_reviewed_companion_surface(self) -> None:
        # #334 shipped health() only; #336 deliberately grew the list to
        # the full companion surface. Every entry is reviewed; the test
        # pins the complete contract.
        assert DESKTOP_API_METHODS == (
            "health",
            "runtime_state",
            "load_history",
            "send_message",
            "delete_history",
            "delete_memories",
            "reset_emotional_state",
            "reset_relationship_state",
            "set_presence_mode",
            "set_always_on_top",
            "window_state",
            "close_window",
        )

    def test_api_exposes_no_generic_objects(self) -> None:
        # The bridge must never hand internal objects/modules to JS.
        bridge = make_js_api()
        for banned in ("engine", "supabase", "settings", "backend", "api"):
            assert not hasattr(bridge, banned), f"bridge must not expose {banned!r}"
        result = bridge.health()
        assert isinstance(result, dict)
        assert all(isinstance(k, str) for k in result)

    def test_make_js_api_returns_fresh_object_each_call(self) -> None:
        assert make_js_api() is not make_js_api()


class TestDesktopApiImplementation:
    """The implementation class may raise; the facade converts to data."""

    def test_implementation_health_rejects_arguments(self) -> None:
        api = DesktopApi()
        try:
            api.health("unexpected")  # type: ignore[arg-type]
        except DesktopApiError as err:
            assert err.payload["code"] == "invalid_input"
            assert "unexpected" not in json.dumps(err.payload)
        else:
            raise AssertionError("health() must reject unexpected arguments")

    def test_implementation_error_payload_is_sanitized(self) -> None:
        try:
            DesktopApi().health(None)  # type: ignore[arg-type]
        except DesktopApiError as err:
            serialized = json.dumps(err.payload)
            assert "<" not in serialized
            assert "NoneType" not in serialized
            assert "Traceback" not in serialized


class TestImportPurity:
    def test_importing_desktop_api_has_no_side_effects(self, monkeypatch) -> None:
        # Import must not read the environment, start threads, or touch
        # pywebview: the module stays importable/testable without display.
        monkeypatch.setenv("KATHERINE_PROBE", "1")
        import importlib

        importlib.reload(desktop_api_module)
        assert make_js_api().health()["ok"] is True

    def test_desktop_api_does_not_import_webview(self) -> None:
        # api.py must not depend on pywebview: window concerns live in
        # the entrypoint, keeping this module GUI-free.
        source = Path(desktop_api_module.__file__).read_text(encoding="utf-8")
        assert "import webview" not in source
        assert "from webview" not in source

    def test_health_signature_takes_no_named_parameters(self) -> None:
        # pywebview inspects parameter names to build the JS proxy;
        # *args-only keeps the surface stable and simple.
        bridge = make_js_api()
        params = inspect.signature(bridge.health).parameters
        assert all(p.kind is p.VAR_POSITIONAL for p in params.values())


# =========================================================================
# #336 extension: the companion-mode surface (T006)
# =========================================================================
#
# The allowlist grows from the single #334 health() proof to the full
# companion surface. Every addition is deliberate and reviewed: the list
# below is the complete public contract of the desktop bridge.

class TestCompanionAllowlist:
    def test_allowlist_is_the_full_companion_surface(self) -> None:
        assert DESKTOP_API_METHODS == (
            "health",
            "runtime_state",
            "load_history",
            "send_message",
            "delete_history",
            "delete_memories",
            "reset_emotional_state",
            "reset_relationship_state",
            "set_presence_mode",
            "set_always_on_top",
            "window_state",
            "close_window",
        )

    def test_facade_exposes_exactly_the_allowlist(self) -> None:
        bridge = make_js_api(runtime=_StubRuntime())
        assert _pywebview_exposed_names(bridge) == set(DESKTOP_API_METHODS)

    def test_all_methods_take_only_positional_args(self) -> None:
        # pywebview builds the JS proxy from parameter names; *args-only
        # keeps the surface stable across pywebview versions.
        bridge = make_js_api(runtime=_StubRuntime())
        for name in DESKTOP_API_METHODS:
            params = inspect.signature(getattr(bridge, name)).parameters
            assert all(p.kind is p.VAR_POSITIONAL for p in params.values()), name


class _StubRuntime:
    """Minimal deterministic runtime double (no SQLite, no Groq)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def runtime_state(self) -> dict:
        self.calls.append("runtime_state")
        return {"ok": True, "storage": True, "provider_configured": True, "revision": 0}

    def load_history(self, limit: int = 50) -> list[dict]:
        self.calls.append(("load_history", limit))
        return [{"id": "m1", "role": "user", "content": "hi", "created_at": 1}]

    def send_turn(self, *, request_id: str, message: str) -> dict:
        self.calls.append(("send_turn", request_id, message))
        return {
            "success": True,
            "response": "ok",
            "emotion_state": {"schema_version": 1},
            "message_id": "m2",
            "revision": 1,
            "duration_ms": 5,
            "replayed": False,
        }

    def delete_history(self) -> dict:
        self.calls.append("delete_history")
        return {"success": True, "result": {"status": "applied"}}

    def delete_memories(self) -> dict:
        self.calls.append("delete_memories")
        return {"success": True, "result": {"status": "applied"}}

    def reset_emotional_state(self) -> dict:
        self.calls.append("reset_emotional_state")
        return {"success": True, "result": {"status": "applied"}}

    def reset_relationship_state(self) -> dict:
        self.calls.append("reset_relationship_state")
        return {"success": True, "result": {"status": "applied"}}


class TestCompanionContract:
    """Shape + validation contract for each new op via the real facade."""

    def _bridge(self) -> tuple[DesktopBridge, _StubRuntime]:
        runtime = _StubRuntime()
        return make_js_api(runtime=runtime), runtime

    def test_runtime_state_returns_payload_and_takes_no_args(self) -> None:
        bridge, runtime = self._bridge()
        result = bridge.runtime_state()
        assert result["ok"] is True
        assert result["provider_configured"] is True
        assert runtime.calls == ["runtime_state"]
        assert bridge.runtime_state("x")["ok"] is False

    def test_load_history_validates_limit(self) -> None:
        bridge, runtime = self._bridge()
        result = bridge.load_history()
        assert result["ok"] is True
        assert result["messages"][0]["content"] == "hi"
        assert ("load_history", 50) in runtime.calls

        # Bounds: 1..500; invalid values are rejected, never clamped
        # silently (invalid input must not reach the runtime).
        for bad in (0, -1, 501, None, "20", 2.5, [10]):
            assert bridge.load_history(bad)["ok"] is False, bad
        assert bridge.load_history(500)["ok"] is True
        assert bridge.load_history(1)["ok"] is True

    def test_send_message_validates_request_id_and_message(self) -> None:
        bridge, runtime = self._bridge()

        ok = bridge.send_message("req-1", "hello there")
        assert ok["success"] is True
        assert ("send_turn", "req-1", "hello there") in runtime.calls

        # request_id: non-empty str, allowed charset, <= 128 chars
        for bad_id in ("", None, 42, "bad id!", "x" * 129, ["id"]):
            assert bridge.send_message(bad_id, "hello")["ok"] is False, bad_id

        # message: non-empty str, <= MAX_MESSAGE_LENGTH, no control garbage
        for bad_msg in ("", None, 42, "   ", "\x00\x01"):
            assert bridge.send_message("req-1", bad_msg)["ok"] is False, bad_msg

    def test_send_message_failure_payload_is_passthrough(self) -> None:
        # The runtime returns a sanitized TurnResult payload for domain
        # failures; the bridge adds the transport-level ``ok`` flag and
        # preserves the domain fields verbatim (stable keys).
        class _FailingRuntime(_StubRuntime):
            def send_turn(self, *, request_id: str, message: str) -> dict:
                return {"success": False, "error_code": "configuration",
                        "error_message": "O provedor remoto não está configurado."}

        bridge = make_js_api(runtime=_FailingRuntime())
        result = bridge.send_message("req-1", "hello")
        assert result == {
            "ok": False,
            "success": False,
            "error_code": "configuration",
            "error_message": "O provedor remoto não está configurado.",
        }

    def test_privacy_ops_take_no_args_and_pass_through(self) -> None:
        bridge, runtime = self._bridge()
        for op in ("delete_history", "delete_memories",
                   "reset_emotional_state", "reset_relationship_state"):
            method = getattr(bridge, op)
            result = method()
            assert result == {"ok": True, "success": True,
                              "result": {"status": "applied"}}, op
            # Stray arguments are rejected (never ignored).
            assert method("x")["ok"] is False, op

    def test_runtime_state_failure_is_sanitized(self) -> None:
        class _BrokenRuntime:
            def runtime_state(self) -> dict:
                raise RuntimeError("secret /path/to/db detail")

        bridge = make_js_api(runtime=_BrokenRuntime())
        result = bridge.runtime_state()
        assert result["ok"] is False
        assert result["code"] == "internal_error"
        serialized = json.dumps(result)
        assert "secret" not in serialized
        assert "/path/to" not in serialized

    def test_runtime_not_injected_fails_closed(self) -> None:
        # No runtime wired (programming error) → sanitized internal error,
        # never an exception across the JS boundary.
        bridge = make_js_api(runtime=None)
        for name in ("runtime_state", "load_history", "send_message",
                     "delete_history", "delete_memories",
                     "reset_emotional_state", "reset_relationship_state"):
            args: tuple = ()
            if name == "send_message":
                args = ("req-1", "hello")
            result = getattr(bridge, name)(*args)
            assert result["ok"] is False, name
            assert result["code"] == "internal_error", name


class TestCompanionSanitization:
    """No input detail ever crosses back into an error payload."""

    def test_invalid_send_input_echoes_nothing(self) -> None:
        bridge = make_js_api(runtime=_StubRuntime())
        result = bridge.send_message("bad id with <script>", "hello")
        serialized = json.dumps(result)
        assert "<script>" not in serialized
        assert "bad id" not in serialized
        assert "Traceback" not in serialized

    def test_load_history_invalid_limit_leaks_no_internal_detail(self) -> None:
        bridge = make_js_api(runtime=_StubRuntime())
        serialized = json.dumps(bridge.load_history(object()))
        assert "object" not in serialized.lower() or "object_at" not in serialized
        assert "Traceback" not in serialized


# =========================================================================
# #342 extension: window lifecycle & floating presence mode surface
# =========================================================================


class _MockNative:
    def __init__(self, x: int = 100, y: int = 150, w: int = 1280, h: int = 800) -> None:
        self.decorated = True
        self.position = (x, y)
        self.size = (w, h)

    def set_decorated(self, val: bool) -> None:
        self.decorated = val

    def get_position(self) -> tuple[int, int]:
        return self.position

    def get_size(self) -> tuple[int, int]:
        return self.size


class _MockWindow:
    def __init__(self) -> None:
        self.native = _MockNative()
        self.on_top = False
        self.resized: tuple[int, int] | None = None
        self.moved: tuple[int, int] | None = None
        self.destroyed = False

    def resize(self, w: int, h: int) -> None:
        self.resized = (w, h)
        self.native.size = (w, h)

    def move(self, x: int, y: int) -> None:
        self.moved = (x, y)
        self.native.position = (x, y)

    def destroy(self) -> None:
        self.destroyed = True


class _StubWindowController:
    """Deterministic window controller double for bridge testing."""

    def __init__(self) -> None:
        self.calls: list[Any] = []
        self.mode = "companion"
        self.on_top = False

    def set_presence_mode(self, enabled: bool) -> dict:
        self.calls.append(("set_presence_mode", enabled))
        self.mode = "presence" if enabled else "companion"
        self.on_top = enabled
        return {
            "ok": True,
            "mode": self.mode,
            "on_top": self.on_top,
            "width": 200 if enabled else 1280,
            "height": 200 if enabled else 800,
        }

    def set_always_on_top(self, enabled: bool) -> dict:
        self.calls.append(("set_always_on_top", enabled))
        self.on_top = enabled
        return {"ok": True, "on_top": enabled}

    def window_state(self) -> dict:
        self.calls.append("window_state")
        return {
            "ok": True,
            "mode": self.mode,
            "on_top": self.on_top,
            "width": 200 if self.mode == "presence" else 1280,
            "height": 200 if self.mode == "presence" else 800,
        }

    def close_window(self) -> dict:
        self.calls.append("close_window")
        return {"ok": True}


class TestWindowControllerDirect:
    """Direct tests for WindowController native mutations and thread-safe state."""

    def test_window_controller_initial_state(self) -> None:
        win = _MockWindow()
        wc = WindowController(window=win)
        state = wc.window_state()
        assert state == {
            "ok": True,
            "mode": "companion",
            "on_top": False,
            "width": 1280,
            "height": 800,
        }

    def test_presence_mode_roundtrip(self) -> None:
        win = _MockWindow()
        wc = WindowController(window=win)

        # 1. Switch to presence
        enter_res = wc.set_presence_mode(True)
        assert enter_res == {
            "ok": True,
            "mode": "presence",
            "on_top": True,
            "width": 200,
            "height": 200,
        }
        assert win.native.decorated is False
        assert win.resized == (200, 200)
        assert win.on_top is True
        assert wc.window_state()["mode"] == "presence"

        # 2. Switch back to companion (restores saved geometry)
        exit_res = wc.set_presence_mode(False)
        assert exit_res == {
            "ok": True,
            "mode": "companion",
            "on_top": False,
            "width": 1280,
            "height": 800,
        }
        assert win.native.decorated is True
        assert win.resized == (1280, 800)
        assert win.moved == (100, 150)
        assert win.on_top is False
        assert wc.window_state()["mode"] == "companion"

    def test_set_always_on_top(self) -> None:
        win = _MockWindow()
        wc = WindowController(window=win)
        res = wc.set_always_on_top(True)
        assert res == {"ok": True, "on_top": True}
        assert win.on_top is True
        assert wc.window_state()["on_top"] is True

        res_off = wc.set_always_on_top(False)
        assert res_off == {"ok": True, "on_top": False}
        assert win.on_top is False

    def test_close_window(self) -> None:
        win = _MockWindow()
        wc = WindowController(window=win)
        assert wc.close_window() == {"ok": True}
        assert win.destroyed is True

    def test_controller_without_window_fails_closed(self) -> None:
        wc = WindowController(window=None)
        assert wc.set_presence_mode(True)["ok"] is False
        assert wc.set_presence_mode(True)["code"] == "window_unavailable"
        assert wc.set_always_on_top(True)["code"] == "window_unavailable"
        assert wc.close_window()["code"] == "window_unavailable"
        # window_state returns local snapshot safely
        assert wc.window_state()["ok"] is True

    def test_glib_idle_add_dispatch_when_available(self, monkeypatch) -> None:
        idle_calls: list[Any] = []

        class FakeGLib:
            @staticmethod
            def idle_add(cb: Any) -> Any:
                idle_calls.append(cb)
                return cb()

        import types

        fake_gi_repo = types.ModuleType("gi.repository")
        fake_gi_repo.GLib = FakeGLib  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "gi.repository", fake_gi_repo)

        win = _MockWindow()
        wc = WindowController(window=win)
        wc.set_presence_mode(True)
        assert len(idle_calls) == 1
        assert win.native.decorated is False


class TestWindowBridgeContract:
    """Bridge facade behavior and argument validation for window operations."""

    def test_window_operations_through_bridge(self) -> None:
        wc = _StubWindowController()
        bridge = make_js_api(window_controller=wc)

        enter = bridge.set_presence_mode(True)
        assert enter["ok"] is True
        assert enter["mode"] == "presence"
        assert ("set_presence_mode", True) in wc.calls

        pin = bridge.set_always_on_top(True)
        assert pin["ok"] is True
        assert pin["on_top"] is True
        assert ("set_always_on_top", True) in wc.calls

        state = bridge.window_state()
        assert state["ok"] is True
        assert state["mode"] == "presence"

        close = bridge.close_window()
        assert close["ok"] is True
        assert "close_window" in wc.calls

    def test_set_presence_mode_validates_argument(self) -> None:
        wc = _StubWindowController()
        bridge = make_js_api(window_controller=wc)

        # Non-boolean inputs must be rejected
        for bad in ("true", 1, 0, None, [True], {"enabled": True}):
            res = bridge.set_presence_mode(bad)
            assert res["ok"] is False
            assert res["code"] == "invalid_input"

        # Wrong arity
        assert bridge.set_presence_mode()["ok"] is False
        assert bridge.set_presence_mode(True, False)["ok"] is False

    def test_set_always_on_top_validates_argument(self) -> None:
        wc = _StubWindowController()
        bridge = make_js_api(window_controller=wc)

        for bad in ("true", 1, 0, None):
            res = bridge.set_always_on_top(bad)
            assert res["ok"] is False
            assert res["code"] == "invalid_input"

        assert bridge.set_always_on_top()["ok"] is False
        assert bridge.set_always_on_top(True, False)["ok"] is False

    def test_nullary_window_methods_reject_arguments(self) -> None:
        wc = _StubWindowController()
        bridge = make_js_api(window_controller=wc)

        assert bridge.window_state("unexpected")["ok"] is False
        assert bridge.window_state("unexpected")["code"] == "invalid_input"
        assert bridge.close_window("unexpected")["ok"] is False
        assert bridge.close_window("unexpected")["code"] == "invalid_input"

    def test_missing_window_controller_fails_closed(self) -> None:
        bridge = make_js_api(window_controller=None)
        for name in ("set_presence_mode", "set_always_on_top"):
            res = getattr(bridge, name)(True)
            assert res["ok"] is False
            assert res["code"] == "window_unavailable"

        for name in ("window_state", "close_window"):
            res = getattr(bridge, name)()
            assert res["ok"] is False
            assert res["code"] == "window_unavailable"
