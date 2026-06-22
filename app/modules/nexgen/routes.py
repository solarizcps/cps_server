# -*- coding: utf-8 -*-
"""
SOLARIZ CPS — NexGen Hammadde Yönetimi
=======================================
FAZ-1A : Modül iskeleti, menü, yetki
FAZ-1B : Stok Kart Master + Hareket Motoru altyapısı
FAZ-2  : Satın Alma Merkezi — Tedarikçi CRUD + Sipariş akışı
FAZ-2.6: Haftalık Fiyat Geçmişi — Excel import, preview/onay akışı
FAZ-3A : Depo Mal Kabul — GIRIS hareketi Depo yetkisiyle

Yetki kodları:
  nexgen.view                — modül geneli görüntüleme
  nexgen.stok.view           — stok kartları görüntüleme
  nexgen.stok.manage         — stok kartı ekleme/düzenleme
  nexgen.satinalma.view      — satın alma sipariş görüntüleme
  nexgen.satinalma.manage    — yeni sipariş oluşturma/düzenleme
  nexgen.satinalma.approve   — sipariş onaylama (sadece Yönetim)
  nexgen.satinalma.fiyat     — fiyat/kur/maliyet görüntüleme
  nexgen.tedarikci.view      — tedarikçi listesi görüntüleme
  nexgen.tedarikci.manage    — tedarikçi ekleme/düzenleme
  nexgen.fiyat.view          — fiyat geçmişini görüntüleme
  nexgen.fiyat.manage        — fiyat girişi (manuel + Excel)
  nexgen.fiyat.approve       — batch onaylama
  nexgen.fiyat.admin         — fiyat pasife alma (sadece Yönetim)
  nexgen.depo.view           — depo ekranı görüntüleme
  nexgen.depo.giris          — mal kabul + GIRIS hareketi oluşturma

KURAL: nexgen_stok_hareket INSERT SADECE Depo mal kabulünde yapılır (FAZ-3A+).
       Satın Alma, Fiyat, Yönetim ekranları stok hareketi oluşturmaz.
"""

import sqlite3
import os
import io
from datetime import datetime, date

from flask import (
    Blueprint, render_template, abort,
    request, jsonify, session, g,
    Response, redirect, url_for, flash
)
from modules.auth import yetki_gerekli, yetki_var

nexgen_bp = Blueprint('nexgen', __name__, url_prefix='/nexgen')

DB_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'mock_data.db')


# ─────────────────────────────────────────────────────────────
# Yardımcı: DB bağlantısı
# ─────────────────────────────────────────────────────────────
def _db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _kullanici_id():
    u = session.get('kullanici')
    return u.get('Id') if u else None


def _kullanici_ad():
    u = session.get('kullanici')
    return u.get('KullaniciAdi', 'sistem') if u else 'sistem'


# ─────────────────────────────────────────────────────────────
# Stok miktarı hesapla (hareket toplamı)
# ─────────────────────────────────────────────────────────────
def _mevcut_stok(con, kart_id):
    row = con.execute(
        "SELECT COALESCE(SUM(miktar_kg), 0) AS toplam "
        "FROM nexgen_stok_hareket WHERE stok_kart_id=?",
        (kart_id,)
    ).fetchone()
    return round(row["toplam"], 3) if row else 0.0


# ─────────────────────────────────────────────────────────────
# Ana Sayfa
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/')
@yetki_gerekli('nexgen.view', 'can_view')
def index():
    can_yonetim = yetki_var('nexgen.yonetim.manage', 'can_view')
    can_depo    = yetki_var('nexgen.depo.view', 'can_view')
    return render_template('nexgen/index.html', active='nexgen',
                           can_yonetim=can_yonetim,
                           can_depo=can_depo)


# ─────────────────────────────────────────────────────────────
# Stok Kartları — Liste
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/stok-kartlari')
@yetki_gerekli('nexgen.stok.view', 'can_view')
def stok_kartlari():
    con = _db()
    try:
        kartlar_raw = con.execute("""
            SELECT k.id, k.kod, k.ad, k.kategori, k.birim,
                   k.minimum_stok, k.kritik_stok, k.aktif,
                   COALESCE(SUM(h.miktar_kg), 0) AS mevcut_stok
            FROM nexgen_stok_kart k
            LEFT JOIN nexgen_stok_hareket h ON h.stok_kart_id = k.id
            GROUP BY k.id
            ORDER BY k.kategori, k.ad
        """).fetchall()
    finally:
        con.close()

    kartlar = []
    for r in kartlar_raw:
        ms = r["mevcut_stok"]
        mn = r["minimum_stok"]
        kr = r["kritik_stok"]
        if ms <= kr:
            durum = "kritik"
        elif ms <= mn:
            durum = "uyari"
        else:
            durum = "normal"
        kartlar.append({
            "id": r["id"], "kod": r["kod"], "ad": r["ad"],
            "kategori": r["kategori"], "birim": r["birim"],
            "minimum_stok": mn, "kritik_stok": kr,
            "mevcut_stok": ms, "durum": durum,
            "aktif": r["aktif"],
        })

    can_manage = yetki_var('nexgen.stok.manage', 'can_manage') or yetki_var('nexgen.stok.manage', 'can_create')
    return render_template(
        'nexgen/stok_kartlari.html',
        active='nexgen',
        kartlar=kartlar,
        can_manage=can_manage,
    )


# ─────────────────────────────────────────────────────────────
# Stok Kart Detay
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/stok-kartlari/<int:kart_id>')
@yetki_gerekli('nexgen.stok.view', 'can_view')
def stok_detay(kart_id):
    con = _db()
    try:
        kart = con.execute(
            "SELECT * FROM nexgen_stok_kart WHERE id=?", (kart_id,)
        ).fetchone()
        if not kart:
            abort(404)

        mevcut = _mevcut_stok(con, kart_id)

        hareketler_raw = con.execute("""
            SELECT h.id, h.hareket_tipi, h.miktar_kg,
                   h.onceki_stok, h.sonraki_stok,
                   h.aciklama, h.referans_tip, h.referans_id,
                   h.olusturma_tarihi,
                   sk.KullaniciAdi AS olusturan_ad
            FROM nexgen_stok_hareket h
            LEFT JOIN sistem_kullanici sk ON sk.Id = h.olusturan_id
            WHERE h.stok_kart_id = ?
            ORDER BY h.id DESC
            LIMIT 200
        """, (kart_id,)).fetchall()

        # FAZ-2.7: Fiyat geçmişi — sadece nexgen.fiyat.admin yetkisiyle
        # Yönetim / Adem / Alpay / Altan görür; Satın Alma / Depo / Üretim görmez
        can_fiyat_admin = yetki_var('nexgen.fiyat.admin', 'can_view') or \
                          yetki_var('nexgen.fiyat.admin', 'can_manage')
        fiyat_gecmisi_raw = []
        if can_fiyat_admin:
            # nexgen_hammadde_fiyat tablosu FAZ-2.6'da oluşturuldu
            try:
                fiyat_gecmisi_raw = con.execute("""
                    SELECT hf.id, hf.fiyat, hf.para_birimi, hf.kur, hf.fiyat_try,
                           hf.vade_gun, hf.fiyat_tarihi, hf.kaynak, hf.aktif,
                           hf.notlar, hf.olusturma_tarihi,
                           t.ad  AS tedarikci_ad,  t.kod AS tedarikci_kod,
                           sk.KullaniciAdi AS olusturan_ad
                    FROM nexgen_hammadde_fiyat hf
                    LEFT JOIN nexgen_tedarikci  t  ON t.id  = hf.tedarikci_id
                    LEFT JOIN sistem_kullanici  sk ON sk.Id = hf.olusturan_id
                    WHERE hf.stok_kart_id = ?
                    ORDER BY hf.fiyat_tarihi DESC, hf.id DESC
                    LIMIT 100
                """, (kart_id,)).fetchall()
            except Exception:
                fiyat_gecmisi_raw = []

    finally:
        con.close()

    ms = mevcut
    mn = kart["minimum_stok"]
    kr = kart["kritik_stok"]
    if ms <= kr:
        durum = "kritik"
    elif ms <= mn:
        durum = "uyari"
    else:
        durum = "normal"

    hareketler = [dict(h) for h in hareketler_raw]
    can_manage  = yetki_var('nexgen.stok.manage', 'can_manage') or \
                  yetki_var('nexgen.stok.manage', 'can_create')

    # Hareket listelerini sekmelere göre ayır
    GIRIS_TIPLERI = {'ACILIS_DEVIR', 'GIRIS', 'URETIM_CIKTI'}
    CIKIS_TIPLERI = {'CIKIS', 'URETIM_TUKETIM', 'SEVK'}

    girişler  = []
    cikislar  = []
    for h in hareketler:
        tip = h.get('hareket_tipi', '')
        kg  = h.get('miktar_kg', 0) or 0
        if tip in GIRIS_TIPLERI or (tip == 'SAYIM_DUZELTME' and kg >= 0):
            girişler.append(h)
        elif tip in CIKIS_TIPLERI or (tip == 'SAYIM_DUZELTME' and kg < 0):
            cikislar.append(h)
        else:
            girişler.append(h)  # bilinmeyen tipler giriş tarafında göster

    # Fiyat geçmişi — önceki AKTİF fiyata göre fark/yüzde hesapla
    # Pasif (aktif=0) kayıtlar fark hesabından atlanır; geçmişte görünür ama
    # referans alınmaz ve kendileri için de fark gösterilmez.
    fiyat_gecmisi = [dict(f) for f in fiyat_gecmisi_raw]
    for i, f in enumerate(fiyat_gecmisi):
        # Pasif kayıt — fark gösterme
        if not f.get('aktif', 1):
            f['fark'] = f['yuzde'] = None
            continue
        # Sonraki kayıtlar arasında ilk aktif olanı bul
        onceki_fiyat = None
        for j in range(i + 1, len(fiyat_gecmisi)):
            kandidat = fiyat_gecmisi[j]
            if kandidat.get('aktif', 1):
                onceki_fiyat = kandidat.get('fiyat')
                break
        if onceki_fiyat:
            fark   = round(f['fiyat'] - onceki_fiyat, 4)
            yuzde  = round((fark / onceki_fiyat) * 100, 2)
            f['fark']  = fark
            f['yuzde'] = yuzde
        else:
            f['fark'] = f['yuzde'] = None

    return render_template(
        'nexgen/stok_detay.html',
        active='nexgen',
        kart=dict(kart),
        mevcut_stok=ms,
        durum=durum,
        hareketler=hareketler,
        girişler=girişler,
        cikislar=cikislar,
        can_manage=can_manage,
        can_fiyat_admin=can_fiyat_admin,
        fiyat_gecmisi=fiyat_gecmisi,
    )


