# -*- coding: utf-8 -*-
"""
setup_plan_detay_v3.py
----------------------
PLAN detay panel - HİYERARŞİK YAPI:
  - Üst özet (Korgun+CPS breakdown)
  - TAKILDI bandı (ilk TAMAM olmayan proses)
  - ATKI bloğu (var ise)
  - GÖVDE bloğu (var ise)
  - ANA EMİR (en altta, secondary, küçük)

DÜZELTMELER:
  1) Rozet: TAKILDI / DEVAM / TAMAM (AKTİF değil)
  2) Proses sırası: üretim sırası (proses_kod numerik artan)
  3) Takıldı = ilk TAMAM OLMAYAN proses (üretim sırasında)
  4) Atkı/Gövde sırası dinamik: en geride kalan üstte

VERİ:
  - get_emir_ozet (mevcut)
  - Urt_Em2Em ile alt emirler
  - Korgun Urt_con_gch + Proses_M batch (TÜM emirler için)
  - CPS uretim_kayit batch (TÜM emirler için)
  - Anahtar: proses_adi.strip().lower() (Korgun '02' ↔ CPS 'KESIM' eslestirme)

CPS_KURALLAR:
  - Korgun read-only
  - DB değişmiyor
  - Frontend tek IIFE override (eski v2'yi kapatır)
  - Diğer sekmeler dokunulmuyor
"""
import os
import shutil
import datetime
import sys
import ast

CPS_ROOT = r"C:\cps_dev"
HEDEF_ROUTES = os.path.join(CPS_ROOT, "modules", "hedef", "routes.py")
JS_PATH = os.path.join(CPS_ROOT, "static", "js", "hedef.js")

ROUTES_MARKER = "# === PLAN_DETAY_V3 endpoint ==="
JS_MARKER = "[CPS LOCAL] PLAN detay v3 yuklendi"


# ====================================================================
# 1) BACKEND - mevcut /hedef/plan-detay endpoint'i v3'e cevir
# ====================================================================
# Mevcut PLAN_DETAY_V1 endpoint'inin TAMAMINI kaldirip v3 ile degistirecegiz.

ESKI_V1 = '''

# === PLAN_DETAY_V1 endpoint ===
# GET /hedef/plan-detay/<emir_no> - Read-only emir detay paneli
# Veri kaynaklari: get_emir_ozet + Urt_con_gch + Proses_M
@hedef_bp.route('/plan-detay/<int:emir_no>', methods=['GET'])
@hedef_yetkili
def hedef_plan_detay(emir_no):'''

YENI_V3_BASLA = '''

# === PLAN_DETAY_V3 endpoint ===
# GET /hedef/plan-detay/<emir_no> - Hiyerarsik detay (Atki/Govde/Ana)
# Veri: Korgun Urt_con_gch + CPS uretim_kayit birlesik (proses_adi anahtar)
@hedef_bp.route('/plan-detay/<int:emir_no>', methods=['GET'])
@hedef_yetkili
def hedef_plan_detay(emir_no):'''

# Eski v1'in icindeki body'i komple yeni v3 ile degistirecegiz.
# Bunun icin v1'in baslangic ve bitiş satirini bulup arasini replace edecegiz.
# Daha basit: v1'in tamamını ezerek v3 yazıyoruz.

# Önce eski v1'in tüm body'sini bul (def hedef_plan_detay'dan return jsonify'a kadar)
# Fakat bu zor. Onun yerine: v1 endpoint'inin tamamini siliyoruz, yerine v3 yaziyoruz.

# Kolay yol: v1 marker'ini bul, oradan baslayarak ESKI_V1_TAM bul.
# v1 body son satiri: "    'aktif_proses': aktif_proses_adi,\n    })\n"

# En kolay: ESKI_V1_BASLA pattern'i ile yakalanan offset'ten itibaren
# bir sonraki @hedef_bp.route line'a kadar (veya EOF'a kadar) komple sil.

# Bu yaklasim guvenli degil. Yerine SADECE ROUTES_MARKER ekleyip,
# v1 bloku kalsin ama yeni v3 endpoint farkli isimle yazilsin yontemi de
# yanlis: ayni route /plan-detay/<emir_no> iki kere olamaz.

# Cozum: v1 endpoint'inin TAM blokunu str_replace ile sil ve v3 yaz.

# v1 endpoint'inin son satirini bulmak icin: v1 docstring'inden return'e kadar.
# Daha basit: dosyada v1 markerinin oldugu satirdan dosya sonuna kadar
# REGEX ile ariyoruz: # === PLAN_DETAY_V1 endpoint === ... return jsonify({...})
# Ama JSON multi-line, regex zor.

# EN GUVENLI YOL: v1 ROUTES_MARKER'i bul, v3 endpoint'ini AYNI yere ek yap,
# v1 fonksiyon adini hedef_plan_detay_v1 (devre disi) yap.

