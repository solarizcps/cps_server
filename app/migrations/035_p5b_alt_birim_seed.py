"""
Migration: 035_p5b_alt_birim_seed
Tarih: 2026-06-10
Faz: P5B — Alt Birim / Çalışma Alanı Seed

Amaç:
  departman_master tablosuna eksik üretim alt birimlerini ekle.
  SAHA_PERSONEL profillerini üretim hareketine göre uygun departmana bağla.

ADIM 1 — departman_master: Atkı, Çapak, UV, Depo, Sevkiyat ekle (idempotent)
ADIM 2 — kullanici_profil:  Üretim hareketine göre güvenli atama yap
           - Emin olunanlar: UPDATE
           - Emin olunmayanlar: NULL bırak, açıklama raporla

Dokunulmaz:
  - ENJ Core tabloları / enj_saatlik_kayit / ENJ hesap mantığı
  - personel_kullanici schema
  - usta_personel_iliskisi
  - P5A üretim blokları (routes.py)
  - Finans / PDKS / Maliyet / Online E-Ticaret

Yöntem:
  python 035_p5b_alt_birim_seed.py          -> dry-run (varsayılan)
  python 035_p5b_alt_birim_seed.py --apply  -> gerçek uygulama (onay sonrası)

Idempotent:
  - Aynı kod varsa INSERT atlanır
  - Zaten dolu departman_id değiştirilmez
  - apply=False (dry-run) modda DB'ye dokunulmaz

Atama Kararı Gerekçesi:
  Proses kodu → birim eşleşmesi (uretim_kayit.proses_kodu bazlı):
    70-73, 60  → Atkı   (atkı silme/rivet/tampon/çapak/paket — atkı hattı)
    80-88      → EVA Enjeksiyon (gövde basım/çapak/tampon/freze — enjeksiyon ürünü)
    90         → NULL   (aşağı iş indirme — lojistik mi üretim mi belirsiz)
    Karışık    → NULL   (birden fazla hatta yakın, emin değil)
    Veri yok   → NULL   (üretim kaydı yok, atama yapılamaz)
"""

import argparse
import sqlite3
import os
import sys
import io
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'mock_data.db')


# ─── Yeni departman_master kayıtları ────────────────────────────────────────
# Mevcut en yüksek id = 22; yeni kayıtlar 23'ten devam eder (idempotent INSERT OR IGNORE)
YENI_DEPARTMANLAR = [
    {'kod': 'atki',     'ad': 'Atkı',      'tur': 'uretim', 'sira': 14},
    {'kod': 'capak',    'ad': 'Çapak',     'tur': 'uretim', 'sira': 15},
    {'kod': 'uv',       'ad': 'UV',        'tur': 'uretim', 'sira': 16},
    {'kod': 'depo',     'ad': 'Depo',      'tur': 'lojistik', 'sira': 17},
    {'kod': 'sevkiyat', 'ad': 'Sevkiyat',  'tur': 'lojistik', 'sira': 18},
]

