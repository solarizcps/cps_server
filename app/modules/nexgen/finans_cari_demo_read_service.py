# -*- coding: utf-8 -*-
"""Cari Kart demo read katmanı — Risk, Yetkililer, Fiyatlar (yalnız demo modu)."""
from __future__ import annotations

import sqlite3
from typing import Any

from modules.nexgen.finans_belgesi_repository import tablo_var

DEMO_MUSTERI_OID = 1
DEMO_TEDARIKCI_OID = 3
DEMO_KARMA_OID = 2


def _demo_yetkililer(unvan: str) -> list[dict[str, Any]]:
    return [
        {
            'yetkili': 'Ayşe Yılmaz',
            'unvan': 'Finans Müdürü',
            'telefon': '+90 212 555 0101',
            'cep': '+90 532 555 0101',
            'email': 'ayse.yilmaz@ornek.com',
            'not': f'{unvan} tahsilat ve vade takibi için birincil yetkili.',
            'sms_yetkili': True,
            'mail_yetkili': True,
        },
        {
            'yetkili': 'Mehmet Kaya',
            'unvan': 'Satın Alma',
            'telefon': '+90 212 555 0102',
            'cep': '+90 533 555 0102',
            'email': 'mehmet.kaya@ornek.com',
            'not': 'Sipariş onayı ve sevkiyat koordinasyonu.',
            'sms_yetkili': False,
            'mail_yetkili': True,
        },
    ]


def _demo_fiyatlar() -> list[dict[str, Any]]:
    return [
        {'stok_kodu': 'RNK-1001', 'stok_tanimi': 'Reactive Black GR', 'fiyat': 12.50, 'para_birimi': 'EUR', 'fiyat_tarihi': '2026-01-15', 'iskonto': 5.0, 'aktif': True},
        {'stok_kodu': 'RNK-2044', 'stok_tanimi': 'Disperse Blue 56', 'fiyat': 9.80, 'para_birimi': 'EUR', 'fiyat_tarihi': '2026-03-01', 'iskonto': 0.0, 'aktif': True},
        {'stok_kodu': 'RNK-3300', 'stok_tanimi': 'Acid Red 88', 'fiyat': 14.20, 'para_birimi': 'TRY', 'fiyat_tarihi': '2025-11-20', 'iskonto': 2.5, 'aktif': False},
    ]


def _demo_cek_senetler() -> list[dict[str, Any]]:
    return [
        {'konum': 'Merkez', 'durum': 'Portföyde', 'tarih': '2026-02-10', 'bordro_no': 'BR-2026-014', 'vade_tarihi': '2026-05-10', 'tutar': 45000.0, 'kur': 1.0, 'tur': 'Şahsi Çek', 'aciklama': 'Demo tahsilat çeki'},
        {'konum': 'Merkez', 'durum': 'Ciro', 'tarih': '2026-04-01', 'bordro_no': 'BR-2026-028', 'vade_tarihi': '2026-07-01', 'tutar': 28000.0, 'kur': 1.0, 'tur': 'Ciro Çek', 'aciklama': 'Demo ciro çeki'},
    ]


def demo_risk_read(
    con: sqlite3.Connection,
    cari_tipi: str,
    operasyonel_id: int,
) -> dict[str, Any]:
    from modules.nexgen.finans_cari_hesap_read_service import cari_ozet
    oz = cari_ozet(con, cari_tipi, int(operasyonel_id))
    cekler = _demo_cek_senetler()
    sahsi = sum(c['tutar'] for c in cekler if 'Şahsi' in c['tur'])
    ciro = sum(c['tutar'] for c in cekler if 'Ciro' in c['tur'])
    bakiye = float(oz.get('bakiye') or 0)
    return {
        'demo_modu': True,
        'demo_etiket': 'DEMO RİSK VERİSİ',
        'cari_bakiye': oz.get('bakiye'),
        'risk_limiti': 250000.0,
        'kredi_limiti': 180000.0,
        'risk_mevcut': True,
        'domain_mevcut': False,
        'cek_senetler': cekler,
        'ozet': {
            'sahsi_cek_tutari': round(sahsi, 2),
            'ciro_cek_tutari': round(ciro, 2),
            'toplam_cek_tutari': round(sahsi + ciro, 2),
            'cari_bakiye': oz.get('bakiye'),
            'toplam_risk': round(max(0, bakiye) + sahsi + ciro, 2),
        },
        'para_birimi': oz.get('para_birimi') or 'TRY',
    }


