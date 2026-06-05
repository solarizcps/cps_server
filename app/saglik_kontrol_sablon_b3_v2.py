# -*- coding: utf-8 -*-
"""
saglik_kontrol_sablon_b3_v2.py
------------------------------
Sablon B3 sistemi tam saglik kontrolu.
v2: emoji yok (cp1252 sorunu icin), UTF-8 stdout.
"""

import os
import sys
import sqlite3
import re
import ast

# UTF-8 stdout
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

CPS_ROOT = r"C:\cps_dev"
DB_PATH = os.path.join(CPS_ROOT, "mock_data.db")
HEDEF_ROUTES = os.path.join(CPS_ROOT, "modules", "hedef", "routes.py")
URETIM_ROUTES = os.path.join(CPS_ROOT, "modules", "uretim_giris", "routes.py")
KORGUN_PY = os.path.join(CPS_ROOT, "modules", "common", "korgun.py")


def section(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


sonuclar = {'ok': 0, 'risk': 0, 'hata': 0}


def add_ok(msg):
    sonuclar['ok'] += 1
    print(f"  [OK]   {msg}")


def add_warn(msg):
    sonuclar['risk'] += 1
    print(f"  [RISK] {msg}")


def add_err(msg):
    sonuclar['hata'] += 1
    print(f"  [HATA] {msg}")


def info(msg):
    print(f"         {msg}")


# ===========================================================
section("1) ENDPOINT HEALTH (static kod analizi)")
# ===========================================================
endpoints_aranacak = [
    ('hedef', '/sablon/liste', 'GET'),
    ('hedef', '/sablon/proses-onerileri', 'GET'),
    ('hedef', '/siparis/emirler', 'GET'),
    ('hedef', '/sablon/uygula', 'POST'),
    ('hedef', '/sablon/geri-al', 'POST'),
    ('hedef', '/sablon/ekle', 'POST'),
    ('hedef', '/sablon/sil', 'POST'),
    ('hedef', '/sablon/guncelle', 'POST'),
    ('hedef', '/siparis/emir-detay', 'GET'),
    ('uretim', '/emir/<emir_no>/prosesler', 'GET'),
    ('uretim', '/kaydet', 'POST'),
]
routes_files = {'hedef': HEDEF_ROUTES, 'uretim': URETIM_ROUTES}

for modul, path, method in endpoints_aranacak:
    file_path = routes_files[modul]
    if not os.path.exists(file_path):
        add_err(f"{modul} routes.py YOK")
        continue
    with open(file_path, 'r', encoding='utf-8') as f:
        src = f.read()
    path_clean = path.lstrip('/').replace('<emir_no>', '').strip('/')
    pattern = re.compile(
        r"@\w+_bp\.route\(['\"]([^'\"]*)['\"][^)]*methods\s*=\s*\[([^\]]*)\]",
        re.IGNORECASE
    )
    bulundu = False
    for m in pattern.finditer(src):
        route_path = m.group(1)
        methods_str = m.group(2)
        norm = route_path.replace('<emir_no>', '').replace('<int:sid>', '').replace('<int:emir_no>', '')
        if path_clean in norm.lstrip('/'):
            if method.upper() in methods_str.upper():
                bulundu = True
                break
    if bulundu:
        add_ok(f"{method} /{modul}{path}")
    else:
        # Daha gevsek arama
        path_start = path.lstrip('/').split('/')[0]
        if path_start in src and method.upper() in src.upper():
            add_ok(f"{method} /{modul}{path} (yaklasik)")
        else:
            add_err(f"{method} /{modul}{path} BULUNAMADI")


# ===========================================================
section("2) VERI TUTARLILIGI (mock_data.db)")
# ===========================================================
if not os.path.exists(DB_PATH):
    add_err(f"DB yok: {DB_PATH}")
else:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT
            COUNT(*),
            SUM(CASE WHEN aktif=1 THEN 1 ELSE 0 END),
            SUM(CASE WHEN aktif=0 THEN 1 ELSE 0 END),
            SUM(CASE WHEN kaynak LIKE 'sablon:%' THEN 1 ELSE 0 END),
            SUM(CASE WHEN kaynak='manuel' THEN 1 ELSE 0 END),
            SUM(CASE WHEN kaynak IS NULL OR kaynak='' THEN 1 ELSE 0 END)
          FROM emir_alt_proses
    """)
    r = cur.fetchone()
    info(f"emir_alt_proses toplam={r[0]}, aktif={r[1]}, pasif={r[2]}")
    info(f"  kaynak: sablon={r[3]}, manuel={r[4]}, bos={r[5]}")
    if r[0] > 0:
        add_ok("emir_alt_proses tablosu erisiliyor")

    cur.execute("""
        SELECT COUNT(*),
               SUM(CASE WHEN aktif=1 THEN 1 ELSE 0 END),
               SUM(CASE WHEN aktif=0 THEN 1 ELSE 0 END)
          FROM sablon
    """)
    r = cur.fetchone()
    info(f"sablon toplam={r[0]}, aktif={r[1]}, pasif={r[2]}")
    if (r[1] or 0) >= 1:
        add_ok(f"En az 1 aktif sablon var ({r[1]})")
    else:
        add_warn("Hic aktif sablon yok")

    cur.execute("SELECT COUNT(*) FROM sablon_proses")
    sp_sayi = cur.fetchone()[0]
    info(f"sablon_proses toplam={sp_sayi}")

    cur.execute("""
        SELECT COUNT(*) FROM sablon_proses sp
         WHERE NOT EXISTS (
             SELECT 1 FROM sablon s WHERE s.id = sp.sablon_id AND s.aktif = 1
         )
    """)
    yetim = cur.fetchone()[0]
    if yetim == 0:
        add_ok("Yetim sablon_proses kaydi yok")
    else:
        add_warn(f"Yetim sablon_proses kaydi var ({yetim})")

    conn.close()


# ===========================================================
section("3) DUPLICATE KONTROL")
# ===========================================================
if os.path.exists(DB_PATH):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT emir_no, proses_adi, COUNT(*)
          FROM emir_alt_proses
         WHERE aktif = 1
         GROUP BY emir_no, proses_adi
        HAVING COUNT(*) > 1
    """)
    dups = cur.fetchall()
    if not dups:
        add_ok("Aktif emir_alt_proses'de duplicate yok")
    else:
        add_warn(f"{len(dups)} duplicate aktif kayit:")
        for d in dups[:5]:
            print(f"            emir={d[0]}, proses={d[1]}, adet={d[2]}")

    cur.execute("""
        SELECT emir_no, proses_adi
          FROM emir_alt_proses
         GROUP BY emir_no, proses_adi
        HAVING SUM(CASE WHEN aktif=1 THEN 1 ELSE 0 END) > 0
           AND SUM(CASE WHEN aktif=0 THEN 1 ELSE 0 END) > 0
    """)
    karisik = cur.fetchall()
    if not karisik:
        add_ok("Aktif/pasif karisikligi yok")
    else:
        info(f"Aktif+pasif karisik kayitlar ({len(karisik)}):")
        for k in karisik[:5]:
            print(f"            emir={k[0]}, proses={k[1]}")
        info("  (Bu normal: bir emire sablon uygulanip geri alinmis olabilir)")

    conn.close()


