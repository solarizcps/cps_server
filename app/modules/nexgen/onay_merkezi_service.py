# -*- coding: utf-8 -*-
"""
Merkezi Onay MVP servisi — F1D.
Fiziksel silme yok. Idempotency zorunlu.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from typing import Any

TALEP_TIPLERI = ('SATIS_SIPARISI', 'SATIN_ALMA_SIPARISI', 'NUMUNE_TALEBI', 'TAHSILAT_KAYDI')
DURUM_BEKLIYOR = ('BEKLIYOR', 'BEKLETILDI')
KARAR_ONAYLA = 'ONAYLA'
KARAR_REVIZYON = 'REVIZYON'
KARAR_REDDET = 'REDDET'
KARAR_BEKLET = 'BEKLET'

SHADOW_OLAYLAR = (
    'ONAY_TALEBI_OLUSTU',
    'ONAY_TALEBI_ONAYLANDI',
    'ONAY_TALEBI_REDDEDILDI',
    'ONAY_TALEBI_REVIZYON',
    'SATIS_SIPARISI_ONAYLANDI',
    'SATIN_ALMA_ONAYLANDI',
)


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _tablo_var(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def talep_kod_uret(con) -> str:
    yil = datetime.now().year
    prefix = f'ON-{yil}-'
    row = con.execute(
        "SELECT talep_kod FROM onay_talep WHERE talep_kod LIKE ? ORDER BY id DESC LIMIT 1",
        (prefix + '%',),
    ).fetchone()
    son = 0
    if row and row['talep_kod']:
        try:
            son = int(str(row['talep_kod']).split('-')[-1])
        except ValueError:
            son = 0
    return f'{prefix}{son + 1:04d}'


def adapter_log(
    con,
    *,
    talep_id: int | None,
    adapter_kodu: str,
    kaynak_modul: str,
    islem: str,
    sonuc: str,
    hata: str | None = None,
    payload: dict | None = None,
) -> None:
    if not _tablo_var(con, 'onay_adapter_log'):
        return
    con.execute(
        """
        INSERT INTO onay_adapter_log
            (talep_id, adapter_kodu, kaynak_modul, islem, sonuc, hata_mesaji, payload_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            talep_id, adapter_kodu, kaynak_modul, islem, sonuc, hata,
            json.dumps(payload, ensure_ascii=False) if payload else None,
        ),
    )


def shadow_olay(con, kod: str, payload: dict) -> None:
    adapter_log(
        con,
        talep_id=payload.get('talep_id'),
        adapter_kodu='SHADOW_OLAY',
        kaynak_modul=payload.get('kaynak_modul', ''),
        islem=kod,
        sonuc='OK',
        payload=payload,
    )


def aktif_talep_var(con, kaynak_modul: str, kaynak_id: int, talep_tipi: str) -> bool:
    row = con.execute(
        """
        SELECT 1 FROM onay_talep
        WHERE kaynak_modul=? AND kaynak_id=? AND talep_tipi=?
          AND aktif=1 AND durum IN ('BEKLIYOR','BEKLETILDI')
        """,
        (kaynak_modul, kaynak_id, talep_tipi),
    ).fetchone()
    return bool(row)


def talep_getir(con, talep_id: int) -> dict | None:
    row = con.execute('SELECT * FROM onay_talep WHERE id=?', (talep_id,)).fetchone()
    return dict(row) if row else None


