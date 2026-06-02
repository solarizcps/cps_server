# -*- coding: utf-8 -*-
"""CPS DEV - Grafik Routes (Faz 2a)"""
from flask import (Blueprint, render_template, request, redirect, url_for,
                   session, abort, flash, jsonify)
from functools import wraps

from modules.grafik import queries as qr
from modules.auth import yetki_var, yetki_gerekli, is_superadmin

grafik_bp = Blueprint('grafik', __name__, url_prefix='/grafik')


def _u():
    k = session.get('kullanici')
    return k['KullaniciAdi'] if k else 'sistem'




# ============== PANEL ==============
@grafik_bp.route('/')
def panel():
    if not session.get('kullanici'):
        return redirect(url_for('auth.login', next=request.path))
    if not is_superadmin(session.get('kullanici')) and not (yetki_var('grafik.urun') or yetki_var('grafik.tedarikci')
                                or yetki_var('grafik.numune') or yetki_var('grafik.cin_siparis')):
        abort(403)
    return render_template('grafik/panel.html',
                           kpi=qr.grafik_kpi())


# ============== ÜRÜN ==============
@grafik_bp.route('/urun')
@yetki_gerekli('grafik.urun', 'can_view')
def urun_liste():
    arama = request.args.get('q', '').strip() or None
    kat_id = request.args.get('k', '').strip() or None
    return render_template('grafik/urun_liste.html',
                           urunler=qr.urun_liste(arama=arama, kategori_id=kat_id),
                           kategoriler=qr.kategori_liste(),
                           arama=arama, kat_id=kat_id)


@grafik_bp.route('/urun/yeni', methods=['POST'])
@yetki_gerekli('grafik.urun', 'can_create')
def urun_yeni():
    try:
        uid = qr.urun_ekle(
            kod=request.form.get('Kod', '').strip(),
            ad=request.form.get('Ad', '').strip(),
            kategori_id=request.form.get('KategoriId'),
            aciklama=request.form.get('Aciklama', '').strip() or None,
            kullanici=_u(),
        )
        flash('Ürün eklendi.', 'ok')
        return redirect(url_for('grafik.urun_detay', urun_id=uid))
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.urun_liste'))


@grafik_bp.route('/urun/<int:urun_id>')
@yetki_gerekli('grafik.urun', 'can_view')
def urun_detay(urun_id):
    urun = qr.urun_tek(urun_id)
    if not urun:
        abort(404)
    from modules import belge as belge_srv
    return render_template('grafik/urun_detay.html',
                           urun=urun,
                           varyantlar=qr.varyant_liste(urun_id),
                           kategoriler=qr.kategori_liste(),
                           belgeler=belge_srv.belge_liste('grafik', 'urun', urun_id),
                           belge_tipleri=belge_srv.BELGE_TIPLERI)


@grafik_bp.route('/urun/<int:urun_id>/guncelle', methods=['POST'])
@yetki_gerekli('grafik.urun', 'can_update')
def urun_guncelle(urun_id):
    try:
        qr.urun_guncelle(
            urun_id=urun_id,
            kod=request.form.get('Kod', '').strip(),
            ad=request.form.get('Ad', '').strip(),
            kategori_id=request.form.get('KategoriId'),
            aciklama=request.form.get('Aciklama', '').strip() or None,
            kullanici=_u(),
        )
        flash('Güncellendi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.urun_detay', urun_id=urun_id))


@grafik_bp.route('/urun/<int:urun_id>/sil', methods=['POST'])
@yetki_gerekli('grafik.urun', 'can_delete')
def urun_sil(urun_id):
    qr.urun_sil(urun_id, kullanici=_u())
    flash('Ürün silindi.', 'ok')
    return redirect(url_for('grafik.urun_liste'))


# ============== VARYANT ==============
@grafik_bp.route('/urun/<int:urun_id>/varyant/yeni', methods=['POST'])
@yetki_gerekli('grafik.urun', 'can_create')
def varyant_yeni(urun_id):
    try:
        qr.varyant_ekle(
            urun_id=urun_id,
            kod=request.form.get('Kod', '').strip() or None,
            renk_ad=request.form.get('RenkAd', '').strip(),
            renk_hex=request.form.get('RenkHex', '').strip() or None,
            beden=request.form.get('Beden', '').strip() or None,
            stok_kod=request.form.get('StokKod', '').strip() or None,
            kullanici=_u(),
        )
        flash('Varyant eklendi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.urun_detay', urun_id=urun_id))


@grafik_bp.route('/urun/varyant/<int:varyant_id>/sil', methods=['POST'])
@yetki_gerekli('grafik.urun', 'can_delete')
def varyant_sil(varyant_id):
    v = qr.varyant_tek(varyant_id)
    qr.varyant_sil(varyant_id, kullanici=_u())
    flash('Varyant silindi.', 'ok')
    return redirect(url_for('grafik.urun_detay', urun_id=v['UrunId']) if v else url_for('grafik.urun_liste'))


# ============== KATEGORİ ==============
@grafik_bp.route('/kategori')
@yetki_gerekli('grafik.urun', 'can_view')
def kategori_liste():
    return render_template('grafik/kategori_liste.html',
                           kategoriler=qr.kategori_liste())


@grafik_bp.route('/kategori/yeni', methods=['POST'])
@yetki_gerekli('grafik.urun', 'can_create')
def kategori_yeni():
    try:
        qr.kategori_ekle(
            ad=request.form.get('Ad', '').strip(),
            aciklama=request.form.get('Aciklama', '').strip() or None,
            sira=request.form.get('Sira', 0),
            kullanici=_u(),
        )
        flash('Kategori eklendi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.kategori_liste'))


