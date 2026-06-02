# -*- coding: utf-8 -*-
"""CPS DEV - Enjeksiyon Takip Routes (FAZ 6.6)

Degisiklik (F6.6):
  - Ust panel sade 4 makine kart, secili makinenin A/B paneli alta acilir
  - Querystring ?makine=N ile secili makine korunur
  - Demo slot state korundu (F7'de DB)
"""
from datetime import datetime
from flask import (Blueprint, render_template, redirect, url_for,
                   request, session, abort, jsonify)
from functools import wraps


enjeksiyon_bp = Blueprint(
    'enjeksiyon', __name__,
    url_prefix='/enjeksiyon',
    template_folder='../../templates/enjeksiyon'
)


SAATLER = {
    'gunduz': [(7,8),(8,9),(9,10),(10,11),(11,12),(12,13),(13,14),(14,15),(15,16),(16,17)],
    'gece':   [(17,18),(18,19),(19,20),(20,21),(21,22),(22,23),(23,0),(0,1),(1,2),(2,3),(3,4),(4,5),(5,6),(6,7)],
    'mesai':  [],
}

VARDIYA_METIN = {
    'gunduz': 'GUNDUZ VARDIYASI (07:00 - 17:00)',
    'gece':   'GECE VARDIYASI (17:00 - 07:00)',
    'mesai':  'MESAI',
}


def vardiya_otomatik(now=None):
    h = (now or datetime.now()).hour
    return 'gunduz' if 7 <= h < 17 else 'gece'


def _yonetim_yetkisi():
    """F_FIX_YONETIM_YETKISI - RolAd VEYA Rol alanini kabul et"""
    u = session.get('kullanici')
    if not u:
        return False
    if u.get('KullaniciAdi') == 'admin':
        return True
    rol = u.get('RolAd') or u.get('Rol') or ''
    if rol in ('Yönetim', 'Planlama', 'Enjeksiyon', 'Uretim', 'Üretim', 'Kalite'):
        return True
    return False


def yonetim_yetkili(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('kullanici'):
            return redirect(url_for('auth.login', next=request.path))
        if not _yonetim_yetkisi():
            abort(403)
        return f(*args, **kwargs)
    return wrapper


def saha_yetkili(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('kullanici'):
            return redirect(url_for('auth.login', next=request.path))
        return f(*args, **kwargs)
    return wrapper


def _makineleri_zenginlestir(rows, secili_tarih=None, vardiya=None):
    """PATCH E: Her makinenin aktif_slot_keys'ini DB'den getir.
    secili_tarih veya vardiya yoksa bos liste doner.
    """
    if not secili_tarih or vardiya not in ('gunduz', 'gece', 'mesai'):
        for m in rows:
            m['aktif'] = False
            m['aktif_slot_keys'] = []
        return rows

    try:
        con = _sqlite3.connect(_enj_kalip_db_path())
        cur = con.cursor()
        for m in rows:
            cur.execute(
                "SELECT i.istasyon_no, i.slot "
                "FROM enj_istasyon_durumu i "
                "JOIN enj_gunluk_rapor r ON r.id = i.rapor_id "
                "WHERE r.tarih = ? AND r.vardiya = ? AND r.makine_id = ? AND i.aktif = 1",
                (secili_tarih, vardiya, m['id'])
            )
            slots = [str(row[0]) + row[1] for row in cur.fetchall()]
            m['aktif_slot_keys'] = slots
            m['aktif'] = len(slots) > 0
        con.close()
    except Exception:
        # DB hatasi sayfayi bozmasin
        for m in rows:
            if 'aktif' not in m:
                m['aktif'] = False
            if 'aktif_slot_keys' not in m:
                m['aktif_slot_keys'] = []
    return rows


@enjeksiyon_bp.route('/')
@yonetim_yetkili
def yonetim_panel():
    from modules.enjeksiyon.db import makine_listele, aksama_sebep_listele, rapor_bul_veya_olustur

    vardiya = request.args.get('vardiya', '').strip()
    if vardiya not in SAATLER:
        vardiya = vardiya_otomatik()

    # PATCH E: secili_tarih'i once hesapla, sonra makineleri zenginlestir
    bugun_iso = datetime.now().strftime('%Y-%m-%d')
    secili_tarih = request.args.get('tarih', '').strip() or bugun_iso

    makineler = _makineleri_zenginlestir(makine_listele(), secili_tarih, vardiya)

    try:
        secili_makine_id = int(request.args.get('makine', ''))
    except ValueError:
        secili_makine_id = makineler[0]['id'] if makineler else None

    valid_ids = [m['id'] for m in makineler]
    if secili_makine_id not in valid_ids:
        secili_makine_id = valid_ids[0] if valid_ids else None

    rapor = None
    saatlik_kayitlar = []
    istasyonlar = []
    if secili_makine_id and vardiya in ('gunduz', 'gece', 'mesai'):
        # PATCH 2: kullanici bilgisini parametre olarak gecir
        _user = _f72_get_user()
        bundle = rapor_bul_veya_olustur(
            secili_tarih, vardiya, secili_makine_id,
            kullanici_id=_user.get("id"),
            kullanici_adi=_user.get("ad"),
        )
        if bundle:
            rapor = bundle.get('rapor') or {}
            saatlik_kayitlar = bundle.get('saatlik') or []
            istasyonlar = bundle.get('istasyonlar') or []

            # PATCH D + F9.0.5: bagli_kalip_adet sync + audit log
            if rapor and istasyonlar:
                aktif_slot_sayisi = sum(1 for i in istasyonlar if i.get('aktif'))
                if rapor.get('bagli_kalip_adet') != aktif_slot_sayisi:
                    try:
                        con_sync = _sqlite3.connect(_enj_kalip_db_path())
                        cur_sync = con_sync.cursor()
                        onceki_bagli_ssr = rapor.get('bagli_kalip_adet')
                        cur_sync.execute(
                            "UPDATE enj_gunluk_rapor SET bagli_kalip_adet=?, son_guncelleme=CURRENT_TIMESTAMP WHERE id=?",
                            (aktif_slot_sayisi, rapor['id'])
                        )
                        try:
                            from modules.enjeksiyon.audit import log_event
                            log_event(
                                con_sync, rapor['id'], 'SYNC', 'SSR_SYNC',
                                onceki_bagli_ssr, aktif_slot_sayisi,
                                meta_extra={"sebep": "SAYFA_ACILIS_MISMATCH"},
                                system_generated=True
                            )
                        except Exception:
                            pass
                        con_sync.commit()
                        con_sync.close()
                        rapor['bagli_kalip_adet'] = aktif_slot_sayisi
                    except Exception:
                        pass


        # F9_2_P3A_IST_MAP - BEGIN
        ist_map = {}
        if istasyonlar:
            _kalip_ids = set()
            for _i in istasyonlar:
                if _i.get('kalip_id'):
                    _kalip_ids.add(_i['kalip_id'])
                if _i.get('setup_kalip_id_yeni'):
                    _kalip_ids.add(_i['setup_kalip_id_yeni'])
            _kalip_kod_map = {}
            if _kalip_ids:
                try:
                    _con_k = _sqlite3.connect(_enj_kalip_db_path())
                    _con_k.row_factory = _sqlite3.Row
                    _cur_k = _con_k.cursor()
                    _q_marks = ",".join(["?"] * len(_kalip_ids))
                    _cur_k.execute(
                        f"SELECT id, kalip_kod FROM enj_kalip WHERE id IN ({_q_marks})",
                        list(_kalip_ids)
                    )
                    for _kr in _cur_k.fetchall():
                        _kalip_kod_map[_kr['id']] = _kr['kalip_kod']
                    _con_k.close()
                except Exception:
                    pass
            for _i in istasyonlar:
                _key = f"{_i.get('istasyon_no')}_{_i.get('slot')}"
                _durum = _i.get('durum')
                if not _durum:
                    _durum = 'AKTIF' if _i.get('aktif') else 'KAPALI'
                ist_map[_key] = {
                    'id': _i.get('id'),
                    'durum': _durum,
                    'kalip_id': _i.get('kalip_id'),
                    'kalip_kod': _kalip_kod_map.get(_i.get('kalip_id')),
                    'setup_kalip_id_yeni': _i.get('setup_kalip_id_yeni'),
                    'setup_yeni_kalip_kod': _kalip_kod_map.get(_i.get('setup_kalip_id_yeni')),
                    'ariza_sebep': _i.get('ariza_sebep'),
                }
        # F9_2_P3A_IST_MAP - END

    return render_template(
        'enjeksiyon/yonetim.html',
        makineler=makineler,
        secili_makine_id=secili_makine_id,
        secili_tarih=secili_tarih,
        bugun_iso=bugun_iso,
        rapor=rapor or {},
        saatlik_kayitlar=saatlik_kayitlar,
        istasyonlar=istasyonlar,
        aksama_sebepleri=aksama_sebep_listele(),
        ist_map=ist_map,  # F9_2_P3A
        bugun=datetime.now().strftime('%d.%m.%Y'),
        vardiya=vardiya,
        vardiya_metin=VARDIYA_METIN.get(vardiya, vardiya),
        saatler=SAATLER[vardiya],
    )


@enjeksiyon_bp.route('/saha')
@saha_yetkili
def saha_panel():
    return render_template('enjeksiyon/saha.html')


@enjeksiyon_bp.route('/api/saglik')
def api_saglik():
    return jsonify({'durum': 'ok', 'modul': 'enjeksiyon', 'faz': 'F6.6'})


@enjeksiyon_bp.route('/api/makine')
@yonetim_yetkili
def api_makine_listele():
    from modules.enjeksiyon.db import makine_listele
    rows = makine_listele()
    return jsonify({'durum': 'ok', 'kayit_sayisi': len(rows), 'veri': rows})


@enjeksiyon_bp.route('/api/aksama-sebep')
@yonetim_yetkili
def api_aksama_sebep_listele():
    from modules.enjeksiyon.db import aksama_sebep_listele
    rows = aksama_sebep_listele()
    return jsonify({'durum': 'ok', 'kayit_sayisi': len(rows), 'veri': rows})

# === BEGIN: ENJ_F25_API_KALIP ===
# F25.1 - Kalip Master API (dropdown listesi + detay)
# Tarih: 20260514

from flask import jsonify
import sqlite3 as _sqlite3


def _enj_kalip_db_path():
    # CPS standart DB yolu - app/mock_data.db
    import os
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, 'mock_data.db')


def _enj_kalip_row_to_dict(row):
    return {
        'id': row[0],
        'kalip_kod': row[1],
        'kalip_tipi': row[2],
        'model_kod': row[3],
        'model_ad': row[4],
        'asorti': row[5],
        'kalip_basi_cift': row[6],
        'varsayilan_bagli_kalip': row[7],
        'renk': row[8],
        'gorsel_dosya': row[9],
        'aktif': row[10],
    }


@enjeksiyon_bp.route('/api/kalip-listesi', methods=['GET'])
def enj_api_kalip_listesi():
    """
    Dropdown icin GOVDE kayitlarini liste halinde dondurur.
    Sadece aktif=1 ve kalip_tipi='GOVDE'.
    Display formati: 'TR-23B16 / CRX-LCW Bebe (22-28)'
    """
    try:
        con = _sqlite3.connect(_enj_kalip_db_path())
        cur = con.cursor()
        cur.execute('''
            SELECT id, kalip_kod, kalip_tipi, model_kod, model_ad, asorti,
                   kalip_basi_cift, varsayilan_bagli_kalip, renk, gorsel_dosya, aktif
            FROM enj_kalip
            WHERE aktif = 1 AND kalip_tipi = 'GOVDE'
            ORDER BY kalip_kod, model_kod, asorti
        ''')
        rows = cur.fetchall()
        con.close()

        kayitlar = []
        for r in rows:
            d = _enj_kalip_row_to_dict(r)
            ad = d['model_ad'] or d['model_kod']
            asorti_str = f" ({d['asorti']})" if d['asorti'] else ''
            d['display'] = f"{d['kalip_kod']} / {ad}{asorti_str}"
            kayitlar.append(d)

        return jsonify({'ok': True, 'sayi': len(kayitlar), 'kayitlar': kayitlar})
    except Exception as e:
        return jsonify({'ok': False, 'hata': str(e)}), 500


@enjeksiyon_bp.route('/api/kalip/<int:kalip_id>', methods=['GET'])
def enj_api_kalip_detay(kalip_id):
    """
    Verilen GOVDE id'sinin detayini + eslesen ATKI'yi (varsa) dondurur.
    state: 'govde-atki' veya 'govde-only'
    """
    try:
        con = _sqlite3.connect(_enj_kalip_db_path())
        cur = con.cursor()

        cur.execute('''
            SELECT id, kalip_kod, kalip_tipi, model_kod, model_ad, asorti,
                   kalip_basi_cift, varsayilan_bagli_kalip, renk, gorsel_dosya, aktif
            FROM enj_kalip
            WHERE id = ? AND aktif = 1
        ''', (kalip_id,))
        secilen_row = cur.fetchone()

        if not secilen_row:
            con.close()
            return jsonify({'ok': False, 'hata': 'Kayit bulunamadi'}), 404

        secilen = _enj_kalip_row_to_dict(secilen_row)

        if secilen['kalip_tipi'] != 'GOVDE':
            con.close()
            return jsonify({'ok': False, 'hata': 'GOVDE kaydi bekleniyor, gelen: ' + str(secilen['kalip_tipi'])}), 400

        # Eslesen ATKI'yi bul: ayni model_kod + ayni asorti + kalip_tipi='ATKI'
        cur.execute('''
            SELECT id, kalip_kod, kalip_tipi, model_kod, model_ad, asorti,
                   kalip_basi_cift, varsayilan_bagli_kalip, renk, gorsel_dosya, aktif
            FROM enj_kalip
            WHERE model_kod = ? AND aktif = 1 AND kalip_tipi = 'ATKI'
                  AND (asorti = ? OR (asorti IS NULL AND ? IS NULL))
            LIMIT 1
        ''', (secilen['model_kod'], secilen['asorti'], secilen['asorti']))
        atki_row = cur.fetchone()
        con.close()

        atki = _enj_kalip_row_to_dict(atki_row) if atki_row else None
        state = 'govde-atki' if atki else 'govde-only'

        return jsonify({
            'ok': True,
            'state': state,
            'secilen': secilen,
            'govde': secilen,
            'atki': atki,
        })
    except Exception as e:
        return jsonify({'ok': False, 'hata': str(e)}), 500
# === END: ENJ_F25_API_KALIP ===

# === BEGIN: ENJ_F7_2_RAPOR_API ===
# F7.2 - Rapor + Saatlik + Istasyon + Aksama Sebep API'leri
# Tarih: 20260514_104315
# Anahtar: (tarih, vardiya, makine_id)

from flask import request, session
from datetime import date as _date

# Vardiya saat sablonlari (sabit)
_VARDIYA_SAATLERI = {
    "gunduz": [("07:00","08:00"),("08:00","09:00"),("09:00","10:00"),("10:00","11:00"),("11:00","12:00"),("12:00","13:00"),("13:00","14:00"),("14:00","15:00"),("15:00","16:00"),("16:00","17:00")],
    "gece":   [("17:00","18:00"),("18:00","19:00"),("19:00","20:00"),("20:00","21:00"),("21:00","22:00"),("22:00","23:00"),("23:00","00:00"),("00:00","01:00"),("01:00","02:00"),("02:00","03:00"),("03:00","04:00"),("04:00","05:00"),("05:00","06:00"),("06:00","07:00")],
    "mesai":  [],
}

# Rapor PATCH icin whitelist
_RAPOR_PATCH_WHITELIST = {
    "kalip_id", "kalip_no", "emir_no", "renk",
    "kalip_basi_cift", "personel_sayisi",
    "teorik_cift_tur", "teorik_cift_gunluk",
    "yukseklik_mm", "bos_agirlik_gr",
    "gun_sonu_notu", "durum",
    # ENJ-FIRE: gun sonu fire breakdown (migration 012)
    "bos_atis_kg", "teknik_fire_kg", "yolluk_fire_kg",
}

# Saatlik PATCH icin whitelist
_SAATLIK_PATCH_WHITELIST = {  # ENJ_AB_FAZ1_V1 + F_AB_DURUM
    "tur_adet", "durum", "aksama_sebep_id", "aciklama",
    "cevrim_a", "cevrim_b",
    # F_AB_DURUM: A/B bagimsiz durum alanlari
    "durum_a", "durum_b",
    "aksama_sebep_a_id", "aksama_sebep_b_id",
    "aciklama_a", "aciklama_b",
}


def _f72_get_user():
    """Login olan kullanici bilgisini al - CPS sistem_kullanici session keylerine genis fallback."""
    # Olasi tum key'leri tara
    kid = (session.get("KullaniciId") or session.get("kullanici_id") or session.get("user_id")
           or session.get("Id") or session.get("id"))
    kad = (session.get("KullaniciAdi") or session.get("kullanici_adi") or session.get("AdSoyad")
           or session.get("ad_soyad") or session.get("kullanici_ad") or session.get("username")
           or session.get("user_name"))
    # user/kullanici dict varsa
    if not kid or not kad:
        for dkey in ("user", "kullanici", "current_user", "auth_user", "sistem_kullanici"):
            d = session.get(dkey)
            if isinstance(d, dict):
                kid = kid or d.get("Id") or d.get("id") or d.get("KullaniciId") or d.get("kullanici_id")
                kad = kad or d.get("KullaniciAdi") or d.get("kullanici_adi") or d.get("AdSoyad") or d.get("username")
                if kid or kad: break
    return {"id": kid, "ad": kad or "bilinmeyen"}


def _f72_init_saatlik(cur, rapor_id, vardiya):
    """Vardiya saatlerine gore bos saatlik kayit satirlari olustur."""
    saatler = _VARDIYA_SAATLERI.get(vardiya, [])
    for bas, bit in saatler:
        try:
            cur.execute(
                "INSERT INTO enj_saatlik_kayit (rapor_id, saat_baslangic, saat_bitis, tur_adet, durum, olusturma_tarih, son_guncelleme) "
                "VALUES (?, ?, ?, 0, 'calisiyor', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (rapor_id, bas, bit)
            )
        except _sqlite3.IntegrityError:
            pass  # zaten varsa


def _f72_init_istasyon(cur, rapor_id, istasyon_sayisi):
    """Makinenin istasyon sayisina gore A/B slot satirlari olustur."""
    for no in range(1, istasyon_sayisi + 1):
        for slot in ("A", "B"):
            try:
                cur.execute(
                    "INSERT INTO enj_istasyon_durumu (rapor_id, istasyon_no, slot, aktif) "
                    "VALUES (?, ?, ?, 0)",
                    (rapor_id, no, slot)
                )
            except _sqlite3.IntegrityError:
                pass


def _f72_load_rapor_payload(cur, rapor_id):
    """Bir rapor + saatlik + istasyon listesini dict olarak doner."""
    cur.execute("SELECT * FROM enj_gunluk_rapor WHERE id = ?", (rapor_id,))
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    rapor = dict(zip(cols, row))

    cur.execute("""
        SELECT * FROM enj_saatlik_kayit
        WHERE rapor_id = ?
        ORDER BY
            CASE
                WHEN (SELECT vardiya FROM enj_gunluk_rapor WHERE id = ?) = 'gece'
                THEN CASE WHEN CAST(SUBSTR(saat_baslangic,1,2) AS INT) >= 17 THEN 0 ELSE 1 END
                ELSE 0
            END,
            saat_baslangic
    """, (rapor_id, rapor_id))
    saatlik = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]

    cur.execute("SELECT * FROM enj_istasyon_durumu WHERE rapor_id = ? ORDER BY istasyon_no, slot", (rapor_id,))
    istasyonlar = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]

    return {"rapor": rapor, "saatlik": saatlik, "istasyonlar": istasyonlar}


