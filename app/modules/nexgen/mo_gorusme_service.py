# -*- coding: utf-8 -*-
"""Müşteri Operasyonu görüşme kaydı — MVP servis."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

_IST = ZoneInfo('Europe/Istanbul')

from modules.nexgen.cari360_yetki import can_cari360_view_all
from modules.nexgen.cari_sorumlu_service import (
    can_mo_view_cari,
    can_view_cari,
    can_write_crm,
    load_kullanici_yetkileri,
)
from modules.nexgen.mo_gorusme_config import (
    FIYAT_BIRIMI_KG,
    FIYAT_PARA_BIRIMLERI,
    GORUSME_GUN_ESIK,
    GORUSME_TIPLERI,
    GORUSME_TIPLERI_ALL,
    KAYNAK_MUSTERI_OPERASYONU,
    ODEME_TIPLERI,
    ONCELIKLER,
    SIPARIS_ZIYARET_ESIK_GUN,
    SONUC_TIPLERI,
    SONUC_TIPLERI_ALL,
    TABLO,
    VADE_GUN_MAX,
)

TAKIP_DURUMLARI: tuple[str, ...] = ('ACIK', 'TAMAMLANDI', 'IPTAL')
KAYNAK_CARI_KART = 'CARI_KART'
ZIYARET_TIPLERI: tuple[str, ...] = (
    'Ziyaret', 'Fabrika Ziyareti', 'Ofis Ziyareti',
)


class MoGorusmeError(Exception):
    def __init__(self, mesaj: str, kod: int = 400):
        self.mesaj = mesaj
        self.kod = kod
        super().__init__(mesaj)


def ajanda_senkron_sonuc_zorunlu(
    sonuc: dict[str, Any] | None,
    *,
    baglam: str,
) -> dict[str, Any]:
    """Ajanda write fail-open skip dönüşlerini görüşme TX içinde hataya çevirir."""
    out = sonuc or {}
    if out.get('durum') == 'skip':
        sebep = out.get('sebep') or 'bilinmiyor'
        raise MoGorusmeError(
            f'Ajanda senkronizasyonu başarısız ({baglam}): {sebep}',
            500,
        )
    return out


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _today() -> str:
    return datetime.now(_IST).date().isoformat()


def _istanbul_today() -> date:
    return datetime.now(_IST).date()


_GORUSME_TARIHI_FMT = '%Y-%m-%d %H:%M:%S'


def _normalize_gorusme_tarihi(raw: str) -> str:
    s = (raw or '').strip()
    if not s:
        return _now()
    if len(s) == 10:
        s = s + ' 12:00:00'
    return s[:19]


def _parse_gorusme_tarihi(gt: str) -> datetime:
    return datetime.strptime(gt[:19], _GORUSME_TARIHI_FMT)


def gerceklesmis_gorusme_tarihi_sql(alias: str = 'g') -> str:
    """Yalnız geçmiş/şimdi gerçekleşmiş görüşme tarihleri (plan değil)."""
    return f"substr({alias}.gorusme_tarihi, 1, 19) <= datetime('now','localtime')"


def is_gerceklesmis_gorusme_tarihi(gt: str | None) -> bool:
    if not gt:
        return False
    try:
        return _parse_gorusme_tarihi(str(gt)) <= datetime.now()
    except ValueError:
        return False


def _assert_gorusme_tarihi_gerceklesmis(gt: str) -> str:
    norm = _normalize_gorusme_tarihi(gt)
    try:
        dt = _parse_gorusme_tarihi(norm)
    except ValueError:
        raise MoGorusmeError('Görüşme tarihi geçersiz.', 400)
    gun = dt.date()
    bugun = _istanbul_today()
    if gun > bugun:
        raise MoGorusmeError('Gerçekleşmiş görüşme tarihi gelecekte olamaz.', 400)
    if (bugun - gun).days > 2:
        raise MoGorusmeError(
            'Görüşme tarihi bugün veya en fazla 2 gün öncesi olmalıdır.', 400,
        )
    return norm


def _tablo_var(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _kullanici_cari_atanmis(con, kullanici_id: int, cari_id: int) -> bool:
    row = con.execute(
        """
        SELECT 1 FROM cari_sorumlu
        WHERE kullanici_id=? AND cari_id=? AND sorumluluk_rolu IN ('ANA','YEDEK','DESTEK')
          AND aktif=1 AND (bitis_tarihi IS NULL OR bitis_tarihi=''
               OR bitis_tarihi > datetime('now','localtime'))
        """,
        (kullanici_id, cari_id),
    ).fetchone()
    return bool(row)


def can_mo_gorusme_yaz(
    con: sqlite3.Connection,
    kullanici_id: int,
    cari_id: int,
    yk: set[str] | None = None,
) -> bool:
    """CRM yazma — atanmış / sorumlusuz aktif (MO) / yönetici.

    Otomatik sorumlu ataması YOK. Fiziksel silme yok.
    """
    from modules.nexgen.cari360_yetki import can_cari360_crm_write, can_cari360_view_own
    from modules.nexgen.cari_sorumlu_service import cari_aktif_atanmamis_mi

    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    if can_write_crm(con, kullanici_id, cari_id, yk):
        return True
    if not can_cari360_crm_write(yk):
        return False
    if can_cari360_view_own(yk) and cari_aktif_atanmamis_mi(con, cari_id):
        return True
    return False


def can_mo_gorusme_yaz_aday(
    con: sqlite3.Connection,
    kullanici_id: int,
    musteri_aday_id: int,
    yk: set[str] | None = None,
) -> bool:
    """Aday görüşmesi yazma — kendi adayı veya admin."""
    from modules.nexgen.musteri_aday_service import can_aday_gor, can_aday_yaz

    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    if not can_aday_yaz(con, kullanici_id, yk):
        return False
    return can_aday_gor(con, kullanici_id, int(musteri_aday_id), yk)


def can_mo_gorusme_duzenle(
    con: sqlite3.Connection,
    kullanici_id: int,
    kayit: dict[str, Any],
    yk: set[str] | None = None,
) -> bool:
    """Yönetici tümünü; pazarlamacı yalnız kendi kaydını düzenler."""
    if yk is None:
        yk = load_kullanici_yetkileri(con, kullanici_id)
    aday_id = kayit.get('musteri_aday_id')
    if aday_id not in (None, '', 0):
        if not can_mo_gorusme_yaz_aday(con, kullanici_id, int(aday_id), yk):
            return False
    else:
        cari_id = int(kayit.get('cari_id') or 0)
        if not cari_id or not can_mo_gorusme_yaz(con, kullanici_id, cari_id, yk):
            return False
    if can_cari360_view_all(yk) or '*' in (yk or set()):
        return True
    return int(kayit.get('kullanici_id') or 0) == int(kullanici_id)


def takip_gorunum(
    takip_durumu: str | None,
    sonraki_takip_tarihi: str | None,
) -> str | None:
    """ACIK + geçmiş tarih → GECİKTİ. Tamamlanan tekrar açık görünmez."""
    d = (takip_durumu or '').strip().upper() or None
    if not d:
        return None
    if d in ('TAMAMLANDI', 'IPTAL'):
        return d
    if d == 'ACIK':
        t = (sonraki_takip_tarihi or '').strip()[:10]
        if t and t < _today():
            return 'GECIKTI'
        return 'ACIK'
    return d


def _kolon_var(con, tablo: str, kolon: str) -> bool:
    return any(c[1] == kolon for c in con.execute(f'PRAGMA table_info({tablo})').fetchall())


def _assert_yetkili_uygun(
    con: sqlite3.Connection,
    cari_id: int,
    yetkili_id: int | None,
    *,
    yeni_gorusme: bool = True,
) -> int | None:
    if yetkili_id in (None, '', 0):
        return None
    try:
        yid = int(yetkili_id)
    except (TypeError, ValueError):
        raise MoGorusmeError('yetkili_id geçersiz.', 400)
    if not _tablo_var(con, 'cari_yetkili'):
        raise MoGorusmeError('cari_yetkili tablosu yok (migration 133).', 503)
    row = con.execute(
        'SELECT id, cari_id, aktif, ad_soyad FROM cari_yetkili WHERE id=?',
        (yid,),
    ).fetchone()
    if not row:
        raise MoGorusmeError('Yetkili bulunamadı.', 404)
    if int(row['cari_id']) != int(cari_id):
        raise MoGorusmeError('Başka carinin yetkilisi seçilemez.', 400)
    if yeni_gorusme and int(row['aktif'] or 0) != 1:
        raise MoGorusmeError('Pasif yetkili yeni görüşmede seçilemez.', 400)
    return yid


def timeline_olay_sozlesmesi(kayit: dict[str, Any]) -> dict[str, Any]:
    """Cari 360 timeline — olay motoru henüz aktif değil; sözleşme hazır."""
    return {
        'olay_tipi': 'MUSTERI_OPERASYONU_GORUSME',
        'kaynak_modul': KAYNAK_MUSTERI_OPERASYONU,
        'kaynak_id': kayit.get('id'),
        'cari_id': kayit.get('cari_id'),
        'baslik': f"Görüşme — {kayit.get('gorusme_tipi', '')}",
        'ozet': (kayit.get('kisa_not') or '')[:200],
        'tarih': kayit.get('gorusme_tarihi'),
        'olay_motoru_aktif': False,
    }


def _row_dict(r) -> dict[str, Any]:
    d = dict(r)
    ad = (d.get('kullanici_adsoyad') or '').strip()
    kadi = (d.get('kullanici_adi') or '').strip()
    d['pazarlamaci_adi'] = ad or kadi or '—'
    d['kullanici_adi'] = d['pazarlamaci_adi']
    d['yetkili_adi'] = d.get('yetkili_adi') or ''
    d['yetkili_unvan'] = d.get('yetkili_unvan') or ''
    d['takip_gorunum'] = takip_gorunum(
        d.get('takip_durumu'), d.get('sonraki_takip_tarihi'),
    )
    d['fiyat_ozet'] = fiyat_ozet_metin(d)
    return d


def _kullanici_select_sql() -> str:
    return (
        "sk.KullaniciAdi AS kullanici_adi, "
        "COALESCE(NULLIF(TRIM(sk.AdSoyad), ''), sk.KullaniciAdi) AS kullanici_adsoyad"
    )


def _yetkili_select_sql(con: sqlite3.Connection) -> tuple[str, str]:
    metin_expr = (
        'g.yetkili_metin' if _kolon_var(con, TABLO, 'yetkili_metin') else "''"
    )
    if _tablo_var(con, 'cari_yetkili') and _kolon_var(con, TABLO, 'yetkili_id'):
        return (
            'LEFT JOIN cari_yetkili cy ON cy.id = g.yetkili_id',
            f"COALESCE(NULLIF(TRIM(cy.ad_soyad), ''), NULLIF(TRIM({metin_expr}), ''), '') "
            f"AS yetkili_adi, cy.unvan AS yetkili_unvan",
        )
    return '', f"COALESCE(NULLIF(TRIM({metin_expr}), ''), '') AS yetkili_adi, '' AS yetkili_unvan"


def _assert_numune_uygun(
    con: sqlite3.Connection,
    cari_id: int,
    numune_talep_id: Any,
) -> int | None:
    """Numune id opsiyonel; varsa aynı cariye ait ve aktif olmalı."""
    if numune_talep_id in (None, '', 0, '0'):
        return None
    try:
        nid = int(numune_talep_id)
    except (TypeError, ValueError):
        raise MoGorusmeError('numune_talep_id geçersiz.', 400)
    if nid <= 0:
        return None
    if not _tablo_var(con, 'nexgen_numune_talep'):
        raise MoGorusmeError('Numune tablosu hazır değil.', 503)
    row = con.execute(
        'SELECT id, cari_id, aktif, talep_kodu FROM nexgen_numune_talep WHERE id=?',
        (nid,),
    ).fetchone()
    if not row or not int(row['aktif'] or 0):
        raise MoGorusmeError('Numune talebi bulunamadı.', 404)
    if row['cari_id'] is None or int(row['cari_id']) != int(cari_id):
        raise MoGorusmeError('Numune bu cariye ait değil.', 403)
    return nid


def _enrich_baglantilar(con: sqlite3.Connection, d: dict[str, Any]) -> dict[str, Any]:
    """Numune/sipariş bağları.

    Ana: gorusme.numune_talep_id (migration 136).
    Geçiş: ters numune.mo_gorusme_id (bozulmaz).
    """
    gid = d.get('id')
    if not gid:
        return d
    d['kaynak_numune_talep_id'] = None
    d['kaynak_numune_kodu'] = None
    d['kaynak_numune_url'] = None
    d['kaynak_siparis_id'] = None

    nid = None
    if _kolon_var(con, TABLO, 'numune_talep_id') and d.get('numune_talep_id') not in (None, ''):
        try:
            nid = int(d['numune_talep_id'])
        except (TypeError, ValueError):
            nid = None
    if nid is None and _tablo_var(con, 'nexgen_numune_talep') and _kolon_var(
        con, 'nexgen_numune_talep', 'mo_gorusme_id'
    ):
        nr = con.execute(
            'SELECT id FROM nexgen_numune_talep WHERE mo_gorusme_id=? ORDER BY id DESC LIMIT 1',
            (gid,),
        ).fetchone()
        if nr:
            nid = int(nr['id'] if hasattr(nr, 'keys') else nr[0])
    if nid:
        d['kaynak_numune_talep_id'] = nid
        d['numune_talep_id'] = nid
        d['kaynak_numune_url'] = f'/nexgen/numune-talep?id={nid}'
        if _tablo_var(con, 'nexgen_numune_talep'):
            nk = con.execute(
                'SELECT talep_kodu FROM nexgen_numune_talep WHERE id=?', (nid,),
            ).fetchone()
            if nk:
                d['kaynak_numune_kodu'] = nk['talep_kodu'] or f'#{nid}'

    if _tablo_var(con, 'nexgen_planlama_siparis') and _kolon_var(con, 'nexgen_planlama_siparis', 'mo_gorusme_id'):
        sr = con.execute(
            'SELECT id FROM nexgen_planlama_siparis WHERE mo_gorusme_id=? ORDER BY id DESC LIMIT 1',
            (gid,),
        ).fetchone()
        if sr:
            d['kaynak_siparis_id'] = int(sr['id'] if hasattr(sr, 'keys') else sr[0])
    return d


def _parse_boolish(v) -> bool:
    if v in (True, 1, '1', 'true', 'True', 'evet', 'EVET', 'yes', 'YES'):
        return True
    return False


def _parse_decimal(v) -> float | None:
    if v in (None, ''):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(' ', '').replace(',', '.')
    if not s:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


_TONAJ_NUM_RE = re.compile(r'^[\d.,]+$')


def _parse_konusulan_tonaj(v) -> float | None:
    """Türkçe binlik/ondalık — yalnız görüşme konuşulan tonaj girişi."""
    if v in (None, ''):
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(' ', '')
    if not s:
        return None
    if not _TONAJ_NUM_RE.match(s):
        return None
    try:
        if ',' in s:
            return float(s.replace('.', '').replace(',', '.'))
        if '.' in s:
            parts = s.split('.')
            last = parts[-1]
            if (
                len(last) == 3
                and last.isdigit()
                and all(p.isdigit() and 1 <= len(p) <= 3 for p in parts)
            ):
                return float(''.join(parts))
            return float(s)
        return float(s)
    except (TypeError, ValueError):
        return None


def format_tr_tonaj(v: float | int) -> str:
    """Canonical tonaj → TR gösterim (ör. 10000 → 10.000)."""
    n = float(v)
    s = f'{n:g}'.replace('.', ',')
    parts = s.split(',')
    parts[0] = re.sub(r'\B(?=(\d{3})+(?!\d))', '.', parts[0])
    return ','.join(parts)


_TICARI_FLAG_REQUIRED_MSG = (
    'Ticari bilgiler girildiği için "Fiyat verildi" seçilmelidir.'
)


def _payload_has_ticari_input(payload: dict) -> bool:
    """Payload'da anlamlı ticari giriş var mı (fiyat_verildi gate dışı)."""
    vf = payload.get('verilen_fiyat')
    if vf not in (None, ''):
        parsed = _parse_decimal(vf)
        if parsed is not None and parsed > 0:
            return True
        if str(vf).strip():
            return True
    if (payload.get('fiyat_para_birimi') or '').strip():
        return True
    tonaj = payload.get('konusulan_tonaj')
    if tonaj not in (None, '') and str(tonaj).strip():
        return True
    odeme = (payload.get('odeme_tipi') or '').strip()
    if odeme:
        return True
    for key in ('vade_gun', 'cek_vade_gun', 'cek_adedi'):
        val = payload.get(key)
        if val not in (None, '') and str(val).strip():
            return True
    ticari_not = (payload.get('ticari_not') or payload.get('odeme_notu') or '').strip()
    if ticari_not:
        return True
    return False


