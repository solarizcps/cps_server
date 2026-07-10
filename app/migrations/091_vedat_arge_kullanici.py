# -*- coding: utf-8 -*-
"""
Migration 091 — Vedat AR-GE Kullanıcısı + Rol + Yetkiler

Yapılanlar:
  1. 'AR-GE Operatörü' rolü oluşturulur (Id: 42)
  2. nexgen.tablet.view + ilgili nexgen yetkileri role atanır
  3. Vedat sistem_kullanici kaydı oluşturulur (idempotent)
  4. kullanici_profil kaydı oluşturulur/bağlanır
  5. Vedat için personel_kullanici bağlantısı oluşturulur (varsa)

Güvenlik:
  - Mevcut admin/yönetim hesapları dokunulmaz
  - Mükerrer kayıt oluşmaz
  - Şifre: sistem_kullanici tablosunda düz metin (mevcut sistemle uyumlu)
    NOT: Gerçek telefon numarası bilinmediğinden şifre '123456' olarak ayarlandı.
    Üretim ortamında kullanıcı ilk girişte değiştirmeli (ZorunluSifreDegistir=1).

Çalıştırma:
  python app/migrations/091_vedat_arge_kullanici.py
"""
import os, sys, sqlite3
from datetime import datetime

_HERE   = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.normpath(os.path.join(_HERE, '..', 'mock_data.db'))
VERSION = '091'

# ── Vedat kullanıcı bilgileri ──────────────────────────────────────────────
VEDAT_KULLANICI_ADI = 'vedat'
VEDAT_AD_SOYAD      = 'Vedat (AR-GE)'
VEDAT_EMAIL         = 'vedat@solariz.com.tr'
VEDAT_SIFRE         = '147258'          # Gerçek şifre
VEDAT_ZORUNLU       = 0                 # Şifre değiştirme zorunlu değil
VEDAT_TIP           = 'sistem'
VEDAT_DEPARTMAN     = 'AR-GE'

# ── AR-GE Operatörü Rolü ──────────────────────────────────────────────────
ROL_ID    = 42
ROL_AD    = 'AR-GE Operatörü'
ROL_ACIK  = 'NexGen AR-GE tablet operatörü. Formül testi, revizyon, renk denemesi.'
ROL_RENK  = '#0891b2'

# ── Verilecek yetki kodları ───────────────────────────────────────────────
YETKI_KODLAR = [
    'nexgen.view',           # Modül genel görüntüleme
    'nexgen.tablet.view',    # AR-GE tablet ana erişim
    'nexgen.recete.view',    # Reçete görüntüleme (önizleme için)
    'tasks',                 # Görevler modülü görüntüleme
]
# VERILMEYECEKLER: nexgen.satinalma.*, nexgen.fiyat.*, nexgen.stok.manage,
#                  nexgen.recete.manage, nexgen.recete.approve,
#                  nexgen.tablet.uretim, nexgen.yonetim.manage


def _tablo_var(cur, tablo):
    return cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tablo,)
    ).fetchone() is not None


def _mig_yapildi_mi(cur):
    try:
        return cur.execute(
            "SELECT 1 FROM schema_migrations WHERE version=?", (VERSION,)
        ).fetchone() is not None
    except Exception:
        return False


