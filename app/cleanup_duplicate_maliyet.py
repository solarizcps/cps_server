# -*- coding: utf-8 -*-
"""
CPS DEV - Duplicate Maliyet Kalem Temizleme Scripti
=====================================================

Amac:
  Ayni (PartiId + KaynakBelgeRef + Tip + Tutar + ParaBirimi + Kaynak)
  olan aktif kalemlerden sadece en yenisini aktif birakir,
  digerlerini Iptal=1 yapar.

Ayrica:
  10M TRY ustu veya 1M USD ustu mantıksız tutarlari da iptal eder.

Calistirma:
  cd C:\\cps_dev
  python cleanup_duplicate_maliyet.py

DIKKAT:
  Bu script calistirilmadan once MUTLAKA mock_data.db yedeklenmelidir:
    copy mock_data.db mock_data.db.backup_<tarih>
"""
import sys
import os
import sqlite3
from datetime import datetime

# Calisma dizinine bak
DB_PATH = os.path.join(os.getcwd(), 'mock_data.db')
if not os.path.isfile(DB_PATH):
    print(f"HATA: {DB_PATH} bulunamadi!")
    print("Bu scripti C:\\cps_dev\\ klasoru icinde calistirin.")
    sys.exit(1)


def main():
    print("=" * 70)
    print("DUPLICATE MALIYET KALEM TEMIZLEME")
    print("=" * 70)

    # Yedek uyarisi
    onay = input(
        "\nDIKKAT: Bu script maliyet kalemlerini degistirecek.\n"
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

    # ========================================================
    # ADIM 1: Duplicate TESPIT
    # ========================================================
    print("\n[1/3] Duplicate kalemler tespit ediliyor...")
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
        ORDER BY PartiId, KaynakBelgeRef, Tip
    """).fetchall()

    if not duplicates:
        print("  Duplicate kalem bulunamadi.")
    else:
        print(f"  {len(duplicates)} duplicate grup bulundu:")
        for d in duplicates:
            print(
                f"    Parti={d['PartiId']} Ref={d['KaynakBelgeRef']} "
                f"Tip={d['Tip']} Tutar={d['Tutar']} {d['ParaBirimi']} "
                f"Kaynak={d['Kaynak']} x{d['Adet']} (Idler: {d['Idler']})"
            )

    # Iptal edilecek kalem Idlerini topla (SonId HARIC hepsi)
    iptal_edilecek_duplicate = []
    for d in duplicates:
        idler = [int(x) for x in d['Idler'].split(',')]
        son_id = int(d['SonId'])
        for kid in idler:
            if kid != son_id:
                iptal_edilecek_duplicate.append(kid)

    print(f"\n  Duplicate nedeniyle iptal edilecek kalem sayisi: "
          f"{len(iptal_edilecek_duplicate)}")

    # ========================================================
    # ADIM 2: MANTIKSIZ TUTAR TESPITI
    # ========================================================
    print("\n[2/3] Mantıksız tutarli kalemler tespit ediliyor...")
    # 10M TRY ustu
    try_ust = cur.execute("""
        SELECT Id, PartiId, Tip, Tutar, KaynakBelgeRef
        FROM ithalat_maliyet_kalem
        WHERE (Iptal IS NULL OR Iptal = 0)
          AND ParaBirimi = 'TRY'
          AND Tutar > 10000000
    """).fetchall()
    # 1M USD/EUR/GBP ustu
    usd_ust = cur.execute("""
        SELECT Id, PartiId, Tip, Tutar, ParaBirimi, KaynakBelgeRef
        FROM ithalat_maliyet_kalem
        WHERE (Iptal IS NULL OR Iptal = 0)
          AND ParaBirimi IN ('USD', 'EUR', 'GBP')
          AND Tutar > 1000000
    """).fetchall()
    # 10M CNY ustu
    cny_ust = cur.execute("""
        SELECT Id, PartiId, Tip, Tutar, KaynakBelgeRef
        FROM ithalat_maliyet_kalem
        WHERE (Iptal IS NULL OR Iptal = 0)
          AND ParaBirimi = 'CNY'
          AND Tutar > 10000000
    """).fetchall()

    mantıksız_idler = []
    if try_ust:
        print(f"  10M TRY ustu: {len(try_ust)} kalem")
        for r in try_ust:
            print(f"    Id={r['Id']} Parti={r['PartiId']} Tip={r['Tip']} "
                  f"Tutar={r['Tutar']:,.2f} TRY Ref={r['KaynakBelgeRef']}")
            mantıksız_idler.append(r['Id'])
    if usd_ust:
        print(f"  1M USD/EUR/GBP ustu: {len(usd_ust)} kalem")
        for r in usd_ust:
            print(f"    Id={r['Id']} Parti={r['PartiId']} Tip={r['Tip']} "
                  f"Tutar={r['Tutar']:,.2f} {r['ParaBirimi']} Ref={r['KaynakBelgeRef']}")
            mantıksız_idler.append(r['Id'])
    if cny_ust:
        print(f"  10M CNY ustu: {len(cny_ust)} kalem")
        for r in cny_ust:
            print(f"    Id={r['Id']} Parti={r['PartiId']} Tip={r['Tip']} "
                  f"Tutar={r['Tutar']:,.2f} CNY Ref={r['KaynakBelgeRef']}")
            mantıksız_idler.append(r['Id'])

    if not mantıksız_idler:
        print("  Mantıksız tutar yok.")

    # ========================================================
    # ADIM 3: ONAY ve UYGULA
    # ========================================================
    toplam_iptal = len(iptal_edilecek_duplicate) + len(mantıksız_idler)
    if toplam_iptal == 0:
        print("\n[3/3] Temizlenecek kalem yok.")
        conn.close()
        return

    print(f"\n[3/3] Toplam {toplam_iptal} kalem Iptal=1 yapilacak:")
    print(f"  - Duplicate: {len(iptal_edilecek_duplicate)}")
    print(f"  - Mantıksız tutar: {len(mantıksız_idler)}")

    onay2 = input("\nDevam edilsin mi? (evet/hayir): ").strip().lower()
    if onay2 not in ('evet', 'e', 'yes', 'y'):
        print("Iptal edildi. Hicbir degisiklik yapilmadi.")
        conn.close()
        return

    # Iptal et
    tum_idler = list(set(iptal_edilecek_duplicate + mantıksız_idler))
    placeholder = ','.join('?' for _ in tum_idler)
    cur.execute(f"""
        UPDATE ithalat_maliyet_kalem
        SET Iptal = 1,
            IptalSebep = 'Otomatik temizleme: duplicate veya mantıksız tutar',
            IptalTarih = ?
        WHERE Id IN ({placeholder})
    """, [simdi] + tum_idler)

    conn.commit()
    print(f"\n✓ {cur.rowcount} kalem Iptal=1 yapildi.")

    # Son ozet
    print("\n" + "=" * 70)
    print("OZET")
    print("=" * 70)
    aktif = cur.execute("""
        SELECT COUNT(*) FROM ithalat_maliyet_kalem
        WHERE (Iptal IS NULL OR Iptal = 0)
    """).fetchone()[0]
    iptal = cur.execute("""
        SELECT COUNT(*) FROM ithalat_maliyet_kalem WHERE Iptal = 1
    """).fetchone()[0]
    print(f"Aktif kalem:  {aktif}")
    print(f"Iptal kalem:  {iptal}")

    # Parti bazli kalem sayisi
    print("\nParti bazinda aktif kalem:")
    rows = cur.execute("""
        SELECT PartiId, COUNT(*) AS Adet
        FROM ithalat_maliyet_kalem
        WHERE (Iptal IS NULL OR Iptal = 0)
        GROUP BY PartiId
        ORDER BY PartiId
    """).fetchall()
    for r in rows:
        print(f"  PartiId={r['PartiId']}: {r['Adet']} aktif kalem")

    conn.close()
    print("\nTemizleme tamamlandi. Flask'i yeniden baslatmaniza gerek yok.")


if __name__ == '__main__':
    main()