def _validate_fiyat_snapshot(payload: dict) -> dict[str, Any]:
    """fiyat_verildi=0 → tüm ticari alanlar NULL; =1 → KG sabit + kurallar."""
    fiyat_verildi = _parse_boolish(payload.get('fiyat_verildi'))
    empty = {
        'fiyat_verildi': 0,
        'verilen_fiyat': None,
        'fiyat_para_birimi': None,
        'fiyat_birimi': None,
        'konusulan_tonaj': None,
        'odeme_tipi': None,
        'vade_gun': None,
        'cek_vade_gun': None,
        'cek_adedi': None,
        'ticari_not': None,
        'cek_notu': None,
    }
    if not fiyat_verildi:
        if _payload_has_ticari_input(payload):
            raise MoGorusmeError(_TICARI_FLAG_REQUIRED_MSG, 400)
        return empty

    fiyat = _parse_decimal(payload.get('verilen_fiyat'))
    if fiyat is None or fiyat <= 0:
        raise MoGorusmeError('Verilen fiyat pozitif olmalıdır.', 400)

    para = (payload.get('fiyat_para_birimi') or '').strip().upper()
    if para not in FIYAT_PARA_BIRIMLERI:
        raise MoGorusmeError('Para birimi seçin (TRY/USD/EUR).', 400)

    # Kullanıcı seçmez — her zaman KG
    birim = FIYAT_BIRIMI_KG

    raw_tonaj = payload.get('konusulan_tonaj')
    if raw_tonaj in (None, ''):
        tonaj = None
    else:
        tonaj = _parse_konusulan_tonaj(raw_tonaj)
        if tonaj is None:
            raise MoGorusmeError('Konuşulan tonaj geçersiz.', 400)
    if tonaj is not None and tonaj <= 0:
        raise MoGorusmeError('Konuşulan tonaj 0\'dan büyük olmalıdır.', 400)

    odeme = (payload.get('odeme_tipi') or '').strip().upper()
    if odeme in ('NAKİT', 'NAKİT'):
        odeme = 'NAKIT'
    if odeme in ('VADELİ', 'VADELİ'):
        odeme = 'VADELI'
    if odeme in ('ÇEK',):
        odeme = 'CEK'
    if odeme not in ODEME_TIPLERI:
        raise MoGorusmeError('Ödeme tipi seçin (NAKIT/VADELI/CEK).', 400)

    def _pos_int(v, label: str, *, required: bool):
        if v in (None, ''):
            if required:
                raise MoGorusmeError(f'{label} zorunlu.', 400)
            return None
        try:
            n = int(v)
        except (TypeError, ValueError):
            raise MoGorusmeError(f'{label} geçersiz.', 400)
        if n < 1:
            raise MoGorusmeError(f'{label} en az 1 olmalıdır.', 400)
        if n > VADE_GUN_MAX:
            raise MoGorusmeError(f'{label} en fazla {VADE_GUN_MAX} olabilir.', 400)
        return n

    vade_gun = None
    cek_vade_gun = None
    cek_adedi = None
    cek_notu = None
    if odeme == 'NAKIT':
        pass
    elif odeme == 'VADELI':
        vade_gun = _pos_int(payload.get('vade_gun'), 'Vade (gün)', required=True)
    else:  # CEK
        cek_vade_gun = _pos_int(payload.get('cek_vade_gun'), 'Çek vadesi (gün)', required=True)
        if payload.get('cek_adedi') not in (None, ''):
            cek_adedi = _pos_int(payload.get('cek_adedi'), 'Çek adedi', required=True)
        cek_notu = (payload.get('cek_notu') or '').strip() or None

    ticari_not = (payload.get('ticari_not') or payload.get('odeme_notu') or '').strip() or None

    return {
        'fiyat_verildi': 1,
        'verilen_fiyat': fiyat,
        'fiyat_para_birimi': para,
        'fiyat_birimi': birim,
        'konusulan_tonaj': tonaj,
        'odeme_tipi': odeme,
        'vade_gun': vade_gun,
        'cek_vade_gun': cek_vade_gun,
        'cek_adedi': cek_adedi,
        'ticari_not': ticari_not,
        'cek_notu': cek_notu,
    }


