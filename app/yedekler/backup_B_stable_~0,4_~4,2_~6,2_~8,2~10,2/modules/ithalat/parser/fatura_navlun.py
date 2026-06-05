# -*- coding: utf-8 -*-
"""
CPS DEV - Navlun / Tasimacilik Faturasi Parser
===============================================
BLOK 4.6-d

Hedef: Turk taşimacilik firmalarinin kestigi e-Fatura PDF'leri
       (KTL, Mars Lojistik, Ekol, Omsan, vb.)

Test dosyasi: 9053_ft.pdf (KTL Uluslararasi Tasimacilik)

Cikardigi kalemler (hepsi GERCEKLESEN kaynakli):
  - NAVLUN (alt_kod: AIR / SEA / TRUCK / RAIL) — ana tasima bedeli
  - NAVLUN (alt_kod: EXW_HANDLING / HANDLING / FUEL / TERMINAL vb.)
    — fatura uzerindeki alt kalemler (her biri ayri)

Idempotency anahtari:
  - Fatura No (orn. "KTH2026000001014")

Fail-safe: Parser hatasi belgenin saklanmasini engellemez.
"""
import logging
import os
import re
from modules.ithalat.parser._base import ParseSonuc

log = logging.getLogger("cps.ithalat.parser.fatura_navlun")


# =====================================================================
# SABITLER
# =====================================================================

# Tasima tipi tespit anahtarlari (metinde aranir)
TASIMA_TIPI_KELIMELERI = [
    # (anahtar, alt_kod)
    ('HAVA NAVLUNU',   'AIR'),
    ('AIR FREIGHT',    'AIR'),
    ('AIRFREIGHT',     'AIR'),
    ('DENIZ NAVLUNU',  'SEA'),
    ('SEA FREIGHT',    'SEA'),
    ('OCEAN FREIGHT',  'SEA'),
    ('DENIZYOLU',      'SEA'),
    ('KARA NAVLUNU',   'TRUCK'),
    ('KARAYOLU',       'TRUCK'),
    ('TRUCKING',       'TRUCK'),
    ('TIR TASIMA',     'TRUCK'),
    ('DEMIRYOLU',      'RAIL'),
    ('RAIL FREIGHT',   'RAIL'),
    ('TREN TASIMA',    'RAIL'),
]

# AWB kontrol - hava yolu var mi
AWB_ANAHTARLARI = ['AWB', 'AIR WAYBILL', 'HAVA KONSIMENTO']

# Kalem adindan alt_kod cikarma
KALEM_ALT_KOD_PATTERNLERI = [
    # (regex_pattern, alt_kod, tip)
    # Ana navlun kalemleri
    (r'HAVA\s*NAVLUNU',          'AIR',          'NAVLUN'),
    (r'AIR\s*FREIGHT',           'AIR',          'NAVLUN'),
    (r'DENIZ\s*NAVLUNU',         'SEA',          'NAVLUN'),
    (r'SEA\s*FREIGHT',           'SEA',          'NAVLUN'),
    (r'KARA\s*NAVLUNU',          'TRUCK',        'NAVLUN'),
    (r'DEMIRYOLU\s*NAVLUN',      'RAIL',         'NAVLUN'),
    # Alt kalemler
    (r'EXW\s*BEDEL[İI]?',        'EXW_HANDLING', 'NAVLUN'),
    (r'EX[-\s]?WORKS?\s*HANDLING', 'EXW_HANDLING', 'NAVLUN'),
    (r'FUEL\s*SURCHARGE',        'FUEL',         'NAVLUN'),
    (r'YAKIT\s*[İI]LAVESI?',     'FUEL',         'NAVLUN'),
    (r'\bTHC\b',                 'TERMINAL',     'NAVLUN'),
    (r'TERMINAL\s*HANDLING',     'TERMINAL',     'NAVLUN'),
    (r'ELLEÇLEME',               'HANDLING',     'NAVLUN'),
    (r'HANDLING',                'HANDLING',     'NAVLUN'),
    (r'ORDINO',                  'ORDINO',       'NAVLUN'),
    (r'GÜMRÜK\s*BEYANN',         'GUMRUK',       'GUMRUK'),
    (r'ARD[İI]YE|DEPOLAMA',      'DEPO',         'DEPOLAMA'),
    (r'TAHM[İI]L',               'TAHMIL',       'DIGER'),
    (r'TAHL[İI]YE',              'TAHMIL',       'DIGER'),
    (r'KOM[İI]SYON',             'KOMISYON',     'KOMISYON'),
    (r'S[İI]GORTA',              None,           'SIGORTA'),
]


