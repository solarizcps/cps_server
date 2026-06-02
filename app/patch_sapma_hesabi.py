# -*- coding: utf-8 -*-
"""
CPS DEV — SAPMA hesabi backend patch scripti
=============================================

KAPSAM:
  modules/ithalat/queries.py icinde 2 fonksiyon guncellenir:
    1) parti_ozet()           - parti detay sayfasi
    2) _parti_ozet_toplu()    - parti listesi KPI'lari

NE DEGISIYOR:
  - Sapma artik yalnizca ESLESEN tiplerden hesaplanir
    (ayni tip icin hem Tahmini > 0 hem Gerceklesen > 0 varsa)
  - Her tip siniflandirilir:
      ESLESEN       -> Tahmini > 0 ve Gerceklesen > 0
      BEKLIYOR      -> Tahmini > 0 ama Gerceklesen = 0
      TAHMINI_YOK   -> Tahmini = 0 ama Gerceklesen > 0   ("YENI" rozet icin)
      YOK           -> ikisi de 0 (gosterme)
  - Para birimi karisikligi flag'i eklenir
  - UI icin hazir kapsam metni eklenir (ornek: "2 tip karsilastirildi")
  - Eski alanlar (sapma_yuzde, tahmini_toplam, vb.) KORUNUR

KURALLAR:
  - Once zaman damgali yedek alir
  - Eski bloklari bulamazsa HICBIR degisiklik yapmaz
  - Syntax dogrulamasi yapar (py_compile)
  - Atomik yazma: once .tmp, basarili olursa rename
  - DB / parser / UI / maliyet kayitlarina DOKUNMAZ

CALISTIRMA:
  cd C:\\cps_dev
  python patch_sapma_hesabi.py
"""

import os
import sys
import shutil
import py_compile
from datetime import datetime

HEDEF = os.path.join('modules', 'ithalat', 'queries.py')


# =====================================================================
# BLOK 1 — parti_ozet()
# =====================================================================
ESKI_1 = '''def parti_ozet(parti_id):
    try:
        parti = parti_getir(parti_id)
        if not parti: return {}

        rows = q("""
            SELECT Tip, Kaynak, SUM(TutarPartiPara) AS Toplam
            FROM ithalat_maliyet_kalem
            WHERE PartiId = ? AND TutarPartiPara IS NOT NULL
              AND (Iptal IS NULL OR Iptal = 0)
            GROUP BY Tip, Kaynak
        """, (parti_id,))

        tip_bazinda = {}
        for r in rows:
            tip = r['Tip']
            if tip not in tip_bazinda:
                tip_bazinda[tip] = {'TAHMINI': 0.0, 'GERCEKLESEN': 0.0}
            tip_bazinda[tip][r['Kaynak']] = float(r['Toplam'] or 0)

        tahmini_toplam = sum(v['TAHMINI'] for v in tip_bazinda.values())
        gerceklesen = sum(v['GERCEKLESEN'] for v in tip_bazinda.values())

        etkin_toplam = 0.0
        tip_detay = []
        for tip, vals in tip_bazinda.items():
            t_tahmini = vals['TAHMINI']
            t_gercek = vals['GERCEKLESEN']
            t_etkin = t_gercek if t_gercek > 0 else t_tahmini
            etkin_toplam += t_etkin
            sapma = None
            if t_tahmini > 0 and t_gercek > 0:
                sapma = round(((t_gercek - t_tahmini) / t_tahmini) * 100, 2)
            tip_detay.append({
                'tip': tip,
                'tahmini': t_tahmini, 'gerceklesen': t_gercek,
                'etkin': t_etkin, 'sapma_yuzde': sapma,
                'bekliyor': (t_gercek == 0 and t_tahmini > 0),
            })

        kg_mal = None
        cift_mal = None
        if parti.get('ToplamKg') and parti['ToplamKg'] > 0:
            kg_mal = round(etkin_toplam / parti['ToplamKg'], 4)
        if parti.get('ToplamCift') and parti['ToplamCift'] > 0:
            cift_mal = round(etkin_toplam / parti['ToplamCift'], 4)

        sapma_genel = None
        if tahmini_toplam > 0:
            sapma_genel = round(((etkin_toplam - tahmini_toplam) / tahmini_toplam) * 100, 2)

        return {
            'parti': parti,
            'tahmini_toplam': round(tahmini_toplam, 4),
            'gerceklesen_toplam': round(gerceklesen, 4),
            'etkin_toplam': round(etkin_toplam, 4),
            'kg_maliyet': kg_mal, 'cift_maliyet': cift_mal,
            'sapma_yuzde': sapma_genel,
            'tip_detay': sorted(tip_detay, key=lambda x: x['tip']),
            'para_birimi': parti['ParaBirimi'],
        }
    except Exception as e:
        log.exception("parti_ozet hata: %s", e)
        return {}'''

