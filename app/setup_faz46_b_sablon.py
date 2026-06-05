# -*- coding: utf-8 -*-
"""
setup_faz46_b_sablon.py
-----------------------
FAZ 4.6 ADIM B - Sablon sistemi (B1 backend + B2 frontend birlikte)

B1) Backend:
  - mock_data.db'ye 2 yeni tablo: sablon_genel, sablon_emir_override
  - modules/hedef/routes.py sonuna 10 endpoint:
      GET  /hedef/sablon/proses-listesi    (dropdown kaynak)
      GET  /hedef/sablon/genel/liste
      POST /hedef/sablon/genel/ekle
      POST /hedef/sablon/genel/guncelle/<id>
      POST /hedef/sablon/genel/sil/<id>
      GET  /hedef/sablon/override/liste?emir_no=
      POST /hedef/sablon/override/ekle
      POST /hedef/sablon/override/guncelle/<id>
      POST /hedef/sablon/override/sil/<id>
      GET  /hedef/sablon/oner-toplu?emir_no=&vardiya=

B2) Frontend:
  - hedef.js'e IIFE: SABLON pane'i dinamik render
  - 2 alt sekme: GENEL | EMIR OZEL OVERRIDE
  - Tablo + filtre + ekle/duzenle/sil modal
  - proses_adi DROPDOWN (manuel string yok)

CPS_KURALLAR uyum:
  ✓ uretim_kaydet'e dokunulmuyor (madde: sablon sadece oneri)
  ✓ Yeni tablo (madde 8)
  ✓ Korgun dokunulmuyor (madde 1, 8)
  ✓ MES v2 yok (madde 9)
"""

import os
import shutil
import datetime
import sys
import ast
import sqlite3

CPS_ROOT = r"C:\cps_dev"
DB_PATH = os.path.join(CPS_ROOT, "mock_data.db")
HEDEF_ROUTES = os.path.join(CPS_ROOT, "modules", "hedef", "routes.py")
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

BE_MARKER = "# === FAZ 4.6 B: SABLON ENDPOINTS ==="
JS_MARKER = "[CPS LOCAL] FAZ 4.6 B sablon"


# =====================================================================
# 1) DB MIGRATION
# =====================================================================
MIGRATIONS = [
    """
    CREATE TABLE IF NOT EXISTS sablon_genel (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proses_adi TEXT NOT NULL COLLATE NOCASE,
        vardiya TEXT NOT NULL CHECK(vardiya IN ('gunduz','gece')),
        hedef_cift INTEGER NOT NULL CHECK(hedef_cift > 0),
        aciklama TEXT,
        aktif INTEGER NOT NULL DEFAULT 1 CHECK(aktif IN (0,1)),
        olusturan_id INTEGER,
        olusturan_ad TEXT,
        olusturma TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        guncelleme TEXT,
        guncelleyen_id INTEGER,
        guncelleyen_ad TEXT,
        UNIQUE(proses_adi, vardiya)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sablon_emir_override (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        emir_no TEXT NOT NULL,
        emir_alt_proses_id INTEGER NOT NULL,
        proses_adi_snapshot TEXT,
        vardiya TEXT NOT NULL CHECK(vardiya IN ('gunduz','gece')),
        hedef_cift INTEGER NOT NULL CHECK(hedef_cift > 0),
        aciklama TEXT,
        aktif INTEGER NOT NULL DEFAULT 1 CHECK(aktif IN (0,1)),
        olusturan_id INTEGER,
        olusturan_ad TEXT,
        olusturma TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        guncelleme TEXT,
        guncelleyen_id INTEGER,
        guncelleyen_ad TEXT,
        UNIQUE(emir_no, emir_alt_proses_id, vardiya)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_seo_lookup ON sablon_emir_override(emir_no, emir_alt_proses_id, vardiya, aktif)",
    "CREATE INDEX IF NOT EXISTS idx_sg_lookup ON sablon_genel(proses_adi, vardiya, aktif)",
]


# =====================================================================
# 2) BACKEND BLOCK (routes.py sonuna)
# =====================================================================
BACKEND_BLOCK = '''


# === FAZ 4.6 B: SABLON ENDPOINTS ===
# Sablon sistemi: hibrit (genel + emir override)
# uretim_kaydet'e DOKUNMAZ - sadece oneri amacli lookup

def _sablon_session():
    """Login kullanicinin id+ad bilgisi."""
    from flask import session
    uid = (session.get('user_id') or session.get('kullanici_id') or
           session.get('id') or 0)
    uad = (session.get('user_name') or session.get('kullanici_ad') or
           session.get('ad') or session.get('username') or 'Sistem')
    return uid, uad


# --- 1) Dropdown kaynak: birlesik proses_adi listesi ---
@hedef_bp.route('/sablon/proses-listesi', methods=['GET'])
def hedef_sablon_proses_listesi():
    """GET /hedef/sablon/proses-listesi - emir_alt_proses + uretim_kayit DISTINCT."""
    import sqlite3
    from flask import jsonify
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT proses_adi,
                   MAX(CASE WHEN src='eap' THEN 1 ELSE 0 END) AS in_eap,
                   MAX(CASE WHEN src='uk' THEN 1 ELSE 0 END) AS in_uk
              FROM (
                SELECT DISTINCT proses_adi, 'eap' AS src
                  FROM emir_alt_proses
                 WHERE aktif=1
                   AND proses_adi IS NOT NULL
                   AND TRIM(proses_adi) != ''
                UNION
                SELECT DISTINCT proses_adi, 'uk' AS src
                  FROM uretim_kayit
                 WHERE proses_adi IS NOT NULL
                   AND TRIM(proses_adi) != ''
              )
             GROUP BY proses_adi
             ORDER BY proses_adi COLLATE NOCASE ASC
        """).fetchall()
        conn.close()
        return jsonify({
            'ok': True, 'success': True,
            'kayitlar': [dict(r) for r in rows]
        })
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e), 'kayitlar': []}), 500


