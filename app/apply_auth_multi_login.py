# -*- coding: utf-8 -*-
"""
CPS DEV - AUTH MULTI-TABLO LOGIN (FAZ 5.1)
============================================

Sadece modules/auth.py'a dokunulur.

YAPILACAK:
  ADIM 1: login_kullanici() fonksiyonu 3 tabloyu sirayla dener
    1. sistem_kullanici (mock_data.db, duz metin sifre) -> tip='sistem'
    2. pers_kullanici (solariz_dev.db, bcrypt hash) -> tip='personel'
    3. usta_kullanici (solariz_dev.db, bcrypt hash) -> tip='usta'
  
  ADIM 2: login() POST sonrasi redirect rule
    - tip='personel' -> /uretim/
    - tip='usta'     -> /hedef/
    - tip='sistem'   -> /  (mevcut)
    - next param varsa o oncelikli (mevcut davranis)
  
  ADIM 3: session['kullanici_tip'] eklenir

DOKUNULMAYAN:
  - login_gerekli decorator
  - yetki_gerekli decorator
  - kullanici_yetkileri fonksiyonu
  - sifre_degistir
  - logout
  - attach_user
  - base.html / sidebar / route'lar / DB

Idempotent: FAZ 5.1 marker zaten varsa SKIP.
"""
import sys
import re
import shutil
import hashlib
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
TARGET_PY    = PROJECT_ROOT / "modules" / "auth.py"
ts = datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# ESKI VE YENI BLOKLAR (string match)
# ============================================================

# A) login_kullanici fonksiyonu - sat 11-15
OLD_LOGIN_KULLANICI = '''def login_kullanici(kadi, sifre):
    return qone("""
        SELECT * FROM sistem_kullanici
        WHERE KullaniciAdi = ? AND Sifre = ? AND Aktif = 1
    """, (kadi, sifre))'''

NEW_LOGIN_KULLANICI = '''def login_kullanici(kadi, sifre):
    """FAZ 5.1: 3 tabloyu sirayla dener.
    
    Sira: sistem_kullanici (duz metin) -> pers_kullanici (bcrypt) -> usta_kullanici (bcrypt)
    Donen dict normalize edilir, 'Tip' alani: 'sistem' | 'personel' | 'usta'.
    Bulunamazsa None.
    """
    # 1) sistem_kullanici (mock_data.db, duz metin)
    u = qone("""
        SELECT * FROM sistem_kullanici
        WHERE KullaniciAdi = ? AND Sifre = ? AND Aktif = 1
    """, (kadi, sifre))
    if u:
        d = dict(u)
        d['Tip'] = 'sistem'
        return d
    
    # 2) pers_kullanici / usta_kullanici (solariz_dev.db, bcrypt hash)
    try:
        import bcrypt as _bcrypt
        import sqlite3 as _sqlite
        import os as _os
        # solariz_dev.db CPS root'unda
        _root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        _solariz_db = _os.path.join(_root, 'solariz_dev.db')
        if not _os.path.exists(_solariz_db):
            return None
        
        _con = _sqlite.connect(_solariz_db, timeout=10)
        _con.row_factory = _sqlite.Row
        try:
            # 2a) pers_kullanici
            row = _con.execute(
                "SELECT id, ad, kullanici_adi, sifre, sicil, birim, aktif "
                "FROM pers_kullanici WHERE kullanici_adi=? AND aktif=1",
                (kadi,)
            ).fetchone()
            if row and row['sifre']:
                try:
                    if _bcrypt.checkpw(sifre.encode('utf-8'), row['sifre'].encode('utf-8')):
                        return {
                            'Id': row['id'],
                            'KullaniciAdi': row['kullanici_adi'],
                            'AdSoyad': row['ad'] or row['kullanici_adi'],
                            'RolId': None,
                            'Rol': 'Personel',
                            'RolAd': 'Personel',
                            'Aktif': 1,
                            'Tip': 'personel',
                            'Sicil': row['sicil'],
                            'Birim': row['birim'],
                        }
                except Exception:
                    pass
            
            # 2b) usta_kullanici
            row = _con.execute(
                "SELECT id, ad, kullanici_adi, sifre, aktif "
                "FROM usta_kullanici WHERE kullanici_adi=? AND aktif=1",
                (kadi,)
            ).fetchone()
            if row and row['sifre']:
                try:
                    if _bcrypt.checkpw(sifre.encode('utf-8'), row['sifre'].encode('utf-8')):
                        return {
                            'Id': row['id'],
                            'KullaniciAdi': row['kullanici_adi'],
                            'AdSoyad': row['ad'] or row['kullanici_adi'],
                            'RolId': None,
                            'Rol': 'Usta',
                            'RolAd': 'Usta',
                            'Aktif': 1,
                            'Tip': 'usta',
                        }
                except Exception:
                    pass
        finally:
            _con.close()
    except ImportError:
        # bcrypt yoksa pers/usta login'ini atla
        pass
    except Exception:
        pass
    
    return None'''


