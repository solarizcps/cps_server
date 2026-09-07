# -*- coding: utf-8 -*-
"""PZM üretim zinciri cascade iptal — tek transaction, fail-closed guard."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

ISLEM_KODU = 'NEXGEN_SIPARIS_CASCADE_IPTAL'

_PZM_TALEP_WHERE = (
    "(talep_referansi LIKE '\\_\\_PZM\\_V%' ESCAPE '\\' "
    "OR talep_referansi LIKE '\\_\\_MO\\_SIP\\_%' ESCAPE '\\' "
    "OR siparis_no LIKE 'PZM-%' "
    "OR siparis_no LIKE 'MO-S-%' "
    "OR kaynak_modul='MUSTERI_OPERASYONU')"
)

_BATCH_IPTAL_DURUMLAR = frozenset({'DEVAM', 'HAZIR', 'BEKLEME', 'IPTAL'})
_PLAN_IPTAL_DURUMLAR = frozenset({'URETIMDE', 'IPTAL'})


class SiparisUretimIptalError(Exception):
    def __init__(
        self,
        mesaj: str,
        http_status: int = 409,
        kod: str | None = None,
        nedenler: list[str] | None = None,
        audit: dict | None = None,
    ):
        super().__init__(mesaj)
        self.mesaj = mesaj
        self.http_status = http_status
        self.kod = kod or 'IPTAL_ENGELLI'
        self.nedenler = nedenler or [mesaj]
        self.audit = audit


def _tablo_var(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _kolon_var(con: sqlite3.Connection, tablo: str, kolon: str) -> bool:
    return kolon in {
        c[1] for c in con.execute(f'PRAGMA table_info({tablo})').fetchall()
    }


def _now_local() -> str:
    row = sqlite3.connect(':memory:').execute(
        "SELECT datetime('now','localtime') AS t",
    ).fetchone()
    return row[0]


def _pzm_yukle(con: sqlite3.Connection, siparis_id: int) -> sqlite3.Row | None:
    if not _tablo_var(con, 'nexgen_planlama_siparis'):
        return None
    return con.execute(
        f"""
        SELECT id, siparis_no, durum, talep_referansi, notlar
        FROM nexgen_planlama_siparis
        WHERE id=? AND {_PZM_TALEP_WHERE}
        """,
        (siparis_id,),
    ).fetchone()


def _mtt_bul(con: sqlite3.Connection, siparis_id: int) -> sqlite3.Row | None:
    if not _tablo_var(con, 'nexgen_musteri_temsilcisi_talep'):
        return None
    return con.execute(
        """
        SELECT id, talep_no, durum, donusturulen_siparis_id
        FROM nexgen_musteri_temsilcisi_talep
        WHERE donusturulen_siparis_id=?
        ORDER BY id DESC LIMIT 1
        """,
        (siparis_id,),
    ).fetchone()


def _planlar_yukle(con: sqlite3.Connection, siparis_id: int) -> list[sqlite3.Row]:
    if not _kolon_var(con, 'nexgen_uretim_plan', 'planlama_siparis_id'):
        return []
    return con.execute(
        """
        SELECT id, plan_kodu, durum
        FROM nexgen_uretim_plan
        WHERE planlama_siparis_id=?
        ORDER BY id
        """,
        (siparis_id,),
    ).fetchall()


def _batchler_yukle(con: sqlite3.Connection, plan_ids: list[int]) -> list[sqlite3.Row]:
    if not plan_ids or not _tablo_var(con, 'nexgen_uretim_batch'):
        return []
    ph = ','.join('?' * len(plan_ids))
    return con.execute(
        f"""
        SELECT id, batch_kodu, durum, plan_id, lot_kodu
        FROM nexgen_uretim_batch
        WHERE plan_id IN ({ph})
        ORDER BY id
        """,
        plan_ids,
    ).fetchall()


def _parca_ozet(con: sqlite3.Connection, batch_ids: list[int], batch_kodlari: list[str]) -> dict:
    if not _tablo_var(con, 'nexgen_uretim_parca'):
        return {'toplam': 0, 'hazir': 0, 'devam': 0, 'bitti': 0, 'iptal': 0,
                'uretilen_pozitif': 0, 'baslama_dolu': 0, 'bitis_dolu': 0}
    filtre = []
    params: list[Any] = []
    if batch_ids:
        ph = ','.join('?' * len(batch_ids))
        filtre.append(f'batch_id IN ({ph})')
        params.extend(batch_ids)
    if batch_kodlari:
        phb = ','.join('?' * len(batch_kodlari))
        filtre.append(f'batch_kodu IN ({phb})')
        params.extend(batch_kodlari)
    if not filtre:
        return {'toplam': 0, 'hazir': 0, 'devam': 0, 'bitti': 0, 'iptal': 0,
                'uretilen_pozitif': 0, 'baslama_dolu': 0, 'bitis_dolu': 0}
    where = ' OR '.join(f'({f})' for f in filtre)
    row = con.execute(
        f"""
        SELECT
            COUNT(*) AS toplam,
            SUM(CASE WHEN durum='HAZIR' THEN 1 ELSE 0 END) AS hazir,
            SUM(CASE WHEN durum='DEVAM' THEN 1 ELSE 0 END) AS devam,
            SUM(CASE WHEN durum='BITTI' THEN 1 ELSE 0 END) AS bitti,
            SUM(CASE WHEN durum='IPTAL' THEN 1 ELSE 0 END) AS iptal,
            SUM(CASE WHEN COALESCE(uretilen_kg, 0) > 0 THEN 1 ELSE 0 END) AS uretilen_pozitif,
            SUM(CASE WHEN baslama_zamani IS NOT NULL AND TRIM(baslama_zamani) != '' THEN 1 ELSE 0 END) AS baslama_dolu,
            SUM(CASE WHEN bitis_zamani IS NOT NULL AND TRIM(bitis_zamani) != '' THEN 1 ELSE 0 END) AS bitis_dolu
        FROM nexgen_uretim_parca
        WHERE {where}
        """,
        params,
    ).fetchone()
    return {k: int(row[k] or 0) for k in row.keys()}


def _stok_hareket_say(con: sqlite3.Connection, plan_ids: list[int], batch_ids: list[int]) -> int:
    if not plan_ids or not _tablo_var(con, 'nexgen_stok_hareket'):
        return 0
    ph = ','.join('?' * len(plan_ids))
    params = list(plan_ids)
    batch_sql = ''
    if batch_ids:
        phb = ','.join('?' * len(batch_ids))
        batch_sql = (
            f" OR (referans_tip IN ('URETIM_BATCH','BATCH') AND referans_id IN ({phb}))"
        )
        params.extend(batch_ids)
    return int(con.execute(
        f"""
        SELECT COUNT(*) FROM nexgen_stok_hareket
        WHERE (referans_tip IN ('URETIM_PLAN','PLAN','MPR_PLAN') AND referans_id IN ({ph}))
           {batch_sql}
        """,
        params,
    ).fetchone()[0] or 0)


def _sevkiyat_var(con: sqlite3.Connection, siparis_id: int) -> bool:
    if not _tablo_var(con, 'mo_musteri_sevkiyat'):
        return False
    return bool(con.execute(
        'SELECT 1 FROM mo_musteri_sevkiyat WHERE siparis_id=? LIMIT 1',
        (siparis_id,),
    ).fetchone())


def _finans_var(con: sqlite3.Connection, siparis_no: str) -> bool:
    if not siparis_no.strip() or not _tablo_var(con, 'finans_belgesi'):
        return False
    return bool(con.execute(
        """
        SELECT 1 FROM finans_belgesi
        WHERE IFNULL(aktif, 1)=1 AND IFNULL(siparis_no, '')=?
        LIMIT 1
        """,
        (siparis_no.strip(),),
    ).fetchone())


def _etiket_var(con: sqlite3.Connection, batch_ids: list[int]) -> bool:
    if not batch_ids or not _tablo_var(con, 'nexgen_arge_etiket'):
        return False
    ph = ','.join('?' * len(batch_ids))
    etiket_cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_arge_etiket)').fetchall()}
    aktif_sql = ' AND IFNULL(aktif,1)=1' if 'aktif' in etiket_cols else ''
    if con.execute(
        f"""
        SELECT 1 FROM nexgen_arge_etiket
        WHERE arge_kayit_id IN ({ph}){aktif_sql}
        LIMIT 1
        """,
        batch_ids,
    ).fetchone():
        return True
    if _tablo_var(con, 'nexgen_arge_etiket_yazdirma'):
        return bool(con.execute(
            f"""
            SELECT 1 FROM nexgen_arge_etiket_yazdirma y
            JOIN nexgen_arge_etiket e ON e.id = y.etiket_id
            WHERE e.arge_kayit_id IN ({ph}){aktif_sql.replace('aktif', 'e.aktif') if aktif_sql else ''}
            LIMIT 1
            """,
            batch_ids,
        ).fetchone())
    return False


def _rf_kayitlari(con: sqlite3.Connection, batch_ids: list[int], batch_kodlari: list[str]) -> list[sqlite3.Row]:
    if not _tablo_var(con, 'nexgen_rf_kullanim'):
        return []
    filtre = []
    params: list[Any] = []
    if batch_ids:
        ph = ','.join('?' * len(batch_ids))
        filtre.append(f'uretim_emir_id IN ({ph})')
        params.extend(batch_ids)
    if batch_kodlari:
        phb = ','.join('?' * len(batch_kodlari))
        filtre.append(f'tablet_session_id IN ({phb})')
        params.extend(batch_kodlari)
    if not filtre:
        return []
    return con.execute(
        f"SELECT id, durum, tablet_session_id, uretim_emir_id FROM nexgen_rf_kullanim WHERE {' OR '.join(filtre)}",
        params,
    ).fetchall()


def _rezerv_aktif_iptal(
    con: sqlite3.Connection,
    *,
    batch_kodu: str | None = None,
    plan_id: int | None = None,
    planlama_siparis_id: int | None = None,
    nedeni: str | None = None,
) -> dict:
    if not _tablo_var(con, 'nexgen_stok_rezerv'):
        return {'ok': True, 'atlandi': True, 'guncellenen': 0}
    filtre = ["durum='AKTIF'"]
    params: list[Any] = []
    if batch_kodu:
        filtre.append('batch_kodu=?')
        params.append(batch_kodu)
    if plan_id is not None:
        filtre.append('plan_id=?')
        params.append(plan_id)
    if planlama_siparis_id is not None:
        filtre.append('planlama_siparis_id=?')
        params.append(planlama_siparis_id)
    if len(filtre) == 1:
        return {'ok': False, 'hata': 'Rezerv iptal filtresi gerekli'}
    cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_stok_rezerv)').fetchall()}
    satirlar = con.execute(
        f"SELECT id, notlar FROM nexgen_stok_rezerv WHERE {' AND '.join(filtre)}",
        params,
    ).fetchall()
    nedeni_trim = (nedeni or '').strip() or None
    guncellenen = 0
    for sat in satirlar:
        set_parts = ["durum='IPTAL'"]
        upd_params: list[Any] = []
        if 'iptal_tarihi' in cols:
            set_parts.append("iptal_tarihi=datetime('now','localtime')")
        elif 'kapanis_tarihi' in cols:
            set_parts.append("kapanis_tarihi=datetime('now','localtime')")
        if 'iptal_nedeni' in cols:
            set_parts.append('iptal_nedeni=?')
            upd_params.append(nedeni_trim or '')
        elif nedeni_trim:
            mevcut = (sat['notlar'] or '').strip()
            yeni_not = (
                f"{mevcut} | İPTAL: {nedeni_trim}".strip(' |')
                if mevcut else f"İPTAL: {nedeni_trim}"
            )
            set_parts.append('notlar=?')
            upd_params.append(yeni_not)
        upd_params.append(sat['id'])
        con.execute(
            f"UPDATE nexgen_stok_rezerv SET {', '.join(set_parts)} WHERE id=?",
            upd_params,
        )
        guncellenen += 1
    return {'ok': True, 'guncellenen': guncellenen}


def _zincir_durum_ozet(con: sqlite3.Connection, siparis_id: int) -> dict:
    pzm = _pzm_yukle(con, siparis_id)
    if not pzm:
        raise SiparisUretimIptalError('Sipariş bulunamadı.', 404, 'SIPARIS_YOK')
    mtt = _mtt_bul(con, siparis_id)
    planlar = _planlar_yukle(con, siparis_id)
    plan_ids = [int(p['id']) for p in planlar]
    batchler = _batchler_yukle(con, plan_ids)
    batch_ids = [int(b['id']) for b in batchler]
    batch_kodlari = [(b['batch_kodu'] or '').strip() for b in batchler if b['batch_kodu']]
    parca = _parca_ozet(con, batch_ids, batch_kodlari)
    rf_rows = _rf_kayitlari(con, batch_ids, batch_kodlari)
    return {
        'pzm': dict(pzm),
        'mtt': dict(mtt) if mtt else None,
        'planlar': [dict(p) for p in planlar],
        'batchler': [dict(b) for b in batchler],
        'parca': parca,
        'rf': [dict(r) for r in rf_rows],
        'plan_ids': plan_ids,
        'batch_ids': batch_ids,
        'batch_kodlari': batch_kodlari,
    }


def _tam_iptal_mi(ozet: dict) -> bool:
    pzm = ozet['pzm']
    if (pzm.get('durum') or '').upper() != 'IPTAL':
        return False
    planlar = ozet['planlar']
    if planlar and not all((p.get('durum') or '').upper() == 'IPTAL' for p in planlar):
        return False
    batchler = ozet['batchler']
    if batchler and not all((b.get('durum') or '').upper() == 'IPTAL' for b in batchler):
        return False
    parca = ozet['parca']
    if parca['toplam'] > 0 and parca['iptal'] != parca['toplam']:
        return False
    for rf in ozet['rf']:
        if (rf.get('durum') or '').upper() != 'IPTAL':
            return False
    return True


def _kismi_iptal_mi(ozet: dict) -> bool:
    durumlar = [(ozet['pzm'].get('durum') or '').upper()]
    durumlar.extend((p.get('durum') or '').upper() for p in ozet['planlar'])
    durumlar.extend((b.get('durum') or '').upper() for b in ozet['batchler'])
    iptal_adet = sum(1 for d in durumlar if d == 'IPTAL')
    if iptal_adet == 0:
        return False
    return not _tam_iptal_mi(ozet)


def _guard_kontrol(con: sqlite3.Connection, ozet: dict) -> list[str]:
    nedenler: list[str] = []
    pzm = ozet['pzm']
    siparis_id = int(pzm['id'])
    siparis_no = (pzm.get('siparis_no') or '').strip()
    pzm_d = (pzm.get('durum') or '').upper()

    if pzm_d != 'URETIMDE':
        nedenler.append(f"PZM sipariş durumu URETIMDE olmalı (mevcut: {pzm_d or '—'}).")

    planlar = [p for p in ozet['planlar'] if (p.get('durum') or '').upper() != 'IPTAL']
    if not planlar:
        nedenler.append('Aktif üretim planı bulunamadı.')
    for p in planlar:
        pd = (p.get('durum') or '').upper()
        if pd == 'BITTI':
            nedenler.append(f"Plan {p.get('plan_kodu') or p.get('id')} BITTI durumunda; iptal edilemez.")
        elif pd != 'URETIMDE':
            nedenler.append(
                f"Plan {p.get('plan_kodu') or p.get('id')} durumu URETIMDE olmalı (mevcut: {pd})."
            )

    aktif_plan_ids = {int(p['id']) for p in planlar}
    batchler = [b for b in ozet['batchler'] if int(b['plan_id']) in aktif_plan_ids]
    if planlar and not batchler:
        nedenler.append('Aktif üretim batch kaydı bulunamadı.')
    for b in batchler:
        bd = (b.get('durum') or '').upper()
        if bd == 'BITTI':
            nedenler.append(f"Batch {b.get('batch_kodu') or b.get('id')} BITTI durumunda; iptal edilemez.")
        elif bd not in ('DEVAM', 'HAZIR'):
            nedenler.append(
                f"Batch {b.get('batch_kodu') or b.get('id')} durumu DEVAM veya HAZIR olmalı (mevcut: {bd})."
            )

    parca = ozet['parca']
    if parca['toplam'] > 0:
        if parca['hazir'] != parca['toplam']:
            nedenler.append(
                f"Tüm parçalar HAZIR olmalı (HAZIR={parca['hazir']}, toplam={parca['toplam']})."
            )
        if parca['uretilen_pozitif'] > 0:
            nedenler.append('uretilen_kg > 0 olan parça var; iptal edilemez.')
        if parca['baslama_dolu'] > 0:
            nedenler.append('baslama_zamani dolu parça var; iptal edilemez.')
        if parca['bitis_dolu'] > 0:
            nedenler.append('bitis_zamani dolu parça var; iptal edilemez.')

    stok_n = _stok_hareket_say(con, ozet['plan_ids'], ozet['batch_ids'])
    if stok_n:
        nedenler.append(f'Üretim/stok tüketim hareketi var ({stok_n} kayıt).')
    if _sevkiyat_var(con, siparis_id):
        nedenler.append('Sevkiyat kaydı var; iptal edilemez.')
    if _finans_var(con, siparis_no):
        nedenler.append('Finans hareketi / belge ilişkisi var; iptal edilemez.')
    if _etiket_var(con, ozet['batch_ids']):
        nedenler.append('Etiket/basım kaydı var; iptal edilemez.')

    return nedenler


def degerlendir_siparis_uretim_iptal(con: sqlite3.Connection, siparis_id: int) -> dict:
    ozet = _zincir_durum_ozet(con, siparis_id)
    if _tam_iptal_mi(ozet):
        return {
            'ok': True,
            'iptal_edilebilir': False,
            'already_cancelled': True,
            'kismi_iptal': False,
            'nedenler': [],
            'ozet': ozet,
        }
    if _kismi_iptal_mi(ozet):
        return {
            'ok': False,
            'iptal_edilebilir': False,
            'already_cancelled': False,
            'kismi_iptal': True,
            'nedenler': ['Zincirde yarım iptal durumu tespit edildi; otomatik tamamlanmaz.'],
            'ozet': ozet,
        }
    nedenler = _guard_kontrol(con, ozet)
    return {
        'ok': True,
        'iptal_edilebilir': len(nedenler) == 0,
        'already_cancelled': False,
        'kismi_iptal': False,
        'nedenler': nedenler,
        'ozet': ozet,
    }


def _audit_yaz(
    con: sqlite3.Connection,
    payload: dict,
    kullanici_id: int,
) -> dict:
    if not _tablo_var(con, 'nexgen_import_item_log') or not _tablo_var(con, 'nexgen_import_batch'):
        return {'ok': True, 'atlandi': True}
    detay = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    sha = hashlib.sha256(detay.encode('utf-8')).hexdigest()
    cur = con.execute(
        """
        INSERT INTO nexgen_import_batch
            (dosya_adi, dosya_sha256, durum, import_eden_id, import_zamani, kaynak_manifest_json)
        VALUES (?, ?, 'TAMAMLANDI', ?, datetime('now','localtime'), ?)
        """,
        (ISLEM_KODU, sha, kullanici_id, detay),
    )
    batch_id = cur.lastrowid
    con.execute(
        """
        INSERT INTO nexgen_import_item_log
            (import_batch_id, nesne_tipi, eski_id, aksiyon, detay_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            batch_id,
            'nexgen_planlama_siparis',
            payload.get('pzm_id'),
            ISLEM_KODU,
            detay,
        ),
    )
    return {'ok': True, 'audit_batch_id': batch_id}


