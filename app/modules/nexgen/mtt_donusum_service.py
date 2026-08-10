# -*- coding: utf-8 -*-
"""
MTT F5 — Sipariş / Numune dönüşüm köprüsü.

Paralel insert YOK. Mevcut pzm_v2_taslak_kaydet / kaydet_taslak kullanılır.
hazirla endpoint'leri salt okunur.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from modules.nexgen.musteri_temsilcisi_talep_service import (
    DONUSUM_DURUMLARI,
    KISMI_NUMUNE_DURUM,
    MAX_KALEMLER,
    NUMUNE_DONUSUM_ACIK_DURUMLAR,
    TABLO,
    TABLO_KALEM,
    MusteriTemsilcisiTalepError,
    can_mtt_isleme_aksiyon,
    kalem_donusum_ozeti,
    talep_detay_getir,
)

TABLO_IDEM = 'nexgen_mtt_numune_donusum_idem'
from modules.nexgen.numune_talep_service import NumuneTalepError, kaydet_taslak
from modules.nexgen.pzm_siparis_write import PzmWriteError, pzm_v2_taslak_kaydet

logger = logging.getLogger(__name__)

MSG_ADAY_SIPARIS = (
    'Bu firma henüz aday müşteridir. Sipariş açmadan önce cariye dönüştürülmelidir.'
)

def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _bekleme_metni(baslangic: str | None) -> str | None:
    if not baslangic:
        return None
    try:
        s = str(baslangic).strip()[:19]
        dt = None
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            return None
        sec = max(0, int((datetime.now() - dt).total_seconds()))
        if sec < 60:
            return f'{sec} sn'
        if sec < 3600:
            return f'{sec // 60} dk'
        if sec < 86400:
            return f'{sec // 3600} saat'
        return f'{sec // 86400} gün'
    except Exception:
        return None


AILE_ETIKET = {
    'TERLIK': 'Terlik',
    'TERLİK': 'Terlik',
    'TABAN': 'Taban',
    'DOKME': 'Dökme',
    'DÖKME': 'Dökme',
}


def urun_ailesi_etiket(aile: str | None) -> str | None:
    if not aile:
        return None
    key = str(aile).strip().upper()
    return AILE_ETIKET.get(key) or AILE_ETIKET.get(key.replace('İ', 'I')) or str(aile).strip()


def miktar_gosterim(kalem: dict | None) -> str:
    """kg / tonaj gösterimi — boşsa —."""
    if not kalem:
        return '—'
    kg = kalem.get('miktar_kg')
    ton = kalem.get('konusulan_tonaj')
    parts = []
    try:
        if ton not in (None, ''):
            t = float(ton)
            if t != 0:
                if abs(t - int(t)) < 1e-9:
                    parts.append(f'{int(t)} ton')
                else:
                    parts.append(f"{str(t).rstrip('0').rstrip('.').replace('.', ',')} ton")
    except (TypeError, ValueError):
        pass
    try:
        if kg not in (None, ''):
            k = float(kg)
            if k != 0:
                if abs(k - int(k)) < 1e-9:
                    parts.append(f'{int(k):,}'.replace(',', '.') + ' kg')
                else:
                    parts.append(f'{k:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.') + ' kg')
    except (TypeError, ValueError):
        pass
    return ' · '.join(parts) if parts else '—'


def istenen_urun_ozet(kalemler: list[dict] | None) -> str | None:
    if not kalemler:
        return None
    k0 = kalemler[0]
    aile = urun_ailesi_etiket(k0.get('urun_ailesi'))
    urun = (k0.get('urun_aciklama') or '').strip() or '—'
    renk = (k0.get('renk_gosterim') or k0.get('renk_aciklama') or '').strip()
    mik = miktar_gosterim(k0)
    parts = [p for p in (aile, urun, renk if renk else None, mik if mik != '—' else None) if p]
    ilk = ' · '.join(parts) if parts else urun
    n = len(kalemler)
    if n <= 1:
        return ilk
    return f'{ilk} +{n - 1} kalem'


def bekleme_hesapla(talep: dict) -> str | None:
    durum = talep.get('durum')
    if durum == 'YENI':
        return _bekleme_metni(talep.get('created_at') or talep.get('olusturma_tarihi'))
    if durum in ('ISLEME_ALINDI', KISMI_NUMUNE_DURUM):
        return _bekleme_metni(talep.get('isleme_alinma_tarihi'))
    return None


def _admin_override(yk) -> bool:
    if not yk:
        return False
    return '*' in yk or can_mtt_isleme_aksiyon(yk)


def assert_donusum_izin(
    talep: dict,
    kullanici_id: int,
    hedef: str,
    yk=None,
) -> None:
    """hedef: SIPARIS | NUMUNE — NUMUNE kısmi (KISMEN) açık bırakır."""
    durum = talep.get('durum')
    tur = talep.get('talep_turu')
    if tur != hedef:
        raise MusteriTemsilcisiTalepError(
            f'Talep türü {tur}; {hedef} dönüşümü yapılamaz.', 409,
        )
    atanan = talep.get('atanan_kullanici_id')
    if atanan not in (None, '', 0) and int(atanan) != int(kullanici_id):
        if not _admin_override(yk):
            raise MusteriTemsilcisiTalepError(
                'Talep başka kullanıcıya atanmış; dönüştüremezsiniz.', 403,
                {'atanan_kullanici_id': atanan},
            )

    if hedef == 'SIPARIS':
        if durum in DONUSUM_DURUMLARI or talep.get('donusturulen_siparis_id'):
            raise MusteriTemsilcisiTalepError('Talep zaten dönüştürülmüş.', 409)
        if durum != 'ISLEME_ALINDI':
            raise MusteriTemsilcisiTalepError(
                f'Yalnız ISLEME_ALINDI talepler siparişe dönüştürülebilir (şu an: {durum}).', 409,
            )
        if talep.get('musteri_aday_id') and not talep.get('cari_id'):
            raise MusteriTemsilcisiTalepError(MSG_ADAY_SIPARIS, 409, {'kod': 'ADAY_SIPARIS'})
        if not talep.get('cari_id'):
            raise MusteriTemsilcisiTalepError('Sipariş dönüşümü için cari_id zorunlu.', 409)
        return

    # NUMUNE — kısmi dönüşüme izin
    if durum == 'NUMUNEYE_DONUSTU':
        raise MusteriTemsilcisiTalepError('Talep zaten numuneye dönüştürülmüş.', 409)
    if durum not in NUMUNE_DONUSUM_ACIK_DURUMLAR:
        raise MusteriTemsilcisiTalepError(
            f'Numune dönüşümü için ISLEME_ALINDI veya KISMEN_NUMUNEYE_DONUSTU gerekli '
            f'(şu an: {durum}).',
            409,
        )


import re


def _parse_mo_siparis_meta(aciklama: str | None, kisa_not: str | None = None) -> dict[str, Any]:
    """MO Sipariş Talebi popup meta — aciklama/kisa_not metninden (DB kolonu yok)."""
    ac = (aciklama or '').strip()
    kn = (kisa_not or '').strip()
    meta: dict[str, Any] = {}
    m = re.search(r'Termin:\s*(\d{4}-\d{2}-\d{2})', ac)
    if m:
        meta['istenen_termin'] = m.group(1)
    m = re.search(r'Teslim:\s*([^|]+)', ac)
    if m:
        lbl = m.group(1).strip()
        meta['teslim_sekli_etiket'] = lbl
        if 'Fabrika' in lbl:
            meta['teslim_sekli'] = 'FABRIKA_TESLIM'
        elif 'Sevk' in lbl or 'Müşteri' in lbl:
            meta['teslim_sekli'] = 'MUSTERIYE_SEVK'
    m = re.search(
        r'KDV:(GAYRI|RESMI)\|oran:(\d+)\|ara:([\d.]+)\|kdv:([\d.]+)\|genel:([\d.]+)(?:\|pb:(\w+))?',
        ac,
    )
    if m:
        meta['kdv_durumu'] = m.group(1)
        meta['kdv_orani'] = int(m.group(2))
        meta['ara_toplam'] = float(m.group(3))
        meta['kdv_tutari'] = float(m.group(4))
        meta['genel_toplam'] = float(m.group(5))
        if m.group(6):
            meta['para_birimi'] = m.group(6).upper()
    m = re.search(r'Çek alınacak:\s*(\d{4}-\d{2}-\d{2})', kn)
    if m:
        meta['cek_alinacak_tarih'] = m.group(1)
    return meta


def _mo_genel_not(talep: dict, snap: dict | None) -> str | None:
    mn = (talep.get('musteri_notu') or '').strip()
    if mn:
        return mn
    ac = (talep.get('aciklama') or '').strip()
    if not ac:
        return (snap or {}).get('kisa_not') or None
    if '|' in ac:
        return ac.split('|')[0].strip() or None
    return ac


def _oncelik_etiket(code: str | None) -> str:
    c = (code or 'NORMAL').upper()
    if c == 'ACIL':
        return 'Acil'
    if c == 'YUKSEK':
        return 'Kritik'
    return 'Normal'


def _odeme_etiket(code: str | None) -> str:
    c = (code or '').upper()
    if c in ('NAKIT', 'PESIN', 'PEŞİN'):
        return 'Nakit'
    if c == 'CEK':
        return 'Çek'
    if c == 'KREDI_KARTI':
        return 'Kredi Kartı'
    if c == 'VADELI':
        return 'Vadeli'
    return c or '—'


def _kalem_tutar(k: dict) -> float | None:
    try:
        kg = k.get('miktar_kg')
        f = k.get('verilen_fiyat')
        if kg in (None, '') or f in (None, ''):
            return None
        return round(float(kg) * float(f), 3)
    except (TypeError, ValueError):
        return None


def _siparis_eksik_alanlar(kalemler: list[dict], hydrate_kalemler: list[dict]) -> list[str]:
    eksik = []
    if not hydrate_kalemler:
        eksik.append('kalemler')
        return eksik
    for i, hk in enumerate(hydrate_kalemler):
        pref = f'kalem[{i + 1}]'
        if not hk.get('urun_ailesi'):
            eksik.append(f'{pref}.urun_ailesi')
        if not hk.get('formul_id'):
            eksik.append(f'{pref}.ana_formul')
        if not (hk.get('renk_varyant_id') or hk.get('rf_renk_id')):
            eksik.append(f'{pref}.renk')
        miktar = (hk.get('miktar_l') or 0) + (hk.get('miktar_s') or 0) + (hk.get('miktar_m') or 0)
        if not miktar:
            eksik.append(f'{pref}.miktar')
        if not hk.get('termin_tarihi'):
            eksik.append(f'{pref}.termin')
    return eksik


def _numune_eksik_alanlar(payload: dict) -> list[str]:
    eksik = []
    if not payload.get('urun_tipi'):
        eksik.append('urun_tipi')
    if not payload.get('karsilama_yolu'):
        eksik.append('karsilama_yolu / numune_tipi')
    ky = (payload.get('karsilama_yolu') or '').upper()
    if ky == 'HAZIR_RENK' and not payload.get('rf_renk_id'):
        eksik.append('rf_renk_id')
    if ky in ('YENI_RENK', 'YENI_FORMUL') and not (payload.get('yeni_renk_aciklama') or '').strip():
        eksik.append('yeni_renk_aciklama')
    if not payload.get('hedef_tarih'):
        eksik.append('hedef_tarih / termin')
    return eksik


def siparis_hazirla(con, talep_id: int, kullanici_id: int, yk=None) -> dict[str, Any]:
    talep = talep_detay_getir(con, talep_id, kullanici_id=kullanici_id)
    # Read-only: izin kontrolü bilgilendirme amaçlı; aday ise hata
    try:
        assert_donusum_izin(talep, kullanici_id, 'SIPARIS', yk)
        donusum_izin = True
        izin_mesaj = None
    except MusteriTemsilcisiTalepError as e:
        donusum_izin = False
        izin_mesaj = e.mesaj

    kalemler = talep.get('kalemler') or []
    snap = talep.get('gorusme_snapshot') or {}
    mo_meta = _parse_mo_siparis_meta(
        talep.get('aciklama'),
        talep.get('gorusme_notu') or snap.get('kisa_not'),
    )
    cek_vade_gun = snap.get('cek_vade_gun')
    for k in kalemler:
        if k.get('cek_vade_gun') not in (None, ''):
            cek_vade_gun = k.get('cek_vade_gun')
            break
    mo_meta['cek_vade_gun'] = cek_vade_gun
    mo_meta['oncelik'] = talep.get('oncelik') or 'NORMAL'
    mo_meta['oncelik_etiket'] = _oncelik_etiket(mo_meta['oncelik'])
    if not mo_meta.get('para_birimi'):
        pb = talep.get('para_birimi') or snap.get('para_birimi')
        if pb:
            mo_meta['para_birimi'] = str(pb).strip().upper().replace('TL', 'TRY')
    hydrate_kalemler = []
    for i, k in enumerate(kalemler):
        kg = k.get('miktar_kg')
        ton = k.get('konusulan_tonaj')
        try:
            if kg in (None, '') and ton not in (None, ''):
                kg = float(ton) * 1000.0
            elif kg not in (None, ''):
                kg = float(kg)
            else:
                kg = None
        except (TypeError, ValueError):
            kg = None
        aile = (k.get('urun_ailesi') or '').strip().upper()
        if aile in ('TERLİK',):
            aile = 'TERLIK'
        if aile in ('DÖKME',):
            aile = 'DOKME'
        # PZM: DOKME → MEDIUM (miktar_m); TABAN/TERLIK → LARGE/SMALL (L/S).
        # Toplam kg varsa yanlış boyuta yazma: DOKME→m, TABAN/TERLIK→L önerisi.
        miktar_l = miktar_s = miktar_m = None
        if kg is not None:
            if aile == 'DOKME':
                miktar_m = kg
            else:
                miktar_l = kg
        notlar_parts = []
        if k.get('urun_aciklama'):
            notlar_parts.append(str(k['urun_aciklama']))
        renk_g = k.get('renk_gosterim') or k.get('renk_aciklama')
        if k.get('boyut'):
            notlar_parts.append('Boyut: ' + str(k['boyut']))
        if k.get('kalem_notu'):
            notlar_parts.append(str(k['kalem_notu']))
        # Teknik renk_id yalnız güvenilir sayısal RF ise; serbest metin otomatik eşleşmez.
        rf_safe = None
        raw_renk = k.get('renk_id') or k.get('rf_renk_id')
        try:
            if raw_renk not in (None, '', 0, '0'):
                rid = int(raw_renk)
                if rid > 0 and con.execute(
                    'SELECT 1 FROM nexgen_rf_renk WHERE id=? AND aktif=1', (rid,),
                ).fetchone():
                    rf_safe = rid
        except (TypeError, ValueError):
            rf_safe = None
        hydrate_kalemler.append({
            'sira_no': k.get('sira_no') or (i + 1),
            'mtt_kalem_id': k.get('id'),
            'urun_ailesi': aile or k.get('urun_ailesi'),
            'formul_id': None,  # Mehmet seçer
            'renk_varyant_id': rf_safe,
            'rf_renk_id': rf_safe,
            'renk_ad': None if rf_safe else None,
            'musteri_renk_aciklama': renk_g,
            'miktar_l': miktar_l,
            'miktar_s': miktar_s,
            'miktar_m': miktar_m,
            'termin_tarihi': None,
            'notlar': ' · '.join(notlar_parts) or None,
            'birim_fiyat': k.get('verilen_fiyat') if k.get('verilen_fiyat') is not None else talep.get('verilen_fiyat'),
            'iskonto_orani': 0,
            'fiyat_kilitli': k.get('verilen_fiyat') is not None or talep.get('verilen_fiyat') is not None,
            'snapshot': {
                'urun_aciklama': k.get('urun_aciklama'),
                'urun_ailesi': aile or k.get('urun_ailesi'),
                'renk_aciklama': renk_g or k.get('renk_aciklama'),
                'boyut': k.get('boyut'),
                'konusulan_tonaj': k.get('konusulan_tonaj'),
                'miktar_kg': k.get('miktar_kg') if k.get('miktar_kg') is not None else kg,
                'verilen_fiyat': k.get('verilen_fiyat'),
            },
        })

    genel_not_parts = []
    genel_kisa = _mo_genel_not(talep, snap)
    if genel_kisa:
        genel_not_parts.append(genel_kisa)
    mehmet_not = (talep.get('mehmet_notu') or snap.get('mehmet_notu') or '').strip()
    if mehmet_not:
        genel_not_parts.append('Not: ' + mehmet_not)

    para = mo_meta.get('para_birimi') or talep.get('para_birimi') or snap.get('para_birimi')
    if para:
        para = str(para).strip().upper()
        if para == 'TL':
            para = 'TRY'

    odeme = talep.get('odeme_tipi') or snap.get('odeme_tipi')
    hydrate = {
        'kaynak_mtt_talep_id': int(talep['id']),
        'mo_gorusme_id': talep.get('gorusme_id'),
        'kaynak_modul': 'MUSTERI_TEMSILCISI_TALEP',
        'cari_id': talep.get('cari_id'),
        'firma_adi': talep.get('firma_adi'),
        'odeme_tipi': odeme,
        'odeme_etiket': _odeme_etiket(odeme),
        'vade_gun': talep.get('vade_gun') if talep.get('vade_gun') is not None else snap.get('vade_gun'),
        'anlasma_para_birimi': para,
        'anlasma_birim_fiyat': None,
        'siparis_tarihi': date.today().isoformat(),
        'genel_not': ' · '.join(genel_not_parts) if genel_not_parts else '',
        'kalemler': hydrate_kalemler,
        'talep_id': None,
        'mo_meta': mo_meta,
        'istenen_termin': mo_meta.get('istenen_termin'),
        'teslim_sekli': mo_meta.get('teslim_sekli'),
        'teslim_sekli_etiket': mo_meta.get('teslim_sekli_etiket'),
        'siparis_onceligi': mo_meta.get('oncelik'),
        'siparis_onceligi_etiket': mo_meta.get('oncelik_etiket'),
        'kdv_durumu': mo_meta.get('kdv_durumu'),
        'kdv_orani': mo_meta.get('kdv_orani'),
        'ara_toplam': mo_meta.get('ara_toplam'),
        'kdv_tutari': mo_meta.get('kdv_tutari'),
        'genel_toplam': mo_meta.get('genel_toplam'),
        'cek_vade_gun': mo_meta.get('cek_vade_gun'),
        'cek_alinacak_tarih': mo_meta.get('cek_alinacak_tarih'),
    }

    eksik = _siparis_eksik_alanlar(kalemler, hydrate_kalemler)
    if not hydrate.get('cari_id'):
        eksik.insert(0, 'cari_id')

    return {
        'ok': True,
        'talep': {
            'id': talep['id'],
            'talep_no': talep.get('talep_no'),
            'talep_turu': talep.get('talep_turu'),
            'durum': talep.get('durum'),
            'aciklama': talep.get('aciklama'),
            'gorusme_id': talep.get('gorusme_id'),
            'firma_adi': talep.get('firma_adi'),
            'entity_type': talep.get('entity_type'),
            'pazarlamaci_adi': talep.get('pazarlamaci_adi'),
            'istenen_urun': istenen_urun_ozet(kalemler),
            'bekleme': bekleme_hesapla(talep),
        },
        'cari': {
            'cari_id': talep.get('cari_id'),
            'firma_adi': talep.get('firma_adi'),
            'entity_type': talep.get('entity_type'),
            'musteri_aday_id': talep.get('musteri_aday_id'),
        },
        'ticari_snapshot': {
            'odeme_tipi': hydrate.get('odeme_tipi'),
            'odeme_etiket': hydrate.get('odeme_etiket'),
            'vade_gun': hydrate.get('vade_gun'),
            'cek_vade_gun': mo_meta.get('cek_vade_gun'),
            'cek_alinacak_tarih': mo_meta.get('cek_alinacak_tarih'),
            'para_birimi': hydrate.get('anlasma_para_birimi'),
            'istenen_termin': mo_meta.get('istenen_termin'),
            'teslim_sekli': mo_meta.get('teslim_sekli'),
            'teslim_sekli_etiket': mo_meta.get('teslim_sekli_etiket'),
            'oncelik': mo_meta.get('oncelik'),
            'oncelik_etiket': mo_meta.get('oncelik_etiket'),
            'kdv_durumu': mo_meta.get('kdv_durumu'),
            'kdv_orani': mo_meta.get('kdv_orani'),
            'ara_toplam': mo_meta.get('ara_toplam'),
            'kdv_tutari': mo_meta.get('kdv_tutari'),
            'genel_toplam': mo_meta.get('genel_toplam'),
            'verilen_fiyat': (
                (hydrate_kalemler[0].get('birim_fiyat') if hydrate_kalemler else None)
                or talep.get('verilen_fiyat')
                or snap.get('verilen_fiyat')
            ),
            'konusulan_tonaj': talep.get('konusulan_tonaj') or snap.get('konusulan_tonaj'),
            'gorusme_notu': talep.get('gorusme_notu') or snap.get('kisa_not'),
        },
        'mo_meta': mo_meta,
        'kalemler': kalemler,
        'hydrate': hydrate,
        'eksik_zorunlu_alanlar': eksik,
        'kaynak': {
            'gorusme_id': talep.get('gorusme_id'),
            'mtt_talep_id': talep['id'],
            'mtt_talep_no': talep.get('talep_no'),
        },
        'donusum_izin': donusum_izin,
        'izin_mesaj': izin_mesaj,
        'aday_siparis_engel': bool(talep.get('aday_siparis_uyari')),
    }


def numune_hazirla(con, talep_id: int, kullanici_id: int, yk=None) -> dict[str, Any]:
    talep = talep_detay_getir(con, talep_id, kullanici_id=kullanici_id)
    try:
        assert_donusum_izin(talep, kullanici_id, 'NUMUNE', yk)
        donusum_izin = True
        izin_mesaj = None
    except MusteriTemsilcisiTalepError as e:
        donusum_izin = False
        izin_mesaj = e.mesaj

    kalemler = talep.get('kalemler') or []
    snap = talep.get('gorusme_snapshot') or {}
    entity = talep.get('entity_type')
    aday = entity == 'ADAY' or bool(talep.get('musteri_aday_id'))

    payloads = []
    for i, k in enumerate(kalemler):
        aciklama_parts = []
        if talep.get('gorusme_notu') or snap.get('kisa_not'):
            aciklama_parts.append(talep.get('gorusme_notu') or snap.get('kisa_not'))
        if talep.get('aciklama'):
            aciklama_parts.append(talep['aciklama'])
        if k.get('kalem_notu'):
            aciklama_parts.append(k['kalem_notu'])
        ref_fiyat = k.get('verilen_fiyat') or talep.get('verilen_fiyat')
        if ref_fiyat is not None:
            pb = k.get('para_birimi') or talep.get('para_birimi') or ''
            aciklama_parts.append(f'Referans fiyat: {ref_fiyat} {pb}'.strip())

        aile = (k.get('urun_ailesi') or '').strip().upper()
        if aile in ('TERLİK',):
            aile = 'TERLIK'
        if aile in ('DÖKME',):
            aile = 'DOKME'
        urun_tipi = aile if aile in ('TERLIK', 'TABAN', 'DOKME') else None
        renk_g = k.get('renk_gosterim') or k.get('renk_aciklama')
        if talep.get('musteri_notu'):
            aciklama_parts.insert(0, 'Amaç: ' + str(talep['musteri_notu']))
        p = {
            'musteri_tipi': 'ADAY' if aday else 'MEVCUT',
            'cari_id': None if aday else talep.get('cari_id'),
            'musteri_aday_id': talep.get('musteri_aday_id') if aday else None,
            'aday_firma_adi': talep.get('firma_adi') if aday else None,
            'talep_kaynagi': 'Ziyaret' if aday else None,
            'mo_gorusme_id': talep.get('gorusme_id'),
            'kaynak_modul': 'MUSTERI_TEMSILCISI_TALEP',
            'kaynak_mtt_talep_id': int(talep['id']),
            'urun_adi': (k.get('urun_aciklama') or '')[:200] or None,
            'urun_aciklama': k.get('urun_aciklama'),
            'yeni_renk_aciklama': renk_g,
            'aciklama': ' · '.join([str(x) for x in aciklama_parts if x]) or None,
            'urun_tipi': urun_tipi,  # MTT urun_ailesi → numune ürün tipi
            'karsilama_yolu': None,
            'rf_renk_id': k.get('renk_id'),
            'hedef_tarih': None,
            'oncelik': (talep.get('oncelik') or 'NORMAL'),
            'numune_adedi': k.get('miktar_kg'),
            'miktar_kg': k.get('miktar_kg'),
            'mtt_kalem_id': k.get('id'),
            'mtt_kalem_sira': k.get('sira_no') or (i + 1),
            'snapshot': {
                'urun_ailesi': aile or k.get('urun_ailesi'),
                'renk_aciklama': renk_g,
                'konusulan_tonaj': k.get('konusulan_tonaj') or talep.get('konusulan_tonaj'),
                'miktar_kg': k.get('miktar_kg'),
                'verilen_fiyat': ref_fiyat,
                'musteri_notu': talep.get('musteri_notu'),
                'pazarlamaci_adi': talep.get('pazarlamaci_adi'),
            },
        }
        payloads.append(p)

    if not payloads:
        # kalemsiz — tek boş hydrate
        payloads = [{
            'musteri_tipi': 'ADAY' if aday else 'MEVCUT',
            'cari_id': None if aday else talep.get('cari_id'),
            'musteri_aday_id': talep.get('musteri_aday_id') if aday else None,
            'aday_firma_adi': talep.get('firma_adi') if aday else None,
            'mo_gorusme_id': talep.get('gorusme_id'),
            'kaynak_modul': 'MUSTERI_TEMSILCISI_TALEP',
            'kaynak_mtt_talep_id': int(talep['id']),
            'aciklama': talep.get('aciklama') or talep.get('gorusme_notu'),
        }]

    eksikler = [_numune_eksik_alanlar(p) for p in payloads]
    ozet = kalem_donusum_ozeti(kalemler)
    secim_listesi = []
    bekleyen_payloads = []
    for i, k in enumerate(kalemler):
        dd = (k.get('donusturme_durumu') or 'BEKLIYOR').upper()
        secilebilir = dd == 'BEKLIYOR' and donusum_izin
        aile_lbl = urun_ailesi_etiket(k.get('urun_ailesi')) or '—'
        renk_lbl = (k.get('renk_gosterim') or k.get('renk_aciklama') or 'Belirtilmedi').strip()
        mik_lbl = miktar_gosterim(k)
        label_parts = [
            str(k.get('sira_no') or (i + 1)),
            aile_lbl,
            (k.get('urun_aciklama') or 'Kalem').strip(),
            renk_lbl,
        ]
        if mik_lbl != '—':
            label_parts.append(mik_lbl)
        secim_listesi.append({
            'id': k.get('id'),
            'sira_no': k.get('sira_no') or (i + 1),
            'label': ' · '.join(label_parts),
            'urun_aciklama': k.get('urun_aciklama'),
            'urun_ailesi': k.get('urun_ailesi'),
            'renk_aciklama': k.get('renk_aciklama') or k.get('renk_gosterim'),
            'miktar_kg': k.get('miktar_kg'),
            'donusturme_durumu': dd,
            'donusturme_durumu_etiket': k.get('donusturme_durumu_etiket') or dd,
            'donusturulen_numune_talep_id': k.get('donusturulen_numune_talep_id'),
            'numune_talep_kodu': k.get('numune_talep_kodu'),
            'secilebilir': secilebilir,
            'secili_varsayilan': False,  # F5B: otomatik seçim yok
            'disabled': not secilebilir,
        })
        if dd == 'BEKLIYOR' and i < len(payloads):
            bekleyen_payloads.append(payloads[i])

    bekleyen_n = ozet['bekleyen_kalem_sayisi']
    secim_gerekli = bekleyen_n > 1
    # Tek bekleyen kalem → doğrudan hydrate; çok → seçim zorunlu
    hydrate_list = bekleyen_payloads if bekleyen_payloads else payloads
    return {
        'ok': True,
        'talep': {
            'id': talep['id'],
            'talep_no': talep.get('talep_no'),
            'talep_turu': talep.get('talep_turu'),
            'durum': talep.get('durum'),
            'gorusme_id': talep.get('gorusme_id'),
            'firma_adi': talep.get('firma_adi'),
            'entity_type': entity,
            'istenen_urun': istenen_urun_ozet(kalemler),
            'bekleme': bekleme_hesapla(talep),
        },
        'kaynak_gorusme': snap,
        'cari_veya_aday': {
            'cari_id': talep.get('cari_id'),
            'musteri_aday_id': talep.get('musteri_aday_id'),
            'firma_adi': talep.get('firma_adi'),
            'entity_type': entity,
            'aday_desteklenir': True,
        },
        'kalemler': kalemler,
        'kalem_sayisi': len(kalemler),
        'kalem_donusum_ozet': ozet,
        'kalem_secim': secim_listesi,
        'secim_gerekli': secim_gerekli,
        'bekleyen_kalem_sayisi': bekleyen_n,
        'cok_kalem': len(kalemler) > 1,
        'cok_kalem_davranis': 'SECIMLI_KISMI',
        'hydrate': hydrate_list[0] if hydrate_list else None,
        'hydrate_payloads': hydrate_list,
        'teknik_eksik_alanlar': (
            _numune_eksik_alanlar(hydrate_list[0]) if hydrate_list else []
        ),
        'teknik_eksik_alanlar_kalemler': [_numune_eksik_alanlar(p) for p in hydrate_list],
        'donusum_izin': donusum_izin and bekleyen_n > 0,
        'izin_mesaj': (
            izin_mesaj if not donusum_izin
            else ('Bekleyen kalem yok.' if bekleyen_n <= 0 else None)
        ),
    }


def _mtt_lock_siparis(con, talep_id: int, siparis_id: int, now: str) -> None:
    cur = con.execute(
        f"""
        UPDATE {TABLO}
        SET durum='SIPARISE_DONUSTU',
            donusturulen_siparis_id=?,
            donusturulme_tarihi=?,
            updated_at=?
        WHERE id=?
          AND durum='ISLEME_ALINDI'
          AND donusturulen_siparis_id IS NULL
          AND donusturulen_numune_talep_id IS NULL
        """,
        (int(siparis_id), now, now, int(talep_id)),
    )
    if cur.rowcount != 1:
        raise MusteriTemsilcisiTalepError(
            'Dönüşüm kilidi alınamadı (talep durumu değişmiş veya zaten dönüşmüş).', 409,
        )


def _kalem_ids_key(ids: list[int]) -> str:
    return ','.join(str(i) for i in sorted(int(x) for x in ids))


def sync_mtt_numune_talep_durumu(con, talep_id: int, *, now: str | None = None) -> str:
    """Kalem pointer'larına göre başlık durumunu senkronize eder (merkezi helper)."""
    now = now or _now()
    rows = con.execute(
        f"""
        SELECT id, donusturme_durumu, donusturulen_numune_talep_id
        FROM {TABLO_KALEM}
        WHERE talep_id=?
        ORDER BY sira_no ASC, id ASC
        """,
        (int(talep_id),),
    ).fetchall()
    if not rows:
        return con.execute(
            f'SELECT durum FROM {TABLO} WHERE id=?', (int(talep_id),),
        ).fetchone()['durum']

    n_bek = 0
    n_don = 0
    n_ipt = 0
    first_nid = None
    for r in rows:
        dd = (r['donusturme_durumu'] or 'BEKLIYOR').upper()
        if dd == 'NUMUNEYE_DONUSTU':
            n_don += 1
            if first_nid is None and r['donusturulen_numune_talep_id']:
                first_nid = int(r['donusturulen_numune_talep_id'])
        elif dd == 'IPTAL':
            n_ipt += 1
        else:
            n_bek += 1

    if n_don == 0 and n_ipt == 0:
        hedef = 'ISLEME_ALINDI'
    elif n_bek > 0:
        hedef = KISMI_NUMUNE_DURUM
    else:
        hedef = 'NUMUNEYE_DONUSTU' if n_don > 0 else 'ISLEME_ALINDI'

    tarih_set = now if n_don > 0 else None
    cur = con.execute(
        f"""
        UPDATE {TABLO}
        SET durum=?,
            donusturulen_numune_talep_id=COALESCE(donusturulen_numune_talep_id, ?),
            donusturulme_tarihi=COALESCE(donusturulme_tarihi, ?),
            updated_at=?
        WHERE id=?
          AND talep_turu='NUMUNE'
          AND durum IN ('ISLEME_ALINDI', 'KISMEN_NUMUNEYE_DONUSTU')
        """,
        (hedef, first_nid, tarih_set, now, int(talep_id)),
    )
    if cur.rowcount != 1:
        # Zaten NUMUNEYE_DONUSTU olabilir (retry) — doğrula
        row = con.execute(
            f'SELECT durum FROM {TABLO} WHERE id=?', (int(talep_id),),
        ).fetchone()
        if not row or row['durum'] not in (hedef, 'NUMUNEYE_DONUSTU', KISMI_NUMUNE_DURUM):
            raise MusteriTemsilcisiTalepError(
                'Talep durum senkronu başarısız (kilidi alınamadı).', 409,
            )
        return row['durum']
    return hedef


