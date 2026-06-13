# -*- coding: utf-8 -*-
"""
CPS — Fuar CRM Modulu (Faz 2)
================================
Ekranlar:
  /fuar-crm/                           -> Dashboard (8 istatistik + tablolar)
  /fuar-crm/firma                      -> Firma listesi (zengin kolonlar)
  /fuar-crm/firma/ekle                 -> Yeni firma
  /fuar-crm/firma/<id>                 -> Detay + hizli aksiyonlar
  /fuar-crm/firma/<id>/gorusme-ekle    -> Gorusme notu POST
  /fuar-crm/firma/<id>/dosya-yukle     -> Kartvizit/gorsel yukle POST
  /fuar-crm/firma/<id>/dosya/<did>/sil -> Dosya sil POST
"""
from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, abort, flash, send_from_directory,
                   jsonify)
from db import q as _q, qone as _qone, get_conn as _get_conn
from modules.auth import login_gerekli
import os, datetime, uuid, mimetypes

fuar_crm_bp = Blueprint(
    'fuar_crm', __name__,
    url_prefix='/fuar-crm',
    template_folder='../../templates/fuar_crm'
)

# Yuklemeler: app/static/uploads/fuar_crm/
UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'static', 'uploads', 'fuar_crm'
)
ALLOWED_EXT = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'pdf'}
MAX_MB = 10


# ── Yardimcilar ---------------------------------------------------------------

def _u():
    k = session.get('kullanici')
    return k['KullaniciAdi'] if k else 'sistem'


def _crm_erisim():
    u = session.get('kullanici')
    if not u:
        return False
    kadi = (u.get('KullaniciAdi') or '').strip().lower()
    rol  = (u.get('RolAd') or u.get('Rol') or '').strip()
    if kadi == 'admin':
        return True
    if rol in ('Yonetim', 'Muhasebe', 'Finans'):
        return True
    # Turkce rol adi da kabul et
    if 'yonetim' in rol.lower():
        return True
    try:
        from modules.auth import yetki_var
        return yetki_var('fuar_crm', 'can_view')
    except Exception:
        return False


@fuar_crm_bp.before_request
def _erisim_kontrol():
    if not session.get('kullanici'):
        return redirect(url_for('auth.login', next=request.path))
    if not _crm_erisim():
        abort(403)


