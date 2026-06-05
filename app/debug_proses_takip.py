# -*- coding: utf-8 -*-
"""
proses_takip.py'a DEBUG ekle:
- 2 yeni debug endpoint (ham + info)
- Mevcut endpoint'e print log
"""
import shutil
from datetime import datetime

PT = r'C:\cps_dev\modules\planlama\proses_takip.py'
YEDEK = PT + '.YEDEK_DEBUG_' + datetime.now().strftime('%Y%m%d_%H%M%S')

shutil.copy(PT, YEDEK)
print(f"[OK] Yedek: {YEDEK}")

with open(PT, 'rb') as f:
    raw = f.read()
try:
    icerik = raw.decode('utf-8')
except:
    icerik = raw.decode('cp1252')
print(f"[OK] Okundu: {len(icerik)} karakter")

# Zaten var mi?
if 'def proses_takip_debug_info' in icerik:
    print("[UYARI] Debug endpointler zaten ekli, tekrar eklenmiyor.")
    exit(0)

# 1) DEBUG print mevcut endpoint icine
arama1 = '    period = request.args.get(\'period\', \'bugun\')'
yeni1 = '''    period = request.args.get('period', 'bugun')
    # === DEBUG LOG (gecici) ===
    print(f"[PT_DATA] === Yeni istek === period={period}")
'''
if arama1 not in icerik:
    print(f"[HATA] Aranacak satir bulunamadi: {arama1}")
    exit(1)
icerik = icerik.replace(arama1, yeni1, 1)
print("[OK] period log eklendi")

# 2) Tum parametreler print
arama2 = '''    tarih_bit = request.args.get('tarih_bit', '')'''
yeni2 = '''    tarih_bit = request.args.get('tarih_bit', '')
    print(f"[PT_DATA] params: lokasyon={lokasyon!r} proses={proses!r} durum={durum!r} tarih_bas={tarih_bas!r} tarih_bit={tarih_bit!r}")
'''
if arama2 not in icerik:
    print(f"[HATA] Aranacak satir 2 bulunamadi")
    exit(1)
icerik = icerik.replace(arama2, yeni2, 1)
print("[OK] params log eklendi")

# 3) SQL print _korgun_proses_rapor sonuna
arama3 = '''    # Mevcut Korgun helper'ini kullan
    from modules.common import korgun as kk
    con = kk._baglan()'''
yeni3 = '''    # Mevcut Korgun helper'ini kullan
    print(f"[PT_SQL] === SQL ===\\n{sql}\\n=========")
    from modules.common import korgun as kk
    con = kk._baglan()'''
if arama3 not in icerik:
    print(f"[HATA] Aranacak satir 3 bulunamadi")
    exit(1)
icerik = icerik.replace(arama3, yeni3, 1)
print("[OK] SQL log eklendi")

# 4) Row count print sonuna ekle
arama4 = '''        cur.close()
        return rows'''
yeni4 = '''        cur.close()
        print(f"[PT_SQL] row count = {len(rows)}")
        return rows'''
if arama4 not in icerik:
    print(f"[HATA] Aranacak satir 4 bulunamadi")
    exit(1)
icerik = icerik.replace(arama4, yeni4, 1)
print("[OK] row count log eklendi")

