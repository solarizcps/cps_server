import sqlite3
DB = r'C:\cps_dev\mock_data.db'
c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row

print("=== USTA_AKSIYON ===")
for r in c.execute("SELECT * FROM usta_aksiyon ORDER BY id DESC LIMIT 5"):
    print(f"  ID={r['id']} | Usta: {r['usta']} | Sebep: {r['sebep_kategori']}")
    print(f"  Aciklama: {r['aciklama']}")
    print(f"  Zaman: {r['giris_zamani']}")
    print()

print("=== SAPMA_OLAY ===")
for r in c.execute("SELECT * FROM sapma_olay ORDER BY id DESC LIMIT 5"):
    print(f"  ID={r['id']} | {r['siparis_no']} | Durum: {r['durum']}")
    print(f"  Acilis: {r['acilis_zamani']} | Kapanis: {r['kapanis_zamani']}")
    print()

print("=== USTA_KILIT_DURUM ===")
for r in c.execute("SELECT * FROM usta_kilit_durum"):
    print(f"  {r['kullanici']}: kilit_aktif={r['kilit_aktif']}")

c.close()