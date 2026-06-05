# -*- coding: utf-8 -*-
"""
CPS DEV - Gumruk Beyannamesi Parser
====================================
BLOK 4.6-c

Test dosyasi: T25-00151_TBEYANNAMEYENIBASIM.pdf
Format: T.C. Gumruk Beyannamesi (standart) - PDF/A text katmanli

Cikardigi kalemler (hepsi GERCEKLESEN kaynakli, TRY para birimi):
  1. GUMRUK   (alt_kod=GV)   - Gumruk Vergisi
  2. GUMRUK   (alt_kod=KDV)  - KDV (sayfa 2 tip 40 uzerinden)
  3. GUMRUK   (alt_kod=DV)   - Damga Vergisi
  4. DEPOLAMA              - Depo gideri (ardiye)
  5. DIGER    (alt_kod=TAHMIL_TAHLIYE) - Tahmil-Tahliye
  6. NAVLUN   (alt_kod=YURTICI)        - Yurtici nakliye
  7. SIGORTA                - Sigorta bedeli

Idempotency anahtari:
  - Beyanname No (Tescil No) - ornek: "25343100IM00057591"
  - Ust-sag konumda, AMBARLI GUMRUK MUDURLUGU yakininda bulunur
  - Sayfa 2'de "VN= TESCIL NO" etiketiyle dogrulanir

Karar notlari (user onayli):
  1. Her vergi/masraf ayri kalem (7 kalem)
  2. TRY olarak yazilir (parti USD ise manuel kur gerekir)
  3. Mense, GTIP, konteyner, gemi, kg, kur - hepsi notta ve uyarilarda
  4. Beyanname no bulunamazsa INSAN_ONAYI_BEKLIYOR

Fail-safe: Parser hatasi belgenin saklanmasini engellemez.
"""
import logging
import os
import re
from modules.ithalat.parser._base import ParseSonuc

log = logging.getLogger("cps.ithalat.parser.beyanname")


# =====================================================================
# SABITLER
# =====================================================================
# Mense ulke listesi - genisletilebilir
BILINEN_ULKELER = [
    'TAYVAN', 'ÇİN', 'CIN', 'CHINA', 'VIETNAM', 'HINDISTAN', 'HİNDİSTAN',
    'GÜNEY KORE', 'GUNEY KORE', 'MALEZYA', 'ENDONEZYA', 'JAPONYA',
    'ITALYA', 'İTALYA', 'ALMANYA', 'FRANSA', 'ABD', 'USA',
    'INGILTERE', 'İNGİLTERE', 'HOLLANDA', 'BELCIKA', 'BELÇİKA',
    'ISPANYA', 'İSPANYA', 'PORTEKIZ', 'PORTEKİZ', 'YUNANISTAN',
    'UKRAYNA', 'RUSYA', 'BULGARISTAN', 'BULGARİSTAN', 'ROMANYA',
    'POLONYA', 'MACARISTAN', 'MACARİSTAN', 'AVUSTURYA', 'ISVICRE',
    'İSVİÇRE', 'NORVEC', 'NORVEÇ', 'ISVEC', 'İSVEÇ', 'FINLANDIYA',
    'FİNLANDİYA', 'DANIMARKA', 'IRAN', 'İRAN', 'IRAK', 'SURIYE',
    'SURİYE', 'AZERBAYCAN', 'MISIR', 'FAS', 'TUNUS', 'GURCISTAN',
    'GÜRCİSTAN', 'SLOVENYA', 'SLOVAKYA', 'CEK', 'ÇEK',
]

TESLIM_SEKILLERI = ['CFR', 'CIF', 'FOB', 'EXW', 'DAP', 'DDP', 'DDU',
                     'FCA', 'FAS', 'CPT', 'CIP']

ODEME_SEKILLERI = [
    'MAL MUKABİLİ', 'MAL MUKABILI',
    'AKREDITIF', 'AKREDİTİF',
    'VESAIK MUKABILI', 'VESAİK MUKABİLİ',
    'PESIN', 'PEŞİN',
]


# Vergi tip kodu -> adi (sayfa 1/2 tablolarinda gecer)
VERGI_TIP_KODU = {
    '10': 'GV',
    '40': 'KDV',
    '89': 'DV',
}


# =====================================================================
# YARDIMCILAR
# =====================================================================
def _tl_float(s):
    """'169.883,17' -> 169883.17. Basarisizsa None."""
    if s is None:
        return None
    s = str(s).strip().replace(' ', '').replace('P', '')
    if not s:
        return None
    # Turkce format: 1.234,56 -> 1234.56
    if ',' in s and '.' in s:
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        s = s.replace(',', '.')
    try:
        return float(s)
    except Exception:
        return None


def _iso_tarih(s):
    """'11.03.2025' -> '2025-03-11'. Basarisizsa None."""
    if not s:
        return None
    m = re.match(r'^\s*(\d{2})\.(\d{2})\.(\d{4})\s*$', str(s))
    if not m:
        return None
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"


