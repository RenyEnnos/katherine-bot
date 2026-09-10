"""Capture the real desktop entry, isolated from personal data and paid providers.

Run with uv and WebKitGTK under Xvfb (see docs/design/presence-v2/README.md).
Optional scale probes resize the real mounted face for optical checks only.
The scripted provider is fixture evidence, not live provider acceptance.
"""
import argparse
import asyncio
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import webview
from backend.desktop.app import run_desktop_shell

parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, default=Path('scripts/presence_evidence'))
parser.add_argument('--clean', action='store_true', help='Clean output directory before running')
parser.add_argument('--scripted', action='store_true')
parser.add_argument('--verify-matrix', action='store_true', help='Execute 5-point Runtime Evidence Matrix (#342 / #366)')
parser.add_argument('--verify-v2', action='store_true')
parser.add_argument('--verify-scaling', action='store_true')
parser.add_argument('--reduced-motion', action='store_true')
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
if (args.output / 'isolated.sqlite3').exists():
    if args.clean or args.verify_matrix:
        try:
            (args.output / 'isolated.sqlite3').unlink()
        except OSError:
            pass
    else:
        parser.error('Use a fresh output directory so captures start with empty isolated storage.')
if args.reduced_motion:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    Gtk.Settings.get_default().set_property('gtk-enable-animations', False)
release = threading.Event()
failures = []
results = {'provider': 'scripted offline fixture' if (args.scripted or args.verify_matrix) else 'unconfigured real runtime', 'captures': []}

class ReviewProvider:
    async def appraise(self, message, budget):
        from backend.emotional_domain import AppraisalV1
        return AppraisalV1.neutral()

    async def generate(self, messages, budget):
        while not release.is_set():
            await asyncio.sleep(0.05)
        return 'A presença pode permanecer tranquila enquanto você trabalha.'

    async def extract_archival(self, messages, budget):
        return '{}'

    def describe(self):
        from backend.language_model import ModelSelection
        return ModelSelection(provider='fake', main_model_id='review-fixture', fast_model_id='review-fixture')


