"""
Migration: 018_core_personel_usta_seed
Tarih: 2026-06-06
Faz: CORE_PERSONEL_360_FAZ1_USTA_SEED

Amac:
  Mevcut CORE iliski temelini duzeltmek — sema degisikligi yok.
  Sadece veri seed / duzeltme (INSERT OR IGNORE, UPDATE sadece bos alanlarda).

Yapilacaklar:
  1. Usta profil_tipi duzeltme: 5 usta icin SAHA_USTASI standardi
  2. Usta departman_id duzeltme: Murat (uretim), Deniz (uretim), Halil dogru dept
  3. Mehmet usta kontrolu: farkli "Mehmet" profillerini raporla, usta olusmasi gerekiyorsa olustur
  4. kullanici_proses usta-proses baglantilarini tamamla (eksik olanlar)
  5. usta_personel_iliskisi onerileri: otomatik UYGULANMAZ, sadece rapor

DOKUNULMAZ:
  - ENJ Core tablolari
  - sistem_rol, sistem_yetki, sistem_rol_yetki
  - sistem_kullanici
  - Finans, Planlama dosyalari
  - Template/route dosyalari
  - Mevcut aktif kullanici_proses kayitlari (varolan silinmez)
  - Mevcut aktif usta_personel_iliskisi kayitlari (varolan silinmez)

Kullanim:
  python 018_core_personel_usta_seed.py          -> dry-run (default)
  python 018_core_personel_usta_seed.py --apply  -> gercek uygulama (sadece onay sonrasi)

Idempotent:
  Ayni script tekrar calistirilabilir, duplicate kayit olusturmaz.

Rollback:
  DB yedegi: C:\\CPS_BACKUPS\\mock_data_BEFORE_CORE_PERSONEL_360_FAZ1_USTA_SEED_20260606.db
  Geri yukle: bu db yedegini app/mock_data.db uzerine kopyala.
"""

import argparse
import sqlite3
import os
import sys
import io
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')

# ─── Usta Haritasi ──────────────────────────────────────────────────────────
# Her usta icin:
#   kullanici_adi: kullanici_profil.kullanici_adi ile eslesmesi beklenen deger
#   proses_kodu:   kullanacagi ana proses (proses_master_ref.kod)
#   departman_id:  dogru departman_master.id
#   iliski_tipi:   kullanici_proses.iliski_tipi
#
# Departman id'leri (recon'dan):
#   1=yonetim, 2=planlama, 3=grafik, 4=enjeksiyon,
#   5=muhasebe, 6=kalite, 7=cin_ofis, 8=idari, 9=sistem
#
# Proses id'leri (recon'dan):
#   1=kesim, 2=enjeksiyon, 3=monta, 4=temizleme, 5=kalite_kontrol
#   (Regola=tum regola proses grubunun sorumlusu — proses_master_ref'te "regola" yok;
#    Halil'in mevcut baglantilarinda kesim/saya/eva/mekval var. Regola = uretim genel)
#
# Ozel durum — Mehmet Kesim:
#   kullanici_profil'de "Mehmet CORABCI" planlama sorumlusu.
#   "Mehmet Usta - Kesim" farkli bir kisi olabilir.
#   Bu sebeple Mehmet_Kesim icin ayri kullanici_adi 'mehmet_kesim' kullanilacak.
#   Eger bu profil yoksa olusturulacak. Kullanici yoksa RAPORDA belirtilecek.

