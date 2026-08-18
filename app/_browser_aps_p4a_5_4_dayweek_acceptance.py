# -*- coding: utf-8 -*-
"""
P4A.5.4 — "1 gün" + "1 hafta" ZOOM CONTRACT ACCEPTANCE

Verifies:
  A1  "1 gün"  view: 1-day window, top=full-date+dayname, bottom=2h columns
  A2  "1 hafta" view: 7-day window, month header, day+date middle, 4h sub
  A3  Turkish labels: full day name, short day name, month name, hour
  A4  Zoom round-trip: 1d → 1w → 2m → 1w → 1d
  A5  Drag M1/A → M2/A, then zoom 1d → 1w → 2m → 1w → 1d → DISCARD
  A6  task/resource/date/duration parity throughout
  A7  DB SHA unchanged, WRITE = 0
"""
from __future__ import annotations
import sys
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


# ─── helpers ────────────────────────────────────────────────────────────────

TR_DAYS_SHORT = ['Paz', 'Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt']
TR_MONTHS_SHORT = ['Oca','Şub','Mar','Nis','May','Haz','Tem','Ağu','Eyl','Eki','Kas','Ara']
TR_MONTHS_FULL  = ['Ocak','Şubat','Mart','Nisan','Mayıs','Haziran',
                   'Temmuz','Ağustos','Eylül','Ekim','Kasım','Aralık']

HOUR_CELLS_1D = {'00:00','02:00','04:00','06:00','08:00','10:00','12:00',
                 '14:00','16:00','18:00','20:00','22:00'}
HOUR_CELLS_1W = {'00','04','08','12','16','20'}


def apply_zoom(page, key):
    page.evaluate(f"() => window.__apsApplyZoom('{key}')")
    page.wait_for_timeout(700)


def scale_texts(page):
    return page.evaluate("""() => {
        var cells = document.querySelectorAll('.gantt_scale_cell');
        return Array.from(cells).map(function(c){ return c.textContent.trim(); });
    }""")


def count_rows(page):
    return page.evaluate(
        "() => document.querySelectorAll('.gantt_grid_data .gantt_row').length"
    )


def snap_task(page, task_id):
    return page.evaluate(f"""() => {{
        if (!window.gantt || !gantt.isTaskExists('{task_id}')) return null;
        var t = gantt.getTask('{task_id}');
        var el = gantt.getTaskNode('{task_id}');
        var r = el ? el.getBoundingClientRect() : null;
        return {{
            start_date: t.start_date ? t.start_date.toISOString() : null,
            end_date:   t.end_date   ? t.end_date.toISOString()   : null,
            duration:   t.duration,
            dom_exists: !!el,
            bar_width:  r ? Math.round(r.width) : null,
        }};
    }}""")


def get_staged(page):
    return page.evaluate("() => window.__apsStagedChanges ? window.__apsStagedChanges() : []")


def discard_staging(page):
    page.evaluate("() => window.__apsDiscardStaging && window.__apsDiscardStaging()")
    page.wait_for_timeout(600)


def drag_and_stage(page, to_slot_id):
    """Move plan sip_no=33917 to target slot and create staging entry."""
    return page.evaluate(f"""() => {{
        var planId = null, fromSlotId = null;
        gantt.eachTask(function(t) {{
            if (fromSlotId) return;
            if (t.aps_type === 'slot' && t.aps_plan && t.aps_plan.sip_no == 33917) {{
                planId = t.aps_plan.id;
                fromSlotId = t.id;
            }}
        }});
        if (!planId)                        return {{ok:false, reason:'plan not found'}};
        if (!gantt.isTaskExists('{to_slot_id}')) return {{ok:false, reason:'toSlot not found'}};
        if (fromSlotId === '{to_slot_id}')   return {{ok:false, reason:'same slot'}};
        if (typeof window.__apsDragAndStage !== 'function')
                                             return {{ok:false, reason:'__apsDragAndStage missing'}};
        window.__apsDragAndStage(fromSlotId, '{to_slot_id}', planId);
        return {{ok:true, fromSlotId:fromSlotId, toSlotId:'{to_slot_id}'}};
    }}""")


# ─── A1: "1 gün" view ────────────────────────────────────────────────────────

