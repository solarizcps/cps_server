# -*- coding: utf-8 -*-
"""Cari Hesap Merkezi — read-only orchestrasyon (FAZ-FINANS-CARI-HESAP-MERKEZI-1)."""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from modules.nexgen.finans_belgesi_config import (
    BELGE_TIP_SATIS_SEVKIYAT,
    DURUM_ETIKET,
    DURUM_KAPANDI,
    DURUM_REDDEDILDI,
    POSTING_DURUM_ETIKET,
)
from modules.nexgen.finans_belgesi_repository import tablo_var
from modules.nexgen.finans_cari_account_service import hareket_dokumu, open_item_ozet
from modules.nexgen.finans_cari_aylik_durum_service import aylik_durum_read
from modules.nexgen.finans_cari_demo_read_service import (
    demo_fiyatlar_read,
    demo_risk_read,
    demo_yetkililer_read,
    production_fiyatlar_read,
    production_risk_read,
    production_yetkililer_read,
)
from modules.nexgen.finans_cari_genel_durum_service import genel_durum_read
from modules.nexgen.finans_cari_hesap_detay_service import hesap_detay_read
from modules.nexgen.finans_cari_hesap_workspace_service import hesap_workspace_read
from modules.nexgen.finans_cari_identity_resolver import (
    FinansCariIdentityError,
    resolve_by_operasyonel,
)
from modules.nexgen.finans_cari_read_service import (
    FinansCariReadError,
    cari_acik_belgeler,
    cari_golden_durum_paket,
    cari_hareket_liste,
    cari_hareket_ozet,
    cari_hesap_paket,
)
from modules.nexgen.finans_read_service import liste_belgeler
from modules.nexgen.finans_ledger_standard import (
    bakiye_durumu_etiket as _ledger_bakiye_etiket,
    bakiye_durumu_kod as _ledger_bakiye_kod,
    hareket_kaynak_say,
)

CARI_TIP_MUSTERI = 'MUSTERI'
CARI_TIP_TEDARIKCI = 'TEDARIKCI'
CARI_TIPLERI = (CARI_TIP_MUSTERI, CARI_TIP_TEDARIKCI)


class FinansCariHesapReadError(Exception):
    def __init__(self, mesaj: str, kod: int = 400, hata_kodu: str | None = None):
        self.mesaj = mesaj
        self.kod = kod
        self.hata_kodu = hata_kodu
        super().__init__(mesaj)


def _float(v: Any) -> float:
    if v in (None, ''):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _today_iso() -> str:
    return date.today().isoformat()


def _bakiye_durumu(bakiye: float) -> str:
    return _ledger_bakiye_kod(bakiye)


def _bakiye_durumu_etiket(kod: str) -> str:
    return _ledger_bakiye_etiket(kod)


def _ckod_musteri(con: sqlite3.Connection, cari_id: int) -> str | None:
    g = cari_golden_durum_paket(con, cari_id)
    return g.get('cari_kart_ckod')


def _ckod_tedarikci(con: sqlite3.Connection, tedarikci_id: int) -> str | None:
    if tablo_var(con, 'tedarikci_eslestirme'):
        row = con.execute(
            """
            SELECT cari_kart_ckod FROM tedarikci_eslestirme
            WHERE nexgen_tedarikci_id=? AND aktif=1
              AND eslestirme_durumu IN ('DOGRULANDI','MANUEL')
              AND cari_kart_ckod IS NOT NULL AND cari_kart_ckod != ''
            ORDER BY id DESC LIMIT 1
            """,
            (int(tedarikci_id),),
        ).fetchone()
        if row:
            return row['cari_kart_ckod']
    if tablo_var(con, 'finans_cari_kimlik'):
        row = con.execute(
            """
            SELECT cari_kart_ckod FROM finans_cari_kimlik
            WHERE nexgen_tedarikci_id=? AND aktif=1
              AND cari_kart_ckod IS NOT NULL AND cari_kart_ckod != ''
            ORDER BY id DESC LIMIT 1
            """,
            (int(tedarikci_id),),
        ).fetchone()
        if row:
            return row['cari_kart_ckod']
    return None


def _kart_baglanti_eksik_resolver(
    con: sqlite3.Connection,
    cari_tipi: str,
    operasyonel_id: int,
) -> bool:
    """Yalnız gerçek teknik istisna — sağlıklı cari False döner."""
    try:
        res = resolve_by_operasyonel(con, cari_tipi, int(operasyonel_id), require_active=True)
        if res.finans_kart and not res.requires_manual_link:
            return False
        return bool(res.requires_manual_link)
    except FinansCariIdentityError:
        return True


def _kart_baglanti_eksik_musteri(con: sqlite3.Connection, cari_id: int) -> bool:
    return _kart_baglanti_eksik_resolver(con, CARI_TIP_MUSTERI, int(cari_id))


def _kart_baglanti_eksik_tedarikci(con: sqlite3.Connection, tedarikci_id: int) -> bool:
    return _kart_baglanti_eksik_resolver(con, CARI_TIP_TEDARIKCI, int(tedarikci_id))