# 5) DEBUG ENDPOINT'leri en sona ekle
DEBUG_ENDPOINTS = '''


# =====================================================
# DEBUG ENDPOINT'LERI (gecici - sorun tespiti icin)
# =====================================================
@proses_takip_bp.route('/proses-takip/debug/ham', methods=['GET'])
def proses_takip_debug_ham():
    """Korgun Urt_con_gch tablosundan TOP 20 ham kayit (filtresiz).
    Amac: gercek lokasyon, proses, birim, cikan degerlerini gormek."""
    if not _yetki_var_mi():
        return jsonify({"hata": "yetkisiz"}), 403
    try:
        from modules.common import korgun as kk
        con = kk._baglan()
        cur = con.cursor()
        sql = """
            SELECT TOP 20
                cg.EmirNo, cg.Proses, cg.SKOD, cg.Personel,
                cg.Cikan, cg.Birim,
                CONVERT(varchar, cg.EndTarih, 20) AS EndTarih,
                cg.FisNo, cg.TarihB,
                ue.Location AS Lokasyon, ue.ModelKod
            FROM Urt_con_gch cg
            LEFT JOIN Urt_Emir ue ON ue.EmirNo = cg.EmirNo
            ORDER BY cg.EndTarih DESC
        """
        cur.execute(sql)
        cols = [c[0] for c in cur.description]
        rows = []
        for r in cur.fetchall():
            d = {}
            for i, c in enumerate(cols):
                v = r[i]
                if isinstance(v, (bytes, bytearray)):
                    try: v = v.decode('cp1254', errors='replace')
                    except: v = str(v)
                d[c] = str(v) if v is not None else None
            rows.append(d)
        cur.close()
        con.close()
        return jsonify({"ok": True, "row_count": len(rows), "kayitlar": rows})
    except Exception as e:
        return jsonify({"ok": False, "hata": str(e)}), 500


@proses_takip_bp.route('/proses-takip/debug/info', methods=['GET'])
def proses_takip_debug_info():
    """Korgun'da benzersiz lokasyon, proses, birim degerleri.
    Amac: hangi lokasyon kodlari gercek, hangi proses kodlari var?"""
    if not _yetki_var_mi():
        return jsonify({"hata": "yetkisiz"}), 403
    try:
        from modules.common import korgun as kk
        con = kk._baglan()
        cur = con.cursor()
        
        # 1) Distinct lokasyon
        cur.execute("SELECT DISTINCT TOP 50 Location FROM Urt_Emir WHERE Location IS NOT NULL ORDER BY Location")
        lokasyonlar = []
        for r in cur.fetchall():
            v = r[0]
            if isinstance(v, (bytes, bytearray)):
                try: v = v.decode('cp1254', errors='replace')
                except: v = str(v)
            lokasyonlar.append(str(v) if v else None)
        
        # 2) Distinct proses
        cur.execute("SELECT DISTINCT TOP 50 Proses FROM Urt_con_gch WHERE Proses IS NOT NULL ORDER BY Proses")
        prosesler = []
        for r in cur.fetchall():
            v = r[0]
            if isinstance(v, (bytes, bytearray)):
                try: v = v.decode('cp1254', errors='replace')
                except: v = str(v)
            prosesler.append(str(v) if v else None)
        
        # 3) Distinct birim
        cur.execute("SELECT DISTINCT TOP 20 Birim FROM Urt_con_gch WHERE Birim IS NOT NULL")
        birimler = []
        for r in cur.fetchall():
            v = r[0]
            if isinstance(v, (bytes, bytearray)):
                try: v = v.decode('cp1254', errors='replace')
                except: v = str(v)
            birimler.append(str(v) if v else None)
        
        # 4) Toplam kayit sayilari
        cur.execute("SELECT COUNT(*) FROM Urt_con_gch")
        toplam_urt = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM Urt_con_gch WHERE Cikan > 0")
        cikan_var = cur.fetchone()[0]
        
        cur.execute("SELECT COUNT(*) FROM Urt_con_gch WHERE Cikan > 0 AND Birim = 'CIFT'")
        cift_filtreli = cur.fetchone()[0]
        
        cur.execute("""SELECT COUNT(*) FROM Urt_con_gch 
                       WHERE Cikan > 0 AND Birim = 'CIFT' 
                       AND CAST(EndTarih AS DATE) >= DATEADD(day,-30,CAST(GETDATE() AS DATE))""")
        son_30_gun = cur.fetchone()[0]
        
        # 5) En son tarih
        cur.execute("SELECT MAX(EndTarih), MIN(EndTarih) FROM Urt_con_gch WHERE Cikan > 0")
        max_tar, min_tar = cur.fetchone()
        
        cur.close()
        con.close()
        
        return jsonify({
            "ok": True,
            "tablo_sayilari": {
                "Urt_con_gch_toplam": toplam_urt,
                "Cikan>0": cikan_var,
                "Cikan>0 + Birim='CIFT'": cift_filtreli,
                "Son 30 gun (Cikan>0 + CIFT)": son_30_gun,
            },
            "tarih_araligi": {
                "en_eski": str(min_tar) if min_tar else None,
                "en_yeni": str(max_tar) if max_tar else None,
            },
            "lokasyonlar": lokasyonlar,
            "proses_kodlari": prosesler,
            "birimler": birimler,
        })
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "hata": str(e), "traceback": traceback.format_exc()}), 500
'''

icerik = icerik.rstrip() + DEBUG_ENDPOINTS
print("[OK] 2 yeni debug endpoint eklendi")

with open(PT, 'w', encoding='utf-8') as f:
    f.write(icerik)
print(f"[OK] proses_takip.py guncellendi: {len(icerik)} karakter")

print("\n=== DOGRULAMA ===")
with open(PT, 'r', encoding='utf-8') as f:
    final = f.read()
print(f"  '/proses-takip/debug/ham' var mi: {'/proses-takip/debug/ham' in final}")
print(f"  '/proses-takip/debug/info' var mi: {'/proses-takip/debug/info' in final}")
print(f"  '[PT_DATA]' log var mi: {'[PT_DATA]' in final}")
print(f"  '[PT_SQL]' log var mi: {'[PT_SQL]' in final}")
print(f"\n[YEDEK]: {YEDEK}")