# ─────────────────────────────────────────────────────────────
# API — Hızlı Panel Özet (FAZ-1D)
# GET /nexgen/api/stok-kart/<id>/ozet
# Yetki: nexgen.stok.view can_view
# Fiyat/maliyet bilgisi dönmez.
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/stok-kart/<int:kart_id>/ozet')
@yetki_gerekli('nexgen.stok.view', 'can_view')
def api_stok_kart_ozet(kart_id):
    con = _db()
    try:
        # SELECT * — Migration 048 çalıştırılmamış olsa bile çalışır
        kart_row = con.execute(
            "SELECT * FROM nexgen_stok_kart WHERE id=?",
            (kart_id,)
        ).fetchone()
        if not kart_row:
            return jsonify({"ok": False, "hata": "Kart bulunamadı."}), 404

        kart = dict(kart_row)
        ms = _mevcut_stok(con, kart_id)

        hareketler_raw = con.execute("""
            SELECT h.hareket_tipi, h.miktar_kg, h.sonraki_stok,
                   h.aciklama, h.olusturma_tarihi,
                   sk.KullaniciAdi AS yapan
            FROM nexgen_stok_hareket h
            LEFT JOIN sistem_kullanici sk ON sk.Id = h.olusturan_id
            WHERE h.stok_kart_id = ?
            ORDER BY h.id DESC LIMIT 5
        """, (kart_id,)).fetchall()

    except Exception as e:
        return jsonify({"ok": False, "hata": f"Veritabanı hatası: {str(e)}"}), 500
    finally:
        con.close()

    mn = kart.get("minimum_stok", 0) or 0
    kr = kart.get("kritik_stok", 0) or 0
    if ms <= kr:
        durum = "kritik"
    elif ms <= mn:
        durum = "uyari"
    else:
        durum = "normal"

    hareketler = []
    for h in hareketler_raw:
        hareketler.append({
            "tip":      h["hareket_tipi"],
            "miktar":   h["miktar_kg"],
            "stok":     h["sonraki_stok"],
            "aciklama": h["aciklama"] or "",
            "tarih":    (h["olusturma_tarihi"] or "")[:16],
            "yapan":    h["yapan"] or "—",
        })

    return jsonify({
        "ok": True,
        "kart": {
            "id":            kart.get("id"),
            "kod":           kart.get("kod", ""),
            "ad":            kart.get("ad", ""),
            "kategori":      kart.get("kategori", ""),
            "birim":         kart.get("birim", "KG"),
            "minimum_stok":  mn,
            "kritik_stok":   kr,
            "aktif":         kart.get("aktif", 1),
            # FAZ-1C opsiyonel alanlar — Migration 048 yoksa None
            "renk":          kart.get("renk"),
            "alt_kategori":  kart.get("alt_kategori"),
            "kalite_sinifi": kart.get("kalite_sinifi"),
            "shore_degeri":  kart.get("shore_degeri"),
            "notlar":        kart.get("notlar"),
        },
        "mevcut_stok": ms,
        "durum":       durum,
        "hareketler":  hareketler,
    })


# ─────────────────────────────────────────────────────────────
# API — Yeni Stok Kartı Ekle
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/stok-kart-ekle', methods=['POST'])
@yetki_gerekli('nexgen.stok.manage', 'can_create')
def api_stok_kart_ekle():
    data = request.get_json(silent=True) or {}
    kod      = (data.get('kod') or '').strip().upper()
    ad       = (data.get('ad') or '').strip()
    kategori = (data.get('kategori') or 'HAMMADDE').strip().upper()
    birim    = (data.get('birim') or 'KG').strip().upper()
    # FAZ-1C opsiyonel alanlar — boşsa None kaydedilir
    renk          = (data.get('renk') or '').strip() or None
    alt_kategori  = (data.get('alt_kategori') or '').strip() or None
    kalite_sinifi = (data.get('kalite_sinifi') or '').strip() or None
    shore_degeri  = (data.get('shore_degeri') or '').strip() or None
    notlar        = (data.get('notlar') or '').strip() or None

    try:
        min_stok  = float(data.get('minimum_stok') or 0)
        krit_stok = float(data.get('kritik_stok') or 0)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "hata": "Geçersiz sayısal değer."}), 400

    GECERLI_KATEGORILER = {
        'HAMMADDE', 'MAMUL_COMPOUND', 'RECYCLE', 'KATKI', 'BOYA', 'DIGER'
    }

    if not kod:
        return jsonify({"ok": False, "hata": "Kod zorunludur."}), 400
    if not ad:
        return jsonify({"ok": False, "hata": "Ad zorunludur."}), 400
    if kategori not in GECERLI_KATEGORILER:
        return jsonify({"ok": False, "hata": f"Geçersiz kategori: {kategori}"}), 400

    con = _db()
    try:
        mevcut = con.execute(
            "SELECT id FROM nexgen_stok_kart WHERE kod=?", (kod,)
        ).fetchone()
        if mevcut:
            return jsonify({"ok": False, "hata": f"'{kod}' kodu zaten mevcut."}), 409

        con.execute("""
            INSERT INTO nexgen_stok_kart
              (kod, ad, kategori, birim, minimum_stok, kritik_stok,
               renk, alt_kategori, kalite_sinifi, shore_degeri, notlar,
               aktif, olusturan_id, olusturma_tarihi)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, datetime('now'))
        """, (kod, ad, kategori, birim, min_stok, krit_stok,
              renk, alt_kategori, kalite_sinifi, shore_degeri, notlar,
              _kullanici_id()))
        yeni_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        con.commit()
    except Exception as e:
        con.rollback()
        return jsonify({"ok": False, "hata": str(e)}), 500
    finally:
        con.close()

    return jsonify({"ok": True, "id": yeni_id, "kod": kod, "ad": ad})


# ─────────────────────────────────────────────────────────────
# API — Stok Hareketi Ekle (manuel giriş/çıkış/sayım)
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/stok-hareket-ekle', methods=['POST'])
@yetki_gerekli('nexgen.stok.manage', 'can_create')
def api_stok_hareket_ekle():
    data = request.get_json(silent=True) or {}
    kart_id       = data.get('stok_kart_id')
    hareket_tipi  = (data.get('hareket_tipi') or '').strip().upper()
    aciklama      = (data.get('aciklama') or '').strip()
    try:
        miktar = float(data.get('miktar_kg') or 0)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "hata": "Geçersiz miktar."}), 400

    GECERLI_TIPLER = {
        'GIRIS', 'CIKIS', 'URETIM_TUKETIM', 'URETIM_CIKTI',
        'SAYIM_DUZELTME', 'SEVK'
    }
    CIKIS_TIPLERI = {'CIKIS', 'URETIM_TUKETIM', 'SEVK'}

    if not kart_id:
        return jsonify({"ok": False, "hata": "stok_kart_id zorunludur."}), 400
    if hareket_tipi not in GECERLI_TIPLER:
        return jsonify({"ok": False, "hata": f"Geçersiz hareket tipi: {hareket_tipi}"}), 400
    if miktar <= 0:
        return jsonify({"ok": False, "hata": "Miktar sıfırdan büyük olmalıdır."}), 400

    # Çıkış hareketlerinde miktarı negatife çevir
    if hareket_tipi in CIKIS_TIPLERI:
        miktar_kayit = -abs(miktar)
    else:
        miktar_kayit = abs(miktar)

    con = _db()
    try:
        kart = con.execute(
            "SELECT id FROM nexgen_stok_kart WHERE id=? AND aktif=1", (kart_id,)
        ).fetchone()
        if not kart:
            return jsonify({"ok": False, "hata": "Stok kartı bulunamadı veya pasif."}), 404

        onceki = _mevcut_stok(con, kart_id)
        sonraki = round(onceki + miktar_kayit, 3)

        con.execute("""
            INSERT INTO nexgen_stok_hareket
              (stok_kart_id, hareket_tipi, miktar_kg,
               onceki_stok, sonraki_stok,
               aciklama, olusturan_id, olusturma_tarihi)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """, (
            kart_id, hareket_tipi, miktar_kayit,
            onceki, sonraki,
            aciklama, _kullanici_id()
        ))
        con.commit()
    except Exception as e:
        con.rollback()
        return jsonify({"ok": False, "hata": str(e)}), 500
    finally:
        con.close()

    return jsonify({
        "ok": True,
        "onceki_stok": onceki,
        "sonraki_stok": sonraki,
        "hareket_tipi": hareket_tipi,
    })


# ─────────────────────────────────────────────────────────────
# API — Kart pasif/aktif yap (silme yok)
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/stok-kart-durum', methods=['POST'])
@yetki_gerekli('nexgen.stok.manage', 'can_update')
def api_stok_kart_durum():
    data = request.get_json(silent=True) or {}
    kart_id = data.get('id')
    aktif   = 1 if data.get('aktif') else 0

    if not kart_id:
        return jsonify({"ok": False, "hata": "id zorunludur."}), 400

    con = _db()
    try:
        kart = con.execute(
            "SELECT id FROM nexgen_stok_kart WHERE id=?", (kart_id,)
        ).fetchone()
        if not kart:
            return jsonify({"ok": False, "hata": "Kart bulunamadı."}), 404

        con.execute("""
            UPDATE nexgen_stok_kart
            SET aktif=?, guncelleyen_id=?, guncelleme_tarihi=datetime('now')
            WHERE id=?
        """, (aktif, _kullanici_id(), kart_id))
        con.commit()
    except Exception as e:
        con.rollback()
        return jsonify({"ok": False, "hata": str(e)}), 500
    finally:
        con.close()

    return jsonify({"ok": True, "aktif": aktif})


# ─────────────────────────────────────────────────────────────
# Placeholder Alt Sayfalar (satinalma ve stok-kartlari hariç)
# ─────────────────────────────────────────────────────────────
_SAYFALAR = {
    'depo':      ('Depo & Stok',    'Hammadde depo ve stok takip ekranı.'),
    'formuller': ('Formüller',       'Ürün başına hammadde formül tanımları.'),
    'uretim':    ('Üretim Tablet',   'Üretim sürecinde kullanılan hammadde giriş/çıkış ekranı.'),
    'recycle':   ('Recycle',         'Geri dönüşüm ve fire takip ekranı.'),
    'deneme':    ('Deneme',          'Deneme/prototip üretim kayıt ekranı.'),
    'sevk':      ('Sevk & Barkod',   'Ürün sevkiyat ve barkod yönetim ekranı.'),
    'maliyet':   ('Maliyet & Rapor', 'Hammadde maliyet analizi ve raporlama ekranı.'),
    'raporlar':  ('Raporlar',        'NexGen genel raporlar merkezi.'),
}