def _domain_alan_yok(alan: str) -> dict[str, Any]:
    return {
        'mevcut': False,
        'tutar': None,
        'sayi': None,
        'mesaj': f'{alan} kaydı NexGen finans modülünde henüz tanımlı değil.',
    }


def _hareket_kaynak_say(con: sqlite3.Connection, ckod: str | None) -> dict[str, int]:
    return hareket_kaynak_say(con, ckod)


def _son_kayit(con: sqlite3.Connection, sql: str, params: tuple) -> dict[str, Any] | None:
    row = con.execute(sql, params).fetchone()
    return dict(row) if row else None


def _liste_satir_bakiye(con: sqlite3.Connection, ckod: str | None) -> dict[str, Any]:
    if not ckod:
        return {
            'bakiye': None,
            'toplam_borc': None,
            'toplam_alacak': None,
            'bakiye_durumu': None,
            'bakiye_durumu_etiket': None,
            'bakiye_mevcut': False,
            'para_birimi': 'TRY',
        }
    oz = cari_hareket_ozet(con, ckod)
    bd = _bakiye_durumu(_float(oz.get('bakiye')))
    return {
        'bakiye': oz.get('bakiye'),
        'toplam_borc': oz.get('toplam_borc'),
        'toplam_alacak': oz.get('toplam_alacak'),
        'bakiye_durumu': bd,
        'bakiye_durumu_etiket': _bakiye_durumu_etiket(bd),
        'bakiye_mevcut': bool(oz.get('hareket_sayisi')),
        'para_birimi': 'TRY',
    }


def cari_liste(
    con: sqlite3.Connection,
    *,
    cari_tipi: str = CARI_TIP_MUSTERI,
    arama: str | None = None,
    aktif: str | None = None,
    bakiye_filtre: str | None = None,
    yalniz_eslesme_eksik: bool = False,
    secim_modu: bool = True,
    limit: int = 80,
    offset: int = 0,
) -> dict[str, Any]:
    """Cari seçim listesi — secim_modu=True iken teknik sorunlu kayıtlar gizlenir."""
    if cari_tipi not in CARI_TIPLERI:
        raise FinansCariHesapReadError('Geçersiz cari tipi.', 400, 'CARI_TIP_GECERSIZ')

    ham: list[dict[str, Any]] = []
    if cari_tipi == CARI_TIP_MUSTERI:
        if not tablo_var(con, 'nexgen_cari'):
            return {'toplam': 0, 'limit': limit, 'offset': offset, 'kayitlar': []}
        q = 'SELECT id, cari_kod, unvan, aktif FROM nexgen_cari WHERE 1=1'
        params: list[Any] = []
        if aktif == '1':
            q += ' AND aktif=1'
        elif aktif == '0':
            q += ' AND aktif=0'
        q += ' ORDER BY unvan COLLATE NOCASE, id'
        for row in con.execute(q, params).fetchall():
            cid = int(row['id'])
            ckod = _ckod_musteri(con, cid)
            bak = _liste_satir_bakiye(con, ckod)
            ham.append({
                'cari_tipi': CARI_TIP_MUSTERI,
                'operasyonel_id': cid,
                'kod': row['cari_kod'],
                'unvan': row['unvan'],
                'firma_unvani': row['unvan'],
                'aktif': bool(row['aktif']),
                'cari_kart_ckod': ckod,
                'kart_baglanti_eksik': _kart_baglanti_eksik_musteri(con, cid),
                **bak,
            })
    else:
        if not tablo_var(con, 'nexgen_tedarikci'):
            return {'toplam': 0, 'limit': limit, 'offset': offset, 'kayitlar': []}
        q = 'SELECT id, kod, ad, aktif FROM nexgen_tedarikci WHERE 1=1'
        params = []
        if aktif == '1':
            q += ' AND aktif=1'
        elif aktif == '0':
            q += ' AND aktif=0'
        q += ' ORDER BY ad COLLATE NOCASE, id'
        for row in con.execute(q, params).fetchall():
            tid = int(row['id'])
            ckod = _ckod_tedarikci(con, tid)
            bak = _liste_satir_bakiye(con, ckod)
            ham.append({
                'cari_tipi': CARI_TIP_TEDARIKCI,
                'operasyonel_id': tid,
                'kod': row['kod'],
                'unvan': row['ad'],
                'firma_unvani': row['ad'],
                'aktif': bool(row['aktif']),
                'cari_kart_ckod': ckod,
                'kart_baglanti_eksik': _kart_baglanti_eksik_tedarikci(con, tid),
                **bak,
            })

    if arama:
        a = arama.strip().casefold()
        ham = [
            r for r in ham
            if a in ' '.join(filter(None, [
                str(r.get('kod') or ''),
                str(r.get('unvan') or ''),
                str(r.get('cari_kart_ckod') or ''),
            ])).casefold()
        ]

    if yalniz_eslesme_eksik:
        ham = [r for r in ham if r.get('kart_baglanti_eksik')]
    elif secim_modu:
        ham = [r for r in ham if not r.get('kart_baglanti_eksik')]

    if bakiye_filtre == 'BORCLU':
        ham = [r for r in ham if r.get('bakiye_durumu') == 'BORCLU']
    elif bakiye_filtre == 'ALACAKLI':
        ham = [r for r in ham if r.get('bakiye_durumu') == 'ALACAKLI']
    elif bakiye_filtre == 'SIFIR':
        ham = [r for r in ham if r.get('bakiye_durumu') == 'SIFIR' or (
            r.get('bakiye') is not None and abs(_float(r.get('bakiye'))) <= 0.005
        )]

    total = len(ham)
    page = ham[int(offset): int(offset) + int(limit)]
    if secim_modu and not yalniz_eslesme_eksik:
        page = [
            {k: v for k, v in r.items() if k not in ('kart_baglanti_eksik', 'cari_kart_ckod')}
            for r in page
        ]
    return {'toplam': total, 'limit': limit, 'offset': offset, 'kayitlar': page}


