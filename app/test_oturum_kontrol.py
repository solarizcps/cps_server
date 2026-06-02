import sqlite3
conn = sqlite3.connect(r"C:\cps_dev\solariz_dev.db")
cur = conn.cursor()
r = cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='usta_gorevleri'").fetchone()
print(f"Tablo: {'VAR' if r else 'YOK'}")
if r:
    toplam = cur.execute("SELECT COUNT(*) FROM usta_gorevleri").fetchone()[0]
    print(f"Toplam kayit: {toplam}")
    durumlar = cur.execute("SELECT durum, COUNT(*) FROM usta_gorevleri GROUP BY durum").fetchall()
    for d, c in durumlar:
        print(f"  {d}: {c}")
    print("Son 3 kayit:")
    son = cur.execute("SELECT id, musteri, model, durum, olusturma_tarih, olusturan FROM usta_gorevleri ORDER BY id DESC LIMIT 3").fetchall()
    for s in son:
        print(f"  id={s[0]} {s[1]}/{s[2]} [{s[3]}] {s[4]} olusturan={s[5]}")
conn.close()