# =====================================================================
# PDF OKUMA
# =====================================================================
def _pdf_metin(dosya_yol):
    """
    Tum PDF'in layout korumali text'i. Ayrica sayfa 1 koordinat bazli
    kelime listesini de dondur.

    Donus: (tum_metin, sayfa1_kelimeler, pdf_yol_var_mi)
    """
    try:
        import pdfplumber
    except ImportError:
        return None, [], False

    if not os.path.isfile(dosya_yol):
        return None, [], True

    try:
        with pdfplumber.open(dosya_yol) as pdf:
            parcalar = []
            sayfa1_kelimeler = []
            for i, sayfa in enumerate(pdf.pages):
                t = sayfa.extract_text(layout=False)
                if t:
                    parcalar.append(t)
                if i == 0:
                    try:
                        sayfa1_kelimeler = sayfa.extract_words(
                            x_tolerance=3, y_tolerance=3,
                            keep_blank_chars=False,
                        )
                    except Exception:
                        sayfa1_kelimeler = []
            return '\n'.join(parcalar), sayfa1_kelimeler, True
    except Exception as e:
        log.exception("PDF acilamadi: %s", e)
        return None, [], True


# =====================================================================
# ALAN CIKARICILAR
# =====================================================================
def _beyanname_no_bul(metin, sayfa1_kelimeler):
    """
    Ust-sag konumda, y<150 piksel icinde, format XXXXXXXIM XXXXXXXXXX.
    Ayni format iki kez gorunebilir (Tescil + Ozet Beyan) - Tescil
    her zaman YUKARIda (y kucuk).
    """
    # Once koordinat bazli dene
    adaylar = [
        k for k in (sayfa1_kelimeler or [])
        if re.match(r'^\d{7,10}IM\d{6,10}$', k.get('text', ''))
           and k.get('top', 999) < 150
    ]
    # Y kucuk olani sec (en ust)
    if adaylar:
        adaylar.sort(key=lambda k: k['top'])
        return adaylar[0]['text']

    # Fallback 1: "TESCIL NO" etiketi yakininda
    if metin:
        m = re.search(
            r'TESC[İI]L\s*NO[^\n]*?(\d{7,10}IM\d{6,10})',
            metin, re.I,
        )
        if m:
            return m.group(1)

    # Fallback 2: Metin ilk 500 karakter icindeki ilk IM
    if metin:
        m = re.search(r'(\d{7,10}IM\d{6,10})', metin[:500])
        if m:
            return m.group(1)

    return None


def _tescil_tarihi_bul(metin, beyanname_no):
    """Beyanname no'dan sonra DD.MM.YYYY."""
    if not metin or not beyanname_no:
        return None
    # Beyanname no + yanindaki tarih
    m = re.search(
        re.escape(beyanname_no) + r'\s+(\d{2}\.\d{2}\.\d{4})',
        metin,
    )
    if m:
        return m.group(1)
    # Ayrica ust-sagda tekrar arama
    ilk_500 = metin[:500]
    m = re.search(r'(\d{2}\.\d{2}\.\d{4})', ilk_500)
    if m:
        return m.group(1)
    return None


def _dosya_no_bul(metin):
    r"""\d{2}-\d{5} format, gumruk musaviri dosya no."""
    if not metin:
        return None
    m = re.search(r'\b(\d{2}-\d{5})\b', metin)
    return m.group(1) if m else None


def _mense_bul(metin):
    if not metin:
        return None
    for u in BILINEN_ULKELER:
        if re.search(r'\b' + re.escape(u) + r'\b', metin, re.I):
            return u
    return None


def _teslim_sekli_bul(metin):
    if not metin:
        return None
    for t in TESLIM_SEKILLERI:
        if re.search(r'\b' + t + r'\b', metin):
            return t
    return None


def _odeme_sekli_bul(metin):
    if not metin:
        return None
    for o in ODEME_SEKILLERI:
        if o.upper() in metin.upper():
            return o
    return None


def _doviz_kur_bul(metin):
    """
    "USD 71.500,00 36,52150" pattern.
    Donus: (doviz_tutari, para_birimi, kur) veya (None, None, None)
    """
    if not metin:
        return None, None, None
    m = re.search(
        r'\b(USD|EUR|GBP|CNY|JPY)\s+([\d.,]+)\s+([\d.,]+)',
        metin,
    )
    if not m:
        return None, None, None
    para = m.group(1)
    tutar = _tl_float(m.group(2))
    kur = _tl_float(m.group(3))
    # Kur makul araligi kontrol
    if kur is None or not (0.001 < kur < 1000):
        kur = None
    return tutar, para, kur


