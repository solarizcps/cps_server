# -*- coding: utf-8 -*-
"""
Pazarlama Merkezi BE-2 — Çok kalemli taslak kaydetme (V2 payload)
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from modules.nexgen.cekirdek_gorunum import cekirdek_formul_mu

PZM_V2_JSON_PREFIX = '__PZM_V2__'
PZM_AILELER = frozenset({'TERLIK', 'TABAN', 'DOKME'})
PZM_PARA_BIRIMLERI = frozenset({'TRY', 'USD', 'EUR'})
PZM_BIRIM_FIYAT_MAX = Decimal('999999.9999')


def pzm_finans_kolonlari_var(con) -> bool:
    cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis)').fetchall()}
    return (
        'anlasma_para_birimi' in cols
        and 'vade_gun' in cols
        and 'anlasma_birim_fiyat' in cols
    )


def pzm_para_birimi_normalize(raw) -> str:
    s = (raw or '').strip().upper()
    if s == 'TL':
        s = 'TRY'
    return s


def pzm_vade_gun_dogrula(raw) -> int:
    if raw in (None, ''):
        raise PzmWriteError('Vade günü zorunludur.')
    if isinstance(raw, str):
        s = raw.strip()
        if not s.isdigit():
            raise PzmWriteError('Vade günü 0 veya daha büyük tam sayı olmalıdır.')
        raw = s
    try:
        v = int(raw)
    except (TypeError, ValueError):
        raise PzmWriteError('Vade günü 0 veya daha büyük tam sayı olmalıdır.')
    if v < 0:
        raise PzmWriteError('Vade günü 0 veya daha büyük tam sayı olmalıdır.')
    return v


def pzm_birim_fiyat_dogrula(raw) -> str:
    """Decimal string döner — en fazla 4 ondalık, örn. 2.3500."""
    if raw in (None, ''):
        raise PzmWriteError('Anlaşma birim fiyatı zorunludur.')
    s = str(raw).strip().replace(' ', '')
    if not s:
        raise PzmWriteError('Anlaşma birim fiyatı zorunludur.')
    if s.count(',') > 1 or s.count('.') > 1:
        raise PzmWriteError('Anlaşma birim fiyatı geçerli bir sayı olmalıdır.')
    if ',' in s and '.' in s:
        raise PzmWriteError('Anlaşma birim fiyatı geçerli bir sayı olmalıdır.')
    s = s.replace(',', '.')
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise PzmWriteError('Anlaşma birim fiyatı geçerli bir sayı olmalıdır.')
    if not d.is_finite():
        raise PzmWriteError('Anlaşma birim fiyatı geçerli bir sayı olmalıdır.')
    if d <= 0:
        raise PzmWriteError('Anlaşma birim fiyatı sıfırdan büyük olmalıdır.')
    if d > PZM_BIRIM_FIYAT_MAX:
        raise PzmWriteError('Anlaşma birim fiyatı geçerli bir sayı olmalıdır.')
    return format(d.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP), 'f')


class PzmWriteError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def pzm_is_v2_payload(data: dict) -> bool:
    return isinstance(data.get('kalemler'), list)


def pzm_v2_header_pack(meta: dict) -> str:
    return PZM_V2_JSON_PREFIX + json.dumps(meta, ensure_ascii=False, separators=(',', ':'))


def _float_miktar(val, alan: str) -> float:
    if val in (None, ''):
        return 0.0
    try:
        v = round(float(val), 3)
    except (TypeError, ValueError):
        raise PzmWriteError(f'{alan} geçersiz.')
    if v < 0:
        raise PzmWriteError('Miktar negatif olamaz.')
    return v


def _kalem_anahtar(k: dict) -> tuple:
    rf = k.get('rf_renk_id') or k.get('renk_varyant_id')
    return (
        int(k['formul_id']),
        int(rf),
        float(k.get('miktar_l') or 0),
        float(k.get('miktar_s') or 0),
        float(k.get('miktar_m') or 0),
    )


def pzm_v2_kalem_dogrula(con, kalem_raw: dict, sira: int, cari_id: int | None = None) -> dict[str, Any]:
    """Tek kalem doğrulama — taslak: renk kartı yeterli, RF uygunluk MRP'de."""
    from modules.nexgen.routes import (
        _pzm_termin_dogrula,
        _renk_varyant_uv_haritasi,
        _pzm_kalem_renk_coz,
        _pzm_formul_boyutlari,
        _pzm_renk_etiketi,
        _pzm_rf_cari_uygun,
    )
    from modules.nexgen.cekirdek_gorunum import yeni_secimde_renk_gosterilebilir_mi

    urun_ailesi = (kalem_raw.get('urun_ailesi') or '').strip().upper()
    if urun_ailesi not in PZM_AILELER:
        raise PzmWriteError(f'Kalem {sira}: geçersiz ürün ailesi.')

    try:
        formul_id = int(kalem_raw.get('formul_id'))
    except (TypeError, ValueError):
        raise PzmWriteError(f'Kalem {sira}: formül zorunlu.')

    rf_renk_id = kalem_raw.get('rf_renk_id')
    if rf_renk_id in (None, ''):
        rf_renk_id = kalem_raw.get('renk_varyant_id')
    try:
        rf_renk_id = int(rf_renk_id)
    except (TypeError, ValueError):
        raise PzmWriteError(f'Kalem {sira}: renk seçimi zorunlu.')

    f = con.execute(
        "SELECT id, ad, kod, urun_ailesi FROM nexgen_formul "
        "WHERE id=? AND aktif=1 AND durum IN ('AKTIF','URETIME_ACIK')",
        (formul_id,),
    ).fetchone()
    if not f or not cekirdek_formul_mu(f['kod']):
        raise PzmWriteError(f'Kalem {sira}: formül geçersiz veya legacy.')

    rf_row = con.execute("""
        SELECT id, rf_kod, ad, durum, aktif, cari_id, ilk_talep_cari_id, kaynak_arge_test_id
        FROM nexgen_rf_renk WHERE id=? AND aktif=1
    """, (rf_renk_id,)).fetchone()
    if not rf_row or not yeni_secimde_renk_gosterilebilir_mi(dict(rf_row)):
        raise PzmWriteError(f'Kalem {sira}: renk kartı geçersiz veya pasif.')
    if not _pzm_rf_cari_uygun(dict(rf_row), cari_id):
        raise PzmWriteError(f'Kalem {sira}: renk bu cari için uygun değil.')

    renk_satir, _ = _pzm_kalem_renk_coz(
        con, formul_id, rf_renk_id, cari_id, rf_renk_id=rf_renk_id,
    )
    if not renk_satir:
        raise PzmWriteError(f'Kalem {sira}: renk seçimi formül ile uyumlu değil.')

    ml = _float_miktar(kalem_raw.get('miktar_l'), 'LARGE')
    ms = _float_miktar(kalem_raw.get('miktar_s'), 'SMALL')
    mm = _float_miktar(kalem_raw.get('miktar_m'), 'MEDIUM')

    if urun_ailesi == 'DOKME':
        if ml > 0 or ms > 0:
            raise PzmWriteError(f'Kalem {sira}: DÖKME yalnız MEDIUM kabul eder.')
        if mm <= 0:
            raise PzmWriteError(f'Kalem {sira}: DÖKME için MEDIUM miktar zorunlu.')
    else:
        if mm > 0:
            raise PzmWriteError(f'Kalem {sira}: TERLİK/TABAN için MEDIUM kullanılamaz.')
        if ml <= 0 and ms <= 0:
            raise PzmWriteError(f'Kalem {sira}: en az bir LARGE veya SMALL miktar girin.')

    ok, t_hata, termin = _pzm_termin_dogrula(kalem_raw.get('termin_tarihi'))
    if not ok:
        raise PzmWriteError(f'Kalem {sira}: {t_hata}')

    boyutlar = _pzm_formul_boyutlari(con, formul_id)
    boyut_rv = {b['boyut']: int(b['rv_id']) for b in boyutlar}
    if ml > 0:
        rv_l = boyut_rv.get('LARGE')
        if not rv_l or not _renk_varyant_uv_haritasi(con, rv_l).get('LARGE'):
            raise PzmWriteError(f'Kalem {sira}: LARGE boyutu üretime açık değil.')
    if ms > 0:
        rv_s = boyut_rv.get('SMALL')
        if not rv_s or not _renk_varyant_uv_haritasi(con, rv_s).get('SMALL'):
            raise PzmWriteError(f'Kalem {sira}: SMALL boyutu üretime açık değil.')
    if mm > 0:
        rv_m = boyut_rv.get('MEDIUM')
        if not rv_m or not _renk_varyant_uv_haritasi(con, rv_m).get('STANDART'):
            raise PzmWriteError(f'Kalem {sira}: MEDIUM boyutu üretime açık değil.')

    if ml > 0 and boyut_rv.get('LARGE'):
        renk_varyant_id = boyut_rv['LARGE']
    elif ms > 0 and boyut_rv.get('SMALL'):
        renk_varyant_id = boyut_rv['SMALL']
    elif mm > 0 and boyut_rv.get('MEDIUM'):
        renk_varyant_id = boyut_rv['MEDIUM']
    else:
        renk_varyant_id = next(iter(boyut_rv.values()), None)

    notlar = (kalem_raw.get('notlar') or '').strip() or None
    renk_ad = _pzm_renk_etiketi(rf_row['rf_kod'], rf_row['ad'])

    return {
        'sira_no': int(kalem_raw.get('sira_no') or sira),
        'urun_ailesi': urun_ailesi,
        'formul_id': formul_id,
        'formul_ad': (f['ad'] or f['kod'] or '').strip(),
        'renk_varyant_id': renk_varyant_id,
        'renk_ad': renk_ad,
        'rf_renk_id': rf_renk_id,
        'miktar_l': ml,
        'miktar_s': ms,
        'miktar_m': mm,
        'termin_tarihi': termin,
        'notlar': notlar,
    }