def adimlar_getir(con, talep_id: int) -> list[dict]:
    rows = con.execute(
        """
        SELECT * FROM onay_talep_adim WHERE talep_id=?
        ORDER BY sira
        """,
        (talep_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _bekleyen_adim(con, talep_id: int) -> dict | None:
    row = con.execute(
        """
        SELECT * FROM onay_talep_adim
        WHERE talep_id=? AND durum='BEKLIYOR'
        ORDER BY sira LIMIT 1
        """,
        (talep_id,),
    ).fetchone()
    return dict(row) if row else None


def _kademe_yetki_kodu(kademe: str, talep_tipi: str) -> str:
    if talep_tipi == 'TAHSILAT_KAYDI':
        return 'onay.finans.karar'
    if talep_tipi == 'NUMUNE_TALEBI':
        return 'onay.merkez.karar'
    if kademe == 'K2':
        return 'onay.finans.karar'
    if kademe in ('K3', 'K4'):
        return 'onay.yonetim.karar'
    if talep_tipi == 'SATIN_ALMA_SIPARISI':
        return 'onay.satinalma.karar'
    return 'onay.satis.karar'


def kullanici_karar_yetkisi(yk: set[str], kademe: str, talep_tipi: str) -> bool:
    if '*' in yk:
        return True
    kod = _kademe_yetki_kodu(kademe, talep_tipi)
    return f'{kod}:can_approve' in yk or f'{kod}:can_manage' in yk or 'onay.merkez.karar:can_approve' in yk


def talep_olustur(
    con,
    *,
    talep_tipi: str,
    kaynak_modul: str,
    kaynak_id: int,
    kaynak_kod: str,
    talep_eden_id: int,
    snapshot: dict,
    etki: dict | None = None,
    cari_id: int | None = None,
    cari_unvan: str | None = None,
    tutar: float | None = None,
    para_birimi: str | None = None,
    vade_gun: int | None = None,
    idempotency_key: str,
    adimlar: list[dict],
    revizyon_no: int = 1,
) -> dict[str, Any]:
    if aktif_talep_var(con, kaynak_modul, kaynak_id, talep_tipi):
        return {'ok': False, 'hata': 'Aktif onay talebi zaten var.', 'code': 'DUPLICATE'}

    dup = con.execute(
        'SELECT id FROM onay_talep WHERE idempotency_key=?', (idempotency_key,)
    ).fetchone()
    if dup:
        return {'ok': False, 'hata': 'Idempotency ihlali.', 'code': 'IDEMPOTENCY'}

    kod = talep_kod_uret(con)
    ts = _now()
    snap_json = json.dumps(snapshot, ensure_ascii=False)
    con.execute(
        """
        INSERT INTO onay_talep
            (talep_kod, talep_tipi, kaynak_modul, kaynak_id, kaynak_kod,
             cari_id, cari_unvan_snapshot, talep_eden_id, talep_tarihi,
             durum, aktif_kademe, tutar, para_birimi, vade_gun,
             snapshot_json, etki_onizleme_json, idempotency_key, revizyon_no,
             created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,'BEKLIYOR',?,?,?,?,?,?,?,?,?,?)
        """,
        (
            kod, talep_tipi, kaynak_modul, kaynak_id, kaynak_kod,
            cari_id, cari_unvan, talep_eden_id, ts,
            adimlar[0]['kademe'] if adimlar else 'K2',
            tutar, para_birimi, vade_gun,
            snap_json,
            json.dumps(etki or {}, ensure_ascii=False),
            idempotency_key, revizyon_no, ts, ts,
        ),
    )
    tid = int(con.execute('SELECT last_insert_rowid()').fetchone()[0])
    for a in adimlar:
        con.execute(
            """
            INSERT INTO onay_talep_adim
                (talep_id, sira, adim_tipi, kademe, rol_adi, durum, created_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (tid, a['sira'], a['adim_tipi'], a['kademe'], a.get('rol_adi'), a.get('durum', 'BEKLIYOR'), ts),
        )
    shadow_olay(con, 'ONAY_TALEBI_OLUSTU', {
        'talep_id': tid, 'talep_kod': kod, 'talep_tipi': talep_tipi,
        'kaynak_modul': kaynak_modul, 'kaynak_id': kaynak_id,
    })
    return {'ok': True, 'talep_id': tid, 'talep_kod': kod}


def karar_ver(
    con,
    talep_id: int,
    kullanici_id: int,
    kullanici_ad: str,
    karar: str,
    notu: str,
    yk: set[str],
) -> dict[str, Any]:
    if karar in (KARAR_REVIZYON, KARAR_REDDET) and not (notu or '').strip():
        return {'ok': False, 'hata': 'Revizyon/Red için not zorunlu.'}

    talep = talep_getir(con, talep_id)
    if not talep or talep['durum'] not in DURUM_BEKLIYOR:
        return {'ok': False, 'hata': 'Talep karar için uygun değil.'}

    adim = _bekleyen_adim(con, talep_id)
    if not adim:
        return {'ok': False, 'hata': 'Bekleyen adım yok.'}

    if talep['talep_eden_id'] == kullanici_id and karar == KARAR_ONAYLA:
        return {'ok': False, 'hata': 'Talep sahibi kendi talebini onaylayamaz.'}

    if not kullanici_karar_yetkisi(yk, adim['kademe'], talep['talep_tipi']):
        return {'ok': False, 'hata': 'Bu adım için yetkiniz yok.'}

    ts = _now()
    adim_durum = {
        KARAR_ONAYLA: 'TAMAMLANDI',
        KARAR_REVIZYON: 'REVIZYON',
        KARAR_REDDET: 'REDDEDILDI',
        KARAR_BEKLET: 'BEKLETILDI',
    }[karar]

    con.execute(
        """
        UPDATE onay_talep_adim
        SET durum=?, karar_notu=?, tarih=?, kullanici_id=?, kullanici_ad_snapshot=?
        WHERE id=?
        """,
        (adim_durum, notu, ts, kullanici_id, kullanici_ad, adim['id']),
    )

    if karar == KARAR_ONAYLA:
        sonraki = con.execute(
            """
            SELECT id, kademe FROM onay_talep_adim
            WHERE talep_id=? AND durum='BEKLIYOR' AND sira > ?
            ORDER BY sira LIMIT 1
            """,
            (talep_id, adim['sira']),
        ).fetchone()
        if sonraki:
            con.execute(
                """
                UPDATE onay_talep SET aktif_kademe=?, updated_at=? WHERE id=?
                """,
                (sonraki['kademe'], ts, talep_id),
            )
            return {'ok': True, 'durum': 'BEKLIYOR', 'aktif_kademe': sonraki['kademe']}

        con.execute(
            """
            UPDATE onay_talep SET durum='ONAYLANDI', aktif_kademe=NULL, updated_at=?
            WHERE id=?
            """,
            (ts, talep_id),
        )
        shadow_olay(con, 'ONAY_TALEBI_ONAYLANDI', {'talep_id': talep_id})
        return {'ok': True, 'durum': 'ONAYLANDI', 'tamamlandi': True}

    if karar == KARAR_REVIZYON:
        con.execute(
            "UPDATE onay_talep SET durum='REVIZYON', aktif=0, updated_at=? WHERE id=?",
            (ts, talep_id),
        )
        shadow_olay(con, 'ONAY_TALEBI_REVIZYON', {'talep_id': talep_id, 'not': notu})
        return {'ok': True, 'durum': 'REVIZYON', 'tamamlandi': True}

    if karar == KARAR_REDDET:
        con.execute(
            "UPDATE onay_talep SET durum='REDDEDILDI', aktif=0, updated_at=? WHERE id=?",
            (ts, talep_id),
        )
        shadow_olay(con, 'ONAY_TALEBI_REDDEDILDI', {'talep_id': talep_id, 'not': notu})
        return {'ok': True, 'durum': 'REDDEDILDI', 'tamamlandi': True}

    con.execute(
        "UPDATE onay_talep SET durum='BEKLETILDI', updated_at=? WHERE id=?",
        (ts, talep_id),
    )
    return {'ok': True, 'durum': 'BEKLETILDI'}


def liste_filtre(con, talep_tipi: str | None = None, durum: str | None = None) -> list[dict]:
    sql = """
        SELECT t.*, sk.KullaniciAdi AS talep_eden_ad
        FROM onay_talep t
        LEFT JOIN sistem_kullanici sk ON sk.Id = t.talep_eden_id
        WHERE t.aktif=1
    """
    params: list[Any] = []
    if talep_tipi:
        sql += ' AND t.talep_tipi=?'
        params.append(talep_tipi)
    if durum:
        sql += ' AND t.durum=?'
        params.append(durum)
    else:
        sql += " AND t.durum IN ('BEKLIYOR','BEKLETILDI','ONAYLANDI','REVIZYON','REDDEDILDI')"
    sql += ' ORDER BY t.id DESC LIMIT 100'
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def snapshot_hash(snapshot: dict) -> str:
    raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()
