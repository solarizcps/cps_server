# -*- coding: utf-8 -*-
"""
CPS - Korgun Uretim Aktarim Servisi (FAZ 2B-1 / 2B-2 / 2B-3)

FAZ 2B-1: korgun_uretim_aktar(kayit_id)
          Sadece aktarim paketi hazirlar. Korgun'a yazma yok.

FAZ 2B-2: wait_kapat(kayit_id, dry_run=True)
          Urt_Wait_gch.Cikan = Giren UPDATE.
          dry_run=True  -> sadece SELECT ile simule eder, yazma yok.
          dry_run=False -> gercek UPDATE (onay gerekli).

FAZ 2B-3: con_insert_hazirla(kayit_id, dry_run=True)
          Urt_con_gch INSERT paketini hazirlar.
          dry_run=True  -> planned_inserts listesi doner, gercek INSERT yok.
          dry_run=False -> gercek INSERT (onay gerekli).

Kural:
  - korgun_yazildi = 0 olan kayitlar aktarim adayidir
  - Wait kaydi yoksa 'wait_yok' sebep kodu doner
  - Personel kodu korgun_personel_eslestirme'den cozulur
  - SP (kg_sp_Urt_CopyProses / kg_sp_Urt_DetisBas) hicbir zaman cagrilmaz
"""
import sqlite3
from datetime import datetime


# ---------------------------------------------------------------------------
# Yardimci
# ---------------------------------------------------------------------------

def _iv(x, default=0):
    try:
        return int(float(x or 0))
    except (ValueError, TypeError):
        return default


def _sv(x, default=''):
    if x is None:
        return default
    return str(x).strip() or default


# ---------------------------------------------------------------------------
# CPS DB'den kayit okuma
# ---------------------------------------------------------------------------

def _cps_kayit_oku(conn, kayit_id):
    """
    CPS SQLite uretim_kayit + uretim_kayit_personel okur.
    conn: sqlite3.Connection (row_factory=sqlite3.Row beklenir)
    Donus: dict veya None
    """
    row = conn.execute(
        """
        SELECT id, emir_no, model_kod, miktar, proses_kodu, proses_adi,
               hat_adi, baslangic_saat, bitis_saat,
               korgun_yazildi, korgun_emir_no, korgun_proses_kodu,
               korgun_fis_no, korgun_fis_harinx,
               onay_durum, tarih, saat, usta_ad
        FROM uretim_kayit
        WHERE id = ?
        """,
        (kayit_id,)
    ).fetchone()

    if not row:
        return None

    kayit = dict(row)

    personeller = conn.execute(
        """
        SELECT personel_id, personel_ad, miktar
        FROM uretim_kayit_personel
        WHERE kayit_id = ?
        ORDER BY id
        """,
        (kayit_id,)
    ).fetchall()

    kayit['personel_listesi'] = [dict(p) for p in personeller]
    return kayit


# ---------------------------------------------------------------------------
# Korgun personel kodu cozme
# ---------------------------------------------------------------------------

def _personel_kodu_coz(conn, usta_ad):
    """
    korgun_personel_eslestirme tablosundan usta_ad icin Korgun personel kodunu dondurur.
    usta_ad: CPS usta adi (ornek: 'halil')
    Donus: {'personel_kodu': '30013', 'korgun_insUN': 'Uretim'} veya None
    """
    if not usta_ad:
        return None

    row = conn.execute(
        """
        SELECT korgun_personel_kodu, korgun_insUN
        FROM korgun_personel_eslestirme
        WHERE aktif = 1
          AND (
            cps_kullanici_adi = ?
            OR cps_kullanici_adi = LOWER(?)
          )
        LIMIT 1
        """,
        (usta_ad.strip(), usta_ad.strip())
    ).fetchone()

    if not row:
        return None

    return {
        'personel_kodu': _sv(row['korgun_personel_kodu']),
        'korgun_insUN':  _sv(row['korgun_insUN'], 'Uretim'),
    }


# ---------------------------------------------------------------------------
# Korgun Wait satiri okuma
# ---------------------------------------------------------------------------

def _wait_satir_oku(korgun_con, emir_no, proses_kodu):
    """
    Korgun Urt_Wait_gch'den emir + proses icin acik satir okur.
    Acik = Giren > Cikan (henuz tamamlanmamis).
    Donus: dict veya None
    """
    cur = korgun_con.cursor()
    try:
        cur.execute(
            """
            SELECT TOP 1
                EmirNo, SKOD, RKOD, BedKod, FisNo, FisHarinx,
                Giren, Cikan, Proses, AltProses, WMakNum,
                SendTar, StartTarih
            FROM Urt_Wait_gch WITH(NOLOCK)
            WHERE EmirNo = %s
              AND LTRIM(RTRIM(ISNULL(Proses, ''))) = %s
              AND ISNULL(Giren, 0) > ISNULL(Cikan, 0)
            ORDER BY FisHarinx DESC
            """,
            (int(emir_no), str(proses_kodu).strip())
        )
        row = cur.fetchone()
        if not row:
            return None

        cols = [d[0] for d in cur.description]
        d = dict(zip(cols, row))

        def _dt(v):
            if v is None:
                return None
            if hasattr(v, 'isoformat'):
                return v.isoformat()[:19]
            return str(v)[:19]

        return {
            'EmirNo':     _iv(d.get('EmirNo')),
            'SKOD':       _sv(d.get('SKOD')),
            'RKOD':       _iv(d.get('RKOD')),
            'BedKod':     _iv(d.get('BedKod')),
            'FisNo':      _iv(d.get('FisNo')),
            'FisHarinx':  _iv(d.get('FisHarinx')),
            'Giren':      _iv(d.get('Giren')),
            'Cikan':      _iv(d.get('Cikan')),
            'Proses':     _sv(d.get('Proses')),
            'AltProses':  _sv(d.get('AltProses')),
            'WMakNum':    _iv(d.get('WMakNum')),
            'SendTar':    _dt(d.get('SendTar')),
            'StartTarih': _dt(d.get('StartTarih')),
        }
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Ana fonksiyon: aktarim paketi hazirla
# ---------------------------------------------------------------------------