@grafik_bp.route('/kategori/<int:kat_id>/guncelle', methods=['POST'])
@yetki_gerekli('grafik.urun', 'can_update')
def kategori_guncelle(kat_id):
    try:
        qr.kategori_guncelle(
            kat_id=kat_id,
            ad=request.form.get('Ad', '').strip(),
            aciklama=request.form.get('Aciklama', '').strip() or None,
            sira=request.form.get('Sira', 0),
            kullanici=_u(),
        )
        flash('Kategori güncellendi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.kategori_liste'))


@grafik_bp.route('/kategori/<int:kat_id>/sil', methods=['POST'])
@yetki_gerekli('grafik.urun', 'can_delete')
def kategori_sil(kat_id):
    try:
        qr.kategori_sil(kat_id, kullanici=_u())
        flash('Kategori silindi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.kategori_liste'))


# ============== TEDARİKÇİ ==============
@grafik_bp.route('/tedarikci')
@yetki_gerekli('grafik.tedarikci', 'can_view')
def tedarikci_liste():
    arama = request.args.get('q', '').strip() or None
    ulke = request.args.get('u', '').strip() or None
    return render_template('grafik/tedarikci_liste.html',
                           tedarikciler=qr.tedarikci_liste(arama=arama, ulke=ulke),
                           arama=arama, ulke=ulke)


@grafik_bp.route('/tedarikci/yeni', methods=['POST'])
@yetki_gerekli('grafik.tedarikci', 'can_create')
def tedarikci_yeni():
    try:
        tid = qr.tedarikci_ekle({
            'Kod':         request.form.get('Kod', '').strip(),
            'Ad':          request.form.get('Ad', '').strip(),
            'Sehir':       request.form.get('Sehir', '').strip() or None,
            'Ulke':        request.form.get('Ulke', '').strip() or 'Çin',
            'Iletisim':    request.form.get('Iletisim', '').strip() or None,
            'Email':       request.form.get('Email', '').strip() or None,
            'WhatsApp':    request.form.get('WhatsApp', '').strip() or None,
            'WeChat':      request.form.get('WeChat', '').strip() or None,
            'NakliyeTipi': request.form.get('NakliyeTipi', 'FOB'),
            'VadeGun':     request.form.get('VadeGun', 0),
            'Notlar':      request.form.get('Notlar', '').strip() or None,
        }, kullanici=_u())
        flash('Tedarikçi eklendi.', 'ok')
        return redirect(url_for('grafik.tedarikci_detay', ted_id=tid))
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.tedarikci_liste'))


@grafik_bp.route('/tedarikci/<int:ted_id>')
@yetki_gerekli('grafik.tedarikci', 'can_view')
def tedarikci_detay(ted_id):
    t = qr.tedarikci_tek(ted_id)
    if not t:
        abort(404)
    from modules import belge as belge_srv
    return render_template('grafik/tedarikci_detay.html',
                           tedarikci=t,
                           belgeler=belge_srv.belge_liste('grafik', 'tedarikci', ted_id),
                           belge_tipleri=belge_srv.BELGE_TIPLERI)


@grafik_bp.route('/tedarikci/<int:ted_id>/guncelle', methods=['POST'])
@yetki_gerekli('grafik.tedarikci', 'can_update')
def tedarikci_guncelle(ted_id):
    try:
        qr.tedarikci_guncelle(ted_id, {
            'Ad':          request.form.get('Ad', '').strip(),
            'Sehir':       request.form.get('Sehir', '').strip() or None,
            'Ulke':        request.form.get('Ulke', '').strip() or 'Çin',
            'Iletisim':    request.form.get('Iletisim', '').strip() or None,
            'Email':       request.form.get('Email', '').strip() or None,
            'WhatsApp':    request.form.get('WhatsApp', '').strip() or None,
            'WeChat':      request.form.get('WeChat', '').strip() or None,
            'NakliyeTipi': request.form.get('NakliyeTipi', 'FOB'),
            'VadeGun':     request.form.get('VadeGun', 0),
            'Notlar':      request.form.get('Notlar', '').strip() or None,
        }, kullanici=_u())
        flash('Güncellendi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.tedarikci_detay', ted_id=ted_id))


@grafik_bp.route('/tedarikci/<int:ted_id>/sil', methods=['POST'])
@yetki_gerekli('grafik.tedarikci', 'can_delete')
def tedarikci_sil(ted_id):
    qr.tedarikci_sil(ted_id, kullanici=_u())
    flash('Tedarikçi silindi.', 'ok')
    return redirect(url_for('grafik.tedarikci_liste'))


# ============================================================
# NUMUNE (Faz 2b)
# ============================================================

@grafik_bp.route('/numune')
@yetki_gerekli('grafik.numune', 'can_view')
def numune_liste():
    arama = request.args.get('q', '').strip() or None
    durum = request.args.get('d', '').strip() or None
    ted_id = request.args.get('t', '').strip() or None
    musteri = request.args.get('m', '').strip() or None
    return render_template('grafik/numune_liste.html',
                           numuneler=qr.numune_liste(arama=arama, durum=durum,
                                                     tedarikci_id=ted_id, musteri_ckod=musteri),
                           tedarikciler=qr.tedarikci_liste(),
                           urunler=qr.urun_liste(),
                           musteriler=qr.musteri_liste_secimlik(),
                           kpi=qr.numune_kpi(),
                           durumlar=qr.NUMUNE_DURUMLARI,
                           arama=arama, durum=durum, ted_id=ted_id, musteri=musteri)


