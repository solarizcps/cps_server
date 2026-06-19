# -*- coding: utf-8 -*-
"""
FAZ-6B: PDKS 2025 Tarihsel Aktarim Scripti
===========================================

KULLANIM:
  python app/scripts/pdks_2025_sync.py --year 2025 --dry-run
  python app/scripts/pdks_2025_sync.py --year 2025 --apply

KURALLAR:
  - PDKS tarafi sadece SELECT.
  - CPS'e sadece personel_devam ve personel_izin yazilir.
  - Hedef modulu KESINLIKLE DOKUNULMAZ.
  - mock_data.db commitlenmeyecek.
  - Idempotent: ayni (kullanici_profil_id, tarih, kaynak='pdks') tekrar yazilmaz.
  - Mukerrer gunler (ayni pdks_id+tarih birden fazla PDKS satiri) SKIP edilir.
  - Var olan CPS kaydi UPDATE/DELETE edilmez.

KARARLAR:
  - pk_id eksik profiller aktarilir; personel_pk_id=NULL olabilir.
  - pts_izin izintipi='gunluk' -> CPS 'yillik'; kaynak_not alana yazilir.
  - Mukerrer gunler skip + raporda listelenir.
"""

import sys
import io
import os
import sqlite3
import datetime
import argparse
import shutil

# Windows encoding
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Yol ayarlari: script app/scripts/ altinda, cps root'u iki ust dizin
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_APP_DIR    = os.path.dirname(_SCRIPT_DIR)
_ROOT_DIR   = os.path.dirname(_APP_DIR)

sys.path.insert(0, _APP_DIR)
os.chdir(_APP_DIR)

CPS_DB_PATH  = os.path.join(_APP_DIR, 'mock_data.db')
BACKUP_DIR   = os.path.join(_ROOT_DIR, '_backups')

# ── Sabitler ─────────────────────────────────────────────────────────────────
GEC_ESIGI_SN = 7 * 3600   # 07:00

IZIN_TIP_MAP = {
    'gunluk'    : 'yillik',
    'yillik'    : 'yillik',
    'ucretsiz'  : 'ucretsiz',
    'dogum'     : 'dogum',
    'olum'      : 'olum',
    'hastalik'  : 'hastalik',
    'resmi'     : 'resmi_tatil',
    'resmi_tatil':'resmi_tatil',
    '0'         : 'yillik',
    '1'         : 'yillik',
    '2'         : 'ucretsiz',
    '3'         : 'dogum',
    '4'         : 'olum',
    '5'         : 'hastalik',
    '6'         : 'resmi_tatil',
}

GIREN_KUL = 'pdks_faz6b'


# ── Yardimci ─────────────────────────────────────────────────────────────────

def _sn(td):
    if td is None:
        return None
    return int(td.total_seconds()) if isinstance(td, datetime.timedelta) else int(td)


def _hhmm(td):
    s = _sn(td)
    return None if s is None else f"{s // 3600:02d}:{(s % 3600) // 60:02d}"


def _durum(giris, cikis, izintipi):
    if izintipi is not None and str(izintipi).strip() not in ('0', '', 'None', 'null'):
        return 'izinli'
    s = _sn(giris)
    if s is None:
        return 'gelmedi'
    return 'gec_giris' if s > GEC_ESIGI_SN else 'geldi'


def _dakika(giris, cikis):
    g, c = _sn(giris), _sn(cikis)
    if g is None or c is None:
        return None
    dk = (c - g) // 60
    return dk if dk >= 0 else None


def _iztip(pdks_tip):
    if pdks_tip is None:
        return 'yillik'
    k = str(pdks_tip).strip().lower()
    return IZIN_TIP_MAP.get(k, 'yillik')


def _gun_sayisi(bas, bit, pdks_sure):
    if pdks_sure is not None:
        try:
            return float(pdks_sure)
        except (ValueError, TypeError):
            pass
    if bas and bit:
        try:
            if isinstance(bas, str):
                bas = datetime.date.fromisoformat(bas[:10])
            if isinstance(bit, str):
                bit = datetime.date.fromisoformat(bit[:10])
            return float((bit - bas).days + 1)
        except Exception:
            pass
    return None


# ── Backup ───────────────────────────────────────────────────────────────────