def korgun_uretim_aktar(kayit_id, cps_db_path=None):
    """
    FAZ 2B-1: CPS uretim_kayit kaydini Korgun aktarimi icin hazirlar.

    Korgun'a hicbir yazma yapilmaz.
    Sadece aktarim paketini doldurur ve donus yapar.

    Parametreler:
        kayit_id    : CPS uretim_kayit.id
        cps_db_path : SQLite DB yolu (None ise Config'den)

    Donus:
        {
            'ok': True/False,
            'sebep': 'paket_hazir' | 'kayit_yok' | 'zaten_aktarildi' |
                     'wait_yok' | 'personel_eslesme_yok' | 'korgun_baglanti_hatasi',
            'kayit_id': int,
            'paket': {                    # ok=True ise dolu
                'EmirNo', 'SKOD', 'RKOD', 'BedKod',
                'FisNo', 'FisHarinx', 'SendTar', 'StartTarih',
                'Proses', 'AltProses', 'Personel', 'insUN',
                'Giren', 'Cikan',           # = toplam_miktar / toplam_miktar
                'Fire',                     # = 0
                'WMakNum',                  # = 0
                'EndTarih',                 # bitis zamani
            },
            'wait_satir'  : dict | None,
            'cps_kayit'   : dict,
            'hata'        : str | None,
        }
    """
    # --- CPS DB yolu ---
    if cps_db_path is None:
        try:
            import os, sys
            _app_dir = os.path.join(os.path.dirname(__file__), '..', '..')
            sys.path.insert(0, os.path.abspath(_app_dir))
            from config import Config
            cps_db_path = Config.MOCK_DB_PATH
        except Exception as e:
            return {
                'ok': False,
                'sebep': 'config_hatasi',
                'kayit_id': kayit_id,
                'hata': f'Config okunamadi: {e}',
                'paket': None,
                'wait_satir': None,
                'cps_kayit': {},
            }

    # --- CPS DB bağlantı ---
    cps_conn = sqlite3.connect(cps_db_path)
    cps_conn.row_factory = sqlite3.Row

    try:
        # 1) CPS kayıt oku
        kayit = _cps_kayit_oku(cps_conn, kayit_id)
        if not kayit:
            return {
                'ok': False,
                'sebep': 'kayit_yok',
                'kayit_id': kayit_id,
                'hata': f'uretim_kayit id={kayit_id} bulunamadi',
                'paket': None,
                'wait_satir': None,
                'cps_kayit': {},
            }

        # 2) Zaten aktarılmış mı?
        if _iv(kayit.get('korgun_yazildi')) == 1:
            return {
                'ok': False,
                'sebep': 'zaten_aktarildi',
                'kayit_id': kayit_id,
                'hata': None,
                'paket': None,
                'wait_satir': None,
                'cps_kayit': kayit,
            }

        # 3) Personel kodu çöz
        usta_ad = kayit.get('usta_ad') or ''
        personel_bilgi = _personel_kodu_coz(cps_conn, usta_ad)

        emir_no      = _iv(kayit.get('emir_no') or kayit.get('korgun_emir_no'))
        proses_kodu  = _sv(kayit.get('korgun_proses_kodu') or kayit.get('proses_kodu'))
        toplam_miktar = _iv(kayit.get('miktar'))

        # 4) Korgun'a bağlan — Wait satırını oku
        wait_satir = None
        korgun_hata = None

        try:
            from modules.common.korgun import _baglan as _korgun_baglan
            k_con = _korgun_baglan()
            try:
                wait_satir = _wait_satir_oku(k_con, emir_no, proses_kodu)
            finally:
                k_con.close()
        except Exception as e:
            korgun_hata = f'Korgun baglanti hatasi: {type(e).__name__}: {str(e)[:200]}'

        if korgun_hata:
            return {
                'ok': False,
                'sebep': 'korgun_baglanti_hatasi',
                'kayit_id': kayit_id,
                'hata': korgun_hata,
                'paket': None,
                'wait_satir': None,
                'cps_kayit': kayit,
            }

        # 5) Wait satırı yoksa
        if wait_satir is None:
            return {
                'ok': False,
                'sebep': 'wait_yok',
                'kayit_id': kayit_id,
                'hata': (
                    f'Urt_Wait_gch\'de EmirNo={emir_no} Proses={proses_kodu} '
                    f'icin acik satir bulunamadi'
                ),
                'paket': None,
                'wait_satir': None,
                'cps_kayit': kayit,
            }

        # 6) Paket hazırla
        simdi = datetime.now()

        def _dt_birlestir(tarih, saat):
            """
            tarih='2026-06-18', saat='10:02' veya saat='2026-06-18T10:02:16'
            -> '2026-06-18T10:02' gibi birlestirir, her zaman 19 karakter.
            """
            t = _sv(tarih) or simdi.strftime('%Y-%m-%d')
            s = _sv(saat)
            if not s:
                return None
            # Saat zaten tam ISO ise direkt don
            if 'T' in s or len(s) > 8:
                return s[:19]
            return f"{t}T{s}"[:19]

        end_tarih   = _dt_birlestir(kayit.get('tarih'), kayit.get('bitis_saat')) \
                      or simdi.isoformat()[:19]
        start_tarih = (
            wait_satir.get('StartTarih')
            or _dt_birlestir(kayit.get('tarih'), kayit.get('baslangic_saat'))
            or simdi.isoformat()[:19]
        )

        paket = {
            'EmirNo':     wait_satir['EmirNo'],
            'SKOD':       wait_satir['SKOD'],
            'RKOD':       wait_satir['RKOD'],
            'BedKod':     wait_satir['BedKod'],
            'FisNo':      wait_satir['FisNo'],
            'FisHarinx':  wait_satir['FisHarinx'],
            'SendTar':    wait_satir.get('SendTar') or simdi.isoformat()[:19],
            'StartTarih': start_tarih,
            'Proses':     proses_kodu or wait_satir['Proses'],
            'AltProses':  wait_satir.get('AltProses') or '',
            'Personel':   personel_bilgi['personel_kodu'] if personel_bilgi else '',
            'insUN':      personel_bilgi['korgun_insUN'] if personel_bilgi else 'Uretim',
            'Giren':      toplam_miktar,
            'Cikan':      toplam_miktar,
            'scikan':     0,
            'Fire':       0,
            'WMakNum':    wait_satir.get('WMakNum') or 0,
            'EndTarih':   end_tarih,
        }

        # 7) Personel uyarısı (kayıt var ama eşleşme yok — uyarı, bloklama değil)
        uyari = None
        if not personel_bilgi:
            uyari = (
                f"usta_ad='{usta_ad}' korgun_personel_eslestirme'de bulunamadi. "
                f"Personel alani bos kalacak."
            )

        return {
            'ok': True,
            'sebep': 'paket_hazir',
            'kayit_id': kayit_id,
            'hata': None,
            'uyari': uyari,
            'paket': paket,
            'wait_satir': wait_satir,
            'cps_kayit': kayit,
        }

    finally:
        cps_conn.close()


# ---------------------------------------------------------------------------
# FAZ 2B-2: Urt_Wait_gch kapama
# ---------------------------------------------------------------------------

