# -*- coding: utf-8 -*-
"""
Müşteri sevkiyat operasyon ekranı — liste / sevkiyata hazır sipariş mantığı.

SEVKİYATA HAZIR KURALI (MVP — raporlanmış):
- Sipariş durumu: ONAYLANDI, MPR_BEKLIYOR, PLANLAMAYA_HAZIR, URETIMDE, TAMAMLANDI
- Hariç: TASLAK, ONAY_BEKLIYOR, REVIZYON, REDDEDILDI, IPTAL
- Kalan sevk miktarı > 0 (mo_musteri_sevkiyat_kalem toplamı)
- Üretilen KG > 0 (nexgen_rf_kullanim → nexgen_uretim_plan.planlama_siparis_id)
- Sevk edilebilir = min(kalan_siparis_kg, uretilen_kg - sevk_edilen_kg)

NOT: Üretim BITTI / batch BITTI ≠ sevk hazır. Alt emir BITTI barkoda hazırlık
içindir; bu ekran rf_kullanim gerçekleşen miktarını esas alır.
Belirsiz edge: planlama_siparis_id olmayan uretim_plan → listede yok.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Any

from modules.nexgen.mo_sevkiyat_config import DURUM_ETIKET
from modules.nexgen.mo_sevkiyat_service import (
    kalan_miktarlar,
    sevk_edilmis_kg,
    termin_karsilastirma,
)
from modules.nexgen.mo_uretim_kg_read import uretilen_kg_siparis
from modules.nexgen.pzm_siparis_read import (
    pzm_payload_unpack,
    pzm_siparis_finans_alanlari,
    pzm_siparis_header_getir,
    pzm_siparis_kalemleri_getir,
    pzm_siparis_ozet,
)

SIPARIS_SEVKE_UYGUN = frozenset({
    'ONAYLANDI', 'MPR_BEKLIYOR', 'PLANLAMAYA_HAZIR', 'URETIMDE', 'TAMAMLANDI',
})

TAB_DURUM = {
    'hazirlananlar': ('HAZIRLANIYOR',),
    'yuklenenler': ('YUKLENIYOR',),
    'yolda': ('SEVK_EDILDI',),
    'teslim': ('TESLIM_EDILDI', 'TAMAMLANDI'),
}

GONDERILEN_SEVK_DURUM = frozenset({'SEVK_EDILDI', 'TESLIM_EDILDI', 'TAMAMLANDI'})


def _tablo_var(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _uretilen_kg_siparis(con: sqlite3.Connection, planlama_siparis_id: int) -> float:
    return uretilen_kg_siparis(con, planlama_siparis_id)


def _siparis_toplam_kg(con: sqlite3.Connection, siparis_id: int) -> float:
    kalemler = pzm_siparis_kalemleri_getir(con, siparis_id)
    oz = pzm_siparis_ozet(kalemler)
    return float(oz.get('toplam_kg') or 0)


def termin_durum_etiket(
    verilen_termin: str | None,
    gercek_sevk: str | None,
    gercek_teslim: str | None = None,
) -> str:
    ref = (verilen_termin or '')[:10]
    if not ref:
        return 'Termin yok'
    if not gercek_sevk and not gercek_teslim:
        return 'Henüz sevk edilmedi'
    gercek = (gercek_teslim or gercek_sevk or '')[:10]
    if not gercek:
        return 'Henüz sevk edilmedi'
    try:
        t_verilen = date.fromisoformat(ref)
        t_gercek = date.fromisoformat(gercek)
    except ValueError:
        return '—'
    if t_gercek < t_verilen:
        return 'Erken'
    if t_gercek == t_verilen:
        return 'Zamanında'
    return 'Gecikmiş'


def _tahsilat_ozet_siparis(con: sqlite3.Connection, siparis_id: int) -> dict[str, Any]:
    cols = [c[1] for c in con.execute('PRAGMA table_info(nexgen_planlama_siparis)').fetchall()]
    if 'tahsilat_kurali' not in cols:
        return {}
    row = con.execute(
        """
        SELECT tahsilat_kurali, tahsilat_gun_sayisi, planlanan_tahsilat_tarihi,
               tahsilat_tarih_kaynagi, tahsilat_durumu, tahsilat_hesaplanan_sevk_ref
        FROM nexgen_planlama_siparis WHERE id=?
        """,
        (siparis_id,),
    ).fetchone()
    if not row:
        return {}
    d = dict(row)
    kural = (d.get('tahsilat_kurali') or '').upper()
    not_metin = (
        'Sipariş bazlı tek tahsilat planı. '
        'SEVKTEN_SONRA kuralında ilk gerçek sevk tarihi + gün sayısı esas alınır; '
        'kısmi sevkiyatlarda plan yeniden yazılmaz (mevcut servis kararı).'
    )
    if kural in ('SEVKTE', 'SEVKTEN_SONRA') and not d.get('planlanan_tahsilat_tarihi'):
        not_metin += ' Gerçek sevk bekleniyor.'
    elif str(d.get('tahsilat_tarih_kaynagi') or '').startswith('GERCEK_SEVK'):
        not_metin += f" Kaynak: {d.get('tahsilat_tarih_kaynagi')}."
    d['tahsilat_kural_notu'] = not_metin
    return d


def _fazla_eksik(uretilen: float, siparis_kg: float) -> dict[str, Any]:
    diff = round(float(uretilen or 0) - float(siparis_kg or 0), 3)
    if diff > 0.001:
        return {
            'fazla_eksik_kg': diff,
            'fazla_eksik_tip': 'fazla',
            'fazla_eksik_etiket': f'+{diff:g} KG',
        }
    if diff < -0.001:
        ad = abs(diff)
        return {
            'fazla_eksik_kg': ad,
            'fazla_eksik_tip': 'eksik',
            'fazla_eksik_etiket': f'-{ad:g} KG',
        }
    return {
        'fazla_eksik_kg': 0.0,
        'fazla_eksik_tip': 'dengeli',
        'fazla_eksik_etiket': '0 KG',
    }


def _termin_durum_ui(
    verilen_termin: str | None,
    gercek_sevk: str | None = None,
) -> str:
    ref = (verilen_termin or '')[:10]
    if not ref:
        return 'Termin Yok'
    if gercek_sevk:
        eski = termin_durum_etiket(ref, gercek_sevk)
        if eski in ('Zamanında', 'Erken'):
            return 'Zamanında'
        if eski == 'Gecikmiş':
            return 'Gecikti'
        return eski
    try:
        t_verilen = date.fromisoformat(ref)
        today = date.today()
        if t_verilen < today:
            return 'Gecikti'
        if (t_verilen - today).days <= 3:
            return 'Yaklaşıyor'
        return 'Zamanında'
    except ValueError:
        return 'Termin Yok'


def _stok_urun_ozet(con: sqlite3.Connection, siparis_id: int) -> dict[str, str]:
    kalemler = pzm_siparis_kalemleri_getir(con, siparis_id)
    if not kalemler:
        return {'stok_kart': '—', 'urun': '—', 'renk': '—'}
    k = kalemler[0]
    urun = k.get('urun_ailesi') or '—'
    renk = k.get('renk_ad') or '—'
    formul = k.get('formul_ad') or ''
    stok = urun
    if formul:
        stok = f'{urun} · {formul}'
    return {'stok_kart': stok, 'urun': urun, 'renk': renk}


def _son_sevkiyat_bilgi(con: sqlite3.Connection, siparis_id: int) -> dict[str, Any]:
    if not _tablo_var(con, 'mo_musteri_sevkiyat'):
        return {'son_sevkiyat_tarihi': '—', 'son_sevkiyat_no': '—'}
    row = con.execute(
        """
        SELECT sevkiyat_no, sevk_tarihi, hazirlik_tarihi, durum
        FROM mo_musteri_sevkiyat
        WHERE siparis_id=? AND aktif=1
          AND durum IN ('SEVK_EDILDI','TESLIM_EDILDI','TAMAMLANDI')
        ORDER BY COALESCE(sevk_tarihi, hazirlik_tarihi) DESC, id DESC
        LIMIT 1
        """,
        (siparis_id,),
    ).fetchone()
    if not row:
        return {'son_sevkiyat_tarihi': '—', 'son_sevkiyat_no': '—'}
    return {
        'son_sevkiyat_tarihi': (row['sevk_tarihi'] or row['hazirlik_tarihi'] or '')[:10] or '—',
        'son_sevkiyat_no': row['sevkiyat_no'] or '—',
    }


def siparis_sevkiyat_gecmisi(con: sqlite3.Connection, siparis_id: int) -> list[dict[str, Any]]:
    if not _tablo_var(con, 'mo_musteri_sevkiyat'):
        return []
    rows = con.execute(
        """
        SELECT s.id, s.sevkiyat_no, s.durum, s.sevk_tarihi, s.arac_plaka,
               s.irsaliye_no, s.kargo_firmasi
        FROM mo_musteri_sevkiyat s
        WHERE s.siparis_id=? AND s.aktif=1
        ORDER BY s.id DESC
        LIMIT 30
        """,
        (siparis_id,),
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        kg_row = con.execute(
            'SELECT SUM(miktar_kg) AS kg FROM mo_musteri_sevkiyat_kalem WHERE sevkiyat_id=?',
            (d['id'],),
        ).fetchone()
        d['net_kg'] = round(float(kg_row['kg'] or 0), 3) if kg_row else 0.0
        d['durum_etiket'] = DURUM_ETIKET.get(d.get('durum') or '', d.get('durum'))
        d['tarih'] = (d.get('sevk_tarihi') or '')[:10] or '—'
        d['arac'] = d.get('arac_plaka') or d.get('kargo_firmasi') or '—'
        out.append(d)
    return out


def operasyon_ozet(con: sqlite3.Connection) -> dict[str, Any]:
    hazir = sevkiyata_hazir_siparisler(con)
    hazirlananlar = liste_sevkiyat_tab(con, 'hazirlananlar')
    yukleniyor = liste_sevkiyat_tab(con, 'yuklenenler')
    today = date.today().isoformat()
    bugun_sevke_hazir_kg = round(sum(float(r.get('sevk_edilebilir_kg') or 0) for r in hazir), 3)
    bugun_sevk_kg = 0.0
    if _tablo_var(con, 'mo_musteri_sevkiyat'):
        row = con.execute(
            """
            SELECT ROUND(COALESCE(SUM(k.miktar_kg), 0), 3) AS kg
            FROM mo_musteri_sevkiyat_kalem k
            JOIN mo_musteri_sevkiyat s ON s.id = k.sevkiyat_id
            WHERE s.aktif=1 AND s.sevk_tarihi=? AND s.durum IN ('SEVK_EDILDI','TESLIM_EDILDI','TAMAMLANDI')
            """,
            (today,),
        ).fetchone()
        bugun_sevk_kg = float(row['kg'] or 0) if row else 0.0
    return {
        'acik_siparis_kg': _acik_siparis_kg_toplam(con),
        'bugun_sevke_hazir_kg': bugun_sevke_hazir_kg,
        'bugun_sevk_edilen_kg': bugun_sevk_kg,
        'kismi_sevkiyat': _kismi_sevkiyat_sayisi(con),
        'bekleyen_sevkiyat': len(hazirlananlar) + len(yukleniyor),
        # geriye dönük okuyucular
        'sevke_hazir_siparis': len(hazir),
        'bugun_sevk_edilecek': sum(
            1 for r in hazir
            if (r.get('verilen_termin') or '')[:10] not in ('', '—')
            and (r.get('verilen_termin') or '')[:10] <= today
        ),
        'yukleniyor': len(yukleniyor),
    }


def tab_sayilari(con: sqlite3.Connection) -> dict[str, int]:
    hazir = sevkiyata_hazir_siparisler(con)
    gonderilen = gonderilen_siparisler(con)
    tumu = tumu_siparis_operasyon(con)
    return {
        'hazir': len(hazir),
        'gonderilenler': len(gonderilen),
        'tumu': len(tumu),
    }


def _sevkiyat_siparis_ozet(
    con: sqlite3.Connection,
    siparis_id: int,
    sevk_edilen: float,
    kalan_kg: float,
) -> dict[str, Any]:
    cnt = 0
    if _tablo_var(con, 'mo_musteri_sevkiyat'):
        row = con.execute(
            'SELECT COUNT(*) AS n FROM mo_musteri_sevkiyat WHERE siparis_id=? AND aktif=1',
            (siparis_id,),
        ).fetchone()
        cnt = int(row['n'] or 0) if row else 0
    kismi = sevk_edilen > 0.001 and kalan_kg > 0.001
    return {
        'sevkiyat_sayisi': cnt,
        'kismi_sevkiyat': kismi,
        'sevkiyat_etiket': f'{cnt} Sevkiyat' if cnt else '—',
    }


def _cari_acik_siparis_ozet(con: sqlite3.Connection, cari_id: int | None) -> dict[str, Any]:
    if not cari_id or not _tablo_var(con, 'nexgen_planlama_siparis'):
        return {'cari_acik_siparis': 0, 'cari_acik_kg': 0.0, 'cari_acik_etiket': ''}
    ph = ','.join(['?'] * len(SIPARIS_SEVKE_UYGUN))
    rows = con.execute(
        f"""
        SELECT id FROM nexgen_planlama_siparis
        WHERE cari_id=? AND durum IN ({ph})
        """,
        (cari_id, *tuple(SIPARIS_SEVKE_UYGUN)),
    ).fetchall()
    acik = 0
    toplam_kalan = 0.0
    for r in rows:
        sid = int(r['id'])
        kalan_list = kalan_miktarlar(con, sid)
        kalan = round(sum(float(k.get('kalan_kg') or 0) for k in kalan_list), 3)
        if kalan <= 0.001:
            continue
        acik += 1
        toplam_kalan += kalan
    etiket = ''
    if acik > 1:
        etiket = f'{acik} Açık Sipariş · {toplam_kalan:g} KG'
    return {
        'cari_acik_siparis': acik,
        'cari_acik_kg': round(toplam_kalan, 3),
        'cari_acik_etiket': etiket,
    }


def _finans_hazirlik_alanlari(
    con: sqlite3.Connection,
    siparis_id: int,
    siparis_kg: float,
    sevk_edilen_kg: float,
) -> dict[str, Any]:
    """Yalnız gerçek DB/meta alanları — sahte finans verisi üretilmez."""
    hdr = pzm_siparis_header_getir(con, siparis_id) or {}
    payload = pzm_payload_unpack(hdr.get('talep_referansi'))
    fin = pzm_siparis_finans_alanlari(hdr, payload)
    tah = _tahsilat_ozet_siparis(con, siparis_id)
    out: dict[str, Any] = {}
    bf = fin.get('anlasma_birim_fiyat')
    if bf not in (None, ''):
        try:
            out['birim_fiyat'] = float(bf)
        except (TypeError, ValueError):
            pass
    pb = fin.get('anlasma_para_birimi')
    if pb:
        out['para_birimi'] = str(pb)
    vg = fin.get('vade_gun')
    if vg not in (None, ''):
        try:
            out['vade_gun'] = int(vg)
        except (TypeError, ValueError):
            pass
    if tah.get('planlanan_tahsilat_tarihi'):
        out['vade_tarihi'] = str(tah['planlanan_tahsilat_tarihi'])[:10]
    if tah.get('tahsilat_durumu'):
        out['tahsilat_durumu'] = tah['tahsilat_durumu']
    if out.get('birim_fiyat') is not None and siparis_kg:
        out['toplam_tutar_siparis'] = round(float(out['birim_fiyat']) * float(siparis_kg), 2)
    if out.get('birim_fiyat') is not None and sevk_edilen_kg:
        out['toplam_tutar_sevk'] = round(float(out['birim_fiyat']) * float(sevk_edilen_kg), 2)
    return out


def _finans_devir_durum(
    *,
    sevk_edilen_kg: float = 0,
    sevkiyat_durum: str | None = None,
) -> str:
    """Bu fazda yalnız Hazır / Sevk Edildi aktif."""
    dur = (sevkiyat_durum or '').upper()
    if dur in ('SEVK_EDILDI', 'TESLIM_EDILDI', 'TAMAMLANDI'):
        return 'Sevk Edildi'
    if dur in ('HAZIRLANIYOR', 'YUKLENIYOR'):
        return 'Hazır'
    if sevk_edilen_kg > 0.001:
        return 'Sevk Edildi'
    return 'Hazır'


def _finans_kolon_meta(rows: list[dict[str, Any]]) -> dict[str, bool]:
    keys = (
        'birim_fiyat', 'para_birimi', 'vade_gun', 'vade_tarihi',
        'toplam_tutar_siparis', 'toplam_tutar_sevk', 'tahsilat_durumu',
    )
    meta = {k: False for k in keys}
    for row in rows:
        fh = row.get('finans_hazirlik') or {}
        for k in keys:
            if fh.get(k) not in (None, '', 0):
                meta[k] = True
    return meta


def _satir_zenginlestir_operasyon(
    con: sqlite3.Connection,
    base: dict[str, Any],
    *,
    cari_cache: dict[int, dict[str, Any]] | None = None,
    sevkiyat_durum: str | None = None,
) -> dict[str, Any]:
    sid = int(base['siparis_id'])
    su = _stok_urun_ozet(con, sid)
    siparis_kg = float(base.get('siparis_kg') or 0)
    uretilen = float(base.get('uretilen_kg') or 0)
    if uretilen <= 0:
        uretilen = _uretilen_kg_siparis(con, sid)
        base['uretilen_kg'] = uretilen
    sevk_edilen = float(base.get('sevk_edilen_kg') or base.get('sevk_edilen_toplam') or 0)
    kalan = float(base.get('kalan_kg') or 0)
    fe = _fazla_eksik(uretilen, siparis_kg)
    son = _son_sevkiyat_bilgi(con, sid)
    verilen = base.get('verilen_termin')
    sevk_oz = _sevkiyat_siparis_ozet(con, sid, sevk_edilen, kalan)
    cari_id = base.get('cari_id')
    if cari_cache is not None and cari_id:
        if cari_id not in cari_cache:
            cari_cache[cari_id] = _cari_acik_siparis_ozet(con, int(cari_id))
        cari_oz = cari_cache[cari_id]
    else:
        cari_oz = _cari_acik_siparis_ozet(con, int(cari_id) if cari_id else None)
    base.update(su)
    base.update(fe)
    base.update(son)
    base.update(sevk_oz)
    base.update(cari_oz)
    base['finans_hazirlik'] = _finans_hazirlik_alanlari(con, sid, siparis_kg, sevk_edilen)
    base['finans_devir_durum'] = _finans_devir_durum(
        sevk_edilen_kg=sevk_edilen,
        sevkiyat_durum=sevkiyat_durum or base.get('durum'),
    )
    base['termin_durum'] = _termin_durum_ui(
        verilen if verilen not in ('—', '') else None,
        son.get('son_sevkiyat_tarihi') if son.get('son_sevkiyat_tarihi') != '—' else None,
    )
    return base


def _acik_siparis_kg_toplam(con: sqlite3.Connection) -> float:
    if not _tablo_var(con, 'nexgen_planlama_siparis'):
        return 0.0
    ph = ','.join(['?'] * len(SIPARIS_SEVKE_UYGUN))
    rows = con.execute(
        f"SELECT id FROM nexgen_planlama_siparis WHERE durum IN ({ph})",
        tuple(SIPARIS_SEVKE_UYGUN),
    ).fetchall()
    toplam = 0.0
    for r in rows:
        sid = int(r['id'])
        kalan_list = kalan_miktarlar(con, sid)
        toplam += sum(float(k.get('kalan_kg') or 0) for k in kalan_list)
    return round(toplam, 3)


def _kismi_sevkiyat_sayisi(con: sqlite3.Connection) -> int:
    if not _tablo_var(con, 'nexgen_planlama_siparis'):
        return 0
    ph = ','.join(['?'] * len(SIPARIS_SEVKE_UYGUN))
    rows = con.execute(
        f"SELECT id FROM nexgen_planlama_siparis WHERE durum IN ({ph})",
        tuple(SIPARIS_SEVKE_UYGUN),
    ).fetchall()
    n = 0
    for r in rows:
        sid = int(r['id'])
        siparis_kg = _siparis_toplam_kg(con, sid)
        sevk = sevk_edilmis_kg(con, sid)
        kalan = round(max(0.0, siparis_kg - sevk), 3)
        if sevk > 0.001 and kalan > 0.001:
            n += 1
    return n


def _satir_zenginlestir_hazir(con: sqlite3.Connection, base: dict[str, Any]) -> dict[str, Any]:
    return _satir_zenginlestir_operasyon(con, base, cari_cache={})


def _gonderilmis_sevkiyat_var(con: sqlite3.Connection, siparis_id: int) -> bool:
    if not _tablo_var(con, 'mo_musteri_sevkiyat'):
        return False
    ph = ','.join(['?'] * len(GONDERILEN_SEVK_DURUM))
    row = con.execute(
        f"""
        SELECT 1 FROM mo_musteri_sevkiyat
        WHERE siparis_id=? AND aktif=1 AND durum IN ({ph})
        LIMIT 1
        """,
        (siparis_id, *tuple(GONDERILEN_SEVK_DURUM)),
    ).fetchone()
    return bool(row)


def _siparis_operasyon_etiket(sevk_edilen: float, kalan_kg: float, kismi: bool) -> str:
    if kalan_kg <= 0.001 and sevk_edilen > 0.001:
        return 'Tamamlandı'
    if kismi or (sevk_edilen > 0.001 and kalan_kg > 0.001):
        return 'Kısmi Sevk'
    if sevk_edilen > 0.001:
        return 'Sevk Edildi'
    return 'Sevke Hazır'


def _build_siparis_operasyon_satir(
    con: sqlite3.Connection,
    r: sqlite3.Row,
    *,
    durum_etiket: str | None = None,
) -> dict[str, Any]:
    sid = int(r['id'])
    siparis_kg = _siparis_toplam_kg(con, sid)
    sevk_edilen = sevk_edilmis_kg(con, sid)
    kalan_list = kalan_miktarlar(con, sid)
    kalan_kg = round(sum(float(k.get('kalan_kg') or 0) for k in kalan_list), 3)
    uretilen = _uretilen_kg_siparis(con, sid)
    sevk_edilebilir = round(min(kalan_kg, max(0.0, uretilen - sevk_edilen)), 3)
    verilen = (r['onerilen_termin'] or r['termin_tarihi'] or '')[:10] or None
    sevk_oz = _sevkiyat_siparis_ozet(con, sid, sevk_edilen, kalan_kg)
    etiket = durum_etiket or _siparis_operasyon_etiket(
        sevk_edilen, kalan_kg, bool(sevk_oz.get('kismi_sevkiyat')),
    )
    row = _satir_zenginlestir_hazir(con, {
        'siparis_id': sid,
        'siparis_no': r['siparis_no'],
        'cari_id': r['cari_id'],
        'musteri': r['cari_unvan'] or '—',
        'urun_ozet': _urun_ozet(con, sid),
        'siparis_kg': siparis_kg,
        'sevk_edilen_kg': sevk_edilen,
        'kalan_kg': kalan_kg,
        'uretilen_kg': uretilen,
        'sevk_edilebilir_kg': sevk_edilebilir,
        'musteri_termin': (r['musteri_termin'] or '')[:10] or '—',
        'verilen_termin': verilen or '—',
        'durum': r['durum'],
        'durum_etiket': etiket,
    })
    return row


def gonderilen_siparisler(con: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _tablo_var(con, 'nexgen_planlama_siparis'):
        return []
    ph = ','.join(['?'] * len(SIPARIS_SEVKE_UYGUN))
    rows = con.execute(
        f"""
        SELECT ps.id, ps.siparis_no, ps.cari_id, ps.cari_unvan, ps.durum,
               ps.musteri_termin, ps.onerilen_termin, ps.termin_tarihi
        FROM nexgen_planlama_siparis ps
        WHERE ps.durum IN ({ph})
        ORDER BY ps.id DESC
        LIMIT 300
        """,
        tuple(SIPARIS_SEVKE_UYGUN),
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        sid = int(r['id'])
        sevk_edilen = sevk_edilmis_kg(con, sid)
        if sevk_edilen <= 0.001:
            continue
        if not _gonderilmis_sevkiyat_var(con, sid):
            continue
        out.append(_build_siparis_operasyon_satir(con, r))
    return out


def tumu_siparis_operasyon(con: sqlite3.Connection) -> list[dict[str, Any]]:
    by_id: dict[int, dict[str, Any]] = {}
    for row in gonderilen_siparisler(con):
        by_id[int(row['siparis_id'])] = row
    for row in sevkiyata_hazir_siparisler(con):
        by_id[int(row['siparis_id'])] = row
    return list(by_id.values())


def sevkiyata_hazir_siparisler(con: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _tablo_var(con, 'nexgen_planlama_siparis'):
        return []
    ph = ','.join(['?'] * len(SIPARIS_SEVKE_UYGUN))
    rows = con.execute(
        f"""
        SELECT ps.id, ps.siparis_no, ps.cari_id, ps.cari_unvan, ps.durum,
               ps.musteri_termin, ps.onerilen_termin, ps.termin_tarihi
        FROM nexgen_planlama_siparis ps
        WHERE ps.durum IN ({ph})
        ORDER BY ps.id DESC
        LIMIT 200
        """,
        tuple(SIPARIS_SEVKE_UYGUN),
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        sid = int(r['id'])
        siparis_kg = _siparis_toplam_kg(con, sid)
        sevk_edilen = sevk_edilmis_kg(con, sid)
        kalan_list = kalan_miktarlar(con, sid)
        kalan_kg = round(sum(float(k.get('kalan_kg') or 0) for k in kalan_list), 3)
        if kalan_kg <= 0.001:
            continue
        uretilen = _uretilen_kg_siparis(con, sid)
        if uretilen <= 0.001:
            continue
        sevk_edilebilir = round(min(kalan_kg, max(0.0, uretilen - sevk_edilen)), 3)
        if sevk_edilebilir <= 0.001:
            continue
        out.append(_build_siparis_operasyon_satir(con, r, durum_etiket='Sevke Hazır'))
    return out


def _urun_ozet(con: sqlite3.Connection, siparis_id: int) -> str:
    kalemler = pzm_siparis_kalemleri_getir(con, siparis_id)
    if not kalemler:
        return '—'
    k = kalemler[0]
    parts = [k.get('urun_ailesi') or '', k.get('renk_ad') or '', k.get('formul_ad') or '']
    s = ' · '.join(p for p in parts if p)
    if len(kalemler) > 1:
        s += f' (+{len(kalemler) - 1})'
    return s or '—'


def liste_sevkiyat_tab(con: sqlite3.Connection, tab: str) -> list[dict[str, Any]]:
    if not _tablo_var(con, 'mo_musteri_sevkiyat'):
        return []
    if tab == 'hazir':
        return []
    if tab == 'tumu':
        durum_filt = None
    else:
        durum_filt = TAB_DURUM.get(tab)
        if not durum_filt:
            return []
    sql = """
        SELECT s.id, s.sevkiyat_no, s.siparis_id, s.cari_id, s.durum,
               s.sevk_tarihi, s.teslim_tarihi, s.hazirlik_tarihi,
               ps.siparis_no, c.unvan AS cari_unvan
        FROM mo_musteri_sevkiyat s
        LEFT JOIN nexgen_planlama_siparis ps ON ps.id = s.siparis_id
        LEFT JOIN nexgen_cari c ON c.id = s.cari_id
        WHERE s.aktif = 1
    """
    params: list = []
    if durum_filt:
        ph = ','.join(['?'] * len(durum_filt))
        sql += f' AND s.durum IN ({ph})'
        params.extend(durum_filt)
    sql += ' ORDER BY s.id DESC LIMIT 150'
    rows = con.execute(sql, params).fetchall()
    out = []
    cari_cache: dict[int, dict[str, Any]] = {}
    for r in rows:
        d = dict(r)
        sid = int(d['siparis_id'])
        kalemler = con.execute(
            'SELECT SUM(miktar_kg) AS kg FROM mo_musteri_sevkiyat_kalem WHERE sevkiyat_id=?',
            (d['id'],),
        ).fetchone()
        d['sevk_kg'] = round(float(kalemler['kg'] or 0), 3) if kalemler else 0
        d['urun_ozet'] = _urun_ozet(con, sid)
        siparis_kg = _siparis_toplam_kg(con, sid)
        uretilen = _uretilen_kg_siparis(con, sid)
        d['siparis_id'] = sid
        d['siparis_kg'] = siparis_kg
        d['sevk_edilen_toplam'] = sevk_edilmis_kg(con, sid)
        d['sevk_edilen_kg'] = d['sevk_edilen_toplam']
        d['kalan_kg'] = round(max(0, siparis_kg - d['sevk_edilen_toplam']), 3)
        d['uretilen_kg'] = uretilen
        d['sevk_edilebilir_kg'] = round(
            min(d['kalan_kg'], max(0.0, uretilen - d['sevk_edilen_toplam'])), 3,
        )
        ps = con.execute(
            'SELECT musteri_termin, onerilen_termin, termin_tarihi FROM nexgen_planlama_siparis WHERE id=?',
            (sid,),
        ).fetchone()
        verilen = '—'
        if ps:
            verilen = (ps['onerilen_termin'] or ps['termin_tarihi'] or '')[:10] or '—'
        d['verilen_termin'] = verilen
        d['durum_etiket'] = DURUM_ETIKET.get(d.get('durum') or '', d.get('durum'))
        d = _satir_zenginlestir_operasyon(
            con, d, cari_cache=cari_cache, sevkiyat_durum=d.get('durum'),
        )
        out.append(d)
    return out


def siparis_sevk_form_verisi(con: sqlite3.Connection, siparis_id: int) -> dict[str, Any]:
    row = con.execute(
        """
        SELECT ps.*, c.cari_kod, c.unvan
        FROM nexgen_planlama_siparis ps
        LEFT JOIN nexgen_cari c ON c.id = ps.cari_id
        WHERE ps.id=?
        """,
        (siparis_id,),
    ).fetchone()
    if not row:
        return {}
    d = dict(row)
    sid = int(d['id'])
    kalemler = kalan_miktarlar(con, sid)
    pzm_k = pzm_siparis_kalemleri_getir(con, sid)
    kalem_map = {k.get('id'): k for k in pzm_k if k.get('id')}
    form_kalemler = []
    for kl in kalemler:
        pk = kalem_map.get(kl.get('siparis_kalem_id')) or {}
        form_kalemler.append({
            **kl,
            'urun_adi': pk.get('urun_ailesi') or kl.get('urun_ailesi') or '—',
            'renk_ad': pk.get('renk_ad') or '—',
            'formul_ad': pk.get('formul_ad') or '—',
            'birim': 'kg',
            'siparis_kg': kl.get('siparis_kg') or pk.get('toplam_kg'),
        })
    siparis_kg = _siparis_toplam_kg(con, sid)
    sevk_edilen = sevk_edilmis_kg(con, sid)
    uretilen = _uretilen_kg_siparis(con, sid)
    fe = _fazla_eksik(uretilen, siparis_kg)
    gecmis = siparis_sevkiyat_gecmisi(con, sid)
    fin = _finans_hazirlik_alanlari(con, sid, siparis_kg, sevk_edilen)
    cari_oz = _cari_acik_siparis_ozet(con, int(d.get('cari_id')) if d.get('cari_id') else None)
    return {
        'siparis_id': sid,
        'siparis_no': d.get('siparis_no'),
        'cari_id': d.get('cari_id'),
        'cari_kod': d.get('cari_kod'),
        'musteri': d.get('unvan') or d.get('cari_unvan'),
        'musteri_termin': (d.get('musteri_termin') or '')[:10] or '—',
        'verilen_termin': (d.get('onerilen_termin') or d.get('termin_tarihi') or '')[:10] or '—',
        'siparis_kg': siparis_kg,
        'sevk_edilen_kg': sevk_edilen,
        'kalan_kg': round(max(0, siparis_kg - sevk_edilen), 3),
        'uretilen_kg': uretilen,
        'sevk_edilebilir_kg': round(min(max(0, siparis_kg - sevk_edilen), max(0, uretilen - sevk_edilen)), 3),
        'fazla_eksik_kg': fe['fazla_eksik_kg'],
        'fazla_eksik_tip': fe['fazla_eksik_tip'],
        'fazla_eksik_etiket': fe['fazla_eksik_etiket'],
        'sevkiyat_sayisi': len(gecmis),
        'sevkiyat_gecmisi': gecmis,
        'stok_kart': _stok_urun_ozet(con, sid).get('stok_kart'),
        'urun': _stok_urun_ozet(con, sid).get('urun'),
        'renk': _stok_urun_ozet(con, sid).get('renk'),
        'kalemler': form_kalemler,
        'termin': termin_karsilastirma(con, sid),
        'tahsilat': _tahsilat_ozet_siparis(con, sid),
        'finans_hazirlik': fin,
        'finans_devir_durum': _finans_devir_durum(sevk_edilen_kg=sevk_edilen),
        **cari_oz,
    }


def operasyon_detay_paket(
    con: sqlite3.Connection,
    sevkiyat_id: int,
    kullanici_id: int,
    yk: set[str] | None,
) -> dict[str, Any]:
    from modules.nexgen.mo_sevkiyat_service import sevkiyat_getir
    det = sevkiyat_getir(con, sevkiyat_id, kullanici_id, yk)
    sid = int(det['siparis_id'])
    det['termin_durum'] = termin_durum_etiket(
        det['termin'].get('verilen_termin'),
        det['termin'].get('gercek_sevk_tarihi'),
        det['termin'].get('gercek_teslim_tarihi'),
    )
    det['tahsilat'] = _tahsilat_ozet_siparis(con, sid)
    det['sonraki_durum'] = _sonraki_durum(det.get('durum'))
    return det


def _sonraki_durum(mevcut: str | None) -> str | None:
    m = (mevcut or '').upper()
    chain = ['HAZIRLANIYOR', 'YUKLENIYOR', 'SEVK_EDILDI', 'TESLIM_EDILDI', 'TAMAMLANDI']
    try:
        i = chain.index(m)
        return chain[i + 1] if i + 1 < len(chain) else None
    except ValueError:
        return None