def _kalem_pointer_bagla(con, kalem_id: int, talep_id: int, numune_id: int, now: str) -> None:
    cur = con.execute(
        f"""
        UPDATE {TABLO_KALEM}
        SET donusturulen_numune_talep_id=?,
            donusturulme_tarihi=?,
            donusturme_durumu='NUMUNEYE_DONUSTU'
        WHERE id=? AND talep_id=?
          AND COALESCE(donusturme_durumu, 'BEKLIYOR')='BEKLIYOR'
          AND donusturulen_numune_talep_id IS NULL
        """,
        (int(numune_id), now, int(kalem_id), int(talep_id)),
    )
    if cur.rowcount != 1:
        raise MusteriTemsilcisiTalepError(
            f'Kalem #{kalem_id} dönüşüm kilidi alınamadı (zaten dönüşmüş veya durum değişmiş).',
            409,
            {'kalem_id': kalem_id},
        )


def _norm_odeme_tipi(v) -> str | None:
    if v in (None, ''):
        return None
    s = str(v).strip().upper().replace('İ', 'I').replace('ı', 'I')
    if s in ('PESIN', 'PEŞIN', 'NAKIT'):
        return 'NAKIT'
    if s in ('VADELI', 'VADE'):
        return 'VADELI'
    if s == 'CEK':
        return 'CEK'
    return s


