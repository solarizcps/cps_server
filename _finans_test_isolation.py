# -*- coding: utf-8 -*-
"""Finans test suite izolasyon yardımcıları — sıra bağımsız testler."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from typing import Any

TEST_SEVK_NO_PREFIX = 'MSV-FINTEST-'
TEST_SEVK_IDEM_PREFIX = 'fintest-sevk-'
TEST_TAH_IDEM_PREFIX = 'fintest-tah-'
F1F1_IDEM_PREFIX = 'f1f1test:'
F1F1_SEVK_NO_PREFIX = 'MSV-F1F1-'


def find_sevk_edildi(
    con: sqlite3.Connection,
    *,
    min_kg: float = 0.001,
    without_finans_belge: bool = False,
    exclude_ids: set[int] | None = None,
) -> dict[str, Any] | None:
    extra = ''
    if without_finans_belge:
        extra += """
        AND NOT EXISTS (
            SELECT 1 FROM finans_belgesi fb
            WHERE fb.sevkiyat_id=s.id AND fb.aktif=1
        )
        """
    rows = con.execute(
        f"""
        SELECT s.id, s.durum, s.siparis_id, s.cari_id, s.sevk_tarihi
        FROM mo_musteri_sevkiyat s
        WHERE s.aktif=1 AND s.durum IN ('SEVK_EDILDI','TESLIM_EDILDI','TAMAMLANDI')
        {extra}
        ORDER BY s.id
        """
    ).fetchall()
    ex = exclude_ids or set()
    for r in rows:
        sid = int(r['id'])
        if sid in ex:
            continue
        kg = con.execute(
            'SELECT COALESCE(SUM(miktar_kg),0) FROM mo_musteri_sevkiyat_kalem WHERE sevkiyat_id=?',
            (sid,),
        ).fetchone()[0]
        if float(kg or 0) >= min_kg:
            d = dict(r)
            d['_kg'] = float(kg)
            return d
    return None


def find_tahsilat(
    con: sqlite3.Connection,
    durum: str,
    *,
    without_finans_belge: bool = False,
) -> dict[str, Any] | None:
    extra = ''
    if without_finans_belge:
        extra = """
        AND NOT EXISTS (
            SELECT 1 FROM finans_belgesi fb
            WHERE fb.tahsilat_kayit_id=mo_tahsilat_kayit.id AND fb.aktif=1
        )
        """
    row = con.execute(
        f"""
        SELECT * FROM mo_tahsilat_kayit
        WHERE aktif=1 AND durum=? AND COALESCE(alinan_tutar,0)>0
        {extra}
        LIMIT 1
        """,
        (durum,),
    ).fetchone()
    return dict(row) if row else None


def find_sevk_same_siparis_farkli(
    con: sqlite3.Connection,
    siparis_id: int,
    exclude_sevk_id: int,
) -> dict[str, Any] | None:
    row = con.execute(
        """
        SELECT s.id, s.durum, s.siparis_id, s.cari_id
        FROM mo_musteri_sevkiyat s
        WHERE s.aktif=1 AND s.siparis_id=? AND s.id!=?
          AND s.durum IN ('SEVK_EDILDI','TESLIM_EDILDI','TAMAMLANDI')
          AND NOT EXISTS (
            SELECT 1 FROM finans_belgesi fb WHERE fb.sevkiyat_id=s.id AND fb.aktif=1
          )
          AND EXISTS (
            SELECT 1 FROM mo_musteri_sevkiyat_kalem k
            WHERE k.sevkiyat_id=s.id AND COALESCE(k.miktar_kg,0)>0
          )
        LIMIT 1
        """,
        (siparis_id, exclude_sevk_id),
    ).fetchone()
    return dict(row) if row else None


def cleanup_finans_belgeler(con: sqlite3.Connection, belge_ids: list[int]) -> int:
    n = 0
    for bid in belge_ids:
        cur = con.execute('DELETE FROM finans_belgesi WHERE id=?', (int(bid),))
        n += cur.rowcount
    if n:
        con.commit()
    return n


def cleanup_test_sevkiyat(con: sqlite3.Connection, sevkiyat_ids: list[int]) -> None:
    for sid in sevkiyat_ids:
        con.execute('DELETE FROM mo_musteri_sevkiyat_kalem WHERE sevkiyat_id=?', (int(sid),))
        con.execute('DELETE FROM mo_musteri_sevkiyat WHERE id=?', (int(sid),))
    if sevkiyat_ids:
        con.commit()


def list_finans_belgeleri(con: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT id, belge_kodu, belge_tipi, durum, sevkiyat_id, tahsilat_kayit_id,
               kaynak_tipi, kaynak_id, posting_durumu
        FROM finans_belgesi ORDER BY id
        """
    ).fetchall()
    return [dict(r) for r in rows]


