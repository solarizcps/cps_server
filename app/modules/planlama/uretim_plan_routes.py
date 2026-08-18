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
        msg = str(e)
        if 'zaten planlı' in msg or msg.startswith('CONFLICT'):
            code = 409
            payload = {'ok': False, 'mesaj': msg, 'errors': [msg]}
            if msg.startswith('CONFLICT'):
                con = get_conn()
                try:
                    from modules.planlama.enj_kapasite_motor import (
                        _check_conflicts, _parse_dt,
                    )
                    from modules.planlama.enj_plan_availability_service import (
                        enrich_conflict_payload,
                    )
                    mid = body.get('enj_makine_id')
                    slot = (body.get('enj_slot') or 'A').upper()
                    ist = body.get('enj_istasyonlar') or []
                    bas = body.get('enj_plan_baslangic')
                    bit = body.get('enj_plan_bitis')
                    if mid and ist and bas:
                        try:
                            bas_dt = _parse_dt(bas)
                            bit_dt = _parse_dt(bit) if bit else bas_dt
                            conflicts = _check_conflicts(
                                con, int(mid), slot,
                                [int(x) for x in ist], bas_dt, bit_dt,
                            )
                            if conflicts:
                                payload['conflict_detail'] = enrich_conflict_payload(
                                    con, int(mid), slot, ist, conflicts,
                                    calisma_modu=(body.get('enj_calisma_modu') or 'GUNDUZ_GECE').upper(),
                                    hafta_sonu=(body.get('enj_hafta_sonu_calisma') or 'HAYIR').upper(),
                                    hs_vardiya=body.get('enj_hafta_sonu_vardiya'),
                                    from_dt=bas_dt,
                                )
                        except (ValueError, TypeError):
                            pass
                finally:
                    con.close()
            return jsonify(payload), code
        return jsonify({'ok': False, 'mesaj': msg, 'errors': [msg]}), 400
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200]}), 500

    calendar_ready = False
    calendar_url = None
    if row and row.get('enj_makine_id') and row.get('enj_plan_baslangic'):
        con = get_conn()
        try:
            mk = con.execute(
                'SELECT kod FROM enj_makine WHERE id=?', (int(row['enj_makine_id']),),
            ).fetchone()
            if mk:
                calendar_ready = True
                anchor = (row.get('enj_plan_baslangic') or '')[:10]
                calendar_url = (
                    f'/planlama/enjeksiyon-plan/?makine={mk["kod"]}'
                    f'&view=bu_hafta&anchor={anchor}'
                )
        finally:
            con.close()
    return jsonify({
        'ok': True,
        'plan': row,
        'plan_id': row.get('id') if row else None,
        'calendar_ready': calendar_ready,
        'calendar_url': calendar_url,
    })


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

@uretim_plan_bp.route('/api/enj-kapasite', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def api_enj_kapasite_read():
    """READ-ONLY enjeksiyon kapasite snapshot — Plan Oluştur read-model."""
    makine_id = request.args.get('makine_id', type=int)
    tarih = (request.args.get('tarih') or '').strip() or None
    vardiya = (request.args.get('vardiya') or '').strip() or None
    if vardiya and vardiya not in ('gunduz', 'gece', 'mesai'):
        return jsonify({'ok': False, 'mesaj': 'Geçersiz vardiya'}), 400
    ref_days = request.args.get('days', default=90, type=int)
    con = get_conn()
    try:
        from modules.planlama.enj_kapasite_read_service import build_kapasite_snapshot
        payload = build_kapasite_snapshot(
            con,
            makine_id=makine_id,
            tarih=tarih,
            vardiya=vardiya,
            ref_days=ref_days,
        )
        return jsonify({'ok': True, **payload})
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200]}), 500
    finally:
        con.close()


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

        hist_ag = con.execute("""
            SELECT s.aktif_goz_sayisi
            FROM enj_ab_setup s
            WHERE s.kalip_id = ? AND COALESCE(s.aktif_goz_sayisi, 0) > 0
            ORDER BY s.baslangic_zamani DESC
            LIMIT 1
        """, (kalip_id,)).fetchone()
        ag = int(hist_ag['aktif_goz_sayisi']) if hist_ag else 1

        return jsonify({'ok': True, 'kapasite': {
            'aktif_goz_sayisi': ag,
            'kalip_basi_cift': kbc,
            'tur_cift': ag * kbc if ag and kbc else None,
            'kaynak': 'master+setup_hist',
        }, 'kapasite_eksik': False})
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200]}), 500
    finally:
        con.close()


