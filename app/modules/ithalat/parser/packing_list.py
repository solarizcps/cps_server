# -*- coding: utf-8 -*-
"""
CPS DEV - Packing List Parser
==============================
Packing List (Koli Listesi) Excel parse eder.

ONEMLI KURAL:
  Bu parser FOB kalemi, NAVLUN kalemi, GUMRUK kalemi URETMEZ.
  Maliyet olusturmaz. Sadece parti metadata'sini zenginlestirir.

Cikardigi bilgiler (sadece bilgi, maliyet degil):
  - Toplam cift (Quantity PRS)
  - Toplam kg (Total Weight)
  - Koli sayisi (CTNS)
  - CBM (Total Cubic Meter)
  - Urun kodu (Item No)
  - Invoice No (idempotency + eslestirme icin)

Davranis:
  - Parti.ToplamCift BOS ise doldurulabilir
  - Parti.ToplamKg BOS ise doldurulabilir
  - CBM parti.Aciklama notuna eklenir (dikkat: tekrar eklenmez)
  - Koli sayisi notlarda belirtilir
  - Parti'de zaten dolu olan alanlari OVERWRITE ETMEZ, uyari verir

Ornek test dosyasi: Packing_list__by_sea_2_5.xls
"""
import logging
import os
import re

from modules.ithalat.parser._base import ParseSonuc

log = logging.getLogger("cps.ithalat.parser.packing_list")


# =====================================================================
# YARDIMCILAR
# =====================================================================
def _norm(v):
    if v is None:
        return ''
    return str(v).strip().replace('\n', ' ').lower()


def _num(v):
    """None, '', sayi-olmayan -> None; aksi halde float."""
    if v is None or v == '':
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(',', '')
    try:
        return float(s)
    except Exception:
        return None


def _aktif_sheet(dosya_yol):
    """Dolu sheet'i ac (dolu olmayan 'Sheet2/3' sheet'leri atla)."""
    try:
        import xlrd
    except ImportError:
        return None, None, ["xlrd kurulu degil - 'pip install xlrd'"]

    try:
        wb = xlrd.open_workbook(dosya_yol, formatting_info=False)
    except Exception as e:
        return None, None, [f"xlrd acamadi: {e}"]

    # Satir sayisi > 5 olan ilk sheet
    for i in range(wb.nsheets):
        s = wb.sheet_by_index(i)
        if s.nrows > 5:
            return s, wb.sheet_names()[i], []
    return None, None, ["Dolu sheet bulunamadi"]


class _SheetProxy:
    """xlrd sheet'ini wrap eden basit yardimci."""
    def __init__(self, sheet):
        self._s = sheet
        self.nrows = sheet.nrows
        self.ncols = sheet.ncols

    def hucre(self, r, c):
        if r < 0 or r >= self.nrows or c < 0 or c >= self.ncols:
            return None
        v = self._s.cell_value(r, c)
        if v == '':
            return None
        return v


# =====================================================================
# ALAN CIKARICILAR
# =====================================================================
def _invoice_no_bul(sp):
    """Invoice NO / PI NO / Proforma NO / Packing ref."""
    bitisik = re.compile(
        r'^(?:pi\s*no|p/i\s*no|proforma\s*no|invoice\s*no\.?|'
        r'packing\s*no|packing\s*list\s*no|reference\s*no)\s*[:：]\s*'
        r'([A-Z0-9][A-Z0-9\-_/]{2,})',
        re.I,
    )
    etiketli = [
        r'^pi\s*no',
        r'^p/i\s*no',
        r'^proforma\s*no',
        r'^invoice\s*no',
        r'^packing\s*no',
        r'^packing\s*list\s*no',
        r'^reference\s*no',
    ]
    for r in range(min(30, sp.nrows)):
        for c in range(sp.ncols):
            v = _norm(sp.hucre(r, c))
            if not v:
                continue

            # Bitisik: "Invoice NO.:PI20251218"
            m = bitisik.match(v)
            if m:
                return m.group(1).upper()

            # Etiket + yan hucre
            if any(re.match(p, v) for p in etiketli):
                for dr, dc in [(0, 1), (0, 2), (1, 0), (1, 1)]:
                    ref = sp.hucre(r + dr, c + dc)
                    if ref is None:
                        continue
                    s = str(ref).strip()
                    if s and re.match(r'^[A-Z0-9][A-Z0-9\-_/]{2,}$', s, re.I):
                        return s.upper()
    return None


