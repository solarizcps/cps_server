# -*- coding: utf-8 -*-
"""
CPS DEV - FAZ 7 ADIM 2: STANDART SURE BACKEND
==============================================

YAPILACAK:
  modules/yonetim/routes.py'a 3 yeni endpoint append:
    1. GET  /yonetim/proses-kategori/liste     - JSON listele
    2. PUT  /yonetim/proses-kategori/<kod>/sure - sure guncelle
    3. POST /yonetim/proses-kategori/yeni       - yeni proses ekle
  
  Auth: Sadece session['kullanici_tip'] == 'sistem' (admin)

DOKUNULMAYAN:
  - Mevcut /kur/api ve /belge/<id> route'lari
  - queries.py
  - templates/yonetim/*.html
  - app.py (yonetim_bp zaten kayitli)

Idempotent: 'FAZ 7' marker varsa SKIP.
Yedek: routes.py.YEDEK_FAZ7_<ts>
"""
import sys
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(r"C:\cps_dev")
TARGET_PY = PROJECT_ROOT / "modules" / "yonetim" / "routes.py"
ts = datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# YENI ENDPOINT KODU - dosya sonuna eklenecek
# ============================================================
NEW_ENDPOINTS = '''

# ================================================================
# FAZ 7 - STANDART SURE ENDPOINT'LERI
# ================================================================
import sqlite3 as _faz7_sqlite3
from flask import session as _faz7_session, request as _faz7_request, jsonify as _faz7_jsonify

_FAZ7_DB_PATH = r"C:\\cps_dev\\mock_data.db"


def _faz7_admin_kontrol():
    """Sadece sistem kullanici (admin) gecebilir."""
    tip = _faz7_session.get('kullanici_tip')
    if tip != 'sistem':
        return False
    return True


def _faz7_db_baglan():
    """proses_kategori icin DB baglanti."""
    conn = _faz7_sqlite3.connect(_FAZ7_DB_PATH)
    conn.row_factory = _faz7_sqlite3.Row
    return conn


@yonetim.route('/proses-kategori/liste', methods=['GET'])
def faz7_proses_kategori_liste():
    """Tum proses_kategori kayitlarini standart_saniye dahil dondur."""
    if not _faz7_admin_kontrol():
        return _faz7_jsonify({'ok': False, 'mesaj': 'Yetkisiz erisim'}), 403
    
    try:
        conn = _faz7_db_baglan()
        cur = conn.cursor()
        cur.execute("""
            SELECT proses_kod, proses_adi, kategori, sira, standart_saniye
              FROM proses_kategori
             ORDER BY kategori, sira
        """)
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            rows.append({
                'proses_kod': d.get('proses_kod') or '',
                'proses_adi': d.get('proses_adi') or '',
                'kategori': d.get('kategori') or '',
                'sira': int(d.get('sira') or 0),
                'standart_saniye': float(d['standart_saniye']) if d.get('standart_saniye') is not None else None
            })
        conn.close()
        return _faz7_jsonify({
            'ok': True,
            'success': True,
            'kayit_sayisi': len(rows),
            'kayitlar': rows
        })
    except Exception as e:
        return _faz7_jsonify({
            'ok': False,
            'success': False,
            'mesaj': f'{type(e).__name__}: {str(e)[:200]}'
        }), 500


@yonetim.route('/proses-kategori/<proses_kod>/sure', methods=['PUT'])
def faz7_proses_kategori_sure_guncelle(proses_kod):
    """Bir prosesin standart_saniye degerini guncelle."""
    if not _faz7_admin_kontrol():
        return _faz7_jsonify({'ok': False, 'mesaj': 'Yetkisiz erisim'}), 403
    
    try:
        data = _faz7_request.get_json(silent=True) or {}
        sure_raw = data.get('standart_saniye')
        
        # NULL silme: standart_saniye = None gonderilirse temizle
        if sure_raw is None or sure_raw == '' or sure_raw == 'null':
            yeni_sure = None
        else:
            try:
                yeni_sure = float(sure_raw)
                if yeni_sure < 0 or yeni_sure > 7200:  # 0-7200 sn (2 saat max)
                    return _faz7_jsonify({
                        'ok': False,
                        'mesaj': 'Sure 0-7200 saniye arasi olmali'
                    }), 400
            except (TypeError, ValueError):
                return _faz7_jsonify({
                    'ok': False,
                    'mesaj': 'Gecersiz sayi formati'
                }), 400
        
        # proses_kod sanitize
        if not proses_kod or len(proses_kod) > 20:
            return _faz7_jsonify({
                'ok': False,
                'mesaj': 'Gecersiz proses_kod'
            }), 400
        
        conn = _faz7_db_baglan()
        cur = conn.cursor()
        
        # Once var mi kontrol
        cur.execute("SELECT proses_kod, proses_adi FROM proses_kategori WHERE proses_kod = ?", (proses_kod,))
        kayit = cur.fetchone()
        if not kayit:
            conn.close()
            return _faz7_jsonify({
                'ok': False,
                'mesaj': f'proses_kod={proses_kod} bulunamadi'
            }), 404
        
        # Guncelle
        cur.execute("UPDATE proses_kategori SET standart_saniye = ? WHERE proses_kod = ?",
                    (yeni_sure, proses_kod))
        conn.commit()
        affected = cur.rowcount
        conn.close()
        
        return _faz7_jsonify({
            'ok': True,
            'success': True,
            'mesaj': f'{kayit["proses_adi"]} guncellendi',
            'proses_kod': proses_kod,
            'standart_saniye': yeni_sure,
            'affected': affected
        })
    except Exception as e:
        return _faz7_jsonify({
            'ok': False,
            'success': False,
            'mesaj': f'{type(e).__name__}: {str(e)[:200]}'
        }), 500


@yonetim.route('/proses-kategori/yeni', methods=['POST'])
def faz7_proses_kategori_yeni():
    """Yeni proses ekle (Capak, Rivet, Tampon vb)."""
    if not _faz7_admin_kontrol():
        return _faz7_jsonify({'ok': False, 'mesaj': 'Yetkisiz erisim'}), 403
    
    try:
        data = _faz7_request.get_json(silent=True) or {}
        
        proses_kod = (data.get('proses_kod') or '').strip()
        proses_adi = (data.get('proses_adi') or '').strip()
        kategori = (data.get('kategori') or '').strip().upper()
        sira = data.get('sira', 0)
        standart_saniye = data.get('standart_saniye')
        
        # Validasyon
        if not proses_kod or len(proses_kod) > 20:
            return _faz7_jsonify({'ok': False, 'mesaj': 'proses_kod gerekli (1-20 karakter)'}), 400
        if not proses_adi or len(proses_adi) > 100:
            return _faz7_jsonify({'ok': False, 'mesaj': 'proses_adi gerekli (1-100 karakter)'}), 400
        if not kategori or kategori not in ['ATKI', 'GOVDE', 'MAMUL']:
            return _faz7_jsonify({'ok': False, 'mesaj': 'kategori ATKI/GOVDE/MAMUL olmali'}), 400
        try:
            sira = int(sira)
            if sira < 0 or sira > 999:
                return _faz7_jsonify({'ok': False, 'mesaj': 'sira 0-999 arasi olmali'}), 400
        except (TypeError, ValueError):
            return _faz7_jsonify({'ok': False, 'mesaj': 'sira sayi olmali'}), 400
        
        if standart_saniye is not None and standart_saniye != '':
            try:
                standart_saniye = float(standart_saniye)
                if standart_saniye < 0 or standart_saniye > 7200:
                    return _faz7_jsonify({'ok': False, 'mesaj': 'standart_saniye 0-7200 olmali'}), 400
            except (TypeError, ValueError):
                return _faz7_jsonify({'ok': False, 'mesaj': 'standart_saniye sayi olmali'}), 400
        else:
            standart_saniye = None
        
        conn = _faz7_db_baglan()
        cur = conn.cursor()
        
        # Duplicate check
        cur.execute("SELECT proses_kod FROM proses_kategori WHERE proses_kod = ?", (proses_kod,))
        if cur.fetchone():
            conn.close()
            return _faz7_jsonify({
                'ok': False,
                'mesaj': f'proses_kod={proses_kod} zaten var'
            }), 409
        
        # INSERT
        cur.execute("""
            INSERT INTO proses_kategori (proses_kod, proses_adi, kategori, sira, standart_saniye)
            VALUES (?, ?, ?, ?, ?)
        """, (proses_kod, proses_adi, kategori, sira, standart_saniye))
        conn.commit()
        conn.close()
        
        return _faz7_jsonify({
            'ok': True,
            'success': True,
            'mesaj': f'{proses_adi} eklendi',
            'proses_kod': proses_kod,
            'proses_adi': proses_adi,
            'kategori': kategori,
            'sira': sira,
            'standart_saniye': standart_saniye
        })
    except Exception as e:
        return _faz7_jsonify({
            'ok': False,
            'success': False,
            'mesaj': f'{type(e).__name__}: {str(e)[:200]}'
        }), 500
# === FAZ 7 ADIM 2 SONU ===
'''