def pzm_v2_payload_dogrula(con, data: dict, cari_id: int) -> dict[str, Any]:
    """V2 payload tam doğrulama."""
    from modules.nexgen.routes import _pzm_termin_dogrula

    cari = con.execute(
        "SELECT id, unvan FROM nexgen_cari WHERE id=? AND aktif=1",
        (cari_id,),
    ).fetchone()
    if not cari:
        raise PzmWriteError('Cari bulunamadı.')

    kalemler_raw = data.get('kalemler')
    if not isinstance(kalemler_raw, list) or len(kalemler_raw) < 1:
        raise PzmWriteError('En az bir sipariş kalemi zorunlu.')

    siparis_tarihi = (data.get('siparis_tarihi') or '').strip()[:10] or None
    genel_termin = data.get('genel_termin_tarihi')
    genel_not = (data.get('genel_not') or data.get('notlar') or '').strip() or None

    if not genel_termin or not str(genel_termin).strip():
        raise PzmWriteError('Genel termin tarihi zorunludur.')
    ok, t_hata, genel_termin = _pzm_termin_dogrula(genel_termin)
    if not ok:
        raise PzmWriteError(t_hata or 'Genel termin tarihi zorunludur.')

    pb = pzm_para_birimi_normalize(data.get('anlasma_para_birimi') or data.get('para_birimi'))
    if pb not in PZM_PARA_BIRIMLERI:
        raise PzmWriteError('Anlaşma para birimi zorunludur.')
    vade_gun = pzm_vade_gun_dogrula(data.get('vade_gun'))
    birim_fiyat = pzm_birim_fiyat_dogrula(
        data.get('anlasma_birim_fiyat') or data.get('birim_fiyat')
    )

    kalemler = []
    seen = set()
    for i, kr in enumerate(kalemler_raw, start=1):
        k = pzm_v2_kalem_dogrula(con, kr, i, cari_id)
        anahtar = (
            k['formul_id'],
            k['rf_renk_id'],
            k['miktar_l'],
            k['miktar_s'],
            k['miktar_m'],
        )
        if anahtar in seen:
            raise PzmWriteError(f'Kalem {i}: aynı ürün/renk/miktar zaten listede.')
        seen.add(anahtar)
        k['sira_no'] = i
        kalemler.append(k)

    terminler = [k['termin_tarihi'] for k in kalemler if k.get('termin_tarihi')]
    header_termin = genel_termin

    return {
        'cari': dict(cari),
        'siparis_tarihi': siparis_tarihi,
        'genel_termin': header_termin,
        'genel_not': genel_not,
        'anlasma_para_birimi': pb,
        'vade_gun': vade_gun,
        'anlasma_birim_fiyat': birim_fiyat,
        'kalemler': kalemler,
    }