@grafik_bp.route('/numune/yeni', methods=['POST'])
@yetki_gerekli('grafik.numune', 'can_create')
def numune_yeni():
    try:
        nid, no = qr.numune_ekle({
            'Baslik':        request.form.get('Baslik', '').strip(),
            'MusteriCKod':   request.form.get('MusteriCKod'),
            'TedarikciId':   request.form.get('TedarikciId'),
            'UrunId':        request.form.get('UrunId'),
            'TalepTarihi':   request.form.get('TalepTarihi'),
            'BeklenenTarih': request.form.get('BeklenenTarih'),
            'Notlar':        request.form.get('Notlar', '').strip() or None,
        }, kullanici=_u())
        flash(f'Numune açıldı: {no}', 'ok')
        return redirect(url_for('grafik.numune_detay', numune_id=nid))
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.numune_liste'))


@grafik_bp.route('/numune/<int:numune_id>')
@yetki_gerekli('grafik.numune', 'can_view')
def numune_detay(numune_id):
    n = qr.numune_tek(numune_id)
    if not n:
        abort(404)
    from modules import belge as belge_srv
    return render_template('grafik/numune_detay.html',
                           numune=n,
                           iterasyonlar=qr.numune_iterasyonlar(numune_id),
                           tedarikciler=qr.tedarikci_liste(),
                           urunler=qr.urun_liste(),
                           musteriler=qr.musteri_liste_secimlik(),
                           durumlar=qr.NUMUNE_DURUMLARI,
                           iter_durumlari=qr.ITERASYON_DURUMLARI,
                           dhl_sevkiyatlari=qr.numune_dhl_sevkiyatlari(numune_id),
                           siparisler_bagli=qr.numune_siparisleri(numune_id),
                           belgeler=belge_srv.belge_liste('grafik', 'numune', numune_id),
                           belge_tipleri=belge_srv.BELGE_TIPLERI)


@grafik_bp.route('/numune/<int:numune_id>/guncelle', methods=['POST'])
@yetki_gerekli('grafik.numune', 'can_update')
def numune_guncelle(numune_id):
    try:
        qr.numune_guncelle(numune_id, {
            'Baslik':        request.form.get('Baslik', '').strip(),
            'MusteriCKod':   request.form.get('MusteriCKod'),
            'TedarikciId':   request.form.get('TedarikciId'),
            'UrunId':        request.form.get('UrunId'),
            'BeklenenTarih': request.form.get('BeklenenTarih'),
            'Notlar':        request.form.get('Notlar', '').strip() or None,
        }, kullanici=_u())
        flash('Güncellendi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.numune_detay', numune_id=numune_id))


@grafik_bp.route('/numune/<int:numune_id>/durum', methods=['POST'])
@yetki_gerekli('grafik.numune', 'can_update')
def numune_durum(numune_id):
    try:
        qr.numune_durum_degistir(numune_id,
                                 request.form.get('Durum', '').strip(),
                                 kullanici=_u())
        flash('Durum güncellendi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.numune_detay', numune_id=numune_id))


@grafik_bp.route('/numune/<int:numune_id>/sil', methods=['POST'])
@yetki_gerekli('grafik.numune', 'can_delete')
def numune_sil(numune_id):
    qr.numune_sil(numune_id, kullanici=_u())
    flash('Numune silindi.', 'ok')
    return redirect(url_for('grafik.numune_liste'))


@grafik_bp.route('/numune/<int:numune_id>/iterasyon/yeni', methods=['POST'])
@yetki_gerekli('grafik.numune', 'can_create')
def iterasyon_yeni(numune_id):
    try:
        from datetime import date
        qr.iterasyon_ekle(
            numune_id,
            tarih=request.form.get('Tarih') or date.today().strftime('%Y-%m-%d'),
            durum=request.form.get('Durum', '').strip(),
            feedback=request.form.get('Feedback', '').strip() or None,
            kullanici=_u(),
        )
        flash('İterasyon eklendi. Numune durumu otomatik güncellendi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.numune_detay', numune_id=numune_id))


@grafik_bp.route('/numune/iterasyon/<int:iter_id>/sil', methods=['POST'])
@yetki_gerekli('grafik.numune', 'can_delete')
def iterasyon_sil(iter_id):
    nid = qr.iterasyon_sil(iter_id, kullanici=_u())
    flash('İterasyon silindi.', 'ok')
    if nid:
        return redirect(url_for('grafik.numune_detay', numune_id=nid))
    return redirect(url_for('grafik.numune_liste'))



# ============================================================
# BELGE YÜKLEME (ürün / numune / tedarikçi)
# ============================================================
from modules import belge as belge_srv