@uretim_plan_bp.route('/api/enj/hesapla', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def api_enj_hesapla():
    """Canonical kapasite motoru — Plan Oluştur HESAPLA."""
    body = request.get_json(silent=True) or {}
    con = get_conn()
    try:
        from modules.planlama.enj_kapasite_motor import hesapla_kapasite, _parse_dt
        from modules.planlama.enj_plan_availability_service import enrich_conflict_payload
        result = hesapla_kapasite(con, body)
        if result.get('conflict_var') and result.get('conflicts'):
            ist = body.get('istasyonlar') or []
            if body.get('istasyon_no') and not ist:
                ist = [body.get('istasyon_no')]
            from_dt = None
            if body.get('plan_baslangic'):
                try:
                    from_dt = _parse_dt(body['plan_baslangic'])
                except ValueError:
                    from_dt = None
            result['conflict_detail'] = enrich_conflict_payload(
                con,
                int(body.get('makine_id') or 0),
                (body.get('slot') or body.get('taraf') or 'A').upper(),
                ist,
                result['conflicts'],
                calisma_modu=(body.get('calisma_modu') or 'GUNDUZ_GECE').upper(),
                hafta_sonu=(body.get('hafta_sonu_calisma') or 'HAYIR').upper(),
                hs_vardiya=body.get('hafta_sonu_vardiya'),
                from_dt=from_dt,
            )
        return jsonify(result)
    except Exception as e:
        return jsonify({'ok': False, 'hata': str(e)[:200]}), 500
    finally:
        con.close()


@uretim_plan_bp.route('/api/enj/cakisma-kontrol', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def api_enj_cakisma_kontrol():
    """Multi-istasyon çakışma kontrolü — child + legacy."""
    body = request.get_json(silent=True) or {}
    makine_id = body.get('makine_id')
    slot = (body.get('slot') or '').upper()
    bas = body.get('enj_plan_baslangic')
    bit = body.get('enj_plan_bitis')
    hariç_plan_id = body.get('hariç_plan_id')
    istasyonlar = body.get('istasyonlar') or []
    if body.get('istasyon_no') and not istasyonlar:
        istasyonlar = [body.get('istasyon_no')]
    istasyonlar = sorted({int(x) for x in istasyonlar if x is not None})
    if not makine_id or not istasyonlar or slot not in ('A', 'B'):
        return jsonify({'ok': False, 'mesaj': 'makine_id, istasyonlar, slot gerekli'}), 400
    if not bas:
        return jsonify({'ok': True, 'cakisma': False, 'cakisan_planlar': []})
    con = get_conn()
    try:
        from modules.planlama.enj_kapasite_motor import _check_conflicts, _parse_dt
        try:
            bas_dt = _parse_dt(bas)
            bit_dt = _parse_dt(bit) if bit else bas_dt
        except ValueError as e:
            return jsonify({'ok': False, 'mesaj': str(e)}), 400
        conflicts = _check_conflicts(
            con, int(makine_id), slot, istasyonlar, bas_dt, bit_dt,
            haric_plan_id=hariç_plan_id,
        )
        detail = None
        if conflicts:
            from modules.planlama.enj_plan_availability_service import enrich_conflict_payload
            detail = enrich_conflict_payload(
                con, int(makine_id), slot, istasyonlar, conflicts,
                calisma_modu=(body.get('calisma_modu') or 'GUNDUZ_GECE').upper(),
                hafta_sonu=(body.get('hafta_sonu_calisma') or 'HAYIR').upper(),
                hs_vardiya=body.get('hafta_sonu_vardiya'),
                from_dt=bas_dt,
            )
        return jsonify({
            'ok': True,
            'cakisma': len(conflicts) > 0,
            'cakisan_planlar': conflicts,
            'conflict_detail': detail,
        })
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200]}), 500
    finally:
        con.close()


@uretim_plan_bp.route('/api/plan/on-check', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def api_plan_on_check():
    """Adım 3 — tarih seçenekleri doluluk + dönem önerisi."""
    body = request.get_json(silent=True) or {}
    sip_no = body.get('sip_no')
    sip_harinx = body.get('sip_harinx')
    mamul_skod = body.get('mamul_skod')
    rkod = body.get('rkod', 0)
    tarihler = body.get('tarihler') or []
    if not sip_no or not mamul_skod:
        return jsonify({'ok': False, 'mesaj': 'sip_no ve mamul_skod gerekli'}), 400
    con = get_conn()
    try:
        ref = date.today()
        secenekler = []
        for t in tarihler:
            tstr = str(t)[:10]
            try:
                td = datetime.strptime(tstr, '%Y-%m-%d').date()
            except ValueError:
                continue
            oneri_donem = repo.donem_for_date(td, ref)
            dup = repo.check_plan_duplicate(
                con, int(sip_no), int(sip_harinx or 0),
                mamul_skod, int(rkod or 0), oneri_donem,
            )
            secenekler.append({
                'tarih': tstr,
                'oneri_donem': oneri_donem,
                'dolu': dup.get('dolu', False),
                'mesaj': dup.get('mesaj') if dup.get('dolu') else None,
                'plan_id': dup.get('plan_id'),
            })
        return jsonify({'ok': True, 'secenekler': secenekler})
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200]}), 500
    finally:
        con.close()