@nexgen_bp.route('/<string:sayfa>')
@yetki_gerekli('nexgen.view', 'can_view')
def alt_sayfa(sayfa):
    if sayfa not in _SAYFALAR:
        abort(404)
    baslik, aciklama = _SAYFALAR[sayfa]
    return render_template(
        'nexgen/placeholder.html',
        active='nexgen',
        sayfa_baslik=baslik,
        sayfa_aciklama=aciklama,
        sayfa_slug=sayfa,
    )


# ═════════════════════════════════════════════════════════════
# FAZ-2: SATIN ALMA MERKEZİ
# ─────────────────────────────────────────────────────────────
# KURAL: Bu bölümde nexgen_stok_hareket INSERT YAPILMAZ.
# ═════════════════════════════════════════════════════════════

def _siparis_no_uret(con):
    """SP-YYYY-NNNN formatında benzersiz sipariş numarası üretir."""
    from datetime import datetime
    yil = datetime.now().strftime('%Y')
    row = con.execute("""
        SELECT MAX(CAST(SUBSTR(siparis_no, -4) AS INTEGER)) AS son
        FROM nexgen_satin_siparis
        WHERE siparis_no LIKE ?
    """, (f'SP-{yil}-%',)).fetchone()
    son = row['son'] if row and row['son'] else 0
    return f'SP-{yil}-{son + 1:04d}'


def _tedarikci_veya_404(con, tedarikci_id):
    t = con.execute(
        "SELECT * FROM nexgen_tedarikci WHERE id=? AND aktif=1", (tedarikci_id,)
    ).fetchone()
    if not t:
        abort(404)
    return t


# ─────────────────────────────────────────────────────────────
# Satın Alma Ana Sayfa
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/satinalma')
@yetki_gerekli('nexgen.satinalma.view', 'can_view')
def satinalma_index():
    con = _db()
    try:
        durum_filtre = request.args.get('durum', '')
        tedarikci_filtre = request.args.get('tedarikci_id', '')

        sorgu = """
            SELECT s.id, s.siparis_no, s.siparis_tarihi, s.beklenen_teslim,
                   s.siparis_miktari_kg, s.para_birimi, s.durum, s.onay_durumu,
                   s.birim_fiyat, s.birim_fiyat_try, s.toplam_tutar_try,
                   s.vade_tarihi, s.aciklama,
                   t.ad AS tedarikci_ad, t.id AS tedarikci_id,
                   k.kod AS stok_kod, k.ad AS stok_ad,
                   COALESCE(
                       (SELECT SUM(mk.miktar_kg)
                        FROM nexgen_mal_kabul mk
                        WHERE mk.satin_siparis_id = s.id), 0
                   ) AS gelen_kg
            FROM nexgen_satin_siparis s
            JOIN nexgen_tedarikci t ON t.id = s.tedarikci_id
            JOIN nexgen_stok_kart k ON k.id = s.stok_kart_id
            WHERE 1=1
        """
        params = []
        if durum_filtre:
            sorgu += " AND s.durum = ?"
            params.append(durum_filtre)
        if tedarikci_filtre:
            sorgu += " AND s.tedarikci_id = ?"
            params.append(tedarikci_filtre)
        sorgu += " ORDER BY s.id DESC"

        siparisler_raw = con.execute(sorgu, params).fetchall()
        tedarikciler   = con.execute(
            "SELECT id, ad FROM nexgen_tedarikci WHERE aktif=1 ORDER BY ad"
        ).fetchall()

    finally:
        con.close()

    can_manage     = yetki_var('nexgen.satinalma.manage', 'can_create')
    can_approve    = yetki_var('nexgen.satinalma.approve', 'can_approve')
    can_fiyat      = yetki_var('nexgen.satinalma.fiyat', 'can_view')
    # Tedarikçi yönetimi: sadece Yönetim rolü — Satın Alma sadece görüntüler
    can_ted_manage = yetki_var('nexgen.tedarikci.manage', 'can_create')
    can_fiyat_view = yetki_var('nexgen.fiyat.view', 'can_view')

    siparisler = []
    for s in siparisler_raw:
        row = dict(s)
        siparis_kg = row.get('siparis_miktari_kg') or 0
        gelen_kg   = row.get('gelen_kg') or 0
        row['gelen_kg']  = round(gelen_kg, 3)
        row['kalan_kg']  = round(siparis_kg - gelen_kg, 3)
        # Teslim durumu DB'deki durum alanından okunur (depo mal kabul sonrası güncellendi)
        # Görsel etiket için ayrıca hesapla
        if gelen_kg <= 0:
            row['teslim_durum'] = 'BEKLIYOR'
        elif gelen_kg >= siparis_kg:
            row['teslim_durum'] = 'TAMAMLANDI'
        else:
            row['teslim_durum'] = 'KISMI_TESLIM'
        siparisler.append(row)

    return render_template(
        'nexgen/satinalma_index.html',
        active='nexgen',
        siparisler=siparisler,
        tedarikciler=[dict(t) for t in tedarikciler],
        durum_filtre=durum_filtre,
        tedarikci_filtre=tedarikci_filtre,
        can_manage=can_manage,
        can_approve=can_approve,
        can_fiyat=can_fiyat,
        can_ted_manage=can_ted_manage,
        can_fiyat_view=can_fiyat_view,
    )


# ─────────────────────────────────────────────────────────────
# Sipariş Detay
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/satinalma/siparis/<int:siparis_id>')
@yetki_gerekli('nexgen.satinalma.view', 'can_view')
def satinalma_siparis_detay(siparis_id):
    con = _db()
    try:
        siparis = con.execute("""
            SELECT s.*,
                   t.ad AS tedarikci_ad, t.kod AS tedarikci_kod,
                   t.ulke, t.iletisim_email,
                   k.kod AS stok_kod, k.ad AS stok_ad, k.kategori AS stok_kategori,
                   oc.KullaniciAdi AS olusturan_ad,
                   ap.KullaniciAdi AS onaylayan_ad
            FROM nexgen_satin_siparis s
            JOIN nexgen_tedarikci t ON t.id = s.tedarikci_id
            JOIN nexgen_stok_kart k ON k.id = s.stok_kart_id
            LEFT JOIN sistem_kullanici oc ON oc.Id = s.olusturan_id
            LEFT JOIN sistem_kullanici ap ON ap.Id = s.onaylayan_id
            WHERE s.id = ?
        """, (siparis_id,)).fetchone()
        if not siparis:
            abort(404)
    finally:
        con.close()

    can_approve = yetki_var('nexgen.satinalma.approve', 'can_approve')
    can_manage  = yetki_var('nexgen.satinalma.manage', 'can_update')
    can_fiyat   = yetki_var('nexgen.satinalma.fiyat', 'can_view')

    return render_template(
        'nexgen/satinalma_siparis_detay.html',
        active='nexgen',
        siparis=dict(siparis),
        can_approve=can_approve,
        can_manage=can_manage,
        can_fiyat=can_fiyat,
    )


# ─────────────────────────────────────────────────────────────
# Tedarikçi Listesi
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/satinalma/tedarikci')
@yetki_gerekli('nexgen.tedarikci.view', 'can_view')
def satinalma_tedarikci():
    con = _db()
    try:
        tedarikciler = con.execute("""
            SELECT t.*,
                   COUNT(s.id) AS siparis_sayisi
            FROM nexgen_tedarikci t
            LEFT JOIN nexgen_satin_siparis s ON s.tedarikci_id = t.id
            GROUP BY t.id
            ORDER BY t.aktif DESC, t.ad
        """).fetchall()
    finally:
        con.close()

    can_manage = yetki_var('nexgen.tedarikci.manage', 'can_create')

    return render_template(
        'nexgen/satinalma_tedarikci.html',
        active='nexgen',
        tedarikciler=[dict(t) for t in tedarikciler],
        can_manage=can_manage,
    )


# ─────────────────────────────────────────────────────────────
# API — Yeni Sipariş Oluştur
# POST /nexgen/api/satinalma/siparis-ekle
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/satinalma/siparis-ekle', methods=['POST'])
@yetki_gerekli('nexgen.satinalma.manage', 'can_create')
def api_satinalma_siparis_ekle():
    data = request.get_json(silent=True) or {}

    tedarikci_id  = data.get('tedarikci_id')
    stok_kart_id  = data.get('stok_kart_id')
    siparis_tarihi = (data.get('siparis_tarihi') or '').strip()
    beklenen_teslim = (data.get('beklenen_teslim') or '').strip() or None
    aciklama = (data.get('aciklama') or '').strip() or None
    para_birimi = (data.get('para_birimi') or 'TRY').strip().upper()
    onay_durumu = 'TASLAK' if data.get('taslak') else 'ONAY_BEKLIYOR'

    try:
        miktar = float(data.get('siparis_miktari_kg') or 0)
        if miktar <= 0:
            return jsonify({"ok": False, "hata": "Sipariş miktarı sıfırdan büyük olmalı."}), 400
    except (ValueError, TypeError):
        return jsonify({"ok": False, "hata": "Geçersiz sipariş miktarı."}), 400

    birim_fiyat = None
    kur = None
    birim_fiyat_try = None
    toplam_tutar_try = None
    vade_gun = None
    vade_tarihi = None

    try:
        if data.get('birim_fiyat') not in (None, ''):
            birim_fiyat = float(data['birim_fiyat'])
            if birim_fiyat < 0:
                return jsonify({"ok": False, "hata": "Birim fiyat negatif olamaz."}), 400
    except (ValueError, TypeError):
        return jsonify({"ok": False, "hata": "Geçersiz birim fiyat."}), 400

    try:
        if data.get('kur') not in (None, ''):
            kur = float(data['kur'])
            if kur <= 0:
                return jsonify({"ok": False, "hata": "Kur sıfırdan büyük olmalı."}), 400
    except (ValueError, TypeError):
        return jsonify({"ok": False, "hata": "Geçersiz kur değeri."}), 400

    if birim_fiyat is not None:
        k = kur if (kur and para_birimi != 'TRY') else 1.0
        birim_fiyat_try = round(birim_fiyat * k, 4)
        toplam_tutar_try = round(birim_fiyat_try * miktar, 2)

    try:
        if data.get('vade_gun') not in (None, ''):
            vade_gun = int(data['vade_gun'])
            if siparis_tarihi and vade_gun >= 0:
                from datetime import date, timedelta
                base = date.fromisoformat(siparis_tarihi)
                vade_tarihi = (base + timedelta(days=vade_gun)).isoformat()
    except (ValueError, TypeError):
        return jsonify({"ok": False, "hata": "Geçersiz vade değeri."}), 400

    GECERLI_PARA = {'TRY', 'USD', 'EUR', 'GBP', 'CNY'}
    if para_birimi not in GECERLI_PARA:
        return jsonify({"ok": False, "hata": f"Geçersiz para birimi: {para_birimi}"}), 400

    if not tedarikci_id:
        return jsonify({"ok": False, "hata": "tedarikci_id zorunludur."}), 400
    if not stok_kart_id:
        return jsonify({"ok": False, "hata": "stok_kart_id zorunludur."}), 400
    if not siparis_tarihi:
        return jsonify({"ok": False, "hata": "siparis_tarihi zorunludur."}), 400

    con = _db()
    try:
        ted = con.execute(
            "SELECT id FROM nexgen_tedarikci WHERE id=? AND aktif=1", (tedarikci_id,)
        ).fetchone()
        if not ted:
            return jsonify({"ok": False, "hata": "Tedarikçi bulunamadı veya pasif."}), 404

        kart = con.execute(
            "SELECT id FROM nexgen_stok_kart WHERE id=? AND aktif=1", (stok_kart_id,)
        ).fetchone()
        if not kart:
            return jsonify({"ok": False, "hata": "Stok kartı bulunamadı veya pasif."}), 404

        siparis_no = _siparis_no_uret(con)

        con.execute("""
            INSERT INTO nexgen_satin_siparis
              (siparis_no, tedarikci_id, stok_kart_id,
               siparis_tarihi, beklenen_teslim,
               siparis_miktari_kg, birim_fiyat, para_birimi, kur,
               birim_fiyat_try, toplam_tutar_try,
               vade_gun, vade_tarihi,
               durum, onay_durumu, aciklama,
               olusturan_id, olusturma_tarihi)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'BEKLIYOR', ?, ?, ?, datetime('now'))
        """, (
            siparis_no, tedarikci_id, stok_kart_id,
            siparis_tarihi, beklenen_teslim,
            miktar, birim_fiyat, para_birimi, kur,
            birim_fiyat_try, toplam_tutar_try,
            vade_gun, vade_tarihi,
            onay_durumu, aciklama,
            _kullanici_id(),
        ))
        yeni_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        con.commit()
    except Exception as e:
        con.rollback()
        return jsonify({"ok": False, "hata": str(e)}), 500
    finally:
        con.close()

    return jsonify({"ok": True, "id": yeni_id, "siparis_no": siparis_no})