def _belge_yukle_helper(modul, alt_modul, kayit_id, ref_url):
    """Ortak belge yükleme mantığı."""
    dosya = request.files.get('dosya')
    if not dosya or not dosya.filename:
        flash('Dosya seçilmedi.', 'hata')
        return redirect(ref_url)
    try:
        belge_srv.belge_yukle(
            modul=modul, alt_modul=alt_modul, kayit_id=kayit_id,
            dosya_storage=dosya,
            belge_tipi=request.form.get('belge_tipi') or request.form.get('BelgeTipi', 'DIGER'),
            aciklama=(request.form.get('aciklama') or request.form.get('Aciklama', '')).strip() or None,
            kullanici=_u(),
        )
        flash(f'"{dosya.filename}" yüklendi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    except Exception as e:
        flash(f'Yükleme hatası: {e}', 'hata')
    return redirect(ref_url)


@grafik_bp.route('/urun/<int:urun_id>/belge/yukle', methods=['POST'])
@yetki_gerekli('grafik.urun', 'can_update')
def urun_belge_yukle(urun_id):
    return _belge_yukle_helper('grafik', 'urun', urun_id,
                                url_for('grafik.urun_detay', urun_id=urun_id))


@grafik_bp.route('/numune/<int:numune_id>/belge/yukle', methods=['POST'])
@yetki_gerekli('grafik.numune', 'can_update')
def numune_belge_yukle(numune_id):
    return _belge_yukle_helper('grafik', 'numune', numune_id,
                                url_for('grafik.numune_detay', numune_id=numune_id))


@grafik_bp.route('/tedarikci/<int:ted_id>/belge/yukle', methods=['POST'])
@yetki_gerekli('grafik.tedarikci', 'can_update')
def tedarikci_belge_yukle(ted_id):
    return _belge_yukle_helper('grafik', 'tedarikci', ted_id,
                                url_for('grafik.tedarikci_detay', ted_id=ted_id))


@grafik_bp.route('/belge/<int:belge_id>/sil', methods=['POST'])
def grafik_belge_sil(belge_id):
    if not session.get('kullanici'):
        return redirect(url_for('auth.login'))
    b = belge_srv.belge_tek(belge_id)
    if not b:
        abort(404)
    # Kaynak modülde düzenleme yetkisi varsa silebilir
    yetki_kod = f"{b['Modul']}.{b['AltModul']}" if b['AltModul'] else b['Modul']
    if not is_superadmin(session.get('kullanici')) and not yetki_var(yetki_kod):
        abort(403)
    belge_srv.belge_sil(belge_id, kullanici=_u())
    flash('Belge silindi.', 'ok')

    # Yönlendirme: hangi modül/kayıt için yüklenmişse oraya dön
    if b['Modul'] == 'grafik':
        if b['AltModul'] == 'urun':
            return redirect(url_for('grafik.urun_detay', urun_id=b['KayitId']))
        if b['AltModul'] == 'numune':
            return redirect(url_for('grafik.numune_detay', numune_id=b['KayitId']))
        if b['AltModul'] == 'tedarikci':
            return redirect(url_for('grafik.tedarikci_detay', ted_id=b['KayitId']))
    return redirect(request.referrer or url_for('grafik.panel'))


# ============================================================
# ÇİN SİPARİŞ (Faz 2b)
# ============================================================

@grafik_bp.route('/siparis')
@yetki_gerekli('grafik.cin_siparis', 'can_view')
def siparis_liste():
    arama = request.args.get('q', '').strip() or None
    durum = request.args.get('d', '').strip() or None
    ted_id = request.args.get('t', '').strip() or None
    musteri = request.args.get('m', '').strip() or None
    return render_template('grafik/siparis_liste.html',
                           siparisler=qr.siparis_liste(arama=arama, durum=durum,
                                                        tedarikci_id=ted_id, musteri_ckod=musteri),
                           tedarikciler=qr.tedarikci_liste(),
                           musteriler=qr.musteri_liste_secimlik(),
                           numuneler_onayli=qr.numune_onayli_secimlik(),
                           kpi=qr.siparis_kpi(),
                           durumlar=qr.SIPARIS_DURUMLARI,
                           arama=arama, durum=durum, ted_id=ted_id, musteri=musteri,
                           fiyat_gor=is_superadmin(session.get('kullanici')) or yetki_var('grafik.cin_siparis.fiyat'))


@grafik_bp.route('/siparis/yeni', methods=['POST'])
@yetki_gerekli('grafik.cin_siparis', 'can_create')
def siparis_yeni():
    try:
        sid, no = qr.siparis_ekle({
            'TedarikciId':         request.form.get('TedarikciId'),
            'KaynakNumuneId':      request.form.get('KaynakNumuneId'),
            'MusteriCKod':         request.form.get('MusteriCKod'),
            'SiparisTarihi':       request.form.get('SiparisTarihi'),
            'BeklenenCikisTarihi': request.form.get('BeklenenCikisTarihi'),
            'Notlar':              request.form.get('Notlar', '').strip() or None,
        }, kullanici=_u())
        flash(f'Sipariş taslağı açıldı: {no}', 'ok')
        return redirect(url_for('grafik.siparis_detay', siparis_id=sid))
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.siparis_liste'))


@grafik_bp.route('/siparis/<int:siparis_id>')
@yetki_gerekli('grafik.cin_siparis', 'can_view')
def siparis_detay(siparis_id):
    s = qr.siparis_tek(siparis_id)
    if not s:
        abort(404)
    from modules import belge as belge_srv
    # Parça 8a: CIN_IMPORT_KONTROL için ön koşul kontrolü
    kontrol_onkosullar = []
    kontrol_tumu_ok = False
    if s['Durum'] == 'CIN_IMPORT_KONTROL':
        try:
            from modules.finans import cin_ofis_queries as _cof_qr
            kontrol_onkosullar, kontrol_tumu_ok = _cof_qr.kontrol_onkosullar(siparis_id)
        except Exception:
            pass
    k = session.get('kullanici') or {}
    yonetim_mi = k.get('RolAd') == 'Yönetim' or k.get('KullaniciAdi') == 'admin'
    return render_template('grafik/siparis_detay.html',
                           siparis=s,
                           kalemler=qr.siparis_kalemler(siparis_id),
                           tedarikciler=qr.tedarikci_liste(),
                           musteriler=qr.musteri_liste_secimlik(),
                           numuneler_onayli=qr.numune_onayli_secimlik(),
                           varyantlar=qr.varyant_secimlik(),
                           durumlar=qr.SIPARIS_DURUMLARI,
                           cari_ozet=qr.siparis_cari_ozet(siparis_id),
                           akis=qr.siparis_akis(siparis_id),
                           sevkiyatlar=qr.siparis_sevkiyatlar(siparis_id),
                           sevkiyat_ozet=qr.siparis_sevkiyat_ozet(siparis_id),
                           belgeler=belge_srv.belge_liste('grafik', 'cin_siparis', siparis_id),
                           belge_tipleri=belge_srv.BELGE_TIPLERI,
                           kontrol_onkosullar=kontrol_onkosullar,
                           kontrol_onkosullar_tumu_ok=kontrol_tumu_ok,
                           yonetim_mi=yonetim_mi,
                           fiyat_gor=is_superadmin(session.get('kullanici')) or yetki_var('grafik.cin_siparis.fiyat'))


@grafik_bp.route('/siparis/<int:siparis_id>/guncelle', methods=['POST'])
@yetki_gerekli('grafik.cin_siparis', 'can_update')
def siparis_guncelle(siparis_id):
    try:
        qr.siparis_guncelle(siparis_id, {
            'TedarikciId':         request.form.get('TedarikciId'),
            'KaynakNumuneId':      request.form.get('KaynakNumuneId'),
            'MusteriCKod':         request.form.get('MusteriCKod'),
            'BeklenenCikisTarihi': request.form.get('BeklenenCikisTarihi'),
            'Notlar':              request.form.get('Notlar', '').strip() or None,
        }, kullanici=_u())
        flash('Güncellendi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.siparis_detay', siparis_id=siparis_id))


