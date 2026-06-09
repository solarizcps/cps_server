# -*- coding: utf-8 -*-
"""CPS DEV - Hedef Routes (MES v2 API koprusu)

Bu modul sadece HTML sayfalarini render eder. Veri MES v2 (port 5070)
API'sinden JS tarafinda fetch edilir. CPS-MES v2 kopru rolu.
"""
from flask import (Blueprint, render_template, redirect, url_for,
                   request, session, abort, jsonify)
from functools import wraps
from modules.auth import yetki_gerekli, yetki_var, is_superadmin
from db import q, qexec

hedef_bp = Blueprint('hedef', __name__, url_prefix='/hedef')


def hedef_yetkili(f):
    """
    F2.7-P2 TRANSITIONAL wrapper.
    Yetkilendirme CORE permission sistemine devredildi.
    @hedef_yetkili = @yetki_gerekli('hedef', 'can_view') esdegeri.
    """
    return yetki_gerekli('hedef', 'can_view')(f)


# ============== PANEL (varsayilan iskelet) ==============
@hedef_bp.route('/')
@hedef_yetkili
def panel():
    """Hedef ana paneli - UI.2'de 4 sekme eklenecek."""
    return render_template('hedef/index.html')


@hedef_bp.route('/sablon')
@hedef_yetkili
def sablon():
    """Sablon listesi - UI.2'de ayri sayfa."""
    return render_template('hedef/sablon.html')


@hedef_bp.route('/sapma')
@hedef_yetkili
def sapma():
    """Sapma analizi - UI.3'te ayri sayfa."""
    return render_template('hedef/index.html')



# === CPS LOCAL HEDEF ONAY ENDPOINTS ===
# Eklendi: setup_hedef_onaylar.py
# Veri kaynagi: mock_data.db.uretim_kayit (MES v2 KULLANILMIYOR)

def _hedef_db_path():
    import os as _os
    from flask import current_app
    candidates = [
        _os.path.join(current_app.root_path, 'mock_data.db'),
        _os.path.join(_os.path.dirname(current_app.root_path), 'mock_data.db'),
        _os.path.join(_os.getcwd(), 'mock_data.db'),
        r'C:\cps_dev\mock_data.db',
    ]
    for p in candidates:
        if _os.path.exists(p):
            return p
    return candidates[0]


def _hedef_usta_session():
    from flask import session
    uid = (session.get('user_id') or session.get('kullanici_id') or
           session.get('id') or 0)
    uad = (session.get('user_name') or session.get('kullanici_ad') or
           session.get('ad') or session.get('username') or 'Sistem')
    return uid, uad


@hedef_bp.route('/onaylar/bekleyen', methods=['GET'])
@yetki_gerekli('hedef', 'can_view')
def hedef_onaylar_bekleyen():
    import sqlite3
    from flask import jsonify
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT id, emir_no, model_kod, model_adi,
                   miktar, proses_kodu, proses_adi,
                   personel_id, personel_ad,
                   tarih, saat, not_metin,
                   onay_durum, olusturma
              FROM uretim_kayit
             WHERE onay_durum = 'bekliyor'
             ORDER BY olusturma DESC, id DESC
        """)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({
            'success': True, 'ok': True,
            'kayitlar': rows, 'kayit_sayisi': len(rows)
        })
    except Exception as e:
        return jsonify({'success': False, 'ok': False,
                        'mesaj': str(e), 'kayitlar': []}), 500


@hedef_bp.route('/gecmis', methods=['GET'])
@yetki_gerekli('hedef', 'can_view')
def hedef_gecmis():
    import sqlite3
    from flask import jsonify, request
    try:
        limit = int(request.args.get('limit', 200))
    except Exception:
        limit = 200
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT id, emir_no, model_kod, model_adi,
                   miktar, proses_kodu, proses_adi,
                   personel_id, personel_ad,
                   tarih, saat, not_metin,
                   onay_durum, usta_id, usta_ad, usta_not,
                   onay_tarihi, olusturma
              FROM uretim_kayit
             WHERE onay_durum IN ('onaylandi', 'reddedildi')
             ORDER BY onay_tarihi DESC, olusturma DESC, id DESC
             LIMIT ?
        """, (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return jsonify({
            'success': True, 'ok': True,
            'kayitlar': rows, 'kayit_sayisi': len(rows)
        })
    except Exception as e:
        return jsonify({'success': False, 'ok': False,
                        'mesaj': str(e), 'kayitlar': []}), 500


@hedef_bp.route('/onayla', methods=['POST'])
@yetki_gerekli('hedef', 'can_approve')
def hedef_onayla():
    import sqlite3
    from flask import jsonify, request
    data = request.get_json(silent=True) or {}
    kayit_id = data.get('uretim_kayit_id') or data.get('id')
    not_metni = (data.get('not') or '').strip() or None
    if not kayit_id:
        return jsonify({'success': False, 'ok': False,
                        'mesaj': 'uretim_kayit_id gerekli'}), 400
    usta_id, usta_ad = _hedef_usta_session()
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            UPDATE uretim_kayit
               SET onay_durum = 'onaylandi',
                   usta_id = ?, usta_ad = ?, usta_not = ?,
                   onay_tarihi = datetime('now', 'localtime')
             WHERE id = ? AND onay_durum = 'bekliyor'
        """, (usta_id, usta_ad, not_metni, kayit_id))
        affected = cur.rowcount
        conn.commit()
        conn.close()
        if affected == 0:
            return jsonify({'success': False, 'ok': False,
                            'mesaj': 'Kayit bulunamadi veya zaten islem gormus'}), 404
        return jsonify({'success': True, 'ok': True,
                        'id': kayit_id, 'mesaj': 'Onaylandi'})
    except Exception as e:
        return jsonify({'success': False, 'ok': False, 'mesaj': str(e)}), 500


@hedef_bp.route('/reddet', methods=['POST'])
@yetki_gerekli('hedef', 'can_approve')
def hedef_reddet():
    import sqlite3
    from flask import jsonify, request
    data = request.get_json(silent=True) or {}
    kayit_id = data.get('uretim_kayit_id') or data.get('id')
    not_metni = (data.get('not') or '').strip()
    if not kayit_id:
        return jsonify({'success': False, 'ok': False,
                        'mesaj': 'uretim_kayit_id gerekli'}), 400
    if not not_metni:
        return jsonify({'success': False, 'ok': False,
                        'mesaj': 'Reddetme nedeni zorunlu'}), 400
    if len(not_metni) < 5:
        return jsonify({'success': False, 'ok': False,
                        'mesaj': 'En az 5 karakter girilmeli'}), 400
    usta_id, usta_ad = _hedef_usta_session()
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            UPDATE uretim_kayit
               SET onay_durum = 'reddedildi',
                   usta_id = ?, usta_ad = ?, usta_not = ?,
                   onay_tarihi = datetime('now', 'localtime')
             WHERE id = ? AND onay_durum = 'bekliyor'
        """, (usta_id, usta_ad, not_metni, kayit_id))
        affected = cur.rowcount
        conn.commit()
        conn.close()
        if affected == 0:
            return jsonify({'success': False, 'ok': False,
                            'mesaj': 'Kayit bulunamadi veya zaten islem gormus'}), 404
        return jsonify({'success': True, 'ok': True,
                        'id': kayit_id, 'mesaj': 'Reddedildi'})
    except Exception as e:
        return jsonify({'success': False, 'ok': False, 'mesaj': str(e)}), 500



# === CPS LOCAL HEDEF PLAN ENDPOINT ===
# Aktif emirler: mock_data.db'de en az 1 uretim kaydi olan emirler
# Her biri icin Korgun (get_emir_ozet) + CPS (onayli SUM) birlestirilir.

@hedef_bp.route('/plan', methods=['GET'])
@yetki_gerekli('hedef', 'can_view')
def hedef_plan():
    """GET /hedef/plan - Aktif emirler hedef/yapilan/kalan/yuzde."""
    import sqlite3
    from flask import jsonify
    db_path = _hedef_db_path()

    # 1) CPS local'den distinct emir_no'lar + onayli + bekleyen toplamlari
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cps_rows = conn.execute("""
            SELECT
                emir_no,
                MAX(model_kod) AS model_kod,
                MAX(model_adi) AS model_adi,
                SUM(CASE WHEN onay_durum='onaylandi' THEN miktar ELSE 0 END) AS cps_onayli,
                SUM(CASE WHEN onay_durum='bekliyor'  THEN miktar ELSE 0 END) AS cps_bekleyen,
                COUNT(*) AS kayit_sayisi
              FROM uretim_kayit
             GROUP BY emir_no
        """).fetchall()
        conn.close()
        cps_list = [dict(r) for r in cps_rows]
    except Exception as e:
        return jsonify({
            'success': False, 'ok': False,
            'mesaj': 'CPS DB hatasi: ' + str(e), 'emirler': []
        }), 500

    # 2) Korgun helper
    try:
        from modules.common import korgun as _kk_plan
    except Exception as e:
        return jsonify({
            'success': False, 'ok': False,
            'mesaj': 'Korgun helper yuklenemedi: ' + str(e), 'emirler': []
        }), 500

    # 3) Her emir icin Korgun ozeti + birlesik hesap
    sonuc = []
    hata_emirler = []
    for em in cps_list:
        try:
            emir_no_int = int(em['emir_no'])
        except Exception:
            continue

        cps_onayli = int(em['cps_onayli'] or 0)
        cps_bekleyen = int(em['cps_bekleyen'] or 0)
        model_local = em.get('model_kod') or em.get('model_adi') or ''

        try:
            ozet = _kk_plan.get_emir_ozet(emir_no_int) or {}
            ok = bool(ozet.get('ok'))
            hedef = int(ozet.get('hedef_adet', 0) or 0) if ok else 0
            korgun_yapilan = int(ozet.get('yapilan_adet', 0) or 0) if ok else 0
            model = (ozet.get('model_kod') or ozet.get('model_adi') or model_local) if ok else model_local
            # FAZ 4.4 - SIPARIS listesi (get_emir_ozet'ten)
            _sip_list = ozet.get('siparisler', []) if (ok and isinstance(ozet, dict)) else []
            _sip_strs = [str(_s.get('sip_no')) for _s in _sip_list
                         if isinstance(_s, dict) and _s.get('sip_no')]
            siparisler_str = ', '.join(_sip_strs)
            if not ok:
                hata_emirler.append({
                    'emir_no': str(emir_no_int),
                    'mesaj': ozet.get('mesaj', 'korgun_ozet_alinamadi')
                })
        except Exception as e:
            hedef = 0
            korgun_yapilan = 0
            model = model_local
            siparisler_str = ''
            hata_emirler.append({'emir_no': str(emir_no_int), 'mesaj': str(e)[:120]})

        toplam_yapilan = korgun_yapilan + cps_onayli
        kalan = max(0, hedef - toplam_yapilan)
        if hedef > 0:
            yuzde = round((toplam_yapilan / hedef) * 100, 1)
        else:
            yuzde = 0.0

        # === PLAN_MUSTERI_TEK_SATIR ===
        # === PLAN_TERMIN_PROSES_V1 ===
        sonuc.append({
            'emir_no': str(emir_no_int),
            'model': model,
            'musteri': (ozet.get('cari_adi') if ok else None),
            'termin': (ozet.get('termin_tarihi') if ok else None),
            'son_proses': None,  # asagidaki batch SQL ile doldurulur
            'siparisler': siparisler_str,
            'hedef': hedef,
            'korgun_yapilan': korgun_yapilan,
            'cps_yapilan': cps_onayli,
            'cps_bekleyen': cps_bekleyen,
            'yapilan': toplam_yapilan,
            'kalan': kalan,
            'yuzde': yuzde,
        })

    # === PLAN_TERMIN_PROSES_V1 ===
    # Son proses icin TEK batch SQL (Urt_con_gch + Proses_M JOIN)
    # Hata olursa eski yanit doner (try/except).
    try:
        if sonuc:
            from modules.common import korgun as _kk_sp
            _emir_listesi = []
            for _x in sonuc:
                try:
                    _emir_listesi.append(int(_x['emir_no']))
                except Exception:
                    pass
            if _emir_listesi:
                _con = _kk_sp._baglan()
                try:
                    _cur = _con.cursor()
                    _ph = ','.join(['%s'] * len(_emir_listesi))
                    # Her emir icin en son EndTarih'li proses (Cikan>0)
                    _cur.execute(f"""
                        SELECT t.EmirNo, t.Proses, t.EndTarih, pm.Tanim
                          FROM (
                            SELECT EmirNo, Proses, EndTarih,
                                   ROW_NUMBER() OVER (
                                       PARTITION BY EmirNo
                                       ORDER BY EndTarih DESC
                                   ) AS rn
                              FROM Urt_con_gch WITH(NOLOCK)
                             WHERE EmirNo IN ({_ph})
                               AND Cikan > 0
                          ) AS t
                          LEFT JOIN Proses_M pm WITH(NOLOCK) ON pm.Pro = t.Proses
                         WHERE t.rn = 1
                    """, tuple(_emir_listesi))
                    _proses_map = {}
                    for _r in _cur.fetchall():
                        _emirno_str = str(int(_r[0]))
                        _kod = _r[1]
                        _adi = _r[3]
                        # Tanim varsa Tanim, yoksa kod
                        _proses_map[_emirno_str] = _adi if _adi else _kod
                    _cur.close()
                finally:
                    _con.close()
                # sonuc listesine yaz
                for _x in sonuc:
                    _key = str(_x.get('emir_no'))
                    if _key in _proses_map:
                        _x['son_proses'] = _proses_map[_key]
    except Exception as _e:
        try:
            print(f'[PLAN_TERMIN_PROSES_V1 hata, son_proses bos]: {_e}')
        except Exception:
            pass

    # En yeni emir ustte (emir_no buyukten kucuge)
    sonuc.sort(key=lambda x: int(x['emir_no']), reverse=True)

    return jsonify({
        'success': True, 'ok': True,
        'emirler': sonuc,
        'emir_sayisi': len(sonuc),
        'hata_emirler': hata_emirler,
    })



