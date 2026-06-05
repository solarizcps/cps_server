#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CPS Performans Seed Script (Parça 6 / UAT Senaryo 11)

Mevcut mock veriyi çoğaltır — liste/detay sayfalarının yoğun veri altında
performansını test etmek için. Tüm eklenen veriler [PERF-SEED] marker'ı
ile işaretlenir, böylece clean komutu sadece bu veriyi siler.

KULLANIM:
    python seed_performans.py medium     # default - 50 sipariş
    python seed_performans.py small      # 20 sipariş
    python seed_performans.py large      # 150 sipariş
    python seed_performans.py clean      # [PERF-SEED] kayıtlarını sil
    python seed_performans.py status     # mevcut PERF-SEED sayısını göster

ÖNEMLİ:
- Prod ortamda çalışmaz (.production dosyası varsa exit)
- Core veri (CIN-0001..0005, SVK-0001..0005, M001-M005, M099) dokunulmaz
- clean komutu sadece marker'lı kayıtları siler
"""
import os
import sys
import random
import time
from datetime import date, datetime, timedelta

# Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

R, G, Y, B, N = '\033[91m', '\033[92m', '\033[93m', '\033[96m', '\033[0m'


def _prod_kontrol():
    """Prod ortamda çalışmayı engelle."""
    if os.path.exists('.production') or os.environ.get('CPS_ENV') == 'production':
        print(f"{R}⛔ HATA: Bu script PROD ortamda çalışmaz!{N}")
        print("  .production dosyası veya CPS_ENV=production tespit edildi.")
        print("  Performans seed sadece geliştirme ortamında kullanılmalı.")
        sys.exit(1)


def _baglan():
    """DB bağlantısı."""
    import sqlite3
    db_path = 'mock_data.db'
    if not os.path.exists(db_path):
        print(f"{R}⛔ mock_data.db bulunamadı. Önce 'python init_mock_db.py' çalıştırın.{N}")
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _olcek_ayari(mode):
    """Mode'a göre ölçek parametreleri."""
    return {
        'small':  {'siparis': 20,  'sevkiyat_catsayi': 2, 'masraf_catsayi': 5, 'teklif': 30,  'musteri': 15},
        'medium': {'siparis': 50,  'sevkiyat_catsayi': 2, 'masraf_catsayi': 5, 'teklif': 80,  'musteri': 30},
        'large':  {'siparis': 150, 'sevkiyat_catsayi': 2, 'masraf_catsayi': 5, 'teklif': 200, 'musteri': 60},
    }.get(mode)


def _baslangic_uyari(mode, ayar):
    """Başlangıç uyarı mesajı."""
    print()
    print(f"{Y}{'═' * 65}{N}")
    print(f"{Y}⚠  CPS PERFORMANS SEED — {mode.upper()} MODE{N}")
    print(f"{Y}{'═' * 65}{N}")
    print(f"  Mode: {B}{mode}{N}")
    print(f"  Eklenecek:")
    print(f"    • {ayar['siparis']} sipariş")
    print(f"    • ~{ayar['siparis'] * ayar['sevkiyat_catsayi']} sevkiyat")
    print(f"    • ~{ayar['siparis'] * ayar['sevkiyat_catsayi'] * ayar['masraf_catsayi']} masraf")
    print(f"    • {ayar['teklif']} fiyat teklifi")
    print(f"    • {ayar['siparis']} finans anlaşması")
    print(f"    • {ayar['musteri']} demo müşteri")
    print()
    print(f"  Tahmini süre: {B}{ayar['siparis'] // 6}-{ayar['siparis'] // 4} saniye{N}")
    print(f"  Marker: {B}[PERF-SEED]{N} — clean için")
    print()
    print(f"  {R}! Prod ortamda çalışmaz (.production dosyası kontrol ediliyor){N}")
    print(f"{Y}{'═' * 65}{N}")
    print()