@grafik_bp.route('/siparis/<int:siparis_id>/kalem/yeni', methods=['POST'])
@yetki_gerekli('grafik.cin_siparis', 'can_create')
def kalem_yeni(siparis_id):
    try:
        qr.kalem_ekle(siparis_id, {
            'VaryantId':  request.form.get('VaryantId'),
            'Aciklama':   request.form.get('Aciklama', '').strip() or None,
            'Miktar':     request.form.get('Miktar'),
            'BirimFiyat': request.form.get('BirimFiyat'),
            'CiftSayi':   request.form.get('CiftSayi'),
            'AgirlikKg':  request.form.get('AgirlikKg'),
            'HacimM3':    request.form.get('HacimM3'),
        }, kullanici=_u())
        flash('Kalem eklendi, toplam güncellendi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.siparis_detay', siparis_id=siparis_id))


@grafik_bp.route('/siparis/kalem/<int:kalem_id>/sil', methods=['POST'])
@yetki_gerekli('grafik.cin_siparis', 'can_delete')
def kalem_sil(kalem_id):
    try:
        sid = qr.kalem_sil(kalem_id, kullanici=_u())
        flash('Kalem silindi.', 'ok')
        if sid:
            return redirect(url_for('grafik.siparis_detay', siparis_id=sid))
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.siparis_liste'))


@grafik_bp.route('/siparis/<int:siparis_id>/onayla', methods=['POST'])
@yetki_gerekli('grafik.cin_siparis.onayla', 'can_update')
def siparis_onayla(siparis_id):
    try:
        anlasma_id = qr.siparis_onayla(siparis_id, kullanici=_u())
        flash(f'Sipariş onaylandı. Otomatik finans anlaşması #{anlasma_id} oluşturuldu.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.siparis_detay', siparis_id=siparis_id))


@grafik_bp.route('/siparis/<int:siparis_id>/durum', methods=['POST'])
@yetki_gerekli('grafik.cin_siparis', 'can_update')
def siparis_durum(siparis_id):
    try:
        qr.siparis_durum_degistir(siparis_id,
                                   request.form.get('Durum', '').strip(),
                                   kullanici=_u())
        flash('Durum güncellendi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.siparis_detay', siparis_id=siparis_id))


@grafik_bp.route('/siparis/<int:siparis_id>/sil', methods=['POST'])
@yetki_gerekli('grafik.cin_siparis', 'can_delete')
def siparis_sil(siparis_id):
    try:
        qr.siparis_sil(siparis_id, kullanici=_u())
        flash('Sipariş silindi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.siparis_liste'))


@grafik_bp.route('/siparis/<int:siparis_id>/belge/yukle', methods=['POST'])
@yetki_gerekli('grafik.cin_siparis', 'can_update')
def siparis_belge_yukle(siparis_id):
    from modules import belge as belge_srv
    try:
        belge_srv.belge_yukle(
            modul='grafik', alt_modul='cin_siparis', kayit_id=siparis_id,
            dosya_storage=request.files.get('dosya'),
            belge_tipi=request.form.get('belge_tipi', 'PROFORMA'),
            aciklama=request.form.get('aciklama', '').strip() or None,
            kullanici=_u(),
        )
        flash('Belge yüklendi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.siparis_detay', siparis_id=siparis_id))


# ============================================================
# SEVKİYAT + MALİYET DAĞITIM (Faz 2b)
# ============================================================

@grafik_bp.route('/sevkiyat')
@yetki_gerekli('grafik.maliyet', 'can_view')
def sevkiyat_liste():
    arama = request.args.get('q', '').strip() or None
    durum = request.args.get('d', '').strip() or None
    nakliye = request.args.get('n', '').strip() or None
    # Numuneleri de DHL sevkiyat için göster
    from db import q as _q
    numuneler_aktif = _q("""SELECT Id, NumuneNo, Baslik FROM grafik_numune
                            WHERE Durum NOT IN ('TAMAMLANDI')
                            ORDER BY NumuneNo DESC""")
    return render_template('grafik/sevkiyat_liste.html',
                           sevkiyatlar=qr.sevkiyat_liste(arama=arama, durum=durum, nakliye=nakliye),
                           siparisler=qr.onaylanmis_siparisler_sevkedilmemis(),
                           numuneler=numuneler_aktif,
                           kpi=qr.sevkiyat_kpi(),
                           durumlar=qr.SEVKIYAT_DURUMLARI,
                           nakliye_tipleri=qr.NAKLIYE_TIPLERI,
                           dagitim_yontemleri=qr.DAGITIM_YONTEMLERI,
                           gonderim_yonleri=qr.GONDERIM_YONLERI,
                           arama=arama, durum=durum, nakliye=nakliye)