# === CPS LOCAL HEDEF RAPOR ENDPOINT ===
# Tarih araligina gore onaylanmis CPS uretim kayitlari (3 blok ozet)

@hedef_bp.route('/rapor', methods=['GET'])
@yetki_gerekli('hedef', 'can_report')
def hedef_rapor():
    """GET /hedef/rapor?baslangic=YYYY-MM-DD&bitis=YYYY-MM-DD"""
    import sqlite3
    from datetime import date, timedelta
    from flask import jsonify, request

    # Parametreler
    bas = (request.args.get('baslangic') or '').strip()
    bit = (request.args.get('bitis') or '').strip()
    today = date.today()
    if not bit:
        bit = today.isoformat()
    if not bas:
        bas = (today - timedelta(days=7)).isoformat()

    # Tarih formati dogrulama (basit)
    import re as _re
    if not _re.match(r'^\d{4}-\d{2}-\d{2}$', bas):
        return jsonify({'ok': False, 'success': False,
                        'mesaj': 'gecersiz baslangic',
                        'personel_bazli': [], 'proses_bazli': [], 'emir_bazli': []}), 400
    if not _re.match(r'^\d{4}-\d{2}-\d{2}$', bit):
        return jsonify({'ok': False, 'success': False,
                        'mesaj': 'gecersiz bitis',
                        'personel_bazli': [], 'proses_bazli': [], 'emir_bazli': []}), 400

    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # --- PERSONEL BAZLI ---
        cur.execute("""
            SELECT
                COALESCE(NULLIF(personel_ad,''), 'Bilinmeyen') AS personel_ad,
                personel_id,
                SUM(miktar) AS toplam_miktar,
                COUNT(*) AS kayit_sayisi
              FROM uretim_kayit
             WHERE onay_durum = 'onaylandi'
               AND date(COALESCE(NULLIF(onay_tarihi,''), olusturma)) BETWEEN ? AND ?
             GROUP BY personel_id, personel_ad
             ORDER BY toplam_miktar DESC, personel_ad ASC
        """, (bas, bit))
        personel_bazli = []
        for r in cur.fetchall():
            d = dict(r)
            personel_bazli.append({
                'personel_id': d.get('personel_id'),
                'personel_ad': d.get('personel_ad') or 'Bilinmeyen',
                'toplam_miktar': int(d.get('toplam_miktar') or 0),
                'kayit_sayisi': int(d.get('kayit_sayisi') or 0),
            })

        # --- PROSES BAZLI ---
        cur.execute("""
            SELECT
                COALESCE(NULLIF(proses_adi,''), 'Bilinmeyen') AS proses_adi,
                SUM(miktar) AS toplam_miktar,
                COUNT(*) AS kayit_sayisi
              FROM uretim_kayit
             WHERE onay_durum = 'onaylandi'
               AND date(COALESCE(NULLIF(onay_tarihi,''), olusturma)) BETWEEN ? AND ?
             GROUP BY proses_adi
             ORDER BY toplam_miktar DESC, proses_adi ASC
        """, (bas, bit))
        proses_bazli = []
        for r in cur.fetchall():
            d = dict(r)
            proses_bazli.append({
                'proses_adi': d.get('proses_adi') or 'Bilinmeyen',
                'toplam_miktar': int(d.get('toplam_miktar') or 0),
                'kayit_sayisi': int(d.get('kayit_sayisi') or 0),
            })

        # --- EMIR BAZLI (raw) ---
        cur.execute("""
            SELECT
                emir_no,
                MAX(model_kod) AS model_kod,
                MAX(model_adi) AS model_adi,
                SUM(miktar) AS toplam_miktar,
                COUNT(*) AS kayit_sayisi
              FROM uretim_kayit
             WHERE onay_durum = 'onaylandi'
               AND date(COALESCE(NULLIF(onay_tarihi,''), olusturma)) BETWEEN ? AND ?
             GROUP BY emir_no
             ORDER BY toplam_miktar DESC, emir_no DESC
        """, (bas, bit))
        emir_raw = [dict(r) for r in cur.fetchall()]

        # FAZ 6.2 - YENI: kayit_listesi (raw uretim_kayit satirlari, detay rapor icin)
        cur.execute("""
            SELECT id, emir_no, proses_kodu, proses_adi, miktar,
                   personel_id, personel_ad, tarih, saat,
                   onay_durum, usta_id, usta_ad, usta_not,
                   not_metin, onay_tarihi, olusturma
              FROM uretim_kayit
             WHERE onay_durum IN ('onaylandi', 'bekliyor')
               AND date(COALESCE(NULLIF(onay_tarihi,''), olusturma)) BETWEEN ? AND ?
             ORDER BY olusturma DESC
             LIMIT 200
        """, (bas, bit))
        kayit_listesi = []
        for r in cur.fetchall():
            d = dict(r)
            kayit_listesi.append({
                'id': d.get('id'),
                'emir_no': str(d.get('emir_no') or ''),
                'proses_kodu': d.get('proses_kodu') or '',
                'proses_adi': d.get('proses_adi') or '',
                'miktar': int(d.get('miktar') or 0),
                'personel_id': d.get('personel_id'),
                'personel_ad': d.get('personel_ad') or '',
                'tarih': d.get('tarih') or '',
                'saat': d.get('saat') or '',
                'onay_durum': d.get('onay_durum') or '',
                'usta_id': d.get('usta_id'),
                'usta_ad': d.get('usta_ad') or '',
                'usta_not': d.get('usta_not') or '',
                'not_metin': d.get('not_metin') or '',
                'onay_tarihi': d.get('onay_tarihi') or '',
                'olusturma': d.get('olusturma') or '',
            })

        conn.close()

        # Korgun'dan model adi zenginlestir (her emir icin 1 cagri)
        try:
            from modules.common import korgun as _kk_rapor
        except Exception:
            _kk_rapor = None

        emir_bazli = []
        for e in emir_raw:
            emir_no_str = str(e.get('emir_no'))
            model = e.get('model_kod') or e.get('model_adi') or ''
            if _kk_rapor is not None:
                try:
                    ozet = _kk_rapor.get_emir_ozet(int(e.get('emir_no'))) or {}
                    if ozet.get('ok'):
                        model = ozet.get('model_kod') or model
                except Exception:
                    pass
            emir_bazli.append({
                'emir_no': emir_no_str,
                'model': model,
                'toplam_miktar': int(e.get('toplam_miktar') or 0),
                'kayit_sayisi': int(e.get('kayit_sayisi') or 0),
            })

        return jsonify({
            'ok': True, 'success': True,
            'baslangic': bas, 'bitis': bit,
            'personel_bazli': personel_bazli,
            'proses_bazli': proses_bazli,
            'emir_bazli': emir_bazli,
            'kayit_listesi': kayit_listesi,
        })
    except Exception as e:
        return jsonify({
            'ok': False, 'success': False,
            'mesaj': f'{type(e).__name__}: {str(e)[:200]}',
            'personel_bazli': [], 'proses_bazli': [], 'emir_bazli': [],
        }), 500



# === CPS LOCAL HEDEF DOGRULAMA ENDPOINT ===
# Veri kalitesi kontrolleri - 4 blok suspheli kayit listesi

@hedef_bp.route('/dogrulama', methods=['GET'])
@yetki_gerekli('hedef', 'can_view')
def hedef_dogrulama():
    """GET /hedef/dogrulama - 4 blok veri uyarisi."""
    import sqlite3
    from flask import jsonify

    db_path = _hedef_db_path()
    eski_bekleyen = []
    duplicate_adaylar = []
    gecersiz_proses = []
    hedefsiz_kayitlar = []
    korgun_hatasi = None

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 1) Eski bekleyen (24 saat+)
        cur.execute("""
            SELECT id, emir_no, proses_adi, miktar,
                   personel_ad, olusturma, onay_durum
              FROM uretim_kayit
             WHERE onay_durum = 'bekliyor'
               AND datetime(olusturma) < datetime('now','localtime','-24 hours')
             ORDER BY olusturma ASC
        """)
        eski_bekleyen = [dict(r) for r in cur.fetchall()]

        # 2) Duplicate adaylar (ayni emir+proses+personel+miktar tekrarli)
        cur.execute("""
            SELECT emir_no, proses_kodu, proses_adi, personel_id, personel_ad, miktar,
                   COUNT(*) as adet,
                   GROUP_CONCAT(id) as id_listesi,
                   MIN(olusturma) as ilk_kayit,
                   MAX(olusturma) as son_kayit
              FROM uretim_kayit
             WHERE onay_durum != 'reddedildi'
             GROUP BY emir_no, proses_kodu, personel_id, miktar
            HAVING COUNT(*) > 1
             ORDER BY MAX(olusturma) DESC
             LIMIT 100
        """)
        duplicate_adaylar = [dict(r) for r in cur.fetchall()]

        # 3) Gecersiz proses (sadece NUMERIC proses_kodu icin emir_alt_proses kontrol)
        # === FAZ 4.5b: legacy_kayitlar ===
        # proses_kodu tamamen 0-9 ise numeric kabul edilir.
        # Numeric olup emir_alt_proses'te yoksa -> gecersiz_proses (uyari)
        # Numeric DEGILSE -> legacy_kayitlar (bilgi amacli, uyari sayilmaz)
        cur.execute("""
            SELECT u.id, u.emir_no, u.proses_kodu, u.proses_adi,
                   u.miktar, u.personel_ad, u.onay_durum, u.olusturma
              FROM uretim_kayit u
              LEFT JOIN emir_alt_proses ap
                ON CAST(ap.id AS TEXT) = u.proses_kodu
               AND ap.emir_no = CAST(u.emir_no AS TEXT)
               AND ap.aktif = 1
             WHERE ap.id IS NULL
               AND u.proses_kodu IS NOT NULL
               AND u.proses_kodu != ''
               AND u.proses_kodu GLOB '[0-9]*'
               AND u.proses_kodu NOT GLOB '*[^0-9]*'
             ORDER BY u.id DESC
             LIMIT 100
        """)
        gecersiz_proses = [dict(r) for r in cur.fetchall()]

        # Legacy kayitlar (string proses_kodu, eski format)
        cur.execute("""
            SELECT u.id, u.emir_no, u.proses_kodu, u.proses_adi,
                   u.miktar, u.personel_ad, u.onay_durum, u.olusturma
              FROM uretim_kayit u
             WHERE u.proses_kodu IS NOT NULL
               AND u.proses_kodu != ''
               AND (u.proses_kodu NOT GLOB '[0-9]*'
                    OR u.proses_kodu GLOB '*[^0-9]*')
             ORDER BY u.id DESC
             LIMIT 100
        """)
        legacy_kayitlar = [dict(r) for r in cur.fetchall()]

        # 4) Hedefsiz emirler - distinct emir_no listesi
        cur.execute("SELECT DISTINCT emir_no FROM uretim_kayit")
        emirler = [r[0] for r in cur.fetchall()]
        conn.close()

        # Korgun'dan her emiri sorgula, hedef=0 olanlari topla
        try:
            from modules.common import korgun as _kk_dog
            for emir_no in emirler:
                try:
                    ozet = _kk_dog.get_emir_ozet(int(emir_no)) or {}
                    ok = ozet.get('ok')
                    hedef = int(ozet.get('hedef_adet', 0) or 0)
                    if not ok or hedef <= 0:
                        # Bu emirin kayitlarini ekle
                        c2 = sqlite3.connect(db_path)
                        c2.row_factory = sqlite3.Row
                        rows = c2.execute("""
                            SELECT id, emir_no, proses_adi, miktar,
                                   personel_ad, onay_durum, olusturma
                              FROM uretim_kayit
                             WHERE emir_no = ?
                             ORDER BY olusturma DESC
                             LIMIT 50
                        """, (emir_no,)).fetchall()
                        c2.close()
                        for r in rows:
                            d = dict(r)
                            d['_neden'] = ('emir_bulunamadi'
                                           if not ok else 'hedef_yok')
                            hedefsiz_kayitlar.append(d)
                except Exception as _e:
                    pass
        except Exception as e:
            korgun_hatasi = str(e)[:200]

    except Exception as e:
        return jsonify({
            'ok': False, 'success': False,
            'mesaj': f'{type(e).__name__}: {str(e)[:200]}',
            'eski_bekleyen': [], 'duplicate_adaylar': [],
            'gecersiz_proses': [], 'hedefsiz_kayitlar': [],
            'toplam_uyari': 0,
        }), 500

    toplam = (len(eski_bekleyen) + len(duplicate_adaylar) +
              len(gecersiz_proses) + len(hedefsiz_kayitlar))

    return jsonify({
        'ok': True, 'success': True,
        'eski_bekleyen': eski_bekleyen,
        'duplicate_adaylar': duplicate_adaylar,
        'gecersiz_proses': gecersiz_proses,
        'hedefsiz_kayitlar': hedefsiz_kayitlar,
        'legacy_kayitlar': legacy_kayitlar,
        'legacy_sayisi': len(legacy_kayitlar),
        'toplam_uyari': toplam,
        'korgun_hatasi': korgun_hatasi,
        'parametreler': {
            'eski_bekleyen_esik_saat': 24,
            'duplicate_window_sn': 60,
        },
    })



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
@yetki_gerekli('hedef.sablon', 'can_view')
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
@yetki_gerekli('hedef.sablon', 'can_create')
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
@yetki_gerekli('hedef.sablon', 'can_update')
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
@yetki_gerekli('hedef.sablon', 'can_delete')
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
@yetki_gerekli('hedef.sablon', 'can_view')
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
@yetki_gerekli('hedef', 'can_view')
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