USTA_MAP = {
    'halil': {
        'gercek_ad':    'Halil',
        'proses_kod':   None,  # Halil zaten cok sayida proses bagli — degistirilmez
        'dept_id':      4,     # DUZELTME: Yonetim(1) yerine Enjeksiyon(4) olmali
        'dept_ad':      'Enjeksiyon',
        'proses_ekle':  [],    # Halil icin proses ekleme yok (zaten dolu)
        'iliski_tipi':  'usta',
        'aciklama':     'Regola ustasi — enjeksiyon departmani',
    },
    'ferhat': {
        'gercek_ad':    'Ferhat Usta',
        'proses_kod':   'enjeksiyon',
        'dept_id':      4,     # zaten enjeksiyon
        'dept_ad':      'Enjeksiyon',
        'proses_ekle':  [('enjeksiyon', 'usta')],
        'iliski_tipi':  'usta',
        'aciklama':     'Enjeksiyon ustasi',
    },
    'murat': {
        'gercek_ad':    'Murat',
        'proses_kod':   'monta',
        'dept_id':      4,     # DUZELTME: None -> Enjeksiyon/Uretim (en yakin uretim dept = 4)
        'dept_ad':      'Enjeksiyon',
        'proses_ekle':  [('monta', 'usta')],
        'iliski_tipi':  'usta',
        'aciklama':     'Monta ustasi',
    },
    'deniz': {
        'gercek_ad':    'Deniz',
        'proses_kod':   'temizleme',
        'dept_id':      4,     # DUZELTME: None -> Enjeksiyon/Uretim
        'dept_ad':      'Enjeksiyon',
        'proses_ekle':  [('temizleme', 'usta')],
        'iliski_tipi':  'usta',
        'aciklama':     'Temizleme ustasi',
    },
    'mehmet_kesim': {
        'gercek_ad':    'Mehmet (Kesim)',
        'proses_kod':   'kesim',
        'dept_id':      4,     # Enjeksiyon/Uretim
        'dept_ad':      'Enjeksiyon',
        'proses_ekle':  [('kesim', 'usta')],
        'iliski_tipi':  'usta',
        'aciklama':     'Kesim ustasi — ayri profil (Mehmet CORABCI ile karistirilmamali)',
    },
}

# ─── Personel → Usta oneri haritasi (sadece rapor — APPLY EDILMEZ) ────────────
USTA_PERSONEL_ONERILER = [
    # (usta_kullanici_adi, personel_profil_id, proses_kodu, not)
    # Bu liste dry-run'da raporlanir, apply modunda bile uygulanmaz.
    # Sebebi: kullanicidan onay bekleniyor.
    ('ferhat',       31, 'enjeksiyon', 'Mustafa Enes Oztürk — Ferhat/Enjeksiyon?'),
    ('ferhat',       32, 'enjeksiyon', 'Moustafa Kordy — Ferhat/Enjeksiyon?'),
    ('ferhat',       33, 'enjeksiyon', 'Badr Safa — Ferhat/Enjeksiyon?'),
    ('murat',        35, 'monta',      'Merdan Hojamkulov — Murat/Monta?'),
    ('murat',        37, 'monta',      'Aman Hudayberdiyev — Murat/Monta?'),
    ('murat',        38, 'monta',      'Mahmoud Alkhatib — Murat/Monta?'),
    ('murat',        39, 'monta',      'Alisher Gaibov — Murat/Monta?'),
    ('mehmet_kesim', 1,  'kesim',      'MANUEL KARAR: Kesim personeli bilinmiyor'),
]

SAHA_PERSONEL_DEPT_ID = 4  # Enjeksiyon — tum SAHA_PERSONEL icin ortak departman


def get_conn(read_only=False):
    if read_only:
        uri = 'file:' + os.path.abspath(DB_PATH) + '?mode=ro'
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def h(msg):
    print('\n' + '=' * 60)
    print('  ' + msg)
    print('=' * 60)


def sub(msg):
    print('  >> ' + msg)


def ok(msg):
    print('  OK  ' + msg)


def warn(msg):
    print('  WARN ' + msg)


def dry(msg):
    print('  [DRY] ' + msg)


def apply_msg(msg):
    print('  [APPLY] ' + msg)


