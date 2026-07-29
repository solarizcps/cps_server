# -*- coding: utf-8 -*-
"""Numune Talep (AT-M) — Pazarlama → Bekleyen Numuneler → Vedat çalışma kartı."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import sqlite3

DURUMLAR = frozenset({
    'YENI_TALEP',
    'TASLAK',
    'BEKLEYEN_NUMUNE',
    'CALISILIYOR',
    'REVIZYONDA',
    'FERHAT_TESTINDE',
    'ONAY_BEKLIYOR',
    'ONAYLANDI',
    'RECETE_MERKEZINE_AKTARILDI',
})

MUSTERI_TIPLERI = frozenset({'MEVCUT', 'ADAY'})
ONCELIKLER = frozenset({'NORMAL', 'ACIL', 'KRITIK'})
RENK_TIPLERI = frozenset({'MEVCUT', 'YENI'})
URUN_TIPLERI = frozenset({'TERLIK', 'TABAN', 'DOKME'})
TALEP_KAYNAKLARI = frozenset({
    'Fuar', 'WhatsApp', 'Telefon', 'E-posta', 'Referans', 'Ziyaret', 'Bayi', 'Diğer',
})
VEDAT_SONUCLAR = frozenset({'Basarili', 'Revizyon', 'Red', 'Calisiliyor'})
KARSILAMA_YOLLARI = frozenset({'HAZIR_RENK', 'YENI_RENK', 'YENI_FORMUL'})
KARSILAMA_YOLLARI_JS = frozenset({'HAZIR_RF', 'HAZIR_RENK', 'YENI_RENK', 'YENI_FORMUL'})
DUZENLENEBILIR_DURUMLAR = frozenset({'YENI_TALEP', 'TASLAK'})
# FAZ-NUMUNE-MEVCUT-CARI-ZORUNLU-VALIDASYON-1
MSG_MEVCUT_CARI_ZORUNLU = 'Mevcut müşteri için cari seçimi zorunludur.'

FILTRE_DURUMLAR = {
    'bekleyen': ('BEKLEYEN_NUMUNE',),
    'calisiliyor': ('CALISILIYOR', 'REVIZYONDA'),
    'tamamlanan': ('ONAY_BEKLIYOR', 'FERHAT_TESTINDE', 'ONAYLANDI', 'RECETE_MERKEZINE_AKTARILDI'),
}


class NumuneTalepError(Exception):
    def __init__(self, message: str, status: int = 400, kod: str | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.kod = kod or 'NT_HATA'


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _today() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def uret_talep_kodu(con) -> str:
    """AT-M-YYYY-NNNN — nexgen_arge_test ile çakışmayacak şekilde max sıra."""
    yil = datetime.now().year
    prefix = f'AT-M-{yil}-'
    row_a = con.execute(
        "SELECT MAX(CAST(SUBSTR(test_no, -4) AS INTEGER)) AS son "
        "FROM nexgen_arge_test WHERE test_no LIKE ?",
        (prefix + '%',),
    ).fetchone()
    row_n = con.execute(
        "SELECT MAX(CAST(SUBSTR(talep_kodu, -4) AS INTEGER)) AS son "
        "FROM nexgen_numune_talep WHERE talep_kodu LIKE ?",
        (prefix + '%',),
    ).fetchone()
    son = max(int(row_a['son'] or 0) if row_a else 0, int(row_n['son'] or 0) if row_n else 0)
    return f'{prefix}{son + 1:04d}'


def _norm_oncelik(v: str | None) -> str:
    m = {
        'Normal': 'NORMAL', 'Acil': 'ACIL', 'Kritik': 'KRITIK',
        'NORMAL': 'NORMAL', 'ACIL': 'ACIL', 'KRITIK': 'KRITIK',
    }
    out = m.get((v or '').strip(), 'NORMAL')
    if out not in ONCELIKLER:
        raise NumuneTalepError('Geçersiz öncelik.', 400)
    return out


def _norm_karsilama_yolu(v: str | None) -> str | None:
    if not v:
        return None
    t = (v or '').strip().upper()
    if t == 'HAZIR_RF':
        t = 'HAZIR_RENK'
    if t not in KARSILAMA_YOLLARI:
        raise NumuneTalepError('Geçersiz karsilama_yolu.', 400)
    return t


def _norm_int(v, *, default: int | None = None) -> int | None:
    if v is None or v == '':
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _norm_flag(v, *, default: int = 0) -> int:
    if v is None or v == '':
        return default
    if isinstance(v, bool):
        return 1 if v else 0
    return 1 if str(v).strip().lower() in ('1', 'true', 'evet', 'yes', 'on') else 0


def _norm_urun_tipi(v: str | None) -> str | None:
    if not v:
        return None
    t = (v or '').strip().upper().replace('İ', 'I')
    m = {'TERLIK': 'TERLIK', 'TERLİK': 'TERLIK', 'TABAN': 'TABAN', 'DOKME': 'DOKME', 'DÖKME': 'DOKME'}
    return m.get(t) or m.get((v or '').strip().upper())


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    d = dict(row)
    if d.get('diger_beklentiler_json'):
        try:
            d['diger_beklentiler'] = json.loads(d['diger_beklentiler_json'])
        except (TypeError, ValueError, json.JSONDecodeError):
            d['diger_beklentiler'] = []
    else:
        d['diger_beklentiler'] = []
    return d


def _validate_payload(payload: dict, *, zorunlu_gonder: bool = False) -> dict:
    if not isinstance(payload, dict):
        raise NumuneTalepError('JSON gövde gerekli.', 400)

    musteri_tipi = (payload.get('musteri_tipi') or 'MEVCUT').strip().upper()
    if musteri_tipi not in MUSTERI_TIPLERI:
        raise NumuneTalepError('musteri_tipi MEVCUT veya ADAY olmalı.', 400)

    cari_id = None
    if musteri_tipi == 'MEVCUT':
        try:
            cari_id = int(payload.get('cari_id') or 0)
        except (TypeError, ValueError):
            cari_id = 0
        # Taslak + gönder: MEVCUT için cari_id her yazmada zorunlu
        if not cari_id:
            raise NumuneTalepError(MSG_MEVCUT_CARI_ZORUNLU, 400)
    else:
        firma = (payload.get('aday_firma_adi') or payload.get('firma_adi') or '').strip()
        kaynak = (payload.get('talep_kaynagi') or '').strip()
        if zorunlu_gonder and not firma:
            raise NumuneTalepError('Aday müşteri için firma adı zorunlu.', 400)
        if zorunlu_gonder and not kaynak:
            raise NumuneTalepError('Aday müşteri için talep kaynağı zorunlu.', 400)
        if kaynak and kaynak not in TALEP_KAYNAKLARI:
            raise NumuneTalepError('Geçersiz talep kaynağı.', 400)

    talep_eden = payload.get('talep_eden_kullanici_id') or payload.get('talep_eden_id')

    renk_tipi = (payload.get('renk_tipi') or '').strip().upper() or None
    if renk_tipi and renk_tipi not in RENK_TIPLERI:
        raise NumuneTalepError('renk_tipi MEVCUT veya YENI olmalı.', 400)

    karsilama_yolu = _norm_karsilama_yolu(payload.get('karsilama_yolu'))
    if zorunlu_gonder and not karsilama_yolu:
        raise NumuneTalepError('Talep türü seçimi zorunlu.', 400)
    if karsilama_yolu == 'YENI_FORMUL':
        renk_tipi = None
    elif karsilama_yolu == 'HAZIR_RENK':
        renk_tipi = 'MEVCUT' if payload.get('rf_renk_id') else None
    elif karsilama_yolu == 'YENI_RENK':
        if not renk_tipi:
            renk_tipi = 'YENI' if not payload.get('rf_renk_id') else 'MEVCUT'

    if renk_tipi == 'YENI' and zorunlu_gonder:
        if not (payload.get('yeni_renk_aciklama') or '').strip():
            raise NumuneTalepError('Yeni renk için açıklama zorunlu.', 400)

    if zorunlu_gonder:
        if karsilama_yolu == 'HAZIR_RENK' and not payload.get('rf_renk_id'):
            raise NumuneTalepError('Hazır renk için katalog renk seçimi zorunlu.', 400)
        if karsilama_yolu == 'YENI_FORMUL':
            if not (payload.get('yeni_renk_aciklama') or '').strip():
                raise NumuneTalepError('Yeni formül için istenen özellik zorunlu.', 400)
        if not _norm_urun_tipi(payload.get('urun_tipi')):
            raise NumuneTalepError('Ürün tipi seçimi zorunlu.', 400)

    diger = payload.get('diger_beklentiler') or []
    if not isinstance(diger, list):
        diger = []

    numune_adedi = _norm_int(payload.get('numune_adedi'))
    if numune_adedi is not None and numune_adedi < 1:
        raise NumuneTalepError('Numune adedi 1 veya daha büyük olmalı.', 400)

    patch_var = _norm_flag(payload.get('patch_aksesuar_var'))
    patch_aciklama = (payload.get('patch_aksesuar_aciklama') or '').strip() or None
    if not patch_var:
        patch_aciklama = None

    data = {
        'musteri_tipi': musteri_tipi,
        'cari_id': cari_id or None,
        'aday_firma_adi': (payload.get('aday_firma_adi') or payload.get('firma_adi') or '').strip() or None,
        'ilgili_kisi': (payload.get('ilgili_kisi') or '').strip() or None,
        'telefon': (payload.get('telefon') or '').strip() or None,
        'eposta': (payload.get('eposta') or '').strip() or None,
        'sehir': (payload.get('sehir') or '').strip() or None,
        'talep_kaynagi': (payload.get('talep_kaynagi') or '').strip() or None,
        'talep_eden_kullanici_id': int(talep_eden) if talep_eden else None,
        'oncelik': _norm_oncelik(payload.get('oncelik')),
        'hedef_tarih': (payload.get('hedef_tarih') or '').strip() or None,
        'talep_nedeni': (payload.get('talep_nedeni') or '').strip() or None,
        'aciklama': (payload.get('aciklama') or '').strip() or None,
        'ek_not': (payload.get('ek_not') or '').strip() or None,
        'urun_tipi': _norm_urun_tipi(payload.get('urun_tipi')),
        'urun_adi': (payload.get('urun_adi') or '').strip() or None,
        'urun_aciklama': (payload.get('urun_aciklama') or '').strip() or None,
        'renk_tipi': renk_tipi,
        'rf_renk_id': int(payload['rf_renk_id']) if payload.get('rf_renk_id') else None,
        'renk_kodu': (payload.get('renk_kodu') or '').strip() or None,
        'yeni_renk_aciklama': (payload.get('yeni_renk_aciklama') or '').strip() or None,
        'acik_koyu': (payload.get('acik_koyu') or '').strip() or None,
        'mat_parlak': (payload.get('mat_parlak') or '').strip() or None,
        'ref_renk_kodu': (payload.get('ref_renk_kodu') or '').strip() or None,
        'yumusaklik': (payload.get('yumusaklik') or '').strip() or None,
        'kaymazlik': (payload.get('kaymazlik') or '').strip() or None,
        'shore_deger': (payload.get('shore_deger') or '').strip() or None,
        'pisme_notu': (payload.get('pisme_notu') or '').strip() or None,
        'diger_beklentiler_json': json.dumps(diger, ensure_ascii=False),
        'karsilama_yolu': karsilama_yolu,
        'numune_adedi': numune_adedi,
        'beden_kalip': (payload.get('beden_kalip') or '').strip() or None,
        'patch_aksesuar_var': patch_var,
        'patch_aksesuar_aciklama': patch_aciklama,
        'paketleme_notu': (payload.get('paketleme_notu') or '').strip() or None,
        'kargo_teslim_notu': (payload.get('kargo_teslim_notu') or '').strip() or None,
        'kullanim_amaci': (payload.get('kullanim_amaci') or '').strip() or None,
        'benzer_urun_numune': (payload.get('benzer_urun_numune') or '').strip() or None,
    }
    return _apply_karsilama_isolation(data)


def _apply_karsilama_isolation(data: dict) -> dict:
    """Talep türüne göre ilgisiz alanları NULL/temiz değere çeker."""
    ky = data.get('karsilama_yolu')
    bos_json = json.dumps([], ensure_ascii=False)
    if ky == 'HAZIR_RENK':
        data.update({
            'yeni_renk_aciklama': None,
            'acik_koyu': None,
            'mat_parlak': None,
            'ref_renk_kodu': None,
            'shore_deger': None,
            'yumusaklik': None,
            'kaymazlik': None,
            'diger_beklentiler_json': bos_json,
            'kullanim_amaci': None,
            'benzer_urun_numune': None,
        })
    elif ky == 'YENI_RENK':
        data.update({
            'rf_renk_id': None,
            'renk_kodu': None,
            'shore_deger': None,
            'yumusaklik': None,
            'kaymazlik': None,
            'diger_beklentiler_json': bos_json,
            'kullanim_amaci': None,
            'benzer_urun_numune': None,
            'renk_tipi': 'YENI',
        })
    elif ky == 'YENI_FORMUL':
        data.update({
            'rf_renk_id': None,
            'renk_kodu': None,
            'acik_koyu': None,
            'mat_parlak': None,
            'ref_renk_kodu': None,
            'renk_tipi': None,
            'shore_deger': None,
            'yumusaklik': None,
            'kaymazlik': None,
            'pisme_notu': None,
            'diger_beklentiler_json': bos_json,
            'kullanim_amaci': None,
            'benzer_urun_numune': None,
        })
    return data


def gelisme_ekle(
    con,
    talep_id: int,
    olay_metni: str,
    *,
    olay_tipi: str | None = None,
    kullanici_id: int | None = None,
    olay_tarihi: str | None = None,
) -> None:
    con.execute(
        """
        INSERT INTO nexgen_numune_talep_gelisme
            (talep_id, olay_tarihi, olay_tipi, olay_metni, kullanici_id, aktif)
        VALUES (?, ?, ?, ?, ?, 1)
        """,
        (talep_id, olay_tarihi or _now(), olay_tipi, olay_metni, kullanici_id),
    )


def gelisme_liste(con, talep_id: int, limit: int = 100) -> list[dict]:
    rows = con.execute(
        """
        SELECT g.*, k.KullaniciAdi AS kullanici_kadi, k.AdSoyad AS kullanici_ad
        FROM nexgen_numune_talep_gelisme g
        LEFT JOIN sistem_kullanici k ON k.Id = g.kullanici_id
        WHERE g.talep_id=? AND g.aktif=1
        ORDER BY g.olay_tarihi ASC, g.id ASC
        LIMIT ?
        """,
        (talep_id, limit),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _olusturan_gelisme_metni(con, kullanici_id: int) -> str:
    row = con.execute(
        'SELECT AdSoyad, KullaniciAdi FROM sistem_kullanici WHERE Id=?',
        (kullanici_id,),
    ).fetchone()
    if not row:
        return 'Kullanıcı talebi oluşturdu'
    ad = (row['AdSoyad'] or row['KullaniciAdi'] or 'Kullanıcı').strip()
    return f'{ad} talebi oluşturdu'


def _isleme_alan_gelisme_metni(con, kullanici_id: int) -> str:
    row = con.execute(
        'SELECT AdSoyad, KullaniciAdi FROM sistem_kullanici WHERE Id=?',
        (kullanici_id,),
    ).fetchone()
    ad = (row['AdSoyad'] or row['KullaniciAdi'] or 'Vedat').strip() if row else 'Vedat'
    return f'{ad} işleme aldı'


def _renk_goster(row: dict) -> str:
    if (row.get('renk_tipi') or '').upper() == 'YENI':
        yr = (row.get('yeni_renk_aciklama') or '').strip()
        return f'Yeni renk isteği' + (f' — {yr}' if yr else '')
    return (row.get('renk_kodu') or row.get('yeni_renk_aciklama') or '—').strip() or '—'


def _firma_goster(row: dict) -> str:
    if (row.get('musteri_tipi') or '').upper() == 'ADAY':
        return (row.get('aday_firma_adi') or '—').strip() or '—'
    return (row.get('cari_unvan') or '—').strip() or '—'


def _liste_satir_zengin(row: dict) -> dict:
    d = _row_to_dict(row)
    d['firma_goster'] = _firma_goster(d)
    d['renk_goster'] = _renk_goster(d)
    d['durum_etiket'] = durum_etiket(d.get('durum'))
    return d


def _insert_fields(data: dict) -> tuple[str, list]:
    cols = list(data.keys())
    return ','.join(cols), [data[c] for c in cols]


def _assert_mevcut_cari_aktif(con, musteri_tipi: str | None, cari_id: int | None) -> None:
    """MEVCUT yazmalarında cari_id aktif nexgen_cari olmalı (ADAY etkilenmez)."""
    if (musteri_tipi or '').strip().upper() != 'MEVCUT':
        return
    if not cari_id:
        raise NumuneTalepError(MSG_MEVCUT_CARI_ZORUNLU, 400)
    row = con.execute(
        'SELECT id, aktif FROM nexgen_cari WHERE id=?',
        (int(cari_id),),
    ).fetchone()
    if not row:
        raise NumuneTalepError('Seçilen cari bulunamadı.', 400)
    if int(row['aktif'] or 0) != 1:
        raise NumuneTalepError('Seçilen cari aktif değil.', 400)


def kaydet_taslak(con, payload: dict, olusturan_id: int, talep_id: int | None = None) -> dict:
    norm = _validate_payload(payload, zorunlu_gonder=False)
    _assert_mevcut_cari_aktif(con, norm.get('musteri_tipi'), norm.get('cari_id'))
    if not norm.get('talep_eden_kullanici_id'):
        norm['talep_eden_kullanici_id'] = olusturan_id
    now = _now()
    if talep_id:
        row = con.execute(
            'SELECT id, talep_kodu, durum, arge_test_id FROM nexgen_numune_talep WHERE id=? AND aktif=1',
            (talep_id,),
        ).fetchone()
        if not row:
            raise NumuneTalepError('Talep bulunamadı.', 404)
        if row['durum'] not in DUZENLENEBILIR_DURUMLAR:
            raise NumuneTalepError('Yalnız taslak talepler düzenlenebilir.', 409)
        if row['arge_test_id']:
            raise NumuneTalepError('Bağlı AR-GE kartı var — duplicate oluşturulamaz.', 409)
        kod = row['talep_kodu']
        norm['guncelleme_tarihi'] = now
        norm['durum'] = 'TASLAK'
        sets = ','.join(f'{k}=?' for k in norm)
        con.execute(
            f'UPDATE nexgen_numune_talep SET {sets} WHERE id=?',
            [*norm.values(), talep_id],
        )
        tid = talep_id
    else:
        kod = uret_talep_kodu(con)
        norm.update({
            'talep_kodu': kod,
            'durum': 'TASLAK',
            'olusturan_kullanici_id': olusturan_id,
            'olusturma_tarihi': now,
            'guncelleme_tarihi': now,
            'aktif': 1,
        })
        if not norm.get('talep_eden_kullanici_id'):
            norm['talep_eden_kullanici_id'] = olusturan_id
        cols, vals = _insert_fields(norm)
        cur = con.execute(f'INSERT INTO nexgen_numune_talep ({cols}) VALUES ({",".join(["?"]*len(vals))})', vals)
        tid = int(cur.lastrowid)
    con.commit()
    return get_talep(con, tid)


def _ana_grup_from_formul_kod(kod: str | None) -> str | None:
    k = (kod or '').strip().upper()
    for g in ('1BA', '2BA', '3BA'):
        if k.startswith(g + '-') or k == g:
            return g
    return None


def _uv_set_for_ana_grup(con, ana_grup: str) -> list[dict]:
    """Aynı ana gruptan reçeteli LARGE+SMALL veya MEDIUM seti (hardcode ID yok)."""
    ana = (ana_grup or '').strip().upper()
    if ana not in ('1BA', '2BA', '3BA'):
        raise NumuneTalepError('ana_formul_grup_kodu 1BA/2BA/3BA olmalı.', 400, 'ANA_GRUP')
    rows = con.execute(
        """
        SELECT uv.id AS uv_id, uv.boyut, f.kod
        FROM nexgen_uretim_varyant uv
        JOIN nexgen_renk_varyant rv ON rv.id = uv.renk_varyant_id
        JOIN nexgen_formul f ON f.id = rv.formul_id
        WHERE uv.aktif=1 AND f.kod LIKE ?
          AND uv.boyut IN ('LARGE','SMALL','MEDIUM')
          AND EXISTS (
            SELECT 1 FROM nexgen_recete_kalem rk
            WHERE rk.uretim_varyant_id=uv.id AND rk.aktif=1
          )
        ORDER BY f.kod, uv.boyut, uv.id
        """,
        (ana + '-%',),
    ).fetchall()
    by_boyut: dict[str, int] = {}
    for r in rows:
        b = (r['boyut'] or '').upper()
        if b not in by_boyut:
            by_boyut[b] = int(r['uv_id'])
    if 'LARGE' in by_boyut and 'SMALL' in by_boyut:
        return [
            {'boyut': 'LARGE', 'kaynak_uretim_varyant_id': by_boyut['LARGE'], 'sira_no': 1},
            {'boyut': 'SMALL', 'kaynak_uretim_varyant_id': by_boyut['SMALL'], 'sira_no': 2},
        ]
    if 'MEDIUM' in by_boyut:
        return [
            {'boyut': 'MEDIUM', 'kaynak_uretim_varyant_id': by_boyut['MEDIUM'], 'sira_no': 1},
        ]
    raise NumuneTalepError(
        f'{ana} için reçeteli kaynak UV seti bulunamadı (LARGE+SMALL veya MEDIUM).',
        400,
        'KAYNAK_UV',
    )


def _resolve_kaynak_from_rf(con, rf_renk_id: int) -> tuple[str, list[dict]]:
    """RF formul uygunluğundan ana grup + gerçek UV seti."""
    uyg = con.execute(
        """
        SELECT u.formul_id, u.ana_formul_kodu, f.kod
        FROM nexgen_rf_formul_uygunluk u
        LEFT JOIN nexgen_formul f ON f.id = u.formul_id
        WHERE u.rf_renk_id=? AND IFNULL(u.aktif,1)=1
        ORDER BY u.id
        """,
        (rf_renk_id,),
    ).fetchall()
    if not uyg:
        raise NumuneTalepError(
            'Seçili RF için formül uygunluğu yok; kaynak UV çözülemedi.',
            400,
            'RF_UYGUNLUK',
        )
    ana = None
    for r in uyg:
        ana = _ana_grup_from_formul_kod(r['ana_formul_kodu']) or _ana_grup_from_formul_kod(r['kod'])
        if ana:
            break
    if not ana:
        raise NumuneTalepError(
            'RF formül kodundan ana grup (1BA/2BA/3BA) çıkarılamadı.',
            400,
            'ANA_GRUP',
        )
    return ana, _uv_set_for_ana_grup(con, ana)


def _rf_renk_bilesenleri(con, rf_renk_id: int) -> list[dict]:
    """Mevcut RF pigment kalemleri — placeholder değil, katalog RF kaydı."""
    rows = con.execute(
        """
        SELECT stok_kart_id, pigment_ad, miktar_kg, sira
        FROM nexgen_rf_kalem
        WHERE rf_renk_id=? AND IFNULL(aktif,1)=1 AND miktar_kg > 0
        ORDER BY sira, id
        """,
        (rf_renk_id,),
    ).fetchall()
    out = []
    for r in rows:
        kg = float(r['miktar_kg'] or 0)
        if kg <= 0 or not r['stok_kart_id']:
            continue
        out.append({
            'stok_kart_id': int(r['stok_kart_id']),
            'ad': (r['pigment_ad'] or '').strip() or None,
            'gram': round(kg * 1000.0, 4),
            'kg': kg,
        })
    return out


def _resolve_nx_ar_kaynak(con, row, gonder_payload: dict | None) -> tuple[str, list[dict], list | None]:
    """
    Kaynak UV sırası:
      1) gonder payload.kaynak_uvler + ana_formul_grup_kodu (kullanıcı)
      2) talep.rf_renk_id → RF uygunluk + UV seti (gerçek bağlantı)
      3) yoksa anlaşılır validasyon
    Hardcode UV ID yok. Otomatik pigment yok (YENI_RENK).
    HAZIR_RENK + RF kalemi varsa gerçek RF pigmentlerini renk_bilesenleri olarak taşır.
    """
    payload = gonder_payload if isinstance(gonder_payload, dict) else {}
    ham_uv = payload.get('kaynak_uvler')
    ana = (payload.get('ana_formul_grup_kodu') or '').strip().upper() or None
    renk_bilesenleri = None

    if isinstance(ham_uv, list) and ham_uv:
        if not ana or ana not in ('1BA', '2BA', '3BA'):
            raise NumuneTalepError(
                'kaynak_uvler ile birlikte ana_formul_grup_kodu (1BA/2BA/3BA) zorunlu.',
                400,
                'ANA_GRUP',
            )
        kaynak = []
        for i, item in enumerate(ham_uv):
            if not isinstance(item, dict):
                raise NumuneTalepError(f'kaynak_uvler[{i}] geçersiz.', 400)
            try:
                uv_id = int(item.get('kaynak_uretim_varyant_id'))
            except (TypeError, ValueError):
                raise NumuneTalepError('kaynak_uretim_varyant_id geçersiz.', 400)
            boyut = (item.get('boyut') or '').strip().upper()
            if boyut not in ('LARGE', 'SMALL', 'MEDIUM'):
                raise NumuneTalepError(f'Geçersiz boyut: {boyut}', 400)
            kaynak.append({
                'boyut': boyut,
                'kaynak_uretim_varyant_id': uv_id,
                'sira_no': int(item.get('sira_no') or (i + 1)),
            })
        if isinstance(payload.get('renk_bilesenleri'), list):
            renk_bilesenleri = payload.get('renk_bilesenleri')
        return ana, kaynak, renk_bilesenleri

    rf_id = row['rf_renk_id'] if 'rf_renk_id' in row.keys() else None
    if rf_id:
        ana, kaynak = _resolve_kaynak_from_rf(con, int(rf_id))
        # HAZIR_RENK: mevcut RF pigmentleri gerçek kaynaktır
        bilesen = _rf_renk_bilesenleri(con, int(rf_id))
        return ana, kaynak, (bilesen or None)

    raise NumuneTalepError(
        'Kaynak formül/UV seçilmeden AR-GE kartı oluşturulamaz. '
        'Hazır RF seçin veya kaynak_uvler + ana_formul_grup_kodu gönderin.',
        400,
        'KAYNAK_BOS',
    )


def _arge_cols(con) -> set[str]:
    return {c[1] for c in con.execute('PRAGMA table_info(nexgen_arge_test)').fetchall()}


def sync_numune_arge_baglantisi(con, talep_id: int, arge_id: int) -> int:
    """
    FAZ-1B — numune.arge_test_id ↔ arge.numune_talep_id tutarlılığı.
    cari kaynağı: numune. Sessiz cari değiştirme yok.
    Migration 141 yoksa 503.
    """
    if 'numune_talep_id' not in _arge_cols(con):
        raise NumuneTalepError(
            'Migration 141 uygulanmamış (arge.numune_talep_id).',
            503, 'MIG141',
        )
    nt = con.execute(
        """
        SELECT id, cari_id, arge_test_id, aktif
        FROM nexgen_numune_talep WHERE id=?
        """,
        (int(talep_id),),
    ).fetchone()
    if not nt or not int(nt['aktif'] or 0):
        raise NumuneTalepError('Talep bulunamadı.', 404)
    ar = con.execute(
        """
        SELECT id, cari_id, numune_talep_id, aktif
        FROM nexgen_arge_test WHERE id=?
        """,
        (int(arge_id),),
    ).fetchone()
    if not ar or not int(ar['aktif'] or 0):
        raise NumuneTalepError('AR-GE kaydı bulunamadı.', 404)

    if ar['numune_talep_id'] not in (None, 0) and int(ar['numune_talep_id']) != int(talep_id):
        raise NumuneTalepError(
            'Bu AR-GE kaydı başka numune talebine bağlı.', 409, 'ARGE_CONFLICT',
        )
    if nt['arge_test_id'] not in (None, 0) and int(nt['arge_test_id']) != int(arge_id):
        raise NumuneTalepError(
            'Bu numune başka AR-GE kaydına bağlı.', 409, 'ARGE_CONFLICT',
        )

    nc = nt['cari_id']
    ac = ar['cari_id']
    if nc not in (None, 0):
        if ac not in (None, 0) and int(ac) != int(nc):
            raise NumuneTalepError(
                'AR-GE cari_id numune ile uyuşmuyor.', 409, 'CARI_MISMATCH',
            )
        if ac in (None, 0):
            con.execute(
                'UPDATE nexgen_arge_test SET cari_id=? WHERE id=?',
                (int(nc), int(arge_id)),
            )

    now = _now()
    if ar['numune_talep_id'] in (None, 0):
        con.execute(
            """
            UPDATE nexgen_arge_test
            SET numune_talep_id=?, guncelleme_tarihi=?
            WHERE id=? AND (numune_talep_id IS NULL OR numune_talep_id=0)
            """,
            (int(talep_id), now, int(arge_id)),
        )
    if nt['arge_test_id'] in (None, 0):
        con.execute(
            """
            UPDATE nexgen_numune_talep
            SET arge_test_id=?, guncelleme_tarihi=?
            WHERE id=? AND (arge_test_id IS NULL OR arge_test_id=0)
            """,
            (int(arge_id), now, int(talep_id)),
        )
    return int(arge_id)


def _ensure_nx_ar_for_talep(
    con, talep_id: int, olusturan_id: int, gonder_payload: dict | None = None,
) -> int:
    """
    Numune talep → tek MUSTERI_RENK köprüsü (FAZ-1D4-B).
    Kaynak çözülemezse kaynaksız skeleton (kaynak UV NULL).
    Ferhat/pigment/RF otomatik oluşmaz. Placeholder UV yok.
    """
    from modules.nexgen.nx_ar_service import (
        NxArError, create_nx_ar, create_musteri_renk_skeleton,
    )

    row = con.execute(
        """
        SELECT id, talep_kodu, arge_test_id, cari_id, oncelik,
               renk_kodu, yeni_renk_aciklama, urun_adi, urun_tipi,
               shore_deger, ek_not, pisme_notu, karsilama_yolu, rf_renk_id
        FROM nexgen_numune_talep WHERE id=? AND aktif=1
        """,
        (talep_id,),
    ).fetchone()
    if not row:
        raise NumuneTalepError('Talep bulunamadı.', 404)
    if row['arge_test_id']:
        arge_id = int(row['arge_test_id'])
        sync_numune_arge_baglantisi(con, talep_id, arge_id)
        con.commit()
        return arge_id

    # Canonical: numune_talep_id ile mevcut AR-GE
    if 'numune_talep_id' in _arge_cols(con):
        by_ntp = con.execute(
            """
            SELECT id FROM nexgen_arge_test
            WHERE aktif=1 AND numune_talep_id=?
            ORDER BY id DESC LIMIT 1
            """,
            (int(talep_id),),
        ).fetchone()
        if by_ntp:
            arge_id = sync_numune_arge_baglantisi(con, talep_id, int(by_ntp['id']))
            con.commit()
            return arge_id

    talep_kodu = row['talep_kodu']
    # Idempotent legacy fallback: aynı AT-M ile mevcut köprü varsa yalnız bağla
    existing = con.execute(
        """
        SELECT id FROM nexgen_arge_test
        WHERE aktif=1 AND test_no=? AND calisma_tipi='MUSTERI_RENK'
        """,
        (talep_kodu,),
    ).fetchone()
    if existing:
        arge_id = int(existing['id'])
        other = con.execute(
            """
            SELECT id FROM nexgen_numune_talep
            WHERE aktif=1 AND arge_test_id=? AND id!=?
            """,
            (arge_id, talep_id),
        ).fetchone()
        if other:
            raise NumuneTalepError(
                'Bu AT-M AR-GE kaydı başka talebe bağlı.', 409, 'ARGE_CONFLICT',
            )
        sync_numune_arge_baglantisi(con, talep_id, arge_id)
        try:
            gelisme_ekle(
                con, talep_id,
                f'Renk Merkezi AR-GE kartı bağlandı (arge_test_id={arge_id})',
                olay_tipi='ARGE_BAGLANDI', kullanici_id=olusturan_id,
            )
        except sqlite3.OperationalError:
            pass
        con.commit()
        return arge_id

    hedef = (
        (row['yeni_renk_aciklama'] or '').strip()
        or (row['renk_kodu'] or '').strip()
        or (row['urun_adi'] or '').strip()
        or talep_kodu
    )
    # FAZ-3A reopen: teknik id kullanıcı notuna yazılmaz (talep_id/arge_test_id ayrı saklanır)
    notlar = ' · '.join(
        x for x in (
            (row['ek_not'] or '').strip(),
            (row['pisme_notu'] or '').strip(),
        ) if x
    )
    shore = None
    if row['shore_deger'] not in (None, ''):
        try:
            shore = float(str(row['shore_deger']).replace(',', '.').rstrip('AaSs'))
        except (TypeError, ValueError):
            shore = None

    kaynaksiz = False
    ana = None
    kaynak_uvler: list | None = None
    renk_bilesenleri = None
    try:
        ana, kaynak_uvler, renk_bilesenleri = _resolve_nx_ar_kaynak(
            con, row, gonder_payload,
        )
    except NumuneTalepError as e:
        if (e.kod or '') in ('KAYNAK_BOS', 'KAYNAK_UV', 'ANA_GRUP', 'RF_UYGUNLUK'):
            kaynaksiz = True
        else:
            raise

    if kaynaksiz or not kaynak_uvler:
        try:
            nx = create_musteri_renk_skeleton(
                con,
                talep_kodu=talep_kodu,
                cari_id=row['cari_id'],
                hedef_renk_adi=hedef,
                kullanici_id=olusturan_id,
                oncelik=(row['oncelik'] or 'NORMAL'),
                urun_ailesi=(row['urun_tipi'] or '').strip() or None,
                renk_kodu=(row['renk_kodu'] or '').strip() or None,
                shore_hedef=shore,
                genel_not=notlar or None,
            )
        except NxArError as e:
            raise NumuneTalepError(
                f'AR-GE kartı oluşturulamadı: {e.message}',
                getattr(e, 'status', 500) or 500,
                getattr(e, 'kod', None) or 'NXAR',
            ) from e
        arge_id = int(nx['arge_test_id'])
    else:
        nx_payload = {
            'calisma_tipi': 'MUSTERI_RENK',
            'ana_formul_grup_kodu': ana,
            'cari_id': row['cari_id'],
            'hedef_renk_adi': hedef,
            'renk_kodu': (row['renk_kodu'] or '').strip() or None,
            'oncelik': (row['oncelik'] or 'NORMAL'),
            'saha_testi_gerekli_mi': 0,
            'talep_referansi': talep_kodu,
            'urun_ailesi': (row['urun_tipi'] or '').strip() or None,
            'shore_hedef': shore,
            'kaynak_uvler': kaynak_uvler,
            'deneme': {
                'numune_orani': 10.0,
                'genel_not': notlar or None,
            },
        }
        if renk_bilesenleri:
            nx_payload['renk_bilesenleri'] = renk_bilesenleri
        try:
            nx = create_nx_ar(con, nx_payload, kullanici_id=olusturan_id)
        except NxArError as e:
            raise NumuneTalepError(
                f'AR-GE kartı oluşturulamadı: {e.message}',
                getattr(e, 'status', 500) or 500,
                getattr(e, 'kod', None) or 'NXAR',
            ) from e

        arge_id = int(nx['arge_test_id'])
        conflict = con.execute(
            "SELECT id FROM nexgen_arge_test WHERE test_no=? AND id!=?",
            (talep_kodu, arge_id),
        ).fetchone()
        if not conflict:
            con.execute(
                "UPDATE nexgen_arge_test SET test_no=?, guncelleme_tarihi=? WHERE id=?",
                (talep_kodu, _now(), arge_id),
            )

    sync_numune_arge_baglantisi(con, talep_id, arge_id)
    try:
        gelisme_ekle(
            con, talep_id,
            f'Renk Merkezi AR-GE kartı bağlandı (arge_test_id={arge_id})',
            olay_tipi='ARGE_BAGLANDI', kullanici_id=olusturan_id,
        )
    except sqlite3.OperationalError:
        pass
    con.commit()
    return arge_id


def _preflight_gonder_kaynak(con, norm: dict) -> None:
    """Commit öncesi zorunlu alan — kaynak UV çözümü _ensure_nx_ar_for_talep'te (kaynaksiz fallback)."""
    ky = norm.get('karsilama_yolu')
    if ky == 'HAZIR_RENK' and not norm.get('rf_renk_id'):
        raise NumuneTalepError('Hazır renk için katalog renk seçimi zorunlu.', 400)