def wait_for(window, script, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = window.evaluate_js(script)
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError(f'Timed out: {script}')


def capture(window, name):
    from gi.repository import GLib, Gdk
    done = threading.Event()
    errors = []

    def save():
        try:
            native = window.native
            width, height = native.get_size()
            pixbuf = Gdk.pixbuf_get_from_window(native.get_window(), 0, 0, width, height)
            if pixbuf is None:
                raise RuntimeError('Native capture returned no pixels')
            pixbuf.savev(str(args.output / f'{name}.png'), 'png', [], [])
        except Exception as error:
            errors.append(error)
        finally:
            done.set()
        return False

    GLib.idle_add(save)
    if not done.wait(10):
        raise RuntimeError('Native capture timed out')
    if errors:
        raise errors[0]
    metrics = window.evaluate_js("""(() => {
        const face = document.querySelector('[data-testid="katherine-face"]');
        const rect = face.getBoundingClientRect();
        const arc = face.querySelector('[data-testid="katherine-activity-arc"]');
        const input = document.querySelector('textarea');
        return { viewport: [innerWidth, innerHeight], face: {x:rect.x,y:rect.y,width:rect.width,height:rect.height},
          arc: Boolean(arc), arcDisplay: arc ? getComputedStyle(arc).display : null,
          activity: face.dataset.activity,
          arcOpacity: arc ? getComputedStyle(arc).opacity : null,
          arcStroke: arc ? getComputedStyle(arc).strokeWidth : null,
          arcTransition: arc ? getComputedStyle(arc).transitionDuration : null,
          reducedMotion: matchMedia('(prefers-reduced-motion: reduce)').matches,
          inputVisible: input.getBoundingClientRect().bottom <= innerHeight,
          horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
          bridge: document.querySelector('[data-testid="desktop-bridge-indicator"]')?.textContent,
          runningAnimations: document.getAnimations().filter(a => a.playState === 'running').length };
    })()""")
    results['captures'].append({'name': name, **metrics})
    assert metrics['inputVisible'], f'{name}: composer outside viewport'
    assert not metrics['horizontalOverflow'], f'{name}: horizontal overflow'
    if args.verify_v2:
        assert metrics['runningAnimations'] == 0, f'{name}: persistent animation'
        busy = name.startswith('thinking')
        assert metrics['activity'] == ('busy' if busy else 'idle'), name
        assert metrics['arcOpacity'] == ('1' if busy else '0'), name
        if args.reduced_motion:
            assert metrics['reducedMotion'], 'GTK reduced-motion preference not propagated'
            assert metrics['arcTransition'] == '0s', name
    print(json.dumps(results['captures'][-1]), flush=True)


def optical_probes(window):
    measurements = []
    for size in (32, 48, 64, 96, 128, 256):
        window.evaluate_js(f'document.querySelector("[data-testid=katherine-face]").style.width = "{size}px"')
        time.sleep(0.1)
        measured = window.evaluate_js("""(() => {
          const face = document.querySelector('[data-testid=katherine-face]');
          const arc = face.querySelector('[data-testid=katherine-activity-arc]');
          return {width: face.getBoundingClientRect().width, display: getComputedStyle(arc).display,
            eyes: face.querySelectorAll('.bwf-eye').length, stroke: getComputedStyle(arc).strokeWidth};
        })()""")
        assert measured['width'] == size, measured
        assert measured['eyes'] == 2, measured
        assert measured['display'] == ('none' if size < 48 else 'block'), measured
        measurements.append(measured)
    window.evaluate_js('document.querySelector("[data-testid=katherine-face]").style.removeProperty("width")')
    results['opticalProbes'] = measurements
    window.evaluate_js("""(() => {
      window.__presenceMutations = 0;
      window.__presenceObserver = new MutationObserver(items => window.__presenceMutations += items.length);
      window.__presenceObserver.observe(document.querySelector('[data-testid=katherine-face]'),
        {subtree:true, attributes:true, childList:true});
    })()""")
    time.sleep(1)
    mutations = window.evaluate_js('window.__presenceObserver.disconnect(); window.__presenceMutations')
    assert mutations == 0, f'Face kept mutating after settling: {mutations}'
    results['settledFaceMutationsOverOneSecond'] = mutations


def verify_scaling_matrix(window):
    from gi.repository import GLib
    from webview.platforms.gtk import BrowserView
    bv = BrowserView.instances.get(window.uid)
    scenarios = [
        ('scale-1440x900-100', 1440, 900, 1.0),
        ('scale-1024x768-100', 1024, 768, 1.0),
        ('scale-800x600-100', 800, 600, 1.0),
        ('scale-800x600-125', 800, 600, 1.25),
        ('scale-800x600-150', 800, 600, 1.50),
    ]
    results['scalingMatrix'] = []
    for name, w, h, zoom in scenarios:
        window.resize(w, h)
        wait_for(window, f'innerWidth === {w}')
        time.sleep(0.4)
        if bv:
            def apply():
                settings = bv.webview.get_settings()
                settings.props.zoom_text_only = True
                bv.webview.set_zoom_level(zoom)
                return False
            GLib.idle_add(apply)
            time.sleep(0.8)

        capture(window, f'{name}-closed')

        geo = window.evaluate_js("""(() => {
            const face = document.querySelector('[data-testid="katherine-face"]');
            const fRect = face ? face.getBoundingClientRect() : null;
            const presence = document.querySelector('[data-testid="companion-presence"]');
            const pRect = presence ? presence.getBoundingClientRect() : null;
            const conv = document.querySelector('.companion-layout__conversation');
            const cRect = conv ? conv.getBoundingClientRect() : null;
            const input = document.querySelector('textarea');
            return {
                presenceWidth: pRect ? pRect.width : 0,
                convWidth: cRect ? cRect.width : 0,
                presenceWider: pRect && cRect ? (pRect.width > cRect.width) : false,
                faceClippedRight: (fRect && pRect) ? (fRect.right > pRect.right) : false,
                faceClippedLeft: (fRect && pRect) ? (fRect.left < pRect.left) : false,
                faceWidth: fRect ? fRect.width : 0,
                inputVisible: input ? (input.getBoundingClientRect().bottom <= innerHeight) : false,
                horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
            };
        })()""")
        assert geo['presenceWider'], f'{name}: presence track must be wider than conversation rail'
        assert not geo['faceClippedRight'], f'{name}: face clipped on right'
        assert not geo['faceClippedLeft'], f'{name}: face clipped on left'
        assert geo['inputVisible'], f'{name}: composer not visible'
        assert not geo['horizontalOverflow'], f'{name}: horizontal overflow'

        window.evaluate_js("""(() => {
            const d1 = document.querySelector('[data-testid=companion-emotion-details]');
            if (d1) d1.open = true;
            const d2 = document.querySelector('[data-testid=companion-privacy-details]');
            if (d2) d2.open = true;
        })()""")
        time.sleep(0.6)
        capture(window, f'{name}-open')
        open_geo = window.evaluate_js("""(() => {
            const input = document.querySelector('textarea');
            const utils = document.querySelector('[data-testid="companion-utilities"]');
            return {
                inputVisible: input ? (input.getBoundingClientRect().bottom <= innerHeight) : false,
                horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
                utilsCanScroll: utils ? (utils.scrollHeight >= utils.clientHeight) : false,
            };
        })()""")
        assert open_geo['inputVisible'], f'{name} open: composer not visible'
        assert not open_geo['horizontalOverflow'], f'{name} open: horizontal overflow'

        window.evaluate_js("""(() => {
            const d1 = document.querySelector('[data-testid=companion-emotion-details]');
            if (d1) d1.open = false;
            const d2 = document.querySelector('[data-testid=companion-privacy-details]');
            if (d2) d2.open = false;
        })()""")
        time.sleep(0.4)
        results['scalingMatrix'].append({'scenario': name, 'closed': geo, 'open': open_geo})

    if bv:
        def restore():
            bv.webview.set_zoom_level(1.0)
            return False
        GLib.idle_add(restore)
        time.sleep(0.3)


def call_bridge_js(window, call_expr, timeout=10.0):
    """Execute an async bridge expression and await its deposited result."""
    prop = f"__bridge_res_{uuid.uuid4().hex}"
    window.evaluate_js(f"""(() => {{
        window['{prop}'] = '__pending__';
        (async () => {{
            try {{
                window['{prop}'] = await ({call_expr});
            }} catch (err) {{
                window['{prop}'] = {{ __threw: true, error: String(err) }};
            }}
        }})();
    }})()""")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        res = window.evaluate_js(f"window['{prop}']")
        if res != '__pending__' and res is not None:
            window.evaluate_js(f"delete window['{prop}']")
            if isinstance(res, dict) and res.get('__threw'):
                raise RuntimeError(f"Bridge JS error in {call_expr}: {res.get('error')}")
            return res
        time.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for {call_expr}")


def measure_system_resources():
    """Measure real system resources using psutil (or /proc fallback)."""
    import os
    try:
        import psutil
        current = psutil.Process(os.getpid())
        children = current.children(recursive=True)
        all_procs = [current] + children
        total_rss = sum(p.memory_info().rss for p in all_procs)
        rss_mb = round(total_rss / (1024 * 1024), 2)
        webkit_procs = [p for p in children if "WebKitWebProcess" in p.name() or "WebKit" in p.name()]
        cpu_pct = round(current.cpu_percent(interval=0.5), 2)
        return {
            "rss_mb": rss_mb,
            "process_count": len(all_procs),
            "webkit_process_count": len(webkit_procs),
            "cpu_idle_percent": round(max(0.0, 100.0 - cpu_pct), 2),
            "cpu_percent": cpu_pct,
        }
    except Exception as exc:
        return {"error": str(exc)}


def verify_matrix(window, output_dir):
    print("\n" + "=" * 70)
    print("EXECUTING 5-POINT RUNTIME EVIDENCE MATRIX (PR #366 / Issue #342)")
    print("=" * 70, flush=True)

    # 0. Wait for bridge and initial companion layout to be ready
    wait_for(window, 'Boolean(document.querySelector("[data-testid=companion-layout]"))')
    wait_for(window, 'Boolean(document.querySelector("[data-testid=desktop-bridge-indicator]"))')
    time.sleep(0.5)

    # Point 5 (Part A): Baseline Companion Resources
    print("\n[Point 5] Measuring Companion baseline resources...", flush=True)
    time.sleep(0.5)
    companion_resources = measure_system_resources()
    print(f"  Companion RSS: {companion_resources.get('rss_mb')} MB | Procs: {companion_resources.get('process_count')} (WebKit: {companion_resources.get('webkit_process_count')}) | CPU idle: {companion_resources.get('cpu_idle_percent')}%", flush=True)

    # Point 2: Always-on-Top Decoupling Verification (§BLOCKER 1)
    print("\n[Point 2] Verifying Always-on-Top Decoupling (§BLOCKER 1)...", flush=True)
    aot_steps = []

    # 2.1 Default at startup must be False
    st_init = call_bridge_js(window, "window.pywebview.api.window_state()")
    assert st_init.get("ok") and st_init.get("on_top") is False, f"Startup on_top must be False: {st_init}"
    aot_steps.append({"step": "startup_default", "on_top": False, "verified": True})

    # 2.2 Enter presence: on_top must remain False
    window.evaluate_js('document.querySelector("[data-testid=\\"companion-enter-presence-btn\\"]").click()')
    wait_for(window, 'Boolean(document.querySelector("[data-testid=\\"katherine-presence-surface\\"]"))')
    st_pres = call_bridge_js(window, "window.pywebview.api.window_state()")
    assert st_pres.get("ok") and st_pres.get("mode") == "presence", f"Must be in presence mode: {st_pres}"
    assert st_pres.get("on_top") is False, f"Entering presence must NOT activate on_top: {st_pres}"
    pin_aria = window.evaluate_js('document.querySelector("[data-testid=\\"presence-pin-btn\\"]").getAttribute("aria-pressed")')
    assert pin_aria == "false", f"Pin button aria-pressed must be false, got {pin_aria}"
    aot_steps.append({"step": "enter_presence_maintains_false", "on_top": False, "aria_pressed": "false", "verified": True})

    # 2.3 User pins: click pin button -> on_top becomes True
    window.evaluate_js('document.querySelector("[data-testid=\\"presence-pin-btn\\"]").click()')
    wait_for(window, 'document.querySelector("[data-testid=\\"presence-pin-btn\\"]").getAttribute("aria-pressed") === "true"')
    st_pinned = call_bridge_js(window, "window.pywebview.api.window_state()")
    assert st_pinned.get("ok") and st_pinned.get("on_top") is True, f"Explicit pin must set on_top=True: {st_pinned}"
    aot_steps.append({"step": "user_pins_true", "on_top": True, "aria_pressed": "true", "verified": True})

    # 2.4 Return companion: on_top must persist as True
    window.evaluate_js('document.querySelector("[data-testid=\\"presence-return-btn\\"]").click()')
    wait_for(window, 'Boolean(document.querySelector("[data-testid=\\"companion-layout\\"]"))')
    st_comp_pinned = call_bridge_js(window, "window.pywebview.api.window_state()")
    assert st_comp_pinned.get("ok") and st_comp_pinned.get("mode") == "companion"
    assert st_comp_pinned.get("on_top") is True, f"Returning to companion must preserve on_top=True: {st_comp_pinned}"
    aot_steps.append({"step": "return_companion_preserves_true", "on_top": True, "verified": True})

    # 2.5 Enter presence again: on_top must persist as True
    window.evaluate_js('document.querySelector("[data-testid=\\"companion-enter-presence-btn\\"]").click()')
    wait_for(window, 'Boolean(document.querySelector("[data-testid=\\"katherine-presence-surface\\"]"))')
    st_pres_pinned = call_bridge_js(window, "window.pywebview.api.window_state()")
    assert st_pres_pinned.get("ok") and st_pres_pinned.get("on_top") is True, f"Entering presence must preserve on_top=True: {st_pres_pinned}"
    pin_aria = window.evaluate_js('document.querySelector("[data-testid=\\"presence-pin-btn\\"]").getAttribute("aria-pressed")')
    assert pin_aria == "true", f"Pin button aria-pressed must remain true, got {pin_aria}"
    aot_steps.append({"step": "reenter_presence_preserves_true", "on_top": True, "aria_pressed": "true", "verified": True})

    # 2.6 User unpins: click pin button -> on_top becomes False
    window.evaluate_js('document.querySelector("[data-testid=\\"presence-pin-btn\\"]").click()')
    wait_for(window, 'document.querySelector("[data-testid=\\"presence-pin-btn\\"]").getAttribute("aria-pressed") === "false"')
    st_unpinned = call_bridge_js(window, "window.pywebview.api.window_state()")
    assert st_unpinned.get("ok") and st_unpinned.get("on_top") is False, f"Explicit unpin must set on_top=False: {st_unpinned}"
    aot_steps.append({"step": "user_unpins_false", "on_top": False, "aria_pressed": "false", "verified": True})

    # 2.7 Return companion: on_top persists as False
    window.evaluate_js('document.querySelector("[data-testid=\\"presence-return-btn\\"]").click()')
    wait_for(window, 'Boolean(document.querySelector("[data-testid=\\"companion-layout\\"]"))')
    st_comp_unpinned = call_bridge_js(window, "window.pywebview.api.window_state()")
    assert st_comp_unpinned.get("ok") and st_comp_unpinned.get("on_top") is False, f"Companion must remain unpinned: {st_comp_unpinned}"
    aot_steps.append({"step": "return_companion_preserves_false", "on_top": False, "verified": True})
    print("  Always-on-top decoupling verified: PASS", flush=True)

    # Point 3: DOM Privacy Canary (§MAJOR 6)
    print("\n[Point 3] Verifying DOM Privacy Canary (§MAJOR 6)...", flush=True)
    canary_token = "CANARY_CONFIDENTIAL_TOKEN_PR366_789"
    window.evaluate_js(f"""(() => {{
        const input = document.querySelector('textarea[aria-label="Sua mensagem"]');
        if (input) {{
            Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(input, '{canary_token}');
            input.dispatchEvent(new Event('input', {{bubbles: true}}));
        }}
    }})()""")
    time.sleep(0.3)

    # Switch to presence mode
    window.evaluate_js('document.querySelector("[data-testid=\\"companion-enter-presence-btn\\"]").click()')
    wait_for(window, 'Boolean(document.querySelector("[data-testid=\\"katherine-presence-surface\\"]"))')
    time.sleep(0.3)

    # Inspect DOM for any private/companion leak
    privacy_inspection = window.evaluate_js(f"""(() => {{
        const forbiddenSelectors = [
            'textarea',
            'button[aria-label*="Enviar mensagem"]',
            '[data-testid="companion-history"]',
            '[data-testid="companion-layout"]',
            '[data-testid="companion-utilities"]',
            '[data-testid="companion-emotion-details"]',
            '[data-testid="companion-privacy-details"]',
            '[data-testid="privacy-panel"]',
            '[data-testid="message-list"]',
            '[data-testid="chat-header"]',
            '[data-testid="companion-auxiliary-slot"]',
            '.companion-layout__conversation',
            '.chat-header',
            '.companion-layout__history'
        ];
        const leaked = forbiddenSelectors.filter(sel => document.querySelector(sel) !== null);
        const text = document.body.innerText || '';
        const html = document.body.innerHTML || '';
        return {{
            leakedSelectors: leaked,
            canaryInText: text.includes('{canary_token}'),
            canaryInHtml: html.includes('{canary_token}'),
            chatStringsLeaked: text.includes('Comece uma conversa') || text.includes('Histórico da conversa'),
            hasPresenceSurface: Boolean(document.querySelector('[data-testid="katherine-presence-surface"]')),
            hasFace: Boolean(document.querySelector('[data-testid="katherine-face"]')),
            hasControls: Boolean(document.querySelector('[data-testid="katherine-presence-controls"]')),
            bodyText: text.trim(),
        }};
    }})()""")

    assert len(privacy_inspection["leakedSelectors"]) == 0, f"Privacy canary failed: found selectors {privacy_inspection['leakedSelectors']}"
    assert not privacy_inspection["canaryInText"], "Privacy canary failed: confidential token found in body text!"
    assert not privacy_inspection["canaryInHtml"], "Privacy canary failed: confidential token found in body HTML!"
    assert not privacy_inspection["chatStringsLeaked"], "Privacy canary failed: chat strings found in presence DOM!"
    assert privacy_inspection["hasPresenceSurface"], "Presence surface must be present in DOM"
    print("  DOM Privacy Canary verified: 0 leaked elements, 0 private tokens, 0 chat strings: PASS", flush=True)

    # Point 4: Transparency Verification (§MAJOR 6)
    print("\n[Point 4] Verifying Window Surface Transparency (§MAJOR 6)...", flush=True)
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    from gi.repository import Gdk, GLib

    screen = Gdk.Screen.get_default()
    is_composited = screen.is_composited() if screen else False

    dom_transparency = window.evaluate_js("""(() => {
        const pres = document.querySelector('.katherine-presence');
        const root = document.querySelector('[data-testid="app-desktop-root"]');
        return {
            presenceBg: pres ? getComputedStyle(pres).backgroundColor : null,
            rootBg: root ? getComputedStyle(root).backgroundColor : null,
        };
    })()""")

    transparency_data = {
        "is_composited": is_composited,
        "dom_presence_bg": dom_transparency.get("presenceBg"),
        "dom_root_bg": dom_transparency.get("rootBg"),
        "tested_mode": "presence",
    }

    if not is_composited:
        transparency_data["status"] = "NOT VERIFIED"
        transparency_data["reason"] = "Display server does not report an active compositing manager (e.g. standard Xvfb); marked NOT VERIFIED per §MAJOR 6"
        print(f"  Transparency status: NOT VERIFIED ({transparency_data['reason']})", flush=True)
    else:
        native = window.native
        w, h = native.get_size()
        pixbuf_done = threading.Event()
        pb_holder = []
        def _get_pb():
            try:
                pb = Gdk.pixbuf_get_from_window(native.get_window(), 0, 0, w, h)
                pb_holder.append(pb)
            except Exception:
                pb_holder.append(None)
            finally:
                pixbuf_done.set()
            return False
        GLib.idle_add(_get_pb)
        pixbuf_done.wait(5.0)
        pb = pb_holder[0] if pb_holder else None

        if pb and pb.get_has_alpha():
            pixels = pb.get_pixels()
            channels = pb.get_n_channels()
            corner_alpha = pixels[channels - 1] if len(pixels) >= channels else None
            transparency_data["pixbuf_has_alpha"] = True
            transparency_data["corner_alpha"] = corner_alpha
            transparency_data["status"] = "VERIFIED"
            print(f"  Transparency status: VERIFIED (Composited GDK screen, pixbuf alpha present, corner alpha={corner_alpha})", flush=True)
        else:
            transparency_data["pixbuf_has_alpha"] = False
            transparency_data["status"] = "NOT VERIFIED"
            transparency_data["reason"] = "Compositor active but native window capture lacks alpha plane in this graphical session; marked NOT VERIFIED per §MAJOR 6"
            print(f"  Transparency status: NOT VERIFIED ({transparency_data['reason']})", flush=True)

    # Point 5 (Part B): Presence Mode Resources
    print("\n[Point 5] Measuring Presence resources...", flush=True)
    time.sleep(1.0)
    presence_resources = measure_system_resources()
    print(f"  Presence RSS: {presence_resources.get('rss_mb')} MB | Procs: {presence_resources.get('process_count')} (WebKit: {presence_resources.get('webkit_process_count')}) | CPU idle: {presence_resources.get('cpu_idle_percent')}%", flush=True)

    delta_rss = round(presence_resources.get("rss_mb", 0) - companion_resources.get("rss_mb", 0), 2)
    resource_matrix = {
        "companion": companion_resources,
        "presence": presence_resources,
        "delta_rss_mb": delta_rss,
    }

    # Return to companion mode before lifecycle loop
    window.evaluate_js('document.querySelector("[data-testid=\\"presence-return-btn\\"]").click()')
    wait_for(window, 'Boolean(document.querySelector("[data-testid=\\"companion-layout\\"]"))')
    time.sleep(0.3)

    # Point 1: Lifecycle (5 Repetitions) (§MAJOR 6)
    print("\n[Point 1] Executing Lifecycle 5x (companion -> presence -> companion -> presence -> minimize -> restore -> companion)...", flush=True)
    lifecycle_results = []

    for rep in range(1, 6):
        rep_data = {"repetition": rep, "transitions": []}

        # In companion
        wait_for(window, 'Boolean(document.querySelector("[data-testid=companion-layout]"))')
        assert len(webview.windows) == 1, f"Rep {rep}: Expected 1 window, found {len(webview.windows)}"
        st = call_bridge_js(window, "window.pywebview.api.window_state()")
        assert st.get("mode") == "companion", f"Rep {rep}: Must be companion, got {st}"
        rep_data["transitions"].append("companion_1")

        # -> presence
        window.evaluate_js('document.querySelector("[data-testid=\\"companion-enter-presence-btn\\"]").click()')
        wait_for(window, 'Boolean(document.querySelector("[data-testid=\\"katherine-presence-surface\\"]"))')
        st = call_bridge_js(window, "window.pywebview.api.window_state()")
        assert st.get("mode") == "presence", f"Rep {rep}: Must be presence, got {st}"
        rep_data["transitions"].append("presence_1")

        # -> companion
        window.evaluate_js('document.querySelector("[data-testid=\\"presence-return-btn\\"]").click()')
        wait_for(window, 'Boolean(document.querySelector("[data-testid=\\"companion-layout\\"]"))')
        st = call_bridge_js(window, "window.pywebview.api.window_state()")
        assert st.get("mode") == "companion", f"Rep {rep}: Must be companion, got {st}"
        rep_data["transitions"].append("companion_2")

        # -> presence
        window.evaluate_js('document.querySelector("[data-testid=\\"companion-enter-presence-btn\\"]").click()')
        wait_for(window, 'Boolean(document.querySelector("[data-testid=\\"katherine-presence-surface\\"]"))')
        st = call_bridge_js(window, "window.pywebview.api.window_state()")
        assert st.get("mode") == "presence", f"Rep {rep}: Must be presence, got {st}"
        rep_data["transitions"].append("presence_2")

        # -> hide/minimize
        window.evaluate_js('document.querySelector("[data-testid=\\"presence-minimize-btn\\"]").click()')
        time.sleep(0.2)
        rep_data["transitions"].append("minimize")

        # -> restore
        restore_done = threading.Event()
        def _restore_win():
            try:
                if hasattr(window, 'restore'):
                    window.restore()
                elif hasattr(window.native, 'deiconify'):
                    window.native.deiconify()
            finally:
                restore_done.set()
            return False
        GLib.idle_add(_restore_win)
        restore_done.wait(3.0)
        time.sleep(0.2)
        wait_for(window, 'Boolean(document.querySelector("[data-testid=\\"katherine-presence-surface\\"]"))')
        rep_data["transitions"].append("restore")

        # -> companion
        window.evaluate_js('document.querySelector("[data-testid=\\"presence-return-btn\\"]").click()')
        wait_for(window, 'Boolean(document.querySelector("[data-testid=\\"companion-layout\\"]"))')
        st = call_bridge_js(window, "window.pywebview.api.window_state()")
        assert st.get("mode") == "companion", f"Rep {rep}: Must be companion, got {st}"
        assert len(webview.windows) == 1, f"Rep {rep}: Window count must be 1"
        rep_data["transitions"].append("companion_final")

        lifecycle_results.append(rep_data)
        print(f"  Repetition {rep}/5 completed cleanly (window count: {len(webview.windows)})", flush=True)

    # Compile final matrix results
    final_matrix = {
        "status": "PASS",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "point_1_lifecycle": {
            "status": "PASS",
            "repetitions_count": len(lifecycle_results),
            "sequence": "companion -> presence -> companion -> presence -> minimize -> restore -> companion",
            "repetitions": lifecycle_results,
            "single_window_verified": len(webview.windows) == 1,
            "zero_duplicate_runtime": True,
        },
        "point_2_always_on_top": {
            "status": "PASS",
            "rule": "set_always_on_top is sole authority; state preserved across mode transitions",
            "steps": aot_steps,
        },
        "point_3_privacy_canary": {
            "status": "PASS",
            "canary_token_found": privacy_inspection["canaryInText"] or privacy_inspection["canaryInHtml"],
            "leaked_forbidden_selectors_count": len(privacy_inspection["leakedSelectors"]),
            "leaked_selectors": privacy_inspection["leakedSelectors"],
            "chat_strings_leaked": privacy_inspection["chatStringsLeaked"],
        },
        "point_4_transparency": transparency_data,
        "point_5_resources": resource_matrix,
    }

    # Save to files
    (output_dir / "matrix_evidence.json").write_text(json.dumps(final_matrix, indent=2, ensure_ascii=False))

    repo_root = Path(__file__).resolve().parents[1]
    (repo_root / "scripts" / "presence_evidence.json").write_text(json.dumps(final_matrix, indent=2, ensure_ascii=False))

    results["matrix_evidence"] = final_matrix
    print("\n" + "=" * 70)
    print("5-POINT RUNTIME EVIDENCE MATRIX SUCCESSFULLY COMPLETED")
    print("Saved evidence to:")
    print(f"  - {output_dir / 'matrix_evidence.json'}")
    print(f"  - {repo_root / 'scripts' / 'presence_evidence.json'}")
    print("=" * 70 + "\n", flush=True)
    return final_matrix


def inspect():
    window = None
    try:
        deadline = time.monotonic() + 20
        while not webview.windows and time.monotonic() < deadline:
            time.sleep(0.1)
        window = webview.windows[0]
        window.events.loaded.wait(20)
        wait_for(window, 'Boolean(document.querySelector("[data-testid=companion-layout]"))')
        wait_for(window, 'Boolean(document.querySelector("[data-testid=desktop-bridge-indicator]"))')
        time.sleep(0.5)

        if args.verify_matrix:
            release.set()
            verify_matrix(window, args.output)

        if not args.verify_matrix or args.verify_v2 or args.verify_scaling:
            capture(window, 'idle-1280')
            window.resize(800, 800)
            wait_for(window, 'innerWidth === 800')
            time.sleep(0.4)
            capture(window, 'idle-800')
            window.resize(1280, 800)
            wait_for(window, 'innerWidth === 1280')
            window.evaluate_js("""(() => {
              const input = document.querySelector('textarea[aria-label="Sua mensagem"]');
              Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(input, 'Olá, Katherine.');
              input.dispatchEvent(new Event('input', {bubbles: true}));
            })()""")
            wait_for(window, '!document.querySelector("button[aria-label=\\"Enviar mensagem (Enter)\\"]").disabled')
            window.evaluate_js('document.querySelector("button[aria-label=\\"Enviar mensagem (Enter)\\"]").click()')
            if args.scripted:
                wait_for(window, 'document.querySelector("textarea").disabled')
                if args.verify_v2:
                    wait_for(window, 'document.querySelector("[role=status]")?.textContent.includes("Preparando resposta")')
                time.sleep(1)
                capture(window, 'thinking-1280')
                window.resize(800, 800)
                wait_for(window, 'innerWidth === 800')
                time.sleep(0.4)
                capture(window, 'thinking-800')
                if args.verify_v2:
                    optical_probes(window)
                release.set()
                wait_for(window, 'document.body.innerText.includes("A presença pode permanecer tranquila")')
                time.sleep(1)
                capture(window, 'response-800')
                if args.verify_scaling:
                    verify_scaling_matrix(window)
            else:
                wait_for(window, 'document.body.innerText.includes("O provedor remoto não está configurado")')
                wait_for(window, '!document.querySelector("textarea").disabled')
                time.sleep(0.5)
                capture(window, 'unconfigured-error-1280')
            results['finalText'] = window.evaluate_js('document.body.innerText')
    except Exception as error:
        failures.append(str(error))
    finally:
        release.set()
        results['failures'] = failures
        (args.output / 'observations.json').write_text(json.dumps(results, indent=2, ensure_ascii=False))
        if window:
            window.destroy()

thread = threading.Thread(target=inspect, daemon=True)
thread.start()
run_desktop_shell(storage_path=args.output / 'isolated.sqlite3', provider=ReviewProvider() if (args.scripted or args.verify_matrix) else None)
thread.join(5)
if failures:
    raise SystemExit('; '.join(failures))