def _status(conn):
    """Mevcut [PERF-SEED] kayıtlarını say ve göster."""
    cur = conn.cursor()
    print()
    print(f"{B}=== MEVCUT [PERF-SEED] KAYITLARI ==={N}")

    tablolar = [
        ('grafik_cin_siparis',       "Notlar LIKE '[PERF-SEED]%'"),
        ('grafik_cin_siparis_kalem', "SiparisId IN (SELECT Id FROM grafik_cin_siparis WHERE Notlar LIKE '[PERF-SEED]%')"),
        ('grafik_sevkiyat',          "Notlar LIKE '[PERF-SEED]%'"),
        ('grafik_sevkiyat_masraf',   "SevkiyatId IN (SELECT Id FROM grafik_sevkiyat WHERE Notlar LIKE '[PERF-SEED]%')"),
        ('grafik_sevkiyat_dagitim',  "SevkiyatId IN (SELECT Id FROM grafik_sevkiyat WHERE Notlar LIKE '[PERF-SEED]%')"),
        ('grafik_fiyat_teklif',      "Notlar LIKE '[PERF-SEED]%'"),
        ('finans_anlasma',           "Notlar LIKE '[PERF-SEED]%'"),
        ('finans_odeme_plan',        "AnlasmaId IN (SELECT Id FROM finans_anlasma WHERE Notlar LIKE '[PERF-SEED]%')"),
        ('Cari_Har',                 "Aciklama LIKE '[PERF-SEED]%'"),
        ('Cari_Kart',                "CName LIKE '[PERF]%'"),
    ]
    toplam = 0
    for tablo, kosul in tablolar:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {tablo} WHERE {kosul}")
            n = cur.fetchone()[0]
            toplam += n
            renk = G if n > 0 else ''
            print(f"  {renk}{tablo:30s}: {n:>6}{N}")
        except Exception as e:
            print(f"  {R}{tablo:30s}: HATA ({e}){N}")
    print(f"  {B}{'─' * 40}{N}")
    print(f"  {B}TOPLAM: {toplam:>6} kayıt{N}")
    print()


def _clean(conn):
    """Sadece [PERF-SEED] kayıtlarını sil. Core veri (CIN-0001..0005 vs) dokunulmaz."""
    cur = conn.cursor()
    print()
    print(f"{Y}=== CLEAN — [PERF-SEED] kayıtlarını siliyor ==={N}")
    print(f"{Y}Core veri (CIN-0001..0005, M001-M005, M099) DOKUNULMAZ.{N}")
    print()

    silindi = {}
    # Sipariş ve altındakiler (dağıtım, masraf, kalem, sevkiyat)
    cur.execute("SELECT Id FROM grafik_cin_siparis WHERE Notlar LIKE '[PERF-SEED]%'")
    siparis_ids = [r[0] for r in cur.fetchall()]
    if siparis_ids:
        ph = ','.join('?' * len(siparis_ids))
        cur.execute(f"""DELETE FROM grafik_sevkiyat_dagitim WHERE SevkiyatId IN
                        (SELECT Id FROM grafik_sevkiyat WHERE SiparisId IN ({ph}))""",
                    siparis_ids)
        silindi['dağıtım'] = cur.rowcount
        cur.execute(f"""DELETE FROM grafik_sevkiyat_masraf WHERE SevkiyatId IN
                        (SELECT Id FROM grafik_sevkiyat WHERE SiparisId IN ({ph}))""",
                    siparis_ids)
        silindi['masraf'] = cur.rowcount
        cur.execute(f"DELETE FROM grafik_sevkiyat WHERE SiparisId IN ({ph})", siparis_ids)
        silindi['sevkiyat'] = cur.rowcount
        cur.execute(f"DELETE FROM grafik_cin_siparis_kalem WHERE SiparisId IN ({ph})", siparis_ids)
        silindi['kalem'] = cur.rowcount
        cur.execute(f"DELETE FROM grafik_cin_siparis WHERE Id IN ({ph})", siparis_ids)
        silindi['sipariş'] = cur.rowcount

    # Teklif
    cur.execute("DELETE FROM grafik_fiyat_teklif WHERE Notlar LIKE '[PERF-SEED]%'")
    silindi['teklif'] = cur.rowcount

    # Anlaşma ve ödeme planı
    cur.execute("SELECT Id FROM finans_anlasma WHERE Notlar LIKE '[PERF-SEED]%'")
    anlasma_ids = [r[0] for r in cur.fetchall()]
    if anlasma_ids:
        ph = ','.join('?' * len(anlasma_ids))
        cur.execute(f"DELETE FROM finans_odeme_plan WHERE AnlasmaId IN ({ph})", anlasma_ids)
        silindi['ödeme_plan'] = cur.rowcount
        cur.execute(f"DELETE FROM finans_anlasma WHERE Id IN ({ph})", anlasma_ids)
        silindi['anlaşma'] = cur.rowcount

    # Cari hareket (sadece marker'lı açıklama)
    cur.execute("DELETE FROM Cari_Har WHERE Aciklama LIKE '[PERF-SEED]%'")
    silindi['cari_hareket'] = cur.rowcount

    # Cari kart (demo müşteriler)
    cur.execute("DELETE FROM Cari_Kart WHERE CName LIKE '[PERF]%'")
    silindi['cari_kart'] = cur.rowcount

    conn.commit()
    for k, v in silindi.items():
        if v > 0:
            print(f"  ✓ {k:15s}: {v:>6} silindi")
    toplam = sum(silindi.values())
    print()
    print(f"{G}✓ Temizlendi: toplam {toplam} kayıt silindi{N}")
    print(f"{G}  Core veri korundu (CIN-0001..0005, M001-M005, M099).{N}")
    print()