# === FAZ 4.7 SABLON ROUTING (atki/govde alt emire dagit) ===
def _normalize_tr_local(s):
    if not s:
        return ''
    s = s.upper()
    repl = [('\u0130','I'),('\u0131','I'),('\u011e','G'),('\u011f','G'),
            ('\u00dc','U'),('\u00fc','U'),('\u015e','S'),('\u015f','S'),
            ('\u00d6','O'),('\u00f6','O'),('\u00c7','C'),('\u00e7','C')]
    for a,b in repl:
        s = s.replace(a,b)
    return s


def _kategori_sablon_adi(sablon_adi):
    """Sablon adindan kategori cikar. None = belirsiz, ana emirde kal."""
    s = _normalize_tr_local(sablon_adi or '')
    if 'ATKI' in s:  return 'ATKI'
    if 'GOVDE' in s: return 'GOVDE'
    if 'TABAN' in s: return 'TABAN'
    if 'SAYA' in s:  return 'SAYA'
    return None


def _kategori_alt_emir(model_kod, model_adi):
    """Alt emrin model bilgisinden kategori cikar."""
    mk = _normalize_tr_local(model_kod or '')
    ma = _normalize_tr_local(model_adi or '')
    text = mk + ' ' + ma
    if 'ATKI' in text:  return 'ATKI'
    if 'GOVDE' in text: return 'GOVDE'
    if 'TABAN' in text: return 'TABAN'
    if 'SAYA' in text:  return 'SAYA'
    return None


def _resolve_target_emir(ana_emir_no, sablon_adi):
    """Sablon hangi emire uygulanmali?
    Donen: (gercek_emir_no_str, sebep_str, emir_miktar_float_or_None)
    emir_miktar: alt emirin EmirMiktari (varsa), yoksa None (caller ana emirden alir).
    """
    kategori = _kategori_sablon_adi(sablon_adi)
    if not kategori:
        return (str(ana_emir_no), 'ana:sablon_belirsiz', None)

    try:
        from modules.common import korgun as _kk
        sonuc = _kk.get_alt_emirler(ana_emir_no)
    except Exception as e:
        return (str(ana_emir_no), 'ana:helper_hata:' + str(e)[:60], None)

    if not sonuc.get('ok'):
        return (str(ana_emir_no), 'ana:korgun_hata', None)

    alt_list = sonuc.get('alt_emirler') or []
    if not alt_list:
        return (str(ana_emir_no), 'ana:alt_yok', None)

    for alt in alt_list:
        alt_kat = _kategori_alt_emir(alt.get('model_kod'), alt.get('model_adi'))
        if alt_kat == kategori:
            return (str(alt['emir_no']),
                    'alt:' + kategori + ':' + str(alt['emir_no']),
                    alt.get('EmirMiktari'))

    return (str(ana_emir_no), 'ana:eslesme_yok', None)


# --- 7) Sablon uygula (emir -> emir_alt_proses) ---
@hedef_bp.route('/sablon/uygula', methods=['POST'])
@yetki_gerekli('hedef.sablon', 'can_update')
def hedef_sablon_uygula():
    from flask import jsonify, request
    data = request.get_json(silent=True) or {}
    emir_no = data.get('emir_no')
    sablon_id = data.get('sablon_id')

    result = _sablon_uygula_internal(emir_no, sablon_id, kaynak_prefix='sablon')
    status = result.pop('http_status', None)
    if status is None:
        status = 200 if result.get('ok') else 500
    return jsonify(result), status





# === FAZ 4.6 B3 emir-detay endpoint ===
# === FAZ 4.6 B3 emir-detay v2 ===
# Lazy detay: belirli emir_no listesi icin Urt_Em_gch SUM(Giren) ve RKOD
# Sayfa acilinca arka planda cagrilir, ekrandaki satirlar update edilir.
@hedef_bp.route('/siparis/emir-detay', methods=['GET'])
@yetki_gerekli('hedef', 'can_view')
def hedef_siparis_emir_detay():
    """GET /hedef/siparis/emir-detay?emirler=109772,109773,...
    Belirli emirler icin Urt_Em_gch'den SUM(Giren) ve RKOD donerir.
    """
    from flask import jsonify, request
    try:
        emirler_str = (request.args.get('emirler') or '').strip()
        if not emirler_str:
            return jsonify({'ok': False, 'mesaj': 'emirler param gerekli', 'detay': {}}), 400

        emir_nos = []
        for x in emirler_str.split(','):
            x = x.strip()
            if x.isdigit():
                emir_nos.append(int(x))
        if not emir_nos:
            return jsonify({'ok': False, 'mesaj': 'gecerli emir_no yok', 'detay': {}}), 400

        # Cok fazla emir limit
        emir_nos = emir_nos[:100]

        from modules.common import korgun as _kk
        con = _kk._baglan()
        try:
            cur = con.cursor()
            placeholders = ','.join(['%s'] * len(emir_nos))
            # Once Urt_Em_gch
            cur.execute(f"""
                SELECT EmirNo,
                       COALESCE(SUM(Giren), 0) AS toplam_giren,
                       MAX(CASE WHEN RKOD IS NOT NULL AND RKOD > 0 AND RKOD < 100
                                THEN RKOD ELSE NULL END) AS rkod_max,
                       MIN(CASE WHEN RKOD IS NOT NULL AND RKOD > 0 AND RKOD < 100
                                THEN RKOD ELSE NULL END) AS rkod_min
                FROM Urt_Em_gch WITH(NOLOCK)
                WHERE EmirNo IN ({placeholders})
                GROUP BY EmirNo
            """, tuple(emir_nos))
            detay = {}
            eksik_rkod = []
            for r in cur.fetchall():
                e_no = int(r[0])
                # Once max'i, yoksa min'i kullan (her ikisi de < 100)
                rkod = r[2] if r[2] is not None else r[3]
                detay[str(e_no)] = {
                    'EmirMiktari': float(r[1] or 0) or None,
                    'RKOD': rkod,
                }
                if rkod is None:
                    eksik_rkod.append(e_no)

            # Fallback: RKOD bulunamayan emirler icin Urt_con_gch dene
            if eksik_rkod:
                ph2 = ','.join(['%s'] * len(eksik_rkod))
                try:
                    cur.execute(f"""
                        SELECT EmirNo,
                               MAX(CASE WHEN RKOD IS NOT NULL AND RKOD > 0 AND RKOD < 100
                                        THEN RKOD ELSE NULL END) AS rkod_temiz
                        FROM Urt_con_gch WITH(NOLOCK)
                        WHERE EmirNo IN ({ph2})
                        GROUP BY EmirNo
                    """, tuple(eksik_rkod))
                    for r in cur.fetchall():
                        e_no = int(r[0])
                        if r[1] is not None:
                            detay[str(e_no)]['RKOD'] = r[1]
                except Exception:
                    pass

            cur.close()
        finally:
            con.close()

        return jsonify({'ok': True, 'detay': detay, 'emir_sayisi': len(detay)})
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200], 'detay': {}}), 500



# === FAZ 4.6 B3 sablon geri-al endpoint ===
# Toplu sablon uygulamasini geri al: secili emirlerin emir_alt_proses'inde
# kaynak='sablon:...' olanlari aktif=0 yapar. 'manuel' kayitlara dokunmaz.
@hedef_bp.route('/sablon/geri-al', methods=['POST'])
@yetki_gerekli('hedef.sablon', 'can_update')
def hedef_sablon_geri_al():
    """POST /hedef/sablon/geri-al
    Body: {emir_no_listesi: [...], sablon_id: optional}
    Eger sablon_id verilirse, sadece o sablondan gelenler silinir.
    Verilmezse, tum sablon-kaynakli kayitlar (kaynak='sablon:%') silinir.
    """
    import sqlite3
    from flask import jsonify, request
    data = request.get_json(silent=True) or {}
    emir_listesi = data.get('emir_no_listesi') or []
    sablon_id = data.get('sablon_id')  # opsiyonel

    if not isinstance(emir_listesi, list) or len(emir_listesi) == 0:
        return jsonify({'ok': False, 'mesaj': 'emir_no_listesi gerekli'}), 400

    # Emir no'lari string'e cevir (emir_alt_proses.emir_no TEXT)
    emir_strs = []
    for e in emir_listesi:
        s = str(e).strip()
        if s:
            emir_strs.append(s)
    if not emir_strs:
        return jsonify({'ok': False, 'mesaj': 'gecerli emir_no yok'}), 400

    uid, uad = _sablon_session()
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # === D5 FAZ C.5 P6: CPS_TRIGGER kapsami eklendi ===
        # Sablon adi (eger sablon_id verilmis ise)
        sablon_kaynak_pattern = 'sablon:%'
        cps_trigger_pattern = 'CPS_TRIGGER%'  # P6: CPS_TRIGGER_C5/_C6/...
        sablon_adi = None
        if sablon_id:
            try:
                sablon_id_int = int(sablon_id)
                row = conn.execute(
                    "SELECT sablon_adi FROM sablon WHERE id=?",
                    (sablon_id_int,)
                ).fetchone()
                if row:
                    sablon_adi = row['sablon_adi']
                    sablon_kaynak_pattern = 'sablon:' + sablon_adi
                    cps_trigger_pattern = 'CPS_TRIGGER%:' + sablon_adi
            except Exception:
                pass

        # Once kac kayit etkilenecek say
        placeholders = ','.join(['?'] * len(emir_strs))
        sayim = conn.execute(f"""
            SELECT COUNT(*) FROM emir_alt_proses
             WHERE emir_no IN ({placeholders})
               AND aktif = 1
               AND (kaynak LIKE ? OR kaynak LIKE ?)
        """, tuple(emir_strs) + (sablon_kaynak_pattern, cps_trigger_pattern)).fetchone()[0]

        # === geri-al kolon fix ===
        # emir_alt_proses tablosunda guncelleme/guncelleyen kolonlari yok
        # Sadece aktif=0 set et
        cur = conn.execute(f"""
            UPDATE emir_alt_proses
               SET aktif = 0
             WHERE emir_no IN ({placeholders})
               AND aktif = 1
               AND (kaynak LIKE ? OR kaynak LIKE ?)
        """, tuple(emir_strs) + (sablon_kaynak_pattern, cps_trigger_pattern))
        affected = cur.rowcount

        # Etkilenen emir sayisi (distinct)
        emir_sayim = conn.execute(f"""
            SELECT COUNT(DISTINCT emir_no) FROM emir_alt_proses
             WHERE emir_no IN ({placeholders})
               AND aktif = 0
               AND (kaynak LIKE ? OR kaynak LIKE ?)
        """, tuple(emir_strs) + (sablon_kaynak_pattern, cps_trigger_pattern)).fetchone()[0]

        conn.commit()
        conn.close()

        return jsonify({
            'ok': True,
            'silinen_proses_sayisi': affected,
            'etkilenen_emir_sayisi': emir_sayim,
            'sablon_adi': sablon_adi or 'tum sablonlar',
            'mesaj': str(affected) + ' proses geri alindi (' +
                     str(emir_sayim) + ' emir).'
        })
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200]}), 500