def run_dryrun(conn):
    """Sadece rapor cikartir, hicbir veri degistirmez."""
    h('ADIM 1 — USTA PROFİL TİPİ KONTROLÜ')
    for kadi, cfg in USTA_MAP.items():
        row = conn.execute(
            "SELECT id, gercek_ad, profil_tipi, departman_id FROM kullanici_profil "
            "WHERE kullanici_adi=? AND aktif=1",
            (kadi,)
        ).fetchone()

        if not row:
            if kadi == 'mehmet_kesim':
                warn(f"'{kadi}' ({cfg['gercek_ad']}) profili BULUNAMADI — [MANUEL KARAR] Faz2'de ayri onay ile olusturulacak (bu fazda uygulanmiyor)")
            else:
                warn(f"'{kadi}' profili bulunamadi — migration sonrasi kontrol et")
            continue

        prefix = f"KP#{row['id']} {row['gercek_ad']}"
        if row['profil_tipi'] == 'SAHA_USTASI':
            ok(f"{prefix}: profil_tipi SAHA_USTASI (duzgun)")
        else:
            dry(f"{prefix}: profil_tipi '{row['profil_tipi']}' → 'SAHA_USTASI' GUNCELLENECEK")

        if row['departman_id'] == cfg['dept_id']:
            ok(f"{prefix}: departman_id={row['departman_id']} ({cfg['dept_ad']}) (duzgun)")
        elif row['departman_id'] is None:
            dry(f"{prefix}: departman_id=None → {cfg['dept_id']} ({cfg['dept_ad']}) ATANACAK")
        elif row['departman_id'] != cfg['dept_id']:
            if kadi == 'halil':
                warn(f"{prefix}: departman_id={row['departman_id']} → {cfg['dept_id']} ({cfg['dept_ad']}) "
                     f"DEGISTIRILECEK — Halil'in mevcut dept=1(Yonetim), hedef=4(Enjeksiyon). "
                     f"NOT: Halil RolId=1 ile yonetim yetkisi korunuyor, sadece profil departmani degisiyor.")
            else:
                dry(f"{prefix}: departman_id={row['departman_id']} → {cfg['dept_id']} ({cfg['dept_ad']}) GUNCELLENECEK")

    h('ADIM 2 — MEHMET KESİM KONTROL')
    mk = conn.execute(
        "SELECT id, gercek_ad, profil_tipi FROM kullanici_profil WHERE kullanici_adi='mehmet_kesim'"
    ).fetchone()
    mehmet_planlama = conn.execute(
        "SELECT id, gercek_ad, profil_tipi FROM kullanici_profil WHERE kullanici_adi='mehmet'"
    ).fetchone()
    if mk:
        ok(f"mehmet_kesim profili mevcut: KP#{mk['id']} {mk['gercek_ad']} ({mk['profil_tipi']})")
    else:
        warn("mehmet_kesim profili YOK — [MANUEL KARAR] Faz2'de ayri onay ile olusturulacak (bu fazda UYGULANMIYOR)")
    if mehmet_planlama:
        sub(f"NOT: 'mehmet' (KP#{mehmet_planlama['id']} — {mehmet_planlama['gercek_ad']}) planlama sorumlsudur, dokunulmayacak.")

    h('ADIM 3 — kullanici_proses USTA-PROSES BAGLANTILARI')
    for kadi, cfg in USTA_MAP.items():
        if not cfg['proses_ekle']:
            sub(f"{kadi}: proses degisikligi yok (mevcut baglantilar korunuyor)")
            continue

        row = conn.execute(
            "SELECT id FROM kullanici_profil WHERE kullanici_adi=? AND aktif=1", (kadi,)
        ).fetchone()
        profil_id = row['id'] if row else None

        for proses_kod, iliski_tipi in cfg['proses_ekle']:
            pm = conn.execute(
                "SELECT id FROM proses_master_ref WHERE kod=?", (proses_kod,)
            ).fetchone()
            if not pm:
                warn(f"proses_master_ref: kod='{proses_kod}' BULUNAMADI")
                continue
            proses_id = pm['id']

            if profil_id:
                # run_apply ile ayni kontrol: sadece 'usta' tipini ara
                mevcut_usta = conn.execute(
                    "SELECT id FROM kullanici_proses "
                    "WHERE kullanici_profil_id=? AND proses_id=? AND iliski_tipi='usta' AND aktif=1",
                    (profil_id, proses_id)
                ).fetchone()
                if mevcut_usta:
                    ok(f"{kadi} KP#{profil_id} — {proses_kod}/usta zaten bagli (KP_proses#{mevcut_usta['id']})")
                else:
                    # calisan tipi kayit var mi kontrol et, varsa bunu da belirt
                    mevcut_diger = conn.execute(
                        "SELECT id, iliski_tipi FROM kullanici_proses "
                        "WHERE kullanici_profil_id=? AND proses_id=? AND aktif=1",
                        (profil_id, proses_id)
                    ).fetchone()
                    if mevcut_diger:
                        dry(f"{kadi} KP#{profil_id} — {proses_kod}/usta EKLENECEK "
                            f"(mevcut {mevcut_diger['iliski_tipi']} kaydi korunur, dokunulmaz)")
                    else:
                        dry(f"{kadi} KP#{profil_id} — {proses_kod}/usta EKLENECEK")
            else:
                if kadi == 'mehmet_kesim':
                    dry(f"mehmet_kesim profil olusturulduktan sonra kesim prosesi baglanacak")
                else:
                    warn(f"{kadi} profili bulunamadi — proses baglantisi yapilamaz")

    h('ADIM 4 — SAHA_PERSONEL departman_id DURUMU')
    eksik = conn.execute(
        "SELECT id, gercek_ad FROM kullanici_profil "
        "WHERE profil_tipi='SAHA_PERSONEL' AND (departman_id IS NULL) AND aktif=1"
    ).fetchall()
    if eksik:
        warn(f"{len(eksik)} SAHA_PERSONEL profilinde departman_id=None — [MANUEL KARAR] Faz2'de onaylanmis liste ile uygulanacak:")
        for r in eksik:
            warn(f"  KP#{r['id']} {r['gercek_ad']}")
    else:
        ok("Tum SAHA_PERSONEL kayitlarinda departman_id dolu")

    h('ADIM 5 — USTA-PERSONEL BAĞLANTISI ÖNERİLERİ (OTOMATIK UYGULANMAZ)')
    print()
    print('  Bu listede belirtilen baglantilar DRY-RUN veya APPLY modunda UYGULANMAZ.')
    print('  Kullanicidan manuel onay bekleniyor.')
    print()
    for kadi, personel_pid, proses_kodu, not_ in USTA_PERSONEL_ONERILER:
        usta_row = conn.execute(
            "SELECT id, gercek_ad FROM kullanici_profil WHERE kullanici_adi=? AND aktif=1", (kadi,)
        ).fetchone()
        p_row = conn.execute(
            "SELECT id, gercek_ad FROM kullanici_profil WHERE id=? AND aktif=1", (personel_pid,)
        ).fetchone()

        usta_str = f"KP#{usta_row['id']} {usta_row['gercek_ad']}" if usta_row else f"'{kadi}' (profil YOK)"
        p_str = f"KP#{p_row['id']} {p_row['gercek_ad']}" if p_row else f"id={personel_pid} (bulunamadi)"

        mevcut_iliski = None
        if usta_row and p_row:
            mevcut_iliski = conn.execute(
                "SELECT id FROM usta_personel_iliskisi "
                "WHERE usta_profil_id=? AND personel_profil_id=? AND aktif=1",
                (usta_row['id'], p_row['id'])
            ).fetchone()

        durum = "✓ MEVCUT" if mevcut_iliski else "? ONAY BEKLIYOR"
        print(f"  {durum}  Usta: {usta_str}  →  Personel: {p_str}  (proses: {proses_kodu})")
        print(f"           Not: {not_}")

    h('DRY-RUN ÖZET')
    print()
    print('  === --apply ILE UYGULANACAKLAR ===')
    print('  Guncellencek dept_id   : Murat (None→4), Deniz (None→4)')
    print('  Eklenecek kullanici_proses (iliski_tipi=usta, sadece eksikler):')
    print('    - Ferhat  → enjeksiyon/usta')
    print('    - Murat   → monta/usta')
    print('    - Deniz   → temizleme/usta')
    print()
    print('  === MANUEL KARAR BEKLIYOR (bu fazda UYGULANMIYOR) ===')
    print('  - Halil departman_id 1(Yonetim)→4(Enjeksiyon)  : ayri onay gerekli')
    print('  - mehmet_kesim profil olusturma                 : Faz2 ile')
    print('  - 11 SAHA_PERSONEL dept_id atamasi              : Faz2 kisi bazli onay ile')
    print('  - usta_personel_iliskisi onerileri (Adim 5)     : ayri onay gerekli')
    print()
    print('  Uygulamak icin: python 018_core_personel_usta_seed.py --apply')
    print()