def check_1d_view(page, slot_id, base_snap):
    print('\n--- A1: "1 gün" view ---')
    apply_zoom(page, '1d')
    sc = scale_texts(page)
    rows = count_rows(page)
    snap = snap_task(page, slot_id)

    check('A1: resource rows == 13', rows == 13, f'rows={rows}')
    check('A1: task in store', snap is not None)
    if snap:
        check('A1: dom_exists', snap['dom_exists'] is True, f'dom={snap["dom_exists"]}')
        check('A1: duration unchanged',
              snap['duration'] == base_snap['duration'],
              f'base={base_snap["duration"]} now={snap["duration"]}')

    # Scale: top row must contain a Turkish full day name
    found_day_name = any(
        any(dn in cell for dn in ['Pazartesi','Salı','Çarşamba','Perşembe','Cuma','Cumartesi','Pazar'])
        for cell in sc
    )
    check('A1: Turkish full day name in top scale', found_day_name,
          f'cells={sc[:4]}')

    # Scale: top row must contain a Turkish month name
    found_month = any(
        any(m in cell for m in TR_MONTHS_FULL + TR_MONTHS_SHORT) for cell in sc
    )
    check('A1: Turkish month name in top scale', found_month, f'cells={sc[:4]}')

    # Scale: hour row must contain 2-hour markers
    found_hours = any(cell in HOUR_CELLS_1D for cell in sc)
    check('A1: Hour columns (2h step) in bottom scale', found_hours,
          f'cells={[c for c in sc if ":00" in c][:8]}')

    # Window must be approximately 1 day — no multi-day scale cells
    # (each top cell = 1 day → should see exactly 1-2 day header cells)
    day_headers = [c for c in sc if any(dn in c for dn in ['Pazartesi','Salı','Çarşamba',
                                                             'Perşembe','Cuma','Cumartesi','Pazar'])]
    check('A1: window is ~1 day (1-2 day headers)', 1 <= len(day_headers) <= 2,
          f'day_headers={day_headers}')

    print(f'  Scale top: {sc[:3]}')
    print(f'  Scale hours: {[c for c in sc if ":00" in c][:8]}')


# ─── A2: "1 hafta" view ──────────────────────────────────────────────────────

def check_1w_view(page, slot_id, base_snap):
    print('\n--- A2: "1 hafta" view ---')
    apply_zoom(page, '1w')
    sc = scale_texts(page)
    rows = count_rows(page)
    snap = snap_task(page, slot_id)

    check('A2: resource rows == 13', rows == 13, f'rows={rows}')
    check('A2: task in store', snap is not None)
    if snap:
        check('A2: dom_exists', snap['dom_exists'] is True)
        check('A2: duration unchanged',
              snap['duration'] == base_snap['duration'],
              f'base={base_snap["duration"]} now={snap["duration"]}')

    # Top scale: Turkish month name
    found_month = any(
        any(m in cell for m in TR_MONTHS_FULL + TR_MONTHS_SHORT) for cell in sc
    )
    check('A2: Turkish month in top scale', found_month, f'cells={sc[:4]}')

    # Middle scale: Turkish short day names
    found_day = any(any(ds in cell for ds in TR_DAYS_SHORT) for cell in sc)
    check('A2: Turkish day names (Pzt/Sal...) in middle scale', found_day,
          f'cells={[c for c in sc if any(ds in c for ds in TR_DAYS_SHORT)][:5]}')

    # Middle scale: must show approximately 7 day headers
    day_cells = [c for c in sc if any(ds in c for ds in TR_DAYS_SHORT)]
    check('A2: ~7 day columns visible', 5 <= len(day_cells) <= 9,
          f'day_cells({len(day_cells)})={day_cells[:9]}')

    # Bottom scale: hour sub-scale (4h step: 00, 04, 08, 12, 16, 20)
    found_hour_sub = any(cell in HOUR_CELLS_1W for cell in sc)
    check('A2: Hour sub-scale (4h) present', found_hour_sub,
          f'cells={[c for c in sc if c in HOUR_CELLS_1W][:6]}')

    # No "Hafta N" in this view (moved to 2m+)
    found_hafta = any('Hafta' in cell for cell in sc)
    check('A2: No Hafta-N label in 1w view (uses day detail instead)',
          not found_hafta,
          f'hafta_cells={[c for c in sc if "Hafta" in c][:3]}')

    print(f'  Scale top: {sc[:2]}')
    print(f'  Scale days: {day_cells[:7]}')
    print(f'  Scale hours: {[c for c in sc if c in HOUR_CELLS_1W][:6]}')


# ─── A3: Round-trip ──────────────────────────────────────────────────────────

def check_roundtrip(page, slot_id, base_snap, sequence, label):
    print(f'\n--- A3/A4 Round-trip [{label}]: {[s[0] for s in sequence]} ---')
    for key, expect_bar in sequence:
        apply_zoom(page, key)
        rows = count_rows(page)
        snap = snap_task(page, slot_id)
        lbl = f'RT/{key}'
        check(f'{lbl}: rows==13', rows == 13, f'rows={rows}')
        check(f'{lbl}: in store', snap is not None)
        if snap:
            check(f'{lbl}: start unchanged',
                  snap['start_date'] == base_snap['start_date'],
                  f"base={base_snap['start_date'][:16]} now={snap['start_date'][:16]}")
            check(f'{lbl}: dur unchanged',
                  snap['duration'] == base_snap['duration'],
                  f"base={base_snap['duration']} now={snap['duration']}")
            check(f'{lbl}: dom_exists', snap['dom_exists'] is True)
            if expect_bar:
                check(f'{lbl}: bar_width>0', (snap['bar_width'] or 0) > 0,
                      f'w={snap["bar_width"]}')


