# -*- coding: utf-8 -*-
"""NEXGEN FAZ-5C-4 — üretim tüketiminde rezerv kapatma testi."""
import sys, io, os, sqlite3, subprocess, importlib.util, shutil

if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP_DIR)
os.chdir(_APP_DIR)
DB = os.path.join(_APP_DIR, 'mock_data.db')
_REG_BAK = os.path.join(_APP_DIR, 'mock_data.db.bak_faz5c4_20260624')
if not os.path.exists(_REG_BAK):
    _REG_BAK = os.path.join(_APP_DIR, 'mock_data.db.bak_faz5c3_20260624')

for _mig in ('085_nexgen_depo_hazirlik.py', '086_nexgen_stok_rezerv.py'):
    _p = os.path.join(_APP_DIR, 'migrations', _mig)
    _spec = importlib.util.spec_from_file_location(_mig, _p)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    _mod.run()
    if _mig.startswith('086'):
        _m086 = _mod

import app as flask_app
from modules.nexgen.routes import (
    _mevcut_stok, _aktif_rezerv_toplam, _kullanilabilir_stok,
    _mpr_stok_ihtiyac_hesapla, _parca_stok_net_tuketim,
    _batch_plan_rf_bilgi,
)

_app = flask_app.app
_app.config['TESTING'] = True
results = []


def ok(name, cond, detail=''):
    results.append((name, cond, detail))
    print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))


def sess_user():
    return {'Id': 1, 'KullaniciAdi': 'admin', 'Tip': 'sistem',
            'RolId': 1, 'RolAd': 'admin', 'Aktif': 1}


def parca_bitir(c, batch_kodu, parca_id):
    return c.post(f'/nexgen/api/batch/{batch_kodu}/parca/{parca_id}/bitir', json={})


def parca_geri_al(c, batch_kodu, parca_id, gerekce='FAZ5C4 test'):
    return c.post(
        f'/nexgen/api/batch/{batch_kodu}/parca/{parca_id}/geri-al',
        json={'gerekce': gerekce},
    )


def batch_rezerv_toplam(con, batch_kodu, stok_kart_id=None):
    q = """
        SELECT COALESCE(SUM(kalan_kg), 0) AS t,
               COALESCE(SUM(CASE WHEN durum='AKTIF' THEN kalan_kg ELSE 0 END), 0) AS aktif
        FROM nexgen_stok_rezerv WHERE batch_kodu=?
    """
    params = [batch_kodu]
    if stok_kart_id:
        q += " AND stok_kart_id=?"
        params.append(stok_kart_id)
    row = con.execute(q, params).fetchone()
    return round(float(row['aktif'] or 0), 3), round(float(row['t'] or 0), 3)


def parca_tuketim_talep(con, aday, hedef_kg=None):
    hk = hedef_kg if hedef_kg is not None else float(aday['hedef_kg'])
    rf_renk_id = aday.get('rf_renk_id')
    if not rf_renk_id:
        rf_bilgi = _batch_plan_rf_bilgi(
            con,
            batch_kodu=aday['batch_kodu'],
            plan_id=aday.get('plan_id'),
            uretim_varyant_id=aday['uretim_varyant_id'],
        )
        if rf_bilgi:
            rf_renk_id = rf_bilgi.get('rf_renk_id')
    chk = _mpr_stok_ihtiyac_hesapla(
        con, aday['uretim_varyant_id'], rf_renk_id, hk,
        exclude_batch_kodu=aday['batch_kodu'],
    )
    if not chk.get('ok'):
        return None
    talep = {}
    for k in chk.get('kalemler', []):
        sid = k['stok_kart_id']
        talep[sid] = round(talep.get(sid, 0) + float(k['gerekli_kg']), 3)
    return talep