def _norm_para(v) -> str | None:
    if v in (None, ''):
        return None
    s = str(v).strip().upper()
    if s == 'TL':
        return 'TRY'
    return s


def _norm_aile(v) -> str | None:
    if v in (None, ''):
        return None
    s = str(v).strip().upper()
    if s in ('TERLİK',):
        return 'TERLIK'
    if s in ('DÖKME',):
        return 'DOKME'
    return s


def _float_eq(a, b, eps: float = 0.0001) -> bool:
    try:
        return abs(float(str(a).replace(',', '.')) - float(str(b).replace(',', '.'))) <= eps
    except (TypeError, ValueError):
        return False


def _assert_mtt_ticari_kilit(talep: dict, data: dict) -> dict:
    """
    Yönetim onaylı MTT ticari alanları — browser payload ile değiştirilemez.
    Kaynak MTT snapshot'ına zorla hizala; sapma → 409.
    """
    snap = talep.get('ticari_snapshot') or {}
    if not isinstance(snap, dict):
        snap = {}
    # talep_detay alanları + kalem/gorusme fallback
    src_cari = talep.get('cari_id')
    src_odeme = _norm_odeme_tipi(
        talep.get('odeme_tipi') or snap.get('odeme_tipi')
    )
    src_vade = talep.get('vade_gun')
    if src_vade is None:
        src_vade = snap.get('vade_gun')
    src_para = _norm_para(talep.get('para_birimi') or snap.get('para_birimi'))
    kals = talep.get('kalemler') or []
    if src_para is None and len(kals) == 1:
        src_para = _norm_para(kals[0].get('para_birimi'))
    if src_odeme is None and len(kals) == 1:
        src_odeme = _norm_odeme_tipi(kals[0].get('odeme_tipi'))
    if src_vade is None and len(kals) == 1:
        src_vade = kals[0].get('vade_gun')
    if src_odeme == 'NAKIT':
        src_vade = 0
    src_cek = (
        talep.get('cek_vadesi')
        or snap.get('cek_vadesi')
        or None
    )
    if src_cek not in (None, ''):
        src_cek = str(src_cek).strip()[:10]
    else:
        src_cek = None

    payload = dict(data or {})
    # cari
    try:
        in_cari = int(payload.get('cari_id') or 0)
    except (TypeError, ValueError):
        in_cari = 0
    if src_cari and in_cari and in_cari != int(src_cari):
        raise MusteriTemsilcisiTalepError(
            'Sipariş cari_id MTT kaynağı ile değiştirilemez.', 409,
            {'alan': 'cari_id'},
        )
    if src_cari:
        payload['cari_id'] = int(src_cari)

    # ödeme
    in_odeme = _norm_odeme_tipi(payload.get('odeme_tipi'))
    if src_odeme and in_odeme and in_odeme != src_odeme:
        raise MusteriTemsilcisiTalepError(
            'Ödeme tipi MTT onaylı değerden değiştirilemez.', 409,
            {'alan': 'odeme_tipi'},
        )
    if src_odeme:
        payload['odeme_tipi'] = src_odeme

    # vade
    try:
        in_vade = payload.get('vade_gun')
        in_vade = int(in_vade) if in_vade not in (None, '') else None
    except (TypeError, ValueError):
        in_vade = None
    try:
        src_vade_i = int(src_vade) if src_vade not in (None, '') else None
    except (TypeError, ValueError):
        src_vade_i = None
    if src_odeme != 'CEK':
        if src_vade_i is not None and in_vade is not None and in_vade != src_vade_i:
            raise MusteriTemsilcisiTalepError(
                'Vade MTT onaylı değerden değiştirilemez.', 409,
                {'alan': 'vade_gun'},
            )
        if src_vade_i is not None:
            payload['vade_gun'] = src_vade_i
    else:
        # CEK: vade_gun normalizasyonu pzm_write katmanında cek_vade_gun'dan yapılır.
        # Burada payload'a müdahale etme; cek_vade_gun payload'da kalır.
        pass

    # çek vadesi
    in_cek = payload.get('cek_vadesi')
    in_cek = str(in_cek).strip()[:10] if in_cek not in (None, '') else None
    if src_odeme == 'CEK' and src_cek and in_cek and in_cek != src_cek:
        raise MusteriTemsilcisiTalepError(
            'Çek vadesi MTT onaylı değerden değiştirilemez.', 409,
            {'alan': 'cek_vadesi'},
        )
    if src_odeme == 'CEK' and src_cek:
        payload['cek_vadesi'] = src_cek
    elif src_odeme != 'CEK':
        payload['cek_vadesi'] = None

    # para
    in_para = _norm_para(payload.get('anlasma_para_birimi') or payload.get('para_birimi'))
    if src_para and in_para and in_para != src_para:
        raise MusteriTemsilcisiTalepError(
            'Para birimi MTT onaylı değerden değiştirilemez.', 409,
            {'alan': 'anlasma_para_birimi'},
        )
    if src_para:
        payload['anlasma_para_birimi'] = src_para

    # Sipariş tarihi server kontrolünde (dönüşüm/kayıt günü)
    payload['siparis_tarihi'] = date.today().isoformat()

    # Kalem sayısı + aile + yönetim onaylı birim fiyat
    in_kals = payload.get('kalemler')
    if not isinstance(in_kals, list):
        in_kals = []
    if len(kals) and len(in_kals) != len(kals):
        raise MusteriTemsilcisiTalepError(
            'Sipariş kalem sayısı MTT kalemleriyle birebir aynı olmalı.', 409,
            {'alan': 'kalemler', 'beklenen': len(kals), 'gelen': len(in_kals)},
        )
    fixed_kals = []
    for i, sk in enumerate(kals):
        ik = dict(in_kals[i] if i < len(in_kals) else {})
        src_aile = _norm_aile(sk.get('urun_ailesi'))
        in_aile = _norm_aile(ik.get('urun_ailesi'))
        if src_aile and in_aile and in_aile != src_aile:
            raise MusteriTemsilcisiTalepError(
                f'Kalem {i + 1}: ürün ailesi MTT kaynağından değiştirilemez.', 409,
                {'alan': 'urun_ailesi', 'kalem': i + 1},
            )
        if src_aile:
            ik['urun_ailesi'] = src_aile
        src_kf = sk.get('verilen_fiyat')
        if src_kf is None and len(kals) == 1:
            src_kf = talep.get('verilen_fiyat') or snap.get('verilen_fiyat')
        if src_kf is not None:
            in_kf = ik.get('birim_fiyat')
            if in_kf not in (None, '') and not _float_eq(in_kf, src_kf):
                raise MusteriTemsilcisiTalepError(
                    f'Kalem {i + 1}: birim fiyat MTT onaylı değerden değiştirilemez.', 409,
                    {'alan': 'birim_fiyat', 'kalem': i + 1},
                )
            ik['birim_fiyat'] = float(str(src_kf).replace(',', '.'))
        # UX V2: termin Siparişler → Terminler alanında sonra tamamlanır
        if not ik.get('termin_tarihi'):
            ik['termin_tarihi'] = None
        fixed_kals.append(ik)
    if fixed_kals:
        payload['kalemler'] = fixed_kals

    # Genel termin: kullanıcıdan istenmez; en yakın kalem termininden türetilir
    termler = []
    for ik in payload.get('kalemler') or []:
        t = (ik.get('termin_tarihi') or '')[:10]
        if t:
            termler.append(t)
    if termler:
        payload['genel_termin_tarihi'] = min(termler)

    # Başlık fiyatı sipariş kaynağı değil — tek kalemde kalem fiyatına senkron (DB kolon)
    if len(fixed_kals) == 1 and fixed_kals[0].get('birim_fiyat') not in (None, ''):
        payload['anlasma_birim_fiyat'] = fixed_kals[0]['birim_fiyat']
    else:
        payload['anlasma_birim_fiyat'] = None

    # Genel not: teknik pointer temizle (DB kaynak alanları korunur)
    gn = payload.get('genel_not')
    if isinstance(gn, str) and '[MTT:' in gn:
        lines = [ln for ln in gn.splitlines() if '[MTT:' not in ln]
        payload['genel_not'] = '\n'.join(lines).strip() or None

    # kaynak pointer zorla
    payload['kaynak_mtt_talep_id'] = int(talep['id'])
    payload['mo_gorusme_id'] = talep.get('gorusme_id')
    payload['kaynak_modul'] = 'MUSTERI_TEMSILCISI_TALEP'
    if payload.get('mo_gorusme_id') in (None, '', 0, '0') and talep.get('gorusme_id'):
        payload['mo_gorusme_id'] = talep.get('gorusme_id')
    in_g = payload.get('mo_gorusme_id')
    if talep.get('gorusme_id') and in_g not in (None, '', 0, '0'):
        try:
            if int(in_g) != int(talep['gorusme_id']):
                raise MusteriTemsilcisiTalepError(
                    'Kaynak görüşme MTT ile değiştirilemez.', 409,
                    {'alan': 'mo_gorusme_id'},
                )
        except MusteriTemsilcisiTalepError:
            raise
        except Exception:
            pass
    return payload


