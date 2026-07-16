# -*- coding: utf-8 -*-
"""
NexGen Formül Kod Üretici
=========================
Merkezi, format-bağımsız kod üretim mekanizması.

ÖNEMLI: Bu modül formül kodunun *mekanizmasını* sağlar.
Gerçek kod standardı (ürün tipi + shore + karışım + formül + renk yapısı)
henüz kesinleşmemiştir. Format kesinleştiğinde YALNIZCA bu dosyadaki
_formul_kod_olustur() ve _rv_kod_olustur() fonksiyonları güncellenir;
routes.py veya başka bir dosyaya dokunulmaz.

Kullanım:
    from modules.nexgen.kod_uretici import yeni_formul_kodu_uret, yeni_rv_kodu_uret
"""

import datetime
import re


# ─────────────────────────────────────────────────────────────────────────────
# BİRLEŞİK ÜRETİM KODU — FAZ-URETIM-KODU-1
# Format: {ana_formul_kodu}-{renk_kodu}  örn. 1BA-FS02-0031
# ─────────────────────────────────────────────────────────────────────────────

_ANA_FORMUL_KOD_RE = re.compile(r'^[123]BA-F[LSM]\d{2}$', re.IGNORECASE)
_RENK_KOD_RE = re.compile(r'^\d{3,4}$')
_URETIM_KOD_TAM_RE = re.compile(r'^[123]BA-F[LSM]\d{2}-\d{3,4}$', re.IGNORECASE)


def uretim_kodu_uret(ana_formul_kodu: str, renk_kodu: str) -> str:
    """Tek kaynak: AnaFormülKodu-RenkKodu birleşik üretim kodu."""
    ana = (ana_formul_kodu or '').strip().upper()
    renk = (renk_kodu or '').strip()
    return f'{ana}-{renk}'


def uretim_kodu_format_gecerli_mi(kod: str) -> bool:
    return bool(_URETIM_KOD_TAM_RE.match((kod or '').strip()))


def uretim_kodu_ana_formul_gecerli_mi(kod: str) -> bool:
    return bool(_ANA_FORMUL_KOD_RE.match((kod or '').strip()))


def uretim_kodu_renk_gecerli_mi(kod: str) -> bool:
    return bool(_RENK_KOD_RE.match((kod or '').strip()))


def uretim_kodu_parcala(kod: str) -> dict | None:
    """1BA-FS02-0031 → {ana_formul_kodu, renk_kodu, uretim_kodu}"""
    k = (kod or '').strip().upper()
    m = _URETIM_KOD_TAM_RE.match(k)
    if not m:
        return None
    parcalar = k.rsplit('-', 1)
    if len(parcalar) != 2:
        return None
    return {
        'uretim_kodu': k,
        'ana_formul_kodu': parcalar[0],
        'renk_kodu': parcalar[1],
    }


# ─────────────────────────────────────────────────────────────────────────────
# FORMAT TANIMLARI — Yalnızca bu bölüm değişecek
# ─────────────────────────────────────────────────────────────────────────────

def _formul_kod_prefix(yil: int) -> str:
    """
    Formül kodu için prefix üretir.
    Format kesinleştiğinde bu fonksiyon güncellenir.

    Geçici format: NX-YYYY-
    Kesin format: Adem onayından sonra ürün tipi + shore + karışım yapısına göre belirlenecek.
    """
    return f'NX-{yil}-'


def _formul_kod_olustur(prefix: str, sira_no: int) -> str:
    """
    Prefix ve sıra numarasından tam formül kodu üretir.
    Format kesinleştiğinde bu fonksiyon güncellenir.

    Geçici format: NX-YYYY-NNNN
    """
    return f'{prefix}{sira_no:04d}'


def _rv_kod_prefix(formul_kod: str) -> str:
    """
    Renk varyant kodu için prefix üretir.
    Formül koduna bağlıdır; formül kodu değişirse bu da değişir.
    """
    return f'{formul_kod}-RV-'


def _rv_kod_olustur(prefix: str, sira_no: int) -> str:
    """
    Prefix ve sıra numarasından tam RV kodu üretir.
    """
    return f'{prefix}{sira_no:02d}'


# ─────────────────────────────────────────────────────────────────────────────
# GENEL AMAÇLI SIRA NO BULUCU
# ─────────────────────────────────────────────────────────────────────────────

def _mevcut_max_sira_no(con, tablo: str, alan: str, prefix: str) -> int:
    """
    Verilen tabloda prefix ile başlayan kodların maks sıra numarasını döner.
    Prefix'ten sonraki kısmı INTEGER'a cast ederek MAX alır.
    Kayıt yoksa 0 döner.

    con : aktif DB bağlantısı (BEGIN IMMEDIATE içinde çağrılmalı)
    tablo: tablo adı (nexgen_formul / nexgen_renk_varyant)
    alan : kod kolonu adı (kod)
    prefix: örn. 'NX-2026-'
    """
    row = con.execute(
        f"SELECT MAX(CAST(SUBSTR({alan}, ?) AS INTEGER)) FROM {tablo} WHERE {alan} LIKE ?",
        (len(prefix) + 1, prefix + '%')
    ).fetchone()
    return row[0] if row and row[0] else 0


# ─────────────────────────────────────────────────────────────────────────────
# DIŞ ARAYÜZ — routes.py yalnızca bunları çağırır
# ─────────────────────────────────────────────────────────────────────────────

def yeni_formul_kodu_uret(con) -> str:
    """
    Transaction içinde (BEGIN IMMEDIATE aktifken) benzersiz formül kodu üretir.

    - Aktif + pasif + tüm kayıtlar çakışma kontrolüne dahildir.
    - nexgen_formul.kod DB-level UNIQUE ile de korunuyor.
    - Format değiştiğinde yalnızca _formul_kod_prefix() ve _formul_kod_olustur() güncellenir.
    """
    yil = datetime.date.today().year
    prefix = _formul_kod_prefix(yil)
    mevcut_max = _mevcut_max_sira_no(con, 'nexgen_formul', 'kod', prefix)
    return _formul_kod_olustur(prefix, mevcut_max + 1)


def cekirdek_rv_kodu(formul_kod: str, sira_no: int = 1) -> str:
    """Çekirdek import RV kodu: 1BA-FS02-RV-01 (Excel ana kodu korunur)."""
    return f"{formul_kod.strip().upper()}-RV-{sira_no:02d}"


def cekirdek_uv_ad(formul_kod: str, boyut: str) -> str:
    """Çekirdek UV görünen adı — ana formül kodu değişmez."""
    return f"{formul_kod.strip().upper()} {boyut.strip().upper()}"


def yeni_rv_kodu_uret(con, formul_kod: str) -> str:
    """
    Formül altında benzersiz renk varyant kodu üretir.

    - formul_kod: üst formülün kodu (yeni üretilmiş, transaction içinde)
    - Format değiştiğinde yalnızca _rv_kod_prefix() ve _rv_kod_olustur() güncellenir.
    """
    prefix = _rv_kod_prefix(formul_kod)
    mevcut_max = _mevcut_max_sira_no(con, 'nexgen_renk_varyant', 'kod', prefix)
    return _rv_kod_olustur(prefix, mevcut_max + 1)