def siparis_uretim_zinciri_iptal(
    con: sqlite3.Connection,
    siparis_id: int,
    *,
    siparis_no: str,
    iptal_nedeni: str,
    kullanici_id: int,
    client_submit_id: str | None = None,
) -> dict:
    nedeni = (iptal_nedeni or '').strip()
    if not nedeni:
        raise SiparisUretimIptalError('İptal nedeni zorunludur.', 400, 'NEDEN_ZORUNLU')

    own_tx = False
    try:
        con.execute('BEGIN IMMEDIATE')
        own_tx = True
    except sqlite3.OperationalError:
        pass

    try:
        ozet = _zincir_durum_ozet(con, siparis_id)
        pzm = ozet['pzm']
        beklenen_no = (pzm.get('siparis_no') or '').strip()
        if (siparis_no or '').strip() != beklenen_no:
            raise SiparisUretimIptalError(
                'Sipariş numarası doğrulanamadı.',
                400,
                'SIPARIS_NO_HATALI',
            )

        if _tam_iptal_mi(ozet):
            if own_tx:
                con.commit()
            return {
                'ok': True,
                'already_cancelled': True,
                'durum': 'IPTAL',
                'siparis_id': siparis_id,
                'siparis_no': beklenen_no,
            }

        if _kismi_iptal_mi(ozet):
            audit = {
                'islem': ISLEM_KODU,
                'pzm_id': siparis_id,
                'pzm_no': beklenen_no,
                'client_submit_id': client_submit_id,
                'hata': 'KISMI_IPTAL',
                'ozet': {
                    'pzm_durum': pzm.get('durum'),
                    'planlar': ozet['planlar'],
                    'batchler': ozet['batchler'],
                },
            }
            raise SiparisUretimIptalError(
                'Zincirde yarım iptal durumu var; otomatik tamamlanmaz.',
                409,
                'KISMI_IPTAL',
                audit=audit,
            )

        nedenler = _guard_kontrol(con, ozet)
        if nedenler:
            raise SiparisUretimIptalError(
                ' '.join(nedenler),
                409,
                'IPTAL_ENGELLI',
                nedenler=nedenler,
            )

        onceki = {
            'pzm': pzm.get('durum'),
            'planlar': {str(p['id']): p.get('durum') for p in ozet['planlar']},
            'batchler': {str(b['id']): b.get('durum') for b in ozet['batchler']},
            'parca_sayisi': ozet['parca']['toplam'],
            'rf': {str(r['id']): r.get('durum') for r in ozet['rf']},
            'mtt': ozet['mtt'].get('durum') if ozet['mtt'] else None,
        }

        rezerv_toplam = 0
        for b in ozet['batchler']:
            bk = (b.get('batch_kodu') or '').strip()
            if bk:
                r = _rezerv_aktif_iptal(con, batch_kodu=bk, nedeni=nedeni)
                rezerv_toplam += int(r.get('guncellenen') or 0)
        for pid in ozet['plan_ids']:
            r = _rezerv_aktif_iptal(con, plan_id=pid, nedeni=nedeni)
            rezerv_toplam += int(r.get('guncellenen') or 0)
        r = _rezerv_aktif_iptal(con, planlama_siparis_id=siparis_id, nedeni=nedeni)
        rezerv_toplam += int(r.get('guncellenen') or 0)

        if ozet['batch_ids'] and _tablo_var(con, 'nexgen_uretim_parca'):
            ph = ','.join('?' * len(ozet['batch_ids']))
            con.execute(
                f"""
                UPDATE nexgen_uretim_parca
                SET durum='IPTAL'
                WHERE batch_id IN ({ph}) AND durum='HAZIR'
                """,
                ozet['batch_ids'],
            )

        for b in ozet['batchler']:
            if (b.get('durum') or '').upper() != 'IPTAL':
                con.execute(
                    "UPDATE nexgen_uretim_batch SET durum='IPTAL' WHERE id=?",
                    (b['id'],),
                )

        for p in ozet['planlar']:
            if (p.get('durum') or '').upper() != 'IPTAL':
                con.execute(
                    "UPDATE nexgen_uretim_plan SET durum='IPTAL' WHERE id=?",
                    (p['id'],),
                )

        con.execute(
            """
            UPDATE nexgen_planlama_siparis
            SET durum='IPTAL', guncelleme_tarihi=datetime('now','localtime')
            WHERE id=?
            """,
            (siparis_id,),
        )

        if ozet['mtt'] and (ozet['mtt'].get('durum') or '').upper() == 'SIPARISE_DONUSTU':
            con.execute(
                """
                UPDATE nexgen_musteri_temsilcisi_talep
                SET durum='IPTAL', updated_at=datetime('now','localtime')
                WHERE id=? AND durum='SIPARISE_DONUSTU'
                """,
                (ozet['mtt']['id'],),
            )

        rf_cols = {c[1] for c in con.execute('PRAGMA table_info(nexgen_rf_kullanim)').fetchall()} if _tablo_var(con, 'nexgen_rf_kullanim') else set()
        for rf in ozet['rf']:
            if (rf.get('durum') or '').upper() == 'IPTAL':
                continue
            set_parts = ["durum='IPTAL'"]
            params: list[Any] = []
            if 'guncelleme_tarihi' in rf_cols:
                set_parts.append("guncelleme_tarihi=datetime('now','localtime')")
            params.append(rf['id'])
            con.execute(
                f"UPDATE nexgen_rf_kullanim SET {', '.join(set_parts)} WHERE id=?",
                params,
            )

        sonraki = _zincir_durum_ozet(con, siparis_id)
        if not _tam_iptal_mi(sonraki):
            raise SiparisUretimIptalError(
                'İptal sonrası tutarlılık doğrulanamadı; işlem geri alındı.',
                500,
                'TUTARSIZLIK',
            )

        audit_payload = {
            'islem': ISLEM_KODU,
            'pzm_id': siparis_id,
            'pzm_no': beklenen_no,
            'mtt_id': ozet['mtt']['id'] if ozet['mtt'] else None,
            'mtt_no': ozet['mtt']['talep_no'] if ozet['mtt'] else None,
            'plan_id': ozet['plan_ids'][0] if len(ozet['plan_ids']) == 1 else ozet['plan_ids'],
            'plan_no': ozet['planlar'][0]['plan_kodu'] if len(ozet['planlar']) == 1 else [p['plan_kodu'] for p in ozet['planlar']],
            'batch_id': ozet['batch_ids'][0] if len(ozet['batch_ids']) == 1 else ozet['batch_ids'],
            'batch_no': ozet['batch_kodlari'][0] if len(ozet['batch_kodlari']) == 1 else ozet['batch_kodlari'],
            'parca_sayisi': ozet['parca']['toplam'],
            'iptal_eden_kullanici_id': kullanici_id,
            'iptal_tarihi': _now_local(),
            'iptal_nedeni': nedeni,
            'client_submit_id': client_submit_id,
            'onceki_durumlar': onceki,
            'sonraki_durumlar': {
                'pzm': 'IPTAL',
                'planlar': 'IPTAL',
                'batchler': 'IPTAL',
                'parca': 'IPTAL',
                'rf': 'IPTAL',
                'mtt': 'IPTAL' if ozet['mtt'] else None,
            },
            'rezerv_iptal_adet': rezerv_toplam,
        }
        audit = _audit_yaz(con, audit_payload, kullanici_id)

        if own_tx:
            con.commit()

        return {
            'ok': True,
            'already_cancelled': False,
            'durum': 'IPTAL',
            'siparis_id': siparis_id,
            'siparis_no': beklenen_no,
            'parca_sayisi': ozet['parca']['toplam'],
            'rezerv_iptal': rezerv_toplam,
            'audit': audit,
            'mesaj': 'Sipariş ve bağlı üretim zinciri iptal edildi.',
        }
    except SiparisUretimIptalError:
        if own_tx:
            con.rollback()
        raise
    except Exception:
        if own_tx:
            con.rollback()
        raise