def gonder_arge(con, payload: dict, olusturan_id: int, talep_id: int | None = None) -> dict:
    norm = _validate_payload(payload, zorunlu_gonder=True)
    _assert_mevcut_cari_aktif(con, norm.get('musteri_tipi'), norm.get('cari_id'))
    if not norm.get('talep_eden_kullanici_id'):
        norm['talep_eden_kullanici_id'] = olusturan_id
    _preflight_gonder_kaynak(con, norm)
    now = _now()
    bekleyen_kopru_tamamla = False
    if talep_id:
        row = con.execute(
            'SELECT id, talep_kodu, durum, arge_test_id FROM nexgen_numune_talep WHERE id=? AND aktif=1',
            (talep_id,),
        ).fetchone()
        if not row:
            raise NumuneTalepError('Talep bulunamadı.', 404)
        durum = (row['durum'] or '').strip().upper()
        if durum == 'BEKLEYEN_NUMUNE':
            if row['arge_test_id']:
                return get_talep(con, talep_id)
            # Önceki gönderim commit oldu ama NX-AR köprüsü tamamlanmadı — yeniden dene
            bekleyen_kopru_tamamla = True
            tid = talep_id
        elif durum not in DUZENLENEBILIR_DURUMLAR:
            raise NumuneTalepError('Yalnız taslak talepler gönderilebilir.', 409)
        else:
            norm['guncelleme_tarihi'] = now
            norm['durum'] = 'BEKLEYEN_NUMUNE'
            sets = ','.join(f'{k}=?' for k in norm)
            con.execute(f'UPDATE nexgen_numune_talep SET {sets} WHERE id=?', [*norm.values(), talep_id])
            tid = talep_id
    else:
        norm.update({
            'talep_kodu': uret_talep_kodu(con),
            'durum': 'BEKLEYEN_NUMUNE',
            'olusturan_kullanici_id': olusturan_id,
            'olusturma_tarihi': now,
            'guncelleme_tarihi': now,
            'aktif': 1,
        })
        if not norm.get('talep_eden_kullanici_id'):
            norm['talep_eden_kullanici_id'] = olusturan_id
        cols, vals = _insert_fields(norm)
        cur = con.execute(f'INSERT INTO nexgen_numune_talep ({cols}) VALUES ({",".join(["?"]*len(vals))})', vals)
        tid = int(cur.lastrowid)
    if not bekleyen_kopru_tamamla:
        try:
            gelisme_ekle(
                con, tid, _olusturan_gelisme_metni(con, olusturan_id),
                olay_tipi='TALEP_OLUSTURULDU', kullanici_id=olusturan_id,
            )
        except sqlite3.OperationalError:
            pass
        con.commit()
    # Mehmet → Vedat köprüsü: tek NX-AR + arge_test_id (Ferhat'a otomatik gitmez)
    _ensure_nx_ar_for_talep(con, tid, olusturan_id, gonder_payload=payload)
    return get_talep(con, tid)


