# -*- coding: utf-8 -*-
"""
setup_faz46_b1_sablon_dogru.py
------------------------------
ADIM B1 - DOGRU SABLON BACKEND.

CLEANUP:
  1) hedef.js'ten 4 yanlis IIFE kaldir
  2) hedef/routes.py'den eski FAZ 4.6 B endpoint blogu kaldir
  3) mock_data.db'den eski bos sablon_genel + sablon_emir_override DROP

YENI:
  4) mock_data.db: sablon + sablon_proses tablolari
  5) modules/common/korgun.py: get_siparis_emirleri() helper
  6) modules/hedef/routes.py: 7 yeni endpoint
       GET  /hedef/sablon/liste            (her sablon prosesleriyle)
       POST /hedef/sablon/ekle             (sablon_adi + prosesler[])
       POST /hedef/sablon/guncelle/<id>
       POST /hedef/sablon/sil/<id>
       GET  /hedef/sablon/proses-onerileri (dropdown kaynak)
       GET  /hedef/siparis/emirler?sipno=  (Korgun proxy: ana+alt)
       POST /hedef/sablon/uygula           (emir_no + sablon_id -> emir_alt_proses)

DOKUNMAZ:
  - uretim_kaydet (kural: sablon hedef olusturmaz)
  - vardiya/mesai
  - PLAN, RAPOR, ONAYLAR, GECMIS, DOGRULAMA endpoint ve UI'lari
  - emir_alt_proses semasi (mevcut tutulur, sadece INSERT yapilir)
"""

import os
import re
import shutil
import datetime
import sys
import ast
import sqlite3

CPS_ROOT = r"C:\cps_dev"
DB_PATH = os.path.join(CPS_ROOT, "mock_data.db")
HEDEF_ROUTES = os.path.join(CPS_ROOT, "modules", "hedef", "routes.py")
KORGUN_PY = os.path.join(CPS_ROOT, "modules", "common", "korgun.py")
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

BE_OLD_MARKER = "# === FAZ 4.6 B: SABLON ENDPOINTS ==="
BE_NEW_MARKER = "# === FAZ 4.6 B1 (DOGRU): SABLON ENDPOINTS ==="
KORGUN_MARKER = "# === FAZ 4.6 B1: get_siparis_emirleri ==="

# JS cleanup marker'lari (her IIFE'in icindeki ayirt edici metin)
JS_CLEANUP_MARKERS = [
    "CPS LOCAL - FAZ 4.6 B: Sablon UI",
    "CPS LOCAL - FAZ 4.6 B FIX: Eski 'UI.3'",
    "CPS LOCAL - FAZ 4.6 B FIX v2",
    "CPS LOCAL - FAZ 4.6 B FIX v3",
]