@grafik_bp.route('/sevkiyat/yeni', methods=['POST'])
@yetki_gerekli('grafik.maliyet', 'can_create')
def sevkiyat_yeni():
    try:
        svk_id, no = qr.sevkiyat_ekle(dict(request.form), kullanici=_u())
        flash(f'Sevkiyat açıldı: {no}', 'ok')
        return redirect(url_for('grafik.sevkiyat_detay', sevkiyat_id=svk_id))
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.sevkiyat_liste'))


@grafik_bp.route('/sevkiyat/<int:sevkiyat_id>')
@yetki_gerekli('grafik.maliyet', 'can_view')
def sevkiyat_detay(sevkiyat_id):
    s = qr.sevkiyat_tek(sevkiyat_id)
    if not s:
        abort(404)
    from modules import belge as belge_srv
    from db import q
    # Kalemleri getir (dağıtım form için)
    kalemler = []
    if s['SiparisId']:
        kalemler = q("""SELECT k.*, v.RenkAd, v.Beden, v.RenkHex,
                               COALESCE(u.Kod, (SELECT Kod FROM grafik_urun WHERE Id=v.UrunId)) AS UrunKod
                        FROM grafik_cin_siparis_kalem k
                        LEFT JOIN grafik_urun_varyant v ON v.Id = k.VaryantId
                        LEFT JOIN grafik_urun u ON u.Id = k.UrunId
                        WHERE k.SiparisId = ?""", (s['SiparisId'],))
    # K3: Önerilen dağıtım yöntemi
    oneri = qr.onerilen_dagitim_yontemi(s['SiparisId']) if s['SiparisId'] else None
    # K1: Teslim kilidi kontrolü (UI için)
    kullanici_rol = qr._kullanici_rol(_u())
    kilit_aktif = (s['Durum'] == 'TESLIM' and kullanici_rol != 'Yönetim')
    # DHL bağlı numuneler (düzenleme için)
    from db import q as _q
    numuneler_aktif = _q("SELECT Id, NumuneNo, Baslik FROM grafik_numune ORDER BY NumuneNo DESC")
    return render_template('grafik/sevkiyat_detay.html',
                           sevkiyat=s,
                           kalemler=kalemler,
                           numuneler=numuneler_aktif,
                           masraflar=qr.sevkiyat_masraflar(sevkiyat_id),
                           dagitim=qr.sevkiyat_dagitim(sevkiyat_id),
                           durumlar=qr.SEVKIYAT_DURUMLARI,
                           nakliye_tipleri=qr.NAKLIYE_TIPLERI,
                           dagitim_yontemleri=qr.DAGITIM_YONTEMLERI,
                           gonderim_yonleri=qr.GONDERIM_YONLERI,
                           masraf_tipleri=qr.MASRAF_TIPLERI,
                           masraf_grup=qr.MASRAF_GRUP,
                           oneri_yontem=oneri,
                           kilit_aktif=kilit_aktif,
                           akis=qr.sevkiyat_akis(sevkiyat_id),
                           cari_ozet=qr.siparis_cari_ozet(s['SiparisId']) if s['SiparisId'] else None,
                           belgeler=belge_srv.belge_liste('grafik', 'sevkiyat', sevkiyat_id),
                           belge_tipleri=belge_srv.BELGE_TIPLERI,
                           fiyat_gor=is_superadmin(session.get('kullanici')) or yetki_var('grafik.cin_siparis.fiyat'))


@grafik_bp.route('/sevkiyat/<int:sevkiyat_id>/guncelle', methods=['POST'])
@yetki_gerekli('grafik.maliyet', 'can_update')
def sevkiyat_guncelle(sevkiyat_id):
    try:
        qr.sevkiyat_guncelle(sevkiyat_id, dict(request.form), kullanici=_u())
        flash('Güncellendi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.sevkiyat_detay', sevkiyat_id=sevkiyat_id))


@grafik_bp.route('/sevkiyat/<int:sevkiyat_id>/durum', methods=['POST'])
@yetki_gerekli('grafik.maliyet', 'can_update')
def sevkiyat_durum(sevkiyat_id):
    try:
        uyarilar = qr.sevkiyat_durum_degistir(sevkiyat_id,
                                               request.form.get('Durum', '').strip(),
                                               kullanici=_u())
        flash('Durum güncellendi.', 'ok')
        for u in (uyarilar or []):
            flash(f"⚠ {u}", 'uyari')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.sevkiyat_detay', sevkiyat_id=sevkiyat_id))


@grafik_bp.route('/sevkiyat/<int:sevkiyat_id>/sil', methods=['POST'])
@yetki_gerekli('grafik.maliyet', 'can_delete')
def sevkiyat_sil(sevkiyat_id):
    try:
        qr.sevkiyat_sil(sevkiyat_id, kullanici=_u())
        flash('Sevkiyat silindi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.sevkiyat_liste'))


@grafik_bp.route('/sevkiyat/<int:sevkiyat_id>/masraf/yeni', methods=['POST'])
@yetki_gerekli('grafik.maliyet', 'can_create')
def masraf_yeni(sevkiyat_id):
    try:
        qr.masraf_ekle(sevkiyat_id, dict(request.form), kullanici=_u())
        flash('Masraf eklendi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.sevkiyat_detay', sevkiyat_id=sevkiyat_id))