def wait_kapat(kayit_id, dry_run=True, cps_db_path=None):
    """
    FAZ 2B-2: Korgun Urt_Wait_gch satirini kapatir.

    UPDATE Urt_Wait_gch
    SET Cikan  = Giren,
        updUN  = 'CPS_Halil',
        updDT  = GETDATE()
    WHERE EmirNo    = <paket.EmirNo>
      AND Proses    = <paket.Proses>
      AND FisNo     = <paket.FisNo>
      AND FisHarinx = <paket.FisHarinx>
      AND ISNULL(Cikan, 0) < ISNULL(Giren, 0)

    FAZ 2B-7 eklentisi:
        - dry_run=True: simule listesinde TUM acik satirlarin kgid listesi doner
        - dry_run=False: UPDATE sonrasi etkilenen satirlarin kgid'leri SELECT ile
          cekilerek 'wait_kgid_listesi' olarak doner
          Bu liste con_insert_hazirla()'ya iletilir, updUN bagimliligini kaldirir.

    Parametreler:
        kayit_id    : CPS uretim_kayit.id
        dry_run     : True  -> SELECT simule, Korgun'a yazma YOK (varsayilan)
                      False -> gercek UPDATE (onay gerekli)
        cps_db_path : SQLite DB yolu

    Donus:
        {
            'ok'              : bool,
            'dry_run'         : bool,
            'sebep'           : str,
            'kayit_id'        : int,
            'paket'           : dict | None,
            'etkilenen'       : int,
            'simule'          : list[dict],  # tum acik satirlar (dry_run=True)
            'wait_kgid_listesi': list[int],  # etkilenen kgid'ler
            'hata'            : str | None,
        }

    KURAL:
        - Urt_con_gch'ye hicbir INSERT yapilmaz.
        - kg_sp_Urt_CopyProses / kg_sp_Urt_DetisBas cagrilmaz.
        - dry_run=False olmadan hicbir Korgun yazma gerceklesmez.
    """
    # --- 1) Aktarim paketini hazirla (2B-1 mantigi) ---
    paket_sonuc = korgun_uretim_aktar(kayit_id, cps_db_path=cps_db_path)

    if not paket_sonuc.get('ok'):
        return {
            'ok': False,
            'dry_run': dry_run,
            'sebep': paket_sonuc.get('sebep', 'paket_hatasi'),
            'kayit_id': kayit_id,
            'paket': None,
            'etkilenen': 0,
            'simule': None,
            'hata': paket_sonuc.get('hata') or f"Paket hazirlanamadi: {paket_sonuc.get('sebep')}",
        }

    paket = paket_sonuc['paket']

    # WHERE icin siki parametreler
    emir_no    = int(paket['EmirNo'])
    proses     = str(paket['Proses']).strip()
    fis_no     = int(paket['FisNo'])
    fis_harinx = int(paket['FisHarinx'])

    # updUN: korgun_personel_eslestirme'den insUN bilgisini al
    # insUN = 'Uretim' (Korgun DB kullanicisi), CPS kim yapti izi icin prefix 'CPS_' ekle
    upd_un = 'CPS_Halil'

    # --- 2) Korgun baglantisi ---
    try:
        from modules.common.korgun import _baglan as _korgun_baglan
        k_con = _korgun_baglan()
    except Exception as e:
        return {
            'ok': False,
            'dry_run': dry_run,
            'sebep': 'korgun_baglanti_hatasi',
            'kayit_id': kayit_id,
            'paket': paket,
            'etkilenen': 0,
            'simule': None,
            'hata': f'Korgun baglanti hatasi: {type(e).__name__}: {str(e)[:200]}',
        }

    try:
        cur = k_con.cursor()

        # --- 3) Tum acik satirlari onizle (her iki modda da calisir) ---
        # FAZ 2B-7: TOP 1 yerine tum satirlar — kgid listesi icin gerekli
        cur.execute(
            """
            SELECT kgid,
                EmirNo, Proses, FisNo, FisHarinx, RKOD, BedKod,
                Giren, Cikan,
                ISNULL(Giren, 0) - ISNULL(Cikan, 0) AS Bekleyen,
                insUN, updUN,
                CONVERT(VARCHAR(19), insDT,  120) AS insDT,
                CONVERT(VARCHAR(19), updDT,  120) AS updDT
            FROM Urt_Wait_gch WITH(NOLOCK)
            WHERE EmirNo    = %s
              AND LTRIM(RTRIM(ISNULL(Proses, ''))) = %s
              AND FisNo     = %s
              AND FisHarinx = %s
              AND ISNULL(Cikan, 0) < ISNULL(Giren, 0)
            ORDER BY kgid
            """,
            (emir_no, proses, fis_no, fis_harinx)
        )
        onizle_rows = cur.fetchall()
        simule_list = []
        if onizle_rows:
            cols = [d[0] for d in cur.description]
            for row in onizle_rows:
                sd = dict(zip(cols, row))
                for k in ('kgid', 'EmirNo', 'FisNo', 'FisHarinx',
                          'Giren', 'Cikan', 'Bekleyen', 'RKOD', 'BedKod'):
                    if k in sd and sd[k] is not None:
                        try:
                            sd[k] = int(float(sd[k]))
                        except (ValueError, TypeError):
                            pass
                simule_list.append(sd)

        # Hedef satir yoksa (zaten kapali veya parametre yanlis)
        if not simule_list:
            cur.close()
            k_con.close()
            return {
                'ok': False,
                'dry_run': dry_run,
                'sebep': 'wait_satir_yok_veya_kapali',
                'kayit_id': kayit_id,
                'paket': paket,
                'etkilenen': 0,
                'simule': [],
                'wait_kgid_listesi': [],
                'hata': (
                    f'Urt_Wait_gch: EmirNo={emir_no} Proses={proses!r} '
                    f'FisNo={fis_no} FisHarinx={fis_harinx} '
                    f'icin acik (Cikan < Giren) satir bulunamadi. '
                    f'Zaten kapali olabilir.'
                ),
            }

        onizle_kgid_listesi = [s['kgid'] for s in simule_list]

        # --- 4) DRY RUN modu: tum kgid'leri simule olarak don ---
        if dry_run:
            cur.close()
            k_con.close()
            return {
                'ok': True,
                'dry_run': True,
                'sebep': 'dry_run_tamam',
                'kayit_id': kayit_id,
                'paket': paket,
                'etkilenen': 0,
                'simule': simule_list,
                'wait_kgid_listesi': onizle_kgid_listesi,
                'hata': None,
                'yapilacak_sql': (
                    f"UPDATE Urt_Wait_gch\n"
                    f"SET Cikan = Giren,\n"
                    f"    updUN = '{upd_un}',\n"
                    f"    updDT = GETDATE()\n"
                    f"WHERE EmirNo    = {emir_no}\n"
                    f"  AND Proses    = '{proses}'\n"
                    f"  AND FisNo     = {fis_no}\n"
                    f"  AND FisHarinx = {fis_harinx}\n"
                    f"  AND ISNULL(Cikan, 0) < ISNULL(Giren, 0)\n"
                    f"-- Etkilenecek kgid'ler: {onizle_kgid_listesi}"
                ),
            }

        # --- 5) GERCEK UPDATE (dry_run=False) ---
        cur.execute(
            """
            UPDATE Urt_Wait_gch
            SET Cikan = Giren,
                updUN = %s,
                updDT = GETDATE()
            WHERE EmirNo    = %s
              AND LTRIM(RTRIM(ISNULL(Proses, ''))) = %s
              AND FisNo     = %s
              AND FisHarinx = %s
              AND ISNULL(Cikan, 0) < ISNULL(Giren, 0)
            """,
            (upd_un, emir_no, proses, fis_no, fis_harinx)
        )
        etkilenen = cur.rowcount
        k_con.commit()

        # UPDATE sonrasi etkilenen satirlarin kgid'lerini dogrulama SELECT ile al
        # updUN='CPS_Halil' + onizle kgid listesi ile guvenli cek
        wait_kgid_listesi = []
        if onizle_kgid_listesi:
            placeholders = ', '.join(['%s'] * len(onizle_kgid_listesi))
            cur.execute(
                f"""
                SELECT kgid
                FROM Urt_Wait_gch WITH(NOLOCK)
                WHERE kgid IN ({placeholders})
                  AND updUN = %s
                  AND ISNULL(Cikan, 0) >= ISNULL(Giren, 0)
                ORDER BY kgid
                """,
                onizle_kgid_listesi + [upd_un]
            )
            wait_kgid_listesi = [r[0] for r in cur.fetchall()]

        cur.close()

        return {
            'ok': True,
            'dry_run': False,
            'sebep': 'wait_kapatildi',
            'kayit_id': kayit_id,
            'paket': paket,
            'etkilenen': etkilenen,
            'simule': simule_list,
            'wait_kgid_listesi': wait_kgid_listesi,
            'hata': None,
            'gerceklesen_sql': (
                f"UPDATE Urt_Wait_gch SET Cikan=Giren, updUN='{upd_un}', updDT=GETDATE() "
                f"WHERE EmirNo={emir_no} AND Proses='{proses}' "
                f"AND FisNo={fis_no} AND FisHarinx={fis_harinx} "
                f"AND ISNULL(Cikan,0)<ISNULL(Giren,0) "
                f"-- etkilenen={etkilenen} satir, kgid={wait_kgid_listesi}"
            ),
        }

    except Exception as e:
        try:
            k_con.rollback()
        except Exception:
            pass
        return {
            'ok': False,
            'dry_run': dry_run,
            'sebep': 'korgun_sorgu_hatasi',
            'kayit_id': kayit_id,
            'paket': paket,
            'etkilenen': 0,
            'simule': [],
            'wait_kgid_listesi': [],
            'hata': f'{type(e).__name__}: {str(e)[:300]}',
        }
    finally:
        try:
            k_con.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# FAZ 2B-3: Urt_con_gch insert paket hazirlama