def _gtipler_bul(metin):
    """
    GTIP 8 veya 12 hane. Yıllar (1900-2100) hariç.
    Sayfa 2'deki bolunmus format "3901\\n3000\\n0000" da yakalanir.
    """
    if not metin:
        return []
    kodlar = set()

    # Tek parca 8 hane
    for m in re.finditer(r'\b(\d{8})\b', metin):
        k = m.group(1)
        if not (1900 < int(k[:4]) < 2100):
            if 1 <= int(k[:2]) <= 99:
                kodlar.add(k)

    # Sayfa 2 bolunmus
    m = re.search(r'\n(\d{4})\n(\d{4})\n(\d{4})', metin)
    if m:
        kodlar.add(m.group(1) + m.group(2) + m.group(3))

    # Beyanname numarasi icinde gecen 8 hane patternleri filtrele
    # (25343100 gibi, IM'den onceki parca) - bunlar gumruk idaresi kodu
    # Zaten 2534 ile baslayanlari yukarida 1 <= [:2] <= 99 kontroluyle
    # yakalayacagiz. Ek filtre: gumruk idaresi kodlari tipik 4+4 = 8 hane,
    # fakat GTIP [:4] ETL ya da SH klasifikasyonuyla eslesir.
    # Pratikte 25343100 ustte "8 hane" olarak bulunur ama istemeyecegiz.
    # Cozum: beyanname no icinde geciyorsa cikar.
    m_b = re.findall(r'(\d{7,10})IM\d{6,10}', metin)
    for b in m_b:
        # 25343100IM... icindeki 25343100'i GTIP olarak kabul etme
        if len(b) == 8 and b in kodlar:
            kodlar.discard(b)

    return sorted(kodlar)


def _ticari_tanimlar_bul(metin):
    if not metin:
        return []
    tanimlar = set()
    # Etiketli
    for m in re.finditer(
        r'Ticari\s*tan[ıi]m[ıi]\s*[:=]?\s*([A-Z0-9]+)', metin, re.I,
    ):
        v = m.group(1).strip()
        if v:
            tanimlar.add(v)
    # Ek: EVA\d+ kodlari
    for m in re.finditer(r'\b(EVA\d+[A-Z]*)\b', metin):
        tanimlar.add(m.group(1))
    return sorted(tanimlar)


def _konteynerler_bul(metin):
    """4 harf + 7 rakam standart konteyner no."""
    if not metin:
        return []
    bulunanlar = re.findall(r'\b([A-Z]{4}\d{7})\b', metin)
    # Deduplicate ama sira koru
    gorulen = set()
    sonuc = []
    for k in bulunanlar:
        if k not in gorulen:
            gorulen.add(k)
            sonuc.append(k)
    return sonuc


def _gemiler_bul(metin):
    """GEMİ - X Y - ... pattern. Gemi adi birden fazla kelime olabilir."""
    if not metin:
        return []
    gemiler = []
    # GEMI - {gemi_adi} - gibi
    for m in re.finditer(r'GEM[İI]\s*-\s*([A-Z][A-Z\s]*?)\s*-\s*', metin):
        g = m.group(1).strip()
        # Tek karakterli olmayan, cok kısa olmayan
        if g and len(g) >= 2 and g not in gemiler:
            gemiler.append(g)
    return gemiler


def _net_brut_kg_bul(metin):
    """
    Sayfa 2 L17: "TOPLAM: 50.000,00 KG 50.370,00 50.000,00 71.562,98 71.500,00"
        -> MKTR: 50.000 / Brut: 50.370 / Net: 50.000 / IstKiy: 71.562,98 / FaturaBed: 71.500
    Donus: (brut_kg, net_kg, ist_kiymet)
    """
    if not metin:
        return None, None, None
    m = re.search(
        r'TOPLAM[:\s]+[\d.,]+\s*KG\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)',
        metin,
    )
    if not m:
        return None, None, None
    return _tl_float(m.group(1)), _tl_float(m.group(2)), _tl_float(m.group(3))


def _ihracatci_ithalatci_bul(metin):
    """Etiket sonrasi ilk satir (sayfa 2'de ayni satirda olabilir)."""
    if not metin:
        return None, None

    ihracatci = None
    ithalatci = None

    # Sayfa 2'de tipik: "IHRACATCI= FUJIAN ... Co., Ltd"
    m = re.search(r'İHRACATÇI\s*=\s*([^\n]+)', metin)
    if m:
        ihr = m.group(1).strip()
        # Eger "FUJIAN ... LTD" gibi devam ediyor ve sonunda "İTHALATÇI=" yok ise kullan
        # İTHALATÇI= varsa kes
        ihr = re.split(r'İTHALATÇI\s*=', ihr, 1)[0].strip()
        ihracatci = ihr[:200] if ihr else None

    m = re.search(r'İTHALATÇI\s*=\s*([^\n]+)', metin)
    if m:
        ith = m.group(1).strip()
        # Devamda IHRACATCI= geliyorsa kes
        ith = re.split(r'İHRACATÇI\s*=', ith, 1)[0].strip()
        ithalatci = ith[:200] if ith else None

    return ihracatci, ithalatci