# ─────────────────────────────────────────────────────────────
# API — Sipariş Onay/Red/İptal
# POST /nexgen/api/satinalma/siparis-durum
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/satinalma/siparis-durum', methods=['POST'])
@yetki_gerekli('nexgen.satinalma.view', 'can_view')
def api_satinalma_siparis_durum():
    data = request.get_json(silent=True) or {}
    siparis_id = data.get('id')
    eylem = (data.get('eylem') or '').strip().upper()

    if not siparis_id:
        return jsonify({"ok": False, "hata": "id zorunludur."}), 400

    EYLEMLER = {'ONAYLA', 'REDDET', 'IPTAL', 'ONAYA_GONDER'}
    if eylem not in EYLEMLER:
        return jsonify({"ok": False, "hata": f"Geçersiz eylem: {eylem}"}), 400

    # Onay eylemi sadece approve yetkisiyle
    if eylem in ('ONAYLA', 'REDDET'):
        if not yetki_var('nexgen.satinalma.approve', 'can_approve'):
            return jsonify({"ok": False, "hata": "Onay/red yetkisi yok."}), 403

    # İptal: manage yetkisi yeterli
    if eylem == 'IPTAL':
        if not yetki_var('nexgen.satinalma.manage', 'can_update'):
            return jsonify({"ok": False, "hata": "İptal yetkisi yok."}), 403

    con = _db()
    try:
        siparis = con.execute(
            "SELECT id, onay_durumu, durum FROM nexgen_satin_siparis WHERE id=?",
            (siparis_id,)
        ).fetchone()
        if not siparis:
            return jsonify({"ok": False, "hata": "Sipariş bulunamadı."}), 404

        mevcut_onay = siparis['onay_durumu']
        mevcut_durum = siparis['durum']

        # Durum geçiş kuralları
        if eylem == 'ONAYA_GONDER':
            if mevcut_onay not in ('TASLAK', 'REDDEDILDI'):
                return jsonify({"ok": False, "hata": "Sadece Taslak veya Reddedilmiş sipariş onaya gönderilebilir."}), 400
            con.execute("""
                UPDATE nexgen_satin_siparis
                SET onay_durumu='ONAY_BEKLIYOR',
                    guncelleyen_id=?, guncelleme_tarihi=datetime('now')
                WHERE id=?
            """, (_kullanici_id(), siparis_id))

        elif eylem == 'ONAYLA':
            if mevcut_onay != 'ONAY_BEKLIYOR':
                return jsonify({"ok": False, "hata": "Sadece Onay Bekleyen sipariş onaylanabilir."}), 400
            con.execute("""
                UPDATE nexgen_satin_siparis
                SET onay_durumu='ONAYLANDI',
                    onaylayan_id=?, onay_tarihi=datetime('now'),
                    guncelleyen_id=?, guncelleme_tarihi=datetime('now')
                WHERE id=?
            """, (_kullanici_id(), _kullanici_id(), siparis_id))

        elif eylem == 'REDDET':
            if mevcut_onay != 'ONAY_BEKLIYOR':
                return jsonify({"ok": False, "hata": "Sadece Onay Bekleyen sipariş reddedilebilir."}), 400
            con.execute("""
                UPDATE nexgen_satin_siparis
                SET onay_durumu='REDDEDILDI',
                    onaylayan_id=?, onay_tarihi=datetime('now'),
                    guncelleyen_id=?, guncelleme_tarihi=datetime('now')
                WHERE id=?
            """, (_kullanici_id(), _kullanici_id(), siparis_id))

        elif eylem == 'IPTAL':
            if mevcut_durum == 'TAMAMLANDI':
                return jsonify({"ok": False, "hata": "Tamamlanmış sipariş iptal edilemez."}), 400
            con.execute("""
                UPDATE nexgen_satin_siparis
                SET durum='IPTAL',
                    guncelleyen_id=?, guncelleme_tarihi=datetime('now')
                WHERE id=?
            """, (_kullanici_id(), siparis_id))

        con.commit()
    except Exception as e:
        con.rollback()
        return jsonify({"ok": False, "hata": str(e)}), 500
    finally:
        con.close()

    return jsonify({"ok": True, "eylem": eylem})


# ─────────────────────────────────────────────────────────────
# API — Tedarikçi Ekle
# POST /nexgen/api/satinalma/tedarikci-ekle
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/satinalma/tedarikci-ekle', methods=['POST'])
@yetki_gerekli('nexgen.tedarikci.manage', 'can_create')
def api_tedarikci_ekle():
    data = request.get_json(silent=True) or {}
    kod   = (data.get('kod') or '').strip().upper()
    ad    = (data.get('ad') or '').strip()
    ulke  = (data.get('ulke') or 'TR').strip().upper()
    pb    = (data.get('para_birimi') or 'TRY').strip().upper()
    notlar = (data.get('notlar') or '').strip() or None
    iletisim_ad    = (data.get('iletisim_ad') or '').strip() or None
    iletisim_tel   = (data.get('iletisim_tel') or '').strip() or None
    iletisim_email = (data.get('iletisim_email') or '').strip() or None

    try:
        vade = int(data.get('varsayilan_vade') or 30)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "hata": "Geçersiz vade değeri."}), 400

    if not kod:
        return jsonify({"ok": False, "hata": "Kod zorunludur."}), 400
    if not ad:
        return jsonify({"ok": False, "hata": "Ad zorunludur."}), 400

    GECERLI_PARA = {'TRY', 'USD', 'EUR', 'GBP', 'CNY'}
    if pb not in GECERLI_PARA:
        return jsonify({"ok": False, "hata": f"Geçersiz para birimi: {pb}"}), 400

    con = _db()
    try:
        mevcut = con.execute(
            "SELECT id FROM nexgen_tedarikci WHERE kod=?", (kod,)
        ).fetchone()
        if mevcut:
            return jsonify({"ok": False, "hata": f"'{kod}' kodu zaten mevcut."}), 409

        con.execute("""
            INSERT INTO nexgen_tedarikci
              (kod, ad, ulke, para_birimi, varsayilan_vade,
               iletisim_ad, iletisim_tel, iletisim_email, notlar,
               aktif, olusturan_id, olusturma_tarihi)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, datetime('now'))
        """, (kod, ad, ulke, pb, vade,
              iletisim_ad, iletisim_tel, iletisim_email, notlar,
              _kullanici_id()))
        yeni_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        con.commit()
    except Exception as e:
        con.rollback()
        return jsonify({"ok": False, "hata": str(e)}), 500
    finally:
        con.close()

    return jsonify({"ok": True, "id": yeni_id, "kod": kod, "ad": ad})


# ─────────────────────────────────────────────────────────────
# API — Tedarikçi Düzenle
# POST /nexgen/api/satinalma/tedarikci-guncelle
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/satinalma/tedarikci-guncelle', methods=['POST'])
@yetki_gerekli('nexgen.tedarikci.manage', 'can_update')
def api_tedarikci_guncelle():
    data = request.get_json(silent=True) or {}
    tid  = data.get('id')
    if not tid:
        return jsonify({"ok": False, "hata": "id zorunludur."}), 400

    ad    = (data.get('ad') or '').strip()
    ulke  = (data.get('ulke') or 'TR').strip().upper()
    pb    = (data.get('para_birimi') or 'TRY').strip().upper()
    notlar = (data.get('notlar') or '').strip() or None
    iletisim_ad    = (data.get('iletisim_ad') or '').strip() or None
    iletisim_tel   = (data.get('iletisim_tel') or '').strip() or None
    iletisim_email = (data.get('iletisim_email') or '').strip() or None

    try:
        vade = int(data.get('varsayilan_vade') or 30)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "hata": "Geçersiz vade değeri."}), 400

    if not ad:
        return jsonify({"ok": False, "hata": "Ad zorunludur."}), 400

    con = _db()
    try:
        mevcut = con.execute(
            "SELECT id FROM nexgen_tedarikci WHERE id=?", (tid,)
        ).fetchone()
        if not mevcut:
            return jsonify({"ok": False, "hata": "Tedarikçi bulunamadı."}), 404

        con.execute("""
            UPDATE nexgen_tedarikci
            SET ad=?, ulke=?, para_birimi=?, varsayilan_vade=?,
                iletisim_ad=?, iletisim_tel=?, iletisim_email=?, notlar=?,
                guncelleyen_id=?, guncelleme_tarihi=datetime('now')
            WHERE id=?
        """, (ad, ulke, pb, vade,
              iletisim_ad, iletisim_tel, iletisim_email, notlar,
              _kullanici_id(), tid))
        con.commit()
    except Exception as e:
        con.rollback()
        return jsonify({"ok": False, "hata": str(e)}), 500
    finally:
        con.close()

    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────
