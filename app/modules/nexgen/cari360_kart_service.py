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
from modules.nexgen.cari_yetkili_service import can_write_yetkili
from modules.nexgen.finans_cari_provision_service import is_test_kayit

SORUMLU_ATANMAMIS = 'Atanmamış'


class Cari360KartError(Exception):
    def __init__(self, mesaj: str, kod: int = 400):
        self.mesaj = mesaj
        self.kod = kod
        super().__init__(mesaj)


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
    if not can_view_cari(con, kullanici_id, cari_id, yk):
        raise Cari360KartError('Bu cari için görüntüleme yetkiniz yok.', 403)

    assert_cari_yetkili_schema(con)

    row = con.execute(
        'SELECT id, cari_kod, unvan, aktif, created_at, updated_at '
        'FROM nexgen_cari WHERE id=?',
        (cari_id,),
    ).fetchone()
    if not row:
        raise Cari360KartError('Cari bulunamadı.', 404)

    cari_kod = row['cari_kod'] or ''
    unvan = row['unvan'] or ''
    es_durum = _eslestirme_durumu(con, cari_id, cari_kod, unvan)
    test_cari = is_test_kayit(cari_kod, unvan)
    sorumlu = _sorumlu_ozet(con, cari_id)

    return {
        'cari': {
            'id': int(row['id']),
            'cari_kod': cari_kod,
            'unvan': unvan,
            'aktif': int(row['aktif'] or 0),
            'created_at': row['created_at'],
            'updated_at': row['updated_at'],
        },
        'sorumlu_adi': sorumlu['ana_adi'],
        'sorumlular': sorumlu['liste'],
        'eslestirme_durumu': es_durum,
        'test_cari': test_cari,
        'test_banner': bool(test_cari and es_durum == 'TEST_NO_LINK'),
        'can_write_yetkili': can_write_yetkili(con, kullanici_id, cari_id, yk),
    }