# =====================================================================
# DB MIGRATION
# =====================================================================
DB_MIGRATIONS = [
    "DROP INDEX IF EXISTS idx_seo_lookup",
    "DROP INDEX IF EXISTS idx_sg_lookup",
    "DROP TABLE IF EXISTS sablon_emir_override",
    "DROP TABLE IF EXISTS sablon_genel",
    """
    CREATE TABLE IF NOT EXISTS sablon (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sablon_adi TEXT NOT NULL UNIQUE COLLATE NOCASE,
        aciklama TEXT,
        aktif INTEGER NOT NULL DEFAULT 1 CHECK(aktif IN (0,1)),
        olusturan_id INTEGER,
        olusturan_ad TEXT,
        olusturma TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        guncelleme TEXT,
        guncelleyen_id INTEGER,
        guncelleyen_ad TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sablon_proses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sablon_id INTEGER NOT NULL,
        proses_adi TEXT NOT NULL,
        siralama INTEGER NOT NULL DEFAULT 0,
        olusturma TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        UNIQUE(sablon_id, proses_adi),
        FOREIGN KEY (sablon_id) REFERENCES sablon(id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sp_sablon ON sablon_proses(sablon_id, siralama)",
]


# =====================================================================
# KORGUN HELPER (modules/common/korgun.py sonuna ekle)
# =====================================================================
KORGUN_BLOCK = '''


# === FAZ 4.6 B1: get_siparis_emirleri ===
def get_siparis_emirleri(sip_no):
    """Bir siparise ait tum emirler: ana (Tip='M') + alt/yari (Tip='Y').

    Akis:
      1. Siparis_Har -> SKOD listesi -> Urt_Emir (Tip='M') -> ana emirler
      2. Her ana emir icin Urt_Em2Em -> Urt_Emir (Tip='Y') -> yari mamul emirler
    """
    try:
        sip_no_int = int(sip_no)
        if sip_no_int <= 0:
            return {'ok': False, 'hata': 'gecersiz_sipno', 'emirler': []}
    except Exception:
        return {'ok': False, 'hata': 'gecersiz_sipno', 'emirler': []}

    try:
        con = _baglan()
        try:
            cur = con.cursor()

            # 1) Ana emirler (Tip='M')
            cur.execute("""
                SELECT DISTINCT
                    e.EmirNo, e.ModelKod, e.Tip,
                    ISNULL(m.Tanim, e.ModelKod) AS ModelAdi,
                    e.Location,
                    LTRIM(RTRIM(ISNULL(e.Durum,''))) AS Durum,
                    e.YazSay,
                    sh.SipNo,
                    sh.Miktar AS HedefMiktar
                FROM Siparis_Har sh
                INNER JOIN Urt_Emir e ON e.ModelKod = sh.SKOD
                LEFT JOIN Model_M m ON m.ModelKod = e.ModelKod
                WHERE sh.SipNo = %s
                  AND LTRIM(RTRIM(ISNULL(sh.Durum,''))) = ''
                  AND UPPER(LTRIM(RTRIM(ISNULL(e.Tip,'')))) = 'M'
                ORDER BY e.EmirNo
            """, (sip_no_int,))
            ana_rows = cur.fetchall()
            ana_cols = [d[0] for d in cur.description]
            ana_dicts = [dict(zip(ana_cols, r)) for r in ana_rows]
            ana_emir_nos = [int(d['EmirNo']) for d in ana_dicts]

            # 2) Yari mamul emirler (Tip='Y') - Urt_Em2Em ile parent eslestirme
            yari_dicts = []
            if ana_emir_nos:
                placeholders = ','.join(['%s'] * len(ana_emir_nos))
                cur.execute(f"""
                    SELECT
                        e.EmirNo, e.ModelKod, e.Tip,
                        ISNULL(m.Tanim, e.ModelKod) AS ModelAdi,
                        e.Location,
                        LTRIM(RTRIM(ISNULL(e.Durum,''))) AS Durum,
                        e.YazSay,
                        em2em.EmirNo AS ParentEmirNo
                    FROM Urt_Em2Em em2em
                    INNER JOIN Urt_Emir e ON e.EmirNo = em2em.EmirNo_YM
                    LEFT JOIN Model_M m ON m.ModelKod = e.ModelKod
                    WHERE em2em.EmirNo IN ({placeholders})
                      AND UPPER(LTRIM(RTRIM(ISNULL(e.Tip,'')))) = 'Y'
                    ORDER BY e.EmirNo
                """, tuple(ana_emir_nos))
                yari_rows = cur.fetchall()
                yari_cols = [d[0] for d in cur.description]
                yari_dicts = [dict(zip(yari_cols, r)) for r in yari_rows]

            # Sonuc liste
            emirler = []
            for d in ana_dicts:
                hm = d.get('HedefMiktar')
                emirler.append({
                    'EmirNo': int(d['EmirNo']),
                    'ModelKod': d.get('ModelKod'),
                    'ModelAdi': d.get('ModelAdi'),
                    'EmirTip': 'ana',
                    'TipKod': (d.get('Tip') or '').strip(),
                    'Location': (d.get('Location') or '').strip() if d.get('Location') else None,
                    'Durum': d.get('Durum'),
                    'HedefMiktar': float(hm) if hm is not None else None,
                    'SipNo': int(d.get('SipNo')) if d.get('SipNo') is not None else sip_no_int,
                    'ParentEmirNo': None,
                })
            for d in yari_dicts:
                emirler.append({
                    'EmirNo': int(d['EmirNo']),
                    'ModelKod': d.get('ModelKod'),
                    'ModelAdi': d.get('ModelAdi'),
                    'EmirTip': 'alt',
                    'TipKod': (d.get('Tip') or '').strip(),
                    'Location': (d.get('Location') or '').strip() if d.get('Location') else None,
                    'Durum': d.get('Durum'),
                    'HedefMiktar': None,
                    'SipNo': sip_no_int,
                    'ParentEmirNo': int(d.get('ParentEmirNo')) if d.get('ParentEmirNo') is not None else None,
                })

            cur.close()
            return {
                'ok': True,
                'siparis_no': str(sip_no_int),
                'emir_sayisi': len(emirler),
                'ana_sayisi': len(ana_dicts),
                'alt_sayisi': len(yari_dicts),
                'emirler': emirler,
            }
        finally:
            con.close()
    except Exception as e:
        return {'ok': False, 'hata': 'sistem_hatasi',
                'mesaj': f'{type(e).__name__}: {str(e)[:200]}',
                'emirler': []}
'''


# =====================================================================
# BACKEND BLOCK (hedef/routes.py sonuna)
# =====================================================================
BACKEND_BLOCK = '''


# === FAZ 4.6 B1 (DOGRU): SABLON ENDPOINTS ===
# Sablon = proses listesi. Hedef ve vardiyaya dokunulmaz.
# Sipariste -> ana+alt emirler -> her gruba sablon uygula -> emir_alt_proses

def _sablon_session():
    from flask import session
    uid = (session.get('user_id') or session.get('kullanici_id') or
           session.get('id') or 0)
    uad = (session.get('user_name') or session.get('kullanici_ad') or
           session.get('ad') or session.get('username') or 'Sistem')
    return uid, uad


# --- 1) Sablon liste (her sablon proses listesi ile) ---
@hedef_bp.route('/sablon/liste', methods=['GET'])
def hedef_sablon_liste():
    import sqlite3
    from flask import jsonify
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        sablonlar = conn.execute("""
            SELECT id, sablon_adi, aciklama, olusturan_ad, olusturma, guncelleme
              FROM sablon WHERE aktif=1
             ORDER BY sablon_adi COLLATE NOCASE
        """).fetchall()
        sonuc = []
        for s in sablonlar:
            d = dict(s)
            prs = conn.execute("""
                SELECT proses_adi, siralama
                  FROM sablon_proses
                 WHERE sablon_id=?
                 ORDER BY siralama, id
            """, (s['id'],)).fetchall()
            d['prosesler'] = [p['proses_adi'] for p in prs]
            d['proses_sayisi'] = len(prs)
            sonuc.append(d)
        conn.close()
        return jsonify({'ok': True, 'kayitlar': sonuc})
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e), 'kayitlar': []}), 500


def _proses_temizle(prosesler):
    """List of (str veya {proses_adi}) -> tekil non-empty string list"""
    if not isinstance(prosesler, list):
        return []
    out = []
    seen = set()
    for p in prosesler:
        if isinstance(p, str):
            v = p.strip()
        elif isinstance(p, dict):
            v = (p.get('proses_adi') or '').strip()
        else:
            continue
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


# --- 2) Sablon ekle ---
@hedef_bp.route('/sablon/ekle', methods=['POST'])
def hedef_sablon_ekle():
    import sqlite3
    from flask import jsonify, request
    data = request.get_json(silent=True) or {}
    sablon_adi = (data.get('sablon_adi') or '').strip()
    aciklama = (data.get('aciklama') or '').strip() or None
    prosesler = _proses_temizle(data.get('prosesler') or [])

    if not sablon_adi:
        return jsonify({'ok': False, 'mesaj': 'sablon_adi zorunlu'}), 400
    if not prosesler:
        return jsonify({'ok': False, 'mesaj': 'En az 1 proses gerekli'}), 400

    uid, uad = _sablon_session()
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute("""
            INSERT INTO sablon (sablon_adi, aciklama, olusturan_id, olusturan_ad)
            VALUES (?, ?, ?, ?)
        """, (sablon_adi, aciklama, uid, uad))
        sid = cur.lastrowid
        for i, p in enumerate(prosesler):
            try:
                conn.execute("""
                    INSERT INTO sablon_proses (sablon_id, proses_adi, siralama)
                    VALUES (?, ?, ?)
                """, (sid, p, i + 1))
            except sqlite3.IntegrityError:
                pass
        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'id': sid, 'mesaj': 'Sablon eklendi'})
    except sqlite3.IntegrityError as e:
        if 'UNIQUE' in str(e).upper():
            return jsonify({'ok': False, 'hata': 'duplicate',
                            'mesaj': 'Bu sablon adi zaten var'}), 409
        return jsonify({'ok': False, 'mesaj': str(e)}), 400
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)}), 500


# --- 3) Sablon guncelle ---
@hedef_bp.route('/sablon/guncelle/<int:sid>', methods=['POST'])
def hedef_sablon_guncelle(sid):
    import sqlite3
    from flask import jsonify, request
    data = request.get_json(silent=True) or {}
    sablon_adi = (data.get('sablon_adi') or '').strip()
    aciklama = (data.get('aciklama') or '').strip() or None
    prosesler_input = data.get('prosesler')  # None ise dokunma

    if not sablon_adi:
        return jsonify({'ok': False, 'mesaj': 'sablon_adi zorunlu'}), 400

    uid, uad = _sablon_session()
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute("""
            UPDATE sablon
               SET sablon_adi=?, aciklama=?,
                   guncelleme=datetime('now','localtime'),
                   guncelleyen_id=?, guncelleyen_ad=?
             WHERE id=? AND aktif=1
        """, (sablon_adi, aciklama, uid, uad, sid))
        if cur.rowcount == 0:
            conn.close()
            return jsonify({'ok': False, 'mesaj': 'Kayit bulunamadi'}), 404

        if prosesler_input is not None:
            prosesler = _proses_temizle(prosesler_input)
            conn.execute("DELETE FROM sablon_proses WHERE sablon_id=?", (sid,))
            for i, p in enumerate(prosesler):
                conn.execute("""
                    INSERT INTO sablon_proses (sablon_id, proses_adi, siralama)
                    VALUES (?, ?, ?)
                """, (sid, p, i + 1))

        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'mesaj': 'Guncellendi'})
    except sqlite3.IntegrityError:
        return jsonify({'ok': False, 'hata': 'duplicate',
                        'mesaj': 'Sablon adi zaten var'}), 409
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)}), 500


# --- 4) Sablon sil (soft) ---
@hedef_bp.route('/sablon/sil/<int:sid>', methods=['POST'])
def hedef_sablon_sil(sid):
    import sqlite3
    from flask import jsonify
    uid, uad = _sablon_session()
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute("""
            UPDATE sablon
               SET aktif=0, guncelleme=datetime('now','localtime'),
                   guncelleyen_id=?, guncelleyen_ad=?
             WHERE id=? AND aktif=1
        """, (uid, uad, sid))
        conn.commit()
        affected = cur.rowcount
        conn.close()
        if affected == 0:
            return jsonify({'ok': False, 'mesaj': 'Kayit bulunamadi'}), 404
        return jsonify({'ok': True, 'mesaj': 'Silindi'})
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)}), 500


# --- 5) Proses dropdown kaynak ---
@hedef_bp.route('/sablon/proses-onerileri', methods=['GET'])
def hedef_sablon_proses_onerileri():
    import sqlite3
    from flask import jsonify
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute("""
            SELECT proses_adi FROM (
                SELECT DISTINCT proses_adi FROM emir_alt_proses
                 WHERE aktif=1 AND proses_adi IS NOT NULL AND TRIM(proses_adi)!=''
                UNION
                SELECT DISTINCT proses_adi FROM uretim_kayit
                 WHERE proses_adi IS NOT NULL AND TRIM(proses_adi)!=''
                UNION
                SELECT DISTINCT proses_adi FROM sablon_proses
                 WHERE proses_adi IS NOT NULL AND TRIM(proses_adi)!=''
            )
             ORDER BY proses_adi COLLATE NOCASE
        """).fetchall()
        conn.close()
        return jsonify({
            'ok': True,
            'kayitlar': [{'proses_adi': r[0]} for r in rows]
        })
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e), 'kayitlar': []}), 500


# --- 6) Siparis -> Emirler (Korgun proxy) ---
@hedef_bp.route('/siparis/emirler', methods=['GET'])
def hedef_siparis_emirler():
    from flask import jsonify, request
    sipno = (request.args.get('sipno') or '').strip()
    if not sipno:
        return jsonify({'ok': False, 'mesaj': 'sipno zorunlu', 'emirler': []}), 400
    try:
        from modules.common import korgun as _kk
        sonuc = _kk.get_siparis_emirleri(sipno)
        return jsonify(sonuc)
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e), 'emirler': []}), 500


# --- 7) Sablon uygula (emir -> emir_alt_proses) ---
@hedef_bp.route('/sablon/uygula', methods=['POST'])
def hedef_sablon_uygula():
    import sqlite3
    from flask import jsonify, request
    data = request.get_json(silent=True) or {}
    emir_no = str(data.get('emir_no') or '').strip()
    sablon_id = data.get('sablon_id')

    if not emir_no:
        return jsonify({'ok': False, 'mesaj': 'emir_no zorunlu'}), 400
    try:
        sablon_id = int(sablon_id)
    except Exception:
        return jsonify({'ok': False, 'mesaj': 'sablon_id zorunlu'}), 400

    uid, uad = _sablon_session()
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        sablon = conn.execute(
            "SELECT id, sablon_adi FROM sablon WHERE id=? AND aktif=1",
            (sablon_id,)
        ).fetchone()
        if not sablon:
            conn.close()
            return jsonify({'ok': False, 'mesaj': 'Sablon bulunamadi'}), 404

        prs = conn.execute("""
            SELECT proses_adi, siralama FROM sablon_proses
             WHERE sablon_id=?
             ORDER BY siralama, id
        """, (sablon_id,)).fetchall()
        if not prs:
            conn.close()
            return jsonify({'ok': False, 'mesaj': 'Sablonda proses yok'}), 400

        kaynak = 'sablon:' + sablon['sablon_adi']
        max_row = conn.execute(
            "SELECT COALESCE(MAX(siralama), 0) FROM emir_alt_proses WHERE emir_no=?",
            (emir_no,)
        ).fetchone()
        max_sira = int(max_row[0] or 0)

        eklenen = []
        atlanan = []
        for p in prs:
            pa = p['proses_adi']
            mevcut = conn.execute("""
                SELECT id FROM emir_alt_proses
                 WHERE emir_no=? AND proses_adi=? AND aktif=1
            """, (emir_no, pa)).fetchone()
            if mevcut:
                atlanan.append({'proses_adi': pa, 'mevcut_id': mevcut[0]})
                continue
            max_sira += 1
            cur = conn.execute("""
                INSERT INTO emir_alt_proses
                    (emir_no, proses_adi, siralama, aktif, kaynak,
                     olusturan_id, olusturan_ad)
                VALUES (?, ?, ?, 1, ?, ?, ?)
            """, (emir_no, pa, max_sira, kaynak, uid, uad))
            eklenen.append({
                'id': cur.lastrowid,
                'proses_adi': pa,
                'siralama': max_sira,
            })

        conn.commit()
        conn.close()
        return jsonify({
            'ok': True,
            'emir_no': emir_no,
            'sablon_id': sablon_id,
            'sablon_adi': sablon['sablon_adi'],
            'eklenen_sayisi': len(eklenen),
            'atlanan_sayisi': len(atlanan),
            'eklenen': eklenen,
            'atlanan': atlanan,
        })
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)}), 500
'''


# =====================================================================
# Helpers
# =====================================================================

def backup(path):
    if not os.path.exists(path):
        return None
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = path + f'.bak_{ts}'
    shutil.copy2(path, bp)
    return bp


def js_iife_kaldir(src, marker):
    """marker icindeki ilk IIFE'i sil. /* ... */ yorum + })(); kapanis."""
    idx = src.find(marker)
    if idx == -1:
        return src, False

    # Geriye dogru /* yorum baslangici ara
    start = src.rfind('/*', 0, idx)
    if start == -1:
        return src, False

    # Ileri dogru })(); ara
    end_marker = '})();'
    end_idx = src.find(end_marker, idx)
    if end_idx == -1:
        return src, False
    end = end_idx + len(end_marker)

    # Sonraki newline'i da sil
    while end < len(src) and src[end] in '\n\r':
        end += 1

    return src[:start] + src[end:], True


# =====================================================================
# Adimlar
# =====================================================================

def adim_db_migrate():
    print()
    print("=" * 64)
    print("1/4 DB MIGRATION: mock_data.db")
    print("=" * 64)
    if not os.path.exists(DB_PATH):
        print(f"  [HATA] {DB_PATH} bulunamadi.")
        return False

    bp = backup(DB_PATH)
    if bp:
        print(f"  [OK] Yedek: {bp}")

    # Once eski tablolari kontrol et (kayit varsa uyari ver)
    try:
        conn = sqlite3.connect(DB_PATH)
        for tbl in ('sablon_genel', 'sablon_emir_override'):
            try:
                cnt = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                if cnt > 0:
                    print(f"  [UYARI] {tbl}'de {cnt} kayit var - yine de DROP edilecek (yedek alindi).")
            except sqlite3.OperationalError:
                pass  # tablo yok, normal

        for sql in DB_MIGRATIONS:
            conn.execute(sql)
        conn.commit()

        tablolar = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('sablon','sablon_proses','sablon_genel','sablon_emir_override')"
        ).fetchall()
        conn.close()
        print(f"  [OK] Var olan tablolar: {[t[0] for t in tablolar]}")
        return True
    except Exception as e:
        print(f"  [HATA] migration: {e}")
        return False


