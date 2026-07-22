# -*- coding: utf-8 -*-
"""
112_nexgen_planlama_mehmet_yetki.py
=====================================
FAZ-MEHMET-KULLANICI-BAZLI-YETKI-DUZELTME  (v2 — override tablosu)

AMAÇ:
  Yalnız KullaniciAdi='mehmet' (KullaniciId=31) kullanıcısına NexGen
  Pazarlama ekranına erişim yetkisi verilir.

  Mehmet RolId=32 Planlama'da KALIR — eski tüm yetkilerini korur.
  mehmetemin (Id=35) ETKİLENMEZ.
  RolId=32'ye hiçbir nexgen yetkisi eklenmez.

ÇÖZÜM:
  user_permission_override tablosuna Mehmet'e özel 3 kayıt INSERT edilir.
  auth.py'deki kullanici_yetkileri() bu tabloyu rol yetkilerine EK olarak okur.

  Eklenen override'lar:
    - nexgen.view       (YetkiId=178) can_view=1   → Sidebar NexGen menü
    - nexgen.plan.view  (YetkiId=188) can_view=1   → Pazarlama sayfası + okuma
    - nexgen.plan.manage(YetkiId=189) can_manage=1 → Taslak kaydet, MRP, Üretime Gönder

KURALLAR:
  - INSERT OR IGNORE → idempotent
  - can_delete=0, can_approve=0 — minimum principle
  - sistem_rol / sistem_rol_yetki / sistem_kullanici.RolId değişmez
"""
import os
import sqlite3
import datetime

MIGRATION_VERSION = 112
MEHMET_KULLANICI_ID = 31
MEHMET_KADI = 'mehmet'

# (YetkiId, beklenen_kod, can_view, can_manage, can_report)
OVERRIDES = [
    (178, 'nexgen.view',        1, 0, 1),
    (188, 'nexgen.plan.view',   1, 0, 1),
    (189, 'nexgen.plan.manage', 0, 1, 0),
]


def log(msg):
    print(msg)


def run(db_path=None):
    if db_path is None:
        db_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')
        )

    log('=' * 70)
    log(f'[{MIGRATION_VERSION}] FAZ-MEHMET-OVERRIDE başlıyor')
    log(f'[{MIGRATION_VERSION}] DB: {db_path}')
    log('=' * 70)

    con = sqlite3.connect(db_path, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        # ── schema_migrations kontrolü ──────────────────────────────
        has_sm = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if has_sm:
            applied = con.execute(
                'SELECT version FROM schema_migrations WHERE version=?',
                (MIGRATION_VERSION,)
            ).fetchone()
            if applied:
                log(f'[{MIGRATION_VERSION}] SKIP — zaten uygulandı (version={MIGRATION_VERSION})')
                return

        # ── user_permission_override tablosu var mı? ─────────────────
        upo_tablo = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='user_permission_override'"
        ).fetchone()
        if not upo_tablo:
            raise RuntimeError('user_permission_override tablosu bulunamadı')

        # ── Doğrulamalar ────────────────────────────────────────────
        mehmet = con.execute(
            'SELECT Id, KullaniciAdi, RolId, Aktif FROM sistem_kullanici WHERE Id=? AND KullaniciAdi=?',
            (MEHMET_KULLANICI_ID, MEHMET_KADI)
        ).fetchone()
        if not mehmet:
            raise RuntimeError(f'mehmet (KullaniciId={MEHMET_KULLANICI_ID}) bulunamadı')
        if not mehmet['Aktif']:
            raise RuntimeError('mehmet pasif')

        for yid, kod, _, _, _ in OVERRIDES:
            row = con.execute('SELECT Kod FROM sistem_yetki WHERE Id=?', (yid,)).fetchone()
            if not row:
                raise RuntimeError(f'YetkiId={yid} ({kod}) sistem_yetki\'de yok')
            if row['Kod'] != kod:
                raise RuntimeError(f'YetkiId={yid} kodu="{row["Kod"]}" — "{kod}" bekleniyor')

        log(f'[{MIGRATION_VERSION}] Doğrulamalar OK')
        log(f'[{MIGRATION_VERSION}] mehmet RolId={mehmet["RolId"]} (değişmeyecek)')

        # ── INSERT override'lar ─────────────────────────────────────
        ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        eklenen = 0
        atlanan = 0
        for yid, kod, view, manage, report in OVERRIDES:
            mevcut = con.execute(
                'SELECT Id FROM user_permission_override WHERE KullaniciId=? AND YetkiId=?',
                (MEHMET_KULLANICI_ID, yid)
            ).fetchone()
            if mevcut:
                atlanan += 1
                log(f'[{MIGRATION_VERSION}] SKIP override: {kod} (Id={mevcut["Id"]})')
                continue
            con.execute("""
                INSERT INTO user_permission_override
                    (KullaniciId, YetkiId, can_view, can_create, can_update,
                     can_delete, can_approve, can_report, can_manage,
                     aciklama, olusturma_tarih, olusturan)
                VALUES (?, ?, ?, 0, 0, 0, 0, ?, ?, ?, ?, 'migration_112')
            """, (MEHMET_KULLANICI_ID, yid, view, report, manage, ts,
                  f'Mehmet NexGen erişim override — {kod}'))
            eklenen += 1
            flags = [a for a, v in [('can_view', view), ('can_manage', manage), ('can_report', report)] if v]
            log(f'[{MIGRATION_VERSION}] INSERT override: {kod} [{", ".join(flags)}]')

        con.commit()
        log(f'[{MIGRATION_VERSION}] COMMIT OK — eklenen={eklenen} atlanan={atlanan}')

        # ── Doğrulama ────────────────────────────────────────────────
        # RolId değişmedi mi?
        mehmet_after = con.execute(
            'SELECT RolId FROM sistem_kullanici WHERE Id=?', (MEHMET_KULLANICI_ID,)
        ).fetchone()
        assert mehmet_after['RolId'] == mehmet['RolId'], 'RolId değişti — HATA'

        # 3 override var mı?
        cnt = con.execute(
            'SELECT COUNT(*) c FROM user_permission_override WHERE KullaniciId=? AND YetkiId IN (178,188,189)',
            (MEHMET_KULLANICI_ID,)
        ).fetchone()['c']
        assert cnt == 3, f'Beklenen 3 override, bulunan {cnt}'

        log(f'[{MIGRATION_VERSION}] DOĞRULAMA OK — mehmet RolId={mehmet_after["RolId"]} korundu, '
            f'override sayısı=3/3')

        # ── schema_migrations ────────────────────────────────────────
        if has_sm:
            con.execute(
                'INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)',
                (MIGRATION_VERSION,)
            )
            con.commit()
            log(f'[{MIGRATION_VERSION}] schema_migrations version={MIGRATION_VERSION} kaydedildi')

        log('=' * 70)
        log(f'[{MIGRATION_VERSION}] TAMAMLANDI')
        log('=' * 70)

    except Exception as exc:
        try:
            con.rollback()
        except Exception:
            pass
        log(f'[{MIGRATION_VERSION}] HATA: {exc}')
        raise
    finally:
        con.close()


if __name__ == '__main__':
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    run()
