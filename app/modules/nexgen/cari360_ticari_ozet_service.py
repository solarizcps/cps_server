# -*- coding: utf-8 -*-
"""
Cari360 Ticari Özet T4 — sipariş snapshot read-model.

Kaynak: nexgen_planlama_siparis + nexgen_planlama_siparis_kalem
JOIN: siparis.cari_id = nexgen_cari.id
Yeni tablo / migration yok. Canlı cari varsayımları kullanılmaz.
"""
from __future__ import annotations

import logging
import sqlite3
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from modules.nexgen.cari360_ops_read_service import Cari360OpsError, _assert_cari, _fmt_dt
from modules.nexgen.cari_sorumlu_service import can_view_cari_ticari
from modules.nexgen.pzm_siparis_read import pzm_payload_unpack, pzm_siparis_tarihi_coz
from modules.nexgen.pzm_siparis_write import pzm_ticari_miktar_kg

logger = logging.getLogger(__name__)

# Merkezi whitelist — bilinmeyen durum sessizce dahil edilmez.
TICARI_OZET_DURUM_DAHIL: frozenset[str] = frozenset({
    'ONAY_BEKLIYOR',
    'ONAYLANDI',
    'TALEP',
    'MPR_BEKLIYOR',
    'PLANLAMAYA_HAZIR',
    'URETIMDE',
    'SEVK_BEKLIYOR',
    'KISMI_SEVK',
    'SEVK_EDILDI',
    'TAMAMLANDI',
})

TICARI_OZET_DURUM_HARIC: frozenset[str] = frozenset({
    'TASLAK',
    'REVIZYON',
    'REDDEDILDI',
    'IPTAL',
    'IPTAL_EDILDI',
    'IPTALEDILDI',
})

PARA_BIRIMI_WHITELIST: frozenset[str] = frozenset({'TRY', 'USD', 'EUR', 'GBP'})

_URUN_LIMIT_DEFAULT = 10
_SON_SIPARIS_LIMIT = 20
_MAX_SIPARIS = 500


def _tablo_var(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,),
    ).fetchone())


def _cols(con: sqlite3.Connection, table: str) -> set[str]:
    return {c[1] for c in con.execute(f'PRAGMA table_info({table})').fetchall()}


def _dec(v: Any) -> Decimal | None:
    if v is None or v == '':
        return None
    try:
        d = Decimal(str(v).strip().replace(' ', '').replace(',', '.'))
    except (InvalidOperation, ValueError, AttributeError):
        return None
    if not d.is_finite():
        return None
    return d


def _dec_str(d: Decimal | None, places: str = '0.0001') -> str | None:
    if d is None:
        return None
    return format(d.quantize(Decimal(places), rounding=ROUND_HALF_UP), 'f')


def _dec_str_qty(d: Decimal | None) -> str | None:
    return _dec_str(d, '0.001')


def durum_ticari_ozete_dahil(durum: Any) -> bool:
    d = (str(durum or '')).strip().upper()
    if not d:
        return False
    if d.startswith('IPTAL'):
        return False
    if d in TICARI_OZET_DURUM_HARIC:
        return False
    return d in TICARI_OZET_DURUM_DAHIL


def _normalize_pb(raw: Any) -> str:
    pb = (str(raw or '')).strip().upper()
    if not pb:
        return 'BELIRTILMEMIS'
    if pb in PARA_BIRIMI_WHITELIST:
        return pb
    return 'DIGER'


def _vade_gun_deger(odeme_tipi: str | None, vade_gun: Any) -> int | None:
    if odeme_tipi == 'NAKIT':
        return 0
    if odeme_tipi != 'VADELI':
        return None
    if vade_gun in (None, ''):
        return None
    try:
        return int(vade_gun)
    except (TypeError, ValueError):
        return None


def _normalize_odeme_tipi_raw(raw: Any) -> str | None:
    """Canonical odeme_tipi normalize — NULL/boş → None."""
    if raw in (None, ''):
        return None
    ot = str(raw).strip().upper()
    if ot == 'ÇEK':
        ot = 'CEK'
    return ot or None


def sinifla_odeme_tipi_sayac(raw: Any) -> str:
    """
    Ticari özet ödeme bucket.
    Dönüş: nakit | vadeli | cek | legacy | bilinmeyen
    """
    ot = _normalize_odeme_tipi_raw(raw)
    if ot is None:
        return 'legacy'
    if ot == 'NAKIT':
        return 'nakit'
    if ot == 'VADELI':
        return 'vadeli'
    if ot == 'CEK':
        return 'cek'
    return 'bilinmeyen'