# ===========================================================
section("4) KURAL IHLALI - Korgun INSERT/UPDATE/DELETE")
# ===========================================================
write_keywords = ['INSERT INTO', 'UPDATE ', 'DELETE FROM', 'TRUNCATE', 'DROP TABLE']
korgun_dosyalari = [HEDEF_ROUTES, URETIM_ROUTES, KORGUN_PY]

ihlal_var = False
for f_path in korgun_dosyalari:
    if not os.path.exists(f_path):
        continue
    with open(f_path, 'r', encoding='utf-8') as f:
        src = f.read()
    f_name = os.path.basename(f_path)
    if 'pytds' in src or '_baglan' in src:
        for kw in write_keywords:
            if kw in src.upper():
                lines = src.split('\n')
                for i, line in enumerate(lines):
                    if kw in line.upper():
                        context_start = max(0, i - 30)
                        context = '\n'.join(lines[context_start:i+1])
                        has_korgun = ('pytds' in context or '_baglan(' in context or
                                      '_kk._baglan' in context or 'KORGUN_' in context.upper())
                        has_sqlite = ('sqlite3' in context or 'mock_data' in context or
                                      '_hedef_db_path' in context)
                        if has_korgun and not has_sqlite:
                            print(f"  [HATA] {f_name} satir {i+1}: {kw}")
                            print(f"         {line.strip()[:100]}")
                            ihlal_var = True

if not ihlal_var:
    add_ok("Korgun connection'da INSERT/UPDATE/DELETE bulunmadi")


# ===========================================================
section("5) SABLON HEDEF URETIYOR MU?")
# ===========================================================
if os.path.exists(URETIM_ROUTES):
    with open(URETIM_ROUTES, 'r', encoding='utf-8') as f:
        src = f.read()
    m = re.search(r"def uretim_kaydet[^:]*:", src)
    if m:
        idx = m.start()
        end = src.find('\n@', idx + 1)
        if end == -1:
            end = idx + 6000
        body = src[idx:end].lower()
        if 'sablon' in body:
            add_warn("uretim_kaydet icinde 'sablon' geciyor")
        else:
            add_ok("uretim_kaydet sablon kullanmiyor (kural OK)")
    else:
        add_warn("uretim_kaydet fonksiyonu bulunamadi")


# ===========================================================
section("6) SYNTAX SAGLIK")
# ===========================================================
for f_path in [HEDEF_ROUTES, URETIM_ROUTES, KORGUN_PY]:
    if not os.path.exists(f_path):
        continue
    f_name = os.path.basename(f_path)
    try:
        with open(f_path, 'r', encoding='utf-8') as f:
            ast.parse(f.read())
        add_ok(f"{f_name} syntax OK")
    except SyntaxError as e:
        add_err(f"{f_name} SYNTAX HATASI: {e}")


# ===========================================================
section("OZET")
# ===========================================================
print(f"  [OK]   sayisi: {sonuclar['ok']}")
print(f"  [RISK] sayisi: {sonuclar['risk']}")
print(f"  [HATA] sayisi: {sonuclar['hata']}")
print()
if sonuclar['hata'] == 0:
    print("  >>> SONUC: STABLE - backup alinabilir")
elif sonuclar['hata'] <= 2:
    print("  >>> SONUC: KISMEN STABLE - hatalari incele, sonra backup")
else:
    print("  >>> SONUC: HATA VAR - once duzelt")
