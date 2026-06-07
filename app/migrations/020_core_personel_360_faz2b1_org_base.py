"""
Migration: 020_core_personel_360_faz2b1_org_base
Tarih: 2026-06-07
Faz: CORE_PERSONEL_360_FAZ2B-1

Amac:
  Personel 360 organizasyon omurgasi icin minimum sozluk ve profil duzeltmesi.
  Personeli tek prosese kilitlemez; sadece guncel ana departman/profil temelidir.

Yapilacaklar:
  ADIM 1 — departman_master: Regola, Monta, Temizleme, Kesim eksikse ekle
  ADIM 2 — kullanici_profil:  Alpay profili eksikse ekle
  ADIM 3 — kullanici_profil:  Halil/Ferhat/Murat/Deniz ana departman_id guncelle

DOKUNULMAZ:
  - kullanici_proses
  - usta_personel_iliskisi
  - sistem_kullanici, sistem_rol, sistem_yetki, sistem_rol_yetki
  - ENJ_CORE tablolari
  - Finans, Planlama dosyalari
  - Template/route dosyalari
  - 11 SAHA_PERSONEL (panelden yonetilecek)
  - Halil / Halil Kirac merge yok
  - Mehmet Kesim yok

Kullanim:
  python 020_core_personel_360_faz2b1_org_base.py          -> dry-run (varsayilan)
  python 020_core_personel_360_faz2b1_org_base.py --apply  -> gercek uygulama (SADECE onay sonrasi)

Idempotent:
  Ayni script tekrar calistirilabilir; mevcut kayit varsa atlanir.

Rollback:
  Backup: C:\\CPS_BACKUPS\\mock_data_BEFORE_FAZ2B1_<timestamp>.db
  Geri yukle: yedegi app/mock_data.db uzerine kopyala.
"""

import argparse
import sqlite3
import os
import sys
import io
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')

# ─── Yeni departman tanimlari ────────────────────────────────────────────────
# Mevcut en buyuk sira=9; yeni kayitlar 10'dan baslar.
YENI_DEPARTMANLAR = [
    {'kod': 'regola',    'ad': 'Regola',    'tur': 'uretim', 'sira': 10},
    {'kod': 'monta',     'ad': 'Monta',     'tur': 'uretim', 'sira': 11},
    {'kod': 'temizleme', 'ad': 'Temizleme', 'tur': 'uretim', 'sira': 12},
    {'kod': 'kesim',     'ad': 'Kesim',     'tur': 'uretim', 'sira': 13},
]

# ─── Alpay profil bilgileri ──────────────────────────────────────────────────
ALPAY = {
    'gercek_ad':    'Alpay Dülger',
    'kullanici_adi': 'alpay',
    'profil_tipi':  'yonetim',
    'departman':    'Yönetim',
    'departman_id': 1,
    'aktif':        1,
    'kaynak':       'sistem_kullanici',
    'kaynak_id':    39,
}

# ─── Usta -> hedef departman kodu haritasi ──────────────────────────────────
# Departman ID'leri dry-run/apply aninda DB'den alinir (idempotent)
USTA_DEPT_MAP = {
    'halil':  'regola',
    'ferhat': 'enjeksiyon',
    'murat':  'monta',
    'deniz':  'temizleme',
}


# ─── Yardimci fonksiyonlar ───────────────────────────────────────────────────
def sep():
    print('─' * 60)

def h(baslik):
    print(f'\n{"="*60}')
    print(f'  {baslik}')
    print(f'{"="*60}')

def ok(msg):
    print(f'  [OK ]  {msg}')

def warn(msg):
    print(f'  [WARN] {msg}')

def dry(msg):
    print(f'  [DRY]  {msg}')

def appl(msg):
    print(f'  [APPLY]{msg}')

def skip(msg):
    print(f'  [SKIP] {msg}')


# ─── DB baglantisi ───────────────────────────────────────────────────────────
def get_conn(readonly=False):
    if readonly:
        con = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True)
    else:
        con = sqlite3.connect(DB_PATH)
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA foreign_keys=ON')
    con.row_factory = sqlite3.Row
    return con


