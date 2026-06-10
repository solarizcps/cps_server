"""
Migration: 036_p5b_departman_hiyerarsi
Tarih: 2026-06-10
Faz: P5B — Departman Hiyerarşisi

Önceki:
  035_p5b_alt_birim_seed: departman_master'a 5 yeni alt birim eklendi (flat)

Bu migration:
  ADIM 1 — departman_master'a parent_id INT kolonu ekle (idempotent)
  ADIM 2 — "Üretim" ana departmanı ekle (parent_id=NULL, Seviye-1)
  ADIM 3 — Üretim altındaki alt birimlerin parent_id'ini set et
  ADIM 4 — Hiyerarşi doğrulama raporu

Hiyerarşi sonucu:
  Seviye-1 (parent_id=NULL):
    Yönetim, Planlama, Grafik, Muhasebe, Kalite, Çin Ofis,
    İdari İşler, Bilgi İşlem, Üretim (YENİ)

  Seviye-2 (parent_id=Üretim.id):
    EVA Enjeksiyon, Atkı, Çapak, Monta/Montaj,
    UV, Depo, Sevkiyat, Regola, Temizleme, Kesim

Notlar:
  - kullanici_profil.departman_id DEĞİŞMEZ → Seviye-2'yi gösterir
  - Seviye-3 (görev/rol): şimdilik tablo açılmıyor
    Kaynak: proses_kategori + proses_alias tabloları (mevcut, okunacak)
  - Geri alım: parent_id kolonu NULL'a çekilir, Üretim kaydı pasife alınır

Dokunulmaz:
  - ENJ schema / enj_saatlik_kayit / ENJ hesap mantığı
  - personel_kullanici schema
  - usta_personel_iliskisi
  - P5A üretim blokları (routes.py)
  - Finans / PDKS / Maliyet / Online E-Ticaret

Kullanım:
  python 036_p5b_departman_hiyerarsi.py          -> dry-run (varsayılan)
  python 036_p5b_departman_hiyerarsi.py --apply  -> gerçek uygulama (onay sonrası)
"""

import argparse
import sqlite3
import os
import sys
import io
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')

# ─── Üretim ana departmanı ───────────────────────────────────────────────────
URETIM_DEPT = {'kod': 'uretim', 'ad': 'Üretim', 'tur': 'uretim', 'aktif': 1, 'sira': 0}

# ─── Üretim altına bağlanacak alt birim kodları ──────────────────────────────
# departman_master.kod değerleri ile eşleştirilecek
URETIM_ALT_BIRIMLER = [
    'enjeksiyon',   # EVA Enjeksiyon (id=4)
    'atki',         # Atkı (id=23, 035'te eklendi)
    'capak',        # Çapak (id=24, 035'te eklendi)
    'monta',        # Montaj/Monta (id=20)
    'uv',           # UV (id=25, 035'te eklendi)
    'depo',         # Depo (id=26, 035'te eklendi)
    'sevkiyat',     # Sevkiyat (id=27, 035'te eklendi)
    'regola',       # Regola (id=19)
    'temizleme',    # Temizleme (id=21)
    'kesim',        # Kesim (id=22)
]


def get_conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=OFF")
    return con


