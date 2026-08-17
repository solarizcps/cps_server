# -*- coding: utf-8 -*-
"""
Müşteri Temsilcisi Talebi — merkezi kuyruk servisi (omurga F1-F2).

Bu fazda:
- talep + kalem oluşturma / liste / detay
- durum geçişleri + isleme alma kilidi + idempotency
Yok:
- siparişe / numuneye gerçek dönüşüm
- UI
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from modules.nexgen.cari360_yetki import _yk_has, can_cari360_view_all
from modules.nexgen.mo_gorusme_service import can_mo_gorusme_yaz, can_mo_gorusme_yaz_aday

TABLO = 'nexgen_musteri_temsilcisi_talep'
TABLO_KALEM = 'nexgen_musteri_temsilcisi_talep_kalem'
GORUSME = 'musteri_operasyon_gorusme'

TALEP_TURLERI = frozenset({'SIPARIS', 'NUMUNE'})
ONCELIKLER = frozenset({'DUSUK', 'NORMAL', 'YUKSEK', 'ACIL'})
DURUMLAR = frozenset({
    'ONAY_BEKLIYOR',
    'YENI', 'ISLEME_ALINDI', 'EKSIK_BILGI',
    'SIPARISE_DONUSTU', 'NUMUNEYE_DONUSTU', 'KISMEN_NUMUNEYE_DONUSTU',
    'REDDEDILDI', 'IPTAL',
})
DONUSUM_DURUMLARI = frozenset({'SIPARISE_DONUSTU', 'NUMUNEYE_DONUSTU'})
# Tamamlanmış sayılmayan ara dönüşüm durumu (numune seçimli)
KISMI_NUMUNE_DURUM = 'KISMEN_NUMUNEYE_DONUSTU'
NUMUNE_DONUSUM_ACIK_DURUMLAR = frozenset({'ISLEME_ALINDI', KISMI_NUMUNE_DURUM})
# Mehmet kuyruğunda görünen aktif durumlar (onay bekleyen yok)
MEHMET_KUYRUK_DURUMLARI = frozenset({
    'YENI', 'ISLEME_ALINDI', 'KISMEN_NUMUNEYE_DONUSTU',
})

# Elle set edilemeyen hedef durumlar (dönüşüm servisi / sync helper)
ELLE_YASAK_HEDEFLER = frozenset(DONUSUM_DURUMLARI | {KISMI_NUMUNE_DURUM})

# F6: EKSIK_BILGI aktif geçişlerden çıkarıldı (legacy kayıtlar korunur).
# ONAY_BEKLIYOR → YENI / REDDEDILDI yalnız onay_service ile (doğrudan SQL).
GECISLER: dict[str, frozenset[str]] = {
    'ONAY_BEKLIYOR': frozenset({'IPTAL'}),
    'YENI': frozenset({'ISLEME_ALINDI', 'REDDEDILDI', 'IPTAL'}),
    'ISLEME_ALINDI': frozenset({'REDDEDILDI', 'IPTAL'}),
    'EKSIK_BILGI': frozenset({'IPTAL'}),  # legacy: yalnız iptal
    KISMI_NUMUNE_DURUM: frozenset({'IPTAL'}),
}

EKSIK_BILGI_DEVRE_DISI = (
    'Eksik bilgi akışı devre dışıdır. '
    'Talep oluşturulurken zorunlu alanlar tamamlanmalıdır.'
)

KALEM_DONUSUM_DURUMLARI = frozenset({'BEKLIYOR', 'NUMUNEYE_DONUSTU', 'IPTAL'})
KALEM_DONUSUM_ETIKET = {
    'BEKLIYOR': 'Bekliyor',
    'NUMUNEYE_DONUSTU': 'Dönüştü',
    'IPTAL': 'İptal',
}

MAX_TALEP_NO_RETRY = 8
MAX_KALEMLER = 20

DURUM_ETIKET = {
    'ONAY_BEKLIYOR': 'Onay Bekliyor',
    'YENI': 'Yeni',
    'ISLEME_ALINDI': 'İşleme Alındı',
    'EKSIK_BILGI': 'Eksik Bilgi',
    'SIPARISE_DONUSTU': 'Siparişe Dönüştü',
    'NUMUNEYE_DONUSTU': 'Numuneye Dönüştü',
    'KISMEN_NUMUNEYE_DONUSTU': 'Kısmen Numuneye Dönüştü',
    'REDDEDILDI': 'Reddedildi',
    'IPTAL': 'İptal',
}
TUR_ETIKET = {
    'SIPARIS': 'Sipariş Talebi',
    'NUMUNE': 'Numune Talebi',
}


class MusteriTemsilcisiTalepError(Exception):
    def __init__(self, mesaj: str, kod: int = 400, ekstra: dict | None = None):
        self.mesaj = mesaj
        self.kod = kod
        self.ekstra = ekstra or {}
        super().__init__(mesaj)


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _tablo_var(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _kolonlar(con, tablo: str) -> set[str]:
    if not _tablo_var(con, tablo):
        return set()
    return {c[1] for c in con.execute(f'PRAGMA table_info({tablo})').fetchall()}


def _parse_decimal(v, alan: str, *, allow_none: bool = True) -> float | None:
    if v is None or v == '':
        if allow_none:
            return None
        raise MusteriTemsilcisiTalepError(f'{alan} zorunlu.', 400)
    try:
        d = Decimal(str(v).replace(',', '.').strip())
    except (InvalidOperation, ValueError):
        raise MusteriTemsilcisiTalepError(f'{alan} geçersiz sayı.', 400)
    if d < 0:
        raise MusteriTemsilcisiTalepError(f'{alan} negatif olamaz.', 400)
    return float(d)


def _parse_nonneg_int(v, alan: str) -> int | None:
    if v is None or v == '':
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise MusteriTemsilcisiTalepError(f'{alan} geçersiz.', 400)
    if n < 0:
        raise MusteriTemsilcisiTalepError(f'{alan} negatif olamaz.', 400)
    return n


def _norm_xor(cari_id, musteri_aday_id) -> tuple[int | None, int | None]:
    c = int(cari_id) if cari_id not in (None, '', 0, '0') else None
    a = int(musteri_aday_id) if musteri_aday_id not in (None, '', 0, '0') else None
    if (c is None) == (a is None):
        raise MusteriTemsilcisiTalepError(
            'cari_id veya musteri_aday_id tam olarak biri zorunlu (XOR).', 400,
        )
    return c, a


def _assert_gecis(kaynak: str, hedef: str) -> None:
    if hedef in ELLE_YASAK_HEDEFLER:
        raise MusteriTemsilcisiTalepError(
            f'{hedef} yalnız dönüşüm servisi tarafından yazılabilir.', 409,
        )
    izinli = GECISLER.get(kaynak) or frozenset()
    if hedef not in izinli:
        raise MusteriTemsilcisiTalepError(
            f'Durum geçişi geçersiz: {kaynak} → {hedef}', 409,
        )


def _fp_num(v):
    if v is None or v == '':
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def _payload_fingerprint(payload: dict) -> str:
    """Idempotency conflict için normalize edilmiş imza."""
    kalemler = []
    for i, k in enumerate(payload.get('kalemler') or []):
        if not isinstance(k, dict):
            continue
        para = (k.get('para_birimi') or '').strip().upper() or None
        if para == 'TL':
            para = 'TRY'
        kalemler.append({
            'sira_no': int(k.get('sira_no') or i + 1),
            'urun_aciklama': (k.get('urun_aciklama') or '').strip(),
            'urun_ailesi': (k.get('urun_ailesi') or '').strip() or None,
            'miktar_kg': _fp_num(k.get('miktar_kg')),
            'konusulan_tonaj': _fp_num(k.get('konusulan_tonaj')),
            'verilen_fiyat': _fp_num(k.get('verilen_fiyat')),
            'para_birimi': para,
            'odeme_tipi': (k.get('odeme_tipi') or '').strip().upper() or None,
            'vade_gun': k.get('vade_gun') if k.get('vade_gun') is not None else None,
            'cek_vade_gun': k.get('cek_vade_gun') if k.get('cek_vade_gun') is not None else None,
            'kalem_notu': (k.get('kalem_notu') or '').strip() or None,
        })
    body = {
        'gorusme_id': int(payload['gorusme_id']) if payload.get('gorusme_id') is not None else None,
        'talep_turu': (payload.get('talep_turu') or '').strip().upper(),
        'cari_id': int(payload['cari_id']) if payload.get('cari_id') not in (None, '') else None,
        'musteri_aday_id': (
            int(payload['musteri_aday_id'])
            if payload.get('musteri_aday_id') not in (None, '') else None
        ),
        'oncelik': (payload.get('oncelik') or 'NORMAL').strip().upper(),
        'aciklama': (payload.get('aciklama') or '').strip() or None,
        'musteri_notu': (payload.get('musteri_notu') or '').strip() or None,
        'kalemler': kalemler,
    }
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _uret_talep_no(con: sqlite3.Connection) -> str:
    """MTT-YYYY-NNNN — MAX sıra + UNIQUE retry ile transaction-safe."""
    yil = datetime.now().year
    prefix = f'MTT-{yil}-'
    row = con.execute(
        "SELECT MAX(CAST(SUBSTR(talep_no, -4) AS INTEGER)) AS son "
        f"FROM {TABLO} WHERE talep_no LIKE ?",
        (prefix + '%',),
    ).fetchone()
    son = int(row['son'] or 0) if row and row['son'] is not None else 0
    return f'{prefix}{son + 1:04d}'


def gorusme_satiri_getir(con, gorusme_id: int) -> sqlite3.Row:
    if not _tablo_var(con, GORUSME):
        raise MusteriTemsilcisiTalepError('Görüşme tablosu yok.', 500)
    row = con.execute(
        f'SELECT * FROM {GORUSME} WHERE id=? AND COALESCE(aktif,1)=1',
        (int(gorusme_id),),
    ).fetchone()
    if not row:
        raise MusteriTemsilcisiTalepError('Görüşme bulunamadı.', 404)
    return row


def _gorusme_snapshot(g: sqlite3.Row | dict) -> dict[str, Any]:
    def _v(key, default=None):
        try:
            return g[key]
        except (KeyError, IndexError, TypeError):
            return default

    fv = _v('fiyat_verildi')
    try:
        fv_int = int(fv) if fv not in (None, '') else 0
    except (TypeError, ValueError):
        fv_int = 1 if fv else 0

    return {
        'gorusme_id': int(_v('id')) if _v('id') not in (None, '') else None,
        'cari_id': _v('cari_id'),
        'musteri_aday_id': _v('musteri_aday_id'),
        'kisa_not': (_v('kisa_not') or '') or None,
        'gorusme_tarihi': _v('gorusme_tarihi'),
        'pazarlamaci_kullanici_id': _v('kullanici_id'),
        'fiyat_verildi': fv_int,
        'verilen_fiyat': _v('verilen_fiyat'),
        'para_birimi': (_v('fiyat_para_birimi') or _v('para_birimi') or None),
        'fiyat_birimi': (_v('fiyat_birimi') or 'KG'),
        'konusulan_tonaj': _v('konusulan_tonaj'),
        'odeme_tipi': _v('odeme_tipi'),
        'vade_gun': _v('vade_gun'),
        'cek_vade_gun': _v('cek_vade_gun'),
        'cek_notu': _v('cek_notu'),
        'fiyat_odeme_notu': _v('fiyat_odeme_notu'),
    }


def _snap_from_gorusme_payload(g_payload: dict) -> dict[str, Any]:
    """Görüşme henüz yazılmadan F6 doğrulama için geçici snapshot."""
    fv = g_payload.get('fiyat_verildi')
    try:
        fv_int = int(fv) if fv not in (None, '') else 0
    except (TypeError, ValueError):
        fv_int = 1 if fv else 0
    para = g_payload.get('fiyat_para_birimi') or g_payload.get('para_birimi')
    if para:
        para = str(para).strip().upper()
        if para == 'TL':
            para = 'TRY'
    odeme = (g_payload.get('odeme_tipi') or '').strip().upper() or None
    if odeme in ('VADELİ', 'VADELİ'):
        odeme = 'VADELI'
    return {
        'fiyat_verildi': fv_int,
        'verilen_fiyat': g_payload.get('verilen_fiyat'),
        'para_birimi': para,
        'konusulan_tonaj': g_payload.get('konusulan_tonaj'),
        'odeme_tipi': odeme,
        'vade_gun': g_payload.get('vade_gun'),
        'cek_vade_gun': g_payload.get('cek_vade_gun'),
        'kisa_not': (g_payload.get('kisa_not') or '').strip() or None,
    }


def _raise_alan_hatalari(hatalar: list[dict]) -> None:
    if not hatalar:
        return
    mesajlar = [h.get('mesaj') or '' for h in hatalar if h.get('mesaj')]
    raise MusteriTemsilcisiTalepError(
        mesajlar[0] if mesajlar else 'Talebi göndermek için zorunlu alanları tamamlayın.',
        422,
        {
            'alan_hatalari': hatalar,
            'mesaj': 'Talebi göndermek için zorunlu alanları tamamlayın.',
        },
    )


def _assert_mtt_zorunlu_alanlar(
    talep_turu: str,
    aciklama: str | None,
    musteri_notu: str | None,
    kalemler: list[dict],
    snap: dict,
) -> None:
    """F6 — SIPARIS/NUMUNE zorunlu + koşullu alanlar (snapshot sonrası)."""
    hatalar: list[dict] = []
    tur = (talep_turu or '').strip().upper()

    if not (aciklama or '').strip():
        hatalar.append({
            'alan': 'aciklama',
            'mesaj': 'Talep açıklaması / müşteri isteği zorunlu.',
        })

    if tur == 'NUMUNE':
        if not (musteri_notu or '').strip():
            hatalar.append({
                'alan': 'musteri_notu',
                'mesaj': 'Numune amacı / müşteri beklentisi zorunlu.',
            })

    fiyat_verildi = int(snap.get('fiyat_verildi') or 0)
    # Kalem + snap birleşik ticari (ilk dolu kazanır)
    def _ticari_pick(key):
        for k in kalemler:
            if k.get(key) not in (None, ''):
                return k.get(key)
        return snap.get(key)

    para = _ticari_pick('para_birimi')
    if para:
        para = str(para).strip().upper()
        if para == 'TL':
            para = 'TRY'
    odeme = _ticari_pick('odeme_tipi')
    if odeme:
        odeme = str(odeme).strip().upper()
        if odeme in ('VADELİ', 'VADELİ'):
            odeme = 'VADELI'
    fiyat = _ticari_pick('verilen_fiyat')
    vade = _ticari_pick('vade_gun')
    cek_vade = _ticari_pick('cek_vade_gun')

    if tur == 'SIPARIS':
        if not para:
            hatalar.append({'alan': 'para_birimi', 'mesaj': 'Para birimi zorunlu.'})
        if not odeme:
            hatalar.append({'alan': 'odeme_tipi', 'mesaj': 'Ödeme tipi zorunlu.'})
        if fiyat_verildi:
            if fiyat in (None, ''):
                hatalar.append({
                    'alan': 'verilen_fiyat',
                    'mesaj': 'Fiyat verildi — fiyat zorunlu.',
                })
            if not para:
                hatalar.append({
                    'alan': 'para_birimi',
                    'mesaj': 'Fiyat verildi — para birimi zorunlu.',
                })
        elif fiyat not in (None, '') and not para:
            hatalar.append({
                'alan': 'para_birimi',
                'mesaj': 'Fiyat var — para birimi zorunlu.',
            })

        if odeme == 'VADELI':
            try:
                vg = int(vade) if vade not in (None, '') else 0
            except (TypeError, ValueError):
                vg = 0
            if vg <= 0:
                hatalar.append({
                    'alan': 'vade_gun',
                    'mesaj': 'Vadeli ödeme için vade günü > 0 zorunlu.',
                })
        elif odeme == 'NAKIT':
            try:
                vg = int(vade) if vade not in (None, '') else 0
            except (TypeError, ValueError):
                vg = 0
            if vg > 0:
                hatalar.append({
                    'alan': 'vade_gun',
                    'mesaj': 'Nakit ödemede vade 0 olmalıdır.',
                })
        elif odeme == 'CEK':
            try:
                cv = int(cek_vade) if cek_vade not in (None, '') else 0
            except (TypeError, ValueError):
                cv = 0
            if cv <= 0:
                hatalar.append({
                    'alan': 'cek_vade_gun',
                    'mesaj': 'Çek konuşulduysa çek vadesi zorunlu.',
                })

    for i, k in enumerate(kalemler):
        sira = int(k.get('sira_no') or i + 1)
        prefix = f'{sira}. kalemde'

        if not (k.get('urun_aciklama') or '').strip():
            hatalar.append({
                'alan': f'kalem.{sira}.urun_aciklama',
                'kalem_sira': sira,
                'mesaj': f'{prefix} Ürün Açıklaması eksik.',
            })
        if not (k.get('urun_ailesi') or '').strip():
            hatalar.append({
                'alan': f'kalem.{sira}.urun_ailesi',
                'kalem_sira': sira,
                'mesaj': f'{prefix} Ürün Ailesi eksik.',
            })
        if not (k.get('renk_aciklama') or '').strip():
            hatalar.append({
                'alan': f'kalem.{sira}.renk_aciklama',
                'kalem_sira': sira,
                'mesaj': f'{prefix} Renk Açıklaması eksik.',
            })

        kg = k.get('miktar_kg')
        tonaj = k.get('konusulan_tonaj')
        if tur == 'SIPARIS':
            if kg in (None, '') and tonaj in (None, ''):
                hatalar.append({
                    'alan': f'kalem.{sira}.miktar',
                    'kalem_sira': sira,
                    'mesaj': f'{prefix} miktar kg veya konuşulan tonajdan en az biri zorunlu.',
                })
        elif tur == 'NUMUNE':
            if kg in (None, '') and tonaj in (None, ''):
                hatalar.append({
                    'alan': f'kalem.{sira}.miktar',
                    'kalem_sira': sira,
                    'mesaj': f'{prefix} tahmini miktar (kg) veya tonaj zorunlu.',
                })

    _raise_alan_hatalari(hatalar)


def _kalem_from_payload(raw: dict, sira: int, snap: dict) -> dict:
    # urun_aciklama boş olabilir — F6 _assert_mtt_zorunlu_alanlar 422 üretir
    aciklama = (raw.get('urun_aciklama') or '').strip()
    fiyat_birimi = (raw.get('fiyat_birimi') or 'KG').strip().upper()
    if fiyat_birimi != 'KG':
        raise MusteriTemsilcisiTalepError('fiyat_birimi yalnız KG olabilir.', 400)

    def _pick(key_payload, key_snap=None):
        if key_payload in raw and raw.get(key_payload) not in (None, ''):
            return raw.get(key_payload)
        return snap.get(key_snap or key_payload)

    para = _pick('para_birimi', 'para_birimi')
    if para is None or para == '':
        para = snap.get('para_birimi')
    if para:
        para = str(para).strip().upper()
        if para == 'TL':
            para = 'TRY'

    odeme = _pick('odeme_tipi')
    if odeme:
        odeme = str(odeme).strip().upper()

    return {
        'sira_no': int(raw.get('sira_no') or sira),
        'urun_ailesi': (raw.get('urun_ailesi') or '').strip() or None,
        'urun_aciklama': aciklama,
        'formul_id': int(raw['formul_id']) if raw.get('formul_id') not in (None, '') else None,
        'renk_id': int(raw['renk_id']) if raw.get('renk_id') not in (None, '') else None,
        'renk_aciklama': (raw.get('renk_aciklama') or '').strip() or None,
        'boyut': (raw.get('boyut') or '').strip() or None,
        'miktar_kg': _parse_decimal(raw.get('miktar_kg'), 'miktar_kg'),
        'konusulan_tonaj': _parse_decimal(
            _pick('konusulan_tonaj'), 'konusulan_tonaj',
        ),
        'verilen_fiyat': _parse_decimal(_pick('verilen_fiyat'), 'verilen_fiyat'),
        'para_birimi': para or None,
        'fiyat_birimi': 'KG',
        'odeme_tipi': odeme or None,
        'vade_gun': _parse_nonneg_int(_pick('vade_gun'), 'vade_gun'),
        'cek_vade_gun': _parse_nonneg_int(_pick('cek_vade_gun'), 'cek_vade_gun'),
        'kalem_notu': (raw.get('kalem_notu') or '').strip() or None,
    }


def talep_donusum_icin_uygun_mu(talep: dict | sqlite3.Row) -> dict[str, Any]:
    """Dönüşüm uygunluk helper — yazma yapmaz."""
    get = talep.__getitem__
    durum = get('durum')
    tur = get('talep_turu')
    hatalar = []
    if tur == 'SIPARIS':
        if durum != 'ISLEME_ALINDI':
            hatalar.append('Sipariş dönüşümü için ISLEME_ALINDI gerekli.')
        if not get('cari_id'):
            hatalar.append('Sipariş dönüşümü için cari_id zorunlu (aday dönüştürülemez).')
        if get('donusturulen_siparis_id'):
            hatalar.append('Talep zaten siparişe dönüştürülmüş.')
    elif tur == 'NUMUNE':
        if durum not in NUMUNE_DONUSUM_ACIK_DURUMLAR:
            hatalar.append('Numune dönüşümü için ISLEME_ALINDI veya KISMEN_NUMUNEYE_DONUSTU gerekli.')
        if durum == 'NUMUNEYE_DONUSTU':
            hatalar.append('Talep zaten numuneye dönüştürülmüş.')
    else:
        hatalar.append('Geçersiz talep türü.')
    return {
        'uygun': not hatalar,
        'hatalar': hatalar,
        'talep_turu': tur,
        'durum': durum,
    }


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    return {k: row[k] for k in row.keys()}


def _renk_gosterim(con, renk_id, renk_aciklama: str | None) -> str:
    """renk_id → Renk Merkezi / RF / varyant adı; yoksa renk_aciklama; yoksa Belirtilmedi."""
    if renk_id not in (None, '', 0):
        rid = int(renk_id)
        for sql in (
            "SELECT TRIM(COALESCE(rf_kod,'') || ' ' || COALESCE(ad,'')) AS ad FROM nexgen_rf_renk WHERE id=?",
            "SELECT ad FROM nexgen_renk_varyant WHERE id=?",
            "SELECT renk_adi AS ad FROM nexgen_renk_varyant WHERE id=?",
            "SELECT kod || ' ' || COALESCE(ad,'') AS ad FROM nexgen_renk_varyant WHERE id=?",
        ):
            try:
                row = con.execute(sql, (rid,)).fetchone()
                if row:
                    ad = (row['ad'] if hasattr(row, 'keys') else row[0]) or ''
                    ad = str(ad).strip()
                    if ad:
                        return ad
            except Exception:
                continue
    acik = (renk_aciklama or '').strip()
    return acik if acik else 'Belirtilmedi'


def _kalemleri_yukle(con, talep_id: int) -> list[dict]:
    rows = con.execute(
        f'SELECT * FROM {TABLO_KALEM} WHERE talep_id=? ORDER BY sira_no ASC, id ASC',
        (int(talep_id),),
    ).fetchall()
    out = [_row_to_dict(r) for r in rows]
    from modules.nexgen.mtt_donusum_service import (
        miktar_gosterim,
        urun_ailesi_etiket,
    )
    # F5B: numune kodu / etiket zenginleştirme
    for d in out:
        dd = (d.get('donusturme_durumu') or 'BEKLIYOR').strip().upper() or 'BEKLIYOR'
        d['donusturme_durumu'] = dd
        d['donusturme_durumu_etiket'] = KALEM_DONUSUM_ETIKET.get(dd, dd)
        d['donusturuldu_mu'] = dd == 'NUMUNEYE_DONUSTU'
        d['urun_ailesi_etiket'] = urun_ailesi_etiket(d.get('urun_ailesi'))
        d['renk_gosterim'] = _renk_gosterim(con, d.get('renk_id'), d.get('renk_aciklama'))
        d['miktar_gosterim'] = miktar_gosterim(d)
        # Teknik durum — formül/renk kaydı eksikse bekliyor
        teknik_eksik = []
        if not d.get('urun_ailesi'):
            teknik_eksik.append('aile')
        if not d.get('formul_id'):
            teknik_eksik.append('formül')
        if not d.get('renk_id'):
            teknik_eksik.append('renk kaydı')
        d['teknik_durum'] = (
            'Hazır' if not teknik_eksik else ('Teknik bilgi bekliyor: ' + ', '.join(teknik_eksik))
        )
        nid = d.get('donusturulen_numune_talep_id')
        d['numune_talep_kodu'] = None
        if nid not in (None, '', 0):
            try:
                nr = con.execute(
                    'SELECT talep_kodu, durum FROM nexgen_numune_talep WHERE id=?',
                    (int(nid),),
                ).fetchone()
                if nr:
                    d['numune_talep_kodu'] = nr['talep_kodu']
                    d['numune_talep_durum'] = nr['durum']
            except Exception:
                pass
    return out


def kalem_donusum_ozeti(kalemler: list[dict] | None) -> dict[str, Any]:
    ks = kalemler or []
    n = len(ks)
    n_don = sum(1 for k in ks if (k.get('donusturme_durumu') or '') == 'NUMUNEYE_DONUSTU')
    n_bek = sum(1 for k in ks if (k.get('donusturme_durumu') or 'BEKLIYOR') == 'BEKLIYOR')
    n_ipt = sum(1 for k in ks if (k.get('donusturme_durumu') or '') == 'IPTAL')
    ozet = None
    if n:
        ozet = f"{n} kalemin {n_don}'si numuneye dönüştürüldü."
    return {
        'kalem_sayisi': n,
        'donusen_kalem_sayisi': n_don,
        'bekleyen_kalem_sayisi': n_bek,
        'iptal_kalem_sayisi': n_ipt,
        'ozet': ozet,
    }


def _detay_paket(con, row) -> dict:
    d = _row_to_dict(row)
    d['kalemler'] = _kalemleri_yukle(con, int(d['id']))
    d['kalem_donusum_ozet'] = kalem_donusum_ozeti(d['kalemler'])
    d['donusum_uygunluk'] = talep_donusum_icin_uygun_mu(d)
    try:
        g = gorusme_satiri_getir(con, int(d['gorusme_id']))
        d['gorusme_snapshot'] = _gorusme_snapshot(g)
    except MusteriTemsilcisiTalepError:
        d['gorusme_snapshot'] = None
    return _enrich_talep(con, d)


def _mevcut_idempotent(con, idem: str) -> sqlite3.Row | None:
    return con.execute(
        f'SELECT * FROM {TABLO} WHERE idempotency_key=?', (idem,),
    ).fetchone()


def talep_olustur(
    con: sqlite3.Connection,
    payload: dict,
    olusturan_kullanici_id: int,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    if not _tablo_var(con, TABLO) or not _tablo_var(con, TABLO_KALEM):
        raise MusteriTemsilcisiTalepError('Talep tabloları yok — migration 146 gerekli.', 500)

    idem = (payload.get('idempotency_key') or '').strip()
    if not idem:
        raise MusteriTemsilcisiTalepError('idempotency_key zorunlu.', 400)

    gorusme_id = payload.get('gorusme_id')
    if not gorusme_id:
        raise MusteriTemsilcisiTalepError('gorusme_id zorunlu.', 400)
    g = gorusme_satiri_getir(con, int(gorusme_id))
    snap = _gorusme_snapshot(g)

    talep_turu = (payload.get('talep_turu') or '').strip().upper()
    if talep_turu not in TALEP_TURLERI:
        raise MusteriTemsilcisiTalepError('talep_turu SIPARIS veya NUMUNE olmalı.', 400)

    cari_id, aday_id = _norm_xor(payload.get('cari_id'), payload.get('musteri_aday_id'))
    g_cari = int(g['cari_id']) if g['cari_id'] not in (None, '') else None
    g_aday = int(g['musteri_aday_id']) if g['musteri_aday_id'] not in (None, '') else None
    if cari_id != g_cari or aday_id != g_aday:
        raise MusteriTemsilcisiTalepError(
            'Talep cari/aday bilgisi görüşme ile uyuşmuyor.', 400,
        )

    oncelik = (payload.get('oncelik') or 'NORMAL').strip().upper()
    if oncelik not in ONCELIKLER:
        raise MusteriTemsilcisiTalepError('Geçersiz öncelik.', 400)

    kalem_raw = payload.get('kalemler') or []
    if not isinstance(kalem_raw, list) or not kalem_raw:
        raise MusteriTemsilcisiTalepError('En az bir kalem zorunlu.', 400)
    if len(kalem_raw) > MAX_KALEMLER:
        raise MusteriTemsilcisiTalepError(
            f'En fazla {MAX_KALEMLER} kalem eklenebilir.', 400,
        )

    kalemler = [_kalem_from_payload(k if isinstance(k, dict) else {}, i + 1, snap)
                for i, k in enumerate(kalem_raw)]

    # F6: talep açıklaması açıkça zorunlu — görüşme notu ile sessiz doldurma yok
    aciklama = (payload.get('aciklama') or '').strip() or None
    musteri_notu = (payload.get('musteri_notu') or '').strip() or None

    _assert_mtt_zorunlu_alanlar(
        talep_turu, aciklama, musteri_notu, kalemler, snap,
    )

    # Snapshot sonrası normalize imza — idempotent karşılaştırma bununla yapılır
    fingerprint = _payload_fingerprint({
        'gorusme_id': int(gorusme_id),
        'talep_turu': talep_turu,
        'cari_id': cari_id,
        'musteri_aday_id': aday_id,
        'oncelik': oncelik,
        'aciklama': aciklama,
        'musteri_notu': musteri_notu,
        'kalemler': kalemler,
    })

    def _idem_conflict_or_ok(mevcut_row):
        detay = _detay_paket(con, mevcut_row)
        mevcut_fp = _payload_fingerprint({
            'gorusme_id': mevcut_row['gorusme_id'],
            'talep_turu': mevcut_row['talep_turu'],
            'cari_id': mevcut_row['cari_id'],
            'musteri_aday_id': mevcut_row['musteri_aday_id'],
            'oncelik': mevcut_row['oncelik'],
            'aciklama': mevcut_row['aciklama'],
            'musteri_notu': mevcut_row['musteri_notu'],
            'kalemler': detay['kalemler'],
        })
        if mevcut_fp != fingerprint:
            raise MusteriTemsilcisiTalepError(
                'idempotency_key aynı ama payload farklı.', 409,
                {'talep_id': int(mevcut_row['id']), 'talep_no': mevcut_row['talep_no']},
            )
        try:
            from modules.nexgen.onay_service import onay_by_kaynak
            onay = onay_by_kaynak(con, 'MUSTERI_TEMSILCISI_TALEP', int(mevcut_row['id']))
            if onay:
                detay['onay_id'] = int(onay['id'])
                detay['onay_no'] = onay.get('onay_no')
                detay['onay_durum'] = onay.get('durum')
                detay['onay_turu'] = onay.get('onay_turu')
        except Exception:
            pass
        return {'kayit': detay, 'idempotent': True}

    mevcut = _mevcut_idempotent(con, idem)
    if mevcut:
        return _idem_conflict_or_ok(mevcut)

    own_tx = False
    if commit:
        try:
            con.execute('BEGIN IMMEDIATE')
            own_tx = True
        except sqlite3.OperationalError:
            pass

    try:
        # Race: başka tx aynı idem yazmış olabilir
        mevcut2 = _mevcut_idempotent(con, idem)
        if mevcut2:
            out = _idem_conflict_or_ok(mevcut2)
            if own_tx:
                con.commit()
            return out

        now = _now()
        talep_id = None
        talep_no = None
        last_err = None
        for _ in range(MAX_TALEP_NO_RETRY):
            talep_no = _uret_talep_no(con)
            try:
                cur = con.execute(
                    f"""
                    INSERT INTO {TABLO} (
                        talep_no, talep_turu, durum, gorusme_id,
                        cari_id, musteri_aday_id,
                        olusturan_kullanici_id, atanan_kullanici_id, oncelik,
                        aciklama, musteri_notu, geri_gonderme_notu, red_nedeni,
                        idempotency_key,
                        donusturulen_siparis_id, donusturulen_numune_talep_id,
                        isleme_alinma_tarihi, donusturulme_tarihi,
                        created_at, updated_at
                    ) VALUES (
                        ?, ?, 'ONAY_BEKLIYOR', ?,
                        ?, ?,
                        ?, NULL, ?,
                        ?, ?, NULL, NULL,
                        ?,
                        NULL, NULL,
                        NULL, NULL,
                        ?, ?
                    )
                    """,
                    (
                        talep_no, talep_turu, int(gorusme_id),
                        cari_id, aday_id,
                        int(olusturan_kullanici_id), oncelik,
                        aciklama, musteri_notu,
                        idem,
                        now, now,
                    ),
                )
                talep_id = int(cur.lastrowid)
                break
            except sqlite3.IntegrityError as e:
                last_err = e
                msg = str(e).lower()
                if 'idempotency_key' in msg:
                    mevcut3 = _mevcut_idempotent(con, idem)
                    if mevcut3:
                        if own_tx:
                            con.commit()
                        return {'kayit': _detay_paket(con, mevcut3), 'idempotent': True}
                if 'talep_no' in msg or 'unique' in msg:
                    continue
                raise MusteriTemsilcisiTalepError(f'Talep kaydı çakıştı: {e}', 409)
        if talep_id is None:
            raise MusteriTemsilcisiTalepError(
                f'Talep numarası üretilemedi: {last_err}', 500,
            )

        for k in kalemler:
            con.execute(
                f"""
                INSERT INTO {TABLO_KALEM} (
                    talep_id, sira_no, urun_ailesi, urun_aciklama,
                    formul_id, renk_id, renk_aciklama, boyut,
                    miktar_kg, konusulan_tonaj, verilen_fiyat, para_birimi,
                    fiyat_birimi, odeme_tipi, vade_gun, cek_vade_gun,
                    kalem_notu, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    'KG', ?, ?, ?,
                    ?, ?, ?
                )
                """,
                (
                    talep_id, k['sira_no'], k['urun_ailesi'], k['urun_aciklama'],
                    k['formul_id'], k['renk_id'], k['renk_aciklama'], k['boyut'],
                    k['miktar_kg'], k['konusulan_tonaj'], k['verilen_fiyat'], k['para_birimi'],
                    k['odeme_tipi'], k['vade_gun'], k['cek_vade_gun'],
                    k['kalem_notu'], now, now,
                ),
            )

        # Onay Merkezi V1 — aynı TX içinde onay kaydı
        from modules.nexgen.onay_service import OnayError, onay_olustur_mtt
        try:
            onay_out = onay_olustur_mtt(
                con, talep_id, int(olusturan_kullanici_id), idem,
                aciklama=aciklama, talep_turu=talep_turu, commit=False,
            )
        except OnayError as e:
            raise MusteriTemsilcisiTalepError(e.mesaj, e.kod, e.ekstra) from e

        onay_kayit = (onay_out or {}).get('kayit') or {}
        if not onay_kayit.get('id'):
            raise MusteriTemsilcisiTalepError('Onay kaydı oluşmadı — işlem geri alındı.', 500)

        if own_tx:
            con.commit()
        row = con.execute(f'SELECT * FROM {TABLO} WHERE id=?', (talep_id,)).fetchone()
        paket = _detay_paket(con, row)
        paket['onay_id'] = int(onay_kayit['id'])
        paket['onay_no'] = onay_kayit.get('onay_no')
        paket['onay_durum'] = onay_kayit.get('durum')
        paket['onay_turu'] = onay_kayit.get('onay_turu')
        return {'kayit': paket, 'idempotent': False}
    except MusteriTemsilcisiTalepError:
        if own_tx:
            try:
                con.rollback()
            except Exception:
                pass
        raise
    except Exception:
        if own_tx:
            try:
                con.rollback()
            except Exception:
                pass
        raise


def talep_listele(
    con: sqlite3.Connection,
    *,
    durum: str | None = None,
    durumlar: list[str] | tuple[str, ...] | None = None,
    talep_turu: str | None = None,
    gorusme_id: int | None = None,
    cari_id: int | None = None,
    musteri_aday_id: int | None = None,
    olusturan_kullanici_id: int | None = None,
    atanan_kullanici_id: int | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
    enrich: bool = True,
) -> list[dict]:
    if not _tablo_var(con, TABLO):
        return []
    where = ['1=1']
    params: list[Any] = []
    if durumlar:
        ds = [d.strip().upper() for d in durumlar if (d or '').strip()]
        if ds:
            where.append(f"durum IN ({','.join('?' * len(ds))})")
            params.extend(ds)
    elif durum:
        where.append('durum=?')
        params.append(durum.strip().upper())
    if talep_turu:
        where.append('talep_turu=?')
        params.append(talep_turu.strip().upper())
    if gorusme_id:
        where.append('gorusme_id=?')
        params.append(int(gorusme_id))
    if cari_id:
        where.append('cari_id=?')
        params.append(int(cari_id))
    if musteri_aday_id:
        where.append('musteri_aday_id=?')
        params.append(int(musteri_aday_id))
    if olusturan_kullanici_id:
        where.append('olusturan_kullanici_id=?')
        params.append(int(olusturan_kullanici_id))
    if atanan_kullanici_id:
        where.append('atanan_kullanici_id=?')
        params.append(int(atanan_kullanici_id))
    qq = (q or '').strip()
    if qq:
        like = f'%{qq}%'
        where.append(
            '(talep_no LIKE ? OR aciklama LIKE ? OR musteri_notu LIKE ? '
            'OR CAST(id AS TEXT)=?)'
        )
        params.extend([like, like, like, qq])
    lim = max(1, min(int(limit or 100), 500))
    off = max(0, int(offset or 0))
    rows = con.execute(
        f"""
        SELECT * FROM {TABLO}
        WHERE {' AND '.join(where)}
        ORDER BY
          CASE durum
            WHEN 'YENI' THEN 0
            WHEN 'ISLEME_ALINDI' THEN 1
            WHEN 'EKSIK_BILGI' THEN 2
            ELSE 3
          END,
          created_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        (*params, lim, off),
    ).fetchall()
    out = [_row_to_dict(r) for r in rows]
    if enrich:
        out = [_enrich_talep(con, d) for d in out]
    return out