# Bu da zor. Basit cozum: v1'in tamamini sil, dosyaya yeni v3 ekle.
# v1 cikarildigini varsayalim. v1 body'si su pattern'le baslar/biter:

V1_BLOK_TAM = '''

# === PLAN_DETAY_V1 endpoint ===
# GET /hedef/plan-detay/<emir_no> - Read-only emir detay paneli
# Veri kaynaklari: get_emir_ozet + Urt_con_gch + Proses_M
@hedef_bp.route('/plan-detay/<int:emir_no>', methods=['GET'])
@hedef_yetkili
def hedef_plan_detay(emir_no):
    """Read-only emir detay - PLAN ekraninda slide-in panel icin."""
    from flask import jsonify
    from modules.common import korgun as _kk_pd

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

    # Proses listesi - tek SQL
    proses_listesi = []
    aktif_proses_kod = None
    aktif_proses_adi = None
    hedef_toplam = int(ozet.get('hedef_adet', 0) or 0)

    try:
        con = _kk_pd._baglan()
        try:
            cur = con.cursor()
            cur.execute("""
                SELECT
                    g.Proses,
                    pm.Tanim,
                    SUM(g.Cikan) AS yapilan,
                    MAX(g.EndTarih) AS son_tarih,
                    COUNT(*) AS kayit
                  FROM Urt_con_gch g WITH(NOLOCK)
                  LEFT JOIN Proses_M pm WITH(NOLOCK) ON pm.Pro = g.Proses
                 WHERE g.EmirNo = %s
                   AND g.Cikan > 0
                 GROUP BY g.Proses, pm.Tanim
                 ORDER BY MAX(g.EndTarih) DESC
            """, (emir_no,))
            rows = cur.fetchall()
            for i, r in enumerate(rows):
                kod = r[0]
                adi = r[1] or kod
                yapilan = float(r[2] or 0)
                son_tarih = r[3]
                kayit = int(r[4] or 0)
                if hedef_toplam > 0:
                    yuzde = round((yapilan / hedef_toplam) * 100, 1)
                else:
                    yuzde = 0.0
                if yuzde >= 100:
                    durum = 'tamam'
                elif yuzde > 0:
                    durum = 'devam'
                else:
                    durum = 'bekliyor'
                proses_listesi.append({
                    'proses_kod': kod,
                    'proses_adi': adi,
                    'yapilan': int(yapilan),
                    'toplam_hedef': hedef_toplam,
                    'yuzde': yuzde,
                    'durum': durum,
                    'son_tarih': son_tarih.isoformat() if son_tarih else None,
                    'kayit_sayisi': kayit,
                })
                # Aktif proses = ilk kayit (ORDER BY EndTarih DESC)
                if i == 0:
                    aktif_proses_kod = kod
                    aktif_proses_adi = adi
            cur.close()
        finally:
            con.close()
    except Exception as e:
        try:
            print(f'[PLAN_DETAY_V1 hata, proses_listesi bos]: {e}')
        except Exception:
            pass
        proses_listesi = []

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
        'yapilan': int(ozet.get('yapilan_adet', 0) or 0),
        'kalan': int(ozet.get('kalan_adet', 0) or 0),
        'siparisler': ozet.get('siparisler', []),
        'proses_listesi': proses_listesi,
        'aktif_proses_kod': aktif_proses_kod,
        'aktif_proses': aktif_proses_adi,
    })
'''

# Yeni v3 endpoint kodu
V3_BLOK = '''

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
            cur.execute("""
                SELECT e.EmirNo, e.ModelKod, e.Tip, e.Location,
                       sk.Tanim AS ModelAdi
                  FROM Urt_Em2Em em WITH(NOLOCK)
                  INNER JOIN Urt_Emir e WITH(NOLOCK) ON e.EmirNo = em.EmirNo_YM
                  LEFT JOIN StokKart sk WITH(NOLOCK) ON sk.SKOD = e.ModelKod
                 WHERE em.EmirNo = %s
            """, (emir_no,))
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
    })


def _alt_parca_kategori(model_kod, model_adi):
    """ModelKod ve ModelAdi'ndan Atki/Govde tespit (frontend ile uyumlu)."""
    mk = (model_kod or '').upper()
    ma = (model_adi or '').upper()
    if 'ATKI' in mk or 'ATKI' in ma or 'ATK\u0130' in ma:
        return 'Atkı'
    if 'GOVDE' in mk or 'GOVDE' in ma or 'G\u00d6VDE' in ma:
        return 'Gövde'
    if 'TABAN' in mk or 'TABAN' in ma:
        return 'Taban'
    if 'SAYA' in mk or 'SAYA' in ma:
        return 'Saya'
    return 'Diğer'
'''