def main():
    print("=" * 60)
    print("CPS DEV - FAZ 7 ADIM 2: STANDART SURE BACKEND")
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
    if 'FAZ 7' in content or 'faz7_proses_kategori_liste' in content:
        print()
        print("  [SKIP] FAZ 7 marker var, endpoint'ler zaten eklenmis.")
        print("=" * 60)
        return 0

    # ============================================================
    # ON-KONTROL
    # ============================================================
    print()
    print("=== ON-KONTROL ===")
    
    # Blueprint adi 'yonetim' olmali
    if 'yonetim = Blueprint' not in content and "Blueprint('yonetim'" not in content:
        print("  [HATA] yonetim Blueprint bulunamadi")
        return 1
    print("  [OK] yonetim Blueprint mevcut")
    
    # Mevcut endpoint'ler korunmali
    if '/kur/api' not in content:
        print("  [UYARI] /kur/api bulunamadi (yine de devam)")
    else:
        print("  [OK] /kur/api korunacak")
    
    if '/belge/' not in content:
        print("  [UYARI] /belge/ bulunamadi (yine de devam)")
    else:
        print("  [OK] /belge/ korunacak")

    # ============================================================
    # YEDEK
    # ============================================================
    backup_path = TARGET_PY.with_suffix(f".py.YEDEK_FAZ7_{ts}")
    print()
    print("=== YEDEK ===")
    shutil.copy2(str(TARGET_PY), str(backup_path))
    print(f"  [OK] Yedek: {backup_path.name}")

    # ============================================================
    # PATCH UYGULA - DOSYA SONUNA APPEND
    # ============================================================
    print()
    print("=== PATCH UYGULAMA ===")
    new_content = content.rstrip() + NEW_ENDPOINTS
    TARGET_PY.write_text(new_content, encoding="utf-8")
    new_size = TARGET_PY.stat().st_size
    diff = new_size - original_size
    print(f"  [OK] Endpoint'ler eklendi")
    print(f"  Yeni boyut: {new_size} byte (fark: +{diff})")

    # ============================================================
    # DOGRULAMA
    # ============================================================
    print()
    print("=== DOGRULAMA ===")
    final = TARGET_PY.read_text(encoding="utf-8")

    checks = [
        ('FAZ 7', 'Marker'),
        ("@yonetim.route('/proses-kategori/liste'", 'Liste route'),
        ("@yonetim.route('/proses-kategori/<proses_kod>/sure'", 'Sure update route'),
        ("@yonetim.route('/proses-kategori/yeni'", 'Yeni route'),
        ('faz7_proses_kategori_liste', 'Liste fonksiyon'),
        ('faz7_proses_kategori_sure_guncelle', 'Update fonksiyon'),
        ('faz7_proses_kategori_yeni', 'Yeni fonksiyon'),
        ('_faz7_admin_kontrol', 'Auth helper'),
        ("session.get('kullanici_tip')", 'Auth check'),
        ('mock_data.db', 'DB path'),
        # Mevcut endpoint'ler korundu
        ('/kur/api', '/kur/api korundu'),
        ('/belge/', '/belge/ korundu'),
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
    print("[OK] FAZ 7 ADIM 2 BACKEND TAMAM")
    print("=" * 60)
    print()
    print("Sonraki:")
    print("  1. Flask RESTART (Python dosya degisti)")
    print("  2. Test:")
    print("     curl -b cookie.txt http://127.0.0.1:5057/yonetim/proses-kategori/liste")
    print()
    print("ADIM 3: HTML UI (templates/yonetim/proses_kategori.html)")
    print()
    print(f"Rollback (manuel):")
    print(f"  Copy-Item modules\\yonetim\\{backup_path.name} modules\\yonetim\\routes.py -Force")
    return 0


if __name__ == "__main__":
    sys.exit(main())
