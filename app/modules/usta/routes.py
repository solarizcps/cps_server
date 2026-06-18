# -*- coding: utf-8 -*-
"""CPS DEV - Usta Routes (Faz 4.2 + FAZ2 Uretim Kayit)

Mobile-first usta paneli.

Endpoint'ler:
    GET  /usta/                         - Ana panel HTML
    GET  /usta/api/gorevler             - Planlama gorev listesi
    POST /usta/api/gorev/<id>/okudu     - ATANDI -> OKUNDU
    POST /usta/api/gorev/<id>/basladi   - OKUNDU -> BASLADI
    POST /usta/api/gorev/<id>/bitti     - BASLADI -> TAMAMLANDI

    GET  /usta/api/onumdeki-isler       - Korgun'dan hat bazli bekleyen emirler
    GET  /usta/api/personel-listesi     - CPS personel (ekip secimi icin)
    POST /usta/api/uretim-kayit         - CPS DB'ye uretim hareketi yaz

    GET  /usta/api/emir-sorgula         - FAZ 2C-2: Korgun emir durum sorgusu
    POST /usta/api/emir-ilerlet         - FAZ 2C-5A: Proses ilerletme (test modu)

Yetki:
    Login yapmis herhangi bir kullanici.
"""
from flask import (Blueprint, render_template, redirect, url_for,
                   request, session, abort)
from functools import wraps

usta_bp = Blueprint('usta', __name__, url_prefix='/usta')


def _usta_yetkili_mi():
    u = session.get('kullanici')
    if not u:
        return False
    # Login yapmis herkes USTA panele erisebilir.
    # Hedef sayfasi sadece admin/yonetim, USTA panel daha genis kapsam.
    # Veri kapsamini service_usta.py icindeki rol parametresi ayarliyor.
    return True


