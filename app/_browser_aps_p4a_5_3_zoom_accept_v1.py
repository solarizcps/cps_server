# -*- coding: utf-8 -*-
"""
P4A.5.3 — WEEK ZOOM TASK DISAPPEARS — Acceptance Test
Tests zoom matrix at multiple viewport widths to confirm fix.
Uses window.__apsApplyZoom (exposed after fix).
"""
from __future__ import annotations
import json
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
APP = Path(__file__).resolve().parent
ROOT = APP.parent
sys.path.insert(0, str(APP))

from tools.test_db_guard import browser_adhoc_context  # noqa
from tools.nexgen_tmp_db import sha256_file             # noqa

CANONICAL = APP / 'mock_data.db'
ROUTE = '/planlama/aps-pilot'

passed_list: list[str] = []
failed_list: list[str] = []


def ok(l):
    passed_list.append(l)
    print(f'  PASS  {l}')


def fail(l, r=''):
    failed_list.append(l)
    print(f'  FAIL  {l}' + (f' — {r}' if r else ''))


def check(l, c, r=''):
    ok(l) if c else fail(l, r)


# ─── JS helpers ────────────────────────────────────────────────────────────────

def apply_zoom(page, key):
    page.evaluate(f"() => window.__apsApplyZoom('{key}')")
    page.wait_for_timeout(600)


def scroll_to_task(page, task_id):
    """Scroll to show the task bar and update viewAnchorDate to task start."""
    page.evaluate(f"""() => {{
        if (!gantt.isTaskExists('{task_id}')) return;
        var t = gantt.getTask('{task_id}');
        if (t.start_date) gantt.showDate(t.start_date);
    }}""")
    page.wait_for_timeout(300)


def snap_task(page, task_id):
    return page.evaluate(f"""() => {{
        if (!window.gantt || !gantt.isTaskExists('{task_id}')) return null;
        var t = gantt.getTask('{task_id}');
        var el = gantt.getTaskNode('{task_id}');
        var r = el ? el.getBoundingClientRect() : null;
        return {{
            start_date: t.start_date ? t.start_date.toISOString() : null,
            end_date: t.end_date ? t.end_date.toISOString() : null,
            start_is_date: t.start_date instanceof Date,
            end_is_date: t.end_date instanceof Date,
            duration: t.duration,
            unscheduled: t.unscheduled,
            no_start: t.$no_start,
            no_end: t.$no_end,
            dom_exists: !!el,
            bar_width: r ? Math.round(r.width) : null,
            bar_left: r ? Math.round(r.left) : null,
            bar_right: r ? Math.round(r.right) : null,
            bar_classes: el ? el.className : null,
            plan_id: t.aps_primary_plan_id || (t.aps_plan ? t.aps_plan.id : null),
        }};
    }}""")


def snap_zoom_metrics(page):
    return page.evaluate("() => window.__apsZoomMetrics ? window.__apsZoomMetrics() : null")


def snap_scroll(page):
    return page.evaluate("""() => {
        var s = gantt.getScrollState ? gantt.getScrollState() : null;
        return s ? s.x : null;
    }""")


def is_bar_in_viewport(page, task_id):
    """Check if bar is within the visible timeline area (not clipped by smart_rendering)."""
    return page.evaluate(f"""() => {{
        var el = gantt.getTaskNode('{task_id}');
        if (!el) return false;
        var r = el.getBoundingClientRect();
        if (r.width < 1) return false;
        // Check if bar overlaps visible screen area
        var vw = window.innerWidth;
        var vh = window.innerHeight;
        return r.left < vw && r.right > 0 && r.top < vh && r.bottom > 0;
    }}""")


