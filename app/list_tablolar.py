import sqlite3

conn = sqlite3.connect('mock_data.db')
c = conn.cursor()

print("=== TUM TABLOLAR ===")
c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tablolar = [r[0] for r in c.fetchall()]
for t in tablolar:
    # her tablonun satir sayisi
    try:
        c.execute(f"SELECT COUNT(*) FROM {t}")
        n = c.fetchone()[0]
    except Exception as e:
        n = f"HATA: {e}"
    print(f"  {t:40s}  ({n} satir)")

print("\n=== BELGE ICEREN TABLOLARIN KOLONLARI ===")
for t in tablolar:
    if 'belge' in t.lower() or 'ithalat' in t.lower() or 'parti' in t.lower():
        print(f"\n--- {t} ---")
        c.execute(f"PRAGMA table_info({t})")
        for col in c.fetchall():
            print(f"  {col[1]:25s}  {col[2]}")

conn.close()