# ---------------------------------------------------------------------------

def _con_duplicate_var_mi(cur, emir_no, proses, fis_no, fis_harinx, rkod, bed_kod):
    """
    Urt_con_gch'de ayni kombinasyon zaten var mi kontrol eder.
    Eslesme: EmirNo + Proses + FisNo + FisHarinx + RKOD + BedKod
    """
    cur.execute(
        """
        SELECT COUNT(*)
        FROM Urt_con_gch WITH(NOLOCK)
        WHERE EmirNo    = %s
          AND LTRIM(RTRIM(ISNULL(Proses, ''))) = %s
          AND FisNo     = %s
          AND FisHarinx = %s
          AND RKOD      = %s
          AND BedKod    = %s
        """,
        (int(emir_no), str(proses).strip(),
         int(fis_no), int(fis_harinx),
         int(rkod), int(bed_kod))
    )
    row = cur.fetchone()
    return (row[0] if row else 0) > 0


def con_insert_hazirla(kayit_id, dry_run=True, cps_db_path=None,
                       wait_kgid_listesi=None):
    """
    FAZ 2B-3 / 2B-7: Urt_con_gch INSERT paketini hazirlar.

    Wait_kapat ile kapanmis Wait satirlarini okur.
    Her satir icin 1 planned_insert dict olusturur.
    dry_run=True  -> sadece plan listesi doner, INSERT yok.
    dry_run=False -> gercek INSERT (onay gerekli).

    FAZ 2B-7 eklentisi:
        wait_kgid_listesi parametresi verilirse:
          - WHERE kgid IN (...) ile arama yapilir
          - updUN='CPS_Halil' bagimliligini ortadan kaldirir
          - Daha guvenli ve net hedefleme saglar
        Verilmezse: eski davranis (updUN='CPS_Halil' + emir/proses/fis filter)

    Parametreler:
        kayit_id         : CPS uretim_kayit.id
        dry_run          : True = gercek INSERT yok (varsayilan)
        cps_db_path      : SQLite DB yolu
        wait_kgid_listesi: wait_kapat'tan gelen kgid listesi (None = eski mod)

    Donus:
        {
            'ok'             : bool,
            'dry_run'        : bool,
            'sebep'          : str,
            'kayit_id'       : int,
            'planned_count'  : int,
            'duplicate_count': int,
            'planned_inserts': [
                {
                    'wait_kgid', 'EmirNo', 'SKOD', 'RKOD', 'BedKod',
                    'FisNo', 'FisHarinx', 'SendTar', 'StartTarih',
                    'Proses', 'AltProses', 'Personel', 'insUN',
                    'Giren', 'Cikan', 'scikan', 'Fire', 'WMakNum',
                    'EndTarih', 'duplicate'
                },
                ...
            ],
            'hata'           : str | None,
        }

    KURAL:
        - Duplicate kontrolu EmirNo+Proses+FisNo+FisHarinx+RKOD+BedKod bazlidir.
        - SP cagrilmaz.
    """
    # --- 1) Aktarim paketini al (2B-1 mantigi: CPS kayit + personel + Wait meta) ---
    paket_sonuc = korgun_uretim_aktar(kayit_id, cps_db_path=cps_db_path)

    if not paket_sonuc.get('ok'):
        # wait_yok gelebilir (Wait zaten kapandi, paket icin Wait aranir)
        # 2B-3 icin: Wait kapanmis olabilir, dogrudan Korgun'dan okuyacagiz
        # Bu durumu asagida ayrica ele aliyoruz — paket olmadan devam et
        pass

    # CPS kayit bilgisi
    cps_kayit = paket_sonuc.get('cps_kayit') or {}

    # Personel kodu — cps_kayit ustasini coz
    personel_kodu = ''
    ins_un        = 'Uretim'

    if cps_db_path is None:
        try:
            import os, sys as _sys
            _app_dir = os.path.join(os.path.dirname(__file__), '..', '..')
            _sys.path.insert(0, os.path.abspath(_app_dir))
            from config import Config
            _db_path = Config.MOCK_DB_PATH
        except Exception as e:
            return {
                'ok': False, 'dry_run': dry_run, 'sebep': 'config_hatasi',
                'kayit_id': kayit_id, 'planned_count': 0, 'duplicate_count': 0,
                'planned_inserts': [], 'hata': f'Config okunamadi: {e}',
            }
    else:
        _db_path = cps_db_path

    import sqlite3 as _sqlite3
    cps_conn = _sqlite3.connect(_db_path)
    cps_conn.row_factory = _sqlite3.Row
    try:
        usta_ad = cps_kayit.get('usta_ad') or ''
        pb = _personel_kodu_coz(cps_conn, usta_ad)
        if pb:
            personel_kodu = pb['personel_kodu']
            ins_un        = pb['korgun_insUN']
    finally:
        cps_conn.close()

    # Emir/proses/fis bilgisi
    emir_no    = _iv(cps_kayit.get('emir_no') or cps_kayit.get('korgun_emir_no'))
    proses     = _sv(cps_kayit.get('korgun_proses_kodu') or cps_kayit.get('proses_kodu'))
    fis_no_str = _sv(cps_kayit.get('korgun_fis_no'))
    fis_har_str= _sv(cps_kayit.get('korgun_fis_harinx'))

    # fis_no / fis_harinx: CPS kaydi yoksa paket'ten al
    if not fis_no_str and paket_sonuc.get('paket'):
        fis_no_str  = str(paket_sonuc['paket'].get('FisNo', ''))
        fis_har_str = str(paket_sonuc['paket'].get('FisHarinx', ''))

    if not emir_no or not proses:
        return {
            'ok': False, 'dry_run': dry_run, 'sebep': 'eksik_emir_proses',
            'kayit_id': kayit_id, 'planned_count': 0, 'duplicate_count': 0,
            'planned_inserts': [],
            'hata': f'emir_no veya proses bos: emir={emir_no!r} proses={proses!r}',
        }

    # --- 2) Korgun'a baglan ---
    try:
        from modules.common.korgun import _baglan as _korgun_baglan
        k_con = _korgun_baglan()
    except Exception as e:
        return {
            'ok': False, 'dry_run': dry_run, 'sebep': 'korgun_baglanti_hatasi',
            'kayit_id': kayit_id, 'planned_count': 0, 'duplicate_count': 0,
            'planned_inserts': [],
            'hata': f'Korgun baglanti hatasi: {type(e).__name__}: {str(e)[:200]}',
        }

    try:
        cur = k_con.cursor()

        # --- 3) Wait satirlarini oku ---
        # FAZ 2B-7: wait_kgid_listesi verilmisse kgid IN (...) ile hedefle
        #           Verilmemisse: updUN='CPS_Halil' bagimliligina duser (eski mod)
        if wait_kgid_listesi:
            placeholders = ', '.join(['%s'] * len(wait_kgid_listesi))
            cur.execute(
                f"""
                SELECT
                    kgid, EmirNo, Proses, AltProses,
                    SKOD, RKOD, BedKod,
                    FisNo, FisHarinx, Giren, Cikan,
                    CONVERT(VARCHAR(19), SendTar,    120) AS SendTar,
                    CONVERT(VARCHAR(19), StartTarih, 120) AS StartTarih,
                    WMakNum, updUN,
                    CONVERT(VARCHAR(19), updDT, 120) AS updDT
                FROM Urt_Wait_gch WITH(NOLOCK)
                WHERE kgid IN ({placeholders})
                ORDER BY kgid
                """,
                wait_kgid_listesi
            )
        else:
            # Eski mod: updUN='CPS_Halil' + emir/proses/fis filtresi
            where_extra = ''
            params_wait = [emir_no, proses]
            if fis_no_str and fis_no_str.isdigit():
                where_extra += ' AND FisNo = %s'
                params_wait.append(int(fis_no_str))
            if fis_har_str and fis_har_str.isdigit():
                where_extra += ' AND FisHarinx = %s'
                params_wait.append(int(fis_har_str))
            cur.execute(
                f"""
                SELECT
                    kgid, EmirNo, Proses, AltProses,
                    SKOD, RKOD, BedKod,
                    FisNo, FisHarinx, Giren, Cikan,
                    CONVERT(VARCHAR(19), SendTar,    120) AS SendTar,
                    CONVERT(VARCHAR(19), StartTarih, 120) AS StartTarih,
                    WMakNum, updUN,
                    CONVERT(VARCHAR(19), updDT, 120) AS updDT
                FROM Urt_Wait_gch WITH(NOLOCK)
                WHERE EmirNo = %s
                  AND LTRIM(RTRIM(ISNULL(Proses, ''))) = %s
                  {where_extra}
                  AND updUN = 'CPS_Halil'
                  AND ISNULL(Cikan, 0) >= ISNULL(Giren, 0)
                ORDER BY kgid
                """,
                params_wait
            )
        wait_rows = cur.fetchall()
        wait_cols = [d[0] for d in cur.description]

        if not wait_rows:
            cur.close()
            return {
                'ok': False, 'dry_run': dry_run,
                'sebep': 'wait_kapanmis_satir_yok',
                'kayit_id': kayit_id, 'planned_count': 0, 'duplicate_count': 0,
                'planned_inserts': [],
                'hata': (
                    f'Wait satiri bulunamadi. '
                    f'EmirNo={emir_no} Proses={proses!r} '
                    f'kgid_listesi={wait_kgid_listesi!r}'
                ),
            }

        # --- 4) Her Wait satiri icin planned_insert olustur ---
        simdi = datetime.now()
        end_tarih_default = simdi.isoformat()[:19]

        # EndTarih: CPS kaydindaki bitis_saat'ten al
        end_tarih = end_tarih_default
        if cps_kayit.get('bitis_saat'):
            bs = _sv(cps_kayit['bitis_saat'])
            tarih = _sv(cps_kayit.get('tarih')) or simdi.strftime('%Y-%m-%d')
            if bs:
                if 'T' in bs or len(bs) > 8:
                    end_tarih = bs[:19]
                else:
                    end_tarih = f"{tarih}T{bs}"[:19]

        planned = []
        dup_count = 0

        for wrow in wait_rows:
            wd = dict(zip(wait_cols, wrow))

            w_kgid      = _iv(wd.get('kgid'))
            w_skod      = _sv(wd.get('SKOD'))
            w_rkod      = _iv(wd.get('RKOD'))
            w_bedkod    = _iv(wd.get('BedKod'))
            w_fisno     = _iv(wd.get('FisNo'))
            w_fishar    = _iv(wd.get('FisHarinx'))
            w_giren     = _iv(wd.get('Giren'))
            w_proses    = _sv(wd.get('Proses')) or proses
            w_altproses = _sv(wd.get('AltProses'))
            w_send_tar  = _sv(wd.get('SendTar')) or end_tarih_default
            w_start_tar = _sv(wd.get('StartTarih')) or end_tarih_default
            w_wmaknum   = _iv(wd.get('WMakNum'))

            # Duplicate kontrolu
            dup = _con_duplicate_var_mi(
                cur, emir_no, w_proses, w_fisno, w_fishar, w_rkod, w_bedkod
            )
            if dup:
                dup_count += 1

            planned.append({
                'wait_kgid' : w_kgid,
                'EmirNo'    : emir_no,
                'SKOD'      : w_skod,
                'RKOD'      : w_rkod,
                'BedKod'    : w_bedkod,
                'FisNo'     : w_fisno,
                'FisHarinx' : w_fishar,
                'SendTar'   : w_send_tar,
                'StartTarih': w_start_tar,
                'Proses'    : w_proses,
                'AltProses' : w_altproses,
                'Personel'  : personel_kodu,
                'insUN'     : ins_un,
                'Giren'     : w_giren,
                'Cikan'     : w_giren,   # tamamlandi = Giren kadar
                'scikan'    : 0,
                'Fire'      : 0,
                'WMakNum'   : w_wmaknum,
                'EndTarih'  : end_tarih,
                'duplicate' : dup,
            })

        cur.close()

        if dry_run:
            return {
                'ok'             : True,
                'dry_run'        : True,
                'sebep'          : 'dry_run_tamam',
                'kayit_id'       : kayit_id,
                'planned_count'  : len(planned),
                'duplicate_count': dup_count,
                'planned_inserts': planned,
                'hata'           : None,
            }

        # --- 5) GERCEK INSERT (dry_run=False, onay alindi) ---
        from datetime import datetime as _dt

        def _to_dt(s):
            """ISO string -> datetime. None donerse GETDATE() yerine None gecilir."""
            if not s:
                return None
            for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M',
                        '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
                try:
                    return _dt.strptime(str(s)[:19], fmt)
                except ValueError:
                    continue
            return None

        eklenen = []
        atlanan = []
        for p in planned:
            if p['duplicate']:
                atlanan.append(p)
                continue
            send_tar    = _to_dt(p['SendTar'])
            start_tarih = _to_dt(p['StartTarih'])
            end_tarih   = _to_dt(p['EndTarih'])
            cur2 = k_con.cursor()
            cur2.execute(
                """
                INSERT INTO Urt_con_gch
                    (EmirNo, SKOD, RKOD, BedKod, FisNo, FisHarinx,
                     SendTar, StartTarih, Proses, AltProses, Personel,
                     EndTarih, Giren, Cikan, scikan, Fire, WMakNum,
                     insUN)
                VALUES
                    (%s, %s, %s, %s, %s, %s,
                     %s, %s, %s, %s, %s,
                     %s, %s, %s, %s, %s, %s,
                     %s)
                """,
                (
                    p['EmirNo'], p['SKOD'], p['RKOD'], p['BedKod'],
                    p['FisNo'], p['FisHarinx'],
                    send_tar, start_tarih,
                    p['Proses'], p['AltProses'] or None, p['Personel'] or None,
                    end_tarih,
                    p['Giren'], p['Cikan'], p['scikan'],
                    p['Fire'], p['WMakNum'],
                    p['insUN'],
                )
            )
            cur2.close()
            eklenen.append(p)

        k_con.commit()

        return {
            'ok'             : True,
            'dry_run'        : False,
            'sebep'          : 'con_insert_tamamlandi',
            'kayit_id'       : kayit_id,
            'planned_count'  : len(planned),
            'eklenen_count'  : len(eklenen),
            'duplicate_count': dup_count,
            'atlanan_count'  : len(atlanan),
            'planned_inserts': planned,
            'hata'           : None,
        }

    except Exception as e:
        return {
            'ok': False, 'dry_run': dry_run, 'sebep': 'korgun_sorgu_hatasi',
            'kayit_id': kayit_id, 'planned_count': 0, 'duplicate_count': 0,
            'planned_inserts': [],
            'hata': f'{type(e).__name__}: {str(e)[:300]}',
        }
    finally:
        try:
            k_con.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# FAZ 2B-4: CPS DB'de korgun_yazildi = 1 isle