@enjeksiyon_bp.route("/api/rapor", methods=["GET"])
def enj_api_rapor_bul_veya_olustur():
    """
    (tarih, vardiya, makine_id) anahtariyla rapor bul veya olustur.
    Yoksa: durum='taslak', bos saatlik + istasyon satirlari ile dogar.
    """
    try:
        tarih = request.args.get("tarih") or _date.today().isoformat()
        vardiya = request.args.get("vardiya") or "gunduz"
        try:
            makine_id = int(request.args.get("makine_id") or 1)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "hata": "makine_id sayisal olmali"}), 400

        if vardiya not in ("gunduz", "gece", "mesai"):
            return jsonify({"ok": False, "hata": "vardiya gecersiz"}), 400

        con = _sqlite3.connect(_enj_kalip_db_path())
        cur = con.cursor()

        # Makine var mi + istasyon sayisini al
        cur.execute("SELECT id, istasyon_sayisi, aktif FROM enj_makine WHERE id = ?", (makine_id,))
        mk = cur.fetchone()
        if not mk:
            con.close()
            return jsonify({"ok": False, "hata": "makine bulunamadi"}), 404

        istasyon_sayisi = mk[1]

        # Mevcut rapor var mi?
        cur.execute(
            "SELECT id FROM enj_gunluk_rapor WHERE tarih = ? AND vardiya = ? AND makine_id = ?",
            (tarih, vardiya, makine_id)
        )
        row = cur.fetchone()

        if row:
            rapor_id = row[0]
            olusturuldu = False
        else:
            user = _f72_get_user()
            try:
                cur.execute(
                    "INSERT INTO enj_gunluk_rapor (tarih, vardiya, makine_id, kullanici_id, kullanici_adi, durum, olusturma_tarih, son_guncelleme) "
                    "VALUES (?, ?, ?, ?, ?, 'taslak', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                    (tarih, vardiya, makine_id, user["id"], user["ad"])
                )
                rapor_id = cur.lastrowid
                _f72_init_saatlik(cur, rapor_id, vardiya)
                _f72_init_istasyon(cur, rapor_id, istasyon_sayisi)
                con.commit()
                olusturuldu = True
            except _sqlite3.IntegrityError:
                # Concurrent: birisi araya girip olusturmus
                con.rollback()
                cur.execute(
                    "SELECT id FROM enj_gunluk_rapor WHERE tarih = ? AND vardiya = ? AND makine_id = ?",
                    (tarih, vardiya, makine_id)
                )
                row = cur.fetchone()
                if not row:
                    con.close()
                    return jsonify({"ok": False, "hata": "rapor olusturulamadi"}), 500
                rapor_id = row[0]
                olusturuldu = False

        payload = _f72_load_rapor_payload(cur, rapor_id)
        con.close()

        if not payload:
            return jsonify({"ok": False, "hata": "rapor yuklenemedi"}), 500

        payload["ok"] = True
        payload["olusturuldu"] = olusturuldu
        return jsonify(payload)
    except Exception as e:
        return jsonify({"ok": False, "hata": str(e)}), 500


@enjeksiyon_bp.route("/api/rapor/<int:rapor_id>", methods=["PATCH"])
def enj_api_rapor_patch(rapor_id):
    """Form alanlarini guncelle (whitelist).
    F9.0.5: bagli_kalip_adet manuel guncellenemez."""
    try:
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({"ok": False, "hata": "body dict olmali"}), 400

        # F9.0.5: bagli_kalip_adet manuel guncelleme YASAK
        if 'bagli_kalip_adet' in body:
            return jsonify({
                "ok": False,
                "hata": "bagli_kalip_adet manuel guncellenemez. /api/istasyon veya /api/rapor/<id>/toplu-istasyon kullanin."
            }), 400

        guncellenecek = {k: v for k, v in body.items() if k in _RAPOR_PATCH_WHITELIST}
        if not guncellenecek:
            return jsonify({"ok": False, "hata": "guncellenecek alan yok (whitelist)"}), 400

        con = _sqlite3.connect(_enj_kalip_db_path())
        cur = con.cursor()

        cur.execute("SELECT id FROM enj_gunluk_rapor WHERE id = ?", (rapor_id,))
        if not cur.fetchone():
            con.close()
            return jsonify({"ok": False, "hata": "rapor bulunamadi"}), 404

        set_parts = [f"{k} = ?" for k in guncellenecek.keys()]
        set_parts.append("son_guncelleme = CURRENT_TIMESTAMP")
        params = list(guncellenecek.values()) + [rapor_id]
        cur.execute(f"UPDATE enj_gunluk_rapor SET {', '.join(set_parts)} WHERE id = ?", params)
        con.commit()
        con.close()

        return jsonify({"ok": True, "guncellenen": list(guncellenecek.keys())})
    except Exception as e:
        return jsonify({"ok": False, "hata": str(e)}), 500