def production_risk_read(
    con: sqlite3.Connection,
    cari_tipi: str,
    operasyonel_id: int,
) -> dict[str, Any]:
    from modules.nexgen.finans_cari_hesap_read_service import cari_ozet
    oz = cari_ozet(con, cari_tipi, int(operasyonel_id))
    risk_limiti = kredi_limiti = None
    ckod = oz.get('cari_kart_ckod')
    if ckod and tablo_var(con, 'finans_cari_kart'):
        row = con.execute(
            'SELECT risk_limiti, kredi_limiti FROM finans_cari_kart WHERE ckod=? LIMIT 1',
            (ckod,),
        ).fetchone()
        if row:
            risk_limiti = row['risk_limiti']
            kredi_limiti = row['kredi_limiti']
    return {
        'demo_modu': False,
        'demo_etiket': None,
        'cari_bakiye': oz.get('bakiye'),
        'risk_limiti': risk_limiti,
        'kredi_limiti': kredi_limiti,
        'risk_mevcut': risk_limiti is not None or kredi_limiti is not None,
        'domain_mevcut': False,
        'cek_senetler': [],
        'ozet': {
            'sahsi_cek_tutari': None,
            'ciro_cek_tutari': None,
            'toplam_cek_tutari': None,
            'cari_bakiye': oz.get('bakiye'),
            'toplam_risk': None,
        },
        'para_birimi': oz.get('para_birimi') or 'TRY',
        'mesaj': 'Çek/senet risk detayı NexGen finans modülünde henüz tanımlı değil.',
    }


def demo_yetkililer_read(
    con: sqlite3.Connection,
    cari_tipi: str,
    operasyonel_id: int,
) -> dict[str, Any]:
    from modules.nexgen.finans_cari_hesap_read_service import cari_ozet
    oz = cari_ozet(con, cari_tipi, int(operasyonel_id))
    return {
        'demo_modu': True,
        'demo_etiket': 'DEMO VERİ',
        'yetkililer': _demo_yetkililer(oz.get('unvan') or 'Cari'),
        'odeme_plani': {'mevcut': True, 'aciklama': 'Demo: 30-60-90 gün vadeli ödeme planı'},
        'notlar': 'Demo cari notu — vade takibi Pazartesi günleri yapılır.',
    }


def production_yetkililer_read(
    con: sqlite3.Connection,
    cari_tipi: str,
    operasyonel_id: int,
) -> dict[str, Any]:
    from modules.nexgen.finans_cari_hesap_read_service import cari_ozet
    oz = cari_ozet(con, cari_tipi, int(operasyonel_id))
    return {
        'demo_modu': False,
        'demo_etiket': None,
        'yetkililer': [],
        'odeme_plani': {'mevcut': False, 'aciklama': None},
        'notlar': None,
        'mesaj': 'Yetkili kişi kaynağı ikinci aşamada bağlanacak.',
        'unvan': oz.get('unvan'),
    }


def demo_fiyatlar_read(con: sqlite3.Connection, cari_tipi: str, operasyonel_id: int) -> dict[str, Any]:
    return {
        'demo_modu': True,
        'demo_etiket': 'DEMO VERİ',
        'fiyatlar': _demo_fiyatlar(),
    }


def production_fiyatlar_read(con: sqlite3.Connection, cari_tipi: str, operasyonel_id: int) -> dict[str, Any]:
    fiyatlar: list[dict[str, Any]] = []
    mesaj = 'Cari özel fiyat listesi kaynağı henüz bağlanmadı.'
    if cari_tipi == 'MUSTERI' and tablo_var(con, 'pzm_anlasma_fiyati'):
        rows = con.execute(
            """
            SELECT urun_kodu, urun_adi, anlasma_fiyati, para_birimi, gecerlilik_baslangic, gecerlilik_bitis
            FROM pzm_anlasma_fiyati WHERE cari_id=? AND aktif=1 LIMIT 50
            """,
            (int(operasyonel_id),),
        ).fetchall()
        for r in rows:
            fiyatlar.append({
                'stok_kodu': r['urun_kodu'],
                'stok_tanimi': r['urun_adi'],
                'fiyat': r['anlasma_fiyati'],
                'para_birimi': r['para_birimi'] or 'TRY',
                'fiyat_tarihi': (r['gecerlilik_baslangic'] or '')[:10],
                'iskonto': 0.0,
                'aktif': True,
            })
        if fiyatlar:
            mesaj = None
    return {
        'demo_modu': False,
        'demo_etiket': None,
        'fiyatlar': fiyatlar,
        'mesaj': mesaj if not fiyatlar else None,
    }