# ====================================================================
# 2) FRONTEND - yeni IIFE (eski v2'yi override)
# ====================================================================
JS_BLOCK = r'''


/* ====================================================================
   CPS LOCAL - PLAN DETAY v3 (HİYERARŞİK)
   - Üst özet (Korgun+CPS breakdown)
   - TAKILDI bandı (ilk TAMAM olmayan proses)
   - ATKI bloğu (var ise) + GÖVDE bloğu (var ise)
   - ANA EMİR (en altta, secondary, küçük)
   - Atki/Gövde sırası: en geride kalan üstte
   - Eski v2 IIFE'yi override eder (window.PlanDetayInline)
   ==================================================================== */
(function () {
    'use strict';

    var STYLE_ID = 'plan-detay-v3-style';
    var aktifEmir = null;
    var loading = false;
    var TOPLAM_KOLON = 11;

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

    function _ensureStyle() {
        if (document.getElementById(STYLE_ID)) return;
        var st = document.createElement('style');
        st.id = STYLE_ID;
        st.textContent = '' +
            '#planBody tr.plan-row {cursor:pointer;transition:background 0.12s;}' +
            '#planBody tr.plan-row:hover {background:rgba(249,115,22,0.04);}' +
            '#planBody tr.plan-row.acik {background:rgba(249,115,22,0.08);}' +
            '#planBody tr.plan-detay-row {background:#fafafa;}' +
            '#planBody tr.plan-detay-row > td {' +
                'padding:0;border-bottom:2px solid #f97316;' +
            '}' +
            '.pdv3-icerik {padding:18px 22px;animation:pdv3Ac 0.18s ease-out;}' +
            '@keyframes pdv3Ac {from{opacity:0;transform:translateY(-4px);} to{opacity:1;transform:translateY(0);}}' +
            // META
            '.pdv3-meta {' +
                'display:grid;grid-template-columns:repeat(6,1fr);gap:14px;' +
                'padding:14px 16px;background:#fff;border-radius:8px;' +
                'border:1px solid #e5e7eb;margin-bottom:14px;' +
            '}' +
            '.pdv3-meta-item {display:flex;flex-direction:column;}' +
            '.pdv3-meta-item .label {' +
                'font-size:9px;color:#9ca3af;text-transform:uppercase;' +
                'letter-spacing:0.5px;font-weight:700;margin-bottom:3px;' +
            '}' +
            '.pdv3-meta-item .val {font-size:13px;color:#111827;font-weight:600;}' +
            '.pdv3-meta-item .val.mono {font-family:var(--mono,monospace);font-size:12px;}' +
            '.pdv3-meta-item .breakdown {' +
                'font-size:10px;color:#6b7280;font-weight:500;margin-top:2px;' +
                'font-family:var(--mono,monospace);' +
            '}' +
            '.pdv3-pill {' +
                'display:inline-block;padding:1px 7px;border-radius:8px;' +
                'font-size:10px;font-weight:700;color:#fff;margin-left:4px;' +
            '}' +
            // TAKILDI BAND
            '.pdv3-takildi {' +
                'display:flex;align-items:center;gap:10px;' +
                'padding:12px 16px;border-radius:8px;margin-bottom:14px;' +
                'border-left:4px solid #f97316;background:rgba(249,115,22,0.06);' +
            '}' +
            '.pdv3-takildi.tamam {border-left-color:#10b981;background:rgba(16,185,129,0.06);}' +
            '.pdv3-takildi.bos {border-left-color:#9ca3af;background:#f9fafb;}' +
            '.pdv3-takildi-ikon {font-size:18px;}' +
            '.pdv3-takildi-etiket {' +
                'font-size:10px;font-weight:700;text-transform:uppercase;' +
                'letter-spacing:0.7px;padding:2px 8px;border-radius:6px;color:#fff;' +
            '}' +
            '.pdv3-takildi-yer {flex:1;font-size:13px;color:#111827;}' +
            '.pdv3-takildi-yer strong {color:#7c2d12;}' +
            '.pdv3-takildi-zaman {font-size:11px;color:#6b7280;}' +
            // BLOK
            '.pdv3-blok {' +
                'border:1px solid #e5e7eb;border-radius:8px;' +
                'padding:12px;margin-bottom:12px;' +
                'border-left:4px solid #9ca3af;background:#fff;' +
            '}' +
            '.pdv3-blok.tip-atki {border-left-color:#8b5cf6;}' +
            '.pdv3-blok.tip-govde {border-left-color:#3b82f6;}' +
            '.pdv3-blok.tip-taban {border-left-color:#06b6d4;}' +
            '.pdv3-blok-baslik {' +
                'display:flex;align-items:center;gap:8px;padding-bottom:8px;' +
                'border-bottom:1px solid #f3f4f6;margin-bottom:10px;flex-wrap:wrap;' +
            '}' +
            '.pdv3-blok-ikon {font-size:18px;}' +
            '.pdv3-blok-ad {font-size:13px;font-weight:700;color:#111827;}' +
            '.pdv3-blok-emir {' +
                'font-size:11px;color:#6b7280;font-family:var(--mono,monospace);' +
                'font-weight:600;' +
            '}' +
            '.pdv3-blok-model {' +
                'font-size:11px;color:#9ca3af;flex:1;' +
                'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;' +
            '}' +
            // PROSES KART
            '.pdv3-proses-grid {' +
                'display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));' +
                'gap:8px;' +
            '}' +
            '.pdv3-proses {' +
                'border:1px solid #e5e7eb;border-radius:6px;' +
                'padding:10px 12px;background:#fafafa;' +
            '}' +
            '.pdv3-proses.takildi {border-color:#f97316;background:rgba(249,115,22,0.04);}' +
            '.pdv3-proses.tamam {border-color:#10b981;background:rgba(16,185,129,0.04);}' +
            '.pdv3-proses-head {display:flex;align-items:center;gap:8px;margin-bottom:5px;}' +
            '.pdv3-ikon {' +
                'width:22px;height:22px;border-radius:6px;font-size:11px;' +
                'display:inline-flex;align-items:center;justify-content:center;' +
                'flex-shrink:0;font-weight:700;' +
            '}' +
            '.pdv3-proses-adi {flex:1;font-size:13px;font-weight:600;color:#111827;}' +
            '.pdv3-rozet {' +
                'font-size:9px;font-weight:700;text-transform:uppercase;' +
                'padding:1px 6px;border-radius:6px;color:#fff;' +
            '}' +
            '.pdv3-bar-wrap {height:4px;background:#f3f4f6;border-radius:2px;overflow:hidden;margin:4px 0;}' +
            '.pdv3-bar {height:100%;border-radius:2px;transition:width 0.3s;}' +
            '.pdv3-detay {' +
                'display:flex;justify-content:space-between;font-size:11px;' +
                'color:#6b7280;font-family:var(--mono,monospace);' +
            '}' +
            '.pdv3-detay-kaynak {' +
                'font-size:9px;color:#9ca3af;text-transform:uppercase;' +
                'letter-spacing:0.5px;margin-top:3px;' +
            '}' +
            // ANA EMIR SECONDARY
            '.pdv3-ana-secondary {' +
                'border-top:1px dashed #d1d5db;margin-top:18px;padding:10px 14px;' +
                'background:#f9fafb;border-radius:0 0 6px 6px;' +
            '}' +
            '.pdv3-ana-baslik {' +
                'font-size:10px;font-weight:700;color:#9ca3af;' +
                'text-transform:uppercase;letter-spacing:0.6px;margin-bottom:6px;' +
            '}' +
            '.pdv3-ana-baslik small {font-weight:500;font-family:var(--mono,monospace);}' +
            '.pdv3-ana-satirlar {display:flex;flex-direction:column;gap:2px;}' +
            '.pdv3-ana-proses {' +
                'display:flex;align-items:center;gap:10px;font-size:11px;' +
                'color:#6b7280;padding:3px 0;' +
            '}' +
            '.pdv3-ana-ikon {width:14px;text-align:center;color:#9ca3af;}' +
            '.pdv3-ana-adi {font-weight:600;color:#374151;flex:1;}' +
            '.pdv3-ana-kod {color:#9ca3af;font-family:var(--mono,monospace);}' +
            '.pdv3-ana-deger {' +
                'font-family:var(--mono,monospace);color:#6b7280;font-weight:500;' +
            '}' +
            '.pdv3-ana-zaman {color:#9ca3af;font-style:italic;font-size:10px;}' +
            // BOS DURUM
            '.pdv3-empty,.pdv3-loading,.pdv3-error {' +
                'text-align:center;padding:24px;font-size:13px;' +
            '}' +
            '.pdv3-loading {color:#9ca3af;}' +
            '.pdv3-empty {color:#9ca3af;font-style:italic;}' +
            '.pdv3-error {color:#dc2626;}' +
            '';
        document.head.appendChild(st);
    }

    function _terminGosterim(termIso) {
        if (!termIso) return '<span style="color:#9ca3af;">-</span>';
        var t = new Date(termIso);
        if (isNaN(t.getTime())) return '<span style="color:#9ca3af;">-</span>';
        var bugun = new Date(); bugun.setHours(0, 0, 0, 0);
        var hedef = new Date(t.getFullYear(), t.getMonth(), t.getDate());
        var fark = Math.round((hedef - bugun) / 86400000);
        var renk = '#10b981';
        var etiket = fark + ' gün';
        if (fark < 0) { renk = '#dc2626'; etiket = Math.abs(fark) + ' gün geçti'; }
        else if (fark === 0) { renk = '#dc2626'; etiket = 'Bugün'; }
        else if (fark <= 7) renk = '#dc2626';
        else if (fark <= 30) renk = '#f59e0b';
        var str = String(t.getFullYear()) + '-' +
            String(t.getMonth() + 1).padStart(2, '0') + '-' +
            String(t.getDate()).padStart(2, '0');
        return _esc(str) + ' <span class="pdv3-pill" style="background:' +
            renk + ';">' + etiket + '</span>';
    }

    function _zamanRel(iso) {
        if (!iso) return '';
        var t = new Date(iso);
        if (isNaN(t.getTime())) return '';
        var fark = Math.round((Date.now() - t.getTime()) / 86400000);
        if (fark === 0) return 'bugün';
        if (fark === 1) return 'dün';
        if (fark > 0) return fark + ' gün önce';
        return '';
    }

    function _siralaUretim(prosesler) {
        var copy = (prosesler || []).slice();
        copy.sort(function (a, b) {
            var na = parseInt(a.proses_kod, 10);
            var nb = parseInt(b.proses_kod, 10);
            if (isNaN(na)) na = 9999;
            if (isNaN(nb)) nb = 9999;
            return na - nb;
        });
        return copy;
    }

    // İlk TAMAM olmayan proses
    function _ilkTamamOlmayan(prosesler) {
        var sirali = _siralaUretim(prosesler);
        for (var i = 0; i < sirali.length; i++) {
            if (sirali[i].durum !== 'tamam') return sirali[i];
        }
        return null;
    }

    // Proses kart
    function _prosesKart(p, takildiKod) {
        var takildi = (takildiKod && p.proses_kod === takildiKod);
        var cls = 'pdv3-proses';
        var rozetText = (p.durum || '').toUpperCase();
        var rozetRenk = '#6b7280';
        var ikonRenk = '#9ca3af', ikonBg = '#f3f4f6', ikonText = '⏳';
        var barRenk = '#9ca3af';

        if (p.durum === 'tamam') {
            cls += ' tamam';
            rozetText = 'TAMAM';
            rozetRenk = '#10b981';
            ikonBg = '#10b981'; ikonRenk = '#fff'; ikonText = '\u2713';
            barRenk = '#10b981';
        } else if (takildi) {
            cls += ' takildi';
            rozetText = 'TAKILDI';
            rozetRenk = '#f97316';
            ikonBg = '#f97316'; ikonRenk = '#fff'; ikonText = '\u25CF';
            barRenk = '#f97316';
        } else if (p.durum === 'devam') {
            rozetText = 'DEVAM';
            rozetRenk = '#3b82f6';
            ikonBg = '#3b82f6'; ikonRenk = '#fff'; ikonText = '\u25CF';
            barRenk = '#3b82f6';
        } else {
            rozetText = 'BEKLİYOR';
        }

        var bar = Math.min(100, p.yuzde || 0);
        var sonTxt = _zamanRel(p.son_tarih);
        var kaynaklar = (p.kaynaklar || []).join('+').toUpperCase();

        return '<div class="' + cls + '">' +
            '<div class="pdv3-proses-head">' +
                '<span class="pdv3-ikon" style="background:' + ikonBg +
                ';color:' + ikonRenk + ';">' + ikonText + '</span>' +
                '<span class="pdv3-proses-adi">' +
                _esc(p.proses_adi || p.proses_kod) +
                ' <span style="font-size:10px;color:#9ca3af;font-weight:400;">[' +
                _esc(p.proses_kod) + ']</span></span>' +
                '<span class="pdv3-rozet" style="background:' + rozetRenk +
                ';">' + rozetText + '</span>' +
            '</div>' +
            '<div class="pdv3-bar-wrap"><div class="pdv3-bar" ' +
                'style="width:' + bar + '%;background:' + barRenk + ';"></div></div>' +
            '<div class="pdv3-detay">' +
                '<span>' + _fmt(p.yapilan) + ' / ' + _fmt(p.toplam_hedef) +
                ' (' + p.yuzde + '%)</span>' +
                '<span>' + (sonTxt ? 'Son: ' + sonTxt : '') + '</span>' +
            '</div>' +
            (kaynaklar ? '<div class="pdv3-detay-kaynak">' + kaynaklar + '</div>' : '') +
        '</div>';
    }

    function _detayHtml(d) {
        var hedef = Number(d.hedef || 0);
        var yapilan = Number(d.yapilan || 0);
        var korgunY = Number(d.yapilan_korgun || 0);
        var cpsY = Number(d.yapilan_cps || 0);
        var yuzde = hedef > 0 ? Math.round((yapilan / hedef) * 1000) / 10 : 0;
        var yrenk = '#dc2626';
        if (yuzde >= 70) yrenk = '#10b981';
        else if (yuzde >= 30) yrenk = '#f59e0b';

        var sipsTxt = '-';
        if (Array.isArray(d.siparisler) && d.siparisler.length) {
            sipsTxt = d.siparisler.map(function (s) { return s.sip_no; }).join(', ');
        }

        var html = '<div class="pdv3-icerik">';

        // 1. ÜST META
        html += '<div class="pdv3-meta">' +
            '<div class="pdv3-meta-item"><span class="label">Sipariş</span>' +
                '<span class="val mono">' + _esc(sipsTxt) + '</span></div>' +
            '<div class="pdv3-meta-item"><span class="label">Müşteri</span>' +
                '<span class="val">' + _esc(d.musteri || '-') + '</span></div>' +
            '<div class="pdv3-meta-item" style="grid-column:span 2;">' +
                '<span class="label">Model</span>' +
                '<span class="val" title="' + _esc(d.model_adi || '') + '" ' +
                'style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' +
                _esc(d.model_adi || d.model_kod || '-') + '</span></div>' +
            '<div class="pdv3-meta-item"><span class="label">Termin</span>' +
                '<span class="val">' + _terminGosterim(d.termin) + '</span></div>' +
            '<div class="pdv3-meta-item"><span class="label">Lokasyon</span>' +
                '<span class="val mono">' + _esc(d.location || '-') + '</span></div>' +
            '<div class="pdv3-meta-item"><span class="label">Hedef</span>' +
                '<span class="val">' + _fmt(hedef) + '</span></div>' +
            '<div class="pdv3-meta-item"><span class="label">Yapılan</span>' +
                '<span class="val">' + _fmt(yapilan) +
                ' <span class="pdv3-pill" style="background:' + yrenk +
                ';">' + yuzde + '%</span></span>' +
                '<span class="breakdown">Korgun ' + _fmt(korgunY) +
                ' + CPS ' + _fmt(cpsY) + '</span></div>' +
            '<div class="pdv3-meta-item"><span class="label">Kalan</span>' +
                '<span class="val">' + _fmt(d.kalan || 0) + '</span></div>' +
            '<div class="pdv3-meta-item"><span class="label">Tip</span>' +
                '<span class="val">' + _esc(d.tip_aciklama || d.tip || '-') +
                '</span></div>' +
        '</div>';

        // 2. TAKILDI BANDI
        var t = d.takildi;
        if (t) {
            var bantCls = 'pdv3-takildi';
            var bantIkon = '\u25CF';  // dolu daire
            var rozetEt = (t.durum || 'bekliyor').toUpperCase();
            var rozetBg = '#f97316';
            if (t.durum === 'tamam') {
                bantCls += ' tamam';
                bantIkon = '\u2713';
                rozetEt = 'TAMAM';
                rozetBg = '#10b981';
            } else if (t.durum === 'bekliyor') {
                rozetEt = 'TAKILDI';
            } else {
                rozetEt = 'TAKILDI';
            }
            var sonStr = _zamanRel(t.son_tarih);
            html += '<div class="' + bantCls + '">' +
                '<span class="pdv3-takildi-ikon">' + bantIkon + '</span>' +
                '<span class="pdv3-takildi-etiket" style="background:' + rozetBg +
                ';">' + rozetEt + '</span>' +
                '<span class="pdv3-takildi-yer">' +
                '<strong>' + _esc(t.kategori || '-') + '</strong> &rarr; ' +
                '<strong>' + _esc(t.proses_adi || '-') + '</strong></span>' +
                '<span class="pdv3-takildi-zaman">' + (sonStr || '-') + '</span>' +
            '</div>';
        } else {
            // Hiç bekleyen yok = hepsi tamam, ya da hiç hareket yok
            html += '<div class="pdv3-takildi tamam">' +
                '<span class="pdv3-takildi-ikon">\u2713</span>' +
                '<span class="pdv3-takildi-etiket" style="background:#10b981;">TAMAM</span>' +
                '<span class="pdv3-takildi-yer">Tüm prosesler tamamlandı veya henüz başlamadı</span>' +
            '</div>';
        }

        // 3. ALT PARÇALAR (Atki, Govde, ...)
        var altParcalar = d.alt_parcalar || [];
        for (var i = 0; i < altParcalar.length; i++) {
            var ap = altParcalar[i];
            var kat = ap.kategori || 'Diğer';
            var ikon = '\ud83d\udce6';
            var tipKlasi = 'tip-diger';
            if (kat === 'Atkı') { ikon = '\ud83e\udeb0'; tipKlasi = 'tip-atki'; }
            else if (kat === 'Gövde') { ikon = '\ud83e\uddb6'; tipKlasi = 'tip-govde'; }
            else if (kat === 'Taban') { ikon = '\ud83d\udc5f'; tipKlasi = 'tip-taban'; }
            else if (kat === 'Saya') { ikon = '\ud83e\uddf5'; tipKlasi = 'tip-saya'; }

            var prosesler = _siralaUretim(ap.prosesler || []);
            var takildiP = _ilkTamamOlmayan(prosesler);
            var takildiKod = takildiP ? takildiP.proses_kod : null;

            html += '<div class="pdv3-blok ' + tipKlasi + '">' +
                '<div class="pdv3-blok-baslik">' +
                    '<span class="pdv3-blok-ikon">' + ikon + '</span>' +
                    '<span class="pdv3-blok-ad">' + _esc(kat).toUpperCase() + '</span>' +
                    '<span class="pdv3-blok-emir">E.' + _esc(ap.emir_no) + '</span>' +
                    '<span class="pdv3-blok-model" title="' + _esc(ap.model_adi || '') + '">' +
                    _esc(ap.model_kod) + ' &middot; ' +
                    _esc(ap.model_adi || '-') + '</span>' +
                '</div>';

            if (prosesler.length === 0) {
                html += '<div class="pdv3-empty">Henüz proses kaydı yok.</div>';
            } else {
                html += '<div class="pdv3-proses-grid">';
                for (var j = 0; j < prosesler.length; j++) {
                    html += _prosesKart(prosesler[j], takildiKod);
                }
                html += '</div>';
            }
            html += '</div>';
        }

        // 4. ANA EMİR (secondary, küçük, en altta)
        var anaPros = _siralaUretim(d.ana_prosesleri || []);
        if (anaPros.length > 0) {
            html += '<div class="pdv3-ana-secondary">' +
                '<div class="pdv3-ana-baslik">ANA EMİR PROSESLERİ ' +
                '<small>(referans &middot; E.' + _esc(d.emir_no) + ')</small></div>' +
                '<div class="pdv3-ana-satirlar">';
            for (var k = 0; k < anaPros.length; k++) {
                var p = anaPros[k];
                var ikonAna = (p.durum === 'tamam') ? '\u2713' :
                              (p.durum === 'devam') ? '\u25CF' : '\u23F3';
                var sonStr2 = _zamanRel(p.son_tarih);
                html += '<div class="pdv3-ana-proses">' +
                    '<span class="pdv3-ana-ikon">' + ikonAna + '</span>' +
                    '<span class="pdv3-ana-adi">' + _esc(p.proses_adi) + '</span>' +
                    '<span class="pdv3-ana-kod">[' + _esc(p.proses_kod) + ']</span>' +
                    '<span class="pdv3-ana-deger">' + _fmt(p.yapilan) + ' / ' +
                    _fmt(p.toplam_hedef) + '</span>' +
                    (sonStr2 ? '<span class="pdv3-ana-zaman">' + sonStr2 + '</span>' : '') +
                '</div>';
            }
            html += '</div></div>';
        }

        html += '</div>'; // .pdv3-icerik
        return html;
    }

    function _kapat() {
        var detayTr = document.querySelector('#planBody tr.plan-detay-row');
        if (detayTr && detayTr.parentNode) detayTr.parentNode.removeChild(detayTr);
        var aktifTr = document.querySelector('#planBody tr.plan-row.acik');
        if (aktifTr) aktifTr.classList.remove('acik');
        aktifEmir = null;
    }

    function _ac(emirNo, srcTr) {
        if (loading) return;
        if (aktifEmir === String(emirNo)) {
            _kapat();
            return;
        }
        _kapat();

        loading = true;
        aktifEmir = String(emirNo);
        srcTr.classList.add('acik');

        var ld = document.createElement('tr');
        ld.className = 'plan-detay-row';
        ld.dataset.detayFor = emirNo;
        ld.innerHTML = '<td colspan="' + TOPLAM_KOLON + '">' +
            '<div class="pdv3-icerik"><div class="pdv3-loading">' +
            'Yükleniyor...</div></div></td>';
        srcTr.parentNode.insertBefore(ld, srcTr.nextSibling);

        fetch('/hedef/plan-detay/' + encodeURIComponent(emirNo), {
            credentials: 'include'
        })
            .then(function (r) {
                return r.json().then(function (d) {
                    return { status: r.status, data: d };
                });
            })
            .then(function (r) {
                loading = false;
                var td = ld.querySelector('td');
                if (!td) return;
                if (r.status >= 400 || !r.data || !r.data.ok) {
                    td.innerHTML = '<div class="pdv3-icerik">' +
                        '<div class="pdv3-error">' +
                        _esc((r.data && r.data.mesaj) || 'Veri alınamadı') +
                        '</div></div>';
                    return;
                }
                td.innerHTML = _detayHtml(r.data);
            })
            .catch(function (e) {
                loading = false;
                var td = ld.querySelector('td');
                if (td) {
                    td.innerHTML = '<div class="pdv3-icerik">' +
                        '<div class="pdv3-error">Sunucuya ulaşılamadı: ' +
                        _esc(e.message) + '</div></div>';
                }
            });
    }

    _ensureStyle();

    // Click delegation - PLAN tablosu
    document.addEventListener('click', function (ev) {
        if (ev.target.closest('button, a, input, select, .tab-x')) return;
        if (ev.target.closest('#planBody tr.plan-detay-row')) return;
        var tr = ev.target.closest('#planBody tr');
        if (!tr) return;
        if (tr.classList.contains('plan-detay-row')) return;
        var en = tr.dataset.emirNo;
        if (!en) {
            var ilkTd = tr.querySelector('td:nth-child(2)');
            if (ilkTd) {
                var m = (ilkTd.textContent || '').match(/(\d+)/);
                if (m) en = m[1];
            }
        }
        if (!en) return;
        _ac(en, tr);
    }, false);

    document.addEventListener('keydown', function (ev) {
        if (ev.key === 'Escape') _kapat();
    });

    // renderPlanRows monkey-patch - data-emir-no garanti et
    if (typeof window.renderPlanRows === 'function' && !window._origRenderRowsV3) {
        window._origRenderRowsV3 = window.renderPlanRows;
        window.renderPlanRows = function (emirler) {
            _kapat();
            var ret = window._origRenderRowsV3.apply(this, arguments);
            var rows = document.querySelectorAll('#planBody tr');
            for (var i = 0; i < rows.length; i++) {
                var tr = rows[i];
                if (tr.classList.contains('plan-detay-row')) continue;
                if (tr.dataset.emirNo) {
                    tr.classList.add('plan-row');
                    continue;
                }
                var ilkTd = tr.querySelector('td:nth-child(2)');
                if (ilkTd) {
                    var m = (ilkTd.textContent || '').match(/(\d+)/);
                    if (m) {
                        tr.dataset.emirNo = m[1];
                        tr.classList.add('plan-row');
                    }
                }
            }
            return ret;
        };
    }

    console.log('[CPS LOCAL] PLAN detay v3 yuklendi');
})();
'''