def _tedarikci_bul(sp):
    """Seller / Shipper etiketinden veya ilk satirdan."""
    # Once 'SELLER:' veya 'SHIPPER:' etiketini ara
    for r in range(min(15, sp.nrows)):
        for c in range(sp.ncols):
            v = sp.hucre(r, c)
            if not v:
                continue
            vs = str(v).strip()
            m = re.match(r'^(?:seller|shipper|exporter)\s*[:：]\s*(.+)',
                         vs, re.I)
            if m:
                ad = m.group(1).strip()
                if ad and len(ad) > 3:
                    return ad[:200]
    # Fallback: ilk dolu satir (Ingilizce veya Cince firma adi)
    for r in range(min(5, sp.nrows)):
        v = sp.hucre(r, 0)
        if not v:
            continue
        s = str(v).strip()
        # Cince Unicode aralik disinda degilse + yeterli uzunluk
        if (len(s) > 5 and len(s) < 200 and
                not re.match(r'^(tel|fax|add|unit|no\.)', s, re.I)):
            return s[:200]
    return None


def _baslik_satiri_bul(sp):
    """Tabloda 'Item', 'Quantity', 'Weight' vs bulunan satir."""
    anahtarlar = ['item', 'quantity', 'qty', 'weight', 'cbm',
                  'carton', 'prs', 'ctn', 'spec']
    en_iyi_skor = 0
    en_iyi_r = None
    for r in range(min(25, sp.nrows)):
        metin = ''
        for c in range(sp.ncols):
            v = _norm(sp.hucre(r, c))
            metin += ' ' + v
        skor = sum(1 for a in anahtarlar if a in metin)
        if skor > en_iyi_skor and skor >= 3:
            en_iyi_skor = skor
            en_iyi_r = r
    return en_iyi_r


def _kolon_harita(sp, baslik_r):
    """
    Header satirindaki sutun adlarini anahtar kolonlara map et.
    Donus: {'item': 0, 'spec': 1, 'quantity': 7, 'ctns': 9,
            'weight': 11, 'cbm_total': 6, ...}
    """
    harita = {}
    if baslik_r is None:
        return harita

    for c in range(sp.ncols):
        ust = _norm(sp.hucre(baslik_r, c))
        # Bazen header 2 satir - altini da birlestir
        alt = _norm(sp.hucre(baslik_r + 1, c)) if baslik_r + 1 < sp.nrows else ''
        birlesik = (ust + ' ' + alt).strip()

        if not birlesik:
            continue

        # Item / Urun kodu
        if 'item' in birlesik and 'no' in birlesik:
            harita['item'] = c
        elif harita.get('item') is None and re.search(r'\bitem\b|model', birlesik):
            harita['item'] = c

        # Spec / aciklama
        if 'spec' in birlesik or 'description' in birlesik:
            harita.setdefault('spec', c)

        # Carton size
        if 'carton size' in birlesik or 'ctn size' in birlesik:
            harita.setdefault('carton_size', c)

        # CBM - "Total CBM" > "CBM" onceligi
        if 'total cbm' in birlesik:
            harita['cbm_total'] = c
        elif 'cbm' in birlesik and 'cbm_total' not in harita:
            harita['cbm_birim'] = c

        # Quantity PRS (toplam cift)
        # "Quantity (PRS)" veya "Quantity 订单数量"
        if ('quantity' in birlesik and 'prs' in birlesik
                and 'ctn' not in birlesik):
            harita['quantity_prs'] = c
        elif 'prs/ctn' in birlesik or 'prs / ctn' in birlesik:
            harita['prs_per_ctn'] = c

        # CTNS (koli sayisi)
        if ('quantity' in birlesik and 'ctns' in birlesik) or \
           re.search(r'\bctns\b', birlesik) or 'box' in birlesik:
            if 'ctns' not in harita:
                harita['ctns'] = c

        # Weight
        if 'total weight' in birlesik or 'total wgt' in birlesik:
            harita['weight_total'] = c
        elif 'weight/ctn' in birlesik or 'wgt/ctn' in birlesik:
            harita['weight_per_ctn'] = c

    return harita


def _veri_satirlarini_oku(sp, baslik_r, harita):
    """Header sonrasi veri satirlarini oku, TOTAL/TOPLAM satirlarini atla."""
    if baslik_r is None or not harita:
        return []

    # Header 2 satirli olabilir - veri baslik_r+2'den basla
    ilk_veri_r = baslik_r + 1
    # Ustte veri var mi gerçekten?
    test = _norm(sp.hucre(ilk_veri_r, harita.get('item', 0) or 0))
    if not test or test in ('item', 'spec', 'prs', 'ctn'):
        ilk_veri_r = baslik_r + 2

    satirlar = []
    for r in range(ilk_veri_r, sp.nrows):
        # Total satiri atla
        ilk_hucre = _norm(sp.hucre(r, 0))
        if 'total' in ilk_hucre or 'toplam' in ilk_hucre:
            break

        kayit = {}
        for k, c in harita.items():
            v = sp.hucre(r, c)
            if v is None:
                continue
            if k in ('quantity_prs', 'prs_per_ctn', 'ctns',
                     'cbm_total', 'cbm_birim',
                     'weight_total', 'weight_per_ctn'):
                n = _num(v)
                if n is not None:
                    kayit[k] = n
            else:
                kayit[k] = str(v).strip()

        # Bos satir atla
        if not kayit:
            continue
        # En az item veya quantity olmali
        if not kayit.get('item') and not kayit.get('quantity_prs'):
            continue
        satirlar.append(kayit)

    return satirlar