# ─── DRY-RUN ─────────────────────────────────────────────────────────────────
def run_dryrun():
    print()
    print('╔══════════════════════════════════════════════════════╗')
    print('║   020 FAZ2B-1 ORG BASE — DRY-RUN                    ║')
    print('╚══════════════════════════════════════════════════════╝')
    print(f'  Tarih  : {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'  DB     : {DB_PATH}')
    print()

    conn = get_conn(readonly=True)

    # ── ADIM 1: Departman ──
    h('ADIM 1 — departman_master: yeni uretim departmanlari')
    dept_bulgu = {}
    for d in YENI_DEPARTMANLAR:
        row = conn.execute(
            "SELECT id, kod, ad FROM departman_master WHERE kod=?", (d['kod'],)
        ).fetchone()
        if row:
            ok(f"'{d['kod']}' zaten mevcut (id={row['id']}, ad='{row['ad']}') — ATLANACAK")
            dept_bulgu[d['kod']] = row['id']
        else:
            dry(f"'{d['kod']}' / '{d['ad']}' / tur={d['tur']} / sira={d['sira']} — EKLENECEK")
            dept_bulgu[d['kod']] = None

    # ── ADIM 2: Alpay profil ──
    h('ADIM 2 — kullanici_profil: Alpay')
    alpay_row = conn.execute(
        "SELECT id, gercek_ad, profil_tipi, departman_id FROM kullanici_profil WHERE kullanici_adi='alpay'"
    ).fetchone()
    sk_alpay = conn.execute(
        "SELECT Id, KullaniciAdi, AdSoyad FROM sistem_kullanici WHERE Id=?", (ALPAY['kaynak_id'],)
    ).fetchone()
    if not sk_alpay:
        warn(f"sistem_kullanici Id={ALPAY['kaynak_id']} BULUNAMADI — Alpay profili eklenemez")
    elif alpay_row:
        ok(f"Alpay profili zaten mevcut (KP#{alpay_row['id']}, profil_tipi={alpay_row['profil_tipi']}) — ATLANACAK")
    else:
        dry(f"Alpay profili EKLENECEK: gercek_ad='{ALPAY['gercek_ad']}', profil_tipi='{ALPAY['profil_tipi']}', dept_id={ALPAY['departman_id']}")

    # ── ADIM 3: Usta departman duzeltme ──
    h('ADIM 3 — kullanici_profil: usta ana departman guncelleme')
    for kadi, dept_kod in USTA_DEPT_MAP.items():
        kp = conn.execute(
            "SELECT id, gercek_ad, profil_tipi, departman_id FROM kullanici_profil WHERE kullanici_adi=? AND aktif=1",
            (kadi,)
        ).fetchone()
        if not kp:
            warn(f"'{kadi}' profili bulunamadi — ATLANACAK")
            continue
        hedef_dept = conn.execute(
            "SELECT id, ad FROM departman_master WHERE kod=?", (dept_kod,)
        ).fetchone()
        if not hedef_dept:
            warn(f"'{kadi}' icin hedef departman '{dept_kod}' henuz DB'de YOK — ADIM 1 sonrasi hazir olacak")
            dry(f"  -> Uygulama sirasinda: KP#{kp['id']} {kp['gercek_ad']} departman_id -> '{dept_kod}' id (ADIM 1'den alınacak)")
            continue
        if kp['departman_id'] == hedef_dept['id']:
            ok(f"KP#{kp['id']} {kp['gercek_ad']}: departman zaten '{hedef_dept['ad']}' (id={hedef_dept['id']}) — ATLANACAK")
        else:
            mevcut_dept = conn.execute(
                "SELECT ad FROM departman_master WHERE id=?", (kp['departman_id'],)
            ).fetchone()
            mevcut_ad = mevcut_dept['ad'] if mevcut_dept else f"id={kp['departman_id']}"
            dry(f"KP#{kp['id']} {kp['gercek_ad']}: departman_id {kp['departman_id']} ({mevcut_ad}) -> '{dept_kod}' ({hedef_dept['ad']}) — GUNCELLENECEK")

    # ── OZET ──
    h('DRY-RUN OZET')
    print()
    print('  === --apply ILE UYGULANACAKLAR ===')
    for d in YENI_DEPARTMANLAR:
        row = conn.execute("SELECT id FROM departman_master WHERE kod=?", (d['kod'],)).fetchone()
        if row:
            print(f'  SKIP  departman_master: {d["kod"]} zaten mevcut')
        else:
            print(f'  EKLE  departman_master: {d["kod"]} / {d["ad"]}')
    if not alpay_row:
        print(f'  EKLE  kullanici_profil: Alpay Dülger (profil_tipi=yonetim)')
    else:
        print(f'  SKIP  kullanici_profil: Alpay zaten mevcut')
    for kadi, dept_kod in USTA_DEPT_MAP.items():
        kp = conn.execute("SELECT id,gercek_ad,departman_id FROM kullanici_profil WHERE kullanici_adi=? AND aktif=1",(kadi,)).fetchone()
        hedef = conn.execute("SELECT id FROM departman_master WHERE kod=?", (dept_kod,)).fetchone()
        if not kp:
            print(f'  SKIP  {kadi}: profil yok')
        elif hedef and kp['departman_id'] == hedef['id']:
            print(f'  SKIP  KP#{kp["id"]} {kp["gercek_ad"]}: departman zaten dogru')
        else:
            print(f'  GUNC  KP#{kp["id"]} {kp["gercek_ad"]}: departman_id -> {dept_kod}')
    print()
    print('  === KESINLIKLE YAPILMAYACAKLAR ===')
    print('  - kullanici_proses: DOKUNULMAZ')
    print('  - usta_personel_iliskisi: DOKUNULMAZ')
    print('  - sistem_kullanici/rol/yetki: DOKUNULMAZ')
    print('  - 11 SAHA_PERSONEL: DOKUNULMAZ (panelden yonetilecek)')
    print('  - Halil/Halil Kirac merge: DOKUNULMAZ')
    print('  - Mehmet Kesim: DOKUNULMAZ')
    print()
    print('  Uygulamak icin: python 020_core_personel_360_faz2b1_org_base.py --apply')
    print()

    conn.close()


# ─── APPLY ───────────────────────────────────────────────────────────────────
def run_apply():
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print()
    print('╔══════════════════════════════════════════════════════╗')
    print('║   020 FAZ2B-1 ORG BASE — APPLY                      ║')
    print('╚══════════════════════════════════════════════════════╝')
    print(f'  Tarih  : {now}')
    print(f'  DB     : {DB_PATH}')
    print()

    conn = get_conn(readonly=False)
    degisen = []

    # ── ADIM 1: Departman ──
    h('[APPLY] ADIM 1 — departman_master')
    for d in YENI_DEPARTMANLAR:
        row = conn.execute("SELECT id FROM departman_master WHERE kod=?", (d['kod'],)).fetchone()
        if row:
            skip(f"'{d['kod']}' zaten mevcut (id={row['id']})")
        else:
            conn.execute(
                "INSERT INTO departman_master (kod, ad, tur, aktif, sira, created_at) VALUES (?,?,?,1,?,?)",
                (d['kod'], d['ad'], d['tur'], d['sira'], now)
            )
            yeni_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            appl(f"'{d['kod']}' / '{d['ad']}' EKLENDI (id={yeni_id})")
            degisen.append(('departman_master', yeni_id, {'kod': d['kod'], 'ad': d['ad']}))

    # ── ADIM 2: Alpay ──
    h('[APPLY] ADIM 2 — kullanici_profil: Alpay')
    sk_alpay = conn.execute("SELECT Id FROM sistem_kullanici WHERE Id=?", (ALPAY['kaynak_id'],)).fetchone()
    if not sk_alpay:
        warn(f"sistem_kullanici Id={ALPAY['kaynak_id']} BULUNAMADI — Alpay eklenmedi")
    else:
        alpay_row = conn.execute(
            "SELECT id FROM kullanici_profil WHERE kullanici_adi='alpay'"
        ).fetchone()
        if alpay_row:
            skip(f"Alpay profili zaten mevcut (KP#{alpay_row['id']})")
        else:
            conn.execute(
                """INSERT INTO kullanici_profil
                   (gercek_ad, kullanici_adi, departman, profil_tipi, departman_id,
                    aktif, kaynak, kaynak_id, created_at, updated_at)
                   VALUES (?,?,?,?,?,1,?,?,?,?)""",
                (ALPAY['gercek_ad'], ALPAY['kullanici_adi'], ALPAY['departman'],
                 ALPAY['profil_tipi'], ALPAY['departman_id'],
                 ALPAY['kaynak'], ALPAY['kaynak_id'], now, now)
            )
            yeni_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            appl(f"Alpay Dülger profili EKLENDI (KP#{yeni_id})")
            degisen.append(('kullanici_profil', yeni_id, {'kullanici_adi': 'alpay'}))

    # ── ADIM 3: Usta departman ──
    h('[APPLY] ADIM 3 — kullanici_profil: usta departman guncelleme')
    for kadi, dept_kod in USTA_DEPT_MAP.items():
        kp = conn.execute(
            "SELECT id, gercek_ad, departman_id FROM kullanici_profil WHERE kullanici_adi=? AND aktif=1",
            (kadi,)
        ).fetchone()
        if not kp:
            warn(f"'{kadi}' profili bulunamadi — atlandi")
            continue
        hedef = conn.execute("SELECT id, ad FROM departman_master WHERE kod=?", (dept_kod,)).fetchone()
        if not hedef:
            warn(f"Hedef departman '{dept_kod}' DB'de bulunamadi — '{kadi}' atlandi")
            continue
        if kp['departman_id'] == hedef['id']:
            skip(f"KP#{kp['id']} {kp['gercek_ad']}: departman zaten '{hedef['ad']}' — degisiklik yok")
        else:
            conn.execute(
                "UPDATE kullanici_profil SET departman_id=?, updated_at=? WHERE id=?",
                (hedef['id'], now, kp['id'])
            )
            appl(f"KP#{kp['id']} {kp['gercek_ad']}: departman_id {kp['departman_id']} -> {hedef['id']} ({hedef['ad']})")
            degisen.append(('kullanici_profil', kp['id'], {'departman_id': hedef['id']}))

    conn.commit()
    conn.close()

    # ── RAPOR ──
    h('APPLY SONUCU')
    print(f'  Toplam degisiklik: {len(degisen)}')
    for tablo, rid, change in degisen:
        print(f'    {tablo} id={rid} | {change}')
    print()
    print('  UYARI: kullanici_proses DOKUNULMADI')
    print('  UYARI: usta_personel_iliskisi DOKUNULMADI')
    print('  UYARI: 11 SAHA_PERSONEL DOKUNULMADI')
    print()
    return degisen


# ─── MAIN ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='020 FAZ2B-1 Org Base Migration')
    parser.add_argument('--apply', action='store_true', help='Gercek uygulama (varsayilan: dry-run)')
    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        print(f'HATA: DB bulunamadi: {DB_PATH}')
        sys.exit(1)

    if args.apply:
        run_apply()
    else:
        run_dryrun()


if __name__ == '__main__':
    main()
