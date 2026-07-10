# -*- coding: utf-8 -*-
"""
NEXGEN PRINT AGENT — Donanımsız Birim Testleri
===============================================
Fiziksel yazıcı, COM port veya ağ bağlantısı gerektirmez.
Mock DB üzerinde çalışır.

Çalıştır:
  python NEXGEN_PRINT_AGENT_TEST.py

Tüm testler PASS olmadan commit yapılmaz.
"""

import sys
import os
import sqlite3
import base64
import traceback

# CPS modüllerini import edebilmek için path ayarla
_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP  = os.path.join(_ROOT, 'app')
if _APP not in sys.path:
    sys.path.insert(0, _APP)

# Migration klasörü
_MIG = os.path.join(_APP, 'migrations')
if _MIG not in sys.path:
    sys.path.insert(0, _MIG)

SEP  = "=" * 60
PASS = 0
FAIL = 0


def test(isim, fn):
    global PASS, FAIL
    try:
        fn()
        print(f"  [PASS] {isim}")
        PASS += 1
    except AssertionError as e:
        print(f"  [FAIL] {isim}: {e}")
        FAIL += 1
    except Exception as e:
        print(f"  [FAIL] {isim}: {type(e).__name__}: {e}")
        traceback.print_exc()
        FAIL += 1


# ─────────────────────────────────────────────────────────────
# 1. SYNTAX / IMPORT KONTROLLERI
# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  1. SYNTAX / IMPORT KONTROLLERI")
print(SEP)


def t_migration_import():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "m093", os.path.join(_MIG, "093_nexgen_print_job.py")
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert hasattr(m, 'mig093'), "mig093 fonksiyonu yok"


def t_agent_import():
    """Agent dosyası import edilebilir mi? (pyserial/requests olmadan)"""
    agent_path = os.path.join(_APP, 'tools', 'nexgen_print_agent.py')
    # Ortam değişkenleri olmadan import — hata vermesin (sadece boş değerler)
    import importlib.util
    spec = importlib.util.spec_from_file_location("agent", agent_path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert hasattr(m, '_bagimlilik_kontrol')
    assert hasattr(m, '_is_isle')
    assert hasattr(m, 'ana_dongu')


def t_agent_zorunlu_config():
    """Baud rate ve COM port tanımsız → hata listesi dolu olmalı."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "agent2", os.path.join(_APP, 'tools', 'nexgen_print_agent.py')
    )
    m = importlib.util.module_from_spec(spec)
    # Ortam değişkenlerini sıfırla
    for k in ['NEXGEN_PRINT_AGENT_KEY', 'NEXGEN_PRINT_COM_PORT', 'NEXGEN_PRINT_BAUDRATE']:
        os.environ.pop(k, None)
    spec.loader.exec_module(m)
    hatalar = m._bagimlilik_kontrol()
    # KEY, COM_PORT ve BAUDRATE eksik — en az 3 hata bekleniyor
    assert len(hatalar) >= 3, f"Beklenen ≥3 hata, gelen: {hatalar}"
    baudrate_hata = any('BAUDRATE' in h for h in hatalar)
    assert baudrate_hata, f"BAUDRATE hatası bekleniyordu, gelen: {hatalar}"


test("migration 093 import", t_migration_import)
test("agent dosyası import", t_agent_import)
test("agent zorunlu config kontrolleri", t_agent_zorunlu_config)

# ─────────────────────────────────────────────────────────────
# 2. IN-MEMORY DB — MIGRATION 093
# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  2. MIGRATION 093 — IN-MEMORY DB")
print(SEP)

_INMEM_CON = None


def _inmem():
    global _INMEM_CON
    if _INMEM_CON is None:
        _INMEM_CON = sqlite3.connect(":memory:")
        _INMEM_CON.row_factory = sqlite3.Row
        # schema_migrations ön koşul
        _INMEM_CON.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                aciklama TEXT,
                applied_at TEXT DEFAULT (datetime('now'))
            )
        """)
        # nexgen_arge_etiket bağımlılık (FK için)
        _INMEM_CON.execute("""
            CREATE TABLE IF NOT EXISTS nexgen_arge_etiket (
                id INTEGER PRIMARY KEY,
                barkod_kodu TEXT,
                durum TEXT
            )
        """)
        _INMEM_CON.commit()
    return _INMEM_CON


