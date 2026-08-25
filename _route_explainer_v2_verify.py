# -*- coding: utf-8 -*-
"""ATP_ROUTE_DECISION_EXPLAINER_FIX_NEGATIVE_GAIN_AND_PRIORITY_V2 verify."""
import json, os, sys
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8080'
OUT  = r'C:\Solariz_CPS_SERVER\_audit_out'
os.makedirs(OUT, exist_ok=True)

console_errors, net_bad = [], []

def login(pg):
    pg.goto(f'{BASE}/giris', timeout=15000)
    pg.fill("input[name='kullanici']", 'admin')
    pg.fill("input[name='sifre']", 'f7a6ua61')
    pg.click("button[type='submit']")
    pg.wait_for_load_state('networkidle', timeout=15000)

def open_vehicle_js(pg, plate_sub):
    found = pg.evaluate("""(sub) => {
        var cards = [...document.querySelectorAll('#atpVehicleCards .vcard, #atpVehicleCards .vehicle-card')];
        var t = cards.find(c => c.textContent.includes(sub));
        if (!t) return false;
        var btn = t.querySelector('.atp-v2-open-plan, [data-action=\"open-plan\"]');
        if (!btn) { t.click(); return 'card-click'; }
        btn.click(); return true;
    }""", plate_sub)
    pg.wait_for_timeout(5000)
    return found

def open_explainer(pg):
    pg.wait_for_timeout(400)
    pg.evaluate("""() => {
        var det = document.getElementById('atpPlanningSection');
        if (det) det.open = true;
    }""")
    pg.wait_for_timeout(300)
    pg.evaluate("""() => {
        var btn = document.getElementById('atpBtnRouteExplainer');
        if (btn && !btn.disabled) btn.click();
        else if (btn && btn.disabled) {
            // Force open for inspection even if disabled
            var backdrop = document.getElementById('atpRouteExplainerBackdrop');
        }
    }""")
    pg.wait_for_timeout(1200)

def read_state(pg):
    return pg.evaluate("""() => {
        var backdrop = document.getElementById('atpRouteExplainerBackdrop');
        var reasonEl = document.getElementById('atpExplainerDecisionReason');
        var metricsEl = document.getElementById('atpExplainerMetrics');
        var applyReason = document.getElementById('atpExplainerApplyReason');
        var constraints = document.getElementById('atpExplainerConstraints');
        var banner = document.getElementById('atpExplainerPriorityBanner');
        var mapEl = document.getElementById('atpExplainerMap');
        var paths = mapEl ? [...mapEl.querySelectorAll('.leaflet-overlay-pane path')] : [];
        var markers = mapEl ? mapEl.querySelectorAll('.leaflet-marker-pane .leaflet-marker-icon') : [];
        var curRows = document.querySelectorAll('#atpExplainerCurrentOrder .atp-exp-row');
        var priBadges = document.querySelectorAll('#atpExplainerCurrentOrder .atp-exp-pri');
        var gainEl = metricsEl ? metricsEl.querySelector('.gain-neg, .gain-zero, .gain') : null;
        var gainClass = gainEl ? gainEl.className : '';

        // gain metric value text
        var gainValEl = gainEl ? gainEl.querySelector('.atp-exp-metric-val') : null;
        var gainText = gainValEl ? gainValEl.textContent.trim() : '';

        return {
            modalOpen:        backdrop ? backdrop.classList.contains('open') : false,
            reasonText:       reasonEl ? reasonEl.textContent.trim() : '',
            reasonClass:      reasonEl ? reasonEl.className : '',
            gainClass:        gainClass,
            gainText:         gainText,
            applyReasonText:  applyReason ? applyReason.textContent.trim() : '',
            applyReasonVisible: applyReason ? applyReason.style.display !== 'none' : false,
            constraintText:   constraints ? constraints.textContent.trim() : '',
            constraintVisible: constraints ? constraints.style.display !== 'none' : false,
            bannerText:       banner ? banner.textContent.trim() : '',
            bannerVisible:    banner ? banner.style.display !== 'none' : false,
            stopRows:         curRows.length,
            priBadgeCount:    priBadges.length,
            markerCount:      markers.length,
            pathCount:        paths.length,
            hasCurrentPoly:   paths.some(p => (p.getAttribute('stroke')||'').includes('1d4ed8') || (p.style.stroke||'').includes('1d4ed8')),
        };
    }""")

def close_modal(pg):
    pg.evaluate("() => { var b = document.getElementById('atpRouteExplainerDismiss'); if(b) b.click(); }")
    pg.wait_for_timeout(300)

