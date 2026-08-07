# -*- coding: utf-8 -*-
"""Onay Merkezi MVP route kayıtları."""
from __future__ import annotations

from flask import jsonify, render_template, request, session

from modules.auth import kullanici_yetkileri, login_gerekli, yetki_gerekli, yetki_var
from modules.nexgen.onay_merkezi_service import (
    adimlar_getir,
    gecmis_filtre,
    karar_ver,
    liste_filtre,
    talep_getir,
)
from modules.nexgen.onay_satis_adapter import (
    karar_sonrasi_adapter,
    satis_onaya_gonder,
)
from modules.nexgen.onay_satinalma_adapter import (
    satin_onay_senkron,
)
from modules.nexgen.onay_numune_adapter import karar_sonrasi_adapter as numune_karar_sonrasi
from modules.nexgen.onay_tahsilat_adapter import karar_sonrasi_adapter as tahsilat_karar_sonrasi


def register_onay_merkezi_routes(bp, db_fn, kullanici_id_fn):
    @bp.route('/onay-merkezi')
    @login_gerekli
    @yetki_gerekli('onay.merkez.view', 'can_view')
    def onay_merkezi_sayfa():
        return render_template(
            'nexgen/onay_merkezi.html',
            active='nexgen',
            can_karar=yetki_var('onay.merkez.karar', 'can_approve')
            or yetki_var('onay.finans.karar', 'can_approve')
            or yetki_var('onay.satinalma.karar', 'can_approve')
            or yetki_var('onay.yonetim.karar', 'can_approve'),
        )

    @bp.route('/api/onay-merkezi/bekleyen-ozet')
    @login_gerekli
    @yetki_gerekli('onay.merkez.view', 'can_view')
    def api_onay_bekleyen_ozet():
        """Üst bar badge: onay_talep + nexgen_onay MTT federasyonu (source ayrımı zorunlu)."""
        con = db_fn()
        try:
            from modules.nexgen.onay_merkezi_service import _tablo_var
            bekleyen_sayi = 0
            liste_ot = []
            liste_mtt = []

            if _tablo_var(con, 'onay_talep'):
                sayi_row = con.execute(
                    "SELECT COUNT(*) AS n FROM onay_talep "
                    "WHERE aktif=1 AND durum IN ('BEKLIYOR','BEKLETILDI')"
                ).fetchone()
                bekleyen_sayi += int(sayi_row['n'] or 0) if sayi_row else 0
                rows = con.execute(
                    """SELECT id, talep_kod, talep_tipi, cari_id, cari_unvan_snapshot,
                              durum, tutar, para_birimi, talep_tarihi, created_at
                       FROM onay_talep
                       WHERE aktif=1 AND durum IN ('BEKLIYOR','BEKLETILDI')
                       ORDER BY id DESC LIMIT 10"""
                ).fetchall()
                for r in rows:
                    d = dict(r)
                    d['source'] = 'ONAY_TALEP'
                    liste_ot.append(d)

            if _tablo_var(con, 'nexgen_onay'):
                sayi_mtt = con.execute(
                    "SELECT COUNT(*) AS n FROM nexgen_onay "
                    "WHERE durum='ONAY_BEKLIYOR' "
                    "AND kaynak_turu='MUSTERI_TEMSILCISI_TALEP'"
                ).fetchone()
                bekleyen_sayi += int(sayi_mtt['n'] or 0) if sayi_mtt else 0

                if _tablo_var(con, 'nexgen_musteri_temsilcisi_talep'):
                    mtt_rows = con.execute(
                        """
                        SELECT o.id, o.onay_no, o.onay_turu, o.durum, o.created_at,
                               m.talep_no, m.talep_turu, m.cari_id,
                               COALESCE(c.unvan, c.cari_kod, ma.firma_adi, '')
                                   AS cari_unvan_snapshot,
                               COALESCE(sk.AdSoyad, sk.KullaniciAdi, '')
                                   AS talep_eden
                        FROM nexgen_onay o
                        JOIN nexgen_musteri_temsilcisi_talep m
                          ON m.id = o.kaynak_id
                        LEFT JOIN nexgen_cari c ON c.id = m.cari_id
                        LEFT JOIN nexgen_musteri_aday ma
                          ON ma.id = m.musteri_aday_id
                        LEFT JOIN sistem_kullanici sk
                          ON sk.Id = o.olusturan_kullanici_id
                        WHERE o.durum='ONAY_BEKLIYOR'
                          AND o.kaynak_turu='MUSTERI_TEMSILCISI_TALEP'
                        ORDER BY o.id DESC
                        LIMIT 10
                        """
                    ).fetchall()
                    _mtt_tip = {
                        'SIPARIS_TALEBI_ONAY': 'NexGen Sipariş Talebi',
                        'NUMUNE_TALEBI_ONAY': 'NexGen Numune Talebi',
                    }
                    for r in mtt_rows:
                        ot = (r['onay_turu'] or '').upper()
                        liste_mtt.append({
                            'id': int(r['id']),
                            'source': 'MTT',
                            'talep_kod': r['talep_no'] or r['onay_no']
                                or ('ONY-' + str(r['id'])),
                            'talep_tipi': ot,
                            'talep_tipi_etiket': _mtt_tip.get(ot, 'MTT Onayı'),
                            'cari_id': r['cari_id'],
                            'cari_unvan_snapshot': r['cari_unvan_snapshot'] or '—',
                            'durum': 'ONAY_BEKLIYOR',
                            'durum_etiket': 'Onay Bekliyor',
                            'mtt_kod': r['talep_no'] or '',
                            'talep_eden': r['talep_eden'] or '',
                            'talep_tarihi': r['created_at'],
                            'created_at': r['created_at'],
                            'tutar': None,
                            'para_birimi': '',
                        })

            # Her iki namespace üst listede görünsün (tamamı MTT ile ezilmesin)
            liste = liste_ot + liste_mtt
            liste.sort(
                key=lambda x: str(
                    x.get('talep_tarihi') or x.get('created_at') or ''
                ),
                reverse=True,
            )
            liste = liste[:15]
            return jsonify({
                'ok': True,
                'bekleyen_sayi': bekleyen_sayi,
                'liste': liste,
            })
        except Exception as e:
            return jsonify({'ok': False, 'mesaj': str(e)}), 500
        finally:
            con.close()

    @bp.route('/api/onay-merkezi/liste')
    @login_gerekli
    @yetki_gerekli('onay.merkez.view', 'can_view')
    def api_onay_liste():
        tip = (request.args.get('talep_tipi') or '').strip() or None
        con = db_fn()
        try:
            liste = liste_filtre(con, tip)
            return jsonify({'ok': True, 'liste': liste})
        finally:
            con.close()

    @bp.route('/api/onay-merkezi/gecmis')
    @login_gerekli
    @yetki_gerekli('onay.merkez.view', 'can_view')
    def api_onay_gecmis():
        """Karar geçmişi: ONAYLANDI + REDDEDILDI + REVIZYON. aktif filtresi yok."""
        tip = (request.args.get('talep_tipi') or '').strip() or None
        limit = min(int(request.args.get('limit') or 100), 200)
        con = db_fn()
        try:
            liste = gecmis_filtre(con, tip, limit=limit)
            return jsonify({'ok': True, 'liste': liste})
        except Exception as e:
            return jsonify({'ok': False, 'mesaj': str(e)}), 500
        finally:
            con.close()

    @bp.route('/api/onay-merkezi/<int:talep_id>')
    @login_gerekli
    @yetki_gerekli('onay.merkez.view', 'can_view')
    def api_onay_detay(talep_id):
        con = db_fn()
        try:
            t = talep_getir(con, talep_id)
            if not t:
                return jsonify({'ok': False, 'hata': 'Bulunamadı'}), 404
            import json as _json
            snap = {}
            try:
                snap = _json.loads(t.get('snapshot_json') or '{}')
            except Exception:
                pass
            etki = {}
            try:
                etki = _json.loads(t.get('etki_onizleme_json') or '{}')
            except Exception:
                pass
            # Tahsilat: sipariş tarihi ve tutarını canlı join ile ekle
            if t.get('talep_tipi') == 'TAHSILAT_KAYDI':
                sip_id = snap.get('siparis_id')
                if sip_id:
                    try:
                        sr = con.execute(
                            'SELECT olusturma_tarihi FROM nexgen_planlama_siparis WHERE id=?',
                            (int(sip_id),),
                        ).fetchone()
                        if sr:
                            snap['siparis_tarihi'] = (sr['olusturma_tarihi'] or '')[:10] or None
                    except Exception:
                        pass
            return jsonify({
                'ok': True,
                'talep': t,
                'adimlar': adimlar_getir(con, talep_id),
                'snapshot': snap,
                'etki': etki,
            })
        finally:
            con.close()

    @bp.route('/api/onay-merkezi/<int:talep_id>/karar', methods=['POST'])
    @login_gerekli
    def api_onay_karar(talep_id):
        u = session.get('kullanici') or {}
        yk = kullanici_yetkileri(u)
        if not (
            yetki_var('onay.merkez.karar', 'can_approve')
            or yetki_var('onay.finans.karar', 'can_approve')
            or yetki_var('onay.satinalma.karar', 'can_approve')
            or yetki_var('onay.yonetim.karar', 'can_approve')
        ):
            return jsonify({'ok': False, 'hata': 'Karar yetkisi yok.'}), 403

        d = request.get_json(silent=True) or {}
        karar = (d.get('karar') or '').strip().upper()
        notu = (d.get('not') or '').strip()

        con = db_fn()
        try:
            con.execute('BEGIN IMMEDIATE')
            sonuc = karar_ver(
                con, talep_id, kullanici_id_fn(),
                u.get('KullaniciAdi') or '', karar, notu, yk,
            )
            if not sonuc.get('ok'):
                con.rollback()
                return jsonify(sonuc), 400

            talep = talep_getir(con, talep_id)
            if talep and talep['talep_tipi'] == 'SATIS_SIPARISI':
                karar_sonrasi_adapter(con, talep_id, sonuc)
            elif talep and talep['talep_tipi'] == 'NUMUNE_TALEBI':
                numune_karar_sonrasi(con, talep_id, sonuc)
            elif talep and talep['talep_tipi'] == 'TAHSILAT_KAYDI':
                tahsilat_karar_sonrasi(con, talep_id, sonuc)
            elif talep and talep['talep_tipi'] == 'SATIN_ALMA_SIPARISI':
                kid = int(talep['kaynak_id'])
                if sonuc.get('durum') == 'ONAYLANDI' and sonuc.get('tamamlandi'):
                    con.execute(
                        """
                        UPDATE nexgen_satin_siparis
                        SET onay_durumu='ONAYLANDI', onaylayan_id=?, onay_tarihi=datetime('now','localtime')
                        WHERE id=?
                        """,
                        (kullanici_id_fn(), kid),
                    )
                    satin_onay_senkron(con, kid, 'ONAYLANDI', talep_id)
                elif sonuc.get('durum') == 'REDDEDILDI':
                    con.execute(
                        """
                        UPDATE nexgen_satin_siparis SET onay_durumu='REDDEDILDI' WHERE id=?
                        """,
                        (kid,),
                    )
                    satin_onay_senkron(con, kid, 'REDDEDILDI', talep_id)

            con.commit()
            return jsonify(sonuc)
        except Exception as e:
            con.rollback()
            return jsonify({'ok': False, 'hata': str(e)}), 500
        finally:
            con.close()

    @bp.route('/api/pazarlama/siparis/<int:siparis_id>/onaya-gonder', methods=['POST'])
    @login_gerekli
    @yetki_gerekli('nexgen.plan.manage', 'can_manage')
    def api_pazarlama_siparis_onaya_gonder(siparis_id):
        con = db_fn()
        try:
            rev = con.execute(
                """
                SELECT COALESCE(MAX(revizyon_no),0)+1 FROM onay_talep
                WHERE kaynak_modul='nexgen_planlama_siparis' AND kaynak_id=?
                """,
                (siparis_id,),
            ).fetchone()[0]
            con.execute('BEGIN IMMEDIATE')
            r = satis_onaya_gonder(con, siparis_id, kullanici_id_fn(), int(rev or 1))
            if not r.get('ok'):
                con.rollback()
                if r.get('code') == 'DUPLICATE':
                    st = 409
                else:
                    st = int(r.get('status') or 400)
                return jsonify({'ok': False, 'hata': r.get('hata') or 'Onaya gönderilemedi.'}), st
            con.commit()
            return jsonify(r)
        except Exception as e:
            con.rollback()
            return jsonify({'ok': False, 'hata': str(e)}), 500
        finally:
            con.close()
