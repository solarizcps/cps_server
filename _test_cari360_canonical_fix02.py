# -*- coding: utf-8 -*-
"""
CARI360-CANONICAL-FIX-02 REGRESSION
READ-ONLY — mock_data.db SHA korunur.

CASE 1 — CEK vade: PZM-2026-0221 → gosterilecek_vade_gun=220
CASE 2 — VADELI vade: mevcut VADELI sipariş unchanged
CASE 3 — Sevkiyat lifecycle: HAZIRLANIYOR dahil değil → sevk_kg=3000
CASE 4 — Legacy header price: kalem birim_fiyat=NULL, header=3.15 → anlasma_birim_fiyat expose
CASE 5 — Modern kalem price: birim_fiyat=4 → değişmedi
CASE 6 — Üretim locks: PZM-2026-0221 PLAN=1, BATCH=1, ÜRETİLEN KG=3068.5
"""
import hashlib
import os
import sqlite3
import sys
import json
import unittest.mock as mock

CANONICAL_DB = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app', 'mock_data.db')
)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app'))

from modules.nexgen.cari360_ops_read_service import (
    load_cari360_siparisler,
    load_cari360_ozet,
    load_cari360_uretim,
)
from modules.nexgen.cari360_ticari_ozet_service import enrich_siparis_listesi_ticari