YENI_1 = '''def parti_ozet(parti_id):
    try:
        parti = parti_getir(parti_id)
        if not parti: return {}

        # Tip + Kaynak bazinda toplam (parti para birimine cevrilmis tutarlar)
        rows = q("""
            SELECT Tip, Kaynak, SUM(TutarPartiPara) AS Toplam
            FROM ithalat_maliyet_kalem
            WHERE PartiId = ? AND TutarPartiPara IS NOT NULL
              AND (Iptal IS NULL OR Iptal = 0)
            GROUP BY Tip, Kaynak
        """, (parti_id,))

        # Tip bazinda kullanilan para birimleri (karisik tespiti icin)
        para_rows = q("""
            SELECT Tip, ParaBirimi, COUNT(*) AS Adet
            FROM ithalat_maliyet_kalem
            WHERE PartiId = ?
              AND (Iptal IS NULL OR Iptal = 0)
            GROUP BY Tip, ParaBirimi
        """, (parti_id,))

        tip_bazinda = {}
        for r in rows:
            tip = r['Tip']
            if tip not in tip_bazinda:
                tip_bazinda[tip] = {'TAHMINI': 0.0, 'GERCEKLESEN': 0.0}
            tip_bazinda[tip][r['Kaynak']] = float(r['Toplam'] or 0)

        tip_paralar = {}  # {tip: set(['USD', 'TRY'])}
        for r in para_rows:
            tip = r['Tip']
            pb = r['ParaBirimi']
            if tip not in tip_paralar:
                tip_paralar[tip] = set()
            if pb:
                tip_paralar[tip].add(pb)

        tahmini_toplam = sum(v['TAHMINI'] for v in tip_bazinda.values())
        gerceklesen = sum(v['GERCEKLESEN'] for v in tip_bazinda.values())

        # YENI: Siniflandirma + ESLESEN toplamlar
        etkin_toplam = 0.0
        eslesen_tahmini = 0.0
        eslesen_gerceklesen = 0.0
        eslesen_sayi = 0
        bekleyen_sayi = 0
        tahmini_yok_sayi = 0
        herhangi_karisik = False

        tip_detay = []
        for tip, vals in tip_bazinda.items():
            t_tahmini = vals['TAHMINI']
            t_gercek = vals['GERCEKLESEN']
            t_etkin = t_gercek if t_gercek > 0 else t_tahmini
            etkin_toplam += t_etkin

            # Siniflandirma
            if t_tahmini > 0 and t_gercek > 0:
                sinif = 'ESLESEN'
                sapma = round(((t_gercek - t_tahmini) / t_tahmini) * 100, 2)
                eslesen_tahmini += t_tahmini
                eslesen_gerceklesen += t_gercek
                eslesen_sayi += 1
            elif t_tahmini > 0 and t_gercek == 0:
                sinif = 'BEKLIYOR'
                sapma = None
                bekleyen_sayi += 1
            elif t_tahmini == 0 and t_gercek > 0:
                sinif = 'TAHMINI_YOK'
                sapma = None
                tahmini_yok_sayi += 1
            else:
                sinif = 'YOK'
                sapma = None

            paralar = sorted(tip_paralar.get(tip, []))
            tip_karisik = len(paralar) > 1
            if tip_karisik:
                herhangi_karisik = True

            tip_detay.append({
                'tip': tip,
                'tahmini': t_tahmini, 'gerceklesen': t_gercek,
                'etkin': t_etkin, 'sapma_yuzde': sapma,
                'bekliyor': (t_gercek == 0 and t_tahmini > 0),
                # YENI
                'sinif': sinif,
                'para_birimleri': paralar,
                'para_birimi_karisik': tip_karisik,
            })

        kg_mal = None
        cift_mal = None
        if parti.get('ToplamKg') and parti['ToplamKg'] > 0:
            kg_mal = round(etkin_toplam / parti['ToplamKg'], 4)
        if parti.get('ToplamCift') and parti['ToplamCift'] > 0:
            cift_mal = round(etkin_toplam / parti['ToplamCift'], 4)

        # Genel sapma artik SADECE ESLESEN tiplerden
        sapma_genel = None
        if eslesen_tahmini > 0:
            sapma_genel = round(
                ((eslesen_gerceklesen - eslesen_tahmini) / eslesen_tahmini) * 100, 2,
            )

        # UI icin hazir kapsam metni
        if sapma_genel is not None:
            sapma_kapsam_metni = f"{eslesen_sayi} tip karsilastirildi"
        elif (bekleyen_sayi + tahmini_yok_sayi) > 0:
            sapma_kapsam_metni = "Karsilastirilabilir tip yok"
        else:
            sapma_kapsam_metni = "Hesaplanamaz"

        return {
            'parti': parti,
            'tahmini_toplam': round(tahmini_toplam, 4),
            'gerceklesen_toplam': round(gerceklesen, 4),
            'etkin_toplam': round(etkin_toplam, 4),
            'kg_maliyet': kg_mal, 'cift_maliyet': cift_mal,
            'sapma_yuzde': sapma_genel,
            'tip_detay': sorted(tip_detay, key=lambda x: x['tip']),
            'para_birimi': parti['ParaBirimi'],
            # YENI alanlar
            'eslesen_tahmini_toplam':     round(eslesen_tahmini, 4),
            'eslesen_gerceklesen_toplam': round(eslesen_gerceklesen, 4),
            'eslesen_tip_sayisi':         eslesen_sayi,
            'bekleyen_tip_sayisi':        bekleyen_sayi,
            'tahmini_yok_tip_sayisi':     tahmini_yok_sayi,
            'para_birimi_karisik':        herhangi_karisik,
            'sapma_kapsam_metni':         sapma_kapsam_metni,
            'sapma_guvenilir': bool(sapma_genel is not None and not herhangi_karisik),
        }
    except Exception as e:
        log.exception("parti_ozet hata: %s", e)
        return {}'''