def _gtip_bul(satirlar):
    """Spec metninden HS code / GTIP cikart."""
    gtipler = set()
    pat = re.compile(r'(?:hs\s*code|gtip|hs\s*no|customs\s*code)\s*[:：]?\s*(\d{4}[\.\- ]?\d{2}[\.\- ]?\d{2}(?:[\.\- ]?\d+)*)', re.I)
    for s in satirlar:
        spec = s.get('spec') or ''
        m = pat.search(spec)
        if m:
            # Noktali isaretleri temizle -> sadece rakamlar
            kod = re.sub(r'[^\d]', '', m.group(1))
            if len(kod) >= 6:
                gtipler.add(kod)
    return sorted(gtipler)


# =====================================================================
# ANA PARSE FONKSIYONU
# =====================================================================
def parse(belge_row, dosya_yol):
    """
    Packing List parse - SADECE metadata, maliyet KALEMI URETMEZ.

    Donus: ParseSonuc
        kalemler = []  (HER ZAMAN BOS)
        parti_bilgi = {'toplam_cift': N, 'toplam_kg': N, ...}
        uyarilar = ['CBM: 1.033', 'Koli: 13', ...]
    """
    try:
        if not os.path.isfile(dosya_yol):
            return ParseSonuc.hata(
                f"Dosya bulunamadi: {os.path.basename(dosya_yol)}",
                durum=ParseSonuc.DURUM_DOSYA_YOK,
            )

        sheet, sheet_ad, hatalar = _aktif_sheet(dosya_yol)
        if sheet is None:
            return ParseSonuc.hata(
                "Packing List dosyasi acilamadi: " + '; '.join(hatalar),
                durum=ParseSonuc.DURUM_FORMAT_HATA,
            )

        sp = _SheetProxy(sheet)
        log.info(
            "Packing List parse: %s sheet=%s (%dx%d)",
            os.path.basename(dosya_yol), sheet_ad, sp.nrows, sp.ncols,
        )

        # Alan çıkarımları
        invoice_no = _invoice_no_bul(sp)
        tedarikci = _tedarikci_bul(sp)
        baslik_r = _baslik_satiri_bul(sp)

        if baslik_r is None:
            return ParseSonuc.hata(
                "Packing List: tablo basligi bulunamadi (Item/Quantity/Weight gerekli)",
                durum=ParseSonuc.DURUM_FORMAT_HATA,
            )

        harita = _kolon_harita(sp, baslik_r)

        # En az bir anlamli kolon olmali
        veri_kolonu_var = any(k in harita for k in
                              ('quantity_prs', 'weight_total', 'ctns', 'cbm_total'))
        if not veri_kolonu_var:
            return ParseSonuc.hata(
                "Packing List: Quantity/Weight/CBM kolonu tespit edilemedi",
                durum=ParseSonuc.DURUM_FORMAT_HATA,
            )

        satirlar = _veri_satirlarini_oku(sp, baslik_r, harita)

        if not satirlar:
            return ParseSonuc.hata(
                "Packing List'te veri satiri okunamadi",
                durum=ParseSonuc.DURUM_BOS,
            )

        # Toplamlar
        toplam_cift = sum(int(s.get('quantity_prs') or 0) for s in satirlar)
        toplam_kg = sum(float(s.get('weight_total') or 0) for s in satirlar)
        toplam_koli = sum(int(s.get('ctns') or 0) for s in satirlar)
        toplam_cbm = sum(float(s.get('cbm_total') or 0) for s in satirlar)

        # Urun kodlari
        urunler = [s.get('item') for s in satirlar if s.get('item')]
        urunler = list(dict.fromkeys(urunler))  # tekrarsiz, sirali

        # GTIP
        gtipler = _gtip_bul(satirlar)

        # --- Parti bilgisi (sadece BOS alanlari doldur - backend kontrol etmeli) ---
        parti_bilgi = {}
        if toplam_cift > 0:
            parti_bilgi['toplam_cift'] = toplam_cift
            parti_bilgi['toplam_cift_kaynak'] = 'packing_list'  # backend bos ise doldur
        if toplam_kg > 0:
            parti_bilgi['toplam_kg'] = round(toplam_kg, 2)
            parti_bilgi['toplam_kg_kaynak'] = 'packing_list'
        if tedarikci:
            parti_bilgi['tedarikci_ad'] = tedarikci
            parti_bilgi['tedarikci_ad_kaynak'] = 'packing_list'

        # Aciklamaya eklenecek notlar
        aciklama_ekleri = []
        if toplam_koli > 0:
            aciklama_ekleri.append(f"Koli: {toplam_koli}")
        if toplam_cbm > 0:
            aciklama_ekleri.append(f"CBM: {toplam_cbm:.3f}")
        if aciklama_ekleri:
            parti_bilgi['aciklama_ekle'] = ' | '.join(aciklama_ekleri)

        # --- Uyarilar ---
        uyarilar = []
        if invoice_no:
            uyarilar.append(f"Invoice No: {invoice_no}")
        if tedarikci:
            uyarilar.append(f"Tedarikci: {tedarikci}")
        if urunler:
            uyarilar.append(f"Urun(ler): {', '.join(urunler[:5])}")
        if toplam_cift:
            uyarilar.append(f"Toplam cift: {toplam_cift:,}")
        if toplam_kg:
            uyarilar.append(f"Toplam kg: {toplam_kg:,.2f}")
        if toplam_koli:
            uyarilar.append(f"Koli sayisi: {toplam_koli}")
        if toplam_cbm:
            uyarilar.append(f"CBM: {toplam_cbm:.3f} m3")
        if gtipler:
            uyarilar.append(f"GTIP: {', '.join(gtipler)}")
        uyarilar.append("NOT: Packing List maliyet kalemi URETMEZ - sadece parti bilgisi guncellenir")

        # --- Tespit edilen kolonlar (UI icin) ---
        tespit = {}
        for k, c in harita.items():
            try:
                harf = chr(ord('A') + c)
            except Exception:
                harf = str(c)
            # Kolon tipine gore Turkce
            kolon_ad = {
                'item':          'Ürün Kodu',
                'spec':          'Açıklama',
                'carton_size':   'Koli Boyutu',
                'cbm_total':     'Toplam CBM',
                'cbm_birim':     'Birim CBM',
                'quantity_prs':  'Miktar (çift)',
                'prs_per_ctn':   'Koli Başı Çift',
                'ctns':          'Koli Sayısı',
                'weight_total':  'Toplam Ağırlık',
                'weight_per_ctn':'Koli Başı Ağırlık',
            }.get(k, k)
            tespit[kolon_ad] = f"Kolon {harf}"

        # --- Guven skoru ---
        # Packing List icin basit mantik: ana alanlar bulundu mu
        skor = 50
        detay = []
        detay.append({'madde': f'Header satiri bulundu (L{baslik_r})',
                      'durum': 'ok', 'puan': 0})
        if invoice_no:
            skor += 15
            detay.append({'madde': f'Invoice No: {invoice_no}',
                          'durum': 'ok', 'puan': 15})
        else:
            detay.append({'madde': 'Invoice No bulunamadi - idempotency zayif',
                          'durum': 'uyari', 'puan': 0})
        if toplam_cift > 0:
            skor += 15
            detay.append({'madde': f'Toplam cift: {toplam_cift:,}',
                          'durum': 'ok', 'puan': 15})
        if toplam_kg > 0:
            skor += 10
            detay.append({'madde': f'Toplam kg: {toplam_kg:,.2f}',
                          'durum': 'ok', 'puan': 10})
        if toplam_koli > 0 or toplam_cbm > 0:
            skor += 10
            detay.append({'madde': f'Koli: {toplam_koli}, CBM: {toplam_cbm:.3f}',
                          'durum': 'ok', 'puan': 10})

        if skor > 100:
            skor = 100

        mesaj = (
            f"Packing List islendi - "
            f"{toplam_cift:,} cift, {toplam_kg:,.0f} kg, "
            f"{toplam_koli} koli, {toplam_cbm:.2f} m3"
        )

        # Packing List icin MALIYET YAZIM YOK - META_GUNCELLENDI
        # Parti.ToplamCift/ToplamKg otomatik guncellenir (overwrite yok)
        # Bu BASARI durumudur - "UYGULANDI ama BOS" yanlistir
        return ParseSonuc.meta_guncellendi(
            parti_bilgi=parti_bilgi,
            meta={
                'belge_tipi_etiket': 'Packing List',
                'invoice_no':        invoice_no,
                'toplam_cift':       toplam_cift,
                'toplam_kg':         toplam_kg,
                'toplam_koli':       toplam_koli,
                'toplam_cbm':        toplam_cbm,
            },
            mesaj=mesaj,
            kaynak_ref=invoice_no,
            uyarilar=uyarilar,
        )

    except Exception as e:
        log.exception("packing_list.parse fail-safe: %s", e)
        return ParseSonuc.hata(
            f"Parse sirasinda beklenmedik hata: {str(e)[:200]}",
            durum=ParseSonuc.DURUM_PARSER_HATA,
        )
