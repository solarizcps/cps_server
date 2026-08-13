# -*- coding: utf-8 -*-
"""P0 — Ferhat Solariz Enjeksiyon home restore — regression lock v2 (A–L).

CONTRACT v2 (13.08.2026):
  Ferhat landing        = /enjeksiyon/
  GENEL Görevler        = VISIBLE  (tasks yetkisi varsa)
  SAHA Enjeksiyon       = VISIBLE
  SAHA Gelen İşler      = VISIBLE  (saha.ferhat_islem yetkisi varsa)
  GENEL Özet            = HIDDEN   (enjeksiyon_home_user ise gizli)
  /nexgen/tablet/ferhat = login landing DEĞİL
  Standard header       = KORUNUYOR
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import sqlite3
import sys

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)
os.chdir(_APP)

import tools.test_db_guard  # noqa: E402
from tools.nexgen_tmp_db import tmp_db_context  # noqa: E402

results: list[tuple[str, bool, str]] = []


def ok(name: str, cond: bool, detail: str = '') -> bool:
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))
    return bool(cond)


def _nav(html: str) -> str:
    html = re.sub(r'<!--.*?-->', '', html, flags=re.S)
    m = re.search(r'<nav[^>]*id="sidebar"[^>]*>(.*?)</nav>', html, re.S | re.I)
    return m.group(1) if m else html


def _db_user(con: sqlite3.Connection, kadi: str) -> dict:
    row = con.execute(
        """
        SELECT k.Id, k.KullaniciAdi, k.RolId, k.AuthVersion, k.ZorunluSifreDegistir,
               k.Aktif, k.Sifre, r.Ad AS RolAd
          FROM sistem_kullanici k
          JOIN sistem_rol r ON r.Id = k.RolId
         WHERE lower(k.KullaniciAdi) = lower(?)
        """,
        (kadi,),
    ).fetchone()
    if not row:
        raise RuntimeError(f'user not found: {kadi}')
    return dict(row)


def run_suite(info: dict) -> None:
    tmp_db = info['tmp_db']
    pre_sha = hashlib.sha256(open(tmp_db, 'rb').read()).hexdigest()
    print(f'TMP_DB={tmp_db}')
    print(f'PRE_SHA={pre_sha}')

    AUTH = open(os.path.join(_APP, 'modules', 'auth.py'), encoding='utf-8').read()
    BASE = open(os.path.join(_APP, 'templates', 'base.html'), encoding='utf-8').read()

    ok('L no username ferhat redirect', "lower() == 'ferhat'" not in AUTH)
    ok('L no uid hard-code', not re.search(r"['\"]Id['\"]\s*:\s*38", AUTH))
    ok('A auth Enjeksiyon redirect', "_rol_ad == 'Enjeksiyon'" in AUTH and "nxt = '/enjeksiyon/'" in AUTH)
    ok('B nav Enjeksiyon link', '/enjeksiyon/' in BASE and 'ENJEKSIYON_SAHA_MENU_V5' in BASE)
    # ENJ_SIDEBAR_COLLAPSED_V1 contract
    ok('M sidebar enj collapsed flag', '__cpsEnjHome' in BASE and 'enjeksiyon_home_user' in BASE)
    ok('M sidebar collapsed init', 'if (window.__cpsEnjHome)' in BASE and 'saveExpanded(false)' in BASE)
    ok('M sidebar no uid hardcode', "ferhat" not in BASE.split('ENJ_SIDEBAR_COLLAPSED_V1')[1].split('</script>')[0] if 'ENJ_SIDEBAR_COLLAPSED_V1' in BASE else True)
    # HEADER_SPACER_V2 contract — dynNavTabs her zaman render edilir (flex:1 spacer)
    ok('N header spacer always rendered', 'HEADER_SPACER_V2' in BASE)
    ok('N header no enj role check in nav-tabs', "RolAd != 'Enjeksiyon'" not in BASE.split('HEADER_SPACER_V2')[1].split('dynNavTabs')[0] if 'HEADER_SPACER_V2' in BASE else True)
    ok('N tab js enj skip', 'ENJ_TAB_SKIP_V1' in BASE and 'window.__cpsEnjHome' in BASE)
    # v2: Gelen İşler artık yetki('saha.ferhat_islem') ile gösteriliyor, enjeksiyon_home_user engeli YOK
    ok('C nav Gelen Isler permission based', 'saha.ferhat_islem' in BASE and ("not enjeksiyon_home_user" not in BASE.split('ENJEKSIYON_SAHA_MENU_V5')[1] if 'ENJEKSIYON_SAHA_MENU_V5' in BASE else True))
    # v2: Özet enjeksiyon_home_user için gizli; GENEL grubunun kendisi gizlenmiyor
    ok('D nav Ozet enjeksiyon gizli', 'not enjeksiyon_home_user' in BASE and '_genel_goster' in BASE)

    import config as _cfg
    _cfg.Config.MOCK_DB_PATH = tmp_db
    import app as flask_app
    from modules.enjeksiyon.home_yetki import is_enjeksiyon_home_user, enjeksiyon_home_redirect
    from modules.auth import is_nexgen_uretim_operator, kullanici_yetkileri

    _app = flask_app.app
    _app.config['TESTING'] = True
    client = _app.test_client()
    con = sqlite3.connect(tmp_db)
    con.row_factory = sqlite3.Row

    def set_db_user(kadi: str) -> dict:
        u = _db_user(con, kadi)
        with client.session_transaction() as s:
            s['kullanici'] = {
                'Id': u['Id'],
                'KullaniciAdi': u['KullaniciAdi'],
                'Tip': 'sistem',
                'RolId': u['RolId'],
                'RolAd': u['RolAd'],
                'Aktif': u['Aktif'],
                'AuthVersion': u['AuthVersion'],
                'ZorunluSifreDegistir': u['ZorunluSifreDegistir'] or 0,
            }
            s['kullanici_tip'] = 'sistem'
        return u

    ferhat = _db_user(con, 'ferhat')
    yk_enj = kullanici_yetkileri({'RolId': ferhat['RolId']})
    u_enj = {'RolAd': ferhat['RolAd'], 'RolId': ferhat['RolId'], 'KullaniciAdi': ferhat['KullaniciAdi']}
    ok('home helper enj', is_enjeksiyon_home_user(u_enj, yk_enj))
    ok('home redirect enj', enjeksiyon_home_redirect(u_enj, yk_enj) == '/enjeksiyon/')
    ok('home helper planlama degil', not is_enjeksiyon_home_user(
        {'RolAd': 'Planlama', 'RolId': 32}, {'planlama:can_view', 'enjeksiyon:can_view'}
    ))

    r_login = client.post(
        '/giris',
        data={'kullanici': ferhat['KullaniciAdi'], 'sifre': ferhat['Sifre']},
        follow_redirects=False,
    )
    loc_login = (r_login.headers.get('Location') or '')
    ok('A ferhat login enjeksiyon', r_login.status_code in (302, 303) and '/enjeksiyon/' in loc_login, loc_login)

    set_db_user('ferhat')
    r_idx = client.get('/', follow_redirects=False)
    loc_idx = (r_idx.headers.get('Location') or '')
    ok('A index redirect enjeksiyon', r_idx.status_code in (302, 303) and '/enjeksiyon/' in loc_idx, loc_idx)

    set_db_user('ferhat')
    r_nav = client.get('/enjeksiyon/', follow_redirects=False)
    nav = _nav(r_nav.get_data(as_text=True))
    ok('A enjeksiyon page reachable', r_nav.status_code == 200, str(r_nav.status_code))
    ok('B nav Enjeksiyon VAR', 'Enjeksiyon' in nav and '/enjeksiyon/' in nav)
    # v2: Gelen İşler VISIBLE (saha.ferhat_islem yetkisi var ise)
    has_ferhat_islem = 'saha.ferhat_islem' in str(kullanici_yetkileri({'RolId': ferhat['RolId']}))
    if has_ferhat_islem:
        ok('C nav Gelen Isler VAR', 'Gelen' in nav and '/saha/numune-talep' in nav)
    else:
        ok('C nav Gelen Isler (no perm skip)', True, 'saha.ferhat_islem yetkisi yok - skip')
    # v2: Görevler VISIBLE (tasks yetkisi var ise)
    has_tasks = 'tasks' in str(yk_enj) or 'tasks:can_view' in str(yk_enj)
    if has_tasks:
        ok('D nav Gorevler VAR', 'G&#246;revler' in nav or 'Görevler' in nav or '/tasks' in nav)
    else:
        ok('D nav Gorevler (no perm skip)', True, 'tasks yetkisi yok - skip')
    # v2: Özet HIDDEN (enjeksiyon_home_user için)
    ok('E nav Ozet YOK', 'title="Özet"' not in nav)

    set_db_user('ferhat')
    r_tf = client.get('/nexgen/tablet/ferhat', follow_redirects=False)
    ok('F tablet ferhat route exists', r_tf.status_code == 200, str(r_tf.status_code))
    ok('F login not tablet ferhat', '/nexgen/tablet/ferhat' not in loc_login, loc_login)

    ali = _db_user(con, 'ali')
    con.execute(
        "UPDATE sistem_kullanici SET ZorunluSifreDegistir=0 WHERE Id=?",
        (ali['Id'],),
    )
    con.commit()
    ali['ZorunluSifreDegistir'] = 0
    set_db_user('ali')
    r_ali_tab = client.get('/nexgen/tablet', follow_redirects=False)
    ok('H ali tablet 200', r_ali_tab.status_code == 200, str(r_ali_tab.status_code))
    ok('G ali is uretim op', is_nexgen_uretim_operator({'RolAd': ali['RolAd'], 'RolId': ali['RolId']}))

    r_ali_login = client.post(
        '/giris',
        data={'kullanici': ali['KullaniciAdi'], 'sifre': ali['Sifre']},
        follow_redirects=False,
    )
    loc_ali = (r_ali_login.headers.get('Location') or '')
    ok('G ali login tablet', r_ali_login.status_code in (302, 303) and (
        loc_ali.rstrip('/').endswith('/nexgen/tablet') or 'sifre-degistir' in loc_ali
    ), loc_ali)

    set_db_user('admin')
    r_admin = client.get('/enjeksiyon/', follow_redirects=False)
    admin_nav = _nav(r_admin.get_data(as_text=True))
    ok('J admin Genel VAR', 'Genel' in admin_nav or 'Özet' in admin_nav, str(r_admin.status_code))

    mehmet = _db_user(con, 'mehmet')
    yk_m = kullanici_yetkileri({'RolId': mehmet['RolId']})
    ok('K mehmet not enj home', not is_enjeksiyon_home_user(
        {'RolAd': mehmet['RolAd'], 'RolId': mehmet['RolId']}, yk_m
    ))
    set_db_user('mehmet')
    r_m = client.get('/planlama/proses-takip', follow_redirects=False)
    ok('K mehmet planlama erisim', r_m.status_code == 200, str(r_m.status_code))

    routes_src = open(os.path.join(_APP, 'modules', 'nexgen', 'routes.py'), encoding='utf-8').read()
    ok('I tablet_ferhat route exists', 'def tablet_ferhat' in routes_src)
    ok('I tua batch query exists', '_tua_tablet_is_liste_sorgu' in routes_src)

    con.close()
    ok('DB canonical unchanged', not info.get('main_db_changed'), str(info.get('sha_before', ''))[:16])


print('=' * 72)
print('ENJEKSIYON HOME RESTORE LOCK')
print('=' * 72)

with tmp_db_context() as info:
    run_suite(info)

fail = [n for n, c, _ in results if not c]
print('=' * 72)
print(f'RESULT: {len(results) - len(fail)}/{len(results)} PASS')
if fail:
    print('FAIL:', ', '.join(fail))
print('=' * 72)
sys.exit(0 if not fail else 1)