def _urun_anahtari(
    formul_id: Any,
    rf_renk_id: Any,
    renk_varyant_id: Any,
    formul_ad: Any,
    renk_ad: Any,
    urun_ailesi: Any,
    para_birimi: str,
) -> tuple[str, str]:
    """
    Dönüş: (anahtar, kaynak_modu)
    Öncelik: formul_id + rf/renk + pb; yoksa teknik ad fallback.
    """
    fid = None
    if formul_id not in (None, ''):
        try:
            fid = int(formul_id)
        except (TypeError, ValueError):
            fid = None
    rid = None
    for cand in (rf_renk_id, renk_varyant_id):
        if rid is not None:
            break
        if cand in (None, ''):
            continue
        try:
            rid = int(cand)
        except (TypeError, ValueError):
            rid = None
    pb = para_birimi or 'BELIRTILMEMIS'
    if fid is not None:
        key = f'F{fid}|R{rid if rid is not None else "-"}|{pb}'
        return key, 'FORMUL_RF_PB'
    ad = (str(formul_ad or '').strip() or str(urun_ailesi or '').strip() or 'URUN')
    renk = (str(renk_ad or '').strip() or (f'R{rid}' if rid is not None else '-'))
    key = f'N{ad}|{renk}|{pb}'
    return key, 'AD_RENK_PB'


def _siparis_sort_key(tarih: str | None, siparis_id: int) -> tuple:
    return (tarih or '', siparis_id)


