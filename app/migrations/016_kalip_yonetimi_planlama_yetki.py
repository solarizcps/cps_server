"""
Migration: 016_kalip_yonetimi_planlama_yetki
Tarih: 2026-06-02
Faz: KALIP-YETKI-FAZ-A

Yapılanlar:
  1) sistem_yetki tablosuna yeni yetki kodu eklenir:
       Kod='planlama.enjeksiyon.kalip'
       Modul='planlama'
       Ad='Kalip Yonetimi Planlama'

  2) sistem_rol_yetki tablosuna Planlama rolü için bu yetki eklenir:
       RolId=32  (Planlama)
       can_view=1, can_create=1, can_update=1, can_delete=1, can_report=1, can_manage=0

Kapsam:
  Mehmet (Planlama rolü):
    - Kalıp listesini görebilir (can_view)
    - Kalıp bilgilerini güncelleyebilir (can_update)
    - Kalıp görseli yükleyebilir (can_create — Faz B'de yeni kalıp ekleme yapılana kadar geçici)
    - can_delete=1 Faz B için hazır (endpoint henüz yok)
    - can_manage=0 → sistem yönetimi erişimi yok

Korunacaklar:
  - SuperAdmin erişimi bozulmaz (yetki_var her zaman '*' shortcut)
  - @ky_kalip_yetki fonksiyonu silinmez
  - KBÇ hesap mantığı dokunulmaz
  - auth.py değişmez
  - Kalıp ekleme/silme endpoint henüz yok (Faz B)

İdempotent:
  - sistem_yetki: Kod zaten varsa skip
  - sistem_rol_yetki: (RolId, YetkiId) çifti varsa skip
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')

PLANLAMA_ROL_ID = 32
YENI_YETKI_KOD = 'planlama.enjeksiyon.kalip'
YENI_YETKI_MODUL = 'planlama'
YENI_YETKI_AD = 'Kalip Yonetimi Planlama'


def run():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # 1) Planlama rolü doğrulama
    rol = cur.execute(
        "SELECT Id, Ad FROM sistem_rol WHERE Id = ?", (PLANLAMA_ROL_ID,)
    ).fetchone()
    if not rol:
        print(f"HATA: RolId={PLANLAMA_ROL_ID} bulunamadi. Migration iptal.")
        con.close()
        return
    print(f"Rol  : Id={rol['Id']} Ad={rol['Ad']}")

    # 2) sistem_yetki — idempotent kontrol + ekle
    mevcut_yetki = cur.execute(
        "SELECT Id, Kod FROM sistem_yetki WHERE Kod = ?", (YENI_YETKI_KOD,)
    ).fetchone()

    if mevcut_yetki:
        yetki_id = mevcut_yetki['Id']
        print(f"SKIP sistem_yetki: Kod='{YENI_YETKI_KOD}' zaten mevcut (Id={yetki_id}).")
    else:
        cur.execute("""
            INSERT INTO sistem_yetki (Kod, Modul, Ad)
            VALUES (?, ?, ?)
        """, (YENI_YETKI_KOD, YENI_YETKI_MODUL, YENI_YETKI_AD))
        yetki_id = cur.lastrowid
        print(f"OK sistem_yetki: Id={yetki_id} Kod='{YENI_YETKI_KOD}' eklendi.")

    # 3) sistem_rol_yetki — idempotent kontrol + ekle
    mevcut_rol_yetki = cur.execute(
        "SELECT Id FROM sistem_rol_yetki WHERE RolId = ? AND YetkiId = ?",
        (PLANLAMA_ROL_ID, yetki_id)
    ).fetchone()

    if mevcut_rol_yetki:
        print(f"SKIP sistem_rol_yetki: Kayit zaten mevcut (Id={mevcut_rol_yetki['Id']}).")
    else:
        cur.execute("""
            INSERT INTO sistem_rol_yetki
                (RolId, YetkiId, Gorebilir, Duzenleyebilir,
                 can_view, can_create, can_update, can_delete,
                 can_approve, can_report, can_manage)
            VALUES (?, ?, 1, 1, 1, 1, 1, 1, 0, 1, 0)
        """, (PLANLAMA_ROL_ID, yetki_id))
        con.commit()
        yeni_id = cur.lastrowid
        print(f"OK sistem_rol_yetki: Id={yeni_id} eklendi.")
        print(f"   Planlama (RolId={PLANLAMA_ROL_ID}) -> '{YENI_YETKI_KOD}' (YetkiId={yetki_id})")
        print(f"   can_view=1, can_create=1, can_update=1, can_delete=1, can_report=1, can_manage=0")

    con.commit()
    con.close()
    print("Migration 016 tamamlandi.")


if __name__ == '__main__':
    run()