def pzm_v2_taslak_kaydet(con, data: dict, uid: int | None) -> dict[str, Any]:
    """Header + kalemler tek transaction."""
    from modules.nexgen.pzm_siparis_read import pzm_kalem_tablosu_var
    from modules.nexgen.routes import _pzm_siparis_no_uret

    if not pzm_kalem_tablosu_var(con):
        raise PzmWriteError('Sipariş kalem tablosu yok.', 400)

    try:
        cari_id = int(data.get('cari_id'))
    except (TypeError, ValueError):
        raise PzmWriteError('Müşteri seçimi zorunludur.')

    hazir = pzm_v2_payload_dogrula(con, data, cari_id)
    cari = hazir['cari']
    kalemler = hazir['kalemler']
    toplam_kg = round(sum(k['miktar_l'] + k['miktar_s'] + k['miktar_m'] for k in kalemler), 3)

    meta = {
        'v': 2,
        'siparis_tarihi': hazir['siparis_tarihi'],
        'genel_termin_tarihi': hazir['genel_termin'],
        'anlasma_para_birimi': hazir['anlasma_para_birimi'],
        'vade_gun': hazir['vade_gun'],
        'anlasma_birim_fiyat': hazir['anlasma_birim_fiyat'],
        'kalem_sayisi': len(kalemler),
    }
    talep_ref = pzm_v2_header_pack(meta)
    finans_kolon = pzm_finans_kolonlari_var(con)

    ps_id = data.get('talep_id')
    guncellendi = False

    try:
        con.execute('BEGIN IMMEDIATE')

        if ps_id:
            try:
                ps_id = int(ps_id)
            except (TypeError, ValueError):
                raise PzmWriteError('talep_id geçersiz.')
            row = con.execute(
                "SELECT id, durum, talep_referansi FROM nexgen_planlama_siparis WHERE id=?",
                (ps_id,),
            ).fetchone()
            if not row:
                raise PzmWriteError('Talep bulunamadı.', 404)
            if row['durum'] not in ('TASLAK',):
                raise PzmWriteError('Yalnız taslak siparişler güncellenebilir.')
            ref = str(row['talep_referansi'] or '')
            if not ref.startswith(PZM_V2_JSON_PREFIX) and not ref.startswith('__PZM_V1__'):
                raise PzmWriteError('Bu sipariş çok kalemli güncelleme için uygun değil.')
            con.execute(
                """
                UPDATE nexgen_planlama_siparis
                SET cari_id=?, cari_unvan=?, termin_tarihi=?, notlar=?,
                    talep_referansi=?, durum='TASLAK',
                    guncelleme_tarihi=datetime('now','localtime')
                    """
                + (", anlasma_para_birimi=?, vade_gun=?, anlasma_birim_fiyat=?" if finans_kolon else "")
                + """
                WHERE id=?
                """,
                (
                    (cari['id'], cari['unvan'], hazir['genel_termin'], hazir['genel_not'],
                     talep_ref, hazir['anlasma_para_birimi'], hazir['vade_gun'],
                     hazir['anlasma_birim_fiyat'], ps_id)
                    if finans_kolon else
                    (cari['id'], cari['unvan'], hazir['genel_termin'], hazir['genel_not'],
                     talep_ref, ps_id)
                ),
            )
            con.execute(
                'DELETE FROM nexgen_planlama_siparis_kalem WHERE planlama_siparis_id=?',
                (ps_id,),
            )
            guncellendi = True
            siparis_no = con.execute(
                'SELECT siparis_no FROM nexgen_planlama_siparis WHERE id=?', (ps_id,)
            ).fetchone()['siparis_no']
        else:
            siparis_no = _pzm_siparis_no_uret(con)
            cur = con.execute(
                """
                INSERT INTO nexgen_planlama_siparis
                    (siparis_no, cari_id, cari_unvan, termin_tarihi, talep_referansi,
                     durum, notlar, olusturan_id"""
                + (", anlasma_para_birimi, vade_gun, anlasma_birim_fiyat" if finans_kolon else "")
                + """)
                VALUES (?, ?, ?, ?, ?, 'TASLAK', ?, ?"""
                + (", ?, ?, ?" if finans_kolon else "")
                + ")",
                (
                    (siparis_no, cari['id'], cari['unvan'], hazir['genel_termin'],
                     talep_ref, hazir['genel_not'], uid,
                     hazir['anlasma_para_birimi'], hazir['vade_gun'], hazir['anlasma_birim_fiyat'])
                    if finans_kolon else
                    (siparis_no, cari['id'], cari['unvan'], hazir['genel_termin'],
                     talep_ref, hazir['genel_not'], uid)
                ),
            )
            ps_id = cur.lastrowid

        for k in kalemler:
            con.execute(
                """
                INSERT INTO nexgen_planlama_siparis_kalem
                    (planlama_siparis_id, sira_no, urun_ailesi, formul_id, formul_ad,
                     renk_varyant_id, renk_ad, rf_renk_id,
                     miktar_l, miktar_s, miktar_m, termin_tarihi, notlar,
                     durum, legacy_kaynak)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'AKTIF', 0)
                """,
                (
                    ps_id, k['sira_no'], k['urun_ailesi'], k['formul_id'], k['formul_ad'],
                    k['renk_varyant_id'], k['renk_ad'], k['rf_renk_id'],
                    k['miktar_l'], k['miktar_s'], k['miktar_m'],
                    k['termin_tarihi'], k['notlar'],
                ),
            )

        con.commit()
    except PzmWriteError:
        con.rollback()
        raise
    except Exception as e:
        con.rollback()
        raise PzmWriteError(str(e), 500) from e

    return {
        'ok': True,
        'talep_id': ps_id,
        'siparis_no': siparis_no,
        'durum': 'TASLAK',
        'kalem_sayisi': len(kalemler),
        'toplam_kg': toplam_kg,
        'guncellendi': guncellendi,
        'anlasma_para_birimi': hazir['anlasma_para_birimi'],
        'vade_gun': hazir['vade_gun'],
        'anlasma_birim_fiyat': hazir['anlasma_birim_fiyat'],
        'genel_termin_tarihi': hazir['genel_termin'],
    }
