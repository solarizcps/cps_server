"""
012 - Fire breakdown kolonlari
22.05.2026 - F9_5_3
Idempotent: PRAGMA kontrolu ile var olan kolonu skip eder.
"""
import sqlite3, os

def db_path():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "mock_data.db")

def kolon_var_mi(con, tablo, kolon):
    cur = con.cursor()
    cur.execute("PRAGMA table_info(" + tablo + ")")
    return any(r[1] == kolon for r in cur.fetchall())

def run():
    con = sqlite3.connect(db_path(), timeout=10)
    yeni = [
        ("teknik_fire_kg", "REAL DEFAULT 0"),
        ("bos_atis_kg",    "REAL DEFAULT 0"),
        ("yolluk_fire_kg", "REAL DEFAULT 0"),
    ]
    eklenen = atlanan = 0
    for kol, tip in yeni:
        if kolon_var_mi(con, "enj_gunluk_rapor", kol):
            print("  [SKIP] " + kol + " zaten var")
            atlanan += 1
        else:
            con.execute("ALTER TABLE enj_gunluk_rapor ADD COLUMN " + kol + " " + tip)
            print("  [ADD]  " + kol + " eklendi")
            eklenen += 1
    con.commit()
    con.close()
    print("\nSonuc: " + str(eklenen) + " eklendi, " + str(atlanan) + " atlandi")

if __name__ == "__main__":
    run()