def fiyat_ozet_metin(kayit: dict[str, Any]) -> str | None:
    """Liste satırı için kısa ticari özet."""
    if not int(kayit.get('fiyat_verildi') or 0):
        return None
    fiyat = kayit.get('verilen_fiyat')
    if fiyat in (None, ''):
        return None
    try:
        ftxt = f'{float(fiyat):g}'.replace('.', ',')
    except (TypeError, ValueError):
        ftxt = str(fiyat)
    para = (kayit.get('fiyat_para_birimi') or '').strip()
    birim = (kayit.get('fiyat_birimi') or FIYAT_BIRIMI_KG).strip() or FIYAT_BIRIMI_KG
    if birim == 'CIFT':
        birim_goster = 'ÇİFT'
    else:
        birim_goster = birim
    odeme = (kayit.get('odeme_tipi') or '').strip()
    parts = [f'{ftxt} {para}/{birim_goster}'.strip()]
    tonaj = kayit.get('konusulan_tonaj')
    if tonaj not in (None, ''):
        try:
            parts.append(f'{format_tr_tonaj(float(tonaj))} ton')
        except (TypeError, ValueError):
            parts.append(f'{tonaj} ton')
    if odeme == 'NAKIT':
        parts.append('NAKİT')
    elif odeme == 'VADELI':
        vg = kayit.get('vade_gun')
        parts.append(f'VADELİ {vg} gün' if vg else 'VADELİ')
    elif odeme == 'CEK':
        cv = kayit.get('cek_vade_gun')
        parts.append(f'ÇEK {cv} gün' if cv else 'ÇEK')
    return ' · '.join(p for p in parts if p)


def _apply_fiyat_snapshot(con: sqlite3.Connection, gorusme_id: int, snap: dict[str, Any]) -> None:
    if not _kolon_var(con, TABLO, 'fiyat_verildi'):
        return
    has_tonaj = _kolon_var(con, TABLO, 'konusulan_tonaj')
    if has_tonaj:
        con.execute(
            f"""
            UPDATE {TABLO} SET
                fiyat_verildi=?, verilen_fiyat=?, fiyat_para_birimi=?, fiyat_birimi=?,
                konusulan_tonaj=?,
                odeme_tipi=?, vade_gun=?, cek_vade_gun=?, cek_adedi=?,
                ticari_not=?, cek_notu=?
            WHERE id=?
            """,
            (
                int(snap.get('fiyat_verildi') or 0),
                snap.get('verilen_fiyat'),
                snap.get('fiyat_para_birimi'),
                snap.get('fiyat_birimi'),
                snap.get('konusulan_tonaj'),
                snap.get('odeme_tipi'),
                snap.get('vade_gun'),
                snap.get('cek_vade_gun'),
                snap.get('cek_adedi'),
                snap.get('ticari_not'),
                snap.get('cek_notu'),
                gorusme_id,
            ),
        )
    else:
        con.execute(
            f"""
            UPDATE {TABLO} SET
                fiyat_verildi=?, verilen_fiyat=?, fiyat_para_birimi=?, fiyat_birimi=?,
                odeme_tipi=?, vade_gun=?, cek_vade_gun=?, cek_adedi=?,
                ticari_not=?, cek_notu=?
            WHERE id=?
            """,
            (
                int(snap.get('fiyat_verildi') or 0),
                snap.get('verilen_fiyat'),
                snap.get('fiyat_para_birimi'),
                snap.get('fiyat_birimi'),
                snap.get('odeme_tipi'),
                snap.get('vade_gun'),
                snap.get('cek_vade_gun'),
                snap.get('cek_adedi'),
                snap.get('ticari_not'),
                snap.get('cek_notu'),
                gorusme_id,
            ),
        )