# API — Stok Kartları (satın alma formu için dropdown)
# GET /nexgen/api/satinalma/stok-listesi
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/satinalma/stok-listesi')
@yetki_gerekli('nexgen.satinalma.manage', 'can_create')
def api_satinalma_stok_listesi():
    con = _db()
    try:
        kartlar = con.execute("""
            SELECT id, kod, ad, kategori, birim
            FROM nexgen_stok_kart
            WHERE aktif=1
            ORDER BY kategori, ad
        """).fetchall()
    finally:
        con.close()
    return jsonify({"ok": True, "kartlar": [dict(k) for k in kartlar]})


# ─────────────────────────────────────────────────────────────
# API — Tedarikçi Listesi (satın alma formu için dropdown)
# GET /nexgen/api/satinalma/tedarikci-listesi
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/satinalma/tedarikci-listesi')
@yetki_gerekli('nexgen.satinalma.manage', 'can_create')
def api_satinalma_tedarikci_listesi():
    con = _db()
    try:
        tedarikciler = con.execute("""
            SELECT id, kod, ad, para_birimi, varsayilan_vade
            FROM nexgen_tedarikci
            WHERE aktif=1
            ORDER BY ad
        """).fetchall()
    finally:
        con.close()
    return jsonify({"ok": True, "tedarikciler": [dict(t) for t in tedarikciler]})


# ═════════════════════════════════════════════════════════════
# FAZ-2.6 — HAFTALlK FİYAT YÖNETİMİ
# ═════════════════════════════════════════════════════════════
# KURAL: Bu bölümde nexgen_stok_hareket INSERT YAPILMAZ.
# Fiyat geçmişi ≠ stok hareketi.
# ─────────────────────────────────────────────────────────────


def _isoweek():
    """Geçerli ISO hafta kodu: '2026-W26'"""
    today = date.today()
    iso = today.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _son_fiyat(con, tedarikci_id, stok_kart_id):
    """
    Son aktif fiyat kaydını döndür.
    Kural: aktif=1 AND ORDER BY fiyat_tarihi DESC, id DESC LIMIT 1
    """
    return con.execute("""
        SELECT nhf.*, t.ad AS tedarikci_ad, sk.ad AS stok_ad,
               sk.kod AS stok_kod
        FROM nexgen_hammadde_fiyat nhf
        JOIN nexgen_tedarikci t ON t.id = nhf.tedarikci_id
        JOIN nexgen_stok_kart sk ON sk.id = nhf.stok_kart_id
        WHERE nhf.tedarikci_id = ?
          AND nhf.stok_kart_id = ?
          AND nhf.aktif = 1
        ORDER BY nhf.fiyat_tarihi DESC, nhf.id DESC
        LIMIT 1
    """, (tedarikci_id, stok_kart_id)).fetchone()


def _fiyat_farki(eski_fiyat, eski_pb, yeni_fiyat, yeni_pb):
    """Aynı para birimi varsa fark ve yüzde hesapla."""
    if eski_fiyat is None or yeni_fiyat is None:
        return None, None
    if eski_pb != yeni_pb:
        return None, None
    fark = yeni_fiyat - eski_fiyat
    yuzde = (fark / eski_fiyat * 100) if eski_fiyat != 0 else None
    return round(fark, 4), round(yuzde, 2) if yuzde is not None else None


# ─────────────────────────────────────────────────────────────
# Fiyat Listesi — GET /nexgen/satinalma/fiyat
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/satinalma/fiyat')
@yetki_gerekli('nexgen.fiyat.view', 'can_view')
def fiyat_listesi():
    con = _db()
    try:
        tedarikci_id = request.args.get('tedarikci_id', type=int)
        stok_kart_id = request.args.get('stok_kart_id', type=int)

        q = """
            SELECT nhf.id, nhf.fiyat, nhf.para_birimi, nhf.kur, nhf.fiyat_try,
                   nhf.vade_gun, nhf.fiyat_tarihi, nhf.kaynak, nhf.notlar,
                   nhf.aktif, nhf.batch_id,
                   t.kod AS tedarikci_kodu, t.ad AS tedarikci_ad,
                   sk.kod AS stok_kodu, sk.ad AS stok_ad
            FROM nexgen_hammadde_fiyat nhf
            JOIN nexgen_tedarikci t ON t.id = nhf.tedarikci_id
            JOIN nexgen_stok_kart sk ON sk.id = nhf.stok_kart_id
            WHERE 1=1
        """
        params = []
        if tedarikci_id:
            q += " AND nhf.tedarikci_id = ?"
            params.append(tedarikci_id)
        if stok_kart_id:
            q += " AND nhf.stok_kart_id = ?"
            params.append(stok_kart_id)
        q += " ORDER BY nhf.fiyat_tarihi DESC, nhf.id DESC LIMIT 200"

        fiyatlar = con.execute(q, params).fetchall()
        tedarikciler = con.execute(
            "SELECT id, kod, ad FROM nexgen_tedarikci WHERE aktif=1 ORDER BY ad"
        ).fetchall()
        stok_kartlari = con.execute(
            "SELECT id, kod, ad FROM nexgen_stok_kart WHERE aktif=1 ORDER BY kod"
        ).fetchall()
        son_batch = con.execute(
            "SELECT * FROM nexgen_fiyat_batch ORDER BY id DESC LIMIT 5"
        ).fetchall()

        can_manage = yetki_var('nexgen.fiyat.manage', 'can_create')
        can_admin  = yetki_var('nexgen.fiyat.admin', 'can_manage')
    finally:
        con.close()

    return render_template(
        'nexgen/fiyat_listesi.html',
        fiyatlar=fiyatlar,
        tedarikciler=tedarikciler,
        stok_kartlari=stok_kartlari,
        son_batch=son_batch,
        filtre_tedarikci=tedarikci_id,
        filtre_stok=stok_kart_id,
        can_manage=can_manage,
        can_admin=can_admin,
        active='nexgen'
    )


# ─────────────────────────────────────────────────────────────
# Excel Şablon İndir — GET /nexgen/satinalma/fiyat-sablonu-indir
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/satinalma/fiyat-sablonu-indir')
@yetki_gerekli('nexgen.fiyat.manage', 'can_create')
def fiyat_sablonu_indir():
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        return jsonify({"ok": False, "hata": "openpyxl yüklü değil"}), 500

    con = _db()
    try:
        eslesmeler = con.execute("""
            SELECT ts.id, t.kod AS t_kod, t.ad AS t_ad, t.varsayilan_vade,
                   sk.kod AS s_kod, sk.ad AS s_ad,
                   t.id AS tedarikci_id, sk.id AS stok_kart_id
            FROM nexgen_tedarikci_stok ts
            JOIN nexgen_tedarikci t ON t.id = ts.tedarikci_id
            JOIN nexgen_stok_kart sk ON sk.id = ts.stok_kart_id
            WHERE ts.aktif = 1 AND t.aktif = 1 AND sk.aktif = 1
            ORDER BY t.kod, sk.kod
        """).fetchall()

        son_fiyatlar = {}
        for e in eslesmeler:
            sf = _son_fiyat(con, e['tedarikci_id'], e['stok_kart_id'])
            son_fiyatlar[(e['tedarikci_id'], e['stok_kart_id'])] = sf
    finally:
        con.close()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Fiyat Girişi"

    bugun = date.today().isoformat()
    hafta = _isoweek()

    baslik_font = Font(bold=True, color="FFFFFF")
    baslik_dolu = PatternFill("solid", fgColor="2C3E50")
    kilitli_dolu = PatternFill("solid", fgColor="ECF0F1")
    orta = Alignment(horizontal="center")

    basliklar = [
        "tedarikci_kodu", "tedarikci_adi", "stok_kodu", "stok_adi",
        "fiyat", "para_birimi", "kur", "vade_gun",
        "fiyat_tarihi", "gecerlilik_bas", "gecerlilik_bitis", "not",
        "son_fiyat_bilgi"
    ]
    ws.append(basliklar)
    for col, hdr in enumerate(basliklar, 1):
        cell = ws.cell(row=1, column=col)
        cell.font = baslik_font
        cell.fill = baslik_dolu
        cell.alignment = orta

    for e in eslesmeler:
        sf = son_fiyatlar.get((e['tedarikci_id'], e['stok_kart_id']))
        son_fiyat_bilgi = ""
        if sf:
            son_fiyat_bilgi = f"{sf['fiyat']} {sf['para_birimi']} ({sf['fiyat_tarihi']})"

        row = [
            e['t_kod'], e['t_ad'], e['s_kod'], e['s_ad'],
            None, "USD", None, e['varsayilan_vade'],
            bugun, bugun, None, None,
            son_fiyat_bilgi
        ]
        ws.append(row)

        r_idx = ws.max_row
        for col in [1, 2, 3, 4, 13]:
            ws.cell(row=r_idx, column=col).fill = kilitli_dolu

    for col_idx, width in zip(range(1, 14), [14, 22, 14, 28, 10, 12, 10, 10, 13, 13, 14, 20, 25]):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = width

    ws.freeze_panes = "E2"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    dosya_adi = f"NexGen_Fiyat_Sablonu_{hafta}.xlsx"
    return Response(
        buf.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={dosya_adi}"}
    )


