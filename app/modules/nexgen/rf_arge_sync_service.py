# -*- coding: utf-8 -*-
"""FAZ-2B — AR-GE ↔ RF ↔ numune pointer sync + guards.

Migration yok. Backfill yok. Commit yapmaz (caller txn).
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class RfArgeSyncError(Exception):
    def __init__(self, message: str, status: int = 400, kod: str | None = None, **extra):
        super().__init__(message)
        self.message = message
        self.status = status
        self.kod = kod or 'RF_ARGE_SYNC'
        self.extra = extra


def _cols(con, table: str) -> set[str]:
    return {c[1] for c in con.execute(f'PRAGMA table_info({table})').fetchall()}


def _int_or_none(v: Any) -> int | None:
    if v in (None, '', 0, '0'):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def assert_rf_usable(
    con,
    rf_renk_id: int,
    *,
    arge_cari_id: Any = None,
) -> dict[str, Any]:
    """RF ID zorunlu; pasif/yok/cari uyumsuz → hata."""
    rid = _int_or_none(rf_renk_id)
    if rid is None:
        raise RfArgeSyncError('rf_renk_id zorunludur.', 400, 'RF_ID_ZORUNLU')

    rf = con.execute(
        """
        SELECT id, rf_kod, ad, durum, aktif, cari_id, ilk_talep_cari_id,
               kaynak_arge_test_id
        FROM nexgen_rf_renk WHERE id=?
        """,
        (rid,),
    ).fetchone()
    if not rf:
        raise RfArgeSyncError(f'RF bulunamadı (id={rid}).', 404, 'RF_YOK')
    if not int(rf['aktif'] or 0):
        raise RfArgeSyncError(
            f'RF pasif (id={rid}).', 400, 'RF_PASIF', rf_renk_id=rid,
        )
    durum = (rf['durum'] or '').strip().upper()
    if durum and durum not in ('ONAYLI', 'ONAYLANDI', 'AKTIF'):
        # IPTAL / REDDEDILDI / TASLAK vb. seçime kapalı
        if durum in ('IPTAL', 'İPTAL', 'REDDEDILDI', 'PASIF', 'TASLAK'):
            raise RfArgeSyncError(
                f'RF durumu kullanıma uygun değil: {rf["durum"]}.',
                400, 'RF_DURUM', rf_renk_id=rid, durum=rf['durum'],
            )

    arge_c = _int_or_none(arge_cari_id)
    rf_c = _int_or_none(rf['cari_id'])
    # Global RF (cari_id NULL) izinli; doluysa AR-GE carisi ile uyumlu olmalı
    if arge_c is not None and rf_c is not None and arge_c != rf_c:
        raise RfArgeSyncError(
            f'RF cari_id ({rf_c}) AR-GE cari_id ({arge_c}) ile uyuşmuyor.',
            409, 'RF_CARI_MISMATCH',
            rf_renk_id=rid, rf_cari_id=rf_c, arge_cari_id=arge_c,
            ilk_talep_cari_id=_int_or_none(rf['ilk_talep_cari_id']),
        )
    return dict(rf)


def resolve_existing_rf_for_arge(
    con,
    arge_id: int,
    arge_rf_renk_id: Any = None,
) -> dict[str, Any] | None:
    """
    Idempotent mevcut RF çözümlemesi.
    1) arge.rf_renk_id
    2) tek kaynak_arge_test_id
    Multi kaynak → 409.
    """
    aid = int(arge_id)
    ptr = _int_or_none(arge_rf_renk_id)
    if ptr is not None:
        rf = con.execute(
            """
            SELECT id, rf_kod, ad, durum, aktif, cari_id, ilk_talep_cari_id,
                   kaynak_arge_test_id
            FROM nexgen_rf_renk WHERE id=?
            """,
            (ptr,),
        ).fetchone()
        if rf and int(rf['aktif'] or 0):
            return dict(rf)
        if rf and not int(rf['aktif'] or 0):
            raise RfArgeSyncError(
                f'AR-GE pointer pasif RF gösteriyor (rf={ptr}).',
                409, 'ARGE_RF_PASIF', rf_renk_id=ptr, arge_id=aid,
            )
        # pointer orphan — kaynak reverse'e düş
        log.warning('[RF_ARGE] orphan arge.rf_renk_id=%s arge=%s', ptr, aid)

    rows = con.execute(
        """
        SELECT id, rf_kod, ad, durum, aktif, cari_id, ilk_talep_cari_id,
               kaynak_arge_test_id
        FROM nexgen_rf_renk
        WHERE kaynak_arge_test_id=? AND aktif=1
        ORDER BY id
        """,
        (aid,),
    ).fetchall()
    if len(rows) > 1:
        ids = [int(r['id']) for r in rows]
        raise RfArgeSyncError(
            f'Aynı AR-GE için birden fazla aktif RF: {ids}. Manuel inceleme.',
            409, 'RF_MULTI_KAYNAK',
            arge_id=aid, rf_ids=ids,
        )
    if len(rows) == 1:
        return dict(rows[0])
    return None


def find_bagli_numune_id(con, arge_id: int) -> int | None:
    """Öncelik arge.numune_talep_id; fallback numune.arge_test_id."""
    aid = int(arge_id)
    arge_cols = _cols(con, 'nexgen_arge_test')
    if 'numune_talep_id' in arge_cols:
        r = con.execute(
            'SELECT numune_talep_id FROM nexgen_arge_test WHERE id=?', (aid,),
        ).fetchone()
        nid = _int_or_none(r['numune_talep_id'] if r else None)
        if nid is not None:
            nt = con.execute(
                'SELECT id, aktif FROM nexgen_numune_talep WHERE id=?', (nid,),
            ).fetchone()
            if nt and int(nt['aktif'] or 0):
                return int(nt['id'])
    else:
        log.info('[RF_ARGE] MIG141 yok — numune_talep_id fallback arge_test_id')

    r = con.execute(
        """
        SELECT id FROM nexgen_numune_talep
        WHERE aktif=1 AND arge_test_id=?
        ORDER BY id DESC LIMIT 2
        """,
        (aid,),
    ).fetchall()
    if len(r) == 1:
        return int(r[0]['id'])
    if len(r) > 1:
        # birden fazla numune aynı arge pointer — overwrite riski; sync atla
        log.warning(
            '[RF_ARGE] multi numune.arge_test_id=%s ids=%s — numune sync atlandı',
            aid, [int(x['id']) for x in r],
        )
        return None
    return None


def sync_arge_rf_pointers(
    con,
    arge_id: int,
    rf_renk_id: int,
    *,
    arge_cari_id: Any = None,
) -> dict[str, Any]:
    """
    Aynı txn içinde:
      arge.rf_renk_id, rf.kaynak_arge_test_id (conflict yoksa),
      numune.rf_renk_id (boşsa / aynıysa).
    Conflict → RfArgeSyncError (caller rollback).
    """
    aid = int(arge_id)
    rid = int(rf_renk_id)
    rf = assert_rf_usable(con, rid, arge_cari_id=arge_cari_id)

    arge = con.execute(
        """
        SELECT id, rf_renk_id, cari_id, aktif, durum
        FROM nexgen_arge_test WHERE id=?
        """,
        (aid,),
    ).fetchone()
    if not arge or not int(arge['aktif'] or 0):
        raise RfArgeSyncError('AR-GE bulunamadı veya pasif.', 404, 'ARGE_YOK')

    arge_c = _int_or_none(arge_cari_id if arge_cari_id is not None else arge['cari_id'])
    # cari guard tekrar (arge satırından)
    assert_rf_usable(con, rid, arge_cari_id=arge_c)

    mevcut_arge_rf = _int_or_none(arge['rf_renk_id'])
    if mevcut_arge_rf is not None and mevcut_arge_rf != rid:
        raise RfArgeSyncError(
            f'AR-GE zaten farklı RF bağlı (mevcut={mevcut_arge_rf}, yeni={rid}). '
            'Overwrite yok — manuel inceleme.',
            409, 'ARGE_RF_CONFLICT',
            arge_id=aid, mevcut_rf=mevcut_arge_rf, yeni_rf=rid,
        )

    kaynak = _int_or_none(rf.get('kaynak_arge_test_id'))
    if kaynak is not None and kaynak != aid:
        raise RfArgeSyncError(
            f'RF başka AR-GE kaynağına bağlı (rf={rid}, kaynak={kaynak}, arge={aid}).',
            409, 'RF_KAYNAK_CONFLICT',
            rf_renk_id=rid, kaynak_arge_test_id=kaynak, arge_id=aid,
        )

    # multi reverse check (bu RF dışında aynı kaynak?)
    others = con.execute(
        """
        SELECT id FROM nexgen_rf_renk
        WHERE kaynak_arge_test_id=? AND aktif=1 AND id!=?
        """,
        (aid, rid),
    ).fetchall()
    if others:
        ids = [int(r['id']) for r in others] + [rid]
        raise RfArgeSyncError(
            f'Aynı AR-GE için birden fazla aktif RF: {ids}.',
            409, 'RF_MULTI_KAYNAK',
            arge_id=aid, rf_ids=ids,
        )

    if mevcut_arge_rf is None:
        con.execute(
            'UPDATE nexgen_arge_test SET rf_renk_id=? WHERE id=?',
            (rid, aid),
        )

    if kaynak is None:
        con.execute(
            """
            UPDATE nexgen_rf_renk
            SET kaynak_arge_test_id=?
            WHERE id=? AND (kaynak_arge_test_id IS NULL OR kaynak_arge_test_id=0)
            """,
            (aid, rid),
        )
        # race: başka tx yazmış olabilir
        chk = con.execute(
            'SELECT kaynak_arge_test_id FROM nexgen_rf_renk WHERE id=?', (rid,),
        ).fetchone()
        k2 = _int_or_none(chk['kaynak_arge_test_id'] if chk else None)
        if k2 is not None and k2 != aid:
            raise RfArgeSyncError(
                f'RF kaynak_arge_test_id conflict (rf={rid}, kaynak={k2}).',
                409, 'RF_KAYNAK_CONFLICT',
                rf_renk_id=rid, kaynak_arge_test_id=k2, arge_id=aid,
            )

    numune_id = find_bagli_numune_id(con, aid)
    numune_sync = None
    if numune_id is not None:
        nt_cols = _cols(con, 'nexgen_numune_talep')
        if 'rf_renk_id' not in nt_cols:
            numune_sync = 'NO_COL'
        else:
            nt = con.execute(
                'SELECT id, rf_renk_id, cari_id, aktif FROM nexgen_numune_talep WHERE id=?',
                (numune_id,),
            ).fetchone()
            if nt and int(nt['aktif'] or 0):
                nt_rf = _int_or_none(nt['rf_renk_id'])
                if nt_rf is None:
                    con.execute(
                        'UPDATE nexgen_numune_talep SET rf_renk_id=? WHERE id=?',
                        (rid, numune_id),
                    )
                    numune_sync = 'SET'
                elif nt_rf == rid:
                    numune_sync = 'IDEM'
                else:
                    raise RfArgeSyncError(
                        f'Numune farklı RF pointer (numune={numune_id}, '
                        f'mevcut={nt_rf}, yeni={rid}). Overwrite yok.',
                        409, 'NUMUNE_RF_CONFLICT',
                        numune_talep_id=numune_id,
                        mevcut_rf=nt_rf, yeni_rf=rid, arge_id=aid,
                    )

    return {
        'ok': True,
        'arge_id': aid,
        'rf_renk_id': rid,
        'numune_talep_id': numune_id,
        'numune_sync': numune_sync,
        'rf_kod': rf.get('rf_kod'),
    }


def ensure_rf_formul_uygunluk(
    con,
    rf_renk_id: int,
    formul_id: int,
    *,
    arge_id: int | None = None,
    ilk_talep_cari_id: Any = None,
    shore_hedef: Any = None,
    shore_sonuc: Any = None,
    renk_sonucu: Any = None,
    numune_sonucu: Any = None,
    onay_tarihi: Any = None,
) -> dict[str, Any]:
    """Formül ID doğrula; uygunluk yoksa INSERT, varsa idempotent."""
    rid = int(rf_renk_id)
    fid = _int_or_none(formul_id)
    if fid is None:
        raise RfArgeSyncError('formul_id zorunlu (text formül canonical değil).', 400, 'FORMUL_ID')

    frm = con.execute(
        'SELECT id, kod, ad, aktif, durum FROM nexgen_formul WHERE id=?',
        (fid,),
    ).fetchone()
    if not frm:
        raise RfArgeSyncError(f'Formül bulunamadı (id={fid}).', 404, 'FORMUL_YOK')
    if not int(frm['aktif'] or 0):
        raise RfArgeSyncError(f'Formül pasif (id={fid}).', 400, 'FORMUL_PASIF')

    mevcut = con.execute(
        """
        SELECT id FROM nexgen_rf_formul_uygunluk
        WHERE rf_renk_id=? AND formul_id=? AND aktif=1
        LIMIT 1
        """,
        (rid, fid),
    ).fetchone()
    if mevcut:
        return {
            'ok': True, 'mevcut': True, 'uygunluk_id': int(mevcut['id']),
            'formul_id': fid, 'formul_kod': frm['kod'], 'formul_ad': frm['ad'],
        }

    # UNIQUE(kaynak_arge_test_id) — yalnızca ilk uygunluk satırı kaynak taşır
    kaynak = arge_id
    if arge_id is not None:
        taken = con.execute(
            """
            SELECT id FROM nexgen_rf_formul_uygunluk
            WHERE kaynak_arge_test_id=? AND aktif=1 LIMIT 1
            """,
            (int(arge_id),),
        ).fetchone()
        if taken:
            kaynak = None

    con.execute(
        """
        INSERT INTO nexgen_rf_formul_uygunluk
            (rf_renk_id, formul_id, kaynak_arge_test_id, durum,
             ilk_talep_cari_id, shore_hedef, shore_sonuc,
             renk_sonucu, numune_sonucu, onay_tarihi, aktif)
        VALUES (?, ?, ?, 'ONAYLI', ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            rid, fid, kaynak, ilk_talep_cari_id,
            shore_hedef, shore_sonuc, renk_sonucu, numune_sonucu, onay_tarihi,
        ),
    )
    uid = con.execute('SELECT last_insert_rowid()').fetchone()[0]
    return {
        'ok': True, 'mevcut': False, 'uygunluk_id': int(uid),
        'formul_id': fid, 'formul_kod': frm['kod'], 'formul_ad': frm['ad'],
    }
