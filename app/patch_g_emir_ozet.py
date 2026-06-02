# ADIM G: get_emir_ozet hedef hesabı düzeltme (FisNo bazlı + fallback)
# - M tipi: Urt_Em_gch'den DISTINCT FisNo, sadece o SipNo+SKOD'dan hedef
# - Y tipi: parent ana emirden hedefi miras al
# - Fallback: hareket yoksa eski SKOD-bazlı SUM (geriye uyumlu)
import io, sys, shutil, time

PATH = r'C:\cps_dev\modules\common\korgun.py'
MARKER = '# === FAZ 4.7 HEDEF: FisNo bazli hedef ==='

with io.open(PATH, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: ADIM G zaten uygulanmis')
    sys.exit(0)

# --- M TIPI BLOK DEGISIKLIGI ---
# Eski blok: tum SKOD'taki siparis kalemlerini topluyor (14.000 hatasi)
OLD_M = """            if tip == 'M':
                # Bitmis urun - direkt siparis
                cur.execute(\"\"\"
                    SELECT sh.SipNo, sh.Miktar, sh.Tanim,
                           ISNULL(ck.CName, '-') AS CariAdi
                    FROM Siparis_Har sh
                    LEFT JOIN Siparis_Kay sk ON sk.SipNo = sh.SipNo
                    LEFT JOIN Cari_Kart ck ON ck.CKod = sh.SipNo
                    WHERE sh.SKOD = %s
                      AND LTRIM(RTRIM(ISNULL(sh.Durum,''))) = ''
                \"\"\", (model_kod,))
                for r in cur.fetchall():
                    sip_no, miktar, tanim, ca = r
                    miktar_f = float(miktar or 0)
                    hedef += miktar_f
                    siparisler.append({
                        'sip_no': sip_no,
                        'miktar': int(miktar_f) if miktar_f == int(miktar_f) else miktar_f,
                        'tanim': tanim,
                        'cari_adi': ca,
                    })
                    if not cari_adi and ca and ca != '-':
                        cari_adi = ca"""

# --- Once asil dosyada bu blok aynen var mi kontrol et (Cari_Kart JOIN tamiri) ---
# Mevcut kodda muhtemelen 'ck.CKod = sk.CariKod' yazıyor - dogrula
OLD_M_CORRECT = """            if tip == 'M':
                # Bitmis urun - direkt siparis
                cur.execute(\"\"\"
                    SELECT sh.SipNo, sh.Miktar, sh.Tanim,
                           ISNULL(ck.CName, '-') AS CariAdi
                    FROM Siparis_Har sh
                    LEFT JOIN Siparis_Kay sk ON sk.SipNo = sh.SipNo
                    LEFT JOIN Cari_Kart ck ON ck.CKod = sk.CariKod
                    WHERE sh.SKOD = %s
                      AND LTRIM(RTRIM(ISNULL(sh.Durum,''))) = ''
                \"\"\", (model_kod,))
                for r in cur.fetchall():
                    sip_no, miktar, tanim, ca = r
                    miktar_f = float(miktar or 0)
                    hedef += miktar_f
                    siparisler.append({
                        'sip_no': sip_no,
                        'miktar': int(miktar_f) if miktar_f == int(miktar_f) else miktar_f,
                        'tanim': tanim,
                        'cari_adi': ca,
                    })
                    if not cari_adi and ca and ca != '-':
                        cari_adi = ca"""

if OLD_M_CORRECT not in src:
    print('HATA: M tipi anchor blogu bulunamadi (kod degistirilmiş olabilir)')
    sys.exit(1)

# --- YENI M TIPI BLOK ---
NEW_M = """            if tip == 'M':
                # === FAZ 4.7 HEDEF: FisNo bazli hedef ===
                # Once emirin gercek FisNo'larini bul (Urt_Em_gch.FisNo = Siparis_Kay.SipNo)
                cur.execute(\"\"\"
                    SELECT DISTINCT FisNo
                    FROM Urt_Em_gch
                    WHERE EmirNo = %s
                      AND FisNo IS NOT NULL
                      AND FisNo > 0
                \"\"\", (emir_no_int,))
                _fis_listesi_47 = [r[0] for r in cur.fetchall() if r and r[0]]
                
                if _fis_listesi_47:
                    # FisNo bulundu - sadece bu siparis(ler)den hedef
                    _ph = ','.join(['%s'] * len(_fis_listesi_47))
                    cur.execute(\"\"\"
                        SELECT sh.SipNo, sh.Miktar, sh.Tanim,
                               ISNULL(ck.CName, '-') AS CariAdi
                        FROM Siparis_Har sh
                        LEFT JOIN Siparis_Kay sk ON sk.SipNo = sh.SipNo
                        LEFT JOIN Cari_Kart ck ON ck.CKod = sk.CariKod
                        WHERE sh.SKOD = %s
                          AND sh.SipNo IN (\"\"\" + _ph + \"\"\")
                          AND LTRIM(RTRIM(ISNULL(sh.Durum,''))) = ''
                    \"\"\", tuple([model_kod] + _fis_listesi_47))
                else:
                    # Fallback: hareket yok (yeni emir), eski SKOD bazli (geriye uyumlu)
                    cur.execute(\"\"\"
                        SELECT sh.SipNo, sh.Miktar, sh.Tanim,
                               ISNULL(ck.CName, '-') AS CariAdi
                        FROM Siparis_Har sh
                        LEFT JOIN Siparis_Kay sk ON sk.SipNo = sh.SipNo
                        LEFT JOIN Cari_Kart ck ON ck.CKod = sk.CariKod
                        WHERE sh.SKOD = %s
                          AND LTRIM(RTRIM(ISNULL(sh.Durum,''))) = ''
                    \"\"\", (model_kod,))
                
                for r in cur.fetchall():
                    sip_no, miktar, tanim, ca = r
                    miktar_f = float(miktar or 0)
                    hedef += miktar_f
                    siparisler.append({
                        'sip_no': sip_no,
                        'miktar': int(miktar_f) if miktar_f == int(miktar_f) else miktar_f,
                        'tanim': tanim,
                        'cari_adi': ca,
                    })
                    if not cari_adi and ca and ca != '-':
                        cari_adi = ca
                # === /FAZ 4.7 HEDEF (M tipi) ==="""

new_src = src.replace(OLD_M_CORRECT, NEW_M, 1)
if new_src == src:
    print('HATA: M tipi replace yapilmadi')
    sys.exit(1)

# --- Y TIPI BLOK DEGISIKLIGI ---
# Eski blok: parent'in SKOD'undan SUM (yine 14.000 hatasi)
OLD_Y = """            elif tip == 'Y':
                # Yari mamul - parent emir kullanan emir
                cur.execute(\"\"\"
                    SELECT TOP 5 EmirNo, Proses, SKod
                    FROM Urt_Em2Em
                    WHERE EmirNo_YM = %s
                \"\"\", (emir_no_int,))
                parent_list = cur.fetchall()
                # Parent emrin model siparis miktarini ozet olarak getir
                if parent_list:
                    parent_no = parent_list[0][0]
                    cur.execute(\"\"\"
                        SELECT TOP 1 e.ModelKod, ISNULL(m.Tanim, e.ModelKod)
                        FROM Urt_Emir e
                        LEFT JOIN Model_M m ON m.ModelKod = e.ModelKod
                        WHERE e.EmirNo = %s
                    \"\"\", (parent_no,))
                    p_row = cur.fetchone()
                    if p_row:
                        p_model = p_row[0]
                        cur.execute(\"\"\"
                            SELECT COALESCE(SUM(Miktar), 0)
                            FROM Siparis_Har
                            WHERE SKOD = %s
                              AND LTRIM(RTRIM(ISNULL(Durum,''))) = ''
                        \"\"\", (p_model,))
                        hedef = float(cur.fetchone()[0] or 0)"""

if OLD_Y not in new_src:
    print('HATA: Y tipi anchor blogu bulunamadi')
    sys.exit(1)

# --- YENI Y TIPI BLOK ---
# Parent emirin hedefini ayni mantiakla bul (FisNo bazli + fallback)
NEW_Y = """            elif tip == 'Y':
                # === FAZ 4.7 HEDEF: Y tipi parent hedefi miras alir ===
                # Parent emiri bul
                cur.execute(\"\"\"
                    SELECT TOP 5 EmirNo, Proses, SKod
                    FROM Urt_Em2Em
                    WHERE EmirNo_YM = %s
                \"\"\", (emir_no_int,))
                parent_list = cur.fetchall()
                if parent_list:
                    parent_no = parent_list[0][0]
                    # Parent emirin modelini al
                    cur.execute(\"\"\"
                        SELECT TOP 1 e.ModelKod
                        FROM Urt_Emir e
                        WHERE e.EmirNo = %s
                    \"\"\", (parent_no,))
                    p_row = cur.fetchone()
                    if p_row:
                        p_model = p_row[0]
                        # Parent'in FisNo'larini bul
                        cur.execute(\"\"\"
                            SELECT DISTINCT FisNo
                            FROM Urt_Em_gch
                            WHERE EmirNo = %s
                              AND FisNo IS NOT NULL
                              AND FisNo > 0
                        \"\"\", (parent_no,))
                        _pfis_47 = [r[0] for r in cur.fetchall() if r and r[0]]
                        
                        if _pfis_47:
                            # Parent'in gercek siparisleri uzerinden hedef
                            _ph_y = ','.join(['%s'] * len(_pfis_47))
                            cur.execute(\"\"\"
                                SELECT COALESCE(SUM(Miktar), 0)
                                FROM Siparis_Har
                                WHERE SKOD = %s
                                  AND SipNo IN (\"\"\" + _ph_y + \"\"\")
                                  AND LTRIM(RTRIM(ISNULL(Durum,''))) = ''
                            \"\"\", tuple([p_model] + _pfis_47))
                        else:
                            # Fallback: parent'in de hareketi yoksa eski mantik
                            cur.execute(\"\"\"
                                SELECT COALESCE(SUM(Miktar), 0)
                                FROM Siparis_Har
                                WHERE SKOD = %s
                                  AND LTRIM(RTRIM(ISNULL(Durum,''))) = ''
                            \"\"\", (p_model,))
                        hedef = float(cur.fetchone()[0] or 0)
                # === /FAZ 4.7 HEDEF (Y tipi) ==="""

new_src2 = new_src.replace(OLD_Y, NEW_Y, 1)
if new_src2 == new_src:
    print('HATA: Y tipi replace yapilmadi')
    sys.exit(1)

# Yedek
bak = PATH + '.bak_pre_g_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(PATH, bak)
print('Yedek: ' + bak)

with io.open(PATH, 'w', encoding='utf-8') as f:
    f.write(new_src2)

artis = len(new_src2) - len(src)
print('OK: ADIM G hedef duzeltildi (' + str(artis) + ' byte degisim)')
print('M tipi: FisNo bazli hedef + fallback')
print('Y tipi: parent emir hedefi miras + fallback')