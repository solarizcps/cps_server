import sqlite3

conn = sqlite3.connect('mock_data.db')
cur = conn.cursor()
cur.execute("UPDATE sablon SET aktif=1, guncelleme=datetime('now','localtime') WHERE id=1")
print(f"Etkilenen satir: {cur.rowcount}")
conn.commit()

print("\nMevcut sablonlar:")
for r in cur.execute("SELECT id, sablon_adi, aktif FROM sablon"):
    print(f"  id={r[0]}, adi={r[1]}, aktif={r[2]}")
conn.close()
