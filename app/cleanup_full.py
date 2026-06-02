# -*- coding: utf-8 -*-
"""
CPS DEV - Veritabani Temizleme Scripti (Birlesik)
===================================================

3 ASAMALI TEMIZLIK:

1) MANTIKSIZ TUTARLARI IPTAL ET
   - TRY > 10,000,000 olan aktif kalemler -> Iptal=1
   - USD/EUR/GBP > 1,000,000 olan aktif kalemler -> Iptal=1
   - CNY > 10,000,000 olan aktif kalemler -> Iptal=1

2) DUPLICATE AKTIF KALEMLERI IPTAL ET
   Ayni (PartiId + KaynakBelgeRef + Tip + Tutar + ParaBirimi + Kaynak)
   olan aktif kalemlerden sadece en yenisini (MAX Id) aktif birak,
   digerlerini Iptal=1 yap.

3) UYGULANDI AMA KALEM YOK KAYITLARINI UYGULANDI_BOS YAP
   ithalat_belge_parse'de ParseDurum='UYGULANDI' ama KayBelgeId'ye
   bagli aktif kalem bulunmayan kayitlari UYGULANDI_BOS durumuna al.
   (Adim 1 ve 2'den sonra bu durum artacak - cunku iptal ettigimiz
   kalemlere bagli belge_parse kayitlari 'bos' kalabilir.)

ONCE YEDEK AL:
  copy mock_data.db mock_data.db.backup_<tarih>

CALISTIR:
  cd C:\\cps_dev
  python cleanup_full.py
"""
import os
import sqlite3
import sys
from datetime import datetime

DB_PATH = os.path.join(os.getcwd(), 'mock_data.db')
if not os.path.isfile(DB_PATH):
    print(f"HATA: {DB_PATH} bulunamadi!")
    print("Bu scripti C:\\cps_dev\\ klasoru icinde calistirin.")
    sys.exit(1)


