# -*- coding: utf-8 -*-
"""
CPS DEV - Beyanname Oncesi Temizleme Scripti
===============================================

Bu script beyanname oneri akisina gecmeden ONCE calistirilir.

3 IS YAPAR:

1) MANTIKSIZ TUTARLI KALEMLERI IPTAL ET
   - TRY > 10,000,000 olan aktif kalemler -> Iptal=1
   - USD/EUR/GBP > 1,000,000 olan aktif kalemler -> Iptal=1
   - CNY > 10,000,000 olan aktif kalemler -> Iptal=1
   Ornek: 2.277.000.000 TRY gibi yanlis parse edilen kalemler.

2) "UYGULANDI AMA KALEM YAZILMAYAN" BELGELERI DUZELT
   ithalat_belge_parse tablosunda ParseDurum='UYGULANDI' ama
   o BelgeId'ye bagli aktif maliyet kalemi bulunmayan kayitlari
   'UYGULANDI_BOS' durumuna al ve net mesaj yaz.
   (Bu durumda UI bu kaydi hata veya yeni yuklenmesi gereken
   olarak gosterecek.)

3) OZET RAPOR
   - Kac kalem iptal edildi
   - Kac parse kaydi 'UYGULANDI_BOS' oldu
   - Parti bazinda yeni aktif kalem sayilari

ONCE YEDEK AL:
  copy mock_data.db mock_data.db.backup_<tarih>

CALISTIR:
  cd C:\\cps_dev
  python cleanup_beyanname_oncesi.py
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
    print("=" * 75)
    print(" BEYANNAME ONCESI TEMIZLEME - Mantiksiz Tutar + UYGULANDI_BOS Duzeltme")
    print("=" * 75)

    onay = input(
        "\nDIKKAT: Bu script ithalat_maliyet_kalem ve ithalat_belge_parse "
        "tablolarini degistirecek.\n"
        "mock_data.db yedeklendi mi? (evet/hayir): "
    ).strip().lower()
    if onay not in ('evet', 'e', 'yes', 'y'):
        print("Islem iptal edildi. Once yedek alin:")
        print(f"  copy {DB_PATH} {DB_PATH}.backup_<tarih>")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    simdi = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # =========================================================
    # ADIM 1: MANTIKSIZ TUTAR TESPIT
    # =========================================================
    print("\n" + "=" * 75)
    print("[1/3] Mantiksiz tutarli aktif kalemler araniyor...")
    print("=" * 75)

    # 10M TRY/CNY ustu, 1M USD/EUR/GBP ustu
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

    iptal_idler = []
    if not mantiksiz:
        print("  Mantiksiz tutarli kalem bulunamadi.")
    else:
        print(f"  {len(mantiksiz)} mantiksiz kalem bulundu:")
        for r in mantiksiz:
            ac = (r['Aciklama'] or '')[:40]
            print(f"    Id={r['Id']} Parti={r['PartiId']} Tip={r['Tip']} "
                  f"Tutar={r['Tutar']:,.2f} {r['ParaBirimi']} "
                  f"Ref={r['KaynakBelgeRef']} BelgeId={r['KaynakBelgeId']} "
                  f"| {ac}")
            iptal_idler.append(r['Id'])

    # =========================================================
    # ADIM 2: "UYGULANDI AMA KALEM YOK" DURUMU TESPIT
    # =========================================================
    print("\n" + "=" * 75)
    print("[2/3] 'UYGULANDI ama kalem yok' parse kayitlari araniyor...")
    print("=" * 75)

    # belge_parse'de UYGULANDI olan ama maliyet kalem tablosunda
    # o BelgeId icin aktif kalemi olmayan kayitlar
    # NOT: Simdi iptal edecegimiz kalemler de dikkate alinir
    # (cunku iptal sonrasi o belge 'boş' olacak)
    iptal_idler_set = set(iptal_idler)
    uygulandi_bos = []

    parse_kayitlari = cur.execute("""
        SELECT Id, BelgeId, PartiId, BelgeTipi,
               ParseDurum, ParseMesaj, KaynakBelgeRef, UygulananKalemSayisi
        FROM ithalat_belge_parse
        WHERE ParseDurum IN ('UYGULANDI', 'OK', 'YENIDEN_ISLENDI')
        ORDER BY PartiId, BelgeId
    """).fetchall()

    for pk in parse_kayitlari:
        belge_id = pk['BelgeId']
        if not belge_id:
            continue
        # Bu BelgeId icin aktif (iptal edilmeyen + iptal planlanmayan) kalem var mi?
        aktif_kalem = cur.execute("""
            SELECT COUNT(*) AS Adet
            FROM ithalat_maliyet_kalem
            WHERE KaynakBelgeId = ?
              AND (Iptal IS NULL OR Iptal = 0)
        """, (belge_id,)).fetchone()

        aktif_adet = aktif_kalem['Adet'] if aktif_kalem else 0

        # Iptal planlanan kalemler de cikarilsin
        if iptal_idler_set:
            planlanan = cur.execute("""
                SELECT COUNT(*) AS Adet
                FROM ithalat_maliyet_kalem
                WHERE KaynakBelgeId = ?
                  AND Id IN ({})
            """.format(','.join('?' for _ in iptal_idler_set)),
            [belge_id] + list(iptal_idler_set)).fetchone()
            aktif_adet -= (planlanan['Adet'] if planlanan else 0)

        if aktif_adet <= 0:
            uygulandi_bos.append(pk)

    if not uygulandi_bos:
        print("  'UYGULANDI ama kalem yok' durum bulunamadi.")
    else:
        print(f"  {len(uygulandi_bos)} parse kaydi 'UYGULANDI ama bos':")
        for pk in uygulandi_bos:
            print(f"    BelgeId={pk['BelgeId']} Parti={pk['PartiId']} "
                  f"Tip={pk['BelgeTipi']} Durum={pk['ParseDurum']} "
                  f"Ref={pk['KaynakBelgeRef']} "
                  f"UygulananSayi={pk['UygulananKalemSayisi']}")

    # =========================================================
    # ADIM 3: ONAY + UYGULA
    # =========================================================
    toplam = len(iptal_idler) + len(uygulandi_bos)
    if toplam == 0:
        print("\n" + "=" * 75)
        print("[3/3] Duzeltilecek bir sey yok - temizlik bitti.")
        print("=" * 75)
        conn.close()
        return

    print("\n" + "=" * 75)
    print(f"[3/3] YAPILACAK ISLEMLER:")
    print("=" * 75)
    print(f"  - {len(iptal_idler)} mantiksiz kalemi Iptal=1 yap")
    print(f"  - {len(uygulandi_bos)} parse kaydi 'UYGULANDI_BOS' durumuna cevir")

    onay2 = input("\nDevam edilsin mi? (evet/hayir): ").strip().lower()
    if onay2 not in ('evet', 'e', 'yes', 'y'):
        print("Iptal edildi. Hicbir degisiklik yapilmadi.")
        conn.close()
        return

    # ---- Mantiksiz kalemleri iptal et ----
    if iptal_idler:
        placeholder = ','.join('?' for _ in iptal_idler)
        cur.execute(f"""
            UPDATE ithalat_maliyet_kalem
            SET Iptal = 1,
                IptalSebep = 'Otomatik: Mantiksiz tutar (10M TRY / 1M USD ustu)',
                IptalTarih = ?
            WHERE Id IN ({placeholder})
        """, [simdi] + iptal_idler)
        print(f"\n  ✓ {cur.rowcount} mantiksiz kalem Iptal=1 yapildi")

    # ---- UYGULANDI_BOS durumuna al ----
    if uygulandi_bos:
        for pk in uygulandi_bos:
            onceki_durum = pk['ParseDurum']
            onceki_mesaj = pk['ParseMesaj'] or ''
            yeni_mesaj = (
                f"[OTOMATIK DUZELTME] Onceden '{onceki_durum}' olarak isaretlenmis "
                f"ama aktif maliyet kalemi bulunmuyor. "
                f"Sebep: Mantiksiz tutar iptali veya eksik parse. "
                f"Belgeyi tekrar yukleyerek maliyet onerileri ekranindan "
                f"dogru kalemleri secebilirsiniz."
            )
            yeni_mesaj = yeni_mesaj[:1000]
            cur.execute("""
                UPDATE ithalat_belge_parse
                SET ParseDurum = 'UYGULANDI_BOS',
                    ParseMesaj = ?,
                    UygulananKalemSayisi = 0,
                    GuncellemeTarih = ?
                WHERE Id = ?
            """, (yeni_mesaj, simdi, pk['Id']))
        print(f"  ✓ {len(uygulandi_bos)} parse kaydi UYGULANDI_BOS oldu")

    conn.commit()

    # =========================================================
    # OZET
    # =========================================================
    print("\n" + "=" * 75)
    print(" OZET")
    print("=" * 75)

    aktif_toplam = cur.execute("""
        SELECT COUNT(*) FROM ithalat_maliyet_kalem
        WHERE (Iptal IS NULL OR Iptal = 0)
    """).fetchone()[0]
    iptal_toplam = cur.execute("""
        SELECT COUNT(*) FROM ithalat_maliyet_kalem WHERE Iptal = 1
    """).fetchone()[0]
    print(f"Toplam aktif kalem:  {aktif_toplam}")
    print(f"Toplam iptal kalem:  {iptal_toplam}")

    bos_sayi = cur.execute("""
        SELECT COUNT(*) FROM ithalat_belge_parse
        WHERE ParseDurum = 'UYGULANDI_BOS'
    """).fetchone()[0]
    print(f"UYGULANDI_BOS parse: {bos_sayi}")

    print("\nParti bazinda aktif kalem:")
    rows = cur.execute("""
        SELECT PartiId, COUNT(*) AS Adet, SUM(TutarPartiPara) AS Tutar
        FROM ithalat_maliyet_kalem
        WHERE (Iptal IS NULL OR Iptal = 0)
          AND TutarPartiPara IS NOT NULL
        GROUP BY PartiId
        ORDER BY PartiId
    """).fetchall()
    for r in rows:
        tutar_str = f"{r['Tutar']:,.2f}" if r['Tutar'] else '—'
        print(f"  PartiId={r['PartiId']}: {r['Adet']} aktif kalem, "
              f"toplam {tutar_str}")

    # UYGULANDI_BOS olan belgelerin listesi
    if bos_sayi > 0:
        print("\nUYGULANDI_BOS olan belgeler (tekrar yuklenmesi gerekenler):")
        bos_list = cur.execute("""
            SELECT bp.BelgeId, bp.PartiId, bp.BelgeTipi, bp.KaynakBelgeRef,
                   b.OrijinalAd
            FROM ithalat_belge_parse bp
            LEFT JOIN belge b ON bp.BelgeId = b.Id
            WHERE bp.ParseDurum = 'UYGULANDI_BOS'
            ORDER BY bp.PartiId, bp.BelgeId
        """).fetchall()
        for r in bos_list:
            ad = (r['OrijinalAd'] or '(bilinmiyor)')[:45]
            print(f"  Parti={r['PartiId']} BelgeId={r['BelgeId']} "
                  f"Tip={r['BelgeTipi']} Ref={r['KaynakBelgeRef']} | {ad}")

    conn.close()
    print("\n" + "=" * 75)
    print(" TEMIZLEME TAMAMLANDI")
    print("=" * 75)
    print("Flask'i yeniden baslatmaniza gerek yok.")
    print("\nSONRAKI ADIM:")
    print("  1. UYGULANDI_BOS olan beyannameleri SILIN (Belgeler sekmesi) veya")
    print("     YENIDEN YUKLEYIN - yeni oneri akisi acilacak.")
    print("  2. Beyanname oneri akisi yeni kodla calistiginda dogru kalemleri")
    print("     secerek uygulayabileceksiniz.")


if __name__ == '__main__':
    main()