def stok_yeterli_kil(con, aday, buffer=5.0):
    talep = parca_tuketim_talep(con, aday)
    if not talep:
        return False
    bk = aday['batch_kodu']
    for sid, miktar in talep.items():
        hedef = round(miktar + buffer, 3)
        kul = _kullanilabilir_stok(con, sid, exclude_batch_kodu=bk)
        if kul < hedef - 0.0005:
            onceki = _mevcut_stok(con, sid)
            eksik = round(hedef - kul, 3)
            con.execute("""
                INSERT INTO nexgen_stok_hareket
                  (stok_kart_id, hareket_tipi, miktar_kg, onceki_stok, sonraki_stok,
                   aciklama, olusturma_tarihi)
                VALUES (?, 'GIRIS', ?, ?, ?, 'FAZ5C4 test seed', datetime('now'))
            """, (sid, eksik, onceki, round(onceki + eksik, 3)))
    con.commit()
    chk = _mpr_stok_ihtiyac_hesapla(
        con, aday['uretim_varyant_id'], aday['rf_renk_id'],
        float(aday['hedef_kg']), exclude_batch_kodu=bk,
    )
    return bool(chk.get('ok') and chk.get('yeterli_mi'))


def manuel_rezerv_olustur(con, batch_kodu, talep):
    """Test batch için doğrudan AKTIF rezerv satırları (depo HAZIR simülasyonu)."""
    con.execute("DELETE FROM nexgen_stok_rezerv WHERE batch_kodu=?", (batch_kodu,))
    for sid, miktar in talep.items():
        if miktar <= 0:
            continue
        rez_mik = round(miktar * 5, 3)
        con.execute("""
            INSERT INTO nexgen_stok_rezerv
              (rezerv_no, stok_kart_id, kaynak_tip, kaynak_id, batch_kodu,
               miktar_kg, kalan_kg, durum, olusturan_id)
            VALUES (?, ?, 'DEPO_HAZIRLIK', 1, ?, ?, ?, 'AKTIF', 1)
        """, (f'RZ-TEST-5C4-{batch_kodu}-{sid}', sid, batch_kodu, rez_mik, rez_mik))
    con.commit()


# Temiz snapshot
if os.path.exists(_REG_BAK):
    shutil.copy2(_REG_BAK, DB)
    _m086.run()

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

# ── Aday: rezervli + bitirilebilir parça ──
rezervli = None
for aday in con.execute("""
    SELECT p.id AS parca_id, p.batch_kodu, p.hedef_kg, p.durum,
           p.plan_id, b.uretim_varyant_id, pl.rf_renk_id
    FROM nexgen_uretim_parca p
    JOIN nexgen_uretim_batch b ON b.batch_kodu = p.batch_kodu
    LEFT JOIN nexgen_uretim_plan pl ON pl.id = COALESCE(p.plan_id, b.plan_id)
    WHERE p.durum IN ('DEVAM', 'HAZIR')
      AND EXISTS (
        SELECT 1 FROM nexgen_stok_rezerv r
        WHERE r.batch_kodu = p.batch_kodu AND r.durum = 'AKTIF'
      )
    ORDER BY p.id
""").fetchall():
    ad = dict(aday)
    if stok_yeterli_kil(con, ad):
        talep = parca_tuketim_talep(con, ad)
        if talep:
            yeterli_rez = all(
                batch_rezerv_toplam(con, ad['batch_kodu'], sid)[0] >= mik - 0.0005
                for sid, mik in talep.items()
            )
            if yeterli_rez:
                rezervli = ad
                break

if not rezervli:
    aday = con.execute("""
        SELECT p.id AS parca_id, p.batch_kodu, p.hedef_kg, p.durum,
               p.plan_id, b.uretim_varyant_id, pl.rf_renk_id
        FROM nexgen_uretim_parca p
        JOIN nexgen_uretim_batch b ON b.batch_kodu = p.batch_kodu
        LEFT JOIN nexgen_uretim_plan pl ON pl.id = COALESCE(p.plan_id, b.plan_id)
        WHERE p.durum IN ('DEVAM', 'HAZIR')
          AND NOT EXISTS (
            SELECT 1 FROM nexgen_stok_hareket h
            WHERE h.referans_tip='URETIM_PARCA' AND h.referans_id=p.id
          )
        ORDER BY p.id LIMIT 1
    """).fetchone()
    if aday:
        ad = dict(aday)
        if stok_yeterli_kil(con, ad):
            talep = parca_tuketim_talep(con, ad)
            if talep:
                manuel_rezerv_olustur(con, ad['batch_kodu'], talep)
                yeterli_rez = all(
                    batch_rezerv_toplam(con, ad['batch_kodu'], sid)[0] >= mik - 0.0005
                    for sid, mik in talep.items()
                )
                ok('seed rezerv olustu', yeterli_rez, str(talep))
                if yeterli_rez:
                    rezervli = ad