# ─── SAHA_PERSONEL departman_id atamaları ────────────────────────────────────
# Sadece güvenilir veri olanlara atama yapılır.
# Emin olunmayanlar NULL bırakılır.
#
# Kod grupları (proses_kodu değerleri, uretim_kayit tablosundan):
#   70-73, 60   → Atkı hattı  (atkı silme, rivet, tampon, çapak, paket)
#   80-88       → EVA Enjeksiyon  (gövde basım, çapak, sayım, tampon, freze)
#   90          → BELİRSİZ  (aşağı iş indirme — mantık dışı)
#   Karışık     → NULL  (birden fazla hatta yakın)
#
# profil_id → (departman_kod, gerekçe)
ATAMALAR = {
    # Atkı grubu: dominant proses 70-73/60
    31: ('atki',           'dominant: 80:8139, 60:5392 → gövde+atkı çapak, her iki hatt güçlü — NULL'),  # karışık
    32: ('atki',           'dominant: 80:4032, 60:2360 → gövde+atkı çapak, karışık — NULL'),             # karışık
    33: ('atki',           'dominant: 80:6012, 60:3493 → gövde+atkı çapak, karışık — NULL'),             # karışık
    34: ('atki',           'dominant: 80:4953, 60:2610 → gövde+atkı çapak, karışık — NULL'),             # karışık
    35: ('atki',           'dominant: 80:6098, 60:2000 → gövde+atkı çapak, karışık — NULL'),             # karışık
    36: ('atki',           'dominant: 71:22088 → atkı rivet takıldı — Atkı kesin'),                      # Atkı ✓
    37: ('enjeksiyon',     'dominant: 90:22212, 82:10049 → aşağı iş + gövde — belirsiz'),                # belirsiz
    38: ('enjeksiyon',     'dominant: 84:600, 80:62 → gövde tampon + gövde — EVA Enjeksiyon'),           # Enjeksiyon ✓
    39: (None,             'dominant: ?:1440, 87:268 → proses bilinmiyor — NULL'),                       # NULL
    40: ('enjeksiyon',     'dominant: 85:4824 → gövde freze — EVA Enjeksiyon'),                          # Enjeksiyon ✓
    41: ('enjeksiyon',     'dominant: 82:14480, 81:14480, 80:14000 → gövde grubu — EVA Enjeksiyon'),     # Enjeksiyon ✓
    43: ('atki',           'dominant: 71:10417, 73:800 → atkı rivet + paket — Atkı; Pozisyon: KKO'),     # Atkı ✓
    44: ('atki',           'dominant: 71:1734, 86:600 → atkı rivet + gövde boy — karışık, Atkı ağır'),   # Atkı ✓ (ağır)
    45: ('atki',           'dominant: 72:50080, 73:20920, 71:10986 → atkı tampon/paket/rivet — Atkı kesin'), # Atkı ✓
    46: (None,             'dominant: 90:21600, 72:13740 → aşağı iş ağır, atkı tampon — belirsiz'),      # NULL
    47: ('atki',           'dominant: 70:46260, 71:24024, 83:8580 → atkı silme/rivet kesin — Atkı'),     # Atkı ✓
    48: ('enjeksiyon',     'dominant: 81:20075 → gövde çapak — EVA Enjeksiyon'),                         # Enjeksiyon ✓
    49: ('enjeksiyon',     'dominant: 81:8986, 80:7026 → gövde çapak + gövde basım — EVA Enjeksiyon'),   # Enjeksiyon ✓
    50: ('atki',           'dominant: 60:8240, 80:4641 → atkı çapak + gövde — karışık, atkı ağır'),      # Atkı ✓ (ağır)
    51: (None,             'dominant: 90:4700 → aşağı iş — lojistik belirsiz — NULL'),                   # NULL
    52: (None,             'üretim kaydı yok — NULL'),                                                   # NULL (çetin göler - 52)
    53: ('atki',           'dominant: 71:1440 → atkı rivet — Atkı'),                                     # Atkı ✓
    54: ('atki',           'dominant: 60:2520, 82:1440 → atkı çapak + gövde sayım — Atkı ağır'),         # Atkı ✓
}

# Gerçek onaylı atamalar (yukarıdaki yorum satırlarından çıkarılan NET liste)
# NULL olanlar veya belirsizler dışarıda bırakılır
ONAYLANAN_ATAMALAR = {
    36: 'atki',        # dominant 71 (atkı rivet) — KESİN
    38: 'enjeksiyon',  # dominant 84+80 (gövde) — KESİN
    40: 'enjeksiyon',  # dominant 85 (gövde freze) — KESİN
    41: 'enjeksiyon',  # dominant 82+81+80 (gövde) — KESİN
    43: 'atki',        # dominant 71+73 (atkı rivet+paket) — KESİN
    44: 'atki',        # dominant 71 (atkı rivet) — AĞIR
    45: 'atki',        # dominant 72+73+71 (atkı tampon/paket/rivet) — KESİN
    47: 'atki',        # dominant 70+71 (atkı silme/rivet) — KESİN
    48: 'enjeksiyon',  # dominant 81 (gövde çapak) — KESİN
    49: 'enjeksiyon',  # dominant 81+80 (gövde çapak+basım) — KESİN
    50: 'atki',        # dominant 60 (atkı çapak) — AĞIR
    53: 'atki',        # dominant 71 (atkı rivet) — KESİN
    54: 'atki',        # dominant 60+82 (atkı çapak ağır) — AĞIR
    # NULL bırakılanlar: 31,32,33,34,35 (karışık), 37,46,51 (belirsiz), 39,52 (veri yok)
}


def get_conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=OFF")  # seed sırasında FK kontrolü kapalı
    return con