def get_talep(con, talep_id: int) -> dict:
    row = con.execute(
        """
        SELECT nt.*,
               c.unvan AS cari_unvan, c.cari_kod,
               te.KullaniciAdi AS talep_eden_kadi, te.AdSoyad AS talep_eden_ad,
               ok.KullaniciAdi AS olusturan_kadi, ok.AdSoyad AS olusturan_ad,
               ia.KullaniciAdi AS isleme_alan_kadi, ia.AdSoyad AS isleme_alan_ad
        FROM nexgen_numune_talep nt
        LEFT JOIN nexgen_cari c ON c.id = nt.cari_id
        LEFT JOIN sistem_kullanici te ON te.Id = nt.talep_eden_kullanici_id
        LEFT JOIN sistem_kullanici ok ON ok.Id = nt.olusturan_kullanici_id
        LEFT JOIN sistem_kullanici ia ON ia.Id = nt.isleme_alan_kullanici_id
        WHERE nt.id=? AND nt.aktif=1
        """,
        (talep_id,),
    ).fetchone()
    if not row:
        raise NumuneTalepError('Talep bulunamadı.', 404)
    d = _row_to_dict(row)
    d['firma_goster'] = _firma_goster(d)
    d['renk_goster'] = _renk_goster(d)
    d['durum_etiket'] = durum_etiket(d.get('durum'))
    return d