# B) login() POST sonrasi redirect rule - sat ~99-110
# Sadece "session['kullanici'] = dict(u)" sonrasini ele alalim
# next sonrasi redirect satirini degistirelim

OLD_LOGIN_REDIRECT = '''            session['kullanici'] = dict(u)
            session.permanent = True

            audit.log(kadi, 'LOGIN', 'sistem_kullanici', u['Id'],
                      aciklama='Giriş yapıldı',
                      modul='yonetim', alt_modul='kullanici')

            if u.get('ZorunluSifreDegistir'):
                return redirect(url_for('auth.sifre_degistir'))

            nxt = request.args.get('next') or request.form.get('next') or '/'
            return redirect(nxt)'''

NEW_LOGIN_REDIRECT = '''            session['kullanici'] = dict(u)
            session['kullanici_tip'] = u.get('Tip') or 'sistem'  # FAZ 5.1
            session.permanent = True

            # Audit log (sadece sistem tipi icin Id mevcut)
            try:
                _audit_kaynak = {
                    'sistem': 'sistem_kullanici',
                    'personel': 'pers_kullanici',
                    'usta': 'usta_kullanici',
                }.get(u.get('Tip'), 'sistem_kullanici')
                audit.log(kadi, 'LOGIN', _audit_kaynak, u.get('Id'),
                          aciklama='Giriş yapıldı (tip=' + (u.get('Tip') or 'sistem') + ')',
                          modul='yonetim', alt_modul='kullanici')
            except Exception:
                pass

            if u.get('ZorunluSifreDegistir'):
                return redirect(url_for('auth.sifre_degistir'))

            # FAZ 5.1: next param oncelikli, yoksa tip bazli redirect
            nxt = request.args.get('next') or request.form.get('next')
            if not nxt:
                _tip = u.get('Tip') or 'sistem'
                if _tip == 'personel':
                    nxt = '/uretim/'
                elif _tip == 'usta':
                    nxt = '/hedef/'
                else:
                    nxt = '/'
            return redirect(nxt)'''


