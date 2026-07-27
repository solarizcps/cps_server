# -*- coding: utf-8 -*-
"""FAZ-CARI-KART-SHELL-1A-DUZELTME — 404 koru; otomatik atama yok; Atanmamış."""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'app'
sys.path.insert(0, str(APP))
os.chdir(APP)

import app as flask_app
from modules.nexgen.cari360_kart_service import SORUMLU_ATANMAMIS, load_cari_kart
from modules.nexgen.cari_sorumlu_service import load_kullanici_yetkileri

app = flask_app.app
app.config['TESTING'] = True
client = app.test_client()


def login(uid=1, kadi='admin', rol_id=1):
    with client.session_transaction() as s:
        s['kullanici'] = {
            'Id': uid, 'KullaniciAdi': kadi, 'Tip': 'sistem',
            'RolId': rol_id, 'Aktif': 1,
        }
        s['kullanici_tip'] = 'sistem'


def _snapshot_cari1(con):
    return [
        dict(r)
        for r in con.execute(
            """
            SELECT id, kullanici_id, sorumluluk_rolu, aktif, bitis_tarihi, atama_notu
            FROM cari_sorumlu WHERE cari_id=1 ORDER BY id
            """
        )
    ]


def test_404_and_atanmamis_live():
    login()
    r0 = client.get('/nexgen/cari360/', follow_redirects=False)
    assert r0.status_code in (200, 302) and r0.status_code != 404
    print('PASS /cari360/ not 404', r0.status_code)

    assert client.get('/nexgen/cari360/1/', follow_redirects=False).status_code == 200
    print('PASS /cari360/1/ 200')

    ry = client.get('/nexgen/yonetim/', follow_redirects=True)
    html = ry.get_data(as_text=True)
    assert 'href="/nexgen/cari360/1"' in html
    assert 'href="/nexgen/cari360/"' not in html
    print('PASS yonetim links have ids')

    con = sqlite3.connect(str(APP / 'mock_data.db'))
    con.row_factory = sqlite3.Row
    before = _snapshot_cari1(con)
    data = load_cari_kart(con, 1, 1, {'*'})
    assert data['sorumlu_adi'] == SORUMLU_ATANMAMIS, data['sorumlu_adi']
    after = _snapshot_cari1(con)
    assert before == after, 'DB değişmemeli (planlamacı ataması pasifleştirilmez)'
    # Mehmet satırları hâlâ aktif olmalı (geri alınmış state)
    mehmet_aktif = [
        r for r in after
        if r['kullanici_id'] == 31 and r['aktif'] == 1
    ]
    assert mehmet_aktif, 'Mehmet otomatik pasif kalmamalı'
    erhan_aktif = con.execute(
        """
        SELECT COUNT(*) FROM cari_sorumlu cs
        JOIN sistem_kullanici sk ON sk.Id=cs.kullanici_id
        WHERE cs.cari_id=1 AND cs.aktif=1 AND lower(sk.KullaniciAdi)='erhan'
        """
    ).fetchone()[0]
    assert erhan_aktif == 0, 'Erhan otomatik ANA olmamalı'
    con.close()

    h = client.get('/nexgen/cari360/1').get_data(as_text=True)
    assert 'Atanmamış' in h
    print('PASS planlamacı atalı → Atanmamış, DB değişmez')

    mehmet = sqlite3.connect(str(APP / 'mock_data.db')).execute(
        "SELECT Id, RolId FROM sistem_kullanici WHERE KullaniciAdi='mehmet'"
    ).fetchone()
    login(int(mehmet[0]), 'mehmet', int(mehmet[1] or 0))
    assert client.post(
        '/nexgen/api/yonetim/cari-yetkili-ekle',
        json={'cari_id': 1, 'ad_soyad': '1A-Blok'},
    ).status_code == 403
    print('PASS Mehmet write 403')


def test_fixture_gercek_pazarlamaci_temp_db():
    """Geçici DB fixture — canlı mock'a yazmaz; gerçek pazarlamacı adı görünür."""
    tmp = tempfile.mkdtemp(prefix='ckart1a_')
    db = os.path.join(tmp, 't.db')
    shutil.copy2(str(APP / 'mock_data.db'), db)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    # fixture kullanıcı: yalnız view_own + crm.write (planlama değil)
    con.execute(
        """
        INSERT INTO sistem_kullanici
            (KullaniciAdi, AdSoyad, Sifre, RolId, Rol, Aktif, Tip)
        VALUES ('pazar_test', 'Ayşe Pazarlama', 'x', NULL, NULL, 1, 'sistem')
        """
    )
    pid = int(con.execute('SELECT last_insert_rowid()').fetchone()[0])
    for kod, flags in (
        ('cari360.view_own', (1, 0, 0, 0, 0, 0, 0)),
        ('cari360.crm.write', (1, 1, 1, 0, 0, 0, 0)),
    ):
        yid = con.execute('SELECT Id FROM sistem_yetki WHERE Kod=?', (kod,)).fetchone()
        if not yid:
            continue
        con.execute(
            """
            INSERT INTO user_permission_override
                (KullaniciId, YetkiId, can_view, can_create, can_update, can_delete,
                 can_approve, can_report, can_manage)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (pid, int(yid[0]), *flags),
        )
    # cari 2 — Mehmet yok; fixture ANA
    con.execute(
        """
        INSERT INTO cari_sorumlu (cari_id, kullanici_id, sorumluluk_rolu, aktif, atama_notu)
        VALUES (2, ?, 'ANA', 1, 'TEST_FIXTURE_ONLY')
        """,
        (pid,),
    )
    con.commit()
    data = load_cari_kart(con, 2, 1, {'*'})
    assert 'Ayşe' in (data['sorumlu_adi'] or ''), data['sorumlu_adi']
    assert data['sorumlu_adi'] != SORUMLU_ATANMAMIS
    con.close()
    shutil.rmtree(tmp, ignore_errors=True)
    print('PASS fixture gerçek pazarlamacı adı görünür')


def main():
    test_404_and_atanmamis_live()
    test_fixture_gercek_pazarlamaci_temp_db()
    print('ALL 1A-DUZELTME TESTS PASS')


if __name__ == '__main__':
    main()