# === PLAN_DETAY_V3 endpoint ===
# GET /hedef/plan-detay/<emir_no> - Hiyerarsik detay
# Atki/Govde alt emirleri + Ana emir + Korgun+CPS birlesik
@hedef_bp.route('/plan-detay/<int:emir_no>', methods=['GET'])
@hedef_yetkili
def hedef_plan_detay(emir_no):
    """Hiyerarsik detay - Atki/Govde/Ana, Korgun+CPS birlesik."""
    import sqlite3
    from flask import jsonify
    from modules.common import korgun as _kk_pd

    # 1) Ana emir ozeti (mevcut helper)
    try:
        ozet = _kk_pd.get_emir_ozet(emir_no)
    except Exception as e:
        return jsonify({
            'ok': False,
            'mesaj': 'Korgun erisilemiyor: ' + str(e)[:120]
        }), 500

    if not ozet or not ozet.get('ok'):
        return jsonify({
            'ok': False,
            'mesaj': 'Emir bulunamadi',
            'kod': 'EMIR_YOK'
        }), 404

    hedef_toplam = int(ozet.get('hedef_adet', 0) or 0)

    # 2) Alt emirler (Urt_Em2Em + Urt_Emir + StokKart)
    alt_emirler = []  # [{emir_no, model_kod, model_adi, kategori}]
    tum_emir_listesi = [emir_no]

    try:
        con = _kk_pd._baglan()
        try:
            cur = con.cursor()
            # /* FAZ 4.10 ALT EMIR UNION ALL */
            # Alt emirler hem Urt_Emir hem Urtx_Emir tablosunda olabilir
            cur.execute("""
                SELECT e.EmirNo, e.ModelKod, e.Tip, e.Location,
                       sk.Tanim AS ModelAdi
                  FROM Urt_Em2Em em WITH(NOLOCK)
                  INNER JOIN Urt_Emir e WITH(NOLOCK) ON e.EmirNo = em.EmirNo_YM
                  LEFT JOIN StokKart sk WITH(NOLOCK) ON sk.SKOD = e.ModelKod
                 WHERE em.EmirNo = %s
                UNION ALL
                SELECT e.EmirNo, e.ModelKod, e.Tip, e.Location,
                       sk.Tanim AS ModelAdi
                  FROM Urt_Em2Em em WITH(NOLOCK)
                  INNER JOIN Urtx_Emir e WITH(NOLOCK) ON e.EmirNo = em.EmirNo_YM
                  LEFT JOIN StokKart sk WITH(NOLOCK) ON sk.SKOD = e.ModelKod
                 WHERE em.EmirNo = %s
            """, (emir_no, emir_no))
            for r in cur.fetchall():
                alt_no = int(r[0])
                model_kod = r[1] or ''
                model_adi = r[4] or ''
                kategori = _alt_parca_kategori(model_kod, model_adi)
                alt_emirler.append({
                    'emir_no': alt_no,
                    'model_kod': model_kod,
                    'model_adi': model_adi,
                    'tip': r[2],
                    'location': r[3],
                    'kategori': kategori,
                })
                tum_emir_listesi.append(alt_no)

            # 3) Korgun proses dagilimi (TUM emirler icin batch)
            korgun_map = {}  # emir_no -> [(proses_kod, proses_adi, yapilan, son_tarih)]
            if tum_emir_listesi:
                ph = ','.join(['%s'] * len(tum_emir_listesi))
                cur.execute(f"""
                    SELECT g.EmirNo, g.Proses, pm.Tanim,
                           SUM(g.Cikan) AS yapilan,
                           MAX(g.EndTarih) AS son_tarih
                      FROM Urt_con_gch g WITH(NOLOCK)
                      LEFT JOIN Proses_M pm WITH(NOLOCK) ON pm.Pro = g.Proses
                     WHERE g.EmirNo IN ({ph})
                       AND g.Cikan > 0
                     GROUP BY g.EmirNo, g.Proses, pm.Tanim
                """, tuple(tum_emir_listesi))
                for r in cur.fetchall():
                    en = int(r[0])
                    if en not in korgun_map:
                        korgun_map[en] = []
                    korgun_map[en].append({
                        'kod': r[1],
                        'adi': r[2] or r[1],
                        'yapilan': int(float(r[3] or 0)),
                        'son_tarih': r[4].isoformat() if r[4] else None,
                        'kaynak': 'korgun',
                    })
            cur.close()
        finally:
            con.close()
    except Exception as e:
        try:
            print(f'[PLAN_DETAY_V3 Korgun hata]: {e}')
        except Exception:
            pass
        korgun_map = {}

    # 4) CPS proses dagilimi (mock_data.db.uretim_kayit batch)
    cps_map = {}  # emir_no -> [(proses_kod, proses_adi, yapilan, son_tarih)]
    cps_toplam_map = {}  # emir_no -> toplam onayli adet
    try:
        db_path = _hedef_db_path()
        cnn = sqlite3.connect(db_path)
        ph = ','.join(['?'] * len(tum_emir_listesi))
        rows = cnn.execute(f"""
            SELECT CAST(emir_no AS INTEGER) AS en,
                   COALESCE(proses_kodu, '') AS kod,
                   COALESCE(proses_adi, '') AS adi,
                   SUM(CAST(miktar AS INTEGER)) AS yapilan,
                   MAX(COALESCE(onay_tarihi, tarih)) AS son_tarih
              FROM uretim_kayit
             WHERE CAST(emir_no AS INTEGER) IN ({ph})
               AND COALESCE(onay_durum, '') = 'onaylandi'
             GROUP BY CAST(emir_no AS INTEGER), proses_kodu, proses_adi
        """, tuple(tum_emir_listesi)).fetchall()
        for r in rows:
            en = int(r[0])
            if en not in cps_map:
                cps_map[en] = []
                cps_toplam_map[en] = 0
            cps_map[en].append({
                'kod': r[1],
                'adi': r[2] or r[1],
                'yapilan': int(r[3] or 0),
                'son_tarih': r[4],
                'kaynak': 'cps',
            })
            cps_toplam_map[en] += int(r[3] or 0)
        cnn.close()
    except Exception as e:
        try:
            print(f'[PLAN_DETAY_V3 CPS hata]: {e}')
        except Exception:
            pass
        cps_map = {}
        cps_toplam_map = {}

    # 5) Birlestir: emir_no icin Korgun+CPS proses listesi (proses_adi anahtar)
    def _proses_birlestir(emirno):
        kayitlar = (korgun_map.get(emirno) or []) + (cps_map.get(emirno) or [])
        if not kayitlar:
            return []
        # proses_adi.lower() anahtar ile grupla
        bucket = {}
        for k in kayitlar:
            anahtar = (k['adi'] or '').strip().lower()
            if not anahtar:
                anahtar = '_kod_' + str(k['kod'])
            if anahtar not in bucket:
                bucket[anahtar] = {
                    'proses_adi': k['adi'],
                    'proses_kod': k['kod'],
                    'yapilan': 0,
                    'kaynaklar': set(),
                    'son_tarih': None,
                    'korgun_yapilan': 0,
                    'cps_yapilan': 0,
                }
            b = bucket[anahtar]
            b['yapilan'] += k['yapilan']
            b['kaynaklar'].add(k['kaynak'])
            if k['kaynak'] == 'korgun':
                b['korgun_yapilan'] += k['yapilan']
                # Korgun kodu varsa onu tercih et (numerik)
                if k['kod'] and str(k['kod']).isdigit():
                    b['proses_kod'] = k['kod']
            else:
                b['cps_yapilan'] += k['yapilan']
            # Son tarih guncelle
            if k['son_tarih']:
                if not b['son_tarih'] or k['son_tarih'] > b['son_tarih']:
                    b['son_tarih'] = k['son_tarih']

        sonuc = []
        for b in bucket.values():
            yp = b['yapilan']
            if hedef_toplam > 0:
                yuzde = round((yp / hedef_toplam) * 100, 1)
            else:
                yuzde = 0.0
            if yuzde >= 100:
                durum = 'tamam'
            elif yp > 0:
                durum = 'devam'
            else:
                durum = 'bekliyor'
            sonuc.append({
                'proses_kod': b['proses_kod'],
                'proses_adi': b['proses_adi'],
                'yapilan': yp,
                'toplam_hedef': hedef_toplam,
                'yuzde': yuzde,
                'durum': durum,
                'son_tarih': b['son_tarih'],
                'kaynaklar': sorted(list(b['kaynaklar'])),
                'korgun_yapilan': b['korgun_yapilan'],
                'cps_yapilan': b['cps_yapilan'],
            })
        return sonuc

    # 6) Ana proses listesi
    ana_prosesleri = _proses_birlestir(emir_no)

    # 7) Alt parca proses listeleri
    alt_parcalar = []
    for ae in alt_emirler:
        prosesler = _proses_birlestir(ae['emir_no'])
        ae_blok = {
            'kategori': ae['kategori'],
            'emir_no': ae['emir_no'],
            'model_kod': ae['model_kod'],
            'model_adi': ae['model_adi'],
            'location': ae['location'],
            'prosesler': prosesler,
        }
        alt_parcalar.append(ae_blok)

    # 8) "En geride kalan" siralama: tamamlanmis proses sayisi az olan ustte
    def _ilerleme_skoru(blok):
        prs = blok.get('prosesler') or []
        if not prs:
            return 0  # En geride
        tamam = sum(1 for p in prs if p['durum'] == 'tamam')
        return tamam / len(prs) if prs else 0

    alt_parcalar.sort(key=_ilerleme_skoru)

    # 9) Toplam yapilan = Korgun + CPS (ana + tum altlar)
    korgun_yapilan = int(ozet.get('yapilan_adet', 0) or 0)  # Korgun toplam
    cps_yapilan = sum(cps_toplam_map.values())
    toplam_yapilan = korgun_yapilan + cps_yapilan
    kalan = max(0, hedef_toplam - toplam_yapilan)

    # 10) Aktif/takildi/tamam durumu - tüm bloklardan
    # "Takildi" = ilk TAMAM olmayan proses (üretim sırasında)
    # Frontend siralayacak proses_kod numerik artan ile, ama backend'de de
    # bir aday hesaplayalim
    def _ilk_tamam_olmayan(prosesler_listesi):
        if not prosesler_listesi:
            return None
        # proses_kod numerik artan sirala (uretim sirasi)
        sirali = sorted(
            prosesler_listesi,
            key=lambda p: int(p['proses_kod']) if str(p['proses_kod']).isdigit() else 9999
        )
        for p in sirali:
            if p['durum'] != 'tamam':
                return p
        return None

    takildi = None  # {kategori, proses_adi, proses_kod, durum, son_tarih}
    for ap in alt_parcalar:
        p = _ilk_tamam_olmayan(ap.get('prosesler') or [])
        if p:
            takildi = {
                'kategori': ap['kategori'],
                'proses_adi': p['proses_adi'],
                'proses_kod': p['proses_kod'],
                'durum': p['durum'],
                'son_tarih': p['son_tarih'],
                'yapilan': p['yapilan'],
                'toplam_hedef': p['toplam_hedef'],
            }
            break
    if not takildi:
        # Alt yoksa veya hepsi tamam ise ana emir prosesleri
        p = _ilk_tamam_olmayan(ana_prosesleri)
        if p:
            takildi = {
                'kategori': 'Ana',
                'proses_adi': p['proses_adi'],
                'proses_kod': p['proses_kod'],
                'durum': p['durum'],
                'son_tarih': p['son_tarih'],
                'yapilan': p['yapilan'],
                'toplam_hedef': p['toplam_hedef'],
            }

    # === FAZ 4.7 MINI: alt parca proses listesi ===
    try:
        import sqlite3 as _sqlite_m47
        from config import Config as _Config_m47
        _con_m47 = _sqlite_m47.connect(_Config_m47.MOCK_DB_PATH)
        try:
            _con_m47.row_factory = _sqlite_m47.Row
            for _ap_m47 in alt_parcalar:
                _alt_emir_m47 = str(_ap_m47.get('emir_no') or '')
                if not _alt_emir_m47:
                    _ap_m47['prosesler'] = []
                    _ap_m47['mesaj'] = 'henuz sablon uygulanmadi'
                    continue
                _rows_m47 = _con_m47.execute("""
                    SELECT
                        ap.proses_adi AS proses_adi,
                        COALESCE(SUM(uk.miktar), 0) AS yapilan
                    FROM emir_alt_proses ap
                    LEFT JOIN uretim_kayit uk
                      ON CAST(uk.emir_no AS TEXT) = ap.emir_no
                     AND LOWER(TRIM(uk.proses_adi)) = LOWER(TRIM(ap.proses_adi))
                     AND uk.onay_durum IN ('onaylandi','bekliyor')
                    WHERE ap.emir_no = ?
                      AND ap.aktif = 1
                    GROUP BY ap.proses_adi, ap.siralama, ap.id
                    ORDER BY ap.siralama, ap.id
                """, (_alt_emir_m47,)).fetchall()
                _plist_m47 = []
                for _r_m47 in _rows_m47:
                    _plist_m47.append({
                        'proses_adi': _r_m47['proses_adi'] or '',
                        'yapilan': int(_r_m47['yapilan'] or 0),
                    })
                _ap_m47['prosesler'] = _plist_m47
                if not _plist_m47:
                    _ap_m47['mesaj'] = 'henuz sablon uygulanmadi'
                else:
                    _ap_m47['mesaj'] = None
        finally:
            _con_m47.close()
    except Exception as _e_m47:
        try:
            from flask import current_app as _ca_m47
            _ca_m47.logger.warning(
                'FAZ 4.7 MINI alt_parca proses enrich hatasi: ' + str(_e_m47)[:200]
            )
        except Exception:
            pass
        for _ap_m47 in alt_parcalar:
            _ap_m47.setdefault('prosesler', [])
            _ap_m47.setdefault('mesaj', None)
    # === /FAZ 4.7 MINI ===

    # === FAZ 4.7 DARBOGAZ ===
    # YAPILAN_DARBOGAZ = min(ATKI tamamlanan, GOVDE tamamlanan, MAMUL tamamlanan)
    # - ATKI/GOVDE: emir_alt_proses son siralanan proses (siralama MAX) - uretim_kayit toplam
    # - MAMUL: emir_alt_proses varsa siralama MAX, yoksa Korgun ana_prosesleri proses_kod MAX
    # - Sablon yoksa = 0 (sipariş ilerleyemez)
    try:
        import sqlite3 as _sqlite_h47
        from config import Config as _Config_h47

        def _h47_son_proses_miktari(emir_no_str):
            """emir_alt_proses siralama MAX olan prosesin uretim_kayit toplam miktari.
            Donen: (yapilan_int, son_proses_adi) veya (None, None) sablon yoksa.
            """
            _con_h47_l = _sqlite_h47.connect(_Config_h47.MOCK_DB_PATH)
            try:
                _row_h47 = _con_h47_l.execute("""
                    SELECT proses_adi, siralama, id
                    FROM emir_alt_proses
                    WHERE emir_no = ? AND aktif = 1
                    ORDER BY siralama DESC, id DESC
                    LIMIT 1
                """, (emir_no_str,)).fetchone()
                if not _row_h47:
                    return (None, None)
                _son_adi_h47 = _row_h47[0]
                _yp_h47 = _con_h47_l.execute("""
                    SELECT COALESCE(SUM(miktar), 0)
                    FROM uretim_kayit
                    WHERE CAST(emir_no AS TEXT) = ?
                      AND LOWER(TRIM(proses_adi)) = LOWER(TRIM(?))
                      AND onay_durum IN ('onaylandi','bekliyor')
                """, (emir_no_str, _son_adi_h47)).fetchone()
                return (int(_yp_h47[0] or 0), _son_adi_h47)
            finally:
                _con_h47_l.close()

        # ATKI/GOVDE: alt_parcalar uzerinden tara
        _atki_tamamlanan_h47 = 0
        _govde_tamamlanan_h47 = 0
        _atki_var_h47 = False
        _govde_var_h47 = False
        for _ap_h47 in alt_parcalar:
            _kat_h47 = (_ap_h47.get('kategori') or '').strip().lower()
            _emir_h47 = str(_ap_h47.get('emir_no') or '')
            if not _emir_h47:
                continue
            _yp_h47, _adi_h47 = _h47_son_proses_miktari(_emir_h47)
            if _kat_h47 in ('atki', 'atkı'):
                _atki_var_h47 = True
                _atki_tamamlanan_h47 = _yp_h47 or 0
                _ap_h47['son_proses_adi'] = _adi_h47
                _ap_h47['tamamlanan'] = _atki_tamamlanan_h47
            elif _kat_h47 in ('govde', 'gövde'):
                _govde_var_h47 = True
                _govde_tamamlanan_h47 = _yp_h47 or 0
                _ap_h47['son_proses_adi'] = _adi_h47
                _ap_h47['tamamlanan'] = _govde_tamamlanan_h47

        # MAMUL: emir_alt_proses ana emir icin var mi?
        _mamul_yp_h47, _mamul_adi_h47 = _h47_son_proses_miktari(str(emir_no))
        _mamul_kaynak_h47 = 'sablon'
        if _mamul_yp_h47 is None:
            # Fallback: Korgun ana_prosesleri proses_kod numerik MAX
            _mamul_kaynak_h47 = 'korgun_max'
            if ana_prosesleri:
                def _kod_int(p):
                    k = str(p.get('proses_kod') or '')
                    try:
                        return int(k) if k.isdigit() else -1
                    except Exception:
                        return -1
                _en_son_h47 = max(ana_prosesleri, key=_kod_int)
                if _kod_int(_en_son_h47) >= 0:
                    _mamul_yp_h47 = int(_en_son_h47.get('yapilan') or 0)
                    _mamul_adi_h47 = _en_son_h47.get('proses_adi')
                else:
                    _mamul_yp_h47 = 0
                    _mamul_adi_h47 = None
            else:
                _mamul_yp_h47 = 0
                _mamul_adi_h47 = None
        _mamul_tamamlanan_h47 = _mamul_yp_h47 or 0

        # YAPILAN_DARBOGAZ = min(ATKI, GOVDE, MAMUL)
        # Eger ATKI/GOVDE alt parcasi yok ise -> sadece MAMUL
        _adaylar_h47 = []
        _adaylar_h47.append(('MAMUL', _mamul_tamamlanan_h47))
        if _atki_var_h47:
            _adaylar_h47.append(('ATKI', _atki_tamamlanan_h47))
        if _govde_var_h47:
            _adaylar_h47.append(('GOVDE', _govde_tamamlanan_h47))

        _en_dusuk_h47 = min(_adaylar_h47, key=lambda x: x[1])
        _yapilan_darbogaz_h47 = int(_en_dusuk_h47[1])
        _darbogaz_kategori_h47 = _en_dusuk_h47[0]
        _kalan_darbogaz_h47 = max(0, hedef_toplam - _yapilan_darbogaz_h47)
        _yuzde_darbogaz_h47 = round((_yapilan_darbogaz_h47 / hedef_toplam) * 100, 1) if hedef_toplam > 0 else 0.0

        _darbogaz_data_h47 = {
            'yapilan_darbogaz': _yapilan_darbogaz_h47,
            'kalan_darbogaz': _kalan_darbogaz_h47,
            'yuzde_darbogaz': _yuzde_darbogaz_h47,
            'darbogaz_kategori': _darbogaz_kategori_h47,
            'darbogaz_detay': {
                'atki_tamamlanan': _atki_tamamlanan_h47 if _atki_var_h47 else None,
                'govde_tamamlanan': _govde_tamamlanan_h47 if _govde_var_h47 else None,
                'mamul_tamamlanan': _mamul_tamamlanan_h47,
                'mamul_son_proses': _mamul_adi_h47,
                'mamul_kaynak': _mamul_kaynak_h47,
            }
        }
    except Exception as _e_h47:
        try:
            from flask import current_app as _ca_h47
            _ca_h47.logger.warning(
                'FAZ 4.7 DARBOGAZ hesap hatasi: ' + str(_e_h47)[:200]
            )
        except Exception:
            pass
        _darbogaz_data_h47 = {
            'yapilan_darbogaz': None,
            'kalan_darbogaz': None,
            'yuzde_darbogaz': None,
            'darbogaz_kategori': None,
            'darbogaz_detay': None,
        }
    # === /FAZ 4.7 DARBOGAZ ===


    return jsonify({
        'ok': True,
        'emir_no': emir_no,
        'model_kod': ozet.get('model_kod'),
        'model_adi': ozet.get('model_adi'),
        'musteri': ozet.get('cari_adi'),
        'termin': ozet.get('termin_tarihi'),
        'tip': ozet.get('tip'),
        'tip_aciklama': ozet.get('tip_aciklama'),
        'location': ozet.get('location'),
        'hedef': hedef_toplam,
        'yapilan': toplam_yapilan,
        'yapilan_korgun': korgun_yapilan,
        'yapilan_cps': cps_yapilan,
        'kalan': kalan,
        'siparisler': ozet.get('siparisler', []),
        'ana_prosesleri': ana_prosesleri,
        'alt_parcalar': alt_parcalar,
        'takildi': takildi,
        'yapilan_darbogaz': _darbogaz_data_h47.get('yapilan_darbogaz'),
        'kalan_darbogaz': _darbogaz_data_h47.get('kalan_darbogaz'),
        'yuzde_darbogaz': _darbogaz_data_h47.get('yuzde_darbogaz'),
        'darbogaz_kategori': _darbogaz_data_h47.get('darbogaz_kategori'),
        'darbogaz_detay': _darbogaz_data_h47.get('darbogaz_detay'),
    })


