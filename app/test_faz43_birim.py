import sys
sys.path.insert(0, r"C:\cps_dev")
from modules.usta import gorev_db

print("=" * 60)
print("BIRIM TESTI - gorev_db.py")
print("=" * 60)

# TEST 1: Bos liste
r = gorev_db.gorev_listele()
print(f"\n[TEST 1] gorev_listele() bos: ok={r['ok']}, sayi={r['gorev_sayisi']}")
assert r["ok"], "TEST 1 BASARISIZ"

# TEST 2: Gorev ekle (eksik alan)
r = gorev_db.gorev_ekle({"siparis_no": "33680"})
print(f"\n[TEST 2] gorev_ekle eksik alan: ok={r['ok']}, hata={r.get('hata')}")
assert not r["ok"], "TEST 2 BASARISIZ - hata bekleniyordu"

# TEST 3: Gorev ekle (tam)
r = gorev_db.gorev_ekle({
    "karar_masasi_satir_id": "MOCK_TEST_001",
    "siparis_no": "33680",
    "emir_no": "110626",
    "musteri": "Lc Waikiki",
    "model": "BRP-9000",
    "bant": "B-2",
    "hedef_adet": 720,
    "kalan_adet": 720,
    "uretilebilirlik": "HAZIR",
    "darbogaz": "Temizleme +88%",
    "talimat": "Temizleme bandini bosalt",
    "oncelik": 75,
    "musteri_etiketi": "NAKIT",
    "atanan_usta": "Hasan",
    "olusturan": "Adem",
    "olusturan_notu": "Birim test - silinebilir",
    "termin": "2026-05-31",
    "termin_durumu": "uzak"
})
print(f"\n[TEST 3] gorev_ekle tam: ok={r['ok']}, gorev_id={r.get('gorev_id')}")
assert r["ok"], "TEST 3 BASARISIZ"
test_gorev_id = r["gorev_id"]

# TEST 4: Listele
r = gorev_db.gorev_listele("acik")
print(f"\n[TEST 4] gorev_listele acik: sayi={r['gorev_sayisi']}, atandi={r['atandi_sayisi']}")

# TEST 5: Durum gecisi ATANDI -> OKUNDU
r = gorev_db.gorev_okudu(test_gorev_id)
print(f"\n[TEST 5] gorev_okudu: ok={r['ok']}, eski={r.get('eski_durum')}, yeni={r.get('yeni_durum')}")
assert r["ok"] and r.get("yeni_durum") == "OKUNDU", "TEST 5 BASARISIZ"

# TEST 6: Yanlis durum gecisi (OKUNDU -> ATANDI denenince)
r = gorev_db.gorev_durum_guncelle(test_gorev_id, "ATANDI")
print(f"\n[TEST 6] yanlis gecis: ok={r['ok']}, hata={r.get('hata')}")
assert not r["ok"] and r.get("hata") == "durum_uyumsuz", "TEST 6 BASARISIZ"

# TEST 7: BASLADI
r = gorev_db.gorev_basladi(test_gorev_id)
print(f"\n[TEST 7] gorev_basladi: ok={r['ok']}, yeni={r.get('yeni_durum')}")
assert r["ok"], "TEST 7 BASARISIZ"

# TEST 8: TAMAMLANDI + usta_notu
r = gorev_db.gorev_bitti(test_gorev_id, "Test tamamlandi - silinebilir")
print(f"\n[TEST 8] gorev_bitti: ok={r['ok']}, yeni={r.get('yeni_durum')}")
assert r["ok"], "TEST 8 BASARISIZ"

# TEST 9: Tekrar bitir (TAMAMLANDI sonrasi)
r = gorev_db.gorev_bitti(test_gorev_id)
print(f"\n[TEST 9] tekrar bitir: ok={r['ok']}, hata={r.get('hata')}")
assert not r["ok"], "TEST 9 BASARISIZ - hata bekleniyordu"

# TEST 10: Olmayan gorev
r = gorev_db.gorev_okudu(99999)
print(f"\n[TEST 10] olmayan gorev: ok={r['ok']}, hata={r.get('hata')}")
assert not r["ok"], "TEST 10 BASARISIZ"

# TEST 11: Istatistik
r = gorev_db.istatistik()
print(f"\n[TEST 11] istatistik: toplam={r['toplam']}, dagilim={r['durum_dagilimi']}")

print("\n" + "=" * 60)
print(f"[TAMAM] 11/11 birim test gecti")
print(f"        Test gorev_id={test_gorev_id} TAMAMLANDI durumda kaldi (audit)")
print("=" * 60)