# ─────────────────────────────────────────────────────────────
# Excel Yükle + Preview — POST /nexgen/satinalma/fiyat-yukle
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/satinalma/fiyat-yukle', methods=['POST'])
@yetki_gerekli('nexgen.fiyat.manage', 'can_create')
def fiyat_yukle():
    try:
        import openpyxl
    except ImportError:
        return jsonify({"ok": False, "hata": "openpyxl yüklü değil"}), 500

    f = request.files.get('dosya')
    if not f or not f.filename.endswith('.xlsx'):
        return jsonify({"ok": False, "hata": "Geçerli bir .xlsx dosyası seçin"}), 400

    kullanici_id = _kullanici_id()
    hafta = _isoweek()

    con = _db()
    try:
        # Batch kaydı oluştur
        con.execute("""
            INSERT INTO nexgen_fiyat_batch
              (hafta_kodu, dosya_adi, durum, yukleyen_id)
            VALUES (?, ?, 'ONAY_BEKLIYOR', ?)
        """, (hafta, f.filename, kullanici_id))
        con.commit()
        batch_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Excel parse
        wb = openpyxl.load_workbook(f, data_only=True)
        ws = wb.active

        tedarikci_map = {r[0]: r[1] for r in con.execute(
            "SELECT kod, id FROM nexgen_tedarikci"
        ).fetchall()}
        stok_map = {r[0]: r[1] for r in con.execute(
            "SELECT kod, id FROM nexgen_stok_kart"
        ).fetchall()}

        toplam = gecerli = hatali = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not any(row):
                continue
            t_kod = str(row[0]).strip() if row[0] else None
            s_kod = str(row[2]).strip() if row[2] else None
            fiyat_raw = row[4]
            pb = str(row[5]).strip().upper() if row[5] else 'USD'
            kur = row[6]
            vade = row[7]
            f_tarih = str(row[8]).strip() if row[8] else date.today().isoformat()
            g_bas = str(row[9]).strip() if row[9] else None
            g_bit = str(row[10]).strip() if row[10] else None
            notlar = str(row[11]).strip() if row[11] else None

            toplam += 1

            if fiyat_raw is None or str(fiyat_raw).strip() == '':
                continue

            hata = None
            t_id = s_id = None
            try:
                fiyat = float(fiyat_raw)
                if fiyat <= 0:
                    hata = "Fiyat sıfır veya negatif olamaz"
            except (ValueError, TypeError):
                hata = f"Geçersiz fiyat: {fiyat_raw}"
                fiyat = None

            if t_kod not in tedarikci_map:
                hata = f"Tedarikçi kodu bulunamadı: {t_kod}"
            else:
                t_id = tedarikci_map[t_kod]

            if s_kod not in stok_map:
                hata = (hata + " | " if hata else "") + f"Stok kodu bulunamadı: {s_kod}"
            else:
                s_id = stok_map[s_kod]

            onceki = None
            fark = yuzde = None
            if t_id and s_id:
                onceki = _son_fiyat(con, t_id, s_id)
            if onceki and fiyat and not hata:
                fark, yuzde = _fiyat_farki(
                    onceki['fiyat'], onceki['para_birimi'], fiyat, pb
                )

            fiyat_try = None
            if fiyat and kur:
                try:
                    fiyat_try = round(float(fiyat) * float(kur), 4)
                except Exception:
                    pass

            gecerli_mi = 0 if hata else 1
            if gecerli_mi:
                gecerli += 1
            else:
                hatali += 1

            con.execute("""
                INSERT INTO nexgen_fiyat_batch_detay
                  (batch_id, tedarikci_kodu, stok_kodu, tedarikci_id, stok_kart_id,
                   fiyat, para_birimi, kur, fiyat_try, vade_gun,
                   fiyat_tarihi, gecerlilik_bas, gecerlilik_bitis, notlar,
                   onceki_fiyat, onceki_pb, onceki_tarih, fark, yuzde_degisim,
                   gecerli_mi, hata_sebebi)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                batch_id, t_kod, s_kod, t_id, s_id,
                fiyat, pb, kur, fiyat_try, vade,
                f_tarih, g_bas, g_bit, notlar,
                onceki['fiyat'] if onceki else None,
                onceki['para_birimi'] if onceki else None,
                onceki['fiyat_tarihi'] if onceki else None,
                fark, yuzde,
                gecerli_mi, hata
            ))

        con.execute("""
            UPDATE nexgen_fiyat_batch
            SET toplam_satir=?, gecerli_satir=?, hatali_satir=?
            WHERE id=?
        """, (toplam, gecerli, hatali, batch_id))
        con.commit()
    finally:
        con.close()

    return redirect(url_for('nexgen.fiyat_preview', batch_id=batch_id))


# ─────────────────────────────────────────────────────────────
# Preview — GET /nexgen/satinalma/fiyat-preview/<batch_id>
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/satinalma/fiyat-preview/<int:batch_id>')
@yetki_gerekli('nexgen.fiyat.manage', 'can_create')
def fiyat_preview(batch_id):
    con = _db()
    try:
        batch = con.execute(
            "SELECT * FROM nexgen_fiyat_batch WHERE id=?", (batch_id,)
        ).fetchone()
        if not batch:
            abort(404)

        if batch['durum'] != 'ONAY_BEKLIYOR':
            flash(f"Bu batch artık işlenemez: durum={batch['durum']}", "warning")
            return redirect(url_for('nexgen.fiyat_listesi'))

        detaylar = con.execute("""
            SELECT * FROM nexgen_fiyat_batch_detay
            WHERE batch_id=?
            ORDER BY tedarikci_kodu, stok_kodu
        """, (batch_id,)).fetchall()

        can_approve = yetki_var('nexgen.fiyat.approve', 'can_approve')
    finally:
        con.close()

    return render_template(
        'nexgen/fiyat_preview.html',
        batch=batch,
        detaylar=detaylar,
        can_approve=can_approve,
        active='nexgen'
    )


# ─────────────────────────────────────────────────────────────
# Onayla — POST /nexgen/satinalma/fiyat-onayla/<batch_id>
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/satinalma/fiyat-onayla/<int:batch_id>', methods=['POST'])
@yetki_gerekli('nexgen.fiyat.approve', 'can_approve')
def fiyat_onayla(batch_id):
    kullanici_id = _kullanici_id()
    con = _db()
    try:
        batch = con.execute(
            "SELECT * FROM nexgen_fiyat_batch WHERE id=?", (batch_id,)
        ).fetchone()
        if not batch or batch['durum'] != 'ONAY_BEKLIYOR':
            return jsonify({"ok": False, "hata": "Geçersiz veya işlenmiş batch"}), 400

        detaylar = con.execute("""
            SELECT * FROM nexgen_fiyat_batch_detay
            WHERE batch_id=? AND gecerli_mi=1
              AND tedarikci_id IS NOT NULL AND stok_kart_id IS NOT NULL
              AND fiyat IS NOT NULL
        """, (batch_id,)).fetchall()

        eklendi = 0
        for d in detaylar:
            con.execute("""
                INSERT INTO nexgen_hammadde_fiyat
                  (tedarikci_id, stok_kart_id, fiyat, para_birimi, kur, fiyat_try,
                   vade_gun, fiyat_tarihi, gecerlilik_bas, gecerlilik_bitis,
                   kaynak, batch_id, notlar, aktif, olusturan_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,'EXCEL_IMPORT',?,?,1,?)
            """, (
                d['tedarikci_id'], d['stok_kart_id'],
                d['fiyat'], d['para_birimi'], d['kur'], d['fiyat_try'],
                d['vade_gun'], d['fiyat_tarihi'], d['gecerlilik_bas'], d['gecerlilik_bitis'],
                batch_id, d['notlar'], kullanici_id
            ))
            eklendi += 1

        con.execute("""
            UPDATE nexgen_fiyat_batch
            SET durum='ONAYLANDI', onaylayan_id=?, onay_tarihi=datetime('now')
            WHERE id=?
        """, (kullanici_id, batch_id))
        con.commit()
    finally:
        con.close()

    return jsonify({"ok": True, "eklendi": eklendi})


# ─────────────────────────────────────────────────────────────
# İptal — POST /nexgen/satinalma/fiyat-iptal/<batch_id>
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/satinalma/fiyat-iptal/<int:batch_id>', methods=['POST'])
@yetki_gerekli('nexgen.fiyat.manage', 'can_create')
def fiyat_iptal(batch_id):
    con = _db()
    try:
        batch = con.execute(
            "SELECT * FROM nexgen_fiyat_batch WHERE id=?", (batch_id,)
        ).fetchone()
        if not batch or batch['durum'] != 'ONAY_BEKLIYOR':
            return jsonify({"ok": False, "hata": "Geçersiz veya işlenmiş batch"}), 400

        con.execute("DELETE FROM nexgen_fiyat_batch_detay WHERE batch_id=?", (batch_id,))
        con.execute(
            "UPDATE nexgen_fiyat_batch SET durum='IPTAL' WHERE id=?", (batch_id,)
        )
        con.commit()
    finally:
        con.close()

    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────
# API — Manuel Tekil Fiyat Girişi
# POST /nexgen/api/satinalma/fiyat-manuel
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/satinalma/fiyat-manuel', methods=['POST'])
@yetki_gerekli('nexgen.fiyat.manage', 'can_create')
def api_fiyat_manuel():
    if not request.is_json:
        return jsonify({"ok": False, "hata": "JSON bekleniyor"}), 400
    d = request.json
    tedarikci_id = d.get('tedarikci_id')
    stok_kart_id = d.get('stok_kart_id')
    fiyat        = d.get('fiyat')
    para_birimi  = d.get('para_birimi', 'USD')
    kur          = d.get('kur')
    vade_gun     = d.get('vade_gun')
    fiyat_tarihi = d.get('fiyat_tarihi')
    notlar       = d.get('notlar')

    if not all([tedarikci_id, stok_kart_id, fiyat, fiyat_tarihi]):
        return jsonify({"ok": False, "hata": "Zorunlu alanlar eksik"}), 400
    if para_birimi not in ('USD', 'EUR', 'TRY', 'GBP', 'CNY'):
        return jsonify({"ok": False, "hata": f"Geçersiz para birimi: {para_birimi}"}), 400

    fiyat_try = None
    if kur:
        try:
            fiyat_try = round(float(fiyat) * float(kur), 4)
        except Exception:
            pass

    kullanici_id = _kullanici_id()
    con = _db()
    try:
        ted  = con.execute("SELECT id FROM nexgen_tedarikci WHERE id=?", (tedarikci_id,)).fetchone()
        stok = con.execute("SELECT id FROM nexgen_stok_kart WHERE id=?", (stok_kart_id,)).fetchone()
        if not ted:
            return jsonify({"ok": False, "hata": "Tedarikçi bulunamadı"}), 400
        if not stok:
            return jsonify({"ok": False, "hata": "Stok kartı bulunamadı"}), 400

        con.execute("""
            INSERT INTO nexgen_hammadde_fiyat
              (tedarikci_id, stok_kart_id, fiyat, para_birimi, kur, fiyat_try,
               vade_gun, fiyat_tarihi, kaynak, aktif, olusturan_id)
            VALUES (?,?,?,?,?,?,?,?,'MANUEL',1,?)
        """, (tedarikci_id, stok_kart_id, fiyat, para_birimi, kur, fiyat_try,
              vade_gun, fiyat_tarihi, kullanici_id))
        con.commit()
        fiyat_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        con.close()

    return jsonify({"ok": True, "id": fiyat_id})


# ─────────────────────────────────────────────────────────────
# API — Son Fiyat Öner (sipariş formu pre-fill)
# GET /nexgen/api/satinalma/son-fiyat?tedarikci_id=X&stok_kart_id=Y
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/satinalma/son-fiyat')
@yetki_gerekli('nexgen.satinalma.manage', 'can_create')
def api_son_fiyat():
    tedarikci_id = request.args.get('tedarikci_id', type=int)
    stok_kart_id = request.args.get('stok_kart_id', type=int)
    if not tedarikci_id or not stok_kart_id:
        return jsonify({"ok": False, "hata": "tedarikci_id ve stok_kart_id gerekli"}), 400

    con = _db()
    try:
        sf = _son_fiyat(con, tedarikci_id, stok_kart_id)
    finally:
        con.close()

    if not sf:
        return jsonify({"ok": True, "fiyat": None})

    return jsonify({
        "ok": True,
        "fiyat": {
            "id": sf['id'],
            "fiyat": sf['fiyat'],
            "para_birimi": sf['para_birimi'],
            "kur": sf['kur'],
            "vade_gun": sf['vade_gun'],
            "fiyat_tarihi": sf['fiyat_tarihi'],
        }
    })


# ─────────────────────────────────────────────────────────────
# API — Fiyat Pasife Al (sadece Yönetim)
# POST /nexgen/api/satinalma/fiyat-pasife-al/<fiyat_id>
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/satinalma/fiyat-pasife-al/<int:fiyat_id>', methods=['POST'])
@yetki_gerekli('nexgen.fiyat.admin', 'can_manage')
def api_fiyat_pasife_al(fiyat_id):
    sebep = request.json.get('sebep', '') if request.is_json else ''
    kullanici_id = _kullanici_id()
    con = _db()
    try:
        kayit = con.execute(
            "SELECT id, aktif FROM nexgen_hammadde_fiyat WHERE id=?", (fiyat_id,)
        ).fetchone()
        if not kayit:
            return jsonify({"ok": False, "hata": "Kayıt bulunamadı"}), 404
        if not kayit['aktif']:
            return jsonify({"ok": False, "hata": "Zaten pasif"}), 400

        con.execute("""
            UPDATE nexgen_hammadde_fiyat
            SET aktif=0, iptal_sebebi=?, iptal_eden_id=?, iptal_tarihi=datetime('now')
            WHERE id=?
        """, (sebep, kullanici_id, fiyat_id))
        con.commit()
    finally:
        con.close()

    return jsonify({"ok": True})


# =============================================================
# FAZ-2.8 — NexGen Yönetim Merkezi
# =============================================================

# ─────────────────────────────────────────────────────────────
# Yönetim Merkezi Ana Sayfa
# GET /nexgen/yonetim/
# Yetki: nexgen.yonetim.manage can_view
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/yonetim/')
@yetki_gerekli('nexgen.yonetim.manage', 'can_view')
def yonetim_merkezi():
    con = _db()
    try:
        # Stok kartları — aile adıyla birlikte
        kartlar_raw = con.execute("""
            SELECT k.id, k.kod, k.ad, k.kategori, k.birim,
                   k.minimum_stok, k.kritik_stok, k.aktif,
                   k.renk, k.alt_kategori, k.kalite_sinifi,
                   k.shore_degeri, k.notlar, k.aile_id,
                   a.ad AS aile_ad, a.aa_kodu AS aile_aa,
                   COALESCE(SUM(h.miktar_kg), 0) AS mevcut_stok
            FROM nexgen_stok_kart k
            LEFT JOIN nexgen_stok_aile a ON a.id = k.aile_id
            LEFT JOIN nexgen_stok_hareket h ON h.stok_kart_id = k.id
            GROUP BY k.id
            ORDER BY a.sira NULLS LAST, k.kod
        """).fetchall()

        # Tedarikçiler — bağlı hammadde sayısıyla
        tedarikciler_raw = con.execute("""
            SELECT t.id, t.kod, t.ad, t.ulke, t.para_birimi,
                   t.varsayilan_vade, t.iletisim_ad, t.iletisim_tel,
                   t.iletisim_email, t.notlar, t.aktif,
                   COUNT(ts.id) AS esleme_sayisi
            FROM nexgen_tedarikci t
            LEFT JOIN nexgen_tedarikci_stok ts ON ts.tedarikci_id = t.id AND ts.aktif=1
            GROUP BY t.id
            ORDER BY t.aktif DESC, t.ad
        """).fetchall()

        # Eşleştirmeler — tümü
        eslesme_raw = con.execute("""
            SELECT ts.id, ts.tedarikci_id, ts.stok_kart_id,
                   ts.tercih_sirasi, ts.aktif, ts.notlar,
                   t.kod  AS ted_kod,  t.ad  AS ted_ad,
                   sk.kod AS stok_kod, sk.ad AS stok_ad
            FROM nexgen_tedarikci_stok ts
            JOIN nexgen_tedarikci  t  ON t.id  = ts.tedarikci_id
            JOIN nexgen_stok_kart  sk ON sk.id = ts.stok_kart_id
            ORDER BY t.ad, ts.tercih_sirasi, sk.kod
        """).fetchall()

        # Stok aile listesi (yeni kart modalında dropdown için)
        aileler_raw = con.execute(
            "SELECT id, aa_kodu, ad FROM nexgen_stok_aile WHERE aktif=1 ORDER BY sira"
        ).fetchall()

    finally:
        con.close()

    return render_template(
        'nexgen/yonetim.html',
        active='nexgen',
        kartlar=[dict(k) for k in kartlar_raw],
        tedarikciler=[dict(t) for t in tedarikciler_raw],
        eslesme_listesi=[dict(e) for e in eslesme_raw],
        aileler=[dict(a) for a in aileler_raw],
    )


# ─────────────────────────────────────────────────────────────
# API — Stok Kartı Güncelle (Yönetim)
# POST /nexgen/api/yonetim/stok-kart-guncelle
# Yetki: nexgen.yonetim.manage can_update
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/yonetim/stok-kart-guncelle', methods=['POST'])
@yetki_gerekli('nexgen.yonetim.manage', 'can_update')
def api_yonetim_stok_kart_guncelle():
    d = request.get_json(silent=True) or {}
    kart_id = d.get('id')
    if not kart_id:
        return jsonify({"ok": False, "hata": "id gerekli"}), 400

    guncellenecek = {}
    for alan in ('ad', 'kategori', 'birim', 'minimum_stok', 'kritik_stok',
                 'renk', 'alt_kategori', 'kalite_sinifi', 'shore_degeri',
                 'notlar', 'aile_id'):
        if alan in d:
            guncellenecek[alan] = d[alan] if d[alan] != '' else None

    if not guncellenecek:
        return jsonify({"ok": False, "hata": "Güncellenecek alan yok"}), 400

    kullanici_id = _kullanici_id()
    set_clause = ', '.join(f"{k}=?" for k in guncellenecek)
    vals = list(guncellenecek.values()) + [kullanici_id, kart_id]

    con = _db()
    try:
        mev = con.execute("SELECT id FROM nexgen_stok_kart WHERE id=?", (kart_id,)).fetchone()
        if not mev:
            return jsonify({"ok": False, "hata": "Stok kartı bulunamadı"}), 404
        con.execute(
            f"UPDATE nexgen_stok_kart SET {set_clause}, "
            f"guncelleyen_id=?, guncelleme_tarihi=datetime('now') WHERE id=?",
            vals
        )
        con.commit()
    finally:
        con.close()

    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────
# API — Stok Kartı Aktif/Pasif (Yönetim)
# POST /nexgen/api/yonetim/stok-kart-durum
# Yetki: nexgen.yonetim.manage can_update
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/yonetim/stok-kart-durum', methods=['POST'])
@yetki_gerekli('nexgen.yonetim.manage', 'can_update')
def api_yonetim_stok_kart_durum():
    d = request.get_json(silent=True) or {}
    kart_id = d.get('id')
    yeni_aktif = d.get('aktif')
    if kart_id is None or yeni_aktif is None:
        return jsonify({"ok": False, "hata": "id ve aktif gerekli"}), 400

    con = _db()
    try:
        con.execute(
            "UPDATE nexgen_stok_kart SET aktif=?, guncelleyen_id=?, "
            "guncelleme_tarihi=datetime('now') WHERE id=?",
            (1 if yeni_aktif else 0, _kullanici_id(), kart_id)
        )
        con.commit()
    finally:
        con.close()
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────
# API — Tedarikçi Güncelle (Yönetim) — mevcut endpoint wrapper
# POST /nexgen/api/yonetim/tedarikci-guncelle
# Yetki: nexgen.yonetim.manage can_update
# Not: Mevcut /api/satinalma/tedarikci-guncelle zaten nexgen.tedarikci.manage
#      gerektiriyor; Yönetim SuperAdmin olduğundan geçer.
#      Yönetim ekranından doğrudan mevcut endpoint çağrılacak (JS'te URL değişir).
# ─────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────
# API — Eşleştirme Ekle (Yönetim)
# POST /nexgen/api/yonetim/eslestirme-ekle
# Yetki: nexgen.yonetim.manage can_create
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/yonetim/eslestirme-ekle', methods=['POST'])
@yetki_gerekli('nexgen.yonetim.manage', 'can_create')
def api_yonetim_eslestirme_ekle():
    d = request.get_json(silent=True) or {}
    tedarikci_id = d.get('tedarikci_id')
    stok_kart_id = d.get('stok_kart_id')
    tercih_sirasi = d.get('tercih_sirasi', 1)
    notlar = d.get('notlar', '')

    if not tedarikci_id or not stok_kart_id:
        return jsonify({"ok": False, "hata": "tedarikci_id ve stok_kart_id gerekli"}), 400

    con = _db()
    try:
        # Çift kayıt kontrolü
        mev = con.execute(
            "SELECT id FROM nexgen_tedarikci_stok WHERE tedarikci_id=? AND stok_kart_id=?",
            (tedarikci_id, stok_kart_id)
        ).fetchone()
        if mev:
            # Pasifse reaktive et
            con.execute(
                "UPDATE nexgen_tedarikci_stok SET aktif=1, tercih_sirasi=?, notlar=? WHERE id=?",
                (tercih_sirasi, notlar, mev['id'])
            )
            con.commit()
            return jsonify({"ok": True, "yeni": False, "id": mev['id']})

        con.execute("""
            INSERT INTO nexgen_tedarikci_stok
              (tedarikci_id, stok_kart_id, tercih_sirasi, aktif, notlar)
            VALUES (?, ?, ?, 1, ?)
        """, (tedarikci_id, stok_kart_id, tercih_sirasi, notlar))
        yeni_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        con.commit()
    finally:
        con.close()

    return jsonify({"ok": True, "yeni": True, "id": yeni_id})


# ─────────────────────────────────────────────────────────────
# API — Eşleştirme Kaldır (Yönetim)
# POST /nexgen/api/yonetim/eslestirme-kaldir
# Yetki: nexgen.yonetim.manage can_delete
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/yonetim/eslestirme-kaldir', methods=['POST'])
@yetki_gerekli('nexgen.yonetim.manage', 'can_delete')
def api_yonetim_eslestirme_kaldir():
    d = request.get_json(silent=True) or {}
    eslesme_id = d.get('id')
    if not eslesme_id:
        return jsonify({"ok": False, "hata": "id gerekli"}), 400

    con = _db()
    try:
        kayit = con.execute(
            "SELECT id FROM nexgen_tedarikci_stok WHERE id=?", (eslesme_id,)
        ).fetchone()
        if not kayit:
            return jsonify({"ok": False, "hata": "Kayıt bulunamadı"}), 404
        # Silmek yerine pasife al — geçmişi koru
        con.execute(
            "UPDATE nexgen_tedarikci_stok SET aktif=0 WHERE id=?", (eslesme_id,)
        )
        con.commit()
    finally:
        con.close()

    return jsonify({"ok": True})


# =============================================================
# FAZ-3A — NexGen Depo Mal Kabul
# =============================================================

# ─────────────────────────────────────────────────────────────
# Depo Ana Sayfa
# GET /nexgen/depo/
# Yetki: nexgen.depo.view can_view
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/depo/')
@yetki_gerekli('nexgen.depo.view', 'can_view')
def depo():
    can_giris = yetki_var('nexgen.depo.giris', 'can_create')
    con = _db()
    try:
        # Bekleyen / kısmi siparişler
        bekleyen_raw = con.execute("""
            SELECT
                ss.id           AS siparis_id,
                ss.siparis_no,
                ss.siparis_miktari_kg    AS siparis_kg,
                ss.durum,
                ss.beklenen_teslim,
                ss.olusturma_tarihi,
                t.id            AS tedarikci_id,
                t.kod           AS ted_kod,
                t.ad            AS ted_ad,
                sk.id           AS stok_kart_id,
                sk.kod          AS stok_kod,
                sk.ad           AS stok_ad,
                sk.birim,
                COALESCE(
                    (SELECT SUM(mk.miktar_kg)
                     FROM nexgen_mal_kabul mk
                     WHERE mk.satin_siparis_id = ss.id), 0
                ) AS gelen_kg
            FROM nexgen_satin_siparis ss
            JOIN nexgen_tedarikci  t  ON t.id  = ss.tedarikci_id
            JOIN nexgen_stok_kart  sk ON sk.id = ss.stok_kart_id
            WHERE ss.durum IN ('BEKLIYOR', 'KISMI_TESLIM')
              AND ss.onay_durumu = 'ONAYLANDI'
            ORDER BY ss.beklenen_teslim ASC NULLS LAST, ss.id DESC
        """).fetchall()

        # Giriş geçmişi (son 100)
        gecmis_raw = con.execute("""
            SELECT
                mk.id,
                mk.miktar_kg,
                mk.irsaliye_no,
                mk.lot_no,
                mk.kabul_tarihi,
                mk.aciklama,
                mk.satin_siparis_id,
                ss.siparis_no,
                t.kod  AS ted_kod,
                t.ad   AS ted_ad,
                sk.kod AS stok_kod,
                sk.ad  AS stok_ad,
                ku.KullaniciAdi AS kabul_eden_ad
            FROM nexgen_mal_kabul mk
            JOIN nexgen_tedarikci  t  ON t.id  = mk.tedarikci_id
            JOIN nexgen_stok_kart  sk ON sk.id = mk.stok_kart_id
            LEFT JOIN nexgen_satin_siparis ss ON ss.id = mk.satin_siparis_id
            LEFT JOIN sistem_kullanici ku ON ku.Id = mk.kabul_eden_id
            ORDER BY mk.kabul_tarihi DESC, mk.id DESC
            LIMIT 100
        """).fetchall()

        # Tedarikçi ve stok listesi (direkt giriş modalı için)
        tedarikciler_raw = con.execute(
            "SELECT id, kod, ad FROM nexgen_tedarikci WHERE aktif=1 ORDER BY ad"
        ).fetchall()
        kartlar_raw = con.execute(
            "SELECT id, kod, ad, birim FROM nexgen_stok_kart WHERE aktif=1 ORDER BY kod"
        ).fetchall()

        # KPI
        bugun_giren_kg = con.execute("""
            SELECT COALESCE(SUM(miktar_kg), 0)
            FROM nexgen_mal_kabul
            WHERE date(kabul_tarihi) = date('now')
        """).fetchone()[0]
        bu_hafta_kabul_say = con.execute("""
            SELECT COUNT(*) FROM nexgen_mal_kabul
            WHERE kabul_tarihi >= datetime('now', '-7 days')
        """).fetchone()[0]

    finally:
        con.close()

    bekleyen = []
    for r in bekleyen_raw:
        d = dict(r)
        d['kalan_kg'] = round(d['siparis_kg'] - d['gelen_kg'], 3)
        bekleyen.append(d)

    return render_template(
        'nexgen/depo.html',
        active='nexgen',
        can_giris=can_giris,
        bekleyen=bekleyen,
        gecmis=[dict(g) for g in gecmis_raw],
        tedarikciler=[dict(t) for t in tedarikciler_raw],
        kartlar=[dict(k) for k in kartlar_raw],
        bugun_giren_kg=round(bugun_giren_kg, 1),
        bu_hafta_kabul_say=bu_hafta_kabul_say,
        bekleyen_say=len(bekleyen),
    )


# ─────────────────────────────────────────────────────────────
# API — Mal Kabul
# POST /nexgen/api/depo/mal-kabul
# Yetki: nexgen.depo.giris can_create
#
# Kurallar:
#   1) nexgen_mal_kabul INSERT (belge)
#   2) nexgen_stok_hareket INSERT hareket_tipi=GIRIS
#   3) Siparişe bağlıysa sipariş durum güncelle
#   4) Fiyat tablolarına dokunulmaz
# ─────────────────────────────────────────────────────────────
@nexgen_bp.route('/api/depo/mal-kabul', methods=['POST'])
@yetki_gerekli('nexgen.depo.giris', 'can_create')
def api_depo_mal_kabul():
    d = request.get_json(silent=True) or {}

    tedarikci_id   = d.get('tedarikci_id')
    stok_kart_id   = d.get('stok_kart_id')
    miktar_kg      = d.get('miktar_kg')
    irsaliye_no    = d.get('irsaliye_no', '').strip() or None
    lot_no         = d.get('lot_no', '').strip() or None
    aciklama       = d.get('aciklama', '').strip() or None
    siparis_id     = d.get('satin_siparis_id') or None  # None → direkt giriş

    # Zorunlu alan kontrolü
    if not tedarikci_id or not stok_kart_id or not miktar_kg:
        return jsonify({"ok": False, "hata": "tedarikci_id, stok_kart_id ve miktar_kg zorunlu"}), 400
    try:
        miktar_kg = float(miktar_kg)
        if miktar_kg <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"ok": False, "hata": "miktar_kg sıfırdan büyük olmalı"}), 400

    kullanici_id = _kullanici_id()
    con = _db()
    try:
        # Tedarikçi ve stok kartı var mı?
        ted = con.execute("SELECT id FROM nexgen_tedarikci WHERE id=?", (tedarikci_id,)).fetchone()
        if not ted:
            return jsonify({"ok": False, "hata": "Tedarikçi bulunamadı"}), 404
        kart = con.execute("SELECT id, ad FROM nexgen_stok_kart WHERE id=?", (stok_kart_id,)).fetchone()
        if not kart:
            return jsonify({"ok": False, "hata": "Stok kartı bulunamadı"}), 404

        # Siparişe bağlıysa kontrol
        siparis = None
        if siparis_id:
            siparis = con.execute(
                "SELECT id, siparis_miktari_kg, durum, stok_kart_id, tedarikci_id FROM nexgen_satin_siparis WHERE id=?",
                (siparis_id,)
            ).fetchone()
            if not siparis:
                return jsonify({"ok": False, "hata": "Sipariş bulunamadı"}), 404
            if siparis['durum'] in ('TAMAMLANDI', 'IPTAL'):
                return jsonify({"ok": False, "hata": f"Sipariş durumu {siparis['durum']}, mal kabul yapılamaz"}), 400

        # ── Stok mevcut durumu ─────────────────────────────────
        onceki_stok = _mevcut_stok(con, stok_kart_id)
        sonraki_stok = round(onceki_stok + miktar_kg, 3)

        # ── referans_tip belirle ───────────────────────────────
        if siparis_id:
            referans_tip = 'SATIN_ALMA_SIPARIS'
            ref_id = siparis_id
        else:
            referans_tip = 'DIREKT_GIRIS'
            ref_id = None  # mal_kabul INSERT sonrası doldurulacak

        # ── nexgen_stok_hareket INSERT ─────────────────────────
        aciklama_hareket = aciklama or (
            f"Mal kabul — "
            + (f"Sipariş #{siparis_id}" if siparis_id else "Direkt giriş")
            + (f" İrsaliye:{irsaliye_no}" if irsaliye_no else "")
        )
        con.execute("""
            INSERT INTO nexgen_stok_hareket
              (stok_kart_id, hareket_tipi, miktar_kg,
               onceki_stok, sonraki_stok,
               aciklama, referans_tip, referans_id,
               olusturan_id, olusturma_tarihi)
            VALUES (?, 'GIRIS', ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """, (stok_kart_id, miktar_kg, onceki_stok, sonraki_stok,
              aciklama_hareket, referans_tip, ref_id, kullanici_id))
        hareket_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

        # ── nexgen_mal_kabul INSERT ────────────────────────────
        con.execute("""
            INSERT INTO nexgen_mal_kabul
              (satin_siparis_id, tedarikci_id, stok_kart_id,
               miktar_kg, irsaliye_no, lot_no,
               kabul_eden_id, kabul_tarihi, aciklama, stok_hareket_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?)
        """, (siparis_id, tedarikci_id, stok_kart_id,
              miktar_kg, irsaliye_no, lot_no,
              kullanici_id, aciklama, hareket_id))
        mal_kabul_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Direkt girişte referans_id = mal_kabul_id
        if not siparis_id:
            con.execute(
                "UPDATE nexgen_stok_hareket SET referans_id=? WHERE id=?",
                (mal_kabul_id, hareket_id)
            )

        # ── Sipariş durumunu güncelle ──────────────────────────
        yeni_durum = None
        toplam_gelen = None
        if siparis and siparis_id:
            toplam_gelen_row = con.execute(
                "SELECT COALESCE(SUM(miktar_kg), 0) FROM nexgen_mal_kabul WHERE satin_siparis_id=?",
                (siparis_id,)
            ).fetchone()[0]
            toplam_gelen = round(toplam_gelen_row, 3)

            if toplam_gelen >= siparis['siparis_miktari_kg']:
                yeni_durum = 'TAMAMLANDI'
            else:
                yeni_durum = 'KISMI_TESLIM'

            con.execute(
                "UPDATE nexgen_satin_siparis SET durum=? WHERE id=?",
                (yeni_durum, siparis_id)
            )

        con.commit()

    except Exception as e:
        con.close()
        return jsonify({"ok": False, "hata": str(e)}), 500
    finally:
        con.close()

    sonuc = {
        "ok": True,
        "mal_kabul_id": mal_kabul_id,
        "hareket_id": hareket_id,
        "onceki_stok": onceki_stok,
        "sonraki_stok": sonraki_stok,
        "miktar_kg": miktar_kg,
    }
    if yeni_durum:
        sonuc["siparis_yeni_durum"] = yeni_durum
        sonuc["toplam_gelen_kg"] = toplam_gelen
    return jsonify(sonuc)