@enjeksiyon_bp.route("/api/saatlik/<int:saatlik_id>", methods=["PATCH"])
def enj_api_saatlik_patch(saatlik_id):
    """Saatlik kaydi guncelle (tur_adet, durum, aksama_sebep_id, aciklama)."""
    try:
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({"ok": False, "hata": "body dict olmali"}), 400

        guncellenecek = {k: v for k, v in body.items() if k in _SAATLIK_PATCH_WHITELIST}
        if not guncellenecek:
            return jsonify({"ok": False, "hata": "guncellenecek alan yok"}), 400

        con = _sqlite3.connect(_enj_kalip_db_path())
        cur = con.cursor()

        cur.execute("SELECT id, rapor_id FROM enj_saatlik_kayit WHERE id = ?", (saatlik_id,))
        if not cur.fetchone():
            con.close()
            return jsonify({"ok": False, "hata": "kayit bulunamadi"}), 404

        set_parts = [f"{k} = ?" for k in guncellenecek.keys()]
        set_parts.append("son_guncelleme = CURRENT_TIMESTAMP")
        params = list(guncellenecek.values()) + [saatlik_id]
        cur.execute(f"UPDATE enj_saatlik_kayit SET {', '.join(set_parts)} WHERE id = ?", params)
        # ENJ_AB_FAZ1_V1 - hesap motoru
        try:
            _ab_hesapla_saatlik(cur, saatlik_id)
        except Exception:
            pass
        con.commit()
        con.close()

        return jsonify({"ok": True, "guncellenen": list(guncellenecek.keys())})
    except Exception as e:
        return jsonify({"ok": False, "hata": str(e)}), 500


@enjeksiyon_bp.route("/api/istasyon/<int:istasyon_id>", methods=["PATCH"])
def enj_api_istasyon_patch(istasyon_id):
    """A/B istasyon slot durumunu guncelle (aktif: 0/1)."""
    try:
        body = request.get_json(silent=True) or {}
        if "aktif" not in body:
            return jsonify({"ok": False, "hata": "aktif alani zorunlu"}), 400
        try:
            aktif = 1 if int(body["aktif"]) else 0
        except (TypeError, ValueError):
            return jsonify({"ok": False, "hata": "aktif 0 veya 1 olmali"}), 400

        con = _sqlite3.connect(_enj_kalip_db_path())
        cur = con.cursor()

        cur.execute("SELECT id FROM enj_istasyon_durumu WHERE id = ?", (istasyon_id,))
        if not cur.fetchone():
            con.close()
            return jsonify({"ok": False, "hata": "kayit bulunamadi"}), 404

        cur.execute("UPDATE enj_istasyon_durumu SET aktif = ? WHERE id = ?", (aktif, istasyon_id))

        # PATCH D + F9.0.5: rapor.bagli_kalip_adet + audit
        cur.execute("SELECT rapor_id, istasyon_no, slot FROM enj_istasyon_durumu WHERE id = ?", (istasyon_id,))
        ist_row = cur.fetchone()
        bagli = None
        if ist_row:
            rapor_id_local = ist_row[0]
            cur.execute("SELECT bagli_kalip_adet FROM enj_gunluk_rapor WHERE id=?", (rapor_id_local,))
            onceki_bagli = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM enj_istasyon_durumu WHERE rapor_id = ? AND aktif = 1",
                (rapor_id_local,)
            )
            bagli = cur.fetchone()[0]
            cur.execute(
                "UPDATE enj_gunluk_rapor SET bagli_kalip_adet = ?, son_guncelleme = CURRENT_TIMESTAMP WHERE id = ?",
                (bagli, rapor_id_local)
            )
            if onceki_bagli != bagli:
                try:
                    from modules.enjeksiyon.audit import log_event
                    log_event(
                        con, rapor_id_local, 'SLOT', 'A_B_TOGGLE',
                        onceki_bagli, bagli,
                        istasyon_id=istasyon_id,
                        meta_extra={"istasyon_no": ist_row[1], "slot": ist_row[2], "yeni_durum": aktif}
                    )
                except Exception:
                    pass

        con.commit()
        con.close()

        return jsonify({"ok": True, "aktif": aktif, "bagli_kalip_adet": bagli})
    except Exception as e:
        return jsonify({"ok": False, "hata": str(e)}), 500


@enjeksiyon_bp.route("/api/rapor/<int:rapor_id>/toplu-istasyon", methods=["POST"])
def enj_api_toplu_istasyon(rapor_id):
    """PATCH G: A TUMU / B TUMU / KAPAT - tum slotlari toplu guncelle.
    Body: { action: 'a'|'b'|'x' }
      a -> A slotlari aktif=1 (B'lere dokunma)
      b -> B slotlari aktif=1 (A'lara dokunma)
      x -> Tum slotlar aktif=0
    Sonra: bagli_kalip_adet sync ve aktif_slotlar listesi response'da.
    """
    try:
        body = request.get_json(silent=True) or {}
        action = (body.get("action") or "").lower().strip()
        if action not in ("a", "b", "x"):
            return jsonify({"ok": False, "hata": "action 'a', 'b' veya 'x' olmali"}), 400

        con = _sqlite3.connect(_enj_kalip_db_path())
        cur = con.cursor()

        # Rapor varligini dogrula
        cur.execute("SELECT id FROM enj_gunluk_rapor WHERE id = ?", (rapor_id,))
        if not cur.fetchone():
            con.close()
            return jsonify({"ok": False, "hata": "rapor bulunamadi"}), 404

        # Toplu UPDATE
        if action == "a":
            cur.execute(
                "UPDATE enj_istasyon_durumu SET aktif = 1 WHERE rapor_id = ? AND slot = 'A'",
                (rapor_id,)
            )
        elif action == "b":
            cur.execute(
                "UPDATE enj_istasyon_durumu SET aktif = 1 WHERE rapor_id = ? AND slot = 'B'",
                (rapor_id,)
            )
        else:  # action == "x"
            cur.execute(
                "UPDATE enj_istasyon_durumu SET aktif = 0 WHERE rapor_id = ?",
                (rapor_id,)
            )

        # F9.0.5: eski deger audit icin
        cur.execute("SELECT bagli_kalip_adet FROM enj_gunluk_rapor WHERE id=?", (rapor_id,))
        onceki_bagli_toplu = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(*) FROM enj_istasyon_durumu WHERE rapor_id = ? AND aktif = 1",
            (rapor_id,)
        )
        bagli = cur.fetchone()[0]

        cur.execute(
            "UPDATE enj_gunluk_rapor SET bagli_kalip_adet = ?, son_guncelleme = CURRENT_TIMESTAMP WHERE id = ?",
            (bagli, rapor_id)
        )

        if onceki_bagli_toplu != bagli:
            try:
                from modules.enjeksiyon.audit import log_event
                tetik_map = {'a': 'TOPLU_A', 'b': 'TOPLU_B', 'x': 'TOPLU_X'}
                etkilenen = abs(bagli - (onceki_bagli_toplu or 0))
                log_event(
                    con, rapor_id, 'SLOT', tetik_map[action],
                    onceki_bagli_toplu, bagli,
                    meta_extra={"action": action, "etkilenen_slot_sayisi": etkilenen}
                )
            except Exception:
                pass

        # Frontend icin aktif slot listesi (istasyon_no + slot)
        cur.execute(
            "SELECT istasyon_no, slot FROM enj_istasyon_durumu "
            "WHERE rapor_id = ? AND aktif = 1 "
            "ORDER BY istasyon_no, slot",
            (rapor_id,)
        )
        aktif_slotlar = [str(r[0]) + r[1] for r in cur.fetchall()]

        con.commit()
        con.close()

        return jsonify({
            "ok": True,
            "bagli_kalip_adet": bagli,
            "aktif_slotlar": aktif_slotlar,
            "action": action
        })
    except Exception as e:
        return jsonify({"ok": False, "hata": str(e)}), 500


@enjeksiyon_bp.route("/api/aksama-sebepleri", methods=["GET"])
def enj_api_aksama_sebepleri():
    """Saatlik kayitlarda dropdown icin aksama sebep listesi."""
    try:
        con = _sqlite3.connect(_enj_kalip_db_path())
        cur = con.cursor()
        cur.execute("PRAGMA table_info(enj_aksama_sebep)")
        kolonlar = [r[1] for r in cur.fetchall()]
        ad_kolon = "ad" if "ad" in kolonlar else ("aciklama" if "aciklama" in kolonlar else "id")
        aktif_var = "aktif" in kolonlar
        sira_var = "sira" in kolonlar

        where = "WHERE aktif = 1" if aktif_var else ""
        order = "ORDER BY sira, " + ad_kolon if sira_var else "ORDER BY " + ad_kolon

        cur.execute(f"SELECT id, {ad_kolon} as ad FROM enj_aksama_sebep {where} {order}")
        sebepler = [{"id": r[0], "ad": r[1]} for r in cur.fetchall()]
        con.close()
        return jsonify({"ok": True, "sayi": len(sebepler), "sebepler": sebepler})
    except Exception as e:
        return jsonify({"ok": False, "hata": str(e)}), 500
# === END: ENJ_F7_2_RAPOR_API ===


# ═══════════════════════════════════════════════════════════════════
# F9_2_PATCH_2_BACKEND_ENDPOINTS - BEGIN
# ═══════════════════════════════════════════════════════════════════
# 5 yeni endpoint:
#   PATCH /api/istasyon/<id>/durum         (AKTIF<->KAPALI)
#   POST  /api/istasyon/<id>/setup-start   (->SETUP)
#   POST  /api/istasyon/<id>/setup-end     (SETUP->AKTIF/KAPALI)
#   POST  /api/istasyon/<id>/ariza-start   (->ARIZA)
#   POST  /api/istasyon/<id>/ariza-end     (ARIZA->AKTIF/KAPALI)
#
# DISIPLIN:
#   - durum SOURCE OF TRUTH
#   - aktif LEGACY COMPAT (otomatik sync)
#   - bagli_kalip_adet = COUNT(durum='AKTIF')
#   - SETUP/ARIZA cakisma korumasi (400)
#   - Audit her gecislide log_event ile (F9.2 event_version)
#   - zaman_kayit her gecisi sure kaydeder (KORUMA 1)
#   - KORUMA 6: setup_end success=False -> kalip_id eski korunur


def _f92_get_kullanici_id():
    """Session'dan kullanici_id cek (yoksa None)."""
    try:
        from flask import session
        for k in ("user", "kullanici", "current_user", "auth_user", "sistem_kullanici"):
            v = session.get(k)
            if isinstance(v, dict) and v.get("id"):
                return v.get("id")
            if isinstance(v, int):
                return v
        return None
    except Exception:
        return None