# ---------------------------------------------------------------------------

def korgun_yazildi_isle(kayit_id, con_kgid_listesi=None, cps_db_path=None):
    """
    FAZ 2B-4: CPS uretim_kayit kaydini Korgun'a aktarildi olarak isaretler.

    UPDATE uretim_kayit
    SET korgun_yazildi = 1,
        korgun_hata    = NULL
    WHERE id = kayit_id

    Korgun DB'ye hicbir yazma yapilmaz.

    Parametreler:
        kayit_id         : CPS uretim_kayit.id
        con_kgid_listesi : Urt_con_gch'de olusturulan kgid listesi (bilgi icin, sema kolonu yok)
        cps_db_path      : SQLite DB yolu (None ise Config'den)

    Donus:
        {
            'ok'              : bool,
            'sebep'           : str,
            'kayit_id'        : int,
            'onceki_durum'    : dict,
            'sonraki_durum'   : dict,
            'con_kgid_listesi': list,
            'hata'            : str | None,
        }
    """
    if cps_db_path is None:
        try:
            import os, sys as _sys
            _app_dir = os.path.join(os.path.dirname(__file__), '..', '..')
            _sys.path.insert(0, os.path.abspath(_app_dir))
            from config import Config
            cps_db_path = Config.MOCK_DB_PATH
        except Exception as e:
            return {
                'ok': False, 'sebep': 'config_hatasi',
                'kayit_id': kayit_id, 'onceki_durum': {},
                'sonraki_durum': {}, 'con_kgid_listesi': con_kgid_listesi or [],
                'hata': f'Config okunamadi: {e}',
            }

    cps_conn = sqlite3.connect(cps_db_path)
    cps_conn.row_factory = sqlite3.Row

    try:
        # 1) Kayit var mi ve mevcut durum nedir?
        kayit = cps_conn.execute(
            """
            SELECT id, emir_no, proses_kodu, korgun_proses_kodu,
                   korgun_fis_no, korgun_fis_harinx,
                   korgun_yazildi, korgun_hata,
                   usta_ad, miktar, kaynak, tarih
            FROM uretim_kayit WHERE id = ?
            """,
            (kayit_id,)
        ).fetchone()

        if not kayit:
            return {
                'ok': False, 'sebep': 'kayit_yok',
                'kayit_id': kayit_id, 'onceki_durum': {},
                'sonraki_durum': {}, 'con_kgid_listesi': con_kgid_listesi or [],
                'hata': f'uretim_kayit id={kayit_id} bulunamadi',
            }

        onceki = dict(kayit)

        # 2) Zaten isaretli mi?
        if _iv(onceki.get('korgun_yazildi')) == 1:
            return {
                'ok': False, 'sebep': 'zaten_isaretli',
                'kayit_id': kayit_id, 'onceki_durum': onceki,
                'sonraki_durum': onceki, 'con_kgid_listesi': con_kgid_listesi or [],
                'hata': None,
            }

        # 3) UPDATE
        cps_conn.execute(
            """
            UPDATE uretim_kayit
            SET korgun_yazildi = 1,
                korgun_hata    = NULL
            WHERE id = ?
            """,
            (kayit_id,)
        )
        cps_conn.commit()

        # 4) Dogrulama SELECT
        sonraki_row = cps_conn.execute(
            """
            SELECT id, emir_no, proses_kodu, korgun_proses_kodu,
                   korgun_fis_no, korgun_fis_harinx,
                   korgun_yazildi, korgun_hata,
                   usta_ad, miktar, kaynak, tarih
            FROM uretim_kayit WHERE id = ?
            """,
            (kayit_id,)
        ).fetchone()
        sonraki = dict(sonraki_row) if sonraki_row else {}

        if _iv(sonraki.get('korgun_yazildi')) != 1:
            return {
                'ok': False, 'sebep': 'dogrulama_basarisiz',
                'kayit_id': kayit_id, 'onceki_durum': onceki,
                'sonraki_durum': sonraki, 'con_kgid_listesi': con_kgid_listesi or [],
                'hata': 'UPDATE sonrasi korgun_yazildi hala 1 degil',
            }

        return {
            'ok': True, 'sebep': 'isaretlendi',
            'kayit_id': kayit_id, 'onceki_durum': onceki,
            'sonraki_durum': sonraki, 'con_kgid_listesi': con_kgid_listesi or [],
            'hata': None,
        }

    except Exception as e:
        try:
            cps_conn.rollback()
        except Exception:
            pass
        return {
            'ok': False, 'sebep': 'cps_db_hatasi',
            'kayit_id': kayit_id, 'onceki_durum': {},
            'sonraki_durum': {}, 'con_kgid_listesi': con_kgid_listesi or [],
            'hata': f'{type(e).__name__}: {str(e)[:300]}',
        }
    finally:
        cps_conn.close()