def adim_korgun():
    print()
    print("=" * 64)
    print("2/4 KORGUN: modules/common/korgun.py")
    print("=" * 64)
    if not os.path.exists(KORGUN_PY):
        print(f"  [HATA] {KORGUN_PY} bulunamadi.")
        return False
    with open(KORGUN_PY, 'r', encoding='utf-8') as f:
        src = f.read()
    if KORGUN_MARKER in src:
        print("  [BILGI] get_siparis_emirleri zaten ekli.")
        return True

    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += KORGUN_BLOCK

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] parse: {e}")
        return False

    bp = backup(KORGUN_PY)
    print(f"  [OK] Yedek: {bp}")
    with open(KORGUN_PY, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] get_siparis_emirleri() helper eklendi.")
    return True


def adim_backend():
    print()
    print("=" * 64)
    print("3/4 BACKEND: modules/hedef/routes.py")
    print("=" * 64)
    if not os.path.exists(HEDEF_ROUTES):
        print(f"  [HATA] {HEDEF_ROUTES} bulunamadi.")
        return False
    with open(HEDEF_ROUTES, 'r', encoding='utf-8') as f:
        src = f.read()

    bp = backup(HEDEF_ROUTES)
    print(f"  [OK] Yedek: {bp}")

    # 1) Eski FAZ 4.6 B blokunu kaldir
    if BE_OLD_MARKER in src:
        idx = src.find(BE_OLD_MARKER)
        # Geriye dogru bos satirlari sil
        while idx > 0 and src[idx-1] in '\n\r ':
            idx -= 1
        src = src[:idx]
        if not src.endswith('\n'):
            src += '\n'
        print("  [OK] Eski FAZ 4.6 B endpoint blogu kaldirildi.")
    else:
        print("  [BILGI] Eski FAZ 4.6 B blogu yok (zaten kaldirilmis).")

    # 2) Yeni B1 marker varsa skip
    if BE_NEW_MARKER in src:
        print("  [BILGI] Yeni B1 endpoint'leri zaten ekli.")
        with open(HEDEF_ROUTES, 'w', encoding='utf-8') as f:
            f.write(src)
        return True

    # 3) Yeni blok ekle
    new_src = src + BACKEND_BLOCK

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] parse: {e}")
        return False

    with open(HEDEF_ROUTES, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] 7 yeni endpoint eklendi (sablon CRUD + siparis + uygula).")
    return True