def _f92_zaman_kayit(eski_durum, son_durum_zamani_str):
    """Onceki durumdan beri gecen sureyi hesapla.
    
    Returns:
        dict {sure_sn, onceki_durum, onceki_zaman} veya None.
    """
    from datetime import datetime
    if not son_durum_zamani_str or not eski_durum:
        return None
    try:
        # SQLite CURRENT_TIMESTAMP formati: 'YYYY-MM-DD HH:MM:SS'
        eski_dt = datetime.strptime(son_durum_zamani_str.split('.')[0], '%Y-%m-%d %H:%M:%S')
        sure_sn = int((datetime.now() - eski_dt).total_seconds())
        if sure_sn < 0:
            sure_sn = 0
        return {
            "sure_sn": sure_sn,
            "onceki_durum": eski_durum,
            "onceki_zaman": son_durum_zamani_str
        }
    except Exception:
        return None


def _f92_durum_to_aktif(durum):
    """durum -> aktif legacy compat mapping."""
    return 1 if durum == "AKTIF" else 0


def _f92_bagli_kalip_sync(cur, rapor_id):
    """COUNT(durum='AKTIF') -> rapor.bagli_kalip_adet sync.
    
    Returns:
        (onceki_bagli, yeni_bagli) tuple.
    """
    cur.execute("SELECT bagli_kalip_adet FROM enj_gunluk_rapor WHERE id=?", (rapor_id,))
    r = cur.fetchone()
    onceki_bagli = r[0] if r else 0
    cur.execute(
        "SELECT COUNT(*) FROM enj_istasyon_durumu WHERE rapor_id=? AND durum='AKTIF'",
        (rapor_id,)
    )
    yeni_bagli = cur.fetchone()[0]
    cur.execute(
        "UPDATE enj_gunluk_rapor SET bagli_kalip_adet=?, son_guncelleme=CURRENT_TIMESTAMP WHERE id=?",
        (yeni_bagli, rapor_id)
    )
    return (onceki_bagli, yeni_bagli)


def _f92_istasyon_yukle(cur, istasyon_id):
    """Istasyonu yukle ve dict olarak don.
    
    Returns:
        dict veya None (kayit yoksa).
    """
    cur.execute("""
        SELECT id, rapor_id, istasyon_no, slot, aktif, durum, kalip_id,
               kalip_kaynak, setup_baslangic, setup_kalip_id_eski, setup_kalip_id_yeni,
               ariza_baslangic, ariza_sebep, son_durum_zamani
        FROM enj_istasyon_durumu WHERE id=?
    """, (istasyon_id,))
    r = cur.fetchone()
    if not r:
        return None
    return {
        "id": r[0], "rapor_id": r[1], "istasyon_no": r[2], "slot": r[3],
        "aktif": r[4], "durum": r[5], "kalip_id": r[6], "kalip_kaynak": r[7],
        "setup_baslangic": r[8], "setup_kalip_id_eski": r[9], "setup_kalip_id_yeni": r[10],
        "ariza_baslangic": r[11], "ariza_sebep": r[12], "son_durum_zamani": r[13]
    }


# ───────────────────────────────────────────────────────────────────
# 1) PATCH /api/istasyon/<id>/durum
# ───────────────────────────────────────────────────────────────────
@enjeksiyon_bp.route("/api/istasyon/<int:istasyon_id>/durum", methods=["PATCH"])
def enj_api_istasyon_durum(istasyon_id):
    """Genel durum gecisi: AKTIF <-> KAPALI.
    
    Body: { durum: 'AKTIF' | 'KAPALI', kalip_id?: int }
    
    Yasak:
        - durum SETUP -> 400 (setup-end kullan)
        - durum ARIZA -> 400 (ariza-end kullan)
    """
    try:
        body = request.get_json(silent=True) or {}
        yeni_durum = body.get("durum")
        
        if yeni_durum not in ("AKTIF", "KAPALI"):
            return jsonify({"ok": False, "hata": "durum AKTIF veya KAPALI olmali"}), 400
        
        con = _sqlite3.connect(_enj_kalip_db_path())
        cur = con.cursor()
        
        ist = _f92_istasyon_yukle(cur, istasyon_id)
        if not ist:
            con.close()
            return jsonify({"ok": False, "hata": "istasyon bulunamadi"}), 404
        
        eski_durum = ist["durum"]
        
        # Yasak gecisler
        if eski_durum == "SETUP":
            con.close()
            return jsonify({"ok": False, "hata": "Slot SETUP'ta. Once /setup-end cagir"}), 400
        if eski_durum == "ARIZA":
            con.close()
            return jsonify({"ok": False, "hata": "Slot ARIZA'da. Once /ariza-end cagir"}), 400
        
        # Idempotent gecis (ayni durum)
        if eski_durum == yeni_durum:
            con.close()
            return jsonify({
                "ok": True, "durum": yeni_durum, "degisim": False,
                "mesaj": "Zaten ayni durumda"
            })
        
        # Zaman kaydi
        zaman_kayit = _f92_zaman_kayit(eski_durum, ist["son_durum_zamani"])
        
        # Update
        yeni_aktif = _f92_durum_to_aktif(yeni_durum)
        kalip_id_yeni = body.get("kalip_id", ist["kalip_id"])  # body verirse degis
        cur.execute("""
            UPDATE enj_istasyon_durumu 
            SET durum=?, aktif=?, kalip_id=?, son_durum_zamani=CURRENT_TIMESTAMP
            WHERE id=?
        """, (yeni_durum, yeni_aktif, kalip_id_yeni, istasyon_id))
        
        # bagli_kalip_adet sync
        onceki_bagli, yeni_bagli = _f92_bagli_kalip_sync(cur, ist["rapor_id"])
        
        # Audit
        try:
            from modules.enjeksiyon.audit import log_event
            log_event(
                con, ist["rapor_id"], "SLOT", "DURUM_DEGISIM",
                onceki_deger=onceki_bagli, yeni_deger=yeni_bagli,
                istasyon_id=istasyon_id,
                meta_extra={
                    "istasyon_no": ist["istasyon_no"], "slot": ist["slot"],
                    "eski_durum": eski_durum, "yeni_durum": yeni_durum,
                    "kalip_id": kalip_id_yeni
                },
                zaman_kayit=zaman_kayit
            )
        except Exception:
            pass
        
        con.commit()
        con.close()
        
        return jsonify({
            "ok": True, "durum": yeni_durum, "aktif": yeni_aktif,
            "kalip_id": kalip_id_yeni, "bagli_kalip_adet": yeni_bagli
        })
    except Exception as e:
        return jsonify({"ok": False, "hata": str(e)}), 500


# ───────────────────────────────────────────────────────────────────
# 2) POST /api/istasyon/<id>/setup-start
# ───────────────────────────────────────────────────────────────────
@enjeksiyon_bp.route("/api/istasyon/<int:istasyon_id>/setup-start", methods=["POST"])
def enj_api_istasyon_setup_start(istasyon_id):
    """Setup baslat: AKTIF/KAPALI -> SETUP.
    
    Body: { sebep: SETUP_SEBEPLER ENUM, yeni_kalip_id?: int }
    
    Yasak:
        - durum ARIZA -> 400
        - durum SETUP -> 400 (zaten setup'ta)
        - gecersiz sebep -> 400
    """
    try:
        body = request.get_json(silent=True) or {}
        sebep = body.get("sebep")
        yeni_kalip_id = body.get("yeni_kalip_id")
        
        from modules.enjeksiyon.constants import SETUP_SEBEPLER
        if sebep not in SETUP_SEBEPLER:
            return jsonify({
                "ok": False,
                "hata": f"Gecersiz sebep. Gecerli: {SETUP_SEBEPLER}"
            }), 400
        
        con = _sqlite3.connect(_enj_kalip_db_path())
        cur = con.cursor()
        
        ist = _f92_istasyon_yukle(cur, istasyon_id)
        if not ist:
            con.close()
            return jsonify({"ok": False, "hata": "istasyon bulunamadi"}), 404
        
        eski_durum = ist["durum"]
        
        if eski_durum == "ARIZA":
            con.close()
            return jsonify({"ok": False, "hata": "Slot ARIZA'da. Once /ariza-end cagir"}), 400
        if eski_durum == "SETUP":
            con.close()
            return jsonify({"ok": False, "hata": "Slot zaten SETUP'ta"}), 400
        
        zaman_kayit = _f92_zaman_kayit(eski_durum, ist["son_durum_zamani"])
        
        # Update: durum=SETUP, eski kalip korunur, yeni kalip temporary
        cur.execute("""
            UPDATE enj_istasyon_durumu 
            SET durum='SETUP', aktif=0,
                setup_baslangic=CURRENT_TIMESTAMP,
                setup_kalip_id_eski=?,
                setup_kalip_id_yeni=?,
                son_durum_zamani=CURRENT_TIMESTAMP
            WHERE id=?
        """, (ist["kalip_id"], yeni_kalip_id, istasyon_id))
        # NOT: kalip_id (mevcut) DOKUNULMAZ. setup_end success=True ile degisecek.
        
        onceki_bagli, yeni_bagli = _f92_bagli_kalip_sync(cur, ist["rapor_id"])
        
        # Audit
        try:
            from modules.enjeksiyon.audit import log_setup_start
            log_setup_start(
                con, ist["rapor_id"], istasyon_id,
                yeni_kalip_id=yeni_kalip_id, sebep=sebep,
                meta_extra={
                    "istasyon_no": ist["istasyon_no"], "slot": ist["slot"],
                    "eski_durum": eski_durum, "eski_kalip_id": ist["kalip_id"],
                    # F9_2_P3C_BACKEND_REVIZE
                    "not": body.get("not"),
                    "kalip_sonra": bool(body.get("kalip_sonra"))
                }
            )
            # zaman_kayit ayri log_event ile (helper imzasinda yok)
            if zaman_kayit:
                from modules.enjeksiyon.audit import log_event
                # Yukaridaki log_setup_start zaten event yazdi.
                # zaman_kayit setup_start meta'sinda olmaliydi,
                # F9.2 P1'de helper imzasina almadik. Patch 3'te eklenecek.
                # Su an meta_extra'da iliskiyi koruyalim.
                pass
        except Exception:
            pass
        
        con.commit()
        con.close()
        
        return jsonify({
            "ok": True, "durum": "SETUP",
            "setup_kalip_id_eski": ist["kalip_id"],
            "setup_kalip_id_yeni": yeni_kalip_id,
            "bagli_kalip_adet": yeni_bagli
        })
    except Exception as e:
        return jsonify({"ok": False, "hata": str(e)}), 500