# ─── A5: Drag + zoom ─────────────────────────────────────────────────────────

def check_drag_zoom(page, slot_id, base_snap):
    print('\n--- A5: Drag + zoom round-trip ---')
    apply_zoom(page, '1d')
    page.wait_for_timeout(300)

    res = drag_and_stage(page, 'M2-A')
    check('A5: drag M1/A→M2/A ok', res and res.get('ok'), str(res))
    if not (res and res.get('ok')):
        fail('A5: SKIP remaining drag+zoom tests')
        return

    page.wait_for_timeout(400)
    staged = get_staged(page)
    check('A5: staging entry exists', isinstance(staged, list) and len(staged) > 0,
          f'staged={staged}')

    new_id = res['toSlotId']
    for key in ('1d', '1w', '2m', '1w', '1d'):
        apply_zoom(page, key)
        rows = count_rows(page)
        snap = snap_task(page, new_id)
        lbl = f'A5/drag+zoom/{key}'
        check(f'{lbl}: rows==13', rows == 13, f'rows={rows}')
        check(f'{lbl}: task in store', snap is not None)
        if snap:
            check(f'{lbl}: dur unchanged',
                  snap['duration'] == base_snap['duration'],
                  f"base={base_snap['duration']} now={snap['duration']}")
            check(f'{lbl}: dom_exists', snap['dom_exists'] is True)

    # Discard
    apply_zoom(page, '1d')
    discard_staging(page)
    page.wait_for_timeout(600)

    snap_disc = snap_task(page, slot_id)
    check('A5: original M1-A restored after discard',
          snap_disc is not None and snap_disc.get('dom_exists') is True,
          f'snap={snap_disc}')
    if snap_disc:
        dur_base = base_snap.get('duration') or 0
        dur_now  = snap_disc.get('duration') or 0
        check('A5: duration restored (±1)', abs(dur_now - dur_base) <= 1,
              f'base={dur_base} now={dur_now}')

    staged_after = get_staged(page)
    check('A5: staging empty after discard',
          isinstance(staged_after, list) and len(staged_after) == 0,
          f'staged={staged_after}')


# ─── main ────────────────────────────────────────────────────────────────────

def main():
    print('=' * 70)
    print('P4A.5.4 — "1 gün" + "1 hafta" ZOOM CONTRACT ACCEPTANCE')
    print('=' * 70)

    sha_before = sha256_file(str(CANONICAL))
    print(f'  DB SHA BEFORE: {sha_before}')

    write_calls: list[str] = []
    page_errors: list[str] = []

    with browser_adhoc_context(str(CANONICAL), prefix='aps_p554_') as srv:
        base = srv['base_url']
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
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
            r = page.goto(base + ROUTE, timeout=60000)
            check('T0 page 200', r and r.status == 200)
            page.wait_for_selector('.gantt_container', timeout=30000)
            page.wait_for_timeout(2500)

            slot_id = page.evaluate("""() => {
                var found = null;
                gantt.eachTask(function(t) {
                    if (found) return;
                    if (t.aps_type === 'slot' && t.aps_plan && t.aps_plan.sip_no == 33917)
                        { found = t.id; }
                });
                return found;
            }""")
            check('T1 task found', slot_id is not None, str(slot_id))
            if not slot_id:
                browser.close()
                return False

            base_snap = snap_task(page, slot_id)
            check('T2 baseline ok', base_snap and base_snap.get('dom_exists') is True)
            if base_snap:
                print(f'  Baseline: start={base_snap["start_date"][:16]} '
                      f'dur={base_snap["duration"]} bar_w={base_snap["bar_width"]}')

            # ── A1: 1 gün ──────────────────────────────────────────────────
            check_1d_view(page, slot_id, base_snap)

            # ── A2: 1 hafta ─────────────────────────────────────────────────
            check_1w_view(page, slot_id, base_snap)

            # ── A3/A4: Round-trip ────────────────────────────────────────────
            apply_zoom(page, '1h')
            check_roundtrip(page, slot_id, base_snap,
                            [('1d',True),('1w',True),('2m',False),('1w',True),('1d',True)],
                            '1d→1w→2m→1w→1d')

            # ── A5: Drag + zoom ──────────────────────────────────────────────
            apply_zoom(page, '1d')
            check_drag_zoom(page, slot_id, base_snap)

            # ── errors ───────────────────────────────────────────────────────
            check('T99 page errors == 0', len(page_errors) == 0,
                  str(page_errors[:3]))

            browser.close()

    sha_after = sha256_file(str(CANONICAL))
    check('A7: DB SHA unchanged', sha_before == sha_after)
    check('A7: WRITE calls == 0', len(write_calls) == 0, str(write_calls))

    print('\n' + '=' * 70)
    p, f_ = len(passed_list), len(failed_list)
    print(f'PASSED: {p}  FAILED: {f_}')
    print('=' * 70)
    return f_ == 0


if __name__ == '__main__':
    ok_result = main()
    sys.exit(0 if ok_result else 1)
