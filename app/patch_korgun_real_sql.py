"""PATCH: korgun_v2.py'de gercek Korgun SQL'e gec.

Yapilan:
1. MOCK_MODE = False
2. get_siparis_listesi: Korgun SQL ile aktif siparisleri cek
3. get_siparis_detay_v2: tek siparis icin tum emirler + prosesler

KORGUN TABLOLARI:
- Siparis_Kay (sipariş başlık)
- Siparis_Har (sipariş kalemleri)
- Cari_Kart (müşteri)
- Urt_Emir / Urtx_Emir (emir başlık)
- Urt_Em_gch (emir-fis bağlantısı)
- Urt_Em2Em (emir-alt emir bağlantısı)
- Urt_con_gch / Urtx_con_gch (proses hareketleri - biten)
- Urt_wait_gch / Urtx_wait_gch (başlayacak)
- Urt_Fin_gch / Urtx_Fin_gch (final - genelde boş)
- Proses_M (proses adı sözlüğü)
"""
import io, sys, shutil, time

KP = r'C:\cps_dev\modules\hedef\korgun_v2.py'
MARKER = '/* CANLI SQL */'

with io.open(KP, 'r', encoding='utf-8') as f:
    src = f.read()

if MARKER in src:
    print('SKIP: canli SQL zaten uygulanmis')
    sys.exit(0)

# 1) MOCK_MODE = False
OLD_MOCK = "MOCK_MODE = True"
NEW_MOCK = "MOCK_MODE = False  # /* CANLI SQL */"

if OLD_MOCK not in src:
    print('UYARI: MOCK_MODE flag bulunamadi (devam)')
else:
    src = src.replace(OLD_MOCK, NEW_MOCK, 1)