# ───────────────────────────────────────────────────────────────────
# 3) POST /api/istasyon/<id>/setup-end
# ───────────────────────────────────────────────────────────────────
@enjeksiyon_bp.route("/api/istasyon/<int:istasyon_id>/setup-end", methods=["POST"])
def enj_api_istasyon_setup_end(istasyon_id):
    """Setup bitir: SETUP -> AKTIF (success) veya KAPALI (fail).
    
    Body: { success: bool, sebep_iptal?: str, hedef_durum?: 'AKTIF'|'KAPALI' }
    
    KRITIK KORUMA 6:
        success=True  -> kalip_id = setup_kalip_id_yeni (yeni aktif)
        success=False -> kalip_id KORUNUR (eski kalip geri)
    """
    try:
        body = request.get_json(silent=True) or {}
        if "success" not in body:
            return jsonify({"ok": False, "hata": "success alani zorunlu (bool)"}), 400
        success = bool(body["success"])
        sebep_iptal = body.get("sebep_iptal")
        hedef_durum = body.get("hedef_durum", "AKTIF" if success else "KAPALI")
        
        if hedef_durum not in ("AKTIF", "KAPALI"):
            return jsonify({"ok": False, "hata": "hedef_durum AKTIF veya KAPALI olmali"}), 400
        
        con = _sqlite3.connect(_enj_kalip_db_path())
        cur = con.cursor()
        
        ist = _f92_istasyon_yukle(cur, istasyon_id)
        if not ist:
            con.close()
            return jsonify({"ok": False, "hata": "istasyon bulunamadi"}), 404
        
        if ist["durum"] != "SETUP":
            con.close()
            return jsonify({
                "ok": False,
                "hata": f"Slot SETUP'ta degil (mevcut: {ist['durum']})"
            }), 400
        
        zaman_kayit = _f92_zaman_kayit("SETUP", ist["son_durum_zamani"])
        sure_dakika = (zaman_kayit["sure_sn"] // 60) if zaman_kayit else None
        
        # F9_2_P3C_BACKEND_REVIZE: setup-end yeni_kalip_id override
        yeni_kalip_id_override = body.get("yeni_kalip_id")

        # KRITIK KORUMA 6
        if success:
            # Oncelik: override (modal'da secildi) > setup_kalip_id_yeni > validation hata
            yeni_kalip_id = yeni_kalip_id_override or ist["setup_kalip_id_yeni"]
            if not yeni_kalip_id:
                con.close()
                return jsonify({
                    "ok": False,
                    "hata": "yeni_kalip_id zorunlu (success=True icin)"
                }), 400
        else:
            yeni_kalip_id = ist["kalip_id"]  # ESKI KORUNUR
        
        yeni_aktif = _f92_durum_to_aktif(hedef_durum)
        
        # Update + setup kolonlari temizle
        cur.execute("""
            UPDATE enj_istasyon_durumu
            SET durum=?, aktif=?, kalip_id=?,
                setup_baslangic=NULL,
                setup_kalip_id_eski=NULL,
                setup_kalip_id_yeni=NULL,
                son_durum_zamani=CURRENT_TIMESTAMP
            WHERE id=?
        """, (hedef_durum, yeni_aktif, yeni_kalip_id, istasyon_id))
        
        onceki_bagli, yeni_bagli = _f92_bagli_kalip_sync(cur, ist["rapor_id"])
        
        # Audit
        try:
            from modules.enjeksiyon.audit import log_setup_end
            log_setup_end(
                con, ist["rapor_id"], istasyon_id,
                success=success,
                sure_dakika=sure_dakika,
                sebep_iptal=sebep_iptal,
                meta_extra={
                    "istasyon_no": ist["istasyon_no"], "slot": ist["slot"],
                    "hedef_durum": hedef_durum,
                    "eski_kalip_id": ist["kalip_id"],
                    "yeni_kalip_id": yeni_kalip_id,
                    "kalip_degisti": (yeni_kalip_id != ist["kalip_id"])
                }
            )
        except Exception:
            pass
        
        con.commit()
        con.close()
        
        return jsonify({
            "ok": True, "durum": hedef_durum, "success": success,
            "kalip_id": yeni_kalip_id,
            "kalip_degisti": (yeni_kalip_id != ist["kalip_id"]),
            "sure_dakika": sure_dakika,
            "bagli_kalip_adet": yeni_bagli
        })
    except Exception as e:
        return jsonify({"ok": False, "hata": str(e)}), 500


# ───────────────────────────────────────────────────────────────────
# 4) POST /api/istasyon/<id>/ariza-start
# ───────────────────────────────────────────────────────────────────
@enjeksiyon_bp.route("/api/istasyon/<int:istasyon_id>/ariza-start", methods=["POST"])
def enj_api_istasyon_ariza_start(istasyon_id):
    """Ariza baslat: AKTIF/KAPALI -> ARIZA.
    
    Body: { sebep: ARIZA_SEBEPLER ENUM, sebep_detay?: str }
    
    Yasak:
        - durum SETUP -> 400
        - durum ARIZA -> 400
        - gecersiz sebep -> 400
    """
    try:
        body = request.get_json(silent=True) or {}
        sebep = body.get("sebep")
        sebep_detay = body.get("sebep_detay")
        
        from modules.enjeksiyon.constants import ARIZA_SEBEPLER
        if sebep not in ARIZA_SEBEPLER:
            return jsonify({
                "ok": False,
                "hata": f"Gecersiz sebep. Gecerli: {ARIZA_SEBEPLER}"
            }), 400
        
        con = _sqlite3.connect(_enj_kalip_db_path())
        cur = con.cursor()
        
        ist = _f92_istasyon_yukle(cur, istasyon_id)
        if not ist:
            con.close()
            return jsonify({"ok": False, "hata": "istasyon bulunamadi"}), 404
        
        eski_durum = ist["durum"]
        
        if eski_durum == "SETUP":
            con.close()
            return jsonify({"ok": False, "hata": "Slot SETUP'ta. Once /setup-end cagir"}), 400
        if eski_durum == "ARIZA":
            con.close()
            return jsonify({"ok": False, "hata": "Slot zaten ARIZA'da"}), 400
        
        zaman_kayit = _f92_zaman_kayit(eski_durum, ist["son_durum_zamani"])
        
        # Update
        cur.execute("""
            UPDATE enj_istasyon_durumu
            SET durum='ARIZA', aktif=0,
                ariza_baslangic=CURRENT_TIMESTAMP,
                ariza_sebep=?,
                son_durum_zamani=CURRENT_TIMESTAMP
            WHERE id=?
        """, (sebep, istasyon_id))
        
        onceki_bagli, yeni_bagli = _f92_bagli_kalip_sync(cur, ist["rapor_id"])
        
        # Audit
        try:
            from modules.enjeksiyon.audit import log_ariza_start
            log_ariza_start(
                con, ist["rapor_id"], istasyon_id,
                sebep=sebep, sebep_detay=sebep_detay,
                meta_extra={
                    "istasyon_no": ist["istasyon_no"], "slot": ist["slot"],
                    "eski_durum": eski_durum, "kalip_id": ist["kalip_id"]
                }
            )
        except Exception:
            pass
        
        con.commit()
        con.close()
        
        return jsonify({
            "ok": True, "durum": "ARIZA",
            "ariza_sebep": sebep,
            "kalip_id": ist["kalip_id"],
            "bagli_kalip_adet": yeni_bagli
        })
    except Exception as e:
        return jsonify({"ok": False, "hata": str(e)}), 500


# ───────────────────────────────────────────────────────────────────
# 5) POST /api/istasyon/<id>/ariza-end
# ───────────────────────────────────────────────────────────────────
@enjeksiyon_bp.route("/api/istasyon/<int:istasyon_id>/ariza-end", methods=["POST"])
def enj_api_istasyon_ariza_end(istasyon_id):
    """Ariza bitir: ARIZA -> AKTIF/KAPALI.
    
    Body: { yeni_durum: 'AKTIF' | 'KAPALI' }
    """
    try:
        body = request.get_json(silent=True) or {}
        yeni_durum = body.get("yeni_durum", "AKTIF")
        
        if yeni_durum not in ("AKTIF", "KAPALI"):
            return jsonify({"ok": False, "hata": "yeni_durum AKTIF veya KAPALI olmali"}), 400
        
        con = _sqlite3.connect(_enj_kalip_db_path())
        cur = con.cursor()
        
        ist = _f92_istasyon_yukle(cur, istasyon_id)
        if not ist:
            con.close()
            return jsonify({"ok": False, "hata": "istasyon bulunamadi"}), 404
        
        if ist["durum"] != "ARIZA":
            con.close()
            return jsonify({
                "ok": False,
                "hata": f"Slot ARIZA'da degil (mevcut: {ist['durum']})"
            }), 400
        
        zaman_kayit = _f92_zaman_kayit("ARIZA", ist["son_durum_zamani"])
        sure_dakika = (zaman_kayit["sure_sn"] // 60) if zaman_kayit else None
        
        yeni_aktif = _f92_durum_to_aktif(yeni_durum)
        
        # Update + ariza kolonlari temizle
        cur.execute("""
            UPDATE enj_istasyon_durumu
            SET durum=?, aktif=?,
                ariza_baslangic=NULL,
                ariza_sebep=NULL,
                son_durum_zamani=CURRENT_TIMESTAMP
            WHERE id=?
        """, (yeni_durum, yeni_aktif, istasyon_id))
        
        onceki_bagli, yeni_bagli = _f92_bagli_kalip_sync(cur, ist["rapor_id"])
        
        # Audit
        try:
            from modules.enjeksiyon.audit import log_ariza_end
            log_ariza_end(
                con, ist["rapor_id"], istasyon_id,
                yeni_durum=yeni_durum, sure_dakika=sure_dakika,
                meta_extra={
                    "istasyon_no": ist["istasyon_no"], "slot": ist["slot"],
                    "kalip_id": ist["kalip_id"],
                    "eski_ariza_sebep": ist["ariza_sebep"]
                }
            )
        except Exception:
            pass
        
        con.commit()
        con.close()
        
        return jsonify({
            "ok": True, "durum": yeni_durum,
            "kalip_id": ist["kalip_id"],
            "sure_dakika": sure_dakika,
            "bagli_kalip_adet": yeni_bagli
        })
    except Exception as e:
        return jsonify({"ok": False, "hata": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════
# F9_2_PATCH_2_BACKEND_ENDPOINTS - END
# ═══════════════════════════════════════════════════════════════════


# === BEGIN: ENJ_FOTO_FIX ===
# Enjeksiyon foto upload (kamera, max 5 MB, anlik)
# Endpointler: POST /api/foto/ekle, GET /api/foto, DELETE /api/foto/<id>
import os as _foto_os
from werkzeug.utils import secure_filename as _foto_secure

_FOTO_TIPLER = {'bos_atis', 'terlik_fire', 'yolluk_fire', 'plc_ekran'}
_FOTO_MAX = 5 * 1024 * 1024
_FOTO_EXTS = {'jpg', 'jpeg', 'png', 'webp'}


def _foto_app_dir():
    return _foto_os.path.dirname(
        _foto_os.path.dirname(_foto_os.path.dirname(__file__))
    )


def _foto_dir_olustur(rapor_id):
    base = _foto_os.path.join(_foto_app_dir(), 'static', 'img', 'enj_foto', str(rapor_id))
    _foto_os.makedirs(base, exist_ok=True)
    return base


def _foto_abs_yol(rel_yol):
    if not rel_yol:
        return None
    rel = rel_yol.lstrip('/').replace('/', _foto_os.sep)
    return _foto_os.path.join(_foto_app_dir(), rel.split(_foto_os.sep, 1)[-1] if rel.startswith('static') else rel)


@enjeksiyon_bp.route('/api/foto/ekle', methods=['POST'])
def enj_foto_ekle():
    try:
        rapor_id = int(request.form.get('rapor_id') or 0)
        tip = (request.form.get('tip') or '').strip()
        f = request.files.get('dosya')
        if not rapor_id or tip not in _FOTO_TIPLER or not f:
            return jsonify({'ok': False, 'hata': 'gecersiz parametre'}), 400

        f.seek(0, 2)
        size = f.tell()
        f.seek(0)
        if size > _FOTO_MAX:
            return jsonify({'ok': False, 'hata': '5 MB sinirini astiniz'}), 400
        if size <= 0:
            return jsonify({'ok': False, 'hata': 'dosya bos'}), 400

        orig = _foto_secure(f.filename or 'foto.jpg')
        ext = (orig.rsplit('.', 1)[-1] if '.' in orig else 'jpg').lower()
        if ext not in _FOTO_EXTS:
            ext = 'jpg'

        from datetime import datetime as _foto_dt
        ts = _foto_dt.now().strftime('%Y%m%d_%H%M%S')
        yeni_ad = tip + '_' + ts + '.' + ext

        klasor = _foto_dir_olustur(rapor_id)
        tam_yol = _foto_os.path.join(klasor, yeni_ad)
        f.save(tam_yol)

        rel_yol = '/static/img/enj_foto/' + str(rapor_id) + '/' + yeni_ad

        con = _sqlite3.connect(_enj_kalip_db_path())
        cur = con.cursor()

        # Ayni (rapor_id, tip) icin eski varsa: dosya sil + DB sil (overwrite)
        cur.execute("SELECT id, dosya_yolu FROM enj_foto WHERE rapor_id=? AND tip=?",
                    (rapor_id, tip))
        for eski in cur.fetchall():
            eski_id, eski_path = eski[0], eski[1]
            if eski_path:
                try:
                    abs_eski = _foto_os.path.join(
                        _foto_app_dir(),
                        eski_path.lstrip('/').replace('/', _foto_os.sep)
                    )
                    if _foto_os.path.isfile(abs_eski) and abs_eski != tam_yol:
                        _foto_os.remove(abs_eski)
                except Exception:
                    pass
            cur.execute("DELETE FROM enj_foto WHERE id=?", (eski_id,))

        cur.execute(
            "INSERT INTO enj_foto (rapor_id, tip, dosya_yolu, dosya_ad, dosya_boyut, yuklenme_tarih) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (rapor_id, tip, rel_yol, yeni_ad, size)
        )
        foto_id = cur.lastrowid
        con.commit()
        con.close()
        return jsonify({'ok': True, 'id': foto_id, 'url': rel_yol, 'boyut': size, 'tip': tip})
    except Exception as e:
        return jsonify({'ok': False, 'hata': str(e)}), 500


@enjeksiyon_bp.route('/api/foto', methods=['GET'])
def enj_foto_listele():
    try:
        rapor_id = int(request.args.get('rapor_id') or 0)
        if not rapor_id:
            return jsonify({'ok': False, 'hata': 'rapor_id gerekli'}), 400
        con = _sqlite3.connect(_enj_kalip_db_path())
        con.row_factory = _sqlite3.Row
        rows = con.execute(
            "SELECT id, tip, dosya_yolu, dosya_ad, dosya_boyut, yuklenme_tarih "
            "FROM enj_foto WHERE rapor_id=? ORDER BY yuklenme_tarih DESC",
            (rapor_id,)
        ).fetchall()
        fotolar = []
        for r in rows:
            fotolar.append({
                'id': r['id'], 'tip': r['tip'], 'url': r['dosya_yolu'],
                'ad': r['dosya_ad'], 'boyut': r['dosya_boyut'],
                'tarih': r['yuklenme_tarih']
            })
        con.close()
        return jsonify({'ok': True, 'fotolar': fotolar})
    except Exception as e:
        return jsonify({'ok': False, 'hata': str(e)}), 500


@enjeksiyon_bp.route('/api/foto/<int:foto_id>', methods=['DELETE'])
def enj_foto_sil(foto_id):
    try:
        con = _sqlite3.connect(_enj_kalip_db_path())
        cur = con.cursor()
        cur.execute("SELECT dosya_yolu FROM enj_foto WHERE id=?", (foto_id,))
        r = cur.fetchone()
        if not r:
            con.close()
            return jsonify({'ok': False, 'hata': 'foto bulunamadi'}), 404
        path = r[0]
        if path:
            try:
                abs_path = _foto_os.path.join(
                    _foto_app_dir(),
                    path.lstrip('/').replace('/', _foto_os.sep)
                )
                if _foto_os.path.isfile(abs_path):
                    _foto_os.remove(abs_path)
            except Exception:
                pass
        cur.execute("DELETE FROM enj_foto WHERE id=?", (foto_id,))
        con.commit()
        con.close()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'hata': str(e)}), 500
# === END: ENJ_FOTO_FIX ===

# ===== BEGIN: ENJ_AB_FAZ1_V1 =====
# FAZ 1 - veri katmani: hesap motoru + 2 yeni endpoint

def _ab_hesapla_saatlik(cur, saatlik_id):
    """Bir saatlik kayit icin uretilen_a, uretilen_b hesapla ve update et."""
    cur.execute("SELECT rapor_id, cevrim_a, cevrim_b FROM enj_saatlik_kayit WHERE id=?", (saatlik_id,))
    row = cur.fetchone()
    if not row:
        return None
    rapor_id = row[0]
    cev_a = int(row[1] or 0)
    cev_b = int(row[2] or 0)
    cur.execute(
        # ENJ_KBC_FIX: COALESCE(istasyon, master) — once uretim ozel, yoksa kalip yonetimi
        "SELECT i.slot, COALESCE(SUM(COALESCE(i.kalip_basi_cift, k.kalip_basi_cift, 0)),0) "
        "FROM enj_istasyon_durumu i LEFT JOIN enj_kalip k ON k.id = i.kalip_id "
        "WHERE i.rapor_id=? AND i.aktif=1 GROUP BY i.slot",
        (rapor_id,)
    )
    kap = {"A": 0, "B": 0}
    for slot, k in cur.fetchall():
        if slot in ("A", "B"):
            kap[slot] = int(k or 0)
    uret_a = cev_a * kap["A"]
    uret_b = cev_b * kap["B"]
    cur.execute(
        "UPDATE enj_saatlik_kayit SET uretilen_a=?, uretilen_b=? WHERE id=?",
        (uret_a, uret_b, saatlik_id)
    )
    return {"uretilen_a": uret_a, "uretilen_b": uret_b, "kapasite_a": kap["A"], "kapasite_b": kap["B"]}


def _ab_hesapla_tum_saatlikler(cur, rapor_id):
    """Bir rapor icin tum saatlik kayitlari yeniden hesapla."""
    cur.execute("SELECT id FROM enj_saatlik_kayit WHERE rapor_id=?", (rapor_id,))
    sayac = 0
    for r in cur.fetchall():
        try:
            _ab_hesapla_saatlik(cur, r[0])
            sayac += 1
        except Exception:
            pass
    return sayac


# F_KBC_MASTER_DATA_BLOCK: kalip_basi_cift kaldirildi - master data sayfasindan duzeltilir
_AB_SLOT_WHITELIST = {"kalip_id", "renk", "bagli_kalip_adet", "pisme_suresi_sn"}


@enjeksiyon_bp.route("/api/rapor/<int:rapor_id>/slot-toplu", methods=["POST"])
def enj_api_slot_toplu(rapor_id):
    """A veya B slotunun tum istasyonlarina ayni kalip/renk/bagli/kbc/pisme yaz.
    Body: {slot, kalip_id, renk, bagli_kalip_adet, kalip_basi_cift, pisme_suresi_sn}
    Tum bu rapora ait saatlikler yeniden hesaplanir.
    """
    try:
        body = request.get_json(silent=True) or {}
        slot = (body.get("slot") or "").upper().strip()
        if slot not in ("A", "B"):
            return jsonify({"ok": False, "hata": "slot A veya B olmali"}), 400
        guncel = {k: body[k] for k in _AB_SLOT_WHITELIST if k in body}
        # ENJ-RENK-KORUMA: bos/null renk = degistirme (uretim rengini silme)
        if "renk" in guncel:
            _rv = guncel["renk"]
            if _rv is None or (isinstance(_rv, str) and not _rv.strip()):
                del guncel["renk"]
        if not guncel:
            return jsonify({"ok": False, "hata": "guncellenecek alan yok"}), 400
        con = _sqlite3.connect(_enj_kalip_db_path())
        cur = con.cursor()
        cur.execute("SELECT id FROM enj_gunluk_rapor WHERE id=?", (rapor_id,))
        if not cur.fetchone():
            con.close()
            return jsonify({"ok": False, "hata": "rapor bulunamadi"}), 404
        set_parts = [k + " = ?" for k in guncel.keys()]
        params = list(guncel.values()) + [rapor_id, slot]
        cur.execute(
            "UPDATE enj_istasyon_durumu SET " + ", ".join(set_parts) +
            " WHERE rapor_id=? AND slot=?", params
        )
        affected = cur.rowcount
        recalc = _ab_hesapla_tum_saatlikler(cur, rapor_id)
        con.commit()
        con.close()
        return jsonify({"ok": True, "slot": slot, "guncellenen_slot_sayisi": affected,
                        "yeniden_hesaplanan_saatlik": recalc,
                        "guncellenen_alanlar": list(guncel.keys())})
    except Exception as e:
        return jsonify({"ok": False, "hata": str(e)}), 500


@enjeksiyon_bp.route("/api/rapor/<int:rapor_id>/ab-ozet", methods=["GET"])
def enj_api_ab_ozet(rapor_id):
    """A ve B icin: cevrim/uretilen toplam + slot ayar bilgileri + gunluk net hesabi."""
    try:
        con = _sqlite3.connect(_enj_kalip_db_path())
        cur = con.cursor()
        cur.execute(
            "SELECT COALESCE(SUM(cevrim_a),0), COALESCE(SUM(cevrim_b),0), "
            "       COALESCE(SUM(uretilen_a),0), COALESCE(SUM(uretilen_b),0) "
            "FROM enj_saatlik_kayit WHERE rapor_id=?", (rapor_id,)
        )
        cevA, cevB, uretA, uretB = cur.fetchone()
        cur.execute(
            "SELECT COALESCE(toplam_fire_cift,0) FROM enj_gunluk_rapor WHERE id=?",
            (rapor_id,)
        )
        r = cur.fetchone()
        fire_toplam = int(r[0]) if r else 0
        cur.execute(
            # ENJ_KBC_FIX: COALESCE(istasyon, master) — once uretim ozel, yoksa kalip yonetimi
            "SELECT i.slot, COALESCE(SUM(COALESCE(i.kalip_basi_cift, k.kalip_basi_cift, 0)),0) "
            "FROM enj_istasyon_durumu i LEFT JOIN enj_kalip k ON k.id = i.kalip_id "
            "WHERE i.rapor_id=? AND i.aktif=1 GROUP BY i.slot", (rapor_id,)
        )
        kap = {"A": 0, "B": 0}
        for slot, k in cur.fetchall():
            if slot in ("A", "B"):
                kap[slot] = int(k or 0)
        cur.execute(
            "SELECT i.slot, i.kalip_id, i.renk, i.bagli_kalip_adet, i.kalip_basi_cift, "
            "       i.pisme_suresi_sn, "
            "       COALESCE(i.kalip_basi_cift, k.kalip_basi_cift) AS efektif_kalip_basi_cift "
            "FROM enj_istasyon_durumu i "
            "LEFT JOIN enj_kalip k ON k.id = i.kalip_id "
            "WHERE i.rapor_id=? AND i.aktif=1 ORDER BY i.istasyon_no",
            (rapor_id,)
        )
        ayar = {"A": None, "B": None}
        for row in cur.fetchall():
            s = row[0]
            if s in ("A", "B") and ayar[s] is None:
                ayar[s] = {"kalip_id": row[1], "renk": row[2],
                           "bagli_kalip_adet": row[3], "kalip_basi_cift": row[4],
                           "pisme_suresi_sn": row[5],
                           "efektif_kalip_basi_cift": row[6]}
        for s in ("A", "B"):
            if ayar[s] and ayar[s].get("kalip_id"):
                cur.execute(
                    "SELECT kalip_kod, model_kod, gorsel_dosya FROM enj_kalip WHERE id=?",
                    (ayar[s]["kalip_id"],)
                )
                kr = cur.fetchone()
                if kr:
                    ayar[s]["kalip_kod"] = kr[0]
                    ayar[s]["model_kod"] = kr[1]
                    # ENJ_AB_GORSEL_V2 - gorsel URL
                    if kr[2]:
                        _g = str(kr[2])
                        if _g.startswith("/") or _g.startswith("http"):
                            ayar[s]["gorsel"] = _g
                        else:
                            ayar[s]["gorsel"] = "/static/img/kalip/" + _g
                    else:
                        ayar[s]["gorsel"] = None
        con.close()
        uretA = int(uretA or 0)
        uretB = int(uretB or 0)
        uret_toplam = uretA + uretB
        net_toplam = max(0, uret_toplam - fire_toplam)
        fire_orani = (fire_toplam * 100.0 / uret_toplam) if uret_toplam > 0 else 0
        net_orani = 100.0 - fire_orani if uret_toplam > 0 else 0
        return jsonify({"ok": True,
            "A": {"cevrim": int(cevA or 0), "uretilen": uretA,
                  "kapasite_per_cycle": kap["A"], "ayar": ayar["A"]},
            "B": {"cevrim": int(cevB or 0), "uretilen": uretB,
                  "kapasite_per_cycle": kap["B"], "ayar": ayar["B"]},
            "toplam": {"cevrim": int(cevA or 0) + int(cevB or 0),
                       "uretilen": uret_toplam, "fire": fire_toplam, "net": net_toplam,
                       "fire_orani": round(fire_orani, 2),
                       "net_orani": round(net_orani, 2)}
        })
    except Exception as e:
        return jsonify({"ok": False, "hata": str(e)}), 500

# ===== END: ENJ_AB_FAZ1_V1 =====


# ===== BEGIN: ENJ_SETUP_V1_FAZ1 =====
from modules.enjeksiyon import setup_db as _setup_db


@enjeksiyon_bp.route("/api/rapor/<int:rapor_id>/setup", methods=["GET"])
def enj_api_setup_list(rapor_id):
    """Slot setup listesi veya aktif setup."""
    try:
        slot = (request.args.get("slot") or "").upper().strip()
        durum = (request.args.get("durum") or "").upper().strip()
        con = _sqlite3.connect(_enj_kalip_db_path())
        cur = con.cursor()
        if slot in ("A", "B") and request.args.get("aktif") == "1":
            row = _setup_db.get_active_setup(cur, rapor_id, slot)
            con.close()
            return jsonify({"ok": True, "setup": row})
        rows = _setup_db.list_setups(
            cur, rapor_id,
            slot=slot if slot in ("A", "B") else None,
            durum=durum if durum else None,
        )
        con.close()
        return jsonify({"ok": True, "setups": rows})
    except Exception as e:
        return jsonify({"ok": False, "hata": str(e)}), 500


@enjeksiyon_bp.route("/api/rapor/<int:rapor_id>/setup", methods=["POST"])
def enj_api_setup_create(rapor_id):
    """Yeni TASLAK setup."""
    try:
        body = request.get_json(silent=True) or {}
        con = _sqlite3.connect(_enj_kalip_db_path())
        result = _setup_db.create_setup(con, rapor_id, body, _f72_get_user())
        if result.get("ok"):
            con.commit()
            con.close()
            return jsonify(result)
        con.close()
        return jsonify(result), 400
    except Exception as e:
        return jsonify({"ok": False, "hata": str(e)}), 500


@enjeksiyon_bp.route("/api/rapor/<int:rapor_id>/setup/<int:setup_id>", methods=["PATCH"])
def enj_api_setup_patch(rapor_id, setup_id):
    """TASLAK setup guncelle."""
    try:
        body = request.get_json(silent=True) or {}
        con = _sqlite3.connect(_enj_kalip_db_path())
        result = _setup_db.update_setup(con, setup_id, rapor_id, body)
        if result.get("ok"):
            con.commit()
            con.close()
            return jsonify(result)
        con.close()
        return jsonify(result), 400
    except Exception as e:
        return jsonify({"ok": False, "hata": str(e)}), 500


@enjeksiyon_bp.route("/api/rapor/<int:rapor_id>/setup/<int:setup_id>/onayla", methods=["POST"])
def enj_api_setup_onayla(rapor_id, setup_id):
    """TASLAK -> AKTIF."""
    try:
        con = _sqlite3.connect(_enj_kalip_db_path())
        result = _setup_db.approve_setup(con, setup_id, rapor_id, _f72_get_user())
        if result.get("ok"):
            con.commit()
            con.close()
            return jsonify(result)
        con.close()
        return jsonify(result), 400
    except Exception as e:
        return jsonify({"ok": False, "hata": str(e)}), 500


@enjeksiyon_bp.route("/api/rapor/<int:rapor_id>/setup/<int:setup_id>/kapat", methods=["POST"])
def enj_api_setup_kapat(rapor_id, setup_id):
    """AKTIF -> KAPANDI."""
    try:
        body = request.get_json(silent=True) or {}
        con = _sqlite3.connect(_enj_kalip_db_path())
        result = _setup_db.close_setup(
            con, setup_id, rapor_id,
            body.get("degisim_sebebi"),
            _f72_get_user(),
            notlar=body.get("notlar"),
        )
        if result.get("ok"):
            con.commit()
            con.close()
            return jsonify(result)
        con.close()
        return jsonify(result), 400
    except Exception as e:
        return jsonify({"ok": False, "hata": str(e)}), 500


# ===== END: ENJ_SETUP_V1_FAZ1 =====


# === BEGIN: ENJ_AB_RENK ===
_RENKLER_DATA = [{"kod": "0001", "ad": "SİYAH"}, {"kod": "0002", "ad": "SİYAH MAT SİYAH"}, {"kod": "0030", "ad": "GRİ"}, {"kod": "0031", "ad": "BUZ GRİ"}, {"kod": "0041", "ad": "FÜME"}, {"kod": "0042", "ad": "ANTRASİT UGG"}, {"kod": "0100", "ad": "OPTIK BEYAZ"}, {"kod": "0102", "ad": "OFF WHITE"}, {"kod": "0103", "ad": "LIGHT ECURU"}, {"kod": "0105", "ad": "BEYAZ CİHAN)"}, {"kod": "0106", "ad": "BEYAZ POLTAP)"}, {"kod": "0170", "ad": "PEMBE"}, {"kod": "0171", "ad": "TOZ PEMBE"}, {"kod": "0172", "ad": "ŞEKER PEMBE"}, {"kod": "0173", "ad": "LIGHT PEMBE"}, {"kod": "0201", "ad": "BEJ"}, {"kod": "0202", "ad": "KOYU BEJ"}, {"kod": "0221", "ad": "ACIK PUDRA"}, {"kod": "0220", "ad": "KOYU PUDRA"}, {"kod": "0240", "ad": "SOMON"}, {"kod": "0241", "ad": "CORAL"}, {"kod": "0242", "ad": "KOYU CORAL"}, {"kod": "0250", "ad": "TURUNCU"}, {"kod": "0260", "ad": "KREM"}, {"kod": "0261", "ad": "KOYU KREM"}, {"kod": "0263", "ad": "KREM FRUDA"}, {"kod": "0268", "ad": "KREM PAW PETROL"}, {"kod": "0301", "ad": "KIRMIZI"}, {"kod": "0302", "ad": "B.KIRMII"}, {"kod": "0303", "ad": "KOYU KIRMIZI"}, {"kod": "0400", "ad": "AÇIK LACİVERT"}, {"kod": "0401", "ad": "LACİVERT"}, {"kod": "0402", "ad": "LACİVERT ELİS TERLİK"}, {"kod": "0449", "ad": "LILA"}, {"kod": "0450", "ad": "AÇIK LILA"}, {"kod": "0451", "ad": "KOYU LİLA"}, {"kod": "0455", "ad": "MOR"}, {"kod": "0500", "ad": "AÇIK SARI"}, {"kod": "0502", "ad": "HARDAL"}, {"kod": "0560", "ad": "FUSYA"}, {"kod": "0677", "ad": "MAVİ"}, {"kod": "0678", "ad": "BUZ MAVİ"}, {"kod": "0680", "ad": "CYAN"}, {"kod": "0683", "ad": "SAX MAVİ"}, {"kod": "0688", "ad": "BEBE MAVİ"}, {"kod": "0700", "ad": "TURKUAZ"}, {"kod": "0702", "ad": "PETROL YEŞİLİ"}, {"kod": "0721", "ad": "AÇIK SU YEŞİL"}, {"kod": "0722", "ad": "YOSUN YEŞİLİ"}, {"kod": "0726", "ad": "HAKİ YEŞİL"}, {"kod": "0730", "ad": "DUL MINT"}, {"kod": "0820", "ad": "LİME"}, {"kod": "0850", "ad": "POWDER PINK"}, {"kod": "0902", "ad": "VİZON"}, {"kod": "0903", "ad": "VİZON(UGG)"}, {"kod": "0929", "ad": "KOYU CAMEL"}, {"kod": "0930", "ad": "CAMEL"}, {"kod": "0960", "ad": "KAHVERENGİ"}, {"kod": "0961", "ad": "SÜTLÜ KAHVE"}, {"kod": "0990", "ad": "BORDO"}]


def _enj_renk_init():
    """Renk tablosunu olustur ve veri yukle (idempotent)."""
    try:
        con = _sqlite3.connect(_enj_kalip_db_path())
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS enj_renk (
                kod TEXT PRIMARY KEY,
                ad TEXT NOT NULL,
                aktif INTEGER DEFAULT 1
            )
        """)
        for r in _RENKLER_DATA:
            cur.execute(
                "INSERT INTO enj_renk(kod, ad, aktif) VALUES(?, ?, 1) "
                "ON CONFLICT(kod) DO UPDATE SET ad=excluded.ad",
                (r['kod'], r['ad'])
            )
        con.commit()
        con.close()
    except Exception as _e:
        pass


_enj_renk_init()


@enjeksiyon_bp.route('/api/renk-listesi', methods=['GET'])
def enj_api_renk_listesi():
    try:
        con = _sqlite3.connect(_enj_kalip_db_path())
        cur = con.cursor()
        cur.execute("SELECT kod, ad FROM enj_renk WHERE aktif=1 ORDER BY kod")
        renkler = [{'kod': r[0], 'ad': r[1]} for r in cur.fetchall()]
        con.close()
        return jsonify({'ok': True, 'sayi': len(renkler), 'renkler': renkler})
    except Exception as e:
        return jsonify({'ok': False, 'hata': str(e)}), 500
# === END: ENJ_AB_RENK ===




# PATCH 3.A imports
from datetime import date as _date, timedelta as _timedelta

# =====================================================================
# PATCH 3.A - GECMIS RAPOR BACKEND ENDPOINTS
# =====================================================================
# Sadece SELECT + runtime hesap. Write yok.
# 2 endpoint:
#   GET /api/raporlar (liste + filtre + pagination)
#   GET /api/raporlar/<id>/detay (lazy load)
# 4 helper (runtime).


def _f74_v1_fallback(saatlik_dict):
    """V1 kayitlari icin fallback - cevrim_a/b NULL ise tur_adet'i A'ya yaz."""
    sk = saatlik_dict
    ca = sk.get("cevrim_a")
    cb = sk.get("cevrim_b")
    # Hem A hem B NULL ise V1 kaydi - tur_adet'i A'ya at
    if ca is None and cb is None:
        v1_tur = sk.get("tur_adet") or 0
        sk["cevrim_a_eff"] = v1_tur
        sk["cevrim_b_eff"] = 0
        sk["v1_fallback"] = True
    else:
        sk["cevrim_a_eff"] = ca or 0
        sk["cevrim_b_eff"] = cb or 0
        sk["v1_fallback"] = False
    # Durum fallback
    sk["durum_a_eff"] = sk.get("durum_a") or sk.get("durum")
    sk["durum_b_eff"] = sk.get("durum_b") or sk.get("durum")
    sk["sebep_a_eff"] = sk.get("aksama_sebep_a_id") or sk.get("aksama_sebep_id")
    sk["sebep_b_eff"] = sk.get("aksama_sebep_b_id") or sk.get("aksama_sebep_id")
    return sk


def _f75_runtime_teorik(uretim_a, uretim_b, fire):
    """Teorik = uretim + fire (uretim hesap motoru tarafindan zaten dogru hesaplanmis)."""
    return int((uretim_a or 0) + (uretim_b or 0) + (fire or 0))


def _f76_runtime_verim(net, teorik):
    """Verim = net/teorik. None doner eger teorik 0 ise."""
    if not teorik or teorik <= 0:
        return None
    try:
        return round((net / teorik) * 100, 2)
    except Exception:
        return None


def _f73_hesap_ozet(rapor_dict, saatlik_aggregate):
    """Tek rapor icin runtime ozet hesapla.
    saatlik_aggregate: {rapor_id: {toplam_tur_a, toplam_tur_b, toplam_uretim_a, toplam_uretim_b, toplam_tur_v1, problemli_saat}}
    """
    rid = rapor_dict.get("id")
    agg = saatlik_aggregate.get(rid, {})
    tur_a = int(agg.get("toplam_tur_a") or 0)
    tur_b = int(agg.get("toplam_tur_b") or 0)
    tur_v1 = int(agg.get("toplam_tur_v1") or 0)
    uret_a = int(agg.get("toplam_uretim_a") or 0)
    uret_b = int(agg.get("toplam_uretim_b") or 0)
    fire = int(rapor_dict.get("toplam_fire_cift") or 0)
    # V1 fallback: A/B yokken tur_adet kullanildiysa, uretim hesap motoru zaten 0 yazmistir
    if tur_a == 0 and tur_b == 0 and tur_v1 > 0:
        # V1 kayit - uretim yok, tur_adet'i goster
        tur_a_eff = tur_v1
    else:
        tur_a_eff = tur_a
    toplam_uretim = uret_a + uret_b
    net = toplam_uretim - fire
    teorik = _f75_runtime_teorik(uret_a, uret_b, fire)
    verim = _f76_runtime_verim(net, teorik)
    return {
        "toplam_tur_a": tur_a_eff,
        "toplam_tur_b": tur_b,
        "toplam_uretim_a": uret_a,
        "toplam_uretim_b": uret_b,
        "toplam_uretim": toplam_uretim,
        "teorik": teorik,
        "fire": fire,
        "net": net,
        "verim_yuzde": verim,
        "korgun_kapatti_cift": rapor_dict.get("korgun_kapatti_cift"),
        "fark_cift": rapor_dict.get("fark_cift"),
        "problemli_saat_sayisi": int(agg.get("problemli_saat") or 0),
        "v1_kayit": (tur_a == 0 and tur_b == 0 and tur_v1 > 0),
    }


@enjeksiyon_bp.route("/api/raporlar", methods=["GET"])
def enj_api_raporlar_listele():
    """PATCH 3.A: Gecmis raporlar listesi - filtreli + pagination + runtime ozet."""
    try:
        tarih_baslangic = (request.args.get("tarih_baslangic") or "").strip()
        tarih_bitis = (request.args.get("tarih_bitis") or "").strip()
        makine_id_raw = request.args.get("makine_id")
        vardiya = (request.args.get("vardiya") or "").strip()
        operator = (request.args.get("operator") or "").strip()
        sadece_problemli = request.args.get("sadece_problemli") == "1"
        sadece_fireli = request.args.get("sadece_fireli") == "1"

        try:
            limit = int(request.args.get("limit") or 100)
        except (TypeError, ValueError):
            limit = 100
        limit = max(1, min(limit, 500))
        try:
            offset = int(request.args.get("offset") or 0)
        except (TypeError, ValueError):
            offset = 0
        offset = max(0, offset)

        # Default tarih: son 7 gun
        if not tarih_baslangic:
            tarih_baslangic = (_date.today() - _timedelta(days=7)).isoformat()
        if not tarih_bitis:
            tarih_bitis = _date.today().isoformat()

        makine_id = None
        if makine_id_raw:
            try:
                makine_id = int(makine_id_raw)
            except (TypeError, ValueError):
                return jsonify({"ok": False, "hata": "makine_id sayisal olmali"}), 400

        if vardiya and vardiya not in ("gunduz", "gece", "mesai"):
            return jsonify({"ok": False, "hata": "vardiya gecersiz"}), 400

        con = _sqlite3.connect(_enj_kalip_db_path())
        con.row_factory = _sqlite3.Row
        cur = con.cursor()

        # WHERE clause + params (paylasilan)
        where_parts = ["r.tarih BETWEEN ? AND ?"]
        params = [tarih_baslangic, tarih_bitis]
        if makine_id is not None:
            where_parts.append("r.makine_id = ?")
            params.append(makine_id)
        if vardiya:
            where_parts.append("r.vardiya = ?")
            params.append(vardiya)
        if operator:
            where_parts.append("r.kullanici_adi = ?")
            params.append(operator)
        if sadece_fireli:
            where_parts.append("COALESCE(r.toplam_fire_cift,0) > 0")

        where_sql = " AND ".join(where_parts)

        # === Sorgu B: toplam (pagination icin) ===
        cur.execute(
            "SELECT COUNT(*) FROM enj_gunluk_rapor r "
            "LEFT JOIN enj_makine m ON m.id = r.makine_id "
            "WHERE " + where_sql,
            params
        )
        toplam = cur.fetchone()[0]

        # === Sorgu A: head + makine ad ===
        cur.execute(
            "SELECT r.id, r.tarih, r.vardiya, r.makine_id, m.ad AS makine_ad, "
            "       r.kullanici_id, r.kullanici_adi AS operator, "
            "       r.personel_sayisi, r.bagli_kalip_adet, r.durum, "
            "       COALESCE(r.toplam_fire_cift,0) AS toplam_fire_cift, "
            "       r.fire_kg, r.korgun_kapatti_cift, r.fark_cift, "
            "       r.olusturma_tarih, r.son_guncelleme "
            "FROM enj_gunluk_rapor r "
            "LEFT JOIN enj_makine m ON m.id = r.makine_id "
            "WHERE " + where_sql + " "
            "ORDER BY r.tarih DESC, r.makine_id, r.vardiya "
            "LIMIT ? OFFSET ?",
            params + [limit, offset]
        )
        rapor_rows = [dict(r) for r in cur.fetchall()]

        if not rapor_rows:
            con.close()
            return jsonify({
                "ok": True, "toplam": toplam, "limit": limit, "offset": offset,
                "kayitlar": []
            })

        # === Sorgu C: saatlik aggregate (rapor_id IN ...) ===
        rapor_ids = [r["id"] for r in rapor_rows]
        placeholders = ",".join("?" for _ in rapor_ids)
        cur.execute(
            "SELECT rapor_id, "
            "       COALESCE(SUM(cevrim_a),0) AS toplam_tur_a, "
            "       COALESCE(SUM(cevrim_b),0) AS toplam_tur_b, "
            "       COALESCE(SUM(uretilen_a),0) AS toplam_uretim_a, "
            "       COALESCE(SUM(uretilen_b),0) AS toplam_uretim_b, "
            "       COALESCE(SUM(tur_adet),0) AS toplam_tur_v1, "
            "       SUM(CASE "
            "           WHEN (durum_a IS NOT NULL AND durum_a != 'calisiyor') "
            "             OR (durum_b IS NOT NULL AND durum_b != 'calisiyor') "
            "           THEN 1 ELSE 0 END) AS problemli_saat "
            "FROM enj_saatlik_kayit "
            "WHERE rapor_id IN (" + placeholders + ") "
            "GROUP BY rapor_id",
            rapor_ids
        )
        aggregate = {row["rapor_id"]: dict(row) for row in cur.fetchall()}

        con.close()

        # Runtime hesap + cevap olustur
        kayitlar = []
        for r in rapor_rows:
            ozet = _f73_hesap_ozet(r, aggregate)
            if sadece_problemli and ozet.get("problemli_saat_sayisi", 0) == 0:
                continue
            kayitlar.append({
                "id": r["id"],
                "tarih": r["tarih"],
                "vardiya": r["vardiya"],
                "makine_id": r["makine_id"],
                "makine_ad": r["makine_ad"],
                "operator": r["operator"],
                "kullanici_id": r["kullanici_id"],
                "personel_sayisi": r["personel_sayisi"],
                "bagli_kalip_adet": r["bagli_kalip_adet"],
                "durum": r["durum"],
                "ozet": ozet,
                "olusturma_tarih": r["olusturma_tarih"],
                "son_guncelleme": r["son_guncelleme"],
            })

        return jsonify({
            "ok": True,
            "toplam": toplam,
            "limit": limit,
            "offset": offset,
            "kayitlar": kayitlar,
        })

    except Exception as e:
        return jsonify({"ok": False, "hata": str(e)[:200]}), 500


@enjeksiyon_bp.route("/api/raporlar/<int:rapor_id>/detay", methods=["GET"])
def enj_api_raporlar_detay(rapor_id):
    """PATCH 3.A: Tek rapor icin saatlik + slot + sebep detayi."""
    try:
        con = _sqlite3.connect(_enj_kalip_db_path())
        con.row_factory = _sqlite3.Row
        cur = con.cursor()

        # Sorgu D-1: head + makine
        cur.execute(
            "SELECT r.*, m.ad AS makine_ad "
            "FROM enj_gunluk_rapor r "
            "LEFT JOIN enj_makine m ON m.id = r.makine_id "
            "WHERE r.id = ?", (rapor_id,)
        )
        row = cur.fetchone()
        if not row:
            con.close()
            return jsonify({"ok": False, "hata": "rapor bulunamadi"}), 404
        rapor = dict(row)

        # Sorgu D-2: saatlik + sebep JOIN
        cur.execute(
            "SELECT s.*, "
            "       sa.ad AS sebep_a_ad, "
            "       sb.ad AS sebep_b_ad, "
            "       so.ad AS sebep_ad "
            "FROM enj_saatlik_kayit s "
            "LEFT JOIN enj_aksama_sebep sa ON sa.id = s.aksama_sebep_a_id "
            "LEFT JOIN enj_aksama_sebep sb ON sb.id = s.aksama_sebep_b_id "
            "LEFT JOIN enj_aksama_sebep so ON so.id = s.aksama_sebep_id "
            "WHERE s.rapor_id = ? "
            "ORDER BY s.saat_baslangic", (rapor_id,)
        )
        saatlik = [_f74_v1_fallback(dict(r)) for r in cur.fetchall()]

        # Sorgu D-3: slot + kalip JOIN
        cur.execute(
            "SELECT i.id, i.istasyon_no, i.slot, i.aktif, "
            "       i.kalip_id, k.kalip_kod, k.model_kod, k.model_ad, "
            "       i.renk, "
            "       COALESCE(i.kalip_basi_cift, k.kalip_basi_cift) AS kalip_basi_cift, "
            "       i.pisme_suresi_sn, i.bagli_kalip_adet, "
            "       i.durum, i.kalip_kaynak, "
            "       i.setup_baslangic, i.ariza_baslangic, i.ariza_sebep, "
            "       i.son_durum_zamani "
            "FROM enj_istasyon_durumu i "
            "LEFT JOIN enj_kalip k ON k.id = i.kalip_id "
            "WHERE i.rapor_id = ? "
            "ORDER BY i.istasyon_no, i.slot", (rapor_id,)
        )
        slotlar = [dict(r) for r in cur.fetchall()]

        # Runtime aggregate (tek rapor)
        cur.execute(
            "SELECT COALESCE(SUM(cevrim_a),0) AS toplam_tur_a, "
            "       COALESCE(SUM(cevrim_b),0) AS toplam_tur_b, "
            "       COALESCE(SUM(uretilen_a),0) AS toplam_uretim_a, "
            "       COALESCE(SUM(uretilen_b),0) AS toplam_uretim_b, "
            "       COALESCE(SUM(tur_adet),0) AS toplam_tur_v1, "
            "       SUM(CASE "
            "           WHEN (durum_a IS NOT NULL AND durum_a != 'calisiyor') "
            "             OR (durum_b IS NOT NULL AND durum_b != 'calisiyor') "
            "           THEN 1 ELSE 0 END) AS problemli_saat "
            "FROM enj_saatlik_kayit WHERE rapor_id = ?", (rapor_id,)
        )
        agg_row = cur.fetchone()
        aggregate = {rapor_id: dict(agg_row)} if agg_row else {}

        con.close()

        ozet = _f73_hesap_ozet(rapor, aggregate)

        return jsonify({
            "ok": True,
            "rapor": rapor,
            "ozet": ozet,
            "saatlik": saatlik,
            "slotlar": slotlar,
        })

    except Exception as e:
        return jsonify({"ok": False, "hata": str(e)[:200]}), 500


# === END: PATCH 3.A ===



# =====================================================================
# PATCH 3.B - GECMIS RAPOR UI ROUTE
# =====================================================================
@enjeksiyon_bp.route('/gecmis')
@yonetim_yetkili
def gecmis_panel():
    """PATCH 3.B: Gecmis raporlar UI sayfasi - sadece template render."""
    return render_template('enjeksiyon/gecmis.html')


# === END: PATCH 3.B ===
