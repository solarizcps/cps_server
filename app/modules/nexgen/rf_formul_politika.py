# -*- coding: utf-8 -*-
"""Geçici RF–formül uygunluk politikası (FAZ-RF-FORMUL-ILISKILENDIRME-GECICI-PASIF).

Merkezi feature flag ile yönetilir. DB'deki nexgen_rf_formul_uygunluk kayıtları
silinmez/pasifleştirilmez; yalnızca lookup davranışı değişir.
"""
from __future__ import annotations

import json
import os
from typing import Any

from modules.nexgen.cekirdek_gorunum import (
    cekirdek_formul_mu,
    renk_sayisal_onek,
    yeni_secimde_renk_gosterilebilir_mi,
)
from modules.nexgen.kod_uretici import uretim_kodu_format_gecerli_mi, uretim_kodu_uret


def rf_formul_uygunluk_zorunlu() -> bool:
    """True → eski davranış (DB uygunluk + dolu uretim_kodu zorunlu)."""
    env = (os.environ.get('CPS_RF_FORMUL_UYGUNLUK_ZORUNLU') or '').strip().lower()
    if env in ('1', 'true', 'yes', 'on'):
        return True
    if env in ('0', 'false', 'no', 'off'):
        return False
    return False


def cekirdek_kod_aile_oneki(formul_kod: str | None) -> str | None:
    k = (formul_kod or '').strip().upper()
    if k.startswith('1BA-'):
        return 'TERLIK'
    if k.startswith('2BA-'):
        return 'TABAN'
    if k.startswith('3BA-'):
        return 'DOKME'
    return None


def _norm_aile(urun_ailesi: str | None) -> str:
    a = (urun_ailesi or '').upper().replace('İ', 'I').replace('Ö', 'O')
    if a in ('DOKME', 'DÖKME'):
        return 'DOKME'
    if a == 'TABAN':
        return 'TABAN'
    return 'TERLIK'


def formul_aile_kod_uyumlu(formul_kod: str | None, urun_ailesi: str | None) -> bool:
    """Formül kodu prefix'i ürün ailesi ile uyumlu mu (1BA/2BA/3BA)."""
    if not cekirdek_formul_mu(formul_kod):
        return True
    onek = cekirdek_kod_aile_oneki(formul_kod)
    if not onek:
        return False
    aile = _norm_aile(urun_ailesi)
    if onek == 'TERLIK':
        return aile == 'TERLIK'
    if onek == 'TABAN':
        return aile == 'TABAN'
    if onek == 'DOKME':
        return aile == 'DOKME'
    return False


def dokme_formul_gecerli_mi(formul_kod: str | None) -> bool:
    """DÖKME yalnız 3BA-FM (MEDIUM) çekirdekleri."""
    k = (formul_kod or '').strip().upper()
    if not k.startswith('3BA-'):
        return True
    return '-FM' in k


def uretim_kodu_hesapla(rf_row: dict | Any, formul_kod: str | None) -> dict | None:
    """DB uygunluk satırı olmadan üretim kodu türet (ör. 1BA-FL01-0260)."""
    rf = dict(rf_row) if rf_row else {}
    if not yeni_secimde_renk_gosterilebilir_mi(rf):
        return None
    fk = (formul_kod or '').strip().upper()
    if not cekirdek_formul_mu(fk):
        return None
    renk_kodu = renk_sayisal_onek(rf.get('rf_kod'))
    if not renk_kodu:
        return None
    uretim_kodu = uretim_kodu_uret(fk, renk_kodu)
    if not uretim_kodu_format_gecerli_mi(uretim_kodu):
        return None
    return {
        'uretim_kodu': uretim_kodu,
        'ana_formul_kodu': fk,
        'renk_kodu': renk_kodu,
    }


def _revizyon_tablosu_var(con) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nexgen_rf_revizyon'"
    ).fetchone())


def _rf_aktif_revizyon_onayli_mi(con, rf_renk_id: int, aktif_rev_no: int | None) -> bool:
    """Aktif revizyon var ve ONAYLANDI + kilitli mi."""
    try:
        rev_no = int(aktif_rev_no or 0)
    except (TypeError, ValueError):
        return False
    if rev_no <= 0:
        return False
    if not _revizyon_tablosu_var(con):
        return True
    rev = con.execute("""
        SELECT durum, kilitli_mi
        FROM nexgen_rf_revizyon
        WHERE rf_renk_id=? AND rev_no=? AND aktif=1
        LIMIT 1
    """, (rf_renk_id, rev_no)).fetchone()
    if not rev:
        return False
    return rev['durum'] == 'ONAYLANDI' and bool(rev['kilitli_mi'])