# ---------------------------------------------------------------------------
# FAZ 2B-6: Birlesik aktarim servisi
# ---------------------------------------------------------------------------

def korgun_aktar(kayit_id, dry_run=True, cps_db_path=None):
    """
    FAZ 2B-6: Korgun aktarim zincirini tek cagrida calistirir.

    Akis:
      1) CPS uretim_kayit oku + Wait kontrol (2B-1 mantigi)
      2) Wait_kapat        (2B-2)  — Cikan = Giren, updUN = 'CPS_Halil'
      3) Con_insert_hazirla (2B-3) — Urt_con_gch INSERT paketi
      4) korgun_yazildi_isle (2B-4) — CPS: korgun_yazildi = 1

    dry_run=True  (varsayilan):
      Hicbir Korgun yazma yapilmaz.
      planned_wait ve planned_con listeleri dondurulur.
      CPS DB guncellenmez.

    dry_run=False (onay gerekli, bu fazda kullanilmaz):
      Gercek UPDATE + INSERT + CPS flag yazilir.

    Hata: herhangi bir adimda hata olursa:
      - islem durur
      - korgun_yazildi = 0 kalir
      - korgun_hata doldurulur (dry_run=False durumunda)

    Parametreler:
        kayit_id    : CPS uretim_kayit.id
        dry_run     : True = sadece plan raporu (varsayilan)
        cps_db_path : SQLite DB yolu (None ise Config'den)

    Donus:
        {
            'ok'            : bool,
            'dry_run'       : bool,
            'sebep'         : str,
            'kayit_id'      : int,
            'adimlar'       : {
                'paket'     : dict,   # 2B-1 sonucu
                'wait'      : dict,   # 2B-2 sonucu
                'con'       : dict,   # 2B-3 sonucu
                'cps_flag'  : dict,   # 2B-4 sonucu (dry_run=False'ta dolu)
            },
            'ozet'          : {
                'emir_no'   : int,
                'proses'    : str,
                'fis_no'    : int,
                'fis_harinx': int,
                'wait_sayi' : int,
                'con_sayi'  : int,
                'toplam_miktar': int,
                'personel'  : str,
            },
            'hata'          : str | None,
        }
    """
    adimlar = {'paket': {}, 'wait': {}, 'con': {}, 'cps_flag': {}}

    # -----------------------------------------------------------------------
    # ADIM 1: Aktarim paketi hazirla (CPS oku + Wait meta)
    # -----------------------------------------------------------------------
    paket = korgun_uretim_aktar(kayit_id, cps_db_path=cps_db_path)
    adimlar['paket'] = paket

    if not paket.get('ok'):
        sebep = paket.get('sebep', 'paket_hatasi')
        # wait_yok: CPS'e kayitli ama Korgun'da acik Wait satiri yok
        # Bu durum dry_run icin gecerlidir (Wait henuz acik olmayabilir)
        if sebep != 'wait_yok':
            return {
                'ok': False, 'dry_run': dry_run,
                'sebep': f'adim1_hatasi:{sebep}',
                'kayit_id': kayit_id,
                'adimlar': adimlar,
                'ozet': {},
                'hata': paket.get('hata') or f'Paket hazirlama basarisiz: {sebep}',
            }

    cps_kayit  = paket.get('cps_kayit') or {}
    emir_no    = _iv(cps_kayit.get('emir_no') or cps_kayit.get('korgun_emir_no'))
    proses     = _sv(cps_kayit.get('korgun_proses_kodu') or cps_kayit.get('proses_kodu'))
    fis_no     = _iv(cps_kayit.get('korgun_fis_no'))
    fis_harinx = _iv(cps_kayit.get('korgun_fis_harinx'))
    personel   = _sv((paket.get('paket') or {}).get('Personel'))

    # -----------------------------------------------------------------------
    # ADIM 2: Wait kontrol + dry_run icin simule (2B-2 mantigi)
    # -----------------------------------------------------------------------
    # dry_run=True: wait_kapat iclerde dry_run=True calisir, yazma yok
    wait_sonuc = wait_kapat(kayit_id, dry_run=dry_run, cps_db_path=cps_db_path)
    adimlar['wait'] = wait_sonuc

    if not wait_sonuc.get('ok'):
        sebep = wait_sonuc.get('sebep', 'wait_hatasi')
        return {
            'ok': False, 'dry_run': dry_run,
            'sebep': f'adim2_hatasi:{sebep}',
            'kayit_id': kayit_id,
            'adimlar': adimlar,
            'ozet': {},
            'hata': wait_sonuc.get('hata') or f'Wait kapat basarisiz: {sebep}',
        }

    # -----------------------------------------------------------------------
    # ADIM 2b: wait_kapat simule listesinden ozet al
    # FAZ 2B-7: wait_kapat artik tum satirlari ve kgid listesini dondurur
    # -----------------------------------------------------------------------
    simule_list    = wait_sonuc.get('simule') or []
    wait_kgid_list = wait_sonuc.get('wait_kgid_listesi') or []
    if not isinstance(simule_list, list):
        simule_list = [simule_list] if simule_list else []

    wait_sayi     = len(simule_list)
    toplam_miktar = sum(_iv(s.get('Giren')) for s in simule_list)
    wait_detay    = simule_list

    # -----------------------------------------------------------------------
    # ADIM 3: Con INSERT paketi hazirla
    # FAZ 2B-7: wait_kgid_list dry_run=True'da onizle kgid'lerini tasir
    #           dry_run=False'ta gercek kapanan kgid'leri tasir
    #           Her iki durumda con_insert_hazirla dogrudan kgid ile hedefler
    # -----------------------------------------------------------------------
    con_sonuc = con_insert_hazirla(
        kayit_id,
        dry_run=dry_run,
        cps_db_path=cps_db_path,
        wait_kgid_listesi=wait_kgid_list if wait_kgid_list else None,
    )
    adimlar['con'] = con_sonuc

    con_sayi  = con_sonuc.get('planned_count') or 0
    con_plani = con_sonuc.get('planned_inserts') or []

    # dry_run=True ve kgid listesi ile denendi ama wait satirlari henuz aciksa:
    # con_insert_hazirla kgid IN ile satirlari okur (Cikan/Giren kontrolu yok)
    # bu durumda con_plani dolu olmali; degilse wait_detay'dan tahmini plan yap
    if dry_run and not con_plani and wait_detay:
        _pb = None
        try:
            import sqlite3 as _sq3
            from config import Config as _Cfg
            _db = cps_db_path or _Cfg.MOCK_DB_PATH
            _cc = _sq3.connect(_db)
            _cc.row_factory = _sq3.Row
            _pb = _personel_kodu_coz(_cc, (paket.get('cps_kayit') or {}).get('usta_ad', ''))
            _cc.close()
        except Exception:
            pass
        _pcode = (_pb or {}).get('personel_kodu', personel)
        _insun = (_pb or {}).get('korgun_insUN', 'Uretim')
        from datetime import datetime as _dt2
        _end = _dt2.now().isoformat()[:19]
        for _wd in wait_detay:
            con_plani.append({
                'wait_kgid' : _iv(_wd.get('kgid')),
                'EmirNo'    : emir_no,
                'BedKod'    : _iv(_wd.get('BedKod')),
                'RKOD'      : _iv(_wd.get('RKOD')),
                'FisNo'     : fis_no,
                'FisHarinx' : fis_harinx,
                'Giren'     : _iv(_wd.get('Giren')),
                'Cikan'     : _iv(_wd.get('Giren')),
                'Personel'  : _pcode,
                'insUN'     : _insun,
                'EndTarih'  : _end,
                'duplicate' : False,
                '_kaynak'   : 'wait_tahmini',
            })
        con_sayi = len(con_plani)

    # dry_run=False ve con basarisizsa dur
    if not dry_run and not con_sonuc.get('ok'):
        sebep = con_sonuc.get('sebep', 'con_hatasi')
        return {
            'ok': False, 'dry_run': dry_run,
            'sebep': f'adim3_hatasi:{sebep}',
            'kayit_id': kayit_id,
            'adimlar': adimlar,
            'ozet': {},
            'hata': con_sonuc.get('hata') or f'Con insert basarisiz: {sebep}',
        }

    # dry_run=False ve con basarisizsa dur
    if not dry_run and not con_sonuc.get('ok'):
        sebep = con_sonuc.get('sebep', 'con_hatasi')
        return {
            'ok': False, 'dry_run': dry_run,
            'sebep': f'adim3_hatasi:{sebep}',
            'kayit_id': kayit_id,
            'adimlar': adimlar,
            'ozet': {},
            'hata': con_sonuc.get('hata') or f'Con insert basarisiz: {sebep}',
        }

    # -----------------------------------------------------------------------
    # ADIM 4: CPS flag — sadece dry_run=False'ta gercek yazma yapilir
    # -----------------------------------------------------------------------
    if not dry_run:
        cps_flag = korgun_yazildi_isle(kayit_id, cps_db_path=cps_db_path)
        adimlar['cps_flag'] = cps_flag

        if not cps_flag.get('ok'):
            sebep = cps_flag.get('sebep', 'cps_flag_hatasi')
            return {
                'ok': False, 'dry_run': dry_run,
                'sebep': f'adim4_hatasi:{sebep}',
                'kayit_id': kayit_id,
                'adimlar': adimlar,
                'ozet': {},
                'hata': cps_flag.get('hata') or f'CPS flag basarisiz: {sebep}',
            }

    # -----------------------------------------------------------------------
    # Basarili donus
    # -----------------------------------------------------------------------
    ozet = {
        'emir_no'       : emir_no,
        'proses'        : proses,
        'fis_no'        : fis_no,
        'fis_harinx'    : fis_harinx,
        'wait_sayi'     : wait_sayi,
        'con_sayi'      : con_sayi,
        'toplam_miktar' : toplam_miktar,
        'personel'      : personel,
        'con_plani'     : con_plani,
    }

    return {
        'ok'        : True,
        'dry_run'   : dry_run,
        'sebep'     : 'dry_run_tamam' if dry_run else 'aktar_tamamlandi',
        'kayit_id'  : kayit_id,
        'adimlar'   : adimlar,
        'ozet'      : ozet,
        'hata'      : None,
    }
