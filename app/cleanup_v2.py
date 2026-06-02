# -*- coding: utf-8 -*-
"""
CPS DEV - Guvenli Temizlik Scripti V2
========================================

Veritabani temizlik araci. 3 asamali:

  1) MANTIKSIZ TUTARLARI IPTAL ET
     - TRY > 10,000,000 -> Iptal=1
     - CNY > 10,000,000 -> Iptal=1
     - USD/EUR/GBP > 1,000,000 -> Iptal=1

  2) DUPLICATE AKTIF KALEMLERI IPTAL ET
     Ayni (PartiId + KaynakBelgeRef + Tip + Tutar + ParaBirimi + Kaynak)
     olan aktif kalemlerden sadece en yenisini (MAX Id) birak.
     Bu ozellikle override sonrasi artan kalemleri temizler -
     'Ayni PI icin aktif tek FOB' kuralini garanti eder.

  3) UYGULANDI AMA KALEM YOK DUZELTMESI
     belge_parse'de ParseDurum='UYGULANDI' ama BelgeId'ye bagli aktif
     kalem bulunmayan kayitlari UYGULANDI_BOS'a cevir.
     META_GUNCELLENDI durumu ATLANIR (Packing List gibi - dogru durum).

GUVENLIK OZELLIKLERI:
  - Transaction: Tum degisiklikler tek bir COMMIT'te. Hata olursa ROLLBACK.
  - Dry-run: Onaydan once DB'ye hicbir sey yazilmaz.
  - Yedek kontrolu: Son 24 saat icinde backup yoksa uyarir.
  - Detayli rapor: Her degisiklik tek tek yazilir.
  - META_GUNCELLENDI: Packing List durumuna DOKUNULMAZ.

KULLANIM:
  cd C:\\cps_dev
  python cleanup_v2.py
"""
import os
import sqlite3
import sys
from datetime import datetime

# =====================================================================
# SABITLER
# =====================================================================
DB_PATH = os.path.join(os.getcwd(), 'mock_data.db')

# Limitler
LIMIT_TRY = 10_000_000
LIMIT_USD_EUR_GBP = 1_000_000
LIMIT_CNY = 10_000_000

# Korunacak parse durumlari
DOKUNULMAZ_PARSE_DURUM = {'META_GUNCELLENDI'}

# UYGULANDI_BOS kontrol edilecek durumlar
UYGULANDI_DURUMLARI = ('UYGULANDI', 'OK', 'YENIDEN_ISLENDI')


# =====================================================================
# YARDIMCILAR
# =====================================================================
def _ayrac(baslik=None, karakter='='):
    cizgi = karakter * 78
    if baslik:
        print(f"\n{cizgi}")
        print(f" {baslik}")
        print(f"{cizgi}")
    else:
        print(cizgi)


def _yedek_kontrol(db_path):
    """Son 24 saat icinde yedek var mi kontrol et."""
    try:
        klasor = os.path.dirname(db_path) or '.'
        yedekler = []
        for f in os.listdir(klasor):
            if f.startswith('mock_data.db.backup') or \
               f.startswith('mock_data.db.bak'):
                tam = os.path.join(klasor, f)
                try:
                    boyut = os.path.getsize(tam)
                    mtime = os.path.getmtime(tam)
                    yas_dakika = (datetime.now().timestamp() - mtime) / 60
                    yedekler.append((f, boyut, yas_dakika))
                except Exception:
                    pass
        yedekler.sort(key=lambda x: x[2])
        guncel_var = any(y[2] < 24 * 60 for y in yedekler)
        return guncel_var, yedekler
    except Exception:
        return False, []


def _onay_al(soru='Devam (evet/hayir): '):
    try:
        c = input(f"  {soru}").strip().lower()
    except EOFError:
        return False
    return c in ('evet', 'e', 'yes', 'y')


# =====================================================================
# TESPITLER
# =====================================================================
def _mantiksiz_tespit(cur):
    return cur.execute("""
        SELECT Id, PartiId, Tip, Tutar, ParaBirimi,
               KaynakBelgeId, KaynakBelgeRef, Aciklama
        FROM ithalat_maliyet_kalem
        WHERE (Iptal IS NULL OR Iptal = 0)
          AND (
              (ParaBirimi = 'TRY' AND Tutar > ?)
              OR (ParaBirimi = 'CNY' AND Tutar > ?)
              OR (ParaBirimi IN ('USD', 'EUR', 'GBP') AND Tutar > ?)
          )
        ORDER BY PartiId, Id
    """, (LIMIT_TRY, LIMIT_CNY, LIMIT_USD_EUR_GBP)).fetchall()