def _alt_parca_kategori(model_kod, model_adi):
    """ModelKod ve ModelAdi'ndan Atki/Govde tespit (frontend ile uyumlu)."""
    mk = (model_kod or '').upper()
    ma = (model_adi or '').upper()
    if 'ATKI' in mk or 'ATKI' in ma or 'ATKİ' in ma:
        return 'Atkı'
    if 'GOVDE' in mk or 'GOVDE' in ma or 'GÖVDE' in ma:
        return 'Gövde'
    if 'TABAN' in mk or 'TABAN' in ma:
        return 'Taban'
    if 'SAYA' in mk or 'SAYA' in ma:
        return 'Saya'
    return 'Diğer'


# === FAZ 4.8 F2.1: PLAN listesi icin batch darbogaz hesabi ===
# Mevcut /hedef/plan endpoint'i degismez, frontend bunu lazy yukler.
@hedef_bp.route('/plan-darbogaz', methods=['GET'])
@hedef_yetkili
def hedef_plan_darbogaz():
    """Birden fazla emir icin tek seferde darbogaz hesabi.
    GET /hedef/plan-darbogaz?emirler=110626,110627,...
    """
    import sqlite3 as _sq_f21
    from flask import jsonify, request
    from modules.common import korgun as _kk_f21
    from config import Config as _Cfg_f21
    import re as _re_f21

    # 1) Parametre kontrolu
    raw = (request.args.get('emirler') or '').strip()
    if not raw:
        return jsonify({'ok': False, 'mesaj': 'emirler parametresi zorunlu'}), 400

    # Sadece rakam ve virgul kabul et
    if not _re_f21.match(r'^[\d,\s]+$', raw):
        return jsonify({'ok': False, 'mesaj': 'gecersiz format'}), 400

    parts = [p.strip() for p in raw.split(',') if p.strip()]
    emirler = []
    seen_f21 = set()
    for p in parts:
        if not p.isdigit():
            continue
        try:
            n = int(p)
        except Exception:
            continue
        if n <= 0:
            continue
        if n in seen_f21:
            continue
        seen_f21.add(n)
        emirler.append(n)

    if not emirler:
        return jsonify({'ok': False, 'mesaj': 'gecerli emir yok'}), 400

    # Limit: max 100
    if len(emirler) > 100:
        return jsonify({'ok': False, 'mesaj': 'maksimum 100 emir'}), 400

    sonuc = {}

    # 2) Korgun bagli sorgular (alt emirler + ana proses + hedef)
    alt_emir_map = {}     # ana_no (int) -> [{alt_no, model_kod, model_adi, kategori}]
    ana_proses_map = {}   # ana_no -> [{proses_kod, yapilan}]
    hedef_map = {}        # ana_no -> hedef_int
    fis_map = {}          # ana_no -> [fis_no_list]

    try:
        kcon = _kk_f21._baglan()
        try:
            kcur = kcon.cursor()

            # --- Sorgu 1: Alt emirler (Tip='Y') ---
            ph1 = ','.join(['%s'] * len(emirler))
            kcur.execute(f"""
                SELECT em2em.EmirNo AS AnaNo,
                       e.EmirNo AS AltNo,
                       e.ModelKod,
                       ISNULL(m.Tanim, e.ModelKod) AS ModelAdi
                FROM Urt_Em2Em em2em WITH (NOLOCK)
                INNER JOIN Urt_Emir e WITH (NOLOCK) ON e.EmirNo = em2em.EmirNo_YM
                LEFT JOIN Model_M m WITH (NOLOCK) ON m.ModelKod = e.ModelKod
                WHERE em2em.EmirNo IN ({ph1})
                  AND UPPER(LTRIM(RTRIM(ISNULL(e.Tip,'')))) = 'Y'
            """, tuple(emirler))
            for r in kcur.fetchall():
                ana_no = int(r[0])
                alt_no = int(r[1])
                mk = r[2] or ''
                ma = r[3] or ''
                # Kategori belirle (ATKI/GOVDE/TABAN/SAYA/...)
                kat = _alt_parca_kategori(mk, ma)
                alt_emir_map.setdefault(ana_no, []).append({
                    'alt_no': alt_no,
                    'model_kod': mk,
                    'model_adi': ma,
                    'kategori': kat,
                })

            # --- Sorgu 2: Ana emir Korgun prosesleri (MAMUL son icin) ---
            kcur.execute(f"""
                SELECT g.EmirNo, g.Proses, SUM(g.Cikan) AS yapilan
                FROM Urt_con_gch g WITH (NOLOCK)
                WHERE g.EmirNo IN ({ph1}) AND g.Cikan > 0
                GROUP BY g.EmirNo, g.Proses
            """, tuple(emirler))
            for r in kcur.fetchall():
                ana_proses_map.setdefault(int(r[0]), []).append({
                    'proses_kod': r[1],
                    'yapilan': int(float(r[2] or 0)),
                })

            # --- Sorgu 3: FisNo listesi (hedef icin) ---
            kcur.execute(f"""
                SELECT EmirNo, FisNo
                FROM Urt_Em_gch WITH (NOLOCK)
                WHERE EmirNo IN ({ph1})
                  AND FisNo IS NOT NULL AND FisNo > 0
                GROUP BY EmirNo, FisNo
            """, tuple(emirler))
            for r in kcur.fetchall():
                fis_map.setdefault(int(r[0]), []).append(int(r[1]))

            # --- Sorgu 4: Hedef hesabi - emir basina FisNo bazli SUM ---
            # Her ana emir icin kendi modelini ve FisNo'larini al, Siparis_Har'dan toplam
            # Once emirin modelini ogren
            kcur.execute(f"""
                SELECT EmirNo, ModelKod
                FROM Urt_Emir WITH (NOLOCK)
                WHERE EmirNo IN ({ph1})
            """, tuple(emirler))
            ana_model_map = {int(r[0]): r[1] for r in kcur.fetchall()}

            # Her ana emir icin hedefi hesapla (FisNo bazli)
            for ana in emirler:
                model = ana_model_map.get(ana)
                if not model:
                    hedef_map[ana] = 0
                    continue

                fis_listesi = fis_map.get(ana, [])
                if fis_listesi:
                    # FisNo bazli: sadece bu siparis(ler)den
                    ph_f = ','.join(['%s'] * len(fis_listesi))
                    kcur.execute(f"""
                        SELECT COALESCE(SUM(Miktar), 0)
                        FROM Siparis_Har WITH (NOLOCK)
                        WHERE SKOD = %s
                          AND SipNo IN ({ph_f})
                          AND LTRIM(RTRIM(ISNULL(Durum,''))) = ''
                    """, tuple([model] + fis_listesi))
                else:
                    # Fallback: tum siparisler
                    kcur.execute("""
                        SELECT COALESCE(SUM(Miktar), 0)
                        FROM Siparis_Har WITH (NOLOCK)
                        WHERE SKOD = %s
                          AND LTRIM(RTRIM(ISNULL(Durum,''))) = ''
                    """, (model,))
                hedef_map[ana] = int(float(kcur.fetchone()[0] or 0))

            kcur.close()
        finally:
            kcon.close()
    except Exception as e_k:
        return jsonify({
            'ok': False,
            'mesaj': 'Korgun erisim hatasi: ' + str(e_k)[:120]
        }), 500

    # 3) SQLite (CPS) sorgular
    alt_son_proses = {}      # alt_no_str -> son_proses_adi
    alt_yapilan = {}         # (alt_no_str, lower(proses_adi)) -> yapilan
    try:
        ccon = _sq_f21.connect(_Cfg_f21.MOCK_DB_PATH)
        try:
            ccon.row_factory = _sq_f21.Row

            # Tum alt emir id'lerini topla
            tum_alt = []
            for ana, alt_list in alt_emir_map.items():
                for a in alt_list:
                    tum_alt.append(str(a['alt_no']))

            if tum_alt:
                ph_a = ','.join(['?'] * len(tum_alt))

                # Sorgu 5: Son sirali proses (her alt icin)
                rows = ccon.execute(f"""
                    SELECT emir_no, proses_adi
                    FROM (
                        SELECT emir_no, proses_adi,
                               ROW_NUMBER() OVER (
                                   PARTITION BY emir_no
                                   ORDER BY siralama DESC, id DESC
                               ) AS rn
                        FROM emir_alt_proses
                        WHERE emir_no IN ({ph_a}) AND aktif = 1
                    )
                    WHERE rn = 1
                """, tuple(tum_alt)).fetchall()
                for r in rows:
                    alt_son_proses[str(r['emir_no'])] = r['proses_adi']

                # Sorgu 6: uretim_kayit toplam (her alt + proses_adi icin)
                rows2 = ccon.execute(f"""
                    SELECT CAST(emir_no AS TEXT) AS en,
                           LOWER(TRIM(proses_adi)) AS pa,
                           COALESCE(SUM(miktar), 0) AS yp
                    FROM uretim_kayit
                    WHERE CAST(emir_no AS TEXT) IN ({ph_a})
                      AND onay_durum IN ('onaylandi','bekliyor')
                    GROUP BY CAST(emir_no AS TEXT), LOWER(TRIM(proses_adi))
                """, tuple(tum_alt)).fetchall()
                for r in rows2:
                    alt_yapilan[(r['en'], r['pa'])] = int(r['yp'] or 0)
        finally:
            ccon.close()
    except Exception as e_s:
        return jsonify({
            'ok': False,
            'mesaj': 'CPS DB hatasi: ' + str(e_s)[:120]
        }), 500

    # 4) Her ana emir icin darbogaz hesapla
    for ana in emirler:
        try:
            hedef = hedef_map.get(ana, 0)
            alt_list = alt_emir_map.get(ana, [])

            # ATKI/GOVDE tamamlanan
            atki_t = 0
            atki_var = False
            govde_t = 0
            govde_var = False
            for a in alt_list:
                kat_lower = (a.get('kategori') or '').lower()
                alt_str = str(a['alt_no'])
                son_p = alt_son_proses.get(alt_str)
                if son_p:
                    yp = alt_yapilan.get((alt_str, son_p.strip().lower()), 0)
                else:
                    yp = 0

                if kat_lower in ('atki', 'atkı'):
                    atki_var = True
                    atki_t = yp
                elif kat_lower in ('govde', 'gövde'):
                    govde_var = True
                    govde_t = yp

            # MAMUL tamamlanan: emir_alt_proses ana icin var mi?
            mamul_son = alt_son_proses.get(str(ana))
            if mamul_son:
                # ana emir sablonlanmis (nadir - genelde yok)
                mamul_t = alt_yapilan.get((str(ana), mamul_son.strip().lower()), 0)
            else:
                # Fallback: Korgun proses_kod numerik MAX
                ana_prs = ana_proses_map.get(ana, [])
                if ana_prs:
                    def _kod_int_f21(p):
                        k = str(p.get('proses_kod') or '')
                        return int(k) if k.isdigit() else -1
                    en_son = max(ana_prs, key=_kod_int_f21)
                    if _kod_int_f21(en_son) >= 0:
                        mamul_t = int(en_son.get('yapilan') or 0)
                    else:
                        mamul_t = 0
                else:
                    mamul_t = 0

            # YAPILAN_DARBOGAZ = min(adaylar)
            adaylar = [('MAMUL', mamul_t)]
            if atki_var:
                adaylar.append(('ATKI', atki_t))
            if govde_var:
                adaylar.append(('GOVDE', govde_t))
            en_dusuk = min(adaylar, key=lambda x: x[1])

            yapilan_d = int(en_dusuk[1])
            darbogaz_kat = en_dusuk[0]
            kalan_d = max(0, hedef - yapilan_d)
            yuzde_d = round((yapilan_d / hedef * 100), 1) if hedef > 0 else 0.0

            sonuc[str(ana)] = {
                'yapilan_darbogaz': yapilan_d,
                'kalan_darbogaz': kalan_d,
                'yuzde_darbogaz': yuzde_d,
                'darbogaz_kategori': darbogaz_kat,
                'hedef': hedef,
            }
        except Exception as e_loop:
            # Bu emirde hata olsa bile diğerleri devam etsin
            sonuc[str(ana)] = {
                'yapilan_darbogaz': None,
                'kalan_darbogaz': None,
                'yuzde_darbogaz': None,
                'darbogaz_kategori': None,
                'hedef': None,
                'hata': str(e_loop)[:80],
            }

    return jsonify({
        'ok': True,
        'darbogaz': sonuc,
        'emir_sayisi': len(emirler),
    })