def run(apply=False):
    mod = "APPLY" if apply else "DRY-RUN"
    print(f"\n{'='*65}")
    print(f"Migration 035 — P5B Alt Birim Seed [{mod}]")
    print(f"{'='*65}")

    con = get_conn()
    now = datetime.now().isoformat(sep=' ', timespec='seconds')

    # ── ADIM 1: departman_master seed ───────────────────────────
    print(f"\n[ADIM 1] departman_master — 5 yeni birim kontrolü")

    for dept in YENI_DEPARTMANLAR:
        mevcut = con.execute(
            "SELECT id, ad FROM departman_master WHERE kod=?", (dept['kod'],)
        ).fetchone()
        if mevcut:
            print(f"  SKIP   kod={dept['kod']:<10} ad={dept['ad']:<12} id={mevcut['id']} — zaten mevcut")
        else:
            if apply:
                con.execute(
                    "INSERT INTO departman_master (kod, ad, tur, aktif, sira, created_at) VALUES (?,?,?,1,?,?)",
                    (dept['kod'], dept['ad'], dept['tur'], dept['sira'], now)
                )
                yeni_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
                print(f"  INSERT kod={dept['kod']:<10} ad={dept['ad']:<12} id={yeni_id} tur={dept['tur']}")
            else:
                print(f"  DRY    kod={dept['kod']:<10} ad={dept['ad']:<12} — eklenecek (tur={dept['tur']}, sira={dept['sira']})")

    if apply:
        con.commit()

    # ── ADIM 2: departman_master güncel listesi ──────────────────
    print(f"\n[ADIM 2] departman_master güncel durum:")
    for r in con.execute("SELECT id, kod, ad, tur, aktif, sira FROM departman_master ORDER BY sira"):
        print(f"  id={r['id']:>2} kod={r['kod']:<15} ad={r['ad']:<15} tur={r['tur']:<12} aktif={r['aktif']}")

    # ── ADIM 3: SAHA_PERSONEL departman_id ataması ──────────────
    print(f"\n[ADIM 3] SAHA_PERSONEL departman_id ataması")
    print(f"  Onaylanan atama sayısı: {len(ONAYLANAN_ATAMALAR)}")
    print()

    atama_yapilan  = 0
    atama_atlanan  = 0
    null_birakilanlar = []

    # Kod → id haritası: mevcut DB + eklenecekler (dry-run'da da doğru çalışsın)
    dept_kod_id = {r['kod']: r['id']
                   for r in con.execute("SELECT id, kod FROM departman_master")}
    # Dry-run'da henüz INSERT olmayan yeni birimler için sanal id ata
    if not apply:
        sanal_id = max(dept_kod_id.values(), default=100) + 1
        for dept in YENI_DEPARTMANLAR:
            if dept['kod'] not in dept_kod_id:
                dept_kod_id[dept['kod']] = f"?{sanal_id}(eklenecek)"
                sanal_id += 1

    # Tüm SAHA profilleri raporla
    saha_profiller = con.execute("""
        SELECT id, gercek_ad, profil_tipi, departman_id
        FROM kullanici_profil
        WHERE profil_tipi IN ('SAHA_PERSONEL','SAHA_USTASI') AND aktif=1
        ORDER BY profil_tipi DESC, id
    """).fetchall()

    for p in saha_profiller:
        pid = p['id']
        hedef_kod = ONAYLANAN_ATAMALAR.get(pid)

        if hedef_kod is None:
            if p['departman_id'] is None:
                null_birakilanlar.append((pid, p['gercek_ad'], ATAMALAR.get(pid, (None, 'usta veya bilinmiyor'))[1]))
            else:
                print(f"  SKIP   id={pid:>3} {p['gercek_ad']:<25} — dept_id zaten dolu: {p['departman_id']}")
                atama_atlanan += 1
            continue

        # Hedef dept_id bul (mevcut + sanal dry-run id)
        hedef_id = dept_kod_id.get(hedef_kod)
        if hedef_id is None:
            print(f"  WARN   id={pid:>3} {p['gercek_ad']:<25} — hedef_kod={hedef_kod} haritada YOK!")
            continue

        # hedef_id apply modda int, dry-run modda "?N(eklenecek)" string olabilir
        hedef_id_int = hedef_id if isinstance(hedef_id, int) else None

        if hedef_id_int is not None and p['departman_id'] == hedef_id_int:
            print(f"  SKIP   id={pid:>3} {p['gercek_ad']:<25} — dept_id zaten {hedef_id} ({hedef_kod})")
            atama_atlanan += 1
        elif p['departman_id'] is not None:
            print(f"  WARN   id={pid:>3} {p['gercek_ad']:<25} — dept_id zaten dolu ({p['departman_id']}), geçersiz kılınmıyor")
            atama_atlanan += 1
        else:
            if apply and hedef_id_int is not None:
                con.execute(
                    "UPDATE kullanici_profil SET departman_id=?, updated_at=? WHERE id=?",
                    (hedef_id_int, now, pid)
                )
                print(f"  UPDATE id={pid:>3} {p['gercek_ad']:<25} → dept_id={hedef_id_int} ({hedef_kod})")
            else:
                print(f"  DRY    id={pid:>3} {p['gercek_ad']:<25} → dept_id={hedef_id} ({hedef_kod})")
            atama_yapilan += 1

    if apply:
        con.commit()

    # NULL bırakılanlar
    print(f"\n[ADIM 4] NULL bırakılan profiller ({len(null_birakilanlar)} adet — atama yapılmadı):")
    for pid, ad, aciklama in null_birakilanlar:
        print(f"  NULL   id={pid:>3} {ad:<25} — {aciklama[:70]}")

    # ── Özet ────────────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print(f"  Mod           : {mod}")
    print(f"  Atama yapılan : {atama_yapilan} profil")
    print(f"  Atlanan       : {atama_atlanan} (zaten dolu)")
    print(f"  NULL bırakılan: {len(null_birakilanlar)} profil")

    if not apply:
        print(f"\n  [DRY-RUN] DB değiştirilmedi.")
        print(f"  Uygulamak için: python 035_p5b_alt_birim_seed.py --apply")

    con.close()
    print(f"{'='*65}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='Gerçek uygulama (default: dry-run)')
    args = parser.parse_args()
    run(apply=args.apply)