def backup(path):
    if not os.path.exists(path):
        return None
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bp = path + f'.bak_{ts}'
    shutil.copy2(path, bp)
    return bp


def patch_routes():
    print()
    print("=" * 64)
    print("1/2 BACKEND: /hedef/plan-detay v1 -> v3")
    print("=" * 64)
    if not os.path.exists(HEDEF_ROUTES):
        print(f"  [HATA] {HEDEF_ROUTES} yok.")
        return False
    with open(HEDEF_ROUTES, 'r', encoding='utf-8') as f:
        src = f.read()
    if ROUTES_MARKER in src:
        print("  [BILGI] V3 zaten ekli.")
        return True
    if V1_BLOK_TAM not in src:
        print("  [HATA] V1 bloku bulunamadi.")
        return False
    if src.count(V1_BLOK_TAM) > 1:
        print("  [HATA] V1 bloku cogul.")
        return False

    new_src = src.replace(V1_BLOK_TAM, V3_BLOK, 1)

    try:
        ast.parse(new_src)
    except SyntaxError as e:
        print(f"  [HATA] parse: {e}")
        return False

    bp = backup(HEDEF_ROUTES)
    print(f"  [OK] Yedek: {bp}")
    with open(HEDEF_ROUTES, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] V3 endpoint eklendi.")
    return True