# === /FAZ 4.8 F2.1 ===
# =====================================================
# DARBOGAZ ENTEGRASYONU (06.05.2026)
# F22'ye dokunmaz, ayri endpoint olarak calisir.
# =====================================================
@hedef_bp.route('/darbogaz-ozet', methods=['GET'])
@yetki_gerekli('hedef', 'can_view')
def darbogaz_ozet():
    """
    siparis_darbogaz tablosundan ozet doner.
    BUYUK_SAPMA -> KRITIK, digerleri -> NORMAL (frontend uyumu).
    """
    import sqlite3
    from config import Config
    from flask import jsonify
    
    try:
        conn = sqlite3.connect(Config.MOCK_DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                siparis_no,
                ana_darbogaz,
                alt_darbogaz_proses,
                sapma_yuzde,
                seviye,
                guncelleme
            FROM siparis_darbogaz
            WHERE ana_darbogaz IS NOT NULL
            ORDER BY 
                CASE seviye
                    WHEN 'BUYUK_SAPMA' THEN 1
                    WHEN 'IZLE' THEN 2
                    ELSE 3
                END,
                sapma_yuzde DESC
        """)
        rows = cur.fetchall()
        conn.close()
        
        sonuc = []
        for r in rows:
            seviye_norm = 'KRITIK' if r['seviye'] == 'BUYUK_SAPMA' else 'NORMAL'
            sonuc.append({
                'siparis_no': str(r['siparis_no']),
                'ana': r['ana_darbogaz'],
                'proses': r['alt_darbogaz_proses'],
                'yuzde': round(r['sapma_yuzde'] or 0, 1),
                'seviye': seviye_norm,
                'guncelleme': r['guncelleme'],
            })
        
        return jsonify(sonuc)
    except Exception as e:
        from flask import jsonify
        return jsonify([])

# === FAZ 6.3 - OPERASYON KPI ENDPOINT ===
@hedef_bp.route('/operasyon-ozet', methods=['GET'])
@yetki_gerekli('hedef', 'can_view')
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


# ============================================================
# FAZ 7 - PERSONEL SEKMESI (HEDEF GENISLETME)
# 13.05.2026 - Faz 1: Sadece okuma
# Yetki: admin/adem/altan/Yonetim/Planlama/Usta(Tip)
# ============================================================

@hedef_bp.route('/personel/liste', methods=['GET'])
@yetki_gerekli('hedef.personel', 'can_view')
def personel_liste():
    """
    PERSONEL sekmesi - liste API (FAZ 1: sadece okuma)
    """
    try:
        rows = q("""
            SELECT 
                pk.id,
                pk.ad,
                pk.kullanici_adi,
                pk.aktif,
                COUNT(uk.id) as toplam_kayit,
                COALESCE(SUM(CAST(uk.miktar AS REAL)), 0) as toplam_miktar,
                MAX(uk.onay_tarihi) as son_kayit_tarihi
            FROM personel_kullanici pk
            LEFT JOIN uretim_kayit uk ON uk.personel_id = pk.id
            GROUP BY pk.id, pk.ad, pk.kullanici_adi, pk.aktif
            ORDER BY toplam_kayit DESC, pk.ad ASC
            LIMIT 500
        """)
        return jsonify({
            'ok': True,
            'personeller': [dict(r) for r in rows]
        })
    except Exception as e:
        return jsonify({'ok': False, 'hata': f'Sorgu hatasi: {str(e)[:200]}'}), 500

# ============================================================
# FAZ 2A - PERSONEL EKLEME (13.05.2026)
# ============================================================

@hedef_bp.route('/personel/ekle', methods=['POST'])
@yetki_gerekli('hedef.personel', 'can_manage')
def personel_ekle():
    """FAZ 2A - Yeni saha personeli ekleme (tablo: personel_kullanici)"""

    data = request.get_json(silent=True) or {}
    ad = (data.get('ad') or '').strip()
    kadi = (data.get('kullanici_adi') or '').strip().lower()
    sifre = (data.get('sifre') or '').strip()
    force = bool(data.get('force', False))

    if not ad or len(ad) < 2:
        return jsonify({'ok': False, 'hata': 'Ad soyad gerekli (min 2 karakter)'}), 400
    if not kadi or len(kadi) < 3:
        return jsonify({'ok': False, 'hata': 'Kullanici adi gerekli (min 3 karakter)'}), 400
    if not sifre or len(sifre) < 4:
        return jsonify({'ok': False, 'hata': 'Sifre gerekli (min 4 karakter)'}), 400

    try:
        # Duplicate 1 - kullanici_adi (KESIN BLOK)
        mevcut_kadi = q(
            "SELECT id FROM personel_kullanici WHERE LOWER(kullanici_adi) = ? LIMIT 1",
            (kadi,)
        )
        if mevcut_kadi:
            return jsonify({
                'ok': False,
                'hata': f"'{kadi}' kullanici adi zaten mevcut",
                'kod': 'DUPLICATE_KADI'
            }), 409

        # Duplicate 2 - ad (UYARI, force ile bypass)
        if not force:
            mevcut_ad = q(
                "SELECT id, kullanici_adi FROM personel_kullanici WHERE LOWER(ad) = ? LIMIT 1",
                (ad.lower(),)
            )
            if mevcut_ad:
                return jsonify({
                    'ok': False,
                    'uyari': True,
                    'hata': f"Ayni isimde personel var: '{mevcut_ad[0]['kullanici_adi']}'",
                    'kod': 'DUPLICATE_AD',
                    'mevcut': dict(mevcut_ad[0])
                }), 409

        # INSERT
        qexec(
            """INSERT INTO personel_kullanici 
               (ad, kullanici_adi, sifre, aktif, kaynak) 
               VALUES (?, ?, ?, 1, 'CPS_CANLI')""",
            (ad, kadi, sifre)
        )

        # Yeni id
        yeni_id_row = q("SELECT last_insert_rowid() as id")
        yeni_id = yeni_id_row[0]['id'] if yeni_id_row else None

        # Audit log (stdout)
        try:
            from datetime import datetime
            ekleyen = session.get('kullanici', {}).get('KullaniciAdi', 'bilinmiyor')
            ts_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(
                f"[{ts_str}] PERSONEL_EKLE | modul=hedef | alt=personel | "
                f"tablo=personel_kullanici | kayit_id={yeni_id} | "
                f"ekleyen={ekleyen} | ad='{ad}' | kadi='{kadi}'",
                flush=True
            )
        except Exception:
            pass

        return jsonify({'ok': True, 'mesaj': f"'{ad}' eklendi", 'id': yeni_id})

    except Exception as e:
        return jsonify({'ok': False, 'hata': f'Hata: {str(e)[:200]}'}), 500

# === D5 FAZ C.4 sablon_eslesme CRUD (18.05.2026) ===
# Plan: PATCH 1B recon onayli, sozlesme uygun, audit pattern kopyalandi.
# Mevcut /sablon/* endpoint'leri DOKUNULMAZ. Sadece dosya sonuna append.

# Eslesme tipi enum (DB CHECK ile paralel - 9 tip)
_ESLESME_TIPLERI = {
    'musteri', 'model', 'tip', 'ozel', 'location',
    'cari_kod', 'stok_kodu', 'ozkod', 'varsayilan'
}


def _validate_eslesme_payload(data, require_sablon_id=True):
    """Sablon_eslesme INSERT/UPDATE payload validation.
    Donen: (errors_list, normalized_dict). errors bos ise valid.
    """
    errors = []
    out = {}

    if require_sablon_id:
        sid = data.get('sablon_id')
        try:
            out['sablon_id'] = int(sid)
        except (TypeError, ValueError):
            errors.append('sablon_id zorunlu (integer)')

    tip = (data.get('eslesme_tipi') or '').strip().lower()
    if not tip:
        errors.append('eslesme_tipi zorunlu')
    elif tip not in _ESLESME_TIPLERI:
        errors.append('eslesme_tipi gecersiz (' + '/'.join(sorted(_ESLESME_TIPLERI)) + ')')
    else:
        out['eslesme_tipi'] = tip

    deger = (data.get('eslesme_degeri') or '').strip()
    if not deger:
        errors.append('eslesme_degeri zorunlu')
    else:
        out['eslesme_degeri'] = deger

    oncelik = data.get('oncelik', 100)
    try:
        oncelik_int = int(oncelik)
        if oncelik_int < 1 or oncelik_int > 999:
            errors.append('oncelik 1-999 arasi olmali')
        else:
            out['oncelik'] = oncelik_int
    except (TypeError, ValueError):
        errors.append('oncelik gecersiz (1-999)')

    aciklama = data.get('aciklama')
    if aciklama is not None:
        aciklama = str(aciklama).strip() or None
    out['aciklama'] = aciklama

    return errors, out


def _sablon_exists(conn, sablon_id):
    """Aktif sablon var mi?"""
    row = conn.execute(
        "SELECT 1 FROM sablon WHERE id=? AND aktif=1", (sablon_id,)
    ).fetchone()
    return row is not None


# --- 1) Eslesme liste (tum aktif kurallar) ---
@hedef_bp.route('/sablon-eslesme/liste', methods=['GET'])
@yetki_gerekli('hedef.sablon', 'can_view')
def hedef_sablon_eslesme_liste():
    import sqlite3
    from flask import jsonify
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT se.id, se.sablon_id, s.sablon_adi,
                   se.eslesme_tipi, se.eslesme_degeri, se.oncelik,
                   se.aktif, se.aciklama,
                   se.olusturan_id, se.olusturan_ad, se.olusturma,
                   se.guncelleme, se.guncelleyen_id, se.guncelleyen_ad
              FROM sablon_eslesme se
              LEFT JOIN sablon s ON s.id = se.sablon_id
             WHERE se.aktif=1
             ORDER BY se.oncelik ASC, se.id ASC
        """).fetchall()
        conn.close()
        return jsonify({'ok': True, 'kayitlar': [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e), 'kayitlar': []}), 500