ok('1 batch aktif rezerv var', rezervli is not None,
   rezervli['batch_kodu'] if rezervli else '')

with _app.test_client() as c:
    with c.session_transaction() as sess:
        sess['kullanici'] = sess_user()
        sess['kullanici_tip'] = 'sistem'

    if rezervli:
        pid = rezervli['parca_id']
        bk = rezervli['batch_kodu']
        talep = parca_tuketim_talep(con, rezervli)
        ornek_sid = next(iter(talep)) if talep else None
        ornek_mik = talep[ornek_sid] if ornek_sid else 0

        fiz_on = _mevcut_stok(con, ornek_sid)
        rez_on, _ = batch_rezerv_toplam(con, bk, ornek_sid)
        kul_on = _kullanilabilir_stok(con, ornek_sid)
        h_on = con.execute(
            "SELECT COUNT(*) FROM nexgen_stok_hareket "
            "WHERE referans_tip='URETIM_PARCA' AND referans_id=?", (pid,)
        ).fetchone()[0]

        r = parca_bitir(c, bk, pid)
        d = r.get_json() or {}
        ok('2 parca bitir 200', r.status_code == 200 and d.get('ok'),
           f"status={r.status_code} hata={d.get('hata')} durum={d.get('durum')}")

        h_son = con.execute(
            "SELECT COUNT(*) FROM nexgen_stok_hareket "
            "WHERE referans_tip='URETIM_PARCA' AND referans_id=?", (pid,)
        ).fetchone()[0]
        tuketim = con.execute("""
            SELECT COUNT(*) FROM nexgen_stok_hareket
            WHERE referans_tip='URETIM_PARCA' AND referans_id=?
              AND hareket_tipi='URETIM_TUKETIM' AND miktar_kg < 0
        """, (pid,)).fetchone()[0]
        ok('2 URETIM_TUKETIM yazildi', h_son > h_on and tuketim > 0, f'h={h_son} t={tuketim}')

        rez_son, _ = batch_rezerv_toplam(con, bk, ornek_sid)
        ok('2 rezerv kalan azaldi', rez_son < rez_on - ornek_mik + 0.01,
           f'{rez_on}->{rez_son} (-{ornek_mik})')

        fiz_son = _mevcut_stok(con, ornek_sid)
        kul_son = _kullanilabilir_stok(con, ornek_sid)
        ok('9 kullanilabilir dengesi',
           abs((fiz_on - fiz_son) - (rez_on - rez_son)) < 0.02
           and abs(kul_on - kul_son) < 0.02,
           f'fiz {fiz_on}->{fiz_son} rez {rez_on}->{rez_son} kul {kul_on}->{kul_son}')

        # Idempotent — ikinci BITTI
        h2_on = con.execute(
            "SELECT COUNT(*) FROM nexgen_stok_hareket "
            "WHERE referans_tip='URETIM_PARCA' AND referans_id=?", (pid,)
        ).fetchone()[0]
        rez2_on = batch_rezerv_toplam(con, bk, ornek_sid)[0]
        r2 = parca_bitir(c, bk, pid)
        h2_son = con.execute(
            "SELECT COUNT(*) FROM nexgen_stok_hareket "
            "WHERE referans_tip='URETIM_PARCA' AND referans_id=?", (pid,)
        ).fetchone()[0]
        rez2_son = batch_rezerv_toplam(con, bk, ornek_sid)[0]
        ok('6 ikinci bitir stok duplicate yok', h2_son == h2_on, f'{h2_on}->{h2_son}')
        ok('6 ikinci bitir rezerv duplicate yok', abs(rez2_son - rez2_on) < 0.001,
           f'{rez2_on}->{rez2_son}')

        # Geri al
        ga = parca_geri_al(c, bk, pid)
        gd = ga.get_json() or {}
        ok('7 geri al 200', ga.status_code == 200 and gd.get('ok'), gd.get('yeni_durum'))

        iptal = con.execute("""
            SELECT COUNT(*) FROM nexgen_stok_hareket
            WHERE referans_tip='URETIM_PARCA_IPTAL' AND referans_id=?
              AND hareket_tipi='URETIM_TUKETIM_IPTAL'
        """, (pid,)).fetchone()[0]
        rez_ga, _ = batch_rezerv_toplam(con, bk, ornek_sid)
        aktif_durum = con.execute("""
            SELECT COUNT(*) FROM nexgen_stok_rezerv
            WHERE batch_kodu=? AND stok_kart_id=? AND durum='AKTIF'
        """, (bk, ornek_sid)).fetchone()[0]
        ok('7 URETIM_TUKETIM_IPTAL', iptal > 0, str(iptal))
        ok('7 rezerv geri artti', rez_ga > rez2_son + 0.0005, f'{rez2_son}->{rez_ga}')
        ok('7 durum AKTIF', aktif_durum > 0, str(aktif_durum))

        # Geri al → tekrar BITTI
        r3 = parca_bitir(c, bk, pid)
        rez_rb = batch_rezerv_toplam(con, bk, ornek_sid)[0]
        ok('8 geri al sonrasi bitir', r3.status_code == 200, str(r3.status_code))
        ok('8 rezerv tekrar azaldi', rez_rb < rez_ga - 0.0005, f'{rez_ga}->{rez_rb}')

        # Tüm parça bitince TUKETILDI (kalan parçaları bitir)
        acik = con.execute("""
            SELECT id, hedef_kg FROM nexgen_uretim_parca
            WHERE batch_kodu=? AND durum NOT IN ('BITTI')
        """, (bk,)).fetchall()
        for ap in acik:
            if ap['id'] != pid:
                stok_yeterli_kil(con, {**rezervli, 'parca_id': ap['id'], 'hedef_kg': ap['hedef_kg']})
            parca_bitir(c, bk, ap['id'])

        tuketildi = con.execute("""
            SELECT COUNT(*) FROM nexgen_stok_rezerv
            WHERE batch_kodu=? AND durum='AKTIF' AND kalan_kg > 0.001
        """, (bk,)).fetchone()[0]
        tuk_cnt = con.execute("""
            SELECT COUNT(*) FROM nexgen_stok_rezerv
            WHERE batch_kodu=? AND durum='TUKETILDI'
        """, (bk,)).fetchone()[0]
        ok('3 tum parca bitince rezerv TUKETILDI',
           tuketildi == 0 and tuk_cnt > 0, f'aktif={tuketildi} tuk={tuk_cnt}')

    # Rezerv yetersiz senaryo
    yetersiz = con.execute("""
        SELECT p.id AS parca_id, p.batch_kodu, p.hedef_kg, p.durum,
               p.plan_id, b.uretim_varyant_id, pl.rf_renk_id
        FROM nexgen_uretim_parca p
        JOIN nexgen_uretim_batch b ON b.batch_kodu = p.batch_kodu
        LEFT JOIN nexgen_uretim_plan pl ON pl.id = COALESCE(p.plan_id, b.plan_id)
        WHERE p.durum IN ('DEVAM', 'HAZIR')
          AND NOT EXISTS (
            SELECT 1 FROM nexgen_stok_hareket h
            WHERE h.referans_tip='URETIM_PARCA' AND h.referans_id=p.id
          )
        ORDER BY p.id LIMIT 1
    """).fetchone()
    if yetersiz:
        yd = dict(yetersiz)
        stok_yeterli_kil(con, yd)
        talep = parca_tuketim_talep(con, yd)
        if talep:
            sid = next(iter(talep))
            mik = talep[sid]
            # Eski rezerv temizle, küçük rezerv koy
            con.execute("DELETE FROM nexgen_stok_rezerv WHERE batch_kodu=?", (yd['batch_kodu'],))
            con.execute("""
                INSERT INTO nexgen_stok_rezerv
                  (rezerv_no, stok_kart_id, kaynak_tip, kaynak_id, batch_kodu,
                   miktar_kg, kalan_kg, durum, olusturan_id)
                VALUES ('RZ-TEST-5C4-YETERSIZ', ?, 'DEPO_HAZIRLIK', 1, ?,
                        ?, ?, 'AKTIF', 1)
            """, (sid, yd['batch_kodu'], mik * 0.1, mik * 0.1))
            con.commit()
            durum_on = con.execute(
                "SELECT durum FROM nexgen_uretim_parca WHERE id=?", (yd['parca_id'],)
            ).fetchone()[0]
            h_on = con.execute(
                "SELECT COUNT(*) FROM nexgen_stok_hareket "
                "WHERE referans_tip='URETIM_PARCA' AND referans_id=?", (yd['parca_id'],)
            ).fetchone()[0]
            ry = parca_bitir(c, yd['batch_kodu'], yd['parca_id'])
            dy = ry.get_json() or {}
            durum_sn = con.execute(
                "SELECT durum FROM nexgen_uretim_parca WHERE id=?", (yd['parca_id'],)
            ).fetchone()[0]
            h_sn = con.execute(
                "SELECT COUNT(*) FROM nexgen_stok_hareket "
                "WHERE referans_tip='URETIM_PARCA' AND referans_id=?", (yd['parca_id'],)
            ).fetchone()[0]
            ok('4 rezerv yetersiz 400', ry.status_code == 400 and 'yetersiz' in (dy.get('hata') or '').lower(),
               dy.get('hata'))
            ok('4 parca BITTI olmadi', durum_sn == durum_on, durum_sn)
            ok('4 stok hareket yazilmadi', h_sn == h_on, f'{h_on}=={h_sn}')
            con.execute("DELETE FROM nexgen_stok_rezerv WHERE rezerv_no='RZ-TEST-5C4-YETERSIZ'")
            con.commit()

    # Legacy — rezerv yok
    legacy = con.execute("""
        SELECT p.id AS parca_id, p.batch_kodu, p.hedef_kg, p.durum,
               p.plan_id, b.uretim_varyant_id, pl.rf_renk_id
        FROM nexgen_uretim_parca p
        JOIN nexgen_uretim_batch b ON b.batch_kodu = p.batch_kodu
        LEFT JOIN nexgen_uretim_plan pl ON pl.id = COALESCE(p.plan_id, b.plan_id)
        WHERE p.durum IN ('DEVAM', 'HAZIR')
          AND NOT EXISTS (
            SELECT 1 FROM nexgen_stok_rezerv r WHERE r.batch_kodu = p.batch_kodu
          )
          AND NOT EXISTS (
            SELECT 1 FROM nexgen_stok_hareket h
            WHERE h.referans_tip='URETIM_PARCA' AND h.referans_id=p.id
          )
        ORDER BY p.id LIMIT 1
    """).fetchone()
    if legacy:
        ld = dict(legacy)
        stok_yeterli_kil(con, ld)
        rl = parca_bitir(c, ld['batch_kodu'], ld['parca_id'])
        dl = rl.get_json() or {}
        ok('5 legacy rezerv yok bitir', rl.status_code == 200 and dl.get('ok'),
           f'status={rl.status_code} hata={dl.get("hata")} durum={dl.get("durum")}')

# FAZ-5C-3 regresyon — temiz snapshot üzerinde
if os.path.exists(_REG_BAK):
    shutil.copy2(_REG_BAK, DB)
    _m086.run()
r10 = subprocess.run(
    [sys.executable, os.path.join(_ROOT, '_test_faz5c3_kullanilabilir_stok.py')],
    cwd=_APP_DIR, capture_output=True, text=True,
    encoding='utf-8', errors='replace',
)
tail10 = r10.stdout.split('SONUC')[-1].strip() if 'SONUC' in r10.stdout else r10.stderr[:120]
core_ok = all(
    tag in r10.stdout for tag in (
        '[PASS] 1 kullanilabilir formul',
        '[PASS] 2 mpr kalem alanlari',
        '[PASS] 2 mpr yeterlilik kullanilabilir',
        '[PASS] 4 plan basla 400 rezervli',
    )
)
ok('10 faz5c3 kullanilabilir stok', core_ok, tail10 if not core_ok else 'core 4/4 PASS')

con.close()

passed = sum(1 for _, c, _ in results if c)
failed = sum(1 for _, c, _ in results if not c)
print(f'\n=== SONUC: {passed}/{len(results)} PASS, {failed} FAIL ===')
sys.exit(1 if failed else 0)