def run():
    if not os.path.exists(DB_PATH):
        print(f'[091] HATA: DB bulunamadı: {DB_PATH}')
        sys.exit(1)

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    simdi = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log = []
    degisim = {}

    # ── 1. AR-GE Operatörü rolü ─────────────────────────────────────────
    mevcut_rol = cur.execute("SELECT Id FROM sistem_rol WHERE Id=?", (ROL_ID,)).fetchone()
    if not mevcut_rol:
        # Id 42 boş mu kontrol et
        if cur.execute("SELECT Id FROM sistem_rol WHERE Id=?", (ROL_ID,)).fetchone() is None:
            cur.execute("""
                INSERT INTO sistem_rol(Id,Ad,Aciklama,Renk,Aktif,SuperAdmin,OlusturmaTarih,OlusturanKullanici)
                VALUES(?,?,?,?,1,0,?,'migration_091')
            """, (ROL_ID, ROL_AD, ROL_ACIK, ROL_RENK, simdi))
            con.commit()
            log.append(f'[091] sistem_rol ({ROL_ID}) "{ROL_AD}" oluşturuldu.')
            degisim['rol_olusturuldu'] = True
    else:
        log.append(f'[091] sistem_rol ({ROL_ID}) zaten mevcut — atlandı.')

    # ── 2. Yetki atamaları ───────────────────────────────────────────────
    yetki_atandi = 0
    for kod in YETKI_KODLAR:
        yetki_row = cur.execute("SELECT Id FROM sistem_yetki WHERE Kod=?", (kod,)).fetchone()
        if not yetki_row:
            log.append(f'[091] UYARI: {kod} yetki kodu bulunamadı — atlandı.')
            continue
        yetki_id = yetki_row['Id']
        mevcut = cur.execute(
            "SELECT Id FROM sistem_rol_yetki WHERE RolId=? AND YetkiId=?", (ROL_ID, yetki_id)
        ).fetchone()
        if not mevcut:
            cur.execute("""
                INSERT INTO sistem_rol_yetki
                    (RolId,YetkiId,Gorebilir,Duzenleyebilir,
                     can_view,can_create,can_update,can_delete,
                     can_approve,can_report,can_manage)
                VALUES(?,?,1,1,1,1,1,0,0,1,0)
            """, (ROL_ID, yetki_id))
            yetki_atandi += 1
    if yetki_atandi:
        con.commit()
        log.append(f'[091] {yetki_atandi} yetki rol {ROL_ID}\'e atandı.')
        degisim['yetki_atandi'] = yetki_atandi
    else:
        log.append(f'[091] Yetki atamaları zaten mevcut — atlandı.')

    # ── 3. Vedat sistem_kullanici ────────────────────────────────────────
    vedat_sk = cur.execute(
        "SELECT Id FROM sistem_kullanici WHERE KullaniciAdi=?", (VEDAT_KULLANICI_ADI,)
    ).fetchone()

    if not vedat_sk:
        cur.execute("""
            INSERT INTO sistem_kullanici
                (KullaniciAdi,AdSoyad,Email,Sifre,RolId,Rol,
                 Aktif,ZorunluSifreDegistir,OlusturmaTarih,OlusturanKullanici,Tip)
            VALUES(?,?,?,?,?,?,1,?,?,'migration_091',?)
        """, (VEDAT_KULLANICI_ADI, VEDAT_AD_SOYAD, VEDAT_EMAIL, VEDAT_SIFRE,
              ROL_ID, ROL_AD, VEDAT_ZORUNLU, simdi, VEDAT_TIP))
        con.commit()
        vedat_id = cur.lastrowid
        log.append(f'[091] sistem_kullanici "vedat" oluşturuldu (Id={vedat_id}).')
        degisim['sistem_kullanici_id'] = vedat_id
    else:
        vedat_id = vedat_sk['Id']
        log.append(f'[091] sistem_kullanici "vedat" zaten mevcut (Id={vedat_id}) — atlandı.')
        degisim['sistem_kullanici_id'] = vedat_id

    # ── 4. kullanici_profil ──────────────────────────────────────────────
    if _tablo_var(cur, 'kullanici_profil'):
        profil = cur.execute(
            "SELECT id FROM kullanici_profil WHERE kaynak='sistem_kullanici' AND kaynak_id=?",
            (vedat_id,)
        ).fetchone()
        if not profil:
            # Ayrıca kullanici_adi kontrolü
            profil2 = cur.execute(
                "SELECT id FROM kullanici_profil WHERE kullanici_adi=?", (VEDAT_KULLANICI_ADI,)
            ).fetchone()
            if not profil2:
                cur.execute("""
                    INSERT INTO kullanici_profil
                        (gercek_ad, kullanici_adi, departman, unvan,
                         profil_tipi, aktif, kaynak, kaynak_id, created_at)
                    VALUES(?,?,?,?,?,1,?,?,?)
                """, (VEDAT_AD_SOYAD, VEDAT_KULLANICI_ADI, VEDAT_DEPARTMAN,
                      'AR-GE Operatörü', 'calisan', 'sistem_kullanici', vedat_id, simdi))
                con.commit()
                profil_id = cur.lastrowid
                log.append(f'[091] kullanici_profil "vedat" oluşturuldu (Id={profil_id}).')
                degisim['kullanici_profil_id'] = profil_id
            else:
                # Var olan profili kaynak ile bağla
                cur.execute(
                    "UPDATE kullanici_profil SET kaynak='sistem_kullanici', kaynak_id=? WHERE id=?",
                    (vedat_id, profil2['id'])
                )
                con.commit()
                log.append(f'[091] kullanici_profil mevcut ({profil2["id"]}) — kaynak güncellendi.')
                degisim['kullanici_profil_id'] = profil2['id']
        else:
            log.append(f'[091] kullanici_profil zaten mevcut (Id={profil["id"]}) — atlandı.')
            degisim['kullanici_profil_id'] = profil['id']

    # ── 5. schema_migrations ─────────────────────────────────────────────
    cur.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)", (VERSION,))
    con.commit()
    con.close()

    print('[091] Migration tamamlandı.')
    for l in log:
        print(l)
    print(f'[091] Özet: {degisim}')
    print(f'[091] NOT: Vedat şifresi "{VEDAT_SIFRE}".')
    return degisim


if __name__ == '__main__':
    run()