def patch_js():
    print()
    print("=" * 64)
    print("2/2 FRONTEND: PLAN detay v3 IIFE")
    print("=" * 64)
    if not os.path.exists(JS_PATH):
        print(f"  [HATA] {JS_PATH} yok.")
        return False
    with open(JS_PATH, 'r', encoding='utf-8') as f:
        src = f.read()
    if JS_MARKER in src:
        print("  [BILGI] V3 IIFE zaten ekli.")
        return True
    new_src = src
    if not new_src.endswith('\n'):
        new_src += '\n'
    new_src += JS_BLOCK

    bp = backup(JS_PATH)
    print(f"  [OK] Yedek: {bp}")
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_src)
    print("  [OK] V3 IIFE eklendi (eski v2'yi override eder).")
    return True


def main():
    print("=" * 64)
    print("PLAN DETAY v3 - HİYERARŞİK")
    print("=" * 64)
    print("Yapilanlar:")
    print("  - Backend: v1 endpoint -> v3 (Atki/Gov\u030cde + Korgun+CPS birlesik)")
    print("  - Frontend: Yeni IIFE - takildi bandi + bloklar + ana secondary")
    print("  - Atki/Gov\u030cde dinamik sira (en geride ustte)")
    print("  - Rozet: TAKILDI/DEVAM/TAMAM")
    print("  - Proses sirasi: uretim sirasi (proses_kod numerik)")
    print("  - Takildi: ilk TAMAM olmayan proses")

    ok1 = patch_routes()
    ok2 = patch_js()

    print()
    if ok1 and ok2:
        print("TAMAM.")
        print()
        print("YAPILACAK:")
        print("  Flask debug mode otomatik restart yapar.")
        print("  Browser Ctrl+F5.")
        print()
        print("BEKLENEN:")
        print("  E.110626 satira tikla:")
        print("  1) Ust meta (Korgun+CPS breakdown)")
        print("  2) TAKILDI bandi (ornek: 'Atki -> Capak' veya 'Govde -> Enjeksiyon')")
        print("  3) Atki blok (mor sol cizgi)")
        print("  4) Govde blok (mavi sol cizgi)")
        print("  5) Ana emir (en altta, kucuk gri)")
        print()
        print("Console: [CPS LOCAL] PLAN detay v3 yuklendi")
        return 0
    print("BAZI ADIMLAR BASARISIZ.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