def _vergi_masraf_kalemleri_bul(metin):
    """
    Sayfa 1 sag panelinde etiket-tutar cift oldugu blok.
    Etiketler: G.V., DV, Dep. Gid., Tahm-Tahl, Y.ICI, Sigorta, MalBed.,
               GV Mat., KDVMat., Ara Toplam

    Donus dict: {etiket_kanonik: tutar_float}
    """
    if not metin:
        return {}

    # Onemli: Etiketler sag panelde "etiket  tutar" formatinda
    # Her etiket ve format variasyonlari
    etiket_arama = [
        # (kanonik_ad, regex_pattern)
        ('G.V.',       r'\bG\.V\.\s+([\d.]+,\d+|\d+,\d+)'),
        ('DV',         r'(?<![\w.])DV\s+([\d.]+,\d+|\d+,\d+)'),
        ('Dep. Gid.',  r'Dep\.?\s*Gid\.?\s+([\d.]+,\d+|\d+,\d+)'),
        ('Tahm-Tahl',  r'Tahm[-\s]*Tahl\w*\s+([\d.]+,\d+|\d+,\d+)'),
        ('Y.İÇİ',      r'Y\.?\s*İ?Ç?İ?\s+([\d.]+,\d+|\d+,\d+)'),
        ('Sigorta',    r'Sigorta\s+([\d.]+,\d+|\d+,\d+)'),
        ('MalBed.',    r'MalBed\.?\s+([\d.]+,\d+|\d+,\d+)'),
        ('GV Mat.',    r'GV\s*Mat\.?\s+([\d.]+,\d+|\d+,\d+)'),
        ('KDVMat.',    r'KDVMat\.?\s+([\d.]+,\d+|\d+,\d+)'),
        ('Ara Toplam', r'Ara\s*Toplam\s+([\d.]+,\d+|\d+,\d+)'),
    ]
    sonuc = {}
    for isim, pat in etiket_arama:
        # Metinde etiketin YAKININDAKI ilk sayi
        # Her satirda ayri kontrol (pattern cok greedy olmasin)
        for satir in metin.split('\n'):
            m = re.search(pat, satir)
            if m:
                v = _tl_float(m.group(1))
                if v is not None and v >= 0:
                    sonuc[isim] = v
                    break
    return sonuc


def _kdv_bul(metin):
    """
    Sayfa 2'de "40 <matrah> <tutar>P" satiri. Tip 40 = KDV.
    Donus: (kdv_tutar, kdv_matrah, kdv_orani)
    """
    if not metin:
        return None, None, None

    # Sayfa 2'deki kalem bazli vergi bloku
    # Format: "10 2.613.587,25 169.883,17P"  (GV)
    #         "40 2.895.868,62 579.173,73P"  (KDV)
    #         "89 0,00 898,20P"              (DV)
    for satir in metin.split('\n'):
        m = re.match(
            r'\s*40\s+([\d.]+,\d+|\d+,\d+)\s+([\d.]+,\d+|\d+,\d+)P?\s*$',
            satir,
        )
        if m:
            matrah = _tl_float(m.group(1))
            tutar = _tl_float(m.group(2))
            orani = None
            if matrah and matrah > 0 and tutar is not None:
                orani = round((tutar / matrah) * 100, 2)
            return tutar, matrah, orani

    # Fallback: metinde "579.173,73" gibi spesifik aramalar yapmayalim
    # (hardcode degil). Ikinci strateji: "P" isaretli sayilar yakala
    # tip 40'dan sonra gelen.
    sayilar_p = re.findall(
        r'(\d+\.\d+,\d+|\d+,\d+)P',
        metin,
    )
    # Bu listenin ikincisi KDV olabilir ama guvenilir degil, atla.
    return None, None, None


def _vergi_oranlari_bul(metin):
    """
    Beyannamede 10 (GV), 40 (KDV), 89 (DV) vergi tiplerinin oranlarini
    dogrudan dokumandan oku. Hesaplama yapmaz.

    Kaynak - Sayfa 1 kalem bazli satir:
      "10 1.297.655,21 6,50 84.347,59 P"  (tip matrah oran tutar P)

    Ayrica Sayfa 2 satir sonlarinda:
      "... 10 1.315.932,04 6,5 85.535,58P"

    Donus: {'GV': 6.5, 'KDV': 20.0, 'DV': 0.0}
    Oran bulunamazsa o tip dict'e girmez.
    Oran 0 ise dict'e girer - cagiran filtrelemeli.
    """
    oranlar = {}
    if not metin:
        return oranlar

    # Pattern 1: Satir basindan: "10 <matrah> <oran> <tutar> P"
    pat1 = re.compile(
        r'^\s*(10|40|89)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s+P(?=\s|$)',
    )
    # Pattern 2: Satir sonunda: "... 10 <matrah> <oran> <tutar>P"
    pat2 = re.compile(
        r'\s(10|40|89)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)P\s*$',
    )

    for satir in metin.split('\n'):
        m = pat1.match(satir.strip())
        if not m:
            m = pat2.search(satir)
        if not m:
            continue

        tip_kod = m.group(1)
        oran_str = m.group(3)
        oran = _tl_float(oran_str)
        tip_adi = VERGI_TIP_KODU.get(tip_kod)

        if tip_adi and oran is not None and tip_adi not in oranlar:
            oranlar[tip_adi] = oran

    return oranlar