# --- 2) GENEL SABLON ---
@hedef_bp.route('/sablon/genel/liste', methods=['GET'])
def hedef_sablon_genel_liste():
    import sqlite3
    from flask import jsonify
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT id, proses_adi, vardiya, hedef_cift, aciklama,
                   olusturan_id, olusturan_ad, olusturma,
                   guncelleme, guncelleyen_ad
              FROM sablon_genel
             WHERE aktif = 1
             ORDER BY proses_adi COLLATE NOCASE ASC, vardiya ASC
        """).fetchall()
        conn.close()
        return jsonify({
            'ok': True, 'success': True,
            'kayitlar': [dict(r) for r in rows]
        })
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e), 'kayitlar': []}), 500


@hedef_bp.route('/sablon/genel/ekle', methods=['POST'])
def hedef_sablon_genel_ekle():
    import sqlite3
    from flask import jsonify, request
    data = request.get_json(silent=True) or {}
    proses_adi = (data.get('proses_adi') or '').strip()
    vardiya = (data.get('vardiya') or '').strip()
    hedef = data.get('hedef_cift')
    aciklama = (data.get('aciklama') or '').strip() or None

    if not proses_adi:
        return jsonify({'ok': False, 'mesaj': 'proses_adi zorunlu'}), 400
    if vardiya not in ('gunduz', 'gece'):
        return jsonify({'ok': False, 'mesaj': "vardiya 'gunduz' veya 'gece' olmali"}), 400
    try:
        hedef = int(hedef)
        if hedef <= 0:
            raise ValueError()
    except Exception:
        return jsonify({'ok': False, 'mesaj': 'hedef_cift pozitif int olmali'}), 400

    uid, uad = _sablon_session()
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute("""
            INSERT INTO sablon_genel
                (proses_adi, vardiya, hedef_cift, aciklama, olusturan_id, olusturan_ad)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (proses_adi, vardiya, hedef, aciklama, uid, uad))
        yeni_id = cur.lastrowid
        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'id': yeni_id, 'mesaj': 'Sablon eklendi'})
    except sqlite3.IntegrityError as e:
        msg = str(e)
        if 'UNIQUE' in msg.upper():
            return jsonify({'ok': False, 'hata': 'duplicate',
                            'mesaj': "Bu proses+vardiya icin sablon zaten var"}), 409
        return jsonify({'ok': False, 'mesaj': msg}), 400
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)}), 500


@hedef_bp.route('/sablon/genel/guncelle/<int:sid>', methods=['POST'])
def hedef_sablon_genel_guncelle(sid):
    import sqlite3
    from flask import jsonify, request
    data = request.get_json(silent=True) or {}
    proses_adi = (data.get('proses_adi') or '').strip()
    vardiya = (data.get('vardiya') or '').strip()
    hedef = data.get('hedef_cift')
    aciklama = (data.get('aciklama') or '').strip() or None

    if not proses_adi:
        return jsonify({'ok': False, 'mesaj': 'proses_adi zorunlu'}), 400
    if vardiya not in ('gunduz', 'gece'):
        return jsonify({'ok': False, 'mesaj': "vardiya 'gunduz' veya 'gece' olmali"}), 400
    try:
        hedef = int(hedef)
        if hedef <= 0:
            raise ValueError()
    except Exception:
        return jsonify({'ok': False, 'mesaj': 'hedef_cift pozitif int olmali'}), 400

    uid, uad = _sablon_session()
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute("""
            UPDATE sablon_genel
               SET proses_adi=?, vardiya=?, hedef_cift=?, aciklama=?,
                   guncelleme=datetime('now','localtime'),
                   guncelleyen_id=?, guncelleyen_ad=?
             WHERE id=? AND aktif=1
        """, (proses_adi, vardiya, hedef, aciklama, uid, uad, sid))
        conn.commit()
        affected = cur.rowcount
        conn.close()
        if affected == 0:
            return jsonify({'ok': False, 'mesaj': 'Kayit bulunamadi'}), 404
        return jsonify({'ok': True, 'mesaj': 'Guncellendi'})
    except sqlite3.IntegrityError:
        return jsonify({'ok': False, 'hata': 'duplicate',
                        'mesaj': "Bu proses+vardiya icin baska sablon zaten var"}), 409
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)}), 500


@hedef_bp.route('/sablon/genel/sil/<int:sid>', methods=['POST'])
def hedef_sablon_genel_sil(sid):
    import sqlite3
    from flask import jsonify
    uid, uad = _sablon_session()
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute("""
            UPDATE sablon_genel
               SET aktif=0, guncelleme=datetime('now','localtime'),
                   guncelleyen_id=?, guncelleyen_ad=?
             WHERE id=? AND aktif=1
        """, (uid, uad, sid))
        conn.commit()
        affected = cur.rowcount
        conn.close()
        if affected == 0:
            return jsonify({'ok': False, 'mesaj': 'Kayit bulunamadi'}), 404
        return jsonify({'ok': True, 'mesaj': 'Silindi (aktif=0)'})
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)}), 500


