# -*- coding: utf-8 -*-
"""
Numune talebi Merkezi Onay adapter.

Kural: Aynı nexgen_numune_talep kaydı; ONAYLANDI sonrası Mehmet bekleyen listesinde (arge_test_id yok).
gonder_arge / _ensure_nx_ar_for_talep çağrılmaz.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from modules.nexgen.mo_numune_talep_service import onay_sonrasi_uygula, red_uygula, revizyon_uygula
from modules.nexgen.onay_merkezi_service import (
    adapter_log,
    aktif_talep_var,
    shadow_olay,
    snapshot_hash,
    talep_olustur,
)

KAYNAK_MODUL = 'nexgen_numune_talep'
TALEP_TIPI = 'NUMUNE_TALEBI'
ADAPTER = 'NUMUNE_TALEBI_ADAPTER'


def _tablo_var(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _acik_numune_sayisi(con, cari_id: int) -> int:
    row = con.execute(
        """
        SELECT COUNT(*) AS n FROM nexgen_numune_talep
        WHERE aktif=1 AND cari_id=? AND durum NOT IN ('REDDEDILDI','TAMAMLANDI','IPTAL')
        """,
        (cari_id,),
    ).fetchone()
    return int(row['n'] or 0) if row else 0


def _son_numune_talepleri(con, cari_id: int, limit: int = 5) -> list[dict]:
    rows = con.execute(
        """
        SELECT id, talep_kodu, durum, olusturma_tarihi, karsilama_yolu, urun_adi
        FROM nexgen_numune_talep
        WHERE aktif=1 AND cari_id=?
        ORDER BY olusturma_tarihi DESC LIMIT ?
        """,
        (cari_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def _son_siparis_tarihi(con, cari_id: int) -> str | None:
    if not _tablo_var(con, 'nexgen_planlama_siparis'):
        return None
    row = con.execute(
        """
        SELECT MAX(olusturma_tarihi) AS t FROM nexgen_planlama_siparis
        WHERE cari_id=? AND durum NOT IN ('IPTAL','REDDEDILDI')
        """,
        (cari_id,),
    ).fetchone()
    return row['t'] if row else None


def numune_snapshot_olustur(con, talep_id: int) -> dict[str, Any]:
    row = con.execute(
        """
        SELECT nt.*, c.unvan AS cari_unvan, c.cari_kod,
               sk.KullaniciAdi AS pazarlamaci_adi
        FROM nexgen_numune_talep nt
        LEFT JOIN nexgen_cari c ON c.id = nt.cari_id
        LEFT JOIN sistem_kullanici sk ON sk.Id = nt.talep_eden_kullanici_id
        WHERE nt.id=? AND nt.aktif=1
        """,
        (talep_id,),
    ).fetchone()
    if not row:
        return {}

    d = dict(row)
    cari_id = int(d['cari_id'] or 0)
    gorusme = None
    if d.get('mo_gorusme_id') and _tablo_var(con, 'musteri_operasyon_gorusme'):
        g = con.execute(
            'SELECT id, gorusme_tipi, kisa_not, gorusme_tarihi FROM musteri_operasyon_gorusme WHERE id=?',
            (d['mo_gorusme_id'],),
        ).fetchone()
        gorusme = dict(g) if g else None

    snap: dict[str, Any] = {
        'numune_talep_id': d['id'],
        'talep_kodu': d['talep_kodu'],
        'cari_id': cari_id,
        'cari_unvan_snapshot': d.get('cari_unvan'),
        'cari_kod_snapshot': d.get('cari_kod'),
        'pazarlamaci_id': d.get('talep_eden_kullanici_id'),
        'pazarlamaci_adi': d.get('pazarlamaci_adi'),
        'urun_tipi': d.get('urun_tipi'),
        'urun_adi': d.get('urun_adi'),
        'talep_turu': d.get('karsilama_yolu'),
        'hedef_tarih': d.get('hedef_tarih'),
        'oncelik': d.get('oncelik'),
        'musteri_talebi': d.get('aciklama') or d.get('talep_nedeni'),
        'musteri_urun_kodu': d.get('musteri_urun_kodu'),
        'ref_renk_kodu': d.get('ref_renk_kodu'),
        'yeni_renk_aciklama': d.get('yeni_renk_aciklama'),
        'dosya_ref': d.get('dosya_ref'),
        'urun_gorsel_belge_id': d.get('urun_gorsel_belge_id'),
        'ref_gorsel_belge_id': d.get('ref_gorsel_belge_id'),
        'onay_notu': d.get('onay_notu'),
        'bagli_gorusme': gorusme,
        'kaynak_modul': d.get('kaynak_modul'),
        'acik_numune_sayisi': _acik_numune_sayisi(con, cari_id) if cari_id else 0,
        'son_numune_talepleri': _son_numune_talepleri(con, cari_id) if cari_id else [],
        'son_siparis_tarihi': _son_siparis_tarihi(con, cari_id) if cari_id else None,
        'onay_talep_id': None,
    }
    snap['snapshot_hash'] = snapshot_hash(snap)
    return snap


def _adimlar_olustur() -> list[dict]:
    return [
        {
            'sira': 1,
            'adim_tipi': 'NUMUNE_INCELEME',
            'kademe': 'K2',
            'rol_adi': 'Merkezi Onay',
            'durum': 'BEKLIYOR',
        },
    ]


def numune_onaya_gonder(
    con: sqlite3.Connection,
    talep_id: int,
    talep_eden_id: int,
    revizyon_no: int = 1,
) -> dict[str, Any]:
    row = con.execute(
        'SELECT id, talep_kodu, durum, cari_id, kaynak_modul FROM nexgen_numune_talep WHERE id=?',
        (talep_id,),
    ).fetchone()
    if not row:
        return {'ok': False, 'hata': 'Numune talebi bulunamadı.'}
    if (row['kaynak_modul'] or '') != 'MUSTERI_OPERASYONU':
        return {'ok': False, 'hata': 'MO kaynağı değil.'}
    durum = (row['durum'] or '').upper()
    if durum not in ('TASLAK', 'REVIZYON_ISTENDI'):
        return {'ok': False, 'hata': f'Onaya gönderilemez: {durum}'}

    if aktif_talep_var(con, KAYNAK_MODUL, talep_id, TALEP_TIPI):
        return {'ok': False, 'hata': 'Aktif onay talebi zaten var.', 'code': 'DUPLICATE'}

    snap = numune_snapshot_olustur(con, talep_id)
    if not snap.get('urun_tipi') or not snap.get('urun_adi') or not snap.get('talep_turu'):
        return {'ok': False, 'hata': 'Zorunlu alanlar eksik.'}
    if not snap.get('musteri_talebi') or not snap.get('hedef_tarih'):
        return {'ok': False, 'hata': 'Müşteri talebi ve termin zorunlu.'}

    idem = f'{TALEP_TIPI}:{talep_id}:rev{revizyon_no}'
    r = talep_olustur(
        con,
        talep_tipi=TALEP_TIPI,
        kaynak_modul=KAYNAK_MODUL,
        kaynak_id=talep_id,
        kaynak_kod=row['talep_kodu'],
        talep_eden_id=talep_eden_id,
        snapshot=snap,
        etki={'acik_numune_sayisi': snap.get('acik_numune_sayisi', 0)},
        cari_id=snap.get('cari_id'),
        cari_unvan=snap.get('cari_unvan_snapshot'),
        idempotency_key=idem,
        adimlar=_adimlar_olustur(),
        revizyon_no=revizyon_no,
    )
    if not r.get('ok'):
        return r

    snap['onay_talep_id'] = r['talep_id']
    snap['snapshot_hash'] = snapshot_hash(snap)
    adapter_log(
        con, talep_id=r['talep_id'], adapter_kodu=ADAPTER,
        kaynak_modul=KAYNAK_MODUL, islem='ONAYA_GONDER', sonuc='OK',
        payload={'numune_talep_id': talep_id, 'talep_kodu': row['talep_kodu']},
    )
    return {'ok': True, 'talep_id': r['talep_id'], 'talep_kod': r['talep_kod']}


def numune_onay_sonrasi_uygula(con, talep_id: int) -> dict[str, Any]:
    talep = con.execute('SELECT * FROM onay_talep WHERE id=?', (talep_id,)).fetchone()
    if not talep or talep['durum'] != 'ONAYLANDI':
        return {'ok': False, 'hata': 'Talep onaylı değil.'}

    numune_id = int(talep['kaynak_id'])
    dup = con.execute(
        """
        SELECT 1 FROM onay_adapter_log
        WHERE talep_id=? AND adapter_kodu=? AND islem='MEHMET_KOPRU' AND sonuc='OK'
        """,
        (talep_id, ADAPTER),
    ).fetchone()
    if dup:
        return {'ok': True, 'skip': True, 'numune_talep_id': numune_id}

    r = onay_sonrasi_uygula(con, numune_id, talep_id)
    if not r.get('ok'):
        return r

    adapter_log(
        con, talep_id=talep_id, adapter_kodu=ADAPTER,
        kaynak_modul=KAYNAK_MODUL, islem='MEHMET_KOPRU', sonuc='OK',
        payload={'numune_talep_id': numune_id, 'talep_kodu': talep['kaynak_kod']},
    )
    shadow_olay(con, 'NUMUNE_TALEBI_ONAYLANDI', {
        'talep_id': talep_id,
        'numune_talep_id': numune_id,
        'kaynak_modul': KAYNAK_MODUL,
    })
    return {'ok': True, 'numune_talep_id': numune_id, 'durum': 'ONAYLANDI'}


def numune_revizyon_uygula(con, talep_id: int, notu: str) -> None:
    talep = con.execute('SELECT kaynak_id FROM onay_talep WHERE id=?', (talep_id,)).fetchone()
    if not talep:
        return
    revizyon_uygula(con, int(talep['kaynak_id']), notu)


def numune_red_uygula(con, talep_id: int, notu: str) -> None:
    talep = con.execute('SELECT kaynak_id FROM onay_talep WHERE id=?', (talep_id,)).fetchone()
    if not talep:
        return
    red_uygula(con, int(talep['kaynak_id']), notu)


def karar_sonrasi_adapter(con, talep_id: int, karar_sonuc: dict) -> None:
    if not karar_sonuc.get('ok'):
        return
    durum = karar_sonuc.get('durum')
    if durum == 'ONAYLANDI' and karar_sonuc.get('tamamlandi'):
        numune_onay_sonrasi_uygula(con, talep_id)
    elif durum == 'REVIZYON':
        adim = con.execute(
            """
            SELECT karar_notu FROM onay_talep_adim
            WHERE talep_id=? AND durum='REVIZYON' ORDER BY id DESC LIMIT 1
            """,
            (talep_id,),
        ).fetchone()
        numune_revizyon_uygula(con, talep_id, (adim['karar_notu'] if adim else '') or '')
    elif durum == 'REDDEDILDI':
        adim = con.execute(
            """
            SELECT karar_notu FROM onay_talep_adim
            WHERE talep_id=? AND durum='REDDEDILDI' ORDER BY id DESC LIMIT 1
            """,
            (talep_id,),
        ).fetchone()
        numune_red_uygula(con, talep_id, (adim['karar_notu'] if adim else '') or '')