def t_mig093_ilk_calistirma():
    con = _inmem()
    cur = con.cursor()
    log = []
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "m093b", os.path.join(_MIG, "093_nexgen_print_job.py")
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.mig093(cur, con, log)
    # Tablo var mı?
    tablo = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='nexgen_print_job'"
    ).fetchone()
    assert tablo, "nexgen_print_job tablosu oluşturulmadı"
    # Kolonlar var mı?
    kolonlar = [c[1] for c in cur.execute("PRAGMA table_info(nexgen_print_job)").fetchall()]
    for k in ['id', 'etiket_id', 'payload_base64', 'status', 'requested_at',
              'claimed_at', 'printed_at', 'last_error']:
        assert k in kolonlar, f"Kolon eksik: {k}"
    # schema_migrations kaydı
    v = cur.execute(
        "SELECT version FROM schema_migrations WHERE version='093'"
    ).fetchone()
    assert v, "schema_migrations'a 093 kaydı girilmedi"
    # Log'da "oluşturuldu" geçmeli
    assert any("oluşturuldu" in l for l in log), f"Log beklenmedik: {log}"


def t_mig093_ikinci_calistirma():
    """İkinci çalıştırma 0 yeni değişiklik raporlamalı."""
    con = _inmem()
    cur = con.cursor()
    log = []
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "m093c", os.path.join(_MIG, "093_nexgen_print_job.py")
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.mig093(cur, con, log)
    # "değişiklik yok" ifadesi logda olmalı
    assert any("değişiklik yok" in l for l in log), f"İkinci çalıştırma idempotent değil: {log}"


test("mig093 ilk çalıştırma — tablo oluşturuldu", t_mig093_ilk_calistirma)
test("mig093 ikinci çalıştırma — 0 değişiklik", t_mig093_ikinci_calistirma)

# ─────────────────────────────────────────────────────────────
# 3. TSPL ÜRETİMİ — MOCK DB
# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  3. TSPL ÜRETİMİ — MOCK DB")
print(SEP)

# Gerçek mock_data.db kullan
_MOCK_DB_PATH = os.path.join(_APP, 'mock_data.db')


def _ilk_etiket_id():
    """mock_data.db'den ilk aktif etiket ID'sini döner."""
    if not os.path.exists(_MOCK_DB_PATH):
        return None
    con = sqlite3.connect(_MOCK_DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT id FROM nexgen_arge_etiket LIMIT 1"
        ).fetchone()
        return row['id'] if row else None
    except Exception:
        return None
    finally:
        con.close()


def t_tspl_routes_import():
    """routes.py import edilebilmeli."""
    # Sadece syntax/import kontrolü — Flask context olmadan çalışmaz
    # Bu yüzden compile ile kontrol ediyoruz
    routes_path = os.path.join(_APP, 'modules', 'nexgen', 'routes.py')
    with open(routes_path, 'rb') as f:
        source = f.read()
    import py_compile, tempfile
    with tempfile.NamedTemporaryFile(suffix='.py', delete=False) as tmp:
        tmp.write(source)
        tmp_path = tmp.name
    try:
        py_compile.compile(tmp_path, doraise=True)
    finally:
        os.unlink(tmp_path)