def usta_yetkili(f):
    """Decorator: login zorunlu. Rol kontrolu MES v2 servis katmaninda."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('kullanici'):
            return redirect(url_for('auth.login', next=request.path))
        if not _usta_yetkili_mi():
            abort(403)
        return f(*args, **kwargs)
    return wrapper


# ============== ANA PANEL ==============
@usta_bp.route('/')
@usta_yetkili
def panel():
    """Usta ana paneli - 3 sekme."""
    return render_template('usta/index.html')


# ============== FAZ 4.3 - GOREV ENDPOINTLERI ==============
# Karar Masasi -> Usta Paneli pilot baglantisi
# uretim_kayit ile iliskisi yok, tamamen izole sandbox

from flask import jsonify, request as _flask_request
from . import gorev_db as _gorev_db


@usta_bp.route('/api/gorevler', methods=['GET'])
@usta_yetkili
def gorevler_liste():
    """
    Usta gorev listesi.

    Query parametreleri:
        durum=acik|tamam|iptal|hepsi (default: acik)
        atanan=Hasan (opsiyonel, NULL olanlar da dahil)
    """
    durum_filtresi = _flask_request.args.get('durum', 'acik')
    atanan = _flask_request.args.get('atanan')

    sonuc = _gorev_db.gorev_listele(
        durum_filtresi=durum_filtresi,
        atanan=atanan
    )
    return jsonify(sonuc)


@usta_bp.route('/api/gorev/<int:gorev_id>/okudu', methods=['POST'])
@usta_yetkili
def gorev_okudu_endpoint(gorev_id):
    """ATANDI -> OKUNDU"""
    sonuc = _gorev_db.gorev_okudu(gorev_id)
    if not sonuc.get("ok"):
        if sonuc.get("hata") == "bulunamadi":
            return jsonify(sonuc), 404
        if sonuc.get("hata") == "durum_uyumsuz":
            return jsonify(sonuc), 409
        return jsonify(sonuc), 400
    return jsonify(sonuc)


@usta_bp.route('/api/gorev/<int:gorev_id>/basladi', methods=['POST'])
@usta_yetkili
def gorev_basladi_endpoint(gorev_id):
    """OKUNDU -> BASLADI"""
    sonuc = _gorev_db.gorev_basladi(gorev_id)
    if not sonuc.get("ok"):
        if sonuc.get("hata") == "bulunamadi":
            return jsonify(sonuc), 404
        if sonuc.get("hata") == "durum_uyumsuz":
            return jsonify(sonuc), 409
        return jsonify(sonuc), 400
    return jsonify(sonuc)


@usta_bp.route('/api/gorev/<int:gorev_id>/bitti', methods=['POST'])
@usta_yetkili
def gorev_bitti_endpoint(gorev_id):
    """BASLADI -> TAMAMLANDI (opsiyonel usta_notu)"""
    body = _flask_request.get_json(silent=True) or {}
    usta_notu = body.get('usta_notu')

    sonuc = _gorev_db.gorev_bitti(gorev_id, usta_notu=usta_notu)
    if not sonuc.get("ok"):
        if sonuc.get("hata") == "bulunamadi":
            return jsonify(sonuc), 404
        if sonuc.get("hata") == "durum_uyumsuz":
            return jsonify(sonuc), 409
        return jsonify(sonuc), 400
    return jsonify(sonuc)


# ============================================================
# FAZ 2 — ÜRETİM KAYIT ENDPOINTLERI
# ============================================================

_HAT_LISTESI = [
    {'kod': 'monta1',      'ad': 'Monta 1',    'proses': '30'},
    {'kod': 'monta2',      'ad': 'Monta 2',    'proses': '30'},
    {'kod': 'monta_bas1',  'ad': 'Monta Baş 1','proses': '28'},
    {'kod': 'monta_bas2',  'ad': 'Monta Baş 2','proses': '28'},
    {'kod': 'kesim',       'ad': 'Kesim',      'proses': '02'},
    {'kod': 'temizleme',   'ad': 'Temizleme',  'proses': '35'},
    {'kod': 'enjeksiyon',  'ad': 'Enjeksiyon', 'proses': '26'},
    {'kod': 'paketleme',   'ad': 'Paketleme',  'proses': '40'},
    {'kod': 'genel',       'ad': 'Genel',      'proses': None},
]


@usta_bp.route('/api/hat-listesi', methods=['GET'])
@usta_yetkili
def hat_listesi():
    """Hat / bölüm listesi."""
    return jsonify({'ok': True, 'hatlar': _HAT_LISTESI})


@usta_bp.route('/api/onumdeki-isler', methods=['GET'])
@usta_yetkili
def onumdeki_isler():
    """
    Korgun'dan hat/proses bazli bekleyen emirler (Urt_Wait_gch).

    Query:
        hat_kodu = monta1 / kesim / temizleme / enjeksiyon / genel
        sip_no   = (opsiyonel) siparis filtresi
    """
    hat_kodu = _flask_request.args.get('hat_kodu', 'genel')
    sip_no_filtre = _flask_request.args.get('sip_no')

    # Hat kodundan proses bul
    hat_proses = None
    hat_adi = hat_kodu
    for h in _HAT_LISTESI:
        if h['kod'] == hat_kodu:
            hat_proses = h['proses']
            hat_adi = h['ad']
            break

    try:
        from modules.common.korgun import _baglan
        con = _baglan()
        try:
            cur = con.cursor()

            # Bekleyen emirler: Wait'te Cikan=0 (tamamlanmamis)
            proses_filtre_sql = ''
            params = []
            if hat_proses:
                proses_filtre_sql = 'AND w.Proses = %s'
                params.append(hat_proses)

            sip_filtre_sql = ''
            if sip_no_filtre:
                try:
                    sip_no_filtre = int(sip_no_filtre)
                    sip_filtre_sql = 'AND w.FisNo = %s'
                    params.append(sip_no_filtre)
                except ValueError:
                    pass

            cur.execute(f"""
                SELECT TOP 50
                    w.EmirNo,
                    w.FisNo AS SipNo,
                    w.SKOD,
                    w.Proses,
                    ISNULL(pm.Tanim, w.Proses) AS ProsesAdi,
                    SUM(ISNULL(w.Giren, 0) - ISNULL(w.Cikan, 0)) AS BekleyenMiktar,
                    w.Birim,
                    ISNULL(e.Notu, '') AS EmirNotu,
                    ISNULL(sk.CName, '-') AS MusteriAdi
                FROM Urt_Wait_gch w WITH(NOLOCK)
                LEFT JOIN Proses_M pm ON pm.Pro = w.Proses
                LEFT JOIN Urt_Emir e WITH(NOLOCK) ON e.EmirNo = w.EmirNo
                LEFT JOIN Siparis_Kay sk2 WITH(NOLOCK) ON sk2.SipNo = w.FisNo
                LEFT JOIN Cari_Kart sk WITH(NOLOCK) ON sk.CKod = sk2.CariKod
                WHERE ISNULL(w.Cikan, 0) < ISNULL(w.Giren, 0)
                  AND LTRIM(RTRIM(ISNULL(e.Durum, ''))) = ''
                  {proses_filtre_sql}
                  {sip_filtre_sql}
                GROUP BY w.EmirNo, w.FisNo, w.SKOD, w.Proses,
                         pm.Tanim, w.Birim, e.Notu, sk.CName
                ORDER BY w.FisNo DESC, w.EmirNo
            """, tuple(params))

            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            isler = []
            for r in rows:
                d = dict(zip(cols, r))
                isler.append({
                    'emir_no':        int(d['EmirNo']),
                    'sip_no':         int(d['SipNo']) if d['SipNo'] else None,
                    'skod':           d['SKOD'] or '',
                    'proses_kodu':    d['Proses'] or '',
                    'proses_adi':     d['ProsesAdi'] or '',
                    'bekleyen_miktar':int(float(d['BekleyenMiktar'] or 0)),
                    'birim':          d['Birim'] or 'CIFT',
                    'musteri_adi':    d['MusteriAdi'] or '-',
                })

            cur.close()
            return jsonify({
                'ok': True,
                'hat_kodu': hat_kodu,
                'hat_adi': hat_adi,
                'is_sayisi': len(isler),
                'isler': isler,
            })
        finally:
            con.close()
    except Exception as e:
        return jsonify({'ok': False, 'hata': f'{type(e).__name__}: {str(e)[:200]}', 'isler': []}), 500


@usta_bp.route('/api/personel-listesi', methods=['GET'])
@usta_yetkili
def personel_listesi():
    """CPS personel_kullanici tablosundan aktif personel listesi."""
    from db import q
    try:
        rows = q("""
            SELECT id, ad, AdSoyad, birim, Pozisyon
            FROM personel_kullanici
            WHERE aktif = 1
            ORDER BY ad
        """)
        personeller = []
        for r in rows:
            ad_goster = r.get('AdSoyad') or r.get('ad') or ''
            personeller.append({
                'id':     r['id'],
                'ad':     ad_goster,
                'birim':  r.get('birim') or '',
            })
        return jsonify({'ok': True, 'personeller': personeller})
    except Exception as e:
        return jsonify({'ok': False, 'hata': str(e)[:200], 'personeller': []}), 500


@usta_bp.route('/api/emir-sorgula', methods=['GET'])
@usta_yetkili
def emir_sorgula():
    """
    FAZ 2C-2: Korgun emir durumu sorgulama.

    GET /usta/api/emir-sorgula?emir_no=111631

    Sadece SELECT. Korgun'a hicbir yazma yapilmaz.

    Donus:
        {
            ok: true,
            emir: {emir_no, model_kod, model_adi, tip, durum, uretim_yeri, emir_tarihi},
            prosesler: [
                {
                    proses_kodu, proses_adi, fis_no, fis_harinx,
                    durum: 'bekliyor'|'tamamlandi',
                    toplam_giren, toplam_bekleyen,
                    bedenler: [{bed_kod, giren, cikan, bekleyen}, ...]
                }
            ],
            tamamlanan_prosesler: [
                {proses_kodu, proses_adi, toplam_giren, toplam_cikan, kayit_sayisi}
            ],
            cps_bekleyen: bool
        }
    """
    from db import get_conn
    try:
        from modules.common.korgun import _baglan as _korgun_baglan
    except Exception as e:
        return jsonify({'ok': False, 'hata': f'Korgun baglanti hatasi: {e}'}), 500

    emir_no_str = (_flask_request.args.get('emir_no') or '').strip()
    if not emir_no_str or not emir_no_str.isdigit():
        return jsonify({'ok': False, 'hata': 'emir_no eksik veya gecersiz'}), 400
    emir_no = int(emir_no_str)

    try:
        k_con = _korgun_baglan()
    except Exception as e:
        return jsonify({'ok': False, 'hata': f'Korgun baglanti hatasi: {type(e).__name__}: {str(e)[:200]}'}), 500

    try:
        k_cur = k_con.cursor()

        # ── 1) Urt_Emir bilgisi ──────────────────────────────────────────
        k_cur.execute("""
            SELECT e.EmirNo,
                   e.ModelKod,
                   ISNULL(m.Tanim, e.ModelKod)          AS ModelAdi,
                   LTRIM(RTRIM(ISNULL(e.Tip,'')))        AS Tip,
                   LTRIM(RTRIM(ISNULL(e.Durum,'')))      AS Durum,
                   ISNULL(e.Location,'')                 AS Location,
                   CONVERT(VARCHAR(10), e.EmirTarihi, 120) AS EmirTarihi
            FROM Urt_Emir e WITH(NOLOCK)
            LEFT JOIN Model_M m ON m.ModelKod = e.ModelKod
            WHERE e.EmirNo = %s
        """, (emir_no,))
        emir_row = k_cur.fetchone()

        if not emir_row:
            k_cur.close()
            k_con.close()
            return jsonify({'ok': False, 'hata': 'emir_bulunamadi',
                            'emir_no': emir_no}), 404

        emir_cols = [d[0] for d in k_cur.description]
        emir_d    = dict(zip(emir_cols, emir_row))

        emir_bilgi = {
            'emir_no'    : int(emir_d.get('EmirNo') or emir_no),
            'model_kod'  : str(emir_d.get('ModelKod') or '').strip(),
            'model_adi'  : str(emir_d.get('ModelAdi') or '').strip(),
            'tip'        : str(emir_d.get('Tip') or '').strip(),
            'durum'      : str(emir_d.get('Durum') or '').strip(),
            'uretim_yeri': str(emir_d.get('Location') or '').strip(),
            'emir_tarihi': str(emir_d.get('EmirTarihi') or ''),
        }

        # ── 2) Acik Wait satirlari (proses + beden kirilimi) ─────────────
        k_cur.execute("""
            SELECT w.Proses,
                   ISNULL(p.Tanim, w.Proses)             AS ProsesAdi,
                   w.FisNo, w.FisHarinx,
                   w.RKOD, w.BedKod,
                   w.Giren, w.Cikan,
                   ISNULL(w.Giren,0) - ISNULL(w.Cikan,0) AS Bekleyen
            FROM Urt_Wait_gch w WITH(NOLOCK)
            LEFT JOIN Proses_M p ON p.Pro = w.Proses
            WHERE w.EmirNo = %s
            ORDER BY w.Proses, w.BedKod
        """, (emir_no,))
        wait_rows = k_cur.fetchall()
        wait_cols = [d[0] for d in k_cur.description]

        # Proses bazinda grupla
        proses_map = {}
        for wr in wait_rows:
            wd = dict(zip(wait_cols, wr))
            p_kodu = str(wd.get('Proses') or '').strip()
            if p_kodu not in proses_map:
                proses_map[p_kodu] = {
                    'proses_kodu'   : p_kodu,
                    'proses_adi'    : str(wd.get('ProsesAdi') or p_kodu).strip(),
                    'fis_no'        : int(wd.get('FisNo') or 0),
                    'fis_harinx'    : int(wd.get('FisHarinx') or 0),
                    'toplam_giren'  : 0,
                    'toplam_bekleyen': 0,
                    'bedenler'      : [],
                }
            giren    = int(wd.get('Giren')   or 0)
            cikan    = int(wd.get('Cikan')   or 0)
            bekleyen = int(wd.get('Bekleyen') or 0)
            proses_map[p_kodu]['toplam_giren']   += giren
            proses_map[p_kodu]['toplam_bekleyen'] += bekleyen
            proses_map[p_kodu]['bedenler'].append({
                'bed_kod' : int(wd.get('BedKod') or 0),
                'giren'   : giren,
                'cikan'   : cikan,
                'bekleyen': bekleyen,
            })

        prosesler = []
        for p_kodu in sorted(proses_map.keys()):
            pm = proses_map[p_kodu]
            toplam_giren   = pm['toplam_giren']
            toplam_bekleyen = pm['toplam_bekleyen']
            toplam_cikan   = toplam_giren - toplam_bekleyen
            # 3-degerli durum: Korgun Wait tarafina gore
            if toplam_cikan <= 0:
                pm['durum'] = 'baslanmadi'
            elif toplam_cikan < toplam_giren:
                pm['durum'] = 'devam_ediyor'
            else:
                pm['durum'] = 'tamamlandi'
            pm['aktif_ilerletilebilir'] = toplam_bekleyen > 0
            prosesler.append(pm)

        # ── 3) Tamamlanmis Con kayitlari ozeti ───────────────────────────
        k_cur.execute("""
            SELECT c.Proses,
                   ISNULL(p.Tanim, c.Proses) AS ProsesAdi,
                   COUNT(*)                  AS KayitSayisi,
                   SUM(c.Giren)              AS TopGiren,
                   SUM(c.Cikan)              AS TopCikan
            FROM Urt_con_gch c WITH(NOLOCK)
            LEFT JOIN Proses_M p ON p.Pro = c.Proses
            WHERE c.EmirNo = %s
            GROUP BY c.Proses, p.Tanim
            ORDER BY c.Proses
        """, (emir_no,))
        con_rows = k_cur.fetchall()
        con_cols = [d[0] for d in k_cur.description]

        tamamlanan = []
        for cr in con_rows:
            cd = dict(zip(con_cols, cr))
            tamamlanan.append({
                'proses_kodu' : str(cd.get('Proses') or '').strip(),
                'proses_adi'  : str(cd.get('ProsesAdi') or '').strip(),
                'kayit_sayisi': int(cd.get('KayitSayisi') or 0),
                'toplam_giren': int(cd.get('TopGiren') or 0),
                'toplam_cikan': int(cd.get('TopCikan') or 0),
            })

        k_cur.close()
        k_con.close()

        # ── 4) CPS bekleyen kayit var mi ─────────────────────────────────
        cps_bekleyen = False
        try:
            cps_conn = get_conn()
            row_cps = cps_conn.execute(
                """
                SELECT COUNT(*) FROM uretim_kayit
                WHERE emir_no = ?
                  AND (korgun_yazildi IS NULL OR korgun_yazildi = 0)
                """,
                (emir_no,)
            ).fetchone()
            cps_bekleyen = bool(row_cps and row_cps[0] > 0)
            cps_conn.close()
        except Exception:
            pass

        return jsonify({
            'ok'                   : True,
            'emir'                 : emir_bilgi,
            'prosesler'            : prosesler,
            'tamamlanan_prosesler' : tamamlanan,
            'cps_bekleyen'         : cps_bekleyen,
        })

    except Exception as e:
        try:
            k_con.close()
        except Exception:
            pass
        return jsonify({'ok': False,
                        'hata': f'{type(e).__name__}: {str(e)[:300]}'}), 500


@usta_bp.route('/api/uretim-kayit', methods=['POST'])
@usta_yetkili
def uretim_kayit_yaz():
    """
    Üretim hareketi CPS DB'ye yazar (uretim_kayit + uretim_kayit_personel).

    Body (JSON):
        emir_no          int       zorunlu
        skod             str       zorunlu
        proses_kodu      str       zorunlu  (Korgun: '28', '30' vs)
        proses_adi       str
        hat_adi          str       Monta 1 / Monta 2 / Kesim ...
        toplam_miktar    int       zorunlu
        baslangic_saat   str       ISO veya HH:MM
        bitis_saat       str       ISO veya HH:MM
        sip_no           int
        korgun_fis_harinx str
        ekip             list[{personel_id, personel_ad, miktar}]
        not_metin        str
    """
    from db import get_conn
    from datetime import datetime

    body = _flask_request.get_json(silent=True) or {}
    kullanici = session.get('kullanici', {})
    usta_ad = (kullanici.get('AdSoyad') or kullanici.get('KullaniciAdi') or
               kullanici.get('kullanici_adi') or 'bilinmiyor')

    # Zorunlu alanlar
    emir_no = body.get('emir_no')
    skod = (body.get('skod') or '').strip()
    proses_kodu = (body.get('proses_kodu') or '').strip()
    toplam_miktar = body.get('toplam_miktar')

    if not emir_no or not skod or not proses_kodu or not toplam_miktar:
        return jsonify({'ok': False, 'hata': 'eksik_alan',
                        'mesaj': 'emir_no, skod, proses_kodu, toplam_miktar zorunlu'}), 400
    try:
        toplam_miktar = int(toplam_miktar)
        emir_no = int(emir_no)
        if toplam_miktar <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({'ok': False, 'hata': 'gecersiz_miktar'}), 400

    simdi = datetime.now()
    tarih_str = simdi.strftime('%Y-%m-%d')
    saat_str = simdi.strftime('%H:%M')

    hat_adi = (body.get('hat_adi') or '').strip()
    proses_adi = (body.get('proses_adi') or proses_kodu).strip()
    baslangic_saat = (body.get('baslangic_saat') or '').strip() or None
    bitis_saat = (body.get('bitis_saat') or saat_str).strip()
    not_metin = (body.get('not_metin') or '').strip() or None
    sip_no = body.get('sip_no')
    korgun_fis_no = str(sip_no) if sip_no else None
    korgun_fis_harinx = (body.get('korgun_fis_harinx') or '').strip() or None
    ekip = body.get('ekip') or []

    conn = get_conn()
    try:
        cur = conn.cursor()

        # uretim_kayit INSERT
        cur.execute("""
            INSERT INTO uretim_kayit
              (emir_no, model_kod, model_adi, miktar, proses_kodu, proses_adi,
               personel_id, personel_ad, tarih, saat, not_metin, onay_durum,
               usta_id, usta_ad, kaynak,
               hat_adi, baslangic_saat, bitis_saat,
               korgun_yazildi, korgun_emir_no, korgun_proses_kodu,
               korgun_fis_no, korgun_fis_harinx)
            VALUES
              (?, ?, ?, ?, ?, ?,
               ?, ?, ?, ?, ?, ?,
               ?, ?, ?,
               ?, ?, ?,
               ?, ?, ?,
               ?, ?)
        """, (
            emir_no, skod, skod, toplam_miktar, proses_kodu, proses_adi,
            None, None, tarih_str, saat_str, not_metin, 'bekliyor',
            None, usta_ad, 'CPS_USTA',
            hat_adi or None, baslangic_saat, bitis_saat,
            0, str(emir_no), proses_kodu,
            korgun_fis_no, korgun_fis_harinx,
        ))
        kayit_id = cur.lastrowid

        # uretim_kayit_personel — ekip kırılımı
        ekip_toplam = 0
        for p in ekip:
            p_id = p.get('personel_id')
            p_ad = (p.get('personel_ad') or '').strip()
            p_miktar = p.get('miktar', 0)
            try:
                p_miktar = int(p_miktar)
            except (ValueError, TypeError):
                p_miktar = 0
            if p_miktar <= 0 and not p_ad:
                continue
            ekip_toplam += p_miktar
            cur.execute("""
                INSERT INTO uretim_kayit_personel
                  (kayit_id, personel_id, personel_ad, miktar, kaynak)
                VALUES (?, ?, ?, ?, ?)
            """, (kayit_id, p_id, p_ad, p_miktar, 'CPS_USTA'))

        conn.commit()
        cur.close()

        return jsonify({
            'ok': True,
            'kayit_id': kayit_id,
            'emir_no': emir_no,
            'skod': skod,
            'proses_kodu': proses_kodu,
            'toplam_miktar': toplam_miktar,
            'ekip_toplam': ekip_toplam,
            'usta_ad': usta_ad,
            'tarih': tarih_str,
            'saat': saat_str,
            'korgun_yazildi': 0,
            'mesaj': f'Kayit oluşturuldu. (#{kayit_id})',
        })
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({'ok': False, 'hata': f'{type(e).__name__}: {str(e)[:300]}'}), 500
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────
# FAZ 2C-5A: POST /usta/api/emir-ilerlet
# ─────────────────────────────────────────────────────────────────
@usta_bp.route('/api/emir-ilerlet', methods=['POST'])
def emir_ilerlet():
    """FAZ 2C-5A - Test modu: Korgun'a yazma YOK.

    Body (JSON):
        emir_no   : str  – üretim emir numarası
        proses_no : str  – proses kodu (örn. "02")
        kalan     : int  – bekleyen miktar
    """
    from flask import session
    if not session.get('kullanici'):
        return jsonify({'success': False, 'message': 'Oturum gerekli.'}), 401

    data = {}
    try:
        import flask
        data = flask.request.get_json(force=True, silent=True) or {}
    except Exception:
        pass

    emir_no   = str(data.get('emir_no',   '')).strip()
    proses_no = str(data.get('proses_no', '')).strip()
    kalan     = data.get('kalan', 0)

    if not emir_no or not proses_no:
        return jsonify({'success': False, 'message': 'emir_no ve proses_no zorunlu.'}), 400

    # FAZ 2C-5A: Korgun'a yazma KAPALI — sadece test yanıtı döner
    return jsonify({
        'success': True,
        'message': f'Test ilerletme hazır — Emir {emir_no} / Proses {proses_no} / Kalan {kalan}',
        'test_modu': True,
        'korgun_yazildi': False,
    })