def create_ephemeral_sevkiyat(
    con: sqlite3.Connection,
    *,
    template_siparis_id: int,
    template_cari_id: int,
    miktar_kg: float = 100.0,
    idem_prefix: str = TEST_SEVK_IDEM_PREFIX,
    no_prefix: str = TEST_SEVK_NO_PREFIX,
) -> int:
    """Finans belgesi olmayan geçici sevkiyat — test sonunda cleanup."""
    uid = uuid.uuid4().hex[:10]
    cur = con.execute(
        """
        INSERT INTO mo_musteri_sevkiyat (
            sevkiyat_no, siparis_id, cari_id, durum, sevk_tarihi, aktif,
            idempotency_key, olusturan_id
        )
        VALUES (?, ?, ?, 'SEVK_EDILDI', date('now'), 1, ?, 1)
        """,
        (
            f'{no_prefix}{uid}',
            template_siparis_id,
            template_cari_id,
            f'{idem_prefix}{uid}',
        ),
    )
    sid = int(cur.lastrowid)
    con.execute(
        'INSERT INTO mo_musteri_sevkiyat_kalem (sevkiyat_id, miktar_kg) VALUES (?, ?)',
        (sid, miktar_kg),
    )
    con.commit()
    return sid


CRITICAL_GUARD_TABLES = (
    'Cari_Har',
    'finans_belgesi',
    'finans_cari_kimlik',
    'tedarikci_eslestirme',
    'cari_eslestirme',
    'sistem_yetki',
    'sistem_rol_yetki',
    'schema_migrations',
)


def pin_all_db_paths(isolated: str) -> None:
    """Config.MOCK_DB_PATH + nexgen routes.DB_PATH — import sonrası tekrar pin."""
    import config as _cfg
    _cfg.Config.MOCK_DB_PATH = isolated
    import modules.nexgen.routes as nx_routes
    nx_routes.DB_PATH = isolated


def critical_table_hashes(db_path: str) -> dict[str, dict[str, Any]]:
    """Kritik tabloların mantıksal hash snapshot'ı."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    out: dict[str, dict[str, Any]] = {}
    for t in CRITICAL_GUARD_TABLES:
        try:
            rows = con.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall()
            cols = [d[0] for d in con.execute(f'SELECT * FROM "{t}" LIMIT 0').description]
            payload = [dict(zip(cols, row)) for row in rows]
            h = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
            out[t] = {'count': len(rows), 'hash': h}
        except sqlite3.Error as exc:
            out[t] = {'count': None, 'hash': f'ERROR:{exc}'}
    con.close()
    return out


def assert_main_db_logical_unchanged(pre_hashes: dict, db_path: str) -> tuple[bool, str]:
    post = critical_table_hashes(db_path)
    diffs = []
    for t in CRITICAL_GUARD_TABLES:
        a = pre_hashes.get(t, {})
        b = post.get(t, {})
        if a.get('hash') != b.get('hash') or a.get('count') != b.get('count'):
            diffs.append(f'{t}:{a.get("count")}->{b.get("count")}')
    if diffs:
        return False, '; '.join(diffs)
    return True, 'logical hashes ok'


def use_isolated_finans_db(root: str, main_db: str, tag: str) -> str:
    """Ana DB kopyası üzerinde finans API testleri — routes.DB_PATH + MOCK_DB_PATH yönlendir."""
    isolated = copy_isolated_db(root, main_db, tag=tag)
    pin_all_db_paths(isolated)
    return isolated


def copy_isolated_db(root: str, app_db: str, tag: str = 'f1f1') -> str:
    """Ana mock DB'nin timestamp'li kopyası — 1F1 gerçek posting testleri."""
    import os
    import shutil
    from datetime import datetime

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    dst_dir = os.path.join(root, 'backup', f'faz_finans_{tag}_test_{ts}')
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, 'mock_data.db')
    shutil.copy2(app_db, dst)
    return dst


def ensure_golden_cari(con: sqlite3.Connection, cari_id: int) -> str:
    """Golden cari eşleştirmesi yoksa test için bağla."""
    ex = con.execute(
        'SELECT cari_kart_ckod FROM cari_eslestirme WHERE nexgen_cari_id=? AND aktif=1',
        (int(cari_id),),
    ).fetchone()
    if ex and ex['cari_kart_ckod']:
        return str(ex['cari_kart_ckod'])
    ck = con.execute(
        """
        SELECT CKod FROM Cari_Kart
        WHERE CKod NOT IN (
            SELECT cari_kart_ckod FROM cari_eslestirme WHERE cari_kart_ckod IS NOT NULL
        ) LIMIT 1
        """
    ).fetchone()
    if not ck:
        ck = con.execute('SELECT CKod FROM Cari_Kart LIMIT 1').fetchone()
    if not ck:
        raise RuntimeError('Cari_Kart bulunamadı')
    con.execute(
        """
        INSERT OR IGNORE INTO cari_eslestirme (
            nexgen_cari_id, cari_kart_ckod, eslestirme_durumu,
            eslestirme_yontemi, aktif, eslestirme_tarihi
        ) VALUES (?, ?, 'DOGRULANDI', 'MANUEL', 1, datetime('now','localtime'))
        """,
        (int(cari_id), ck['CKod']),
    )
    con.commit()
    return str(ck['CKod'])


def db_sha256(db_path: str) -> str:
    return hashlib.sha256(open(db_path, 'rb').read()).hexdigest()


def db_counts(db_path: str) -> dict[str, int]:
    con = sqlite3.connect(db_path)
    har = int(con.execute('SELECT COUNT(*) FROM Cari_Har').fetchone()[0])
    fb = int(con.execute('SELECT COUNT(*) FROM finans_belgesi').fetchone()[0])
    con.close()
    return {'cari_har': har, 'finans_belgesi': fb}


def assert_main_db_unchanged(
    pre_sha: str,
    db_path: str,
    *,
    pre_har: int | None = None,
    pre_fb: int | None = None,
) -> tuple[bool, str]:
    """Ana DB'nin test öncesi SHA/count ile aynı kaldığını doğrula."""
    post_sha = db_sha256(db_path)
    if post_sha != pre_sha:
        return False, f'SHA degisti: {pre_sha} -> {post_sha}'
    if pre_har is not None or pre_fb is not None:
        post = db_counts(db_path)
        if pre_har is not None and post['cari_har'] != pre_har:
            return False, f"Cari_Har degisti: {pre_har} -> {post['cari_har']}"
        if pre_fb is not None and post['finans_belgesi'] != pre_fb:
            return False, f"finans_belgesi degisti: {pre_fb} -> {post['finans_belgesi']}"
    return True, post_sha