@grafik_bp.route('/sevkiyat/masraf/<int:masraf_id>/sil', methods=['POST'])
@yetki_gerekli('grafik.maliyet', 'can_delete')
def masraf_sil(masraf_id):
    svk_id = None
    try:
        svk_id = qr.masraf_sil(masraf_id, kullanici=_u())
        flash('Masraf silindi. Dağıtım sıfırlandı — yeniden hesaplayın.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
        # Kilit aktifse masrafın sevkiyatını bulup oraya dön
        from db import qone
        m = qone("SELECT SevkiyatId FROM grafik_sevkiyat_masraf WHERE Id=?", (masraf_id,))
        if m:
            svk_id = m['SevkiyatId']
    if svk_id:
        return redirect(url_for('grafik.sevkiyat_detay', sevkiyat_id=svk_id))
    return redirect(url_for('grafik.sevkiyat_liste'))


@grafik_bp.route('/sevkiyat/masraf/<int:masraf_id>/guncelle', methods=['POST'])
@yetki_gerekli('grafik.maliyet', 'can_update')
def masraf_guncelle(masraf_id):
    """Parça 5 / EK-1: Masraf düzenleme.
    Kur snapshot politikası:
    - IslemTarih + ParaBirimi aynıysa eski kur korunur (queries katmanında)
    - Değiştiyse form'dan gelen KurPolitikasi alanına göre: KORU / YENI
      - KORU → mevcut kur DB'den tekrar çekilip aynen yazılır
      - YENI → KurSnapshot boş gönderilir, queries katmanı /yonetim/kur'dan çeker
    """
    svk_id = None
    try:
        veri = dict(request.form)
        # Kur politikası kullanıcı seçimi — "KORU" seçiliyse KurSnapshot'ı eski değerle override
        if veri.get('KurPolitikasi') == 'KORU':
            from db import qone as _qone
            m = _qone("SELECT KurSnapshot FROM grafik_sevkiyat_masraf WHERE Id=?", (masraf_id,))
            if m:
                veri['KurSnapshot'] = str(m['KurSnapshot'])
        elif veri.get('KurPolitikasi') == 'YENI':
            # Boş bırak — queries katmanı kur_guncel'den alır
            veri['KurSnapshot'] = ''
        svk_id = qr.masraf_guncelle(masraf_id, veri, kullanici=_u())
        flash('Masraf güncellendi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
        from db import qone as _qone
        m = _qone("SELECT SevkiyatId FROM grafik_sevkiyat_masraf WHERE Id=?", (masraf_id,))
        if m:
            svk_id = m['SevkiyatId']
    if svk_id:
        return redirect(url_for('grafik.sevkiyat_detay', sevkiyat_id=svk_id))
    return redirect(url_for('grafik.sevkiyat_liste'))


@grafik_bp.route('/sevkiyat/<int:sevkiyat_id>/dagitim/hesapla', methods=['POST'])
@yetki_gerekli('grafik.maliyet', 'can_update')
def dagitim_hesapla(sevkiyat_id):
    try:
        # MANUEL yöntemse oranları topla
        manuel = None
        s = qr.sevkiyat_tek(sevkiyat_id)
        if s and s['DagitimYontemi'] == 'MANUEL':
            manuel = {}
            for key, val in request.form.items():
                if key.startswith('oran_'):
                    kid = key.replace('oran_', '')
                    manuel[kid] = val
        sayi = qr.dagitim_hesapla(sevkiyat_id, kullanici=_u(), manuel_oranlar=manuel)
        flash(f'Dağıtım hesaplandı: {sayi} kalem.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.sevkiyat_detay', sevkiyat_id=sevkiyat_id))


@grafik_bp.route('/sevkiyat/<int:sevkiyat_id>/belge/yukle', methods=['POST'])
@yetki_gerekli('grafik.maliyet', 'can_update')
def sevkiyat_belge_yukle(sevkiyat_id):
    from modules import belge as belge_srv
    try:
        belge_srv.belge_yukle(
            modul='grafik', alt_modul='sevkiyat', kayit_id=sevkiyat_id,
            dosya_storage=request.files.get('dosya'),
            belge_tipi=request.form.get('belge_tipi', 'BEYANNAME'),
            aciklama=request.form.get('aciklama', '').strip() or None,
            kullanici=_u(),
        )
        flash('Belge yüklendi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.sevkiyat_detay', sevkiyat_id=sevkiyat_id))


# ============================================================
# FİYAT TEKLİFİ (Parça 2)
# ============================================================

@grafik_bp.route('/teklif')
@yetki_gerekli('grafik.cin_siparis', 'can_view')
def teklif_liste():
    arama = request.args.get('q', '').strip() or None
    durum = request.args.get('d', '').strip() or None
    ulke  = request.args.get('u', '').strip() or None
    return render_template('grafik/teklif_liste.html',
                           teklifler=qr.teklif_liste(arama=arama, durum=durum, ulke=ulke),
                           kpi=qr.teklif_kpi(),
                           tedarikciler=qr.tedarikci_liste(),
                           musteriler=qr.musteri_liste_secimlik(),
                           durumlar=qr.TEKLIF_DURUMLARI,
                           ulke_kodlari=qr.ULKE_KODLARI,
                           arama=arama, durum=durum, ulke=ulke)


@grafik_bp.route('/teklif/yeni', methods=['POST'])
@yetki_gerekli('grafik.cin_siparis', 'can_create')
def teklif_yeni():
    try:
        tid, no = qr.teklif_ekle(dict(request.form), kullanici=_u())
        flash(f'Teklif alındı: {no} (kur sabitlendi)', 'ok')
        return redirect(url_for('grafik.teklif_detay', teklif_id=tid))
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.teklif_liste'))


