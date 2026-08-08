# -*- coding: utf-8 -*-
"""
NexGen Onay Merkezi — genel omurga (V1).

V1'de yalnız MUSTERI_TEMSILCISI_TALEP bağlıdır.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from modules.nexgen.cari360_yetki import _yk_has, can_cari360_view_all

TABLO = 'nexgen_onay'
TABLO_MTT = 'nexgen_musteri_temsilcisi_talep'

KAYNAK_MUSTERI_TEMSILCISI_TALEP = 'MUSTERI_TEMSILCISI_TALEP'
ONAY_TURU_OLUSTURMA = 'OLUSTURMA'
ONAY_TURU_NUMUNE_TALEBI = 'NUMUNE_TALEBI_ONAY'
ONAY_TURU_SIPARIS_TALEBI = 'SIPARIS_TALEBI_ONAY'

KAYNAK_TURLERI = frozenset({
    'MUSTERI_TEMSILCISI_TALEP',
    'SIPARIS', 'NUMUNE', 'TAHSILAT', 'CEK',
    'MUHASEBE', 'SATINALMA', 'FIYAT',
})
DURUMLAR = frozenset({'ONAY_BEKLIYOR', 'ONAYLANDI', 'REDDEDILDI', 'IPTAL'})
DURUM_ETIKET = {
    'ONAY_BEKLIYOR': 'Onay Bekliyor',
    'ONAYLANDI': 'Onaylandı',
    'REDDEDILDI': 'Reddedildi',
    'IPTAL': 'İptal',
}
KAYNAK_ETIKET = {
    'MUSTERI_TEMSILCISI_TALEP': 'Müşteri Temsilcisi Talebi',
    'SIPARIS': 'Sipariş',
    'NUMUNE': 'Numune',
    'TAHSILAT': 'Tahsilat',
    'CEK': 'Çek',
    'MUHASEBE': 'Muhasebe',
    'SATINALMA': 'Satın Alma',
    'FIYAT': 'Fiyat',
}

MAX_ONAY_NO_RETRY = 8


class OnayError(Exception):
    def __init__(self, mesaj: str, kod: int = 400, ekstra: dict | None = None):
        self.mesaj = mesaj
        self.kod = kod
        self.ekstra = ekstra or {}
        super().__init__(mesaj)


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _tablo_var(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def can_onay_karar(yk: set[str] | frozenset[str] | None) -> bool:
    """Yalnız Yönetici/Admin — Mehmet ve pazarlamacı veremez."""
    if not yk:
        return False
    if '*' in yk:
        return True
    if can_cari360_view_all(yk):
        return True
    if _yk_has(yk, 'nexgen.yonetim.manage', 'can_approve'):
        return True
    if _yk_has(yk, 'nexgen.yonetim.manage', 'can_manage'):
        return True
    if _yk_has(yk, 'nexgen.yonetim.manage', 'can_update'):
        return True
    return False


def can_onay_liste_gor(yk: set[str] | frozenset[str] | None) -> bool:
    if not yk:
        return False
    if '*' in yk:
        return True
    if can_cari360_view_all(yk):
        return True
    return _yk_has(yk, 'nexgen.yonetim.manage', 'can_view')


def _uret_onay_no(con: sqlite3.Connection) -> str:
    yil = datetime.now().year
    prefix = f'ONY-{yil}-'
    row = con.execute(
        f"SELECT onay_no FROM {TABLO} WHERE onay_no LIKE ? ORDER BY id DESC LIMIT 1",
        (prefix + '%',),
    ).fetchone()
    n = 1
    if row and row['onay_no']:
        try:
            n = int(str(row['onay_no']).split('-')[-1]) + 1
        except (TypeError, ValueError):
            n = 1
    return f'{prefix}{n:04d}'


def _row_dict(row) -> dict:
    if row is None:
        return {}
    return {k: row[k] for k in row.keys()}


AKTIF_KAYNAK_UQ = 'uq_nonay_aktif_kaynak'


def ensure_onay_indexes(con: sqlite3.Connection) -> None:
    """
    Aktif onay: aynı (kaynak_turu, kaynak_id) için en fazla bir ONAY_BEKLIYOR.
    Migration 148 tabloyu oluşturduysa sonradan da güvenli eklenir.
    """
    if not _tablo_var(con, TABLO):
        return
    con.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS {AKTIF_KAYNAK_UQ}
        ON {TABLO}(kaynak_turu, kaynak_id)
        WHERE durum = 'ONAY_BEKLIYOR'
        """
    )


def _aktif_kaynak_row(con, kaynak_turu: str, kaynak_id: int):
    return con.execute(
        f"""
        SELECT * FROM {TABLO}
        WHERE kaynak_turu=? AND kaynak_id=? AND durum='ONAY_BEKLIYOR'
        ORDER BY id ASC LIMIT 1
        """,
        (kaynak_turu, int(kaynak_id)),
    ).fetchone()


def _resolve_integrity_conflict(
    con,
    *,
    kaynak_turu: str,
    kaynak_id: int,
    onay_turu: str,
    idem: str,
) -> dict[str, Any] | None:
    """IntegrityError sonrası mevcut kaydı bul. None = henüz yok (ör. onay_no retry)."""
    m = con.execute(
        f'SELECT * FROM {TABLO} WHERE idempotency_key=?', (idem,),
    ).fetchone()
    if m:
        return {'kayit': _row_dict(m), 'idempotent': True}

    u = con.execute(
        f'SELECT * FROM {TABLO} WHERE kaynak_turu=? AND kaynak_id=? AND onay_turu=?',
        (kaynak_turu, int(kaynak_id), onay_turu),
    ).fetchone()
    if u:
        return {'kayit': _row_dict(u), 'idempotent': True}

    aktif = _aktif_kaynak_row(con, kaynak_turu, int(kaynak_id))
    if aktif:
        if (aktif['onay_turu'] or '').upper() == onay_turu:
            return {'kayit': _row_dict(aktif), 'idempotent': True}
        raise OnayError(
            'Bu kaynak için farklı türde aktif onay zaten var.',
            409,
            {
                'mevcut_onay_id': int(aktif['id']),
                'mevcut_onay_turu': aktif['onay_turu'],
                'istenen_onay_turu': onay_turu,
            },
        )
    return None