def snapshot_finans_belgesi_seed(con: sqlite3.Connection) -> str:
    """Seed finans_belgesi satırlarının JSON snapshot'ı (geri yükleme için)."""
    rows = con.execute('SELECT * FROM finans_belgesi ORDER BY id').fetchall()
    cols = [d[0] for d in con.execute('SELECT * FROM finans_belgesi LIMIT 0').description]
    payload = [dict(zip(cols, row)) for row in rows]
    return json.dumps(payload, ensure_ascii=False, default=str)


def restore_finans_belgesi_seed(con: sqlite3.Connection, snapshot_json: str) -> int:
    """Seed finans_belgesi snapshot'ını geri yükle."""
    rows = json.loads(snapshot_json)
    if not rows:
        return 0
    cols = [c[1] for c in con.execute('PRAGMA table_info(finans_belgesi)').fetchall()]
    n = 0
    for row in rows:
        rid = int(row['id'])
        sets = ', '.join(f'{c}=?' for c in cols if c != 'id')
        vals = [row.get(c) for c in cols if c != 'id'] + [rid]
        cur = con.execute(f'UPDATE finans_belgesi SET {sets} WHERE id=?', vals)
        n += cur.rowcount
    con.commit()
    return n


def snapshot_sistem_audit_max_id(con: sqlite3.Connection) -> int:
    return int(con.execute('SELECT COALESCE(MAX(Id), 0) FROM sistem_audit').fetchone()[0])


def cleanup_sistem_audit_after(con: sqlite3.Connection, min_id_exclusive: int) -> int:
    """Test sırasında eklenen sistem_audit satırlarını sil."""
    cur = con.execute('DELETE FROM sistem_audit WHERE Id > ?', (int(min_id_exclusive),))
    if cur.rowcount:
        con.commit()
    return cur.rowcount


def finalize_main_db_test_cleanup(
    db_path: str,
    *,
    audit_max_id: int | None = None,
    ephemeral_belge_ids: list[int] | None = None,
) -> None:
    """Ephemeral belge + test audit izlerini temizle."""
    con = sqlite3.connect(db_path)
    if ephemeral_belge_ids:
        cleanup_finans_belgeler(con, list(dict.fromkeys(ephemeral_belge_ids)))
    if audit_max_id is not None:
        cleanup_sistem_audit_after(con, audit_max_id)
    con.close()


def cleanup_f1f1_postings(con: sqlite3.Connection) -> dict[str, int]:
    """f1f1test prefix kayıtlarını temizle."""
    belgeler = con.execute(
        """
        SELECT fb.id, fb.cari_har_id FROM finans_belgesi fb
        LEFT JOIN mo_musteri_sevkiyat s ON s.id = fb.sevkiyat_id
        LEFT JOIN mo_tahsilat_kayit t ON t.id = fb.tahsilat_kayit_id
        WHERE s.idempotency_key LIKE ?
           OR t.idempotency_key LIKE ?
           OR fb.idempotency_key LIKE ?
        """,
        (F1F1_IDEM_PREFIX + '%', 'f1f1test-tah:%', F1F1_IDEM_PREFIX + '%'),
    ).fetchall()
    har_ids = [int(b['cari_har_id']) for b in belgeler if b['cari_har_id']]
    n_har = 0
    for hid in har_ids:
        cur = con.execute('DELETE FROM Cari_Har WHERE Id=?', (hid,))
        n_har += cur.rowcount
    n_fb = 0
    for b in belgeler:
        cur = con.execute('DELETE FROM finans_belgesi WHERE id=?', (int(b['id']),))
        n_fb += cur.rowcount
    if n_har or n_fb:
        con.commit()
    return {'cari_har_deleted': n_har, 'finans_belgesi_deleted': n_fb}