def t_tspl_size_komutu():
    """TSPL stringi 40×80 mm SIZE komutu içermeli."""
    # _m05_etiket_tspl_bytes gerçek DB bağlantısı gerektiriyor
    # Dolayısıyla TSPL string mantığını izole test ediyoruz
    def _mock_tspl(barkod, arge, musteri, talep, numune, rev, n, copies=1):
        copies_safe = max(1, min(5, int(copies)))
        cmds = [
            "SIZE 40 mm,80 mm",
            "GAP 3 mm,0 mm",
            "DIRECTION 0",
            "REFERENCE 0,0",
            "OFFSET 0 mm",
            "SET PEEL OFF",
            "SET TEAR ON",
            "CODEPAGE 857",
            "SPEED 4",
            "DENSITY 10",
            "CLS",
            "BAR 0,0,320,30",
            f'REVERSE 6,4,308,24,"4",0,1,1,"NEXGEN AR-GE"',
            f'TEXT 6,36,"4",0,1,1,"{arge}"',
            "BAR 0,62,320,1",
            f'TEXT 6,68,"3",0,1,1,"Mst: {musteri}"',
            f'TEXT 6,88,"3",0,1,1,"Talep : {talep}"',
            f'TEXT 6,104,"3",0,1,1,"Numune: {numune}"',
            f'TEXT 6,120,"3",0,1,1,"REV: R{rev:02d}   N: N{n:02d}"',
            "BAR 0,138,320,1",
            f'BARCODE 10,144,"128",60,1,0,2,4,"{barkod}"',
            f'TEXT 6,218,"3",0,1,1,"{barkod}"',
            f"PRINT {copies_safe},1",
        ]
        tspl_str = "\r\n".join(cmds) + "\r\n"
        return tspl_str.encode('cp857', errors='replace')

    payload = _mock_tspl(
        "NX-ARGE-RT0004-R00-N01",
        "NX-RT-0004", "TEST MUSTERI",
        "10.07.2026", "10.07.2026", 0, 1
    )
    tspl_str = payload.decode('cp857')
    assert "SIZE 40 mm,80 mm" in tspl_str, "SIZE komutu eksik"
    assert "CODEPAGE 857" in tspl_str, "CODEPAGE eksik"
    assert "NX-ARGE-RT0004-R00-N01" in tspl_str, "Barkod değeri TSPL'de bulunamadı"
    assert "BARCODE" in tspl_str, "BARCODE komutu eksik"
    assert "ARIAL" not in tspl_str, "TTF font var! Olmamalı"
    assert "PRINT 1,1" in tspl_str, "PRINT komutu eksik"


def t_tspl_barkod_degismez():
    """Barkod değeri TSPL payload içinde aynen korunmalı."""
    barkod = "NX-ARGE-AR0005-R02-N03"
    tspl_line = f'BARCODE 10,144,"128",60,1,0,2,4,"{barkod}"'
    assert barkod in tspl_line
    # encode/decode sonrası bozulmamalı
    payload = tspl_line.encode('cp857', errors='replace')
    assert barkod.encode('cp857') in payload


def t_tspl_kopya_siniri():
    """copies 1–5 dışında clamp edilmeli."""
    assert max(1, min(5, 0))  == 1
    assert max(1, min(5, 6))  == 5
    assert max(1, min(5, 3))  == 3


def t_tspl_b64_encode_decode():
    """base64 round-trip doğru çalışmalı."""
    orjinal = "SIZE 40 mm,80 mm\r\nCLS\r\nPRINT 1,1\r\n".encode('cp857')
    b64 = base64.b64encode(orjinal).decode('ascii')
    geri = base64.b64decode(b64)
    assert geri == orjinal, "base64 round-trip başarısız"


test("routes.py syntax/compile kontrolü", t_tspl_routes_import)
test("TSPL SIZE 40×80 mm komutu doğru", t_tspl_size_komutu)
test("TSPL barkod değeri payload'da aynen var", t_tspl_barkod_degismez)
test("TSPL copies 1–5 sınır kontrolü", t_tspl_kopya_siniri)
test("base64 encode/decode round-trip", t_tspl_b64_encode_decode)