# =====================================================================
# BLOK 2 — _parti_ozet_toplu()
# =====================================================================
ESKI_2 = '''def _parti_ozet_toplu(parti_ids):
    try:
        if not parti_ids: return {}
        placeholder = ','.join('?' for _ in parti_ids)
        rows = q(f"""
            SELECT k.PartiId, k.Tip, k.Kaynak,
                   SUM(k.TutarPartiPara) AS Toplam,
                   p.ToplamKg, p.ToplamCift
            FROM ithalat_maliyet_kalem k
            JOIN ithalat_parti p ON p.Id = k.PartiId
            WHERE k.PartiId IN ({placeholder})
              AND k.TutarPartiPara IS NOT NULL
              AND (k.Iptal IS NULL OR k.Iptal = 0)
            GROUP BY k.PartiId, k.Tip, k.Kaynak, p.ToplamKg, p.ToplamCift
        """, tuple(parti_ids))

        parti_data = {}
        for r in rows:
            pid = r['PartiId']
            if pid not in parti_data:
                parti_data[pid] = {
                    'tipler': {}, 'kg': r['ToplamKg'], 'cift': r['ToplamCift'],
                }
            d = parti_data[pid]
            if r['Tip'] not in d['tipler']:
                d['tipler'][r['Tip']] = {'TAHMINI': 0.0, 'GERCEKLESEN': 0.0}
            d['tipler'][r['Tip']][r['Kaynak']] = float(r['Toplam'] or 0)

        sonuc = {}
        for pid, d in parti_data.items():
            tahmini_toplam = sum(v['TAHMINI'] for v in d['tipler'].values())
            gerceklesen = sum(v['GERCEKLESEN'] for v in d['tipler'].values())
            etkin = 0.0
            for vals in d['tipler'].values():
                etkin += (vals['GERCEKLESEN'] if vals['GERCEKLESEN'] > 0
                          else vals['TAHMINI'])
            kg_mal = round(etkin / d['kg'], 4) if (d['kg'] and d['kg'] > 0) else None
            cift_mal = round(etkin / d['cift'], 4) if (d['cift'] and d['cift'] > 0) else None
            sapma = (round(((etkin - tahmini_toplam) / tahmini_toplam) * 100, 2)
                     if tahmini_toplam > 0 else None)
            sonuc[pid] = {
                'tahmini_toplam': round(tahmini_toplam, 2),
                'gerceklesen_toplam': round(gerceklesen, 2),
                'etkin_toplam': round(etkin, 2),
                'kg_maliyet': kg_mal, 'cift_maliyet': cift_mal,
                'sapma_yuzde': sapma,
            }
        return sonuc
    except Exception as e:
        log.exception("_parti_ozet_toplu hata: %s", e)
        return {}'''