def talep_detay_getir(
    con: sqlite3.Connection,
    talep_id: int,
    *,
    kullanici_id: int | None = None,
) -> dict:
    if not _tablo_var(con, TABLO):
        raise MusteriTemsilcisiTalepError('Talep tabloları yok.', 500)
    row = con.execute(
        f'SELECT * FROM {TABLO} WHERE id=?', (int(talep_id),),
    ).fetchone()
    if not row:
        raise MusteriTemsilcisiTalepError('Talep bulunamadı.', 404)
    return _detay_paket(con, row)


def talep_sayaclari(con: sqlite3.Connection) -> dict[str, int]:
    out = {d: 0 for d in (
        'YENI', 'ISLEME_ALINDI', 'EKSIK_BILGI',
        'SIPARISE_DONUSTU', 'NUMUNEYE_DONUSTU', 'KISMEN_NUMUNEYE_DONUSTU',
        'REDDEDILDI', 'IPTAL', 'TOPLAM',
    )}
    if not _tablo_var(con, TABLO):
        return out
    rows = con.execute(
        f'SELECT durum, COUNT(*) AS n FROM {TABLO} GROUP BY durum'
    ).fetchall()
    toplam = 0
    for r in rows:
        d = r['durum']
        n = int(r['n'] or 0)
        if d in out:
            out[d] = n
        toplam += n
    out['TOPLAM'] = toplam
    return out


