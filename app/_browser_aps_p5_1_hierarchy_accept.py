# -*- coding: utf-8 -*-
"""
P5.1 — MAKİNE HİYERARŞİSİ ACCEPTANCE TESTS
H1  Toplam 13 satır (1 process + 4 machine + 8 slot)
H2  ENJEKSİYON default open
H3  MAKİNE 1..4 default open
H4  MAKİNE 1 collapse → A/B gizlenir (2 satır azalır)
H5  MAKİNE 1 re-open → A/B geri gelir
H6  ENJEKSİYON collapse → tüm subtree gizlenir (1 satır kalır)
H7  33917 M1-A satırında görünür (parent == 'M1-A')
H8  M1-A → M2-A drag PASS
H9  1px bug YOK (bar_width > 20px)
H10 DISCARD → M1-A'ya geri döner
H11 Zoom round-trip PASS
H12 DB SHA unchanged
H13 DB WRITE == 0
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
APP = Path(__file__).resolve().parent
ROOT = APP.parent
sys.path.insert(0, str(APP))

from tools.nexgen_tmp_db import sha256_file
from tools.test_db_guard import browser_adhoc_context

CANONICAL = APP / 'mock_data.db'
ROUTE = '/planlama/aps-pilot'

passed, failed = [], []
write_calls: list[str] = []
page_errors: list[str] = []


def ok(l): passed.append(l); print(f'  PASS  {l}')
def fail(l, r=''): failed.append(l); print(f'  FAIL  {l}' + (f' — {r}' if r else ''))
def check(l, c, r=''): ok(l) if c else fail(l, r)


def grid_rows(page):
    return page.evaluate('() => document.querySelectorAll(".gantt_grid_data .gantt_row").length')


def grid_row_texts(page):
    return page.evaluate('''() => {
        var rows = document.querySelectorAll(".gantt_grid_data .gantt_row");
        return Array.from(rows).map(function(r) {
            var cell = r.querySelector(".gantt_cell");
            return cell ? cell.textContent.trim() : "";
        });
    }''')


def count_visible_rows(page):
    return page.evaluate('''() => {
        var rows = document.querySelectorAll(".gantt_grid_data .gantt_row");
        return Array.from(rows).filter(function(r) {
            return window.getComputedStyle(r).display !== "none";
        }).length;
    }''')


def task_open(page, task_id):
    return page.evaluate(f'() => {{ var t=gantt.getTask("{task_id}"); return t ? !!t.$open : null; }}')


def click_tree_toggle(page, task_id):
    page.evaluate(f'''() => {{
        var row = document.querySelector('.gantt_row[task_id="{task_id}"]');
        if (!row) return;
        var arrow = row.querySelector(".gantt_tree_icon");
        if (arrow) arrow.click();
    }}''')
    page.wait_for_timeout(600)


def find_plan_task(page):
    return page.evaluate('''() => {
        var found = null;
        gantt.eachTask(function(t) {
            if (t.aps_plan && Number(t.aps_plan.sip_no) === 33917) {
                found = { id: t.id, parent: t.parent };
            }
        });
        return found;
    }''')


def task_bar_width(page, task_id):
    return page.evaluate(f'''() => {{
        var bar = document.querySelector('.gantt_task_line[task_id="{task_id}"]');
        if (!bar) return -1;
        return bar.getBoundingClientRect().width;
    }}''')


def main():
    sha_before = sha256_file(str(CANONICAL))
    print(f'DB_SHA_BEFORE: {sha_before}')

    with browser_adhoc_context(str(CANONICAL), prefix='aps_p5_1_') as srv:
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
            page.goto(base + ROUTE, timeout=60000)
            page.wait_for_selector('.gantt_container', timeout=30000)
            page.wait_for_timeout(2500)

            # H1: 13 satır
            rows = grid_rows(page)
            texts = grid_row_texts(page)
            print(f'  Grid row texts: {texts}')
            check('H1 toplam 13 satır (1 process + 4 machine + 8 slot)', rows == 13, f'rows={rows}')

            # H2: ENJEKSİYON open
            enj_open = task_open(page, 'proc-ENJ')
            check('H2 ENJEKSİYON default open', enj_open is True, f'$open={enj_open}')

            # H3: MAKİNE 1..4 default open
            for mk in ['M1', 'M2', 'M3', 'M4']:
                mak_id = f'mak-{mk}'
                mak_open = task_open(page, mak_id)
                check(f'H3 {mak_id} default open', mak_open is True, f'$open={mak_open}')

            # H4: MAKİNE 1 collapse → 2 satır gizlenir
            visible_before = count_visible_rows(page)
            click_tree_toggle(page, 'mak-M1')
            visible_after = count_visible_rows(page)
            check('H4 MAKİNE 1 collapse A/B gizler (2 row azalır)',
                  visible_after == visible_before - 2,
                  f'before={visible_before} after={visible_after}')

            # H5: MAKİNE 1 re-open
            click_tree_toggle(page, 'mak-M1')
            visible_reopen = count_visible_rows(page)
            check('H5 MAKİNE 1 re-open A/B geri gelir',
                  visible_reopen == visible_before,
                  f'before={visible_before} reopen={visible_reopen}')

            # H6: ENJEKSİYON collapse
            click_tree_toggle(page, 'proc-ENJ')
            visible_enj_closed = count_visible_rows(page)
            check('H6 ENJEKSİYON collapse tüm subtree gizler',
                  visible_enj_closed == 1,
                  f'visible={visible_enj_closed}')
            # Re-open for subsequent tests
            click_tree_toggle(page, 'proc-ENJ')
            page.wait_for_timeout(600)

            # H7: 33917 M1-A slot task'ında (task.id == 'M1-A')
            pt = find_plan_task(page)
            check('H7 33917 planı gantt\'ta bulunuyor', pt is not None, str(pt))
            if pt:
                check('H7 33917 slot task id = M1-A', pt.get('id') == 'M1-A', f'task={pt}')

            # H8+H9: drag M1-A → M2-A
            drag_res = page.evaluate('''() => {
                try {
                    var r = window.__apsDragAndStage("M1-A", "M2-A");
                    return { ok: true, r: r };
                } catch(e) { return { ok: false, e: String(e) }; }
            }''')
            check('H8 __apsDragAndStage M1-A→M2-A ok', drag_res.get('ok'), str(drag_res))
            page.wait_for_timeout(500)

            pt_after = find_plan_task(page)
            check('H8 drag sonrası 33917 slot id = M2-A',
                  pt_after and pt_after.get('id') == 'M2-A',
                  str(pt_after))

            if pt_after:
                bw = task_bar_width(page, pt_after['id'])
                check('H9 1px bug yok (bar_width > 20px)', bw > 20, f'bar_width={bw:.1f}px')
            else:
                check('H9 1px bug yok', False, 'task id not found after drag')

            # H10: DISCARD → M1-A'ya geri döner
            page.evaluate('() => window.__apsDiscardStaging && window.__apsDiscardStaging()')
            page.wait_for_timeout(700)
            plans_m1a = page.evaluate("() => window.__apsPlansOnResource('M1-A')")
            check('H10 DISCARD → plan-199 M1-A\'ya geri döndü',
                  'plan-199' in (plans_m1a or []),
                  f'M1-A plans={plans_m1a}')

            # H11: zoom round-trip
            zoom_ok = page.evaluate('''() => {
                try {
                    window.__apsApplyZoom("1w");
                    window.__apsApplyZoom("2m");
                    window.__apsApplyZoom("1h");
                    var t = null;
                    gantt.eachTask(function(x) {
                        if (x.aps_plan && Number(x.aps_plan.sip_no) === 33917) t = x;
                    });
                    return t !== null;
                } catch(e) { return false; }
            }''')
            check('H11 zoom round-trip 1h→1w→2m→1h (33917 visible)', zoom_ok)

            # --- UX: Indent checks ---
            # UX1a: ENJEKSİYON $level == 0
            enj_level = page.evaluate('() => { var t=gantt.getTask("proc-ENJ"); return t ? t.$level : -1; }')
            check('UX1a ENJEKSİYON level = 0', enj_level == 0, f'level={enj_level}')

            # UX1b: MAKİNE 1 $level == 1
            mak_level = page.evaluate('() => { var t=gantt.getTask("mak-M1"); return t ? t.$level : -1; }')
            check('UX1b MAKİNE 1 level = 1', mak_level == 1, f'level={mak_level}')

            # UX1c: M1-A $level == 2
            slot_level = page.evaluate('() => { var t=gantt.getTask("M1-A"); return t ? t.$level : -1; }')
            check('UX1c M1-A (slot) level = 2', slot_level == 2, f'level={slot_level}')

            # UX1d: Machine row has deeper indent than process row in DOM
            indent_ok = page.evaluate('''() => {
                var enjRow  = document.querySelector('.gantt_row[task_id="proc-ENJ"]');
                var makRow  = document.querySelector('.gantt_row[task_id="mak-M1"]');
                var slotRow = document.querySelector('.gantt_row[task_id="M1-A"]');
                if (!enjRow || !makRow || !slotRow) return {ok:false, reason:"rows not found"};
                function indentWidth(row) {
                    var spans = row.querySelectorAll(".gantt_tree_indent");
                    var total = 0;
                    spans.forEach(function(s) { total += s.offsetWidth; });
                    return total;
                }
                var eW = indentWidth(enjRow);
                var mW = indentWidth(makRow);
                var sW = indentWidth(slotRow);
                return {ok: mW > eW && sW > mW, e:eW, m:mW, s:sW};
            }''')
            check('UX1d indent: ENJ < MAKİNE < SLOT (DHTMLX tree indent)',
                  indent_ok.get('ok'),
                  str(indent_ok))

            # --- UX: Tooltip / no-drawer ---
            # UX2a: tooltip_text for plan task returns non-empty HTML
            tip_html = page.evaluate('''() => {
                var t = gantt.getTask("M1-A");
                if (!t || !t.aps_plan) return "";
                return gantt.templates.tooltip_text(t.start_date, t.end_date, t);
            }''')
            check('UX2a tooltip_text non-empty for M1-A plan', bool(tip_html and len(tip_html) > 20),
                  f'len={len(tip_html) if tip_html else 0}')

            # UX2b: tooltip HTML contains sipariş number
            check('UX2b tooltip contains sip_no 33917',
                  tip_html and '33917' in tip_html, f'tip={tip_html[:80] if tip_html else ""}')

            # UX2c: tooltip contains key sections
            check('UX2c tooltip contains ENJEKSİYON section',
                  tip_html and 'ENJEKSİYON' in tip_html, '')
            check('UX2d tooltip contains PLAN ZAMANI section',
                  tip_html and 'PLAN ZAMANI' in tip_html, '')

            # UX2e: clicking plan bar does NOT open drawer
            # Simulate click by dispatching onTaskClick; drawer should remain closed
            page.evaluate('() => { if(gantt.callEvent) gantt.callEvent("onTaskClick", ["M1-A", {}]); }')
            page.wait_for_timeout(300)
            drawer_open = page.evaluate('''() => {
                var d = document.getElementById("apsPlanDrawer");
                return d ? d.classList.contains("open") : false;
            }''')
            check('UX2e click plan → drawer stays closed', not drawer_open, f'drawer_open={drawer_open}')

            # --- UX drag after tooltip check ---
            # UX3: drag still works after UX changes (re-run H8)
            drag_res2 = page.evaluate('''() => {
                try {
                    var r = window.__apsDragAndStage("M1-A", "M2-A");
                    return { ok: true, r: r };
                } catch(e) { return { ok: false, e: String(e) }; }
            }''')
            check('UX3 drag still works after tooltip/click changes', drag_res2.get('ok'), str(drag_res2))
            page.wait_for_timeout(400)
            # Discard after UX3 drag
            page.evaluate('() => window.__apsDiscardStaging && window.__apsDiscardStaging()')
            page.wait_for_timeout(500)
            plans_m1a_ux3 = page.evaluate("() => window.__apsPlansOnResource('M1-A')")
            check('UX3 DISCARD after UX3 drag → M1-A ok',
                  'plan-199' in (plans_m1a_ux3 or []), f'{plans_m1a_ux3}')

            # H13: no write calls
            check('H13 DB WRITE == 0', len(write_calls) == 0, str(write_calls))

            browser.close()

    # H12: DB SHA
    sha_after = sha256_file(str(CANONICAL))
    check('H12 DB SHA unchanged', sha_before == sha_after,
          f'before={sha_before[:16]} after={sha_after[:16]}')

    print()
    print(f'PASSED: {len(passed)}  FAILED: {len(failed)}')
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
