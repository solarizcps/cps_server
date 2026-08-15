# -*- coding: utf-8 -*-
"""Cari360 operasyon timeline — federasyon read-model (FAZ-3B).

Yeni tablo yok. SELECT-only. Soft-write/backfill çağrılmaz.
Merkez kimlik: nexgen_cari.id
"""
from __future__ import annotations

import sqlite3
from typing import Any

from modules.nexgen.cari_sorumlu_service import can_view_cari
from modules.nexgen.cari360_relation_policy import (
    PARENT_ARGE,
    PARENT_CARI,
    PARENT_GORUSME,
    PARENT_NUMUNE,
    PARENT_SIPARIS,
    classify_mo_gorusme_parent,
    classify_siparis_parent,
    iid as _iid,
    resolve_tek_sorumlu,
)
from modules.nexgen.mo_gorusme_config import TABLO as GORUSME_TABLO
from modules.nexgen.mo_gorusme_service import is_gerceklesmis_gorusme_tarihi

# Olay önceliği (aynı olay_tarihi için; düşük = önce listede DESC sonrası tie-break)
_EVENT_PRIORITY = {
    'SEVKIYAT': 10,
    'TAHSILAT': 15,
    'URETIM_COMPLETED': 20,
    'URETIM_STARTED': 30,
    'SIPARIS_CREATED': 40,
    'SIPARIS_ONAYLANDI': 42,
    'SIPARIS_REDDEDILDI': 43,
    'SIPARIS_REVIZYON': 44,
    'CEK_KAYDI': 45,
    'MTT_ONAY': 46,
    'MTT_YASAM': 45,
    'ONAY_TALEBI': 46,
    'RF_APPROVED': 50,
    'RF_CREATED': 60,
    'ARGE_CREATED': 70,
    'NUMUNE_CREATED': 80,
    'GORUSME_CREATED': 90,
    'GORUSME_PLANLANDI': 88,
    'PAZARLAMACI': 100,
}

_URETIM_TAMAM_DURUM = frozenset({
    'TAMAMLANDI', 'BITTI', 'BITIRILDI', 'DONE', 'COMPLETED', 'KAPANDI',
})
_URETIM_PARCA_TAMAM = frozenset({
    'TAMAMLANDI', 'BITTI', 'BITIRILDI', 'DONE', 'COMPLETED', 'BITTI_OK',
})

_AJANDA_TABLO = 'musteri_operasyon_ajanda'
_AJANDA_DURUM_GOSTER = frozenset({'PLANLANDI', 'GERCEKLESTI'})


def _sevk_timeline_baslik(durum: str | None) -> str:
    """Sevkiyat timeline başlığı — canonical durum değerini değiştirmez."""
    d = (durum or '').strip().upper()
    if d == 'HAZIRLANIYOR':
        return 'Sevkiyat hazırlanıyor'
    if d == 'SEVK_EDILDI':
        return 'Sevkiyat yapıldı'
    if d == 'TESLIM_EDILDI':
        return 'Sevkiyat teslim edildi'
    if d == 'TAMAMLANDI':
        return 'Sevkiyat tamamlandı'
    return 'Sevkiyat yapıldı'


def _ajanda_adhoc_idempotency(idem: str | None) -> bool:
    return str(idem or '').startswith('ADHOC-GOR-')


class Cari360TimelineError(Exception):
    def __init__(self, mesaj: str, kod: int = 400):
        self.mesaj = mesaj
        self.kod = kod
        super().__init__(mesaj)


