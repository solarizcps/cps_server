# -*- coding: utf-8 -*-
"""Planlama > Üretim Plan — Faz 2 + Faz 3 (Enjeksiyon Kapasite)."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

from flask import Blueprint, abort, jsonify, render_template, request, send_file, session

from db import get_conn
from modules.auth import yetki_gerekli, yetki_var
from modules.planlama import uretim_plan_repo as repo
from modules.planlama.uretim_plan_service import (
    merge_plan_korgun,
    m_emirler_lazy,
    model_satir_by_canonical,
    proses_detay_lazy,
    siparis_model_satirlari,
    stok_gorsel_yolu,
    y_emirler_lazy,
)

uretim_plan_bp = Blueprint(
    'uretim_plan_bp',
    __name__,
    url_prefix='/planlama/uretim-plan',
)


def _uid():
    u = session.get('kullanici') or {}
    return int(u.get('Id') or u.get('id') or 0)


def _plan_edit_required():
    if not yetki_var('planlama', 'can_update') and not yetki_var('planlama', 'can_create'):
        abort(403)


@uretim_plan_bp.route('/', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def uretim_plan_sayfa():
    return render_template(
        'planlama/uretim_plan.html',
        gerekce_secenekleri=repo.GEREKCE_SECENEKLERI,
        plan_donemleri=repo.PLAN_DONEMLERI,
        can_edit=yetki_var('planlama', 'can_update') or yetki_var('planlama', 'can_create'),
    )


@uretim_plan_bp.route('/api/siparis-onizle', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def api_siparis_onizle():
    sip = (request.args.get('sipno') or '').strip()
    if not sip.isdigit():
        return jsonify({'ok': False, 'mesaj': 'Geçerli sipariş no girin'}), 400
    try:
        from modules.common import korgun as kk
        con = kk._baglan()
        try:
            data = siparis_model_satirlari(con, int(sip))
        finally:
            con.close()
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': 'Korgun: ' + str(e)[:200]}), 500
    if not data:
        return jsonify({'ok': False, 'mesaj': 'Sipariş bulunamadı'}), 404
    return jsonify({'ok': True, 'siparis': data['siparis'], 'onizleme': data['onizleme']})


@uretim_plan_bp.route('/api/planlar', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def api_planlar():
    donem = (request.args.get('donem') or 'bu_hafta').strip()
    if donem not in repo.PLAN_DONEMLERI:
        return jsonify({'ok': False, 'mesaj': 'Geçersiz dönem', 'satirlar': []}), 400
    plans = repo.liste_aktif_planlar(donem)
    satirlar = []
    try:
        from modules.common import korgun as kk
        con = kk._baglan()
        try:
            for p in plans:
                kg = model_satir_by_canonical(
                    con, p['sip_no'], p['sip_harinx'], p['mamul_skod'], p['rkod'],
                    plan_fields=p,
                )
                satirlar.append(merge_plan_korgun(p, kg))
        finally:
            con.close()
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': 'Korgun: ' + str(e)[:200], 'satirlar': []}), 500
    satirlar.sort(key=lambda x: (x.get('oncelik') or 99, x.get('plan_baslangic') or ''))
    return jsonify({
        'ok': True, 'donem': donem, 'satirlar': satirlar,
        'toplam': len(satirlar), 'kaynak': 'korgun+cps',
    })


@uretim_plan_bp.route('/api/plan', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def api_plan_ekle():
    _plan_edit_required()
    body = request.get_json(silent=True) or {}
    required = ('sip_no', 'sip_harinx', 'mamul_skod', 'rkod', 'plan_donemi')
    for k in required:
        if body.get(k) is None or body.get(k) == '':
            return jsonify({'ok': False, 'mesaj': f'Eksik alan: {k}'}), 400
    try:
        row = repo.plan_ekle(body, _uid())
    except ValueError as e:
        return jsonify({'ok': False, 'mesaj': str(e)}), 409
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200]}), 500
    return jsonify({'ok': True, 'plan': row})


@uretim_plan_bp.route('/api/plan/<int:plan_id>', methods=['PUT'])
@yetki_gerekli('planlama', 'can_view')
def api_plan_guncelle(plan_id):
    _plan_edit_required()
    body = request.get_json(silent=True) or {}
    try:
        row = repo.plan_guncelle(plan_id, body, _uid())
    except ValueError as e:
        return jsonify({'ok': False, 'mesaj': str(e)}), 404
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200]}), 500
    return jsonify({'ok': True, 'plan': row})


@uretim_plan_bp.route('/api/plan/<int:plan_id>', methods=['DELETE'])
@yetki_gerekli('planlama', 'can_view')
def api_plan_pasif(plan_id):
    _plan_edit_required()
    try:
        row = repo.plan_pasif(plan_id, _uid())
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200]}), 500
    if not row:
        return jsonify({'ok': False, 'mesaj': 'Plan bulunamadı'}), 404
    return jsonify({'ok': True, 'plan': row})


@uretim_plan_bp.route('/api/detay/<int:plan_id>', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def api_detay_ozet(plan_id):
    plan = repo.plan_get(plan_id)
    if not plan or not plan.get('aktif'):
        return jsonify({'ok': False, 'mesaj': 'Plan bulunamadı'}), 404
    try:
        from modules.common import korgun as kk
        con = kk._baglan()
        try:
            kg = model_satir_by_canonical(
                con, plan['sip_no'], plan['sip_harinx'], plan['mamul_skod'], plan['rkod'],
                plan_fields=plan,
            )
        finally:
            con.close()
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': 'Korgun: ' + str(e)[:200]}), 500
    satir = merge_plan_korgun(plan, kg)
    return jsonify({'ok': True, 'satir': satir})


@uretim_plan_bp.route('/api/detay/<int:plan_id>/m-emirler', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def api_detay_m_emirler(plan_id):
    plan = repo.plan_get(plan_id)
    if not plan:
        return jsonify({'ok': False, 'mesaj': 'Plan bulunamadı'}), 404
    try:
        from modules.common import korgun as kk
        con = kk._baglan()
        try:
            lots = m_emirler_lazy(
                con, plan['sip_no'], plan['sip_harinx'], plan['mamul_skod'], plan['rkod'],
            )
        finally:
            con.close()
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200]}), 500
    return jsonify({'ok': True, 'm_lotlar': lots})


@uretim_plan_bp.route('/api/detay/m/<int:m_emir_no>/y-emirler', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def api_detay_y_emirler(m_emir_no):
    try:
        from modules.common import korgun as kk
        con = kk._baglan()
        try:
            rows = y_emirler_lazy(con, m_emir_no)
        finally:
            con.close()
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200]}), 500
    return jsonify({'ok': True, 'y_emirler': rows})


@uretim_plan_bp.route('/api/detay/emir/<int:emir_no>/proses', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def api_detay_proses(emir_no):
    try:
        from modules.common import korgun as kk
        con = kk._baglan()
        try:
            rows = proses_detay_lazy(con, emir_no)
        finally:
            con.close()
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200]}), 500
    return jsonify({'ok': True, 'prosesler': rows})


# ─── ENJEKSİYON KAPASİTE API'LERİ ──────────────────────────────────────────

@uretim_plan_bp.route('/api/enj/makineler', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def api_enj_makineler():
    """Aktif enjeksiyon makineleri — makine select için."""
    con = get_conn()
    try:
        rows = con.execute(
            'SELECT id, kod, ad, istasyon_sayisi FROM enj_makine WHERE aktif=1 ORDER BY sira'
        ).fetchall()
        return jsonify({'ok': True, 'makineler': [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200]}), 500
    finally:
        con.close()


@uretim_plan_bp.route('/api/enj/slot-durum', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def api_enj_slot_durum():
    """Verilen makine+istasyon+slot için canlı setup durumu (bilgi amaçlı, write yok)."""
    makine_id = request.args.get('makine_id', type=int)
    istasyon_no = request.args.get('istasyon_no', type=int)
    slot = (request.args.get('slot') or '').upper()
    if not makine_id or not istasyon_no or slot not in ('A', 'B'):
        return jsonify({'ok': False, 'mesaj': 'makine_id, istasyon_no, slot gerekli'}), 400
    con = get_conn()
    try:
        row = con.execute("""
            SELECT s.kalip_kod_snapshot, s.aktif_goz_sayisi, s.kalip_basi_cift,
                   s.aktif_goz_sayisi * s.kalip_basi_cift AS tur_cift,
                   s.baslangic_zamani, r.tarih, r.vardiya
            FROM enj_ab_setup s
            JOIN enj_gunluk_rapor r ON r.id = s.rapor_id
            WHERE s.makine_id = ? AND s.slot = ?
              AND r.makine_id = ?
              AND s.durum = 'AKTIF'
              AND r.tarih = (
                  SELECT MAX(r2.tarih) FROM enj_gunluk_rapor r2
                   WHERE r2.makine_id = ?
              )
            ORDER BY s.baslangic_zamani DESC LIMIT 1
        """, (makine_id, slot, makine_id, makine_id)).fetchone()
        if not row:
            return jsonify({'ok': True, 'durum': 'BOS', 'veri': None})
        d = dict(row)
        d['durum'] = 'DOLU' if (d.get('aktif_goz_sayisi') or 0) > 0 else 'BOS'
        return jsonify({'ok': True, 'durum': d['durum'], 'veri': d})
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200]}), 500
    finally:
        con.close()


@uretim_plan_bp.route('/api/enj/kaliplar', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def api_enj_kaliplar():
    """Aktif kalıp master listesi — kalıp select için."""
    con = get_conn()
    try:
        rows = con.execute("""
            SELECT id, kalip_kod, kalip_tipi, model_kod, model_ad,
                   kalip_basi_cift, kapasite_cift
            FROM enj_kalip
            WHERE aktif = 1
            ORDER BY kalip_kod
        """).fetchall()
        return jsonify({'ok': True, 'kaliplar': [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200]}), 500
    finally:
        con.close()


@uretim_plan_bp.route('/api/enj/kalip-kapasite', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def api_enj_kalip_kapasite():
    """Kalıp için aktif setup'tan ya da master'dan tur_cift bilgisi."""
    kalip_id = request.args.get('kalip_id', type=int)
    makine_id = request.args.get('makine_id', type=int)
    slot = (request.args.get('slot') or '').upper() or None
    if not kalip_id:
        return jsonify({'ok': False, 'mesaj': 'kalip_id gerekli'}), 400
    con = get_conn()
    try:
        setup = None
        if makine_id:
            q = """
                SELECT s.aktif_goz_sayisi, s.kalip_basi_cift,
                       s.aktif_goz_sayisi * s.kalip_basi_cift AS tur_cift,
                       'setup' AS kaynak
                FROM enj_ab_setup s
                JOIN enj_gunluk_rapor r ON r.id = s.rapor_id
                WHERE s.kalip_id = ? AND s.makine_id = ? AND s.durum = 'AKTIF'
                  AND r.tarih = (SELECT MAX(r2.tarih) FROM enj_gunluk_rapor r2 WHERE r2.makine_id=?)
            """
            params = [kalip_id, makine_id, makine_id]
            if slot:
                q += ' AND s.slot = ?'
                params.append(slot)
            q += ' ORDER BY s.baslangic_zamani DESC LIMIT 1'
            setup = con.execute(q, params).fetchone()

        if setup:
            d = dict(setup)
            d['kapasite_eksik'] = False
            return jsonify({'ok': True, 'kapasite': d})

        master = con.execute("""
            SELECT kalip_basi_cift, kapasite_cift
            FROM enj_kalip WHERE id=? AND aktif=1
        """, (kalip_id,)).fetchone()
        if not master:
            return jsonify({'ok': True, 'kapasite': None, 'kapasite_eksik': True,
                            'mesaj': 'Kalıp bulunamadı'})

        kbc = master['kalip_basi_cift']
        if not kbc:
            return jsonify({'ok': True, 'kapasite': None, 'kapasite_eksik': True,
                            'mesaj': 'Kapasite bilgisi eksik — manuel girin'})

        return jsonify({'ok': True, 'kapasite': {
            'aktif_goz_sayisi': None,
            'kalip_basi_cift': kbc,
            'tur_cift': None,
            'kaynak': 'master',
        }, 'kapasite_eksik': True,
            'mesaj': 'Aktif setup yok — aktif göz sayısını girin'})
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200]}), 500
    finally:
        con.close()


@uretim_plan_bp.route('/api/enj/cakisma-kontrol', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def api_enj_cakisma_kontrol():
    """Aynı slot/tarih çakışma kontrolü — uyarı amaçlı."""
    body = request.get_json(silent=True) or {}
    makine_id = body.get('makine_id')
    istasyon_no = body.get('istasyon_no')
    slot = (body.get('slot') or '').upper()
    bas = body.get('enj_plan_baslangic')
    bit = body.get('enj_plan_bitis')
    hariç_plan_id = body.get('hariç_plan_id')
    if not makine_id or not istasyon_no or slot not in ('A', 'B'):
        return jsonify({'ok': False, 'mesaj': 'Eksik parametre'}), 400
    if not bas:
        return jsonify({'ok': True, 'cakisma': False, 'cakisan_planlar': []})
    con = get_conn()
    try:
        q = """
            SELECT id, sip_no, mamul_skod, renk_adi,
                   enj_plan_baslangic, enj_plan_bitis
            FROM uretim_model_plan
            WHERE aktif=1
              AND enj_makine_id=? AND enj_istasyon_no=? AND enj_slot=?
              AND enj_plan_baslangic IS NOT NULL
        """
        params = [makine_id, istasyon_no, slot]
        if hariç_plan_id:
            q += ' AND id <> ?'
            params.append(hariç_plan_id)
        rows = con.execute(q, params).fetchall()
        bit_dt = datetime.strptime(bit[:10], '%Y-%m-%d').date() if bit else None
        bas_dt = datetime.strptime(bas[:10], '%Y-%m-%d').date()
        cakisan = []
        for r in rows:
            r_bas = r['enj_plan_baslangic']
            r_bit = r['enj_plan_bitis']
            try:
                rb = datetime.strptime(r_bas[:10], '%Y-%m-%d').date()
                re = datetime.strptime(r_bit[:10], '%Y-%m-%d').date() if r_bit else rb
                sorgu_bit = bit_dt if bit_dt else bas_dt
                if not (sorgu_bit < rb or bas_dt > re):
                    cakisan.append(dict(r))
            except (ValueError, TypeError):
                continue
        return jsonify({'ok': True, 'cakisma': len(cakisan) > 0, 'cakisan_planlar': cakisan})
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200]}), 500
    finally:
        con.close()


# ─── MEVCUT ROUTES ───────────────────────────────────────────────────────────

@uretim_plan_bp.route('/gorsel/<path:skod>', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def gorsel_skod(skod):
    try:
        from modules.common import korgun as kk
        con = kk._baglan()
        try:
            yol = stok_gorsel_yolu(con, skod)
        finally:
            con.close()
    except Exception:
        abort(404)
    if not yol or not os.path.isfile(yol):
        abort(404)
    resp = send_file(yol, conditional=True)
    resp.headers['Cache-Control'] = 'private, max-age=3600'
    return resp