def _ext_ok(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT


def _is_image(filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return ext in ('jpg', 'jpeg', 'png', 'webp', 'gif')


def _safe_name(original):
    ext = original.rsplit('.', 1)[-1].lower() if '.' in original else 'bin'
    return f"{uuid.uuid4().hex}.{ext}"


# ── DASHBOARD -----------------------------------------------------------------

@fuar_crm_bp.route('/')
@login_gerekli
def dashboard():
    today = datetime.date.today().isoformat()

    toplam_firma    = (_qone("SELECT COUNT(*) AS c FROM crm_firma WHERE aktif=1") or {}).get('c', 0)
    toplam_gorusme  = (_qone("SELECT COUNT(*) AS c FROM crm_gorusme") or {}).get('c', 0)
    takip_bekleyen  = (_qone("SELECT COUNT(*) AS c FROM crm_gorusme WHERE durum='takip_bekliyor'") or {}).get('c', 0)
    numune_isteyen  = (_qone("SELECT COUNT(*) AS c FROM crm_gorusme WHERE numune=1") or {}).get('c', 0)
    fiyat_verilecek = (_qone("SELECT COUNT(*) AS c FROM crm_gorusme WHERE fiyat_verildi=0 AND durum NOT IN ('kapandi','olumsuz')") or {}).get('c', 0)
    bugun_gorusme   = (_qone(
        "SELECT COUNT(*) AS c FROM crm_gorusme WHERE substr(created_at,1,10)=?", (today,)
    ) or {}).get('c', 0)
    toplam_urun     = (_qone("SELECT COUNT(*) AS c FROM crm_urun WHERE aktif=1") or {}).get('c', 0)

    # Ulke dagilimi
    ulke_dagilim = _q("""
        SELECT ulke, COUNT(*) AS cnt
        FROM crm_firma
        WHERE aktif=1 AND ulke IS NOT NULL AND ulke != ''
        GROUP BY ulke ORDER BY cnt DESC LIMIT 8
    """) or []

    # Son eklenen firmalar
    son_firmalar = _q("""
        SELECT f.id, f.firma_adi, f.yetkili, f.ulke, f.firma_tipi,
               f.telefon, f.whatsapp, f.created_at,
               COUNT(g.id) AS gorusme_sayisi,
               MAX(g.durum) AS son_durum
        FROM crm_firma f
        LEFT JOIN crm_gorusme g ON g.firma_id = f.id
        WHERE f.aktif = 1
        GROUP BY f.id
        ORDER BY f.created_at DESC
        LIMIT 8
    """) or []

    # Yaklasan takipler (7 gun icinde)
    from datetime import timedelta
    bitis = (datetime.date.today() + timedelta(days=7)).isoformat()
    yaklasan_takip = _q("""
        SELECT g.takip_tarihi, g.durum, g.urun_ilgisi,
               f.id AS firma_id, f.firma_adi, f.yetkili
        FROM crm_gorusme g
        JOIN crm_firma f ON f.id = g.firma_id
        WHERE g.takip_tarihi IS NOT NULL
          AND g.takip_tarihi >= ?
          AND g.takip_tarihi <= ?
          AND g.durum NOT IN ('kapandi','olumsuz')
        ORDER BY g.takip_tarihi ASC
        LIMIT 10
    """, (today, bitis)) or []

    # En cok ilgi goren urunler (gorusme_urun tablosundan)
    en_cok_urun = _q("""
        SELECT u.model_no, u.kategori, u.tip, u.urun_cinsi,
               COUNT(gu.id) AS ilgi_sayisi
        FROM crm_gorusme_urun gu
        JOIN crm_urun u ON u.id = gu.urun_id
        GROUP BY u.id
        ORDER BY ilgi_sayisi DESC
        LIMIT 5
    """) or []

    return render_template(
        'fuar_crm/dashboard.html',
        toplam_firma=toplam_firma,
        toplam_gorusme=toplam_gorusme,
        takip_bekleyen=takip_bekleyen,
        numune_isteyen=numune_isteyen,
        fiyat_verilecek=fiyat_verilecek,
        bugun_gorusme=bugun_gorusme,
        toplam_urun=toplam_urun,
        en_cok_urun=en_cok_urun,
        ulke_dagilim=ulke_dagilim,
        son_firmalar=son_firmalar,
        yaklasan_takip=yaklasan_takip,
    )


# ── FIRMA LISTESI -------------------------------------------------------------

@fuar_crm_bp.route('/firma')
@login_gerekli
def firma_liste():
    arama       = request.args.get('q', '').strip()
    ulke_filtre = request.args.get('ulke', '').strip()
    durum_filtre= request.args.get('durum', '').strip()

    params = []
    where  = ["f.aktif = 1"]

    if arama:
        where.append("(f.firma_adi LIKE ? OR f.yetkili LIKE ? OR f.email LIKE ? OR f.marka_ilgisi LIKE ?)")
        like = f"%{arama}%"
        params += [like, like, like, like]

    if ulke_filtre:
        where.append("f.ulke = ?")
        params.append(ulke_filtre)

    where_sql = " AND ".join(where)

    firmalar = _q(f"""
        SELECT f.id, f.firma_adi, f.yetkili, f.telefon, f.whatsapp,
               f.email, f.ulke, f.sehir, f.firma_tipi, f.marka_ilgisi,
               f.kaynak, f.created_at,
               COUNT(DISTINCT g.id)          AS gorusme_sayisi,
               MAX(g.durum)                  AS son_durum,
               MAX(g.created_at)             AS son_gorusme_tarihi,
               MAX(g.takip_tarihi)           AS son_takip_tarihi,
               SUM(CASE WHEN substr(g.created_at,1,10)=date('now') THEN 1 ELSE 0 END) AS bugun_gorusme,
               COUNT(DISTINCT gu.urun_id)    AS urun_sayisi
        FROM crm_firma f
        LEFT JOIN crm_gorusme g  ON g.firma_id = f.id
        LEFT JOIN crm_gorusme_urun gu ON gu.gorusme_id = g.id
        WHERE {where_sql}
        GROUP BY f.id
        ORDER BY f.firma_adi
    """, params) or []

    ulkeler = _q(
        "SELECT DISTINCT ulke FROM crm_firma WHERE aktif=1 AND ulke IS NOT NULL AND ulke != '' ORDER BY ulke"
    ) or []
    ulke_listesi = [r['ulke'] for r in ulkeler]

    return render_template(
        'fuar_crm/firma_liste.html',
        firmalar=firmalar,
        arama=arama,
        ulke_filtre=ulke_filtre,
        durum_filtre=durum_filtre,
        ulke_listesi=ulke_listesi,
    )


# ── FIRMA EKLE ----------------------------------------------------------------

@fuar_crm_bp.route('/firma/ekle', methods=['GET', 'POST'])
@login_gerekli
def firma_ekle():
    if request.method == 'POST':
        firma_adi = request.form.get('firma_adi', '').strip()
        if not firma_adi:
            flash('Firma adi zorunludur.', 'hata')
            return redirect(url_for('fuar_crm.firma_ekle'))

        fields = {
            'yetkili':      request.form.get('yetkili', '').strip() or None,
            'telefon':      request.form.get('telefon', '').strip() or None,
            'whatsapp':     request.form.get('whatsapp', '').strip() or None,
            'email':        request.form.get('email', '').strip() or None,
            'ulke':         request.form.get('ulke', '').strip() or None,
            'sehir':        request.form.get('sehir', '').strip() or None,
            'firma_tipi':   request.form.get('firma_tipi', '').strip() or None,
            'marka_ilgisi': request.form.get('marka_ilgisi', '').strip() or None,
            'erp_cari_kodu':request.form.get('erp_cari_kodu', '').strip() or None,
            'kaynak':       request.form.get('kaynak', '').strip() or None,
        }

        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO crm_firma
                    (firma_adi, yetkili, telefon, whatsapp, email,
                     ulke, sehir, firma_tipi, marka_ilgisi,
                     erp_cari_kodu, kaynak, aktif, created_by)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?)
            """, (firma_adi,
                  fields['yetkili'], fields['telefon'], fields['whatsapp'],
                  fields['email'], fields['ulke'], fields['sehir'],
                  fields['firma_tipi'], fields['marka_ilgisi'],
                  fields['erp_cari_kodu'], fields['kaynak'], _u()))
            conn.commit()
            new_id = cur.lastrowid
            flash(f'"{firma_adi}" basariyla eklendi.', 'basari')
            return redirect(url_for('fuar_crm.firma_detay', firma_id=new_id))
        except Exception as exc:
            conn.rollback()
            flash(f'Kayit hatasi: {exc}', 'hata')
        finally:
            conn.close()

    return render_template('fuar_crm/firma_ekle.html')


# ── FIRMA DETAY ---------------------------------------------------------------

@fuar_crm_bp.route('/firma/<int:firma_id>')
@login_gerekli
def firma_detay(firma_id):
    firma = _qone("SELECT * FROM crm_firma WHERE id = ? AND aktif = 1", (firma_id,))
    if not firma:
        abort(404)

    gorusmeler = _q("""
        SELECT * FROM crm_gorusme
        WHERE firma_id = ?
        ORDER BY created_at DESC
    """, (firma_id,)) or []

    # Her gorusme icin urunleri de cek
    gorusme_listesi = []
    today = datetime.date.today().isoformat()
    for g in gorusmeler:
        g = dict(g)
        g['urunler'] = _q("""
            SELECT gu.id AS gu_id, gu.fiyat_konusuldu, gu.numune_istendi, gu.not_text,
                   gu.verilen_fiyat, gu.para_birimi, gu.eski_fiyat, gu.indirim_notu,
                   gu.numune_adet, gu.numune_beden, gu.istenen_renk,
                   gu.renk_basi_adet, gu.toplam_adet, gu.teslim_notu, gu.urun_notu,
                   u.model_no, u.kategori, u.tip, u.urun_cinsi, u.asorti,
                   u.birim_fiyat, u.maliyet,
                   gorsel.dosya_yolu AS gorsel_yolu
            FROM crm_gorusme_urun gu
            JOIN crm_urun u ON u.id = gu.urun_id
            LEFT JOIN crm_urun_gorsel gorsel ON gorsel.urun_id = u.id
            WHERE gu.gorusme_id = ?
        """, (g['id'],)) or []
        g['bugun'] = (g.get('created_at') or '')[:10] == today
        gorusme_listesi.append(g)

    dosyalar = _q(
        "SELECT * FROM crm_dosya WHERE firma_id = ? ORDER BY created_at DESC",
        (firma_id,)
    ) or []

    dosya_listesi = []
    for d in dosyalar:
        d = dict(d)
        fn = os.path.basename(d.get('dosya_yolu', ''))
        d['is_image'] = _is_image(fn)
        d['filename'] = fn
        dosya_listesi.append(d)

    # Urun istatistigi
    toplam_urun = (_qone("SELECT COUNT(*) AS c FROM crm_urun WHERE aktif=1") or {}).get('c', 0)

    return render_template(
        'fuar_crm/firma_detay.html',
        firma=firma,
        gorusmeler=gorusme_listesi,
        dosyalar=dosya_listesi,
        toplam_urun=toplam_urun,
        today=today,
    )


# ── GORUSME EKLE -------------------------------------------------------------

@fuar_crm_bp.route('/firma/<int:firma_id>/gorusme-ekle', methods=['POST'])
@login_gerekli
def gorusme_ekle(firma_id):
    firma = _qone("SELECT id FROM crm_firma WHERE id = ? AND aktif = 1", (firma_id,))
    if not firma:
        abort(404)

    fuar_adi      = request.form.get('fuar_adi', '').strip() or None
    gorusen       = request.form.get('gorusen', '').strip() or None
    not_text      = request.form.get('not_text', '').strip() or None
    urun_ilgisi   = request.form.get('urun_ilgisi', '').strip() or None
    numune        = 1 if request.form.get('numune') == '1' else 0
    fiyat_verildi = 1 if request.form.get('fiyat_verildi') == '1' else 0
    takip_tarihi  = request.form.get('takip_tarihi', '').strip() or None
    durum         = request.form.get('durum', 'beklemede').strip()

    # Secilen urunler: urun_ids[] listesi
    urun_ids = request.form.getlist('urun_ids[]')

    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO crm_gorusme
                (firma_id, fuar_adi, gorusen, not_text, urun_ilgisi,
                 numune, fiyat_verildi, takip_tarihi, durum, created_by)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (firma_id, fuar_adi, gorusen, not_text, urun_ilgisi,
              numune, fiyat_verildi, takip_tarihi, durum, _u()))
        gorusme_id = cur.lastrowid

        # Urun iliskileri kaydet
        for uid in urun_ids:
            try:
                uid_int = int(uid)
                fiyat_k      = 1 if request.form.get(f'fiyat_{uid}') == '1' else 0
                numune_i     = 1 if request.form.get(f'numune_{uid}') == '1' else 0
                urun_not     = request.form.get(f'urun_not_{uid}', '').strip() or None

                def _float_f(key):
                    v = request.form.get(key, '').strip()
                    try: return float(v) if v else None
                    except ValueError: return None

                def _int_f(key):
                    v = request.form.get(key, '').strip()
                    try: return int(v) if v else None
                    except ValueError: return None

                verilen_fiyat  = _float_f(f'verilen_fiyat_{uid}')
                para_birimi    = request.form.get(f'para_birimi_{uid}', 'USD').strip() or 'USD'
                eski_fiyat     = _float_f(f'eski_fiyat_{uid}')
                indirim_notu   = request.form.get(f'indirim_notu_{uid}', '').strip() or None
                numune_adet    = _int_f(f'numune_adet_{uid}')
                numune_beden   = request.form.get(f'numune_beden_{uid}', '').strip() or None
                istenen_renk   = request.form.get(f'istenen_renk_{uid}', '').strip() or None
                renk_basi_adet = _int_f(f'renk_basi_adet_{uid}')
                toplam_adet    = _int_f(f'toplam_adet_{uid}')
                teslim_notu    = request.form.get(f'teslim_notu_{uid}', '').strip() or None
                urun_notu      = request.form.get(f'urun_notu_{uid}', '').strip() or None

                cur.execute("""
                    INSERT INTO crm_gorusme_urun
                        (gorusme_id, urun_id, not_text, fiyat_konusuldu, numune_istendi,
                         verilen_fiyat, para_birimi, eski_fiyat, indirim_notu,
                         numune_adet, numune_beden, istenen_renk,
                         renk_basi_adet, toplam_adet, teslim_notu, urun_notu)
                    VALUES (?,?,?,?,?, ?,?,?,?, ?,?,?, ?,?,?,?)
                """, (gorusme_id, uid_int, urun_not, fiyat_k, numune_i,
                      verilen_fiyat, para_birimi, eski_fiyat, indirim_notu,
                      numune_adet, numune_beden, istenen_renk,
                      renk_basi_adet, toplam_adet, teslim_notu, urun_notu))
            except (ValueError, TypeError):
                continue

        conn.commit()
        flash('Gorusme notu eklendi.', 'basari')
    except Exception as exc:
        conn.rollback()
        flash(f'Hata: {exc}', 'hata')
    finally:
        conn.close()

    return redirect(url_for('fuar_crm.firma_detay', firma_id=firma_id) + '#gecmis')


# ── URUN KATALOGU SAYFASI -----------------------------------------------------

@fuar_crm_bp.route('/urunler')
@login_gerekli
def urun_katalogu():
    q_str    = request.args.get('q', '').strip()
    kat_filt = request.args.get('kategori', '').strip()
    tip_filt = request.args.get('tip', '').strip()

    params = ["aktif = 1"]
    vals   = []

    if q_str:
        like = f"%{q_str}%"
        params.append("(model_no LIKE ? OR kategori LIKE ? OR tip LIKE ? OR urun_cinsi LIKE ? OR malzeme_bilgisi LIKE ?)")
        vals += [like, like, like, like, like]
    if kat_filt:
        params.append("kategori = ?")
        vals.append(kat_filt)
    if tip_filt:
        params.append("tip = ?")
        vals.append(tip_filt)

    where_sql = " AND ".join(params)
    urunler = _q(f"""
        SELECT u.id, u.model_no, u.kategori, u.tip, u.urun_cinsi, u.asorti,
               u.birim_fiyat, u.maliyet, u.malzeme_bilgisi, u.sheet_adi, u.excel_satir_no,
               g.dosya_yolu AS gorsel_yolu
        FROM crm_urun u
        LEFT JOIN crm_urun_gorsel g ON g.urun_id = u.id
        WHERE {where_sql}
        ORDER BY u.model_no, u.sheet_adi
    """, vals) or []

    kategoriler = [r['kategori'] for r in (_q(
        "SELECT DISTINCT kategori FROM crm_urun WHERE aktif=1 AND kategori IS NOT NULL ORDER BY kategori"
    ) or []) if r.get('kategori')]
    tipler = [r['tip'] for r in (_q(
        "SELECT DISTINCT tip FROM crm_urun WHERE aktif=1 AND tip IS NOT NULL ORDER BY tip"
    ) or []) if r.get('tip')]

    toplam_urun = (_qone("SELECT COUNT(*) AS c FROM crm_urun WHERE aktif=1") or {}).get('c', 0)

    return render_template(
        'fuar_crm/urun_katalogu.html',
        urunler=urunler,
        q_str=q_str,
        kat_filt=kat_filt,
        tip_filt=tip_filt,
        kategoriler=kategoriler,
        tipler=tipler,
        toplam_urun=toplam_urun,
    )


# ── URUN ARAMA API (JSON) -----------------------------------------------------

@fuar_crm_bp.route('/api/urun-ara')
@login_gerekli
def urun_ara():
    q_str   = request.args.get('q', '').strip()
    limit   = min(int(request.args.get('limit', 30)), 100)

    params = []
    where  = ["aktif = 1"]

    if q_str:
        like = f"%{q_str}%"
        where.append("""(
            model_no        LIKE ? OR
            kategori        LIKE ? OR
            tip             LIKE ? OR
            urun_cinsi      LIKE ?
        )""")
        params += [like, like, like, like]

    where_sql = " AND ".join(where)
    rows = _q(f"""
        SELECT u.id, u.model_no, u.kategori, u.tip, u.urun_cinsi,
               u.asorti, u.birim_fiyat, u.maliyet, u.malzeme_bilgisi,
               u.sheet_adi, u.excel_satir_no,
               g.dosya_yolu AS gorsel_yolu
        FROM crm_urun u
        LEFT JOIN crm_urun_gorsel g ON g.urun_id = u.id
        WHERE {where_sql}
        ORDER BY u.model_no
        LIMIT {limit}
    """, params) or []

    return jsonify(rows)


# ── GORUSME URUN SIL ----------------------------------------------------------

@fuar_crm_bp.route('/gorusme-urun/<int:gu_id>/sil', methods=['POST'])
@login_gerekli
def gorusme_urun_sil(gu_id):
    gu = _qone("SELECT gorusme_id FROM crm_gorusme_urun WHERE id=?", (gu_id,))
    if not gu:
        abort(404)
    gorusme_id = gu['gorusme_id']
    firma = _qone("""
        SELECT g.firma_id FROM crm_gorusme g WHERE g.id = ?
    """, (gorusme_id,))
    firma_id = firma['firma_id'] if firma else None

    conn = _get_conn()
    try:
        conn.execute("DELETE FROM crm_gorusme_urun WHERE id=?", (gu_id,))
        conn.commit()
        flash('Urun gorunden kaldirildi.', 'basari')
    except Exception as exc:
        conn.rollback()
        flash(f'Hata: {exc}', 'hata')
    finally:
        conn.close()

    if firma_id:
        return redirect(url_for('fuar_crm.firma_detay', firma_id=firma_id) + '#gecmis')
    return redirect(url_for('fuar_crm.firma_liste'))


# ── DOSYA YUKLE --------------------------------------------------------------

@fuar_crm_bp.route('/firma/<int:firma_id>/dosya-yukle', methods=['POST'])
@login_gerekli
def dosya_yukle(firma_id):
    firma = _qone("SELECT id FROM crm_firma WHERE id = ? AND aktif = 1", (firma_id,))
    if not firma:
        abort(404)

    f = request.files.get('dosya')
    if not f or not f.filename:
        flash('Dosya secilmedi.', 'hata')
        return redirect(url_for('fuar_crm.firma_detay', firma_id=firma_id))

    if not _ext_ok(f.filename):
        flash('Desteklenmeyen dosya tipi. Izin verilenler: jpg, jpeg, png, pdf', 'hata')
        return redirect(url_for('fuar_crm.firma_detay', firma_id=firma_id))

    aciklama = request.form.get('aciklama', '').strip() or None
    tip      = request.form.get('tip', 'kartvizit').strip()

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe_fn  = _safe_name(f.filename)
    abs_path = os.path.join(UPLOAD_DIR, safe_fn)

    try:
        f.save(abs_path)
    except Exception as exc:
        flash(f'Dosya kaydedilemedi: {exc}', 'hata')
        return redirect(url_for('fuar_crm.firma_detay', firma_id=firma_id))

    # DB'ye kaydet — dosya_yolu = relative web path
    web_path = f"uploads/fuar_crm/{safe_fn}"

    conn = _get_conn()
    try:
        cur = conn.cursor()
        # crm_dosya tablosuna aciklama kolonu olmayabilir, ALTER ile ekle
        try:
            cur.execute("ALTER TABLE crm_dosya ADD COLUMN aciklama TEXT")
            conn.commit()
        except Exception:
            pass  # zaten varsa hata verir, sorun degil

        cur.execute("""
            INSERT INTO crm_dosya (firma_id, dosya_yolu, tip, aciklama, created_by)
            VALUES (?,?,?,?,?)
        """, (firma_id, web_path, tip, aciklama, _u()))
        conn.commit()
        flash('Dosya basariyla yuklendi.', 'basari')
    except Exception as exc:
        conn.rollback()
        # Dosyayi geri sil
        try:
            os.remove(abs_path)
        except Exception:
            pass
        flash(f'DB hatasi: {exc}', 'hata')
    finally:
        conn.close()

    return redirect(url_for('fuar_crm.firma_detay', firma_id=firma_id))


# ── DOSYA SIL ----------------------------------------------------------------

@fuar_crm_bp.route('/firma/<int:firma_id>/dosya/<int:dosya_id>/sil', methods=['POST'])
@login_gerekli
def dosya_sil(firma_id, dosya_id):
    d = _qone("SELECT * FROM crm_dosya WHERE id=? AND firma_id=?", (dosya_id, firma_id))
    if not d:
        abort(404)

    web_path = d['dosya_yolu']
    # Disk'ten sil
    static_root = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'static'
    )
    abs_path = os.path.join(static_root, web_path)
    try:
        if os.path.exists(abs_path):
            os.remove(abs_path)
    except Exception:
        pass

    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM crm_dosya WHERE id=?", (dosya_id,))
        conn.commit()
        flash('Dosya silindi.', 'basari')
    except Exception as exc:
        conn.rollback()
        flash(f'Silme hatasi: {exc}', 'hata')
    finally:
        conn.close()

    return redirect(url_for('fuar_crm.firma_detay', firma_id=firma_id))


# ── STATIK DOSYA SERVISI (opsiyonel fallback) ---------------------------------

@fuar_crm_bp.route('/uploads/<path:filename>')
@login_gerekli
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)