def cari_ozet(
    con: sqlite3.Connection,
    cari_tipi: str,
    operasyonel_id: int,
    *,
    yk: set[str] | frozenset[str] | None = None,
    user_dict: dict | None = None,
) -> dict[str, Any]:
    if cari_tipi == CARI_TIP_MUSTERI:
        paket = cari_hesap_paket(con, int(operasyonel_id), yk=yk, user_dict=user_dict)
        nc = paket['nexgen_cari']
        bak = paket.get('bakiye') or {}
        acik = paket.get('acik_belgeler') or {}
        golden = paket.get('golden') or {}
        son_h_raw = paket.get('son_hareketler') or []
        son_h = [h for h in son_h_raw if not h.get('legacy_kaynak')][:10]
        ckod = golden.get('cari_kart_ckod') or _ckod_musteri(con, int(operasyonel_id))
        hsay = _hareket_kaynak_say(con, ckod)
        son_tah = _son_kayit(
            con,
            """
            SELECT kayit_kodu, alinan_tarih, alinan_tutar, odeme_tipi
            FROM mo_tahsilat_kayit WHERE cari_id=? AND aktif=1
            ORDER BY alinan_tarih DESC, id DESC LIMIT 1
            """,
            (int(operasyonel_id),),
        ) if tablo_var(con, 'mo_tahsilat_kayit') else None
        son_sev = _son_kayit(
            con,
            """
            SELECT sevkiyat_no, sevk_tarihi, durum
            FROM mo_musteri_sevkiyat WHERE cari_id=? AND aktif=1
            ORDER BY sevk_tarihi DESC, id DESC LIMIT 1
            """,
            (int(operasyonel_id),),
        ) if tablo_var(con, 'mo_musteri_sevkiyat') else None
        son_fb = _son_kayit(
            con,
            """
            SELECT belge_kodu, belge_tipi, islem_tarihi, toplam_tutar, para_birimi
            FROM finans_belgesi WHERE cari_id=? AND aktif=1
            ORDER BY islem_tarihi DESC, id DESC LIMIT 1
            """,
            (int(operasyonel_id),),
        ) if tablo_var(con, 'finans_belgesi') else None
        bd = _bakiye_durumu(_float(bak.get('bakiye'))) if bak.get('mevcut') else 'SIFIR'
        kart_eksik = _kart_baglanti_eksik_musteri(con, int(operasyonel_id))
        resolution = resolve_by_operasyonel(con, CARI_TIP_MUSTERI, int(operasyonel_id))
        oi = open_item_ozet(con, resolution.finance_card_code if resolution.finans_kart else None)
        vadesi_gecmis_tutar = acik.get('vadesi_gecen_tutar')
        vadesi_gecmis_sayisi = acik.get('vadesi_gecen_belge_sayisi')
        if oi.get('mevcut'):
            vadesi_gecmis_tutar = oi.get('vadesi_gecmis_toplam')
            vadesi_gecmis_sayisi = oi.get('vadesi_gecmis_sayisi')
        return {
            'cari_tipi': CARI_TIP_MUSTERI,
            'operasyonel_id': int(operasyonel_id),
            'kod': nc.get('cari_kod'),
            'unvan': nc.get('unvan'),
            'aktif': nc.get('aktif'),
            'para_birimi': 'TRY',
            'cari_kart_ckod': ckod,
            'kart_baglanti_eksik': kart_eksik or resolution.requires_manual_link,
            'finans_kart': resolution.finans_kart,
            'kimlik_cozumleme': resolution.to_dict(),
            'open_item': oi,
            'is_legacy_fallback': resolution.is_legacy_fallback,
            'toplam_borc': bak.get('toplam_borc'),
            'toplam_alacak': bak.get('toplam_alacak'),
            'bakiye': bak.get('bakiye') if bak.get('mevcut') else None,
            'bakiye_durumu': bd if bak.get('mevcut') else None,
            'bakiye_durumu_etiket': _bakiye_durumu_etiket(bd) if bak.get('mevcut') else None,
            'bakiye_mevcut': bool(bak.get('mevcut')),
            'vadesi_gecmis_tutar': vadesi_gecmis_tutar,
            'vadesi_gecmis_sayisi': vadesi_gecmis_sayisi,
            'acik_belge_sayisi': acik.get('aktif_belge_sayisi'),
            'acik_belge_tutari': acik.get('aktif_belge_tutar_toplami'),
            'son_hareket_tarihi': bak.get('son_islem_tarihi'),
            'hareket_sayisi': hsay,
            'risk': _domain_alan_yok('Risk'),
            'cek_alinan': _domain_alan_yok('Alınan çek'),
            'cek_verilen': _domain_alan_yok('Verilen çek'),
            'avans': _domain_alan_yok('Avans'),
            'odeme_plani': _domain_alan_yok('Ödeme planı'),
            'son_tahsilat': {
                'mevcut': bool(son_tah),
                'no': son_tah.get('kayit_kodu') if son_tah else None,
                'tarih': son_tah.get('alinan_tarih') if son_tah else None,
                'tutar': round(_float(son_tah.get('alinan_tutar')), 2) if son_tah else None,
                'yontem': son_tah.get('odeme_tipi') if son_tah else None,
            },
            'son_odeme': {'mevcut': False, 'mesaj': 'Ödeme kaydı NexGen finans modülünde henüz tanımlı değil.'},
            'son_sevkiyat': {
                'mevcut': bool(son_sev),
                'no': son_sev.get('sevkiyat_no') if son_sev else None,
                'tarih': son_sev.get('sevk_tarihi') if son_sev else None,
                'durum': son_sev.get('durum') if son_sev else None,
            },
            'son_finans_belgesi': {
                'mevcut': bool(son_fb),
                'no': son_fb.get('belge_kodu') if son_fb else None,
                'tarih': son_fb.get('islem_tarihi') if son_fb else None,
                'tutar': round(_float(son_fb.get('toplam_tutar')), 2) if son_fb else None,
                'para_birimi': son_fb.get('para_birimi') if son_fb else None,
            },
            'golden': golden,
            'uyarilar': paket.get('uyarilar') or [],
            'navigasyon': paket.get('navigasyon') or {},
            'son_hareketler': son_h,
            'legacy_hareket_sayisi': hsay.get('legacy', 0),
            'nexgen_hareket_sayisi': hsay.get('nexgen', 0),
            'reversal_hareket_sayisi': hsay.get('reversal', 0),
        }

    if not tablo_var(con, 'nexgen_tedarikci'):
        raise FinansCariHesapReadError('Tedarikçi tablosu yok.', 404, 'TEDARIKCI_TABLO_YOK')
    nt = con.execute(
        'SELECT id, kod, ad, aktif FROM nexgen_tedarikci WHERE id=?',
        (int(operasyonel_id),),
    ).fetchone()
    if not nt:
        raise FinansCariHesapReadError('Tedarikçi bulunamadı.', 404, 'TEDARIKCI_YOK')
    ckod = _ckod_tedarikci(con, int(operasyonel_id))
    bak = _liste_satir_bakiye(con, ckod)
    son_h_raw = cari_hareket_liste(con, ckod, limit=50) if ckod else []
    son_h = [h for h in son_h_raw if not h.get('legacy_kaynak')][:10]
    hsay = _hareket_kaynak_say(con, ckod)
    uyarilar: list[dict[str, str]] = []
    if not ckod:
        uyarilar.append({
            'kod': 'KART_BAGLANTISI_EKSIK',
            'mesaj': 'Cari kart verisi kontrol edilmeli.',
        })
    kart_eksik = _kart_baglanti_eksik_tedarikci(con, int(operasyonel_id))
    resolution = resolve_by_operasyonel(con, CARI_TIP_TEDARIKCI, int(operasyonel_id))
    oi = open_item_ozet(con, resolution.finance_card_code if resolution.finans_kart else None)
    return {
        'cari_tipi': CARI_TIP_TEDARIKCI,
        'operasyonel_id': int(operasyonel_id),
        'kod': nt['kod'],
        'unvan': nt['ad'],
        'aktif': bool(nt['aktif']),
        'cari_kart_ckod': ckod,
        'kart_baglanti_eksik': kart_eksik or resolution.requires_manual_link,
        'finans_kart': resolution.finans_kart,
        'kimlik_cozumleme': resolution.to_dict(),
        'open_item': oi,
        'is_legacy_fallback': resolution.is_legacy_fallback,
        'para_birimi': 'TRY',
        'toplam_borc': bak.get('toplam_borc'),
        'toplam_alacak': bak.get('toplam_alacak'),
        'bakiye': bak.get('bakiye'),
        'bakiye_durumu': bak.get('bakiye_durumu'),
        'bakiye_durumu_etiket': bak.get('bakiye_durumu_etiket'),
        'bakiye_mevcut': bak.get('bakiye_mevcut'),
        'vadesi_gecmis_tutar': oi.get('vadesi_gecmis_toplam') if oi.get('mevcut') else None,
        'vadesi_gecmis_sayisi': oi.get('vadesi_gecmis_sayisi') if oi.get('mevcut') else None,
        'acik_belge_sayisi': 0,
        'acik_belge_tutari': 0.0,
        'son_hareket_tarihi': None,
        'hareket_sayisi': hsay,
        'risk': _domain_alan_yok('Risk'),
        'cek_alinan': _domain_alan_yok('Alınan çek'),
        'cek_verilen': _domain_alan_yok('Verilen çek'),
        'avans': _domain_alan_yok('Avans'),
        'odeme_plani': _domain_alan_yok('Ödeme planı'),
        'son_tahsilat': {'mevcut': False, 'mesaj': 'Tahsilat kayıtları müşteri carilerinde gösterilir.'},
        'son_odeme': {'mevcut': False, 'mesaj': 'Ödeme kaydı NexGen finans modülünde henüz tanımlı değil.'},
        'son_sevkiyat': {'mevcut': False, 'mesaj': 'Sevkiyat kayıtları müşteri carilerinde gösterilir.'},
        'son_finans_belgesi': {'mevcut': False, 'mesaj': 'Finans belgeleri bu fazda müşteri carilerinde desteklenir.'},
        'golden': None,
        'uyarilar': uyarilar,
        'navigasyon': {},
        'son_hareketler': son_h,
        'legacy_hareket_sayisi': hsay.get('legacy', 0),
        'nexgen_hareket_sayisi': hsay.get('nexgen', 0),
        'reversal_hareket_sayisi': hsay.get('reversal', 0),
    }