# --- 2) Eslesme liste (tek sablon) ---
@hedef_bp.route('/sablon-eslesme/liste/<int:sid>', methods=['GET'])
@yetki_gerekli('hedef.sablon', 'can_view')
def hedef_sablon_eslesme_liste_sablon(sid):
    import sqlite3
    from flask import jsonify
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT se.id, se.sablon_id, s.sablon_adi,
                   se.eslesme_tipi, se.eslesme_degeri, se.oncelik,
                   se.aktif, se.aciklama,
                   se.olusturma, se.guncelleme,
                   se.olusturan_ad, se.guncelleyen_ad
              FROM sablon_eslesme se
              LEFT JOIN sablon s ON s.id = se.sablon_id
             WHERE se.sablon_id=? AND se.aktif=1
             ORDER BY se.oncelik ASC, se.id ASC
        """, (sid,)).fetchall()
        conn.close()
        return jsonify({
            'ok': True,
            'sablon_id': sid,
            'kayitlar': [dict(r) for r in rows]
        })
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e), 'kayitlar': []}), 500


# --- 3) Eslesme ekle ---
@hedef_bp.route('/sablon-eslesme/ekle', methods=['POST'])
@yetki_gerekli('hedef.sablon', 'can_create')
def hedef_sablon_eslesme_ekle():
    import sqlite3
    from flask import jsonify, request
    data = request.get_json(silent=True) or {}

    errors, payload = _validate_eslesme_payload(data, require_sablon_id=True)
    if errors:
        return jsonify({'ok': False, 'mesaj': '; '.join(errors)}), 400

    uid, uad = _sablon_session()
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        if not _sablon_exists(conn, payload['sablon_id']):
            conn.close()
            return jsonify({'ok': False, 'mesaj': 'sablon bulunamadi'}), 400
        cur = conn.execute("""
            INSERT INTO sablon_eslesme
                (sablon_id, eslesme_tipi, eslesme_degeri, oncelik,
                 aciklama, olusturan_id, olusturan_ad)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (payload['sablon_id'], payload['eslesme_tipi'],
              payload['eslesme_degeri'], payload['oncelik'],
              payload.get('aciklama'), uid, uad))
        new_id = cur.lastrowid
        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'id': new_id, 'mesaj': 'Eklendi'})
    except sqlite3.IntegrityError as e:
        msg = str(e)
        if 'UNIQUE' in msg.upper():
            return jsonify({
                'ok': False, 'hata': 'duplicate',
                'mesaj': 'Bu sablon icin ayni tip+deger+oncelik kombinasyonu zaten var'
            }), 409
        if 'CHECK' in msg.upper():
            return jsonify({'ok': False, 'mesaj': 'eslesme_tipi gecersiz (DB CHECK)'}), 400
        return jsonify({'ok': False, 'mesaj': msg}), 400
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)}), 500


# --- 4) Eslesme guncelle ---
@hedef_bp.route('/sablon-eslesme/guncelle/<int:eid>', methods=['POST'])
@yetki_gerekli('hedef.sablon', 'can_update')
def hedef_sablon_eslesme_guncelle(eid):
    import sqlite3
    from flask import jsonify, request
    data = request.get_json(silent=True) or {}

    errors, payload = _validate_eslesme_payload(data, require_sablon_id=True)
    if errors:
        return jsonify({'ok': False, 'mesaj': '; '.join(errors)}), 400

    uid, uad = _sablon_session()
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        if not _sablon_exists(conn, payload['sablon_id']):
            conn.close()
            return jsonify({'ok': False, 'mesaj': 'sablon bulunamadi'}), 400
        cur = conn.execute("""
            UPDATE sablon_eslesme
               SET sablon_id=?, eslesme_tipi=?, eslesme_degeri=?,
                   oncelik=?, aciklama=?,
                   guncelleme=datetime('now','localtime'),
                   guncelleyen_id=?, guncelleyen_ad=?
             WHERE id=? AND aktif=1
        """, (payload['sablon_id'], payload['eslesme_tipi'],
              payload['eslesme_degeri'], payload['oncelik'],
              payload.get('aciklama'), uid, uad, eid))
        affected = cur.rowcount
        conn.commit()
        conn.close()
        if affected == 0:
            return jsonify({'ok': False, 'mesaj': 'Kayit bulunamadi'}), 404
        return jsonify({'ok': True, 'mesaj': 'Guncellendi'})
    except sqlite3.IntegrityError as e:
        msg = str(e)
        if 'UNIQUE' in msg.upper():
            return jsonify({
                'ok': False, 'hata': 'duplicate',
                'mesaj': 'Bu sablon icin ayni tip+deger+oncelik kombinasyonu zaten var'
            }), 409
        if 'CHECK' in msg.upper():
            return jsonify({'ok': False, 'mesaj': 'eslesme_tipi gecersiz (DB CHECK)'}), 400
        return jsonify({'ok': False, 'mesaj': msg}), 400
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)}), 500


# --- 5) Eslesme sil (soft, aktif=0) ---
@hedef_bp.route('/sablon-eslesme/sil/<int:eid>', methods=['POST'])
@yetki_gerekli('hedef.sablon', 'can_delete')
def hedef_sablon_eslesme_sil(eid):
    import sqlite3
    from flask import jsonify
    uid, uad = _sablon_session()
    db_path = _hedef_db_path()
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute("""
            UPDATE sablon_eslesme
               SET aktif=0,
                   guncelleme=datetime('now','localtime'),
                   guncelleyen_id=?, guncelleyen_ad=?
             WHERE id=? AND aktif=1
        """, (uid, uad, eid))
        affected = cur.rowcount
        conn.commit()
        conn.close()
        if affected == 0:
            return jsonify({'ok': False, 'mesaj': 'Kayit bulunamadi'}), 404
        return jsonify({'ok': True, 'mesaj': 'Silindi'})
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)}), 500


# === D5 FAZ C.4 sablon_eslesme CRUD SONU ===

# === D5 FAZ C.5 P1 - _eslesme_bul helper (18.05.2026) ===
# Saf okuma helper'i. INSERT/UPDATE/DELETE YOK. HTTP cagri YOK.
# Sablon_eslesme tablosundan oncelik sirali kural arayip ilk eslesen sablon_id donur.
# Kural tipi karsilastirma: musteri/model=CONTAINS, tip=EXACT, location=startsWith
# varsayilan=her zaman, cari_kod/stok_kodu/ozkod meta'da yok -> SKIP.
# Mevcut /sablon/* ve diger endpoint'ler DOKUNULMADI. Sadece dosya sonuna append.

def _eslesme_meta_from_emir(emir_no):
    """Korgun get_emir_ozet'i cagirir, eslesme icin onemli alanlari donerir.
    Donus: dict veya None (Korgun hatasi/emir yok).
    Side-effect YOK. Sadece okuma.
    """
    try:
        from modules.common import korgun as _kk
        ozet = _kk.get_emir_ozet(emir_no)
        if not ozet or not ozet.get('ok'):
            return None
        return {
            'emir_no': ozet.get('emir_no'),
            'cari_adi': ozet.get('cari_adi'),
            'model_kod': ozet.get('model_kod'),
            'model_adi': ozet.get('model_adi'),
            'tip': ozet.get('tip'),
            'location': ozet.get('location'),
            # Asagidaki alanlar mevcut get_emir_ozet'te YOK.
            # Ileride alan eklenince otomatik aktiflesir.
            'cari_kod': ozet.get('cari_kod'),
            'stok_kodu': ozet.get('stok_kodu'),
            'ozkod_set': set(ozet.get('ozkod_set') or []),
        }
    except Exception:
        return None


def _kural_eslesti(tip, deger, meta):
    """Tek kural icin true/false donerir.
    Saf fonksiyon, side-effect yok, exception atmaz.
    """
    deger_n = _normalize_tr_local(deger or '')

    if tip == 'varsayilan':
        return True
    if tip == 'musteri':
        v = _normalize_tr_local(meta.get('cari_adi') or '')
        return bool(v) and bool(deger_n) and (deger_n in v)
    if tip == 'model':
        mk = _normalize_tr_local(meta.get('model_kod') or '')
        ma = _normalize_tr_local(meta.get('model_adi') or '')
        v = (mk + ' ' + ma).strip()
        return bool(v) and bool(deger_n) and (deger_n in v)
    if tip == 'tip':
        v = _normalize_tr_local(meta.get('tip') or '')
        return v == deger_n
    if tip == 'location':
        v = _normalize_tr_local(meta.get('location') or '')
        return bool(v) and bool(deger_n) and v.startswith(deger_n)
    if tip == 'cari_kod':
        ck = meta.get('cari_kod')
        if not ck:
            return False  # meta'da yok -> SKIP
        return _normalize_tr_local(ck) == deger_n
    if tip == 'stok_kodu':
        sk = meta.get('stok_kodu')
        if not sk:
            return False  # meta'da yok -> SKIP
        return _normalize_tr_local(sk) == deger_n
    if tip == 'ozkod':
        ozk = meta.get('ozkod_set')
        if not ozk:
            return False  # meta'da yok -> SKIP
        return deger_n in {_normalize_tr_local(x) for x in ozk}
    if tip == 'ozel':
        return False  # reserved, ileride
    return False


def _eslesme_bul(meta, conn=None):
    """Emir meta'sina gore en uygun sablon'u bulur.
    Sablon_eslesme'yi oncelik sirali tarar, ILK eslesen kuralin sablon_id'sini donerir.
    Pasif (aktif=0) sablonlar atlanir.
    Side-effect YOK. INSERT/UPDATE/DELETE yok.

    Args:
        meta: dict (_eslesme_meta_from_emir donusu)
        conn: opsiyonel sqlite3.Connection. Verilmezse kendi acar.

    Donus dict:
        sablon_id, sablon_adi, kural_id, eslesme_tipi, eslesme_degeri, oncelik, sebep
    """
    import sqlite3
    bos_sonuc = {
        'sablon_id': None, 'sablon_adi': None, 'kural_id': None,
        'eslesme_tipi': None, 'eslesme_degeri': None, 'oncelik': None,
    }
    if not meta:
        return dict(bos_sonuc, sebep='meta_eksik')

    close_conn = False
    if conn is None:
        conn = sqlite3.connect(_hedef_db_path())
        close_conn = True

    try:
        rows = conn.execute("""
            SELECT se.id, se.sablon_id, s.sablon_adi,
                   se.eslesme_tipi, se.eslesme_degeri, se.oncelik
              FROM sablon_eslesme se
              LEFT JOIN sablon s ON s.id = se.sablon_id AND s.aktif=1
             WHERE se.aktif=1
             ORDER BY se.oncelik ASC, se.id ASC
        """).fetchall()

        if not rows:
            return dict(bos_sonuc, sebep='kural_yok')

        for r in rows:
            kural_id, sablon_id, sablon_adi, tip, deger, oncelik = r[0], r[1], r[2], r[3], r[4], r[5]
            # sablon_adi None ise sablon pasif (LEFT JOIN ile aktif=1 sarti)
            if sablon_adi is None:
                continue
            try:
                if _kural_eslesti(tip, deger, meta):
                    return {
                        'sablon_id': sablon_id, 'sablon_adi': sablon_adi,
                        'kural_id': kural_id, 'eslesme_tipi': tip,
                        'eslesme_degeri': deger, 'oncelik': oncelik,
                        'sebep': 'eslesme_bulundu',
                    }
            except Exception:
                # Tek kural patlasa bile akista devam et
                continue

        return dict(bos_sonuc, sebep='eslesme_yok')
    finally:
        if close_conn:
            conn.close()


# === D5 FAZ C.5 P1 helper SONU ===

# === D5 FAZ C.5 P2 - _sablon_uygula_internal (18.05.2026) ===
# Mevcut /sablon/uygula HTTP endpoint'inin govdesi buraya tasindi.
# Davranis BIRE BIR korundu. Trigger (P4) bu fonksiyonu cagiracak.
# kaynak_prefix='sablon' -> HTTP default (mevcut davranis)
# kaynak_prefix='CPS_TRIGGER_C5' -> trigger (P4'te kullanilacak)

