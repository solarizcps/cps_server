# -*- coding: utf-8 -*-
"""NexGen Finans çekirdek sabitleri — FAZ-FINANS-F1."""
from __future__ import annotations

# --- Cari kart ---
CARI_TIP_MUSTERI = 'MUSTERI'
CARI_TIP_TEDARIKCI = 'TEDARIKCI'
CARI_TIP_HER_IKISI = 'HER_IKISI'
CARI_TIPLER: tuple[str, ...] = (CARI_TIP_MUSTERI, CARI_TIP_TEDARIKCI, CARI_TIP_HER_IKISI)

ODEME_SEKLI_NAKIT = 'NAKIT'
ODEME_SEKLI_EFT = 'EFT'
ODEME_SEKLI_HAVALE = 'HAVALE'
ODEME_SEKLI_CEK = 'CEK'
ODEME_SEKLI_KART = 'KART'
ODEME_SEKLI_MAHSUP = 'MAHSUP'

# --- Open item ---
OI_YON_BORC = 'BORC'
OI_YON_ALACAK = 'ALACAK'
OI_YONLAR: tuple[str, ...] = (OI_YON_BORC, OI_YON_ALACAK)

OI_DURUM_ACIK = 'ACIK'
OI_DURUM_KISMI_KAPALI = 'KISMI_KAPALI'
OI_DURUM_KAPALI = 'KAPALI'
OI_DURUM_UYUSMAZLIK = 'UYUSMAZLIK'
OI_DURUM_IPTAL = 'IPTAL'
OI_DURUM_TERS_ACILDI = 'TERS_ACILDI'
OI_DURUMLAR: tuple[str, ...] = (
    OI_DURUM_ACIK,
    OI_DURUM_KISMI_KAPALI,
    OI_DURUM_KAPALI,
    OI_DURUM_UYUSMAZLIK,
    OI_DURUM_IPTAL,
    OI_DURUM_TERS_ACILDI,
)

# --- Hareket metadata ---
HAREKET_DURUM_AKTIF = 'AKTIF'
HAREKET_DURUM_IPTAL = 'IPTAL'
HAREKET_DURUM_TERS = 'TERS'

KAYNAK_SISTEM_NEXGEN = 'NEXGEN'
KAYNAK_SISTEM_LEGACY = 'LEGACY'
KAYNAK_SISTEM_IMPORT = 'IMPORT'

KAYNAK_ENTITY_BELGE = 'FINANS_BELGESI'
KAYNAK_ENTITY_LEGACY = 'LEGACY'

# --- Belge genişletme (F1 — mevcut finans_belgesi_config ile birlikte) ---
DURUM_IPTAL = 'IPTAL'

BELGE_TIP_SATINALMA_MAL_KABUL = 'SATINALMA_MAL_KABUL'
BELGE_TIP_SATINALMA_FATURA = 'SATINALMA_FATURA'
BELGE_TIP_TERS = 'TERS'
BELGE_TIP_DUZELTME = 'DUZELTME'
BELGE_TIP_MAHSUP = 'MAHSUP'

# --- Audit ---
AUDIT_ISLEM_OLUSTUR = 'OLUSTUR'
AUDIT_ISLEM_GUNCELLE = 'GUNCELLE'
AUDIT_ISLEM_DURUM_DEGIS = 'DURUM_DEGIS'
AUDIT_ISLEM_POST = 'POST'
AUDIT_ISLEM_IPTAL = 'IPTAL'
AUDIT_ISLEM_TERS = 'TERS'

AUDIT_ENTITY_CARI_KART = 'FINANS_CARI_KART'
AUDIT_ENTITY_BELGE = 'FINANS_BELGESI'
AUDIT_ENTITY_HAREKET = 'FINANS_HAREKET'
AUDIT_ENTITY_OPEN_ITEM = 'FINANS_OPEN_ITEM'
AUDIT_ENTITY_CARI_BAGLANTI = 'FINANS_CARI_BAGLANTI'
AUDIT_ENTITY_CARI_GECIS = 'FINANS_CARI_GECIS'

# --- Geçiş audit işlem türleri (FAZ-GECIS) ---
AUDIT_GECIS_KART_OLUSTUR = 'FINANS_CARI_KART_GECIS_OLUSTUR'
AUDIT_GECIS_BAGLANTI_OLUSTUR = 'FINANS_CARI_BAGLANTI_GECIS_OLUSTUR'
AUDIT_GECIS_BAGLANTI_DUZELT = 'FINANS_CARI_BAGLANTI_DUZELT'
AUDIT_GECIS_KART_OTOMATIK = 'FINANS_CARI_KART_OTOMATIK_OLUSTUR'
AUDIT_GECIS_NOOP = 'FINANS_CARI_GECIS_NOOP'
AUDIT_GECIS_HATA = 'FINANS_CARI_GECIS_HATA'
AUDIT_GECIS_TEKNIK_ISTISNA = 'FINANS_CARI_TEKNIK_ISTISNA'

FAZ_GECIS_IDEM_PREFIX = 'FAZ-GECIS'

# --- Idempotency format ---
KAYNAK_SISTEM_PREFIX = 'NEXGEN'


def idempotency_belge(belge_tipi: str, kaynak_tur: str, kaynak_id: int, olay_versiyon: int | None = None) -> str:
    base = f'{KAYNAK_SISTEM_PREFIX}:{belge_tipi}:{kaynak_tur}:{int(kaynak_id)}'
    if olay_versiyon is not None:
        return f'{base}:v{int(olay_versiyon)}'
    return base


def idempotency_open_item(finans_belgesi_id: int, satir_no: int | None = None, taksit_no: int | None = None) -> str:
    if taksit_no is not None:
        return f'OI:BELGE:{int(finans_belgesi_id)}:TAKSIT:{int(taksit_no)}'
    if satir_no is not None:
        return f'OI:BELGE:{int(finans_belgesi_id)}:SATIR:{int(satir_no)}'
    return f'OI:BELGE:{int(finans_belgesi_id)}'


def idempotency_hareket_post(belge_idempotency_key: str) -> str:
    return f'POST:{belge_idempotency_key}'


def idempotency_gecis(kaynak_tipi: str, operasyonel_id: int, ckod: str) -> str:
    return f'{FAZ_GECIS_IDEM_PREFIX}:{kaynak_tipi}:{int(operasyonel_id)}:{ckod}'


def idempotency_posting_event(
    kaynak_sistem: str,
    kaynak_tur: str,
    kaynak_id: int,
    olay_turu: str,
    olay_versiyon: int | None = None,
) -> str:
    base = f'{kaynak_sistem}:{kaynak_tur}:{int(kaynak_id)}:{olay_turu}'
    if olay_versiyon is not None:
        return f'{base}:v{int(olay_versiyon)}'
    return base
