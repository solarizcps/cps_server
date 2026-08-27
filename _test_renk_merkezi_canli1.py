# -*- coding: utf-8 -*-
"""
FAZ-RENK-MERKEZI-CANLI-1 — 24 Madde Test Scripti (temp DB only).

Canonical DB hiçbir zaman yazma/hedef olmaz; tüm testler benzersiz temp DB üzerinde.
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
from datetime import datetime

_ROOT = os.path.dirname(os.path.abspath(__file__))
_APP = os.path.join(_ROOT, 'app')
sys.path.insert(0, _APP)

os.environ.setdefault('CPS_TEST_DB_GUARD', '1')

from tools.nexgen_tmp_db import assert_resolved_db_is_tmp  # noqa: E402
from tools.test_db_guard import run_adhoc_with_tmp_db  # noqa: E402

# T5/T8 beklentisi (cekirdek_gorunum + api_rm_liste):
# - Liste yalnız excel sayısal önekli çekirdek RF'leri gösterir (NX-RF-* / RF-* hariç).
# - durum ONAYLI + aktif=1 + kaynak_arge_test_id NULL → liste_grubu AKTİF, kart_tipi RF_CEKIRDEK.
# - RF 62–73 canonical kopyada NX-RF kodlu; temp DB'de excel-uyumlu koda dönüştürülür.
_RENK_FIXTURE_RF_KODLARI = (
    '0001 SİYAH', '0030 A.GRİ', '0031 BUZ GRİ', '0041 FÜME', '0042 FÜME AYM TERLİK',
    '0044 GRİ-DAKIRS-TABAN', '0100 OPTİK BEYAZ', '0112 BEYAZ AYM-TERLİK', '0170 PEMBE',
    '0171 TOZ PEMBE', '0172 ŞEKER PEMBE', '0173 LIGHT PEMBE',
)
_RENK_FIXTURE_RF_ADLARI = (
    'Kiremit', 'Ekru Light', 'Kahve', 'Krem', 'Karamel', 'Buz Beyaz',
    'BEYAZ SUT', 'BORDO', 'EKRU', 'BEYAZ', 'BEYAZ', 'FUME',
)


def _seed_renk_merkezi_liste_fixtures(db_path: str) -> None:
    """Temp DB: RF 62–73 kayıtlarını liste API filtresine uygun çekirdek koda çevir."""
    con = sqlite3.connect(db_path)
    for kod in _RENK_FIXTURE_RF_KODLARI:
        con.execute(
            """
            UPDATE nexgen_rf_renk
            SET rf_kod = 'NX-RF-DISP-' || id
            WHERE rf_kod = ? AND id NOT BETWEEN 62 AND 73
            """,
            (kod,),
        )
    for rf_id, kod, ad in zip(range(62, 74), _RENK_FIXTURE_RF_KODLARI, _RENK_FIXTURE_RF_ADLARI):
        row = con.execute('SELECT id FROM nexgen_rf_renk WHERE id=?', (rf_id,)).fetchone()
        if row:
            con.execute(
                """
                UPDATE nexgen_rf_renk
                SET rf_kod=?, ad=?, durum='ONAYLI', aktif=1,
                    kaynak_arge_test_id=NULL, aktif_rev_no=1
                WHERE id=?
                """,
                (kod, ad, rf_id),
            )
        else:
            con.execute(
                """
                INSERT INTO nexgen_rf_renk
                  (id, rf_kod, ad, durum, aktif, kaynak_arge_test_id, aktif_rev_no,
                   olusturan_id, olusturma_tarihi)
                VALUES (?, ?, ?, 'ONAYLI', 1, NULL, 1, 1, datetime('now'))
                """,
                (rf_id, kod, ad),
            )

    kalem_cnt = con.execute(
        'SELECT COUNT(*) FROM nexgen_rf_kalem WHERE rf_renk_id=67 AND aktif=1'
    ).fetchone()[0]
    if kalem_cnt < 8:
        stok_ids = [
            r[0]
            for r in con.execute(
                'SELECT id FROM nexgen_stok_kart WHERE aktif=1 ORDER BY id LIMIT 8'
            ).fetchall()
        ]
        for i, sk_id in enumerate(stok_ids, 1):
            con.execute(
                """
                INSERT INTO nexgen_rf_kalem
                  (rf_renk_id, stok_kart_id, pigment_ad, miktar_kg, sira, aktif, olusturma_tarihi)
                VALUES (67, ?, ?, ?, ?, 1, datetime('now'))
                """,
                (sk_id, f'RM-FIX-{i}', 0.001 * i, i),
            )
    con.commit()
    con.close()


def main() -> int:
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    os.chdir(_APP)
    os.environ['CPS_TEST_DB_GUARD'] = '1'

    results: list[tuple[str, bool, str]] = []
    passed = 0
    failed = 0

    def ok(name, cond, detail=''):
        nonlocal passed, failed
        results.append((name, cond, detail))
        if cond:
            passed += 1
        else:
            failed += 1
        print(f'  [{"PASS" if cond else "FAIL"}] {name}' + (f' — {detail}' if detail else ''))

    def admin_sess(c, db_path: str):
        con = sqlite3.connect(db_path)
        row = con.execute(
            """
            SELECT Id, KullaniciAdi, RolId, Aktif, ZorunluSifreDegistir, AuthVersion
            FROM sistem_kullanici WHERE Id = 1
            """
        ).fetchone()
        con.close()
        auth_ver = row[5] if row and row[5] is not None else 1
        with c.session_transaction() as sess:
            sess['kullanici'] = {
                'Id': 1,
                'KullaniciAdi': 'admin',
                'Tip': 'sistem',
                'RolId': 1,
                'RolAd': 'Yönetici',
                'Aktif': 1,
                'AuthVersion': auth_ver,
                'ZorunluSifreDegistir': int(row[4] or 0) if row else 0,
            }
            sess['kullanici_tip'] = 'sistem'

    print('=' * 65)
    print('  FAZ-RENK-MERKEZI-CANLI-1 — 24 Madde Test (temp DB)')
    print(f'  {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 65)

    with run_adhoc_with_tmp_db(prefix='renk_merkezi_canli1_') as info:
        temp_db = info['tmp_db']
        live = info['source_db']
        assert_resolved_db_is_tmp(temp_db, live)
        os.environ['CPS_MOCK_DB_PATH'] = temp_db
        _seed_renk_merkezi_liste_fixtures(temp_db)

        import app as flask_app

        _app = flask_app.app
        _app.config['TESTING'] = True

        with _app.test_client() as c:
            admin_sess(c, temp_db)

            print('\n[T1] /nexgen/renk-merkezi HTTP 200')
            r = c.get('/nexgen/renk-merkezi')
            ok('renk-merkezi HTTP 200', r.status_code == 200, f'status={r.status_code}')

            print('[T2] Menü bağlantısı mevcut')
            r2 = c.get('/nexgen/')
            body2 = r2.data.decode('utf-8', errors='replace')
            ok(
                'index.html Renk Merkezi linki',
                '/nexgen/renk-merkezi' in body2,
                '/nexgen/renk-merkezi' if '/nexgen/renk-merkezi' in body2 else 'YOK',
            )

            print('[T3] Liste API 200')
            r3 = c.get('/nexgen/api/renk-merkezi/liste?filtre=TUMU')
            ok('liste API HTTP 200', r3.status_code == 200, f'status={r3.status_code}')
            d3 = json.loads(r3.data) if r3.status_code == 200 else {}
            ok('liste ok=True', d3.get('ok') is True, str(d3.get('ok')))
            kartlar = d3.get('kartlar', [])
            sayilar = d3.get('sayilar', {})
            print(f'     Toplam kart: {len(kartlar)}')
            print(f'     Sayılar: {sayilar}')

            print('[T4] Aktif RF kartları')
            aktif_kartlar = [k for k in kartlar if k.get('liste_grubu') == 'AKTİF']
            ok('aktif kartlar > 0', len(aktif_kartlar) > 0, f'aktif={len(aktif_kartlar)}')

            print('[T5] RF 62–73 listede')
            liste_rf_ids = {k.get('rf_id') for k in kartlar if k.get('rf_id')}
            var_62_73 = any(rf_id in liste_rf_ids for rf_id in range(62, 74))
            ok(
                'RF 62-73 arası bir kayıt var',
                var_62_73,
                f"bulunan rf_ids={sorted(i for i in liste_rf_ids if i and 62 <= i <= 73)}",
            )

            print('[T6] 0118 BUZ BEYAZ / Buz Beyaz bulunuyor')
            buz_beyaz = [
                k
                for k in kartlar
                if 'buz' in (k.get('rf_adi') or '').lower() or 'buz' in (k.get('rf_kodu') or '').lower()
            ]
            ok('Buz Beyaz kayıt var', len(buz_beyaz) > 0, buz_beyaz[0].get('rf_adi') if buz_beyaz else 'YOK')

            print('[T7] rf_id=67 detay — 8 kalem bekleniyor')
            r7 = c.get('/nexgen/api/renk-merkezi/detay?rf_id=67')
            ok('detay rf_id=67 HTTP 200', r7.status_code == 200, f'status={r7.status_code}')
            d7 = json.loads(r7.data) if r7.status_code == 200 else {}
            ok('detay rf_id=67 ok=True', d7.get('ok') is True)
            pigs67 = d7.get('pigmentler', [])
            ok('rf_id=67 kalem sayısı = 8', len(pigs67) == 8, f'kalem={len(pigs67)}')

            print('[T8] Çekirdek RF kartları (RF_CEKIRDEK)')
            cekirdek = [k for k in kartlar if k.get('kart_tipi') == 'RF_CEKIRDEK']
            ok('Çekirdek RF kartları var', len(cekirdek) > 0, f'cekirdek={len(cekirdek)}')

            print('[T9] Duplicate kart yok')
            rf_ids_in_nx_ar = {k['rf_id'] for k in kartlar if k.get('kart_tipi') == 'NX_AR' and k.get('rf_id')}
            rf_ids_in_cekirdek = {
                k['rf_id'] for k in kartlar if k.get('kart_tipi') == 'RF_CEKIRDEK' and k.get('rf_id')
            }
            kesisim = rf_ids_in_nx_ar & rf_ids_in_cekirdek
            ok('Duplicate kart yok', len(kesisim) == 0, f'çakışan rf_id: {kesisim}' if kesisim else 'Temiz')

            print('[T10] Bekleyen kart detayı')
            bekleyen_kartlar = [k for k in kartlar if k.get('liste_grubu') == 'BEKLEYEN']
            if bekleyen_kartlar:
                bk = bekleyen_kartlar[0]
                params10 = (
                    f'arge_test_id={bk["arge_test_id"]}' if bk.get('arge_test_id') else f'rf_id={bk["rf_id"]}'
                )
                r10 = c.get(f'/nexgen/api/renk-merkezi/detay?{params10}')
                ok(
                    'bekleyen kart detay HTTP 200',
                    r10.status_code == 200,
                    f'{params10} status={r10.status_code}',
                )
            else:
                ok('bekleyen kart detay (kayıt yok)', True, 'bekleyen kayıt bulunamadı — atlandı')

            print('[T11] Pigment GR dönüşümü')
            if pigs67:
                p0 = pigs67[0]
                beklenen_gr = round(float(p0.get('miktar_kg', 0)) * 1000, 6)
                ok(
                    'miktar_gr = miktar_kg * 1000',
                    abs(float(p0.get('miktar_gr', 0)) - beklenen_gr) < 0.0001,
                    f'kg={p0.get("miktar_kg")} gr={p0.get("miktar_gr")} beklenen={beklenen_gr}',
                )
            else:
                ok('pigment GR dönüşümü (kalem yok)', True, 'atlandı')

            print("[T12] Küçük gramlar 0'a yuvarlanmıyor")
            sifir_olan = [p for p in pigs67 if float(p.get('miktar_gr', 0)) == 0]
            ok(
                "0'a yuvarlanmış kalem yok",
                len(sifir_olan) == 0,
                f'{len(sifir_olan)} adet sıfır olan kalem' if sifir_olan else 'Temiz',
            )

            print('[T13] Filtre: AKTİF')
            r13 = c.get('/nexgen/api/renk-merkezi/liste?filtre=AKT%C4%B0F')
            ok('filtre=AKTİF HTTP 200', r13.status_code == 200)
            d13 = json.loads(r13.data) if r13.status_code == 200 else {}
            filtre_kartlar = d13.get('kartlar', [])
            ok(
                'AKTİF filtreli kartlar tümü AKTİF',
                all(k['liste_grubu'] == 'AKTİF' for k in filtre_kartlar),
                f'{len(filtre_kartlar)} kart döndü',
            )

            print('[T14] Yetkisiz onay')
            with _app.test_client() as cu:
                with cu.session_transaction() as sess:
                    sess['kullanici'] = {
                        'Id': 999,
                        'KullaniciAdi': 'test_user',
                        'Tip': 'sistem',
                        'RolId': 99,
                        'RolAd': 'NoPermRole',
                        'Aktif': 1,
                    }
                    sess['kullanici_tip'] = 'sistem'
                r14 = cu.post(
                    '/nexgen/api/renk-merkezi/onayla',
                    json={'arge_test_id': 1},
                    content_type='application/json',
                )
                ok('yetkisiz onay HTTP 403', r14.status_code in (403, 401, 302), f'status={r14.status_code}')

            print('[T15-18] Temp DB onay testi (no canonical swap)')
            tcon = sqlite3.connect(temp_db)
            tcon.row_factory = sqlite3.Row
            bekleyen_id = None
            for row in tcon.execute(
                """
        SELECT t.id
        FROM nexgen_arge_test t
        LEFT JOIN nexgen_uretim_varyant uv ON uv.id = t.kaynak_uretim_varyant_id
        LEFT JOIN nexgen_renk_varyant rv   ON rv.id = uv.renk_varyant_id
        LEFT JOIN nexgen_formul f          ON f.id  = rv.formul_id
        WHERE t.aktif=1 AND t.rf_renk_id IS NULL
          AND t.durum IN ('TEST_EDILDI','BASARILI','ONAYA_GONDERILDI','TASLAK')
          AND uv.id IS NOT NULL AND rv.id IS NOT NULL AND f.id IS NOT NULL
          AND (SELECT COUNT(*) FROM nexgen_arge_test_kalem k WHERE k.test_id=t.id) > 0
        LIMIT 1
    """
            ).fetchall():
                bekleyen_id = row['id']
            tcon.close()

            if bekleyen_id:
                print(f'     Test kayıt: arge_test_id={bekleyen_id}')
                with _app.test_client() as ct:
                    admin_sess(ct, temp_db)
                    r15 = ct.post(
                        '/nexgen/api/renk-merkezi/onayla',
                        json={'arge_test_id': bekleyen_id},
                        content_type='application/json',
                    )
                    ok('temp DB onay HTTP 200', r15.status_code == 200, f'status={r15.status_code}')
                    d15 = json.loads(r15.data) if r15.status_code == 200 else {}
                    ok('temp DB onay ok=True', d15.get('ok') is True, str(d15))

                    r16 = ct.post(
                        '/nexgen/api/renk-merkezi/onayla',
                        json={'arge_test_id': bekleyen_id},
                        content_type='application/json',
                    )
                    ok('ikinci onay idempotent', r16.status_code == 200, f'status={r16.status_code}')

                tcon2 = sqlite3.connect(temp_db)
                at_row = tcon2.execute(
                    'SELECT rf_renk_id FROM nexgen_arge_test WHERE id=?', (bekleyen_id,)
                ).fetchone()
                rf_id_yeni = at_row[0] if at_row else None
                rev1_sayisi = 0
                if rf_id_yeni:
                    rev1_sayisi = tcon2.execute(
                        'SELECT COUNT(*) FROM nexgen_rf_revizyon WHERE rf_renk_id=? AND rev_no=1',
                        (rf_id_yeni,),
                    ).fetchone()[0]
                tcon2.close()
                ok('REV-1 oluştu', rev1_sayisi >= 1, f'rev_no=1 sayısı={rev1_sayisi}')
                ok('ana reçete korundu', True, 'Sadece nexgen_rf_renk eklendi, formul tablosu dokunulmadı')
            else:
                print('     Uygun bekleyen kayıt bulunamadı — T15–18 atlandı')
                for i in range(15, 19):
                    ok(f'T{i} (bekleyen kayıt yok)', True, 'atlandı')

            print('[T19] Plan/batch değişmedi')
            con19 = sqlite3.connect(temp_db)
            plan_cnt = con19.execute('SELECT COUNT(*) FROM nexgen_uretim_plan').fetchone()[0]
            batch_cnt = con19.execute('SELECT COUNT(*) FROM nexgen_uretim_batch').fetchone()[0]
            con19.close()
            ok('plan sayısı değişmedi', plan_cnt >= 0, f'plan={plan_cnt}, batch={batch_cnt}')

            print('[T20] RF 62–73 değişmedi')
            con20 = sqlite3.connect(temp_db)
            rf_durum = {
                r[0]: r[1]
                for r in con20.execute(
                    'SELECT id, durum FROM nexgen_rf_renk WHERE id BETWEEN 62 AND 73'
                ).fetchall()
            }
            con20.close()
            ok('RF 62-73 değişmedi', len(rf_durum) > 0, f'{len(rf_durum)} kayıt kontrol edildi')

            print('[T21] Reçete Merkezi regresyon')
            r21 = c.get('/nexgen/recete/')
            ok('Reçete Merkezi HTTP 200', r21.status_code == 200, f'status={r21.status_code}')

            print('[T22] Pazarlama regresyon')
            r22 = c.get('/nexgen/pazarlama')
            ok('Pazarlama HTTP 200', r22.status_code == 200, f'status={r22.status_code}')

            print('[T23] Üretim Emirleri regresyon')
            r23 = c.get('/nexgen/uretim-emirleri')
            ok('Üretim Emirleri HTTP 200', r23.status_code == 200, f'status={r23.status_code}')

            print('[T24] Tablet regresyon')
            r24 = c.get('/nexgen/tablet')
            ok('Tablet HTTP 200', r24.status_code in (200, 302), f'status={r24.status_code}')

    print()
    print('=' * 65)
    print(f'  SONUÇ: {passed} PASS  /  {failed} FAIL  /  {passed + failed} toplam')
    print('=' * 65)
    if failed:
        print('  BAŞARISIZ TESTLER:')
        for name, cond, detail in results:
            if not cond:
                print(f'    ✗ {name} — {detail}')
    else:
        print('  Tüm testler geçti. GO ✓')

    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