def _durum_guncelle(
    con,
    talep_id: int,
    hedef: str,
    *,
    ekstra_set: str = '',
    ekstra_params: tuple = (),
    where_extra: str = '',
    where_params: tuple = (),
    beklenen_durum: str | None = None,
) -> sqlite3.Row:
    row = con.execute(
        f'SELECT * FROM {TABLO} WHERE id=?', (int(talep_id),),
    ).fetchone()
    if not row:
        raise MusteriTemsilcisiTalepError('Talep bulunamadı.', 404)
    kaynak = row['durum']
    if beklenen_durum and kaynak != beklenen_durum:
        raise MusteriTemsilcisiTalepError(
            f'Talep durumu uygun değil (beklenen {beklenen_durum}, mevcut {kaynak}).', 409,
        )
    _assert_gecis(kaynak, hedef)
    now = _now()
    sql = (
        f"UPDATE {TABLO} SET durum=?, updated_at=?{ekstra_set} "
        f"WHERE id=? AND durum=?{where_extra}"
    )
    params = (hedef, now, *ekstra_params, int(talep_id), kaynak, *where_params)
    cur = con.execute(sql, params)
    if cur.rowcount != 1:
        raise MusteriTemsilcisiTalepError('Durum güncellemesi çakıştı.', 409)
    return con.execute(
        f'SELECT * FROM {TABLO} WHERE id=?', (int(talep_id),),
    ).fetchone()