def _duplicate_tespit(cur):
    return cur.execute("""
        SELECT
            PartiId, KaynakBelgeRef, Tip, Tutar, ParaBirimi, Kaynak,
            COUNT(*) AS Adet,
            GROUP_CONCAT(Id) AS Idler,
            MAX(Id) AS SonId
        FROM ithalat_maliyet_kalem
        WHERE (Iptal IS NULL OR Iptal = 0)
          AND KaynakBelgeRef IS NOT NULL
          AND KaynakBelgeRef != ''
        GROUP BY PartiId, KaynakBelgeRef, Tip, Tutar, ParaBirimi, Kaynak
        HAVING COUNT(*) > 1
        ORDER BY PartiId, KaynakBelgeRef
    """).fetchall()


def _uygulandi_bos_tespit(cur, planlanan_iptal_set):
    """UYGULANDI ama aktif kalem yok - META_GUNCELLENDI haric."""
    placeholder_list = ','.join('?' for _ in UYGULANDI_DURUMLARI)
    parse_kayitlari = cur.execute(f"""
        SELECT Id, BelgeId, PartiId, BelgeTipi,
               ParseDurum, KaynakBelgeRef, UygulananKalemSayisi
        FROM ithalat_belge_parse
        WHERE ParseDurum IN ({placeholder_list})
        ORDER BY PartiId, BelgeId
    """, UYGULANDI_DURUMLARI).fetchall()

    bos_listesi = []
    for pk in parse_kayitlari:
        belge_id = pk['BelgeId']
        if not belge_id:
            continue

        aktif_kalemler = cur.execute("""
            SELECT Id FROM ithalat_maliyet_kalem
            WHERE KaynakBelgeId = ? AND (Iptal IS NULL OR Iptal = 0)
        """, (belge_id,)).fetchall()

        kalan_aktif = [
            k['Id'] for k in aktif_kalemler
            if k['Id'] not in planlanan_iptal_set
        ]

        if len(kalan_aktif) == 0:
            bos_listesi.append(dict(pk))
    return bos_listesi