YENI_2 = '''def _parti_ozet_toplu(parti_ids):
    try:
        if not parti_ids: return {}
        placeholder = ','.join('?' for _ in parti_ids)
        rows = q(f"""
            SELECT k.PartiId, k.Tip, k.Kaynak,
                   SUM(k.TutarPartiPara) AS Toplam,
                   p.ToplamKg, p.ToplamCift
            FROM ithalat_maliyet_kalem k
            JOIN ithalat_parti p ON p.Id = k.PartiId
            WHERE k.PartiId IN ({placeholder})
              AND k.TutarPartiPara IS NOT NULL
              AND (k.Iptal IS NULL OR k.Iptal = 0)
            GROUP BY k.PartiId, k.Tip, k.Kaynak, p.ToplamKg, p.ToplamCift
        """, tuple(parti_ids))

        parti_data = {}
        for r in rows:
            pid = r['PartiId']
            if pid not in parti_data:
                parti_data[pid] = {
                    'tipler': {}, 'kg': r['ToplamKg'], 'cift': r['ToplamCift'],
                }
            d = parti_data[pid]
            if r['Tip'] not in d['tipler']:
                d['tipler'][r['Tip']] = {'TAHMINI': 0.0, 'GERCEKLESEN': 0.0}
            d['tipler'][r['Tip']][r['Kaynak']] = float(r['Toplam'] or 0)

        sonuc = {}
        for pid, d in parti_data.items():
            tahmini_toplam = sum(v['TAHMINI'] for v in d['tipler'].values())
            gerceklesen = sum(v['GERCEKLESEN'] for v in d['tipler'].values())
            etkin = 0.0
            # YENI: sadece ESLESEN tiplerden sapma hesabi
            eslesen_tahmini = 0.0
            eslesen_gerceklesen = 0.0
            eslesen_sayi = 0
            for vals in d['tipler'].values():
                t_tahmini = vals['TAHMINI']
                t_gercek = vals['GERCEKLESEN']
                etkin += (t_gercek if t_gercek > 0 else t_tahmini)
                if t_tahmini > 0 and t_gercek > 0:
                    eslesen_tahmini += t_tahmini
                    eslesen_gerceklesen += t_gercek
                    eslesen_sayi += 1
            kg_mal = round(etkin / d['kg'], 4) if (d['kg'] and d['kg'] > 0) else None
            cift_mal = round(etkin / d['cift'], 4) if (d['cift'] and d['cift'] > 0) else None
            # Sapma sadece ESLESEN tiplerden
            sapma = None
            if eslesen_tahmini > 0:
                sapma = round(
                    ((eslesen_gerceklesen - eslesen_tahmini) / eslesen_tahmini) * 100, 2,
                )
            sonuc[pid] = {
                'tahmini_toplam': round(tahmini_toplam, 2),
                'gerceklesen_toplam': round(gerceklesen, 2),
                'etkin_toplam': round(etkin, 2),
                'kg_maliyet': kg_mal, 'cift_maliyet': cift_mal,
                'sapma_yuzde': sapma,
                # YENI
                'eslesen_tip_sayisi': eslesen_sayi,
            }
        return sonuc
    except Exception as e:
        log.exception("_parti_ozet_toplu hata: %s", e)
        return {}'''