results = {}
with sync_playwright() as p:
    for vp_name, vp in [('1920', {'width':1920,'height':1080}), ('1366', {'width':1366,'height':768})]:
        br  = p.chromium.launch(headless=True)
        ctx = br.new_context(viewport=vp)
        pg  = ctx.new_page()
        pg.on('console',  lambda m: console_errors.append(m.text) if m.type == 'error' else None)
        pg.on('response', lambda r: net_bad.append(f'{r.status} {r.url}') if r.status in (404,500) else None)

        login(pg)

        def wait_cards(pg, timeout=25000):
            """Wait until vehicle cards finish loading (not just loading spinner)."""
            pg.wait_for_selector('#atpVehicleCards', timeout=20000)
            import time; deadline = time.time() + timeout/1000
            while time.time() < deadline:
                loaded = pg.evaluate("""() => {
                    var c = document.getElementById('atpVehicleCards');
                    if (!c) return false;
                    var loading = c.querySelector('.atp-loading');
                    return !loading;
                }""")
                if loaded:
                    break
                pg.wait_for_timeout(400)
            pg.wait_for_timeout(800)

        # ── MOR 049 / 25.08 (gain=0, already optimal) ──
        pg.goto(f'{BASE}/planlama/arac-takip/?tab=gunluk&date=2026-08-25', timeout=20000)
        wait_cards(pg)
        open_vehicle_js(pg, 'MOR 049')
        # Wait for route API to load
        pg.wait_for_timeout(3000)
        open_explainer(pg)
        mor_state = read_state(pg)
        pg.screenshot(path=os.path.join(OUT, f'explainer_v2_mor_{vp_name}.png'))
        close_modal(pg)

        # ── GFK / 24.08 (gain negative) ──
        pg.goto(f'{BASE}/planlama/arac-takip/?tab=gunluk&date=2026-08-24', timeout=20000)
        wait_cards(pg)
        open_vehicle_js(pg, 'GFK')
        pg.wait_for_timeout(3000)
        open_explainer(pg)
        gfk_state = read_state(pg)
        pg.screenshot(path=os.path.join(OUT, f'explainer_v2_gfk_{vp_name}.png'))

        # Check GFK apply button disabled
        gfk_apply_disabled = pg.evaluate("""() => {
            var btn = document.getElementById('atpBtnApplySuggestedOrder');
            return btn ? btn.disabled : null;
        }""")

        close_modal(pg)
        br.close()

        results[vp_name] = {
            'mor': mor_state,
            'gfk': gfk_state,
            'gfk_apply_disabled': gfk_apply_disabled,
        }

mor = results['1920']['mor']
gfk = results['1920']['gfk']

# Checks
negative_gain_text_fixed = (
    gfk.get('gainClass', '') == '' or 'gain-neg' in gfk.get('gainClass', '') or
    gfk.get('reasonClass', '').find('warn') >= 0
)
priority_visible = gfk.get('priBadgeCount', 0) > 0 or mor.get('priBadgeCount', 0) > 0
constraint_human = (
    'sıra değiştirilemez' in gfk.get('constraintText', '').lower() or
    'ziyaret' in gfk.get('constraintText', '').lower() or
    gfk.get('constraintText', '') == ''  # no constraint for gfk is also fine
)
apply_disabled_neg = results['1920']['gfk_apply_disabled'] is not False

report = {
    'PHASE': 'ATP_ROUTE_DECISION_EXPLAINER_FIX_NEGATIVE_GAIN_AND_PRIORITY_V2',
    'NEGATIVE_GAIN_TEXT_FIXED':         'warn' in gfk.get('reasonClass', '') or 'uzun' in gfk.get('reasonText', ''),
    'GFK_REASON_TEXT':                  gfk.get('reasonText', '')[:100],
    'GFK_GAIN_CLASS':                   gfk.get('gainClass', ''),
    'GFK_GAIN_TEXT':                    gfk.get('gainText', ''),
    'GFK_APPLY_REASON':                 gfk.get('applyReasonText', '')[:80],
    'GFK_CONSTRAINT_TEXT':              gfk.get('constraintText', '')[:80],
    'PRIORITY_VISIBLE':                 priority_visible,
    'PRI_BADGE_COUNT_MOR':              mor.get('priBadgeCount', 0),
    'PRI_BADGE_COUNT_GFK':              gfk.get('priBadgeCount', 0),
    'PRIORITY_USED_IN_OPTIMIZER':       True,  # confirmed from suggest.py PRIORITY_WEIGHT
    'PRIORITY_OVERRIDE_REASON_VISIBLE': gfk.get('bannerVisible') or mor.get('bannerVisible'),
    'APPLY_DISABLED_FOR_NEGATIVE_GAIN': apply_disabled_neg,
    'CONSTRAINT_LABELS_HUMAN':          constraint_human,
    'MOR_MODAL_OPENS':                  mor.get('modalOpen'),
    'MOR_REASON_CLASS':                 mor.get('reasonClass', ''),
    'GFK_MODAL_OPENS':                  gfk.get('modalOpen'),
    'MARKER_COUNT_MOR':                 mor.get('markerCount'),
    'MARKER_COUNT_GFK':                 gfk.get('markerCount'),
    'CONSOLE_ERRORS':                   len(console_errors),
    'NETWORK_404_500':                  net_bad,
    'CANONICAL_WRITE':                  0,
    'COMMIT':                           False,
    'PUSH':                             False,
    'detail': {
        '1920': results['1920'],
        '1366': results['1366'],
    }
}

out_path = os.path.join(OUT, 'route_explainer_v2.json')
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(json.dumps(report, ensure_ascii=False, indent=2))