def _tablo_var(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _kolonlar(con: sqlite3.Connection, tablo: str) -> set[str]:
    return {c[1] for c in con.execute(f'PRAGMA table_info({tablo})').fetchall()}


def _parse_dt(val: Any) -> str:
    if not val:
        return ''
    s = str(val).strip()
    if not s:
        return ''
    return (s + ' 12:00:00') if len(s) == 10 else s[:19]


def _user_map(con: sqlite3.Connection, uids: set[int]) -> dict[int, str]:
    out: dict[int, str] = {}
    ids = [i for i in uids if i]
    if not ids or not _tablo_var(con, 'sistem_kullanici'):
        return out
    ph = ','.join('?' * len(ids))
    for r in con.execute(
        f'SELECT Id, AdSoyad, KullaniciAdi FROM sistem_kullanici WHERE Id IN ({ph})',
        ids,
    ):
        out[int(r['Id'])] = (
            (r['AdSoyad'] or r['KullaniciAdi'] or '').strip() or str(r['Id'])
        )
    return out


def _event(
    *,
    olay_kodu: str,
    entity_type: str,
    entity_id: int | str,
    cari_id: int,
    olay_tarihi: str,
    baslik: str,
    aciklama: str = '',
    durum: str = '',
    kategori: str,
    parent_type: str | None = None,
    parent_id: int | str | None = None,
    olusturan_kullanici_id: int | None = None,
    olusturan_kullanici: str | None = None,
    icon: str = '',
    renk: str = '',
    hedef_modul: str = '',
    hedef_id: int | str | None = None,
    detay_url: str = '',
    dedupe_key: str,
    result_type: str | None = None,
    result_id: int | str | None = None,
    baslangic_tipi: str | None = None,
    zincir_eksik: bool = False,
    zincir_uyarilari: list[str] | None = None,
    kayit_no: str = '',
    oncelik: int | None = None,
    metadata: dict | None = None,
    hareket_turu: str | None = None,
) -> dict[str, Any]:
    uyarilar = list(zincir_uyarilari or [])
    dt = _parse_dt(olay_tarihi)
    if not dt:
        uyarilar.append('TARIH_EKSIK')
        dt = '1970-01-01 00:00:00'
    pri = oncelik if oncelik is not None else _EVENT_PRIORITY.get(olay_kodu, 50)
    # Eski hafıza alanları + 3B contract (backward compatible)
    return {
        'event_date': dt,
        'olay_tarihi': dt,
        'hareket_turu': hareket_turu or baslik,
        'title': baslik,
        'baslik': baslik,
        'short_description': (aciklama or '')[:500],
        'aciklama': (aciklama or '')[:500],
        'status': durum or '—',
        'durum': durum or '—',
        'source_type': entity_type,
        'source_id': entity_id,
        'kayit_no': kayit_no or str(entity_id),
        'tutar': '',
        'termin': '',
        'category': kategori,
        'kategori': kategori,
        'test_kayit': False,
        'dedupe_key': dedupe_key,
        'audit_events': [],
        'metadata': metadata or {},
        'detay_url': detay_url or '',
        'oncelik': pri,
        'sonraki_asama': '',
        'gecikme': '',
        'entity_type': entity_type,
        'entity_id': entity_id,
        'parent_type': parent_type,
        'parent_id': parent_id,
        'cari_id': int(cari_id),
        'olusturan_kullanici_id': olusturan_kullanici_id,
        'olusturan_kullanici': olusturan_kullanici,
        'icon': icon or '',
        'renk': renk or ('uyari' if zincir_eksik else ''),
        'hedef_modul': hedef_modul or '',
        'hedef_id': hedef_id if hedef_id is not None else entity_id,
        'result_type': result_type,
        'result_id': result_id,
        'baslangic_tipi': baslangic_tipi,
        'zincir_eksik': bool(zincir_eksik),
        'zincir_uyarilari': uyarilar,
        'olay_kodu': olay_kodu,
    }


def build_ops_timeline(
    con: sqlite3.Connection,
    cari_id: int,
    *,
    include_test: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Operasyon zinciri olayları — SELECT only, batch sorgular."""
    cid = int(cari_id)
    kart = f'/nexgen/cari360/{cid}'
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    qstats: dict[str, int] = {}

    def _add(ev: dict[str, Any]) -> None:
        dk = ev.get('dedupe_key') or ''
        if not dk or dk in seen:
            return
        if ev.get('test_kayit') and not include_test:
            return
        seen.add(dk)
        events.append(ev)

    # --- kullanıcı id toplama sonra lookup ---
    user_ids: set[int] = set()

    # 1) Tek sorumlu
    sorumlu_meta = resolve_tek_sorumlu(con, cid)
    qstats['q_sorumlu'] = 1
    sorumlu = sorumlu_meta.get('sorumlu')
    if sorumlu:
        if sorumlu.get('kullanici_id'):
            user_ids.add(int(sorumlu['kullanici_id']))
        if sorumlu.get('atayan_kullanici_id'):
            user_ids.add(int(sorumlu['atayan_kullanici_id']))

    # 2) Görüşmeler
    gorusme_by_id: dict[int, dict] = {}
    gorusme_rows: list[dict] = []
    if _tablo_var(con, GORUSME_TABLO):
        for r in con.execute(
            f"""
            SELECT id, cari_id, kullanici_id, olusturan_kullanici_id, gorusme_tipi,
                   sonuc_tipi, kisa_not, gorusme_tarihi, olusturma_tarihi, aktif,
                   takip_durumu, konu, numune_talep_id, idempotency_key
            FROM {GORUSME_TABLO}
            WHERE cari_id=? AND COALESCE(aktif,1)=1
            """,
            (cid,),
        ):
            d = dict(r)
            gorusme_by_id[int(d['id'])] = d
            if is_gerceklesmis_gorusme_tarihi(d.get('gorusme_tarihi')):
                gorusme_rows.append(d)
            for k in ('kullanici_id', 'olusturan_kullanici_id'):
                uid = _iid(d.get(k))
                if uid:
                    user_ids.add(uid)
        qstats['q_gorusme'] = 1

    # 3) Numuneler
    numune_rows: list[dict] = []
    numune_ids: list[int] = []
    ncols = _kolonlar(con, 'nexgen_numune_talep') if _tablo_var(con, 'nexgen_numune_talep') else set()
    if ncols:
        extra = []
        for c in ('mo_gorusme_id', 'rf_renk_id', 'arge_test_id', 'talep_eden_kullanici_id',
                  'olusturan_kullanici_id', 'urun_adi', 'urun_tipi', 'aciklama', 'idempotency_key'):
            if c in ncols:
                extra.append(c)
        sel = 'id, talep_kodu, durum, olusturma_tarihi, guncelleme_tarihi, cari_id, aktif'
        if extra:
            sel += ', ' + ', '.join(extra)
        for r in con.execute(
            f'SELECT {sel} FROM nexgen_numune_talep WHERE cari_id=? AND COALESCE(aktif,1)=1',
            (cid,),
        ):
            d = dict(r)
            numune_rows.append(d)
            numune_ids.append(int(d['id']))
            for k in ('talep_eden_kullanici_id', 'olusturan_kullanici_id'):
                uid = _iid(d.get(k))
                if uid:
                    user_ids.add(uid)
        qstats['q_numune'] = 1

    # 4) AR-GE (cari + numune bağları)
    arge_by_id: dict[int, dict] = {}
    if _tablo_var(con, 'nexgen_arge_test'):
        acols = _kolonlar(con, 'nexgen_arge_test')
        has_ntp = 'numune_talep_id' in acols
        # a) cari_id
        for r in con.execute(
            f"""
            SELECT id, test_no, durum, olusturma_tarihi, olusturan_id, cari_id,
                   rf_renk_id, talep_referansi, yeni_renk_adi, renk_kodu,
                   formul_grup_adi, ana_formul_grup_kodu, aktif
                   {', numune_talep_id' if has_ntp else ', NULL AS numune_talep_id'}
            FROM nexgen_arge_test
            WHERE cari_id=? AND COALESCE(aktif,1)=1
            """,
            (cid,),
        ):
            arge_by_id[int(r['id'])] = dict(r)
        # b) numune_talep_id IN
        if has_ntp and numune_ids:
            ph = ','.join('?' * len(numune_ids))
            for r in con.execute(
                f"""
                SELECT id, test_no, durum, olusturma_tarihi, olusturan_id, cari_id,
                       rf_renk_id, talep_referansi, yeni_renk_adi, renk_kodu,
                       formul_grup_adi, ana_formul_grup_kodu, aktif, numune_talep_id
                FROM nexgen_arge_test
                WHERE numune_talep_id IN ({ph}) AND COALESCE(aktif,1)=1
                """,
                numune_ids,
            ):
                arge_by_id.setdefault(int(r['id']), dict(r))
        # c) numune.arge_test_id pointers
        ptrs = [_iid(n.get('arge_test_id')) for n in numune_rows]
        ptrs = [p for p in ptrs if p and p not in arge_by_id]
        if ptrs:
            ph = ','.join('?' * len(ptrs))
            for r in con.execute(
                f"""
                SELECT id, test_no, durum, olusturma_tarihi, olusturan_id, cari_id,
                       rf_renk_id, talep_referansi, yeni_renk_adi, renk_kodu,
                       formul_grup_adi, ana_formul_grup_kodu, aktif
                       {', numune_talep_id' if has_ntp else ', NULL AS numune_talep_id'}
                FROM nexgen_arge_test WHERE id IN ({ph})
                """,
                ptrs,
            ):
                arge_by_id.setdefault(int(r['id']), dict(r))
        for a in arge_by_id.values():
            uid = _iid(a.get('olusturan_id'))
            if uid:
                user_ids.add(uid)
        qstats['q_arge'] = 1 + (1 if has_ntp and numune_ids else 0) + (1 if ptrs else 0)

    # 5) RF — cari / ilk_talep / kaynak_arge
    rf_by_id: dict[int, dict] = {}
    if _tablo_var(con, 'nexgen_rf_renk'):
        rcols = _kolonlar(con, 'nexgen_rf_renk')
        arge_ids = list(arge_by_id.keys())
        clauses = ['cari_id=?', 'ilk_talep_cari_id=?']
        params: list[Any] = [cid, cid]
        if 'kaynak_arge_test_id' in rcols and arge_ids:
            ph = ','.join('?' * len(arge_ids))
            clauses.append(f'kaynak_arge_test_id IN ({ph})')
            params.extend(arge_ids)
        # numune/arge rf pointers
        rf_ptrs: set[int] = set()
        for n in numune_rows:
            rid = _iid(n.get('rf_renk_id'))
            if rid:
                rf_ptrs.add(rid)
        for a in arge_by_id.values():
            rid = _iid(a.get('rf_renk_id'))
            if rid:
                rf_ptrs.add(rid)
        if rf_ptrs:
            ph = ','.join('?' * len(rf_ptrs))
            clauses.append(f'id IN ({ph})')
            params.extend(rf_ptrs)
        sql = f"""
            SELECT id, rf_kod, ad, durum, aktif, olusturma_tarihi, onay_tarihi,
                   olusturan_id, onaylayan_id, kaynak_arge_test_id,
                   ilk_talep_cari_id, cari_id, aktif_rev_no
            FROM nexgen_rf_renk
            WHERE {' OR '.join(clauses)}
        """
        for r in con.execute(sql, params):
            d = dict(r)
            # leak koruması: cari doluysa bu cari olmalı
            rc = _iid(d.get('cari_id'))
            itc = _iid(d.get('ilk_talep_cari_id'))
            if rc is not None and rc != cid and (itc is None or itc != cid):
                # yalnız kaynak_arge ile geldiyse ve arge bu carinin ise izin ver
                kid = _iid(d.get('kaynak_arge_test_id'))
                if not (kid and kid in arge_by_id):
                    continue
            rf_by_id[int(d['id'])] = d
            for k in ('olusturan_id', 'onaylayan_id'):
                uid = _iid(d.get(k))
                if uid:
                    user_ids.add(uid)
        qstats['q_rf'] = 1

    # 6) Siparişler — durum/çek/tahsilat alanları dahil
    siparis_rows: list[dict] = []
    _siparis_scols: set[str] = set()
    if _tablo_var(con, 'nexgen_planlama_siparis'):
        scols = _kolonlar(con, 'nexgen_planlama_siparis')
        _siparis_scols = scols
        mo_sel = ', mo_gorusme_id' if 'mo_gorusme_id' in scols else ', NULL AS mo_gorusme_id'
        extra_cols = ''
        for _ec in ('cek_vadesi', 'cek_vade_gun', 'odeme_tipi', 'vade_gun',
                    'tahsilat_durumu', 'revizyon_gerekce'):
            if _ec in scols:
                extra_cols += f', {_ec}'
        for r in con.execute(
            f"""
            SELECT id, siparis_no, durum, olusturma_tarihi, guncelleme_tarihi,
                   olusturan_id, cari_id, notlar, talep_referansi, idempotency_key
                   {mo_sel}{extra_cols}
            FROM nexgen_planlama_siparis
            WHERE cari_id=?
            """,
            (cid,),
        ):
            d = dict(r)
            siparis_rows.append(d)
            uid = _iid(d.get('olusturan_id'))
            if uid:
                user_ids.add(uid)
        qstats['q_siparis'] = 1

    # 7) Üretim plan + aggregate parça
    plan_rows: list[dict] = []
    plan_agg: dict[int, dict[str, Any]] = {}
    if _tablo_var(con, 'nexgen_uretim_plan'):
        for r in con.execute(
            """
            SELECT id, plan_kodu, durum, created_at, plan_tarihi, created_by,
                   cari_id, planlama_siparis_id, siparis_no, termin_tarihi
            FROM nexgen_uretim_plan
            WHERE cari_id=?
            """,
            (cid,),
        ):
            d = dict(r)
            # leak
            if _iid(d.get('cari_id')) not in (None, cid):
                continue
            plan_rows.append(d)
            uid = _iid(d.get('created_by'))
            if uid:
                user_ids.add(uid)
        qstats['q_uretim_plan'] = 1
        if plan_rows and _tablo_var(con, 'nexgen_uretim_parca'):
            pids = [int(p['id']) for p in plan_rows]
            ph = ','.join('?' * len(pids))
            for r in con.execute(
                f"""
                SELECT plan_id,
                       MIN(CASE WHEN baslama_zamani IS NOT NULL AND TRIM(baslama_zamani)!=''
                                THEN baslama_zamani END) AS first_start,
                       MAX(CASE WHEN bitis_zamani IS NOT NULL AND TRIM(bitis_zamani)!=''
                                THEN bitis_zamani END) AS last_end,
                       COUNT(*) AS parca_n,
                       SUM(CASE WHEN bitis_zamani IS NOT NULL AND TRIM(bitis_zamani)!=''
                                  OR UPPER(COALESCE(durum,'')) IN
                                    ('TAMAMLANDI','BITTI','BITIRILDI','DONE','COMPLETED')
                                THEN 1 ELSE 0 END) AS parca_done
                FROM nexgen_uretim_parca
                WHERE plan_id IN ({ph})
                GROUP BY plan_id
                """,
                pids,
            ):
                plan_agg[int(r['plan_id'])] = dict(r)
            qstats['q_uretim_agg'] = 1

    # 8) Sevkiyat
    sevk_rows: list[dict] = []
    if _tablo_var(con, 'mo_musteri_sevkiyat'):
        for r in con.execute(
            """
            SELECT id, sevkiyat_no, siparis_id, cari_id, durum, sevk_tarihi,
                   olusturma_tarihi, guncelleme_tarihi, olusturan_id, aktif
            FROM mo_musteri_sevkiyat
            WHERE cari_id=? AND COALESCE(aktif,1)=1
            """,
            (cid,),
        ):
            d = dict(r)
            if _iid(d.get('cari_id')) not in (None, cid):
                continue
            sevk_rows.append(d)
            uid = _iid(d.get('olusturan_id'))
            if uid:
                user_ids.add(uid)
        qstats['q_sevkiyat'] = 1

    # 9) Ajanda planları (timeline read-only)
    ajanda_rows: list[dict] = []
    if _tablo_var(con, _AJANDA_TABLO):
        for r in con.execute(
            f"""
            SELECT id, cari_id, kullanici_id, plan_tarihi, gorusme_tipi, plan_notu,
                   durum, gorusme_id, idempotency_key, olusturma_tarihi, aktif,
                   plan_yetkili_metin, olusturan_kullanici_id
            FROM {_AJANDA_TABLO}
            WHERE cari_id=? AND COALESCE(aktif,1)=1
            """,
            (cid,),
        ):
            d = dict(r)
            if _ajanda_adhoc_idempotency(d.get('idempotency_key')):
                continue
            durum_u = (d.get('durum') or '').strip().upper()
            if durum_u not in _AJANDA_DURUM_GOSTER:
                continue
            ajanda_rows.append(d)
            for k in ('kullanici_id', 'olusturan_kullanici_id'):
                uid = _iid(d.get(k))
                if uid:
                    user_ids.add(uid)
        qstats['q_ajanda'] = 1

    users = _user_map(con, user_ids)
    qstats['q_users'] = 1 if user_ids else 0

    # Parent doğrulama için eksik numune / sipariş id'lerini toplu yükle (N+1 yok)
    missing_ntp = {
        _iid(a.get('numune_talep_id'))
        for a in arge_by_id.values()
        if _iid(a.get('numune_talep_id')) and _iid(a.get('numune_talep_id')) not in set(numune_ids)
    }
    missing_ntp.discard(None)
    nt_cari_map: dict[int, int | None] = {i: cid for i in numune_ids}
    if missing_ntp and _tablo_var(con, 'nexgen_numune_talep'):
        ph = ','.join('?' * len(missing_ntp))
        for r in con.execute(
            f'SELECT id, cari_id FROM nexgen_numune_talep WHERE id IN ({ph})',
            list(missing_ntp),
        ):
            nt_cari_map[int(r['id'])] = _iid(r['cari_id'])
        qstats['q_numune_parent'] = 1

    missing_arge = {
        _iid(rf.get('kaynak_arge_test_id'))
        for rf in rf_by_id.values()
        if _iid(rf.get('kaynak_arge_test_id'))
        and _iid(rf.get('kaynak_arge_test_id')) not in arge_by_id
    }
    missing_arge.discard(None)
    arge_cari_map: dict[int, int | None] = {
        i: _iid(a.get('cari_id')) for i, a in arge_by_id.items()
    }
    if missing_arge and _tablo_var(con, 'nexgen_arge_test'):
        ph = ','.join('?' * len(missing_arge))
        for r in con.execute(
            f'SELECT id, cari_id FROM nexgen_arge_test WHERE id IN ({ph})',
            list(missing_arge),
        ):
            arge_cari_map[int(r['id'])] = _iid(r['cari_id'])
        qstats['q_arge_parent'] = 1

    siparis_by_id_pre = {int(s['id']): s for s in siparis_rows}
    missing_sip: set[int] = set()
    for p in plan_rows:
        sid = _iid(p.get('planlama_siparis_id'))
        if sid and sid not in siparis_by_id_pre:
            missing_sip.add(sid)
    for s in sevk_rows:
        sid = _iid(s.get('siparis_id'))
        if sid and sid not in siparis_by_id_pre:
            missing_sip.add(sid)
    sip_cari_map: dict[int, int | None] = {
        i: cid for i in siparis_by_id_pre
    }
    if missing_sip and _tablo_var(con, 'nexgen_planlama_siparis'):
        ph = ','.join('?' * len(missing_sip))
        for r in con.execute(
            f'SELECT id, cari_id FROM nexgen_planlama_siparis WHERE id IN ({ph})',
            list(missing_sip),
        ):
            sip_cari_map[int(r['id'])] = _iid(r['cari_id'])
        qstats['q_siparis_parent'] = 1

    # ---- Olay üretimi ----
    dogrudan_numune = 0
    dogrudan_siparis = 0
    zincir_uyari_toplam = 0

    # Pazarlamacı
    if sorumlu:
        uyarilar = list(sorumlu_meta.get('sorumlu_uyarilari') or [])
        zincir_uyari_toplam += len(uyarilar)
        kid = sorumlu.get('kullanici_id')
        _add(_event(
            olay_kodu='PAZARLAMACI',
            entity_type='cari_sorumlu',
            entity_id=int(sorumlu['id']),
            cari_id=cid,
            olay_tarihi=sorumlu.get('baslangic_tarihi') or '',
            baslik='Pazarlamacı atandı',
            aciklama=sorumlu.get('kullanici_adi') or '',
            durum='Aktif',
            kategori='cari',
            parent_type=PARENT_CARI,
            parent_id=cid,
            olusturan_kullanici_id=sorumlu.get('atayan_kullanici_id'),
            olusturan_kullanici=users.get(sorumlu['atayan_kullanici_id'] or 0),
            icon='user',
            renk='',
            hedef_modul='cari360',
            hedef_id=cid,
            detay_url=f'{kart}?tab=genel',
            dedupe_key=f'PAZARLAMACI:{sorumlu["id"]}',
            baslangic_tipi='PAZARLAMACI',
            zincir_eksik=False,
            zincir_uyarilari=uyarilar,
            kayit_no=str(sorumlu['id']),
            hareket_turu='Sorumlu',
            metadata={'kullanici_id': kid, 'rol': sorumlu.get('sorumluluk_rolu') or sorumlu.get('rol')},
        ))

    # Görüşme
    for g in gorusme_rows:
        gid = int(g['id'])
        uid = _iid(g.get('olusturan_kullanici_id')) or _iid(g.get('kullanici_id'))
        _add(_event(
            olay_kodu='GORUSME_CREATED',
            entity_type='musteri_operasyon_gorusme',
            entity_id=gid,
            cari_id=cid,
            olay_tarihi=g.get('gorusme_tarihi') or g.get('olusturma_tarihi') or '',
            baslik='Görüşme yapıldı',
            aciklama=(g.get('konu') or g.get('kisa_not') or g.get('gorusme_tipi') or '')[:300],
            durum=(g.get('takip_durumu') or g.get('sonuc_tipi') or '—'),
            kategori='gorusmeler',
            parent_type=PARENT_CARI,
            parent_id=cid,
            olusturan_kullanici_id=uid,
            olusturan_kullanici=users.get(uid or 0),
            icon='chat',
            hedef_modul='gorusme',
            hedef_id=gid,
            detay_url=f'{kart}?tab=gorusmeler',
            dedupe_key=f'GORUSME_CREATED:{gid}',
            baslangic_tipi='GORUSME',
            kayit_no=str(gid),
            hareket_turu='Görüşme',
        ))

    # Ajanda planlama (olay_tarihi = olusturma_tarihi; plan_tarihi yalnız özet)
    for a in ajanda_rows:
        aid = int(a['id'])
        olusturma = a.get('olusturma_tarihi') or ''
        if not olusturma:
            continue
        uid = _iid(a.get('kullanici_id'))
        pazarlamaci = users.get(uid or 0) or ''
        ozet_parcalar: list[str] = []
        if a.get('plan_tarihi'):
            ozet_parcalar.append(f"Plan: {str(a['plan_tarihi'])[:16]}")
        if a.get('gorusme_tipi'):
            ozet_parcalar.append(str(a['gorusme_tipi']))
        if a.get('plan_notu'):
            ozet_parcalar.append(str(a['plan_notu'])[:200])
        if pazarlamaci:
            ozet_parcalar.append(pazarlamaci)
        elif a.get('plan_yetkili_metin'):
            ozet_parcalar.append(str(a['plan_yetkili_metin']))
        _add(_event(
            olay_kodu='GORUSME_PLANLANDI',
            entity_type=_AJANDA_TABLO,
            entity_id=aid,
            cari_id=cid,
            olay_tarihi=olusturma,
            baslik='Görüşme planlandı',
            aciklama=' · '.join(x for x in ozet_parcalar if x),
            durum=(a.get('durum') or 'PLANLANDI'),
            kategori='gorusmeler',
            parent_type=PARENT_CARI,
            parent_id=cid,
            olusturan_kullanici_id=uid or _iid(a.get('olusturan_kullanici_id')),
            olusturan_kullanici=pazarlamaci or None,
            icon='calendar',
            hedef_modul='gorusme',
            hedef_id=aid,
            detay_url=f'{kart}?tab=gorusmeler',
            dedupe_key=f'GORUSME_PLANLANDI:{aid}',
            baslangic_tipi='AJANDA_PLAN',
            kayit_no=str(aid),
            hareket_turu='Görüşme',
            metadata={
                'plan_tarihi': a.get('plan_tarihi'),
                'gorusme_tipi': a.get('gorusme_tipi'),
                'plan_notu': a.get('plan_notu'),
                'gorusme_id': a.get('gorusme_id'),
            },
        ))

    # Numune
    for n in numune_rows:
        nid = int(n['id'])
        gid = _iid(n.get('mo_gorusme_id'))
        rel = classify_mo_gorusme_parent(gid, cid, gorusme_by_id, kind='NUMUNE')
        if rel['baslangic_tipi'] == 'DOGRUDAN_NUMUNE':
            dogrudan_numune += 1
            acik_extra = 'Doğrudan numune talebi'
        elif rel['baslangic_tipi'] == 'ZINCIR_KOPUK':
            acik_extra = 'Kırık görüşme bağlantısı'
        else:
            acik_extra = ''
        if rel['zincir_eksik']:
            zincir_uyari_toplam += 1
        kod = n.get('talep_kodu') or str(nid)
        acik = f"{kod} · {n.get('urun_adi') or n.get('urun_tipi') or ''}".strip(' ·')
        if acik_extra:
            acik = f'{acik} · {acik_extra}' if acik else acik_extra
        uid = _iid(n.get('olusturan_kullanici_id')) or _iid(n.get('talep_eden_kullanici_id'))
        rf_id = _iid(n.get('rf_renk_id'))
        _add(_event(
            olay_kodu='NUMUNE_CREATED',
            entity_type='nexgen_numune_talep',
            entity_id=nid,
            cari_id=cid,
            olay_tarihi=n.get('olusturma_tarihi') or '',
            baslik='Numune talebi açıldı',
            aciklama=acik,
            durum=(n.get('durum') or '—'),
            kategori='numuneler',
            parent_type=rel['parent_type'],
            parent_id=rel['parent_id'],
            olusturan_kullanici_id=uid,
            olusturan_kullanici=users.get(uid or 0),
            icon='sample',
            renk='uyari' if rel['zincir_eksik'] else '',
            hedef_modul='numune',
            hedef_id=nid,
            detay_url=f'{kart}?tab=numuneler',
            dedupe_key=f'NUMUNE_CREATED:{nid}',
            result_type='nexgen_rf_renk' if rf_id else None,
            result_id=rf_id,
            baslangic_tipi=rel['baslangic_tipi'],
            zincir_eksik=rel['zincir_eksik'],
            zincir_uyarilari=rel['zincir_uyarilari'],
            kayit_no=kod,
            hareket_turu='Numune',
            metadata={'mo_gorusme_id': gid, 'rf_renk_id': rf_id},
        ))

    # AR-GE
    for aid, a in arge_by_id.items():
        # leak: arge başka cariye ait ve numune bağı bu cari değilse atla
        ac = _iid(a.get('cari_id'))
        ntp = _iid(a.get('numune_talep_id'))
        if ac is not None and ac != cid and not (ntp and ntp in set(numune_ids)):
            continue
        uyarilar: list[str] = []
        zeksik = False
        parent_type = parent_id = None
        btip = 'LEGACY_ARGE'
        if ntp:
            if ntp in nt_cari_map:
                if nt_cari_map[ntp] == cid:
                    parent_type, parent_id = PARENT_NUMUNE, ntp
                    btip = 'NUMUNEDEN_ARGE'
                else:
                    btip = 'ZINCIR_KOPUK'
                    zeksik = True
                    uyarilar.append('PARENT_BASKA_CARI')
            else:
                btip = 'ZINCIR_KOPUK'
                zeksik = True
                uyarilar.append('PARENT_BULUNAMADI')
        elif (a.get('talep_referansi') or '').strip():
            btip = 'LEGACY_ARGE'
            parent_type, parent_id = PARENT_CARI, cid
        else:
            parent_type, parent_id = PARENT_CARI, cid
            btip = 'LEGACY_ARGE'
        if zeksik:
            zincir_uyari_toplam += 1
        uid = _iid(a.get('olusturan_id'))
        rf_id = _iid(a.get('rf_renk_id'))
        _add(_event(
            olay_kodu='ARGE_CREATED',
            entity_type='nexgen_arge_test',
            entity_id=aid,
            cari_id=cid,
            olay_tarihi=a.get('olusturma_tarihi') or '',
            baslik='AR-GE çalışması açıldı',
            aciklama=(a.get('test_no') or f'#{aid}')
                     + (f" · {a.get('yeni_renk_adi') or a.get('renk_kodu') or ''}".rstrip()),
            durum=(a.get('durum') or '—'),
            kategori='numuneler',
            parent_type=parent_type,
            parent_id=parent_id,
            olusturan_kullanici_id=uid,
            olusturan_kullanici=users.get(uid or 0),
            icon='lab',
            renk='uyari' if zeksik else '',
            hedef_modul='arge',
            hedef_id=aid,
            detay_url=f'{kart}?tab=numuneler',
            dedupe_key=f'ARGE_CREATED:{aid}',
            result_type='nexgen_rf_renk' if rf_id else None,
            result_id=rf_id,
            baslangic_tipi=btip,
            zincir_eksik=zeksik,
            zincir_uyarilari=uyarilar,
            kayit_no=a.get('test_no') or str(aid),
            hareket_turu='AR-GE',
            metadata={
                'numune_talep_id': ntp,
                'talep_referansi': a.get('talep_referansi'),
                'legacy_rf_text': (a.get('yeni_renk_adi') or a.get('renk_kodu') or None),
            },
        ))

    # RF create + approve
    for rid, rf in rf_by_id.items():
        uyarilar = []
        zeksik = False
        parent_type = parent_id = None
        btip = 'LEGACY_RF'
        kid = _iid(rf.get('kaynak_arge_test_id'))
        if kid:
            if kid in arge_by_id:
                parent_type, parent_id = PARENT_ARGE, kid
                btip = 'ARGEDEN_RF'
                # pointer mismatch: arge.rf != this rf and numune.rf different
                ar = arge_by_id[kid]
                ar_rf = _iid(ar.get('rf_renk_id'))
                ntp = _iid(ar.get('numune_talep_id'))
                nt_rf = None
                if ntp:
                    for n in numune_rows:
                        if int(n['id']) == ntp:
                            nt_rf = _iid(n.get('rf_renk_id'))
                            break
                # nt.rf ≠ arge.rf → mismatch; bu RF olayını "tek doğru" gibi sunma
                if nt_rf and ar_rf and nt_rf != ar_rf:
                    zeksik = True
                    uyarilar.append('RF_POINTER_UYUSMAZLIGI')
            else:
                if kid in arge_cari_map:
                    if arge_cari_map[kid] in (None, cid):
                        parent_type, parent_id = PARENT_ARGE, kid
                        btip = 'ARGEDEN_RF'
                    else:
                        btip = 'ZINCIR_KOPUK'
                        zeksik = True
                        uyarilar.append('PARENT_BASKA_CARI')
                else:
                    btip = 'ZINCIR_KOPUK'
                    zeksik = True
                    uyarilar.append('PARENT_BULUNAMADI')
        else:
            # numune pointer ile bağ
            linked_nt = next(
                (n for n in numune_rows if _iid(n.get('rf_renk_id')) == rid),
                None,
            )
            if linked_nt:
                parent_type, parent_id = PARENT_NUMUNE, int(linked_nt['id'])
                btip = 'NUMUNEDEN_RF'
            else:
                # text-only master RF değilse olay üretilebilir (master kayıt var)
                parent_type, parent_id = PARENT_CARI, cid
                btip = 'ARGEDEN_RF' if kid else 'RF_MASTER'
        if zeksik:
            zincir_uyari_toplam += 1
        # Text-only: master RF kaydı yokken üretme — burada master var
        uid = _iid(rf.get('olusturan_id'))
        label = rf.get('rf_kod') or rf.get('ad') or str(rid)
        if rf.get('rf_kod') and rf.get('ad') and rf['rf_kod'] != rf['ad']:
            label = f"{rf['rf_kod']} — {rf['ad']}"
        _add(_event(
            olay_kodu='RF_CREATED',
            entity_type='nexgen_rf_renk',
            entity_id=rid,
            cari_id=cid,
            olay_tarihi=rf.get('olusturma_tarihi') or '',
            baslik='RF oluşturuldu',
            aciklama=label,
            durum=(rf.get('durum') or '—'),
            kategori='numuneler',
            parent_type=parent_type,
            parent_id=parent_id,
            olusturan_kullanici_id=uid,
            olusturan_kullanici=users.get(uid or 0),
            icon='rf',
            renk='uyari' if zeksik else '',
            hedef_modul='rf',
            hedef_id=rid,
            detay_url=f'{kart}?tab=numuneler',
            dedupe_key=f'RF_CREATED:{rid}',
            baslangic_tipi=btip,
            zincir_eksik=zeksik,
            zincir_uyarilari=uyarilar,
            kayit_no=rf.get('rf_kod') or str(rid),
            hareket_turu='RF',
            metadata={'kaynak_arge_test_id': kid},
        ))
        if rf.get('onay_tarihi'):
            oid = _iid(rf.get('onaylayan_id'))
            _add(_event(
                olay_kodu='RF_APPROVED',
                entity_type='nexgen_rf_renk',
                entity_id=rid,
                cari_id=cid,
                olay_tarihi=rf.get('onay_tarihi') or '',
                baslik='RF onaylandı',
                aciklama=label,
                durum=(rf.get('durum') or 'ONAYLI'),
                kategori='numuneler',
                parent_type=parent_type,
                parent_id=parent_id,
                olusturan_kullanici_id=oid,
                olusturan_kullanici=users.get(oid or 0),
                icon='rf-ok',
                renk='uyari' if zeksik else '',
                hedef_modul='rf',
                hedef_id=rid,
                detay_url=f'{kart}?tab=numuneler',
                dedupe_key=f'RF_APPROVED:{rid}',
                baslangic_tipi=btip,
                zincir_eksik=zeksik,
                zincir_uyarilari=list(uyarilar),
                kayit_no=rf.get('rf_kod') or str(rid),
                hareket_turu='RF',
            ))

    # Sipariş
    siparis_by_id = siparis_by_id_pre
    for s in siparis_rows:
        sid = int(s['id'])
        gid = _iid(s.get('mo_gorusme_id'))
        rel = classify_mo_gorusme_parent(gid, cid, gorusme_by_id, kind='SIPARIS')
        if rel['baslangic_tipi'] == 'DOGRUDAN_SIPARIS':
            dogrudan_siparis += 1
            acik_extra = 'Doğrudan sipariş talebi'
        elif rel['baslangic_tipi'] == 'ZINCIR_KOPUK':
            acik_extra = 'Kırık görüşme bağlantısı'
        else:
            acik_extra = ''
        if rel['zincir_eksik']:
            zincir_uyari_toplam += 1
        no = s.get('siparis_no') or str(sid)
        acik = f"{no} · {s.get('notlar') or s.get('talep_referansi') or ''}".strip(' ·')
        if acik_extra:
            acik = f'{acik} · {acik_extra}' if acik else acik_extra
        uid = _iid(s.get('olusturan_id'))
        _add(_event(
            olay_kodu='SIPARIS_CREATED',
            entity_type='nexgen_planlama_siparis',
            entity_id=sid,
            cari_id=cid,
            olay_tarihi=s.get('olusturma_tarihi') or '',
            baslik='Sipariş talebi açıldı',
            aciklama=acik,
            durum=(s.get('durum') or '—'),
            kategori='siparisler',
            parent_type=rel['parent_type'],
            parent_id=rel['parent_id'],
            olusturan_kullanici_id=uid,
            olusturan_kullanici=users.get(uid or 0),
            icon='order',
            renk='uyari' if rel['zincir_eksik'] else '',
            hedef_modul='siparis',
            hedef_id=sid,
            detay_url=f'{kart}?tab=siparisler',
            dedupe_key=f'SIPARIS_CREATED:{sid}',
            baslangic_tipi=rel['baslangic_tipi'],
            zincir_eksik=rel['zincir_eksik'],
            zincir_uyarilari=rel['zincir_uyarilari'],
            kayit_no=no,
            hareket_turu='Sipariş',
            metadata={'mo_gorusme_id': gid},
        ))

    # Sipariş durum/çek/onay/revizyon ek olayları
    for s in siparis_rows:
        sid = int(s['id'])
        no = s.get('siparis_no') or str(sid)
        durum = (s.get('durum') or '').strip().upper()
        guncelleme = s.get('guncelleme_tarihi') or s.get('olusturma_tarihi') or ''
        olusturma = s.get('olusturma_tarihi') or ''

        # Onay / Red / Revizyon — yalnız onay_talep kaydı yoksa üret; varsa ONAY_TALEBI duplicate önler
        _onay_var = _tablo_var(con, 'onay_talep') and bool(con.execute(
            "SELECT 1 FROM onay_talep WHERE kaynak_modul='nexgen_planlama_siparis' AND kaynak_id=? LIMIT 1",
            (sid,),
        ).fetchone())
        if not _onay_var and durum in ('ONAYLANDI', 'REDDEDILDI', 'REVIZYON') and guncelleme and guncelleme[:16] != olusturma[:16]:
            lbl = {'ONAYLANDI': 'Sipariş onaylandı', 'REDDEDILDI': 'Sipariş reddedildi',
                   'REVIZYON': 'Sipariş revizyon istendi'}.get(durum, durum)
            renk_val = 'uyari' if durum == 'REDDEDILDI' else ''
            acik = s.get('revizyon_gerekce') or no
            _add(_event(
                olay_kodu=f'SIPARIS_{durum}',
                entity_type='nexgen_planlama_siparis',
                entity_id=sid,
                cari_id=cid,
                olay_tarihi=guncelleme,
                baslik=lbl,
                aciklama=str(acik),
                durum=durum,
                kategori='siparisler',
                detay_url=f'{kart}?tab=siparisler',
                dedupe_key=f'SIPARIS_{durum}:{sid}',
                renk=renk_val,
                kayit_no=no,
                hareket_turu='Sipariş',
            ))

        # Çek kaydı — odeme_tipi=CEK ve cek_vadesi varsa
        cek_vadesi = s.get('cek_vadesi')
        odeme_tipi = (s.get('odeme_tipi') or '').upper()
        if odeme_tipi == 'CEK' and cek_vadesi:
            _add(_event(
                olay_kodu='CEK_KAYDI',
                entity_type='nexgen_planlama_siparis',
                entity_id=sid,
                cari_id=cid,
                olay_tarihi=olusturma,
                baslik='Çek kaydı',
                aciklama=f'{no} · Vade: {str(cek_vadesi)[:10]}',
                durum='CEK',
                kategori='tahsilatlar',
                detay_url=f'{kart}?tab=siparisler',
                dedupe_key=f'CEK_KAYDI:{sid}',
                kayit_no=no,
                hareket_turu='Çek',
            ))

    # Tahsilat kayıtları — mo_tahsilat_kayit
    if _tablo_var(con, 'mo_tahsilat_kayit'):
        for r in con.execute(
            """SELECT id, siparis_id, durum, odeme_tipi, alinan_tarih,
                      alinan_tutar, beklenen_tutar, aktif
               FROM mo_tahsilat_kayit
               WHERE cari_id=? AND COALESCE(aktif,1)=1
               ORDER BY COALESCE(alinan_tarih,'') DESC, id DESC""",
            (cid,),
        ).fetchall():
            d = dict(r)
            td = (d.get('durum') or '').upper()
            tarih = d.get('alinan_tarih') or ''
            if not tarih:
                continue
            tutar_str = ''
            try:
                t = float(d.get('alinan_tutar') or 0)
                if t:
                    tutar_str = f'{t:,.2f} TL'
            except (TypeError, ValueError):
                pass
            lbl = {'ONAYLANDI': 'Tahsilat alındı', 'BEKLIYOR': 'Tahsilat bekliyor',
                   'REDDEDILDI': 'Tahsilat reddedildi'}.get(td, f'Tahsilat — {td}')
            sip_ids_local = {
                int(row[0])
                for row in con.execute('SELECT id FROM nexgen_planlama_siparis WHERE cari_id=?', (cid,))
            }
            sip_id_t = d.get('siparis_id')
            if sip_id_t and int(sip_id_t) not in sip_ids_local:
                continue  # başka cariye ait
            _add(_event(
                olay_kodu='TAHSILAT',
                entity_type='mo_tahsilat_kayit',
                entity_id=int(d['id']),
                cari_id=cid,
                olay_tarihi=tarih,
                baslik=lbl,
                aciklama=tutar_str,
                durum=td,
                kategori='tahsilatlar',
                detay_url=f'{kart}?tab=siparisler',
                dedupe_key=f'TAHSILAT:{d["id"]}',
                kayit_no=str(d.get('siparis_id') or d['id']),
                hareket_turu='Tahsilat',
                renk='uyari' if td == 'REDDEDILDI' else '',
            ))
        qstats['q_tahsilat'] = 1

    # Üretim aggregate (plan)
    for p in plan_rows:
        pid = int(p['id'])
        agg = plan_agg.get(pid) or {}
        sip_id = _iid(p.get('planlama_siparis_id'))
        rel = classify_siparis_parent(
            sip_id, cid, sip_cari_map, null_tipi='LEGACY_URETIM',
        )
        if rel['zincir_eksik']:
            zincir_uyari_toplam += 1
        kod = p.get('plan_kodu') or str(pid)
        uid = _iid(p.get('created_by'))
        first_start = agg.get('first_start')
        if first_start:
            _add(_event(
                olay_kodu='URETIM_STARTED',
                entity_type='nexgen_uretim_plan',
                entity_id=pid,
                cari_id=cid,
                olay_tarihi=first_start,
                baslik='Üretim başladı',
                aciklama=f"{kod} · {p.get('siparis_no') or ''}".strip(' ·'),
                durum=(p.get('durum') or 'Üretimde'),
                kategori='uretim',
                parent_type=rel['parent_type'],
                parent_id=rel['parent_id'],
                olusturan_kullanici_id=uid,
                olusturan_kullanici=users.get(uid or 0),
                icon='factory',
                renk='uyari' if rel['zincir_eksik'] else '',
                hedef_modul='uretim',
                hedef_id=pid,
                detay_url=f'{kart}?tab=uretim',
                dedupe_key=f'URETIM_STARTED:{pid}',
                baslangic_tipi=rel['baslangic_tipi'],
                zincir_eksik=rel['zincir_eksik'],
                zincir_uyarilari=list(rel['zincir_uyarilari']),
                kayit_no=kod,
                hareket_turu='Üretim',
                metadata={'parca_n': agg.get('parca_n'), 'aggregate': True},
            ))
        plan_durum = (p.get('durum') or '').upper()
        parca_n = int(agg.get('parca_n') or 0)
        parca_done = int(agg.get('parca_done') or 0)
        completed = (
            plan_durum in _URETIM_TAMAM_DURUM
            or (parca_n > 0 and parca_done >= parca_n)
        )
        if completed:
            end_ts = agg.get('last_end') or p.get('created_at') or p.get('plan_tarihi') or ''
            _add(_event(
                olay_kodu='URETIM_COMPLETED',
                entity_type='nexgen_uretim_plan',
                entity_id=pid,
                cari_id=cid,
                olay_tarihi=end_ts,
                baslik='Üretim tamamlandı',
                aciklama=f"{kod} · {p.get('siparis_no') or ''}".strip(' ·'),
                durum=plan_durum or 'Tamamlandı',
                kategori='uretim',
                parent_type=rel['parent_type'],
                parent_id=rel['parent_id'],
                olusturan_kullanici_id=uid,
                olusturan_kullanici=users.get(uid or 0),
                icon='factory-ok',
                renk='uyari' if rel['zincir_eksik'] else '',
                hedef_modul='uretim',
                hedef_id=pid,
                detay_url=f'{kart}?tab=uretim',
                dedupe_key=f'URETIM_COMPLETED:{pid}',
                baslangic_tipi=rel['baslangic_tipi'],
                zincir_eksik=rel['zincir_eksik'],
                zincir_uyarilari=list(rel['zincir_uyarilari']),
                kayit_no=kod,
                hareket_turu='Üretim',
                metadata={'parca_n': parca_n, 'parca_done': parca_done, 'aggregate': True},
            ))

    # Sevkiyat
    for s in sevk_rows:
        svid = int(s['id'])
        sip_id = _iid(s.get('siparis_id'))
        rel = classify_siparis_parent(
            sip_id, cid, sip_cari_map, null_tipi='DOGRUDAN_SEVKIYAT',
        )
        if rel['zincir_eksik']:
            zincir_uyari_toplam += 1
        sno = s.get('sevkiyat_no') or str(svid)
        sip_no = ''
        if sip_id and sip_id in siparis_by_id:
            sip_no = siparis_by_id[sip_id].get('siparis_no') or ''
        uid = _iid(s.get('olusturan_id'))
        _add(_event(
            olay_kodu='SEVKIYAT',
            entity_type='mo_musteri_sevkiyat',
            entity_id=svid,
            cari_id=cid,
            olay_tarihi=s.get('sevk_tarihi') or s.get('olusturma_tarihi') or '',
            baslik=_sevk_timeline_baslik(s.get('durum')),
            aciklama=f"{sno} · {sip_no}".strip(' ·'),
            durum=(s.get('durum') or '—'),
            kategori='sevkiyatlar',
            parent_type=rel['parent_type'] if rel['parent_type'] else PARENT_SIPARIS,
            parent_id=rel['parent_id'],
            olusturan_kullanici_id=uid,
            olusturan_kullanici=users.get(uid or 0),
            icon='truck',
            renk='uyari' if rel['zincir_eksik'] else '',
            hedef_modul='sevkiyat',
            hedef_id=svid,
            detay_url=f'{kart}?tab=sevkiyatlar',
            dedupe_key=f'SEVKIYAT:{svid}',
            baslangic_tipi='SEVKIYAT',
            zincir_eksik=rel['zincir_eksik'],
            zincir_uyarilari=rel['zincir_uyarilari'],
            kayit_no=sno,
            hareket_turu='Sevkiyat',
            metadata={'siparis_id': sip_id},
        ))

    # Onay Merkezi olayları — onay_talep kaynağından
    # SIPARIS_ONAYLANDI ile duplicate oluşturmamak için ayrı olay_kodu: ONAY_TALEBI
    if _tablo_var(con, 'onay_talep'):
        _ONAY_LBL = {
            'ONAYLANDI': 'Onaylandı', 'REDDEDILDI': 'Reddedildi',
            'REVIZYON': 'Revizyon istendi', 'BEKLIYOR': 'Onay bekliyor',
            'BEKLETILDI': 'Bekletildi', 'IPTAL': 'İptal',
        }
        _ONAY_RENK = {
            'ONAYLANDI': '', 'REDDEDILDI': 'uyari',
            'REVIZYON': 'uyari', 'BEKLIYOR': '',
        }
        # aktif filtresi kaldırıldı: onaylanan/reddedilen talepler de Timeline'a girer
        # Karar tarihi için onay_talep_adim'den son karar adımını JOIN ile getir
        _has_adim = _tablo_var(con, 'onay_talep_adim')
        _adim_tarih_map: dict[int, str] = {}
        # karar_bilgi_map: talep_id -> {zaman, veren, notu}
        _karar_bilgi: dict[int, dict] = {}
        if _has_adim:
            # onay_talep_adim.tarih = gerçek karar zamanı
            _adim_cols = {c[1] for c in con.execute('PRAGMA table_info(onay_talep_adim)').fetchall()}
            _tarih_col = 'tarih' if 'tarih' in _adim_cols else ('updated_at' if 'updated_at' in _adim_cols else 'created_at')
            _veren_col = 'kullanici_ad_snapshot' if 'kullanici_ad_snapshot' in _adim_cols else "''"
            for _ar in con.execute(
                f"""SELECT a.talep_id, a.{_tarih_col} AS karar_zaman,
                           a.{_veren_col} AS karar_veren, a.karar_notu
                   FROM onay_talep_adim a
                   INNER JOIN (
                       SELECT talep_id, MAX({_tarih_col}) AS mz
                       FROM onay_talep_adim
                       WHERE durum IN ('ONAYLANDI','TAMAMLANDI','REDDEDILDI','REVIZYON')
                       GROUP BY talep_id
                   ) mx ON mx.talep_id=a.talep_id AND mx.mz=a.{_tarih_col}
                   WHERE a.durum IN ('ONAYLANDI','TAMAMLANDI','REDDEDILDI','REVIZYON')""",
            ).fetchall():
                _tid_a = int(_ar['talep_id'])
                if _tid_a not in _karar_bilgi:
                    _karar_bilgi[_tid_a] = {
                        'zaman': str(_ar['karar_zaman'] or ''),
                        'veren': str(_ar['karar_veren'] or ''),
                        'notu': str(_ar['karar_notu'] or ''),
                    }
                    _adim_tarih_map[_tid_a] = str(_ar['karar_zaman'] or '')

        for _ot_row in con.execute(
            """SELECT id, talep_kod, talep_tipi, kaynak_modul, kaynak_id,
                      kaynak_kod, durum, tutar, para_birimi, talep_tarihi, created_at
               FROM onay_talep
               WHERE cari_id=?
               ORDER BY id DESC""",
            (cid,),
        ).fetchall():
            ot = dict(_ot_row)
            tid = int(ot['id'])
            ot_durum = (ot.get('durum') or '').upper()
            # Karar tarihi: ONAYLANDI/REDDEDILDI/REVIZYON → gerçek adım zamanı
            talep_tarihi = ot.get('talep_tarihi') or ot.get('created_at') or ''
            if ot_durum in ('ONAYLANDI', 'REDDEDILDI', 'REVIZYON', 'IPTAL'):
                tarih = _adim_tarih_map.get(tid) or talep_tarihi
            else:
                tarih = talep_tarihi
            if not tarih:
                continue
            tip = ot.get('talep_tipi') or ''
            kod = ot.get('talep_kod') or str(tid)
            try:
                tutar_v = float(ot.get('tutar') or 0)
                tutar_s = f' · {tutar_v:,.2f} {ot.get("para_birimi") or ""}'.rstrip()
            except (TypeError, ValueError):
                tutar_s = ''
            baslik_tip = {
                'SATIS_SIPARISI': 'Sipariş onay talebi',
                'NUMUNE_TALEBI': 'Numune onay talebi',
                'TAHSILAT_KAYDI': 'Tahsilat onay talebi',
            }.get(tip, 'Onay talebi')
            baslik = f'{baslik_tip} — {_ONAY_LBL.get(ot_durum, ot_durum)}'
            # Açıklamaya karar veren + not ekle (duplicate-free)
            _kb = _karar_bilgi.get(tid)
            _aciklama_parcalar = [f'{kod}{tutar_s}']
            if _kb and _kb.get('veren'):
                _aciklama_parcalar.append(f'Karar: {_kb["veren"]}')
            if _kb and _kb.get('notu'):
                _aciklama_parcalar.append(_kb['notu'])
            _add(_event(
                olay_kodu='ONAY_TALEBI',
                entity_type='onay_talep',
                entity_id=tid,
                cari_id=cid,
                olay_tarihi=tarih,
                baslik=baslik,
                aciklama=' · '.join(_aciklama_parcalar),
                durum=ot_durum,
                kategori='onaylar',
                detay_url='/nexgen/onay-merkezi',
                dedupe_key=f'ONAY_TALEBI:{tid}',
                renk=_ONAY_RENK.get(ot_durum, ''),
                kayit_no=kod,
                hareket_turu='Onay',
            ))
        qstats['q_onay_talep'] = 1

    # MTT Yönetim Onayları (nexgen_onay) — Timeline federasyonu
    # nexgen_onay.cari_id yoktur; nexgen_musteri_temsilcisi_talep.cari_id ile bağlanır
    if _tablo_var(con, 'nexgen_onay') and _tablo_var(con, 'nexgen_musteri_temsilcisi_talep'):
        _MTT_LBL = {
            'ONAY_BEKLIYOR': 'Onay bekliyor',
            'ONAYLANDI': 'Onaylandı',
            'REDDEDILDI': 'Reddedildi',
        }
        _MTT_TIP = {
            'SIPARIS_TALEBI_ONAY': 'Sipariş Talebi',
            'NUMUNE_TALEBI_ONAY': 'Numune Talebi',
        }
        _MTT_RENK = {'REDDEDILDI': 'uyari', 'ONAY_BEKLIYOR': '', 'ONAYLANDI': ''}
        for _mrow in con.execute(
            """SELECT o.id, o.onay_no, o.onay_turu, o.durum,
                      o.karar_tarihi, o.red_nedeni, o.created_at,
                      sk_on.KullaniciAdi AS karar_veren,
                      m.talep_no
               FROM nexgen_onay o
               JOIN nexgen_musteri_temsilcisi_talep m ON m.id=o.kaynak_id
               LEFT JOIN sistem_kullanici sk_on ON sk_on.Id=o.onaylayan_kullanici_id
               WHERE o.kaynak_turu='MUSTERI_TEMSILCISI_TALEP'
                 AND m.cari_id=?
               ORDER BY o.id DESC""",
            (cid,),
        ).fetchall():
            _md = dict(_mrow)
            _mdurum = (_md.get('durum') or '').upper()
            _mdurum_lbl = _MTT_LBL.get(_mdurum, _mdurum)
            _mtip = _MTT_TIP.get(_md.get('onay_turu') or '', 'MTT Onayı')
            _mbaslik = f'NexGen {_mtip} — {_mdurum_lbl}'
            # Tarih: kararlanmışsa karar_tarihi, yoksa oluşturma
            _mtarih = str(_md.get('karar_tarihi') or _md.get('created_at') or '')
            if not _mtarih:
                continue
            _macik_parcalar = [_md.get('talep_no') or _md.get('onay_no') or '']
            if _md.get('karar_veren'):
                _macik_parcalar.append(_md['karar_veren'])
            if _md.get('red_nedeni'):
                _macik_parcalar.append(_md['red_nedeni'])
            _add(_event(
                olay_kodu='MTT_ONAY',
                entity_type='nexgen_onay',
                entity_id=int(_md['id']),
                cari_id=cid,
                olay_tarihi=_mtarih,
                baslik=_mbaslik,
                aciklama=' · '.join(p for p in _macik_parcalar if p),
                durum=_mdurum,
                kategori='onaylar',
                detay_url='/nexgen/onay-merkezi',
                dedupe_key=f'MTT_ONAY:{_md["id"]}',
                renk=_MTT_RENK.get(_mdurum, ''),
                kayit_no=_md.get('onay_no') or str(_md['id']),
                hareket_turu='Onay',
            ))
        qstats['q_mtt_onay'] = 1

    # MTT Yaşam Döngüsü olayları — Mehmet tarafı geçişleri
    # MTT_ONAY onay kararını, MTT_YASAM Mehmet işlem geçişlerini temsil eder — ayrı dedupe
    if _tablo_var(con, 'nexgen_musteri_temsilcisi_talep'):
        _MTT_YD_LBL = {
            'YENI': "Mehmet'e Aktarıldı",
            'ISLEME_ALINDI': 'Mehmet İşleme Aldı',
            'SIPARISE_DONUSTU': 'Siparişe Dönüştü',
            'NUMUNEYE_DONUSTU': 'Numuneye Dönüştü',
            'KISMEN_NUMUNEYE_DONUSTU': 'Kısmen Numuneye Dönüştü',
        }
        _MTT_YD_RENK = {
            'SIPARISE_DONUSTU': '',
            'NUMUNEYE_DONUSTU': '',
            'KISMEN_NUMUNEYE_DONUSTU': '',
            'YENI': '',
            'ISLEME_ALINDI': '',
        }
        _MTT_TIP2 = {
            'SIPARIS': 'Sipariş Talebi',
            'NUMUNE': 'Numune Talebi',
        }
        # Sipariş/numune kodlarını toplu çek
        _yd_sip_ids: list[int] = []
        _yd_num_ids: list[int] = []
        _yd_mtt_rows = con.execute(
            'SELECT id, talep_no, talep_turu, durum, '
            'isleme_alinma_tarihi, donusturulme_tarihi, updated_at, '
            'donusturulen_siparis_id, donusturulen_numune_talep_id '
            'FROM nexgen_musteri_temsilcisi_talep '
            'WHERE cari_id=? AND durum IN (\'YENI\',\'ISLEME_ALINDI\','
            '\'SIPARISE_DONUSTU\',\'NUMUNEYE_DONUSTU\',\'KISMEN_NUMUNEYE_DONUSTU\')',
            (cid,),
        ).fetchall()
        for _yd in _yd_mtt_rows:
            if _yd['donusturulen_siparis_id']:
                _yd_sip_ids.append(int(_yd['donusturulen_siparis_id']))
            if _yd['donusturulen_numune_talep_id']:
                _yd_num_ids.append(int(_yd['donusturulen_numune_talep_id']))
        _yd_sip_map: dict[int, str] = {}
        _yd_num_map: dict[int, str] = {}
        if _yd_sip_ids and _tablo_var(con, 'nexgen_planlama_siparis'):
            _ph = ','.join('?' * len(_yd_sip_ids))
            for _sr in con.execute(
                f'SELECT id, siparis_no FROM nexgen_planlama_siparis WHERE id IN ({_ph})',
                _yd_sip_ids,
            ).fetchall():
                _yd_sip_map[int(_sr['id'])] = _sr['siparis_no'] or ''
        if _yd_num_ids and _tablo_var(con, 'nexgen_numune_talep'):
            _ph = ','.join('?' * len(_yd_num_ids))
            for _nr in con.execute(
                f'SELECT id, talep_kodu FROM nexgen_numune_talep WHERE id IN ({_ph})',
                _yd_num_ids,
            ).fetchall():
                _yd_num_map[int(_nr['id'])] = _nr['talep_kodu'] or ''

        for _yd in _yd_mtt_rows:
            _yd_dur = (_yd['durum'] or '').upper()
            _yd_lbl = _MTT_YD_LBL.get(_yd_dur)
            if not _yd_lbl:
                continue
            # Canonical tarih: donusturulme > isleme_alinma > updated_at
            if _yd_dur in ('SIPARISE_DONUSTU', 'NUMUNEYE_DONUSTU', 'KISMEN_NUMUNEYE_DONUSTU'):
                _yd_tarih = str(_yd['donusturulme_tarihi'] or _yd['updated_at'] or '')
            elif _yd_dur == 'ISLEME_ALINDI':
                _yd_tarih = str(_yd['isleme_alinma_tarihi'] or _yd['updated_at'] or '')
            else:
                _yd_tarih = str(_yd['updated_at'] or '')
            if not _yd_tarih:
                continue
            _yd_tip = _MTT_TIP2.get(_yd['talep_turu'] or '', 'MTT')
            _yd_baslik = f'{_yd_tip} — {_yd_lbl}'
            # Dönüşüm kodu
            _yd_kod = ''
            _sip_id = _yd['donusturulen_siparis_id']
            _num_id = _yd['donusturulen_numune_talep_id']
            if _sip_id and int(_sip_id) in _yd_sip_map:
                _yd_kod = _yd_sip_map[int(_sip_id)]
            elif _num_id and int(_num_id) in _yd_num_map:
                _yd_kod = _yd_num_map[int(_num_id)]
            _yd_acik = _yd['talep_no'] or ''
            if _yd_kod:
                _yd_acik = f'{_yd_acik} → {_yd_kod}'
            _add(_event(
                olay_kodu='MTT_YASAM',
                entity_type='nexgen_musteri_temsilcisi_talep',
                entity_id=int(_yd['id']),
                cari_id=cid,
                olay_tarihi=_yd_tarih,
                baslik=_yd_baslik,
                aciklama=_yd_acik,
                durum=_yd_dur,
                kategori='onaylar',
                detay_url='/nexgen/onay-merkezi',
                dedupe_key=f'MTT_YASAM:{_yd["id"]}:{_yd_dur}',
                renk=_MTT_YD_RENK.get(_yd_dur, ''),
                kayit_no=_yd['talep_no'] or str(_yd['id']),
                hareket_turu='Onay',
            ))
        qstats['q_mtt_yasam'] = 1

    # Sıralama: olay_tarihi DESC → oncelik DESC → entity_id DESC
    def _sort_key(e: dict[str, Any]) -> tuple:
        eid = e.get('entity_id')
        try:
            eid_n = int(eid)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            eid_n = 0
        return (
            e.get('olay_tarihi') or '',
            int(e.get('oncelik') or 0),
            eid_n,
        )

    events.sort(key=_sort_key, reverse=True)

    # ERP-yönetici whitelist: teknik log olaylarını Timeline'dan çıkar
    _IZIN = frozenset({
        'GORUSME_CREATED', 'GORUSME_UPDATED', 'GORUSME_IPTAL',
        'NUMUNE_CREATED', 'NUMUNE_ONAYLANDI', 'NUMUNE_REDDEDILDI',
        # SIPARIS_ONAYLANDI/REDDEDILDI/REVIZYON kaldırıldı — onay sistemi olan siparişlerde
        # ONAY_TALEBI zaten aynı bilgiyi taşır; olmayan siparişlerde üretilir (koşullu)
        'SIPARIS_CREATED', 'SIPARIS_ONAYLANDI', 'SIPARIS_REDDEDILDI',
        'SIPARIS_REVIZYON', 'SIPARIS_IPTAL',
        'CEK_KAYDI', 'CEK_GUNCELLENDI',
        'TAHSILAT', 'ONAY_TALEBI', 'MTT_ONAY', 'MTT_YASAM',
        'SEVKIYAT',
        'URETIM_STARTED', 'URETIM_COMPLETED',
        'GORUSME_PLANLANDI',
    })
    events = [e for e in events if e.get('olay_kodu') in _IZIN]

    meta = {
        'query_stats': qstats,
        'zincir_uyari_sayisi': zincir_uyari_toplam,
        'dogrudan_numune_sayisi': dogrudan_numune,
        'dogrudan_siparis_sayisi': dogrudan_siparis,
        'sorumlu': sorumlu,
        'sorumlu_uyarilari': list(sorumlu_meta.get('sorumlu_uyarilari') or []),
        'sorumlu_atanmamis': bool(sorumlu_meta.get('sorumlu_atanmamis')),
        'toplam_ops': len(events),
    }
    return events, meta


def load_cari360_timeline(
    con: sqlite3.Connection,
    cari_id: int,
    kullanici_id: int,
    yk: set[str] | None,
    *,
    limit: int | None = None,
    include_test: bool = False,
) -> dict[str, Any]:
    """Yetki kontrollü timeline payload — write yok."""
    if not can_view_cari(con, kullanici_id, int(cari_id), yk):
        raise Cari360TimelineError('Bu cari için görüntüleme yetkiniz yok.', 403)
    row = con.execute(
        'SELECT id FROM nexgen_cari WHERE id=?', (int(cari_id),),
    ).fetchone()
    if not row:
        raise Cari360TimelineError('Cari bulunamadı.', 404)

    olaylar, meta = build_ops_timeline(con, int(cari_id), include_test=include_test)
    if limit is not None:
        lim = max(1, min(int(limit), 500))
        olaylar = olaylar[:lim]
    return {
        'olaylar': olaylar,
        'events': olaylar,
        'toplam': meta.get('toplam_ops', len(olaylar)),
        'count': len(olaylar),
        'zincir_uyari_sayisi': meta.get('zincir_uyari_sayisi', 0),
        'dogrudan_numune_sayisi': meta.get('dogrudan_numune_sayisi', 0),
        'dogrudan_siparis_sayisi': meta.get('dogrudan_siparis_sayisi', 0),
        'sorumlu': meta.get('sorumlu'),
        'sorumlu_uyarilari': meta.get('sorumlu_uyarilari') or [],
        'sorumlu_atanmamis': meta.get('sorumlu_atanmamis', False),
        'query_stats': meta.get('query_stats') or {},
    }
