# -*- coding: utf-8 -*-
"""
Cari 360 yetki anayasası + pazarlamacı finans özeti sözleşmesi + silme kuralı.

FAZ-CARI-GOLDEN-MASTER-ESLESTIRME-F1B — henüz route/UI yok; servis katmanı kuralı.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

# --- Yetki kodları ---
YETKI_CARI360_VIEW = 'cari360.view'
YETKI_CARI360_VIEW_OWN = 'cari360.view_own'
YETKI_CARI360_FINANS_VIEW = 'cari360.finans.view'
YETKI_CARI360_FINANS_WRITE = 'cari360.finans.write'
YETKI_CARI360_CRM_WRITE = 'cari360.crm.write'
YETKI_CARI360_MAKINA_WRITE = 'cari360.makina.write'
YETKI_CARI360_MAPPING_MANAGE = 'cari360.mapping.manage'
YETKI_CARI360_SORUMLU_MANAGE = 'cari360.sorumlu.manage'
YETKI_FINANS_TAHSILAT_WRITE = 'finans.tahsilat.write'
YETKI_FINANS_CEK_WRITE = 'finans.cek.write'
YETKI_FINANS_ODEME_PLANI_WRITE = 'finans.odeme_plani.write'
YETKI_ONAY_MERKEZ_VIEW = 'onay.merkez.view'
YETKI_ONAY_MERKEZ_KARAR = 'onay.merkez.karar'

CARI360_YETKI_KODLARI: tuple[str, ...] = (
    YETKI_CARI360_VIEW,
    YETKI_CARI360_VIEW_OWN,
    YETKI_CARI360_FINANS_VIEW,
    YETKI_CARI360_FINANS_WRITE,
    YETKI_CARI360_CRM_WRITE,
    YETKI_CARI360_MAKINA_WRITE,
    YETKI_CARI360_MAPPING_MANAGE,
    YETKI_CARI360_SORUMLU_MANAGE,
    YETKI_FINANS_TAHSILAT_WRITE,
    YETKI_FINANS_CEK_WRITE,
    YETKI_FINANS_ODEME_PLANI_WRITE,
    YETKI_ONAY_MERKEZ_VIEW,
    YETKI_ONAY_MERKEZ_KARAR,
)

# --- Pazarlamacı finans özeti: görülebilir alanlar (F1B sözleşme, ekran yok) ---
PAZARLAMACI_FINANS_OZET_GORUNUR: tuple[str, ...] = (
    'acik_alacak_toplami',
    'vadesi_gecen_toplam',
    'en_yakin_tahsilat_tarihi',
    'alinmasi_gereken_cek_sayisi',
    'en_yakin_cek_alim_tarihi',
    'risk_durumu',          # NORMAL | UYARI | KRITIK | BLOKE
    'kullanilabilir_risk',
    'son_tahsilat_tarihi',
)

PAZARLAMACI_FINANS_OZET_GIZLI: tuple[str, ...] = (
    'sirket_toplam_kasa',
    'banka_hesap_bakiyeleri',
    'diger_musteri_finanslari',
    'muhasebe_fis_ayrintilari',
    'ic_finans_notlari',
    'maliyet_karlilik',
)

RISK_DURUMU_VALUES: tuple[str, ...] = ('NORMAL', 'UYARI', 'KRITIK', 'BLOKE')

PAZARLAMACI_FINANS_OZET_SOZLESMESI: dict[str, Any] = {
    'gorunur_alanlar': list(PAZARLAMACI_FINANS_OZET_GORUNUR),
    'gizli_alanlar': list(PAZARLAMACI_FINANS_OZET_GIZLI),
    'risk_durumu_degerleri': list(RISK_DURUMU_VALUES),
    'not': 'Pazarlamacı yalnız kendi carisi için özet görür; kasa/banka/fiş detayı yok.',
}


def _yk_has(yk: set[str] | frozenset[str], kod: str, action: str = 'can_view') -> bool:
    if '*' in yk:
        return True
    if f'{kod}:{action}' in yk:
        return True
    return kod in yk


def can_physical_delete(yk: set[str] | frozenset[str]) -> bool:
    """
    Cari 360 / Finans fiziksel silme — F1B kuralı.
    Muhasebeci, pazarlamacı ve normal admin UI'da kapalı.
    Yanlış kayıt: IPTAL/PASIF + audit (gelecek faz).
    """
    return False


def can_cari360_view_all(yk: set[str] | frozenset[str]) -> bool:
    return _yk_has(yk, YETKI_CARI360_VIEW, 'can_view')


def can_cari360_view_own(yk: set[str] | frozenset[str]) -> bool:
    return _yk_has(yk, YETKI_CARI360_VIEW_OWN, 'can_view')


def can_cari360_view(yk: set[str] | frozenset[str], *, own_scope: bool = False) -> bool:
    if can_cari360_view_all(yk):
        return True
    return own_scope and can_cari360_view_own(yk)


def can_cari360_finans_view(yk: set[str] | frozenset[str]) -> bool:
    return _yk_has(yk, YETKI_CARI360_FINANS_VIEW, 'can_view')


def can_cari360_dosya_ekrani(yk: set[str] | frozenset[str]) -> bool:
    """Cari 360 dijital dosya — pazarlamacı (view_own) erişemez."""
    if can_cari360_view_all(yk):
        return True
    if _yk_has(yk, 'nexgen.yonetim.manage', 'can_view'):
        return True
    if _yk_has(yk, YETKI_CARI360_SORUMLU_MANAGE, 'can_manage'):
        return True
    if can_cari360_finans_view(yk) and not can_cari360_view_own(yk):
        return True
    return False


def can_cari360_finans_write(yk: set[str] | frozenset[str]) -> bool:
    return (
        _yk_has(yk, YETKI_CARI360_FINANS_WRITE, 'can_create')
        or _yk_has(yk, YETKI_CARI360_FINANS_WRITE, 'can_update')
        or _yk_has(yk, YETKI_CARI360_FINANS_WRITE, 'can_manage')
    )


def can_cari360_crm_write(yk: set[str] | frozenset[str]) -> bool:
    return (
        _yk_has(yk, YETKI_CARI360_CRM_WRITE, 'can_create')
        or _yk_has(yk, YETKI_CARI360_CRM_WRITE, 'can_update')
    )


def can_cari360_mapping_manage(yk: set[str] | frozenset[str]) -> bool:
    return _yk_has(yk, YETKI_CARI360_MAPPING_MANAGE, 'can_manage')


def can_finans_tahsilat_write(yk: set[str] | frozenset[str]) -> bool:
    return _yk_has(yk, YETKI_FINANS_TAHSILAT_WRITE, 'can_create') or _yk_has(
        yk, YETKI_FINANS_TAHSILAT_WRITE, 'can_update'
    )


def can_onay_merkez_karar(yk: set[str] | frozenset[str]) -> bool:
    return (
        _yk_has(yk, YETKI_ONAY_MERKEZ_KARAR, 'can_approve')
        or _yk_has(yk, YETKI_ONAY_MERKEZ_KARAR, 'can_manage')
    )


def can_siparis_onaya_gonder(yk: set[str] | frozenset[str]) -> bool:
    """Pazarlamacı siparişi onaya gönderebilir (nexgen.plan.manage)."""
    return _yk_has(yk, 'nexgen.plan.manage', 'can_manage') or _yk_has(
        yk, 'nexgen.plan.manage', 'can_create'
    )


def can_musteri_pazarlama_menu(yk: set[str] | frozenset[str]) -> bool:
    """MÜŞTERİ OPERASYONU menüsü — pazarlamacı + yönetim."""
    return (
        can_cari360_view_own(yk)
        or can_cari360_view_all(yk)
        or _yk_has(yk, YETKI_CARI360_SORUMLU_MANAGE, 'can_manage')
    )


def is_pazarlamaci_home_user(yk: set[str] | frozenset[str]) -> bool:
    """Login varsayılan ekranı — yalnız kendi-carisi pazarlamacı (yönetim hariç)."""
    if '*' in yk:
        return False
    if can_cari360_view_all(yk):
        return False
    if _yk_has(yk, YETKI_CARI360_SORUMLU_MANAGE, 'can_manage'):
        return False
    return can_cari360_view_own(yk)


def filter_pazarlamaci_finans_ozet(data: Mapping[str, Any]) -> dict[str, Any]:
    """Tam finans objesinden pazarlamacıya izin verilen alanları filtreler."""
    return {k: data[k] for k in PAZARLAMACI_FINANS_OZET_GORUNUR if k in data}


def finans_iptal_kurali() -> dict[str, Any]:
    """Fiziksel silme yerine iptal/pasif kuralı (ekran bu fazda yok)."""
    return {
        'fiziksel_silme': False,
        'yontem': 'IPTAL_PASIF',
        'iptal_nedeni_zorunlu': True,
        'audit_zorunlu': True,
        'kullanici_tarih_zorunlu': True,
        'ters_hareket': 'ayri_kayit_gerekebilir',
    }
