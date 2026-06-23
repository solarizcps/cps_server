"""
Migration 065: nexgen_arge_test bağlantı alanı
FAZ-4C-4 — ARGE Testten Üretim Reçetesine Aktarım

Değişiklikler:
1) nexgen_arge_test.olusan_uretim_varyant_id  — hangi uretim_varyant'a dönüştü
2) nexgen_arge_test.olusan_renk_varyant_id    — hangi renk_varyant oluşturuldu / seçildi

KURAL: nexgen_stok_hareket'e DOKUNULMAZ.
       Ana kaynak reçete (nexgen_recete_kalem) değiştirilemez.
"""

import sqlite3, os


def run(db_path):
    con = sqlite3.connect(db_path)
    try:
        cols = [c[1] for c in con.execute("PRAGMA table_info(nexgen_arge_test)").fetchall()]

        if 'olusan_uretim_varyant_id' not in cols:
            con.execute("""
                ALTER TABLE nexgen_arge_test
                ADD COLUMN olusan_uretim_varyant_id INTEGER
            """)
            print("[065] nexgen_arge_test.olusan_uretim_varyant_id eklendi")
        else:
            print("[065] olusan_uretim_varyant_id zaten var — atlanıyor")

        if 'olusan_renk_varyant_id' not in cols:
            con.execute("""
                ALTER TABLE nexgen_arge_test
                ADD COLUMN olusan_renk_varyant_id INTEGER
            """)
            print("[065] nexgen_arge_test.olusan_renk_varyant_id eklendi")
        else:
            print("[065] olusan_renk_varyant_id zaten var — atlanıyor")

        con.commit()
        print("[065] Migration basarili")
    except Exception as e:
        con.rollback()
        print(f"[065] HATA: {e}")
        raise
    finally:
        con.close()


if __name__ == '__main__':
    db = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
    run(os.path.abspath(db))