def adim_js_cleanup():
    print()
    print("=" * 64)
    print("4/4 JS CLEANUP: static/js/hedef.js")
    print("=" * 64)
    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} bulunamadi.")
        return False
    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()

    bp = backup(JS_PATH)
    print(f"  [OK] Yedek: {bp}")

    silinen = 0
    for marker in JS_CLEANUP_MARKERS:
        src, ok = js_iife_kaldir(src, marker)
        if ok:
            silinen += 1
            print(f"  [OK] Kaldirildi: '{marker[:50]}...'")
        else:
            print(f"  [BILGI] Bulunamadi (zaten silinmis?): '{marker[:50]}...'")

    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(src)
    print(f"  [OK] Toplam {silinen} IIFE kaldirildi.")
    return True


def main():
    print("=" * 64)
    print("FAZ 4.6 B1 - DOGRU SABLON BACKEND (cleanup + yeni)")
    print("=" * 64)
    print("CPS_KURALLAR uyum:")
    print("  - uretim_kaydet'e dokunulmuyor (sablon hedef olusturmaz)")
    print("  - Vardiya/mesai sistemine dokunulmuyor")
    print("  - Korgun read-only (yeni helper sadece SELECT)")
    print("  - mock_data.db yeni tablo (eski boş tablolar DROP edildi)")
    print("  - Frontend cleanup: 4 yanlis IIFE silindi")

    if not os.path.exists(CPS_ROOT):
        print(f"  [HATA] {CPS_ROOT} bulunamadi.")
        return 1

    ok1 = adim_db_migrate()
    ok2 = adim_korgun()
    ok3 = adim_backend()
    ok4 = adim_js_cleanup()

    print()
    print("=" * 64)
    if ok1 and ok2 and ok3 and ok4:
        print("ADIM B1 TAMAM.")
        print("=" * 64)
        print()
        print("YAPILACAK:")
        print("  1) CPS sunucusunu yeniden baslat (Korgun helper ve endpoint icin)")
        print("  2) Browser'da Ctrl+F5")
        print("  3) /hedef/ -> SABLON sekmesi")
        print("     -> Eski 'UI.3 asamasinda' metni geri donmus olabilir (B2'de duzelir)")
        print("     -> Bu beklenen, simdilik backend test ediyoruz")
        print()
        print("BACKEND TEST (Browser DevTools Console):")
        print()
        print("  // 1) Sablon liste (bos beklenir)")
        print("  fetch('/hedef/sablon/liste',{credentials:'include'})")
        print("    .then(r=>r.json()).then(console.log)")
        print()
        print("  // 2) Proses onerileri (mevcut sistem proses adlari)")
        print("  fetch('/hedef/sablon/proses-onerileri',{credentials:'include'})")
        print("    .then(r=>r.json()).then(console.log)")
        print()
        print("  // 3) Yeni sablon ekle (Atki LCW)")
        print("  fetch('/hedef/sablon/ekle',{")
        print("    method:'POST',credentials:'include',")
        print("    headers:{'Content-Type':'application/json'},")
        print("    body:JSON.stringify({")
        print("      sablon_adi:'Atki LCW',")
        print("      aciklama:'Test',")
        print("      prosesler:['Capak','Rivet Takma','Tampon Baski','Atki Silme']")
        print("    })")
        print("  }).then(r=>r.json()).then(console.log)")
        print()
        print("  // 4) Liste (1 sablon goster)")
        print("  fetch('/hedef/sablon/liste',{credentials:'include'})")
        print("    .then(r=>r.json()).then(console.log)")
        print()
        print("  // 5) KORGUN: sipariste emirleri (33558)")
        print("  fetch('/hedef/siparis/emirler?sipno=33558',{credentials:'include'})")
        print("    .then(r=>r.json()).then(console.log)")
        print("  // Beklenen: 110626 ana + (varsa) yari mamul emirler")
        print()
        print("  // 6) Sablon uygula (110626 emrine 'Atki LCW' sablonu)")
        print("  // Once liste'den sablon_id'yi al, sonra:")
        print("  fetch('/hedef/sablon/uygula',{")
        print("    method:'POST',credentials:'include',")
        print("    headers:{'Content-Type':'application/json'},")
        print("    body:JSON.stringify({emir_no:'110626',sablon_id:1})")
        print("  }).then(r=>r.json()).then(console.log)")
        print()
        print("  // 7) /uretim/emir/110626/prosesler -> 4 yeni proses gorunmeli")
        print("  fetch('/uretim/emir/110626/prosesler',{credentials:'include'})")
        print("    .then(r=>r.json()).then(console.log)")
        print()
        print("Hepsi calisiyorsa: 'devam B2' de, frontend UI yapayim.")
        return 0
    print("BAZI ADIMLAR BASARISIZ.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