def load_cari360_ticari_ozet(
    con: sqlite3.Connection,
    cari_id: int,
    kullanici_id: int,
    yk: set[str] | None,
    *,
    urun_limit: int = _URUN_LIMIT_DEFAULT,
) -> dict[str, Any]:
    """
    Ticari Özet read-model.
    - Cari erişimi yok → 403
    - Cari yok → 404
    - Ticari yetki yok → 403 (hassas endpoint)
    """
    cari = _assert_cari(con, cari_id, kullanici_id, yk)
    if not can_view_cari_ticari(con, kullanici_id, int(cari_id), yk):
        raise Cari360OpsError('Bu cari için ticari özet görüntüleme yetkiniz yok.', 403)

    cid = int(cari['id'])
    urun_limit = max(1, min(int(urun_limit or _URUN_LIMIT_DEFAULT), 50))

    empty = {
        'cari': cari,
        'ticari_gorunur': True,
        'ticari_ozet': {
            'siparis_adedi': 0,
            'son_siparis_tarihi': None,
            'son_siparis_no': None,
            'son_siparis_durumu': None,
            'nakit_adet': 0,
            'vadeli_adet': 0,
            'cek_adet': 0,
            'legacy_odeme_yok_adet': 0,
            'bilinmeyen_odeme_adet': 0,
            'belirtilmemis_odeme_adet': 0,
            'ortalama_vade_gun': None,
            'min_vade_gun': None,
            'max_vade_gun': None,
            'son_siparis_vade_gun': None,
            'toplam_siparis_try': None,
            'toplam_siparis_para_birimleri': {},
            'para_birimi_dagilimi': {},
            'fiyatli_kalem_adedi': 0,
            'fiyatsiz_kalem_adedi': 0,
            'nakit_toplam_try': None,
            'vadeli_toplam_try': None,
            'mesaj': 'Henüz ticari sipariş kaydı yok.',
            'eski_veri_uyarisi': False,
        },
        'urun_fiyatlari': [],
        'son_siparisler': [],
        'bilinmeyen_durumlar': [],
        'urun_anahtari_modu': 'FORMUL_RF_PB',
    }

    if not _tablo_var(con, 'nexgen_planlama_siparis'):
        return empty

    scols = _cols(con, 'nexgen_planlama_siparis')
    has_kalem = _tablo_var(con, 'nexgen_planlama_siparis_kalem')
    kcols = _cols(con, 'nexgen_planlama_siparis_kalem') if has_kalem else set()

    sel = [
        'id', 'siparis_no', 'durum', 'olusturma_tarihi', 'talep_referansi',
        'anlasma_para_birimi', 'anlasma_birim_fiyat',
    ]
    for col in ('odeme_tipi', 'vade_gun', 'cek_vade_gun', 'kur', 'kur_tarihi', 'kur_kaynagi'):
        if col in scols:
            sel.append(col)

    # Whitelist SQL'de uygulanır (TASLAK yoğunluğunda LIMIT kaçırmasın).
    dahil_list = sorted(TICARI_OZET_DURUM_DAHIL)
    dahil_ph = ','.join('?' * len(dahil_list))
    rows = con.execute(
        f"""
        SELECT {', '.join(sel)}
        FROM nexgen_planlama_siparis
        WHERE cari_id=?
          AND UPPER(TRIM(IFNULL(durum,''))) IN ({dahil_ph})
        ORDER BY id DESC
        LIMIT ?
        """,
        (cid, *dahil_list, _MAX_SIPARIS),
    ).fetchall()

    # Bilinmeyen durum adedi (analize alınmayanlar) — ayrı sayım
    bilinmeyen: dict[str, int] = {}
    for br in con.execute(
        """
        SELECT UPPER(TRIM(IFNULL(durum,''))) AS d, COUNT(*) AS n
        FROM nexgen_planlama_siparis
        WHERE cari_id=?
        GROUP BY UPPER(TRIM(IFNULL(durum,'')))
        """,
        (cid,),
    ).fetchall():
        d = br['d'] or ''
        if not d or d in TICARI_OZET_DURUM_HARIC or d.startswith('IPTAL'):
            continue
        if d not in TICARI_OZET_DURUM_DAHIL:
            bilinmeyen[d] = int(br['n'] or 0)

    headers: list[dict[str, Any]] = []
    for r in rows:
        durum = (r['durum'] or '').strip().upper()
        if not durum_ticari_ozete_dahil(durum):
            continue
        payload = pzm_payload_unpack(r['talep_referansi'] if 'talep_referansi' in scols else None)
        tarih = pzm_siparis_tarihi_coz(payload, r['olusturma_tarihi'])
        # cek_vade_gun: DB kolon öncelikli, yoksa talep_referansi JSON fallback
        _cvg_raw = r['cek_vade_gun'] if 'cek_vade_gun' in scols else None
        if _cvg_raw in (None, ''):
            _cvg_json = (payload or {}).get('cek_vade_gun')
            if _cvg_json not in (None, ''):
                try:
                    _cvg_raw = int(_cvg_json)
                except (TypeError, ValueError):
                    _cvg_raw = None
        _ot_h = (r['odeme_tipi'] if 'odeme_tipi' in scols else None)
        _ot_h_str = (str(_ot_h).strip().upper() if _ot_h not in (None, '') else None)
        headers.append({
            'id': int(r['id']),
            'siparis_no': r['siparis_no'] or '',
            'durum': durum,
            'tarih': tarih,
            'olusturma_tarihi': r['olusturma_tarihi'],
            'odeme_tipi': _ot_h_str,
            'vade_gun': r['vade_gun'] if 'vade_gun' in scols else None,
            'cek_vade_gun': _cvg_raw,
            'para_birimi': _normalize_pb(r['anlasma_para_birimi']),
            'kur': _dec(r['kur']) if 'kur' in scols else None,
            'kur_kaynagi': (r['kur_kaynagi'] if 'kur_kaynagi' in scols else None),
            'anlasma_birim_fiyat': _dec(r['anlasma_birim_fiyat']),
        })

    if bilinmeyen:
        logger.info(
            'cari360_ticari_ozet bilinmeyen_durum cari_id=%s %s',
            cid, bilinmeyen,
        )

    if not headers:
        empty['bilinmeyen_durumlar'] = [
            {'durum': k, 'adet': v} for k, v in sorted(bilinmeyen.items())
        ]
        return empty

    headers.sort(key=lambda h: _siparis_sort_key(h['tarih'], h['id']), reverse=True)
    siparis_ids = [h['id'] for h in headers]

    kalemler_by_sip: dict[int, list[dict[str, Any]]] = {sid: [] for sid in siparis_ids}
    if has_kalem and siparis_ids:
        placeholders = ','.join('?' * len(siparis_ids))
        ksel = [
            'id', 'planlama_siparis_id', 'formul_id', 'formul_ad',
            'renk_varyant_id', 'renk_ad', 'rf_renk_id',
            'miktar_l', 'miktar_s', 'miktar_m',
        ]
        if 'urun_ailesi' in kcols:
            ksel.append('urun_ailesi')
        for col in (
            'birim_fiyat', 'iskonto_orani', 'iskonto_tutari',
            'net_birim_fiyat', 'satir_tutari',
            'net_birim_fiyat_try', 'satir_tutari_try',
        ):
            if col in kcols:
                ksel.append(col)
        krows = con.execute(
            f"""
            SELECT {', '.join(ksel)}
            FROM nexgen_planlama_siparis_kalem
            WHERE planlama_siparis_id IN ({placeholders})
            ORDER BY planlama_siparis_id ASC, id ASC
            """,
            siparis_ids,
        ).fetchall()
        for kr in krows:
            sid = int(kr['planlama_siparis_id'])
            if sid not in kalemler_by_sip:
                continue
            miktar = pzm_ticari_miktar_kg(kr['miktar_l'], kr['miktar_s'], kr['miktar_m'])
            if miktar < 0:
                logger.warning(
                    'cari360_ticari_ozet negatif_miktar siparis=%s kalem=%s',
                    sid, kr['id'],
                )
                continue
            kalemler_by_sip[sid].append({
                'id': int(kr['id']),
                'formul_id': kr['formul_id'],
                'formul_ad': kr['formul_ad'],
                'renk_varyant_id': kr['renk_varyant_id'],
                'renk_ad': kr['renk_ad'],
                'rf_renk_id': kr['rf_renk_id'],
                'urun_ailesi': kr['urun_ailesi'] if 'urun_ailesi' in kr.keys() else None,
                'miktar': miktar,
                'birim_fiyat': _dec(kr['birim_fiyat']) if 'birim_fiyat' in kcols else None,
                'iskonto_orani': _dec(kr['iskonto_orani']) if 'iskonto_orani' in kcols else None,
                'net_birim_fiyat': _dec(kr['net_birim_fiyat']) if 'net_birim_fiyat' in kcols else None,
                'satir_tutari': _dec(kr['satir_tutari']) if 'satir_tutari' in kcols else None,
                'satir_tutari_try': _dec(kr['satir_tutari_try']) if 'satir_tutari_try' in kcols else None,
            })

    # --- sipariş seviyesinde fiyat durumu / toplamlar ---
    son_siparisler: list[dict[str, Any]] = []
    nakit_adet = vadeli_adet = cek_adet = 0
    legacy_odeme_yok_adet = bilinmeyen_odeme_adet = 0
    vade_list: list[int] = []
    toplam_try = Decimal('0')
    has_try_total = False
    nakit_try = Decimal('0')
    vadeli_try = Decimal('0')
    has_nakit_try = False
    has_vadeli_try = False
    pb_orijinal: dict[str, Decimal] = {}
    pb_try: dict[str, Decimal] = {}
    pb_meta: dict[str, dict[str, Any]] = {}
    fiyatli_kalem = fiyatsiz_kalem = 0
    eski_veri_uyarisi = False

    # ürün grupları
    urun_groups: dict[str, dict[str, Any]] = {}

    for h in headers:
        sid = h['id']
        kals = kalemler_by_sip.get(sid) or []
        pb = h['para_birimi']
        ot_raw = h['odeme_tipi']
        ot = (str(ot_raw).strip().upper() if ot_raw not in (None, '') else None)

        bucket = sinifla_odeme_tipi_sayac(ot_raw)
        if bucket == 'nakit':
            nakit_adet += 1
        elif bucket == 'vadeli':
            vadeli_adet += 1
            vg = h['vade_gun']
            try:
                vg_i = int(vg) if vg not in (None, '') else None
            except (TypeError, ValueError):
                vg_i = None
            if vg_i is not None and vg_i >= 1:
                vade_list.append(vg_i)
        elif bucket == 'cek':
            cek_adet += 1
        elif bucket == 'legacy':
            legacy_odeme_yok_adet += 1
        else:
            bilinmeyen_odeme_adet += 1

        fiyatli_n = 0
        fiyatsiz_n = 0
        sip_orijinal = Decimal('0')
        sip_orijinal_ok = True
        sip_try = Decimal('0')
        sip_try_ok = False
        has_eski = False
        has_snapshot = False

        for k in kals:
            bf = k['birim_fiyat']
            if bf is not None:
                fiyat_kaynagi = 'KALEM_SNAPSHOT'
                net = k['net_birim_fiyat']
                iskonto = k['iskonto_orani']
                satir = k['satir_tutari']
                satir_try = k['satir_tutari_try']
                has_snapshot = True
                fiyatli_n += 1
                fiyatli_kalem += 1
            elif len(kals) == 1 and h['anlasma_birim_fiyat'] is not None:
                fiyat_kaynagi = 'ESKI_BASLIK_FIYATI'
                bf = h['anlasma_birim_fiyat']
                net = None  # iskonto bilinmiyor — net varsayma
                iskonto = None
                satir = None
                if k['miktar'] > 0:
                    # işaretli tahmini satır (sipariş satırında ayrı etiket)
                    satir = (k['miktar'] * bf).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
                satir_try = None
                has_eski = True
                eski_veri_uyarisi = True
                fiyatli_n += 1
                fiyatli_kalem += 1
            else:
                fiyat_kaynagi = 'BELIRTILMEMIS'
                if len(kals) > 1 and h['anlasma_birim_fiyat'] is not None and bf is None:
                    eski_veri_uyarisi = True
                fiyatsiz_n += 1
                fiyatsiz_kalem += 1
                net = None
                iskonto = None
                satir = None
                satir_try = None

            if fiyat_kaynagi == 'KALEM_SNAPSHOT' and satir is not None:
                sip_orijinal += satir
            elif fiyat_kaynagi == 'ESKI_BASLIK_FIYATI' and satir is not None:
                sip_orijinal += satir
            elif fiyat_kaynagi == 'BELIRTILMEMIS':
                sip_orijinal_ok = False

            if fiyat_kaynagi == 'KALEM_SNAPSHOT' and satir_try is not None:
                sip_try += satir_try
                sip_try_ok = True

            # ürün grubu — yalnız fiyatlı kaynaklar
            if fiyat_kaynagi in ('KALEM_SNAPSHOT', 'ESKI_BASLIK_FIYATI') and bf is not None:
                ukey, umode = _urun_anahtari(
                    k['formul_id'], k['rf_renk_id'], k['renk_varyant_id'],
                    k['formul_ad'], k['renk_ad'], k['urun_ailesi'], pb,
                )
                g = urun_groups.get(ukey)
                if g is None:
                    g = {
                        'urun_anahtari': ukey,
                        'urun_anahtari_modu': umode,
                        'urun_adi': (k['formul_ad'] or k['urun_ailesi'] or 'Ürün'),
                        'formul_id': int(k['formul_id']) if k['formul_id'] not in (None, '') else None,
                        'formul_adi': k['formul_ad'],
                        'renk_id': (
                            int(k['rf_renk_id']) if k['rf_renk_id'] not in (None, '')
                            else (int(k['renk_varyant_id']) if k['renk_varyant_id'] not in (None, '') else None)
                        ),
                        'renk_adi': k['renk_ad'],
                        'rf_id': int(k['rf_renk_id']) if k['rf_renk_id'] not in (None, '') else None,
                        'para_birimi': pb,
                        'son_birim_fiyat': None,
                        'son_net_birim_fiyat': None,
                        'son_iskonto_orani': None,
                        'son_iskonto_belirtilmemis': False,
                        'min_net_fiyat': None,
                        'max_net_fiyat': None,
                        'agirlikli_pay': Decimal('0'),
                        'agirlikli_kg': Decimal('0'),
                        'agirlikli_try_pay': Decimal('0'),
                        'agirlikli_try_kg': Decimal('0'),
                        'son_siparis_id': None,
                        'son_siparis_no': None,
                        'son_siparis_tarihi': None,
                        'son_vade_gun': None,
                        'son_odeme_tipi': None,
                        'son_gosterilecek_vade_gun': None,
                        'fiyat_kaynagi': None,
                        'toplam_miktar_kg': Decimal('0'),
                        'siparis_ids': set(),
                        'snapshot_nets': [],
                    }
                    urun_groups[ukey] = g
                g['toplam_miktar_kg'] += k['miktar']
                g['siparis_ids'].add(sid)
                sk = _siparis_sort_key(h['tarih'], sid)
                cur_sk = _siparis_sort_key(g['son_siparis_tarihi'], g['son_siparis_id'] or 0)
                if g['son_siparis_id'] is None or sk > cur_sk:
                    g['son_siparis_id'] = sid
                    g['son_siparis_no'] = h['siparis_no']
                    g['son_siparis_tarihi'] = h['tarih']
                    g['son_birim_fiyat'] = bf
                    g['son_net_birim_fiyat'] = net if net is not None else None
                    g['son_iskonto_orani'] = iskonto
                    g['son_iskonto_belirtilmemis'] = (fiyat_kaynagi == 'ESKI_BASLIK_FIYATI')
                    g['fiyat_kaynagi'] = fiyat_kaynagi
                    g['son_odeme_tipi'] = ot
                    # canonical vade resolver — enrich_siparis_listesi_ticari ile aynı mantık
                    if ot == 'CEK':
                        _cvg = h.get('cek_vade_gun')
                        try:
                            g['son_vade_gun'] = int(_cvg) if _cvg not in (None, '') else None
                        except (TypeError, ValueError):
                            g['son_vade_gun'] = None
                        g['son_gosterilecek_vade_gun'] = g['son_vade_gun']
                    elif ot == 'VADELI':
                        _vg = h['vade_gun']
                        try:
                            g['son_vade_gun'] = int(_vg) if _vg not in (None, '') else None
                        except (TypeError, ValueError):
                            g['son_vade_gun'] = None
                        g['son_gosterilecek_vade_gun'] = g['son_vade_gun']
                    else:
                        g['son_vade_gun'] = 0 if ot == 'NAKIT' else None
                        g['son_gosterilecek_vade_gun'] = None

                # min/max/ağırlıklı: yalnız KALEM_SNAPSHOT + net + miktar>0
                if fiyat_kaynagi == 'KALEM_SNAPSHOT' and net is not None and k['miktar'] > 0:
                    g['snapshot_nets'].append(net)
                    g['agirlikli_pay'] += (k['miktar'] * net)
                    g['agirlikli_kg'] += k['miktar']
                    if k['satir_tutari_try'] is not None:
                        g['agirlikli_try_pay'] += k['satir_tutari_try']
                        g['agirlikli_try_kg'] += k['miktar']

        if fiyatli_n == 0:
            fiyat_durumu = 'BELIRTILMEMIS'
            toplam_tutar = None
        elif fiyatsiz_n > 0:
            fiyat_durumu = 'KISMI'
            toplam_tutar = _dec_str(sip_orijinal) if sip_orijinal_ok and fiyatli_n else None
            # kısmi → tam toplam gibi sunma
            if fiyatsiz_n:
                toplam_tutar = _dec_str(sip_orijinal)  # bilinen kısım; UI KISMI etiketi
        elif has_eski and not has_snapshot:
            fiyat_durumu = 'ESKI_BASLIK_FIYATI'
            toplam_tutar = _dec_str(sip_orijinal)
        else:
            fiyat_durumu = 'TAM'
            toplam_tutar = _dec_str(sip_orijinal)

        toplam_tutar_try = _dec_str(sip_try) if sip_try_ok else None

        if sip_try_ok:
            toplam_try += sip_try
            has_try_total = True
            if ot == 'NAKIT':
                nakit_try += sip_try
                has_nakit_try = True
            elif ot == 'VADELI':
                vadeli_try += sip_try
                has_vadeli_try = True

        if toplam_tutar is not None and pb in PARA_BIRIMI_WHITELIST:
            pb_orijinal[pb] = pb_orijinal.get(pb, Decimal('0')) + Decimal(toplam_tutar)
        if toplam_tutar_try is not None and pb in PARA_BIRIMI_WHITELIST:
            pb_try[pb] = pb_try.get(pb, Decimal('0')) + Decimal(toplam_tutar_try)

        meta = pb_meta.setdefault(pb, {
            'siparis_adedi': 0,
            'fiyatli_siparis_adedi': 0,
            'son_siparis_tarihi': None,
        })
        meta['siparis_adedi'] += 1
        if fiyat_durumu in ('TAM', 'KISMI', 'ESKI_BASLIK_FIYATI'):
            meta['fiyatli_siparis_adedi'] += 1
        if meta['son_siparis_tarihi'] is None or (h['tarih'] or '') > (meta['son_siparis_tarihi'] or ''):
            meta['son_siparis_tarihi'] = h['tarih']

        son_siparisler.append({
            'siparis_id': sid,
            'siparis_no': h['siparis_no'],
            'tarih': h['tarih'],
            'durum': h['durum'],
            'odeme_tipi': ot or 'BELIRTILMEMIS',
            'vade_gun': _vade_gun_deger(ot, h['vade_gun']),
            'para_birimi': pb,
            'kur': _dec_str(h['kur']),
            'kur_kaynagi': h['kur_kaynagi'],
            'toplam_tutar': toplam_tutar,
            'toplam_tutar_try': toplam_tutar_try,
            'kalem_adedi': len(kals),
            'fiyatli_kalem_adedi': fiyatli_n,
            'fiyat_durumu': fiyat_durumu,
            'detay_url': f'/nexgen/pazarlama?siparis={sid}',
        })

    # vade özeti
    ortalama_vade = None
    min_vade = max_vade = None
    if vade_list:
        min_vade = min(vade_list)
        max_vade = max(vade_list)
        ortalama_vade = str(
            (Decimal(sum(vade_list)) / Decimal(len(vade_list)))
            .quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        )

    son = headers[0]
    son_vade = None
    son_ot = (str(son['odeme_tipi']).strip().upper() if son['odeme_tipi'] not in (None, '') else None)
    if son_ot == 'NAKIT':
        son_vade = 0
    elif son_ot == 'VADELI' and son['vade_gun'] not in (None, ''):
        try:
            son_vade = int(son['vade_gun'])
        except (TypeError, ValueError):
            son_vade = None

    para_dagilim: dict[str, Any] = {}
    for pb, meta in pb_meta.items():
        para_dagilim[pb] = {
            'siparis_adedi': meta['siparis_adedi'],
            'fiyatli_siparis_adedi': meta['fiyatli_siparis_adedi'],
            'toplam_orijinal_tutar': _dec_str(pb_orijinal.get(pb)),
            'toplam_try': _dec_str(pb_try.get(pb)),
            'son_siparis_tarihi': meta['son_siparis_tarihi'],
        }

    toplam_pb = {pb: _dec_str(v) for pb, v in pb_orijinal.items()}

    mesaj = None
    if not headers:
        mesaj = 'Henüz ticari sipariş kaydı yok.'
    elif fiyatli_kalem == 0:
        mesaj = 'Sipariş mevcut; ticari fiyat snapshot’ı bulunmuyor.'
    elif eski_veri_uyarisi and fiyatli_kalem > 0:
        mesaj = 'Eski sipariş verileri sınırlı olabilir.'

    # ürün fiyat listesi
    urun_list: list[dict[str, Any]] = []
    for g in urun_groups.values():
        nets = g['snapshot_nets']
        min_n = min(nets) if nets else None
        max_n = max(nets) if nets else None
        # Eski-only grup: min/max = son birim (ayrı kaynak)
        if min_n is None and g['fiyat_kaynagi'] == 'ESKI_BASLIK_FIYATI' and g['son_birim_fiyat'] is not None:
            min_n = g['son_birim_fiyat']
            max_n = g['son_birim_fiyat']
        w_avg = None
        if g['agirlikli_kg'] > 0:
            w_avg = (g['agirlikli_pay'] / g['agirlikli_kg']).quantize(
                Decimal('0.0001'), rounding=ROUND_HALF_UP,
            )
        w_avg_try = None
        if g['agirlikli_try_kg'] > 0:
            w_avg_try = (g['agirlikli_try_pay'] / g['agirlikli_try_kg']).quantize(
                Decimal('0.0001'), rounding=ROUND_HALF_UP,
            )
        urun_list.append({
            'urun_anahtari': g['urun_anahtari'],
            'urun_adi': g['urun_adi'],
            'formul_id': g['formul_id'],
            'formul_adi': g['formul_adi'],
            'renk_id': g['renk_id'],
            'renk_adi': g['renk_adi'],
            'rf_id': g['rf_id'],
            'rf_kodu': None,
            'para_birimi': g['para_birimi'],
            'son_birim_fiyat': _dec_str(g['son_birim_fiyat']),
            'son_net_birim_fiyat': _dec_str(g['son_net_birim_fiyat']),
            'son_iskonto_orani': (
                'BELIRTILMEMIS' if g['son_iskonto_belirtilmemis']
                else _dec_str(g['son_iskonto_orani'])
            ),
            'min_net_fiyat': _dec_str(min_n),
            'max_net_fiyat': _dec_str(max_n),
            'agirlikli_ortalama_net_fiyat': _dec_str(w_avg),
            'agirlikli_ortalama_net_fiyat_try': _dec_str(w_avg_try),
            'son_siparis_id': g['son_siparis_id'],
            'son_siparis_no': g['son_siparis_no'],
            'son_siparis_tarihi': g['son_siparis_tarihi'],
            'son_odeme_tipi': g['son_odeme_tipi'],
            'son_vade_gun': g['son_vade_gun'],
            'son_gosterilecek_vade_gun': g['son_gosterilecek_vade_gun'],
            'fiyat_kaynagi': g['fiyat_kaynagi'],
            'toplam_miktar_kg': _dec_str_qty(g['toplam_miktar_kg']),
            'siparis_adedi': len(g['siparis_ids']),
            'detay_url': (
                f"/nexgen/pazarlama?siparis={g['son_siparis_id']}"
                if g['son_siparis_id'] else None
            ),
        })

    urun_list.sort(
        key=lambda u: (u.get('son_siparis_tarihi') or '', u.get('son_siparis_id') or 0),
        reverse=True,
    )
    urun_list = urun_list[:urun_limit]

    return {
        'cari': cari,
        'ticari_gorunur': True,
        'ticari_ozet': {
            'siparis_adedi': len(headers),
            'son_siparis_tarihi': son['tarih'],
            'son_siparis_no': son['siparis_no'],
            'son_siparis_durumu': son['durum'],
            'nakit_adet': nakit_adet,
            'vadeli_adet': vadeli_adet,
            'cek_adet': cek_adet,
            'legacy_odeme_yok_adet': legacy_odeme_yok_adet,
            'bilinmeyen_odeme_adet': bilinmeyen_odeme_adet,
            'belirtilmemis_odeme_adet': bilinmeyen_odeme_adet,
            'ortalama_vade_gun': ortalama_vade,
            'min_vade_gun': min_vade,
            'max_vade_gun': max_vade,
            'son_siparis_vade_gun': son_vade,
            'toplam_siparis_try': _dec_str(toplam_try) if has_try_total else None,
            'toplam_siparis_para_birimleri': toplam_pb,
            'para_birimi_dagilimi': para_dagilim,
            'fiyatli_kalem_adedi': fiyatli_kalem,
            'fiyatsiz_kalem_adedi': fiyatsiz_kalem,
            'nakit_toplam_try': _dec_str(nakit_try) if has_nakit_try else None,
            'vadeli_toplam_try': _dec_str(vadeli_try) if has_vadeli_try else None,
            'mesaj': mesaj,
            'eski_veri_uyarisi': eski_veri_uyarisi,
            'toplam_kaynak_notu': (
                'Kayıtlı ticari toplam (TRY snapshot). Eksik eski kayıtlar dahil olmayabilir.'
                if has_try_total else None
            ),
        },
        'urun_fiyatlari': urun_list,
        'son_siparisler': son_siparisler[:_SON_SIPARIS_LIMIT],
        'bilinmeyen_durumlar': [
            {'durum': k, 'adet': v} for k, v in sorted(bilinmeyen.items())
        ],
        'urun_anahtari_modu': 'FORMUL_RF_PB',
    }