# =====================================================================
# YARDIMCILAR
# =====================================================================
def _us_float(s):
    """
    Fatura rakam formati: 7,879.20 (US format - virgul binlik, nokta ondalik).
    Donus: float veya None.
    """
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    # Virgulleri binlik sayarak kaldir, nokta ondalik
    s = s.replace(',', '')
    try:
        return float(s)
    except Exception:
        return None


def _tr_float(s):
    """
    Turk format: 409.284,84 (nokta binlik, virgul ondalik).
    Ayrica US format da kabul: 409284.84.
    """
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    # Hem nokta hem virgul var - hangisi ondalik?
    if ',' in s and '.' in s:
        if s.rfind('.') < s.rfind(','):
            # Nokta binlik, virgul ondalik (TR format)
            s = s.replace('.', '').replace(',', '.')
        else:
            # Virgul binlik, nokta ondalik (US format)
            s = s.replace(',', '')
    elif ',' in s:
        # Sadece virgul - ondalik kabul et
        s = s.replace(',', '.')
    try:
        return float(s)
    except Exception:
        return None


def _iso_tarih(s):
    """'17/02/2026' veya '2026-02-17' -> '2026-02-17'."""
    if not s:
        return None
    s = str(s).strip()
    # ISO formati
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', s)
    if m:
        return s
    # DD/MM/YYYY
    m = re.match(r'^(\d{2})/(\d{2})/(\d{4})$', s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    # DD.MM.YYYY
    m = re.match(r'^(\d{2})\.(\d{2})\.(\d{4})$', s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


# =====================================================================
# PDF OKUMA
# =====================================================================
def _pdf_metin(dosya_yol):
    """Tum PDF'in layout korumali text'i. (None, hata_mesaji) veya (metin, None)."""
    try:
        import pdfplumber
    except ImportError:
        return None, "pdfplumber kurulu degil. 'pip install pdfplumber' ile kurun."

    if not os.path.isfile(dosya_yol):
        return None, "Dosya diskte bulunamadi"

    try:
        with pdfplumber.open(dosya_yol) as pdf:
            parcalar = []
            for sayfa in pdf.pages:
                t = sayfa.extract_text(layout=False)
                if t:
                    parcalar.append(t)
            if not parcalar:
                return None, "PDF okundu ama metin cikarilamadi (scan olabilir)"
            return '\n'.join(parcalar), None
    except Exception as e:
        log.exception("PDF acilamadi: %s", e)
        return None, f"PDF acilamadi: {str(e)[:100]}"


# =====================================================================
# ALAN CIKARICILAR
# =====================================================================
def _fatura_no_bul(metin):
    """Fatura No: ... pattern."""
    if not metin:
        return None
    m = re.search(r'Fatura\s*No\s*:\s*(\S+)', metin)
    return m.group(1) if m else None


def _fatura_tarihi_bul(metin):
    """Fatura Tarihi: DD/MM/YYYY pattern."""
    if not metin:
        return None
    m = re.search(r'Fatura\s*Tarihi\s*:\s*(\d{2}[/.]\d{2}[/.]\d{4})', metin)
    return m.group(1) if m else None


def _vade_bul(metin):
    """Odeme Tarihi: DD/MM/YYYY pattern."""
    if not metin:
        return None
    m = re.search(r'[ÖO]deme\s*Tarihi\s*:\s*(\d{2}[/.]\d{2}[/.]\d{4})', metin)
    return m.group(1) if m else None


def _ettn_bul(metin):
    """ETTN UUID formati."""
    if not metin:
        return None
    m = re.search(
        r'ETTN\s*:\s*([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})',
        metin, re.I,
    )
    return m.group(1) if m else None


def _tasimaci_bul(metin):
    """PDF'in ilk dolu satiri = tasimaci firma."""
    if not metin:
        return None
    for satir in metin.split('\n'):
        s = satir.strip()
        if s:
            return s[:200]
    return None


def _tasimaci_vkn_bul(metin):
    """VKN: 10 haneli vergi numarasi."""
    if not metin:
        return None
    m = re.search(r'VKN\s*:\s*(\d{10,11})', metin)
    return m.group(1) if m else None


def _gonderici_bul(metin):
    """Notlardaki 'Gonderici:' etiketinden sonraki firma adi."""
    if not metin:
        return None
    m = re.search(r'G[oö]nderici\s*:\s*([^,\n]+)', metin, re.I)
    if not m:
        return None
    # Virgul gelene kadar veya satir sonuna kadar
    g = m.group(1).strip()
    # "CHENGYU GLOBAL TRADING CO., LIMITED" gibi - virgul sonrasi "LIMITED" da dahil olmasi icin
    # notlar satirinda "Gonderici: X, Adet:" seklinde. X'in icinde virgul varsa kisaltilir.
    # Daha saglam: "Gonderici:" sonrasi "," + bosluk + "Adet|Brut|Sefer|AWB|Yuk" gelene kadar
    m2 = re.search(
        r'G[oö]nderici\s*:\s*(.+?)(?=,\s*(?:Adet|Br[uü]t|Sefer|AWB|Y[uü]k|Kalk[ıi]s|Var[ıi]s)|\n|$)',
        metin, re.I,
    )
    if m2:
        return m2.group(1).strip()[:200]
    return g[:200]


def _awb_bul(metin):
    """AWB (Air Waybill) numarasi."""
    if not metin:
        return None
    m = re.search(r'AWB\s*No\s*:\s*(\d+)', metin, re.I)
    return m.group(1) if m else None


def _adet_bul(metin):
    if not metin:
        return None
    m = re.search(r'Adet\s*:\s*([\d.,]+)', metin)
    return _us_float(m.group(1)) if m else None


def _brut_kg_bul(metin):
    if not metin:
        return None
    m = re.search(r'Br[uü]t\s*A[gğ][ıi]rl[ıi]k\s*:\s*([\d.,]+)', metin, re.I)
    return _us_float(m.group(1)) if m else None


def _etd_eta_bul(metin):
    """ETD ve ETA tarihlerini isoya cevir."""
    if not metin:
        return None, None
    etd = None
    eta = None
    m = re.search(r'ETD\s*:\s*(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})', metin)
    if m:
        etd = _iso_tarih(m.group(1))
    m = re.search(r'ETA\s*:\s*(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})', metin)
    if m:
        eta = _iso_tarih(m.group(1))
    return etd, eta


def _kur_bul(metin):
    if not metin:
        return None
    m = re.search(r'Kur\s*:\s*([\d.,]+)', metin)
    if not m:
        return None
    v = _tr_float(m.group(1))
    # Kur makul aralikta mi? (TRY/USD bugun ~30-50)
    if v and 0.001 < v < 1000:
        return v
    return None


def _tl_karsiligi_bul(metin):
    if not metin:
        return None
    m = re.search(r'Tutar\s*\(TL\)\s*:\s*([\d.,]+)', metin)
    return _tr_float(m.group(1)) if m else None


def _tasima_tipi_bul(metin):
    """Metinde hangi tasima tipi anahtari var?"""
    if not metin:
        return None
    metin_upper = metin.upper()
    for anahtar, tip in TASIMA_TIPI_KELIMELERI:
        if anahtar in metin_upper:
            return tip
    # AWB varsa kesin hava
    for awb_k in AWB_ANAHTARLARI:
        if awb_k in metin_upper:
            return 'AIR'
    return None


def _toplam_tutar_bul(metin):
    """'Odenecek Tutar' veya 'KDV Dahil Toplam Tutar' satirindan."""
    if not metin:
        return None, None
    # Oncelik 1: "Odenecek Tutar"
    m = re.search(
        r'[ÖO]denecek\s*Tutar[^\d]*([\d,]+\.\d+)\s+(USD|EUR|TRY|GBP|CNY)',
        metin, re.I,
    )
    if m:
        return _us_float(m.group(1)), m.group(2)
    # Oncelik 2: "KDV Dahil Toplam Tutar"
    m = re.search(
        r'KDV\s*Dahil\s*Toplam\s*Tutar[^\d]*([\d,]+\.\d+)\s+(USD|EUR|TRY|GBP|CNY)',
        metin, re.I,
    )
    if m:
        return _us_float(m.group(1)), m.group(2)
    # Oncelik 3: "Mal Hizmet Tutari" (KDV'siz)
    m = re.search(
        r'Mal\s*Hizmet\s*Tutar[ıi]\s*([\d,]+\.\d+)\s+(USD|EUR|TRY|GBP|CNY)',
        metin, re.I,
    )
    if m:
        return _us_float(m.group(1)), m.group(2)
    return None, None


def _kalemleri_oku(metin):
    """
    Fatura kalem tablosu. Her satir:
      <ad> <miktar> <birim_fiyat> <para> <kdv_oran> <kdv_tutar> <para> <toplam> <para>

    Donus: [{ad, miktar, birim_fiyat, kdv_oran, kdv_tutar, toplam, para}, ...]
    """
    if not metin:
        return []

    kalem_regex = re.compile(
        r'^(.+?)\s+'                                 # Ad
        r'(\d+(?:[.,]\d+)?)\s+'                       # Miktar
        r'([\d,]+\.\d{2})\s+(USD|EUR|TRY|GBP|CNY)\s+'  # Birim fiyat + para
        r'(\d+\.\d+)\s+'                              # KDV orani
        r'([\d,]+\.\d{2})\s+(USD|EUR|TRY|GBP|CNY)\s+'  # KDV tutar + para
        r'([\d,]+\.\d{2})\s+(USD|EUR|TRY|GBP|CNY)\s*$' # Toplam + para
    )

    kalemler = []
    for satir in metin.split('\n'):
        s = satir.strip()
        if not s:
            continue
        # Basliklari atla
        sl = s.lower()
        if 'mal hizmet' in sl and ('miktar' in sl or 'brim' in sl):
            continue
        if 'toplam iskonto' in sl or 'hesaplanan kdv' in sl:
            continue
        m = kalem_regex.match(s)
        if not m:
            continue
        ad = m.group(1).strip()
        # Banka iban satirlari kalem gibi gorunebilir - filtrele
        if ad.upper().startswith(('TRY ', 'USD ', 'EUR ', 'GBP ')):
            continue
        # Cok kisa veya bozuk adlari atla
        if len(ad) < 3:
            continue
        kalemler.append({
            'ad':            ad,
            'miktar':        _us_float(m.group(2)),
            'birim_fiyat':   _us_float(m.group(3)),
            'fiyat_para':    m.group(4),
            'kdv_oran':      _us_float(m.group(5)),
            'kdv_tutar':     _us_float(m.group(6)),
            'toplam':        _us_float(m.group(8)),
            'para':          m.group(9),
        })
    return kalemler


def _kalem_alt_kod_bul(kalem_ad, tasima_tipi):
    """
    Kalem adindan alt_kod ve tip cikar.
    Donus: (alt_kod, tip). Hicbir pattern uymazsa (tasima_tipi or 'DIGER', 'NAVLUN').
    """
    for pat, alt_kod, tip in KALEM_ALT_KOD_PATTERNLERI:
        if re.search(pat, kalem_ad, re.I):
            return alt_kod, tip
    # Varsayilan: NAVLUN + tasima tipi
    return (tasima_tipi or 'DIGER'), 'NAVLUN'


# =====================================================================
# ANA PARSE FONKSIYONU
# =====================================================================
def parse(belge_row, dosya_yol):
    """
    Navlun / tasimacilik faturasi parse et.
    Donus: ParseSonuc
    """
    try:
        # PDF oku
        metin, hata_msj = _pdf_metin(dosya_yol)
        if not metin:
            return ParseSonuc.hata(
                hata_msj or "PDF okunamadi",
                durum=ParseSonuc.DURUM_FORMAT_HATA,
            )

        log.info(
            "Navlun fatura parse: %s (%d karakter)",
            os.path.basename(dosya_yol), len(metin),
        )

        # --- Temel alanlar ---
        fatura_no = _fatura_no_bul(metin)
        fatura_tarih = _fatura_tarihi_bul(metin)
        vade = _vade_bul(metin)
        ettn = _ettn_bul(metin)
        tasimaci = _tasimaci_bul(metin)
        tasimaci_vkn = _tasimaci_vkn_bul(metin)
        gonderici = _gonderici_bul(metin)
        awb = _awb_bul(metin)
        adet = _adet_bul(metin)
        brut_kg = _brut_kg_bul(metin)
        etd, eta = _etd_eta_bul(metin)
        kur = _kur_bul(metin)
        tl_karsilik = _tl_karsiligi_bul(metin)
        tasima_tipi = _tasima_tipi_bul(metin)
        toplam_tutar, toplam_para = _toplam_tutar_bul(metin)

        # --- Kalemler ---
        ham_kalemler = _kalemleri_oku(metin)

        if not ham_kalemler:
            # YENI: HATA yerine bos oneri listesi - kullanici manuel girsin
            return ParseSonuc.oneri_bekliyor(
                oneriler=[],
                meta={
                    'belge_tipi_etiket': 'Tasima/Navlun Faturasi',
                    'fatura_no':         fatura_no,
                    'fatura_tarihi':     fatura_tarih,
                    'toplam_tutar':      toplam_tutar,
                    'toplam_para':       toplam_para,
                    'tasima_tipi':       tasima_tipi,
                },
                mesaj=(
                    'Bu faturadan kalemler otomatik okunamadi. '
                    'Manuel giris yapiniz - Maliyet sekmesinden kalem ekleyebilirsiniz.'
                ),
                kaynak_ref=fatura_no,
                uyarilar=(
                    [f"Fatura No: {fatura_no}"] if fatura_no else []
                ) + (
                    [f"Fatura Tarihi: {fatura_tarih}"] if fatura_tarih else []
                ),
            )

        # --- Ortak not (tum kalemlere) ---
        ortak_not_parcalari = []
        if fatura_no:
            ortak_not_parcalari.append(f"Fatura: {fatura_no}")
        if fatura_tarih:
            ortak_not_parcalari.append(f"Tarih: {fatura_tarih}")
        if vade:
            ortak_not_parcalari.append(f"Vade: {vade}")
        if awb:
            ortak_not_parcalari.append(f"AWB: {awb}")
        if tasima_tipi:
            ortak_not_parcalari.append(f"Tasima: {tasima_tipi}")
        if gonderici:
            ortak_not_parcalari.append(f"Gonderici: {gonderici}")
        if adet:
            ortak_not_parcalari.append(f"Adet: {adet:.0f}")
        if brut_kg:
            ortak_not_parcalari.append(f"Brut: {brut_kg:.0f} kg")
        if etd:
            ortak_not_parcalari.append(f"ETD: {etd}")
        if eta:
            ortak_not_parcalari.append(f"ETA: {eta}")
        if kur:
            ortak_not_parcalari.append(f"Kur: {kur:.4f}")
        if tl_karsilik:
            ortak_not_parcalari.append(f"TL: {tl_karsilik:,.2f}")

        ortak_not = ' | '.join(ortak_not_parcalari) if ortak_not_parcalari else None
        ortak_not_kisaltilmis = ortak_not[:500] if ortak_not else None

        # --- Kalemleri ParseSonuc formatina cevir ---
        kalemler = []
        for hk in ham_kalemler:
            ad = hk['ad']
            tutar = hk['toplam']
            para = hk['para']

            if not tutar or tutar <= 0:
                continue

            alt_kod, tip = _kalem_alt_kod_bul(ad, tasima_tipi)

            kalem = {
                'tip':         tip,          # NAVLUN (cogunlukla)
                'kaynak':      'GERCEKLESEN',
                'tutar':       tutar,
                'para_birimi': para,
                'alt_kod':     alt_kod,
                'aciklama':    ad,
                'fatura_no':   fatura_no,
                'cari_ad':     tasimaci,
                'not_metni':   ortak_not_kisaltilmis,
            }

            # Kur bilgisi kaleme kur olarak da gecirilmeli mi?
            # TRY/USD kuru fatura ustunde yazili ama bu KTL'nin bildirdigi
            # TCMB kuru, parti ile iliskisi yok. Kaleme manuel kur koymayiz.
            # Parti USD ise USD olarak kalir; TRY partiye yuklenirse kalem TRY
            # otomatik atanmis olur.

            kalemler.append(kalem)

        if not kalemler:
            # YENI: HATA yerine bos oneri listesi
            return ParseSonuc.oneri_bekliyor(
                oneriler=[],
                meta={
                    'belge_tipi_etiket': 'Tasima/Navlun Faturasi',
                    'fatura_no':         fatura_no,
                    'fatura_tarihi':     fatura_tarih,
                    'toplam_tutar':      toplam_tutar,
                    'toplam_para':       toplam_para,
                    'tasima_tipi':       tasima_tipi,
                },
                mesaj=(
                    'Bu faturadan anlamli kalem cikarilamadi. '
                    'Manuel giris yapiniz - Maliyet sekmesinden kalem ekleyebilirsiniz.'
                ),
                kaynak_ref=fatura_no,
                uyarilar=[f"Fatura No: {fatura_no}"] if fatura_no else [],
            )

        # --- Toplam kontrol (opsiyonel - sadece log) ---
        if toplam_tutar and toplam_para:
            hesap = sum(k['tutar'] for k in kalemler if k['para_birimi'] == toplam_para)
            if abs(hesap - toplam_tutar) > 0.02:
                log.warning(
                    "Fatura toplam kontrolu uyumsuz: hesap=%.2f, beyan=%.2f %s",
                    hesap, toplam_tutar, toplam_para,
                )

        # --- parti_bilgi ---
        parti_bilgi = {}
        if tasimaci:
            # Partinin tedarikcisi gibi degil - bu tasimaci.
            # parti_bilgi.tedarikci_ad olarak yazmiyoruz; not olarak yeterli.
            pass
        # Varis tarihi parti'ye yazilabilir (bos ise)
        if eta:
            parti_bilgi['gerceklesen_varis_tarih'] = eta

        # --- uyarilar ---
        uyarilar = []
        if fatura_no:
            uyarilar.append(f"Fatura No: {fatura_no}")
        if fatura_tarih:
            uyarilar.append(f"Fatura Tarihi: {fatura_tarih}")
        if vade:
            uyarilar.append(f"Vade: {vade}")
        if tasimaci:
            uyarilar.append(f"Tasimaci: {tasimaci}")
        if tasimaci_vkn:
            uyarilar.append(f"Tasimaci VKN: {tasimaci_vkn}")
        if gonderici:
            uyarilar.append(f"Gonderici: {gonderici}")
        if tasima_tipi:
            uyarilar.append(f"Tasima Tipi: {tasima_tipi}")
        if awb:
            uyarilar.append(f"AWB No: {awb}")
        if adet and brut_kg:
            uyarilar.append(f"Yuk: {adet:.0f} adet / {brut_kg:.0f} kg")
        elif brut_kg:
            uyarilar.append(f"Brut Agirlik: {brut_kg:.0f} kg")
        if etd or eta:
            parts = []
            if etd: parts.append(f"ETD {etd}")
            if eta: parts.append(f"ETA {eta}")
            uyarilar.append(' | '.join(parts))
        if kur:
            uyarilar.append(f"Fatura kuru: {kur:.4f} TRY/USD")
        if tl_karsilik:
            uyarilar.append(f"TL Karsiligi: {tl_karsilik:,.2f} TRY")
        if toplam_tutar and toplam_para:
            uyarilar.append(f"Toplam Fatura: {toplam_tutar:,.2f} {toplam_para}")
        uyarilar.append(f"{len(kalemler)} kalem okundu")

        # --- ETTN de yardimci not ---
        if ettn:
            uyarilar.append(f"ETTN: {ettn}")

        # --- Fatura No yoksa insan onayi ---
        if not fatura_no:
            return ParseSonuc.insan_onayi(
                kalemler=kalemler,
                mesaj=(
                    f"Fatura parse edildi ({len(kalemler)} kalem) "
                    "ama Fatura No bulunamadi. Manuel ref girilerek uygulanabilir."
                ),
            )

        # --- Basari ---
        toplam_hesap = sum(k['tutar'] for k in kalemler)
        mesaj_para = kalemler[0].get('para_birimi') if kalemler else ''
        mesaj = (
            f"{len(kalemler)} kalem okundu "
            f"(Toplam: {toplam_hesap:,.2f} {mesaj_para}"
            + (f", Tasima: {tasima_tipi}" if tasima_tipi else '')
            + f") - Fatura: {fatura_no}"
        )

        return ParseSonuc.basari(
            kalemler=kalemler,
            mesaj=mesaj,
            parti_bilgi=parti_bilgi,
            uyarilar=uyarilar,
            kaynak_ref=fatura_no,
        )

    except Exception as e:
        log.exception("fatura_navlun.parse fail-safe: %s", e)
        return ParseSonuc.hata(
            f"Parse sirasinda beklenmedik hata: {str(e)[:200]}",
            durum=ParseSonuc.DURUM_PARSER_HATA,
        )