# --- 3) EMIR OVERRIDE ---
@hedef_bp.route('/sablon/override/liste', methods=['GET'])
def hedef_sablon_override_liste():
    import sqlite3
    from flask import jsonify, request
    emir_no = (request.args.get('emir_no') or '').strip()
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        if emir_no:
            rows = conn.execute("""
                SELECT seo.id, seo.emir_no, seo.emir_alt_proses_id,
                       COALESCE(eap.proses_adi, seo.proses_adi_snapshot) AS proses_adi,
                       seo.vardiya, seo.hedef_cift, seo.aciklama,
                       seo.olusturan_ad, seo.olusturma
                  FROM sablon_emir_override seo
                  LEFT JOIN emir_alt_proses eap ON eap.id = seo.emir_alt_proses_id
                 WHERE seo.aktif = 1 AND seo.emir_no = ?
                 ORDER BY proses_adi ASC, seo.vardiya ASC
            """, (emir_no,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT seo.id, seo.emir_no, seo.emir_alt_proses_id,
                       COALESCE(eap.proses_adi, seo.proses_adi_snapshot) AS proses_adi,
                       seo.vardiya, seo.hedef_cift, seo.aciklama,
                       seo.olusturan_ad, seo.olusturma
                  FROM sablon_emir_override seo
                  LEFT JOIN emir_alt_proses eap ON eap.id = seo.emir_alt_proses_id
                 WHERE seo.aktif = 1
                 ORDER BY seo.emir_no DESC, proses_adi ASC, seo.vardiya ASC
                 LIMIT 200
            """).fetchall()
        conn.close()
        return jsonify({'ok': True, 'kayitlar': [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e), 'kayitlar': []}), 500


@hedef_bp.route('/sablon/override/ekle', methods=['POST'])
def hedef_sablon_override_ekle():
    import sqlite3
    from flask import jsonify, request
    data = request.get_json(silent=True) or {}
    emir_no = str(data.get('emir_no') or '').strip()
    eap_id = data.get('emir_alt_proses_id')
    vardiya = (data.get('vardiya') or '').strip()
    hedef = data.get('hedef_cift')
    aciklama = (data.get('aciklama') or '').strip() or None

    if not emir_no:
        return jsonify({'ok': False, 'mesaj': 'emir_no zorunlu'}), 400
    try:
        eap_id = int(eap_id)
    except Exception:
        return jsonify({'ok': False, 'mesaj': 'emir_alt_proses_id zorunlu'}), 400
    if vardiya not in ('gunduz', 'gece'):
        return jsonify({'ok': False, 'mesaj': "vardiya 'gunduz' veya 'gece'"}), 400
    try:
        hedef = int(hedef)
        if hedef <= 0:
            raise ValueError()
    except Exception:
        return jsonify({'ok': False, 'mesaj': 'hedef_cift pozitif int olmali'}), 400

    uid, uad = _sablon_session()
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        # emir_alt_proses gercekten bu emire ait mi?
        eap = conn.execute("""
            SELECT id, proses_adi FROM emir_alt_proses
             WHERE id=? AND emir_no=? AND aktif=1
        """, (eap_id, emir_no)).fetchone()
        if not eap:
            conn.close()
            return jsonify({'ok': False, 'hata': 'gecersiz_proses',
                            'mesaj': 'Bu emir_alt_proses bu emire ait degil'}), 400
        snapshot = eap[1]
        cur = conn.execute("""
            INSERT INTO sablon_emir_override
                (emir_no, emir_alt_proses_id, proses_adi_snapshot,
                 vardiya, hedef_cift, aciklama, olusturan_id, olusturan_ad)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (emir_no, eap_id, snapshot, vardiya, hedef, aciklama, uid, uad))
        yeni_id = cur.lastrowid
        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'id': yeni_id, 'mesaj': 'Override eklendi'})
    except sqlite3.IntegrityError as e:
        if 'UNIQUE' in str(e).upper():
            return jsonify({'ok': False, 'hata': 'duplicate',
                            'mesaj': 'Bu emir+proses+vardiya icin override zaten var'}), 409
        return jsonify({'ok': False, 'mesaj': str(e)}), 400
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)}), 500


@hedef_bp.route('/sablon/override/guncelle/<int:sid>', methods=['POST'])
def hedef_sablon_override_guncelle(sid):
    import sqlite3
    from flask import jsonify, request
    data = request.get_json(silent=True) or {}
    vardiya = (data.get('vardiya') or '').strip()
    hedef = data.get('hedef_cift')
    aciklama = (data.get('aciklama') or '').strip() or None

    if vardiya not in ('gunduz', 'gece'):
        return jsonify({'ok': False, 'mesaj': "vardiya 'gunduz' veya 'gece'"}), 400
    try:
        hedef = int(hedef)
        if hedef <= 0:
            raise ValueError()
    except Exception:
        return jsonify({'ok': False, 'mesaj': 'hedef_cift pozitif int'}), 400

    uid, uad = _sablon_session()
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute("""
            UPDATE sablon_emir_override
               SET vardiya=?, hedef_cift=?, aciklama=?,
                   guncelleme=datetime('now','localtime'),
                   guncelleyen_id=?, guncelleyen_ad=?
             WHERE id=? AND aktif=1
        """, (vardiya, hedef, aciklama, uid, uad, sid))
        conn.commit()
        affected = cur.rowcount
        conn.close()
        if affected == 0:
            return jsonify({'ok': False, 'mesaj': 'Kayit bulunamadi'}), 404
        return jsonify({'ok': True, 'mesaj': 'Guncellendi'})
    except sqlite3.IntegrityError:
        return jsonify({'ok': False, 'hata': 'duplicate',
                        'mesaj': 'Ayni emir+proses+vardiya icin baska override var'}), 409
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)}), 500


@hedef_bp.route('/sablon/override/sil/<int:sid>', methods=['POST'])
def hedef_sablon_override_sil(sid):
    import sqlite3
    from flask import jsonify
    uid, uad = _sablon_session()
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute("""
            UPDATE sablon_emir_override
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


# --- 4) HIBRIT LOOKUP (oner-toplu) ---
@hedef_bp.route('/sablon/oner-toplu', methods=['GET'])
def hedef_sablon_oner_toplu():
    """GET /hedef/sablon/oner-toplu?emir_no=110626&vardiya=gunduz
    Bir emirin tum aktif alt prosesleri icin hibrit hedef onerisi.
    Oncelik: 1) sablon_emir_override 2) sablon_genel 3) yok
    """
    import sqlite3
    from flask import jsonify, request
    emir_no = (request.args.get('emir_no') or '').strip()
    vardiya = (request.args.get('vardiya') or '').strip()
    if not emir_no:
        return jsonify({'ok': False, 'mesaj': 'emir_no zorunlu'}), 400
    if vardiya not in ('gunduz', 'gece'):
        return jsonify({'ok': False, 'mesaj': "vardiya 'gunduz' veya 'gece'"}), 400

    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT
                eap.id AS emir_alt_proses_id,
                eap.proses_adi,
                eap.siralama,
                COALESCE(seo.hedef_cift, sg.hedef_cift) AS hedef_cift,
                CASE
                    WHEN seo.id IS NOT NULL THEN 'override'
                    WHEN sg.id IS NOT NULL THEN 'genel'
                    ELSE 'yok'
                END AS kaynak,
                COALESCE(seo.id, sg.id) AS sablon_id,
                COALESCE(seo.aciklama, sg.aciklama) AS aciklama
              FROM emir_alt_proses eap
              LEFT JOIN sablon_emir_override seo
                ON seo.emir_no = eap.emir_no
               AND seo.emir_alt_proses_id = eap.id
               AND seo.vardiya = ?
               AND seo.aktif = 1
              LEFT JOIN sablon_genel sg
                ON LOWER(TRIM(sg.proses_adi)) = LOWER(TRIM(eap.proses_adi))
               AND sg.vardiya = ?
               AND sg.aktif = 1
             WHERE eap.emir_no = ?
               AND eap.aktif = 1
             ORDER BY eap.siralama ASC, eap.id ASC
        """, (vardiya, vardiya, emir_no)).fetchall()
        conn.close()
        return jsonify({
            'ok': True, 'success': True,
            'emir_no': emir_no, 'vardiya': vardiya,
            'oneriler': [dict(r) for r in rows]
        })
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e), 'oneriler': []}), 500
'''


# =====================================================================
# 3) FRONTEND BLOCK
# =====================================================================
JS_BLOCK = r'''