def _validate_payload(payload: dict, *, require_idem: bool = True, mod: str = 'YAPILDI') -> dict[str, Any]:
    """mod: 'YAPILDI' (varsayılan) veya 'PLANLA' — planlama modunda gelecek tarih kabul edilir."""
    is_plan = (mod or '').strip().upper() == 'PLANLA'

    tip = (payload.get('gorusme_tipi') or '').strip()
    if tip not in GORUSME_TIPLERI:
        raise MoGorusmeError('Geçerli görüşme tipi seçin.', 400)

    sonuc = (payload.get('sonuc_tipi') or '').strip() or 'Genel Görüşme'
    if not is_plan and sonuc not in SONUC_TIPLERI_ALL:
        raise MoGorusmeError('Geçerli görüşme sonucu seçin.', 400)

    kisa = (payload.get('kisa_not') or '').strip()
    konu = (payload.get('konu') or '').strip()
    if not is_plan:
        # Yapıldı modunda not zorunlu
        if len(kisa) < 3:
            if len(konu) >= 2:
                kisa = konu[:200]
            else:
                raise MoGorusmeError('Görüşme notu gerekli.', 400)
    else:
        kisa = kisa or konu or ''

    if is_plan:
        # Planlama modunda gelecek tarih kabul edilir — normalize yeterli
        gt = _normalize_gorusme_tarihi(
            (payload.get('gorusme_tarihi') or '').strip() or _now()
        )
    else:
        gt = _assert_gorusme_tarihi_gerceklesmis(
            (payload.get('gorusme_tarihi') or '').strip() or _now(),
        )

    oncelik = (payload.get('oncelik') or 'NORMAL').strip().upper()
    if oncelik not in ONCELIKLER:
        oncelik = 'NORMAL'

    idem = (payload.get('idempotency_key') or '').strip()
    if require_idem and not idem:
        raise MoGorusmeError('idempotency_key zorunlu.', 400)

    def _opt_float(v):
        return _parse_decimal(v)

    def _opt_int(v):
        if v in (None, ''):
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    cari_raw = payload.get('cari_id')
    aday_raw = payload.get('musteri_aday_id', payload.get('aday_id'))
    cari_id = _opt_int(cari_raw) if cari_raw not in (None, '', 0, '0') else None
    musteri_aday_id = _opt_int(aday_raw) if aday_raw not in (None, '', 0, '0') else None
    yeni_musteri = bool(payload.get('yeni_musteri')) or (
        (payload.get('firma_adi') or '').strip()
        and not cari_id
        and not musteri_aday_id
    )
    if cari_id and musteri_aday_id:
        raise MoGorusmeError('cari_id ve musteri_aday_id birlikte gönderilemez.', 400)
    if not cari_id and not musteri_aday_id and not yeni_musteri:
        raise MoGorusmeError('cari_id veya musteri_aday_id zorunlu.', 400)

    takip = (payload.get('sonraki_takip_tarihi') or payload.get('takip_tarihi') or '').strip() or None
    takip_durum = (payload.get('takip_durumu') or '').strip().upper() or None
    if takip and not takip_durum:
        takip_durum = 'ACIK'
    if takip_durum and takip_durum not in TAKIP_DURUMLARI:
        raise MoGorusmeError('takip_durumu geçersiz (ACIK/TAMAMLANDI/IPTAL).', 400)

    kaynak = (payload.get('kaynak') or KAYNAK_MUSTERI_OPERASYONU).strip().upper()
    if kaynak not in (KAYNAK_MUSTERI_OPERASYONU, KAYNAK_CARI_KART):
        kaynak = KAYNAK_MUSTERI_OPERASYONU

    fiyat_snap = _validate_fiyat_snapshot(payload)

    # Yeni modal: yetkili_id gönderilmez; yalnız yetkili_metin
    yetkili_id_raw = payload.get('yetkili_id')
    yetkili_id = None
    if cari_id and yetkili_id_raw not in (None, '', 0, '0'):
        yetkili_id = yetkili_id_raw

    return {
        'cari_id': cari_id,
        'musteri_aday_id': musteri_aday_id,
        'gorusme_tipi': tip,
        'sonuc_tipi': sonuc,
        'sonuc_etiketler': json.dumps(payload.get('sonuc_etiketler') or [], ensure_ascii=False),
        'kisa_not': kisa,
        'konu': konu or None,
        'sonraki_aksiyon': (payload.get('sonraki_aksiyon') or '').strip() or None,
        'yetkili_id': yetkili_id,
        'yetkili_metin': (
            (payload.get('yetkili_metin') or payload.get('yetkili_adi_serbest') or '').strip() or None
        ),
        'numune_talep_id': payload.get('numune_talep_id') if cari_id else None,
        'gorusme_tarihi': gt,
        'sonraki_takip_tarihi': takip,
        'takip_durumu': takip_durum,
        'oncelik': oncelik,
        'tahmini_siparis_tutari': _opt_float(payload.get('tahmini_siparis_tutari')),
        'tahmini_siparis_tarihi': (payload.get('tahmini_siparis_tarihi') or '').strip() or None,
        'istenen_vade_gun': _opt_int(payload.get('istenen_vade_gun')),
        'cek_alim_tarihi': (payload.get('cek_alim_tarihi') or '').strip() or None,
        'rakip_firma': (payload.get('rakip_firma') or '').strip() or None,
        'makina_notu': (payload.get('makina_notu') or '').strip() or None,
        'detay_not': (payload.get('detay_not') or '').strip() or None,
        'dosya_ref': (payload.get('dosya_ref') or '').strip() or None,
        'idempotency_key': idem,
        'kaynak': kaynak,
        'is_plan': is_plan,
        'yeni_musteri': yeni_musteri,
        **fiyat_snap,
    }