_STUB_YK = {'NEXGEN_ADMIN'}
CANONICAL_SHA = 'd7c18580ff77f05db1c45a1fec9124eae67874a85f397e086555bf9bd0158546'


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def get_con():
    db_uri = f'file:{os.path.abspath(CANONICAL_DB)}?mode=ro'
    con = sqlite3.connect(db_uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _load_siparisler(cari_id, **kwargs):
    con = get_con()
    try:
        with mock.patch(
            'modules.nexgen.cari360_ops_read_service._assert_cari',
            return_value={'id': cari_id},
        ), mock.patch(
            'modules.nexgen.cari360_ops_read_service.can_view_cari',
            return_value=True,
        ), mock.patch(
            'modules.nexgen.cari360_ops_read_service.can_view_cari_ticari',
            return_value=True,
        ):
            return load_cari360_siparisler(con, cari_id, kullanici_id=1, yk=_STUB_YK, **kwargs)
    finally:
        con.close()


def _load_ozet(cari_id):
    con = get_con()
    try:
        with mock.patch(
            'modules.nexgen.cari360_ops_read_service._assert_cari',
            return_value={'id': cari_id},
        ), mock.patch(
            'modules.nexgen.cari360_ops_read_service.can_view_cari',
            return_value=True,
        ), mock.patch(
            'modules.nexgen.cari360_ops_read_service.can_view_cari_ticari',
            return_value=True,
        ):
            return load_cari360_ozet(con, cari_id, kullanici_id=1, yk=_STUB_YK)
    finally:
        con.close()


def _load_uretim(cari_id, **kwargs):
    con = get_con()
    try:
        with mock.patch(
            'modules.nexgen.cari360_ops_read_service._assert_cari',
            return_value={'id': cari_id},
        ), mock.patch(
            'modules.nexgen.cari360_ops_read_service.can_view_cari',
            return_value=True,
        ), mock.patch(
            'modules.nexgen.cari360_ops_read_service.can_view_cari_ticari',
            return_value=True,
        ):
            return load_cari360_uretim(con, cari_id, kullanici_id=1, yk=_STUB_YK, **kwargs)
    finally:
        con.close()


results = []


def check(name, cond, detail=''):
    status = 'PASS' if cond else 'FAIL'
    results.append((name, status, detail))
    print(f'  [{status}] {name}' + (f' — {detail}' if detail else ''))
    return cond


print('\n' + '='*60)
print('CARI360-CANONICAL-FIX-02 REGRESSION')
print('='*60)

# ── DB guard ───────────────────────────────────────────────────────────────────
print('\n[GUARD] DB SHA kontrolü')
sha_before = sha256_file(CANONICAL_DB)
check('DB-SHA başlangıç doğru', sha_before == CANONICAL_SHA, sha_before[:16])

# ═══════════════════════════════════════════════════════════════════════════════
# CASE 1 — CEK VADE: PZM-2026-0221
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[CASE 1] CEK vade — PZM-2026-0221')
c1 = _load_siparisler(5)
liste1 = c1.get('liste', [])
pzm0221 = next((s for s in liste1 if s.get('siparis_no') == 'PZM-2026-0221'), None)
if pzm0221:
    check('C1-odeme_tipi CEK', pzm0221.get('odeme_tipi') == 'CEK', str(pzm0221.get('odeme_tipi')))
    cvg = pzm0221.get('cek_vade_gun')
    check('C1-cek_vade_gun=220', cvg == 220, str(cvg))
    gvg = pzm0221.get('gosterilecek_vade_gun')
    check('C1-gosterilecek_vade_gun=220', gvg == 220, str(gvg))
    check('C1-para_birimi USD', pzm0221.get('para_birimi') == 'USD')
    # Fiyat
    toplam = pzm0221.get('toplam_tutar')
    check('C1-toplam_tutar=12000', float(toplam or 0) == 12000.0, str(toplam))
    # Kalem fiyatı
    kals = pzm0221.get('kalemler', [])
    check('C1-kalem fiyat=4', any(str(k.get('birim_fiyat', '')) == '4' for k in kals), str([k.get('birim_fiyat') for k in kals]))
else:
    check('C1-PZM-2026-0221 bulundu', False, 'sipariş yok')

# ═══════════════════════════════════════════════════════════════════════════════
# CASE 2 — VADELI sipariş mevcut davranışı korunuyor
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[CASE 2] VADELI sipariş vade_gun değişmedi')
con2 = get_con()
try:
    vadeli_sips = con2.execute(
        "SELECT id, siparis_no, vade_gun FROM nexgen_planlama_siparis "
        "WHERE odeme_tipi='VADELI' AND vade_gun IS NOT NULL LIMIT 3"
    ).fetchall()
finally:
    con2.close()
if vadeli_sips:
    cari_ids_vadeli = set()
    for vs in vadeli_sips:
        cid_row = None
        con_v = get_con()
        try:
            cid_row = con_v.execute(
                "SELECT cari_id FROM nexgen_planlama_siparis WHERE id=?", (vs['id'],)
            ).fetchone()
        finally:
            con_v.close()
        if cid_row:
            cari_ids_vadeli.add(int(cid_row['cari_id']))
    for cid_v in list(cari_ids_vadeli)[:2]:
        data_v = _load_siparisler(cid_v)
        for sip in data_v.get('liste', []):
            if sip.get('odeme_tipi') == 'VADELI' and sip.get('vade_gun') not in (None, ''):
                vg_actual = sip.get('gosterilecek_vade_gun')
                vg_expected = sip.get('vade_gun')
                check(
                    f'C2-{sip["siparis_no"]} gosterilecek_vade_gun=vade_gun',
                    vg_actual == int(vg_expected) if vg_expected else vg_actual is None,
                    f'{vg_actual} vs {vg_expected}',
                )
                break
else:
    print('  [INFO] Sistemde VADELI sipariş yok — skip')
    results.append(('C2-VADELI-skip', 'PASS', 'no VADELI orders'))

# ═══════════════════════════════════════════════════════════════════════════════
# CASE 3 — Sevkiyat lifecycle: HAZIRLANIYOR dahil değil
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[CASE 3] Sevkiyat lifecycle — HAZIRLANIYOR hariç')
# Sipariş geçmişi sevk_kg (PZM-2026-0221)
if pzm0221:
    sevk_kg = pzm0221.get('sevk_edilen_kg')
    check('C3-sevk_kg=3000 (sadece SEVK_EDILDI)', str(sevk_kg) == '3000', str(sevk_kg))
    son_sevk = pzm0221.get('son_sevkiyat_tarihi')
    check('C3-son_sevkiyat mevcut', son_sevk is not None, str(son_sevk))
else:
    check('C3-PZM-2026-0221 mevcut', False)

# DB doğrudan — iki satır var mı
con3 = get_con()
try:
    rows3 = con3.execute(
        "SELECT id, sevkiyat_no, durum, sevk_tarihi FROM mo_musteri_sevkiyat WHERE siparis_id=759"
    ).fetchall()
    check('C3-DB iki sevkiyat satırı', len(rows3) == 2, str(len(rows3)))
    durumlar = sorted([r['durum'] for r in rows3])
    check('C3-DB HAZIRLANIYOR+SEVK_EDILDI', durumlar == ['HAZIRLANIYOR', 'SEVK_EDILDI'], str(durumlar))
    check('C3-DB direct HAZIRLANIYOR dahil değil', str(sevk_kg) == '3000' if pzm0221 else False, str(sevk_kg))
finally:
    con3.close()

# ═══════════════════════════════════════════════════════════════════════════════
# CASE 4 — Legacy header price: kalem birim_fiyat=NULL, header=anlasma_birim_fiyat
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[CASE 4] Legacy header price — ESKI_BASLIK_FIYATI fixture')
# Gerçek bir legacy sipariş oluştur (in-memory fixture, DB yazmaz)
import sqlite3 as _sl3
con4 = _sl3.connect(':memory:')
con4.row_factory = _sl3.Row
con4.executescript("""
CREATE TABLE nexgen_planlama_siparis (
    id INTEGER PRIMARY KEY, siparis_no TEXT, cari_id INTEGER, durum TEXT,
    olusturma_tarihi TEXT, termin_tarihi TEXT, musteri_termin TEXT, onerilen_termin TEXT,
    anlasma_para_birimi TEXT, anlasma_birim_fiyat TEXT,
    talep_referansi TEXT, mo_gorusme_id INTEGER,
    odeme_tipi TEXT, vade_gun INTEGER, cek_vadesi TEXT, cek_vade_gun INTEGER,
    kur TEXT, kur_kaynagi TEXT
);
CREATE TABLE nexgen_planlama_siparis_kalem (
    id INTEGER PRIMARY KEY, planlama_siparis_id INTEGER, sira_no INTEGER,
    urun_ailesi TEXT, formul_ad TEXT, renk_ad TEXT,
    miktar_l REAL, miktar_s REAL, miktar_m REAL,
    birim_fiyat TEXT, net_birim_fiyat TEXT, satir_tutari TEXT,
    satir_tutari_try TEXT, iskonto_orani TEXT, iskonto_tutari TEXT,
    net_birim_fiyat_try TEXT,
    termin_tarihi TEXT, notlar TEXT, durum TEXT, legacy_kaynak INTEGER,
    olusturma_tarihi TEXT, guncelleme_tarihi TEXT,
    numune_talep_id INTEGER, rf_renk_id INTEGER, mtt_kalem_id INTEGER,
    formul_id INTEGER, renk_varyant_id INTEGER, uretim_plan_id INTEGER
);
INSERT INTO nexgen_planlama_siparis VALUES
  (901,'SEHA-LEGACY-0001',9,'TAMAMLANDI','2026-07-27','2026-09-01',NULL,NULL,
   'USD','3.15',NULL,NULL,'VADELI',225,NULL,NULL,NULL,NULL);
INSERT INTO nexgen_planlama_siparis_kalem VALUES
  (901,901,1,'TERLIK','Terlik Formül','0350 KIRMIZI',5000,0,0,
   NULL,NULL,NULL,NULL,NULL,NULL,NULL,
   '2026-09-01',NULL,'AKTIF',0,'2026-07-27','2026-07-27',NULL,NULL,NULL,NULL,NULL,NULL);
""")
legacy_liste = [{
    'id': 901, 'siparis_no': 'SEHA-LEGACY-0001', 'siparis_tarihi': None,
    'durum': 'TAMAMLANDI', 'termin': None, 'toplam_kg': None,
    'kalem_sayisi': 1, 'plan_sayisi': 0, 'batch_sayisi': 0,
    'uretilen_kg': None, 'son_sevkiyat_tarihi': None, 'sevk_edilen_kg': None,
    'kalan_kg': None, 'kalemler': [
        {'id': 901, 'birim_fiyat': None, 'net_birim_fiyat': None,
         'satir_tutari': None, 'satir_tutari_try': None}
    ],
}]
enriched4 = enrich_siparis_listesi_ticari(con4, legacy_liste, ticari_gorunur=True)
con4.close()
leg = enriched4[0]
check('C4-fiyat_durumu=ESKI_BASLIK_FIYATI', leg.get('fiyat_durumu') == 'ESKI_BASLIK_FIYATI', str(leg.get('fiyat_durumu')))
check('C4-anlasma_birim_fiyat=3.15', abs(float(str(leg.get('anlasma_birim_fiyat') or 0).replace(',', '.')) - 3.15) < 0.001, str(leg.get('anlasma_birim_fiyat')))
check('C4-para_birimi=USD', leg.get('para_birimi') == 'USD')
check('C4-odeme_tipi=VADELI', leg.get('odeme_tipi') == 'VADELI')
check('C4-vade_gun=225', str(leg.get('vade_gun', '')) == '225', str(leg.get('vade_gun')))
check('C4-gosterilecek_vade_gun=225', leg.get('gosterilecek_vade_gun') == 225, str(leg.get('gosterilecek_vade_gun')))

# ═══════════════════════════════════════════════════════════════════════════════
# CASE 5 — Modern kalem price: birim_fiyat=4 değişmedi
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[CASE 5] Modern kalem price — PZM-2026-0221 birim_fiyat=4')
if pzm0221:
    kals5 = pzm0221.get('kalemler', [])
    check('C5-kalem var', len(kals5) > 0, str(len(kals5)))
    if kals5:
        bp = kals5[0].get('birim_fiyat')
        nbp = kals5[0].get('net_birim_fiyat')
        check('C5-birim_fiyat=4', str(bp) == '4', str(bp))
        check('C5-net_birim_fiyat=4', str(nbp) == '4', str(nbp))
    check('C5-fiyat_durumu=TAM', pzm0221.get('fiyat_durumu') == 'TAM', str(pzm0221.get('fiyat_durumu')))
    check('C5-toplam_tutar=12000', abs(float(pzm0221.get('toplam_tutar') or 0) - 12000.0) < 0.01, str(pzm0221.get('toplam_tutar')))
else:
    check('C5-PZM-2026-0221 mevcut', False)

# ═══════════════════════════════════════════════════════════════════════════════
# CASE 6 — Üretim locks: PLAN=1, BATCH=1, ÜRETİLEN KG=3068.5
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[CASE 6] Üretim locks — PZM-2026-0221')
ur6 = _load_uretim(5)
plan_0221 = next((p for p in ur6.get('liste', []) if p.get('siparis_no') == 'PZM-2026-0221'), None)
if plan_0221:
    check('C6-plan_kodu=NP-2026-00115', plan_0221.get('plan_kodu') == 'NP-2026-00115', str(plan_0221.get('plan_kodu')))
    check('C6-batch_sayisi=1', plan_0221.get('batch_sayisi') == 1, str(plan_0221.get('batch_sayisi')))
    check('C6-batch_kodu=NG-PRD-2026-00029', 'NG-PRD-2026-00029' in (plan_0221.get('batch_kodlari') or []))
    uk = plan_0221.get('uretilen_kg')
    check('C6-uretilen_kg=3068.5', abs(float(uk or 0) - 3068.5) < 0.1, str(uk))
    check('C6-durum=BITTI', plan_0221.get('durum') == 'BITTI', str(plan_0221.get('durum')))
    check('C6-tamamlanma=100', plan_0221.get('tamamlanma_yuzdesi') == 100, str(plan_0221.get('tamamlanma_yuzdesi')))
    check('C6-zincir_eksik=False', plan_0221.get('zincir_eksik') is False)
else:
    check('C6-PZM-0221 üretim planı bulundu', False)
# Sipariş geçmişindeki üretim alanları
if pzm0221:
    check('C6-sip_plan_sayisi=1', pzm0221.get('plan_sayisi') == 1, str(pzm0221.get('plan_sayisi')))
    check('C6-sip_batch_sayisi=1', pzm0221.get('batch_sayisi') == 1, str(pzm0221.get('batch_sayisi')))
    sip_uk = pzm0221.get('uretilen_kg')
    check('C6-sip_uretilen_kg=3068.5', abs(float(sip_uk or 0) - 3068.5) < 0.1, str(sip_uk))

# ═══════════════════════════════════════════════════════════════════════════════
# KPI — 3E (cari_id=5) özet: TOPLAM SEVKİYAT + TOPLAM SEVK KG
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[KPI] 3E Cari360 özet — sadece SEVK_EDILDI')
kpi5 = _load_ozet(5)
kpi = kpi5.get('kpi', {})
check('KPI-toplam_sevkiyat=1', kpi.get('toplam_sevkiyat') == 1, str(kpi.get('toplam_sevkiyat')))
check('KPI-toplam_sevk_kg=3000', str(kpi.get('toplam_sevk_kg', '')) == '3000', str(kpi.get('toplam_sevk_kg')))
check('KPI-son_sevkiyat mevcut', kpi.get('son_sevkiyat_tarihi') is not None, str(kpi.get('son_sevkiyat_tarihi')))
check('KPI-son_sevkiyat=2026-08-10', str(kpi.get('son_sevkiyat_tarihi', '')).startswith('2026-08-10'), str(kpi.get('son_sevkiyat_tarihi')))

# ═══════════════════════════════════════════════════════════════════════════════
# DB SHA guard — son kontrol
# ═══════════════════════════════════════════════════════════════════════════════
print('\n[GUARD] DB SHA son kontrol')
sha_after = sha256_file(CANONICAL_DB)
check('DB-SHA değişmedi', sha_after == CANONICAL_SHA, sha_after[:16])

# ═══════════════════════════════════════════════════════════════════════════════
# ÖZET
# ═══════════════════════════════════════════════════════════════════════════════
print('\n' + '='*60)
total = len(results)
passed = sum(1 for _, s, _ in results if s == 'PASS')
failed = sum(1 for _, s, _ in results if s == 'FAIL')
print(f'TOPLAM: {total}  PASS: {passed}  FAIL: {failed}')
for name, status, detail in results:
    if status == 'FAIL':
        print(f'  FAIL: {name}' + (f' — {detail}' if detail else ''))
print('='*60)
if failed:
    sys.exit(1)