/* ====================================================================
   CPS LOCAL - FAZ 4.6 B: Sablon UI
   - SABLON pane'ini dinamik render
   - 2 alt sekme: GENEL + EMIR OZEL OVERRIDE
   - Tab tiklamasinda lazy-load
   ==================================================================== */
(function () {
    'use strict';

    var _state = {
        aktifAlt: 'genel',
        prosesListesi: null,
        genelListesi: null,
        overrideListesi: null,
        overrideEmirNo: '',
        emirAltProsesleri: null,
        yuklendi: false
    };

    if (!document.getElementById('sablonStyles46b')) {
        var s = document.createElement('style');
        s.id = 'sablonStyles46b';
        s.textContent = [
            '#sablonPane { padding:8px 4px; }',
            '#sablonPane .alt-sekme-bar { display:flex; gap:4px; margin-bottom:14px; border-bottom:2px solid var(--border); }',
            '#sablonPane .alt-sekme { padding:9px 18px; cursor:pointer; font-size:12px; font-weight:700; letter-spacing:0.5px; color:var(--text3); border-bottom:2px solid transparent; margin-bottom:-2px; user-select:none; }',
            '#sablonPane .alt-sekme.aktif { color:var(--sol); border-bottom-color:var(--sol); }',
            '#sablonPane .alt-sekme:hover:not(.aktif) { color:var(--text2); }',
            '#sablonPane .filtre-bar { display:flex; gap:8px; align-items:center; margin-bottom:12px; flex-wrap:wrap; }',
            '#sablonPane .filtre-bar input, #sablonPane .filtre-bar select { padding:7px 12px; border:1px solid var(--border); border-radius:6px; font-size:13px; box-sizing:border-box; }',
            '#sablonPane .filtre-bar .ara { flex:1; min-width:180px; }',
            '#sablonPane .ekle-btn { background:var(--sol,#f97316); color:#fff; border:0; padding:8px 14px; border-radius:6px; font-size:12px; font-weight:700; cursor:pointer; letter-spacing:0.4px; }',
            '#sablonPane .ekle-btn:hover { filter:brightness(0.92); }',
            '#sablonPane table.sb-table { width:100%; border-collapse:collapse; background:#fff; border-radius:8px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.05); }',
            '#sablonPane table.sb-table th, #sablonPane table.sb-table td { padding:8px 12px; text-align:left; border-bottom:1px solid var(--border); font-size:13px; white-space:nowrap; }',
            '#sablonPane table.sb-table th { font-size:10px; color:var(--text3); text-transform:uppercase; letter-spacing:0.5px; background:#fafafa; }',
            '#sablonPane table.sb-table td.num { text-align:right; font-family:var(--mono); }',
            '#sablonPane table.sb-table td.aks { text-align:right; }',
            '#sablonPane .vardiya-rozet { display:inline-block; padding:2px 8px; border-radius:10px; font-size:10px; font-weight:700; letter-spacing:0.5px; }',
            '#sablonPane .v-gunduz { background:#fef3c7; color:#92400e; }',
            '#sablonPane .v-gece { background:#1f2937; color:#f3f4f6; }',
            '#sablonPane .icon-btn { background:none; border:0; cursor:pointer; padding:4px 8px; font-size:14px; border-radius:4px; }',
            '#sablonPane .icon-btn:hover { background:#f3f4f6; }',
            '#sablonPane .empty-msg { padding:32px; text-align:center; color:var(--text3); background:#fff; border-radius:8px; }',
            '#sablonModal { position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:9999; display:none; align-items:center; justify-content:center; padding:20px; }',
            '#sablonModal.acik { display:flex; }',
            '#sablonModal .modal-icerik { background:#fff; border-radius:12px; max-width:480px; width:100%; padding:22px 26px; }',
            '#sablonModal h3 { margin:0 0 16px 0; font-size:16px; }',
            '#sablonModal .form-grup { margin-bottom:14px; }',
            '#sablonModal label { display:block; font-size:10px; font-weight:700; letter-spacing:0.6px; color:var(--text3); margin-bottom:5px; text-transform:uppercase; }',
            '#sablonModal input, #sablonModal select, #sablonModal textarea { width:100%; padding:9px 12px; border:1px solid var(--border); border-radius:6px; font-size:13px; box-sizing:border-box; font-family:inherit; outline:none; }',
            '#sablonModal input:focus, #sablonModal select:focus, #sablonModal textarea:focus { border-color:var(--sol,#f97316); box-shadow:0 0 0 2px rgba(249,115,22,0.15); }',
            '#sablonModal .vardiya-radyo { display:flex; gap:8px; }',
            '#sablonModal .vardiya-radyo .radyo { flex:1; cursor:pointer; padding:10px; border:1px solid var(--border); border-radius:6px; text-align:center; font-size:13px; font-weight:600; user-select:none; }',
            '#sablonModal .vardiya-radyo .radyo.secili { border-color:var(--sol,#f97316); background:#fff7ed; color:#c2410c; }',
            '#sablonModal .vardiya-radyo input { display:none; }',
            '#sablonModal .form-aksiyon { display:flex; gap:8px; justify-content:flex-end; margin-top:18px; }',
            '#sablonModal button { padding:9px 18px; border-radius:6px; font-size:13px; font-weight:700; cursor:pointer; border:0; }',
            '#sablonModal .btn-iptal { background:#f3f4f6; color:var(--text2); }',
            '#sablonModal .btn-kaydet { background:var(--sol,#f97316); color:#fff; }',
            '#sablonModal .hata { color:#dc2626; font-size:12px; margin-top:6px; display:none; }',
            '#sablonModal .hata.gor { display:block; }'
        ].join('\n');
        document.head.appendChild(s);
    }

    function _esc(s) {
        if (s == null) return '';
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    function _fmt(n) {
        var x = Number(n);
        if (!isFinite(x)) return _esc(n);
        return x.toLocaleString('tr-TR');
    }
    function _vRozet(v) {
        if (v === 'gunduz') return '<span class="vardiya-rozet v-gunduz">☀ GÜNDÜZ</span>';
        if (v === 'gece') return '<span class="vardiya-rozet v-gece">☾ GECE</span>';
        return _esc(v);
    }
    function _api(url, opts) {
        opts = opts || {};
        opts.credentials = 'include';
        opts.headers = opts.headers || {};
        if (!opts.headers['Content-Type']) opts.headers['Content-Type'] = 'application/json';
        return fetch(url, opts).then(function (r) {
            return r.text().then(function (t) {
                var d; try { d = JSON.parse(t); } catch (_) { d = null; }
                return { status: r.status, data: d };
            });
        });
    }

    function _ensurePane() {
        var pane = document.querySelector('[data-pane="sablon"]') ||
                   document.querySelector('.h-pane[data-pane="sablon"]') ||
                   document.getElementById('h-pane-sablon');
        if (!pane) {
            var main = document.querySelector('main') || document.body;
            pane = document.createElement('section');
            pane.className = 'h-pane';
            pane.setAttribute('data-pane', 'sablon');
            pane.style.display = 'none';
            main.appendChild(pane);
        }
        return pane;
    }

    function _renderPane() {
        var pane = _ensurePane();
        if (pane.querySelector('#sablonPane')) return;
        pane.innerHTML = [
            '<div id="sablonPane">',
            '  <div class="alt-sekme-bar">',
            '    <div class="alt-sekme aktif" data-alt="genel">📋 Genel Şablonlar</div>',
            '    <div class="alt-sekme" data-alt="override">🎯 Emir Özel Override</div>',
            '  </div>',
            '  <div id="sablonContent"></div>',
            '</div>',
            '<div id="sablonModal"><div class="modal-icerik" id="sablonModalIcerik"></div></div>'
        ].join('\n');
        pane.querySelectorAll('.alt-sekme').forEach(function (el) {
            el.addEventListener('click', function () {
                _state.aktifAlt = el.dataset.alt;
                pane.querySelectorAll('.alt-sekme').forEach(function (x) { x.classList.remove('aktif'); });
                el.classList.add('aktif');
                _renderContent();
            });
        });
        _renderContent();
    }

    function _renderContent() {
        if (_state.aktifAlt === 'genel') _renderGenel();
        else _renderOverride();
    }

    // ============ GENEL ŞABLON ============
    function _renderGenel() {
        var c = document.getElementById('sablonContent');
        if (!c) return;
        c.innerHTML = [
            '<div class="filtre-bar">',
            '  <input type="search" id="sgArama" class="ara" placeholder="🔍 Proses ara...">',
            '  <select id="sgVar">',
            '    <option value="">Tüm Vardiyalar</option>',
            '    <option value="gunduz">☀ Gündüz</option>',
            '    <option value="gece">☾ Gece</option>',
            '  </select>',
            '  <button class="ekle-btn" id="sgEkle">+ YENİ ŞABLON</button>',
            '</div>',
            '<div id="sgListe"><div class="empty-msg">Yükleniyor...</div></div>'
        ].join('\n');
        document.getElementById('sgEkle').addEventListener('click', function () { _genelModal(null); });
        document.getElementById('sgArama').addEventListener('input', _genelListele);
        document.getElementById('sgVar').addEventListener('change', _genelListele);
        _yukleGenel().then(_genelListele);
    }
    function _yukleGenel() {
        return _api('/hedef/sablon/genel/liste').then(function (r) {
            _state.genelListesi = (r.data && r.data.kayitlar) || [];
        });
    }
    function _genelListele() {
        var c = document.getElementById('sgListe');
        if (!c) return;
        var rows = _state.genelListesi || [];
        var arama = (document.getElementById('sgArama').value || '').toLowerCase().trim();
        var vard = document.getElementById('sgVar').value;
        var f = rows.filter(function (r) {
            if (arama && (r.proses_adi || '').toLowerCase().indexOf(arama) === -1) return false;
            if (vard && r.vardiya !== vard) return false;
            return true;
        });
        if (f.length === 0) {
            c.innerHTML = '<div class="empty-msg">Şablon yok. Yukarıdan + YENİ ŞABLON ile ekle.</div>';
            return;
        }
        var html = ['<table class="sb-table"><thead><tr>',
            '<th>PROSES</th><th>VARDIYA</th><th class="num">HEDEF / VARDIYA</th>',
            '<th>AÇIKLAMA</th><th>OLUŞTURAN</th><th class="aks">İŞLEM</th>',
            '</tr></thead><tbody>'];
        f.forEach(function (r) {
            html.push('<tr>',
                '<td><strong>' + _esc(r.proses_adi) + '</strong></td>',
                '<td>' + _vRozet(r.vardiya) + '</td>',
                '<td class="num"><strong>' + _fmt(r.hedef_cift) + '</strong> çift</td>',
                '<td>' + _esc(r.aciklama || '-') + '</td>',
                '<td>' + _esc(r.olusturan_ad || '-') + '</td>',
                '<td class="aks">',
                '<button class="icon-btn" data-id="' + r.id + '" data-akt="duzenle" title="Düzenle">✏️</button>',
                '<button class="icon-btn" data-id="' + r.id + '" data-akt="sil" title="Sil">🗑️</button>',
                '</td></tr>');
        });
        html.push('</tbody></table>');
        c.innerHTML = html.join('');
        c.querySelectorAll('.icon-btn').forEach(function (b) {
            b.addEventListener('click', function () {
                var id = parseInt(b.dataset.id, 10);
                var rec = _state.genelListesi.find(function (x) { return x.id === id; });
                if (b.dataset.akt === 'duzenle') _genelModal(rec);
                else if (b.dataset.akt === 'sil') _genelSil(rec);
            });
        });
    }
    function _genelSil(rec) {
        if (!rec) return;
        if (!confirm('Bu şablonu silmek istiyor musun?\n"' + rec.proses_adi + ' / ' + rec.vardiya + '"')) return;
        _api('/hedef/sablon/genel/sil/' + rec.id, { method: 'POST' }).then(function (r) {
            if (r.data && r.data.ok) {
                _yukleGenel().then(_genelListele);
            } else {
                alert((r.data && r.data.mesaj) || 'Silme başarısız');
            }
        });
    }
    function _genelModal(rec) {
        var rec0 = rec || { proses_adi: '', vardiya: 'gunduz', hedef_cift: '', aciklama: '' };
        var i = document.getElementById('sablonModalIcerik');
        i.innerHTML = [
            '<h3>' + (rec ? 'Şablon Düzenle' : 'Yeni Genel Şablon') + '</h3>',
            '<div class="form-grup"><label>Proses</label>',
            '<select id="mProses"><option value="">Yükleniyor...</option></select></div>',
            '<div class="form-grup"><label>Vardiya</label>',
            '<div class="vardiya-radyo">',
            '<label class="radyo' + (rec0.vardiya === 'gunduz' ? ' secili' : '') + '">' +
            '<input type="radio" name="mVar" value="gunduz"' + (rec0.vardiya === 'gunduz' ? ' checked' : '') + '>☀ Gündüz</label>',
            '<label class="radyo' + (rec0.vardiya === 'gece' ? ' secili' : '') + '">' +
            '<input type="radio" name="mVar" value="gece"' + (rec0.vardiya === 'gece' ? ' checked' : '') + '>☾ Gece</label>',
            '</div></div>',
            '<div class="form-grup"><label>Hedef (Vardiya boyu, çift)</label>',
            '<input type="number" id="mHedef" min="1" value="' + _esc(rec0.hedef_cift) + '" placeholder="örn 1000"></div>',
            '<div class="form-grup"><label>Açıklama (opsiyonel)</label>',
            '<textarea id="mAciklama" rows="2">' + _esc(rec0.aciklama || '') + '</textarea></div>',
            '<div class="hata" id="mHata"></div>',
            '<div class="form-aksiyon">',
            '<button class="btn-iptal" id="mIptal">İptal</button>',
            '<button class="btn-kaydet" id="mKaydet">Kaydet</button>',
            '</div>'
        ].join('\n');
        document.getElementById('sablonModal').classList.add('acik');

        // Proses dropdown
        _yukleProsesListesi().then(function () {
            var sel = document.getElementById('mProses');
            if (!sel) return;
            sel.innerHTML = '<option value="">— Seç —</option>';
            (_state.prosesListesi || []).forEach(function (p) {
                var opt = document.createElement('option');
                opt.value = p.proses_adi;
                opt.textContent = p.proses_adi;
                if (rec0.proses_adi && rec0.proses_adi.toLowerCase() === p.proses_adi.toLowerCase()) opt.selected = true;
                sel.appendChild(opt);
            });
        });

        // Vardiya radyo görsel
        i.querySelectorAll('.vardiya-radyo input').forEach(function (inp) {
            inp.addEventListener('change', function () {
                i.querySelectorAll('.vardiya-radyo .radyo').forEach(function (l) { l.classList.remove('secili'); });
                inp.parentElement.classList.add('secili');
            });
        });

        document.getElementById('mIptal').addEventListener('click', _modalKapat);
        document.getElementById('mKaydet').addEventListener('click', function () {
            var prs = document.getElementById('mProses').value;
            var v = (i.querySelector('input[name=mVar]:checked') || {}).value;
            var h = parseInt(document.getElementById('mHedef').value, 10);
            var ac = document.getElementById('mAciklama').value;
            var hata = document.getElementById('mHata');
            hata.classList.remove('gor');
            if (!prs) { hata.textContent = 'Proses seçimi zorunlu.'; hata.classList.add('gor'); return; }
            if (!v) { hata.textContent = 'Vardiya seçimi zorunlu.'; hata.classList.add('gor'); return; }
            if (!h || h <= 0) { hata.textContent = 'Hedef pozitif sayı olmalı.'; hata.classList.add('gor'); return; }
            var url = rec ? '/hedef/sablon/genel/guncelle/' + rec.id : '/hedef/sablon/genel/ekle';
            _api(url, {
                method: 'POST',
                body: JSON.stringify({ proses_adi: prs, vardiya: v, hedef_cift: h, aciklama: ac })
            }).then(function (r) {
                if (r.data && r.data.ok) {
                    _modalKapat();
                    _yukleGenel().then(_genelListele);
                } else {
                    hata.textContent = (r.data && r.data.mesaj) || ('HTTP ' + r.status);
                    hata.classList.add('gor');
                }
            });
        });
    }
    function _modalKapat() {
        var m = document.getElementById('sablonModal');
        if (m) m.classList.remove('acik');
    }
    function _yukleProsesListesi() {
        if (_state.prosesListesi) return Promise.resolve();
        return _api('/hedef/sablon/proses-listesi').then(function (r) {
            _state.prosesListesi = (r.data && r.data.kayitlar) || [];
        });
    }

    // ============ EMIR OVERRIDE ============
    function _renderOverride() {
        var c = document.getElementById('sablonContent');
        if (!c) return;
        c.innerHTML = [
            '<div class="filtre-bar">',
            '  <input type="text" id="ovEmirNo" class="ara" placeholder="Emir no (boş = tümü)" value="' + _esc(_state.overrideEmirNo || '') + '">',
            '  <button class="ekle-btn" id="ovYukleBtn">YÜKLE</button>',
            '  <button class="ekle-btn" id="ovEkleBtn" style="background:#10b981;">+ YENİ OVERRIDE</button>',
            '</div>',
            '<div id="ovListe"><div class="empty-msg">Emir no gir veya boş bırakıp YÜKLE.</div></div>'
        ].join('\n');
        document.getElementById('ovYukleBtn').addEventListener('click', function () {
            _state.overrideEmirNo = document.getElementById('ovEmirNo').value.trim();
            _yukleOverride().then(_overrideListele);
        });
        document.getElementById('ovEkleBtn').addEventListener('click', function () {
            _state.overrideEmirNo = document.getElementById('ovEmirNo').value.trim();
            _overrideModal(null);
        });
        if (_state.overrideListesi) _overrideListele();
        else _yukleOverride().then(_overrideListele);
    }
    function _yukleOverride() {
        var url = '/hedef/sablon/override/liste' +
            (_state.overrideEmirNo ? '?emir_no=' + encodeURIComponent(_state.overrideEmirNo) : '');
        return _api(url).then(function (r) {
            _state.overrideListesi = (r.data && r.data.kayitlar) || [];
        });
    }
    function _overrideListele() {
        var c = document.getElementById('ovListe');
        if (!c) return;
        var rows = _state.overrideListesi || [];
        if (rows.length === 0) {
            c.innerHTML = '<div class="empty-msg">Override yok. + YENİ OVERRIDE ile ekle.</div>';
            return;
        }
        var html = ['<table class="sb-table"><thead><tr>',
            '<th>EMİR</th><th>ALT PROSES</th><th>VARDIYA</th><th class="num">HEDEF / VARDIYA</th>',
            '<th>AÇIKLAMA</th><th>OLUŞTURAN</th><th class="aks">İŞLEM</th>',
            '</tr></thead><tbody>'];
        rows.forEach(function (r) {
            html.push('<tr>',
                '<td><strong>E.' + _esc(r.emir_no) + '</strong></td>',
                '<td>' + _esc(r.proses_adi || '-') + '</td>',
                '<td>' + _vRozet(r.vardiya) + '</td>',
                '<td class="num"><strong>' + _fmt(r.hedef_cift) + '</strong> çift</td>',
                '<td>' + _esc(r.aciklama || '-') + '</td>',
                '<td>' + _esc(r.olusturan_ad || '-') + '</td>',
                '<td class="aks">',
                '<button class="icon-btn" data-id="' + r.id + '" data-akt="duzenle" title="Düzenle">✏️</button>',
                '<button class="icon-btn" data-id="' + r.id + '" data-akt="sil" title="Sil">🗑️</button>',
                '</td></tr>');
        });
        html.push('</tbody></table>');
        c.innerHTML = html.join('');
        c.querySelectorAll('.icon-btn').forEach(function (b) {
            b.addEventListener('click', function () {
                var id = parseInt(b.dataset.id, 10);
                var rec = _state.overrideListesi.find(function (x) { return x.id === id; });
                if (b.dataset.akt === 'duzenle') _overrideModal(rec);
                else _overrideSil(rec);
            });
        });
    }
    function _overrideSil(rec) {
        if (!rec) return;
        if (!confirm('Bu override\'ı silmek istiyor musun?\n"' + rec.emir_no + ' / ' + rec.proses_adi + ' / ' + rec.vardiya + '"')) return;
        _api('/hedef/sablon/override/sil/' + rec.id, { method: 'POST' }).then(function (r) {
            if (r.data && r.data.ok) _yukleOverride().then(_overrideListele);
            else alert((r.data && r.data.mesaj) || 'Silme başarısız');
        });
    }
    function _overrideModal(rec) {
        var rec0 = rec || { emir_no: _state.overrideEmirNo || '', emir_alt_proses_id: '', vardiya: 'gunduz', hedef_cift: '', aciklama: '' };
        var i = document.getElementById('sablonModalIcerik');
        var emirNoReadonly = rec ? ' readonly' : '';
        i.innerHTML = [
            '<h3>' + (rec ? 'Override Düzenle' : 'Yeni Emir Override') + '</h3>',
            '<div class="form-grup"><label>Emir No</label>',
            '<input type="text" id="ovEmir" value="' + _esc(rec0.emir_no) + '"' + emirNoReadonly + ' placeholder="örn 110626"></div>',
            '<div class="form-grup"><label>Alt Proses</label>',
            '<select id="ovAlt"><option value="">Önce emir no gir, sonra YÜKLE</option></select></div>',
            '<div class="form-grup"><label>Vardiya</label>',
            '<div class="vardiya-radyo">',
            '<label class="radyo' + (rec0.vardiya === 'gunduz' ? ' secili' : '') + '">' +
            '<input type="radio" name="ovVar" value="gunduz"' + (rec0.vardiya === 'gunduz' ? ' checked' : '') + '>☀ Gündüz</label>',
            '<label class="radyo' + (rec0.vardiya === 'gece' ? ' secili' : '') + '">' +
            '<input type="radio" name="ovVar" value="gece"' + (rec0.vardiya === 'gece' ? ' checked' : '') + '>☾ Gece</label>',
            '</div></div>',
            '<div class="form-grup"><label>Hedef (Vardiya boyu, çift)</label>',
            '<input type="number" id="ovHedef" min="1" value="' + _esc(rec0.hedef_cift) + '"></div>',
            '<div class="form-grup"><label>Açıklama (opsiyonel)</label>',
            '<textarea id="ovAciklama" rows="2">' + _esc(rec0.aciklama || '') + '</textarea></div>',
            '<div class="hata" id="ovHata"></div>',
            '<div class="form-aksiyon">',
            '<button class="btn-iptal" id="ovIptal">İptal</button>',
            '<button class="btn-kaydet" id="ovKaydet">Kaydet</button>',
            '</div>'
        ].join('\n');
        document.getElementById('sablonModal').classList.add('acik');

        function _yukleAltProsesler(emirNo, secId) {
            if (!emirNo) return;
            _api('/uretim/emir/' + encodeURIComponent(emirNo) + '/prosesler').then(function (r) {
                var sel = document.getElementById('ovAlt');
                if (!sel) return;
                sel.innerHTML = '<option value="">— Alt Proses Seç —</option>';
                var prosesler = (r.data && r.data.prosesler) || [];
                prosesler.forEach(function (p) {
                    var opt = document.createElement('option');
                    opt.value = p.id;
                    opt.textContent = p.proses_adi;
                    if (secId && parseInt(secId, 10) === p.id) opt.selected = true;
                    sel.appendChild(opt);
                });
            });
        }
        if (rec0.emir_no) _yukleAltProsesler(rec0.emir_no, rec0.emir_alt_proses_id);
        var emirInp = document.getElementById('ovEmir');
        if (emirInp && !rec) {
            emirInp.addEventListener('change', function () {
                _yukleAltProsesler(emirInp.value.trim(), null);
            });
        }

        i.querySelectorAll('.vardiya-radyo input').forEach(function (inp) {
            inp.addEventListener('change', function () {
                i.querySelectorAll('.vardiya-radyo .radyo').forEach(function (l) { l.classList.remove('secili'); });
                inp.parentElement.classList.add('secili');
            });
        });

        document.getElementById('ovIptal').addEventListener('click', _modalKapat);
        document.getElementById('ovKaydet').addEventListener('click', function () {
            var emirNo = document.getElementById('ovEmir').value.trim();
            var altId = parseInt(document.getElementById('ovAlt').value, 10);
            var v = (i.querySelector('input[name=ovVar]:checked') || {}).value;
            var h = parseInt(document.getElementById('ovHedef').value, 10);
            var ac = document.getElementById('ovAciklama').value;
            var hata = document.getElementById('ovHata');
            hata.classList.remove('gor');
            if (!emirNo) { hata.textContent = 'Emir no zorunlu.'; hata.classList.add('gor'); return; }
            if (!altId) { hata.textContent = 'Alt proses seçimi zorunlu.'; hata.classList.add('gor'); return; }
            if (!v) { hata.textContent = 'Vardiya zorunlu.'; hata.classList.add('gor'); return; }
            if (!h || h <= 0) { hata.textContent = 'Hedef pozitif sayı olmalı.'; hata.classList.add('gor'); return; }
            var url = rec ? '/hedef/sablon/override/guncelle/' + rec.id : '/hedef/sablon/override/ekle';
            var body = rec
                ? { vardiya: v, hedef_cift: h, aciklama: ac }
                : { emir_no: emirNo, emir_alt_proses_id: altId, vardiya: v, hedef_cift: h, aciklama: ac };
            _api(url, { method: 'POST', body: JSON.stringify(body) }).then(function (r) {
                if (r.data && r.data.ok) {
                    _modalKapat();
                    _state.overrideEmirNo = emirNo;
                    _yukleOverride().then(_overrideListele);
                } else {
                    hata.textContent = (r.data && r.data.mesaj) || ('HTTP ' + r.status);
                    hata.classList.add('gor');
                }
            });
        });
    }

    // ============ Tab tıklama / ilk yukleme ============
    function _kurulum() {
        var sablonTab = document.querySelector('.h-tab[data-tab="sablon"]');
        if (sablonTab) {
            sablonTab.addEventListener('click', function () {
                setTimeout(_renderPane, 50);
            });
        }
        // Eger SABLON sekmesi zaten aktifse hemen render
        var aktTab = document.querySelector('.h-tab.active[data-tab="sablon"]');
        if (aktTab) setTimeout(_renderPane, 100);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { setTimeout(_kurulum, 200); });
    } else {
        setTimeout(_kurulum, 200);
    }

    console.log('[CPS LOCAL] FAZ 4.6 B sablon yuklendi.');
})();
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