def siparis_mtt_ile_kaydet(
    con, mtt_id: int, data: dict, kullanici_id: int, yk=None,
) -> dict[str, Any]:
    """Mevcut PZM taslak kaydı + MTT durum güncellemesi — tek TX."""
    talep = talep_detay_getir(con, mtt_id, kullanici_id=kullanici_id)

    # Dönüşmüş MTT yalnız kendi mevcut TASLAK siparişini güncelleyebilir.
    mevcut_siparis_id = talep.get('donusturulen_siparis_id')
    raw_siparis_id = data.get('talep_id')
    mevcut_guncelleme = False
    if talep.get('durum') == 'SIPARISE_DONUSTU' and talep.get('donusturulen_siparis_id'):
        try:
            mevcut_guncelleme = int(raw_siparis_id) == int(mevcut_siparis_id)
        except (TypeError, ValueError):
            mevcut_guncelleme = False
        if not mevcut_guncelleme:
            raise MusteriTemsilcisiTalepError(
                'Talep zaten siparişe dönüştürülmüş.',
                409,
                {
                    'donusturulen_siparis_id': int(mevcut_siparis_id),
                    'mtt_durum': 'SIPARISE_DONUSTU',
                },
            )

    if mevcut_guncelleme:
        atanan = talep.get('atanan_kullanici_id')
        if atanan not in (None, '', 0) and int(atanan) != int(kullanici_id):
            if not _admin_override(yk):
                raise MusteriTemsilcisiTalepError(
                    'Talep başka kullanıcıya atanmış; dönüştüremezsiniz.', 403,
                    {'atanan_kullanici_id': atanan},
                )
    else:
        assert_donusum_izin(talep, kullanici_id, 'SIPARIS', yk)

    payload = _assert_mtt_ticari_kilit(talep, data)
    payload['talep_id'] = int(mevcut_siparis_id) if mevcut_guncelleme else None
    if not payload.get('cari_id'):
        raise MusteriTemsilcisiTalepError(
            'Sipariş cari_id talepteki cari ile eşleşmeli.', 409,
        )

    con.execute('BEGIN IMMEDIATE')

    try:
        sonuc = pzm_v2_taslak_kaydet(con, payload, kullanici_id, commit=False)
        siparis_id = int(sonuc['talep_id'])
        if not mevcut_guncelleme:
            _mtt_lock_siparis(con, mtt_id, siparis_id, _now())
        con.commit()
    except MusteriTemsilcisiTalepError:
        try:
            con.rollback()
        except Exception:
            pass
        raise
    except PzmWriteError as e:
        try:
            con.rollback()
        except Exception:
            pass
        raise MusteriTemsilcisiTalepError(e.message, e.status)
    except Exception as e:
        try:
            con.rollback()
        except Exception:
            pass
        logger.exception('MTT sipariş dönüşümü tamamlanamadı')
        raise MusteriTemsilcisiTalepError('Sipariş dönüşümü tamamlanamadı.', 500)

    kayit = talep_detay_getir(con, mtt_id, kullanici_id=kullanici_id)
    sonuc['kaynak_mtt_talep_id'] = mtt_id
    sonuc['mtt_durum'] = 'SIPARISE_DONUSTU'
    sonuc['mtt'] = kayit
    return sonuc


