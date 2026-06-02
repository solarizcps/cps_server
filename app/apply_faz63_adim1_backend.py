# -*- coding: utf-8 -*-
"""
CPS DEV - HEDEF OPERASYON KPI BACKEND (FAZ 6.3 ADIM 1)
========================================================

YAPILACAK:
  modules/hedef/routes.py'a YENI endpoint eklenir:
    GET /hedef/operasyon-ozet
  
  Tek SQL transaction'da 5 KPI hesaplanir:
    1. Açık İş             (emir_alt_proses WHERE aktif=1, DISTINCT emir_no)
    2. Bekleyen Onay       (uretim_kayit WHERE onay_durum='bekliyor')
    3. Bugün Üretim        (uretim_kayit SUM(miktar) WHERE today + onaylandi)
    4. Aktif Personel      (uretim_kayit DISTINCT personel_id WHERE today)
    5. Kritik Darboğaz     (siparis_darbogaz WHERE seviye='KRITIK')
  
  Salt okuma. Hicbir DB yazma yok.

DOKUNULMAYAN:
  - Mevcut 22 hedef route'u
  - hedef_rapor() (FAZ 6.2 ile dokundu)
  - Diger fonksiyonlar
  - DB schema
  - Korgun helper

Idempotent: 'FAZ 6.3' marker varsa SKIP.
Yedek: routes.py.YEDEK_FAZ63_<ts>
"""
import sys
import re
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
TARGET_PY = PROJECT_ROOT / "modules" / "hedef" / "routes.py"
ts = datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# YENI ENDPOINT KODU
# ============================================================
NEW_ENDPOINT = '''

# === FAZ 6.3 - OPERASYON KPI ENDPOINT ===
@hedef_bp.route('/operasyon-ozet', methods=['GET'])
def hedef_operasyon_ozet():
    """
    GET /hedef/operasyon-ozet
    
    /hedef/ ekrani ust KPI bandi icin 5 metrik tek SQL transaction'da:
      - acik_is        : emir_alt_proses WHERE aktif=1 (DISTINCT emir_no)
      - bekleyen_onay  : uretim_kayit WHERE onay_durum='bekliyor'
      - bugun_uretim   : uretim_kayit SUM(miktar) WHERE today AND onaylandi
      - aktif_personel : uretim_kayit DISTINCT personel_id WHERE today
      - kritik_darbogaz: siparis_darbogaz WHERE seviye='KRITIK'
    
    Salt okuma. Hicbir DB yazma yok. Cache yok (her cagrida fresh data).
    """
    import sqlite3
    from datetime import date, datetime as _dt
    from flask import jsonify

    db_path = _hedef_db_path()
    today = date.today().isoformat()

    kpi = {
        'acik_is': 0,
        'bekleyen_onay': 0,
        'bugun_uretim': 0,
        'aktif_personel': 0,
        'kritik_darbogaz': 0,
    }
    darbogaz_detay = []

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 1. ACIK IS - emir_alt_proses aktif=1
        try:
            cur.execute("SELECT COUNT(DISTINCT emir_no) FROM emir_alt_proses WHERE aktif=1")
            row = cur.fetchone()
            kpi['acik_is'] = int(row[0]) if row and row[0] else 0
        except Exception:
            pass

        # 2. BEKLEYEN ONAY
        try:
            cur.execute("SELECT COUNT(*) FROM uretim_kayit WHERE onay_durum='bekliyor'")
            row = cur.fetchone()
            kpi['bekleyen_onay'] = int(row[0]) if row and row[0] else 0
        except Exception:
            pass

        # 3. BUGUN URETIM (sadece onaylanmis miktar)
        try:
            cur.execute("""
                SELECT COALESCE(SUM(miktar), 0)
                  FROM uretim_kayit
                 WHERE date(COALESCE(NULLIF(onay_tarihi,''), olusturma)) = ?
                   AND onay_durum = 'onaylandi'
            """, (today,))
            row = cur.fetchone()
            kpi['bugun_uretim'] = int(row[0]) if row and row[0] else 0
        except Exception:
            pass

        # 4. AKTIF PERSONEL (bugun en az 1 kayit yapan)
        try:
            cur.execute("""
                SELECT COUNT(DISTINCT personel_id)
                  FROM uretim_kayit
                 WHERE date(olusturma) = ?
                   AND personel_id IS NOT NULL
            """, (today,))
            row = cur.fetchone()
            kpi['aktif_personel'] = int(row[0]) if row and row[0] else 0
        except Exception:
            pass

        # 5. KRITIK DARBOGAZ - siparis_darbogaz tablosundan (varsa)
        try:
            # Tablo var mi kontrolu
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='siparis_darbogaz'")
            if cur.fetchone():
                cur.execute("SELECT COUNT(*) FROM siparis_darbogaz WHERE UPPER(seviye)='KRITIK'")
                row = cur.fetchone()
                kpi['kritik_darbogaz'] = int(row[0]) if row and row[0] else 0

                # Detay (en fazla 5 satir)
                cur.execute("""
                    SELECT siparis_no, ana, proses, seviye, yuzde, guncelleme
                      FROM siparis_darbogaz
                     WHERE UPPER(seviye)='KRITIK'
                     ORDER BY yuzde DESC
                     LIMIT 5
                """)
                for r in cur.fetchall():
                    d = dict(r)
                    darbogaz_detay.append({
                        'siparis_no': str(d.get('siparis_no') or ''),
                        'ana': d.get('ana') or '',
                        'proses': str(d.get('proses') or ''),
                        'seviye': d.get('seviye') or '',
                        'yuzde': float(d.get('yuzde') or 0),
                        'guncelleme': d.get('guncelleme') or '',
                    })
        except Exception:
            pass

        conn.close()

        return jsonify({
            'ok': True,
            'success': True,
            'kpi': kpi,
            'darbogaz_detay': darbogaz_detay,
            'guncelleme': _dt.now().strftime('%Y-%m-%d %H:%M:%S'),
        })
    except Exception as e:
        return jsonify({
            'ok': False,
            'success': False,
            'mesaj': f'{type(e).__name__}: {str(e)[:200]}',
            'kpi': kpi,
            'darbogaz_detay': [],
        }), 500
# === FAZ 6.3 SONU ===
'''