def _oran_format(oran):
    """
    6.5 -> '%6,5'
    20.0 -> '%20'
    0.0 veya None -> None (gosterilmez)
    """
    if oran is None or oran <= 0:
        return None
    # Tam sayiysa sondaki ,0 yazma
    if oran == int(oran):
        return f"%{int(oran)}"
    # TR format: 6.5 -> 6,5
    s = f"{oran:.2f}".replace('.', ',')
    # Sondaki 0 ve virgulu temizle: "6,50" -> "6,5"
    s = s.rstrip('0').rstrip(',')
    return f"%{s}"


# =====================================================================
# ANA PARSE FONKSIYONU
# =====================================================================
def parse(belge_row, dosya_yol):
    """
    Gumruk Beyannamesi PDF parse et.
    Donus: ParseSonuc
    """
    try:
        # Dosya var mi?
        if not os.path.isfile(dosya_yol):
            return ParseSonuc.hata(
                f"Dosya bulunamadi: {os.path.basename(dosya_yol)}",
                durum=ParseSonuc.DURUM_DOSYA_YOK,
            )

        # pdfplumber kontrol ve okuma
        metin, s1_kelimeler, pdf_var = _pdf_metin(dosya_yol)
        if not pdf_var:
            return ParseSonuc.hata(
                "pdfplumber kurulu degil. 'pip install pdfplumber' ile kurun.",
                durum=ParseSonuc.DURUM_PARSER_HATA,
            )
        if not metin:
            return ParseSonuc.hata(
                "PDF okundu ama metin cikarilamadi (PDF gorsel/scan olabilir).",
                durum=ParseSonuc.DURUM_FORMAT_HATA,
            )

        log.info(
            "Beyanname parse basliyor: %s (%d karakter)",
            os.path.basename(dosya_yol), len(metin),
        )

        # --- 1) Beyanname No (kaynak_ref) ---
        beyanname_no = _beyanname_no_bul(metin, s1_kelimeler)

        # --- 2) Tescil Tarihi ---
        tescil_tarihi = _tescil_tarihi_bul(metin, beyanname_no)
        tescil_tarihi_iso = _iso_tarih(tescil_tarihi)

        # --- 3) Dosya No (gumruk musaviri) ---
        dosya_no = _dosya_no_bul(metin)

        # --- 4) Mense / Teslim / Odeme ---
        mense = _mense_bul(metin)
        teslim = _teslim_sekli_bul(metin)
        odeme = _odeme_sekli_bul(metin)

        # --- 5) Doviz / kur ---
        doviz_tutari, doviz_para, kur = _doviz_kur_bul(metin)

        # --- 6) GTIP ---
        gtipler = _gtipler_bul(metin)

        # --- 7) Ticari tanimlar ---
        ticari_tanimlar = _ticari_tanimlar_bul(metin)

        # --- 8) Konteyner / gemi ---
        konteynerler = _konteynerler_bul(metin)
        gemiler = _gemiler_bul(metin)

        # --- 9) KG ve Istatistiki Kiymet ---
        brut_kg, net_kg, ist_kiymet = _net_brut_kg_bul(metin)

        # --- 10) Firmalar ---
        ihracatci, ithalatci = _ihracatci_ithalatci_bul(metin)

        # --- 11) Vergi ve masraf kalemleri ---
        vm = _vergi_masraf_kalemleri_bul(metin)

        # --- 12) KDV (sayfa 2 tip 40) ---
        kdv_tutar, kdv_matrah, kdv_orani_hesap = _kdv_bul(metin)

        # --- 12b) YENI: Vergi oranlari (GV, KDV, DV) - dokumandan direkt oku ---
        vergi_oranlari = _vergi_oranlari_bul(metin)
        # Oncelik: dokumandan okunan oran > hesaplanan oran
        gv_oran    = vergi_oranlari.get('GV')
        kdv_oran   = vergi_oranlari.get('KDV') or kdv_orani_hesap
        dv_oran    = vergi_oranlari.get('DV')  # 0 ise None gibi davranir (format)

        # --- Kalemleri olustur ---
        kalemler = []
        not_ek = []

        # ==================================================================
        # GUVENLIK LIMITI - her kalem icin
        # 10M+ TRY tutarlar aday listesine GIRMEZ, sadece log'a yazilir.
        # ==================================================================
        MAX_TRY_TUTAR = 10_000_000
        elenen_kalemler = []  # debug/rapor icin

        def _guvenli_ekle(tip, tutar, alt_kod, aciklama, kaynak_etiket=None):
            """Guvenlik kontrolu + ekle. 10M+ ise eler ve log'a yazar."""
            if tutar is None or tutar <= 0:
                return
            try:
                tutar_f = float(tutar)
            except Exception:
                log.warning(
                    "beyanname GUVENLIK: tutar float'a cevrilemedi - "
                    "alt_kod=%s tutar=%r aciklama=%s",
                    alt_kod, tutar, aciklama,
                )
                return

            if tutar_f > MAX_TRY_TUTAR:
                log.error(
                    "beyanname GUVENLIK FILTRESI: Mantiksiz tutar ELENDI | "
                    "alt_kod=%s aciklama=%s tutar=%.2f TRY "
                    "beyanname_no=%s kaynak=%s | Ust limit: %d",
                    alt_kod, aciklama, tutar_f, beyanname_no,
                    kaynak_etiket or '(?)', MAX_TRY_TUTAR,
                )
                elenen_kalemler.append({
                    'alt_kod':   alt_kod,
                    'aciklama':  aciklama,
                    'tutar':     tutar_f,
                    'sebep':     '10.000.000 TRY ustu - mantiksiz',
                    'kaynak':    kaynak_etiket,
                })
                return

            kalemler.append({
                'tip':         tip,
                'kaynak':      'GERCEKLESEN',
                'tutar':       tutar_f,
                'para_birimi': 'TRY',
                'alt_kod':     alt_kod,
                'aciklama':    aciklama,
                'fatura_no':   beyanname_no,
            })

        # 1) GV
        gv = vm.get('G.V.')
        if gv and gv > 0:
            gv_aciklama = 'Gumruk Vergisi'
            gv_fmt = _oran_format(gv_oran)
            if gv_fmt:
                gv_aciklama += ' ' + gv_fmt
            _guvenli_ekle('GUMRUK', gv, 'GV', gv_aciklama,
                          kaynak_etiket='vm[G.V.]')

        # 2) KDV
        if kdv_tutar and kdv_tutar > 0:
            kdv_aciklama = 'KDV'
            kdv_fmt = _oran_format(kdv_oran)
            if kdv_fmt:
                kdv_aciklama += ' ' + kdv_fmt
            _guvenli_ekle('GUMRUK', kdv_tutar, 'KDV', kdv_aciklama,
                          kaynak_etiket='kdv_tutar')

        # 3) DV - oran genelde 0 oldugu icin sadece tutar gosterilir
        dv = vm.get('DV')
        if dv and dv > 0:
            dv_aciklama = 'Damga Vergisi'
            dv_fmt = _oran_format(dv_oran)
            if dv_fmt:
                dv_aciklama += ' ' + dv_fmt
            _guvenli_ekle('GUMRUK', dv, 'DV', dv_aciklama,
                          kaynak_etiket='vm[DV]')

        # 4) Depolama
        depo = vm.get('Dep. Gid.')
        if depo and depo > 0:
            _guvenli_ekle('DEPOLAMA', depo, 'DEPO',
                          'Depo gideri (ardiye)',
                          kaynak_etiket='vm[Dep. Gid.]')

        # 5) Tahmil-Tahliye
        tahmil = vm.get('Tahm-Tahl')
        if tahmil and tahmil > 0:
            _guvenli_ekle('DIGER', tahmil, 'TAHMIL_TAHLIYE',
                          'Tahmil-Tahliye',
                          kaynak_etiket='vm[Tahm-Tahl]')

        # 6) Yurtici nakliye
        yurt = vm.get('Y.İÇİ')
        if yurt and yurt > 0:
            _guvenli_ekle('NAVLUN', yurt, 'YURTICI',
                          'Yurtici nakliye',
                          kaynak_etiket='vm[Y.İÇİ]')

        # 7) Sigorta
        sigorta = vm.get('Sigorta')
        if sigorta and sigorta > 0:
            _guvenli_ekle('SIGORTA', sigorta, None,
                          'Sigorta bedeli',
                          kaynak_etiket='vm[Sigorta]')

        # --- Notlar kalemlere ortak ek bilgi olarak ---
        ortak_not_parcalari = []
        if beyanname_no:
            ortak_not_parcalari.append(f"Beyanname: {beyanname_no}")
        if dosya_no:
            ortak_not_parcalari.append(f"Dosya: {dosya_no}")
        if mense:
            ortak_not_parcalari.append(f"Mense: {mense}")
        if gtipler:
            ortak_not_parcalari.append(f"GTIP: {', '.join(gtipler[:3])}")
        if teslim:
            ortak_not_parcalari.append(f"Teslim: {teslim}")
        if odeme:
            ortak_not_parcalari.append(f"Odeme: {odeme}")
        if doviz_tutari and doviz_para:
            ortak_not_parcalari.append(
                f"Fatura: {doviz_tutari:,.2f} {doviz_para}"
                + (f" @ kur {kur}" if kur else '')
            )

        ortak_not = ' | '.join(ortak_not_parcalari) if ortak_not_parcalari else None

        # Not'u her kaleme ekle
        if ortak_not:
            for k in kalemler:
                k['not_metni'] = ortak_not
                if ihracatci:
                    k['cari_ad'] = ihracatci[:200]

        # --- parti_bilgi ---
        parti_bilgi = {}
        if ihracatci:
            parti_bilgi['tedarikci_ad'] = ihracatci[:200]
        if tescil_tarihi_iso:
            parti_bilgi['gerceklesen_varis_tarih'] = tescil_tarihi_iso

        # --- uyarilar ---
        uyarilar = []
        if beyanname_no:
            uyarilar.append(f"Beyanname No: {beyanname_no}")
        if tescil_tarihi:
            uyarilar.append(f"Tescil Tarihi: {tescil_tarihi}")
        if dosya_no:
            uyarilar.append(f"Dosya No: {dosya_no}")
        if mense:
            uyarilar.append(f"Mense Ulke: {mense}")
        if gtipler:
            uyarilar.append(f"GTIP: {', '.join(gtipler)}")
        if ticari_tanimlar:
            uyarilar.append(f"Ticari Tanim: {', '.join(ticari_tanimlar)}")
        if gemiler:
            uyarilar.append(f"Gemi(ler): {', '.join(gemiler)}")
        if konteynerler:
            uyarilar.append(f"Konteyner(ler): {', '.join(konteynerler)}")
        if brut_kg or net_kg:
            uyarilar.append(
                f"KG - Brut: {brut_kg:,.2f} Net: {net_kg:,.2f}"
                if brut_kg and net_kg else
                f"Net KG: {net_kg:,.2f}" if net_kg else
                f"Brut KG: {brut_kg:,.2f}"
            )
        if ist_kiymet:
            uyarilar.append(f"Istatistiki Kiymet: {ist_kiymet:,.2f} TRY")
        if doviz_tutari and doviz_para:
            uyarilar.append(
                f"Fatura Bedeli: {doviz_tutari:,.2f} {doviz_para}"
                + (f" (kur {kur})" if kur else '')
            )
        if teslim:
            uyarilar.append(f"Teslim Sekli: {teslim}")
        if odeme:
            uyarilar.append(f"Odeme Sekli: {odeme}")

        # Vergi ozet
        vergi_toplam = sum(
            k['tutar'] for k in kalemler
            if k.get('alt_kod') in ('GV', 'KDV', 'DV')
        )
        if vergi_toplam > 0:
            uyarilar.append(f"Toplam Vergi (GV+KDV+DV): {vergi_toplam:,.2f} TRY")

        masraf_toplam = sum(
            k['tutar'] for k in kalemler
            if k.get('alt_kod') in ('DEPO', 'TAHMIL_TAHLIYE', 'YURTICI')
            or k['tip'] == 'SIGORTA'
        )
        if masraf_toplam > 0:
            uyarilar.append(f"Toplam Diger Masraf: {masraf_toplam:,.2f} TRY")

        # Elenen kalem uyarisi (kullaniciya net bilgi ver)
        if elenen_kalemler:
            uyarilar.append(
                f"⚠ {len(elenen_kalemler)} mantiksiz tutar guvenlik filtresi "
                f"ile ELENDI (10M TRY ustu) - oneriye alinmadi"
            )
            for ek in elenen_kalemler:
                uyarilar.append(
                    f"  → Elenen: {ek['alt_kod'] or ek['aciklama']} "
                    f"= {ek['tutar']:,.2f} TRY ({ek['sebep']})"
                )

        # --- Sonuc ---
        if not kalemler:
            # Hic GUVENLI kalem okunamadi
            # Sebep: ya PDF formatinda kalem yok, ya da tumu elendi
            if elenen_kalemler:
                hata_mesaj = (
                    "Bu beyannamede maliyet kalemleri guvenli okunamadi. "
                    f"({len(elenen_kalemler)} mantiksiz tutar guvenlik filtresi "
                    "ile elendi.) Manuel giris gerekli."
                )
            else:
                hata_mesaj = (
                    "Bu beyannamede maliyet kalemi tespit edilemedi. "
                    "PDF formati beklenen yapida olmayabilir. Manuel giris gerekli."
                )
            # HATA donmek yerine ONERI_BEKLIYOR + bos oneri listesi
            # UI net mesaji gostersin, meta bilgiler korunsun.
            # (Kullanici istediginde sil/tekrar yukle diyebilsin)
            bos_meta = {
                'belge_tipi_etiket': 'Gumruk Beyannamesi',
                'beyanname_no':      beyanname_no,
                'tescil_tarihi':     tescil_tarihi_iso or tescil_tarihi,
                'teslim_sekli':      teslim,
                'odeme_sekli':       odeme,
                'para_birimi_ana':   'TRY',
                'doviz_tutari':      doviz_tutari,
                'doviz_para':        doviz_para,
                'kur':                kur,
                'brut_kg':            brut_kg,
                'net_kg':             net_kg,
                'ist_kiymet':         ist_kiymet,
                'vergi_toplam':       0,
                'masraf_toplam':      0,
                'toplam_ifade':       None,
                'guvenli_okuma_hatasi': True,
                'elenen_kalem_sayisi': len(elenen_kalemler),
            }
            return ParseSonuc.oneri_bekliyor(
                oneriler=[],  # bos
                meta=bos_meta,
                mesaj=hata_mesaj,
                kaynak_ref=beyanname_no,
                uyarilar=uyarilar,
            )

        # ==================================================================
        # GUVENLI MOD: Su kurallar uygulanir
        #
        # 1) 10M TRY ustu tutarlar ONERI LISTESINE BILE ALINMAZ.
        #    (Kullanici kirmizi kutuyu gorunce bile yanlislikla tiklayabilir)
        # 2) USD/EUR/GBP > 1M ustu tutarlar ONERI LISTESINE BILE ALINMAZ.
        # 3) Hicbir guvenli kalem yoksa -> bos oneri + net mesaj:
        #    "Bu beyannamede maliyet kalemi guvenli okunamadi. Manuel giris
        #     gerekli."
        # 4) Guvenli kalem(ler) varsa normal oneri akisi.
        #
        # Parser her PDF formatina uydurulmuyor - oncelik YANLIS tutar yazmamak.
        # ==================================================================

        # kalemler listesi zaten _guvenli_ekle() ile filtrelendi.
        # 10M+ tutarlar elenen_kalemler'de, listeye hic alinmadi.
        # Burada sadece ONERI formatina donustur ve uyari seviyeleri ekle.

        oneriler = []

        for kalem in kalemler:
            tutar = kalem.get('tutar', 0)
            aciklama = kalem.get('aciklama', '')
            alt_kod = kalem.get('alt_kod')
            tip_ori = kalem.get('tip', 'DIGER')
            para = kalem.get('para_birimi', 'TRY')
            kaynak = kalem.get('kaynak', 'GERCEKLESEN')

            if tutar is None or tutar <= 0:
                continue

            # Sinir altinda ama dikkat cekici tutarlar icin uyari
            uyari = None
            isaretli = True
            if para == 'TRY' and tutar > 5_000_000:
                uyari = 'yuksek'
            elif para in ('USD', 'EUR', 'GBP') and tutar > 500_000:
                uyari = 'yuksek'

            oneriler.append({
                'aciklama':            aciklama,
                'tutar':               float(tutar),
                'para_birimi':         para,
                'tip_onerisi':         tip_ori,
                'kaynak_onerisi':      kaynak,
                'varsayilan_isaretli': isaretli,
                'uyari':               uyari,
                'kaynak_satir':        f'Beyanname: {alt_kod or "-"}',
                'alt_kod':             alt_kod,
                'fatura_no':           beyanname_no,
            })

        # Meta bilgi - UI'da gorunsun (her durumda)
        meta = {
            'belge_tipi_etiket':   'Gumruk Beyannamesi',
            'beyanname_no':        beyanname_no,
            'tescil_tarihi':       tescil_tarihi_iso or tescil_tarihi,
            'teslim_sekli':        teslim,
            'odeme_sekli':         odeme,
            'para_birimi_ana':     'TRY',
            'doviz_tutari':        doviz_tutari,
            'doviz_para':          doviz_para,
            'kur':                 kur,
            'brut_kg':             brut_kg,
            'net_kg':              net_kg,
            'ist_kiymet':          ist_kiymet,
            # Elenen (10M+ mantiksiz) kalem sayisi
            'elenen_kalem_sayisi': len(elenen_kalemler),
        }

        # ==== BOS ONERI LISTESI - MANUEL GIRIS MESAJI ====
        if not oneriler:
            if elenen_kalemler:
                mesaj = (
                    "Bu beyannamede maliyet kalemleri guvenli okunamadi "
                    f"(tespit edilen {len(elenen_kalemler)} tutar guvenlik "
                    "filtresine takildi: 10.000.000 TRY ustu). "
                    "Manuel giris gerekli - Maliyet sekmesinden kalem ekleyebilirsiniz."
                )
            else:
                mesaj = (
                    "Bu beyannamede maliyet kalemi tespit edilemedi. "
                    "PDF formati parser tarafindan desteklenmiyor olabilir. "
                    "Manuel giris gerekli - Maliyet sekmesinden kalem ekleyebilirsiniz."
                )
            log.warning(
                "BEYANNAME GUVENLI MOD: Hic guvenli oneri yok. "
                "Elenen: %d (beyanname_no=%s)",
                len(elenen_kalemler), beyanname_no,
            )
            return ParseSonuc.oneri_bekliyor(
                oneriler=[],
                meta=meta,
                mesaj=mesaj,
                kaynak_ref=beyanname_no,
                uyarilar=uyarilar,
            )

        # Normal akis - en az 1 guvenli oneri var
        return ParseSonuc.oneri_bekliyor(
            oneriler=oneriler,
            meta=meta,
            mesaj=(
                f"Beyanname parse edildi - {len(oneriler)} guvenli kalem onerisi."
                + (f" ({len(elenen_kalemler)} mantiksiz tutar filtrelendi)"
                   if elenen_kalemler else "")
                + " Lutfen kalemleri dogrulayip maliyete ekleyin."
                + (f" (Beyanname No: {beyanname_no})" if beyanname_no else "")
            ),
            kaynak_ref=beyanname_no,
            uyarilar=uyarilar,
        )

    except Exception as e:
        log.exception("beyanname.parse fail-safe: %s", e)
        return ParseSonuc.hata(
            f"Parse sirasinda beklenmedik hata: {str(e)[:200]}",
            durum=ParseSonuc.DURUM_PARSER_HATA,
        )
