import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from PIL import Image

from modules import auth
from modules.yonetim import routes
from modules.enjeksiyon import routes as enj_routes


class ConnectionWrapper:
    def __init__(self, path, *, fail_commit=False, reject_select_after_commit=False, fail_update=False):
        self.raw=sqlite3.connect(path)
        self.fail_commit=fail_commit
        self.reject_select_after_commit=reject_select_after_commit
        self.fail_update=fail_update
        self.committed=False
        self.commit_count=0
        self.rollback_count=0
        self.close_count=0
    def cursor(self): return CursorWrapper(self,self.raw.cursor())
    def execute(self,*args,**kwargs): return self.cursor().execute(*args,**kwargs)
    def commit(self):
        self.commit_count+=1
        if self.fail_commit: raise sqlite3.OperationalError("controlled commit failure /secret")
        result=self.raw.commit(); self.committed=True; return result
    def rollback(self): self.rollback_count+=1; return self.raw.rollback()
    def close(self): self.close_count+=1; return self.raw.close()


class CursorWrapper:
    def __init__(self,owner,raw): self.owner=owner; self.raw=raw
    def execute(self,sql,*args,**kwargs):
        if self.owner.fail_update and sql.lstrip().upper().startswith("UPDATE"):
            raise sqlite3.OperationalError("controlled update failure /secret")
        if self.owner.committed and self.owner.reject_select_after_commit and sql.lstrip().upper().startswith("SELECT"):
            raise sqlite3.OperationalError("post-commit select forbidden")
        self.raw.execute(sql,*args,**kwargs); return self
    def fetchone(self): return self.raw.fetchone()
    def fetchall(self): return self.raw.fetchall()
    @property
    def lastrowid(self): return self.raw.lastrowid
    @property
    def rowcount(self): return self.raw.rowcount


def sqlite_proxy(factory):
    return type("SQLiteProxy",(),{
        "IntegrityError":sqlite3.IntegrityError,
        "connect":staticmethod(factory),
    })


class KalipGuvenlikTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="kalip_guvenlik_py313_"))
        cls.db = cls.root / "kalip_test.db"
        cls.upload = cls.root / "uploads"
        cls.upload.mkdir()
        cls.app = Flask("kalip_guvenlik_test")
        cls.app.secret_key = "test-only"
        cls.app.register_blueprint(routes.yonetim_bp)
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        print("UPLOAD_TEST_KLASORU=" + str(cls.root))

    def setUp(self):
        if self.db.exists():
            self.db.unlink()
        con = sqlite3.connect(self.db)
        con.executescript("""
        CREATE TABLE enj_kalip(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          kalip_kod TEXT UNIQUE NOT NULL,
          kalip_tipi TEXT NOT NULL,
          model_kod TEXT NOT NULL,
          model_ad TEXT,
          asorti TEXT,
          kalip_basi_cift INTEGER NOT NULL,
          varsayilan_bagli_kalip INTEGER NOT NULL,
          renk TEXT,
          gorsel_dosya TEXT,
          aktif INTEGER NOT NULL DEFAULT 1,
          kapasite_cift INTEGER,
          kalip_durumu TEXT NOT NULL DEFAULT 'AKTIF',
          aciklama TEXT,
          cift_agirlik_gr REAL,
          pisme_suresi_sn INTEGER,
          olusturma_tarihi TEXT,
          guncelleme_tarihi TEXT
        );
        """)
        con.commit(); con.close()
        for p in self.upload.iterdir():
            if p.is_file(): p.unlink()
        routes._KY_IMG_KLASOR = str(self.upload)
        self.path_patch = patch.object(routes, "_ky_db_path", return_value=str(self.db))
        self.enj_path_patch = patch.object(enj_routes, "_enj_kalip_db_path", return_value=str(self.db))
        self.audit_patch = patch.object(routes.audit, "log")
        self.path_patch.start(); self.enj_path_patch.start(); self.audit = self.audit_patch.start()

    def tearDown(self):
        self.audit_patch.stop(); self.enj_path_patch.stop(); self.path_patch.stop()

    def login(self):
        with self.client.session_transaction() as s:
            s["kullanici"] = {"KullaniciAdi": "tester"}

    def post_create(self, **overrides):
        self.login()
        body={"kalip_kod":" k-001 ","kalip_tipi":"GOVDE","model_kod":"M1",
              "kalip_basi_cift":4,"varsayilan_bagli_kalip":8}
        body.update(overrides)
        with patch.object(auth, "yetki_var", return_value=True):
            return self.client.post("/yonetim/api/kalip/ekle", json=body)

    def seed(self, kod="K-001", gorsel=None, aktif=1, durum="AKTIF"):
        con=sqlite3.connect(self.db)
        cur=con.execute("""INSERT INTO enj_kalip
          (kalip_kod,kalip_tipi,model_kod,kalip_basi_cift,varsayilan_bagli_kalip,
           gorsel_dosya,aktif,kalip_durumu) VALUES(?,?,?,?,?,?,?,?)""",
          (kod,"GOVDE","M1",4,8,gorsel,aktif,durum))
        con.commit(); rid=cur.lastrowid; con.close(); return rid

    def image(self, fmt, size=(8,8)):
        b=io.BytesIO(); Image.new("RGB",size,(20,40,60)).save(b,format=fmt); b.seek(0); return b

    def upload_image(self, rid, fmt="JPEG", ext="jpg", mime="image/jpeg", stream=None):
        self.login()
        stream = stream or self.image(fmt)
        with patch.object(auth, "yetki_var", return_value=True):
            return self.client.post(f"/yonetim/api/kalip/{rid}/gorsel",
                data={"file":(stream,"resim."+ext,mime)}, content_type="multipart/form-data")

    def row(self, rid):
        con=sqlite3.connect(self.db); con.row_factory=sqlite3.Row
        r=dict(con.execute("SELECT * FROM enj_kalip WHERE id=?",(rid,)).fetchone()); con.close(); return r

    def test_01_yeni_kalip(self):
        r=self.post_create(); self.assertEqual(201,r.status_code); self.assertTrue(r.get_json()["ok"]); self.assertEqual("k-001",self.row(1)["kalip_kod"])

    def test_02_duplicate(self):
        self.assertEqual(201,self.post_create().status_code); r=self.post_create(kalip_kod="k-001"); self.assertEqual(400,r.status_code); self.assertEqual("DUPLICATE_KOD",r.get_json()["tip"])

    def test_03_kbc_sifir(self): self.assertEqual(400,self.post_create(kalip_basi_cift=0).status_code)
    def test_04_kbc_negatif(self): self.assertEqual(400,self.post_create(kalip_basi_cift=-1).status_code)
    def test_05_kbc_metin(self): self.assertEqual(400,self.post_create(kalip_basi_cift="abc").status_code)
    def test_06_kbc_21(self): self.assertEqual(400,self.post_create(kalip_basi_cift=21).status_code)

    def test_07_aktif_pasif_tutarliligi(self):
        r=self.post_create(aktif=1,kalip_durumu="PASIF"); self.assertEqual(400,r.status_code)
        r=self.post_create(kalip_kod="K-002",aktif=0,kalip_durumu="PASIF"); self.assertEqual(201,r.status_code); self.assertEqual((0,"PASIF"),(self.row(1)["aktif"],self.row(1)["kalip_durumu"]))

    def test_08_gorselsiz(self): self.assertIsNone(self.post_create().get_json()["kalip"]["gorsel_dosya"])
    def test_09_jpeg(self): self.assertEqual(200,self.upload_image(self.seed(),"JPEG","jpg","image/jpeg").status_code)
    def test_10_png(self): self.assertEqual(200,self.upload_image(self.seed(),"PNG","png","image/png").status_code)
    def test_11_webp(self): self.assertEqual(200,self.upload_image(self.seed(),"WEBP","webp","image/webp").status_code)
    def test_12_gif_reddi(self): self.assertEqual(400,self.upload_image(self.seed(),"GIF","gif","image/gif").status_code)

    def test_13_bes_mb_ustu(self):
        r=self.upload_image(self.seed(),ext="jpg",mime="image/jpeg",stream=io.BytesIO(b"x"*(5*1024*1024+1)))
        self.assertEqual(400,r.status_code); self.assertEqual([],list(self.upload.iterdir()))

    def test_14_sahte_jpg(self):
        r=self.upload_image(self.seed(),stream=io.BytesIO(b"not-jpeg")); self.assertEqual(400,r.status_code); self.assertEqual([],list(self.upload.iterdir()))

    def test_15_gorsel_degistirme(self):
        old="old.jpg"; (self.upload/old).write_bytes(self.image("JPEG").getvalue()); rid=self.seed(gorsel=old)
        r=self.upload_image(rid,"PNG","png","image/png"); self.assertEqual(200,r.status_code); self.assertNotEqual(old,self.row(rid)["gorsel_dosya"])

    def test_16_db_hatasinda_orphan_yok(self):
        rid=self.seed(); con=sqlite3.connect(self.db)
        con.execute("CREATE TRIGGER fail_img BEFORE UPDATE OF gorsel_dosya ON enj_kalip BEGIN SELECT RAISE(FAIL,'secret-sql'); END;"); con.commit(); con.close()
        r=self.upload_image(rid); self.assertEqual(500,r.status_code); self.assertEqual([],list(self.upload.iterdir())); self.assertNotIn("secret-sql",r.get_data(as_text=True))

    def test_17_paylasilan_eski_dosya_korunur(self):
        old="shared.jpg"; (self.upload/old).write_bytes(self.image("JPEG").getvalue()); rid=self.seed(gorsel=old); self.seed("K-002",old)
        self.assertEqual(200,self.upload_image(rid).status_code); self.assertTrue((self.upload/old).exists())

    def test_18_can_create(self):
        self.login()
        with patch.object(auth,"yetki_var",return_value=False):
            r=self.client.post("/yonetim/api/kalip/ekle",json={})
        self.assertEqual(403,r.status_code)

    def test_19_can_update(self):
        self.login(); rid=self.seed()
        with patch.object(auth,"yetki_var",return_value=False):
            r=self.client.post(f"/yonetim/api/kalip/{rid}/gorsel",data={})
        self.assertEqual(403,r.status_code)

    def test_20_audit(self):
        self.post_create(); self.assertEqual("KALIP_CREATE",self.audit.call_args.args[1]); self.assertEqual("enj_kalip",self.audit.call_args.args[2])
        self.audit.reset_mock(); rid=1
        self.login()
        with patch.object(auth,"yetki_var",return_value=True):
            r=self.client.patch(f"/yonetim/api/kalip/{rid}",json={"kalip_basi_cift":5})
        self.assertEqual(200,r.status_code); self.assertEqual("KALIP_UPDATE",self.audit.call_args.args[1])
        self.audit.reset_mock(); self.upload_image(rid); self.assertEqual("KALIP_GORSEL_UPLOAD",self.audit.call_args.args[1])
        self.audit.reset_mock(); self.upload_image(rid,"PNG","png","image/png"); self.assertEqual("KALIP_GORSEL_CHANGE",self.audit.call_args.args[1])

    def test_20b_audit_hatasi_yarim_basari_uretmez(self):
        self.audit.side_effect=RuntimeError("audit unavailable")
        r=self.post_create(); self.assertEqual(201,r.status_code); self.assertTrue(r.get_json()["ok"]); self.assertEqual(1,self.row(1)["id"])

    def test_21_guvenli_hata(self):
        rid=self.seed(); con=sqlite3.connect(self.db); con.execute("CREATE TRIGGER leak BEFORE UPDATE ON enj_kalip BEGIN SELECT RAISE(FAIL,'SQL /secret/path'); END;"); con.commit(); con.close()
        r=self.upload_image(rid); text=r.get_data(as_text=True); self.assertEqual(500,r.status_code); self.assertNotIn("secret",text); self.assertNotIn("SQL",text)

    def test_22_integrity(self):
        self.post_create(); con=sqlite3.connect(self.db); self.assertEqual("ok",con.execute("PRAGMA integrity_check").fetchone()[0]); con.close()

    def test_23_liste_regresyonu(self):
        self.seed()
        with self.app.test_request_context("/"):
            response=routes.ky_api_kaliplar.__wrapped__()
        self.assertTrue(response.get_json()["ok"]); self.assertEqual(1,response.get_json()["sayi"])

    def test_24_patch_regresyonu(self):
        rid=self.seed(); self.login(); made=[]
        def connect(path,*a,**k): c=ConnectionWrapper(self.db); made.append(c); return c
        with patch.object(routes,"_sqlite3_ky",sqlite_proxy(connect)), patch.object(auth,"yetki_var",return_value=True):
            r=self.client.patch(f"/yonetim/api/kalip/{rid}",json={"kalip_basi_cift":5})
            r404=self.client.patch("/yonetim/api/kalip/999",json={"renk":"X"})
            r400=self.client.patch(f"/yonetim/api/kalip/{rid}",json={"aktif":1,"kalip_durumu":"PASIF"})
        self.assertEqual(200,r.status_code); self.assertEqual(5,self.row(rid)["kalip_basi_cift"]); self.assertEqual((1,1),(made[0].commit_count,made[0].close_count))
        self.assertEqual(404,r404.status_code); self.assertEqual(1,made[1].close_count)
        self.assertEqual(400,r400.status_code); self.assertEqual(1,made[2].close_count)

    def test_25_enjeksiyon_aktif_liste_regresyonu(self):
        self.seed()
        with self.app.test_request_context("/"):
            response=enj_routes.enj_api_kalip_listesi()
        self.assertTrue(response.get_json()["ok"]); self.assertEqual(1,response.get_json()["sayi"])

    def test_27_mime_uzanti_uyumsuzlugu(self):
        r=self.upload_image(self.seed(),"PNG","jpg","image/png"); self.assertEqual(400,r.status_code); self.assertEqual([],list(self.upload.iterdir()))

    def test_28_nan_reddi(self): self.assertEqual(400,self.post_create(cift_agirlik_gr=float("nan")).status_code)
    def test_29_infinity_reddi(self): self.assertEqual(400,self.post_create(cift_agirlik_gr=float("inf")).status_code)
    def test_30_negatif_infinity_reddi(self): self.assertEqual(400,self.post_create(cift_agirlik_gr=float("-inf")).status_code)

    def test_31_create_commit_failure_rollback(self):
        holder=[]
        def connect(path,*a,**k):
            c=ConnectionWrapper(self.db,fail_commit=True); holder.append(c); return c
        self.login()
        with patch.object(routes,"_sqlite3_ky",sqlite_proxy(connect)), patch.object(auth,"yetki_var",return_value=True):
            r=self.client.post("/yonetim/api/kalip/ekle",json={"kalip_kod":"K-X","kalip_tipi":"GOVDE","model_kod":"M","kalip_basi_cift":1})
        self.assertEqual(500,r.status_code); self.assertEqual(1,holder[0].rollback_count)
        con=sqlite3.connect(self.db); self.assertEqual(0,con.execute("SELECT COUNT(*) FROM enj_kalip").fetchone()[0]); con.close()

    def test_32_move_sonrasi_commit_failure_orphan_yok(self):
        rid=self.seed(); holder=[]
        def connect(path,*a,**k):
            c=ConnectionWrapper(self.db,fail_commit=True); holder.append(c); return c
        with patch.object(routes,"_sqlite3_ky",sqlite_proxy(connect)):
            r=self.upload_image(rid)
        self.assertEqual(500,r.status_code); self.assertEqual([],list(self.upload.iterdir())); self.assertIsNone(self.row(rid)["gorsel_dosya"]); self.assertEqual(1,holder[0].rollback_count)

    def test_33_commit_sonrasi_select_yok_db_dosya_tutarli(self):
        rid=self.seed(); holder=[]
        def connect(path,*a,**k):
            c=ConnectionWrapper(self.db,reject_select_after_commit=True); holder.append(c); return c
        with patch.object(routes,"_sqlite3_ky",sqlite_proxy(connect)):
            r=self.upload_image(rid)
        self.assertEqual(200,r.status_code); ad=self.row(rid)["gorsel_dosya"]; self.assertTrue((self.upload/ad).is_file()); self.assertTrue(holder[0].committed)

    def test_34_basarili_degisim_eskiyi_siler(self):
        old="old.jpg"; (self.upload/old).write_bytes(self.image("JPEG").getvalue()); rid=self.seed(gorsel=old)
        self.assertEqual(200,self.upload_image(rid).status_code); self.assertFalse((self.upload/old).exists())

    def test_35_final_dosya_var_ve_decode(self):
        rid=self.seed(); self.assertEqual(200,self.upload_image(rid,"WEBP","webp","image/webp").status_code); p=self.upload/self.row(rid)["gorsel_dosya"]
        with Image.open(p) as img: img.load(); self.assertEqual("WEBP",img.format)

    def test_36_uuid_ve_path_containment(self):
        rid=self.seed(); self.upload_image(rid); ad=self.row(rid)["gorsel_dosya"]
        stem=Path(ad).stem; self.assertEqual(32,len(stem)); int(stem,16); self.assertEqual((self.upload/ad).resolve().parent,self.upload.resolve()); self.assertIsNone(routes._ky_yonetilen_gorsel_yolu("../x.jpg"))

    def test_37_yalniz_aktif_patch(self):
        rid=self.seed(); self.login()
        with patch.object(auth,"yetki_var",return_value=True): r=self.client.patch(f"/yonetim/api/kalip/{rid}",json={"aktif":0})
        self.assertEqual(200,r.status_code); self.assertEqual(["aktif"],r.get_json()["guncellenen_alanlar"]); self.assertEqual((0,"PASIF"),(self.row(rid)["aktif"],self.row(rid)["kalip_durumu"]))

    def test_38_yalniz_durum_patch(self):
        rid=self.seed(); self.login()
        with patch.object(auth,"yetki_var",return_value=True): r=self.client.patch(f"/yonetim/api/kalip/{rid}",json={"kalip_durumu":"PASIF"})
        self.assertEqual(200,r.status_code); self.assertEqual(["kalip_durumu"],r.get_json()["guncellenen_alanlar"]); self.assertEqual(0,self.row(rid)["aktif"])

    def test_39_ilgisiz_patch_legacy_celiskiyi_engellemez(self):
        rid=self.seed(aktif=1,durum="PASIF"); self.login()
        with patch.object(auth,"yetki_var",return_value=True): r=self.client.patch(f"/yonetim/api/kalip/{rid}",json={"renk":"MAVI"})
        self.assertEqual(200,r.status_code); self.assertEqual("MAVI",self.row(rid)["renk"])

    def test_40_create_genel_db_hatasi_guvenli(self):
        con=sqlite3.connect(self.db); con.execute("CREATE TRIGGER fail_create BEFORE INSERT ON enj_kalip BEGIN SELECT RAISE(FAIL,'SQL /secret/create'); END;"); con.commit(); con.close()
        r=self.post_create(); text=r.get_data(as_text=True); self.assertEqual(500,r.status_code); self.assertNotIn("secret",text); self.assertNotIn("SQL",text)

    def test_41_patch_genel_db_hatasi_guvenli(self):
        rid=self.seed(); self.login(); made=[]
        def connect(path,*a,**k): c=ConnectionWrapper(self.db,fail_update=True); made.append(c); return c
        with patch.object(routes,"_sqlite3_ky",sqlite_proxy(connect)), patch.object(auth,"yetki_var",return_value=True):
            r=self.client.patch(f"/yonetim/api/kalip/{rid}",json={"renk":"X"})
        text=r.get_data(as_text=True); self.assertEqual(500,r.status_code); self.assertNotIn("secret",text); self.assertNotIn("SQL",text); self.assertEqual((1,1),(made[0].rollback_count,made[0].close_count))

    def test_42_upload_permission_action_can_update(self):
        calls=[]; rid=self.seed(); self.login()
        def allowed(kod,action): calls.append((kod,action)); return True
        with patch.object(auth,"yetki_var",side_effect=allowed):
            r=self.client.post(f"/yonetim/api/kalip/{rid}/gorsel",data={})
        self.assertEqual(400,r.status_code); self.assertIn(("planlama.enjeksiyon.kalip","can_update"),calls)


if __name__ == "__main__":
    unittest.main(verbosity=2)
