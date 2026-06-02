"""
Migration: 015_enjeksiyon_planlama_yetki
Tarih: 2026-06-02
Faz: ENJ-RAPOR-FIX2

Yapılanlar:
  sistem_rol_yetki tablosuna Planlama rolü için enjeksiyon base yetki kaydı eklenir.

Root Cause:
  Planlama (RolId=32) için sistem_rol_yetki içinde enjeksiyon (YetkiId=135) kaydı yoktu.
  Bu nedenle base.html'deki {% if yetki('enjeksiyon') %} koşulu False dönüyor,
  Saha menü grubu (Enjeksiyon + Geçmiş/Rapor linkleri) Planlama kullanıcılarına görünmüyordu.

Eklenen kayıt:
  RolId=32       → Planlama rolü
  YetkiId=135    → enjeksiyon (Enjeksiyon Modulu base yetki)
  Gorebilir=1    → legacy uyum
  can_view=1     → sidebar görünürlüğü + rapor okuma
  can_report=1   → rapor erişimi semantiği
  can_create=0   → yazma yok
  can_update=0   → yazma yok
  can_delete=0   → yazma yok
  can_approve=0  → onay yok
  can_manage=0   → yönetim yok

İdempotent:
  Aynı (RolId, YetkiId) çifti zaten varsa ekleme yapılmaz.

DOKUNULMAYAN:
  - auth.py
  - base.html
  - route/decorator
  - Enjeksiyon saha yazma yetkileri (enjeksiyon.saha YetkiId=136)
  - Diğer roller
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')

# Sabit değerler — recon'da doğrulandı
PLANLAMA_ROL_ID = 32
ENJ_BASE_YETKI_ID = 135  # Kod='enjeksiyon', Ad='Enjeksiyon Modulu'


def run():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # 1) Rol doğrulama
    rol = cur.execute(
        "SELECT Id, Ad FROM sistem_rol WHERE Id = ?", (PLANLAMA_ROL_ID,)
    ).fetchone()
    if not rol:
        print(f"HATA: RolId={PLANLAMA_ROL_ID} bulunamadi. Migration iptal.")
        con.close()
        return

    # 2) Yetki doğrulama
    yetki = cur.execute(
        "SELECT Id, Kod, Modul FROM sistem_yetki WHERE Id = ?", (ENJ_BASE_YETKI_ID,)
    ).fetchone()
    if not yetki:
        print(f"HATA: YetkiId={ENJ_BASE_YETKI_ID} bulunamadi. Migration iptal.")
        con.close()
        return

    print(f"Rol  : Id={rol['Id']} Ad={rol['Ad']}")
    print(f"Yetki: Id={yetki['Id']} Kod={yetki['Kod']} Modul={yetki['Modul']}")

    # 3) Idempotent kontrol
    mevcut = cur.execute(
        "SELECT Id FROM sistem_rol_yetki WHERE RolId = ? AND YetkiId = ?",
        (PLANLAMA_ROL_ID, ENJ_BASE_YETKI_ID)
    ).fetchone()

    if mevcut:
        print(f"SKIP: Kayit zaten mevcut (Id={mevcut['Id']}). Islem yapilmadi.")
        con.close()
        return

    # 4) Ekle
    cur.execute("""
        INSERT INTO sistem_rol_yetki
            (RolId, YetkiId, Gorebilir, Duzenleyebilir,
             can_view, can_create, can_update, can_delete,
             can_approve, can_report, can_manage)
        VALUES (?, ?, 1, 0, 1, 0, 0, 0, 0, 1, 0)
    """, (PLANLAMA_ROL_ID, ENJ_BASE_YETKI_ID))

    con.commit()
    yeni_id = cur.lastrowid
    print(f"OK: sistem_rol_yetki Id={yeni_id} eklendi.")
    print(f"    Planlama (RolId={PLANLAMA_ROL_ID}) -> enjeksiyon (YetkiId={ENJ_BASE_YETKI_ID})")
    print(f"    can_view=1, can_report=1, yazma=0")

    con.close()


if __name__ == '__main__':
    run()