# =====================================================================
# ANA FONKSIYON
# =====================================================================
def main():
    _ayrac("CPS DEV - GUVENLI TEMIZLIK V2")
    print(" 3 asamali: Mantiksiz tutar + Duplicate + UYGULANDI_BOS")
    print(" Transaction korumali | Onay gerekli | META_GUNCELLENDI dokunulmaz")
    _ayrac(karakter='=')

    if not os.path.isfile(DB_PATH):
        print(f"\n  HATA: {DB_PATH} bulunamadi.")
        print(f"  Bu scripti C:\\cps_dev\\ klasoru icinde calistirin.")
        sys.exit(1)

    db_boyut = os.path.getsize(DB_PATH) / 1024
    print(f"\n  DB dosyasi: {DB_PATH}")
    print(f"  Boyut:      {db_boyut:,.1f} KB")

    _ayrac("YEDEK KONTROLU", '-')
    guncel_var, yedekler = _yedek_kontrol(DB_PATH)
    if yedekler:
        print(f"  Bulunan yedek dosyalari ({len(yedekler)} adet):")
        for ad, bt, yas in yedekler[:5]:
            yas_str = (f"{yas/60:.1f} saat once" if yas > 60
                       else f"{yas:.0f} dakika once")
            print(f"    - {ad} ({bt/1024:.1f} KB, {yas_str})")
        if len(yedekler) > 5:
            print(f"    ... ve {len(yedekler)-5} tane daha")
    else:
        print("  Hicbir yedek dosyasi bulunamadi!")

    if not guncel_var:
        print("\n  UYARI: Son 24 saat icinde YEDEK YOK!")
        print("  Once yedek alin:")
        tarih_etiket = datetime.now().strftime('%Y%m%d_%H%M%S')
        print(f"\n    copy mock_data.db mock_data.db.backup_{tarih_etiket}")
        print()
        if not _onay_al('Yedek aldiniz mi, devam edelim mi? (evet/hayir): '):
            print("\n  Iptal. Once yedek alin.")
            sys.exit(0)
    else:
        print("\n  ✓ Son 24 saat icinde yedek mevcut")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    simdi = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # MEVCUT DURUM
    onceki_aktif = cur.execute(
        "SELECT COUNT(*) FROM ithalat_maliyet_kalem "
        "WHERE (Iptal IS NULL OR Iptal = 0)"
    ).fetchone()[0]
    onceki_iptal = cur.execute(
        "SELECT COUNT(*) FROM ithalat_maliyet_kalem WHERE Iptal = 1"
    ).fetchone()[0]
    parse_onceki = {}
    for r in cur.execute(
        "SELECT ParseDurum, COUNT(*) AS Adet FROM ithalat_belge_parse "
        "GROUP BY ParseDurum ORDER BY ParseDurum"
    ).fetchall():
        parse_onceki[r['ParseDurum']] = r['Adet']

    _ayrac("MEVCUT DURUM", '-')
    print(f"  Aktif kalem:  {onceki_aktif}")
    print(f"  Iptal kalem:  {onceki_iptal}")
    print(f"\n  Parse durum dagilimi:")
    for durum, adet in parse_onceki.items():
        isaret = ' (korunacak)' if durum in DOKUNULMAZ_PARSE_DURUM else ''
        print(f"    {durum:25}: {adet}{isaret}")

    # ADIM 1: MANTIKSIZ
    _ayrac("[1/3] MANTIKSIZ TUTAR TESPITI", '=')
    mantiksiz = _mantiksiz_tespit(cur)
    mantiksiz_idler = [r['Id'] for r in mantiksiz]

    if mantiksiz:
        print(f"\n  Bulunan: {len(mantiksiz)} mantiksiz kalem\n")
        print(f"  {'Id':>5}  {'Parti':>6}  {'Tip':10}  "
              f"{'Tutar':>18}  {'Para':4}  {'Ref':25}  Aciklama")
        print(f"  {'-'*5}  {'-'*6}  {'-'*10}  {'-'*18}  "
              f"{'-'*4}  {'-'*25}  {'-'*25}")
        for r in mantiksiz:
            ac = (r['Aciklama'] or '')[:25]
            ref = (r['KaynakBelgeRef'] or '-')[:25]
            print(f"  {r['Id']:>5}  {r['PartiId']:>6}  {r['Tip']:10}  "
                  f"{r['Tutar']:>18,.2f}  {r['ParaBirimi']:4}  "
                  f"{ref:25}  {ac}")
    else:
        print("\n  ✓ Mantiksiz tutar YOK")

    # ADIM 2: DUPLICATE
    _ayrac("[2/3] DUPLICATE AKTIF KALEM TESPITI", '=')
    duplicates = _duplicate_tespit(cur)
    duplicate_iptal_idler = []

    if duplicates:
        print(f"\n  Bulunan: {len(duplicates)} duplicate grup")
        print(f"  (Ayni PI icin aktif TEK kalem kuralini garanti eder)\n")
        for d in duplicates:
            idler = [int(x) for x in d['Idler'].split(',')]
            son_id = int(d['SonId'])
            iptal_bunlar = [x for x in idler if x != son_id]
            ref = (d['KaynakBelgeRef'] or '-')[:25]
            print(f"  Parti={d['PartiId']} Tip={d['Tip']:8} "
                  f"{d['Tutar']:>13,.2f} {d['ParaBirimi']:3}  "
                  f"Ref={ref}")
            print(f"    > Aktif kalacak: Id={son_id}")
            print(f"    > Iptal edilecek: {iptal_bunlar}  "
                  f"({len(iptal_bunlar)} adet)")
            duplicate_iptal_idler.extend(iptal_bunlar)
    else:
        print("\n  ✓ Duplicate aktif kalem YOK")

    # ADIM 3: UYGULANDI_BOS
    _ayrac("[3/3] 'UYGULANDI AMA KALEM YOK' TESPITI", '=')
    print("\n  META_GUNCELLENDI durumu ATLANACAK (dogrudur, kalem uretmez)")

    planlanan_iptal = set(mantiksiz_idler + duplicate_iptal_idler)
    uygulandi_bos = _uygulandi_bos_tespit(cur, planlanan_iptal)

    if uygulandi_bos:
        print(f"\n  Bulunan: {len(uygulandi_bos)} 'UYGULANDI ama bos' kayit\n")
        print(f"  {'ParseId':>7}  {'BelgeId':>7}  {'Parti':>6}  "
              f"{'Tip':18}  {'Onceki':18}  Ref")
        print(f"  {'-'*7}  {'-'*7}  {'-'*6}  {'-'*18}  {'-'*18}  {'-'*25}")
        for pk in uygulandi_bos:
            tip = (pk['BelgeTipi'] or '-')[:18]
            ref = (pk['KaynakBelgeRef'] or '-')[:25]
            print(f"  {pk['Id']:>7}  {pk['BelgeId']:>7}  "
                  f"{pk['PartiId']:>6}  {tip:18}  "
                  f"{pk['ParseDurum']:18}  {ref}")
    else:
        print("\n  ✓ 'UYGULANDI ama kalem yok' durumu YOK")

    # OZET + ONAY
    _ayrac("YAPILACAK ISLEMLER OZETI", '=')
    adim1 = len(mantiksiz_idler)
    adim2 = len(duplicate_iptal_idler)
    adim3 = len(uygulandi_bos)
    toplam_islem = adim1 + adim2 + adim3

    print(f"\n  [1/3] Mantiksiz kalem iptali:     {adim1} adet")
    print(f"  [2/3] Duplicate kalem iptali:     {adim2} adet")
    print(f"  [3/3] UYGULANDI_BOS isaretleme:   {adim3} adet")
    print(f"  {'-'*40}")
    print(f"  TOPLAM DEGISIKLIK:                {toplam_islem} adet")

    if toplam_islem == 0:
        print("\n  ✓ Temizlenecek kayit yok. DB zaten temiz.")
        conn.close()
        return

    _ayrac("ONAY", '=')
    print("\n  Yukaridaki islemler uygulansin mi?")
    print("  - Iptal edilen kalemler: Iptal=1 isaretlenir (fiziksel silme YOK)")
    print("  - Transaction kullanilir: Hata olursa HICBIR degisiklik yapilmaz")
    print("  - Yedegi zaten aldiniz")
    print()
    if not _onay_al('Devam (evet/hayir): '):
        print("\n  Iptal. Hicbir degisiklik yapilmadi. DB dokunulmadi.")
        conn.close()
        return

    # UYGULA - TRANSACTION
    _ayrac("UYGULANIYOR (transaction icinde)", '=')

    try:
        cur.execute("BEGIN")

        toplam_kalem_iptal = list(set(mantiksiz_idler + duplicate_iptal_idler))
        if toplam_kalem_iptal:
            placeholder = ','.join('?' for _ in toplam_kalem_iptal)
            cur.execute(f"""
                UPDATE ithalat_maliyet_kalem
                SET Iptal = 1,
                    IptalSebep = 'Otomatik temizlik V2: mantiksiz/duplicate',
                    IptalTarih = ?
                WHERE Id IN ({placeholder})
            """, [simdi] + toplam_kalem_iptal)
            print(f"  ✓ {cur.rowcount} kalem Iptal=1 oldu (Adim 1+2)")

        if uygulandi_bos:
            bos_idler = [pk['Id'] for pk in uygulandi_bos]
            placeholder = ','.join('?' for _ in bos_idler)
            yeni_mesaj = (
                '[TEMIZLIK V2] Onceden UYGULANDI ama aktif maliyet kalemi yok. '
                'Belgeyi tekrar yukleyerek oneri ekranindan kalemleri secebilirsiniz.'
            )[:1000]
            cur.execute(f"""
                UPDATE ithalat_belge_parse
                SET ParseDurum = 'UYGULANDI_BOS',
                    ParseMesaj = ?,
                    UygulananKalemSayisi = 0,
                    GuncellemeTarih = ?
                WHERE Id IN ({placeholder})
            """, [yeni_mesaj, simdi] + bos_idler)
            print(f"  ✓ {cur.rowcount} parse kaydi UYGULANDI_BOS oldu (Adim 3)")

        conn.commit()
        print(f"\n  ✓ Transaction COMMIT tamamlandi.")

    except Exception as e:
        conn.rollback()
        print(f"\n  HATA: {e}")
        print(f"  ROLLBACK yapildi. DB'ye hicbir degisiklik yansimadi.")
        conn.close()
        sys.exit(1)

    # SONRASI RAPOR
    _ayrac("SONRASI DURUM", '=')
    yeni_aktif = cur.execute(
        "SELECT COUNT(*) FROM ithalat_maliyet_kalem "
        "WHERE (Iptal IS NULL OR Iptal = 0)"
    ).fetchone()[0]
    yeni_iptal = cur.execute(
        "SELECT COUNT(*) FROM ithalat_maliyet_kalem WHERE Iptal = 1"
    ).fetchone()[0]
    parse_yeni = {}
    for r in cur.execute(
        "SELECT ParseDurum, COUNT(*) AS Adet FROM ithalat_belge_parse "
        "GROUP BY ParseDurum ORDER BY ParseDurum"
    ).fetchall():
        parse_yeni[r['ParseDurum']] = r['Adet']

    print(f"\n  KALEM TABLOSU:")
    print(f"    {'':18}  {'ONCE':>6}  {'SONRA':>6}  {'FARK':>7}")
    print(f"    Aktif kalem:    {onceki_aktif:>6}  {yeni_aktif:>6}  "
          f"{yeni_aktif - onceki_aktif:>+7}")
    print(f"    Iptal kalem:    {onceki_iptal:>6}  {yeni_iptal:>6}  "
          f"{yeni_iptal - onceki_iptal:>+7}")

    print(f"\n  PARSE DURUM DAGILIMI:")
    tum_durumlar = sorted(set(parse_onceki.keys()) | set(parse_yeni.keys()))
    for durum in tum_durumlar:
        onc = parse_onceki.get(durum, 0)
        yni = parse_yeni.get(durum, 0)
        fark = yni - onc
        isaret = f"{fark:>+5}" if fark != 0 else "    ="
        print(f"    {durum:25}: {onc:>4} -> {yni:>4}  ({isaret})")

    print(f"\n  PARTI BAZINDA AKTIF KALEM:")
    parti_rows = cur.execute("""
        SELECT PartiId, COUNT(*) AS Adet,
               SUM(CASE WHEN TutarPartiPara IS NOT NULL
                        THEN TutarPartiPara ELSE 0 END) AS Toplam
        FROM ithalat_maliyet_kalem
        WHERE (Iptal IS NULL OR Iptal = 0)
        GROUP BY PartiId
        ORDER BY PartiId
    """).fetchall()
    for r in parti_rows:
        tutar_str = (f"{r['Toplam']:>14,.2f}" if r['Toplam']
                     else '             -')
        print(f"    Parti #{r['PartiId']}: {r['Adet']:>3} aktif kalem, "
              f"toplam {tutar_str}")

    bos_sayi = parse_yeni.get('UYGULANDI_BOS', 0)
    if bos_sayi > 0:
        print(f"\n  UYGULANDI_BOS OLAN BELGELER ({bos_sayi} adet):")
        print(f"  Tekrar yuklemeniz gerekenler:\n")
        bos_list = cur.execute("""
            SELECT bp.BelgeId, bp.PartiId, bp.BelgeTipi, bp.KaynakBelgeRef
            FROM ithalat_belge_parse bp
            WHERE bp.ParseDurum = 'UYGULANDI_BOS'
            ORDER BY bp.PartiId, bp.BelgeId
        """).fetchall()
        for r in bos_list:
            tip = (r['BelgeTipi'] or '-')[:20]
            ref = (r['KaynakBelgeRef'] or '-')[:30]
            print(f"    Parti #{r['PartiId']:>3} BelgeId={r['BelgeId']:>4}  "
                  f"{tip:20}  Ref={ref}")

    conn.close()

    _ayrac("TEMIZLIK TAMAMLANDI", '=')
    print("\n  Flask'i yeniden baslatmaya GEREK YOK")
    print("  Tarayicida Ctrl+F5 yapin.\n")
    print("  SONRAKI ADIM:")
    print("  - UYGULANDI_BOS olan belgeleri SIL veya TEKRAR YUKLEYEREK")
    print("    yeni oneri akisindan kalemleri secebilirsiniz.")
    print("  - Maliyet sekmesindeki toplam tutarlari kontrol edin.\n")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Kullanici iptal etti (Ctrl+C).")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n  BEKLENMEDIK HATA: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
