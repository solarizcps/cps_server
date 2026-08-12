# -*- coding: utf-8 -*-
"""Cari360 Finans Sekmesi — read-only özet + tahsilat listesi + çek listesi.

Kaynaklar:
  1. mo_tahsilat_kayit (cari_id direkt) — kaynak_modul ayrımı dahil
  2. mo_tahsilat_cek — gerçek çek evrakları
  3. nexgen_planlama_siparis (vade / çek canonical resolver)
  4. Cari_Har + Cari_Kart — yalnız cari_eslestirme.aktif=1
                             ve eslestirme_durumu='DOGRULANDI' olan carilerde.

YASAK: risk skoru, cari limit, sahte veri, sipariş toplamından bakiye üretimi.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from modules.nexgen.finans_ledger_standard import bakiye_float_dict, compute_bakiye

# Canonical kaynak sabitleri — mo_tahsilat_config ile uyumlu
KAYNAK_MUSTERI_OPERASYONU = 'MUSTERI_OPERASYONU'
KAYNAK_MANUEL_FINANS = 'MANUEL_FINANS'

_KAYNAK_ETIKET = {
    KAYNAK_MUSTERI_OPERASYONU: 'Müşteri Operasyonu',
    KAYNAK_MANUEL_FINANS: 'Manuel Finans',
}

_ODEME_ETIKET = {
    'NAKIT': 'Nakit',
    'HAVALE': 'Havale',
    'CEK': 'Çek',
    'SENET': 'Senet',
    'DIGER': 'Diğer',
}

_DURUM_ETIKET = {
    'TASLAK': 'Taslak',
    'MUHASEBE_ONAY_BEKLIYOR': 'Onay Bekliyor',
    'REVIZYON_ISTENDI': 'Revizyon İstendi',
    'REDDEDILDI': 'Reddedildi',
    'ONAYLANDI': 'Onaylandı',
}

_TAHSILAT_SAYIMDA = frozenset({'ONAYLANDI', 'MUHASEBE_ONAY_BEKLIYOR'})
_TAHSILAT_HARIC = frozenset({'IPTAL', 'REDDEDILDI'})

_VADE_CEK_HARIC = frozenset({
    'TASLAK', 'REDDEDILDI', 'REVIZYON',
    'IPTAL', 'IPTAL_EDILDI', 'IPTALEDILDI',
})


def _tablo_var(con: sqlite3.Connection, ad: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (ad,)
    ).fetchone())


def _cols(con: sqlite3.Connection, tablo: str) -> set[str]:
    return {r[1] for r in con.execute(f'PRAGMA table_info({tablo})')}


def _float(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Legacy köprü — cari_eslestirme → Cari_Har / Cari_Kart
# ---------------------------------------------------------------------------

def _legacy_ckod(con: sqlite3.Connection, cari_id: int) -> str | None:
    """Yalnız aktif=1 ve DOGRULANDI eşleşmesi döndürür."""
    if not _tablo_var(con, 'cari_eslestirme'):
        return None
    row = con.execute(
        """SELECT cari_kart_ckod FROM cari_eslestirme
           WHERE nexgen_cari_id=? AND aktif=1
             AND eslestirme_durumu='DOGRULANDI'
             AND cari_kart_ckod IS NOT NULL AND cari_kart_ckod != ''
           ORDER BY id DESC LIMIT 1""",
        (int(cari_id),),
    ).fetchone()
    return row['cari_kart_ckod'] if row else None


def _legacy_bakiye(con: sqlite3.Connection, ckod: str | None) -> dict[str, Any]:
    """Cari_Har bakiyesi + Cari_Kart.Bakiye fallback bilgisi."""
    if not ckod:
        return {'eslesme': False, 'mesaj': 'Finans eşleşmesi yok'}

    bpak = bakiye_float_dict(compute_bakiye(con, ckod))

    if not bpak.get('mevcut'):
        # Cari_Har satırı yok — Cari_Kart.Bakiye fallback
        kart_bak = bpak.get('cari_kart_bakiye')
        if kart_bak is not None:
            return {
                'eslesme': True,
                'ckod': ckod,
                'kaynak': 'Cari_Kart (kart bakiyesi)',
                'bakiye': float(kart_bak),
                'borc': None,
                'alacak': None,
                'acik_bakiye': None,
                'uyari': 'Cari_Har hareketi bulunamadı — Cari_Kart.Bakiye gösterilmektedir.',
            }
        return {'eslesme': True, 'ckod': ckod, 'mesaj': 'Finans eşleşmesi var ama hareket kaydı yok'}

    return {
        'eslesme': True,
        'ckod': ckod,
        'kaynak': 'Cari_Har',
        'bakiye': bpak.get('bakiye'),
        'borc': bpak.get('toplam_borc'),
        'alacak': bpak.get('toplam_alacak'),
        'acik_bakiye': bpak.get('bakiye'),
        'hareket_sayisi': bpak.get('hareket_sayisi'),
        'ilk_islem': bpak.get('ilk_islem_tarihi'),
        'son_islem': bpak.get('son_islem_tarihi'),
        'cari_kart_bakiye': bpak.get('cari_kart_bakiye'),
        'uyumlu': bpak.get('uyumlu'),
        'bakiye_farki': bpak.get('bakiye_farki'),
    }


# ---------------------------------------------------------------------------
# Tahsilat özeti — mo_tahsilat_kayit
# ---------------------------------------------------------------------------

def _tahsilat_ozet(con: sqlite3.Connection, cari_id: int) -> dict[str, Any]:
    """KPI özet — tüm kaynak_modul dahil. Para birimi ayrımı TRY-only güvenli."""
    if not _tablo_var(con, 'mo_tahsilat_kayit'):
        return {}
    cid = int(cari_id)
    tcols = _cols(con, 'mo_tahsilat_kayit')
    pb_sel = ', para_birimi' if 'para_birimi' in tcols else ''

    rows = con.execute(
        f"""SELECT durum, alinan_tutar, beklenen_tutar, kalan_tutar,
                  alinan_tarih, planlanan_tahsilat_tarihi{pb_sel}
           FROM mo_tahsilat_kayit
           WHERE cari_id=? AND COALESCE(aktif,1)=1""",
        (cid,),
    ).fetchall()

    alinan_try = 0.0
    bekleyen_try = 0.0
    kalan_try = 0.0
    has_fx = False
    gecikme_n = 0
    son_tarih = None
    son_tutar = None

    for r in rows:
        d = (r['durum'] or '').upper()
        pb = (r['para_birimi'] if 'para_birimi' in r.keys() else None) or 'TRY'
        if d == 'ONAYLANDI':
            t = _float(r['alinan_tutar'])
            if pb == 'TRY':
                alinan_try += t
            else:
                has_fx = True
            at = r['alinan_tarih'] or ''
            if at and (son_tarih is None or at > son_tarih):
                son_tarih = at
                son_tutar = t
            pt = r['planlanan_tahsilat_tarihi'] or ''
            if pt and at and at > pt:
                gecikme_n += 1
        elif d not in _TAHSILAT_HARIC:
            if pb == 'TRY':
                bekleyen_try += _float(r['beklenen_tutar'])
                kalan_try += _float(r['kalan_tutar'])
            else:
                has_fx = True

    return {
        'alinan_toplam': round(alinan_try, 2),
        'bekleyen_toplam': round(bekleyen_try, 2),
        'kalan_toplam': round(kalan_try, 2),
        'son_tahsilat_tarihi': son_tarih,
        'son_tahsilat_tutari': round(son_tutar, 2) if son_tutar is not None else None,
        'gecikme_sayisi': gecikme_n,
        'fx_kayit_var': has_fx,
        'fx_uyari': 'Dövizli tahsilatlar TRY toplamına dahil edilmedi.' if has_fx else None,
    }


def _tahsilat_liste(
    con: sqlite3.Connection,
    cari_id: int,
    limit: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    """Son tahsilat hareketleri — canonical liste. İki kaynak: MO + Manuel."""
    if not _tablo_var(con, 'mo_tahsilat_kayit'):
        return {'liste': [], 'toplam': 0}
    cid = int(cari_id)
    tcols = _cols(con, 'mo_tahsilat_kayit')

    sel_extra = []
    for col in ('para_birimi', 'kaynak_modul', 'siparis_id', 'sevkiyat_id',
                'kur_tarihi_snapshot', 'tcmb_satis_kur_snapshot'):
        if col in tcols:
            sel_extra.append(col)

    sel = ', '.join([
        'id', 'kayit_kodu', 'alinan_tarih', 'odeme_tipi',
        'alinan_tutar', 'beklenen_tutar', 'durum', 'odeme_referansi', 'aciklama',
    ] + sel_extra)

    total = con.execute(
        'SELECT COUNT(*) FROM mo_tahsilat_kayit WHERE cari_id=? AND COALESCE(aktif,1)=1',
        (cid,),
    ).fetchone()[0]

    rows = con.execute(
        f"""SELECT {sel}
            FROM mo_tahsilat_kayit
            WHERE cari_id=? AND COALESCE(aktif,1)=1
            ORDER BY COALESCE(alinan_tarih,'') DESC, id DESC
            LIMIT ? OFFSET ?""",
        (cid, limit, offset),
    ).fetchall()

    # Sipariş no hızlı lookup
    sip_ids = [int(r['siparis_id']) for r in rows
               if 'siparis_id' in r.keys() and r['siparis_id']]
    sip_no_map: dict[int, str] = {}
    if sip_ids and _tablo_var(con, 'nexgen_planlama_siparis'):
        ph = ','.join('?' * len(sip_ids))
        for sr in con.execute(
            f'SELECT id, siparis_no FROM nexgen_planlama_siparis WHERE id IN ({ph})',
            sip_ids,
        ).fetchall():
            sip_no_map[int(sr['id'])] = sr['siparis_no'] or ''

    liste = []
    for r in rows:
        d = (r['durum'] or '').upper()
        kaynak_raw = r['kaynak_modul'] if 'kaynak_modul' in r.keys() else KAYNAK_MUSTERI_OPERASYONU
        pb = (r['para_birimi'] if 'para_birimi' in r.keys() else None) or 'TRY'
        tutar = r['alinan_tutar'] if d == 'ONAYLANDI' else (r['beklenen_tutar'] if 'beklenen_tutar' in r.keys() else None)
        sip_id = int(r['siparis_id']) if ('siparis_id' in r.keys() and r['siparis_id']) else None
        liste.append({
            'id': int(r['id']),
            'belge_no': r['kayit_kodu'] or r['odeme_referansi'] or '',
            'tarih': r['alinan_tarih'] or '',
            'tur': _ODEME_ETIKET.get((r['odeme_tipi'] or '').upper(), r['odeme_tipi'] or '—'),
            'odeme_tipi': (r['odeme_tipi'] or '').upper(),
            'kaynak': _KAYNAK_ETIKET.get(kaynak_raw or '', kaynak_raw or KAYNAK_MUSTERI_OPERASYONU),
            'kaynak_raw': kaynak_raw or KAYNAK_MUSTERI_OPERASYONU,
            'tutar': _float(r['alinan_tutar']),
            'para_birimi': pb,
            'durum': _DURUM_ETIKET.get(d, d),
            'durum_raw': d,
            'siparis_id': sip_id,
            'siparis_no': sip_no_map.get(sip_id, '') if sip_id else '',
            'aciklama': r['aciklama'] or '',
        })

    return {'liste': liste, 'toplam': total}


# ---------------------------------------------------------------------------
# Vade / Çek özeti — nexgen_planlama_siparis
# ---------------------------------------------------------------------------

def _vade_cek_ozet(con: sqlite3.Connection, cari_id: int) -> dict[str, Any]:
    """
    Vade & Çek özeti — canonical resolver ile.
    CEK → cek_vade_gun (DB kolon öncelikli → talep_referansi JSON fallback).
    VADELI → vade_gun.
    NAKIT → vade yok.
    SİPARİŞ ÇEKİ ≠ GERÇEK ÇEK EVRAĞI (mo_tahsilat_cek ayrı).
    """
    if not _tablo_var(con, 'nexgen_planlama_siparis'):
        return {}
    cid = int(cari_id)

    scols = _cols(con, 'nexgen_planlama_siparis')
    sel_extra = []
    for col in ('cek_vade_gun', 'cek_vadesi', 'talep_referansi'):
        if col in scols:
            sel_extra.append(col)

    extra = (', ' + ', '.join(sel_extra)) if sel_extra else ''
    all_rows = con.execute(
        f"""SELECT id, siparis_no, vade_gun, odeme_tipi{extra},
                   UPPER(TRIM(COALESCE(durum,''))) AS d
            FROM nexgen_planlama_siparis WHERE cari_id=?""",
        (cid,),
    ).fetchall()

    vade_list: list[float] = []
    cek_rows = []

    for r in all_rows:
        if r['d'] in _VADE_CEK_HARIC:
            continue
        ot = (r['odeme_tipi'] or '').strip().upper()
        if ot == 'CEK':
            cek_rows.append(r)
        elif ot == 'VADELI':
            vg = _float(r['vade_gun'])
            if vg > 0:
                vade_list.append(vg)

    ort_vade = round(sum(vade_list) / len(vade_list), 1) if vade_list else None

    # CEK siparişlerinin canonical vade değerleri
    cek_vadeleri_set: set[str] = set()
    for r in cek_rows:
        # canonical resolver: DB kolon → JSON fallback
        cvg = r['cek_vade_gun'] if 'cek_vade_gun' in r.keys() else None
        if cvg in (None, ''):
            import json as _json
            tr = r['talep_referansi'] if 'talep_referansi' in r.keys() else None
            if tr:
                for prefix in ('__PZM_V2__', '__PZM_V1__'):
                    if str(tr).startswith(prefix):
                        try:
                            pl = _json.loads(str(tr)[len(prefix):])
                            cvg = pl.get('cek_vade_gun')
                        except Exception:
                            pass
                        break
        if cvg not in (None, ''):
            cek_vadeleri_set.add(str(cvg))
        elif 'cek_vadesi' in r.keys() and r['cek_vadesi']:
            cek_vadeleri_set.add(str(r['cek_vadesi'])[:10])

    return {
        'ortalama_vade_gun': ort_vade,
        'vade_ornekleri_n': len(vade_list),
        'cekli_siparis_sayisi': len(cek_rows),
        'cek_vadeleri': sorted(cek_vadeleri_set)[:10],
        'kapsam_notu': 'TASLAK/REDDEDILDI/IPTAL/REVIZYON hariç. CEK=sipariş çeki.',
    }


def _gercek_cek_listesi(con: sqlite3.Connection, cari_id: int) -> list[dict[str, Any]]:
    """
    Gerçek çek evrakları — mo_tahsilat_cek.
    Sipariş ödeme tipi CEK ≠ gerçek çek evrakı.
    """
    if not _tablo_var(con, 'mo_tahsilat_cek') or not _tablo_var(con, 'mo_tahsilat_kayit'):
        return []
    cid = int(cari_id)

    # mo_tahsilat_cek → mo_tahsilat_kayit.cari_id
    rows = con.execute(
        """
        SELECT c.id, c.tahsilat_kayit_id, c.sira_no, c.tutar, c.para_birimi,
               c.cek_alim_tarihi, c.gercek_cek_vade_tarihi, c.odeme_referansi,
               c.banka_adi, c.durum,
               k.kayit_kodu, k.siparis_id
        FROM mo_tahsilat_cek c
        JOIN mo_tahsilat_kayit k ON k.id = c.tahsilat_kayit_id
        WHERE k.cari_id=? AND COALESCE(c.aktif,1)=1 AND COALESCE(k.aktif,1)=1
        ORDER BY c.gercek_cek_vade_tarihi ASC, c.id ASC
        """,
        (cid,),
    ).fetchall()

    # Sipariş no lookup
    sip_ids = [int(r['siparis_id']) for r in rows if r['siparis_id']]
    sip_no_map: dict[int, str] = {}
    if sip_ids and _tablo_var(con, 'nexgen_planlama_siparis'):
        ph = ','.join('?' * len(sip_ids))
        for sr in con.execute(
            f'SELECT id, siparis_no FROM nexgen_planlama_siparis WHERE id IN ({ph})',
            sip_ids,
        ).fetchall():
            sip_no_map[int(sr['id'])] = sr['siparis_no'] or ''

    liste = []
    for r in rows:
        sip_id = int(r['siparis_id']) if r['siparis_id'] else None
        liste.append({
            'id': int(r['id']),
            'tahsilat_kayit_id': int(r['tahsilat_kayit_id']),
            'belge_no': r['odeme_referansi'] or '',
            'tahsilat_kodu': r['kayit_kodu'] or '',
            'tutar': _float(r['tutar']),
            'para_birimi': r['para_birimi'] or 'TRY',
            'alim_tarihi': r['cek_alim_tarihi'] or '',
            'vade_tarihi': r['gercek_cek_vade_tarihi'] or '',
            'banka': r['banka_adi'] or '',
            'durum': r['durum'] or '',
            'siparis_id': sip_id,
            'siparis_no': sip_no_map.get(sip_id, '') if sip_id else '',
        })
    return liste


# ---------------------------------------------------------------------------
# Ana yükleme fonksiyonu
# ---------------------------------------------------------------------------

def load_cari360_finans(
    con: sqlite3.Connection,
    cari_id: int,
    *,
    tahsilat_limit: int = 10,
    tahsilat_offset: int = 0,
) -> dict[str, Any]:
    """Cari360 finans sekmesi payload — yalnız gerçek kaynaklar."""
    cid = int(cari_id)

    ckod = _legacy_ckod(con, cid)
    legacy = _legacy_bakiye(con, ckod)
    tahsilat = _tahsilat_ozet(con, cid)
    tahsilat_liste = _tahsilat_liste(con, cid, limit=tahsilat_limit, offset=tahsilat_offset)
    vade_cek = _vade_cek_ozet(con, cid)
    gercek_cekler = _gercek_cek_listesi(con, cid)

    # finans_cari_kart'tan risk/limit
    risk_d = _risk_limit(con, cid, ckod)

    return {
        'cari_id': cid,
        'eslesme': legacy,
        'tahsilat': tahsilat,
        'tahsilat_liste': tahsilat_liste,
        'vade_cek': vade_cek,
        'gercek_cekler': gercek_cekler,
        'risk': risk_d.get('risk'),
        'limit': risk_d.get('limit'),
        'risk_notu': risk_d.get('risk_notu', 'Risk kaynağı tanımlı değil.'),
        'limit_notu': risk_d.get('limit_notu', 'Cari limit kaynağı tanımlı değil.'),
    }


def load_cari360_tahsilat_liste(
    con: sqlite3.Connection,
    cari_id: int,
    limit: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    """Ayrı endpoint için tahsilat listesi."""
    return _tahsilat_liste(con, int(cari_id), limit=limit, offset=offset)


def _risk_limit(con: sqlite3.Connection, cari_id: int, ckod: str | None) -> dict[str, Any]:
    """Risk/Limit — finans_cari_kart veya Cari_Kart'tan."""
    result: dict[str, Any] = {
        'risk': None, 'limit': None,
        'risk_notu': 'Risk kaynağı tanımlı değil.',
        'limit_notu': 'Cari limit kaynağı tanımlı değil.',
    }
    # finans_cari_kart kaynağı — nexgen_cari_id → ckod eşleşmesiyle değil, ckod ile
    if ckod and _tablo_var(con, 'finans_cari_kart'):
        r = con.execute(
            "SELECT risk_limiti, kredi_limiti FROM finans_cari_kart WHERE ckod=? AND COALESCE(aktif,1)=1",
            (ckod,),
        ).fetchone()
        if r:
            if r['risk_limiti'] is not None:
                result['risk'] = _float(r['risk_limiti'])
                result['risk_notu'] = 'finans_cari_kart.risk_limiti'
            if r['kredi_limiti'] is not None:
                result['limit'] = _float(r['kredi_limiti'])
                result['limit_notu'] = 'finans_cari_kart.kredi_limiti'
    return result