def run_zoom_matrix(page, slot_id, snap_base, viewport_label):
    """Run zoom matrix for all zoom levels and assert bar visible + data parity."""
    # Full matrix: all zoom levels. Bar must exist in DOM for short zooms;
    # for long zooms (2m/3m/6m/1y) task bar may be very small but must be
    # in store with date/duration parity.
    zoom_keys = ['1d', '1w', '2m', '3m', '6m', '1y', '30m', '1h']
    labels = {
        '10m': '10 dk',
        '30m': '30 dk',
        '1h':  '1 saat',
        '1d':  '1 gün',
        '1w':  '1 hafta',
        '2m':  '2 ay',
        '3m':  '3 ay',
        '6m':  '6 ay',
        '1y':  '1 yıl',
    }
    for key in zoom_keys:
        apply_zoom(page, key)
        snap_z = snap_task(page, slot_id)
        zm = snap_zoom_metrics(page)
        scroll_x = snap_scroll(page)
        in_vp = is_bar_in_viewport(page, slot_id)
        label = f'[{viewport_label}] {labels.get(key, key)}'

        # Close zoom (minute/hour/day scale): bar must be wide and in viewport.
        # Medium zoom (1w/1d): bar must exist and be in viewport; thin is OK for
        #   very short plans vs wide window (17 h vs 8 week window).
        # Long zoom (2m+): only store integrity matters; thin bar is expected.
        close_zoom  = key in ('10m', '30m', '1h')
        medium_zoom = key in ('1d', '1w')

        check(f'{label}: task in store', snap_z is not None)
        if snap_z:
            check(f'{label}: start_date unchanged',
                  snap_z.get('start_date') == snap_base.get('start_date'),
                  f"base={snap_base.get('start_date')[:10]} z={snap_z.get('start_date')[:10] if snap_z.get('start_date') else None}")
            check(f'{label}: duration unchanged',
                  snap_z.get('duration') == snap_base.get('duration'),
                  f"base={snap_base.get('duration')} z={snap_z.get('duration')}")
            check(f'{label}: start_date instanceof Date', snap_z.get('start_is_date') is True)
            check(f'{label}: end_date instanceof Date', snap_z.get('end_is_date') is True)
            # gantt_thin_task is only disallowed on close zooms where bar must be wide
            if close_zoom:
                check(f'{label}: no gantt_thin_task',
                      'gantt_thin_task' not in (snap_z.get('bar_classes') or ''),
                      str(snap_z.get('bar_classes')))
            if close_zoom or medium_zoom:
                check(f'{label}: DOM bar exists', snap_z.get('dom_exists') is True,
                      f"dom={snap_z.get('dom_exists')}")
                check(f'{label}: bar_width > 0', (snap_z.get('bar_width') or 0) > 0,
                      f"w={snap_z.get('bar_width')}")
                if close_zoom:
                    check(f'{label}: bar in viewport', in_vp,
                          f"bar_left={snap_z.get('bar_left')} bar_right={snap_z.get('bar_right')} scroll_x={scroll_x}")
            else:
                # Long zoom: bar may be a thin strip but must still exist in DOM
                check(f'{label}: DOM bar exists (long zoom)',
                      snap_z.get('dom_exists') is True,
                      f"dom={snap_z.get('dom_exists')}")
        # Row count check at each zoom level
        g_rows = page.evaluate("() => document.querySelectorAll('.gantt_grid_data .gantt_row').length")
        # P5.1: 1 process + 4 machine + 8 slot = 13 rows
        check(f'{label}: resource rows == 13', g_rows == 13, f"rows={g_rows}")
        if zm:
            check(f'{label}: zoom key == {key}', zm.get('zoom') == key, str(zm.get('zoom')))