def main():
    print("=" * 60)
    print("CPS DEV - HEDEF OPERASYON KPI BACKEND (FAZ 6.3 ADIM 1)")
    print("=" * 60)

    if not TARGET_PY.exists():
        print(f"  [HATA] dosya yok: {TARGET_PY}")
        return 1

    content = TARGET_PY.read_text(encoding="utf-8")
    original_size = len(content.encode("utf-8"))
    print(f"  Mevcut boyut: {original_size} byte")

    # ============================================================
    # IDEMPOTENT
    # ============================================================
    if 'FAZ 6.3' in content or 'hedef_operasyon_ozet' in content:
        print()
        print("  [SKIP] FAZ 6.3 marker var, KPI endpoint zaten eklenmis.")
        print("=" * 60)
        return 0

    # ============================================================
    # ON-KONTROL
    # ============================================================
    print()
    print("=== ON-KONTROL ===")

    # _hedef_db_path() fonksiyonu var mi (yeni endpoint bunu kullanacak)
    if '_hedef_db_path' not in content:
        print("  [HATA] _hedef_db_path fonksiyonu yok")
        return 1
    print("  [OK] _hedef_db_path fonksiyonu mevcut")

    # hedef_bp Blueprint var mi
    if 'hedef_bp' not in content:
        print("  [HATA] hedef_bp Blueprint yok")
        return 1
    print("  [OK] hedef_bp Blueprint mevcut")

    # FAZ 6.2 (rapor detay) duruyor mu (regression check)
    if 'FAZ 6.2' in content:
        print("  [OK] FAZ 6.2 (rapor detay) korundu")
    else:
        print("  [UYARI] FAZ 6.2 marker yok - yine de devam")

    # ============================================================
    # YEDEK
    # ============================================================
    backup_path = TARGET_PY.with_suffix(f".py.YEDEK_FAZ63_{ts}")
    print()
    print("=== YEDEK ===")
    shutil.copy2(str(TARGET_PY), str(backup_path))
    print(f"  [OK] Yedek: {backup_path.name}")

    # ============================================================
    # PATCH UYGULA - DOSYA SONUNA APPEND
    # ============================================================
    print()
    print("=== PATCH UYGULAMA ===")

    # Sondaki whitespace temizle, sonra append
    new_content = content.rstrip() + NEW_ENDPOINT
    
    if new_content == content:
        print("  [HATA] Append etkisiz")
        return 1
    print("  [OK] /hedef/operasyon-ozet endpoint dosya sonuna eklendi")

    # ============================================================
    # YAZ
    # ============================================================
    print()
    print("=== DOSYAYA YAZMA ===")
    TARGET_PY.write_text(new_content, encoding="utf-8")
    new_size = TARGET_PY.stat().st_size
    diff = new_size - original_size
    print(f"  [OK] Yeni boyut: {new_size} byte (fark: +{diff})")

    # ============================================================
    # DOGRULAMA
    # ============================================================
    print()
    print("=== DOGRULAMA ===")
    final = TARGET_PY.read_text(encoding="utf-8")

    checks = [
        ('FAZ 6.3', 'Yeni marker'),
        ("@hedef_bp.route('/operasyon-ozet'", 'Route tanimi'),
        ('def hedef_operasyon_ozet(', 'Fonksiyon tanimi'),
        ("'acik_is':", 'KPI: acik_is'),
        ("'bekleyen_onay':", 'KPI: bekleyen_onay'),
        ("'bugun_uretim':", 'KPI: bugun_uretim'),
        ("'aktif_personel':", 'KPI: aktif_personel'),
        ("'kritik_darbogaz':", 'KPI: kritik_darbogaz'),
        ("'darbogaz_detay':", 'darbogaz detay alani'),
        ('siparis_darbogaz', 'Darbogaz tablo erisimi'),
        ('emir_alt_proses', 'emir_alt_proses tablo erisimi'),
        ('uretim_kayit', 'uretim_kayit tablo erisimi'),
        # Mevcut yapilar KORUNDU mu
        ('def hedef_rapor(', 'hedef_rapor (FAZ 6.2) korundu'),
        ('FAZ 6.2', 'FAZ 6.2 marker korundu'),
        ('def hedef_onayla(', 'hedef_onayla korundu'),
        ('def hedef_reddet(', 'hedef_reddet korundu'),
        ('def hedef_gecmis(', 'hedef_gecmis korundu'),
        ('def sapma(', 'sapma korundu'),
        ('def panel(', 'panel korundu'),
        ('kayit_listesi', 'FAZ 6.2 kayit_listesi korundu'),
    ]
    all_ok = True
    for needle, desc in checks:
        ok = needle in final
        sym = "[OK]" if ok else "[HATA]"
        print(f"  {sym} {desc}")
        if not ok:
            all_ok = False

    if not all_ok:
        return 1

    # ============================================================
    # PYTHON SYNTAX CHECK
    # ============================================================
    print()
    print("=== PYTHON SYNTAX CHECK ===")
    try:
        compile(final, str(TARGET_PY), 'exec')
        print("  [OK] Syntax dogru")
    except SyntaxError as e:
        print(f"  [HATA] SyntaxError: {e}")
        return 1

    print()
    print("=" * 60)
    print("[OK] FAZ 6.3 ADIM 1 BACKEND TAMAM")
    print("=" * 60)
    print()
    print("Sonraki:")
    print("  1. Flask RESTART (Python dosya degisti)")
    print("  2. Test:")
    print("     curl http://127.0.0.1:5057/hedef/operasyon-ozet")
    print("     -> response: {ok:true, kpi:{acik_is, bekleyen_onay, ...}}")
    print()
    print("ADIM 2: HTML KPI div + script tag (sira sirada)")
    print()
    print(f"Rollback (manuel):")
    print(f"  Copy-Item modules\\hedef\\{backup_path.name} modules\\hedef\\routes.py -Force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