def say_bekleyen_numune(con) -> int:
    row = con.execute(
        "SELECT COUNT(*) AS c FROM nexgen_numune_talep "
        "WHERE aktif=1 AND durum='BEKLEYEN_NUMUNE'"
    ).fetchone()
    return int(row['c'] or 0) if row else 0


def liste_bekleyen(con, limit: int = 50, filtre: str | None = None, q: str | None = None) -> list[dict]:
    if filtre:
        durumlar = FILTRE_DURUMLAR.get(filtre, FILTRE_DURUMLAR['bekleyen'])
    else:
        durumlar = ('BEKLEYEN_NUMUNE', 'CALISILIYOR', 'REVIZYONDA')
    ph = ','.join(['?'] * len(durumlar))
    sql = f"""
        SELECT nt.id, nt.talep_kodu, nt.durum, nt.oncelik, nt.hedef_tarih,
               nt.urun_tipi, nt.urun_adi, nt.renk_kodu, nt.yeni_renk_aciklama,
               nt.rf_renk_id, nt.renk_tipi,
               nt.musteri_tipi, nt.aday_firma_adi,
               nt.kaynak_modul, nt.mo_gorusme_id, nt.karsilama_yolu,
               c.unvan AS cari_unvan,
               te.AdSoyad AS talep_eden_ad
        FROM nexgen_numune_talep nt
        LEFT JOIN nexgen_cari c ON c.id = nt.cari_id
        LEFT JOIN sistem_kullanici te ON te.Id = nt.talep_eden_kullanici_id
        WHERE nt.aktif=1 AND (
            nt.durum IN ({ph})
            OR (
                nt.kaynak_modul='MUSTERI_OPERASYONU'
                AND nt.durum='ONAYLANDI'
                AND (nt.arge_test_id IS NULL OR nt.arge_test_id=0)
            )
        )
    """
    params: list[Any] = list(durumlar)
    qn = (q or '').strip()
    if qn:
        like = f'%{qn}%'
        sql += """
          AND (
            nt.talep_kodu LIKE ? OR c.unvan LIKE ? OR nt.aday_firma_adi LIKE ?
            OR te.AdSoyad LIKE ? OR nt.urun_adi LIKE ? OR nt.renk_kodu LIKE ?
            OR nt.yeni_renk_aciklama LIKE ? OR nt.durum LIKE ?
          )
        """
        params.extend([like] * 8)
    sql += """
        ORDER BY
          CASE nt.oncelik WHEN 'KRITIK' THEN 0 WHEN 'ACIL' THEN 1 ELSE 2 END,
          nt.guncelleme_tarihi DESC, nt.id DESC
        LIMIT ?
    """
    params.append(limit)
    rows = con.execute(sql, params).fetchall()
    return [_liste_satir_zengin(r) for r in rows]


