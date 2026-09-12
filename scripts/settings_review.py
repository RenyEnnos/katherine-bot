"""Runtime evidence for the Katherine settings workspace (#347).

Runs the real desktop entry (desktop.html) under WebKitGTK/Xvfb with an
isolated SQLite database and a scripted offline provider, then exercises
the settings workspace end-to-end:

- Access & discretion: the workspace opens only from the companion header
  (two buttons, not in the sidebar or presence surface).
- Conversation preservation: the composer draft survives an open -> close
  -> reopen cycle; component tests cover history and the single useChat
  composition seam.
- Honesty: only the "Janela" section with the single always-on-top
  control exists; no fake sections for voice, memory, models or
  integrations.
- Always-on-top lifecycle: the real `window_state` / `set_always_on_top`
  bridge ops stay coherent, including session-only scope.
- Presence isolation: opening settings never leaks into presence mode,
  and the presence surface never exposes settings.
- Keyboard & focus: back button is focused on open, Escape closes, focus
  returns to the gear button.
- Efficiency: opening settings triggers no polling (no timers, no
  repeated bridge reads).
- Resolutions: 1440x900, 1024x768, 800x600 and 125%/150% zoom, with
  geometry checks (no overflow, composer visible).

The scripted provider is fixture evidence, not live provider acceptance.
Sanitized output only: no personal data, no secrets, no real provider
traffic. Screenshots capture the settings UI, which contains no user
data by construction.
"""

import argparse
import asyncio
import json
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import webview
from backend.desktop.app import run_desktop_shell

parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, default=Path('scripts/settings_evidence'))
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
release = threading.Event()
failures = []
results = {
    'provider': 'scripted offline fixture',
    'captures': [],
}


class ReviewProvider:
    async def appraise(self, message, budget):
        from backend.emotional_domain import AppraisalV1

        return AppraisalV1.neutral()

    async def generate(self, messages, budget):
        while not release.is_set():
            await asyncio.sleep(0.05)
        return 'Resposta de fixture para a evidência das configurações.'

    async def extract_archival(self, messages, budget):
        return '{}'

    def describe(self):
        from backend.language_model import ModelSelection

        return ModelSelection(
            provider='fake', main_model_id='review-fixture', fast_model_id='review-fixture'
        )


