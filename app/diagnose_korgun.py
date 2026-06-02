# -*- coding: utf-8 -*-
"""
diagnose_korgun.py
------------------
1) C:\\cps_dev\\modules\\common\\korgun.py kaynak kodunu dump et
2) get_emir_ozet(110626) sonucunu dump et
3) Korgun connection helper'i kullanilabilir mi test et + Siparis_Har ve
   Urt_con_gch'tan 110626 ornek satirlar cek
"""

import os
import sys
import json

CPS_ROOT = r"C:\cps_dev"
KORGUN_PY = os.path.join(CPS_ROOT, "modules", "common", "korgun.py")


def section(t):
    print()
    print("=" * 72)
    print(t)
    print("=" * 72)


# ----------------------------------------------------------
section("1) korgun.py KAYNAK KODU")
# ----------------------------------------------------------
if not os.path.exists(KORGUN_PY):
    print(f"  HATA: {KORGUN_PY} bulunamadi")
    sys.exit(1)

with open(KORGUN_PY, 'r', encoding='utf-8') as f:
    src = f.read()
print(src)


# ----------------------------------------------------------
section("2) get_emir_ozet(110626) SONUC")
# ----------------------------------------------------------
sys.path.insert(0, CPS_ROOT)
try:
    from modules.common import korgun as _kk
    ozet = _kk.get_emir_ozet(110626)
    try:
        print(json.dumps(ozet, indent=2, default=str, ensure_ascii=False))
    except Exception:
        print(repr(ozet))
except Exception as e:
    print(f"HATA: {type(e).__name__}: {e}")


# ----------------------------------------------------------
section("3) Connection helper TESPIT + ornek sorgular")
# ----------------------------------------------------------
# korgun.py'deki tum public/private fonksiyonlar
print("\nkorgun modulundeki callable'lar:")
try:
    for name in sorted(dir(_kk)):
        if name.startswith('__'):
            continue
        obj = getattr(_kk, name)
        if callable(obj):
            print(f"  {name}")
except Exception as e:
    print(f"  HATA: {e}")

# Kor connection icin sik kullanilan helper isimleri
candidates = ['_connect', '_kor_connect', '_get_conn', 'get_conn',
              '_open_conn', 'baglan', '_baglan', 'conn']
print("\nConnection helper deneme:")
conn = None
helper_used = None
for c in candidates:
    if hasattr(_kk, c):
        try:
            obj = getattr(_kk, c)
            if callable(obj):
                conn = obj()
                helper_used = c
                break
        except Exception as e:
            print(f"  {c}() -> HATA: {e}")

if not conn:
    # AST ile pytds.connect cagrilarini bul
    import ast
    print("  (helper bulunamadi — pytds.connect cagrilari ast ile aranıyor)")
    try:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Attribute) and fn.attr == 'connect':
                    print(f"\n  satir {node.lineno}: {ast.unparse(node)[:200]}")
    except Exception as e:
        print(f"  ast walk HATA: {e}")
else:
    print(f"  [OK] helper kullanildi: {helper_used}")
    cur = conn.cursor()

    # Siparis_Har TOP 1 — kolon isimleri
    print("\n--- Siparis_Har TOP 1 (kolon adlari) ---")
    try:
        cur.execute("SELECT TOP 1 * FROM Siparis_Har")
        cols = [d[0] for d in cur.description]
        print("  Kolonlar:", cols)
        row = cur.fetchone()
        if row:
            for c, v in zip(cols, row):
                vs = repr(v)[:80]
                print(f"    {c:<25} = {vs}")
    except Exception as e:
        print(f"  HATA: {e}")

    # Siparis_Har 110626 — tum satirlar
    print("\n--- Siparis_Har 110626 satirlari (Urt_Emir.SipNo ile) ---")
    try:
        cur.execute("""
            SELECT TOP 20 sh.*
            FROM Urt_Emir ue
            INNER JOIN Siparis_Har sh ON sh.SipNo = ue.SipNo
            WHERE ue.EmirNo = 110626
        """)
        cols = [d[0] for d in cur.description]
        for r in cur.fetchall():
            print()
            for c, v in zip(cols, r):
                vs = repr(v)[:80]
                print(f"    {c:<25} = {vs}")
    except Exception as e:
        # Alternatif: SipNo Urt_Emir'de degil, Siparis_Kay'da olabilir
        print(f"  HATA(1): {e}")
        try:
            cur.execute("""
                SELECT TOP 20 *
                FROM Siparis_Har
                WHERE SipNo IN (33558, 33638)
            """)
            cols = [d[0] for d in cur.description]
            for r in cur.fetchall():
                print()
                for c, v in zip(cols, r):
                    vs = repr(v)[:80]
                    print(f"    {c:<25} = {vs}")
        except Exception as e2:
            print(f"  HATA(2): {e2}")

    # Urt_con_gch TOP 1 — kolonlar
    print("\n--- Urt_con_gch TOP 1 (kolonlar) ---")
    try:
        cur.execute("SELECT TOP 1 * FROM Urt_con_gch")
        cols = [d[0] for d in cur.description]
        print("  Kolonlar:", cols)
    except Exception as e:
        print(f"  HATA: {e}")

    # Urt_con_gch 110626 GROUP BY RKOD
    print("\n--- Urt_con_gch 110626 GROUP BY RKOD ---")
    try:
        cur.execute("""
            SELECT RKOD, SUM(Cikan) AS toplam_cikan, COUNT(*) AS kayit
            FROM Urt_con_gch
            WHERE EmirNo = 110626
            GROUP BY RKOD
            ORDER BY toplam_cikan DESC
        """)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        print(f"  ({len(rows)} renk grubu)")
        for r in rows:
            print(f"    {dict(zip(cols, r))}")
    except Exception as e:
        print(f"  HATA: {e}")

    # Urtx_con_gch da var mi?
    print("\n--- Urtx_con_gch 110626 GROUP BY RKOD ---")
    try:
        cur.execute("""
            SELECT RKOD, SUM(Cikan) AS toplam_cikan, COUNT(*) AS kayit
            FROM Urtx_con_gch
            WHERE EmirNo = 110626
            GROUP BY RKOD
            ORDER BY toplam_cikan DESC
        """)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        print(f"  ({len(rows)} renk grubu)")
        for r in rows:
            print(f"    {dict(zip(cols, r))}")
    except Exception as e:
        print(f"  HATA: {e}")

    try:
        conn.close()
    except Exception:
        pass

print()
print("BITTI.")