def file_hash(path):
    if not path.exists(): return None
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main():
    print("=" * 60)
    print("CPS DEV - AUTH MULTI-TABLO LOGIN (FAZ 5.1)")
    print("=" * 60)

    if not TARGET_PY.exists():
        print(f"  [HATA] auth.py yok: {TARGET_PY}")
        return 1

    content = TARGET_PY.read_text(encoding="utf-8")
    original_size = len(content.encode("utf-8"))
    print(f"  Mevcut boyut: {original_size} byte")

    # ============================================================
    # IDEMPOTENT KONTROL
    # ============================================================
    if 'FAZ 5.1' in content or "session['kullanici_tip']" in content:
        print()
        print("  [SKIP] FAZ 5.1 marker var, login multi-tablo zaten uygulanmis.")
        print()
        print("=" * 60)
        print("[OK] PATCH ZATEN UYGULANMIS")
        print("=" * 60)
        return 0

    # ============================================================
    # ON-KONTROLLER (anchor pattern'lar)
    # ============================================================
    print()
    print("=== ON-KONTROL ===")

    if OLD_LOGIN_KULLANICI not in content:
        print("  [HATA] Eski login_kullanici fonksiyonu bulunamadi")
        # Diagnostik
        if 'def login_kullanici' in content:
            print("  Fonksiyon var ama tam blok match degil. Manuel inceleme gerek.")
        return 1
    print("  [OK] Anchor 1: login_kullanici bulundu")

    if OLD_LOGIN_REDIRECT not in content:
        print("  [HATA] Eski login redirect bloku bulunamadi")
        return 1
    print("  [OK] Anchor 2: login redirect bulundu")

    # ============================================================
    # YEDEK
    # ============================================================
    backup_path = TARGET_PY.with_suffix(f".py.YEDEK_AUTH_FAZ51_{ts}")
    print()
    print("=== YEDEK ===")
    shutil.copy2(str(TARGET_PY), str(backup_path))
    print(f"  [OK] Yedek: {backup_path.name}")
    print(f"       Boyut: {backup_path.stat().st_size} byte")

    # ============================================================
    # PATCH UYGULA
    # ============================================================
    print()
    print("=== PATCH UYGULAMA ===")

    yeni_content = content.replace(OLD_LOGIN_KULLANICI, NEW_LOGIN_KULLANICI, 1)
    if yeni_content == content:
        print("  [HATA] login_kullanici replace etkisiz")
        return 1
    print("  [OK] 1) login_kullanici 3 tabloyu deniyor")

    yeni_content2 = yeni_content.replace(OLD_LOGIN_REDIRECT, NEW_LOGIN_REDIRECT, 1)
    if yeni_content2 == yeni_content:
        print("  [HATA] login redirect replace etkisiz")
        return 1
    print("  [OK] 2) Login sonrasi tip bazli redirect rule eklendi")
    print("  [OK] 3) session['kullanici_tip'] eklendi")

    # ============================================================
    # YAZ
    # ============================================================
    print()
    print("=== DOSYAYA YAZMA ===")
    TARGET_PY.write_text(yeni_content2, encoding="utf-8")
    new_size = TARGET_PY.stat().st_size
    diff = new_size - original_size
    print(f"  [OK] Yeni boyut: {new_size} byte (fark: {'+' if diff >= 0 else ''}{diff})")

    # ============================================================
    # DOGRULAMA
    # ============================================================
    print()
    print("=== DOGRULAMA ===")
    final = TARGET_PY.read_text(encoding="utf-8")

    checks = [
        ('FAZ 5.1', 'Yeni marker var mi'),
        ("session['kullanici_tip']", "session kullanici_tip eklendi mi"),
        ('pers_kullanici', 'pers_kullanici tablosu kullanildi mi'),
        ('usta_kullanici', 'usta_kullanici tablosu kullanildi mi'),
        ('bcrypt.checkpw', 'bcrypt.checkpw kullanildi mi'),
        ("d['Tip'] = 'sistem'", "sistem tipi atandi mi"),
        ("'Tip': 'personel'", 'personel tipi atandi mi'),
        ("'Tip': 'usta'", 'usta tipi atandi mi'),
        ("'/uretim/'", 'personel redirect mevcut mu'),
        ("'/hedef/'", 'usta redirect mevcut mu'),
        # Eski kod parçaları korundu mu
        ('def yetki_gerekli(kod):', 'yetki_gerekli decorator korundu mu'),
        ('def login_gerekli(f):', 'login_gerekli decorator korundu mu'),
        ('def attach_user():', 'attach_user korundu mu'),
        ('@auth_bp.route(\'/cikis\')', 'logout route korundu mu'),
    ]
    all_ok = True
    for needle, desc in checks:
        ok = needle in final
        sym = "[OK]" if ok else "[HATA]"
        print(f"  {sym} {desc}")
        if not ok:
            all_ok = False

    # ============================================================
    # SYNTAX CHECK
    # ============================================================
    print()
    print("=== PYTHON SYNTAX CHECK ===")
    try:
        compile(final, str(TARGET_PY), 'exec')
        print("  [OK] Syntax dogru")
    except SyntaxError as e:
        print(f"  [HATA] SyntaxError: {e}")
        print(f"         Satir {e.lineno}: {e.text}")
        return 1

    if not all_ok:
        print()
        print("  [UYARI] Bazi dogrulamalar basarisiz")
        return 1

    # ============================================================
    # bcrypt MEVCUT MU (kritik) 
    # ============================================================
    print()
    print("=== bcrypt MEVCUDIYET KONTROLU ===")
    try:
        import bcrypt
        print(f"  [OK] bcrypt versiyon: {bcrypt.__version__}")
    except ImportError:
        print("  [UYARI] bcrypt YUKLU DEGIL!")
        print("         pers/usta login calismayacak.")
        print("         Kurmak icin: python -m pip install bcrypt")
        # Patch yine de uygulandi - hata degil

    print()
    print("=" * 60)
    print("[OK] AUTH MULTI-TABLO LOGIN PATCH TAMAM")
    print("=" * 60)
    print()
    print("Sonraki:")
    print("  1. Flask RESTART (zorunlu - Python dosya degisti)")
    print("  2. Test:")
    print("     - admin/admin123             -> /  (mevcut, sistem)")
    print("     - halil/admin123             -> / (sistem, Yonetim)")
    print("     - [bir personel]/[sifre]     -> /uretim/  (personel)")
    print("     - [bir usta]/[sifre]         -> /hedef/  (usta)")
    print("     - admin/yanlis_sifre         -> hata mesaji")
    print()
    print(f"Rollback (manuel, gerekirse):")
    print(f"  Copy-Item modules\\{backup_path.name} modules\\auth.py -Force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