def numune_mtt_ile_kaydet(
    con, mtt_id: int, data: dict, kullanici_id: int, yk=None,
) -> dict[str, Any]:
    """
    Seçimli kalem → mevcut kaydet_taslak + kalem pointer + durum sync — tek TX.

    data:
      - secilen_kalem_ids: [int, ...]  (zorunlu, en az 1)
      - kalem_payloads: [{..., mtt_kalem_id}, ...]  (secilen ile aynı uzunluk/set)
      - idempotency_key: opsiyonel; varsa aynı set retry / farklı set 409
      - tek kalem kısayol: tek payload + mtt_kalem_id veya tek bekleyen kalem
    """
    import json
    from modules.nexgen.numune_talep_service import get_talep

    talep = talep_detay_getir(con, mtt_id, kullanici_id=kullanici_id)
    kalemler = talep.get('kalemler') or []
    by_id = {int(k['id']): k for k in kalemler if k.get('id') is not None}

    # --- seçilen kalem id'lerini çöz ---
    raw_ids = data.get('secilen_kalem_ids')
    raw_list = data.get('kalem_payloads')
    payloads: list[dict]
    if raw_list is not None:
        if not isinstance(raw_list, list) or not raw_list:
            raise MusteriTemsilcisiTalepError('kalem_payloads boş olamaz.', 400)
        payloads = list(raw_list)
        if raw_ids is None:
            raw_ids = [p.get('mtt_kalem_id') for p in payloads]
    else:
        payloads = [data]
        if raw_ids is None:
            kid = data.get('mtt_kalem_id')
            if kid not in (None, '', 0, '0'):
                raw_ids = [kid]
            else:
                bekleyen = [
                    int(k['id']) for k in kalemler
                    if (k.get('donusturme_durumu') or 'BEKLIYOR') == 'BEKLIYOR'
                ]
                if len(bekleyen) == 1:
                    raw_ids = bekleyen
                elif len(bekleyen) == 0 and talep.get('durum') == 'NUMUNEYE_DONUSTU':
                    # tam tamamlanmış — idempotent header sonucu
                    nid = talep.get('donusturulen_numune_talep_id')
                    t = get_talep(con, int(nid)) if nid else None
                    return {
                        'ok': True,
                        'talep': t,
                        'numune_talepleri': [t] if t else [],
                        'idempotent': True,
                        'kaynak_mtt_talep_id': mtt_id,
                        'mtt_durum': 'NUMUNEYE_DONUSTU',
                        'mtt': talep,
                    }
                else:
                    raise MusteriTemsilcisiTalepError(
                        'En az bir kalem seçilmelidir (secilen_kalem_ids).',
                        400,
                        {'secim_gerekli': True, 'bekleyen': len(bekleyen)},
                    )

    try:
        secilen = [int(x) for x in (raw_ids or []) if x not in (None, '', 0, '0')]
    except (TypeError, ValueError):
        raise MusteriTemsilcisiTalepError('secilen_kalem_ids geçersiz.', 400)

    if not secilen:
        raise MusteriTemsilcisiTalepError('En az bir kalem seçilmelidir.', 400)
    if len(secilen) > MAX_KALEMLER:
        raise MusteriTemsilcisiTalepError(f'En fazla {MAX_KALEMLER} kalem seçilebilir.', 400)
    if len(set(secilen)) != len(secilen):
        raise MusteriTemsilcisiTalepError('Seçilen kalem id tekrar ediyor.', 400)

    secilen_key = _kalem_ids_key(secilen)
    idem = (data.get('idempotency_key') or data.get('mtt_donusum_idempotency_key') or '').strip()

    # Idempotency tablosu
    if idem:
        prev = con.execute(
            f'SELECT * FROM {TABLO_IDEM} WHERE idempotency_key=?', (idem,),
        ).fetchone()
        if prev:
            if int(prev['talep_id']) != int(mtt_id) or (prev['secilen_kalem_ids'] or '') != secilen_key:
                raise MusteriTemsilcisiTalepError(
                    'Aynı idempotency key farklı kalem seti ile kullanılamaz.',
                    409,
                    {'kod': 'IDEM_KALEM_CONFLICT'},
                )
            ids = json.loads(prev['numune_ids_json'] or '[]')
            talepler = [get_talep(con, int(i)) for i in ids]
            kayit = talep_detay_getir(con, mtt_id, kullanici_id=kullanici_id)
            return {
                'ok': True,
                'talep': talepler[0] if talepler else None,
                'numune_talepleri': talepler,
                'idempotent': True,
                'kaynak_mtt_talep_id': mtt_id,
                'mtt_durum': kayit.get('durum'),
                'mtt': kayit,
                'secilen_kalem_ids': secilen,
            }

    assert_donusum_izin(talep, kullanici_id, 'NUMUNE', yk)

    # Payload ↔ seçim eşlemesi
    if len(payloads) != len(secilen):
        raise MusteriTemsilcisiTalepError(
            f'Seçilen {len(secilen)} kalem için {len(secilen)} numune payload gerekli '
            f'(gelen: {len(payloads)}).',
            409,
        )

    # Her payload'a kalem id bağla; dönüşmüş kalem engeli
    paired: list[tuple[int, dict]] = []
    for i, kid in enumerate(secilen):
        if kid not in by_id:
            raise MusteriTemsilcisiTalepError(f'Kalem #{kid} bu talebe ait değil.', 409)
        krow = by_id[kid]
        dd = (krow.get('donusturme_durumu') or 'BEKLIYOR').upper()
        if dd == 'NUMUNEYE_DONUSTU' or krow.get('donusturulen_numune_talep_id'):
            raise MusteriTemsilcisiTalepError(
                f'Kalem #{kid} daha önce numuneye dönüştürülmüş; tekrar dönüştürülemez.',
                409,
                {'kalem_id': kid, 'numune_talep_id': krow.get('donusturulen_numune_talep_id')},
            )
        if dd == 'IPTAL':
            raise MusteriTemsilcisiTalepError(f'Kalem #{kid} iptal; dönüştürülemez.', 409)
        body = dict(payloads[i])
        p_kid = body.get('mtt_kalem_id')
        if p_kid not in (None, '', 0, '0') and int(p_kid) != kid:
            raise MusteriTemsilcisiTalepError(
                'kalem_payloads ile secilen_kalem_ids eşleşmiyor.', 409,
            )
        body['mtt_kalem_id'] = kid
        paired.append((kid, body))

    try:
        con.execute('BEGIN IMMEDIATE')
    except Exception:
        pass

    created = []
    now = _now()
    try:
        for kid, body in paired:
            body = dict(body)
            body['kaynak_mtt_talep_id'] = int(mtt_id)
            body['mo_gorusme_id'] = talep.get('gorusme_id')
            body['kaynak_modul'] = 'MUSTERI_TEMSILCISI_TALEP'
            if talep.get('musteri_aday_id') and not talep.get('cari_id'):
                body['musteri_tipi'] = 'ADAY'
                body['musteri_aday_id'] = talep.get('musteri_aday_id')
                body.setdefault('aday_firma_adi', talep.get('firma_adi'))
                body['cari_id'] = None
            else:
                body['musteri_tipi'] = 'MEVCUT'
                body['cari_id'] = talep.get('cari_id')
            out = kaydet_taslak(con, body, kullanici_id, None, commit=False)
            created.append(out)
            _kalem_pointer_bagla(con, kid, mtt_id, int(out['id']), now)

        mtt_durum = sync_mtt_numune_talep_durumu(con, mtt_id, now=now)
        numune_ids = [int(x['id']) for x in created]
        if idem:
            con.execute(
                f"""
                INSERT INTO {TABLO_IDEM}
                  (idempotency_key, talep_id, secilen_kalem_ids, primary_numune_id,
                   numune_ids_json, created_at)
                VALUES (?,?,?,?,?,?)
                """,
                (
                    idem, int(mtt_id), secilen_key, numune_ids[0],
                    json.dumps(numune_ids), now,
                ),
            )
        con.commit()
    except MusteriTemsilcisiTalepError:
        try:
            con.rollback()
        except Exception:
            pass
        raise
    except NumuneTalepError as e:
        try:
            con.rollback()
        except Exception:
            pass
        raise MusteriTemsilcisiTalepError(e.message, e.status)
    except Exception as e:
        try:
            con.rollback()
        except Exception:
            pass
        logger.exception('MTT numune dönüşümü tamamlanamadı')
        raise MusteriTemsilcisiTalepError('Numune dönüşümü tamamlanamadı.', 500)

    kayit = talep_detay_getir(con, mtt_id, kullanici_id=kullanici_id)
    return {
        'ok': True,
        'talep': created[0],
        'numune_talepleri': created,
        'kaynak_mtt_talep_id': mtt_id,
        'mtt_durum': mtt_durum,
        'mtt': kayit,
        'secilen_kalem_ids': secilen,
        'kalem_donusum_ozet': kayit.get('kalem_donusum_ozet'),
    }
