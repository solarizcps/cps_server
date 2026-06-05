import sqlite3
conn = sqlite3.connect('mock_data.db')
cur = conn.cursor()
print("emir_alt_proses tablosu kolonlari:")
for r in cur.execute("PRAGMA table_info(emir_alt_proses)"):
    nn = "NOT NULL" if r[3] else "        "
    dflt = f"default={r[4]!r}" if r[4] is not None else ""
    pk = "[PK]" if r[5] else ""
    print(f"  [{r[0]:>2}] {r[1]:<25} {r[2]:<10} {nn} {dflt}{pk}")
conn.close()
