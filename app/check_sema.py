import sqlite3

conn = sqlite3.connect('mock_data.db')
c = conn.cursor()

print("=== ithalat_belge KOLONLARI ===")
c.execute("PRAGMA table_info(ithalat_belge)")
for col in c.fetchall():
    print(f"  {col[1]:25s}  {col[2]}")

print("\n=== SON 10 KAYIT (tum kolonlar) ===")
c.execute("SELECT * FROM ithalat_belge ORDER BY belge_id DESC LIMIT 10")
cols = [d[0] for d in c.description]
print("KOLONLAR:", cols)
print()
for r in c.fetchall():
    print(dict(zip(cols, r)))
    print("---")

conn.close()