def migrate_db():
    print()
    print("=" * 64)
    print("1/3 DB MIGRATION: mock_data.db (yeni 2 tablo)")
    print("=" * 64)
    if not os.path.exists(DB_PATH):
        print(f"  [HATA] {DB_PATH} bulunamadi.")
        return False
    bp = backup(DB_PATH)
    if bp:
        print(f"  [OK] Yedek: {bp}")
    try:
        conn = sqlite3.connect(DB_PATH)
        for sql in MIGRATIONS:
            conn.execute(sql)
        conn.commit()
        # Dogrulama
        tablolar = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('sablon_genel','sablon_emir_override')"
        ).fetchall()
        conn.close()
        print(f"  [OK] Tablolar: {[t[0] for t in tablolar]}")
        return True
    except Exception as e:
        print(f"  [HATA] migration: {e}")
        return False


def patch_backend():
    print()
    print("=" * 64)
    print("2/3 BACKEND: modules/hedef/routes.py (10 endpoint)")
    print("=" * 64)
    if not os.path.exists(HEDEF_ROUTES):
        print(f"  [HATA] {HEDEF_ROUTES} bulunamadi.")
        return False
    with open(HEDEF_ROUTES, 'r', encoding='utf-8') as f:
        src = f.read()
    if BE_MARKER in src:
        print("  [BILGI] Sablon endpoint'leri zaten ekli.")
        return True

    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += BACKEND_BLOCK

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] parse: {e}")
        return False

    bp = backup(HEDEF_ROUTES)
    print(f"  [OK] Yedek: {bp}")
    with open(HEDEF_ROUTES, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] 10 sablon endpoint'i eklendi.")
    return True