def talep_isleme_al(
    con: sqlite3.Connection,
    talep_id: int,
    kullanici_id: int,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    """YENI → ISLEME_ALINDI; optimistic lock WHERE durum='YENI'."""
    if not _tablo_var(con, TABLO):
        raise MusteriTemsilcisiTalepError('Talep tabloları yok.', 500)

    own_tx = False
    if commit:
        try:
            con.execute('BEGIN IMMEDIATE')
            own_tx = True
        except sqlite3.OperationalError:
            pass

    try:
        row = con.execute(
            f'SELECT * FROM {TABLO} WHERE id=?', (int(talep_id),),
        ).fetchone()
        if not row:
            raise MusteriTemsilcisiTalepError('Talep bulunamadı.', 404)

        if row['durum'] == 'ISLEME_ALINDI' and int(row['atanan_kullanici_id'] or 0) == int(kullanici_id):
            if own_tx:
                con.commit()
            return {'kayit': _detay_paket(con, row), 'idempotent': True}

        if row['durum'] != 'YENI':
            raise MusteriTemsilcisiTalepError(
                f'Talep işleme alınamaz (durum={row["durum"]}).', 409,
                {'atanan_kullanici_id': row['atanan_kullanici_id']},
            )

        now = _now()
        cur = con.execute(
            f"""
            UPDATE {TABLO}
            SET durum='ISLEME_ALINDI',
                atanan_kullanici_id=?,
                isleme_alinma_tarihi=?,
                updated_at=?
            WHERE id=? AND durum='YENI'
            """,
            (int(kullanici_id), now, now, int(talep_id)),
        )
        if cur.rowcount != 1:
            again = con.execute(
                f'SELECT * FROM {TABLO} WHERE id=?', (int(talep_id),),
            ).fetchone()
            if (
                again
                and again['durum'] == 'ISLEME_ALINDI'
                and int(again['atanan_kullanici_id'] or 0) == int(kullanici_id)
            ):
                if own_tx:
                    con.commit()
                return {'kayit': _detay_paket(con, again), 'idempotent': True}
            raise MusteriTemsilcisiTalepError(
                'Talep başka kullanıcı tarafından işleme alındı.', 409,
                {'atanan_kullanici_id': again['atanan_kullanici_id'] if again else None},
            )

        if own_tx:
            con.commit()
        row2 = con.execute(
            f'SELECT * FROM {TABLO} WHERE id=?', (int(talep_id),),
        ).fetchone()
        return {'kayit': _detay_paket(con, row2), 'idempotent': False}
    except MusteriTemsilcisiTalepError:
        if own_tx:
            try:
                con.rollback()
            except Exception:
                pass
        raise
    except Exception:
        if own_tx:
            try:
                con.rollback()
            except Exception:
                pass
        raise


def talep_eksik_bilgiye_gonder(
    con: sqlite3.Connection,
    talep_id: int,
    kullanici_id: int,
    not_metni: str,
    *,
    commit: bool = True,
) -> dict:
    """F6: yeni talepler için devre dışı (410)."""
    raise MusteriTemsilcisiTalepError(EKSIK_BILGI_DEVRE_DISI, 410)


def talep_tekrar_gonder(
    con: sqlite3.Connection,
    talep_id: int,
    kullanici_id: int,
    *,
    commit: bool = True,
) -> dict:
    """F6: EKSIK_BILGI → YENI akışı devre dışı (410)."""
    raise MusteriTemsilcisiTalepError(EKSIK_BILGI_DEVRE_DISI, 410)


def talep_reddet(
    con: sqlite3.Connection,
    talep_id: int,
    kullanici_id: int,
    red_nedeni: str,
    *,
    commit: bool = True,
) -> dict:
    neden = (red_nedeni or '').strip()
    if not neden:
        raise MusteriTemsilcisiTalepError('red_nedeni zorunlu.', 400)

    own_tx = False
    if commit:
        try:
            con.execute('BEGIN IMMEDIATE')
            own_tx = True
        except sqlite3.OperationalError:
            pass
    try:
        row = con.execute(
            f'SELECT * FROM {TABLO} WHERE id=?', (int(talep_id),),
        ).fetchone()
        if not row:
            raise MusteriTemsilcisiTalepError('Talep bulunamadı.', 404)
        _assert_gecis(row['durum'], 'REDDEDILDI')
        now = _now()
        cur = con.execute(
            f"""
            UPDATE {TABLO}
            SET durum='REDDEDILDI', red_nedeni=?, updated_at=?
            WHERE id=? AND durum=?
            """,
            (neden, now, int(talep_id), row['durum']),
        )
        if cur.rowcount != 1:
            raise MusteriTemsilcisiTalepError('Red işlemi çakıştı.', 409)
        if own_tx:
            con.commit()
        row2 = con.execute(
            f'SELECT * FROM {TABLO} WHERE id=?', (int(talep_id),),
        ).fetchone()
        return {'kayit': _detay_paket(con, row2)}
    except MusteriTemsilcisiTalepError:
        if own_tx:
            try:
                con.rollback()
            except Exception:
                pass
        raise
    except Exception:
        if own_tx:
            try:
                con.rollback()
            except Exception:
                pass
        raise


def talep_iptal_et(
    con: sqlite3.Connection,
    talep_id: int,
    kullanici_id: int,
    *,
    commit: bool = True,
) -> dict:
    own_tx = False
    if commit:
        try:
            con.execute('BEGIN IMMEDIATE')
            own_tx = True
        except sqlite3.OperationalError:
            pass
    try:
        row = con.execute(
            f'SELECT * FROM {TABLO} WHERE id=?', (int(talep_id),),
        ).fetchone()
        if not row:
            raise MusteriTemsilcisiTalepError('Talep bulunamadı.', 404)
        _assert_gecis(row['durum'], 'IPTAL')
        now = _now()
        cur = con.execute(
            f"""
            UPDATE {TABLO}
            SET durum='IPTAL', updated_at=?
            WHERE id=? AND durum=?
            """,
            (now, int(talep_id), row['durum']),
        )
        if cur.rowcount != 1:
            raise MusteriTemsilcisiTalepError('İptal çakıştı.', 409)
        if own_tx:
            con.commit()
        row2 = con.execute(
            f'SELECT * FROM {TABLO} WHERE id=?', (int(talep_id),),
        ).fetchone()
        return {'kayit': _detay_paket(con, row2)}
    except MusteriTemsilcisiTalepError:
        if own_tx:
            try:
                con.rollback()
            except Exception:
                pass
        raise
    except Exception:
        if own_tx:
            try:
                con.rollback()
            except Exception:
                pass
        raise


def can_mtt_kuyruk_gor(yk: set[str] | frozenset[str]) -> bool:
    """Liste/detay: Mehmet (plan.manage) veya yönetim."""
    if '*' in yk:
        return True
    if can_cari360_view_all(yk):
        return True
    # F4: kuyruk PZM'de — plan.manage (Mehmet). MO menü açılmaz.
    return _yk_has(yk, 'nexgen.plan.manage', 'can_manage') or _yk_has(
        yk, 'nexgen.plan.manage', 'can_view',
    )


def can_mtt_isleme_aksiyon(yk: set[str] | frozenset[str]) -> bool:
    """İşleme Al / Reddet / dönüşüm — yalnız plan.manage (Mehmet)."""
    if '*' in yk:
        return True
    if can_cari360_view_all(yk):
        return True
    return _yk_has(yk, 'nexgen.plan.manage', 'can_manage')


def can_mtt_talep_olustur(
    con, kullanici_id: int, gorusme_row, yk: set[str] | frozenset[str] | None = None,
) -> bool:
    if gorusme_row['musteri_aday_id']:
        return can_mo_gorusme_yaz_aday(con, kullanici_id, int(gorusme_row['musteri_aday_id']), yk)
    if gorusme_row['cari_id']:
        return can_mo_gorusme_yaz(con, kullanici_id, int(gorusme_row['cari_id']), yk)
    return False


def kuyruk_sayaci(con: sqlite3.Connection) -> int:
    """Sekme rozeti: YENI + ISLEME_ALINDI + KISMEN_NUMUNEYE_DONUSTU."""
    sc = talep_sayaclari(con)
    return (
        int(sc.get('YENI') or 0)
        + int(sc.get('ISLEME_ALINDI') or 0)
        + int(sc.get('KISMEN_NUMUNEYE_DONUSTU') or 0)
    )


def _kullanici_adi(con, kid) -> str | None:
    if kid in (None, '', 0):
        return None
    try:
        row = con.execute(
            'SELECT AdSoyad, KullaniciAdi FROM sistem_kullanici WHERE Id=?',
            (int(kid),),
        ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    return (row['AdSoyad'] or row['KullaniciAdi'] or '').strip() or None


def _enrich_talep(con, d: dict) -> dict:
    """Liste/detay için firma, pazarlamacı, atanan, görüşme özeti."""
    cari_id = d.get('cari_id')
    aday_id = d.get('musteri_aday_id')
    firma = None
    entity = None
    if cari_id not in (None, '', 0):
        entity = 'CARI'
        row = con.execute(
            'SELECT unvan, cari_kod FROM nexgen_cari WHERE id=?',
            (int(cari_id),),
        ).fetchone()
        if row:
            firma = (row['unvan'] or row['cari_kod'] or '').strip() or None
    elif aday_id not in (None, '', 0):
        entity = 'ADAY'
        row = con.execute(
            'SELECT firma_adi FROM nexgen_musteri_aday WHERE id=?',
            (int(aday_id),),
        ).fetchone()
        if row:
            firma = (row['firma_adi'] or '').strip() or None
    d['entity_type'] = entity
    d['firma_adi'] = firma
    d['atanan_adi'] = _kullanici_adi(con, d.get('atanan_kullanici_id'))
    d['olusturan_adi'] = _kullanici_adi(con, d.get('olusturan_kullanici_id'))
    d['durum_etiket'] = DURUM_ETIKET.get(d.get('durum') or '', d.get('durum'))
    d['tur_etiket'] = TUR_ETIKET.get(d.get('talep_turu') or '', d.get('talep_turu'))

    snap = d.get('gorusme_snapshot')
    if snap is None and d.get('gorusme_id'):
        try:
            g = gorusme_satiri_getir(con, int(d['gorusme_id']))
            snap = _gorusme_snapshot(g)
            d['gorusme_snapshot'] = snap
        except MusteriTemsilcisiTalepError:
            snap = None
            d['gorusme_snapshot'] = None
    if snap:
        d['pazarlamaci_adi'] = _kullanici_adi(con, snap.get('pazarlamaci_kullanici_id'))
        d['gorusme_notu'] = snap.get('kisa_not')
        d['gorusme_tarihi'] = snap.get('gorusme_tarihi')
        d['verilen_fiyat'] = snap.get('verilen_fiyat')
        d['para_birimi'] = snap.get('para_birimi')
        d['konusulan_tonaj'] = snap.get('konusulan_tonaj')
        d['odeme_tipi'] = snap.get('odeme_tipi')
        d['vade_gun'] = snap.get('vade_gun')
        d['cek_vade_gun'] = snap.get('cek_vade_gun')
    else:
        d.setdefault('pazarlamaci_adi', None)
        d.setdefault('gorusme_notu', None)

    d['aday_siparis_uyari'] = (
        d.get('talep_turu') == 'SIPARIS' and entity == 'ADAY'
    )
    # MTT yaşam döngüsü: Erhan ekranı için kullanıcı dostu etiket
    # DURUM_ETIKET'ten farklı: YENI → "Mehmet'e Aktarıldı", ISLEME_ALINDI → "Mehmet İşleme Aldı"
    _MTT_ISLEM_LBL = {
        'ONAY_BEKLIYOR': 'Onay Bekliyor',
        'YENI': "Mehmet'e Aktarıldı",
        'ISLEME_ALINDI': 'Mehmet İşleme Aldı',
        'SIPARISE_DONUSTU': 'Siparişe Dönüştü',
        'NUMUNEYE_DONUSTU': 'Numuneye Dönüştü',
        'KISMEN_NUMUNEYE_DONUSTU': 'Kısmen Numuneye Dönüştü',
        'REDDEDILDI': 'Reddedildi',
        'IPTAL': 'İptal',
        'EKSIK_BILGI': 'Eksik Bilgi',
    }
    d['islem_durumu_etiket'] = _MTT_ISLEM_LBL.get(
        d.get('durum') or '', d.get('durum') or ''
    )
    d.setdefault('donusum_kodu', None)
    _sip_id = d.get('donusturulen_siparis_id')
    _num_id = d.get('donusturulen_numune_talep_id')
    if _sip_id and _tablo_var(con, 'nexgen_planlama_siparis'):
        try:
            _sr = con.execute(
                'SELECT siparis_no FROM nexgen_planlama_siparis WHERE id=?',
                (int(_sip_id),),
            ).fetchone()
            if _sr:
                d['donusum_kodu'] = _sr['siparis_no']
        except Exception:
            pass
    elif _num_id and _tablo_var(con, 'nexgen_numune_talep'):
        try:
            _nr = con.execute(
                'SELECT talep_kodu FROM nexgen_numune_talep WHERE id=?',
                (int(_num_id),),
            ).fetchone()
            if _nr:
                d['donusum_kodu'] = _nr['talep_kodu']
        except Exception:
            pass
    # Onay Merkezi özeti
    d.setdefault('onay_durum', None)
    d.setdefault('onay_no', None)
    d.setdefault('onay_durum_etiket', None)
    if d.get('id') and _tablo_var(con, 'nexgen_onay'):
        try:
            from modules.nexgen.onay_service import DURUM_ETIKET as ONAY_DURUM_ETIKET
            orow = con.execute(
                "SELECT onay_no, durum FROM nexgen_onay "
                "WHERE kaynak_turu='MUSTERI_TEMSILCISI_TALEP' AND kaynak_id=? "
                "ORDER BY id DESC LIMIT 1",
                (int(d['id']),),
            ).fetchone()
            if orow:
                d['onay_no'] = orow['onay_no']
                d['onay_durum'] = orow['durum']
                d['onay_durum_etiket'] = ONAY_DURUM_ETIKET.get(
                    orow['durum'] or '', orow['durum'],
                )
        except Exception:
            pass
    # F5 liste: İstenen Ürün + Bekleme
    try:
        from modules.nexgen.mtt_donusum_service import bekleme_hesapla, istenen_urun_ozet
        if d.get('kalemler') is not None:
            d['istenen_urun'] = istenen_urun_ozet(d.get('kalemler') or [])
        elif d.get('id') and _tablo_var(con, TABLO_KALEM):
            # Liste için hafif yükleme — aile/renk/miktar dahil
            tid = int(d['id'])
            krows = con.execute(
                f'SELECT urun_aciklama, urun_ailesi, renk_aciklama, miktar_kg, konusulan_tonaj '
                f'FROM {TABLO_KALEM} WHERE talep_id=? ORDER BY sira_no ASC, id ASC',
                (tid,),
            ).fetchall()
            fake = [_row_to_dict(r) for r in krows]
            d['istenen_urun'] = istenen_urun_ozet(fake) if fake else None
        else:
            d['istenen_urun'] = None
        d['bekleme'] = bekleme_hesapla(d)
    except Exception:
        d.setdefault('istenen_urun', None)
        d.setdefault('bekleme', None)
    # Detay UI: termin / karşılama / toplam miktar (read-only presentation)
    d.setdefault('istenen_termin', None)
    d.setdefault('karsilama_yolu', None)
    d.setdefault('teslim_sekli_etiket', None)
    d.setdefault('toplam_miktar_ozet', None)
    try:
        import re
        from modules.nexgen.mtt_donusum_service import (
            _parse_mo_siparis_meta,
            miktar_gosterim,
        )
        ac = d.get('aciklama')
        gn = d.get('gorusme_notu')
        meta = _parse_mo_siparis_meta(ac, gn)
        if meta.get('istenen_termin'):
            d['istenen_termin'] = meta['istenen_termin']
        if meta.get('teslim_sekli_etiket'):
            d['teslim_sekli_etiket'] = meta['teslim_sekli_etiket']
        mk = re.search(r'Karşılama:\s*([^|]+)', ac or '')
        if mk:
            d['karsilama_yolu'] = mk.group(1).strip()
        ks = d.get('kalemler') or []
        if ks:
            ton_sum = 0.0
            kg_sum = 0.0
            has_ton = has_kg = False
            for k in ks:
                try:
                    if k.get('konusulan_tonaj') not in (None, ''):
                        ton_sum += float(k['konusulan_tonaj'])
                        has_ton = True
                except (TypeError, ValueError):
                    pass
                try:
                    if k.get('miktar_kg') not in (None, ''):
                        kg_sum += float(k['miktar_kg'])
                        has_kg = True
                except (TypeError, ValueError):
                    pass
            parts: list[str] = []
            if has_ton:
                if abs(ton_sum - int(ton_sum)) < 1e-9:
                    parts.append(f'{int(ton_sum)} ton')
                else:
                    parts.append(
                        f"{str(ton_sum).rstrip('0').rstrip('.').replace('.', ',')} ton",
                    )
            if has_kg:
                if abs(kg_sum - int(kg_sum)) < 1e-9:
                    parts.append(f'{int(kg_sum):,}'.replace(',', '.') + ' kg')
                else:
                    parts.append(
                        f'{kg_sum:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.') + ' kg',
                    )
            if parts:
                d['toplam_miktar_ozet'] = ' · '.join(parts)
            elif len(ks) == 1:
                d['toplam_miktar_ozet'] = miktar_gosterim(ks[0])
    except Exception:
        pass
    return d


def _normalize_talep_input(talep_in) -> dict | None:
    """None / boş → talep yok. Aksi halde doğrulanmış dict."""
    if talep_in is None:
        return None
    if not isinstance(talep_in, dict):
        raise MusteriTemsilcisiTalepError('talep nesnesi geçersiz.', 400)
    tur = (talep_in.get('talep_turu') or '').strip().upper()
    if not tur or tur in ('YOK', 'NONE', 'TALEP_YOK'):
        return None
    if tur not in TALEP_TURLERI:
        raise MusteriTemsilcisiTalepError('talep_turu SIPARIS veya NUMUNE olmalı.', 400)
    kalemler = talep_in.get('kalemler') or []
    if not isinstance(kalemler, list) or not kalemler:
        raise MusteriTemsilcisiTalepError('En az bir talep kalemi zorunlu.', 400)
    if len(kalemler) > MAX_KALEMLER:
        raise MusteriTemsilcisiTalepError(
            f'En fazla {MAX_KALEMLER} kalem eklenebilir.', 400,
        )
    for i, k in enumerate(kalemler):
        if not isinstance(k, dict):
            raise MusteriTemsilcisiTalepError(f'Kalem {i + 1} geçersiz.', 400)
    oncelik = (talep_in.get('oncelik') or 'NORMAL').strip().upper()
    if oncelik not in ONCELIKLER:
        raise MusteriTemsilcisiTalepError('Geçersiz talep önceliği.', 400)
    out = dict(talep_in)
    out['talep_turu'] = tur
    out['oncelik'] = oncelik
    out['aciklama'] = (talep_in.get('aciklama') or '').strip() or None
    out['musteri_notu'] = (talep_in.get('musteri_notu') or '').strip() or None
    return out


def _erken_talep_zorunlu_dogrula(talep_norm: dict, g_payload: dict) -> None:
    """TX öncesi F6 doğrulama — görüşme/talep yazılmadan 422."""
    snap = _snap_from_gorusme_payload(g_payload or {})
    kalem_raw = talep_norm.get('kalemler') or []
    kalemler = [
        _kalem_from_payload(k if isinstance(k, dict) else {}, i + 1, snap)
        for i, k in enumerate(kalem_raw)
    ]
    _assert_mtt_zorunlu_alanlar(
        talep_norm['talep_turu'],
        talep_norm.get('aciklama'),
        talep_norm.get('musteri_notu'),
        kalemler,
        snap,
    )


def _combined_fingerprint(gorusme_payload: dict, talep_norm: dict | None) -> str:
    body = {
        'cari_id': gorusme_payload.get('cari_id'),
        'musteri_aday_id': gorusme_payload.get('musteri_aday_id'),
        'yeni_musteri': bool(gorusme_payload.get('yeni_musteri')),
        'firma_adi': (gorusme_payload.get('firma_adi') or '').strip() or None,
        'gorusme_tipi': (gorusme_payload.get('gorusme_tipi') or '').strip(),
        'sonuc_tipi': (gorusme_payload.get('sonuc_tipi') or '').strip(),
        'kisa_not': (gorusme_payload.get('kisa_not') or '').strip(),
        'fiyat_verildi': gorusme_payload.get('fiyat_verildi'),
        'verilen_fiyat': _fp_num(gorusme_payload.get('verilen_fiyat')),
        'fiyat_para_birimi': (gorusme_payload.get('fiyat_para_birimi') or '').strip().upper() or None,
        'konusulan_tonaj': _fp_num(gorusme_payload.get('konusulan_tonaj')),
        'odeme_tipi': (gorusme_payload.get('odeme_tipi') or '').strip().upper() or None,
        'talep': None,
    }
    if talep_norm:
        body['talep'] = {
            'talep_turu': talep_norm.get('talep_turu'),
            'oncelik': talep_norm.get('oncelik') or 'NORMAL',
            'aciklama': (talep_norm.get('aciklama') or '').strip() or None,
            'kalemler': [
                {
                    'sira_no': int(k.get('sira_no') or i + 1),
                    'urun_aciklama': (k.get('urun_aciklama') or '').strip(),
                    'urun_ailesi': (k.get('urun_ailesi') or '').strip() or None,
                    'renk_aciklama': (k.get('renk_aciklama') or '').strip() or None,
                    'miktar_kg': _fp_num(k.get('miktar_kg')),
                    'konusulan_tonaj': _fp_num(k.get('konusulan_tonaj')),
                    'verilen_fiyat': _fp_num(k.get('verilen_fiyat')),
                    'para_birimi': (k.get('para_birimi') or '').strip().upper() or None,
                    'kalem_notu': (k.get('kalem_notu') or '').strip() or None,
                }
                for i, k in enumerate(talep_norm.get('kalemler') or [])
                if isinstance(k, dict)
            ],
        }
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _talep_by_gorusme(con, gorusme_id: int) -> sqlite3.Row | None:
    if not _tablo_var(con, TABLO):
        return None
    return con.execute(
        f'SELECT * FROM {TABLO} WHERE gorusme_id=? ORDER BY id DESC LIMIT 1',
        (int(gorusme_id),),
    ).fetchone()


def _talep_by_idem(con, idem: str) -> sqlite3.Row | None:
    if not _tablo_var(con, TABLO):
        return None
    return _mevcut_idempotent(con, idem)


def _talep_response_slice(talep_row, con=None) -> dict:
    if not talep_row:
        return {
            'talep_olusturuldu': False,
        }
    out = {
        'talep_olusturuldu': True,
        'talep_id': int(talep_row['id']),
        'talep_no': talep_row['talep_no'],
        'talep_turu': talep_row['talep_turu'],
        'talep_durum': talep_row['durum'],
    }
    if con is not None:
        try:
            from modules.nexgen.onay_service import onay_by_kaynak
            onay = onay_by_kaynak(con, 'MUSTERI_TEMSILCISI_TALEP', int(talep_row['id']))
            if onay:
                out['onay_id'] = int(onay['id'])
                out['onay_no'] = onay.get('onay_no')
                out['onay_durum'] = onay.get('durum')
                out['onay_turu'] = onay.get('onay_turu')
        except Exception:
            pass
    return out


def gorusmelere_talep_ozeti_ekle(con, liste: list[dict]) -> list[dict]:
    """N+1 olmadan görüşme listesine talep özeti ekler."""
    if not liste or not _tablo_var(con, TABLO):
        return liste
    ids = [int(x['id']) for x in liste if x.get('id')]
    if not ids:
        return liste
    ph = ','.join('?' * len(ids))
    rows = con.execute(
        f"""
        SELECT id, gorusme_id, talep_no, talep_turu, durum
        FROM {TABLO}
        WHERE gorusme_id IN ({ph})
        ORDER BY id ASC
        """,
        ids,
    ).fetchall()
    by_g: dict[int, sqlite3.Row] = {}
    for r in rows:
        by_g[int(r['gorusme_id'])] = r  # son (en yeni) kalsın
    for item in liste:
        t = by_g.get(int(item['id']))
        if not t:
            item['temsilci_talep'] = None
            continue
        tur = t['talep_turu']
        dur = t['durum']
        item['temsilci_talep'] = {
            'id': int(t['id']),
            'talep_no': t['talep_no'],
            'talep_turu': tur,
            'talep_turu_etiket': TUR_ETIKET.get(tur, tur),
            'durum': dur,
            'durum_etiket': DURUM_ETIKET.get(dur, dur),
            'ozet': (
                f"{TUR_ETIKET.get(tur, tur)} · {t['talep_no']} · "
                f"{DURUM_ETIKET.get(dur, dur)}"
            ),
        }
    return liste


def kaydet_gorusme_opsiyonel_talep(
    con: sqlite3.Connection,
    payload: dict,
    kullanici_id: int,
    yk: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    """
    Görüşme (+ opsiyonel MTT) tek transaction.
    Standalone talep_olustur commit=False ile çağrılır.
    """
    from modules.nexgen.mo_gorusme_service import MoGorusmeError, gorusme_detay, gorusme_kaydet
    from modules.nexgen.musteri_aday_service import (
        MusteriAdayError,
        aday_getir,
        aday_olustur,
        can_aday_yaz,
        load_kullanici_yetkileri,
    )

    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)

    g_payload = {k: v for k, v in (payload or {}).items() if k != 'talep'}
    mod = (g_payload.get('mod') or 'YAPILDI').strip().upper()
    if mod == 'PLANLA':
        from modules.nexgen.mo_gorusme_service import gorusme_planla_kaydet
        plan = gorusme_planla_kaydet(con, g_payload, kullanici_id, yk, commit=True)
        aj = plan.get('ajanda') or {}
        if not aj.get('id'):
            raise MoGorusmeError('Plan ajandaya yazılamadı.', 500)
        return {
            'ok': True,
            'kayit': aj,
            'ajanda': aj,
            'aday': plan.get('aday'),
            'idempotent': plan.get('idempotent', False),
            'entity_type': plan.get('entity_type'),
            'mesaj': plan.get('mesaj') or 'Plan oluşturuldu.',
            'talep_olusturuldu': False,
        }

    talep_norm = _normalize_talep_input(payload.get('talep') if payload else None)

    idem = (g_payload.get('idempotency_key') or '').strip()
    if not idem:
        raise MoGorusmeError('idempotency_key zorunlu.', 400)
    if talep_norm is not None:
        talep_norm = dict(talep_norm)
        talep_norm['idempotency_key'] = idem

    yeni = bool(g_payload.get('yeni_musteri')) or (
        g_payload.get('firma_adi')
        and not g_payload.get('cari_id')
        and not g_payload.get('musteri_aday_id')
        and not g_payload.get('aday_id')
    )

    incoming_fp = _combined_fingerprint(g_payload, talep_norm)

    # Erken idempotency — görüşme varsa
    if _tablo_var(con, GORUSME):
        mevcut_g = con.execute(
            f'SELECT id FROM {GORUSME} WHERE idempotency_key=? AND COALESCE(aktif,1)=1',
            (idem,),
        ).fetchone()
        if mevcut_g:
            gid = int(mevcut_g['id'])
            kayit = gorusme_detay(con, gid, kullanici_id, yk)
            trow = _talep_by_idem(con, idem) or _talep_by_gorusme(con, gid)
            # Stored fingerprint yaklaşık: talep varlığı + gorusme temel alanları
            stored_talep = None
            if trow:
                stored_talep = {
                    'talep_turu': trow['talep_turu'],
                    'oncelik': trow['oncelik'],
                    'aciklama': trow['aciklama'],
                    'kalemler': _kalemleri_yukle(con, int(trow['id'])),
                }
            stored_g = {
                'cari_id': kayit.get('cari_id'),
                'musteri_aday_id': kayit.get('musteri_aday_id'),
                'yeni_musteri': False,
                'firma_adi': None,
                'gorusme_tipi': kayit.get('gorusme_tipi'),
                'sonuc_tipi': kayit.get('sonuc_tipi'),
                'kisa_not': kayit.get('kisa_not'),
                'fiyat_verildi': kayit.get('fiyat_verildi'),
                'verilen_fiyat': kayit.get('verilen_fiyat'),
                'fiyat_para_birimi': kayit.get('fiyat_para_birimi'),
                'konusulan_tonaj': kayit.get('konusulan_tonaj'),
                'odeme_tipi': kayit.get('odeme_tipi'),
            }
            stored_fp = _combined_fingerprint(stored_g, stored_talep)
            # Talep yok/var uyumsuzluğu kesin conflict
            if bool(talep_norm) != bool(trow):
                raise MusteriTemsilcisiTalepError(
                    'idempotency_key aynı ama payload farklı.', 409,
                    {'gorusme_id': gid},
                )
            if talep_norm and trow:
                # Kalem/ürün karşılaştırması — talep fingerprint
                try:
                    talep_olustur(
                        con,
                        {
                            **talep_norm,
                            'gorusme_id': gid,
                            'cari_id': kayit.get('cari_id'),
                            'musteri_aday_id': kayit.get('musteri_aday_id'),
                            'idempotency_key': idem,
                        },
                        kullanici_id,
                        commit=False,
                    )
                except MusteriTemsilcisiTalepError:
                    raise
            elif stored_fp != incoming_fp:
                # Görüşme alanı farkı — gevşek: kisa_not / tip / sonuc
                if (
                    (stored_g.get('gorusme_tipi') or '') != (g_payload.get('gorusme_tipi') or '').strip()
                    or (stored_g.get('sonuc_tipi') or '') != (g_payload.get('sonuc_tipi') or '').strip()
                    or (stored_g.get('kisa_not') or '').strip() != (g_payload.get('kisa_not') or '').strip()
                ):
                    raise MusteriTemsilcisiTalepError(
                        'idempotency_key aynı ama payload farklı.', 409,
                        {'gorusme_id': gid},
                    )
            aday = None
            if kayit.get('musteri_aday_id'):
                aday = aday_getir(con, int(kayit['musteri_aday_id']), kullanici_id, yk)
            out = {
                'ok': True,
                'kayit': kayit,
                'gorusme_id': gid,
                'idempotent': True,
                'aday': aday,
                'entity_type': 'ADAY' if kayit.get('musteri_aday_id') else 'CARI',
                **_talep_response_slice(trow, con),
            }
            if out['talep_olusturuldu']:
                if out.get('talep_turu') == 'NUMUNE' and out.get('talep_durum') == 'ONAY_BEKLIYOR':
                    out['mesaj'] = (
                        f"Numune talebi {out['talep_no']} numarasıyla "
                        f"yönetim onayına gönderildi."
                    )
                elif out.get('talep_durum') == 'ONAY_BEKLIYOR':
                    out['mesaj'] = (
                        f"Görüşme ve {out['talep_no']} talebi kaydedildi. Onay bekliyor."
                    )
                else:
                    out['mesaj'] = f"Görüşme ve {out['talep_no']} talebi kaydedildi."
            else:
                out['mesaj'] = 'Görüşme kaydedildi.'
            return out

    # Erken F6 doğrulama — başarısızsa görüşme/talep yazılmaz
    if talep_norm:
        _erken_talep_zorunlu_dogrula(talep_norm, g_payload)

    try:
        con.execute('BEGIN IMMEDIATE')
    except sqlite3.OperationalError:
        pass

    try:
        aday = None
        if yeni:
            if not can_aday_yaz(con, kullanici_id, yk):
                raise MusteriAdayError('Aday oluşturma yetkiniz yok.', 403)
            aday_payload = {
                'firma_adi': g_payload.get('firma_adi'),
                'yetkili_adi': g_payload.get('yetkili_adi') or g_payload.get('aday_yetkili'),
                'telefon': g_payload.get('telefon') or g_payload.get('aday_telefon'),
                'sehir': g_payload.get('sehir') or g_payload.get('aday_sehir'),
                'not_metni': g_payload.get('not_metni') or g_payload.get('aday_not'),
                'idempotency_key': idem,
            }
            aid = aday_olustur(con, aday_payload, kullanici_id, commit=False)
            g_payload = dict(g_payload)
            g_payload.pop('cari_id', None)
            g_payload['musteri_aday_id'] = aid
            g_payload['cari_id'] = None
            g_payload['idempotency_key'] = idem
            kayit = gorusme_kaydet(con, g_payload, kullanici_id, yk, commit=False)
            aday = aday_getir(con, aid, kullanici_id, yk)
            entity = 'ADAY'
        else:
            kayit = gorusme_kaydet(con, g_payload, kullanici_id, yk, commit=False)
            entity = 'ADAY' if kayit.get('musteri_aday_id') else 'CARI'
            if kayit.get('musteri_aday_id'):
                aday = aday_getir(con, int(kayit['musteri_aday_id']), kullanici_id, yk)

        gid = int(kayit['id'])
        ajanda_id = g_payload.get('ajanda_id')
        if ajanda_id:
            from modules.nexgen.mo_ajanda_service import MoAjandaError, ajanda_tamamla
            ajanda_tamamla(
                con,
                int(ajanda_id),
                gid,
                kullanici_id,
                int(kayit['cari_id']) if kayit.get('cari_id') else None,
                yk,
                musteri_aday_id=int(kayit['musteri_aday_id']) if kayit.get('musteri_aday_id') else None,
                commit=False,
            )
        elif not ajanda_id and (kayit.get('cari_id') or kayit.get('musteri_aday_id')):
            from modules.nexgen.mo_ajanda_service import gercek_gorusmeyi_ajandaya_bagla
            from modules.nexgen.mo_gorusme_service import ajanda_senkron_sonuc_zorunlu
            aj_sonuc = gercek_gorusmeyi_ajandaya_bagla(
                con,
                gorusme_id=gid,
                kullanici_id=kullanici_id,
                cari_id=int(kayit['cari_id']) if kayit.get('cari_id') else None,
                musteri_aday_id=int(kayit['musteri_aday_id']) if kayit.get('musteri_aday_id') else None,
                gorusme_tarihi=g_payload.get('gorusme_tarihi') or '',
                gorusme_tipi=g_payload.get('gorusme_tipi') or '',
                yk=yk,
                commit=False,
            )
            ajanda_senkron_sonuc_zorunlu(aj_sonuc, baglam='gorusme_kayit')
        trow = None
        if talep_norm:
            t_payload = {
                'gorusme_id': gid,
                'talep_turu': talep_norm['talep_turu'],
                'cari_id': kayit.get('cari_id'),
                'musteri_aday_id': kayit.get('musteri_aday_id'),
                'oncelik': talep_norm.get('oncelik') or 'NORMAL',
                'aciklama': talep_norm.get('aciklama'),
                'musteri_notu': talep_norm.get('musteri_notu'),
                'idempotency_key': idem,
                'kalemler': talep_norm.get('kalemler') or [],
            }
            t_out = talep_olustur(con, t_payload, kullanici_id, commit=False)
            trow = t_out['kayit']
            # Yeni oluşturmada onay zorunlu (idempotent eski kayıtlar hariç)
            if (
                not t_out.get('idempotent')
                and (trow or {}).get('durum') == 'ONAY_BEKLIYOR'
                and not (trow or {}).get('onay_id')
            ):
                raise MusteriTemsilcisiTalepError(
                    'Onay kaydı oluşmadı — işlem geri alındı.', 500,
                )

        con.commit()
        out = {
            'ok': True,
            'kayit': kayit,
            'gorusme_id': gid,
            'idempotent': False,
            'aday': aday,
            'entity_type': entity,
            **_talep_response_slice(trow if talep_norm else None, con),
        }
        if out.get('talep_olusturuldu'):
            if out.get('talep_turu') == 'NUMUNE' and out.get('talep_durum') == 'ONAY_BEKLIYOR':
                out['mesaj'] = (
                    f"Numune talebi {out['talep_no']} numarasıyla "
                    f"yönetim onayına gönderildi."
                )
            elif out.get('talep_durum') == 'ONAY_BEKLIYOR':
                out['mesaj'] = (
                    f"Görüşme ve {out['talep_no']} talebi kaydedildi. Onay bekliyor."
                )
            else:
                out['mesaj'] = f"Görüşme ve {out['talep_no']} talebi kaydedildi."
            if yeni:
                out['aciklama'] = 'Yeni müşteri aday listesine eklendi.'
        else:
            out['mesaj'] = 'Görüşme kaydedildi.'
            if yeni:
                out['aciklama'] = 'Yeni müşteri aday listesine eklendi.'
        return out
    except (MusteriTemsilcisiTalepError, MoGorusmeError, MusteriAdayError):
        try:
            con.rollback()
        except Exception:
            pass
        raise
    except Exception as exc:
        from modules.nexgen.mo_ajanda_service import MoAjandaError
        if isinstance(exc, MoAjandaError):
            try:
                con.rollback()
            except Exception:
                pass
            raise MoGorusmeError(exc.mesaj, exc.kod) from exc
        try:
            con.rollback()
        except Exception:
            pass
        raise


def numune_popup_mtt_onaya_gonder(
    con: sqlite3.Connection,
    payload: dict,
    kullanici_id: int,
    yk: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    """
    MO Numune popup → tek TX: görüşme + MTT NUMUNE + kalem + nexgen_onay.
    nexgen_numune_talep / eski onay_talep yazılmaz.
    """
    from datetime import datetime as _dt

    p = payload or {}
    try:
        cari_id = int(p.get('cari_id') or 0)
    except (TypeError, ValueError):
        cari_id = 0
    if not cari_id:
        raise MusteriTemsilcisiTalepError('cari_id zorunlu.', 400)

    idem = (p.get('idempotency_key') or '').strip()
    if not idem:
        raise MusteriTemsilcisiTalepError('idempotency_key zorunlu.', 400)

    urun_adi = (p.get('urun_adi') or '').strip()
    urun_tipi = (p.get('urun_tipi') or '').strip().upper()
    musteri_talebi = (p.get('musteri_talebi') or '').strip()
    if not urun_adi:
        raise MusteriTemsilcisiTalepError('Ürün adı zorunlu.', 400)
    if not urun_tipi:
        raise MusteriTemsilcisiTalepError('Ürün tipi zorunlu.', 400)
    if not musteri_talebi:
        raise MusteriTemsilcisiTalepError('Müşteri talebi zorunlu.', 400)

    aile_map = {
        'TERLIK': 'TERLIK', 'TABAN': 'TABAN', 'DOKME': 'DOKME',
        'DÖKME': 'DOKME',
    }
    urun_ailesi = aile_map.get(urun_tipi, urun_tipi)
    renk = (p.get('referans_renk') or '').strip() or 'Belirtilmedi'
    oncelik = (p.get('oncelik') or 'NORMAL').strip().upper()
    if oncelik not in ONCELIKLER:
        oncelik = 'NORMAL'
    onay_notu = (p.get('onay_notu') or '').strip()
    ek_not = (p.get('not') or '').strip()
    talep_alt = (p.get('talep_turu') or p.get('karsilama_yolu') or '').strip()
    musteri_kod = (p.get('musteri_urun_kodu') or '').strip()
    termin = (p.get('istenen_termin') or p.get('hedef_tarih') or '').strip()

    aciklama_parts = [musteri_talebi]
    if onay_notu:
        aciklama_parts.append(f'Onay notu: {onay_notu}')
    if termin:
        aciklama_parts.append(f'Termin: {termin}')
    if talep_alt:
        aciklama_parts.append(f'Karşılama: {talep_alt}')
    aciklama = ' | '.join(aciklama_parts)[:500]

    kalem_not_parts = []
    if musteri_kod:
        kalem_not_parts.append(f'Kod: {musteri_kod}')
    if ek_not:
        kalem_not_parts.append(ek_not)
    kalem_notu = ' | '.join(kalem_not_parts)[:300] or None

    gorusme_id = p.get('mo_gorusme_id')
    try:
        gorusme_id = int(gorusme_id) if gorusme_id not in (None, '', 0, '0') else None
    except (TypeError, ValueError):
        gorusme_id = None

    now_str = _dt.now().strftime('%Y-%m-%d %H:%M:%S')
    talep_block = {
        'talep_turu': 'NUMUNE',
        'oncelik': oncelik,
        'aciklama': aciklama,
        'musteri_notu': musteri_talebi,
        'kalemler': [{
            'urun_aciklama': urun_adi,
            'urun_ailesi': urun_ailesi,
            'renk_aciklama': renk,
            'miktar_kg': 1,
            'kalem_notu': kalem_notu,
        }],
    }

    if gorusme_id:
        # Mevcut görüşmeye MTT bağla — yeni görüşme yok
        grow = con.execute(
            'SELECT id, cari_id, aktif FROM musteri_operasyon_gorusme WHERE id=?',
            (gorusme_id,),
        ).fetchone()
        if not grow or int(grow['aktif'] or 0) != 1:
            raise MusteriTemsilcisiTalepError('Bağlı görüşme bulunamadı.', 404)
        if int(grow['cari_id'] or 0) != cari_id:
            raise MusteriTemsilcisiTalepError('Görüşme cari ile uyuşmuyor.', 409)
        t_out = talep_olustur(
            con,
            {
                **talep_block,
                'gorusme_id': gorusme_id,
                'cari_id': cari_id,
                'idempotency_key': idem,
            },
            kullanici_id,
            commit=True,
        )
        kayit = t_out['kayit']
        if not kayit.get('onay_id'):
            raise MusteriTemsilcisiTalepError('Onay kaydı oluşmadı.', 500)
        return {
            'ok': True,
            'gorusme_id': gorusme_id,
            'talep_id': int(kayit['id']),
            'talep_no': kayit.get('talep_no'),
            'talep_turu': 'NUMUNE',
            'talep_durum': kayit.get('durum'),
            'onay_id': kayit.get('onay_id'),
            'onay_no': kayit.get('onay_no'),
            'onay_durum': kayit.get('onay_durum'),
            'onay_turu': kayit.get('onay_turu'),
            'idempotent': bool(t_out.get('idempotent')),
            'mesaj': (
                f"Numune talebi {kayit.get('talep_no')} numarasıyla "
                f"yönetim onayına gönderildi."
            ),
        }

    g_payload = {
        'cari_id': cari_id,
        'gorusme_tipi': (p.get('gorusme_tipi') or 'Telefon').strip() or 'Telefon',
        'sonuc_tipi': 'Numune İstedi',
        'kisa_not': musteri_talebi[:500],
        'gorusme_tarihi': now_str,
        'oncelik': oncelik,
        'kaynak': 'MUSTERI_OPERASYONU',
        'idempotency_key': idem,
        'talep': talep_block,
    }
    out = kaydet_gorusme_opsiyonel_talep(con, g_payload, kullanici_id, yk)
    if not out.get('talep_olusturuldu') or not out.get('onay_id'):
        raise MusteriTemsilcisiTalepError(
            'Numune talebi onay kaydı oluşmadan tamamlanamaz.', 500,
        )
    return {
        'ok': True,
        'gorusme_id': out.get('gorusme_id'),
        'talep_id': out.get('talep_id'),
        'talep_no': out.get('talep_no'),
        'talep_turu': out.get('talep_turu') or 'NUMUNE',
        'talep_durum': out.get('talep_durum'),
        'onay_id': out.get('onay_id'),
        'onay_no': out.get('onay_no'),
        'onay_durum': out.get('onay_durum'),
        'onay_turu': out.get('onay_turu'),
        'idempotent': bool(out.get('idempotent')),
        'mesaj': out.get('mesaj') or (
            f"Numune talebi {out.get('talep_no')} numarasıyla "
            f"yönetim onayına gönderildi."
        ),
        'kayit': out.get('kayit'),
    }