# =====================================================================
# PATCH MANTIGI
# =====================================================================
BLOKLAR = [
    ('parti_ozet',        ESKI_1, YENI_1),
    ('_parti_ozet_toplu', ESKI_2, YENI_2),
]


def yaz(msg):
    sys.stdout.write(msg + '\n')
    sys.stdout.flush()


def cik(code, msg):
    yaz(msg)
    sys.exit(code)


def main():
    yaz('')
    yaz('=' * 60)
    yaz('  CPS DEV — SAPMA hesabi patch scripti')
    yaz('=' * 60)

    # --- 1) Dosya var mi? ---
    if not os.path.isfile(HEDEF):
        cik(1, f'HATA: Hedef dosya yok: {HEDEF}\n'
               '  Bu scripti C:\\cps_dev\\ dizininde calistir.')

    yaz(f'Hedef  : {HEDEF}')

    # --- 2) Mevcut icerik ---
    try:
        with open(HEDEF, 'r', encoding='utf-8') as f:
            mevcut = f.read()
    except Exception as e:
        cik(2, f'HATA: Dosya okunamadi: {e}')

    # --- 3) Baseline syntax ---
    try:
        compile(mevcut, HEDEF, 'exec')
    except SyntaxError as e:
        cik(3, f'HATA: Mevcut dosyada zaten syntax hatasi var: {e}\n'
               '  Patch uygulanmadi.')

    # --- 4) Tum bloklar bulunuyor mu? ---
    idempotent_sayac = 0  # yeni blok zaten varsa arttir
    for ad, eski, yeni in BLOKLAR:
        es = mevcut.count(eski)
        yn = mevcut.count(yeni)

        if es == 1:
            continue  # normal, degistirilebilir
        if es == 0 and yn >= 1:
            idempotent_sayac += 1
            continue  # zaten guncellenmis
        if es == 0 and yn == 0:
            cik(4, f'HATA: "{ad}" eski bloku bulunamadi '
                   f'(yeni blok da yok).\n'
                   '  Dosya farkli bir versiyonda veya elle degistirilmis.\n'
                   '  Patch uygulanmadi.')
        if es > 1:
            cik(5, f'HATA: "{ad}" eski bloku {es} kez geciyor '
                   f'(beklenen 1).\n  Patch uygulanmadi.')

    if idempotent_sayac == len(BLOKLAR):
        cik(0, '\nBILGI: Tum yeni bloklar zaten dosyada mevcut.\n'
               '  Patch daha once uygulanmis - yeniden uygulanmadi.\n'
               '  Dosya ve yedek dokunulmadi.')

    yaz(f'Bloklar hazir: {len(BLOKLAR)} fonksiyon guncellenecek.')

    # --- 5) Yedek al ---
    damga = datetime.now().strftime('%Y%m%d_%H%M%S')
    yedek_yol = f'{HEDEF}.yedek_{damga}'
    try:
        shutil.copy2(HEDEF, yedek_yol)
    except Exception as e:
        cik(6, f'HATA: Yedek alinamadi: {e}')

    yaz(f'Yedek  : {yedek_yol}')

    # --- 6) Replace - sirayla ---
    yeni_icerik = mevcut
    degisen = []
    for ad, eski, yeni in BLOKLAR:
        if eski in yeni_icerik:
            yeni_icerik = yeni_icerik.replace(eski, yeni, 1)
            degisen.append(ad)
        # yoksa zaten idempotent — atla

    if not degisen:
        cik(7, 'HATA: Replace yapilmadi (beklenmedik).\n'
               '  Orijinal dosya dokunulmadi.')

    if yeni_icerik == mevcut:
        cik(8, 'HATA: Icerik degismedi (beklenmedik).\n'
               '  Orijinal dosya dokunulmadi.')

    # --- 7) Gecici dosya ---
    tmp_yol = HEDEF + '.tmp_patch'
    try:
        with open(tmp_yol, 'w', encoding='utf-8', newline='') as f:
            f.write(yeni_icerik)
    except Exception as e:
        try:
            if os.path.isfile(tmp_yol): os.remove(tmp_yol)
        except Exception:
            pass
        cik(9, f'HATA: Gecici dosya yazilamadi: {e}')

    # --- 8) Syntax dogrula ---
    try:
        py_compile.compile(tmp_yol, doraise=True)
    except py_compile.PyCompileError as e:
        try: os.remove(tmp_yol)
        except Exception: pass
        cik(10, f'HATA: Yeni icerik syntax hatasi veriyor: {e}\n'
                '  Orijinal dosya dokunulmadi.')

    # --- 9) Atomik rename ---
    try:
        os.replace(tmp_yol, HEDEF)
    except Exception as e:
        try:
            if os.path.isfile(tmp_yol): os.remove(tmp_yol)
        except Exception:
            pass
        cik(11, f'HATA: Rename basarisiz: {e}\n'
                '  Orijinal dosya dokunulmadi, yedek duruyor.')

    # --- 10) Son dogrulama ---
    try:
        with open(HEDEF, 'r', encoding='utf-8') as f:
            son = f.read()
    except Exception as e:
        cik(12, f'UYARI: Dogrulama okuma hatasi: {e}\n'
                f'  Yedek: {yedek_yol}')

    eksik = [ad for ad, _eski, yeni in BLOKLAR if yeni not in son]
    if eksik:
        cik(13, 'UYARI: Yazim sonrasi bazi yeni bloklar bulunamadi.\n'
                f'  Eksik: {eksik}\n'
                f'  Yedek: {yedek_yol}')

    # --- BASARILI ---
    yaz('')
    yaz('=' * 60)
    yaz('  PATCH BASARIYLA UYGULANDI')
    yaz('=' * 60)
    yaz(f'Dosya         : {HEDEF}')
    yaz(f'Yedek         : {yedek_yol}')
    yaz(f'Guncellenen   : {", ".join(degisen)}')
    yaz('')
    yaz('Etki:')
    yaz('  - Sapma artik sadece ESLESEN tiplerden hesaplanir')
    yaz('  - Her tip icin sinif alani: ESLESEN / BEKLIYOR / TAHMINI_YOK')
    yaz('  - Para birimi karisikligi flag\'i')
    yaz('  - UI icin hazir kapsam metni (ornek: "2 tip karsilastirildi")')
    yaz('')
    yaz('Geri alma:')
    yaz(f'  copy "{yedek_yol}" "{HEDEF}"')
    yaz('')


if __name__ == '__main__':
    main()