def enrich_siparis_listesi_ticari(
    con: sqlite3.Connection,
    liste: list[dict[str, Any]],
    *,
    ticari_gorunur: bool,
) -> list[dict[str, Any]]:
    """Sipariş geçmişi satırlarına ticari alan ekler (toplu). Yetkisizde eklemez."""
    if not liste or not ticari_gorunur:
        for item in liste:
            item['ticari_gorunur'] = False
        return liste

    ids = [int(x['id']) for x in liste if x.get('id')]
    if not ids or not _tablo_var(con, 'nexgen_planlama_siparis'):
        return liste

    scols = _cols(con, 'nexgen_planlama_siparis')
    placeholders = ','.join('?' * len(ids))
    sel = ['id', 'anlasma_para_birimi', 'anlasma_birim_fiyat', 'talep_referansi', 'olusturma_tarihi']
    for col in ('odeme_tipi', 'vade_gun', 'kur', 'kur_kaynagi', 'cek_vadesi', 'cek_vade_gun'):
        if col in scols:
            sel.append(col)
    rows = {
        int(r['id']): r
        for r in con.execute(
            f"SELECT {', '.join(sel)} FROM nexgen_planlama_siparis WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
    }

    kcols = _cols(con, 'nexgen_planlama_siparis_kalem') if _tablo_var(
        con, 'nexgen_planlama_siparis_kalem'
    ) else set()
    sums: dict[int, dict[str, Any]] = {}
    if 'birim_fiyat' in kcols:
        has_st = 'satir_tutari' in kcols
        has_st_try = 'satir_tutari_try' in kcols
        # TRY/orijinal toplam yalnız birim_fiyat snapshot satırlarından (stale TRY hariç)
        st_expr = (
            'SUM(CASE WHEN birim_fiyat IS NOT NULL THEN satir_tutari END)'
            if has_st else 'NULL'
        )
        st_try_expr = (
            'SUM(CASE WHEN birim_fiyat IS NOT NULL THEN satir_tutari_try END)'
            if has_st_try else 'NULL'
        )
        krows = con.execute(
            f"""
            SELECT planlama_siparis_id,
                   COUNT(*) AS kalem_n,
                   SUM(CASE WHEN birim_fiyat IS NOT NULL THEN 1 ELSE 0 END) AS fiyatli_n,
                   {st_expr} AS toplam_tutar,
                   {st_try_expr} AS toplam_try
            FROM nexgen_planlama_siparis_kalem
            WHERE planlama_siparis_id IN ({placeholders})
            GROUP BY planlama_siparis_id
            """,
            ids,
        ).fetchall()
        for kr in krows:
            sums[int(kr['planlama_siparis_id'])] = dict(kr)

    for item in liste:
        sid = int(item['id'])
        r = rows.get(sid)
        item['ticari_gorunur'] = True
        if not r:
            continue
        payload = pzm_payload_unpack(r['talep_referansi'])
        item['siparis_tarihi'] = _fmt_dt(pzm_siparis_tarihi_coz(payload, r['olusturma_tarihi']))
        kdv_raw = (payload or {}).get('kdv_durumu')
        item['kdv_durumu'] = (
            str(kdv_raw).strip().upper() if kdv_raw not in (None, '') else None
        )
        ot = r['odeme_tipi'] if 'odeme_tipi' in scols else None
        item['odeme_tipi'] = (str(ot).strip().upper() if ot not in (None, '') else None)
        item['vade_gun'] = r['vade_gun'] if 'vade_gun' in scols else None
        item['cek_vadesi'] = (r['cek_vadesi'] if 'cek_vadesi' in scols else None)
        # cek_vade_gun: DB kolonu varsa oradan, yoksa talep_referansi JSON snapshot'tan
        cvg_raw = r['cek_vade_gun'] if 'cek_vade_gun' in scols else None
        if cvg_raw in (None, ''):
            _pl = payload or pzm_payload_unpack(r['talep_referansi'])
            _cvg_json = (_pl or {}).get('cek_vade_gun')
            if _cvg_json not in (None, ''):
                try:
                    cvg_raw = int(_cvg_json)
                except (TypeError, ValueError):
                    cvg_raw = None
        item['cek_vade_gun'] = cvg_raw
        # gosterilecek_vade_gun: backend canonical resolve — UI business logic üretmez
        _ot = item['odeme_tipi']
        if _ot == 'CEK':
            item['gosterilecek_vade_gun'] = cvg_raw
        elif _ot == 'VADELI':
            _vg = item['vade_gun']
            item['gosterilecek_vade_gun'] = (int(_vg) if _vg not in (None, '') else None)
        else:
            item['gosterilecek_vade_gun'] = None
        item['para_birimi'] = _normalize_pb(r['anlasma_para_birimi'])
        item['kur'] = str(r['kur']) if 'kur' in scols and r['kur'] not in (None, '') else None
        sm = sums.get(sid) or {}
        kn = int(sm.get('kalem_n') or 0)
        fn = int(sm.get('fiyatli_n') or 0)
        if fn == 0 and r['anlasma_birim_fiyat'] not in (None, '') and kn == 1:
            item['fiyat_durumu'] = 'ESKI_BASLIK_FIYATI'
            item['anlasma_birim_fiyat'] = _dec_str(_dec(r['anlasma_birim_fiyat']))
            item['toplam_tutar'] = None
            item['toplam_tutar_try'] = None
        elif fn == 0:
            item['fiyat_durumu'] = 'BELIRTILMEMIS'
            item['anlasma_birim_fiyat'] = None
            item['toplam_tutar'] = None
            item['toplam_tutar_try'] = None
        elif fn < kn:
            item['fiyat_durumu'] = 'KISMI'
            item['toplam_tutar'] = _dec_str(_dec(sm.get('toplam_tutar')))
            item['toplam_tutar_try'] = _dec_str(_dec(sm.get('toplam_try')))
        else:
            item['fiyat_durumu'] = 'TAM'
            item['toplam_tutar'] = _dec_str(_dec(sm.get('toplam_tutar')))
            item['toplam_tutar_try'] = _dec_str(_dec(sm.get('toplam_try')))
    return liste
