"""Capture the real desktop entry, isolated from personal data and paid providers.

Run with uv and WebKitGTK under Xvfb (see docs/design/presence-v2/README.md).
Optional scale probes resize the real mounted face for optical checks only.
The scripted provider is fixture evidence, not live provider acceptance.
"""
import argparse
import asyncio
import json
import threading
import time
from pathlib import Path

import webview
from backend.desktop.app import run_desktop_shell

parser = argparse.ArgumentParser()
parser.add_argument('--output', required=True, type=Path)
parser.add_argument('--scripted', action='store_true')
parser.add_argument('--verify-v2', action='store_true')
parser.add_argument('--verify-scaling', action='store_true')
parser.add_argument('--reduced-motion', action='store_true')
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
if (args.output / 'isolated.sqlite3').exists():
    parser.error('Use a fresh output directory so captures start with empty isolated storage.')
if args.reduced_motion:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    Gtk.Settings.get_default().set_property('gtk-enable-animations', False)
release = threading.Event()
failures = []
results = {'provider': 'scripted offline fixture' if args.scripted else 'unconfigured real runtime', 'captures': []}

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
        time.sleep(1)
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
run_desktop_shell(storage_path=args.output / 'isolated.sqlite3', provider=ReviewProvider() if args.scripted else None)
thread.join(5)
if failures:
    raise SystemExit('; '.join(failures))