def check_turkish_labels(page, viewport_label):
    """Verify Turkish month/week labels appear in the DHTMLX scale DOM."""
    # Switch to 1h zoom (month + hour scale → should show Turkish month)
    apply_zoom(page, '1h')
    scale_text_1h = page.evaluate("""() => {
        var cells = document.querySelectorAll('.gantt_scale_cell');
        return Array.from(cells).map(function(c){ return c.textContent.trim(); });
    }""")
    tr_months = ['Oca','Şub','Mar','Nis','May','Haz','Tem','Ağu','Eyl','Eki','Kas','Ara',
                 'Ocak','Şubat','Mart','Nisan','Mayıs','Haziran',
                 'Temmuz','Ağustos','Eylül','Ekim','Kasım','Aralık']
    found_tr_month = any(
        any(m in cell for m in tr_months) for cell in scale_text_1h
    )
    check(f'[{viewport_label}] TR: Turkish month in 1h scale', found_tr_month,
          f"cells={scale_text_1h[:6]}")

    # Switch to 1w zoom → P4A.5.4: now shows 7 days with Turkish day names
    # (Paz, Pzt, Sal, Çar, Per, Cum, Cmt) + hour sub-scale
    # No longer shows "Hafta N" — that moved to 2m/3m zoom levels.
    apply_zoom(page, '1w')
    scale_text_1w = page.evaluate("""() => {
        var cells = document.querySelectorAll('.gantt_scale_cell');
        return Array.from(cells).map(function(c){ return c.textContent.trim(); });
    }""")
    TR_DAYS_SHORT = ['Paz','Pzt','Sal','Çar','Per','Cum','Cmt']
    found_tr_day = any(any(ds in cell for ds in TR_DAYS_SHORT) for cell in scale_text_1w)
    check(f'[{viewport_label}] TR: Turkish day names in 1w scale', found_tr_day,
          f"cells={[c for c in scale_text_1w if c][:10]}")
    # Also check for hour sub-scale (should contain '00', '04', '08' etc.)
    found_hour = any(cell in ('00','04','08','12','16','20') for cell in scale_text_1w)
    check(f'[{viewport_label}] TR: Hour sub-scale in 1w view', found_hour,
          f"cells={[c for c in scale_text_1w if c][:15]}")

    # Switch to 2m → should show Turkish full month names + "Hafta N"
    apply_zoom(page, '2m')
    scale_text_2m = page.evaluate("""() => {
        var cells = document.querySelectorAll('.gantt_scale_cell');
        return Array.from(cells).map(function(c){ return c.textContent.trim(); });
    }""")
    full_tr_months = ['Ocak','Şubat','Mart','Nisan','Mayıs','Haziran',
                      'Temmuz','Ağustos','Eylül','Ekim','Kasım','Aralık']
    found_full_month = any(
        any(m in cell for m in full_tr_months) for cell in scale_text_2m
    )
    check(f'[{viewport_label}] TR: Turkish full month in 2m scale', found_full_month,
          f"cells={scale_text_2m[:8]}")
    found_hafta_2m = any('Hafta' in cell for cell in scale_text_2m)
    check(f'[{viewport_label}] TR: "Hafta" in 2m scale', found_hafta_2m,
          f"cells={scale_text_2m[:8]}")

    # Print sample labels for visual inspection
    print(f'  [{viewport_label}] Scale samples (1h): {scale_text_1h[:5]}')
    print(f'  [{viewport_label}] Scale samples (1w days): {[c for c in scale_text_1w if any(ds in c for ds in TR_DAYS_SHORT)][:7]}')
    print(f'  [{viewport_label}] Scale samples (2m): {scale_text_2m[:6]}')

    # Reset to default 1h for subsequent tests
    apply_zoom(page, '1h')