def _seed(conn, mode):
    """Performans verisini oluştur."""
    ayar = _olcek_ayari(mode)
    random.seed(42)  # Deterministik
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cur = conn.cursor()

    t0 = time.time()
    sayac = {'musteri': 0, 'siparis': 0, 'kalem': 0, 'sevkiyat': 0, 'masraf': 0,
             'teklif': 0, 'anlasma': 0, 'plan': 0, 'cari_har': 0, 'dagitim': 0}

    # Mevcut tedarikçileri al
    cur.execute("SELECT Id FROM grafik_tedarikci WHERE Aktif=1")
    tedarikci_ids = [r[0] for r in cur.fetchall()]
    if not tedarikci_ids:
        print(f"{R}HATA: Aktif tedarikçi yok. init_mock_db.py çalıştırın.{N}")
        return

    # 1) Demo müşteriler
    print(f"→ {ayar['musteri']} müşteri oluşturuluyor...")
    for i in range(ayar['musteri']):
        ckod = f'PM{100 + i:03d}'
        cname = f'[PERF] Müşteri {100 + i} Tekstil'
        cur.execute("""INSERT OR IGNORE INTO Cari_Kart
                       (CKod, CName, CTip, Ulke, Bakiye, Aktif)
                       VALUES (?, ?, 'MUSTERI', 'TR', 0, 1)""",
                    (ckod, cname))
        sayac['musteri'] += cur.rowcount
    conn.commit()

    # 2) Siparişler + kalemler + sevkiyatlar + masraflar + dağıtım
    print(f"→ {ayar['siparis']} sipariş oluşturuluyor (kalem + sevkiyat + masraf + anlaşma)...")
    durumlar = ['ONAYLANDI', 'URETILIYOR', 'HAZIR', 'SEVKEDILDI', 'TAMAMLANDI']
    sevkiyat_durumlari = ['HAZIRLIK', 'YOLDA', 'GUMRUK', 'TESLIM']
    masraf_tipleri = ['NAVLUN', 'GUMRUK', 'SIGORTA', 'ARDIYE', 'LIMAN', 'MUSAVIR', 'YUKLEME', 'DIGER']
    pb_secenekleri = ['USD', 'EUR', 'CNY']

    for i in range(ayar['siparis']):
        snum = 100 + i
        sno = f'CIN-2026-{snum:04d}'
        durum = random.choice(durumlar)
        pb = random.choice(pb_secenekleri)
        kur = {'USD': 32.10, 'EUR': 41.00, 'CNY': 4.85}[pb] + random.uniform(-3, 3)
        kur = round(kur, 4)
        kalem_sayi = random.randint(1, 4)
        toplam_fiyat = random.uniform(5000, 50000)
        notlar = f'[PERF-SEED] Otomatik üretim mock sipariş #{i}'

        cur.execute("""INSERT INTO grafik_cin_siparis
                       (SiparisNo, TedarikciId, MusteriCKod, Durum, ParaBirimi, KurSnapshot,
                        ToplamTutar, BeklenenCikisTarihi, Notlar, OlusturmaTarih, OlusturanKullanici)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'admin')""",
                    (sno, random.choice(tedarikci_ids),
                     f'PM{100 + random.randint(0, ayar["musteri"]-1):03d}',
                     durum, pb, kur, round(toplam_fiyat, 2),
                     (date.today() - timedelta(days=random.randint(0, 120))).strftime('%Y-%m-%d'),
                     notlar, now))
        sayac['siparis'] += 1
        sid = cur.lastrowid

        # Kalemler
        fiyat_kalan = toplam_fiyat
        for kn in range(kalem_sayi):
            if kn == kalem_sayi - 1:
                tutar = fiyat_kalan
            else:
                tutar = fiyat_kalan / (kalem_sayi - kn) * random.uniform(0.8, 1.2)
            fiyat_kalan -= tutar
            miktar = random.randint(500, 5000)
            cur.execute("""INSERT INTO grafik_cin_siparis_kalem
                           (SiparisId, VaryantId, UrunId, Aciklama, Miktar, BirimFiyat, Tutar,
                            AgirlikKg, HacimM3, CiftSayi, OlusturmaTarih)
                           VALUES (?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (sid, f'[PERF] Model-{snum}-{kn+1}', miktar,
                         round(tutar/miktar, 4), round(tutar, 2),
                         random.randint(30, 200), round(random.uniform(0.3, 1.5), 2),
                         miktar, now))
            sayac['kalem'] += 1

        # Sevkiyat(lar)
        sevk_sayi = random.randint(1, 2)
        for sn in range(sevk_sayi):
            svno = f'SVK-2026-{100 + i * 2 + sn:04d}'
            svdurum = random.choice(sevkiyat_durumlari)
            svnotlar = f'[PERF-SEED] Otomatik sevkiyat #{i}-{sn}'
            svtarih = (date.today() - timedelta(days=random.randint(0, 90))).strftime('%Y-%m-%d')
            nakliye = random.choice(['KONTEYNER', 'UCAK', 'KARAYOLU'])
            cur.execute("""INSERT INTO grafik_sevkiyat
                           (SevkiyatNo, SiparisId, NakliyeTipi, Forwarder,
                            SevkTarihi, Durum, DagitimYontemi, DagitimHesaplandi,
                            ToplamMasrafTL, Notlar, OlusturmaTarih, OlusturanKullanici)
                           VALUES (?, ?, ?, 'Demo Forwarder', ?, ?, 'AGIRLIK', 0, 0, ?, ?, 'admin')""",
                        (svno, sid, nakliye, svtarih, svdurum, svnotlar, now))
            sayac['sevkiyat'] += 1
            sevk_id = cur.lastrowid

            # Masraflar (3-7 satır, farklı tarih/kur)
            masraf_sayi = random.randint(3, ayar['masraf_catsayi'] + 2)
            toplam_tl = 0
            for mn in range(masraf_sayi):
                mtip = random.choice(masraf_tipleri)
                mpb = random.choice(['TRY', 'USD'])
                mtutar = round(random.uniform(200, 5000), 2)
                mkur = 1.0 if mpb == 'TRY' else round(random.uniform(28, 40), 4)
                mtl = round(mtutar * mkur, 2)
                toplam_tl += mtl
                mtarih = (date.today() - timedelta(days=random.randint(0, 120))).strftime('%Y-%m-%d')
                cur.execute("""INSERT INTO grafik_sevkiyat_masraf
                               (SevkiyatId, Tip, BirimSayi, BirimFiyat, Tutar, ParaBirimi,
                                IslemTarih, KurSnapshot, TutarTL, OlusturmaTarih, OlusturanKullanici)
                               VALUES (?, ?, 0, 0, ?, ?, ?, ?, ?, ?, 'admin')""",
                            (sevk_id, mtip, mtutar, mpb, mtarih, mkur, mtl, now))
                sayac['masraf'] += 1
            cur.execute("UPDATE grafik_sevkiyat SET ToplamMasrafTL=? WHERE Id=?",
                        (round(toplam_tl, 2), sevk_id))

        # Anlaşma (her sipariş için)
        anl_tutar = round(toplam_fiyat * kur, 2)
        cur.execute("""INSERT INTO finans_anlasma
                       (ProjeKod, ProjeAdi, CKod, ToplamTutar, ParaBirimi, BaslangicTarih,
                        Durum, Notlar, OlusturmaTarih, OlusturanKullanici)
                       VALUES (?, ?, ?, ?, 'TRY', ?, 'AKTIF', ?, ?, 'admin')""",
                    (sno, f'Cin Siparis {snum}',
                     f'PM{100 + random.randint(0, ayar["musteri"]-1):03d}',
                     anl_tutar, (date.today() - timedelta(days=random.randint(0, 100))).strftime('%Y-%m-%d'),
                     f'[PERF-SEED] Otomatik anlaşma #{i}', now))
        sayac['anlasma'] += 1
        anl_id = cur.lastrowid

        # Plan satırları (1-3)
        plan_sayi = random.randint(1, 3)
        for pn in range(plan_sayi):
            cur.execute("""INSERT INTO finans_odeme_plan
                           (AnlasmaId, Sira, PlanTarih, OdemeTipi, Tutar, CekAdeti, Durum, Aciklama)
                           VALUES (?, ?, ?, 'HAVALE', ?, 1, 'BEKLIYOR', ?)""",
                        (anl_id, pn+1,
                         (date.today() + timedelta(days=random.randint(-60, 60))).strftime('%Y-%m-%d'),
                         round(anl_tutar / plan_sayi, 2),
                         f'Taksit {pn+1}/{plan_sayi}'))
            sayac['plan'] += 1

        # Cari hareket (anlaşma kaydı)
        cur.execute("""INSERT INTO Cari_Har
                       (CKod, Tarih, BelgeTip, BelgeNo, Aciklama, Borc, Alacak)
                       VALUES (?, ?, 'ANLASMA', ?, ?, ?, 0)""",
                    (f'PM{100 + random.randint(0, ayar["musteri"]-1):03d}',
                     (date.today() - timedelta(days=random.randint(0, 100))).strftime('%Y-%m-%d'),
                     sno, f'[PERF-SEED] {sno} anlasmasi', anl_tutar))
        sayac['cari_har'] += 1

        if (i + 1) % 20 == 0:
            conn.commit()
            print(f"  ... {i+1}/{ayar['siparis']} sipariş işlendi")
    conn.commit()

    # 3) Fiyat teklifleri
    print(f"→ {ayar['teklif']} fiyat teklifi oluşturuluyor...")
    teklif_durumlari = ['ALINDI', 'DEGERLENDIRILIYOR', 'SIPARIS_OLDU', 'REDDEDILDI']
    for i in range(ayar['teklif']):
        tno = f'TKF-2026-P{200 + i:04d}'
        pb = random.choice(['USD', 'EUR', 'CNY'])
        kur = {'USD': 32.10, 'EUR': 41.00, 'CNY': 4.85}[pb]
        try:
            cur.execute("""INSERT INTO grafik_fiyat_teklif
                           (TeklifNo, TedarikciId, UlkeKodu, UrunAd, Miktar, BirimFiyat, ParaBirimi,
                            KurSnapshot, TeklifTarihi, Durum, Notlar, OlusturmaTarih, OlusturanKullanici)
                           VALUES (?, ?, 'CN', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'admin')""",
                        (tno, random.choice(tedarikci_ids),
                         f'[PERF] Ürün tanımı {i+1}',
                         random.randint(1000, 20000),
                         round(random.uniform(0.5, 5.0), 4), pb, kur,
                         (date.today() - timedelta(days=random.randint(0, 180))).strftime('%Y-%m-%d'),
                         random.choice(teklif_durumlari),
                         '[PERF-SEED] Otomatik teklif', now))
            sayac['teklif'] += 1
        except Exception:
            pass
    conn.commit()

    # Cari bakiye güncelle (sadece [PERF] müşterileri için)
    cur.execute("""UPDATE Cari_Kart
                   SET Bakiye = COALESCE((SELECT SUM(Borc) - SUM(Alacak)
                                          FROM Cari_Har WHERE CKod = Cari_Kart.CKod), 0)
                   WHERE CName LIKE '[PERF]%'""")
    conn.commit()

    sure = time.time() - t0
    print()
    print(f"{G}{'═' * 65}{N}")
    print(f"{G}✓ TAMAMLANDI — {sum(sayac.values())} kayıt eklendi{N}")
    print(f"{G}{'═' * 65}{N}")
    print(f"  Süre: {B}{sure:.1f} saniye{N}")
    print()
    for k, v in sayac.items():
        if v > 0:
            print(f"    • {k:15s}: {v:>6}")
    print()
    print(f"  Test URL'leri:")
    print(f"    http://127.0.0.1:5057/grafik/siparis     (→ {3 + ayar['siparis'] + 2} sipariş)")
    print(f"    http://127.0.0.1:5057/grafik/sevkiyat    (→ {5 + sayac['sevkiyat']} sevkiyat)")
    print(f"    http://127.0.0.1:5057/grafik/teklif      (→ {3 + ayar['teklif']} teklif)")
    print(f"    http://127.0.0.1:5057/finans/cari        (→ {9 + ayar['musteri']} cari)")
    print()
    print(f"  Temizlemek için: {B}python seed_performans.py clean{N}")
    print()


def main():
    if len(sys.argv) < 2:
        mode = 'medium'
    else:
        mode = sys.argv[1].lower().strip()

    if mode not in ('small', 'medium', 'large', 'clean', 'status'):
        print(f"{R}HATA: Geçersiz mode: {mode}{N}")
        print(f"Geçerli mode'lar: small, medium, large, clean, status")
        sys.exit(1)

    _prod_kontrol()
    conn = _baglan()

    if mode == 'status':
        _status(conn)
        return

    if mode == 'clean':
        _clean(conn)
        return

    ayar = _olcek_ayari(mode)
    _baslangic_uyari(mode, ayar)
    _seed(conn, mode)


if __name__ == '__main__':
    main()