@uretim_plan_bp.route('/api/enj/ilk-uygun', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def api_enj_ilk_uygun():
    """Seçili istasyonlar için ilk uygun başlangıç — makine bazlı."""
    body = request.get_json(silent=True) or {}
    slot = (body.get('slot') or body.get('taraf') or '').upper()
    istasyonlar = sorted({int(x) for x in (body.get('istasyonlar') or []) if x is not None})
    calisma = (body.get('calisma_modu') or 'GUNDUZ_GECE').upper()
    hs = (body.get('hafta_sonu_calisma') or 'HAYIR').upper()
    hs_v = body.get('hafta_sonu_vardiya')
    if hs == 'HAYIR':
        hs_v = None
    elif hs_v:
        hs_v = str(hs_v).upper()
    makine_ids = body.get('makine_ids') or []
    if body.get('makine_id') and not makine_ids:
        makine_ids = [body.get('makine_id')]
    makine_ids = [int(x) for x in makine_ids if x is not None]
    if not istasyonlar or slot not in ('A', 'B'):
        return jsonify({'ok': False, 'mesaj': 'slot ve istasyonlar gerekli'}), 400
    con = get_conn()
    try:
        from modules.planlama.enj_kapasite_motor import find_first_available_start
        results = []
        onerilen = None
        selected_mid = body.get('selected_makine_id')
        for mid in makine_ids:
            mk = con.execute(
                'SELECT id, kod FROM enj_makine WHERE id=? AND aktif=1', (int(mid),),
            ).fetchone()
            if not mk:
                continue
            try:
                dt = find_first_available_start(
                    con, int(mk['id']), slot, istasyonlar,
                    calisma_modu=calisma, hafta_sonu=hs, hs_vardiya=hs_v,
                )
                fmt = dt.strftime('%Y-%m-%d %H:%M:%S')
                entry = {
                    'makine_id': int(mk['id']),
                    'makine_kod': mk['kod'],
                    'ilk_uygun': fmt,
                    'ilk_uygun_gosterim': dt.strftime('%d.%m.%Y %H:%M'),
                }
                results.append(entry)
                if selected_mid and int(selected_mid) == int(mk['id']):
                    onerilen = fmt
            except RuntimeError:
                results.append({
                    'makine_id': int(mk['id']),
                    'makine_kod': mk['kod'],
                    'ilk_uygun': None,
                    'ilk_uygun_gosterim': '—',
                })
        if not onerilen and results:
            sel = next((r for r in results if r.get('ilk_uygun')), None)
            onerilen = sel['ilk_uygun'] if sel else None
        return jsonify({'ok': True, 'onerilen': onerilen, 'makineler': results})
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200]}), 500
    finally:
        con.close()


