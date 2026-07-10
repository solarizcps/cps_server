# -*- coding: utf-8 -*-
"""
Server tani - C:\Solariz_CPS_SERVER kok dizininden calistirin:
  python SERVER_IMPORT_TANI.py
"""
import sys, os

# app/ klasorunu path'e ekle (Flask app.py'nin calistigi yer)
_app_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app')
sys.path.insert(0, _app_dir)

print("=" * 60)
print("SERVER IMPORT TANISI")
print("=" * 60)
print(f"Script yolu : {__file__}")
print(f"app/ yolu   : {_app_dir}")
print(f"app/ var mi : {os.path.exists(_app_dir)}")
print()

# 1. nexgen blueprint import testi
print("--- 1. nexgen_bp import ---")
try:
    from modules.nexgen import nexgen_bp
    print(f"  OK — url_prefix={nexgen_bp.url_prefix!r}")
    print(f"  Dosya: {nexgen_bp.import_name}")
except Exception as e:
    print(f"  HATA: {e}")
    import traceback; traceback.print_exc()
print()

# 2. Flask app olustur ve route listesi
print("--- 2. Nexgen route listesi ---")
try:
    # app.py'yi import etmeden sadece blueprint route'larini goster
    from modules.nexgen.routes import nexgen_bp as _bp
    rules = [r for r in _bp.deferred_functions]
    # Blueprint'in kayitli endpoint'lerini goster
    import flask
    test_app = flask.Flask(__name__)
    test_app.config['TESTING'] = True
    test_app.register_blueprint(_bp)
    nexgen_routes = [r.rule for r in test_app.url_map.iter_rules() if '/nexgen' in r.rule]
    nexgen_routes.sort()
    # tablet/arge var mi?
    tablet_arge = [r for r in nexgen_routes if 'tablet/arge' in r]
    print(f"  Toplam nexgen route: {len(nexgen_routes)}")
    print(f"  /nexgen/tablet/arge iceren: {tablet_arge[:5]}")
    if not tablet_arge:
        print("  *** UYARI: /nexgen/tablet/arge ROUTE KAYITLI DEGIL ***")
except Exception as e:
    print(f"  HATA: {e}")
    import traceback; traceback.print_exc()
print()

# 3. Mock DB yolu
print("--- 3. Mock DB ---")
db = os.path.join(_app_dir, 'mock_data.db')
print(f"  Yol : {db}")
print(f"  Var : {os.path.exists(db)}")
if os.path.exists(db):
    import sqlite3
    con = sqlite3.connect(db)
    row = con.execute(
        "SELECT r.Ad FROM sistem_kullanici k "
        "LEFT JOIN sistem_rol r ON r.Id=k.RolId "
        "WHERE lower(k.KullaniciAdi)='vedat'"
    ).fetchone()
    print(f"  Vedat RolAd: {row[0] if row else 'BULUNAMADI'!r}")
    con.close()
print()
print("=" * 60)
