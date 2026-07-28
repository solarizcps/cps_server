# -*- coding: utf-8 -*-
"""
FAZ-YONETIM-CARI360-OMURGA-ILISKI-MERKEZI-1

Sipariş kalemi ↔ üretim planı bağlama (nexgen_cari.id omurgası).
Yeni tablo yok. Yalnız mevcut kolon: nexgen_planlama_siparis_kalem.uretim_plan_id
"""
from __future__ import annotations

import sqlite3
from typing import Any


def _tablo_var(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _kolon_var(con: sqlite3.Connection, tablo: str, kolon: str) -> bool:
    return any(
        c[1] == kolon
        for c in con.execute(f'PRAGMA table_info({tablo})').fetchall()
    )


def kalem_uretim_plan_yaz(
    con: sqlite3.Connection,
    kalem_id: int,
    plan_id: int,
    siparis_id: int,
) -> bool:
    """Tek kaleme plan bağlar. Sahiplik: kalem.planlama_siparis_id == siparis_id."""
    if not _tablo_var(con, 'nexgen_planlama_siparis_kalem'):
        return False
    if not _kolon_var(con, 'nexgen_planlama_siparis_kalem', 'uretim_plan_id'):
        return False
    cur = con.execute(
        """
        UPDATE nexgen_planlama_siparis_kalem
        SET uretim_plan_id=?,
            guncelleme_tarihi=datetime('now','localtime')
        WHERE id=? AND planlama_siparis_id=?
        """,
        (int(plan_id), int(kalem_id), int(siparis_id)),
    )
    return (cur.rowcount or 0) > 0


def backfill_kalem_uretim_planlari(
    con: sqlite3.Connection,
    *,
    siparis_id: int | None = None,
    cari_id: int | None = None,
    limit: int = 300,
) -> dict[str, Any]:
    """NULL uretim_plan_id kalemleri planlama_siparis_id (+ rf_renk_id) ile doldurur.

    Çoklu plan varsa: aynı rf_renk_id eşleşeni, yoksa henüz bağlanmamış ilk plan.
    """
    if not _tablo_var(con, 'nexgen_planlama_siparis_kalem'):
        return {'ok': True, 'baglanan': 0, 'skip': 'no_kalem_table'}
    if not _kolon_var(con, 'nexgen_planlama_siparis_kalem', 'uretim_plan_id'):
        return {'ok': True, 'baglanan': 0, 'skip': 'no_col'}
    if not _tablo_var(con, 'nexgen_uretim_plan'):
        return {'ok': True, 'baglanan': 0, 'skip': 'no_plan_table'}

    where = ['k.uretim_plan_id IS NULL']
    params: list[Any] = []
    if siparis_id is not None:
        where.append('k.planlama_siparis_id=?')
        params.append(int(siparis_id))
    if cari_id is not None and _tablo_var(con, 'nexgen_planlama_siparis'):
        where.append(
            'EXISTS (SELECT 1 FROM nexgen_planlama_siparis s '
            'WHERE s.id=k.planlama_siparis_id AND s.cari_id=?)'
        )
        params.append(int(cari_id))

    sql = f"""
        SELECT k.id AS kalem_id, k.planlama_siparis_id, k.rf_renk_id
        FROM nexgen_planlama_siparis_kalem k
        WHERE {' AND '.join(where)}
        ORDER BY k.id
        LIMIT ?
    """
    params.append(max(1, min(int(limit), 1000)))
    kalemler = con.execute(sql, params).fetchall()
    baglanan = 0
    for k in kalemler:
        sid = int(k['planlama_siparis_id'])
        kid = int(k['kalem_id'])
        rf = k['rf_renk_id']
        plan = None
        if rf is not None and _kolon_var(con, 'nexgen_uretim_plan', 'rf_renk_id'):
            plan = con.execute(
                """
                SELECT p.id FROM nexgen_uretim_plan p
                WHERE p.planlama_siparis_id=? AND p.rf_renk_id=?
                  AND COALESCE(p.durum, '') NOT IN ('IPTAL')
                  AND NOT EXISTS (
                    SELECT 1 FROM nexgen_planlama_siparis_kalem kx
                    WHERE kx.uretim_plan_id=p.id AND kx.id!=?
                  )
                ORDER BY p.id
                LIMIT 1
                """,
                (sid, rf, kid),
            ).fetchone()
        if not plan:
            plan = con.execute(
                """
                SELECT p.id FROM nexgen_uretim_plan p
                WHERE p.planlama_siparis_id=?
                  AND COALESCE(p.durum, '') NOT IN ('IPTAL')
                  AND NOT EXISTS (
                    SELECT 1 FROM nexgen_planlama_siparis_kalem kx
                    WHERE kx.uretim_plan_id=p.id
                  )
                ORDER BY p.id
                LIMIT 1
                """,
                (sid,),
            ).fetchone()
        if not plan:
            # Son çare: siparişin ilk planı (tek kalem senaryosu)
            plan = con.execute(
                """
                SELECT p.id FROM nexgen_uretim_plan p
                WHERE p.planlama_siparis_id=?
                  AND COALESCE(p.durum, '') NOT IN ('IPTAL')
                ORDER BY p.id
                LIMIT 1
                """,
                (sid,),
            ).fetchone()
        if plan and kalem_uretim_plan_yaz(con, kid, int(plan['id']), sid):
            baglanan += 1

    return {'ok': True, 'baglanan': baglanan, 'aday': len(kalemler)}