@uretim_plan_bp.route('/api/enj/son-hafta-hiz', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def api_enj_son_hafta_hiz():
    """Son 7 takvim günü gerçek çalışan vardiya tur hızı — READ-ONLY referans bilgisi.

    0-tur / üretim yok / çalışılmamış vardiyalar ortalamaya dahil edilmez.
    Değer hesap motoru girdisi değildir; planlamacı için görsel referanstır.
    """
    days = request.args.get('days', default=7, type=int)
    days = max(1, min(days, 30))
    # gunduz: 10h canonical, gece: 14h canonical (enj_kapasite_read_service ile uyumlu)
    CANON_SAAT = {'gunduz': 10, 'gece': 14}
    # En az 1 aktif saat olan vardiyalar dahil edilir (gürültü filtresi)
    MIN_ACTIVE_SAAT = 1
    con = get_conn()
    try:
        makineler_rows = con.execute(
            'SELECT id, kod FROM enj_makine WHERE aktif = 1 ORDER BY sira, kod'
        ).fetchall()
        sonuc = {}
        for mk in makineler_rows:
            mid = int(mk['id'])
            mkod = mk['kod']
            makine_veri = {}
            for slot_col, vd in [('cevrim_a', 'gunduz'), ('cevrim_a', 'gunduz'),
                                  ('cevrim_b', 'gunduz'), ('cevrim_a', 'gece'),
                                  ('cevrim_b', 'gece')]:
                pass  # aşağıda döngü ile
            for vd in ('gunduz', 'gece'):
                for slot_col, slot_lbl in (('cevrim_a', 'A'), ('cevrim_b', 'B')):
                    rows = con.execute(f"""
                        SELECT r.tarih,
                               SUM(h.{slot_col})                              AS shift_tur,
                               SUM(CASE WHEN h.{slot_col} > 0 THEN 1 ELSE 0 END) AS active_saat
                        FROM enj_gunluk_rapor r
                        JOIN enj_saatlik_kayit h ON h.rapor_id = r.id
                        WHERE r.makine_id = ?
                          AND r.vardiya   = ?
                          AND r.tarih    >= date('now', ?)
                        GROUP BY r.id
                        HAVING shift_tur > 0 AND active_saat >= ?
                        ORDER BY r.tarih
                    """, (mid, vd, f'-{days} day', MIN_ACTIVE_SAAT)).fetchall()

                    if not rows:
                        makine_veri.setdefault(vd, {})[slot_lbl] = {
                            'median': None,
                            'avg': None,
                            'min': None,
                            'max': None,
                            'sample': 0,
                            'calisan_vardiya': 0,
                            'calismadi': True,
                        }
                        continue

                    canon = CANON_SAAT[vd]
                    norm_vals = [
                        round(r['shift_tur'] / r['active_saat'] * canon, 1)
                        for r in rows
                    ]
                    n = len(norm_vals)
                    sorted_v = sorted(norm_vals)
                    if n % 2 == 1:
                        med = sorted_v[n // 2]
                    else:
                        med = round((sorted_v[n // 2 - 1] + sorted_v[n // 2]) / 2, 1)

                    makine_veri.setdefault(vd, {})[slot_lbl] = {
                        'median': med,
                        'avg': round(sum(norm_vals) / n, 1),
                        'min': min(norm_vals),
                        'max': max(norm_vals),
                        'sample': n,
                        'calisan_vardiya': n,
                        'calismadi': False,
                    }

            sonuc[mkod] = makine_veri

        return jsonify({'ok': True, 'days': days, 'makineler': sonuc})
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200]}), 500
    finally:
        con.close()


@uretim_plan_bp.route('/api/enj/makine-plan-ozet', methods=['GET'])
@yetki_gerekli('planlama', 'can_view')
def api_enj_makine_plan_ozet():
    """Makine kartları — gelecek plan rezervasyon özeti (READ)."""
    days = request.args.get('days', default=7, type=int)
    anchor_s = (request.args.get('anchor') or '').strip()
    calisma = (request.args.get('calisma_modu') or 'GUNDUZ_GECE').upper()
    hs = (request.args.get('hafta_sonu_calisma') or 'HAYIR').upper()
    hs_v = request.args.get('hafta_sonu_vardiya')
    if hs == 'HAYIR':
        hs_v = None
    con = get_conn()
    try:
        from modules.planlama.enj_kapasite_motor import _parse_dt
        from modules.planlama.enj_plan_availability_service import build_makine_plan_ozet
        anchor = None
        if anchor_s:
            try:
                anchor = _parse_dt(anchor_s + ' 07:00:00' if len(anchor_s) <= 10 else anchor_s)
            except ValueError:
                anchor = None
        makineler = build_makine_plan_ozet(
            con, days=days, anchor=anchor,
            calisma_modu=calisma, hafta_sonu=hs, hs_vardiya=hs_v,
        )
        return jsonify({'ok': True, 'makineler': makineler, 'days': days})
    except Exception as e:
        return jsonify({'ok': False, 'mesaj': str(e)[:200]}), 500
    finally:
        con.close()


@uretim_plan_bp.route('/api/enj/istasyon-plan-durum', methods=['POST'])
@yetki_gerekli('planlama', 'can_view')
def api_enj_istasyon_plan_durum():
    """Seçilen başlangıç anında istasyon plan durumu."""
    body = request.get_json(silent=True) or {}
    makine_id = body.get('makine_id')
    slot = (body.get('slot') or '').upper()
    istasyonlar = sorted({int(x) for x in (body.get('istasyonlar') or []) if x is not None})
    at_dt = body.get('plan_baslangic') or body.get('at')
    if not makine_id or not istasyonlar or slot not in ('A', 'B') or not at_dt:
        return jsonify({'ok': False, 'mesaj': 'makine_id, slot, istasyonlar, plan_baslangic gerekli'}), 400
    con = get_conn()
    try:
        from modules.planlama.enj_plan_availability_service import build_istasyon_plan_durum
        rows = build_istasyon_plan_durum(
            con, int(makine_id), slot, istasyonlar, str(at_dt),
            haric_plan_id=body.get('haric_plan_id'),
        )
        return jsonify({'ok': True, 'istasyonlar': rows})
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