def backup():
    ts  = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    dst = os.path.join(BACKUP_DIR, f'faz6b_{ts}')
    os.makedirs(dst, exist_ok=True)

    kaynak_dosyalar = {
        'mock_data.db'   : CPS_DB_PATH,
        'pdks.py'        : os.path.join(_APP_DIR, 'modules', 'common', 'pdks.py'),
        'yonetim_routes.py': os.path.join(_APP_DIR, 'modules', 'yonetim', 'routes.py'),
    }
    for hedef_ad, src in kaynak_dosyalar.items():
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(dst, hedef_ad))
            sz = os.path.getsize(src)
            print(f"  [BACKUP] {hedef_ad} --> {dst}  ({sz // 1024} KB)")
        else:
            print(f"  [UYARI] Kaynak bulunamadi: {src}")

    print(f"  [BACKUP TAMAM] {dst}")
    return dst


# ── Baglanti ─────────────────────────────────────────────────────────────────

def cps_baglan():
    if not os.path.exists(CPS_DB_PATH):
        raise FileNotFoundError(f"CPS DB bulunamadi: {CPS_DB_PATH}")
    con = sqlite3.connect(CPS_DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def pdks_baglan():
    try:
        import pymysql
        import pymysql.cursors
    except ImportError:
        raise ImportError("pymysql yuklu degil: pip install pymysql")
    from modules.common.pdks import (PDKS_HOST, PDKS_PORT, PDKS_DATABASE,
                                     PDKS_USER, PDKS_PASSWORD, PDKS_CHARSET,
                                     PDKS_TIMEOUT)
    return pymysql.connect(
        host=PDKS_HOST, port=PDKS_PORT, database=PDKS_DATABASE,
        user=PDKS_USER, password=PDKS_PASSWORD,
        charset=PDKS_CHARSET, connect_timeout=PDKS_TIMEOUT,
        cursorclass=pymysql.cursors.DictCursor,
    )


# ── Eslesmis personel listesi ─────────────────────────────────────────────────

def eslesik_personel_al(db):
    """pdks_personel_id dolu, aktif profiller.
    pk_id: personel_kullanici.id (NULL olabilir -- FAZ-6B kararı: yazilacak)
    """
    rows = db.execute("""
        SELECT kp.id               AS profil_id,
               kp.gercek_ad,
               kp.pdks_personel_id,
               pk.id               AS pk_id
        FROM   kullanici_profil kp
        LEFT JOIN personel_kullanici pk
               ON kp.kaynak = 'personel_kullanici' AND kp.kaynak_id = pk.id
        WHERE  kp.pdks_personel_id IS NOT NULL
          AND  kp.aktif = 1
        ORDER  BY kp.id
    """).fetchall()

    eslesik = {}   # pdks_id -> {profil_id, pk_id, ad}
    for r in rows:
        pdks_id = int(r['pdks_personel_id'])
        pk_id   = r['pk_id']
        if pk_id is None:
            # Eski kopru: PdksPersonelId kolonu
            alt = db.execute(
                "SELECT id FROM personel_kullanici WHERE PdksPersonelId=? LIMIT 1",
                (pdks_id,)
            ).fetchone()
            pk_id = alt['id'] if alt else None
        eslesik[pdks_id] = {
            'profil_id': r['profil_id'],
            'pk_id'    : pk_id,
            'ad'       : r['gercek_ad'],
        }
    return eslesik


# ── PDKS veri cekme ───────────────────────────────────────────────────────────

def pdks_giris_cikis_al(pdks, pdks_id_listesi, tarih_bas, tarih_bit):
    ph = ','.join(['%s'] * len(pdks_id_listesi))
    with pdks.cursor() as cur:
        cur.execute(f"""
            SELECT personelid, giristarihi, girissaati, cikissaati, izintipi, aciklama
            FROM pts_giriscikis
            WHERE personelid IN ({ph})
              AND giristarihi >= %s AND giristarihi <= %s
            ORDER BY personelid, giristarihi
        """, pdks_id_listesi + [tarih_bas, tarih_bit])
        return cur.fetchall()


def pdks_izin_al(pdks, pdks_id_listesi, tarih_bas, tarih_bit):
    ph = ','.join(['%s'] * len(pdks_id_listesi))
    try:
        with pdks.cursor() as cur:
            cur.execute(f"""
                SELECT personelid, giristarihi, cikistarihi, izintipi, izinsure, aciklama
                FROM pts_izin
                WHERE personelid IN ({ph})
                  AND giristarihi >= %s AND giristarihi <= %s
                ORDER BY personelid, giristarihi
            """, pdks_id_listesi + [tarih_bas, tarih_bit])
            return cur.fetchall()
    except Exception as e:
        print(f"  [UYARI] pts_izin sorgusu hatasi: {e}")
        return []


# ── Mukerrer tespiti ──────────────────────────────────────────────────────────

def mukerrer_anahtarlari_bul(gc_rows):
    """pdks_id + tarih cifti birden fazla satira sahipse mukerrer say."""
    sayac = {}
    for r in gc_rows:
        k = (r['personelid'], str(r['giristarihi']))
        sayac[k] = sayac.get(k, 0) + 1
    return {k for k, v in sayac.items() if v > 1}


# ── Mevcut CPS kayitlari ──────────────────────────────────────────────────────

def mevcut_devam_seti(db, profil_id_listesi):
    """(kullanici_profil_id, tarih) seti -- mevcut personel_devam."""
    if not profil_id_listesi:
        return set()
    ph = ','.join(['?'] * len(profil_id_listesi))
    rows = db.execute(f"""
        SELECT kullanici_profil_id, tarih FROM personel_devam
        WHERE  kullanici_profil_id IN ({ph})
    """, profil_id_listesi).fetchall()
    return {(r[0], str(r[1])) for r in rows}


def mevcut_izin_seti(db, profil_id_listesi):
    """(kullanici_profil_id, baslangic_tarihi, bitis_tarihi) seti."""
    if not profil_id_listesi:
        return set()
    ph = ','.join(['?'] * len(profil_id_listesi))
    rows = db.execute(f"""
        SELECT kullanici_profil_id, baslangic_tarihi, bitis_tarihi FROM personel_izin
        WHERE  kullanici_profil_id IN ({ph})
    """, profil_id_listesi).fetchall()
    return {(r[0], str(r[1]), str(r[2])) for r in rows}


# ── Satir donusum ─────────────────────────────────────────────────────────────

def gc_row_to_devam(r, profil_id, pk_id):
    """pts_giriscikis satiri -> personel_devam INSERT tuple."""
    tarih   = str(r['giristarihi'])
    giris   = _hhmm(r.get('girissaati'))
    cikis   = _hhmm(r.get('cikissaati'))
    durum   = _durum(r.get('girissaati'), r.get('cikissaati'), r.get('izintipi'))
    cal_dk  = _dakika(r.get('girissaati'), r.get('cikissaati'))
    aciklama = r.get('aciklama') or None

    return (
        pk_id,           # personel_pk_id   (NULL olabilir)
        profil_id,       # kullanici_profil_id
        tarih,           # tarih
        durum,           # durum
        giris,           # giris_saati
        cikis,           # cikis_saati
        cal_dk,          # calisma_dakika
        'pdks',          # kaynak
        aciklama,        # aciklama
        GIREN_KUL,       # giren_kullanici
    )


def izin_row_to_izin(r, profil_id, pk_id):
    """pts_izin satiri -> personel_izin INSERT tuple."""
    bas  = str(r.get('giristarihi') or '')
    bit  = str(r.get('cikistarihi') or '')
    yil  = int(str(r.get('giristarihi') or '2025')[:4])
    tip  = _iztip(r.get('izintipi'))
    gun  = _gun_sayisi(r.get('giristarihi'), r.get('cikistarihi'), r.get('izinsure'))

    # Kaynak izintipi + aciklama notlarda korunuyor
    pdks_not = f"pdks_izintipi={r.get('izintipi')}"
    aciklama = r.get('aciklama') or None
    notlar   = (pdks_not + ('  ' + aciklama if aciklama else '')).strip()

    return (
        pk_id,           # personel_pk_id   (NULL olabilir)
        profil_id,       # kullanici_profil_id
        yil,             # yil
        14.0,            # hak_gun   (varsayilan -- PDKS'te yok)
        gun or 1.0,      # kullanilan_gun
        tip,             # izin_tipi
        bas,             # baslangic_tarihi
        bit,             # bitis_tarihi
        gun,             # gun_sayisi
        'onaylandi',     # durum   (PDKS'te kayitliysa onaylandi kabul)
        notlar,          # notlar
        GIREN_KUL,       # giren_kullanici
    )


# ── Ana akis ──────────────────────────────────────────────────────────────────

def run(year: int, dry_run: bool):
    tarih_bas = datetime.date(year, 1, 1)
    tarih_bit = datetime.date(year, 12, 31)

    mod = "DRY-RUN" if dry_run else "APPLY"
    print("=" * 65)
    print(f"FAZ-6B PDKS TARIHSEL AKTARIM  --  {mod}")
    print(f"Yil: {year}  |  {tarih_bas} --> {tarih_bit}")
    if dry_run:
        print("DB'ye HICBIR SEY YAZILMAYACAK.")
    else:
        print("GERCEK YAZMA YAPILACAK. Idempotent.")
    print("=" * 65)

    # ── Backup (sadece --apply modunda) ──────────────────────────────────────
    if not dry_run:
        print("\n[BACKUP]")
        backup()

    # ── Baglantilar ───────────────────────────────────────────────────────────
    db   = cps_baglan()
    try:
        pdks = pdks_baglan()
    except Exception as e:
        print(f"\n[HATA] PDKS: {e}")
        db.close()
        return
    print("[PDKS] Baglanti OK")

    try:
        _run_sync(db, pdks, tarih_bas, tarih_bit, dry_run)
    except Exception as e:
        import traceback
        print(f"\n[HATA] {e}")
        traceback.print_exc()
    finally:
        try:
            pdks.close()
        except Exception:
            pass
        db.close()


def _run_sync(db, pdks, tarih_bas, tarih_bit, dry_run):
    SEP = "-" * 65

    # ── Eslesmis personel ─────────────────────────────────────────────────────
    print(f"\n{SEP}\nEslesmis personel aliniyor...\n{SEP}")
    eslesik = eslesik_personel_al(db)
    pids    = list(eslesik.keys())
    print(f"  Toplam eslesik profil : {len(eslesik)}")
    pk_eksik_cnt = sum(1 for v in eslesik.values() if v['pk_id'] is None)
    print(f"  pk_id bulunan         : {len(eslesik) - pk_eksik_cnt}")
    print(f"  pk_id eksik (NULL ok) : {pk_eksik_cnt}")

    if not pids:
        print("  [UYARI] Eslesik personel yok. Cikiliyor.")
        return

    profil_ids = [v['profil_id'] for v in eslesik.values()]

    # ── PDKS verisi cek ───────────────────────────────────────────────────────
    print(f"\n{SEP}\nPDKS veri cekiliyor...\n{SEP}")
    gc_rows   = pdks_giris_cikis_al(pdks, pids, tarih_bas, tarih_bit)
    izin_rows = pdks_izin_al(pdks, pids, tarih_bas, tarih_bit)
    print(f"  pts_giriscikis satir  : {len(gc_rows)}")
    print(f"  pts_izin satir        : {len(izin_rows)}")

    # ── Mukerrer tespiti ──────────────────────────────────────────────────────
    mukerrer = mukerrer_anahtarlari_bul(gc_rows)
    print(f"  Mukerrer gun cifti    : {len(mukerrer)}")
    if mukerrer:
        print(f"  [MUKERRER LISTE]")
        for (pid, tarih) in sorted(mukerrer):
            ad = eslesik.get(pid, {}).get('ad', '?')
            print(f"    pdks_id={pid} '{ad}' tarih={tarih}")

    # ── Mevcut CPS seti ───────────────────────────────────────────────────────
    mev_dev = mevcut_devam_seti(db, profil_ids)
    mev_iz  = mevcut_izin_seti(db, profil_ids)
    print(f"\n  Mevcut CPS devam kayit: {len(mev_dev)}")
    print(f"  Mevcut CPS izin kayit : {len(mev_iz)}")

    # ── personel_devam hazirla ────────────────────────────────────────────────
    print(f"\n{SEP}\npersonel_devam hazirlanıyor...\n{SEP}")

    devam_yazilacak  = []   # INSERT edilecek tuple listesi
    devam_skip_cak   = 0    # mevcut CPS kaydı var, skip
    devam_skip_muk   = 0    # mukerrer gun, skip
    devam_skip_profil = 0   # profil_id yok

    for r in gc_rows:
        inf = eslesik.get(r['personelid'])
        if not inf or not inf.get('profil_id'):
            devam_skip_profil += 1
            continue

        tarih_str = str(r['giristarihi'])
        pdks_key  = (r['personelid'], tarih_str)

        # Mukerrer kontrol
        if pdks_key in mukerrer:
            devam_skip_muk += 1
            continue

        # Idempotent: CPS'te zaten var mi?
        cps_key = (inf['profil_id'], tarih_str)
        if cps_key in mev_dev:
            devam_skip_cak += 1
            continue

        devam_yazilacak.append(gc_row_to_devam(r, inf['profil_id'], inf['pk_id']))

    print(f"  Yazilacak             : {len(devam_yazilacak)}")
    print(f"  Skip (mevcut CPS)     : {devam_skip_cak}")
    print(f"  Skip (mukerrer)       : {devam_skip_muk}")
    print(f"  Skip (profil_id yok)  : {devam_skip_profil}")

    # ── personel_izin hazirla ─────────────────────────────────────────────────
    print(f"\n{SEP}\npersonel_izin hazirlanıyor...\n{SEP}")

    izin_yazilacak  = []
    izin_skip_cak   = 0
    izin_skip_profil = 0

    for r in izin_rows:
        inf = eslesik.get(r['personelid'])
        if not inf or not inf.get('profil_id'):
            izin_skip_profil += 1
            continue

        bas_str = str(r.get('giristarihi') or '')
        bit_str = str(r.get('cikistarihi') or '')
        cps_key = (inf['profil_id'], bas_str, bit_str)

        if cps_key in mev_iz:
            izin_skip_cak += 1
            continue

        izin_yazilacak.append(izin_row_to_izin(r, inf['profil_id'], inf['pk_id']))

    print(f"  Yazilacak             : {len(izin_yazilacak)}")
    print(f"  Skip (mevcut CPS)     : {izin_skip_cak}")
    print(f"  Skip (profil_id yok)  : {izin_skip_profil}")

    # ── DRY-RUN cikisi ────────────────────────────────────────────────────────
    if dry_run:
        print(f"\n{'=' * 65}")
        print("DRY-RUN OZET -- DB'ye HICBIR SEY YAZILMADI")
        print(f"{'=' * 65}")
        print(f"  Yazilacak devam       : {len(devam_yazilacak)}")
        print(f"  Skip mukerrer         : {devam_skip_muk}")
        print(f"  Yazilacak izin        : {len(izin_yazilacak)}")
        print(f"  Skip mevcut CPS       : {devam_skip_cak + izin_skip_cak}")
        print(f"  Mukerrer liste        : {len(mukerrer)} gun")
        if mukerrer:
            for (pid, t) in sorted(mukerrer):
                ad = eslesik.get(pid, {}).get('ad', '?')
                print(f"    pdks_id={pid} '{ad}' tarih={t}")
        print()
        return

    # ── GERCEK YAZMA ──────────────────────────────────────────────────────────
    print(f"\n{SEP}\nGERCEK YAZMA BASLIYOR...\n{SEP}")

    cur = db.cursor()

    DEVAM_SQL = """
        INSERT OR IGNORE INTO personel_devam
            (personel_pk_id, kullanici_profil_id, tarih, durum,
             giris_saati, cikis_saati, calisma_dakika,
             kaynak, aciklama, giren_kullanici)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    IZIN_SQL = """
        INSERT OR IGNORE INTO personel_izin
            (personel_pk_id, kullanici_profil_id, yil, hak_gun,
             kullanilan_gun, izin_tipi, baslangic_tarihi, bitis_tarihi,
             gun_sayisi, durum, notlar, giren_kullanici)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    yazilan_devam = 0
    yazilan_izin  = 0

    # personel_devam batch insert
    try:
        for tpl in devam_yazilacak:
            cur.execute(DEVAM_SQL, tpl)
            yazilan_devam += cur.rowcount
        db.commit()
        print(f"  [OK] personel_devam yazildi : {yazilan_devam}")
    except Exception as e:
        db.rollback()
        print(f"  [HATA] personel_devam: {e}")
        raise

    # personel_izin batch insert
    try:
        for tpl in izin_yazilacak:
            cur.execute(IZIN_SQL, tpl)
            yazilan_izin += cur.rowcount
        db.commit()
        print(f"  [OK] personel_izin yazildi  : {yazilan_izin}")
    except Exception as e:
        db.rollback()
        print(f"  [HATA] personel_izin: {e}")
        raise

    # ── RAPOR ─────────────────────────────────────────────────────────────────
    year = tarih_bas.year
    ph_prof = ','.join(['?'] * len(profil_ids)) if profil_ids else 'NULL'

    dev_pdks_toplam = db.execute(
        "SELECT COUNT(*) FROM personel_devam WHERE kaynak='pdks'"
    ).fetchone()[0]

    iz_yil_toplam = db.execute(f"""
        SELECT COUNT(*) FROM personel_izin
        WHERE kullanici_profil_id IN ({ph_prof}) AND yil=?
    """, profil_ids + [year]).fetchone()[0]

    # Profil 12 (Ibrahim Kilic) -- 2025-03
    profil12_devam = db.execute("""
        SELECT tarih, durum, giris_saati, cikis_saati, calisma_dakika
        FROM personel_devam
        WHERE kullanici_profil_id=12
          AND tarih >= '2025-03-01' AND tarih <= '2025-03-31'
        ORDER BY tarih
    """).fetchall()

    # Profil 7 (Mehmet Corabci) -- 2025-03
    profil7_devam = db.execute("""
        SELECT tarih, durum, giris_saati, cikis_saati, calisma_dakika
        FROM personel_devam
        WHERE kullanici_profil_id=7
          AND tarih >= '2025-03-01' AND tarih <= '2025-03-31'
        ORDER BY tarih
    """).fetchall()

    print(f"\n{'=' * 65}")
    print("FAZ-6B AKTARIM RAPORU")
    print(f"{'=' * 65}")
    print(f"  A) Yazilan devam kayit        : {yazilan_devam}")
    print(f"  B) Skip mukerrer devam        : {devam_skip_muk}")
    print(f"  C) Yazilan izin kayit         : {yazilan_izin}")
    print(f"  D) Skip mevcut CPS kayit      : {devam_skip_cak + izin_skip_cak}")
    print(f"  E) personel_devam pdks toplam : {dev_pdks_toplam}")
    print(f"  F) personel_izin {year} toplam  : {iz_yil_toplam}")
    print()
    print(f"  G) profil_id=12 (Ibrahim Kilic) 2025-03: {len(profil12_devam)} kayit")
    for row in profil12_devam[:5]:
        print(f"      {dict(row)}")
    if len(profil12_devam) > 5:
        print(f"      ... +{len(profil12_devam)-5} daha")
    print()
    print(f"  H) profil_id=7 (Mehmet Corabci) 2025-03: {len(profil7_devam)} kayit")
    for row in profil7_devam[:5]:
        print(f"      {dict(row)}")
    if len(profil7_devam) > 5:
        print(f"      ... +{len(profil7_devam)-5} daha")

    if mukerrer:
        print(f"\n  MUKERRER MANUEL KONTROL LISTESI ({len(mukerrer)} adet):")
        for (pid, t) in sorted(mukerrer):
            ad = eslesik.get(pid, {}).get('ad', '?')
            print(f"    pdks_id={pid} '{ad}' tarih={t}")

    print(f"\n{'=' * 65}")
    print("Gercek aktarim tamamlandi.")
    print("Commit/push oncesi raporu Adem'e gonder.")
    print(f"{'=' * 65}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='FAZ-6B PDKS 2025 Tarihsel Aktarim')
    parser.add_argument('--year',    type=int, default=2025, help='Aktarim yili (varsayilan: 2025)')
    parser.add_argument('--dry-run', action='store_true',   help='Sadece rapor, DB yazma')
    parser.add_argument('--apply',   action='store_true',   help='Gercek aktarim yap')
    args = parser.parse_args()

    if args.apply and args.dry_run:
        print("[HATA] --dry-run ve --apply ayni anda kullanılamaz.")
        sys.exit(1)

    if not args.apply and not args.dry_run:
        print("[BILGI] Mod belirtilmedi. --dry-run ile calistiriliyor.")
        args.dry_run = True

    run(year=args.year, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