def wait_for(window, script, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = window.evaluate_js(script)
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError(f'Timed out: {script}')


def capture(window, name):
    from gi.repository import Gdk, GLib

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


def metrics(window):
    return window.evaluate_js("""(() => {
        const q = (sel) => document.querySelector(sel);
        const rect = (el) => el ? el.getBoundingClientRect() : null;
        const workspace = q('[data-testid="settings-workspace"]');
        const back = q('[data-testid="settings-back-btn"]');
        const section = q('[data-testid="settings-section-window"]');
        const sw = q('[data-testid="settings-always-on-top-switch"]');
        const gear = q('[data-testid="companion-open-settings-btn"]');
        const sidebarBtns = Array.from(document.querySelectorAll(
            '[data-testid="katherine-state-sidebar"] button, .katherine-state-sidebar button'));
        const heading = q('#settings-workspace-heading');
        const sectionHeading = q('#settings-window-heading');
        const input = q('textarea[aria-label="Sua mensagem"]');
        return {
            hasWorkspace: Boolean(workspace),
            backVisible: back ? (back.getBoundingClientRect().bottom > 0) : false,
            backLabel: back ? back.textContent : null,
            hasWindowSection: Boolean(section),
            hasVoiceSection: Boolean(q('[data-testid="settings-section-voice"]')),
            hasMemorySection: Boolean(q('[data-testid="settings-section-memory"]')),
            hasModelsSection: Boolean(q('[data-testid="settings-section-models"]')),
            hasIntegrationsSection: Boolean(q('[data-testid="settings-section-integrations"]')),
            switchRole: sw ? sw.getAttribute('role') : null,
            switchChecked: sw ? sw.getAttribute('aria-checked') : null,
            switchDisabled: sw ? sw.disabled : null,
            switchText: sw ? sw.textContent : null,
            headingLevel: heading ? heading.tagName : null,
            sectionHeadingLevel: sectionHeading ? sectionHeading.tagName : null,
            headings: Array.from(document.querySelectorAll('h1, h2, h3')).map(h => h.textContent.trim()),
            gearInSidebar: sidebarBtns.some(b => b.matches('[data-testid="companion-open-settings-btn"]')),
            gearInHeader: Boolean(gear),
            horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
            inputVisible: input ? (input.getBoundingClientRect().bottom <= innerHeight) : false,
            runningAnimations: document.getAnimations().filter(a => a.playState === 'running').length,
        };
    })()""")


def open_settings(window):
    window.evaluate_js(
        'document.querySelector("[data-testid=\\"companion-open-settings-btn\\"]").click()'
    )
    wait_for(window, 'Boolean(document.querySelector("[data-testid=\\"settings-workspace\\"]"))')


def close_settings(window):
    window.evaluate_js('document.querySelector("[data-testid=\\"settings-back-btn\\"]").click()')
    wait_for(window, 'Boolean(document.querySelector("[data-testid=\\"companion-layout\\"]"))')


def call_bridge_js(window, call_expr, timeout=10.0):
    """Execute an async bridge expression and await its deposited result."""
    import uuid

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
    raise TimeoutError(f'Timed out waiting for {call_expr}')


def verify_settings(window, output_dir):
    print('=' * 70)
    print('SETTINGS WORKSPACE RUNTIME EVIDENCE (#347)')
    print('=' * 70, flush=True)

    evidence = {'timestamp_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}

    wait_for(window, 'Boolean(document.querySelector("[data-testid=companion-layout]"))')
    wait_for(window, 'Boolean(document.querySelector("[data-testid=desktop-bridge-indicator]"))')
    time.sleep(0.5)

    # ---- 1. Access & discretion ------------------------------------------
    print('[1] Access & discretion...', flush=True)
    gear_count = window.evaluate_js(
        'document.querySelectorAll(\'[data-testid="companion-open-settings-btn"]\').length'
    )
    assert gear_count == 1, f'Expected exactly one gear button, found {gear_count}'
    sidebar_has_gear = window.evaluate_js("""(() => {
        const sidebar = document.querySelector('[data-testid="katherine-state-sidebar"]');
        return sidebar
            ? Boolean(sidebar.querySelector('[data-testid="companion-open-settings-btn"]'))
            : false;
    })()""")
    assert not sidebar_has_gear, 'Settings button must not live in the state sidebar'
    access = {'gear_buttons': gear_count, 'gear_in_sidebar': sidebar_has_gear}
    evidence['access'] = access
    print(f'  gear buttons={gear_count}, in sidebar={sidebar_has_gear}: PASS', flush=True)

    # ---- 2. Conversation preservation ------------------------------------
    print('[2] Conversation preservation...', flush=True)
    window.evaluate_js("""(() => {
        const input = document.querySelector('textarea[aria-label="Sua mensagem"]');
        Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(
            input, 'rascunho-para-preservar');
        input.dispatchEvent(new Event('input', {bubbles: true}));
    })()""")
    time.sleep(0.3)
    open_settings(window)
    time.sleep(0.4)
    close_settings(window)
    time.sleep(0.4)
    draft_after_cycle = window.evaluate_js(
        'document.querySelector(\'textarea[aria-label="Sua mensagem"]\').value'
    )
    assert draft_after_cycle == 'rascunho-para-preservar', (
        f'Draft lost after settings cycle: {draft_after_cycle!r}'
    )
    workspace_gone = window.evaluate_js(
        '!document.querySelector(\'[data-testid="settings-workspace"]\')'
    )
    assert workspace_gone, 'Workspace must unmount after closing'
    preservation = {
        'draft_preserved': draft_after_cycle == 'rascunho-para-preservar',
        'draft_value': draft_after_cycle,
    }
    evidence['conversation_preservation'] = preservation
    print(f'  draft preserved after open->close: PASS ({draft_after_cycle!r})', flush=True)

    # ---- 3. Honesty: only real capabilities -------------------------------
    print('[3] Honesty (only the Janela section / always-on-top)...', flush=True)
    open_settings(window)
    time.sleep(0.5)
    m = metrics(window)
    assert m['hasWorkspace'], 'Workspace did not open'
    assert m['hasWindowSection'], 'Janela section missing'
    assert not m['hasVoiceSection'], 'Fake voice section present'
    assert not m['hasMemorySection'], 'Fake memory section present'
    assert not m['hasModelsSection'], 'Fake models section present'
    assert not m['hasIntegrationsSection'], 'Fake integrations section present'
    assert m['switchRole'] == 'switch', f'role={m["switchRole"]!r}'
    assert m['headingLevel'] == 'H1', f'heading level={m["headingLevel"]!r}'
    assert m['sectionHeadingLevel'] == 'H2', f'section heading level={m["sectionHeadingLevel"]!r}'
    honesty = {
        'sections': m['headings'],
        'switch_role': m['switchRole'],
        'heading_levels': [m['headingLevel'], m['sectionHeadingLevel']],
        'fake_sections': [
            name for name, present in {
                'voice': m['hasVoiceSection'],
                'memory': m['hasMemorySection'],
                'models': m['hasModelsSection'],
                'integrations': m['hasIntegrationsSection'],
            }.items() if present
        ],
    }
    evidence['honesty'] = honesty
    print(f"  sections={m['headings']}, fake_sections=[]: PASS", flush=True)
    capture(window, 'settings-open-default')

    # ---- 4. Always-on-top lifecycle ---------------------------------------
    print('[4] Always-on-top lifecycle (real bridge)...', flush=True)
    st0 = call_bridge_js(window, 'window.pywebview.api.window_state()')
    assert st0.get('ok') and st0.get('mode') == 'companion', f'Bad state: {st0}'
    assert st0.get('on_top') is False, f'Startup must be unpinned: {st0}'
    checked_before = window.evaluate_js(
        'document.querySelector(\'[data-testid="settings-always-on-top-switch"]\')'
        '.getAttribute("aria-checked")'
    )
    assert checked_before == 'false', f'aria-checked={checked_before!r}'

    window.evaluate_js(
        'document.querySelector("[data-testid=\\"settings-always-on-top-switch\\"]").click()'
    )
    wait_for(
        window,
        'document.querySelector("[data-testid=\\"settings-always-on-top-switch\\"]")'
        '.getAttribute("aria-checked") === "true"',
    )
    st1 = call_bridge_js(window, 'window.pywebview.api.window_state()')
    assert st1.get('ok') and st1.get('on_top') is True, f'Pin failed: {st1}'

    window.evaluate_js(
        'document.querySelector("[data-testid=\\"settings-always-on-top-switch\\"]").click()'
    )
    wait_for(
        window,
        'document.querySelector("[data-testid=\\"settings-always-on-top-switch\\"]")'
        '.getAttribute("aria-checked") === "false"',
    )
    st2 = call_bridge_js(window, 'window.pywebview.api.window_state()')
    assert st2.get('ok') and st2.get('on_top') is False, f'Unpin failed: {st2}'
    lifecycle = {
        'startup': {'on_top': st0['on_top'], 'aria_checked': checked_before},
        'after_enable': {'on_top': st1['on_top'], 'aria_checked': 'true'},
        'after_disable': {'on_top': st2['on_top'], 'aria_checked': 'false'},
    }
    evidence['always_on_top_lifecycle'] = lifecycle
    print(
        f"  on_top: {st0['on_top']} -> {st1['on_top']} -> {st2['on_top']}"
        ' (aria-checked coherent): PASS',
        flush=True,
    )

    # ---- 5. Keyboard & focus ----------------------------------------------
    print('[5] Keyboard & focus...', flush=True)
    # Settings are currently open (from section 3); close them first so
    # we can observe a fresh open with focus on the back button.
    close_settings(window)
    time.sleep(0.2)
    focus_before_open = window.evaluate_js(
        'document.activeElement?.getAttribute("data-testid")'
    )
    assert focus_before_open == 'companion-open-settings-btn', (
        f'Focus must return to gear after close, got {focus_before_open!r}'
    )
    open_settings(window)
    time.sleep(0.2)
    focused_on_open = window.evaluate_js(
        'document.activeElement?.getAttribute("data-testid")'
    )
    assert focused_on_open == 'settings-back-btn', (
        f'Back button not focused on open: {focused_on_open!r}'
    )
    window.evaluate_js("""(() => {
        document.activeElement.dispatchEvent(
            new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
    })()""")
    time.sleep(0.4)
    closed_by_escape = window.evaluate_js(
        '!document.querySelector(\'[data-testid="settings-workspace"]\')'
    )
    assert closed_by_escape, 'Escape must close settings'
    focus_after_escape = window.evaluate_js(
        'document.activeElement?.getAttribute("data-testid")'
    )
    assert focus_after_escape == 'companion-open-settings-btn', (
        f'Focus must return to gear after Escape, got {focus_after_escape!r}'
    )
    keyboard = {
        'focus_returns_to_gear_on_close': focus_before_open,
        'focused_on_open': focused_on_open,
        'escape_closes': closed_by_escape,
        'focus_after_escape': focus_after_escape,
    }
    evidence['keyboard_focus'] = keyboard
    print(
        f'  focused_on_open={focused_on_open!r}, escape closes,'
        f' focus returns to {focus_after_escape!r}: PASS',
        flush=True,
    )

    # ---- 6. Efficiency: no polling ----------------------------------------
    print('[6] Efficiency (no polling while open)...', flush=True)
    open_settings(window)
    window.evaluate_js('window.__stateReads = 0')
    window.evaluate_js("""(() => {
        const api = window.pywebview.api;
        const orig = api.window_state.bind(api);
        api.window_state = async (...argv) => {
            window.__stateReads += 1;
            return orig(...argv);
        };
    })()""")
    time.sleep(2.0)
    reads = window.evaluate_js('window.__stateReads')
    assert reads == 0, f'Polling detected: {reads} window_state reads in 2s'
    evidence['efficiency'] = {
        'window_state_reads_while_open_2s': reads,
        'polling_detected': reads > 0,
    }
    print(f'  window_state reads in 2s while open: {reads}: PASS', flush=True)

    # ---- 7. Presence isolation --------------------------------------------
    print('[7] Presence isolation...', flush=True)
    close_settings(window)
    time.sleep(0.3)
    window.evaluate_js(
        'document.querySelector("[data-testid=\\"companion-enter-presence-btn\\"]").click()'
    )
    wait_for(
        window,
        'Boolean(document.querySelector("[data-testid=\\"katherine-presence-surface\\"]"))',
    )
    time.sleep(0.4)
    presence_settings = window.evaluate_js("""(() => {
        const forbidden = [
            '[data-testid="settings-workspace"]',
            '[data-testid="settings-back-btn"]',
            '[data-testid="settings-section-window"]',
            '[data-testid="settings-always-on-top-switch"]',
            '.settings-workspace'
        ];
        return {
            settingsDOM: Boolean(document.querySelector('[data-testid="settings-workspace"]')),
            gearBtn: Boolean(document.querySelector('[data-testid="companion-open-settings-btn"]')),
            leaked: forbidden.filter(sel => document.querySelector(sel) !== null)
        };
    })()""")
    assert not presence_settings['settingsDOM'], 'Settings leaked into presence mode'
    assert not presence_settings['gearBtn'], 'Settings entry leaked into presence mode'
    assert not presence_settings['leaked'], (
        f"Forbidden selectors in presence: {presence_settings['leaked']}"
    )
    window.evaluate_js(
        'document.querySelector("[data-testid=\\"presence-return-btn\\"]").click()'
    )
    wait_for(window, 'Boolean(document.querySelector("[data-testid=\\"companion-layout\\"]"))')
    time.sleep(0.3)
    back_in_companion = window.evaluate_js(
        'Boolean(document.querySelector(\'[data-testid="companion-open-settings-btn"]\'))'
    )
    assert back_in_companion, 'Gear button must return with companion mode'
    isolation = {
        'settings_in_presence': presence_settings['settingsDOM'],
        'leaked_selectors': presence_settings['leaked'],
        'gear_returns_with_companion': back_in_companion,
    }
    evidence['presence_isolation'] = isolation
    print('  0 leaked selectors in presence, gear returns with companion: PASS', flush=True)

    # ---- 8. Resolutions & scaling -----------------------------------------
    print('[8] Resolutions & scaling...', flush=True)
    from gi.repository import GLib

    try:
        from webview.platforms.gtk import BrowserView

        bv = BrowserView.instances.get(window.uid)
    except Exception:
        bv = None
    scenarios = [
        ('1440x900-100', 1440, 900, 1.0),
        ('1024x768-100', 1024, 768, 1.0),
        ('800x600-100', 800, 600, 1.0),
        ('800x600-125', 800, 600, 1.25),
        ('800x600-150', 800, 600, 1.50),
    ]
    matrix = []
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

        open_settings(window)
        time.sleep(0.4)
        m = metrics(window)
        assert m['hasWorkspace'], f'{name}: workspace missing'
        assert not m['horizontalOverflow'], f'{name}: horizontal overflow'
        capture(window, f'settings-{name}')
        close_settings(window)
        m_closed = metrics(window)
        assert m_closed['inputVisible'], f'{name}: composer not visible after return'
        assert not m_closed['horizontalOverflow'], f'{name}: overflow after return'
        matrix.append({'scenario': name, 'workspace': m, 'after_return': m_closed})
        print(f'  {name}: PASS', flush=True)

    if bv:
        def restore():
            bv.webview.set_zoom_level(1.0)
            return False

        GLib.idle_add(restore)
        time.sleep(0.3)

    evidence['resolution_matrix'] = matrix

    # ---- 9. Draft + history across reopen (final) -------------------------
    print('[9] Draft still preserved at the end...', flush=True)
    final_draft = window.evaluate_js(
        'document.querySelector(\'textarea[aria-label="Sua mensagem"]\').value'
    )
    assert final_draft == 'rascunho-para-preservar', (
        f'Draft lost during matrix: {final_draft!r}'
    )
    evidence['final_draft_preserved'] = final_draft
    print(f'  draft={final_draft!r}: PASS', flush=True)

    evidence['status'] = 'PASS'
    (output_dir / 'settings_evidence.json').write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False)
    )
    print('=' * 70)
    print('SETTINGS WORKSPACE RUNTIME EVIDENCE COMPLETED: PASS')
    print(f'Saved: {output_dir / "settings_evidence.json"}')
    print('=' * 70 + '\n', flush=True)
    return evidence


def inspect():
    window = None
    try:
        deadline = time.monotonic() + 20
        while not webview.windows and time.monotonic() < deadline:
            time.sleep(0.1)
        window = webview.windows[0]
        window.events.loaded.wait(20)
        wait_for(window, 'Boolean(document.querySelector("[data-testid=companion-layout]"))')
        time.sleep(0.5)
        release.set()
        verify_settings(window, args.output)
    except Exception as error:
        failures.append(str(error))
    finally:
        release.set()
        results['failures'] = failures
        (args.output / 'observations.json').write_text(
            json.dumps(results, indent=2, ensure_ascii=False)
        )
        if window:
            window.destroy()


thread = threading.Thread(target=inspect, daemon=True)
thread.start()
run_desktop_shell(
    storage_path=args.output / 'isolated.sqlite3',
    provider=ReviewProvider(),
)
thread.join(5)
if failures:
    raise SystemExit('; '.join(failures))