def _rf_pigment_dolu_mi(con, rf_renk_id: int, aktif_rev_no: int | None) -> bool:
    """Boya reçetesi (pigment) dolu mu — revizyon snapshot veya legacy rf_kalem."""
    if _revizyon_tablosu_var(con):
        try:
            rev_no = int(aktif_rev_no or 0)
        except (TypeError, ValueError):
            rev_no = 0
        if rev_no > 0:
            rev = con.execute("""
                SELECT pigmentler_json
                FROM nexgen_rf_revizyon
                WHERE rf_renk_id=? AND rev_no=? AND aktif=1
                LIMIT 1
            """, (rf_renk_id, rev_no)).fetchone()
            if rev:
                try:
                    pigmentler = json.loads(rev['pigmentler_json'] or '[]')
                except (ValueError, TypeError):
                    pigmentler = []
                if pigmentler and any(float(p.get('miktar_kg') or 0) > 0 for p in pigmentler):
                    return True
    row = con.execute("""
        SELECT COALESCE(SUM(miktar_kg), 0) AS toplam
        FROM nexgen_rf_kalem
        WHERE rf_renk_id=? AND aktif=1
    """, (rf_renk_id,)).fetchone()
    return bool(row and float(row['toplam'] or 0) > 0)


def _formul_uretime_acik_mi(con, formul_id: int) -> bool:
    row = con.execute("""
        SELECT 1
        FROM nexgen_renk_varyant rv
        JOIN nexgen_uretim_varyant uv ON uv.renk_varyant_id = rv.id
            AND uv.aktif = 1 AND uv.recete_durum = 'URETIME_ACIK'
        JOIN nexgen_recete_kalem rk ON rk.uretim_varyant_id = uv.id AND rk.aktif = 1
        WHERE rv.formul_id = ? AND rv.aktif = 1
        LIMIT 1
    """, (formul_id,)).fetchone()
    return bool(row)


def rf_formul_gecici_hazir_mi(con, rf_renk_id: int, formul_id: int) -> bool:
    """Geçici mod: manuel uygunluk satırı olmadan RF+formül hazır mı."""
    if rf_formul_uygunluk_zorunlu():
        return False
    try:
        rf_renk_id = int(rf_renk_id)
        formul_id = int(formul_id)
    except (TypeError, ValueError):
        return False

    rf = con.execute("""
        SELECT id, rf_kod, ad, durum, aktif, kaynak_arge_test_id, aktif_rev_no
        FROM nexgen_rf_renk WHERE id = ?
    """, (rf_renk_id,)).fetchone()
    if not rf or not yeni_secimde_renk_gosterilebilir_mi(dict(rf)):
        return False
    if not _rf_aktif_revizyon_onayli_mi(con, rf_renk_id, rf['aktif_rev_no']):
        return False
    if not _rf_pigment_dolu_mi(con, rf_renk_id, rf['aktif_rev_no']):
        return False

    frm = con.execute("""
        SELECT id, kod, urun_ailesi, aktif
        FROM nexgen_formul WHERE id = ?
    """, (formul_id,)).fetchone()
    if not frm or not frm['aktif'] or not cekirdek_formul_mu(frm['kod']):
        return False
    if not formul_aile_kod_uyumlu(frm['kod'], frm['urun_ailesi']):
        return False
    if not dokme_formul_gecerli_mi(frm['kod']):
        return False
    if not uretim_kodu_hesapla(dict(rf), frm['kod']):
        return False
    return _formul_uretime_acik_mi(con, formul_id)


def uretim_kodu_coz(con, rf_renk_id: int, formul_id: int) -> dict | None:
    """Önce DB uygunluk satırı; geçici modda hesaplanmış kod."""
    cols = [c[1] for c in con.execute("PRAGMA table_info(nexgen_rf_formul_uygunluk)").fetchall()]
    if 'uretim_kodu' in cols:
        row = con.execute("""
            SELECT id AS uygunluk_id, uretim_kodu, ana_formul_kodu, renk_kodu
            FROM nexgen_rf_formul_uygunluk
            WHERE rf_renk_id=? AND formul_id=? AND aktif=1
              AND uretim_kodu IS NOT NULL AND TRIM(uretim_kodu) != ''
              AND ana_formul_kodu IS NOT NULL AND TRIM(ana_formul_kodu) != ''
              AND renk_kodu IS NOT NULL AND TRIM(renk_kodu) != ''
            LIMIT 1
        """, (rf_renk_id, formul_id)).fetchone()
        if row:
            return dict(row)

    if rf_formul_uygunluk_zorunlu():
        return None

    rf = con.execute("""
        SELECT rf_kod, aktif, durum, kaynak_arge_test_id
        FROM nexgen_rf_renk WHERE id=?
    """, (rf_renk_id,)).fetchone()
    frm = con.execute("""
        SELECT kod, urun_ailesi FROM nexgen_formul WHERE id=?
    """, (formul_id,)).fetchone()
    if not rf or not frm:
        return None
    if not formul_aile_kod_uyumlu(frm['kod'], frm['urun_ailesi']):
        return None
    if not dokme_formul_gecerli_mi(frm['kod']):
        return None
    return uretim_kodu_hesapla(dict(rf), frm['kod'])
