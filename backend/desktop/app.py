"""Desktop entrypoint: opens the Katherine window via pywebview (#334).

Responsibilities (deliberately tiny):

1. resolve the local frontend build (explicit failure if missing);
2. build the sanitized, allowlisted desktop bridge (``make_js_api``);
3. open one pywebview window pointed at the local build via ``file://``;
4. enforce the navigation policy below;
5. block until the window closes, then return cleanly.

Not here (on purpose): no domain logic, no ConversationEngine, no
backend server, no HTTP hosting of the UI, no background services.

Lifecycle notes:
* No threads, sockets, servers, or ports are created by this shell.
* Shutdown is the window close: ``webview.start()`` returns and the
  process exits normally through the caller. No ``os._exit``, no kills.

Navigation policy (remote content must never gain the privileged bridge)
---------------------------------------------------------------------------

pywebview injects ``window.pywebview`` into *whatever document the
webview loaded last* (WebKitGTK re-injects on every ``load-changed`` /
FINISHED). Loading ``file://`` initially is therefore not enough: a
same-window ``location`` change (link click, ``window.location = ...``)
would hand ``window.pywebview.api`` to remote content.

This module enforces two independent, local layers:

1. **Revert navigation** — a ``loaded`` event handler checks the window
   URL; if it is no longer the local build, it *revokes the trust
   first* (:meth:`BuildTrust.revoke`) and then navigates back to the
   entry. The remote document may exist transiently, but cannot be
   interacted with and does not persist.
2. **Fail-closed bridge** — the ``js_api`` object checks the URL on
   *every* call. A call is served only when the current URL is exactly
   the URL of the last *completed and committed* local load. Any
   in-flight navigation — remote, or the revert itself, even when
   ``get_uri()`` already shows the local entry URL again — leaves the
   bridge closed. Even in the race window before the revert completes,
   remote code cannot invoke Python through the bridge.

Both layers are simple and local (no proxy, no HTTP server, no extra
process) and covered by ``backend/tests/test_desktop_navigation.py``
plus the reproducible smoke in ``scripts/desktop_smoke.py``.

Why the trust must be *revoked* before the revert navigation
(reviewer follow-up on the same-URL window): WebKitGTK's ``get_uri()``
reflects the load that *started*. When the revert navigates back to
the very same ``entry_html`` the window opened with, ``get_uri()``
returns the previously committed URL while the **remote document is
still the live document**. URL equality therefore proves neither
document identity nor load completion; the only thing that may
re-open the bridge is the ``loaded`` event of the *new* local load
committing again.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import urlsplit

import webview

from backend.desktop.api import DESKTOP_API_METHODS, DesktopApiError, make_js_api
from backend.desktop.build_resolver import (
    BuildResolutionError,
    DesktopBuildConfig,
    ResolvedBuild,
    default_frontend_root,
    resolve_frontend_build,
)

_WINDOW_TITLE = "Katherine"
_WINDOW_SIZE = (1280, 800)

#: Actionable hint reused for a missing smoke page inside the build.
_BUILD_HINT = "Run 'npm run build' in the frontend/ directory first."

#: Public error code used when the bridge refuses to serve a non-local page.
ERROR_BRIDGE_UNAVAILABLE = "bridge_unavailable"

#: Public error code used when the local runtime cannot start (corrupt DB,
#: unwritable directory). Sanitized: no path, no traceback.
ERROR_RUNTIME_STARTUP = "runtime_startup_failed"

_MSG_BRIDGE_UNAVAILABLE = "Desktop bridge is not available for this page."
_MSG_INTERNAL = "The desktop bridge failed to complete the request."
_MSG_RUNTIME_STARTUP = (
    "O armazenamento local não pôde ser aberto. "
    "Verifique o banco de dados local e tente novamente."
)


def _build_language_model_factory():
    """Build the desktop provider wiring (issue #337 review).

    The concrete provider choice lives in this composition root, not
    in the runtime or in the generic contract: the desktop selects
    Groq explicitly (no auto-routing, no fallback) and closes over the
    adapter's own factory helper, reading its keys Python-side only
    (env values are never echoed, never in the Vite bundle, never
    through the bridge). The factory stays lazy — importing the app or
    building the runtime never loads a provider SDK; the adapter is
    constructed on the first turn that needs the model.
    """
    from backend.groq_keys import get_groq_api_keys
    from backend.groq_language_model import build_groq_language_model_factory

    keys = tuple(
        k for k in get_groq_api_keys() if isinstance(k, str) and k.strip()
    )
    return build_groq_language_model_factory(keys=keys)


def _build_runtime():
    """Build the production companion runtime (#336, #337).

    Lazy import on purpose: ``backend.desktop.app`` stays import-pure
    (no domain modules at import time; the runtime pulls only light,
    pure-domain dependencies — verified by the import-cost budget
    tests). The runtime opens its storage lazily on first use, so this
    call never touches SQLite; it just constructs the object.

    Provider wiring (issue #337 review): the runtime itself is
    provider-agnostic; this composition root supplies the explicit
    Groq factory and the configuration probe (presence-only, never a
    generation call).
    """
    from backend.companion_runtime import build_companion_runtime

    factory = _build_language_model_factory()
    return build_companion_runtime(
        language_model_factory=factory,
        provider_configured_probe=getattr(
            factory, "provider_configured_probe", None
        ),
    )


def is_local_build_url(url: str | None, build: ResolvedBuild) -> bool:
    """Return True iff ``url`` points inside the resolved local build.

    Structural check (not string-prefix based): the URL must be
    ``file://`` with an empty host, no query string and no fragment, and
    its path must resolve (lexically, no filesystem access) inside the
    build's ``dist`` directory or be the ``index.html`` itself. Pure
    predicate: no network, no filesystem access, never raises.
    """
    if not url or not url.startswith("file://"):
        return False
    try:
        split = urlsplit(url)
    except ValueError:  # pragma: no cover - defensive: malformed URLs
        return False
    if split.scheme != "file" or split.netloc:
        return False
    if split.query or split.fragment:
        return False
    dist_dir = build.dist_dir
    index_html = build.index_html
    if split.path == index_html.as_posix():
        return True
    candidate = Path(split.path)
    try:
        candidate.relative_to(dist_dir)
    except ValueError:
        return False
    # Reject lexical traversal: any ``..``/``.`` segment means the URL
    # does not literally point inside dist (e.g. ``dist/../x.html``).
    # Raw ``split.path`` is used: ``Path`` would normalize the ``..``
    # segments away and defeat this check.
    segments = split.path.split("/")
    if ".." in segments or "." in segments:
        return False
    return split.path.startswith(dist_dir.as_posix() + "/")


def _get_url_safely(get_url: Callable[[], str | None]) -> str | None:
    """Call ``get_url()`` defensively; None on any failure."""
    try:
        return get_url()
    except Exception:  # noqa: BLE001 (policy layer must never crash the shell)
        return None


class BuildTrust:
    """The URL of the last *completed, local* load (#334, review B2).

    Why this exists (race found during validation): WebKitGTK's
    ``get_uri()`` reflects the most recent load that *started*, not the
    document that is actually alive. During the revert navigation
    (remote → local) there is a window where ``get_uri()`` is already
    the local ``file://`` URL while the **remote document is still
    alive** and could invoke the bridge. A URL check alone would pass
    in that window.

    The trust model closes it: only a URL whose load *completed* as a
    local build page (committed by the ``loaded`` handler, which also
    reverts non-local pages) may serve bridge calls, and the current
    URL must still equal that committed URL.

    **The same-URL window** (reviewer follow-up): the revert navigates
    back to the very ``entry_html`` the window opened with. Because
    ``get_uri()`` flips as soon as that load starts, ``current_url ==
    committed`` is TRUE again while the remote document is still the
    live document. URL equality proves neither identity nor
    completion, so the trust is *revoked* (:meth:`revoke`) the moment
    a non-local load is reported — BEFORE the revert navigation is
    issued — and only the ``loaded`` event of the new local load
    (a fresh commit) may re-open the bridge. There is no state in
    which an in-flight navigation (remote or revert) serves a call.

    Thread-safety: ``loaded`` handlers run on the GUI thread; bridge
    calls arrive on worker threads (WebKit dispatch). A simple lock
    guards the committed value.
    """

    def __init__(self, build: ResolvedBuild) -> None:
        import threading

        self._build = build
        self._lock = threading.Lock()
        self._committed: str | None = None

    def commit_if_local(self, url: str | None) -> bool:
        """Commit ``url`` as trusted iff it is a local build page.

        Called from the ``loaded`` handler (load completed). Returns
        True when the URL was committed as trusted.
        """
        if not is_local_build_url(url, self._build):
            with self._lock:
                self._committed = None
            return False
        with self._lock:
            self._committed = url
        return True

    def revoke(self) -> None:
        """Drop the committed trust immediately.

        Called the moment a non-local load is reported, BEFORE any
        revert ``load_url()`` is issued: from that instant until the
        new local load completes and is committed again, every bridge
        call fails closed — including calls that arrive while
        ``get_uri()`` already reads the local entry URL (the revert
        load started, the remote document may still be alive).
        """
        with self._lock:
            self._committed = None

    def is_trusted(self, current_url: str | None) -> bool:
        """True iff ``current_url`` is exactly the committed local URL.

        The commit only exists between a *completed* local load and
        the next revocation, so any in-flight navigation (remote page
        alive while a revert load already started — even to the same
        URL — or a local page still loading) fails this check and the
        bridge fails closed.
        """
        with self._lock:
            committed = self._committed
        if committed is None:
            return False
        return current_url == committed and is_local_build_url(current_url, self._build)


@dataclass(frozen=True)
class WorkArea:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height


@dataclass(frozen=True)
class ClampedGeometry:
    x: int
    y: int
    width: int
    height: int


def clamp_window_geometry(
    target_rect: tuple[int | None, int | None, int, int],
    workareas: Sequence[WorkArea],
    primary_index: int = 0,
    min_size: tuple[int, int] = (120, 120),
) -> ClampedGeometry:
    """Pure, deterministic clamp ensuring window is reachable and within usable screen bounds.

    - Handles negative coordinates for multi-monitor setups.
    - Uses usable workareas (excluding OS panels/docks).
    - Recovers windows when monitors vanish or resolution shrinks.
    """
    if not workareas:
        workareas = [WorkArea(0, 0, _WINDOW_SIZE[0], _WINDOW_SIZE[1])]

    pri_idx = primary_index if 0 <= primary_index < len(workareas) else 0
    primary_wa = workareas[pri_idx]

    prop_x, prop_y, prop_w, prop_h = target_rect
    w = max(min_size[0], prop_w)
    h = max(min_size[1], prop_h)

    # 1. Unspecified position: center on primary workarea
    if prop_x is None or prop_y is None:
        target_w = min(w, primary_wa.width)
        target_h = min(h, primary_wa.height)
        target_x = primary_wa.x + max(0, (primary_wa.width - target_w) // 2)
        target_y = primary_wa.y + max(0, (primary_wa.height - target_h) // 2)
        return ClampedGeometry(target_x, target_y, target_w, target_h)

    # 2. Select best workarea based on maximum overlap area
    best_wa: WorkArea | None = None
    max_overlap = -1
    for wa in workareas:
        ix1 = max(prop_x, wa.x)
        iy1 = max(prop_y, wa.y)
        ix2 = min(prop_x + w, wa.right)
        iy2 = min(prop_y + h, wa.bottom)
        overlap = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if overlap > max_overlap:
            max_overlap = overlap
            best_wa = wa

    # 3. If zero overlap (e.g. monitor unplugged), pick closest workarea by center distance
    if max_overlap <= 0 or best_wa is None:
        center_x = prop_x + w / 2
        center_y = prop_y + h / 2
        min_dist_sq = float("inf")
        best_wa = primary_wa
        for wa in workareas:
            wa_cx = wa.x + wa.width / 2
            wa_cy = wa.y + wa.height / 2
            dist_sq = (center_x - wa_cx) ** 2 + (center_y - wa_cy) ** 2
            if dist_sq < min_dist_sq:
                min_dist_sq = dist_sq
                best_wa = wa

    # 4. Clamp dimensions to selected workarea
    clamped_w = min(w, best_wa.width)
    clamped_h = min(h, best_wa.height)

    # 5. Clamp coordinates to keep window 100% inside workarea bounds
    max_x = best_wa.x + best_wa.width - clamped_w
    max_y = best_wa.y + best_wa.height - clamped_h

    clamped_x = max(best_wa.x, min(prop_x, max_x))
    clamped_y = max(best_wa.y, min(prop_y, max_y))

    return ClampedGeometry(clamped_x, clamped_y, clamped_w, clamped_h)


def _query_workareas_and_primary() -> tuple[list[WorkArea], int]:
    """Query available monitor workareas from Gdk Display, excluding OS panels/docks."""
    try:
        import sys

        wgtk = sys.modules.get("webview.platforms.gtk")
        has_active_app = wgtk is not None and getattr(wgtk, "_app", None) is not None
        if not has_active_app:
            return [], 0

        import gi

        try:
            gi.require_version("Gdk", "3.0")
        except (ValueError, AttributeError):
            pass
        from gi.repository import Gdk  # type: ignore[import-not-found]

        display = Gdk.Display.get_default()
        if display is None:
            return [], 0
        n = display.get_n_monitors()
        if n > 0:
            primary_mon = (
                display.get_primary_monitor()
                if hasattr(display, "get_primary_monitor")
                else None
            )
            workareas: list[WorkArea] = []
            primary_idx = 0
            for i in range(n):
                mon = display.get_monitor(i)
                if mon is primary_mon:
                    primary_idx = i
                if mon is not None and hasattr(mon, "get_workarea"):
                    rect = mon.get_workarea()
                    workareas.append(
                        WorkArea(rect.x, rect.y, rect.width, rect.height)
                    )
                elif mon is not None and hasattr(mon, "get_geometry"):
                    rect = mon.get_geometry()
                    workareas.append(
                        WorkArea(rect.x, rect.y, rect.width, rect.height)
                    )
            if workareas:
                return workareas, primary_idx
    except Exception:  # noqa: BLE001
        pass

    return [], 0


def _dispatch_sync(
    action: Callable[[], Any], timeout: float = 2.0
) -> tuple[bool, Any]:
    """Execute action synchronously on the GUI main loop thread with bounded timeout.

    If already on the GUI thread or if no GTK main loop is active, runs immediately.
    Returns (True, result) on success, (False, exception) on failure or timeout.
    """
    try:
        from gi.repository import GLib  # type: ignore[import-not-found]
        import sys

        wgtk = sys.modules.get("webview.platforms.gtk")
        has_active_app = wgtk is not None and getattr(wgtk, "_app", None) is not None

        is_owner = False
        try:
            main_ctx = GLib.MainContext.default()
            if main_ctx is not None and hasattr(main_ctx, "is_owner"):
                is_owner = main_ctx.is_owner()
        except Exception:  # noqa: BLE001
            is_owner = False

        if is_owner or not has_active_app:
            try:
                return True, action()
            except Exception as exc:  # noqa: BLE001
                return False, exc

        import threading

        cancelled = threading.Event()
        event = threading.Event()
        result_box: list[Any] = []
        error_box: list[Exception] = []

        def _callback() -> bool:
            if cancelled.is_set():
                return False
            try:
                result_box.append(action())
            except Exception as exc:  # noqa: BLE001
                error_box.append(exc)
            finally:
                event.set()
            return False

        source_id = GLib.idle_add(_callback)
        if not event.wait(timeout=timeout):
            cancelled.set()
            try:
                if hasattr(GLib, "source_remove"):
                    GLib.source_remove(source_id)
            except Exception:  # noqa: BLE001
                pass
            return False, TimeoutError("Window operation timed out.")
        if error_box:
            return False, error_box[0]
        return True, result_box[0] if result_box else None
    except (ImportError, AttributeError):
        try:
            return True, action()
        except Exception as exc:  # noqa: BLE001
            return False, exc


def _dispatch_main_loop(action: Callable[[], Any]) -> None:
    """Legacy helper; delegates to _dispatch_sync."""
    _dispatch_sync(action)


class WindowController:
    """Thread-safe controller for desktop window lifecycle and mode transitions (#342).

    Dispatches native GTK operations (set_decorated, resize, move, on_top, destroy)
    safely onto the GUI main loop via bounded synchronous dispatch while maintaining
    transactional state tracking for mode, geometry, and always-on-top status.
    """

    def __init__(
        self,
        window: Any = None,
        workareas: Sequence[WorkArea] | None = None,
        dispatch_timeout: float = 2.0,
    ) -> None:
        import threading

        self._lock = threading.RLock()
        self._window = window
        self._workareas = workareas
        self._dispatch_timeout = dispatch_timeout
        self._mode = "companion"
        self._on_top = False
        self._width = _WINDOW_SIZE[0]
        self._height = _WINDOW_SIZE[1]
        self._x: int | None = None
        self._y: int | None = None
        self._is_reconciling = False
        self._screen_signals_connected = False
        self._saved_geometry: tuple[int | None, int | None, int, int] = (
            None,
            None,
            _WINDOW_SIZE[0],
            _WINDOW_SIZE[1],
        )
        if window is not None:
            self._bind_window_events(window)

    def _bind_window_events(self, window: Any) -> None:
        """Bind moved and lifecycle event handlers on the pywebview window."""
        if hasattr(window, "events") and hasattr(window.events, "moved"):
            try:
                window.events.moved -= self._on_window_moved
            except (ValueError, KeyError, AttributeError):
                pass
            window.events.moved += self._on_window_moved
        if hasattr(window, "events") and hasattr(window.events, "shown"):
            try:
                window.events.shown -= self._connect_screen_signals
            except (ValueError, KeyError, AttributeError):
                pass
            window.events.shown += self._connect_screen_signals

    def set_window(self, window: Any) -> None:
        """Bind the pywebview window instance after creation."""
        with self._lock:
            self._window = window
            if window is not None:
                self._bind_window_events(window)

    def _connect_screen_signals(self, *args: Any) -> None:
        """Connect to Gdk.Screen signals for monitor/resolution changes (#342, #366)."""
        with self._lock:
            if self._screen_signals_connected:
                return
        try:
            import gi

            try:
                gi.require_version("Gdk", "3.0")
            except (ValueError, AttributeError):
                pass
            from gi.repository import Gdk  # type: ignore[import-not-found]

            display = Gdk.Display.get_default()
            if display is None:
                return

            screen = Gdk.Screen.get_default()
            if screen is not None and hasattr(screen, "connect"):
                screen.connect("monitors-changed", self._on_screen_changed)
                screen.connect("size-changed", self._on_screen_changed)
                with self._lock:
                    self._screen_signals_connected = True
        except Exception:
            pass

    def _on_screen_changed(self, *args: Any) -> None:
        """Reconcile geometry upon display monitor addition, removal, or resolution changes."""
        self.reconcile_geometry()

    def _on_window_moved(self, *args: Any, **kwargs: Any) -> None:
        """Handle window move event (e.g. from drag region or configure-event) with loop protection."""
        if self._is_reconciling:
            return
        int_args = [a for a in args if isinstance(a, int) and not isinstance(a, bool)]
        x = int_args[0] if len(int_args) >= 1 else None
        y = int_args[1] if len(int_args) >= 2 else None
        self.reconcile_geometry(x=x, y=y)

    def reconcile_geometry(
        self, x: int | None = None, y: int | None = None
    ) -> dict[str, Any]:
        """Reconcile window geometry against usable workareas while in presence mode (#342, #366).

        Ensures dragged or shifted presence window stays 100% within usable bounds
        and recovers windows upon resolution or monitor changes.
        Protected against re-entrant event loops.
        """
        with self._lock:
            if self._is_reconciling:
                return {"ok": True, "clamped": False, "in_progress": True}
            if self._window is None:
                return {"ok": False, "code": "window_unavailable"}
            if self._mode != "presence":
                return {"ok": True, "clamped": False, "mode": self._mode}

            window = self._window
            curr_x = x
            curr_y = y
            curr_w = None
            curr_h = None

            native = getattr(window, "native", None)
            if native is not None:
                try:
                    if (curr_x is None or curr_y is None) and hasattr(native, "get_position"):
                        pos = native.get_position()
                        if pos and len(pos) == 2:
                            curr_x, curr_y = pos[0], pos[1]
                    if hasattr(native, "get_size"):
                        sz = native.get_size()
                        if sz and len(sz) == 2:
                            curr_w, curr_h = sz[0], sz[1]
                except Exception:
                    pass

            if curr_x is None:
                curr_x = getattr(window, "x", None)
            if curr_y is None:
                curr_y = getattr(window, "y", None)
            if curr_w is None:
                w_attr = getattr(window, "width", None)
                curr_w = (
                    w_attr
                    if isinstance(w_attr, int) and not isinstance(w_attr, bool)
                    else self._width
                )
            if curr_h is None:
                h_attr = getattr(window, "height", None)
                curr_h = (
                    h_attr
                    if isinstance(h_attr, int) and not isinstance(h_attr, bool)
                    else self._height
                )

            w = curr_w if isinstance(curr_w, int) and curr_w > 0 else 200
            h = curr_h if isinstance(curr_h, int) and curr_h > 0 else 200

            workareas = self._workareas
            primary_idx = 0
            if workareas is None:
                queried, pri = _query_workareas_and_primary()
                if queried:
                    workareas = queried
                    primary_idx = pri

            clamped = clamp_window_geometry(
                (curr_x, curr_y, w, h),
                workareas or [],
                primary_index=primary_idx,
                min_size=(120, 120),
            )

            needs_move = (
                curr_x is not None
                and curr_y is not None
                and (clamped.x != curr_x or clamped.y != curr_y)
            )
            needs_resize = clamped.width != w or clamped.height != h

            if not needs_move and not needs_resize:
                if curr_x is not None:
                    self._x = curr_x
                if curr_y is not None:
                    self._y = curr_y
                self._width = clamped.width
                self._height = clamped.height
                return {
                    "ok": True,
                    "clamped": False,
                    "x": clamped.x,
                    "y": clamped.y,
                    "width": clamped.width,
                    "height": clamped.height,
                }

            self._is_reconciling = True

        try:
            def _apply_reconcile() -> None:
                if needs_resize and hasattr(window, "resize"):
                    window.resize(clamped.width, clamped.height)
                if needs_move and hasattr(window, "move"):
                    window.move(clamped.x, clamped.y)

            ok, err = _dispatch_sync(_apply_reconcile, timeout=self._dispatch_timeout)
            if not ok:
                return {
                    "ok": False,
                    "code": "reconciliation_failed",
                    "error": str(err),
                }
        finally:
            with self._lock:
                self._is_reconciling = False
                self._x = clamped.x
                self._y = clamped.y
                self._width = clamped.width
                self._height = clamped.height

        return {
            "ok": True,
            "clamped": True,
            "x": clamped.x,
            "y": clamped.y,
            "width": clamped.width,
            "height": clamped.height,
        }

    def set_presence_mode(self, enabled: bool) -> dict[str, Any]:
        """Transition between companion and floating presence modes."""
        with self._lock:
            if self._window is None:
                return {
                    "ok": False,
                    "code": "window_unavailable",
                    "message": "The window is not available.",
                }
            window = self._window

            if enabled:
                curr_x: int | None = None
                curr_y: int | None = None
                curr_w: int | None = None
                curr_h: int | None = None

                native = getattr(window, "native", None)
                if native is not None:
                    try:
                        if hasattr(native, "get_position"):
                            curr_x, curr_y = native.get_position()
                        if hasattr(native, "get_size"):
                            curr_w, curr_h = native.get_size()
                    except Exception:  # noqa: BLE001
                        pass

                if curr_x is None:
                    curr_x = getattr(window, "x", None)
                if curr_y is None:
                    curr_y = getattr(window, "y", None)
                if curr_w is None and hasattr(window, "width") and isinstance(window.width, int):
                    curr_w = window.width
                if curr_h is None and hasattr(window, "height") and isinstance(window.height, int):
                    curr_h = window.height

                # Precompute candidate saved geometry only when transitioning from companion
                candidate_saved_geometry = self._saved_geometry
                if self._mode == "companion":
                    candidate_saved_geometry = (
                        curr_x,
                        curr_y,
                        curr_w or self._width or _WINDOW_SIZE[0],
                        curr_h or self._height or _WINDOW_SIZE[1],
                    )

                # Query or use injected workareas
                workareas = self._workareas
                primary_idx = 0
                if workareas is None:
                    queried, pri = _query_workareas_and_primary()
                    if queried:
                        workareas = queried
                        primary_idx = pri

                if workareas:
                    clamped = clamp_window_geometry(
                        (curr_x, curr_y, 200, 200),
                        workareas,
                        primary_index=primary_idx,
                    )
                    presence_w = clamped.width
                    presence_h = clamped.height
                    presence_x = clamped.x
                    presence_y = clamped.y
                else:
                    presence_w = 200
                    presence_h = 200
                    presence_x = curr_x
                    presence_y = curr_y

                orig_w = curr_w or self._width or _WINDOW_SIZE[0]
                orig_h = curr_h or self._height or _WINDOW_SIZE[1]

                def _apply_presence() -> None:
                    nat = getattr(window, "native", None)
                    decorated_modified = False
                    resized = False
                    if nat is not None and hasattr(nat, "set_decorated"):
                        nat.set_decorated(False)
                        decorated_modified = True
                    try:
                        if hasattr(window, "resize"):
                            window.resize(presence_w, presence_h)
                            resized = True
                        if hasattr(window, "move") and presence_x is not None and presence_y is not None:
                            if presence_x != curr_x or presence_y != curr_y:
                                window.move(presence_x, presence_y)
                    except Exception:
                        if resized and hasattr(window, "resize"):
                            try:
                                window.resize(orig_w, orig_h)
                            except Exception:  # noqa: BLE001
                                pass
                        if decorated_modified and hasattr(nat, "set_decorated"):
                            try:
                                nat.set_decorated(True)
                            except Exception:  # noqa: BLE001
                                pass
                        raise

                ok, err = _dispatch_sync(_apply_presence, timeout=self._dispatch_timeout)
                if not ok:
                    code = "timeout" if isinstance(err, TimeoutError) else "window_mutation_failed"
                    return {
                        "ok": False,
                        "code": code,
                        "message": "The window operation could not be completed.",
                    }

                self._connect_screen_signals()

                # Commit transactional state only after confirmed success
                self._saved_geometry = candidate_saved_geometry
                self._mode = "presence"
                self._width = presence_w
                self._height = presence_h
                self._x = presence_x
                self._y = presence_y

                return {
                    "ok": True,
                    "mode": "presence",
                    "on_top": self._on_top,
                    "width": self._width,
                    "height": self._height,
                }
            else:
                saved_x, saved_y, saved_w, saved_h = self._saved_geometry
                target_w = saved_w or _WINDOW_SIZE[0]
                target_h = saved_h or _WINDOW_SIZE[1]

                # Query or use injected workareas
                workareas = self._workareas
                primary_idx = 0
                if workareas is None:
                    queried, pri = _query_workareas_and_primary()
                    if queried:
                        workareas = queried
                        primary_idx = pri

                if workareas:
                    clamped = clamp_window_geometry(
                        (saved_x, saved_y, target_w, target_h),
                        workareas,
                        primary_index=primary_idx,
                    )
                    companion_w = clamped.width
                    companion_h = clamped.height
                    companion_x = clamped.x
                    companion_y = clamped.y
                else:
                    companion_w = target_w
                    companion_h = target_h
                    companion_x = saved_x
                    companion_y = saved_y

                presence_w = getattr(window, "width", None)
                if not isinstance(presence_w, int):
                    presence_w = self._width if isinstance(self._width, int) else 200
                presence_h = getattr(window, "height", None)
                if not isinstance(presence_h, int):
                    presence_h = self._height if isinstance(self._height, int) else 200

                def _apply_companion() -> None:
                    nat = getattr(window, "native", None)
                    decorated_modified = False
                    resized = False
                    if nat is not None and hasattr(nat, "set_decorated"):
                        nat.set_decorated(True)
                        decorated_modified = True
                    try:
                        if hasattr(window, "resize"):
                            window.resize(companion_w, companion_h)
                            resized = True
                        if hasattr(window, "move") and companion_x is not None and companion_y is not None:
                            window.move(companion_x, companion_y)
                    except Exception:
                        if resized and hasattr(window, "resize"):
                            try:
                                window.resize(presence_w, presence_h)
                            except Exception:  # noqa: BLE001
                                pass
                        if decorated_modified and hasattr(nat, "set_decorated"):
                            try:
                                nat.set_decorated(False)
                            except Exception:  # noqa: BLE001
                                pass
                        raise

                ok, err = _dispatch_sync(_apply_companion, timeout=self._dispatch_timeout)
                if not ok:
                    code = "timeout" if isinstance(err, TimeoutError) else "window_mutation_failed"
                    return {
                        "ok": False,
                        "code": code,
                        "message": "The window operation could not be completed.",
                    }

                # Commit transactional state only after confirmed success
                self._mode = "companion"
                self._width = companion_w
                self._height = companion_h
                self._x = companion_x
                self._y = companion_y

                return {
                    "ok": True,
                    "mode": "companion",
                    "on_top": self._on_top,
                    "width": self._width,
                    "height": self._height,
                }

    def set_always_on_top(self, enabled: bool) -> dict[str, Any]:
        """Toggle always-on-top layering for the window."""
        with self._lock:
            if self._window is None:
                return {
                    "ok": False,
                    "code": "window_unavailable",
                    "message": "The window is not available.",
                }
            window = self._window

            def _apply_on_top() -> None:
                if hasattr(window, "on_top"):
                    window.on_top = enabled
                else:
                    raise RuntimeError("Native window capability not supported")

            ok, err = _dispatch_sync(_apply_on_top, timeout=self._dispatch_timeout)
            if not ok:
                code = "timeout" if isinstance(err, TimeoutError) else "window_mutation_failed"
                return {
                    "ok": False,
                    "code": code,
                    "message": "The window operation could not be completed.",
                }

            self._on_top = enabled
            return {"ok": True, "on_top": enabled}

    def minimize_window(self) -> dict[str, Any]:
        """Minimize the window to the desktop taskbar/dock (#342)."""
        with self._lock:
            if self._window is None:
                return {
                    "ok": False,
                    "code": "window_unavailable",
                    "message": "The window is not available.",
                }
            window = self._window

            def _apply_minimize() -> None:
                if hasattr(window, "minimize"):
                    window.minimize()
                else:
                    native = getattr(window, "native", None)
                    if native is not None and hasattr(native, "iconify"):
                        native.iconify()
                    else:
                        raise RuntimeError("Native window capability not supported")

            ok, err = _dispatch_sync(_apply_minimize, timeout=self._dispatch_timeout)
            if not ok:
                code = "timeout" if isinstance(err, TimeoutError) else "window_mutation_failed"
                return {
                    "ok": False,
                    "code": code,
                    "message": "The window operation could not be completed.",
                }

            return {"ok": True}

    def window_state(self) -> dict[str, Any]:
        """Return current window state snapshot."""
        with self._lock:
            state: dict[str, Any] = {
                "ok": True,
                "mode": self._mode,
                "on_top": self._on_top,
                "width": self._width,
                "height": self._height,
            }
            if self._x is not None:
                state["x"] = self._x
            if self._y is not None:
                state["y"] = self._y
            return state

    def close_window(self) -> dict[str, Any]:
        """Request window destruction and clean shell shutdown."""
        with self._lock:
            if self._window is None:
                return {
                    "ok": False,
                    "code": "window_unavailable",
                    "message": "The window is not available.",
                }
            window = self._window

            def _apply_close() -> None:
                if hasattr(window, "destroy"):
                    window.destroy()
                else:
                    raise RuntimeError("Native window capability not supported")

            ok, err = _dispatch_sync(_apply_close, timeout=self._dispatch_timeout)
            if not ok:
                code = "timeout" if isinstance(err, TimeoutError) else "window_mutation_failed"
                return {
                    "ok": False,
                    "code": code,
                    "message": "The window operation could not be completed.",
                }

            return {"ok": True}


class LocalBuildBridge:
    """``js_api`` facade that fails closed outside the local build (#334).

    Wraps the sanitized :class:`~backend.desktop.api.DesktopBridge` with
    the navigation policy: every call first verifies that the window is
    still showing the trusted local build page (see :class:`BuildTrust`).
    If not, the call returns a sanitized ``bridge_unavailable`` payload —
    remote content never reaches the underlying Python methods, including
    during the revert race window (remote document alive while the
    revert load already changed ``get_uri()``).

    The public surface stays exactly ``DESKTOP_API_METHODS`` (pywebview
    exposes every public attribute), and no public method ever raises
    (pywebview would convert exceptions into JS ``Error`` objects
    carrying stacktrace information).
    """

    def __init__(
        self,
        bridge: Any,
        build: ResolvedBuild,
        get_url: Callable[[], str | None],
        trust: BuildTrust | None = None,
    ) -> None:
        # ``bridge`` is the sanitized facade from make_js_api(); typed Any
        # to keep this layer decoupled from the concrete facade class.
        self._bridge = bridge
        self._build = build
        self._get_url = get_url
        self._trust = trust if trust is not None else BuildTrust(build)

    def _serve(self, op: str, args: tuple[Any, ...]) -> dict[str, Any]:
        """Shared fail-closed wrapper for one allowlisted op."""
        url = _get_url_safely(self._get_url)
        if not (
            is_local_build_url(url, self._build) and self._trust.is_trusted(url)
        ):
            return {
                "ok": False,
                "code": ERROR_BRIDGE_UNAVAILABLE,
                "message": _MSG_BRIDGE_UNAVAILABLE,
            }
        try:
            result = getattr(self._bridge, op)(*args)
        except DesktopApiError as err:
            return err.payload
        except Exception:  # noqa: BLE001 (boundary: never leak internals to JS)
            return {"ok": False, "code": "internal_error", "message": _MSG_INTERNAL}
        if not isinstance(result, dict):
            return {"ok": False, "code": "internal_error", "message": _MSG_INTERNAL}
        return result

    # -- allowlisted surface (exactly DESKTOP_API_METHODS) -----------------

    def health(self, *args: Any) -> dict[str, Any]:
        """Allowlisted round-trip, local-build-only; never raises."""
        return self._serve("health", args)

    def runtime_state(self, *args: Any) -> dict[str, Any]:
        """Readiness probe, local-build-only; never raises."""
        return self._serve("runtime_state", args)

    def load_history(self, *args: Any) -> dict[str, Any]:
        """Bounded history read, local-build-only; never raises."""
        return self._serve("load_history", args)

    def send_message(self, *args: Any) -> dict[str, Any]:
        """One conversation turn, local-build-only; never raises."""
        return self._serve("send_message", args)

    def delete_history(self, *args: Any) -> dict[str, Any]:
        """Privacy: erase history, local-build-only; never raises."""
        return self._serve("delete_history", args)

    def delete_memories(self, *args: Any) -> dict[str, Any]:
        """Privacy: erase memories, local-build-only; never raises."""
        return self._serve("delete_memories", args)

    def reset_emotional_state(self, *args: Any) -> dict[str, Any]:
        """Privacy: reset emotional state, local-build-only; never raises."""
        return self._serve("reset_emotional_state", args)

    def reset_relationship_state(self, *args: Any) -> dict[str, Any]:
        """Privacy: reset relationship state, local-build-only; never raises."""
        return self._serve("reset_relationship_state", args)

    def set_presence_mode(self, *args: Any) -> dict[str, Any]:
        """Window presence mode, local-build-only; never raises."""
        return self._serve("set_presence_mode", args)

    def set_always_on_top(self, *args: Any) -> dict[str, Any]:
        """Window always on top, local-build-only; never raises."""
        return self._serve("set_always_on_top", args)

    def window_state(self, *args: Any) -> dict[str, Any]:
        """Window state query, local-build-only; never raises."""
        return self._serve("window_state", args)

    def close_window(self, *args: Any) -> dict[str, Any]:
        """Window close, local-build-only; never raises."""
        return self._serve("close_window", args)

    def minimize_window(self, *args: Any) -> dict[str, Any]:
        """Window minimize, local-build-only; never raises."""
        return self._serve("minimize_window", args)


class NavigationPolicy:
    """The ``loaded``-handler logic, extracted to be testable (#334).

    Contract (all transitions explicit, no timing assumptions):

    * local load completed → commit the URL as trusted;
    * non-local load reported → revoke the trust FIRST, then issue the
      revert ``load_url`` to the entry page;
    * while the revert is in flight (``get_uri()`` may already read the
      same entry URL) → the trust stays revoked, so the bridge stays
      closed;
    * new local load completed → the ``loaded`` event commits again and
      the bridge re-opens.

    The object is deliberately passive: no polling, no threads, no
    timers. It acts only when the window fires ``loaded``.
    """

    def __init__(
        self, window: Any, build: ResolvedBuild, entry_uri: str, trust: BuildTrust
    ) -> None:
        self._window = window
        self._build = build
        self._entry_uri = entry_uri
        self._trust = trust

    def on_loaded(self) -> None:
        """Handle one ``loaded`` event (a load completed in the window)."""
        url = _get_url_safely(self._window.get_current_url)
        if is_local_build_url(url, self._build):
            self._trust.commit_if_local(url)
        else:
            # Non-local document reported: drop the trust BEFORE the
            # revert navigation starts. From this instant the bridge is
            # closed for every caller, including one that arrives while
            # get_uri() already reads the same entry URL again (the
            # revert load started, the remote document may still be
            # the live document).
            self._trust.revoke()
            self._window.load_url(self._entry_uri)


def make_navigation_policy(
    window: Any,
    build: ResolvedBuild,
    *,
    entry_uri: str | None = None,
    trust: BuildTrust | None = None,
) -> NavigationPolicy:
    """Build the :class:`NavigationPolicy` for a shell window.

    ``entry_uri`` defaults to ``build.desktop_html.as_uri()`` (the
    desktop companion entry; production passes the page it opened,
    e.g. the smoke page).
    ``trust`` defaults to a fresh :class:`BuildTrust`; production
    passes the one the bridge shares so both layers stay in sync.
    """
    resolved_entry = entry_uri if entry_uri is not None else build.desktop_html.as_uri()
    return NavigationPolicy(
        window=window,
        build=build,
        entry_uri=resolved_entry,
        trust=trust if trust is not None else BuildTrust(build),
    )


def run_desktop_shell(
    frontend_root: Path | None = None,
    *,
    html_name: str = "desktop.html",
    storage_path: Path | str | None = None,
    provider: Any = None,
) -> int:
    """Open the desktop window and block until it is closed.

    Returns 0 on clean close. Raises :class:`BuildResolutionError` (or
    ``ValueError`` for an invalid root) *before* any window is created,
    so startup failures are explicit and safe to print.

    ``html_name`` selects which page inside the resolved build opens
    first. Production uses the default ``desktop.html`` — the desktop
    companion entry whose module graph contains no web modules (#336,
    review blocker 1; web entry is index.html and is never loaded by
    the shell). The reproducible smoke (#334, review B3) opens
    ``desktop-smoke.html`` which mounts the real ChatWindow. The page
    must exist inside ``dist`` (the resolver still validates the build
    root), and the navigation policy treats every page inside ``dist``
    as local build content.

    ``storage_path`` / ``provider`` are smoke-test seams only (#336):
    the reproducible smoke must not touch the user's real database or
    spend real provider quota. Production callers never pass them —
    the default path and the real Groq provider factory stay exactly
    as they are.

    Frontend root resolution (#338): with no explicit ``frontend_root``,
    the root is derived structurally from this package's own location
    (``default_frontend_root``), so the shell works both in a checkout
    and from the installed ``.deb`` layout at ``/usr/lib/katherine`` —
    never from the CWD, never requiring a checkout or ``PYTHONPATH``.
    """
    root = frontend_root if frontend_root is not None else default_frontend_root()
    config = DesktopBuildConfig(frontend_root=root)
    build = resolve_frontend_build(config)

    entry_html = build.dist_dir / html_name
    if not entry_html.is_file():
        raise BuildResolutionError(
            f"Frontend page {html_name!r} not found in the build. " + _BUILD_HINT
        )

    # Runtime lifecycle (#336): constructed before the window so the
    # bridge it serves is wired exactly once; closed after the window
    # loop returns (window close ⇒ clean shutdown, always, via finally).
    if storage_path is None and provider is None:
        runtime = _build_runtime()
    else:
        from backend.companion_runtime import CompanionRuntime

        runtime = CompanionRuntime(
            storage_path=storage_path,
            language_model=provider,
        )

    # ``create_window`` returns the Window synchronously, before
    # ``webview.start()``; the holder is populated right after creation so
    # the URL guard can query it. The bridge is delivered at creation time
    # (js_api=), never reassigned afterwards.
    window_holder: list[Any] = []
    trust = BuildTrust(build)

    def _current_url() -> str | None:
        if not window_holder:
            return None
        return _get_url_safely(window_holder[0].get_current_url)

    window_controller = WindowController()
    bridge_facade = make_js_api(runtime=runtime, window_controller=window_controller)
    js_api = LocalBuildBridge(bridge_facade, build, _current_url, trust)

    window = webview.create_window(
        title=_WINDOW_TITLE,
        url=entry_html.as_uri(),
        js_api=js_api,
        width=_WINDOW_SIZE[0],
        height=_WINDOW_SIZE[1],
        transparent=True,
        min_size=(120, 120),
    )
    window_holder.append(window)
    window_controller.set_window(window)

    # Policy layer 1: on every completed load, commit local pages as
    # trusted and revert non-local navigation back to the build. A
    # non-local load REVOKES the trust before the revert ``load_url``
    # is issued, so the bridge stays closed for the whole revert —
    # including the window where get_uri() already reads the same
    # entry URL while the remote document is still the live one.
    policy = make_navigation_policy(
        window=window,
        build=build,
        entry_uri=entry_html.as_uri(),
        trust=trust,
    )
    window.events.loaded += policy.on_loaded
    window.events.loaded += window_controller._connect_screen_signals

    try:
        webview.start()
    finally:
        # Window closed (or the loop raised): shut the runtime down
        # cleanly. Idempotent and never raises.
        runtime.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    """Console entrypoint: ``python -m backend.desktop.app``.

    Prints a sanitized, actionable message on predictable startup errors
    (missing build, invalid root) and returns a non-zero exit code.
    Never falls back to opening anything else.
    """
    try:
        return run_desktop_shell()
    except BuildResolutionError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    except ValueError as err:
        print(f"error: invalid desktop configuration: {err}", file=sys.stderr)
        return 2
    except Exception:  # noqa: BLE001 (startup boundary: sanitized output only)
        # Any unexpected startup failure (corrupt local database,
        # unwritable storage): print the constant, sanitized message —
        # never a path, traceback or internal detail — and exit 2.
        print(f"error: {_MSG_RUNTIME_STARTUP}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