@grafik_bp.route('/teklif/<int:teklif_id>')
@yetki_gerekli('grafik.cin_siparis', 'can_view')
def teklif_detay(teklif_id):
    t = qr.teklif_tek(teklif_id)
    if not t:
        abort(404)
    return render_template('grafik/teklif_detay.html',
                           teklif=t,
                           tedarikciler=qr.tedarikci_liste(),
                           musteriler=qr.musteri_liste_secimlik(),
                           durumlar=qr.TEKLIF_DURUMLARI,
                           ulke_kodlari=qr.ULKE_KODLARI)


@grafik_bp.route('/teklif/<int:teklif_id>/guncelle', methods=['POST'])
@yetki_gerekli('grafik.cin_siparis', 'can_update')
def teklif_guncelle(teklif_id):
    try:
        qr.teklif_guncelle(teklif_id, dict(request.form), kullanici=_u())
        flash('Güncellendi. (Kur değişmez — sabit snapshot)', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.teklif_detay', teklif_id=teklif_id))


@grafik_bp.route('/teklif/<int:teklif_id>/durum', methods=['POST'])
@yetki_gerekli('grafik.cin_siparis', 'can_update')
def teklif_durum(teklif_id):
    try:
        qr.teklif_durum_degistir(teklif_id,
                                  request.form.get('Durum', '').strip(),
                                  kullanici=_u())
        flash('Durum güncellendi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.teklif_detay', teklif_id=teklif_id))


@grafik_bp.route('/teklif/<int:teklif_id>/siparise-donustur', methods=['POST'])
@yetki_gerekli('grafik.cin_siparis', 'can_create')
def teklif_donustur(teklif_id):
    try:
        sid, sno = qr.teklif_siparise_donustur(teklif_id, kullanici=_u())
        flash(f'Teklif siparişe çevrildi: {sno}. Kur snapshot aynen taşındı.', 'ok')
        return redirect(url_for('grafik.siparis_detay', siparis_id=sid))
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.teklif_detay', teklif_id=teklif_id))


@grafik_bp.route('/teklif/<int:teklif_id>/sil', methods=['POST'])
@yetki_gerekli('grafik.cin_siparis', 'can_delete')
def teklif_sil(teklif_id):
    try:
        qr.teklif_sil(teklif_id, kullanici=_u())
        flash('Teklif silindi.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    return redirect(url_for('grafik.teklif_liste'))


# ============================================================
# PARÇA 8a: ÇİN IMPORT — Sipariş Kontrol Aksiyonları (Yönetim)
# ============================================================
from modules.finans import cin_ofis_queries as _cof_qr


def _yonetim_mi():
    k = session.get('kullanici') or {}
    return k.get('RolAd') == 'Yönetim' or k.get('KullaniciAdi') == 'admin'


@grafik_bp.route('/siparis/<int:sid>/kontrol-tamamla', methods=['POST'])
@yetki_gerekli('grafik.cin_siparis.onayla', 'can_update')
def siparis_kontrol_tamamla(sid):
    if not _yonetim_mi():
        abort(403)
    try:
        _cof_qr.kontrol_tamamla(sid, kullanici=_u())
        flash('✓ Sipariş onaylandı (Durum: ONAYLANDI).', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    except Exception as e:
        import logging, traceback
        logging.error(f'Kontrol tamamla hatası sid={sid}: {e}\n{traceback.format_exc()}')
        flash(f'Sistem hatası: işlem tamamlanamadı. Detay: {str(e)[:120]}', 'hata')
    return redirect(url_for('grafik.siparis_detay', siparis_id=sid))


@grafik_bp.route('/siparis/<int:sid>/kontrol-reddet', methods=['POST'])
@yetki_gerekli('grafik.cin_siparis.onayla', 'can_update')
def siparis_kontrol_reddet(sid):
    if not _yonetim_mi():
        abort(403)
    try:
        _cof_qr.kontrol_reddet(sid, request.form.get('sebep') or '', kullanici=_u())
        flash('Sipariş reddedildi ve IPTAL durumuna alındı.', 'ok')
    except ValueError as e:
        flash(str(e), 'hata')
    except Exception as e:
        import logging, traceback
        logging.error(f'Kontrol reddet hatası sid={sid}: {e}\n{traceback.format_exc()}')
        flash(f'Sistem hatası: reddetme yapılamadı. Detay: {str(e)[:120]}', 'hata')
    return redirect(url_for('grafik.siparis_detay', siparis_id=sid))


@grafik_bp.route('/siparis/<int:sid>/kur-override', methods=['POST'])
@yetki_gerekli('grafik.cin_siparis.kur_override', 'can_update')
def siparis_kur_override_route(sid):
    if not _yonetim_mi():
        abort(403)
    try:
        yeni_kur = float(request.form.get('yeni_kur') or 0)
        gerekce = request.form.get('gerekce') or ''
        _cof_qr.siparis_kur_override(sid, yeni_kur, gerekce, kullanici=_u())
        flash('✓ Sipariş kuru güncellendi (audit log düştü).', 'ok')
    except (ValueError, TypeError) as e:
        flash(str(e), 'hata')
    except Exception as e:
        import logging, traceback
        logging.error(f'Kur override hatası sid={sid}: {e}\n{traceback.format_exc()}')
        flash(f'Sistem hatası: kur güncellenemedi. Detay: {str(e)[:120]}', 'hata')
    return redirect(url_for('grafik.siparis_detay', siparis_id=sid))