def _sablon_uygula_internal(emir_no, sablon_id, kaynak_prefix='sablon',
                             conn=None, uid=None, uad=None):
    """Sablon'u emire uygula. Saf is mantigi (HTTP bagimsiz).
    Returns: dict, opsiyonel 'http_status' key ile.
    """
    import sqlite3
    emir_no = str(emir_no or '').strip()

    if not emir_no:
        return {'ok': False, 'mesaj': 'emir_no zorunlu', 'http_status': 400}
    try:
        sablon_id = int(sablon_id)
    except Exception:
        return {'ok': False, 'mesaj': 'sablon_id zorunlu', 'http_status': 400}

    if uid is None or uad is None:
        uid, uad = _sablon_session()

    close_conn = False
    if conn is None:
        conn = sqlite3.connect(_hedef_db_path())
        conn.row_factory = sqlite3.Row
        close_conn = True
    else:
        conn.row_factory = sqlite3.Row

    try:
        sablon = conn.execute(
            "SELECT id, sablon_adi FROM sablon WHERE id=? AND aktif=1",
            (sablon_id,)
        ).fetchone()
        if not sablon:
            if close_conn: conn.close()
            return {'ok': False, 'mesaj': 'Sablon bulunamadi', 'http_status': 404}

        prs = conn.execute("""
            SELECT proses_adi, siralama FROM sablon_proses
             WHERE sablon_id=?
             ORDER BY siralama, id
        """, (sablon_id,)).fetchall()
        if not prs:
            if close_conn: conn.close()
            return {'ok': False, 'mesaj': 'Sablonda proses yok', 'http_status': 400}

        kaynak = kaynak_prefix + ':' + sablon['sablon_adi']

        gercek_emir_no, routing_sebep, alt_emir_miktar = _resolve_target_emir(emir_no, sablon['sablon_adi'])
        try:
            from flask import current_app
            current_app.logger.info(
                f'sablon_uygula routing: ana={emir_no} -> hedef={gercek_emir_no} ({routing_sebep}) miktar={alt_emir_miktar}'
            )
        except Exception:
            pass

        # hedef_adet hesapla: alt emir miktari > ana emir miktari > 0
        hedef_adet = 0
        if alt_emir_miktar is not None and alt_emir_miktar > 0:
            hedef_adet = int(alt_emir_miktar)
        else:
            # alt emirde miktar yok — ana emirden al (tek seferlik Korgun okuma)
            try:
                from modules.common import korgun as _kk_m
                ozet = _kk_m.get_emir_ozet(emir_no)
                if ozet.get('ok'):
                    _ha = ozet.get('hedef_adet') or 0
                    hedef_adet = int(_ha) if _ha else 0
            except Exception:
                hedef_adet = 0

        max_row = conn.execute(
            "SELECT COALESCE(MAX(siralama), 0) FROM emir_alt_proses WHERE emir_no=?",
            (gercek_emir_no,)
        ).fetchone()
        max_sira = int(max_row[0] or 0)

        eklenen = []
        atlanan = []
        for p in prs:
            pa = p['proses_adi']
            mevcut = conn.execute("""
                SELECT id FROM emir_alt_proses
                 WHERE emir_no=? AND proses_adi=? AND aktif=1
            """, (gercek_emir_no, pa)).fetchone()
            if mevcut:
                atlanan.append({'proses_adi': pa, 'mevcut_id': mevcut[0]})
                continue
            max_sira += 1
            cur = conn.execute("""
                INSERT INTO emir_alt_proses
                    (emir_no, proses_adi, siralama, aktif, kaynak,
                     olusturan_id, olusturan_ad, sablon_id, hedef_adet)
                VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
            """, (gercek_emir_no, pa, max_sira, kaynak, uid, uad, sablon_id, hedef_adet))
            eklenen.append({
                'id': cur.lastrowid,
                'proses_adi': pa,
                'siralama': max_sira,
                'emir_no': gercek_emir_no,
                'hedef_adet': hedef_adet,
            })

        conn.commit()
        if close_conn:
            conn.close()
        return {
            'ok': True,
            'emir_no': emir_no,
            'sablon_id': sablon_id,
            'sablon_adi': sablon['sablon_adi'],
            'eklenen_sayisi': len(eklenen),
            'atlanan_sayisi': len(atlanan),
            'eklenen': eklenen,
            'atlanan': atlanan,
        }
    except Exception as e:
        try:
            if close_conn: conn.close()
        except Exception:
            pass
        return {'ok': False, 'mesaj': str(e), 'http_status': 500}


# === D5 FAZ C.5 P2 helper SONU ===

# === D5 FAZ C.5 P3 - /sablon/trigger-test dry-run endpoint (18.05.2026) ===
# Sadece OKUMA. INSERT/UPDATE/DELETE YOK. Emir icin eslesme sonucunu doner.
# Tarayicidan canli test penceresi.

def _meta_jsonable(meta):
    """meta'daki set tipini list'e cevir (JSON serialize icin)."""
    if not meta:
        return None
    out = dict(meta)
    if isinstance(out.get('ozkod_set'), set):
        out['ozkod_set'] = sorted(out['ozkod_set'])
    return out


@hedef_bp.route('/sablon/trigger-test/<emir_no>', methods=['GET'])
@yetki_gerekli('hedef.sablon', 'can_view')
def hedef_sablon_trigger_test(emir_no):
    """C.5 P3 dry-run: trigger calissaydi ne yapacakti?
    INSERT YAPMAZ. Sadece eslesme + tahmin doner.
    """
    import sqlite3
    from flask import jsonify

    emir_no = str(emir_no or '').strip()
    if not emir_no:
        return jsonify({
            'ok': False, 'dry_run': True,
            'mesaj': 'emir_no zorunlu'
        }), 400

    # 1) Meta cek (Korgun)
    try:
        meta = _eslesme_meta_from_emir(emir_no)
    except Exception as e:
        return jsonify({
            'ok': False, 'dry_run': True, 'emir_no': emir_no,
            'mesaj': 'Korgun cagirisi basarisiz: ' + str(e)[:200]
        }), 502

    if not meta:
        return jsonify({
            'ok': False, 'dry_run': True, 'emir_no': emir_no,
            'mesaj': 'Korgun veri yok veya emir bulunamadi',
            'meta': None, 'eslesme': None
        }), 404

    # 2) Eslesme bul
    try:
        eslesme = _eslesme_bul(meta)
    except Exception as e:
        return jsonify({
            'ok': False, 'dry_run': True, 'emir_no': emir_no,
            'meta': _meta_jsonable(meta),
            'mesaj': 'Eslesme motoru hata: ' + str(e)[:200]
        }), 500

    # 3) Eslesme yoksa erken don
    if eslesme.get('sebep') != 'eslesme_bulundu':
        return jsonify({
            'ok': True, 'dry_run': True, 'emir_no': emir_no,
            'meta': _meta_jsonable(meta),
            'eslesme': eslesme,
            'sablon_proses': [],
            'mevcut_proses': [],
            'mevcut_proses_sayisi': 0,
            'tahmini_eklenecek': 0,
            'not': 'Eslesme yok - INSERT yapilmadi'
        })

    # 4) Sablon prosesleri + mevcut emir_alt_proses
    sablon_id = eslesme['sablon_id']
    try:
        conn = sqlite3.connect(_hedef_db_path())
        conn.row_factory = sqlite3.Row

        # Routing: ATKI/GOVDE alt emire yonlendir
        gercek_emir_no, routing_sebep, _alt_miktar = _resolve_target_emir(emir_no, eslesme['sablon_adi'])

        # Sablon prosesleri
        prs = conn.execute("""
            SELECT proses_adi, siralama FROM sablon_proses
             WHERE sablon_id=? ORDER BY siralama, id
        """, (sablon_id,)).fetchall()
        sablon_proses_list = [
            {'proses_adi': p['proses_adi'], 'siralama': p['siralama']}
            for p in prs
        ]

        # Mevcut emir_alt_proses (gercek_emir_no icin)
        mevcut_rows = conn.execute("""
            SELECT proses_adi, kaynak, siralama FROM emir_alt_proses
             WHERE emir_no=? AND aktif=1
             ORDER BY siralama, id
        """, (gercek_emir_no,)).fetchall()
        mevcut_proses = [
            {'proses_adi': r['proses_adi'], 'kaynak': r['kaynak'], 'siralama': r['siralama']}
            for r in mevcut_rows
        ]
        mevcut_set = {r['proses_adi'] for r in mevcut_rows}

        conn.close()

        # Tahmin
        eklenecek = [p['proses_adi'] for p in prs if p['proses_adi'] not in mevcut_set]
        atlanacak = [p['proses_adi'] for p in prs if p['proses_adi'] in mevcut_set]

        return jsonify({
            'ok': True, 'dry_run': True,
            'emir_no': emir_no,
            'gercek_emir_no': gercek_emir_no,
            'routing_sebep': routing_sebep,
            'meta': _meta_jsonable(meta),
            'eslesme': eslesme,
            'sablon_proses': sablon_proses_list,
            'mevcut_proses': mevcut_proses,
            'mevcut_proses_sayisi': len(mevcut_proses),
            'tahmini_eklenecek': len(eklenecek),
            'tahmini_eklenecek_listesi': eklenecek,
            'tahmini_atlanacak_listesi': atlanacak,
            'not': 'INSERT yapilmadi - dry run'
        })
    except Exception as e:
        try: conn.close()
        except Exception: pass
        return jsonify({
            'ok': False, 'dry_run': True, 'emir_no': emir_no,
            'meta': _meta_jsonable(meta),
            'eslesme': eslesme,
            'mesaj': 'DB hatasi: ' + str(e)[:200]
        }), 500


# === D5 FAZ C.5 P3 endpoint SONU ===

# === D5 FAZ C.5 P5 - /sablon/trigger manuel endpoint (18.05.2026) ===
# Admin manuel trigger. GERCEK INSERT yapar.
# Lazy hook DEGIL - sadece admin/test cagrisi.
# Duplicate koruma: emir_alt_proses'te aktif=1 kayit varsa zaten_islenmis doner.
# Audit: kaynak='CPS_TRIGGER_C5:<sablon_adi>'
# Rollback: /sablon/geri-al endpoint'i kullanilabilir (mevcut)

@hedef_bp.route('/sablon/trigger/<emir_no>', methods=['POST'])
@yetki_gerekli('hedef.sablon', 'can_manage')
def hedef_sablon_trigger_manuel(emir_no):
    """C.5 P5 manuel trigger - GERCEK INSERT.
    Sadece admin/test cagrisi icin. Lazy hook degil.
    Duplicate koruma + transaction + audit.
    """
    import sqlite3
    from flask import jsonify

    emir_no = str(emir_no or '').strip()
    if not emir_no:
        return jsonify({
            'ok': False, 'dry_run': False,
            'mesaj': 'emir_no zorunlu'
        }), 400

    # 1) Duplicate kontrolu - emir_alt_proses'te aktif kayit var mi?
    try:
        conn_check = sqlite3.connect(_hedef_db_path())
        mevcut_cnt = conn_check.execute(
            "SELECT COUNT(*) FROM emir_alt_proses WHERE emir_no=? AND aktif=1",
            (emir_no,)
        ).fetchone()[0]
        # Routing icin sablon adi onceden bilinmedigi icin, ayrica routing'li
        # emirleri de kontrol etmek gerek (alt emire yonelenler).
        conn_check.close()
    except Exception as e:
        return jsonify({
            'ok': False, 'dry_run': False, 'emir_no': emir_no,
            'mesaj': 'DB hatasi: ' + str(e)[:200]
        }), 500

    if mevcut_cnt > 0:
        return jsonify({
            'ok': True, 'dry_run': False, 'emir_no': emir_no,
            'durum': 'zaten_islenmis',
            'mevcut_proses_sayisi': mevcut_cnt,
            'mesaj': 'Bu emirde zaten emir_alt_proses kayitlari var. INSERT yapilmadi.'
        })

    # 2) Korgun meta cek
    try:
        meta = _eslesme_meta_from_emir(emir_no)
    except Exception as e:
        return jsonify({
            'ok': False, 'dry_run': False, 'emir_no': emir_no,
            'mesaj': 'Korgun hatasi: ' + str(e)[:200]
        }), 502

    if not meta:
        return jsonify({
            'ok': False, 'dry_run': False, 'emir_no': emir_no,
            'durum': 'korgun_veri_yok',
            'mesaj': 'Korgun veri yok veya emir bulunamadi'
        }), 404

    # 3) Eslesme bul
    try:
        eslesme = _eslesme_bul(meta)
    except Exception as e:
        return jsonify({
            'ok': False, 'dry_run': False, 'emir_no': emir_no,
            'mesaj': 'Eslesme motoru hatasi: ' + str(e)[:200]
        }), 500

    if eslesme.get('sebep') != 'eslesme_bulundu':
        return jsonify({
            'ok': False, 'dry_run': False, 'emir_no': emir_no,
            'durum': 'eslesme_yok',
            'eslesme': eslesme,
            'mesaj': 'Hicbir kural eslesmedi'
        }), 200

    # 4) GERCEK INSERT - _sablon_uygula_internal(kaynak_prefix='CPS_TRIGGER_C5')
    sablon_id = eslesme['sablon_id']
    try:
        sonuc = _sablon_uygula_internal(
            emir_no, sablon_id,
            kaynak_prefix='CPS_TRIGGER_C5'
        )
    except Exception as e:
        return jsonify({
            'ok': False, 'dry_run': False, 'emir_no': emir_no,
            'eslesme': eslesme,
            'mesaj': '_sablon_uygula_internal hatasi: ' + str(e)[:200]
        }), 500

    # http_status varsa cikar (HTTP wrapper davranisi)
    status = sonuc.pop('http_status', None)
    if status and status >= 400:
        # Internal hata - direct dondur
        return jsonify({
            'ok': False, 'dry_run': False, 'emir_no': emir_no,
            'eslesme': eslesme,
            'internal_sonuc': sonuc
        }), status

    # Basari - audit + eslesme bilgisi ile zenginlestir
    sonuc['dry_run'] = False
    sonuc['eslesme'] = eslesme
    sonuc['kaynak_prefix'] = 'CPS_TRIGGER_C5'
    sonuc['durum'] = 'islendi'
    return jsonify(sonuc)


# === D5 FAZ C.5 P5 endpoint SONU ===