def run(apply=False):
    mod = "APPLY" if apply else "DRY-RUN"
    print(f"\n{'='*65}")
    print(f"Migration 036 — P5B Departman Hiyerarşisi [{mod}]")
    print(f"{'='*65}")

    con = get_conn()
    now = datetime.now().isoformat(sep=' ', timespec='seconds')

    # ── ADIM 1: parent_id kolonu ekle ───────────────────────────
    print(f"\n[ADIM 1] departman_master.parent_id kolonu kontrolü")

    mevcut_kolonlar = [c[1] for c in con.execute("PRAGMA table_info(departman_master)")]
    if 'parent_id' in mevcut_kolonlar:
        print(f"  SKIP   parent_id kolonu zaten mevcut")
    else:
        if apply:
            con.execute("ALTER TABLE departman_master ADD COLUMN parent_id INTEGER DEFAULT NULL")
            con.commit()
            print(f"  ALTER  parent_id INT kolonu eklendi")
        else:
            print(f"  DRY    ALTER TABLE departman_master ADD COLUMN parent_id INT → eklenecek")

    # ── ADIM 2: Üretim ana departmanı ───────────────────────────
    print(f"\n[ADIM 2] 'Üretim' ana departmanı kontrolü")

    mevcut_uretim = con.execute(
        "SELECT id, kod, ad, aktif FROM departman_master WHERE kod=?", (URETIM_DEPT['kod'],)
    ).fetchone()

    if mevcut_uretim:
        uretim_id = mevcut_uretim['id']
        print(f"  SKIP   kod=uretim id={uretim_id} '{mevcut_uretim['ad']}' zaten mevcut (aktif={mevcut_uretim['aktif']})")
    else:
        if apply:
            con.execute(
                "INSERT INTO departman_master (kod, ad, tur, aktif, sira, created_at) VALUES (?,?,?,?,?,?)",
                (URETIM_DEPT['kod'], URETIM_DEPT['ad'], URETIM_DEPT['tur'],
                 URETIM_DEPT['aktif'], URETIM_DEPT['sira'], now)
            )
            con.commit()
            uretim_id = con.execute(
                "SELECT id FROM departman_master WHERE kod=?", (URETIM_DEPT['kod'],)
            ).fetchone()['id']
            print(f"  INSERT kod=uretim id={uretim_id} 'Üretim' oluşturuldu (parent_id=NULL, Seviye-1)")
        else:
            # Dry-run'da sanal id
            max_id = con.execute("SELECT MAX(id) mx FROM departman_master").fetchone()['mx'] or 0
            uretim_id = f"?{max_id+1}(eklenecek)"
            print(f"  DRY    kod=uretim id={uretim_id} 'Üretim' eklenecek (parent_id=NULL, Seviye-1, sira=0)")

    # ── ADIM 3: Alt birim parent_id atamaları ───────────────────
    print(f"\n[ADIM 3] Üretim alt birimlerine parent_id ataması")
    print(f"  Üretim id: {uretim_id}")
    print()

    atama_yapilan = 0
    atama_atlanan = 0
    bulunamayan   = 0

    # parent_id kolonu var mı? (dry-run'da ALTER henüz olmamış olabilir)
    kolonlar_adim3 = [c[1] for c in con.execute("PRAGMA table_info(departman_master)")]
    parent_id_var  = 'parent_id' in kolonlar_adim3

    for kod in URETIM_ALT_BIRIMLER:
        if parent_id_var:
            row = con.execute(
                "SELECT id, kod, ad, parent_id FROM departman_master WHERE kod=?", (kod,)
            ).fetchone()
        else:
            row = con.execute(
                "SELECT id, kod, ad FROM departman_master WHERE kod=?", (kod,)
            ).fetchone()

        if row is None:
            print(f"  WARN   kod={kod:<15} — departman_master'da YOK!")
            bulunamayan += 1
            continue

        rid     = row['id']
        ad      = row['ad']
        cur_pid = row['parent_id'] if parent_id_var else None

        uretim_id_int = uretim_id if isinstance(uretim_id, int) else None

        if uretim_id_int and cur_pid == uretim_id_int:
            print(f"  SKIP   id={rid:>2} kod={kod:<15} ad={ad:<15} — parent_id zaten {uretim_id_int}")
            atama_atlanan += 1
        elif cur_pid is not None and cur_pid != uretim_id_int:
            print(f"  WARN   id={rid:>2} kod={kod:<15} ad={ad:<15} — parent_id={cur_pid} (farklı, geçersiz kılınmıyor)")
            atama_atlanan += 1
        else:
            if apply and uretim_id_int:
                con.execute(
                    "UPDATE departman_master SET parent_id=? WHERE id=?",
                    (uretim_id_int, rid)
                )
                print(f"  UPDATE id={rid:>2} kod={kod:<15} ad={ad:<15} → parent_id={uretim_id_int} (Üretim)")
            else:
                print(f"  DRY    id={rid:>2} kod={kod:<15} ad={ad:<15} → parent_id={uretim_id} (Üretim)")
            atama_yapilan += 1

    if apply:
        con.commit()

    # ── ADIM 4: Hiyerarşi doğrulama ─────────────────────────────
    print(f"\n[ADIM 4] Hiyerarşi raporu (apply sonrası veya dry-run tahmini)")

    # Kolonlar kontrol (apply sonrasında parent_id var)
    kolonlar = [c[1] for c in con.execute("PRAGMA table_info(departman_master)")]
    if 'parent_id' not in kolonlar:
        print(f"  NOT: parent_id kolonu henüz yok (dry-run) — hiyerarşi gösterilemiyor")
    else:
        s1_rows = con.execute(
            "SELECT id, kod, ad, tur FROM departman_master WHERE parent_id IS NULL AND aktif=1 ORDER BY sira"
        ).fetchall()
        print(f"  Seviye-1 (parent_id=NULL): {len(s1_rows)} departman")
        for r in s1_rows:
            s2_rows = con.execute(
                "SELECT id, kod, ad FROM departman_master WHERE parent_id=? AND aktif=1 ORDER BY sira",
                (r['id'],)
            ).fetchall()
            alt_str = ', '.join(f"{x['ad']}(id={x['id']})" for x in s2_rows)
            print(f"    {r['ad']:<15} (id={r['id']:>2}, tur={r['tur']:<10}) → {len(s2_rows)} alt birim"
                  + (f": {alt_str}" if alt_str else ""))

    # ── Özet ────────────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print(f"  Mod            : {mod}")
    print(f"  parent_id kolon: {'zaten vardı' if 'parent_id' in mevcut_kolonlar else ('eklendi' if apply else 'eklenecek')}")
    print(f"  Üretim kaydı   : {'mevcuttu' if mevcut_uretim else ('oluşturuldu' if apply else 'oluşturulacak')}")
    print(f"  Alt birim güncelleme: {atama_yapilan} yapıldı / {atama_atlanan} atlandı / {bulunamayan} bulunamadı")

    if not apply:
        print(f"\n  [DRY-RUN] DB değiştirilmedi.")
        print(f"  Uygulamak için: python 036_p5b_departman_hiyerarsi.py --apply")
    else:
        print(f"\n  [APPLY] Tüm değişiklikler commit edildi.")

    con.close()
    print(f"{'='*65}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='Gerçek uygulama (default: dry-run)')
    args = parser.parse_args()
    run(apply=args.apply)