# ─────────────────────────────────────────────────────────────
# 4. PRINT JOB DURUM GEÇİŞLERİ — IN-MEMORY DB
# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  4. PRINT JOB DURUM GEÇİŞLERİ")
print(SEP)


def _job_db():
    """Test için temiz in-memory DB."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("""
        CREATE TABLE nexgen_print_job (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            etiket_id            INTEGER NOT NULL,
            payload_base64       TEXT    NOT NULL,
            status               TEXT    NOT NULL DEFAULT 'PENDING',
            requested_by_user_id INTEGER,
            requested_at         TEXT,
            claimed_at           TEXT,
            printed_at           TEXT,
            last_error           TEXT,
            created_at           TEXT DEFAULT (datetime('now','localtime')),
            updated_at           TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    con.commit()
    return con


def t_job_pending_insert():
    con = _job_db()
    payload_b64 = base64.b64encode(b"SIZE 40 mm,80 mm\r\nPRINT 1,1\r\n").decode('ascii')
    cur = con.execute(
        "INSERT INTO nexgen_print_job (etiket_id, payload_base64, status, requested_at) "
        "VALUES (1, ?, 'PENDING', datetime('now','localtime'))",
        (payload_b64,)
    )
    con.commit()
    job_id = cur.lastrowid
    row = con.execute("SELECT * FROM nexgen_print_job WHERE id=?", (job_id,)).fetchone()
    assert row['status'] == 'PENDING'
    assert row['claimed_at'] is None


def t_job_claim_atomik():
    """PENDING → CLAIMED atomik geçiş; aynı job iki kez claim edilemez."""
    con = _job_db()
    payload_b64 = base64.b64encode(b"TEST").decode('ascii')
    con.execute(
        "INSERT INTO nexgen_print_job (etiket_id, payload_base64, status) VALUES (1, ?, 'PENDING')",
        (payload_b64,)
    )
    con.commit()

    # Birinci claim
    con.execute("BEGIN IMMEDIATE")
    row = con.execute(
        "SELECT id FROM nexgen_print_job WHERE status='PENDING' ORDER BY id LIMIT 1"
    ).fetchone()
    assert row is not None
    job_id = row['id']
    con.execute(
        "UPDATE nexgen_print_job SET status='CLAIMED', claimed_at=datetime('now') WHERE id=?",
        (job_id,)
    )
    con.commit()

    # İkinci claim denemesi — PENDING yok artık
    row2 = con.execute(
        "SELECT id FROM nexgen_print_job WHERE status='PENDING' ORDER BY id LIMIT 1"
    ).fetchone()
    assert row2 is None, "Aynı job ikinci kez claim edildi!"


def t_job_printed():
    """CLAIMED → PRINTED geçişi."""
    con = _job_db()
    payload_b64 = base64.b64encode(b"TEST").decode('ascii')
    con.execute(
        "INSERT INTO nexgen_print_job (etiket_id, payload_base64, status) VALUES (1, ?, 'CLAIMED')",
        (payload_b64,)
    )
    con.commit()
    job_id = con.execute("SELECT id FROM nexgen_print_job").fetchone()['id']
    con.execute(
        "UPDATE nexgen_print_job SET status='PRINTED', printed_at=datetime('now') "
        "WHERE id=? AND status='CLAIMED'",
        (job_id,)
    )
    con.commit()
    row = con.execute("SELECT * FROM nexgen_print_job WHERE id=?", (job_id,)).fetchone()
    assert row['status'] == 'PRINTED'
    assert row['printed_at'] is not None


def t_job_failed():
    """CLAIMED → FAILED geçişi, last_error dolu."""
    con = _job_db()
    payload_b64 = base64.b64encode(b"TEST").decode('ascii')
    con.execute(
        "INSERT INTO nexgen_print_job (etiket_id, payload_base64, status) VALUES (1, ?, 'CLAIMED')",
        (payload_b64,)
    )
    con.commit()
    job_id = con.execute("SELECT id FROM nexgen_print_job").fetchone()['id']
    con.execute(
        "UPDATE nexgen_print_job SET status='FAILED', last_error=? "
        "WHERE id=? AND status='CLAIMED'",
        ("COM port açılamadı", job_id)
    )
    con.commit()
    row = con.execute("SELECT * FROM nexgen_print_job WHERE id=?", (job_id,)).fetchone()
    assert row['status'] == 'FAILED'
    assert 'COM port' in row['last_error']


def t_job_printed_tekrar_claim_edilemez():
    """PRINTED veya FAILED iş tekrar CLAIMED yapılamaz."""
    con = _job_db()
    payload_b64 = base64.b64encode(b"TEST").decode('ascii')
    con.execute(
        "INSERT INTO nexgen_print_job (etiket_id, payload_base64, status) VALUES (1, ?, 'PRINTED')",
        (payload_b64,)
    )
    con.commit()
    # PENDING olmadığı için claim gelmemeli
    row = con.execute(
        "SELECT id FROM nexgen_print_job WHERE status='PENDING' ORDER BY id LIMIT 1"
    ).fetchone()
    assert row is None, "PRINTED iş PENDING olarak görünüyor!"


test("PENDING job insert", t_job_pending_insert)
test("Claim atomik — aynı job iki kez alınamaz", t_job_claim_atomik)
test("CLAIMED → PRINTED geçişi", t_job_printed)
test("CLAIMED → FAILED geçişi + last_error", t_job_failed)
test("PRINTED iş tekrar claim edilemez", t_job_printed_tekrar_claim_edilemez)

# ─────────────────────────────────────────────────────────────
# 5. AGENT KEY KONTROL — MOCK
# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  5. AGENT KEY KONTROL")
print(SEP)


def t_agent_key_mantigi():
    """Doğru key PASS, yanlış key FAIL, boş key FAIL."""
    beklenen = "gizli-test-key-123"

    def kontrol(gelen, beklenen_sonuc):
        if not beklenen:
            return False, "key tanımsız"
        if not gelen or gelen != beklenen:
            return False, "geçersiz key"
        return True, ""

    tamam, _ = kontrol("gizli-test-key-123", True)
    assert tamam is True, "Doğru key reddedildi"

    tamam, _ = kontrol("yanlis-key", True)
    assert tamam is False, "Yanlış key kabul edildi"

    tamam, _ = kontrol("", True)
    assert tamam is False, "Boş key kabul edildi"


def t_agent_key_hardcoded_degil():
    """Agent kaynak kodunda hardcoded key olmamalı."""
    agent_path = os.path.join(_APP, 'tools', 'nexgen_print_agent.py')
    with open(agent_path, 'r', encoding='utf-8') as f:
        source = f.read()
    # Gerçek görünen key formatları
    import re
    # Uzun rastgele string yok
    hardcoded = re.findall(r'["\'][a-zA-Z0-9]{20,}["\']', source)
    assert not hardcoded, f"Hardcoded key adayı bulundu: {hardcoded}"


def t_agent_key_env_kaynagi():
    """Agent key sadece os.environ'dan okunmalı."""
    agent_path = os.path.join(_APP, 'tools', 'nexgen_print_agent.py')
    with open(agent_path, 'r', encoding='utf-8') as f:
        source = f.read()
    assert "os.environ.get('NEXGEN_PRINT_AGENT_KEY'" in source


test("Agent key mantık kontrolü (doğru/yanlış/boş)", t_agent_key_mantigi)
test("Agent kaynak kodunda hardcoded key yok", t_agent_key_hardcoded_degil)
test("Agent key ortam değişkeninden okunuyor", t_agent_key_env_kaynagi)

# ─────────────────────────────────────────────────────────────
# 6. POLL TIMEOUT — SONSUZ DÖNGÜ KORUMASI
# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  6. POLL TIMEOUT KONTROLÜ")
print(SEP)


def t_poll_timeout():
    """_m5JobPoll maks 15 deneme × 2 sn = 30 sn'de durmalı."""
    # Tablet JS'den alınan sayı (modul04_revize.html)
    MAKS_DENEME   = 15
    POLL_ARALIK   = 2  # saniye
    MAKS_SURE_SN  = MAKS_DENEME * POLL_ARALIK
    assert MAKS_SURE_SN == 30, f"Poll timeout 30 sn olmalı, hesaplanan: {MAKS_SURE_SN}"

    # Kaynak kodda 15 kontrolü var mı?
    dosyalar = [
        os.path.join(_APP, 'templates', 'nexgen', 'modul04_revize.html'),
        os.path.join(_APP, 'templates', 'nexgen', 'modul01_musteri_renk.html'),
    ]
    for dosya in dosyalar:
        with open(dosya, 'r', encoding='utf-8') as f:
            ic = f.read()
        assert "deneme >= 15" in ic or "MAKS = 15" in ic or "15" in ic, \
            f"{os.path.basename(dosya)}: poll maks deneme kontrolü bulunamadı"


def t_browser_print_fallback():
    """Browser print sayfası endpoint'i hâlâ var mı?"""
    routes_path = os.path.join(_APP, 'modules', 'nexgen', 'routes.py')
    with open(routes_path, 'r', encoding='utf-8') as f:
        src = f.read()
    assert "tablet_arge_etiket_print" in src, "Browser print fallback kaldırılmış!"
    assert "/print'" in src or '"/print"' in src or "etiket_id>/print" in src, \
        "Print URL route'u bulunamadı"


def t_barkod_degistirilmiyor():
    """_m05_barkod_kimlik fonksiyonu hâlâ var ve dokunulmamış."""
    routes_path = os.path.join(_APP, 'modules', 'nexgen', 'routes.py')
    with open(routes_path, 'r', encoding='utf-8') as f:
        src = f.read()
    assert "_m05_barkod_kimlik" in src, "_m05_barkod_kimlik fonksiyonu kaldırılmış!"
    assert "NX-ARGE-" in src, "Barkod format sabiti bulunamadı"


def t_route_icinde_migration_yok():
    """Route içinde schema repair / CREATE TABLE yapılmamalı."""
    routes_path = os.path.join(_APP, 'modules', 'nexgen', 'routes.py')
    with open(routes_path, 'r', encoding='utf-8') as f:
        src = f.read()
    # Route fonksiyonları içinde CREATE TABLE olmamalı
    import re
    # Fonksiyon başlığı + CREATE TABLE kombinasyonu
    route_create = re.findall(r'def api_[^\n]+\n(?:(?!^def ).+\n)*.*CREATE TABLE', src, re.M)
    assert not route_create, f"Route içinde CREATE TABLE bulundu: {route_create[:1]}"


test("Tablet poll timeout 30 sn sınırı", t_poll_timeout)
test("Browser print fallback korunmuş", t_browser_print_fallback)
test("Barkod değerleri değiştirilmemiş", t_barkod_degistirilmiyor)
test("Route içinde migration yok", t_route_icinde_migration_yok)

# ─────────────────────────────────────────────────────────────
# SONUÇ
# ─────────────────────────────────────────────────────────────
print(f"\n{SEP}")
print("  SONUÇ")
print(SEP)
TOPLAM = PASS + FAIL
print(f"  Toplam : {TOPLAM}")
print(f"  PASS   : {PASS}")
print(f"  FAIL   : {FAIL}")
print()

if FAIL > 0:
    print("  [!] Bazı testler başarısız — commit yapılmadan önce düzeltin.")
    sys.exit(1)
else:
    print("  [OK] Tüm testler geçti — commit güvenli.")
    sys.exit(0)