def main():
    print("=" * 78)
    print(" VERITABANI TEMIZLEME - 3 ASAMALI (Mantiksiz + Duplicate + UYGULANDI_BOS)")
    print("=" * 78)

    onay = input(
        "\nDIKKAT: Bu script ithalat_maliyet_kalem ve ithalat_belge_parse "
        "tablolarini\ndegistirecek. mock_data.db yedeklendi mi? (evet/hayir): "
    ).strip().lower()
    if onay not in ('evet', 'e', 'yes', 'y'):
        print("Iptal. Once yedek alin:")
        print(f"  copy mock_data.db mock_data.db.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    simdi = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # =========================================================
    # ONCEKI DURUM
    # =========================================================
    onceki_aktif = cur.execute(
        "SELECT COUNT(*) FROM ithalat_maliyet_kalem WHERE (Iptal IS NULL OR Iptal = 0)"
    ).fetchone()[0]
    onceki_iptal = cur.execute(
        "SELECT COUNT(*) FROM ithalat_maliyet_kalem WHERE Iptal = 1"
    ).fetchone()[0]
    onceki_uygulandi = cur.execute(
        "SELECT COUNT(*) FROM ithalat_belge_parse WHERE ParseDurum = 'UYGULANDI'"
    ).fetchone()[0]
    onceki_uygulandi_bos = cur.execute(
        "SELECT COUNT(*) FROM ithalat_belge_parse WHERE ParseDurum = 'UYGULANDI_BOS'"
    ).fetchone()[0]

    print(f"\n[BASLANGIC] Aktif kalem: {onceki_aktif} | Iptal: {onceki_iptal} | "
          f"UYGULANDI parse: {onceki_uygulandi} | UYGULANDI_BOS: {onceki_uygulandi_bos}")

    # =========================================================
    # ADIM 1: MANTIKSIZ TUTARLAR
    # =========================================================
    print("\n" + "=" * 78)
    print(" [1/3] Mantiksiz tutarli aktif kalemler araniyor...")
    print("=" * 78)

    mantiksiz = cur.execute("""
        SELECT Id, PartiId, Tip, Tutar, ParaBirimi,
               KaynakBelgeId, KaynakBelgeRef, Aciklama
        FROM ithalat_maliyet_kalem
        WHERE (Iptal IS NULL OR Iptal = 0)
          AND (
              (ParaBirimi = 'TRY' AND Tutar > 10000000)
              OR (ParaBirimi = 'CNY' AND Tutar > 10000000)
              OR (ParaBirimi IN ('USD', 'EUR', 'GBP') AND Tutar > 1000000)
          )
        ORDER BY PartiId, Id
    """).fetchall()

    mantiksiz_idler = []
    mantiksiz_rapor = []
    if not mantiksiz:
        print("  (Mantiksiz tutarli kalem yok)")
    else:
        for r in mantiksiz:
            ac = (r['Aciklama'] or '')[:40]
            print(f"  ISARET: Id={r['Id']} Parti={r['PartiId']} Tip={r['Tip']} "
                  f"Tutar={r['Tutar']:,.2f} {r['ParaBirimi']} | {ac}")
            mantiksiz_idler.append(r['Id'])
            mantiksiz_rapor.append(dict(r))
    print(f"\n  Toplam: {len(mantiksiz_idler)} mantiksiz kalem")

    # =========================================================
    # ADIM 2: DUPLICATE AKTIF KALEM
    # =========================================================
    print("\n" + "=" * 78)
    print(" [2/3] Duplicate aktif kalemler araniyor...")
    print("=" * 78)

    duplicates = cur.execute("""
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

    duplicate_iptal_idler = []
    duplicate_rapor = []
    if not duplicates:
        print("  (Duplicate aktif kalem yok)")
    else:
        for d in duplicates:
            idler = [int(x) for x in d['Idler'].split(',')]
            son_id = int(d['SonId'])
            iptal_bunlar = [x for x in idler if x != son_id]
            print(f"  GRUP: Parti={d['PartiId']} Ref={d['KaynakBelgeRef']} "
                  f"Tip={d['Tip']} {d['Tutar']:,.2f} {d['ParaBirimi']} "
                  f"x{d['Adet']} | Iptal={iptal_bunlar} Aktif kalacak=Id{son_id}")
            duplicate_iptal_idler.extend(iptal_bunlar)
            duplicate_rapor.append({
                'parti_id': d['PartiId'],
                'kaynak_ref': d['KaynakBelgeRef'],
                'tip': d['Tip'],
                'tutar': d['Tutar'],
                'adet': d['Adet'],
                'son_id': son_id,
                'iptal_edilen': iptal_bunlar,
            })
    print(f"\n  Toplam: {len(duplicate_iptal_idler)} duplicate kalem iptal edilecek")

    # ---- 1. ve 2. ADIM: IPTAL UYGULA ----
    toplam_kalem_iptal = set(mantiksiz_idler + duplicate_iptal_idler)

    if toplam_kalem_iptal:
        print(f"\n  Toplam {len(toplam_kalem_iptal)} kalem Iptal=1 olacak...")
        placeholder = ','.join('?' for _ in toplam_kalem_iptal)
        cur.execute(f"""
            UPDATE ithalat_maliyet_kalem
            SET Iptal = 1,
                IptalSebep = 'Otomatik temizleme: mantiksiz tutar veya duplicate',
                IptalTarih = ?
            WHERE Id IN ({placeholder})
        """, [simdi] + list(toplam_kalem_iptal))
        adet1 = cur.rowcount
        conn.commit()
        print(f"  ✓ {adet1} kalem Iptal=1 oldu")
    else:
        print("\n  Iptal edilecek kalem yok.")

    # =========================================================
    # ADIM 3: UYGULANDI AMA KALEM YOK -> UYGULANDI_BOS
    # =========================================================
    # NOT: Bu adim 1. ve 2. adimin commit'inden SONRA calismali
    # cunku oradaki iptal sonrasi 'bos' kalan belgeler ortaya cikar
    print("\n" + "=" * 78)
    print(" [3/3] 'UYGULANDI ama aktif kalem yok' kayitlari araniyor...")
    print("=" * 78)

    parse_kayitlari = cur.execute("""
        SELECT Id, BelgeId, PartiId, BelgeTipi,
               ParseDurum, ParseMesaj, KaynakBelgeRef, UygulananKalemSayisi
        FROM ithalat_belge_parse
        WHERE ParseDurum IN ('UYGULANDI', 'OK', 'YENIDEN_ISLENDI')
        ORDER BY PartiId, BelgeId
    """).fetchall()

    uygulandi_bos = []
    for pk in parse_kayitlari:
        belge_id = pk['BelgeId']
        if not belge_id:
            continue
        aktif = cur.execute("""
            SELECT COUNT(*) AS Adet
            FROM ithalat_maliyet_kalem
            WHERE KaynakBelgeId = ?
              AND (Iptal IS NULL OR Iptal = 0)
        """, (belge_id,)).fetchone()
        aktif_adet = aktif['Adet'] if aktif else 0
        if aktif_adet == 0:
            uygulandi_bos.append(dict(pk))

    if not uygulandi_bos:
        print("  (Her UYGULANDI kaydi icin aktif kalem var)")
    else:
        print(f"  {len(uygulandi_bos)} parse kaydi 'UYGULANDI ama bos':")
        for pk in uygulandi_bos:
            print(f"    Id={pk['Id']} BelgeId={pk['BelgeId']} Parti={pk['PartiId']} "
                  f"Tip={pk['BelgeTipi']} Onceki={pk['ParseDurum']} "
                  f"Ref={pk['KaynakBelgeRef']}")

    if uygulandi_bos:
        print(f"\n  {len(uygulandi_bos)} parse kaydi UYGULANDI_BOS durumuna alinacak...")
        bos_idler = [pk['Id'] for pk in uygulandi_bos]
        placeholder = ','.join('?' for _ in bos_idler)
        yeni_mesaj = (
            '[OTOMATIK DUZELTME] Onceden UYGULANDI ama aktif maliyet kalemi yok. '
            'Belgeyi tekrar yukleyerek oneri ekranindan dogru kalemleri secebilirsiniz.'
        )[:1000]
        cur.execute(f"""
            UPDATE ithalat_belge_parse
            SET ParseDurum = 'UYGULANDI_BOS',
                ParseMesaj = ?,
                UygulananKalemSayisi = 0,
                GuncellemeTarih = ?
            WHERE Id IN ({placeholder})
        """, [yeni_mesaj, simdi] + bos_idler)
        adet2 = cur.rowcount
        conn.commit()
        print(f"  ✓ {adet2} parse kaydi UYGULANDI_BOS oldu")

    # =========================================================
    # RAPOR
    # =========================================================
    print("\n" + "=" * 78)
    print(" TEMIZLIK RAPORU")
    print("=" * 78)

    yeni_aktif = cur.execute(
        "SELECT COUNT(*) FROM ithalat_maliyet_kalem WHERE (Iptal IS NULL OR Iptal = 0)"
    ).fetchone()[0]
    yeni_iptal = cur.execute(
        "SELECT COUNT(*) FROM ithalat_maliyet_kalem WHERE Iptal = 1"
    ).fetchone()[0]
    yeni_uygulandi = cur.execute(
        "SELECT COUNT(*) FROM ithalat_belge_parse WHERE ParseDurum = 'UYGULANDI'"
    ).fetchone()[0]
    yeni_uygulandi_bos = cur.execute(
        "SELECT COUNT(*) FROM ithalat_belge_parse WHERE ParseDurum = 'UYGULANDI_BOS'"
    ).fetchone()[0]

    print(f"\nKALEM TABLOSU:")
    print(f"  Aktif kalem:    {onceki_aktif:>5}  ->  {yeni_aktif:>5}  "
          f"(fark: {yeni_aktif - onceki_aktif:+d})")
    print(f"  Iptal kalem:    {onceki_iptal:>5}  ->  {yeni_iptal:>5}  "
          f"(fark: {yeni_iptal - onceki_iptal:+d})")

    print(f"\nPARSE TABLOSU:")
    print(f"  UYGULANDI:      {onceki_uygulandi:>5}  ->  {yeni_uygulandi:>5}  "
          f"(fark: {yeni_uygulandi - onceki_uygulandi:+d})")
    print(f"  UYGULANDI_BOS:  {onceki_uygulandi_bos:>5}  ->  {yeni_uygulandi_bos:>5}  "
          f"(fark: {yeni_uygulandi_bos - onceki_uygulandi_bos:+d})")

    # Parti bazinda
    print("\nPARTI BAZINDA AKTIF KALEM:")
    parti_rows = cur.execute("""
        SELECT PartiId, COUNT(*) AS Adet, SUM(TutarPartiPara) AS Toplam
        FROM ithalat_maliyet_kalem
        WHERE (Iptal IS NULL OR Iptal = 0)
        GROUP BY PartiId
        ORDER BY PartiId
    """).fetchall()
    for r in parti_rows:
        tutar_str = f"{r['Toplam']:>12,.2f}" if r['Toplam'] else '(TutarPartiPara yok)'
        print(f"  Parti #{r['PartiId']}: {r['Adet']:>3} kalem · {tutar_str}")

    # UYGULANDI_BOS olan belgeler
    if yeni_uygulandi_bos > 0:
        print("\nUYGULANDI_BOS OLAN BELGELER (tekrar yuklemen gerekenler):")
        bos_list = cur.execute("""
            SELECT bp.BelgeId, bp.PartiId, bp.BelgeTipi, bp.KaynakBelgeRef,
                   bp.ParseMesaj, b.OrijinalAd
            FROM ithalat_belge_parse bp
            LEFT JOIN belge b ON bp.BelgeId = b.Id
            WHERE bp.ParseDurum = 'UYGULANDI_BOS'
            ORDER BY bp.PartiId, bp.BelgeId
        """).fetchall()
        for r in bos_list:
            ad = (r['OrijinalAd'] or '(bilinmiyor)')[:55]
            print(f"  Parti #{r['PartiId']} BelgeId={r['BelgeId']} "
                  f"Tip={r['BelgeTipi']:15} Ref={r['KaynakBelgeRef'] or '-':30} "
                  f"| {ad}")

    conn.close()
    print("\n" + "=" * 78)
    print(" TEMIZLIK TAMAMLANDI. Flask'i yeniden baslatmaya gerek yok.")
    print("=" * 78)
    print("\nSONRAKI ADIM:")
    print("  - Tarayicida Ctrl+F5 yap")
    print("  - Parti detayindaki Belgeler sekmesinde 'UYGULANDI ama BOS' rozeti")
    print("    gorenleri SIL veya TEKRAR YUKLEYEREK oneri ekranindan kalemleri sec")


if __name__ == '__main__':
    main()