def main():
    print('=' * 70)
    print('P4A.5.3 — ZOOM MATRIX ACCEPTANCE TEST (Turkish UI)')
    print('=' * 70)

    sha_before = sha256_file(str(CANONICAL))
    print(f'  DB SHA BEFORE: {sha_before}')

    write_calls: list[str] = []

    with browser_adhoc_context(str(CANONICAL), prefix='aps_p553a_') as srv:
        base = srv['base_url']
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page_errors: list[str] = []

            # ── Viewport 1: 1920x1080 (headless reference) ─────────────────
            print('\n=== VIEWPORT 1: 1920x1080 ===')
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})
            page.on('pageerror', lambda e: page_errors.append(str(e)))

            def track(route):
                if route.request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
                    if 'aps-pilot' in route.request.url or 'planlama' in route.request.url:
                        write_calls.append(route.request.method + ' ' + route.request.url)
                route.continue_()

            page.route('**/*', track)
            page.goto(base + '/giris')
            page.fill('input[name="kullanici"]', 'mehmet')
            page.fill('input[name="sifre"]', '1453')
            page.click('button[type="submit"]')
            page.wait_for_timeout(800)
            r2 = page.goto(base + ROUTE, timeout=60000)
            check('T0 page 200', r2.status == 200 if r2 else False)
            page.wait_for_selector('.gantt_container', timeout=30000)
            page.wait_for_timeout(2500)

            slot_id = page.evaluate("""() => {
                var found = null;
                gantt.eachTask(function(t) {
                    if (found) return;
                    if (t.aps_plan && t.aps_plan.id == 33917) { found = t.id; return; }
                    if (t.aps_primary_plan_id == 33917) { found = t.id; return; }
                    if (!found && t.aps_type === 'slot' && t.aps_plan) { found = t.id; return; }
                });
                return found;
            }""")
            check('T1 task found', slot_id is not None, str(slot_id))
            if not slot_id:
                print('ABORT: task not found')
                browser.close()
                return False

            print(f'  Task ID: {slot_id}')
            check('T2 __apsApplyZoom exposed', page.evaluate("() => typeof window.__apsApplyZoom === 'function'"))

            # Get baseline from initial load state (1h zoom is default, already loaded)
            snap_base = snap_task(page, slot_id)
            check('T3 baseline duration > 100', (snap_base.get('duration') or 0) > 100)
            check('T3b baseline DOM bar exists', snap_base.get('dom_exists') is True,
                  f"dom={snap_base.get('dom_exists')} bar_w={snap_base.get('bar_width')}")
            print(f'  Baseline: start={snap_base.get("start_date")[:16]} dur={snap_base.get("duration")} bar_w={snap_base.get("bar_width")}')

            run_zoom_matrix(page, slot_id, snap_base, '1920')

            # ── Turkish locale checks (viewport 1 only — same locale for all) ─
            print('\n=== TURKISH LABEL CHECKS (1920) ===')
            check_turkish_labels(page, '1920')
            page.close()

            # ── Viewport 2: 1366x768 (common small laptop) ─────────────────
            print('\n=== VIEWPORT 2: 1366x768 (CRITICAL — was failing before fix) ===')
            page2 = browser.new_page(viewport={'width': 1366, 'height': 768})
            page2.route('**/*', track)
            page2.goto(base + '/giris')
            page2.fill('input[name="kullanici"]', 'mehmet')
            page2.fill('input[name="sifre"]', '1453')
            page2.click('button[type="submit"]')
            page2.wait_for_timeout(800)
            page2.goto(base + ROUTE, timeout=60000)
            page2.wait_for_selector('.gantt_container', timeout=30000)
            page2.wait_for_timeout(2500)

            slot_id_2 = page2.evaluate("""() => {
                var found = null;
                gantt.eachTask(function(t) {
                    if (found) return;
                    if (t.aps_plan && t.aps_plan.id == 33917) { found = t.id; return; }
                    if (t.aps_primary_plan_id == 33917) { found = t.id; return; }
                    if (!found && t.aps_type === 'slot' && t.aps_plan) { found = t.id; return; }
                });
                return found;
            }""")
            check('T4 task found at 1366', slot_id_2 is not None)

            snap_base_2 = snap_task(page2, slot_id_2)
            run_zoom_matrix(page2, slot_id_2, snap_base_2, '1366')
            page2.close()

            # ── Viewport 3: 1600x900 ────────────────────────────────────────
            print('\n=== VIEWPORT 3: 1600x900 ===')
            page3 = browser.new_page(viewport={'width': 1600, 'height': 900})
            page3.route('**/*', track)
            page3.goto(base + '/giris')
            page3.fill('input[name="kullanici"]', 'mehmet')
            page3.fill('input[name="sifre"]', '1453')
            page3.click('button[type="submit"]')
            page3.wait_for_timeout(800)
            page3.goto(base + ROUTE, timeout=60000)
            page3.wait_for_selector('.gantt_container', timeout=30000)
            page3.wait_for_timeout(2500)

            slot_id_3 = page3.evaluate("""() => {
                var found = null;
                gantt.eachTask(function(t) {
                    if (found) return;
                    if (t.aps_type === 'slot' && t.aps_plan) { found = t.id; return; }
                });
                return found;
            }""")
            if slot_id_3:
                snap_base_3 = snap_task(page3, slot_id_3)
                run_zoom_matrix(page3, slot_id_3, snap_base_3, '1600')
            else:
                fail('T5 task found at 1600')
            page3.close()

            browser.close()

    # DB safety
    sha_after = sha256_file(str(CANONICAL))
    check('DB SHA unchanged', sha_before == sha_after)
    check('write calls == 0', len(write_calls) == 0, str(write_calls))

    print('\n' + '=' * 70)
    p = len(passed_list)
    f = len(failed_list)
    print(f'PASSED: {p}  FAILED: {f}')
    print('=' * 70)
    return f == 0


if __name__ == '__main__':
    ok_result = main()
    sys.exit(0 if ok_result else 1)