# 2) Korgun bağlantı helper'ı dosyanın sonuna ekle (eğer yoksa)
KORGUN_HELPERS = '''


# === CANLI SQL FONKSIYONLARI === /* CANLI SQL */
def _korgun_baglan():
    """Korgun MSSQL baglantisi."""
    import pytds
    from config import Config
    return pytds.connect(
        server=getattr(Config, 'KORGUN_HOST', '25.7.184.221'),
        database=getattr(Config, 'KORGUN_DB', 'Solariz22'),
        user=getattr(Config, 'KORGUN_USER', 'claude'),
        password=getattr(Config, 'KORGUN_PASS', '104099'),
        port=int(getattr(Config, 'KORGUN_PORT', 1433)),
        timeout=30, login_timeout=10,
    )


def _sql_get_siparis_listesi():
    """Aktif siparisler + emir/proses ozeti."""
    con = _korgun_baglan()
    try:
        cur = con.cursor()

        # 1) Aktif siparisler
        cur.execute("""
            SELECT
                sk.SipNo,
                ISNULL(ck.CName, '-') AS CariAdi,
                sh.SKOD AS ModelKod,
                ISNULL(sm.Tanim, sh.SKOD) AS ModelAdi,
                sh.Miktar AS Hedef,
                CONVERT(VARCHAR(10), sh.TerminTarihi, 120) AS Termin,
                sk.BelgeNo,
                sk.CariKod
            FROM Siparis_Kay sk WITH (NOLOCK)
            INNER JOIN Siparis_Har sh WITH (NOLOCK) ON sh.SipNo = sk.SipNo
            LEFT JOIN Cari_Kart ck WITH (NOLOCK) ON ck.CKod = sk.CariKod
            LEFT JOIN StokKart sm WITH (NOLOCK) ON sm.SKod = sh.SKOD
            WHERE LTRIM(RTRIM(ISNULL(sh.Durum,''))) = ''
              AND EXISTS (
                  SELECT 1 FROM Urt_Em_gch g WITH (NOLOCK)
                  WHERE g.FisNo = sk.SipNo
              )
            ORDER BY sk.SipNo DESC
        """)

        siparisler = []
        for r in cur.fetchall():
            siparisler.append({
                'sip_no': int(r[0]),
                'musteri': r[1],
                'model_kod': r[2],
                'model_adi': r[3],
                'hedef': int(float(r[4] or 0)),
                'termin': r[5],
                'belge_no': r[6],
                'cari_kod': r[7],
            })

        cur.close()
        return siparisler
    finally:
        con.close()


def _sql_get_siparis_emirler(sip_no):
    """Bir siparisin tum emirleri (ana + alt) + her emir icin prosesler.

    Donus: list of {emir_no, kategori (MAMUL/GOVDE/ATKI), tip, yaz_say,
                    parent_emir, model_kod, prosesler[]}

    prosesler[]: {proses_kod, proses_adi, biten, baslayacak, devam}
    """
    con = _korgun_baglan()
    try:
        cur = con.cursor()

        # 1) Bu siparisin ana emirleri (Tip='M')
        # Once Urt_Em_gch'den FisNo=sip_no olan emir listesi
        cur.execute("""
            SELECT DISTINCT g.EmirNo
            FROM Urt_Em_gch g WITH (NOLOCK)
            WHERE g.FisNo = %s

            UNION

            SELECT DISTINCT g2.EmirNo
            FROM Urt_Em_gch g2 WITH (NOLOCK)
            WHERE g2.FisNo = %s
        """, (sip_no, sip_no))
        gch_emirler = [int(r[0]) for r in cur.fetchall()]

        if not gch_emirler:
            return []

        # 2) Her emirin Urt_Emir veya Urtx_Emir bilgisi
        ph = ','.join(['%s'] * len(gch_emirler))
        cur.execute(f"""
            SELECT e.EmirNo, e.ModelKod, UPPER(LTRIM(RTRIM(ISNULL(e.Tip,'')))) AS Tip,
                   ISNULL(e.YazSay, 0) AS YazSay,
                   ISNULL(sk.Tanim, e.ModelKod) AS ModelAdi
            FROM Urt_Emir e WITH (NOLOCK)
            LEFT JOIN StokKart sk WITH (NOLOCK) ON sk.SKod = e.ModelKod
            WHERE e.EmirNo IN ({ph})

            UNION ALL

            SELECT e.EmirNo, e.ModelKod, UPPER(LTRIM(RTRIM(ISNULL(e.Tip,'')))) AS Tip,
                   ISNULL(e.YazSay, 0) AS YazSay,
                   ISNULL(sk.Tanim, e.ModelKod) AS ModelAdi
            FROM Urtx_Emir e WITH (NOLOCK)
            LEFT JOIN StokKart sk WITH (NOLOCK) ON sk.SKod = e.ModelKod
            WHERE e.EmirNo IN ({ph})
        """, tuple(gch_emirler) + tuple(gch_emirler))

        emir_meta = {}
        for r in cur.fetchall():
            en = int(r[0])
            if en in emir_meta:
                continue
            mk = r[1] or ''
            tip = r[2] or 'M'
            yaz = int(float(r[3] or 0))
            ma = r[4] or mk
            kat = _kategori_belirle(mk, ma)
            emir_meta[en] = {
                'emir_no': en,
                'model_kod': mk,
                'model_adi': ma,
                'tip': tip,
                'kategori': kat,
                'yaz_say': yaz,
                'parent_emir': None,
                'prosesler': [],
            }

        # 3) Em2Em ile parent baglanti
        cur.execute(f"""
            SELECT em.EmirNo AS Parent, em.EmirNo_YM AS Alt
            FROM Urt_Em2Em em WITH (NOLOCK)
            WHERE em.EmirNo IN ({ph}) OR em.EmirNo_YM IN ({ph})
        """, tuple(gch_emirler) + tuple(gch_emirler))
        for r in cur.fetchall():
            parent = int(r[0])
            alt = int(r[1])
            if alt in emir_meta:
                emir_meta[alt]['parent_emir'] = parent

        # 4) BITEN: Urt_con_gch + Urtx_con_gch UNION
        cur.execute(f"""
            SELECT g.EmirNo, g.Proses, SUM(g.Cikan) AS Biten
            FROM Urt_con_gch g WITH (NOLOCK)
            WHERE g.EmirNo IN ({ph})
              AND g.Cikan > 0
            GROUP BY g.EmirNo, g.Proses

            UNION ALL

            SELECT g.EmirNo, g.Proses, SUM(g.Cikan) AS Biten
            FROM Urtx_con_gch g WITH (NOLOCK)
            WHERE g.EmirNo IN ({ph})
              AND g.Cikan > 0
            GROUP BY g.EmirNo, g.Proses
        """, tuple(gch_emirler) + tuple(gch_emirler))

        # Aynı emir+proses iki tabloda varsa topla
        biten_map = {}  # (emir, proses) -> biten
        for r in cur.fetchall():
            en = int(r[0])
            pr = str(r[1]).strip()
            bt = int(float(r[2] or 0))
            anahtar = (en, pr)
            biten_map[anahtar] = biten_map.get(anahtar, 0) + bt

        # 5) BAŞLAYACAK: Urt_wait_gch + Urtx_wait_gch UNION
        cur.execute(f"""
            SELECT g.EmirNo, g.Proses, SUM(ISNULL(g.Giren, 0)) AS Baslayacak
            FROM Urt_wait_gch g WITH (NOLOCK)
            WHERE g.EmirNo IN ({ph})
            GROUP BY g.EmirNo, g.Proses

            UNION ALL

            SELECT g.EmirNo, g.Proses, SUM(ISNULL(g.Giren, 0)) AS Baslayacak
            FROM Urtx_wait_gch g WITH (NOLOCK)
            WHERE g.EmirNo IN ({ph})
            GROUP BY g.EmirNo, g.Proses
        """, tuple(gch_emirler) + tuple(gch_emirler))

        baslayacak_map = {}
        for r in cur.fetchall():
            en = int(r[0])
            pr = str(r[1]).strip()
            bs = int(float(r[2] or 0))
            anahtar = (en, pr)
            baslayacak_map[anahtar] = baslayacak_map.get(anahtar, 0) + bs

        # 6) Proses adlari (Proses_M)
        tum_proses_kodlari = set()
        for k in biten_map.keys():
            tum_proses_kodlari.add(k[1])
        for k in baslayacak_map.keys():
            tum_proses_kodlari.add(k[1])

        proses_adlari = {}
        if tum_proses_kodlari:
            ph_p = ','.join(['%s'] * len(tum_proses_kodlari))
            cur.execute(f"""
                SELECT Pro, Tanim
                FROM Proses_M WITH (NOLOCK)
                WHERE Pro IN ({ph_p})
            """, tuple(tum_proses_kodlari))
            for r in cur.fetchall():
                proses_adlari[str(r[0]).strip()] = r[1]

        # 7) Her emir icin proses listesi olustur
        for (en, pr), bt in biten_map.items():
            if en not in emir_meta:
                continue
            adi = proses_adlari.get(pr, pr)
            bs = baslayacak_map.pop((en, pr), 0)  # baslayacak da varsa al
            emir_meta[en]['prosesler'].append({
                'proses_kod': pr,
                'proses_adi': adi,
                'biten': bt,
                'baslayacak': bs,
                'devam': 0,
            })

        # 8) Sadece baslayacak (biten yok) olanlar
        for (en, pr), bs in baslayacak_map.items():
            if en not in emir_meta:
                continue
            adi = proses_adlari.get(pr, pr)
            emir_meta[en]['prosesler'].append({
                'proses_kod': pr,
                'proses_adi': adi,
                'biten': 0,
                'baslayacak': bs,
                'devam': 0,
            })

        cur.close()
        return list(emir_meta.values())
    finally:
        con.close()


def _sql_siparis_listesi_full():
    """Tum aktif siparisleri ozet bilgi ile dondurur (PLAN listesi icin)."""
    siparisler = _sql_get_siparis_listesi()
    sonuc = []
    for sip in siparisler:
        try:
            emirler = _sql_get_siparis_emirler(sip['sip_no'])
        except Exception as e:
            try:
                print(f'[korgun_v2 SQL hata sip {sip["sip_no"]}]: {e}')
            except Exception:
                pass
            emirler = []

        # Kategorize
        atki_emirler = [e for e in emirler if e.get('kategori') == 'ATKI']
        govde_emirler = [e for e in emirler if e.get('kategori') == 'GOVDE']
        mamul_emirler = [e for e in emirler if e.get('kategori') == 'MAMUL']

        atki_t = sum(_son_proses_yapilan(e.get('prosesler', []))[0] for e in atki_emirler)
        govde_t = sum(_son_proses_yapilan(e.get('prosesler', []))[0] for e in govde_emirler)
        mamul_t = sum(_son_proses_yapilan(e.get('prosesler', []))[0] for e in mamul_emirler)

        sip_kopya = dict(sip)
        sip_kopya['emir_sayisi'] = {
            'mamul': len(mamul_emirler),
            'atki': len(atki_emirler),
            'govde': len(govde_emirler),
        }
        sip_kopya['korgun'] = {
            'atki_tamamlanan': atki_t,
            'govde_tamamlanan': govde_t,
            'mamul_tamamlanan': mamul_t,
        }
        # Detay icin emir listesini sakla
        sip_kopya['_emirler_cache'] = emirler
        sonuc.append(sip_kopya)
    return sonuc


# get_siparis_listesi'i guncelle - MOCK kontrol
_orig_get_siparis_listesi = get_siparis_listesi if 'get_siparis_listesi' in dir() else None


def get_siparis_listesi_canli():
    """CANLI Korgun'dan siparis listesi."""
    if MOCK_MODE:
        return _orig_get_siparis_listesi() if _orig_get_siparis_listesi else []
    try:
        sonuc = _sql_siparis_listesi_full()
        # _emirler_cache alanini cikar (sadece liste icin)
        for s in sonuc:
            s.pop('_emirler_cache', None)
        return sonuc
    except Exception as e:
        try:
            print(f'[korgun_v2 SQL liste hata]: {e}')
        except Exception:
            pass
        return []


def get_siparis_detay_v2_canli(sip_no):
    """CANLI Korgun'dan siparis detayi (hiyerarsik)."""
    if MOCK_MODE:
        return get_siparis_detay_v2(sip_no) if 'get_siparis_detay_v2' in dir() else None

    try:
        # Once siparisin meta bilgisini al
        siparisler = _sql_get_siparis_listesi()
        sip = None
        for s in siparisler:
            if int(s['sip_no']) == int(sip_no):
                sip = s
                break

        if not sip:
            return None

        # Emirler
        emirler = _sql_get_siparis_emirler(int(sip_no))

        if not emirler:
            return None

        hedef = int(sip.get('hedef', 0) or 0)

        atki_emirler = [e for e in emirler if e.get('kategori') == 'ATKI']
        govde_emirler = [e for e in emirler if e.get('kategori') == 'GOVDE']
        mamul_emirler = [e for e in emirler if e.get('kategori') == 'MAMUL']

        # Modeller bazli grupla
        model_gruplari = {}
        for me in mamul_emirler:
            mk = me.get('model_kod', '?')
            ma = me.get('model_adi', mk)
            if mk not in model_gruplari:
                model_gruplari[mk] = {
                    'model_kod': mk,
                    'model_adi': ma,
                    'mamul_emirler': [],
                }
            model_gruplari[mk]['mamul_emirler'].append(me)

        if not model_gruplari and sip.get('model_kod'):
            model_gruplari[sip['model_kod']] = {
                'model_kod': sip['model_kod'],
                'model_adi': sip.get('model_adi', sip['model_kod']),
                'mamul_emirler': [],
            }

        modeller_listesi = []
        for mk, grup in model_gruplari.items():
            mamul_emir_detaylari = []
            kat_atki_t = 0
            kat_govde_t = 0
            kat_mamul_t = 0

            for me in grup['mamul_emirler']:
                atki_iliskili = [a for a in atki_emirler if a.get('parent_emir') == me['emir_no']]
                govde_iliskili = [g for g in govde_emirler if g.get('parent_emir') == me['emir_no']]
                korgun = _emir_korgun_blok(me, atki_iliskili, govde_iliskili)
                mamul_emir_detaylari.append({
                    'emir_no': me['emir_no'],
                    'yaz_say': int(me.get('yaz_say', 0) or 0),
                    'korgun': korgun,
                })
                kat_atki_t += korgun['atki']['tamamlanan']
                kat_govde_t += korgun['govde']['tamamlanan']
                kat_mamul_t += korgun['mamul']['son_yapilan']

            # Parent_emir'i olmayan ATKI/GOVDE varsa bunlari da ek olarak goster
            # (mamul_emir bagi bulunamadi)
            modeller_listesi.append({
                'model_kod': grup['model_kod'],
                'model_adi': grup['model_adi'],
                'hedef_pay': hedef,
                'mamul_emirler': mamul_emir_detaylari,
                'kategori_ozet': {
                    'atki_tamamlanan': kat_atki_t,
                    'govde_tamamlanan': kat_govde_t,
                    'mamul_tamamlanan': kat_mamul_t,
                },
            })

        # Toplam
        toplam_atki = sum(_son_proses_yapilan(e.get('prosesler', []))[0] for e in atki_emirler)
        toplam_govde = sum(_son_proses_yapilan(e.get('prosesler', []))[0] for e in govde_emirler)
        toplam_mamul = sum(_son_proses_yapilan(e.get('prosesler', []))[0] for e in mamul_emirler)

        return {
            'sip_no': int(sip_no),
            'musteri': sip.get('musteri'),
            'cari_kod': sip.get('cari_kod'),
            'model_kod': sip.get('model_kod'),
            'model_adi': sip.get('model_adi'),
            'hedef': hedef,
            'termin': sip.get('termin'),
            'belge_no': sip.get('belge_no'),
            'model_sayisi': len(modeller_listesi),
            'modeller': modeller_listesi,
            'toplam_korgun': {
                'atki_tamamlanan': toplam_atki,
                'govde_tamamlanan': toplam_govde,
                'mamul_tamamlanan': toplam_mamul,
            },
        }
    except Exception as e:
        try:
            print(f'[korgun_v2 SQL detay hata sip {sip_no}]: {e}')
            import traceback
            traceback.print_exc()
        except Exception:
            pass
        return None


# Mevcut fonksiyonlari override et (canli moda gec)
_orig_get_siparis_listesi_v2 = get_siparis_listesi
get_siparis_listesi = get_siparis_listesi_canli

_orig_get_siparis_detay_v2 = get_siparis_detay_v2
get_siparis_detay_v2 = get_siparis_detay_v2_canli
'''

# Sona ekle
new_src = src.rstrip() + KORGUN_HELPERS + '\n'

bak = KP + '.bak_pre_canli_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(KP, bak)
print('Yedek: ' + bak)

with io.open(KP, 'w', encoding='utf-8') as f:
    f.write(new_src)

artis = len(new_src) - len(src)
print('OK: CANLI SQL eklendi (' + str(artis) + ' byte)')
print('  - MOCK_MODE = False')
print('  - _sql_get_siparis_listesi (siparişler)')
print('  - _sql_get_siparis_emirler (emirler+prosesler)')
print('  - get_siparis_listesi -> canli')
print('  - get_siparis_detay_v2 -> canli')
print()
print('SUNUCU RESTART GEREKLI:')
print('  taskkill /F /IM python.exe')
print('  cd C:\\cps_dev')
print('  py app.py')