def cari_hareketler(
    con: sqlite3.Connection,
    cari_tipi: str,
    operasyonel_id: int,
    *,
    tarih_bas: str | None = None,
    tarih_bit: str | None = None,
    islem_turu: str | None = None,
    belge_no: str | None = None,
    kaynak: str | None = 'NEXGEN',
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    resolution = resolve_by_operasyonel(con, cari_tipi, int(operasyonel_id))
    ckod = resolution.finance_card_code
    if not ckod or not tablo_var(con, 'Cari_Har'):
        return {
            'toplam': 0,
            'limit': limit,
            'offset': offset,
            'bakiye_hesaplanabilir': False,
            'uyari': 'Cari Kart bağlantısı veya Cari_Har kaydı olmadan hareket dökümü gösterilemez.',
            'hareketler': [],
            'legacy_sayisi': 0,
            'nexgen_sayisi': 0,
            'kaynak_filtre': kaynak or 'NEXGEN',
        }

    paket = hareket_dokumu(
        con, ckod,
        kaynak=kaynak or 'NEXGEN',
        limit=100000,
        offset=0,
        tarih_bas=tarih_bas,
        tarih_bit=tarih_bit,
        islem_turu=islem_turu,
        belge_no=belge_no,
    )
    enriched = []
    for h in paket.get('hareketler') or []:
        fb_id = h.get('finans_belge_id')
        enriched.append({
            'id': h['id'],
            'tarih': h['tarih'],
            'belge_no': h['belge_no'],
            'islem_turu': h['islem_turu'],
            'aciklama': h['aciklama'],
            'kaynak': h['kaynak'],
            'kaynak_kodu': h['kaynak_kodu'],
            'legacy_kaynak': h.get('legacy_kaynak'),
            'borc': h['borc'],
            'alacak': h['alacak'],
            'bakiye': h['bakiye'],
            'vade': None,
            'durum': h['kaynak'] if not h.get('legacy_kaynak') else 'Önceki Dönem',
            'finans_belgesi_id': fb_id,
            'finans_belgesi_kodu': h.get('finans_belge_kodu'),
        })

    hsay = _hareket_kaynak_say(con, ckod)
    kaynak_norm = (kaynak or 'NEXGEN').strip().upper()
    total = len(enriched)
    page = list(reversed(enriched))[int(offset): int(offset) + int(limit)]
    uyari = None
    if kaynak_norm == 'NEXGEN' and hsay.get('legacy', 0) and not page:
        uyari = (
            f'NexGen finans belgesine bağlı hareket bulunmuyor. '
            f'Önceki dönem hareket sayısı: {hsay.get("legacy", 0)}.'
        )
    return {
        'toplam': total,
        'limit': limit,
        'offset': offset,
        'bakiye_hesaplanabilir': True,
        'uyari': uyari,
        'hareketler': page,
        'legacy_sayisi': hsay.get('legacy', 0),
        'nexgen_sayisi': hsay.get('nexgen', 0),
        'kaynak_filtre': kaynak_norm,
    }


def cari_finans_belgeleri(
    con: sqlite3.Connection,
    cari_tipi: str,
    operasyonel_id: int,
    *,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    if cari_tipi != CARI_TIP_MUSTERI:
        return {'liste': [], 'sayfalama': {'page': 1, 'total_pages': 0, 'total': 0}, 'uyari': 'Tedarikçi finans belgeleri bu fazda yalnız müşteri carilerinde desteklenir.'}
    paket = liste_belgeler(con, cari_id=int(operasyonel_id), page=page, page_size=page_size)
    return {'liste': paket.get('liste') or [], 'sayfalama': paket.get('sayfalama') or {}, 'uyari': None}


def cari_sevkiyatlar(con: sqlite3.Connection, cari_tipi: str, operasyonel_id: int) -> dict[str, Any]:
    if cari_tipi != CARI_TIP_MUSTERI or not tablo_var(con, 'mo_musteri_sevkiyat'):
        return {'sevkiyatlar': [], 'uyari': 'Sevkiyat kayıtları yalnız müşteri carilerinde gösterilir.'}

    rows = con.execute(
        """
        SELECT s.id, s.sevkiyat_no, s.siparis_id, s.durum, s.sevk_tarihi, s.teslim_tarihi,
               (SELECT COALESCE(SUM(miktar_kg),0) FROM mo_musteri_sevkiyat_kalem WHERE sevkiyat_id=s.id) AS toplam_kg
        FROM mo_musteri_sevkiyat s
        WHERE s.cari_id=? AND s.aktif=1
        ORDER BY s.id DESC LIMIT 100
        """,
        (int(operasyonel_id),),
    ).fetchall()

    out: list[dict[str, Any]] = []
    for r in rows:
        sid = int(r['id'])
        fb = None
        if tablo_var(con, 'finans_belgesi'):
            fb = con.execute(
                """
                SELECT id, belge_kodu, durum, posting_durumu, toplam_tutar, para_birimi
                FROM finans_belgesi WHERE sevkiyat_id=? AND aktif=1 ORDER BY id DESC LIMIT 1
                """,
                (sid,),
            ).fetchone()
        sip_no = None
        if tablo_var(con, 'nexgen_planlama_siparis'):
            sp = con.execute('SELECT siparis_no FROM nexgen_planlama_siparis WHERE id=?', (r['siparis_id'],)).fetchone()
            sip_no = sp['siparis_no'] if sp else None
        posting = dict(fb) if fb else None
        muh_durum = 'Finans belgesi yok'
        if posting:
            pd = posting.get('posting_durumu') or ''
            if pd == 'POST_EDILDI':
                muh_durum = 'Muhasebeleşti'
            elif pd == 'HAZIR':
                muh_durum = 'Muhasebeye hazır'
            elif pd:
                muh_durum = POSTING_DURUM_ETIKET.get(pd, pd)
            else:
                muh_durum = 'Muhasebe bekliyor'
        out.append({
            'sevkiyat_id': sid,
            'sevkiyat_no': r['sevkiyat_no'],
            'siparis_id': r['siparis_id'],
            'siparis_no': sip_no,
            'sevk_tarihi': r['sevk_tarihi'],
            'toplam_kg': round(_float(r['toplam_kg']), 2),
            'durum': r['durum'],
            'finans_belgesi_id': posting['id'] if posting else None,
            'finans_belgesi_kodu': posting['belge_kodu'] if posting else None,
            'finans_durumu': DURUM_ETIKET.get(posting['durum'], posting['durum']) if posting else None,
            'muhasebe_durumu': muh_durum,
            'tutar': round(_float(posting['toplam_tutar']), 2) if posting else None,
            'para_birimi': posting.get('para_birimi') if posting else 'TRY',
            'sevkiyat_url': f'/nexgen/sevkiyat/{sid}',
        })
    return {'sevkiyatlar': out, 'uyari': None}


def cari_tahsilatlar(con: sqlite3.Connection, cari_tipi: str, operasyonel_id: int) -> dict[str, Any]:
    if cari_tipi != CARI_TIP_MUSTERI or not tablo_var(con, 'mo_tahsilat_kayit'):
        return {'tahsilatlar': [], 'uyari': None}
    rows = con.execute(
        """
        SELECT id, kayit_kodu, alinan_tutar, alinan_tarih, odeme_tipi, durum, aciklama, kalan_tutar
        FROM mo_tahsilat_kayit WHERE cari_id=? AND aktif=1 ORDER BY id DESC LIMIT 100
        """,
        (int(operasyonel_id),),
    ).fetchall()
    out = []
    for r in rows:
        belge_id = None
        belge_kodu = None
        if tablo_var(con, 'finans_belgesi'):
            fb = con.execute(
                'SELECT id, belge_kodu FROM finans_belgesi WHERE tahsilat_kayit_id=? AND aktif=1 LIMIT 1',
                (int(r['id']),),
            ).fetchone()
            if fb:
                belge_id = fb['id']
                belge_kodu = fb['belge_kodu']
        out.append({
            'id': r['id'],
            'tahsilat_no': r['kayit_kodu'] or f'THS-{r["id"]}',
            'tarih': r['alinan_tarih'],
            'tutar': round(_float(r['alinan_tutar']), 2),
            'para_birimi': 'TRY',
            'odeme_yontemi': r['odeme_tipi'] or '—',
            'bagli_belge_id': belge_id,
            'bagli_belge_kodu': belge_kodu,
            'durum': r['durum'],
            'aciklama': r['aciklama'],
        })
    return {'tahsilatlar': out, 'uyari': None if out else 'Bu cari için tahsilat kaydı bulunmuyor.'}


def cari_odemeler(con: sqlite3.Connection, cari_tipi: str, operasyonel_id: int) -> dict[str, Any]:
    """NexGen finans modülünde tedarikçi ödeme tablosu yok — boş liste."""
    return {
        'odemeler': [],
        'uyari': (
            'NexGen finans modülünde ödeme kayıt tablosu bulunmuyor. '
            'Tedarikçi ödemeleri legacy finans modülünde tutuluyor olabilir.'
        ),
    }


def cari_vadeler(con: sqlite3.Connection, cari_tipi: str, operasyonel_id: int) -> dict[str, Any]:
    if cari_tipi != CARI_TIP_MUSTERI:
        return {'vadeler': [], 'uyari': 'Vade takibi yalnız finans belgelerinden türetilir (müşteri).'}
    acik = cari_acik_belgeler(con, int(operasyonel_id))
    bugun = _today_iso()
    vadeler = []
    for b in acik.get('belgeler') or []:
        vade = b.get('vade_tarihi')
        if not vade:
            continue
        try:
            gun = (date.fromisoformat(vade) - date.fromisoformat(bugun)).days
        except ValueError:
            gun = None
        if gun is not None:
            if gun < 0:
                vd = 'Vadesi geçti'
            elif gun == 0:
                vd = 'Bugün'
            elif gun <= 7:
                vd = 'Yaklaşıyor'
            else:
                vd = 'Normal'
        else:
            vd = '—'
        vadeler.append({
            'belge_id': b['id'],
            'belge_no': b['belge_kodu'],
            'belge_tarihi': None,
            'vade_tarihi': vade,
            'gun_sayisi': gun,
            'acik_tutar': b.get('toplam_tutar'),
            'para_birimi': b.get('para_birimi') or 'TRY',
            'vade_durumu': vd,
        })
    return {
        'vadeler': vadeler,
        'uyari': None if vadeler else 'Açık vade kalemi bulunmuyor (finans belgesi vade alanı).',
    }


def cari_bilgileri(con: sqlite3.Connection, cari_tipi: str, operasyonel_id: int) -> dict[str, Any]:
    oz = cari_ozet(con, cari_tipi, operasyonel_id)
    kimlik_durum = None
    ckod = oz.get('cari_kart_ckod') or (oz.get('golden') or {}).get('cari_kart_ckod')
    if cari_tipi == CARI_TIP_MUSTERI and tablo_var(con, 'finans_cari_kimlik'):
        row = con.execute(
            'SELECT durum, cari_kart_ckod FROM finans_cari_kimlik WHERE nexgen_cari_id=? ORDER BY id DESC LIMIT 1',
            (int(operasyonel_id),),
        ).fetchone()
        if row:
            kimlik_durum = row['durum']
            ckod = ckod or row['cari_kart_ckod']
    return {
        'kod': oz.get('kod'),
        'unvan': oz.get('unvan'),
        'cari_tipi': cari_tipi,
        'aktif': oz.get('aktif'),
        'para_birimi': oz.get('para_birimi') or 'TRY',
        'varsayilan_vade': None,
        'finans_kimlik_durumu': kimlik_durum,
        'cari_kart_ckod': ckod,
        'cari_kart_unvan': (oz.get('golden') or {}).get('cari_kart_unvan'),
        'muhasebe_uygunlugu': (oz.get('golden') or {}).get('posting_uygun') if oz.get('golden') else None,
        'kart_baglanti_eksik': oz.get('kart_baglanti_eksik'),
    }


def cari_hesap_workspace(
    con: sqlite3.Connection,
    cari_tipi: str,
    operasyonel_id: int,
    *,
    gorunum: str = 'aciklar',
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    """Hesap çalışma alanı — open item + önceki dönem (read-only)."""
    return hesap_workspace_read(
        con, cari_tipi, int(operasyonel_id),
        gorunum=gorunum,
        limit=limit,
        offset=offset,
    )


def cari_hesap_detay(
    con: sqlite3.Connection,
    cari_tipi: str,
    operasyonel_id: int,
    *,
    kaynak: str = 'TUMU',
    tarih_bas: str | None = None,
    tarih_bit: str | None = None,
    islem_turu: str | None = None,
    belge_no: str | None = None,
    tutar_min: float | None = None,
    tutar_max: float | None = None,
) -> dict[str, Any]:
    return hesap_detay_read(
        con, cari_tipi, int(operasyonel_id),
        kaynak=kaynak,
        tarih_bas=tarih_bas,
        tarih_bit=tarih_bit,
        islem_turu=islem_turu,
        belge_no=belge_no,
        tutar_min=tutar_min,
        tutar_max=tutar_max,
    )


def cari_genel_durum(
    con: sqlite3.Connection,
    cari_tipi: str,
    operasyonel_id: int,
    *,
    para_birimi: str | None = None,
    tum_islem_turleri: bool = False,
) -> dict[str, Any]:
    return genel_durum_read(
        con, cari_tipi, int(operasyonel_id),
        para_birimi=para_birimi,
        tum_islem_turleri=tum_islem_turleri,
    )


def cari_aylik_durum(
    con: sqlite3.Connection,
    cari_tipi: str,
    operasyonel_id: int,
    *,
    yil: int | None = None,
    para_birimi: str | None = None,
) -> dict[str, Any]:
    return aylik_durum_read(
        con, cari_tipi, int(operasyonel_id),
        yil=yil,
        para_birimi=para_birimi,
    )


def cari_risk(
    con: sqlite3.Connection,
    cari_tipi: str,
    operasyonel_id: int,
    *,
    demo_modu: bool = False,
) -> dict[str, Any]:
    if demo_modu:
        return demo_risk_read(con, cari_tipi, int(operasyonel_id))
    return production_risk_read(con, cari_tipi, int(operasyonel_id))


def cari_yetkililer(
    con: sqlite3.Connection,
    cari_tipi: str,
    operasyonel_id: int,
    *,
    demo_modu: bool = False,
) -> dict[str, Any]:
    if demo_modu:
        return demo_yetkililer_read(con, cari_tipi, int(operasyonel_id))
    return production_yetkililer_read(con, cari_tipi, int(operasyonel_id))


def cari_fiyatlar(
    con: sqlite3.Connection,
    cari_tipi: str,
    operasyonel_id: int,
    *,
    demo_modu: bool = False,
) -> dict[str, Any]:
    if demo_modu:
        return demo_fiyatlar_read(con, cari_tipi, int(operasyonel_id))
    return production_fiyatlar_read(con, cari_tipi, int(operasyonel_id))


def cari_siparisler(con: sqlite3.Connection, cari_tipi: str, operasyonel_id: int) -> dict[str, Any]:
    if cari_tipi != CARI_TIP_MUSTERI or not tablo_var(con, 'nexgen_planlama_siparis'):
        return {'siparisler': [], 'uyari': 'Bu cari tipi için sipariş listesi bulunmuyor.'}
    rows = con.execute(
        """
        SELECT id, siparis_no, olusturma_tarihi, termin_tarihi, durum, cari_unvan
        FROM nexgen_planlama_siparis
        WHERE cari_id=?
        ORDER BY olusturma_tarihi DESC, id DESC
        LIMIT 100
        """,
        (int(operasyonel_id),),
    ).fetchall()
    liste = []
    for r in rows:
        liste.append({
            'siparis_id': int(r['id']),
            'siparis_no': r['siparis_no'],
            'siparis_tarihi': (r['olusturma_tarihi'] or '')[:10],
            'termin_tarihi': (r['termin_tarihi'] or '')[:10] if r['termin_tarihi'] else None,
            'durum': r['durum'],
            'tutar': None,
            'kalan_tutar': None,
            'para_birimi': 'TRY',
            'siparis_url': f'/nexgen/planlama/siparis/{int(r["id"])}',
        })
    return {
        'siparisler': liste,
        'uyari': None if liste else 'Bu cari için sipariş kaydı bulunmuyor.',
    }


def cari_kart_kimlik(con: sqlite3.Connection, cari_tipi: str, operasyonel_id: int) -> dict[str, Any]:
    """Cari Kart header — teknik alanlar hariç."""
    oz = cari_ozet(con, cari_tipi, int(operasyonel_id))
    acilis = None
    ckod = oz.get('cari_kart_ckod')
    if ckod and tablo_var(con, 'finans_cari_kart'):
        kr = con.execute(
            'SELECT olusturma_tarihi FROM finans_cari_kart WHERE ckod=?', (ckod,),
        ).fetchone()
        if kr:
            acilis = (kr['olusturma_tarihi'] or '')[:10]
    elif ckod and tablo_var(con, 'Cari_Kart'):
        kr = con.execute('SELECT CKod FROM Cari_Kart WHERE CKod=?', (ckod,)).fetchone()
        if kr:
            acilis = None
    return {
        'cari_tipi': cari_tipi,
        'operasyonel_id': int(operasyonel_id),
        'kod': oz.get('kod'),
        'unvan': oz.get('unvan'),
        'firma_unvani': oz.get('unvan'),
        'para_birimi': oz.get('para_birimi') or 'TRY',
        'kart_acilis_tarihi': acilis,
        'aktif': oz.get('aktif'),
        'cari_tipi_etiket': 'Müşteri' if cari_tipi == CARI_TIP_MUSTERI else 'Tedarikçi',
        'bakiye': oz.get('bakiye'),
        'bakiye_durumu_etiket': oz.get('bakiye_durumu_etiket'),
    }
