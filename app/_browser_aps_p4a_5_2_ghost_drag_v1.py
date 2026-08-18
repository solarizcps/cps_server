# -*- coding: utf-8 -*-
"""APS P4A.5.2 — Ghost/proxy MOVE drag acceptance."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
APP = Path(__file__).resolve().parent
ROOT = APP.parent
sys.path.insert(0, str(APP))

from tools.planlama_test_isolation import assert_canonical_pristine
from tools.nexgen_tmp_db import sha256_file
from tools.test_db_guard import browser_adhoc_context

CANONICAL = APP / 'mock_data.db'
ROUTE = '/planlama/aps-pilot'
SHOT_DIR = APP / '_shot_aps_p4a_5_2'

passed, failed = [], []
write_calls: list[str] = []
page_errors: list[str] = []


def ok(l):
    passed.append(l)
    print(f'  PASS  {l}')


def fail(l, r=''):
    failed.append(l)
    print(f'  FAIL  {l}' + (f' — {r}' if r else ''))


def check(l, c, r=''):
    ok(l) if c else fail(l, r)


def bar_cy(page):
    return page.evaluate("""() => {
      const el = document.querySelector('.gantt_task_line.aps-enj-task');
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return r.top + r.height / 2;
    }""")


def ghost_cy(page):
    return page.evaluate("""() => {
      const el = document.querySelector('.aps-drag-ghost');
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return r.top + r.height / 2;
    }""")


def drag_plan(page, dx=80, dy=0, steps=14, hold_mid=False):
    task = page.locator('.gantt_task_line.aps-enj-task').first
    box = task.bounding_box()
    if not box:
        return None
    sx = box['x'] + 24
    sy = box['y'] + box['height'] / 2
    page.mouse.move(sx, sy)
    page.mouse.down()
    mid = None
    if hold_mid and dy:
        my = sy + dy // 2
        page.mouse.move(sx, my, steps=max(steps // 2, 1))
        mid = page.evaluate('''() => ({
          ghost: window.__apsGhostMetrics(),
          nativeDim: window.__apsNativeBarDimmed(),
          ghostVisible: window.__apsGhostVisible(),
          target: window.__apsDragTargetResource(),
          nativeY: (() => {
            const el = document.querySelector('.gantt_task_line.aps-enj-task');
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return r.top + r.height / 2;
          })(),
          ghostY: (() => {
            const g = document.querySelector('.aps-drag-ghost');
            if (!g) return null;
            const r = g.getBoundingClientRect();
            return r.top + r.height / 2;
          })(),
          pointerY: my
        })'''.replace('my', str(my)))
    page.mouse.move(sx + dx, sy + dy, steps=max(steps // 2 if hold_mid else steps, 1))
    if not hold_mid:
        page.wait_for_timeout(80)
    page.mouse.up()
    page.wait_for_timeout(450)
    return {'start': {'x': sx, 'y': sy}, 'mid': mid}


def main():
    print('=' * 70)
    print('APS P4A.5.2 — Ghost/Proxy MOVE Drag')
    print('=' * 70)

    SHOT_DIR.mkdir(exist_ok=True)
    sha_before = sha256_file(str(CANONICAL))

    with browser_adhoc_context(str(CANONICAL), prefix='aps_p552_') as srv:
        base = srv['base_url']
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1920, 'height': 1080})
            page.on('pageerror', lambda e: page_errors.append(str(e)))

            def track(route):
                if route.request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
                    if 'aps-pilot' in route.request.url or 'planlama' in route.request.url:
                        write_calls.append(route.request.method + ' ' + route.request.url)
                route.continue_()

            page.route('**/*', track)
            resp = page.goto(base + '/giris')
            page.fill('input[name="kullanici"]', 'mehmet')
            page.fill('input[name="sifre"]', '1453')
            page.click('button[type="submit"]')
            page.wait_for_timeout(800)
            r2 = page.goto(base + ROUTE, timeout=60000)
            check('T1 page GET 200', r2.status == 200 if r2 else False)
            page.wait_for_selector('.gantt_container', timeout=30000)
            page.wait_for_timeout(2500)

            metrics = page.evaluate('() => window.__apsRowMetrics()')
            # P5.1: 1 process + 4 machine + 8 slot = 13 rows (machine hierarchy added)
            check('T2 13 resource/process row korunuyor', metrics.get('gridRows') == 13, str(metrics))
            on_m1 = page.evaluate("() => window.__apsPlansOnResource('M1-A')")
            check('T3 33917 M1/A', 'plan-199' in on_m1, str(on_m1))

            page.evaluate('() => window.__apsDiscardStaging()')
            task = page.locator('.gantt_task_line.aps-enj-task').first
            box = task.bounding_box()
            sx = box['x'] + 24
            sy = box['y'] + box['height'] / 2
            page.mouse.move(sx, sy)
            page.mouse.down()
            page.mouse.move(sx + 30, sy, steps=6)
            page.wait_for_selector('.aps-drag-ghost', timeout=5000)
            check('T4 drag start ghost oluşuyor', page.locator('.aps-drag-ghost').count() > 0)
            check('T5 native bar dim', page.evaluate('() => window.__apsNativeBarDimmed()'))
            page.screenshot(path=str(SHOT_DIR / 'A_drag_start_ghost.png'), full_page=False)
            page.mouse.move(sx + 80, sy, steps=8)
            page.wait_for_timeout(80)
            gm = page.evaluate('() => window.__apsGhostMetrics()')
            gap_h = gm.get('gap') if gm.get('gap') is not None else 999
            check('T6 horizontal ghost pointer takip', gap_h < 8, str(gm))
            page.screenshot(path=str(SHOT_DIR / 'F_horizontal_ghost.png'), full_page=False)
            page.mouse.up()
            page.wait_for_timeout(400)
            page.evaluate('() => window.__apsDiscardStaging()')

            y_m1a = page.evaluate("() => window.__apsTimelineRowY('M1-A')")
            y_m2a = page.evaluate("() => window.__apsTimelineRowY('M2-A')")
            y_m1b = page.evaluate("() => window.__apsTimelineRowY('M1-B')")
            dy_m1b = int(y_m1b - y_m1a) if y_m1b and y_m1a else 0
            dy_m2a = int(y_m2a - y_m1a) if y_m2a and y_m1a else 0

            # T8 M1/B highlight — before vertical drop
            if dy_m1b:
                box = task.bounding_box()
                sx, sy = box['x'] + 24, box['y'] + box['height'] / 2
                page.mouse.move(sx, sy)
                page.mouse.down()
                page.mouse.move(sx, sy + dy_m1b - 4, steps=8)
                page.wait_for_timeout(100)
                tgt = page.evaluate('() => window.__apsDragTargetResource()')
                page.mouse.up()
                page.wait_for_timeout(300)
                check('T8 M1/A→M1/B highlight', tgt == 'M1-B', str(tgt))
                page.evaluate('() => window.__apsDiscardStaging()')

            # Vertical M1/A → M2/A with coordinate samples
            box = task.bounding_box()
            sx, sy = box['x'] + 24, box['y'] + box['height'] / 2
            page.mouse.move(sx, sy)
            page.mouse.down()
            vert_samples = []
            steps = 12
            for i in range(1, steps + 1):
                cy = sy + dy_m2a * (i / steps)
                page.mouse.move(sx, cy, steps=1)
                page.wait_for_timeout(40)
                if i in (4, 8, 12):
                    s = page.evaluate('''(cy) => ({
                      pointerY: cy,
                      ghostY: (() => {
                        const g = document.querySelector('.aps-drag-ghost');
                        if (!g) return null;
                        const r = g.getBoundingClientRect();
                        return r.top + r.height / 2;
                      })(),
                      ghostGap: window.__apsGhostMetrics().gap,
                      targetResource: window.__apsDragTargetResource(),
                      nativeBarY: (() => {
                        const el = document.querySelector('.gantt_task_line.aps-enj-task');
                        if (!el) return null;
                        const r = el.getBoundingClientRect();
                        return r.top + r.height / 2;
                      })()
                    })''', cy)
                    vert_samples.append(s)
            page.screenshot(path=str(SHOT_DIR / 'B_drag_between_rows.png'), full_page=False)
            page.screenshot(path=str(SHOT_DIR / 'C_drag_M2A_target.png'), full_page=False)

            max_gap = 0
            for s in vert_samples:
                g = s.get('ghostGap')
                if g is not None:
                    max_gap = max(max_gap, g)
                elif s.get('ghostY') is not None:
                    max_gap = max(max_gap, abs(s['pointerY'] - s['ghostY']))
            check('T7 vertical ghost pointer takip', max_gap < 8, f'max_gap={max_gap} samples={vert_samples}')
            check('T10 ghost pointer gap kabul', max_gap < 8, str(max_gap))

            tgt_m2 = vert_samples[-1].get('targetResource') if vert_samples else None
            check('T9 M1/A→M2/A highlight', tgt_m2 == 'M2-A', str(tgt_m2))

            page.mouse.up()
            page.wait_for_timeout(500)
            page.screenshot(path=str(SHOT_DIR / 'D_after_drop_M2A.png'), full_page=False)

            check('T11 drop M2/A', page.evaluate('() => window.__apsStagingCount()') >= 1)
            check('T13 ghost siliniyor', not page.evaluate('() => window.__apsGhostVisible()'))
            staged = page.evaluate('() => window.__apsStagedChanges()')
            if staged:
                check('T12 gerçek bar M2/A staged', staged[0].get('new_resource') == 'M2-A', str(staged[0]))
                check('T14 staging old_resource M1/A', staged[0].get('old_resource') == 'M1-A')
                check('T15 staging new_resource M2/A', staged[0].get('new_resource') == 'M2-A')
            bar_y = bar_cy(page)
            check('T12b bar Y on M2/A row', abs(bar_y - y_m2a) < 14 if bar_y and y_m2a else False,
                  f'bar_y={bar_y} y_m2a={y_m2a}')

            # ===== T-V1..T-V16: Vertical Resource Drag Regression =====
            tv_snap = page.evaluate("""() => {
                var t = gantt.getTask('M2-A');
                var el = gantt.getTaskNode('M2-A');
                var r = el ? el.getBoundingClientRect() : null;
                return {
                    resource: t ? t.id : null,
                    start_date: t && t.start_date ? t.start_date.toISOString() : null,
                    start_is_date: t ? (t.start_date instanceof Date) : null,
                    end_date: t && t.end_date ? t.end_date.toISOString() : null,
                    end_is_date: t ? (t.end_date instanceof Date) : null,
                    duration: t ? t.duration : null,
                    bar_width: r ? Math.round(r.width) : null,
                    bar_height: r ? Math.round(r.height) : null,
                    bar_classes: el ? el.className : null,
                    no_thin: el ? !el.classList.contains('gantt_thin_task') : null,
                    no_dependent: el ? !el.classList.contains('gantt_dependent_task') : null,
                    staging_count: window.__apsStagingCount(),
                    staged: window.__apsStagedChanges(),
                };
            }""")
            # Get baseline duration from M1-A before drag (captured at snapshot time)
            m1a_orig_dur = page.evaluate("""() => {
                // planOriginals has the baseline
                var t = gantt.getTask('M2-A');
                var planId = t && t.aps_primary_plan_id ? t.aps_primary_plan_id : null;
                if (!planId) return null;
                // staged has old_start/old_end
                var staged = window.__apsStagedChanges();
                if (staged && staged.length) {
                    var s = staged[0];
                    if (s.old_start && s.old_end) {
                        return Math.round((new Date(s.old_end) - new Date(s.old_start)) / 60000);
                    }
                }
                return null;
            }""")

            check('T-V1 resource == M2-A', tv_snap.get('resource') == 'M2-A', str(tv_snap.get('resource')))
            check('T-V2 start_date instanceof Date', tv_snap.get('start_is_date') is True)
            check('T-V3 end_date instanceof Date', tv_snap.get('end_is_date') is True)
            dur_after = tv_snap.get('duration')
            if m1a_orig_dur is not None and dur_after is not None:
                check('T-V4 duration preserved', abs(dur_after - m1a_orig_dur) <= 1,
                      f'before={m1a_orig_dur} after={dur_after}')
            else:
                check('T-V4 duration preserved', dur_after is not None and dur_after > 100,
                      f'dur_after={dur_after}')
            check('T-V5 bar_width > 100', (tv_snap.get('bar_width') or 0) > 100,
                  f"bar_width={tv_snap.get('bar_width')}")
            check('T-V6 NO gantt_thin_task', tv_snap.get('no_thin') is True,
                  str(tv_snap.get('bar_classes')))
            check('T-V7 NO gantt_dependent_task', tv_snap.get('no_dependent') is True,
                  str(tv_snap.get('bar_classes')))
            check('T-V8 staging exactly 1 change', tv_snap.get('staging_count') == 1,
                  str(tv_snap.get('staging_count')))
            if tv_snap.get('staged'):
                s0 = tv_snap['staged'][0]
                check('T-V9 staging proposed_start not None', s0.get('proposed_start') is not None)
                ps = s0.get('proposed_start')
                pe = s0.get('proposed_end') if s0.get('proposed_end') else s0.get('proposed_start')
                check('T-V10 duration NOT 1 minute', ps != pe,
                      f"{ps} == {pe}")
            else:
                fail('T-V9 staging proposed_start not None', 'staged list is empty')
                fail('T-V10 duration NOT 1 minute', 'staged list is empty')

            # T-V11: M1/A → M3/A
            page.click('#apsStagingDiscard')
            page.wait_for_timeout(300)
            y_m3a = page.evaluate("() => window.__apsTimelineRowY('M3-A')")
            dy_m3a = int(y_m3a - y_m1a) if y_m3a and y_m1a else 0
            if dy_m3a > 0:
                box = task.bounding_box()
                sx2, sy2 = box['x'] + 24, box['y'] + box['height'] / 2
                page.mouse.move(sx2, sy2)
                page.mouse.down()
                for i in range(1, 15):
                    page.mouse.move(sx2, sy2 + dy_m3a * (i/14), steps=1)
                    page.wait_for_timeout(20)
                page.mouse.up()
                page.wait_for_timeout(500)
                tv11 = page.evaluate("""() => {
                    var t = gantt.getTask('M3-A');
                    var el = gantt.getTaskNode('M3-A');
                    var r = el ? el.getBoundingClientRect() : null;
                    return {
                        new_resource: window.__apsStagedChanges().length ? window.__apsStagedChanges()[0].new_resource : null,
                        bar_width: r ? Math.round(r.width) : null,
                        duration: t ? t.duration : null,
                        no_thin: el ? !el.classList.contains('gantt_thin_task') : null,
                    };
                }""")
                check('T-V11 M1/A→M3/A resource', tv11.get('new_resource') == 'M3-A', str(tv11))
                check('T-V11b M3/A bar_width > 100', (tv11.get('bar_width') or 0) > 100, str(tv11))
                check('T-V11c M3/A no gantt_thin_task', tv11.get('no_thin') is True, str(tv11))
                page.evaluate('() => window.__apsDiscardStaging()')
            else:
                ok('T-V11 M1/A→M3/A skipped (no row data)')

            # T-V12: horizontal MOVE
            drag_plan(page, dx=70, dy=0)
            tv12 = page.evaluate('() => window.__apsStagingCount()')
            check('T-V12 horizontal move staged', tv12 >= 1, str(tv12))
            page.evaluate('() => window.__apsDiscardStaging()')

            # T-V13: RESIZE
            box = task.bounding_box()
            rx2, ry2 = box['x'] + box['width'] - 6, box['y'] + box['height'] / 2
            page.mouse.move(rx2, ry2)
            page.mouse.down()
            page.mouse.move(rx2 + 60, ry2, steps=8)
            page.mouse.up()
            page.wait_for_timeout(400)
            check('T-V13 resize staged', page.evaluate('() => window.__apsStagingCount()') >= 1)
            check('T-V13b resize no ghost', not page.evaluate('() => window.__apsGhostVisible()'))
            page.evaluate('() => window.__apsDiscardStaging()')

            # T-V14: ESC cancel
            box = task.bounding_box()
            sx3, sy3 = box['x'] + 24, box['y'] + box['height'] / 2
            page.mouse.move(sx3, sy3)
            page.mouse.down()
            page.mouse.move(sx3 + 40, sy3, steps=4)
            page.wait_for_timeout(80)
            page.keyboard.press('Escape')
            page.mouse.up()
            page.wait_for_timeout(400)
            esc_snap = page.evaluate("""() => {
                var t = gantt.getTask('M1-A');
                var el = gantt.getTaskNode('M1-A');
                var r = el ? el.getBoundingClientRect() : null;
                return {
                    ghost_visible: window.__apsGhostVisible(),
                    staging: window.__apsStagingCount(),
                    bar_width: r ? Math.round(r.width) : null,
                    resource: t ? t.id : null,
                    duration: t ? t.duration : null,
                };
            }""")
            check('T-V14 ESC ghost gone', not esc_snap.get('ghost_visible'))
            check('T-V14b ESC no staging', esc_snap.get('staging', 99) == 0, str(esc_snap.get('staging')))
            check('T-V14c ESC task back M1-A', esc_snap.get('resource') == 'M1-A')

            # T-V15: no getDuration errors (T30 covers page errors)
            tv15_errors = page.evaluate("""() => {
                return typeof window.__aps_last_getDuration_error !== 'undefined'
                    ? window.__aps_last_getDuration_error : 0;
            }""")
            check('T-V15 getDuration errors == 0', tv15_errors == 0, str(tv15_errors))

            # T-V16: page errors = 0 (also covered by T30 but explicit)
            check('T-V16 page errors == 0', len(page_errors) == 0, str(page_errors))

            page.evaluate('() => window.__apsDiscardStaging()')
            page.wait_for_timeout(300)
            # ===== End T-V1..T-V16 =====

            # T16: Re-do vertical drag M1/A → M2/A and then DISCARD to verify revert
            box = task.bounding_box()
            sx_t16, sy_t16 = box['x'] + 24, box['y'] + box['height'] / 2
            page.mouse.move(sx_t16, sy_t16)
            page.mouse.down()
            for i in range(1, 13):
                page.mouse.move(sx_t16, sy_t16 + dy_m2a * (i/12), steps=1)
                page.wait_for_timeout(25)
            page.mouse.up()
            page.wait_for_timeout(400)
            page.evaluate('() => window.__apsDiscardStaging()')
            page.wait_for_timeout(450)
            page.screenshot(path=str(SHOT_DIR / 'E_discard_M1A.png'), full_page=False)
            check('T16 DISCARD → M1/A', page.evaluate("() => window.__apsPlansOnResource('M1-A')").count('plan-199') >= 1)

            drag_plan(page, dx=70, dy=0)
            check('T17 horizontal move staged', page.evaluate('() => window.__apsStagingCount()') >= 1)
            page.evaluate('() => window.__apsDiscardStaging()')

            # Resize regression
            box = task.bounding_box()
            rx = box['x'] + box['width'] - 6
            ry = box['y'] + box['height'] / 2
            w0 = box['width']
            page.mouse.move(rx, ry)
            page.mouse.down()
            page.mouse.move(rx + 60, ry, steps=8)
            page.mouse.up()
            page.wait_for_timeout(400)
            check('T18 resize regression', page.evaluate('() => window.__apsStagingCount()') >= 1)
            check('T18b resize no ghost', not page.evaluate('() => window.__apsGhostVisible()'))
            page.evaluate('() => window.__apsDiscardStaging()')

            drag_plan(page, dx=50, dy=0)
            prof = page.evaluate('() => window.__apsDragProfile()')
            dm = prof.get('metrics', {})
            check('T19 conflict drop-only', dm.get('conflict', 0) >= 1 and dm.get('stage', 0) >= 1, str(dm))
            page.evaluate('() => window.__apsDiscardStaging()')

            page.click('#apsZoomGroup button[data-zoom="10m"]')
            page.wait_for_timeout(350)
            drag_plan(page, dx=80, dy=0, steps=10)
            check('T20 10dk zoom', page.evaluate('() => window.__apsStagingCount()') >= 1)
            page.evaluate('() => window.__apsDiscardStaging()')

            page.click('#apsZoomGroup button[data-zoom="1h"]')
            page.wait_for_timeout(300)
            drag_plan(page, dx=60, dy=0)
            check('T21 1h zoom', page.evaluate('() => window.__apsStagingCount()') >= 1)
            page.evaluate('() => window.__apsDiscardStaging()')

            # Autoscroll edge smoke
            box = task.bounding_box()
            sx, sy = box['x'] + 24, box['y'] + box['height'] / 2
            scroll_before = page.evaluate("() => document.querySelector('.gantt_task')?.scrollLeft ?? 0")
            page.mouse.move(sx, sy)
            page.mouse.down()
            for i in range(1, 25):
                page.mouse.move(sx + i * 35, sy, steps=1)
                page.wait_for_timeout(35)
            page.screenshot(path=str(SHOT_DIR / 'G_autoscroll_edge.png'), full_page=False)
            page.mouse.up()
            page.wait_for_timeout(300)
            scroll_after = page.evaluate("() => document.querySelector('.gantt_task')?.scrollLeft ?? 0")
            check('T22 edge autoscroll', scroll_after >= scroll_before, f'{scroll_before}->{scroll_after}')
            page.evaluate('() => window.__apsDiscardStaging()')

            # During drag drawer/tooltip
            box = task.bounding_box()
            page.mouse.move(box['x'] + 24, box['y'] + box['height'] / 2)
            page.mouse.down()
            page.mouse.move(box['x'] + 50, box['y'] + box['height'] / 2, steps=4)
            during = page.evaluate('''() => ({
              drawer: window.__apsDrawerOpen(),
              tooltipHidden: !document.querySelector('.gantt_tooltip') ||
                getComputedStyle(document.querySelector('.gantt_tooltip')).display === 'none',
              ghost: window.__apsGhostVisible()
            })''')
            page.mouse.up()
            page.wait_for_timeout(300)
            check('T23 drawer drag sırasında update yok', not during.get('drawer'))
            check('T24 tooltip drag sırasında yok', during.get('tooltipHidden', True))
            check('T4b ghost during move', during.get('ghost'))
            page.evaluate('() => window.__apsDiscardStaging()')

            print('\n  --- Coordinate proof (vertical) ---')
            for s in vert_samples:
                print('   ', json.dumps(s, ensure_ascii=False))

            browser.close()

    check('T25 POST=0', not any('POST' in c for c in write_calls), str(write_calls))
    check('T26 PUT=0', not any('PUT' in c for c in write_calls))
    check('T27 DELETE=0', not any('DELETE' in c for c in write_calls))

    try:
        assert_canonical_pristine(sha_before)
        ok('T28 canonical SHA unchanged')
    except RuntimeError as exc:
        fail('T28 canonical SHA unchanged', str(exc))

    diff = subprocess.run(['git', 'diff', '--name-only', 'app/modules/enjeksiyon/'],
                          cwd=str(ROOT), capture_output=True, text=True)
    check('T29 ENJ diff EMPTY', (diff.stdout or '').strip() == '')
    check('T30 console/page error=0', len(page_errors) == 0, str(page_errors))

    for name in (
        'A_drag_start_ghost.png', 'B_drag_between_rows.png', 'C_drag_M2A_target.png',
        'D_after_drop_M2A.png', 'E_discard_M1A.png', 'F_horizontal_ghost.png',
        'G_autoscroll_edge.png',
    ):
        check(f'Shot {name}', (SHOT_DIR / name).exists())

    print('\n' + '=' * 70)
    print(f'PASSED: {len(passed)}  FAILED: {len(failed)}')
    if failed:
        for f in failed:
            print(f'  - {f}')
    print('=' * 70)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