def onay_olustur(
    con: sqlite3.Connection,
    *,
    kaynak_turu: str,
    kaynak_id: int,
    onay_turu: str,
    olusturan_kullanici_id: int,
    idempotency_key: str,
    aciklama: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """
    Tek duplicate / idempotent business logic.

    - Aynı idempotency_key → idempotent başarı
    - Aynı (kaynak_turu, kaynak_id, onay_turu) → idempotent başarı
    - Aynı kaynakta aktif ONAY_BEKLIYOR + aynı onay_turu → idempotent
    - Aynı kaynakta aktif + farklı onay_turu → 409 Conflict
    """
    if not _tablo_var(con, TABLO):
        raise OnayError('Onay tablosu yok — migration 148 gerekli.', 500)
    try:
        ensure_onay_indexes(con)
    except sqlite3.IntegrityError as e:
        raise OnayError(
            f'Aktif onay UNIQUE uygulanamadı — duplicate temizliği gerekli: {e}',
            500,
        ) from e

    kaynak_turu = (kaynak_turu or '').strip().upper()
    onay_turu = (onay_turu or '').strip().upper()
    idem = (idempotency_key or '').strip()
    if kaynak_turu not in KAYNAK_TURLERI:
        raise OnayError('Geçersiz kaynak_turu.', 400)
    if not onay_turu:
        raise OnayError('onay_turu zorunlu.', 400)
    if not idem:
        raise OnayError('idempotency_key zorunlu.', 400)
    if not kaynak_id:
        raise OnayError('kaynak_id zorunlu.', 400)

    mevcut = con.execute(
        f'SELECT * FROM {TABLO} WHERE idempotency_key=?', (idem,),
    ).fetchone()
    if mevcut:
        return {'kayit': _row_dict(mevcut), 'idempotent': True}

    uniq = con.execute(
        f'SELECT * FROM {TABLO} WHERE kaynak_turu=? AND kaynak_id=? AND onay_turu=?',
        (kaynak_turu, int(kaynak_id), onay_turu),
    ).fetchone()
    if uniq:
        return {'kayit': _row_dict(uniq), 'idempotent': True}

    aktif = _aktif_kaynak_row(con, kaynak_turu, int(kaynak_id))
    if aktif:
        if (aktif['onay_turu'] or '').upper() == onay_turu:
            return {'kayit': _row_dict(aktif), 'idempotent': True}
        raise OnayError(
            'Bu kaynak için farklı türde aktif onay zaten var.',
            409,
            {
                'mevcut_onay_id': int(aktif['id']),
                'mevcut_onay_turu': aktif['onay_turu'],
                'istenen_onay_turu': onay_turu,
            },
        )

    own_tx = False
    if commit:
        try:
            con.execute('BEGIN IMMEDIATE')
            own_tx = True
        except sqlite3.OperationalError:
            pass
    try:
        # TX içinde tekrar kontrol (yarış)
        mevcut2 = con.execute(
            f'SELECT * FROM {TABLO} WHERE idempotency_key=?', (idem,),
        ).fetchone()
        if mevcut2:
            if own_tx:
                con.commit()
            return {'kayit': _row_dict(mevcut2), 'idempotent': True}
        uniq2 = con.execute(
            f'SELECT * FROM {TABLO} WHERE kaynak_turu=? AND kaynak_id=? AND onay_turu=?',
            (kaynak_turu, int(kaynak_id), onay_turu),
        ).fetchone()
        if uniq2:
            if own_tx:
                con.commit()
            return {'kayit': _row_dict(uniq2), 'idempotent': True}
        aktif2 = _aktif_kaynak_row(con, kaynak_turu, int(kaynak_id))
        if aktif2:
            if own_tx:
                con.commit()
            if (aktif2['onay_turu'] or '').upper() == onay_turu:
                return {'kayit': _row_dict(aktif2), 'idempotent': True}
            raise OnayError(
                'Bu kaynak için farklı türde aktif onay zaten var.',
                409,
                {
                    'mevcut_onay_id': int(aktif2['id']),
                    'mevcut_onay_turu': aktif2['onay_turu'],
                    'istenen_onay_turu': onay_turu,
                },
            )

        now = _now()
        onay_id = None
        last_err = None
        for _ in range(MAX_ONAY_NO_RETRY):
            onay_no = _uret_onay_no(con)
            try:
                cur = con.execute(
                    f"""
                    INSERT INTO {TABLO} (
                        onay_no, kaynak_turu, kaynak_id, onay_turu, durum,
                        olusturan_kullanici_id, onaylayan_kullanici_id,
                        red_nedeni, aciklama,
                        created_at, updated_at, karar_tarihi, idempotency_key
                    ) VALUES (
                        ?, ?, ?, ?, 'ONAY_BEKLIYOR',
                        ?, NULL,
                        NULL, ?,
                        ?, ?, NULL, ?
                    )
                    """,
                    (
                        onay_no, kaynak_turu, int(kaynak_id), onay_turu,
                        int(olusturan_kullanici_id),
                        (aciklama or '').strip() or None,
                        now, now, idem,
                    ),
                )
                onay_id = int(cur.lastrowid)
                break
            except sqlite3.IntegrityError as e:
                last_err = e
                resolved = _resolve_integrity_conflict(
                    con,
                    kaynak_turu=kaynak_turu,
                    kaynak_id=int(kaynak_id),
                    onay_turu=onay_turu,
                    idem=idem,
                )
                if resolved is not None:
                    if own_tx:
                        con.commit()
                    return resolved
                # onay_no çakışması — yeni numara dene
                if 'onay_no' in str(e).lower():
                    continue
                raise OnayError(f'Onay kaydı çakıştı: {e}', 409)
        if onay_id is None:
            raise OnayError(f'Onay numarası üretilemedi: {last_err}', 500)
        if own_tx:
            con.commit()
        row = con.execute(f'SELECT * FROM {TABLO} WHERE id=?', (onay_id,)).fetchone()
        return {'kayit': _row_dict(row), 'idempotent': False}
    except OnayError:
        if own_tx:
            try:
                con.rollback()
            except Exception:
                pass
        raise
    except Exception:
        if own_tx:
            try:
                con.rollback()
            except Exception:
                pass
        raise


def onay_turu_for_mtt(talep_turu: str | None) -> str:
    tur = (talep_turu or '').strip().upper()
    if tur == 'NUMUNE':
        return ONAY_TURU_NUMUNE_TALEBI
    if tur == 'SIPARIS':
        return ONAY_TURU_SIPARIS_TALEBI
    return ONAY_TURU_OLUSTURMA


def onay_olustur_mtt(
    con: sqlite3.Connection,
    talep_id: int,
    olusturan_kullanici_id: int,
    mtt_idempotency_key: str,
    *,
    aciklama: str | None = None,
    talep_turu: str | None = None,
    onay_turu: str | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    """MTT oluşturma onayı — duplicate engeli yalnız onay_olustur içinde."""
    tur = (onay_turu or '').strip().upper()
    if not tur:
        tt = (talep_turu or '').strip().upper()
        if not tt and _tablo_var(con, TABLO_MTT):
            row = con.execute(
                f'SELECT talep_turu FROM {TABLO_MTT} WHERE id=?',
                (int(talep_id),),
            ).fetchone()
            if row:
                tt = (row['talep_turu'] or '').strip().upper()
        tur = onay_turu_for_mtt(tt)
    return onay_olustur(
        con,
        kaynak_turu=KAYNAK_MUSTERI_TEMSILCISI_TALEP,
        kaynak_id=int(talep_id),
        onay_turu=tur,
        olusturan_kullanici_id=int(olusturan_kullanici_id),
        idempotency_key=f'ONY-{mtt_idempotency_key}',
        aciklama=aciklama,
        commit=commit,
    )


def _mtt_durum_set(con, talep_id: int, hedef: str, *, beklenen: str) -> None:
    now = _now()
    cur = con.execute(
        f"UPDATE {TABLO_MTT} SET durum=?, updated_at=? WHERE id=? AND durum=?",
        (hedef, now, int(talep_id), beklenen),
    )
    if cur.rowcount != 1:
        raise OnayError(
            f'MTT durum güncellenemedi (beklenen {beklenen}).', 409,
        )


def onay_onayla(
    con: sqlite3.Connection,
    onay_id: int,
    kullanici_id: int,
    yk: set[str] | frozenset[str] | None = None,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    if not can_onay_karar(yk):
        raise OnayError('Onay yetkiniz yok.', 403)
    row = con.execute(f'SELECT * FROM {TABLO} WHERE id=?', (int(onay_id),)).fetchone()
    if not row:
        raise OnayError('Onay bulunamadı.', 404)
    if row['durum'] == 'ONAYLANDI':
        return {'kayit': _enrich_onay(con, _row_dict(row)), 'idempotent': True}
    if row['durum'] != 'ONAY_BEKLIYOR':
        raise OnayError(f'Onay durumu uygun değil: {row["durum"]}', 409)

    own_tx = False
    if commit:
        try:
            con.execute('BEGIN IMMEDIATE')
            own_tx = True
        except sqlite3.OperationalError:
            pass
    try:
        now = _now()
        cur = con.execute(
            f"""
            UPDATE {TABLO}
            SET durum='ONAYLANDI', onaylayan_kullanici_id=?, karar_tarihi=?,
                updated_at=?, red_nedeni=NULL
            WHERE id=? AND durum='ONAY_BEKLIYOR'
            """,
            (int(kullanici_id), now, now, int(onay_id)),
        )
        if cur.rowcount != 1:
            # Eşzamanlı ikinci Onayla — ilk karar kazanır
            row_now = con.execute(
                f'SELECT * FROM {TABLO} WHERE id=?', (int(onay_id),),
            ).fetchone()
            if row_now and row_now['durum'] == 'ONAYLANDI':
                if own_tx:
                    con.commit()
                return {'kayit': _enrich_onay(con, _row_dict(row_now)), 'idempotent': True}
            raise OnayError('Onay çakışması — tekrar deneyin.', 409)

        if row['kaynak_turu'] == KAYNAK_MUSTERI_TEMSILCISI_TALEP:
            _mtt_durum_set(con, int(row['kaynak_id']), 'YENI', beklenen='ONAY_BEKLIYOR')

        if own_tx:
            con.commit()
        row2 = con.execute(f'SELECT * FROM {TABLO} WHERE id=?', (int(onay_id),)).fetchone()
        return {'kayit': _enrich_onay(con, _row_dict(row2)), 'idempotent': False}
    except OnayError:
        if own_tx:
            try:
                con.rollback()
            except Exception:
                pass
        raise
    except Exception:
        if own_tx:
            try:
                con.rollback()
            except Exception:
                pass
        raise


def onay_reddet(
    con: sqlite3.Connection,
    onay_id: int,
    kullanici_id: int,
    red_nedeni: str,
    yk: set[str] | frozenset[str] | None = None,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    if not can_onay_karar(yk):
        raise OnayError('Onay yetkiniz yok.', 403)
    neden = (red_nedeni or '').strip()
    if not neden:
        raise OnayError('red_nedeni zorunlu.', 400)
    row = con.execute(f'SELECT * FROM {TABLO} WHERE id=?', (int(onay_id),)).fetchone()
    if not row:
        raise OnayError('Onay bulunamadı.', 404)
    if row['durum'] == 'REDDEDILDI':
        return {'kayit': _enrich_onay(con, _row_dict(row)), 'idempotent': True}
    if row['durum'] != 'ONAY_BEKLIYOR':
        raise OnayError(f'Onay durumu uygun değil: {row["durum"]}', 409)

    own_tx = False
    if commit:
        try:
            con.execute('BEGIN IMMEDIATE')
            own_tx = True
        except sqlite3.OperationalError:
            pass
    try:
        now = _now()
        cur = con.execute(
            f"""
            UPDATE {TABLO}
            SET durum='REDDEDILDI', onaylayan_kullanici_id=?, karar_tarihi=?,
                red_nedeni=?, updated_at=?
            WHERE id=? AND durum='ONAY_BEKLIYOR'
            """,
            (int(kullanici_id), now, neden, now, int(onay_id)),
        )
        if cur.rowcount != 1:
            raise OnayError('Red çakışması — tekrar deneyin.', 409)

        if row['kaynak_turu'] == KAYNAK_MUSTERI_TEMSILCISI_TALEP:
            # MTT → REDDEDILDI + red_nedeni
            cur2 = con.execute(
                f"""
                UPDATE {TABLO_MTT}
                SET durum='REDDEDILDI', red_nedeni=?, updated_at=?
                WHERE id=? AND durum='ONAY_BEKLIYOR'
                """,
                (neden, now, int(row['kaynak_id'])),
            )
            if cur2.rowcount != 1:
                raise OnayError('MTT red durumu güncellenemedi.', 409)

        if own_tx:
            con.commit()
        row2 = con.execute(f'SELECT * FROM {TABLO} WHERE id=?', (int(onay_id),)).fetchone()
        return {'kayit': _enrich_onay(con, _row_dict(row2)), 'idempotent': False}
    except OnayError:
        if own_tx:
            try:
                con.rollback()
            except Exception:
                pass
        raise
    except Exception:
        if own_tx:
            try:
                con.rollback()
            except Exception:
                pass
        raise


def _kullanici_adi(con, kid) -> str | None:
    if kid in (None, '', 0):
        return None
    try:
        row = con.execute(
            'SELECT AdSoyad, KullaniciAdi FROM sistem_kullanici WHERE Id=?',
            (int(kid),),
        ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    return (row['AdSoyad'] or row['KullaniciAdi'] or '').strip() or None


def _mtt_kalem_ozet(con, talep_id: int) -> dict[str, Any]:
    """Liste/UX için ilk kalem özeti — yeni tablo yok."""
    from modules.nexgen.mtt_donusum_service import miktar_gosterim, urun_ailesi_etiket
    out = {
        'urun_ailesi': None,
        'urun_ailesi_etiket': None,
        'urun_aciklama': None,
        'renk_gosterim': None,
        'miktar_gosterim': '—',
        'verilen_fiyat': None,
        'para_birimi': None,
        'vade_gun': None,
        'odeme_tipi': None,
        'oncelik': None,
    }
    if not talep_id or not _tablo_var(con, TABLO_MTT):
        return out
    try:
        tr = con.execute(
            f'SELECT oncelik FROM {TABLO_MTT} WHERE id=?', (int(talep_id),),
        ).fetchone()
        if tr:
            out['oncelik'] = tr['oncelik']
        kr = con.execute(
            """
            SELECT urun_ailesi, urun_aciklama, renk_id, renk_aciklama, miktar_kg, konusulan_tonaj,
                   verilen_fiyat, para_birimi, vade_gun, odeme_tipi
            FROM nexgen_musteri_temsilcisi_talep_kalem
            WHERE talep_id=?
            ORDER BY sira_no ASC, id ASC LIMIT 1
            """,
            (int(talep_id),),
        ).fetchone()
        if not kr:
            return out
        kd = _row_dict(kr)
        out['urun_ailesi'] = kd.get('urun_ailesi')
        out['urun_ailesi_etiket'] = urun_ailesi_etiket(kd.get('urun_ailesi'))
        out['urun_aciklama'] = kd.get('urun_aciklama')
        from modules.nexgen.musteri_temsilcisi_talep_service import _renk_gosterim
        out['renk_gosterim'] = _renk_gosterim(con, kd.get('renk_id'), kd.get('renk_aciklama'))
        out['miktar_gosterim'] = miktar_gosterim(kd)
        out['verilen_fiyat'] = kd.get('verilen_fiyat')
        out['para_birimi'] = kd.get('para_birimi')
        out['vade_gun'] = kd.get('vade_gun')
        out['odeme_tipi'] = kd.get('odeme_tipi')
    except Exception:
        pass
    return out


def _enrich_onay(con, d: dict) -> dict:
    import re as _re
    d['durum_etiket'] = DURUM_ETIKET.get(d.get('durum') or '', d.get('durum'))
    d['kaynak_etiket'] = KAYNAK_ETIKET.get(d.get('kaynak_turu') or '', d.get('kaynak_turu'))
    d['olusturan_adi'] = _kullanici_adi(con, d.get('olusturan_kullanici_id'))
    d['onaylayan_adi'] = _kullanici_adi(con, d.get('onaylayan_kullanici_id'))
    d['firma_adi'] = None
    d['cari_kod'] = None
    d['talep_turu'] = None
    d['talep_no'] = None
    if d.get('kaynak_turu') == KAYNAK_MUSTERI_TEMSILCISI_TALEP and d.get('kaynak_id'):
        try:
            from modules.nexgen.musteri_temsilcisi_talep_service import talep_detay_getir
            t = talep_detay_getir(con, int(d['kaynak_id']))
            d['firma_adi'] = t.get('firma_adi')
            d['talep_turu'] = t.get('talep_turu')
            d['talep_no'] = t.get('talep_no')
            d['tur_etiket'] = t.get('tur_etiket')
            d['mtt'] = t
            d['oncelik'] = t.get('oncelik')
            # cari_kod (MTT popup için)
            cid = t.get('cari_id')
            if cid:
                try:
                    cr = con.execute('SELECT cari_kod FROM nexgen_cari WHERE id=?', (int(cid),)).fetchone()
                    if cr:
                        d['cari_kod'] = cr['cari_kod']
                except Exception:
                    pass
        except Exception:
            tr = con.execute(
                f'SELECT talep_no, talep_turu, cari_id, musteri_aday_id, oncelik FROM {TABLO_MTT} WHERE id=?',
                (int(d['kaynak_id']),),
            ).fetchone()
            if tr:
                d['talep_no'] = tr['talep_no']
                d['talep_turu'] = tr['talep_turu']
                d['oncelik'] = tr['oncelik'] if 'oncelik' in tr.keys() else None
        oz = _mtt_kalem_ozet(con, int(d['kaynak_id']))
        d.update({
            'urun_ailesi': oz.get('urun_ailesi'),
            'urun_ailesi_etiket': oz.get('urun_ailesi_etiket'),
            'urun_aciklama': oz.get('urun_aciklama'),
            'renk_gosterim': oz.get('renk_gosterim'),
            'miktar_gosterim': oz.get('miktar_gosterim'),
            'verilen_fiyat': oz.get('verilen_fiyat') if d.get('verilen_fiyat') is None else d.get('verilen_fiyat'),
            'para_birimi': oz.get('para_birimi'),
            'vade_gun': oz.get('vade_gun') if d.get('vade_gun') is None else d.get('vade_gun'),
            'odeme_tipi': oz.get('odeme_tipi'),
        })
        if not d.get('oncelik'):
            d['oncelik'] = oz.get('oncelik')
        # Tüm kalemler listesi (popup tablosu için)
        try:
            from modules.nexgen.mtt_donusum_service import miktar_gosterim as _mg, urun_ailesi_etiket as _ua
            kalem_rows = con.execute(
                """
                SELECT sira_no, urun_ailesi, urun_aciklama, renk_aciklama,
                       miktar_kg, konusulan_tonaj, fiyat_birimi,
                       verilen_fiyat, para_birimi, odeme_tipi, vade_gun,
                       cek_vade_gun, kalem_notu
                FROM nexgen_musteri_temsilcisi_talep_kalem
                WHERE talep_id=?
                ORDER BY sira_no ASC, id ASC
                """,
                (int(d['kaynak_id']),),
            ).fetchall()
            kalemler_out = []
            for kr in kalem_rows:
                kd = _row_dict(kr)
                kalemler_out.append({
                    'sira_no': kd.get('sira_no'),
                    'urun_ailesi': kd.get('urun_ailesi'),
                    'urun_ailesi_etiket': _ua(kd.get('urun_ailesi')),
                    'urun_aciklama': kd.get('urun_aciklama'),
                    'renk_aciklama': kd.get('renk_aciklama'),
                    'miktar_gosterim': _mg(kd),
                    'verilen_fiyat': kd.get('verilen_fiyat'),
                    'para_birimi': kd.get('para_birimi'),
                    'fiyat_birimi': kd.get('fiyat_birimi'),
                    'odeme_tipi': kd.get('odeme_tipi'),
                    'vade_gun': kd.get('vade_gun'),
                    'cek_vade_gun': kd.get('cek_vade_gun'),
                    'kalem_notu': kd.get('kalem_notu'),
                })
            d['kalemler'] = kalemler_out
        except Exception:
            pass
        # Parse siparis meta from aciklama (termin, teslim, kdv)
        ac = (d.get('aciklama') or '').strip()
        meta: dict = {}
        m = _re.search(r'Termin:\s*(\d{4}-\d{2}-\d{2})', ac)
        if m:
            meta['istenen_termin'] = m.group(1)
        m = _re.search(r'Teslim:\s*([^|]+)', ac)
        if m:
            meta['teslim_sekli_etiket'] = m.group(1).strip()
        m = _re.search(
            r'KDV:(GAYRI|RESMI)\|oran:(\d+)\|ara:([\d.]+)\|kdv:([\d.]+)\|genel:([\d.]+)(?:\|pb:(\w+))?',
            ac,
        )
        if m:
            meta['kdv_durumu'] = m.group(1)
            meta['kdv_orani'] = int(m.group(2))
            meta['ara_toplam'] = float(m.group(3))
            meta['kdv_tutari'] = float(m.group(4))
            meta['genel_toplam'] = float(m.group(5))
            if m.group(6):
                meta['para_birimi'] = m.group(6).upper()
        if meta:
            d['siparis_meta'] = meta
    return d


def onay_listele(
    con: sqlite3.Connection,
    *,
    durum: str | None = None,
    kaynak_turu: str | None = None,
    q: str | None = None,
    limit: int = 100,
) -> list[dict]:
    if not _tablo_var(con, TABLO):
        return []
    sql = f'SELECT * FROM {TABLO} WHERE 1=1'
    params: list[Any] = []
    if durum:
        sql += ' AND durum=?'
        params.append(durum.strip().upper())
    if kaynak_turu:
        sql += ' AND kaynak_turu=?'
        params.append(kaynak_turu.strip().upper())
    sql += ' ORDER BY CASE durum WHEN \'ONAY_BEKLIYOR\' THEN 0 ELSE 1 END, created_at DESC, id DESC'
    sql += ' LIMIT ?'
    params.append(int(limit))
    rows = con.execute(sql, params).fetchall()
    out = [_enrich_onay(con, _row_dict(r)) for r in rows]
    qq = (q or '').strip().lower()
    if qq:
        out = [
            x for x in out
            if qq in (x.get('onay_no') or '').lower()
            or qq in (x.get('firma_adi') or '').lower()
            or qq in (x.get('talep_no') or '').lower()
            or qq in (x.get('olusturan_adi') or '').lower()
        ]
    return out


def onay_detay_getir(con: sqlite3.Connection, onay_id: int) -> dict:
    if not _tablo_var(con, TABLO):
        raise OnayError('Onay tablosu yok.', 500)
    row = con.execute(f'SELECT * FROM {TABLO} WHERE id=?', (int(onay_id),)).fetchone()
    if not row:
        raise OnayError('Onay bulunamadı.', 404)
    return _enrich_onay(con, _row_dict(row))


def onay_by_kaynak(
    con: sqlite3.Connection,
    kaynak_turu: str,
    kaynak_id: int,
    onay_turu: str | None = None,
) -> dict | None:
    if not _tablo_var(con, TABLO):
        return None
    if onay_turu:
        row = con.execute(
            f'SELECT * FROM {TABLO} WHERE kaynak_turu=? AND kaynak_id=? AND onay_turu=?',
            (kaynak_turu, int(kaynak_id), onay_turu.strip().upper()),
        ).fetchone()
    else:
        row = con.execute(
            f'SELECT * FROM {TABLO} WHERE kaynak_turu=? AND kaynak_id=? ORDER BY id DESC LIMIT 1',
            (kaynak_turu, int(kaynak_id)),
        ).fetchone()
    return _enrich_onay(con, _row_dict(row)) if row else None


def onay_kuyruk_sayaci(con: sqlite3.Connection) -> int:
    if not _tablo_var(con, TABLO):
        return 0
    row = con.execute(
        f"SELECT COUNT(*) AS n FROM {TABLO} WHERE durum='ONAY_BEKLIYOR'",
    ).fetchone()
    return int(row['n'] or 0) if row else 0


def pazarlamaci_karar_listele(
    con: sqlite3.Connection,
    kullanici_id: int,
    *,
    limit: int = 30,
    after_ts: str | None = None,
) -> list[dict]:
    """Pazarlamacının oluşturduğu MTT onay kararları (sonuç geçmişi)."""
    if not _tablo_var(con, TABLO) or not kullanici_id:
        return []
    sql = f"""
        SELECT * FROM {TABLO}
        WHERE kaynak_turu=?
          AND olusturan_kullanici_id=?
          AND durum IN ('ONAYLANDI', 'REDDEDILDI')
    """
    params: list[Any] = [KAYNAK_MUSTERI_TEMSILCISI_TALEP, int(kullanici_id)]
    if after_ts:
        sql += ' AND COALESCE(karar_tarihi, updated_at) > ?'
        params.append(after_ts)
    sql += ' ORDER BY COALESCE(karar_tarihi, updated_at) DESC, id DESC LIMIT ?'
    params.append(int(limit))
    rows = con.execute(sql, params).fetchall()
    return [_enrich_onay(con, _row_dict(r)) for r in rows]


def pazarlamaci_okunmamis_karar_sayisi(
    con: sqlite3.Connection,
    kullanici_id: int,
    seen_ts: str | None,
) -> int:
    if not _tablo_var(con, TABLO) or not kullanici_id:
        return 0
    sql = f"""
        SELECT COUNT(*) AS n FROM {TABLO}
        WHERE kaynak_turu=?
          AND olusturan_kullanici_id=?
          AND durum IN ('ONAYLANDI', 'REDDEDILDI')
    """
    params: list[Any] = [KAYNAK_MUSTERI_TEMSILCISI_TALEP, int(kullanici_id)]
    if seen_ts:
        sql += ' AND COALESCE(karar_tarihi, updated_at) > ?'
        params.append(seen_ts)
    row = con.execute(sql, params).fetchone()
    return int(row['n'] or 0) if row else 0


def _pazarlamaci_talep_turu_etiket(talep_turu: str | None) -> str:
    tur = (talep_turu or '').strip().upper()
    if tur == 'SIPARIS':
        return 'SİPARİŞ TALEBİ'
    if tur == 'NUMUNE':
        return 'NUMUNE TALEBİ'
    return 'TALEP'


def _pazarlamaci_bildirim_baslik(tip: str, talep_turu: str | None = None) -> str:
    tt = _pazarlamaci_talep_turu_etiket(talep_turu)
    _MAP = {
        'MTT_ONAYLANDI': f'{tt} ONAYLANDI',
        'MTT_REDDEDILDI': f'{tt} REDDEDİLDİ',
        'MTT_SIPARISE_DONUSTU': 'SİPARİŞE DÖNÜŞTÜ',
        'MTT_NUMUNEYE_DONUSTU': 'NUMUNEYE DÖNÜŞTÜ',
        'MTT_ISLEME_ALINDI': 'MEHMET İŞLEME ALDI',
        'TAHSILAT_ONAYLANDI': 'TAHSİLAT ONAYLANDI',
        'TAHSILAT_REDDEDILDI': 'TAHSİLAT REDDEDİLDİ',
        'TAHSILAT_REVIZYON': 'TAHSİLAT REVİZYON İSTENDİ',
    }
    return _MAP.get(tip, tip.replace('_', ' '))


def _pazarlamaci_urun_ozet(con: sqlite3.Connection, talep_id: int) -> tuple[str | None, int]:
    """İlk kalem özeti + ek kalem sayısı (read-only)."""
    if not talep_id or not _tablo_var(con, TABLO_MTT):
        return None, 0
    try:
        kalem_sayisi = int(con.execute(
            'SELECT COUNT(*) AS n FROM nexgen_musteri_temsilcisi_talep_kalem WHERE talep_id=?',
            (int(talep_id),),
        ).fetchone()['n'] or 0)
    except Exception:
        kalem_sayisi = 0
    oz = _mtt_kalem_ozet(con, int(talep_id))
    parcalar: list[str] = []
    urun = oz.get('urun_ailesi_etiket') or oz.get('urun_aciklama')
    if urun:
        parcalar.append(str(urun).strip())
    renk = (oz.get('renk_gosterim') or '').strip()
    if renk and renk != 'Belirtilmedi':
        parcalar.append(renk)
    miktar = (oz.get('miktar_gosterim') or '').strip()
    if miktar and miktar != '—':
        parcalar.append(miktar)
    if not parcalar:
        return None, max(0, kalem_sayisi - 1)
    satir = ' · '.join(parcalar)
    ek = max(0, kalem_sayisi - 1)
    if ek:
        satir += f' · +{ek} kalem'
    return satir, ek


def _pazarlamaci_donusum_kodu(con: sqlite3.Connection, siparis_id, numune_id) -> str | None:
    try:
        if siparis_id and _tablo_var(con, 'nexgen_planlama_siparis'):
            row = con.execute(
                'SELECT siparis_no FROM nexgen_planlama_siparis WHERE id=?',
                (int(siparis_id),),
            ).fetchone()
            if row and row['siparis_no']:
                return str(row['siparis_no']).strip()
        if numune_id and _tablo_var(con, 'nexgen_numune_talep'):
            row = con.execute(
                'SELECT talep_kodu FROM nexgen_numune_talep WHERE id=?',
                (int(numune_id),),
            ).fetchone()
            if row and row['talep_kodu']:
                return str(row['talep_kodu']).strip()
    except Exception:
        pass
    return None


def pazarlamaci_bildirimler(
    con: sqlite3.Connection,
    kullanici_id: int,
    *,
    limit: int = 15,
) -> list[dict]:
    """Pazarlamacının kendi MTT + Tahsilat sonuç bildirimleri (salt-okunur).

    MTT: nexgen_onay (ONAYLANDI/REDDEDILDI) + MTT lifecycle durumu
    Tahsilat: onay_talep (TAHSILAT_KAYDI, ONAYLANDI/REDDEDILDI)
    Tarih kaynağı: karar_tarihi COALESCE updated_at — sahte tarih üretilmez.
    """
    if not kullanici_id:
        return []
    import json as _json
    sonuclar: list[dict] = []

    # --- MTT sonuçları ---
    if _tablo_var(con, TABLO):
        rows = con.execute(f"""
            SELECT no.id, no.durum, no.red_nedeni,
                   COALESCE(no.karar_tarihi, no.updated_at) AS tarih,
                   mt.id AS mtt_id, mt.talep_no, mt.talep_turu, mt.durum AS mtt_durum,
                   mt.cari_id, mt.donusturulen_siparis_id, mt.donusturulen_numune_talep_id
            FROM {TABLO} no
            LEFT JOIN {TABLO_MTT} mt ON mt.id = no.kaynak_id
            WHERE no.kaynak_turu = ?
              AND no.olusturan_kullanici_id = ?
              AND no.durum IN ('ONAYLANDI', 'REDDEDILDI')
            ORDER BY COALESCE(no.karar_tarihi, no.updated_at) DESC, no.id DESC
            LIMIT ?
        """, (KAYNAK_MUSTERI_TEMSILCISI_TALEP, int(kullanici_id), limit)).fetchall()

        for r in rows:
            mtt_durum = r['mtt_durum'] or ''
            onay_durum = r['durum']
            talep_turu = r['talep_turu']
            # Lifecycle etiket: onay sonrası MTT nerede?
            if onay_durum == 'ONAYLANDI':
                if mtt_durum == 'SIPARISE_DONUSTU':
                    tip = 'MTT_SIPARISE_DONUSTU'
                elif mtt_durum in ('NUMUNEYE_DONUSTU', 'KISMEN_NUMUNEYE_DONUSTU'):
                    tip = 'MTT_NUMUNEYE_DONUSTU'
                elif mtt_durum == 'ISLEME_ALINDI':
                    tip = 'MTT_ISLEME_ALINDI'
                else:
                    tip = 'MTT_ONAYLANDI'
            else:
                tip = 'MTT_REDDEDILDI'

            # Firma adı: cari join
            firma_adi = None
            if r['cari_id']:
                try:
                    cr = con.execute(
                        'SELECT unvan FROM nexgen_cari WHERE id=?', (r['cari_id'],)
                    ).fetchone()
                    if cr:
                        firma_adi = cr['unvan']
                except Exception:
                    pass

            mtt_id = r['mtt_id']
            urun_ozet, _kalem_ek = _pazarlamaci_urun_ozet(con, mtt_id) if mtt_id else (None, 0)
            donusum_kodu = _pazarlamaci_donusum_kodu(
                con, r['donusturulen_siparis_id'], r['donusturulen_numune_talep_id'],
            )

            sonuclar.append({
                'tip': tip,
                'baslik': _pazarlamaci_bildirim_baslik(tip, talep_turu),
                'talep_turu': talep_turu,
                'talep_no': r['talep_no'],
                'firma_adi': firma_adi,
                'urun_ozet': urun_ozet,
                'tarih': (r['tarih'] or '')[:16],
                'red_nedeni': r['red_nedeni'] if onay_durum == 'REDDEDILDI' else None,
                'donusum_kodu': donusum_kodu,
                'tutar': None,
            })

    # --- Tahsilat sonuçları (ONAYLANDI + REDDEDILDI + REVIZYON) ---
    if _tablo_var(con, 'onay_talep'):
        trows = con.execute("""
            SELECT ot.id, ot.durum, ot.snapshot_json, ot.talep_kod,
                   COALESCE(
                     (SELECT ota.tarih FROM onay_talep_adim ota
                      WHERE ota.talep_id = ot.id
                        AND ota.durum IN ('ONAYLANDI', 'REDDEDILDI', 'REVIZYON')
                      ORDER BY ota.id DESC LIMIT 1),
                     ot.updated_at, ot.created_at
                   ) AS tarih,
                   (SELECT ota2.karar_notu FROM onay_talep_adim ota2
                    WHERE ota2.talep_id = ot.id
                      AND ota2.durum IN ('REVIZYON', 'REDDEDILDI')
                    ORDER BY ota2.id DESC LIMIT 1) AS son_karar_notu
            FROM onay_talep ot
            WHERE ot.talep_tipi = 'TAHSILAT_KAYDI'
              AND ot.talep_eden_id = ?
              AND ot.durum IN ('ONAYLANDI', 'REDDEDILDI', 'REVIZYON')
            ORDER BY tarih DESC, ot.id DESC
            LIMIT ?
        """, (int(kullanici_id), limit)).fetchall()

        for r in trows:
            snap = {}
            try:
                snap = _json.loads(r['snapshot_json'] or '{}')
            except Exception:
                pass
            if r['durum'] == 'ONAYLANDI':
                tip = 'TAHSILAT_ONAYLANDI'
            elif r['durum'] == 'REDDEDILDI':
                tip = 'TAHSILAT_REDDEDILDI'
            else:
                tip = 'TAHSILAT_REVIZYON'
            red = None
            if r['durum'] in ('REDDEDILDI', 'REVIZYON'):
                red = r['son_karar_notu'] or snap.get('red_nedeni') or snap.get('karar_notu')
            # mo_tahsilat_kayit.id — revizyon için modal hydrate (onay_talep.kaynak_id)
            tahsilat_kayit_id = None
            if r['durum'] == 'REVIZYON':
                try:
                    ot_row = con.execute(
                        "SELECT kaynak_id FROM onay_talep WHERE id=? AND kaynak_id IS NOT NULL LIMIT 1",
                        (int(r['id']),),
                    ).fetchone()
                    if ot_row and ot_row['kaynak_id']:
                        kayit_row = con.execute(
                            "SELECT id FROM mo_tahsilat_kayit "
                            "WHERE id=? AND olusturan_id=? AND durum='REVIZYON_ISTENDI' LIMIT 1",
                            (int(ot_row['kaynak_id']), int(kullanici_id)),
                        ).fetchone()
                        if kayit_row:
                            tahsilat_kayit_id = int(kayit_row['id'])
                except Exception:
                    pass
            sonuclar.append({
                'tip': tip,
                'baslik': _pazarlamaci_bildirim_baslik(tip),
                'talep_turu': 'TAHSILAT',
                'talep_no': snap.get('kayit_kodu') or r['talep_kod'],
                'firma_adi': snap.get('cari_unvan_snapshot'),
                'urun_ozet': None,
                'tarih': (r['tarih'] or '')[:16],
                'red_nedeni': red,
                'donusum_kodu': None,
                'tutar': snap.get('alinan_tutar') or snap.get('beklenen_tutar'),
                'tahsilat_kayit_id': tahsilat_kayit_id,
            })

    # Karar zamanına göre sırala — en yeni en üste (oluşturma/tahsilat günü değil)
    def _bildirim_sort_key(item: dict) -> str:
        return (item.get('tarih') or '').replace('T', ' ').strip()

    sonuclar.sort(key=_bildirim_sort_key, reverse=True)
    return sonuclar[:limit]


def mehmet_okunmamis_yeni_sayisi(
    con: sqlite3.Connection,
    seen_ts: str | None,
) -> int:
    """Yönetim onayından sonra YENI düşen okunmamış MTT sayısı."""
    if not _tablo_var(con, TABLO_MTT):
        return 0
    sql = f"SELECT COUNT(*) AS n FROM {TABLO_MTT} WHERE durum='YENI'"
    params: list[Any] = []
    if seen_ts:
        sql += ' AND COALESCE(updated_at, created_at) > ?'
        params.append(seen_ts)
    row = con.execute(sql, params).fetchone()
    return int(row['n'] or 0) if row else 0
