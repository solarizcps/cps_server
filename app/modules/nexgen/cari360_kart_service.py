# -*- coding: utf-8 -*-
"""
Cari Kart shell — FAZ-CARI-KART-SHELL-VE-YETKILILER-UI-1

Hafif okuma: nexgen_cari + iç sorumlu + eşleşme durumu.
Finans/CRM/numune/sipariş/tahsilat sorgusu YOK.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from modules.nexgen.cari360_yetki import (
    can_cari360_crm_write,
    can_cari360_view_all,
    can_cari360_view_own,
)
from modules.nexgen.cari_sorumlu_service import can_view_cari, load_kullanici_yetkileri
from modules.nexgen.cari360_relation_policy import resolve_tek_sorumlu
from modules.nexgen.cari_genel_bilgi_service import GENEL_EDIT_FIELDS, can_edit_cari_genel
from modules.nexgen.cari_yetkili_service import can_write_yetkili
from modules.nexgen.mo_gorusme_service import can_mo_gorusme_yaz
from modules.nexgen.finans_cari_provision_service import is_test_kayit

SORUMLU_ATANMAMIS = 'Atanmamış'

_CARI_TIPI_LABEL = {
    'MUSTERI': 'Müşteri',
    'TEDARIKCI': 'Tedarikçi',
    'HER_IKISI': 'Her İkisi',
}
_YURT_LABEL = {
    'YURTICI': 'Yurtiçi',
    'YURTDISI': 'Yurtdışı',
}


class Cari360KartError(Exception):
    def __init__(self, mesaj: str, kod: int = 400):
        self.mesaj = mesaj
        self.kod = kod
        super().__init__(mesaj)


def _fmt_dt(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    if 'T' in s:
        s = s.replace('T', ' ', 1)
    if len(s) >= 16 and s[10] == ' ':
        return s[:16]
    if len(s) >= 10:
        return s[:10]
    return s


def _tablo_var(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def assert_cari_yetkili_schema(con: sqlite3.Connection) -> None:
    if not _tablo_var(con, 'cari_yetkili'):
        raise Cari360KartError(
            'cari_yetkili tablosu yok. Migration 133 uygulanmalı.',
            503,
        )


def _eslestirme_durumu(con: sqlite3.Connection, cari_id: int, cari_kod: str, unvan: str) -> str:
    """Tek satır cari_eslestirme — Cari_Kart / CRM / hareket yok."""
    test = is_test_kayit(cari_kod, unvan)
    durum = None
    if _tablo_var(con, 'cari_eslestirme'):
        row = con.execute(
            """
            SELECT eslestirme_durumu FROM cari_eslestirme
            WHERE nexgen_cari_id=? AND aktif=1
            ORDER BY id DESC LIMIT 1
            """,
            (cari_id,),
        ).fetchone()
        if row:
            durum = (row['eslestirme_durumu'] or '').strip().upper() or None

    if test and durum not in ('DOGRULANDI', 'MANUEL'):
        return 'TEST_NO_LINK'
    if durum in ('DOGRULANDI', 'MANUEL', 'BEKLIYOR', 'TEST_NO_LINK'):
        return durum
    if durum:
        return durum
    return 'BEKLIYOR'


def _is_planlamaci_kullanici(con: sqlite3.Connection, kullanici_id: int | None) -> bool:
    """Planlamacı (Mehmet) iç sorumlu pazarlamacı olarak gösterilmez — DB değiştirilmez."""
    if not kullanici_id:
        return False
    row = con.execute(
        """
        SELECT sk.KullaniciAdi, sk.RolId, sr.Ad AS rol_adi
        FROM sistem_kullanici sk
        LEFT JOIN sistem_rol sr ON sr.Id = sk.RolId
        WHERE sk.Id=?
        """,
        (int(kullanici_id),),
    ).fetchone()
    if not row:
        return False
    rol = (row['rol_adi'] or '').casefold()
    if 'planlama' in rol:
        return True
    yrow = con.execute(
        """
        SELECT 1
        FROM user_permission_override upo
        JOIN sistem_yetki y ON y.Id = upo.YetkiId
        WHERE upo.KullaniciId=? AND y.Kod='nexgen.plan.manage'
          AND COALESCE(upo.can_manage, 0)=1
        LIMIT 1
        """,
        (int(kullanici_id),),
    ).fetchone()
    return bool(yrow)


def _is_gecerli_ic_pazarlamaci(con: sqlite3.Connection, kullanici_id: int) -> bool:
    """Gerçek pazarlama / müşteri operasyon kullanıcısı mı? (read-only karar)."""
    if _is_planlamaci_kullanici(con, kullanici_id):
        return False
    yk = load_kullanici_yetkileri(con, kullanici_id)
    if '*' in yk:
        return False  # admin fallback yok
    # Saf yönetim (tüm cari) ama CRM yazma yok → pazarlamacı sayma
    if can_cari360_view_all(yk) and not can_cari360_crm_write(yk):
        return False
    return can_cari360_crm_write(yk) or can_cari360_view_own(yk)


def _sorumlu_gorunen_ad(con: sqlite3.Connection, kullanici_id: int | None, fallback: str | None) -> str | None:
    if not kullanici_id:
        return (fallback or '').strip() or None
    row = con.execute(
        'SELECT KullaniciAdi, AdSoyad FROM sistem_kullanici WHERE Id=?',
        (int(kullanici_id),),
    ).fetchone()
    if not row:
        return (fallback or '').strip() or None
    adsoyad = (row['AdSoyad'] or '').strip()
    kadi = (row['KullaniciAdi'] or '').strip()
    if adsoyad:
        return adsoyad
    return kadi or ((fallback or '').strip() or None)


def _sorumlu_ozet(con: sqlite3.Connection, cari_id: int) -> dict[str, Any]:
    """cari_sorumlu read-only. Yazma/pasifleştirme/otomatik atama YOK.

    Geçerli pazarlamacı yoksa ana_adi = 'Atanmamış'.
    Planlamacı hatalı atansa bile DB'ye dokunulmaz; ekranda Atanmamış.
    """
    if not _tablo_var(con, 'cari_sorumlu'):
        return {'ana_adi': SORUMLU_ATANMAMIS, 'liste': []}

    rows = con.execute(
        """
        SELECT cs.id, cs.kullanici_id, cs.sorumluluk_rolu, cs.aktif,
               sk.KullaniciAdi AS kullanici_adi, sk.AdSoyad AS ad_soyad,
               sr.Ad AS rol_adi
        FROM cari_sorumlu cs
        JOIN sistem_kullanici sk ON sk.Id = cs.kullanici_id
        LEFT JOIN sistem_rol sr ON sr.Id = sk.RolId
        WHERE cs.cari_id=? AND cs.aktif=1
          AND (cs.bitis_tarihi IS NULL OR cs.bitis_tarihi=''
               OR cs.bitis_tarihi > datetime('now','localtime'))
        ORDER BY
          CASE cs.sorumluluk_rolu
            WHEN 'ANA' THEN 0
            WHEN 'YEDEK' THEN 1
            WHEN 'DESTEK' THEN 2
            WHEN 'YONETICI' THEN 3
            ELSE 9
          END,
          cs.baslangic_tarihi
        """,
        (cari_id,),
    ).fetchall()

    gecerli: list[dict[str, Any]] = []
    liste: list[dict[str, Any]] = []
    for r in rows:
        kid = int(r['kullanici_id'])
        plan = _is_planlamaci_kullanici(con, kid)
        ok = (not plan) and _is_gecerli_ic_pazarlamaci(con, kid)
        item = {
            'kullanici_id': kid,
            'kullanici_adi': r['kullanici_adi'],
            'ad_soyad': r['ad_soyad'],
            'rol': r['sorumluluk_rolu'],
            'planlamaci': plan,
            'gecerli_pazarlamaci': ok,
        }
        liste.append(item)
        if ok:
            gecerli.append(item)

    ana_adi = SORUMLU_ATANMAMIS
    for s in gecerli:
        if (s.get('rol') or '').upper() == 'ANA':
            ana_adi = _sorumlu_gorunen_ad(con, s['kullanici_id'], s.get('kullanici_adi')) or SORUMLU_ATANMAMIS
            break
    else:
        if gecerli:
            s0 = gecerli[0]
            ana_adi = _sorumlu_gorunen_ad(con, s0['kullanici_id'], s0.get('kullanici_adi')) or SORUMLU_ATANMAMIS

    return {
        'ana_adi': ana_adi,
        'liste': liste,
    }


def load_cari_kart(
    con: sqlite3.Connection,
    cari_id: int,
    kullanici_id: int,
    yk: set[str] | None,
) -> dict[str, Any]:
    """Cari Kart shell verisi — ağır modül sorgusu yok."""
    try:
        cid = int(cari_id)
    except (TypeError, ValueError):
        raise Cari360KartError('Geçersiz cari id.', 400)
    if cid <= 0:
        raise Cari360KartError('Geçersiz cari id.', 400)

    if not can_view_cari(con, kullanici_id, cid, yk):
        raise Cari360KartError('Bu cari için görüntüleme yetkiniz yok.', 403)

    assert_cari_yetkili_schema(con)

    cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_cari)').fetchall()}
    base = ['id', 'cari_kod', 'unvan', 'aktif', 'created_at', 'updated_at']
    extra = [c for c in GENEL_EDIT_FIELDS if c in cols]
    sel = base + extra
    row = con.execute(
        f"SELECT {', '.join(sel)} FROM nexgen_cari WHERE id=?",
        (cid,),
    ).fetchone()
    if not row:
        raise Cari360KartError('Cari bulunamadı.', 404)

    cari_kod = row['cari_kod'] or ''
    unvan = row['unvan'] or ''
    es_durum = _eslestirme_durumu(con, cid, cari_kod, unvan)
    test_cari = is_test_kayit(cari_kod, unvan)
    # FAZ-3C: V1 tek sorumlu politikası (timeline/ops ile aynı)
    tek = resolve_tek_sorumlu(con, cid)
    sorumlu = _sorumlu_ozet(con, cid)  # legacy liste (YEDEK görünmez V1 ana adında)
    if tek.get('sorumlu'):
        sorumlu_adi = (tek['sorumlu'].get('ad_soyad') or tek['sorumlu'].get('kullanici_adi') or '').strip() or SORUMLU_ATANMAMIS
    else:
        sorumlu_adi = SORUMLU_ATANMAMIS

    def _g(name, default=None):
        if name not in row.keys():
            return default
        return row[name]

    tip = (_g('cari_tipi') or '').strip().upper()
    yurt = (_g('yurt_durumu') or '').strip().upper()

    cari = {
        'id': int(row['id']),
        'cari_kod': cari_kod,
        'unvan': unvan,
        'aktif': int(row['aktif'] or 0),
        'created_at': _fmt_dt(row['created_at']) or '—',
        'updated_at': _fmt_dt(row['updated_at']) or '—',
        'kisa_ad': _g('kisa_ad'),
        'cari_tipi': tip or None,
        'cari_tipi_label': _CARI_TIPI_LABEL.get(tip),
        'kategori': _g('kategori'),
        'yurt_durumu': yurt or None,
        'yurt_durumu_label': _YURT_LABEL.get(yurt),
        'vergi_dairesi': _g('vergi_dairesi'),
        'vergi_no': _g('vergi_no'),
        'tc_kimlik_no': _g('tc_kimlik_no'),
        'ticaret_sicil_no': _g('ticaret_sicil_no'),
        'mersis_no': _g('mersis_no'),
        'e_fatura_mukellefi': _g('e_fatura_mukellefi'),
        'e_irsaliye_mukellefi': _g('e_irsaliye_mukellefi'),
        'telefon': _g('telefon'),
        'telefon2': _g('telefon2'),
        'eposta': _g('eposta'),
        'web': _g('web'),
        'kep': _g('kep'),
        'fax': _g('fax'),
        'ulke': _g('ulke'),
        'sehir': _g('sehir'),
        'ilce': _g('ilce'),
        'acik_adres': _g('acik_adres'),
        'para_birimi': _g('para_birimi'),
        'odeme_vadesi_gun': _g('odeme_vadesi_gun'),
        'fiyat_grubu': _g('fiyat_grubu'),
        'iskonto_orani': _g('iskonto_orani'),
        'minimum_siparis_kg': _g('minimum_siparis_kg'),
        'teslim_sekli': _g('teslim_sekli'),
        'dil': _g('dil'),
    }

    return {
        'cari': cari,
        'sorumlu_adi': sorumlu_adi,
        'sorumlular': sorumlu['liste'],
        # FAZ-3C opsiyonel — V1 tek sorumlu
        'sorumlu': tek.get('sorumlu'),
        'sorumlu_atanmamis': bool(tek.get('sorumlu_atanmamis')),
        'sorumlu_uyarilari': tek.get('sorumlu_uyarilari') or [],
        'eslestirme_durumu': es_durum,
        'test_cari': test_cari,
        'test_banner': False,
        'can_write_yetkili': can_write_yetkili(con, kullanici_id, cid, yk),
        'can_write_gorusme': can_mo_gorusme_yaz(con, kullanici_id, cid, yk),
        'can_edit_genel': can_edit_cari_genel(con, kullanici_id, cid, yk),
    }