def gorusme_planla_kaydet(
    con: sqlite3.Connection,
    payload: dict,
    kullanici_id: int,
    yk: set[str] | None = None,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    """PLANLA — yalnız Ajanda PLANLANDI; görüşme satırı oluşturulmaz."""
    from modules.nexgen.mo_ajanda_service import MoAjandaError, ajanda_olustur, _tablo_var as _aj_var
    from modules.nexgen.mo_ajanda_config import TABLO as AJ_TABLO
    from modules.nexgen.musteri_aday_service import (
        DURUM_ADAY,
        MusteriAdayError,
        aday_getir,
        aday_olustur,
        can_aday_yaz,
    )

    if not _aj_var(con, AJ_TABLO):
        raise MoGorusmeError('Ajanda tablosu hazır değil.', 503)

    norm = _validate_payload(payload, mod='PLANLA')
    idem = norm['idempotency_key']
    ajanda_idem = 'gorusme_plan:' + idem

    mevcut_a = con.execute(
        f'SELECT * FROM {AJ_TABLO} WHERE idempotency_key=? AND aktif=1',
        (ajanda_idem,),
    ).fetchone()
    if mevcut_a:
        from modules.nexgen.mo_ajanda_service import _aday_map, _cari_map, _row_dict
        cm = _cari_map(con, [int(mevcut_a['cari_id'])] if mevcut_a['cari_id'] else [])
        am = _aday_map(con, [int(mevcut_a['musteri_aday_id'])] if (
            'musteri_aday_id' in mevcut_a.keys() and mevcut_a['musteri_aday_id']
        ) else [])
        kayit = _row_dict(mevcut_a, cm, am)
        aday = None
        aid = mevcut_a['musteri_aday_id'] if 'musteri_aday_id' in mevcut_a.keys() else None
        if aid:
            aday = aday_getir(con, int(aid), kullanici_id, yk)
        return {
            'ok': True,
            'ajanda': kayit,
            'aday': aday,
            'idempotent': True,
            'mesaj': 'Plan zaten kayıtlı.',
            'entity_type': 'ADAY' if aid else 'CARI',
        }

    yeni = bool(payload.get('yeni_musteri')) or (
        (payload.get('firma_adi') or '').strip()
        and not norm.get('cari_id')
        and not norm.get('musteri_aday_id')
    )

    try:
        con.execute('BEGIN IMMEDIATE')
    except sqlite3.OperationalError:
        pass

    aday = None
    try:
        aj_payload: dict[str, Any] = {
            'plan_tarihi': norm['gorusme_tarihi'],
            'gorusme_tipi': norm['gorusme_tipi'],
            'plan_notu': norm.get('kisa_not') or norm.get('konu') or None,
            'idempotency_key': ajanda_idem,
        }
        if yeni:
            if not can_aday_yaz(con, kullanici_id, yk):
                raise MusteriAdayError('Aday oluşturma yetkiniz yok.', 403)
            firma = (payload.get('firma_adi') or '').strip()
            if not firma:
                raise MoGorusmeError('Firma adı zorunlu.', 400)
            aid = aday_olustur(con, {
                'firma_adi': firma,
                'yetkili_adi': payload.get('yetkili_adi'),
                'telefon': payload.get('telefon'),
                'sehir': payload.get('sehir'),
                'not_metni': payload.get('not_metni'),
                'idempotency_key': idem,
            }, kullanici_id, commit=False)
            aday = aday_getir(con, aid, kullanici_id, yk, _skip_auth=True)
            aj_payload['musteri_aday_id'] = aid
            aj_payload['firma_adi_gorunum'] = firma
        elif norm.get('musteri_aday_id'):
            aid = int(norm['musteri_aday_id'])
            if not can_mo_gorusme_yaz_aday(con, kullanici_id, aid, yk):
                raise MoGorusmeError('Bu aday için plan oluşturma yetkiniz yok.', 403)
            aday = aday_getir(con, aid, _skip_auth=True)
            if not aday or aday.get('durum') != DURUM_ADAY:
                raise MoGorusmeError('Aday bulunamadı veya aktif değil.', 404)
            aj_payload['musteri_aday_id'] = aid
            aj_payload['firma_adi_gorunum'] = (
                (payload.get('firma_adi_gorunum') or '').strip()
                or aday.get('firma_adi')
            )
        else:
            cari_id = int(norm['cari_id'])
            if not can_mo_gorusme_yaz(con, kullanici_id, cari_id, yk):
                raise MoGorusmeError('Bu cari için plan oluşturma yetkiniz yok.', 403)
            cari = con.execute(
                'SELECT unvan FROM nexgen_cari WHERE id=? AND aktif=1', (cari_id,),
            ).fetchone()
            if not cari:
                raise MoGorusmeError('Cari bulunamadı.', 404)
            aj_payload['cari_id'] = cari_id
            aj_payload['firma_adi_gorunum'] = (
                (payload.get('firma_adi_gorunum') or '').strip() or cari['unvan']
            )

        plan_yetkili = None
        plan_telefon = None
        plan_sehir = None
        if yeni:
            plan_yetkili = (
                (payload.get('yetkili_adi') or payload.get('yetkili_metin') or '').strip() or None
            )
            plan_telefon = (payload.get('telefon') or '').strip() or None
            plan_sehir = (payload.get('sehir') or '').strip() or None
        elif norm.get('musteri_aday_id'):
            plan_yetkili = (
                (payload.get('yetkili_adi') or payload.get('yetkili_metin') or '').strip() or None
            )
            plan_telefon = (payload.get('telefon') or '').strip() or None
            plan_sehir = (payload.get('sehir') or '').strip() or None
            if aday:
                plan_yetkili = plan_yetkili or (aday.get('yetkili_adi') or '').strip() or None
                plan_telefon = plan_telefon or (aday.get('telefon') or '').strip() or None
                plan_sehir = plan_sehir or (aday.get('sehir') or '').strip() or None
        else:
            plan_yetkili = (
                (norm.get('yetkili_metin') or payload.get('yetkili_metin') or '').strip() or None
            )
            plan_telefon = (payload.get('telefon') or '').strip() or None
            plan_sehir = (payload.get('sehir') or '').strip() or None
        aj_payload['plan_yetkili_metin'] = plan_yetkili
        aj_payload['plan_telefon'] = plan_telefon
        aj_payload['plan_sehir'] = plan_sehir

        aj_sonuc = ajanda_olustur(
            con, aj_payload, kullanici_id, yk, commit=False,
        )
        aj_kayit = aj_sonuc.get('kayit') or {}
        if not aj_kayit.get('id'):
            raise MoGorusmeError('Plan ajandaya yazılamadı.', 500)
        if commit:
            con.commit()
        return {
            'ok': True,
            'ajanda': aj_kayit,
            'aday': aday,
            'idempotent': aj_sonuc.get('idempotent', False),
            'mesaj': aj_sonuc.get('mesaj') or 'Plan oluşturuldu.',
            'entity_type': 'ADAY' if aday else 'CARI',
        }
    except (MoAjandaError, MusteriAdayError, MoGorusmeError):
        try:
            con.rollback()
        except Exception:
            pass
        raise
    except Exception:
        try:
            con.rollback()
        except Exception:
            pass
        raise


def gorusme_kaydet(
    con: sqlite3.Connection,
    payload: dict,
    kullanici_id: int,
    yk: set[str] | None = None,
    *,
    commit: bool = True,
) -> dict[str, Any]:
    if not _tablo_var(con, TABLO):
        raise MoGorusmeError('Görüşme tablosu hazır değil.', 503)

    mod = (payload.get('mod') or 'YAPILDI').strip().upper()
    if mod == 'PLANLA':
        plan_out = gorusme_planla_kaydet(
            con, payload, kullanici_id, yk, commit=commit,
        )
        return {
            'id': None,
            'ajanda': plan_out.get('ajanda'),
            'musteri_aday_id': (
                plan_out.get('aday', {}) or {}
            ).get('id') if plan_out.get('aday') else None,
            'cari_id': plan_out.get('ajanda', {}).get('cari_id'),
            **{k: v for k, v in plan_out.items() if k not in ('ajanda',)},
        }

    norm = _validate_payload(payload, mod=mod)
    is_plan = norm.get('is_plan', False)
    aday_id = norm.get('musteri_aday_id')
    cari_id = norm.get('cari_id')

    if aday_id:
        if not _kolon_var(con, TABLO, 'musteri_aday_id'):
            raise MoGorusmeError('Aday görüşmesi için migration 142 gerekli.', 503)
        if not can_mo_gorusme_yaz_aday(con, kullanici_id, int(aday_id), yk):
            raise MoGorusmeError('Bu aday için görüşme yazma yetkiniz yok.', 403)
        from modules.nexgen.musteri_aday_service import DURUM_ADAY, aday_getir
        aday = aday_getir(con, int(aday_id), _skip_auth=True)
        if not aday or aday.get('durum') != DURUM_ADAY:
            raise MoGorusmeError('Aday bulunamadı veya aktif değil.', 404)
        yetkili_id = None
        numune_id = None
    else:
        if not can_mo_gorusme_yaz(con, kullanici_id, int(cari_id), yk):
            raise MoGorusmeError('Bu cari için görüşme yazma yetkiniz yok.', 403)
        cari = con.execute(
            'SELECT id, cari_kod, unvan FROM nexgen_cari WHERE id=? AND aktif=1',
            (cari_id,),
        ).fetchone()
        if not cari:
            raise MoGorusmeError('Cari bulunamadı.', 404)
        yetkili_id = _assert_yetkili_uygun(
            con, int(cari_id), norm.get('yetkili_id'), yeni_gorusme=True,
        )
        numune_id = _assert_numune_uygun(con, int(cari_id), norm.get('numune_talep_id'))

    # Serbest yetkili metni — kart oluşturmaz; seçili yetkili varsa metin gerekmez
    yetkili_metin = norm.get('yetkili_metin')
    if yetkili_id is not None:
        yetkili_metin = None
    elif yetkili_metin:
        yetkili_metin = yetkili_metin[:120]

    mevcut = con.execute(
        f'SELECT id FROM {TABLO} WHERE idempotency_key=? AND aktif=1',
        (norm['idempotency_key'],),
    ).fetchone()
    if mevcut:
        return gorusme_detay(con, int(mevcut['id']), kullanici_id, yk)

    audit = json.dumps({
        'islem': 'OLUSTUR',
        'kullanici_id': kullanici_id,
        'tarih': _now(),
        'musteri_aday_id': aday_id,
    }, ensure_ascii=False)

    has_yetkili = _kolon_var(con, TABLO, 'yetkili_id')
    has_aday_col = _kolon_var(con, TABLO, 'musteri_aday_id')
    has_yetkili_metin = _kolon_var(con, TABLO, 'yetkili_metin')
    if has_yetkili and has_aday_col:
        if has_yetkili_metin:
            cur = con.execute(
                f"""
                INSERT INTO {TABLO} (
                    cari_id, musteri_aday_id, kullanici_id, kaynak, gorusme_tipi, sonuc_tipi,
                    sonuc_etiketler, kisa_not, konu, sonraki_aksiyon, yetkili_id, yetkili_metin,
                    gorusme_tarihi, sonraki_takip_tarihi, takip_durumu, oncelik,
                    tahmini_siparis_tutari, tahmini_siparis_tarihi, istenen_vade_gun,
                    cek_alim_tarihi, rakip_firma, makina_notu, detay_not, dosya_ref,
                    idempotency_key, olusturan_kullanici_id, guncelleyen_kullanici_id,
                    guncelleme_tarihi, audit_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    cari_id, aday_id, kullanici_id, norm['kaynak'],
                    norm['gorusme_tipi'], norm['sonuc_tipi'], norm['sonuc_etiketler'],
                    norm['kisa_not'], norm['konu'], norm['sonraki_aksiyon'], yetkili_id,
                    yetkili_metin,
                    norm['gorusme_tarihi'], norm['sonraki_takip_tarihi'], norm['takip_durumu'],
                    norm['oncelik'], norm['tahmini_siparis_tutari'], norm['tahmini_siparis_tarihi'],
                    norm['istenen_vade_gun'], norm['cek_alim_tarihi'], norm['rakip_firma'],
                    norm['makina_notu'], norm['detay_not'], norm['dosya_ref'],
                    norm['idempotency_key'], kullanici_id, kullanici_id, _now(), audit,
                ),
            )
        else:
            cur = con.execute(
                f"""
                INSERT INTO {TABLO} (
                    cari_id, musteri_aday_id, kullanici_id, kaynak, gorusme_tipi, sonuc_tipi,
                    sonuc_etiketler, kisa_not, konu, sonraki_aksiyon, yetkili_id,
                    gorusme_tarihi, sonraki_takip_tarihi, takip_durumu, oncelik,
                    tahmini_siparis_tutari, tahmini_siparis_tarihi, istenen_vade_gun,
                    cek_alim_tarihi, rakip_firma, makina_notu, detay_not, dosya_ref,
                    idempotency_key, olusturan_kullanici_id, guncelleyen_kullanici_id,
                    guncelleme_tarihi, audit_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    cari_id, aday_id, kullanici_id, norm['kaynak'],
                    norm['gorusme_tipi'], norm['sonuc_tipi'], norm['sonuc_etiketler'],
                    norm['kisa_not'], norm['konu'], norm['sonraki_aksiyon'], yetkili_id,
                    norm['gorusme_tarihi'], norm['sonraki_takip_tarihi'], norm['takip_durumu'],
                    norm['oncelik'], norm['tahmini_siparis_tutari'], norm['tahmini_siparis_tarihi'],
                    norm['istenen_vade_gun'], norm['cek_alim_tarihi'], norm['rakip_firma'],
                    norm['makina_notu'], norm['detay_not'], norm['dosya_ref'],
                    norm['idempotency_key'], kullanici_id, kullanici_id, _now(), audit,
                ),
            )
    elif has_yetkili:
        cur = con.execute(
            f"""
            INSERT INTO {TABLO} (
                cari_id, kullanici_id, kaynak, gorusme_tipi, sonuc_tipi, sonuc_etiketler,
                kisa_not, konu, sonraki_aksiyon, yetkili_id,
                gorusme_tarihi, sonraki_takip_tarihi, takip_durumu, oncelik,
                tahmini_siparis_tutari, tahmini_siparis_tarihi, istenen_vade_gun,
                cek_alim_tarihi, rakip_firma, makina_notu, detay_not, dosya_ref,
                idempotency_key, olusturan_kullanici_id, guncelleyen_kullanici_id,
                guncelleme_tarihi, audit_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                cari_id, kullanici_id, norm['kaynak'],
                norm['gorusme_tipi'], norm['sonuc_tipi'], norm['sonuc_etiketler'],
                norm['kisa_not'], norm['konu'], norm['sonraki_aksiyon'], yetkili_id,
                norm['gorusme_tarihi'], norm['sonraki_takip_tarihi'], norm['takip_durumu'],
                norm['oncelik'], norm['tahmini_siparis_tutari'], norm['tahmini_siparis_tarihi'],
                norm['istenen_vade_gun'], norm['cek_alim_tarihi'], norm['rakip_firma'],
                norm['makina_notu'], norm['detay_not'], norm['dosya_ref'],
                norm['idempotency_key'], kullanici_id, kullanici_id, _now(), audit,
            ),
        )
        if has_yetkili_metin and yetkili_metin:
            con.execute(
                f'UPDATE {TABLO} SET yetkili_metin=? WHERE id=?',
                (yetkili_metin, int(cur.lastrowid)),
            )
    else:
        cur = con.execute(
            f"""
            INSERT INTO {TABLO} (
                cari_id, kullanici_id, kaynak, gorusme_tipi, sonuc_tipi, sonuc_etiketler,
                kisa_not, gorusme_tarihi, sonraki_takip_tarihi, oncelik,
                tahmini_siparis_tutari, tahmini_siparis_tarihi, istenen_vade_gun,
                cek_alim_tarihi, rakip_firma, makina_notu, detay_not, dosya_ref,
                idempotency_key, olusturan_kullanici_id, audit_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                cari_id, kullanici_id, norm['kaynak'],
                norm['gorusme_tipi'], norm['sonuc_tipi'], norm['sonuc_etiketler'],
                norm['kisa_not'], norm['gorusme_tarihi'], norm['sonraki_takip_tarihi'],
                norm['oncelik'], norm['tahmini_siparis_tutari'], norm['tahmini_siparis_tarihi'],
                norm['istenen_vade_gun'], norm['cek_alim_tarihi'], norm['rakip_firma'],
                norm['makina_notu'], norm['detay_not'], norm['dosya_ref'],
                norm['idempotency_key'], kullanici_id, audit,
            ),
        )
    gid = int(cur.lastrowid)
    if numune_id is not None and _kolon_var(con, TABLO, 'numune_talep_id'):
        con.execute(
            f'UPDATE {TABLO} SET numune_talep_id=? WHERE id=?',
            (numune_id, gid),
        )
    _apply_fiyat_snapshot(con, gid, norm)

    # FAZ 2A: Ajanda entegrasyonu — YAPILDI (PLANLA ayrı akış)
    try:
        from modules.nexgen.mo_ajanda_service import (
            gercek_gorusmeyi_ajandaya_bagla,
            ajanda_olustur,
            _tablo_var as _ajanda_tablo_var,
            TABLO as AJANDA_TABLO,
        )
        if _ajanda_tablo_var(con, AJANDA_TABLO) and (cari_id or aday_id):
            ajanda_id_explicit = payload.get('ajanda_id')
            if not ajanda_id_explicit:
                aj_sonuc = gercek_gorusmeyi_ajandaya_bagla(
                    con, gid, kullanici_id,
                    cari_id=int(cari_id) if cari_id else None,
                    musteri_aday_id=int(aday_id) if aday_id else None,
                    gorusme_tarihi=norm['gorusme_tarihi'],
                    gorusme_tipi=norm['gorusme_tipi'],
                    firma_adi_gorunum=(payload.get('firma_adi_gorunum') or payload.get('firma_adi') or '').strip() or None,
                    yk=yk,
                    commit=False,
                )
                ajanda_senkron_sonuc_zorunlu(aj_sonuc, baglam='gercek_gorusme')
            takip_tarihi = norm.get('sonraki_takip_tarihi')
            if takip_tarihi and norm.get('sonraki_aksiyon'):
                takip_idem = 'takip_plan:' + norm['idempotency_key']
                takip_payload: dict[str, Any] = {
                    'kullanici_id': kullanici_id,
                    'plan_tarihi': takip_tarihi,
                    'gorusme_tipi': norm['gorusme_tipi'],
                    'plan_notu': norm.get('sonraki_aksiyon') or None,
                    'idempotency_key': takip_idem,
                }
                if cari_id:
                    takip_payload['cari_id'] = int(cari_id)
                    # Mevcut müşteri: formda girilen yetkili/tel/şehir varsa snapshota aktar
                    _tkp_y = (norm.get('yetkili_metin') or '').strip()
                    if _tkp_y:
                        takip_payload['plan_yetkili_metin'] = _tkp_y
                        takip_payload['plan_telefon'] = (payload.get('telefon') or '').strip() or None
                        takip_payload['plan_sehir'] = (payload.get('sehir') or '').strip() or None
                elif aday_id:
                    takip_payload['musteri_aday_id'] = int(aday_id)
                    if aday:
                        takip_payload['firma_adi_gorunum'] = aday.get('firma_adi')
                        # Aday görüşmesi: snapshot veya aday tablosundan yetkili/tel/şehir aktar
                        takip_payload['plan_yetkili_metin'] = (
                            (norm.get('yetkili_metin') or '').strip()
                            or (aday.get('yetkili_adi') or '').strip() or None
                        )
                        takip_payload['plan_telefon'] = (
                            (payload.get('telefon') or '').strip()
                            or (aday.get('telefon') or '').strip() or None
                        )
                        takip_payload['plan_sehir'] = (
                            (payload.get('sehir') or '').strip()
                            or (aday.get('sehir') or '').strip() or None
                        )
                ajanda_olustur(con, takip_payload, kullanici_id, yk, commit=False)
    except ImportError:
        pass

    if commit:
        con.commit()
    detay = gorusme_detay(con, gid, kullanici_id, yk)
    detay['timeline_sozlesme'] = timeline_olay_sozlesmesi(detay)
    return detay


def gorusme_detay(
    con: sqlite3.Connection,
    gorusme_id: int,
    kullanici_id: int,
    yk: set[str] | None = None,
) -> dict[str, Any]:
    yetkili_join, yetkili_sel = _yetkili_select_sql(con)
    row = con.execute(
        f"""
        SELECT g.*, {_kullanici_select_sql()}, {yetkili_sel}
        FROM {TABLO} g
        LEFT JOIN sistem_kullanici sk ON sk.Id = g.kullanici_id
        {yetkili_join}
        WHERE g.id=? AND g.aktif=1
        """,
        (gorusme_id,),
    ).fetchone()
    if not row:
        raise MoGorusmeError('Görüşme kaydı bulunamadı.', 404)
    aday_id = row['musteri_aday_id'] if 'musteri_aday_id' in row.keys() else None
    if aday_id not in (None, '', 0):
        from modules.nexgen.musteri_aday_service import can_aday_gor
        if not can_aday_gor(con, kullanici_id, int(aday_id), yk):
            raise MoGorusmeError('Görüntüleme yetkiniz yok.', 403)
    else:
        if row['cari_id'] is None or not can_mo_view_cari(
            con, kullanici_id, int(row['cari_id']), yk,
        ):
            raise MoGorusmeError('Görüntüleme yetkiniz yok.', 403)
    d = _enrich_baglantilar(con, _row_dict(row))
    d['can_edit'] = can_mo_gorusme_duzenle(con, kullanici_id, d, yk)
    return d


def list_gorusmeler(
    con: sqlite3.Connection,
    cari_id: int | None = None,
    kullanici_id: int = 0,
    yk: set[str] | None = None,
    limit: int = 50,
    *,
    musteri_aday_id: int | None = None,
) -> list[dict[str, Any]]:
    if musteri_aday_id:
        from modules.nexgen.musteri_aday_service import can_aday_gor
        if not can_aday_gor(con, kullanici_id, int(musteri_aday_id), yk):
            raise MoGorusmeError('Görüntüleme yetkiniz yok.', 403)
        where_sql = f'g.musteri_aday_id=? AND g.aktif=1 AND {gerceklesmis_gorusme_tarihi_sql("g")}'
        where_params: list[Any] = [int(musteri_aday_id)]
    else:
        if cari_id is None:
            raise MoGorusmeError('cari_id veya musteri_aday_id zorunlu.', 400)
        if not can_mo_view_cari(con, kullanici_id, cari_id, yk):
            raise MoGorusmeError('Görüntüleme yetkiniz yok.', 403)
        where_sql = f"g.cari_id=? AND g.aktif=1 AND {gerceklesmis_gorusme_tarihi_sql('g')}"
        where_params = [int(cari_id)]
    if not _tablo_var(con, TABLO):
        return []
    yetkili_join, yetkili_sel = _yetkili_select_sql(con)
    order = 'g.gorusme_tarihi DESC, g.id DESC'
    rows = con.execute(
        f"""
        SELECT g.*, {_kullanici_select_sql()}, {yetkili_sel}
        FROM {TABLO} g
        LEFT JOIN sistem_kullanici sk ON sk.Id = g.kullanici_id
        {yetkili_join}
        WHERE {where_sql}
        ORDER BY {order}
        LIMIT ?
        """,
        (*where_params, limit),
    ).fetchall()
    out = []
    for r in rows:
        d = _enrich_baglantilar(con, _row_dict(r))
        d['can_edit'] = can_mo_gorusme_duzenle(con, kullanici_id, d, yk)
        out.append(d)
    return out


def list_gorusmeler_paginated(
    con: sqlite3.Connection,
    cari_id: int,
    kullanici_id: int = 0,
    yk: set[str] | None = None,
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    """Server-side pagination için yeni endpoint — Cari Kart Görüşmeler sekmesi.

    Response contract:
      items        list[dict]
      total_count  int
      page         int
      page_size    int
      total_pages  int
    Sıralama: gorusme_tarihi DESC, id DESC (açık takip yalnız badge/sayaç).
    """
    if not can_mo_view_cari(con, kullanici_id, cari_id, yk):
        raise MoGorusmeError('Görüntüleme yetkiniz yok.', 403)
    if not _tablo_var(con, TABLO):
        return {'items': [], 'total_count': 0, 'page': 1, 'page_size': page_size, 'total_pages': 0}

    page_size = max(1, min(100, int(page_size)))
    page = max(1, int(page))

    where_sql = f"g.cari_id=? AND g.aktif=1 AND {gerceklesmis_gorusme_tarihi_sql('g')}"
    where_params: list[Any] = [int(cari_id)]

    total_count = int(con.execute(
        f'SELECT COUNT(*) FROM {TABLO} g WHERE {where_sql}',
        where_params,
    ).fetchone()[0] or 0)

    total_pages = max(1, (total_count + page_size - 1) // page_size)
    page = min(page, total_pages)
    offset = (page - 1) * page_size

    yetkili_join, yetkili_sel = _yetkili_select_sql(con)
    order = 'g.gorusme_tarihi DESC, g.id DESC'

    rows = con.execute(
        f"""
        SELECT g.*, {_kullanici_select_sql()}, {yetkili_sel}
        FROM {TABLO} g
        LEFT JOIN sistem_kullanici sk ON sk.Id = g.kullanici_id
        {yetkili_join}
        WHERE {where_sql}
        ORDER BY {order}
        LIMIT ? OFFSET ?
        """,
        (*where_params, page_size, offset),
    ).fetchall()

    items = []
    for r in rows:
        d = _enrich_baglantilar(con, _row_dict(r))
        d['can_edit'] = can_mo_gorusme_duzenle(con, kullanici_id, d, yk)
        items.append(d)

    return {
        'items': items,
        'total_count': total_count,
        'page': page,
        'page_size': page_size,
        'total_pages': total_pages,
    }


def gorusme_guncelle(
    con: sqlite3.Connection,
    gorusme_id: int,
    payload: dict,
    kullanici_id: int,
    yk: set[str] | None = None,
) -> dict[str, Any]:
    mevcut = gorusme_detay(con, gorusme_id, kullanici_id, yk)
    cari_id = int(mevcut['cari_id']) if mevcut.get('cari_id') not in (None, '') else None
    if not can_mo_gorusme_duzenle(con, kullanici_id, mevcut, yk):
        raise MoGorusmeError('Bu görüşmeyi düzenleme yetkiniz yok.', 403)

    tip = (payload.get('gorusme_tipi') or mevcut.get('gorusme_tipi') or '').strip()
    sonuc = (payload.get('sonuc_tipi') or mevcut.get('sonuc_tipi') or '').strip()
    kisa = (payload.get('kisa_not') if 'kisa_not' in payload else mevcut.get('kisa_not') or '')
    kisa = (kisa or '').strip()
    konu_tmp = payload.get('konu') if 'konu' in payload else mevcut.get('konu')
    konu_tmp = (konu_tmp or '').strip()
    if tip not in GORUSME_TIPLERI_ALL:
        raise MoGorusmeError('Geçerli görüşme tipi seçin.', 400)
    if sonuc and sonuc not in SONUC_TIPLERI_ALL:
        raise MoGorusmeError('Geçerli görüşme sonucu seçin.', 400)
    if not sonuc:
        sonuc = 'Genel Görüşme'
    if len(kisa) < 3:
        if len(konu_tmp) >= 2:
            kisa = konu_tmp[:200]
        else:
            raise MoGorusmeError('Görüşme notu gerekli.', 400)

    # Yeni modal yetkili_id göndermez; metin güncellenebilir
    if 'yetkili_metin' in payload and _kolon_var(con, TABLO, 'yetkili_metin'):
        ym = (payload.get('yetkili_metin') or '').strip() or None
        con.execute(
            f'UPDATE {TABLO} SET yetkili_metin=? WHERE id=?',
            (ym[:120] if ym else None, gorusme_id),
        )
        if ym:
            yetkili_id = None
        else:
            yetkili_raw = payload.get('yetkili_id') if 'yetkili_id' in payload else mevcut.get('yetkili_id')
            if cari_id is None or yetkili_raw in (None, '', 0):
                yetkili_id = None
            else:
                yetkili_id = _assert_yetkili_uygun(con, cari_id, yetkili_raw, yeni_gorusme=False)
    else:
        yetkili_raw = payload['yetkili_id'] if 'yetkili_id' in payload else mevcut.get('yetkili_id')
        if cari_id is None:
            yetkili_id = None
        elif 'yetkili_id' in payload and yetkili_raw not in (None, '', 0):
            yetkili_id = _assert_yetkili_uygun(con, cari_id, yetkili_raw, yeni_gorusme=True)
        elif yetkili_raw in (None, '', 0):
            yetkili_id = None
        else:
            yetkili_id = _assert_yetkili_uygun(con, cari_id, yetkili_raw, yeni_gorusme=False)

    takip = payload.get('sonraki_takip_tarihi') if 'sonraki_takip_tarihi' in payload else mevcut.get('sonraki_takip_tarihi')
    takip = (takip or '').strip() or None
    takip_durum = payload.get('takip_durumu') if 'takip_durumu' in payload else mevcut.get('takip_durumu')
    takip_durum = (takip_durum or '').strip().upper() or None
    if takip and not takip_durum:
        takip_durum = 'ACIK'
    if takip_durum and takip_durum not in TAKIP_DURUMLARI:
        raise MoGorusmeError('takip_durumu geçersiz.', 400)

    gt_raw = (payload.get('gorusme_tarihi') or mevcut.get('gorusme_tarihi') or '').strip()
    if not gt_raw:
        gt = _assert_gorusme_tarihi_gerceklesmis(_now())
    elif 'gorusme_tarihi' in payload:
        gt = _assert_gorusme_tarihi_gerceklesmis(gt_raw)
    else:
        gt = _normalize_gorusme_tarihi(gt_raw)

    konu = payload.get('konu') if 'konu' in payload else mevcut.get('konu')
    aksiyon = payload.get('sonraki_aksiyon') if 'sonraki_aksiyon' in payload else mevcut.get('sonraki_aksiyon')

    if not _kolon_var(con, TABLO, 'yetkili_id'):
        raise MoGorusmeError('Migration 134 gerekli.', 503)

    numune_id = mevcut.get('numune_talep_id') or mevcut.get('kaynak_numune_talep_id')
    if 'numune_talep_id' in payload:
        if cari_id is None:
            numune_id = None
        else:
            numune_id = _assert_numune_uygun(con, cari_id, payload.get('numune_talep_id'))

    if _kolon_var(con, TABLO, 'numune_talep_id'):
        con.execute(
            f"""
            UPDATE {TABLO} SET
                gorusme_tipi=?, sonuc_tipi=?, kisa_not=?, konu=?, sonraki_aksiyon=?,
                yetkili_id=?, numune_talep_id=?, gorusme_tarihi=?, sonraki_takip_tarihi=?,
                takip_durumu=?, guncelleme_tarihi=?, guncelleyen_kullanici_id=?
            WHERE id=? AND aktif=1
            """,
            (
                tip, sonuc, kisa, (konu or '').strip() or None,
                (aksiyon or '').strip() or None, yetkili_id, numune_id, gt, takip,
                takip_durum, _now(), kullanici_id, gorusme_id,
            ),
        )
    else:
        con.execute(
            f"""
            UPDATE {TABLO} SET
                gorusme_tipi=?, sonuc_tipi=?, kisa_not=?, konu=?, sonraki_aksiyon=?,
                yetkili_id=?, gorusme_tarihi=?, sonraki_takip_tarihi=?, takip_durumu=?,
                guncelleme_tarihi=?, guncelleyen_kullanici_id=?
            WHERE id=? AND aktif=1
            """,
            (
                tip, sonuc, kisa, (konu or '').strip() or None,
                (aksiyon or '').strip() or None, yetkili_id, gt, takip, takip_durum,
                _now(), kullanici_id, gorusme_id,
            ),
        )
    if 'fiyat_verildi' in payload or 'verilen_fiyat' in payload or 'odeme_tipi' in payload:
        snap = _validate_fiyat_snapshot(payload)
        _apply_fiyat_snapshot(con, gorusme_id, snap)
    con.commit()
    return gorusme_detay(con, gorusme_id, kullanici_id, yk)


def takip_durum_ayarla(
    con: sqlite3.Connection,
    gorusme_id: int,
    durum: str,
    kullanici_id: int,
    yk: set[str] | None = None,
) -> dict[str, Any]:
    d = (durum or '').strip().upper()
    if d not in TAKIP_DURUMLARI:
        raise MoGorusmeError('takip_durumu geçersiz.', 400)
    mevcut = gorusme_detay(con, gorusme_id, kullanici_id, yk)
    if mevcut.get('musteri_aday_id') not in (None, '', 0):
        if not can_mo_gorusme_yaz_aday(con, kullanici_id, int(mevcut['musteri_aday_id']), yk):
            raise MoGorusmeError('Bu aday için görüşme yazma yetkiniz yok.', 403)
    elif not can_mo_gorusme_yaz(con, kullanici_id, int(mevcut['cari_id']), yk):
        raise MoGorusmeError('Bu cari için görüşme yazma yetkiniz yok.', 403)
    if not _kolon_var(con, TABLO, 'takip_durumu'):
        raise MoGorusmeError('Migration 134 gerekli.', 503)
    con.execute(
        f"""
        UPDATE {TABLO}
        SET takip_durumu=?, guncelleme_tarihi=?, guncelleyen_kullanici_id=?
        WHERE id=? AND aktif=1
        """,
        (d, _now(), kullanici_id, gorusme_id),
    )
    con.commit()
    return gorusme_detay(con, gorusme_id, kullanici_id, yk)


def acik_takip_sayisi(con: sqlite3.Connection, cari_id: int) -> int:
    if not _tablo_var(con, TABLO) or not _kolon_var(con, TABLO, 'takip_durumu'):
        return 0
    return int(con.execute(
        f"SELECT COUNT(*) FROM {TABLO} WHERE cari_id=? AND aktif=1 AND takip_durumu='ACIK'",
        (cari_id,),
    ).fetchone()[0] or 0)


def son_gorusme_ozet_map(
    con: sqlite3.Connection,
    cari_ids: list[int],
) -> dict[int, dict[str, Any]]:
    if not cari_ids or not _tablo_var(con, TABLO):
        return {}
    ph = ','.join(['?'] * len(cari_ids))
    rows = con.execute(
        f"""
        SELECT g.*, sk.KullaniciAdi AS kullanici_adi
        FROM {TABLO} g
        LEFT JOIN sistem_kullanici sk ON sk.Id = g.kullanici_id
        WHERE g.cari_id IN ({ph}) AND g.aktif=1
          AND {gerceklesmis_gorusme_tarihi_sql('g')}
        ORDER BY g.gorusme_tarihi DESC, g.id DESC
        """,
        cari_ids,
    ).fetchall()
    out: dict[int, dict] = {}
    for r in rows:
        cid = int(r['cari_id'])
        if cid not in out:
            out[cid] = _row_dict(r)
    return out


def son_gorusmeler_grup(
    con: sqlite3.Connection,
    cari_ids: list[int],
    limit_per_cari: int = 3,
) -> dict[int, list[dict[str, Any]]]:
    if not cari_ids or not _tablo_var(con, TABLO):
        return {}
    ph = ','.join(['?'] * len(cari_ids))
    rows = con.execute(
        f"""
        SELECT g.*, sk.KullaniciAdi AS kullanici_adi
        FROM {TABLO} g
        LEFT JOIN sistem_kullanici sk ON sk.Id = g.kullanici_id
        WHERE g.cari_id IN ({ph}) AND g.aktif=1
          AND {gerceklesmis_gorusme_tarihi_sql('g')}
        ORDER BY g.gorusme_tarihi DESC, g.id DESC
        """,
        cari_ids,
    ).fetchall()
    out: dict[int, list] = {cid: [] for cid in cari_ids}
    for r in rows:
        cid = int(r['cari_id'])
        if len(out.get(cid, [])) < limit_per_cari:
            out.setdefault(cid, []).append(_row_dict(r))
    return out


def sorumlu_pazarlamaci_adi(con, cari_id: int) -> str | None:
    row = con.execute(
        """
        SELECT sk.KullaniciAdi
        FROM cari_sorumlu cs
        JOIN sistem_kullanici sk ON sk.Id = cs.kullanici_id
        WHERE cs.cari_id=? AND cs.sorumluluk_rolu='ANA' AND cs.aktif=1
          AND (cs.bitis_tarihi IS NULL OR cs.bitis_tarihi=''
               OR cs.bitis_tarihi > datetime('now','localtime'))
        LIMIT 1
        """,
        (cari_id,),
    ).fetchone()
    return row['KullaniciAdi'] if row else None


def bugunun_gorusme_sayaclari(
    con: sqlite3.Connection,
    cari_ids: list[int],
) -> dict[str, int]:
    today = _today()
    week_end = (date.today() + timedelta(days=7 - date.today().weekday())).isoformat()
    out = {'bugun_cek': 0, 'bugun_ziyaret': 0, 'bugun_aranacak': 0, 'takip_bugun': 0, 'takip_hafta': 0}
    if not cari_ids or not _tablo_var(con, TABLO):
        return out
    ph = ','.join(['?'] * len(cari_ids))

    out['bugun_ziyaret'] = int(con.execute(
        f"""
        SELECT COUNT(*) FROM {TABLO}
        WHERE cari_id IN ({ph}) AND aktif=1
          AND substr(gorusme_tarihi,1,10)=?
          AND gorusme_tipi IN ({','.join('?' * len(ZIYARET_TIPLERI))})
        """,
        [*cari_ids, today, *ZIYARET_TIPLERI],
    ).fetchone()[0] or 0)

    out['bugun_aranacak'] = int(con.execute(
        f"""
        SELECT COUNT(*) FROM {TABLO}
        WHERE cari_id IN ({ph}) AND aktif=1
          AND sonraki_takip_tarihi=?
          AND gorusme_tipi IN ('Telefon','WhatsApp')
        """,
        [*cari_ids, today],
    ).fetchone()[0] or 0)

    out['bugun_cek'] = int(con.execute(
        f"""
        SELECT COUNT(*) FROM {TABLO}
        WHERE cari_id IN ({ph}) AND aktif=1
          AND (cek_alim_tarihi=? OR (sonraki_takip_tarihi=? AND sonuc_tipi='Çek / Tahsilat Görüşüldü'))
        """,
        [*cari_ids, today, today],
    ).fetchone()[0] or 0)

    out['takip_bugun'] = int(con.execute(
        f"""
        SELECT COUNT(DISTINCT cari_id) FROM {TABLO}
        WHERE cari_id IN ({ph}) AND aktif=1 AND sonraki_takip_tarihi=?
        """,
        [*cari_ids, today],
    ).fetchone()[0] or 0)

    out['takip_hafta'] = int(con.execute(
        f"""
        SELECT COUNT(DISTINCT cari_id) FROM {TABLO}
        WHERE cari_id IN ({ph}) AND aktif=1
          AND sonraki_takip_tarihi > ? AND sonraki_takip_tarihi <= ?
        """,
        [*cari_ids, today, week_end],
    ).fetchone()[0] or 0)

    return out


def _gun_farki(tarih_str: str | None) -> int:
    if not tarih_str:
        return 9999
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
        try:
            dt = datetime.strptime(str(tarih_str)[:19], fmt)
            return max(0, (datetime.now() - dt).days)
        except ValueError:
            continue
    return 9999


def gorusme_oneri_kaynaklari(
    con: sqlite3.Connection,
    cari_ids: list[int],
    cari_map: dict[int, dict],
) -> list[dict[str, Any]]:
    """Akıllı öneriler için görüşme tabanlı kaynaklar."""
    if not cari_ids or not _tablo_var(con, TABLO):
        return []
    today = _today()
    week_end = (date.today() + timedelta(days=7 - date.today().weekday())).isoformat()
    son_map = son_gorusme_ozet_map(con, cari_ids)
    oneriler: list[dict] = []

    for cid in cari_ids:
        info = cari_map.get(cid) or {}
        unvan = info.get('unvan') or '—'
        son = son_map.get(cid)
        if son:
            gun = _gun_farki(son.get('gorusme_tarihi'))
            if gun >= GORUSME_GUN_ESIK:
                oneriler.append({
                    'cari_id': cid, 'musteri': unvan, 'tip': 'gorusme_esik',
                    'surec_tipi': 'Ziyaret',
                    'surec_asama': 'Ziyaret gerekli',
                    'neden': f'Müşteri {gun} gündür ziyaret edilmedi',
                    'aksiyon': 'Görüşme Kaydet',
                })
            takip = (son.get('sonraki_takip_tarihi') or '')[:10]
            if takip == today:
                oneriler.append({
                    'cari_id': cid, 'musteri': unvan, 'tip': 'takip_bugun',
                    'surec_tipi': 'Ziyaret',
                    'surec_asama': 'Takip tarihi bugün',
                    'neden': 'Takip tarihi bugün',
                    'aksiyon': 'Görüşme Kaydet',
                })
            elif takip and today < takip <= week_end:
                oneriler.append({
                    'cari_id': cid, 'musteri': unvan, 'tip': 'takip_hafta',
                    'surec_tipi': 'Ziyaret',
                    'surec_asama': 'Takip bu hafta',
                    'neden': 'Takip tarihi bu hafta',
                    'aksiyon': 'Görüşme Kaydet',
                })

    return oneriler
