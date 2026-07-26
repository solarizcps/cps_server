# -*- coding: utf-8 -*-
"""Finans Belgesi repository — DB okuma/yazma, audit append."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from modules.nexgen.finans_belgesi_config import (
    DURUM_GECIS,
    DURUMLAR,
    POSTING_DURUM_BEKLIYOR,
    POSTING_DURUM_BASARISIZ,
    POSTING_DURUM_HAZIR,
    POSTING_DURUM_POST_EDILDI,
    POSTING_DURUM_VALIDASYON_HATASI,
)


class FinansBelgesiError(Exception):
    def __init__(self, mesaj: str, kod: int = 400, hata_kodu: str | None = None):
        self.mesaj = mesaj
        self.kod = kod
        self.hata_kodu = hata_kodu
        super().__init__(mesaj)


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def tablo_var(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def belge_kodu_uret(con: sqlite3.Connection) -> str:
    yil = datetime.now().year
    prefix = f'FBL-{yil}-'
    row = con.execute(
        "SELECT belge_kodu FROM finans_belgesi WHERE belge_kodu LIKE ? ORDER BY id DESC LIMIT 1",
        (prefix + '%',),
    ).fetchone()
    son = 0
    if row and row['belge_kodu']:
        try:
            son = int(str(row['belge_kodu']).split('-')[-1])
        except ValueError:
            son = 0
    return f'{prefix}{son + 1:04d}'


def _kolon_var(con: sqlite3.Connection, kolon: str) -> bool:
    if not tablo_var(con, 'finans_belgesi'):
        return False
    return kolon in [c[1] for c in con.execute('PRAGMA table_info(finans_belgesi)').fetchall()]


def get_by_kaynak(
    con: sqlite3.Connection,
    belge_tipi: str,
    kaynak_tipi: str,
    kaynak_id: int,
) -> dict[str, Any] | None:
    if not _kolon_var(con, 'kaynak_tipi'):
        return None
    row = con.execute(
        """
        SELECT * FROM finans_belgesi
        WHERE belge_tipi=? AND kaynak_tipi=? AND kaynak_id=? AND aktif=1
        """,
        (belge_tipi, kaynak_tipi, int(kaynak_id)),
    ).fetchone()
    return dict(row) if row else None


def get_by_posting_idempotency(con: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    if not _kolon_var(con, 'posting_idempotency_key'):
        return None
    row = con.execute(
        'SELECT * FROM finans_belgesi WHERE posting_idempotency_key=? AND aktif=1', (key,),
    ).fetchone()
    return dict(row) if row else None


def get_by_id(con: sqlite3.Connection, belge_id: int) -> dict[str, Any]:
    row = con.execute(
        'SELECT * FROM finans_belgesi WHERE id=? AND aktif=1', (belge_id,)
    ).fetchone()
    if not row:
        raise FinansBelgesiError('Finans belgesi bulunamadı.', 404, 'BELGE_YOK')
    return dict(row)


def get_by_idempotency(con: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    row = con.execute(
        'SELECT * FROM finans_belgesi WHERE idempotency_key=? AND aktif=1', (key,)
    ).fetchone()
    return dict(row) if row else None


def get_by_sevkiyat(con: sqlite3.Connection, sevkiyat_id: int) -> dict[str, Any] | None:
    row = con.execute(
        'SELECT * FROM finans_belgesi WHERE sevkiyat_id=? AND aktif=1', (sevkiyat_id,)
    ).fetchone()
    return dict(row) if row else None


def get_by_tahsilat(con: sqlite3.Connection, tahsilat_kayit_id: int) -> dict[str, Any] | None:
    row = con.execute(
        'SELECT * FROM finans_belgesi WHERE tahsilat_kayit_id=? AND aktif=1', (tahsilat_kayit_id,)
    ).fetchone()
    return dict(row) if row else None


def audit_append(
    con: sqlite3.Connection,
    belge_id: int,
    olay: str,
    *,
    onceki_durum: str | None = None,
    yeni_durum: str | None = None,
    kullanici_id: int | None = None,
    kullanici_ad: str | None = None,
    kaynak_tipi: str | None = None,
    kaynak_id: int | None = None,
    aciklama: str | None = None,
    ek: dict | None = None,
) -> None:
    row = con.execute('SELECT audit_json FROM finans_belgesi WHERE id=?', (belge_id,)).fetchone()
    if not row:
        raise FinansBelgesiError('Finans belgesi bulunamadı.', 404)
    try:
        audit = json.loads(row['audit_json'] or '[]')
    except (TypeError, json.JSONDecodeError):
        audit = []
    kayit = {
        'olay': olay,
        'onceki_durum': onceki_durum,
        'yeni_durum': yeni_durum,
        'kullanici_id': kullanici_id,
        'kullanici_ad': kullanici_ad,
        'tarih': _now(),
        'kaynak_tipi': kaynak_tipi,
        'kaynak_id': kaynak_id,
        'finans_belge_id': belge_id,
        'aciklama': aciklama,
    }
    if ek:
        kayit['ek'] = ek
    audit.append(kayit)
    con.execute(
        'UPDATE finans_belgesi SET audit_json=?, guncelleme_tarihi=? WHERE id=?',
        (json.dumps(audit, ensure_ascii=False), _now(), belge_id),
    )


def durum_guncelle(
    con: sqlite3.Connection,
    belge_id: int,
    yeni_durum: str,
    *,
    kullanici_id: int | None = None,
    kullanici_ad: str | None = None,
    olay: str,
    kaynak_tipi: str | None = None,
    kaynak_id: int | None = None,
    aciklama: str | None = None,
    ek_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    belge = get_by_id(con, belge_id)
    mevcut = (belge.get('durum') or '').upper()
    yeni = (yeni_durum or '').upper()
    if yeni not in DURUMLAR:
        raise FinansBelgesiError('Geçersiz durum.', 400, 'GECERSIZ_DURUM')
    if yeni not in DURUM_GECIS.get(mevcut, frozenset()):
        raise FinansBelgesiError(
            f'{mevcut} → {yeni} geçişi yapılamaz.', 409, 'GECERSIZ_GECIS',
        )
    updates: dict[str, Any] = {'durum': yeni, 'guncelleme_tarihi': _now()}
    if ek_updates:
        updates.update(ek_updates)
    set_sql = ', '.join(f'{k}=?' for k in updates)
    con.execute(
        f'UPDATE finans_belgesi SET {set_sql} WHERE id=?',
        [*updates.values(), belge_id],
    )
    audit_append(
        con, belge_id, olay,
        onceki_durum=mevcut, yeni_durum=yeni,
        kullanici_id=kullanici_id, kullanici_ad=kullanici_ad,
        kaynak_tipi=kaynak_tipi, kaynak_id=kaynak_id, aciklama=aciklama,
    )
    return get_by_id(con, belge_id)


def insert_belge(con: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    cols = [
        'belge_kodu', 'belge_tipi', 'durum', 'sevkiyat_id', 'tahsilat_kayit_id',
        'siparis_id', 'cari_id', 'cari_kart_ckod', 'kaynak_no', 'siparis_no',
        'cari_unvan', 'irsaliye_no', 'islem_tarihi', 'toplam_kg', 'birim_fiyat',
        'para_birimi', 'toplam_tutar', 'vade_gun', 'vade_tarihi',
        'idempotency_key', 'olusturan_id', 'olusturma_tarihi', 'guncelleme_tarihi',
        'audit_json', 'aktif',
    ]
    if _kolon_var(con, 'kaynak_tipi'):
        cols.extend([
            'kaynak_tipi', 'kaynak_id', 'siparis_kalem_id', 'posting_durumu',
        ])
        if data.get('posting_durumu') is None:
            data['posting_durumu'] = POSTING_DURUM_BEKLIYOR
    vals = [data.get(c) for c in cols]
    if vals[cols.index('olusturma_tarihi')] is None:
        vals[cols.index('olusturma_tarihi')] = _now()
    if vals[cols.index('guncelleme_tarihi')] is None:
        vals[cols.index('guncelleme_tarihi')] = _now()
    cur = con.execute(
        f"INSERT INTO finans_belgesi ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        vals,
    )
    bid = int(cur.lastrowid)
    audit_append(
        con, bid, data.get('_olay') or 'BELGE_OLUSTURULDU',
        onceki_durum=None, yeni_durum=data.get('durum'),
        kullanici_id=data.get('olusturan_id'),
        kullanici_ad=data.get('_kullanici_ad'),
        kaynak_tipi=data.get('kaynak_tipi') or data.get('_kaynak_tipi'),
        kaynak_id=data.get('kaynak_id') or data.get('_kaynak_id'),
        aciklama=data.get('_aciklama'),
        ek=data.get('_audit_ek'),
    )
    return get_by_id(con, bid)


def posting_isaretle(
    con: sqlite3.Connection,
    belge_id: int,
    *,
    dry_run: bool,
    kullanici_id: int,
    kullanici_ad: str | None = None,
    cari_har_id: int | None = None,
    belge_no: str | None = None,
    posting_idempotency_key: str | None = None,
    posting_hata: str | None = None,
    olay: str,
    aciklama: str | None = None,
) -> dict[str, Any]:
    """Posting alanlarını günceller. dry_run: workflow durumu değişmez."""
    from modules.nexgen.finans_belgesi_config import DURUM_POST_EDILDI

    belge = get_by_id(con, belge_id)
    onceki_post = belge.get('posting_durumu')
    updates: dict[str, Any] = {'guncelleme_tarihi': _now()}

    if dry_run:
        updates['posting_durumu'] = POSTING_DURUM_HAZIR
    elif posting_hata:
        updates['posting_durumu'] = POSTING_DURUM_BASARISIZ
        updates['posting_hata'] = posting_hata
    else:
        updates['posting_durumu'] = POSTING_DURUM_POST_EDILDI
        updates['posting_tarihi'] = _now()
        updates['posting_kullanici_id'] = kullanici_id
        if posting_idempotency_key:
            updates['posting_idempotency_key'] = posting_idempotency_key
        if cari_har_id is not None:
            updates['cari_har_id'] = cari_har_id
        if belge_no:
            updates['cari_har_belge_no'] = belge_no
        updates['durum'] = DURUM_POST_EDILDI

    if _kolon_var(con, 'posting_durumu'):
        set_sql = ', '.join(f'{k}=?' for k in updates)
        con.execute(
            f'UPDATE finans_belgesi SET {set_sql} WHERE id=?',
            [*updates.values(), belge_id],
        )

    audit_append(
        con, belge_id, olay,
        onceki_durum=belge.get('durum'),
        yeni_durum=updates.get('durum', belge.get('durum')),
        kullanici_id=kullanici_id,
        kullanici_ad=kullanici_ad,
        aciklama=aciklama,
        ek={
            'posting_durumu_onceki': onceki_post,
            'posting_durumu_yeni': updates.get('posting_durumu'),
            'dry_run': dry_run,
        },
    )
    return get_by_id(con, belge_id)


def posting_durumu_dogrula_post(con: sqlite3.Connection, belge: dict[str, Any]) -> None:
    """Posting öncesi posting_durumu kontrolü."""
    if not _kolon_var(con, 'posting_durumu'):
        if belge.get('cari_har_id'):
            raise FinansBelgesiError('Duplicate posting engellendi.', 409, 'POST_DUPLICATE')
        return
    pd = (belge.get('posting_durumu') or POSTING_DURUM_BEKLIYOR).upper()
    if pd == POSTING_DURUM_POST_EDILDI or belge.get('cari_har_id'):
        raise FinansBelgesiError('Duplicate posting engellendi.', 409, 'POST_DUPLICATE')


def posting_idempotency_dogrula(
    con: sqlite3.Connection,
    key: str,
    belge_id: int,
) -> None:
    if not _kolon_var(con, 'posting_idempotency_key'):
        return
    mevcut = get_by_posting_idempotency(con, key)
    if mevcut and int(mevcut['id']) != int(belge_id):
        raise FinansBelgesiError(
            'Posting idempotency çakışması.', 409, 'POST_IDEMPOTENCY_CAKISMA',
        )


def resolve_golden_cari_kart(con: sqlite3.Connection, cari_id: int) -> str:
    """nexgen_cari → cari_eslestirme → Cari_Kart.CKod. Posting öncesi zorunlu."""
    if not tablo_var(con, 'cari_eslestirme'):
        raise FinansBelgesiError('Cari eşleştirme tablosu yok.', 503, 'ESLESME_TABLO_YOK')
    rows = con.execute(
        """
        SELECT cari_kart_ckod, eslestirme_durumu
        FROM cari_eslestirme
        WHERE nexgen_cari_id=? AND aktif=1 AND cari_kart_ckod IS NOT NULL AND cari_kart_ckod != ''
        """,
        (cari_id,),
    ).fetchall()
    if not rows:
        raise FinansBelgesiError(
            'Golden cari eşleşmesi bulunamadı.', 409, 'CARI_ESLESME_YOK',
        )
    if len(rows) > 1:
        kodlar = {r['cari_kart_ckod'] for r in rows}
        if len(kodlar) > 1:
            raise FinansBelgesiError(
                'Birden fazla cari eşleşmesi — posting engellendi.', 409, 'CARI_ESLESME_CAKISMA',
            )
    ckod = rows[0]['cari_kart_ckod']
    durum = (rows[0]['eslestirme_durumu'] or '').upper()
    if durum not in ('DOGRULANDI', 'MANUEL'):
        raise FinansBelgesiError(
            f'Cari eşleşmesi doğrulanmamış ({durum}).', 409, 'CARI_ESLESME_DOGRULANMADI',
        )
    ck = con.execute('SELECT CKod FROM Cari_Kart WHERE CKod=?', (ckod,)).fetchone()
    if not ck:
        raise FinansBelgesiError(
            f'Cari_Kart kaydı bulunamadı: {ckod}', 409, 'CARI_KART_YOK',
        )
    return ckod