def run_apply(conn):
    """Gercek veri degisikliklerini uygular. Sadece --apply ile calisir."""
    degisen = []
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    h('[APPLY] ADIM 1 — USTA PROFİL TİPİ VE DEPARTMAN DUZELTME')
    for kadi, cfg in USTA_MAP.items():
        if kadi == 'mehmet_kesim':
            continue  # adim 2'de ele aliniyor
        row = conn.execute(
            "SELECT id, gercek_ad, profil_tipi, departman_id FROM kullanici_profil "
            "WHERE kullanici_adi=? AND aktif=1", (kadi,)
        ).fetchone()
        if not row:
            warn(f"'{kadi}' profili bulunamadi, atlandi")
            continue
        pid = row['id']
        updates = {}
        if row['profil_tipi'] != 'SAHA_USTASI':
            updates['profil_tipi'] = 'SAHA_USTASI'
        if kadi != 'halil' and row['departman_id'] != cfg['dept_id']:
            updates['departman_id'] = cfg['dept_id']
        if kadi == 'halil' and row['departman_id'] != cfg['dept_id']:
            warn(f"KP#{pid} Halil: departman_id={row['departman_id']} → {cfg['dept_id']} degisimi UYGULANMADI (manuel karar bekliyor)")
        if updates:
            set_clause = ', '.join(f"{k}=?" for k in updates)
            vals = list(updates.values()) + [now, pid]
            conn.execute(f"UPDATE kullanici_profil SET {set_clause}, updated_at=? WHERE id=?", vals)
            apply_msg(f"KP#{pid} {row['gercek_ad']}: {updates}")
            degisen.append(('kullanici_profil', pid, updates))
        else:
            ok(f"KP#{pid} {row['gercek_ad']}: degisiklik yok")

    h('[APPLY] ADIM 2 — MEHMET KESİM PROFİLİ')
    # Bu fazda mehmet_kesim profili OLUSTURULMUYOR — manuel karar bekliyor.
    mk = conn.execute(
        "SELECT id FROM kullanici_profil WHERE kullanici_adi='mehmet_kesim'"
    ).fetchone()
    if mk:
        ok(f"mehmet_kesim KP#{mk['id']} zaten mevcut")
        mk_id = mk['id']
    else:
        warn("mehmet_kesim profili YOK — Faz2'de ayri onay ile olusturulacak (bu fazda UYGULANMIYOR)")
        mk_id = None

    h('[APPLY] ADIM 3 — kullanici_proses BAGLANTILAR')
    for kadi, cfg in USTA_MAP.items():
        if not cfg.get('proses_ekle'):
            continue
        if kadi == 'mehmet_kesim':
            # Bu fazda mehmet_kesim tamamen apply disi — profil mevcut olsa bile
            warn("mehmet_kesim bu fazda tamamen apply disi — Faz2'de ayri onay ile yapilacak")
            continue
        else:
            row = conn.execute(
                "SELECT id FROM kullanici_profil WHERE kullanici_adi=? AND aktif=1", (kadi,)
            ).fetchone()
        if not row:
            warn(f"{kadi} profili hala bulunamadi")
            continue
        profil_id = row['id']

        for proses_kod, iliski_tipi in cfg['proses_ekle']:
            pm = conn.execute("SELECT id FROM proses_master_ref WHERE kod=?", (proses_kod,)).fetchone()
            if not pm:
                warn(f"proses_master_ref.kod='{proses_kod}' bulunamadi")
                continue
            proses_id = pm['id']
            # iliski_tipi='usta' kontrolu: calisan tipi varsa bile ayri usta kaydi eklenir
            mevcut_usta = conn.execute(
                "SELECT id FROM kullanici_proses "
                "WHERE kullanici_profil_id=? AND proses_id=? AND iliski_tipi='usta' AND aktif=1",
                (profil_id, proses_id)
            ).fetchone()
            if mevcut_usta:
                ok(f"KP#{profil_id} {kadi} — {proses_kod}/usta zaten bagli (id:{mevcut_usta['id']})")
            else:
                conn.execute(
                    "INSERT INTO kullanici_proses (kullanici_profil_id, proses_id, iliski_tipi, kaynak, aktif, created_at) "
                    "VALUES (?, ?, ?, '018_seed', 1, ?)",
                    (profil_id, proses_id, iliski_tipi, now)
                )
                yeni_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                apply_msg(f"KP#{profil_id} {kadi} — {proses_kod}/usta BAGLANDI (kullanici_proses#{yeni_id})")
                degisen.append(('kullanici_proses', yeni_id, {'profil_id': profil_id, 'proses_kod': proses_kod}))

    h('[APPLY] ADIM 4 — SAHA_PERSONEL departman_id')
    # Bu fazda toplu atama UYGULANMIYOR — Faz2'de kisi bazli onay ile yapilacak.
    eksik_say = conn.execute(
        "SELECT count(*) FROM kullanici_profil "
        "WHERE profil_tipi='SAHA_PERSONEL' AND departman_id IS NULL AND aktif=1"
    ).fetchone()[0]
    if eksik_say:
        warn(f"{eksik_say} SAHA_PERSONEL profilinde departman_id=None — Faz2'de manuel onay ile atanacak (bu fazda UYGULANMIYOR)")
    else:
        ok("Tum SAHA_PERSONEL kayitlarinda departman_id dolu")

    h('[APPLY] ÖZET')
    print(f"  Toplam degisen/eklenen kayit: {len(degisen)}")
    for tablo, rid, change in degisen:
        print(f"    {tablo} id={rid} | {change}")
    print()
    print('  UYARI: usta_personel_iliskisi onerileri UYGULANMADI (manuel onay gerekli)')
    print()
    return degisen