def liste_pazarlama(con, kullanici_id: int | None, limit: int = 100) -> list[dict]:
    rows = con.execute(
        """
        SELECT id, talep_kodu, durum, oncelik, olusturma_tarihi, hedef_tarih,
               musteri_tipi, aday_firma_adi, cari_id
        FROM nexgen_numune_talep
        WHERE aktif=1
          AND (olusturan_kullanici_id=? OR talep_eden_kullanici_id=? OR ? IS NULL)
        ORDER BY id DESC
        LIMIT ?
        """,
        (kullanici_id, kullanici_id, kullanici_id, limit),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _ensure_isleme_al_musteri_renk_bridge(con, talep_id: int, kullanici_id: int) -> int:
    """
    FAZ-2C — İşleme Al akıllı köprü (yalnız MUSTERI_RENK skeleton).
    arge_test_id varsa doğrular; yoksa / kırıkysa aynı AT-M ile temel kayıt.
    UV / pigment / RF / Ferhat / barkod / placeholder YOK.
    """
    from modules.nexgen.nx_ar_service import NxArError, create_musteri_renk_skeleton

    row = con.execute(
        """
        SELECT id, talep_kodu, arge_test_id, cari_id, oncelik,
               renk_kodu, yeni_renk_aciklama, urun_adi, urun_tipi,
               shore_deger, ek_not, pisme_notu
        FROM nexgen_numune_talep WHERE id=? AND aktif=1
        """,
        (talep_id,),
    ).fetchone()
    if not row:
        raise NumuneTalepError('Talep bulunamadı.', 404)

    if row['arge_test_id']:
        arge = con.execute(
            """
            SELECT id, test_no, aktif FROM nexgen_arge_test WHERE id=?
            """,
            (int(row['arge_test_id']),),
        ).fetchone()
        if arge and int(arge['aktif'] or 0):
            arge_id = sync_numune_arge_baglantisi(con, talep_id, int(arge['id']))
            con.commit()
            return arge_id
        # Kırık bağ — sessizce yeniden kur
        con.execute(
            """
            UPDATE nexgen_numune_talep
            SET arge_test_id=NULL, guncelleme_tarihi=?
            WHERE id=?
            """,
            (_now(), talep_id),
        )
        con.commit()

    if 'numune_talep_id' in _arge_cols(con):
        by_ntp = con.execute(
            """
            SELECT id FROM nexgen_arge_test
            WHERE aktif=1 AND numune_talep_id=?
            ORDER BY id DESC LIMIT 1
            """,
            (int(talep_id),),
        ).fetchone()
        if by_ntp:
            arge_id = sync_numune_arge_baglantisi(con, talep_id, int(by_ntp['id']))
            con.commit()
            return arge_id

    talep_kodu = (row['talep_kodu'] or '').strip()
    if not talep_kodu:
        raise NumuneTalepError('Talep kodu yok.', 409)

    existing = con.execute(
        """
        SELECT id FROM nexgen_arge_test
        WHERE aktif=1 AND test_no=? AND calisma_tipi='MUSTERI_RENK'
        """,
        (talep_kodu,),
    ).fetchone()
    if existing:
        arge_id = int(existing['id'])
        other = con.execute(
            """
            SELECT id FROM nexgen_numune_talep
            WHERE aktif=1 AND arge_test_id=? AND id!=?
            """,
            (arge_id, talep_id),
        ).fetchone()
        if other:
            raise NumuneTalepError(
                'Bu AT-M AR-GE kaydı başka talebe bağlı.', 409, 'ARGE_CONFLICT',
            )
        sync_numune_arge_baglantisi(con, talep_id, arge_id)
        try:
            gelisme_ekle(
                con, talep_id,
                f'Renk Merkezi AR-GE kartı bağlandı (arge_test_id={arge_id})',
                olay_tipi='ARGE_BAGLANDI', kullanici_id=kullanici_id,
            )
        except sqlite3.OperationalError:
            pass
        con.commit()
        return arge_id

    hedef = (
        (row['yeni_renk_aciklama'] or '').strip()
        or (row['renk_kodu'] or '').strip()
        or (row['urun_adi'] or '').strip()
        or talep_kodu
    )
    # FAZ-3A reopen: teknik id kullanıcı notuna yazılmaz
    notlar = ' · '.join(
        x for x in (
            (row['ek_not'] or '').strip(),
            (row['pisme_notu'] or '').strip(),
        ) if x
    )
    shore = None
    if row['shore_deger'] not in (None, ''):
        try:
            shore = float(str(row['shore_deger']).replace(',', '.').rstrip('AaSs'))
        except (TypeError, ValueError):
            shore = None

    try:
        nx = create_musteri_renk_skeleton(
            con,
            talep_kodu=talep_kodu,
            cari_id=row['cari_id'],
            hedef_renk_adi=hedef,
            kullanici_id=kullanici_id,
            oncelik=(row['oncelik'] or 'NORMAL'),
            urun_ailesi=(row['urun_tipi'] or '').strip() or None,
            renk_kodu=(row['renk_kodu'] or '').strip() or None,
            shore_hedef=shore,
            genel_not=notlar or None,
        )
    except NxArError as e:
        raise NumuneTalepError(
            f'AR-GE kartı oluşturulamadı: {e.message}',
            getattr(e, 'status', 500) or 500,
            getattr(e, 'kod', None) or 'NXAR',
        ) from e

    arge_id = sync_numune_arge_baglantisi(con, talep_id, int(nx['arge_test_id']))
    try:
        gelisme_ekle(
            con, talep_id,
            f'Renk Merkezi AR-GE kartı bağlandı (arge_test_id={arge_id})',
            olay_tipi='ARGE_BAGLANDI', kullanici_id=kullanici_id,
        )
    except sqlite3.OperationalError:
        pass
    con.commit()
    return arge_id


def talep_yeni_renk_mi(talep: dict) -> bool:
    """
    İşleme Al / hydrate: YENI renk talebi mi?
    - karsilama_yolu=YENI_RENK → evet
    - HAZIR_* / YENI_FORMUL → hayır
    - Legacy: karsilama_yolu boş + renk_tipi=YENI → evet
      (AT-M-2026-0029 vb. eski Mehmet talepleri)
    """
    ky = (talep.get('karsilama_yolu') or '').strip().upper()
    if ky == 'YENI_RENK':
        return True
    if ky in ('HAZIR_RENK', 'HAZIR_RF', 'YENI_FORMUL'):
        return False
    return (talep.get('renk_tipi') or '').strip().upper() == 'YENI'


def isleme_al_redirect_url(talep: dict) -> str:
    """
    FAZ-2B/2D/2E — talep türüne göre mevcut ekran.
    YENI_RENK (veya legacy renk_tipi=YENI) → MODÜL-02 yeni-rf hydrate.
    HAZIR_RENK → MODÜL-01 musteri-renk hydrate.
    """
    arge_id = talep.get('arge_test_id')
    tid = talep.get('id')
    if not arge_id or not tid:
        # isleme_al köprüyü kurmuş olmalı
        raise NumuneTalepError('İşleme alınamadı.', 409)
    if talep_yeni_renk_mi(talep):
        return (
            f'/nexgen/tablet/arge/yeni-rf'
            f'?arge_test_id={int(arge_id)}&talep_id={int(tid)}'
        )
    return (
        f'/nexgen/tablet/arge/musteri-renk'
        f'?arge_test_id={int(arge_id)}&talep_id={int(tid)}'
    )


def isleme_al(con, talep_id: int, kullanici_id: int) -> dict:
    """
    FAZ-2C — İşleme Al akıllı giriş.
    Köprü yoksa aynı AT-M ile MUSTERI_RENK skeleton oluşturur (UV/pigment yok).
    Mevcut arge_test_id korunur; idempotent.
    """
    row = con.execute(
        """
        SELECT id, durum, arge_test_id, talep_kodu, karsilama_yolu, kaynak_modul
        FROM nexgen_numune_talep WHERE id=? AND aktif=1
        """,
        (talep_id,),
    ).fetchone()
    if not row:
        raise NumuneTalepError('Talep bulunamadı.', 404)

    mo_onaylandi = (
        (row['kaynak_modul'] or '') == 'MUSTERI_OPERASYONU'
        and (row['durum'] or '') == 'ONAYLANDI'
    )

    # Akıllı köprü: Vedat teknik popup görmez
    arge_id = _ensure_isleme_al_musteri_renk_bridge(con, talep_id, kullanici_id)

    row = con.execute(
        """
        SELECT id, durum, arge_test_id, talep_kodu, kaynak_modul
        FROM nexgen_numune_talep WHERE id=? AND aktif=1
        """,
        (talep_id,),
    ).fetchone()
    if not row or int(row['arge_test_id'] or 0) != int(arge_id):
        raise NumuneTalepError('Talep bulunamadı.', 404)

    from modules.nexgen.nx_ar_service import ensure_nx_ar_teknik_kodu
    ensure_nx_ar_teknik_kodu(con, arge_id, kullanici_id)

    # Idempotent: zaten işleme alınmış (NX-AR teknik kod repair dahil)
    if row['durum'] in ('CALISILIYOR', 'REVIZYONDA'):
        return get_talep(con, talep_id)

    if row['durum'] != 'BEKLEYEN_NUMUNE' and not mo_onaylandi:
        raise NumuneTalepError('Yalnız bekleyen numune işleme alınabilir.', 409)

    now = _now()
    con.execute(
        """
        UPDATE nexgen_numune_talep SET
            durum='CALISILIYOR',
            isleme_alan_kullanici_id=?,
            isleme_alinma_tarihi=?,
            guncelleme_tarihi=?
        WHERE id=? AND arge_test_id=?
        """,
        (kullanici_id, now, now, talep_id, arge_id),
    )
    con.execute(
        "UPDATE nexgen_arge_test SET guncelleme_tarihi=? WHERE id=?",
        (now, arge_id),
    )
    try:
        gelisme_ekle(
            con, talep_id, _isleme_alan_gelisme_metni(con, kullanici_id),
            olay_tipi='ISLEME_ALINDI', kullanici_id=kullanici_id,
        )
    except sqlite3.OperationalError:
        pass
    con.commit()
    return get_talep(con, talep_id)


def vedat_calisma_baslat(con, talep_id: int, kullanici_id: int | None = None) -> dict:
    """İşleme Al ile aynı — yeni AR-GE kaydı üretmez."""
    if not kullanici_id:
        raise NumuneTalepError('Kullanıcı gerekli.', 400)
    return isleme_al(con, talep_id, kullanici_id)


def vedat_kaydet(con, talep_id: int, payload: dict) -> dict:
    row = con.execute(
        'SELECT id, arge_test_id FROM nexgen_numune_talep WHERE id=? AND aktif=1',
        (talep_id,),
    ).fetchone()
    if not row:
        raise NumuneTalepError('Talep bulunamadı.', 404)
    if row['arge_test_id']:
        raise NumuneTalepError('Duplicate AR-GE kartı oluşturulamaz.', 409)

    ferhat = payload.get('vedat_ferhat_testi')
    try:
        ferhat_i = 1 if str(ferhat).lower() in ('1', 'true', 'evet', 'yes') else 0
    except Exception:
        ferhat_i = 0

    sonuc = (payload.get('vedat_sonuc') or '').strip()
    if sonuc and sonuc not in VEDAT_SONUCLAR:
        raise NumuneTalepError('Geçersiz Vedat sonucu.', 400)

    durum = 'CALISILIYOR'
    if sonuc == 'Revizyon':
        durum = 'REVIZYONDA'
    elif sonuc == 'Basarili':
        durum = 'CALISILIYOR'
    elif sonuc == 'Red':
        durum = 'CALISILIYOR'

    pigment = (payload.get('vedat_pigment') or '').strip() or None
    rev_not = (payload.get('vedat_revizyon_notu') or '').strip() or None
    degisiklik = (payload.get('vedat_yapilan_degisiklik') or '').strip() or None
    deneme_t = (payload.get('vedat_deneme_tarihi') or '').strip() or None

    con.execute(
        """
        UPDATE nexgen_numune_talep SET
            vedat_pigment=?,
            vedat_numune_miktari=?,
            vedat_numune_sonucu=?,
            vedat_revizyon_notu=?,
            vedat_yapilan_degisiklik=?,
            vedat_deneme_tarihi=?,
            vedat_ferhat_testi=?,
            vedat_sonuc=?,
            durum=?,
            guncelleme_tarihi=?
        WHERE id=?
        """,
        (
            pigment,
            (payload.get('vedat_numune_miktari') or '').strip() or None,
            (payload.get('vedat_numune_sonucu') or '').strip() or None,
            rev_not,
            degisiklik,
            deneme_t,
            ferhat_i,
            sonuc or None,
            durum,
            _now(),
            talep_id,
        ),
    )
    try:
        if pigment:
            gelisme_ekle(con, talep_id, 'Pigment denemesi yapıldı', olay_tipi='DENEME')
        if rev_not:
            gelisme_ekle(con, talep_id, rev_not, olay_tipi='REVIZYON')
        elif sonuc == 'Revizyon':
            gelisme_ekle(con, talep_id, 'Revizyon gerekli', olay_tipi='REVIZYON')
        if degisiklik:
            gelisme_ekle(con, talep_id, degisiklik, olay_tipi='DEGISIKLIK')
    except sqlite3.OperationalError:
        pass
    con.commit()
    return get_talep(con, talep_id)


def belge_id_guncelle(con, talep_id: int, alan: str, belge_id: int) -> None:
    izin = {'urun_gorsel_belge_id', 'ref_gorsel_belge_id', 'vedat_sonuc_gorsel_belge_id'}
    if alan not in izin:
        raise NumuneTalepError('Geçersiz belge alanı.', 400)
    cur = con.execute(
        f'UPDATE nexgen_numune_talep SET {alan}=?, guncelleme_tarihi=? WHERE id=? AND aktif=1',
        (belge_id, _now(), talep_id),
    )
    if cur.rowcount < 1:
        raise NumuneTalepError('Talep bulunamadı — belge ilişkilendirilemedi.', 404)
    con.commit()


def durum_etiket(durum: str | None) -> str:
    m = {
        'YENI_TALEP': 'Yeni Talep',
        'TASLAK': 'Taslak',
        'BEKLEYEN_NUMUNE': 'Bekleyen Numune',
        'CALISILIYOR': 'Çalışılıyor',
        'REVIZYONDA': 'Revizyonda',
        'FERHAT_TESTINDE': 'Ferhat Testinde',
        'ONAY_BEKLIYOR': 'Onay Bekliyor',
        'ONAYLANDI': 'Onaylandı',
        'RECETE_MERKEZINE_AKTARILDI': 'Reçete Merkezine Aktarıldı',
    }
    return m.get((durum or '').upper(), durum or '—')


def _karsilama_etiket(ky: str | None) -> str:
    m = {
        'HAZIR_RENK': 'Katalogdan Renk Seç',
        'HAZIR_RF': 'Katalogdan Renk Seç',
        'YENI_RENK': 'Yeni Renk Talebi',
        'YENI_FORMUL': 'Yeni Hammadde / Formül Talebi',
    }
    return m.get((ky or '').strip().upper(), (ky or '—'))


def _oncelik_etiket(v: str | None) -> str:
    m = {'NORMAL': 'Normal', 'ACIL': 'Acil', 'KRITIK': 'Kritik'}
    return m.get((v or 'NORMAL').upper(), v or 'Normal')


def _arge_durum_etiket(durum: str | None, saha: int | None = None) -> str:
    d = (durum or '').upper()
    if int(saha or 0) == 1 and d in ('ARGE_HAZIR', 'SAHA_BEKLIYOR', 'FERHAT_BEKLIYOR'):
        if d == 'DENEMEDE':
            return 'Enjeksiyon Denemesi Devam Ediyor'
        return 'Enjeksiyon Denemesi Bekliyor'
    m = {
        'ARGE_HAZIR': 'AR-GE Test',
        'DENEMEDE': 'Enjeksiyon Denemesi Devam Ediyor',
        'REVIZYON_GEREKLI': 'Revizyon Gerekli',
        'ONAY_BEKLIYOR': 'Onay Bekliyor',
        'ONAYA_GONDERILDI': 'Onay Bekliyor',
        'ONAYLANDI': 'Onaylandı',
        'FERHAT_BEKLIYOR': 'Enjeksiyon Denemesi Bekliyor',
        'REDDEDILDI': 'Reddedildi',
    }
    return m.get(d, d or '—')


TAKIP_FILTRE_ANAHTARLARI = (
    'tumu', 'bekleyen', 'vedat', 'ferhat', 'renk_merkezi',
    'onay_bekleyen', 'tamamlanan', 'iptal_red',
)


def _takip_son_tarih(talep: dict, arge: dict | None) -> str:
    aday = [
        (talep.get('guncelleme_tarihi') or '').strip(),
        (talep.get('olusturma_tarihi') or '').strip(),
    ]
    if arge:
        aday.append((arge.get('guncelleme_tarihi') or '').strip())
        aday.append((arge.get('ferhat_kayit_tarihi') or '').strip())
    aday = [a for a in aday if a]
    return max(aday)[:16] if aday else '—'


def _takip_kart_cozumle(talep: dict, arge: dict | None) -> dict:
    """Tek talep için takip kartı alanları — salt okunur."""
    td = (talep.get('durum') or '').upper()
    ad = (arge.get('durum') if arge else '') or ''
    adu = ad.upper()
    saha = int(arge.get('saha_testi_gerekli_mi') or 0) if arge else 0
    gonderildi = td not in ('YENI_TALEP', 'TASLAK')
    vedat_bitti = bool(arge and adu in (
        'ONAY_BEKLIYOR', 'ONAYA_GONDERILDI', 'ONAYLANDI', 'FERHAT_BEKLIYOR',
        'DENEMEDE', 'REDDEDILDI',
    ))
    ferhat_atlandi = bool(arge and saha == 0 and gonderildi)
    ferhat_bitti = bool(
        arge and (
            ferhat_atlandi
            or (arge.get('ferhat_genel_karar') or arge.get('ferhat_kayit_tarihi'))
            or adu in ('ONAY_BEKLIYOR', 'ONAYA_GONDERILDI', 'ONAYLANDI', 'REDDEDILDI')
        )
    )
    rm_bitti = bool(arge and adu in ('ONAY_BEKLIYOR', 'ONAYA_GONDERILDI', 'ONAYLANDI', 'REDDEDILDI'))
    admin_bitti = adu == 'ONAYLANDI' or td in ('ONAYLANDI', 'RECETE_MERKEZINE_AKTARILDI')

    def _step(label: str, durum: str, notu: str = '') -> dict:
        return {'label': label, 'durum': durum, 'not': notu}

    surec = [
        _step('Mehmet', 'tamam' if gonderildi else 'aktif', ''),
        _step('Vedat', 'tamam' if vedat_bitti else ('aktif' if gonderildi and not vedat_bitti else 'bekle'), ''),
    ]
    if ferhat_atlandi:
        surec.append(_step('Ferhat', 'atlandi', 'Atlandı'))
    elif saha == 1:
        fd = 'tamam' if ferhat_bitti else ('aktif' if vedat_bitti and not ferhat_bitti else 'bekle')
        fn = (arge.get('ferhat_genel_karar') if arge else '') or ''
        surec.append(_step('Ferhat', fd, fn))
    surec.append(_step(
        'Renk Merkezi',
        'tamam' if rm_bitti else ('aktif' if ferhat_bitti and not rm_bitti else 'bekle'),
        '',
    ))
    surec.append(_step(
        'Admin Onay',
        'tamam' if admin_bitti else ('aktif' if adu in ('ONAY_BEKLIYOR', 'ONAYA_GONDERILDI') else 'bekle'),
        '',
    ))

    grup = 'bekleyen'
    rozet = 'BEKLEYEN'
    if adu == 'REDDEDILDI' or td == 'REDDEDILDI':
        grup, rozet = 'iptal_red', 'RED'
    elif admin_bitti:
        grup, rozet = 'tamamlanan', 'TAMAMLANDI'
    elif td == 'ONAY_BEKLIYOR' or adu in ('ONAY_BEKLIYOR', 'ONAYA_GONDERILDI'):
        grup, rozet = 'onay_bekleyen', 'ONAY BEKLİYOR'
    elif td == 'FERHAT_TESTINDE' or (arge and saha == 1 and not ferhat_bitti):
        grup, rozet = 'ferhat', 'FERHAT\'TA'
    elif arge and gonderildi and ferhat_bitti and not rm_bitti:
        grup, rozet = 'renk_merkezi', 'RENK MERKEZİ'
    elif td == 'BEKLEYEN_NUMUNE':
        grup, rozet = 'bekleyen', 'BEKLEYEN'
    elif td == 'REVIZYONDA':
        grup, rozet = 'vedat', 'REVİZYON'
    elif td == 'CALISILIYOR':
        grup, rozet = 'vedat', 'VEDAT\'TA'
    elif not gonderildi:
        grup, rozet = 'taslak', 'TASLAK'
    elif td in ('YENI_TALEP', 'TASLAK'):
        grup, rozet = 'taslak', 'TASLAK'

    if not gonderildi:
        kimde = 'Mehmet'
        guncel = 'Taslak — henüz gönderilmedi'
        siradaki = "AR-GE'ye gönderilmeyi bekliyor"
    elif td == 'BEKLEYEN_NUMUNE':
        kimde = 'Vedat'
        guncel = 'Vedat AR-GE değerlendirmesinde'
        siradaki = 'Vedat işleme alacak'
    elif td in ('CALISILIYOR', 'REVIZYONDA') and not rm_bitti:
        kimde = 'Vedat'
        guncel = durum_etiket(td)
        siradaki = 'AR-GE renk çalışması devam ediyor'
    elif arge and saha == 1 and not ferhat_bitti:
        kimde = 'Ferhat'
        guncel = _arge_durum_etiket(ad, saha)
        siradaki = 'Enjeksiyon denemesi'
    elif arge and adu in ('ONAY_BEKLIYOR', 'ONAYA_GONDERILDI'):
        kimde = 'Renk Merkezi / Admin'
        guncel = 'Onay bekliyor'
        siradaki = 'Renk / formül onayı'
    elif admin_bitti:
        kimde = 'Tamamlandı'
        guncel = 'Onaylandı'
        siradaki = 'Süreç tamamlandı'
    elif grup == 'renk_merkezi':
        kimde = 'Renk Merkezi'
        guncel = _arge_durum_etiket(ad, saha) if arge else durum_etiket(td)
        siradaki = 'Renk Merkezi değerlendirmesi'
    else:
        kimde = durum_etiket(td)
        guncel = _arge_durum_etiket(ad, saha) if arge else durum_etiket(td)
        siradaki = '—'

    ferhat_karar = '—'
    if arge:
        if ferhat_atlandi:
            ferhat_karar = 'Atlandı — Enjeksiyon gerekli değil'
        elif arge.get('ferhat_genel_karar'):
            ferhat_karar = str(arge.get('ferhat_genel_karar'))

    renk_kodu = (arge.get('renk_kodu') if arge else None) or talep.get('renk_kodu') or '—'
    at_kodu = (arge.get('test_no') if arge else None) or talep.get('talep_kodu') or '—'

    return {
        'grup': grup,
        'rozet': rozet,
        'kimde': kimde,
        'guncel_durum': guncel,
        'siradaki_islem': siradaki,
        'son_islem_tarihi': _takip_son_tarih(talep, arge),
        'at_kodu': at_kodu,
        'ferhat_karar': ferhat_karar,
        'renk_kodu': renk_kodu,
        'enjeksiyon_gerekli': bool(saha == 1) if arge else False,
        'surec': surec,
    }


def get_takip_liste_readonly(
    con,
    kullanici_id: int | None,
    *,
    admin: bool = False,
    filtre: str | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """Mehmet toplu Numune Takip listesi — yalnız SELECT."""
    uid = None if admin else kullanici_id
    sql = """
        SELECT nt.*,
               c.unvan AS cari_unvan, c.cari_kod,
               t.id AS arge_row_id, t.test_no, t.arge_kodu, t.durum AS arge_durum,
               t.saha_testi_gerekli_mi, t.ferhat_genel_karar, t.ferhat_kayit_tarihi,
               t.renk_kodu AS arge_renk_kodu, t.guncelleme_tarihi AS arge_guncelleme
        FROM nexgen_numune_talep nt
        LEFT JOIN nexgen_cari c ON c.id = nt.cari_id
        LEFT JOIN nexgen_arge_test t ON t.id = nt.arge_test_id AND t.aktif=1
        WHERE nt.aktif=1
          AND (nt.olusturan_kullanici_id=? OR nt.talep_eden_kullanici_id=? OR ? IS NULL)
    """
    params: list[Any] = [uid, uid, uid]
    qn = (q or '').strip()
    if qn:
        like = f'%{qn}%'
        sql += """
          AND (
            nt.talep_kodu LIKE ? OR t.test_no LIKE ? OR c.unvan LIKE ?
            OR c.cari_kod LIKE ? OR nt.aday_firma_adi LIKE ?
            OR nt.urun_adi LIKE ? OR nt.urun_tipi LIKE ?
            OR nt.renk_kodu LIKE ? OR nt.yeni_renk_aciklama LIKE ?
          )
        """
        params.extend([like] * 9)
    sql += ' ORDER BY nt.guncelleme_tarihi DESC, nt.id DESC'
    rows = con.execute(sql, params).fetchall()

    kartlar: list[dict] = []
    sayilar = {k: 0 for k in TAKIP_FILTRE_ANAHTARLARI}
    sayilar['tumu'] = 0

    for row in rows:
        d = _liste_satir_zengin(row)
        arge = None
        if row['arge_row_id']:
            arge = {
                'test_no': row['test_no'],
                'arge_kodu': row['arge_kodu'],
                'durum': row['arge_durum'],
                'saha_testi_gerekli_mi': row['saha_testi_gerekli_mi'],
                'ferhat_genel_karar': row['ferhat_genel_karar'],
                'ferhat_kayit_tarihi': row['ferhat_kayit_tarihi'],
                'renk_kodu': row['arge_renk_kodu'],
                'guncelleme_tarihi': row['arge_guncelleme'],
            }
        coz = _takip_kart_cozumle(d, arge)
        grup = coz['grup']
        sayilar['tumu'] += 1
        if grup in ('taslak', 'bekleyen'):
            sayilar['bekleyen'] += 1
        elif grup == 'vedat':
            sayilar['vedat'] += 1
        elif grup == 'ferhat':
            sayilar['ferhat'] += 1
        elif grup == 'renk_merkezi':
            sayilar['renk_merkezi'] += 1
        elif grup == 'onay_bekleyen':
            sayilar['onay_bekleyen'] += 1
        elif grup == 'tamamlanan':
            sayilar['tamamlanan'] += 1
        elif grup == 'iptal_red':
            sayilar['iptal_red'] += 1

        kart = {
            'id': d['id'],
            'at_kodu': coz['at_kodu'],
            'talep_kodu': d.get('talep_kodu') or '—',
            'musteri_unvan': d.get('firma_goster') or '—',
            'cari_kod': d.get('cari_kod') or '—',
            'urun_model': f"{(d.get('urun_tipi') or '').strip()} · {(d.get('urun_adi') or '—').strip()}".strip(' ·'),
            'talep_turu': _karsilama_etiket(d.get('karsilama_yolu')),
            'renk_goster': d.get('renk_goster') or '—',
            'oncelik': _oncelik_etiket(d.get('oncelik')),
            'acilis_tarihi': (d.get('olusturma_tarihi') or '—')[:10],
            'kimde': coz['kimde'],
            'guncel_durum': coz['guncel_durum'],
            'son_islem_tarihi': coz['son_islem_tarihi'],
            'rozet': coz['rozet'],
            'grup': grup,
            'siradaki_islem': coz['siradaki_islem'],
            'ferhat_karar': coz['ferhat_karar'],
            'renk_kodu': coz['renk_kodu'],
            'enjeksiyon_gerekli': coz['enjeksiyon_gerekli'],
            'surec': coz['surec'],
        }
        kartlar.append(kart)

    filtre_key = (filtre or 'tumu').strip().lower()
    if filtre_key not in TAKIP_FILTRE_ANAHTARLARI:
        filtre_key = 'tumu'

    def _filtre_esles(k: dict) -> bool:
        g = k['grup']
        if filtre_key == 'tumu':
            return True
        if filtre_key == 'bekleyen':
            return g in ('taslak', 'bekleyen')
        return g == filtre_key

    filtrelenmis = [k for k in kartlar if _filtre_esles(k)]
    toplam = len(filtrelenmis)
    sayfa = filtrelenmis[offset: offset + limit]

    return {
        'ok': True,
        'sayilar': sayilar,
        'talepler': sayfa,
        'toplam': toplam,
        'filtre': filtre_key,
        'offset': offset,
        'limit': limit,
    }