class FinansManuelTahsilatError(Exception):
    def __init__(self, mesaj: str, kod: int = 400):
        self.mesaj = mesaj
        self.kod = kod
        super().__init__(mesaj)


def manuel_tahsilat_olustur(
    con: sqlite3.Connection,
    cari_id: int,
    kullanici_id: int,
    *,
    alinan_tarih: str,
    odeme_tipi: str,
    alinan_tutar: float,
    para_birimi: str = 'TRY',
    siparis_id: int | None = None,
    sevkiyat_id: int | None = None,
    aciklama: str | None = None,
    odeme_referansi: str | None = None,
    cek_vade_tarihi: str | None = None,
) -> dict[str, Any]:
    """
    Manuel finans tahsilatı — MO write service ile aynı canonical tabloya yazar.
    kaynak_modul = MANUEL_FINANS.
    DB kolon uyumluluğu için mevcut mo_tahsilat_kayit şemasını kullanır.
    """
    from datetime import datetime
    import uuid as _uuid

    if not _tablo_var(con, 'mo_tahsilat_kayit'):
        raise FinansManuelTahsilatError('Tahsilat tablosu mevcut değil.', 500)

    tcols = _cols(con, 'mo_tahsilat_kayit')

    # Validasyon
    ot = (odeme_tipi or '').strip().upper()
    from modules.nexgen.mo_tahsilat_config import ODEME_SEKILLERI
    if ot not in ODEME_SEKILLERI:
        raise FinansManuelTahsilatError(f'Geçersiz ödeme tipi: {ot}', 400)
    if alinan_tutar is None or float(alinan_tutar) <= 0:
        raise FinansManuelTahsilatError('Tutar sıfırdan büyük olmalı.', 400)
    if not alinan_tarih:
        raise FinansManuelTahsilatError('Tahsilat tarihi zorunludur.', 400)

    # Cross-cari pointer validation
    if siparis_id is not None:
        sprow = con.execute(
            'SELECT id FROM nexgen_planlama_siparis WHERE id=? AND cari_id=?',
            (int(siparis_id), int(cari_id))
        ).fetchone()
        if not sprow:
            raise FinansManuelTahsilatError('Sipariş bu cariye ait değil.', 400)
    if sevkiyat_id is not None:
        svrow = con.execute(
            'SELECT id FROM mo_musteri_sevkiyat WHERE id=? AND cari_id=?',
            (int(sevkiyat_id), int(cari_id))
        ).fetchone()
        if not svrow:
            raise FinansManuelTahsilatError('Sevkiyat bu cariye ait değil.', 400)

    # Otomatik kayit_kodu
    seq = con.execute(
        "SELECT COUNT(*) FROM mo_tahsilat_kayit WHERE COALESCE(aktif,1)=1"
    ).fetchone()[0] + 1
    kayit_kodu = f'MAN-T-{datetime.now().year}-{seq:04d}'
    idempotency = str(_uuid.uuid4())
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    cols_ins = [
        'kayit_kodu', 'cari_id', 'kaynak_modul', 'alinan_tutar', 'alinan_tarih',
        'odeme_tipi', 'durum', 'idempotency_key', 'olusturan_id',
        'olusturma_tarihi', 'guncelleme_tarihi', 'aktif', 'beklenen_tahmini',
    ]
    vals: list[Any] = [
        kayit_kodu, int(cari_id), KAYNAK_MANUEL_FINANS, float(alinan_tutar), alinan_tarih,
        ot, 'ONAYLANDI', idempotency, int(kullanici_id),
        now, now, 1, 0,
    ]

    if 'para_birimi' in tcols:
        cols_ins.append('para_birimi')
        vals.append(para_birimi or 'TRY')
    if 'siparis_id' in tcols and siparis_id is not None:
        cols_ins.append('siparis_id')
        vals.append(int(siparis_id))
    if 'sevkiyat_id' in tcols and sevkiyat_id is not None:
        cols_ins.append('sevkiyat_id')
        vals.append(int(sevkiyat_id))
    if 'aciklama' in tcols:
        cols_ins.append('aciklama')
        vals.append(aciklama or None)
    if 'odeme_referansi' in tcols:
        cols_ins.append('odeme_referansi')
        vals.append(odeme_referansi or None)

    ph = ','.join('?' * len(vals))
    col_str = ','.join(cols_ins)
    con.execute(f'INSERT INTO mo_tahsilat_kayit ({col_str}) VALUES ({ph})', vals)

    # CEK ise gerçek çek kaydı
    if ot == 'CEK' and cek_vade_tarihi and _tablo_var(con, 'mo_tahsilat_cek'):
        new_id = con.execute('SELECT last_insert_rowid()').fetchone()[0]
        cek_idem = _uuid.uuid4().hex
        cek_now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        con.execute(
            """INSERT INTO mo_tahsilat_cek
               (tahsilat_kayit_id, sira_no, tutar, para_birimi,
                cek_alim_tarihi, gercek_cek_vade_tarihi, odeme_referansi,
                durum, aktif, idempotency_key, olusturan_id,
                olusturma_tarihi, guncelleme_tarihi)
               VALUES (?,1,?,?,?,?,?,'AKTIF',1,?,?,?,?)""",
            (new_id, float(alinan_tutar), para_birimi or 'TRY',
             alinan_tarih, cek_vade_tarihi, odeme_referansi or None,
             cek_idem, int(kullanici_id), cek_now, cek_now),
        )

    con.commit()
    return {'ok': True, 'kayit_kodu': kayit_kodu}
