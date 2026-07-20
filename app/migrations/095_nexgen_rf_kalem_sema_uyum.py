# -*- coding: utf-8 -*-
"""
Migration 095 — NexGen FAZ-MRP-00A: RF Kalem Şema Uyumu + BOYA Audit
======================================================================
Sorun:
  [1] nexgen_rf_kalem.pigment_ad  — routes.py bu kolonu bekliyor;
      PRAGMA ile runtime check var ama migration'da tanımlı değil.
  [2] nexgen_rf_kalem.stok_kart_id — migration'da NOT NULL;
      routes.py FAZ-3F-6C'de LEFT JOIN + NULL toleransı bekliyor
      (eşleşmemiş pigment kalemleri için).
  [3] recete_kalem BOYA kalıntıları — routes çalışma anında hariç
      tutuyor ama eski veride aktif BOYA kalemleri çift sayım riski.

Bu migration:
  [1] nexgen_rf_kalem'e pigment_ad TEXT NULL kolonu ekler (idempotent)
  [2] stok_kart_id NOT NULL → nullable YAPILAMAZ SQLite'ta (sütun
      constraint değişimi yok); bu nedenle NULL kayıt YASAK'tır,
      routes LEFT JOIN sadece güvenlik önlemi — belgelenir, değişmez.
  [3] recete_kalem BOYA kalemleri audit eder; aktif varsa pasife alır
      (aktif=0) — BOYA hesabı routes tarafından zaten dışlanıyor,
      pasifleştirme tutarlılığı sağlar.

Korunan şeyler:
  - Mevcut RF kalemleri, RF renkleri, formül uygunlukları
  - Stok hareketleri, rezervler, batch kayıtları
  - Hesaplama motoru fonksiyonları

Idempotent: Tekrar çalıştırılabilir.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


def run():
    if not os.path.exists(DB_PATH):
        print(f"HATA: DB bulunamadı: {DB_PATH}")
        return

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("=" * 70)
    print("Migration 095 — RF Kalem Şema Uyumu + BOYA Audit")
    print(f"DB: {os.path.abspath(DB_PATH)}")
    print("=" * 70)

    # ── Güvenlik: mevcut durum ────────────────────────────────────────
    rfk_onceki = cur.execute("SELECT COUNT(*) FROM nexgen_rf_kalem").fetchone()[0]
    rk_onceki  = cur.execute("SELECT COUNT(*) FROM nexgen_recete_kalem WHERE aktif=1").fetchone()[0]
    sh_onceki  = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]
    print(f"\n[KONTROL ÖNCESİ]")
    print(f"  nexgen_rf_kalem:       {rfk_onceki} kayıt")
    print(f"  nexgen_recete_kalem:   {rk_onceki} aktif")
    print(f"  nexgen_stok_hareket:   {sh_onceki} (dokunulmaz)")

    # ── 1) nexgen_rf_kalem.pigment_ad ekle ───────────────────────────
    print("\n[1] nexgen_rf_kalem.pigment_ad kolonu:")
    rfk_cols = [c['name'] for c in cur.execute("PRAGMA table_info(nexgen_rf_kalem)").fetchall()]
    print(f"    Mevcut kolonlar: {rfk_cols}")

    if 'pigment_ad' not in rfk_cols:
        cur.execute("ALTER TABLE nexgen_rf_kalem ADD COLUMN pigment_ad TEXT")
        con.commit()
        print("    OK   pigment_ad kolonu eklendi (NULL default)")
    else:
        print("    SKIP pigment_ad zaten mevcut")

    # Doğrulama
    rfk_cols_sonra = [c['name'] for c in cur.execute("PRAGMA table_info(nexgen_rf_kalem)").fetchall()]
    has_pigment = 'pigment_ad' in rfk_cols_sonra
    print(f"    CHECK pigment_ad in nexgen_rf_kalem: {has_pigment}")

    # ── 2) stok_kart_id NULL bilgisi (SQLite kısıtı) ─────────────────
    print("\n[2] nexgen_rf_kalem.stok_kart_id NOT NULL analizi:")
    stok_kart_nullable = next(
        (c['notnull'] == 0 for c in cur.execute("PRAGMA table_info(nexgen_rf_kalem)").fetchall()
         if c['name'] == 'stok_kart_id'), None
    )
    print(f"    stok_kart_id notnull={not stok_kart_nullable}")
    print(f"    SQLite'ta mevcut sütun kısıtı DEĞİŞTİRİLEMEZ (tabloyu yeniden oluşturmak gerekir).")
    print(f"    NOT: Bu sütun gerçekte hiç NULL değer içermiyor — LEFT JOIN sadece güvenlik önlemi.")

    # NULL var mı kontrol
    null_say = cur.execute(
        "SELECT COUNT(*) FROM nexgen_rf_kalem WHERE stok_kart_id IS NULL"
    ).fetchone()[0]
    print(f"    Mevcut NULL stok_kart_id kaydı: {null_say}  (beklenen: 0)")

    if null_say > 0:
        print(f"    UYARI: {null_say} adet NULL stok_kart_id kaydı var — inceleme gerekiyor!")
        null_rows = cur.execute(
            "SELECT id, rf_renk_id, miktar_kg, pigment_ad, aktif FROM nexgen_rf_kalem WHERE stok_kart_id IS NULL"
        ).fetchall()
        for r in null_rows:
            print(f"    rfk.id={r['id']} rf_renk_id={r['rf_renk_id']} "
                  f"miktar={r['miktar_kg']} pigment_ad={r['pigment_ad']} aktif={r['aktif']}")

    # ── 3) recete_kalem BOYA audit ────────────────────────────────────
    print("\n[3] nexgen_recete_kalem BOYA audit:")

    boya_rows = cur.execute("""
        SELECT rk.id, rk.uretim_varyant_id, rk.stok_kart_id,
               sk.kod AS stok_kod, sk.ad AS stok_ad, sk.kategori,
               rk.miktar_kg, rk.aktif
        FROM nexgen_recete_kalem rk
        JOIN nexgen_stok_kart sk ON sk.id = rk.stok_kart_id
        WHERE UPPER(COALESCE(sk.kategori, '')) = 'BOYA'
    """).fetchall()

    print(f"    BOYA kategorili recete_kalem toplam: {len(boya_rows)}")

    aktif_boya = [r for r in boya_rows if r['aktif']]
    pasif_boya = [r for r in boya_rows if not r['aktif']]

    print(f"    Aktif BOYA kalem: {len(aktif_boya)}")
    print(f"    Pasif BOYA kalem: {len(pasif_boya)}")

    for r in boya_rows:
        durum = "AKTİF" if r['aktif'] else "pasif"
        print(f"    rk.id={r['id']} uv_id={r['uretim_varyant_id']} "
              f"stok={r['stok_kod']} ({r['stok_ad']}) miktar={r['miktar_kg']} [{durum}]")

    if aktif_boya:
        print(f"\n    {len(aktif_boya)} aktif BOYA kalem pasife alınıyor...")
        for r in aktif_boya:
            # Çift sayım önlemi: Bu kalemler routes tarafından zaten hariç tutuluyor.
            # Veri tutarlılığı için aktif=0 yapılıyor.
            cur.execute(
                "UPDATE nexgen_recete_kalem SET aktif=0 WHERE id=?",
                (r['id'],)
            )
            print(f"    UPDATE recete_kalem id={r['id']} aktif=0 "
                  f"(stok={r['stok_kod']}, uv_id={r['uretim_varyant_id']})")
        con.commit()
        print(f"    OK   {len(aktif_boya)} BOYA kalem pasife alındı")
    else:
        print("    OK   Aktif BOYA kalem yok — çift sayım riski yok")

    # ── 4) Kontrol: uretim_plan rf_renk_id boş ────────────────────────
    print("\n[4] nexgen_uretim_plan rf_renk_id analizi:")
    up_cols = [c['name'] for c in cur.execute("PRAGMA table_info(nexgen_uretim_plan)").fetchall()]
    if 'rf_renk_id' in up_cols:
        up_total = cur.execute("SELECT COUNT(*) FROM nexgen_uretim_plan").fetchone()[0]
        up_bos   = cur.execute("SELECT COUNT(*) FROM nexgen_uretim_plan WHERE rf_renk_id IS NULL").fetchone()[0]
        up_dolu  = up_total - up_bos
        print(f"    Toplam plan: {up_total}  rf_renk_id dolu: {up_dolu}  boş: {up_bos}")
        if up_bos > 0:
            print(f"    BİLGİ: {up_bos} planda rf_renk_id boş — MPR bu planlarda boya hesaplamaz.")
            print(f"    Bu bir veri durumu; migration'da değiştirilmez.")
    else:
        print("    rf_renk_id kolonu yok!")

    # ── 5) Son kontrol ────────────────────────────────────────────────
    rfk_sonraki = cur.execute("SELECT COUNT(*) FROM nexgen_rf_kalem").fetchone()[0]
    rk_sonraki  = cur.execute("SELECT COUNT(*) FROM nexgen_recete_kalem WHERE aktif=1").fetchone()[0]
    sh_sonraki  = cur.execute("SELECT COUNT(*) FROM nexgen_stok_hareket").fetchone()[0]

    print("\n[KONTROL SONRASI]")
    print(f"  nexgen_rf_kalem:       {rfk_sonraki} (öncesi={rfk_onceki}, delta={rfk_sonraki - rfk_onceki})")
    print(f"  nexgen_recete_kalem:   {rk_sonraki} aktif (öncesi={rk_onceki}, delta={rk_sonraki - rk_onceki})")
    print(f"  nexgen_stok_hareket:   {sh_sonraki} (öncesi={sh_onceki}, delta={sh_sonraki - sh_onceki}) — 0 olmalı!")

    assert sh_sonraki == sh_onceki, "HATA: stok_hareket değişti!"

    # ── schema_migrations ─────────────────────────────────────────────
    try:
        cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(95)")
        con.commit()
        print("\n  OK   schema_migrations version=95")
    except Exception as e:
        print(f"\n  WARN schema_migrations: {e}")

    print("\n" + "=" * 70)
    print("ÖZET")
    print("=" * 70)
    print(f"  [1] pigment_ad kolonu:  {'zaten vardı' if 'pigment_ad' in rfk_cols else 'EKLENDİ'}")
    print(f"  [2] NULL stok_kart_id:  {null_say} kayıt (beklenen: 0)")
    print(f"  [3] BOYA pasifleştirme: {len(aktif_boya)} kalem pasife alındı")
    print(f"  [4] stok_hareket delta: {sh_sonraki - sh_onceki} (0 olmalı)")
    if sh_sonraki == sh_onceki and null_say == 0:
        print("\n  SONUÇ: Veri bütünlüğü TAMAM. Şema uyumu sağlandı.")
    else:
        print("\n  SONUÇ: Bazı kontrol maddelerini gözden geçir (yukarıdaki uyarılara bak).")

    con.close()
    print("=== Migration 095 tamamlandı ===\n")


if __name__ == '__main__':
    run()