def main():
    parser = argparse.ArgumentParser(description='018 CORE_PERSONEL_360_FAZ1_USTA_SEED')
    parser.add_argument('--apply', action='store_true',
                        help='Gercek degisiklikleri uygula (default: dry-run)')
    args = parser.parse_args()

    print()
    print('╔' + '═' * 58 + '╗')
    print('║   018 — CORE_PERSONEL_360_FAZ1_USTA_SEED' + ' ' * 17 + '║')
    print(f'║   Mod: {"APPLY" if args.apply else "DRY-RUN (degisiklik YOK)"}' + ' ' * (51 - len('APPLY' if args.apply else 'DRY-RUN (degisiklik YOK)')) + '║')
    print(f'║   Tarih: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}' + ' ' * 20 + '║')
    print('╚' + '═' * 58 + '╝')
    print()

    if not os.path.exists(DB_PATH):
        print(f'HATA: DB bulunamadi: {DB_PATH}')
        sys.exit(1)

    if args.apply:
        conn = get_conn(read_only=False)
        try:
            run_dryrun(conn)
            h('[APPLY] MODU AKTIF — Degisiklikler uygulanıyor...')
            run_apply(conn)
            conn.commit()
            print()
            print('  COMMIT OK — Tum degisiklikler DB ye yazildi.')
            print()
        except Exception as e:
            conn.rollback()
            print(f'\n  HATA — ROLLBACK yapildi: {e}')
            sys.exit(1)
        finally:
            conn.close()
    else:
        conn = get_conn(read_only=True)
        try:
            run_dryrun(conn)
        finally:
            conn.close()


if __name__ == '__main__':
    main()