def patch_js():
    print()
    print("=" * 64)
    print("3/3 FRONTEND: static/js/hedef.js (UI)")
    print("=" * 64)
    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} bulunamadi.")
        return False
    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()
    if JS_MARKER in src:
        print("  [BILGI] Sablon UI zaten ekli.")
        return True

    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += JS_BLOCK

    bp = backup(JS_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] Sablon UI IIFE eklendi.")
    return True


def main():
    print("=" * 64)
    print("FAZ 4.6 ADIM B - Sablon sistemi (B1+B2)")
    print("=" * 64)
    print("CPS_KURALLAR uyum:")
    print("  ✓ uretim_kaydet'e dokunulmuyor (sablon sadece oneri)")
    print("  ✓ Yeni tablo (madde 8)")
    print("  ✓ Korgun read-only (madde 1)")
    print("  ✓ MES v2 yok (madde 9)")
    print("  ✓ proses_adi dropdown zorunlu, manuel string yok")

    ok1 = migrate_db()
    ok2 = patch_backend()
    ok3 = patch_js()

    print()
    print("=" * 64)
    if ok1 and ok2 and ok3:
        print("ADIM B TAMAM.")
        print("=" * 64)
        print()
        print("YAPILACAK:")
        print("  1) CPS sunucusunu yeniden baslat")
        print("  2) Browser'da Ctrl+F5")
        print("  3) /hedef/ -> SABLON sekmesi")
        print()
        print("Beklenen:")
        print("  GENEL Sablonlar (bos liste, '+ YENI SABLON' ile ekle)")
        print("  EMIR OZEL OVERRIDE (alt sekme)")
        print()
        print("Test:")
        print("  1. + YENI SABLON tikla")
        print("     - Proses dropdown: 'Capak Alma', 'Tampon Baski', 'Rivet Takma',")
        print("                        'Atki Takma', 'Temizleme', 'Paketleme',")
        print("                        + (legacy) 'Monta', 'Enjeksiyon', 'Kesim'")
        print("     - Vardiya: gunduz/gece radyo")
        print("     - Hedef: 1000")
        print("     - Kaydet")
        print("  2. Tabloda goruncek")
        print("  3. Lookup test (DevTools console):")
        print("     fetch('/hedef/sablon/oner-toplu?emir_no=110626&vardiya=gunduz')")
        print("       .then(r=>r.json()).then(console.log)")
        print()
        print("  4. EMIR OZEL OVERRIDE alt sekmesine geç")
        print("     - Emir no: 110626 yaz, YUKLE")
        print("     - + YENI OVERRIDE")
        print("     - Alt proses dropdown: 110626'nin 6 alt prosesi")
        print()
        print("Console:")
        print("  [CPS LOCAL] FAZ 4.6 B sablon yuklendi.")
        return 0
    print("BAZI ADIMLAR BASARISIZ.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
