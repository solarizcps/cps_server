# -*- coding: utf-8 -*-
"""FAZ-ENJ-SAATLIK-ATOMIK-YAZMA-FIX-1 dar transaction testleri."""
import os
import sys
import types
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ROOT, "app")
if APP not in sys.path:
    sys.path.insert(0, APP)

try:
    from flask import Flask
    HAS_FLASK = True
except ModuleNotFoundError:
    HAS_FLASK = False

    class _Response:
        status_code = 200
        def __init__(self, data): self._data = data
        def get_json(self): return self._data

    class _Request:
        path = "/enjeksiyon/api/saatlik/101"
        body = {}
        def get_json(self, silent=True): return self.body

    class _Blueprint:
        def __init__(self, *args, **kwargs): pass
        def route(self, *args, **kwargs):
            return lambda fn: fn

    flask_stub = types.ModuleType("flask")
    flask_stub.Blueprint = _Blueprint
    flask_stub.render_template = lambda *a, **k: None
    flask_stub.redirect = lambda *a, **k: None
    flask_stub.url_for = lambda *a, **k: ""
    flask_stub.request = _Request()
    flask_stub.session = {}
    flask_stub.abort = lambda code: (_ for _ in ()).throw(RuntimeError(code))
    flask_stub.jsonify = lambda data: _Response(data)
    sys.modules["flask"] = flask_stub
    werkzeug_stub = types.ModuleType("werkzeug")
    werkzeug_utils_stub = types.ModuleType("werkzeug.utils")
    werkzeug_utils_stub.secure_filename = lambda name: name
    sys.modules["werkzeug"] = werkzeug_stub
    sys.modules["werkzeug.utils"] = werkzeug_utils_stub

from modules.enjeksiyon import routes


class FakeCursor:
    def __init__(self, con, exists=True):
        self.con = con
        self.exists = exists
        self._one = None

    def execute(self, sql, params=()):
        compact = " ".join(str(sql).split())
        self.con.sql.append((compact, tuple(params)))
        if compact.startswith("SELECT id, rapor_id FROM enj_saatlik_kayit"):
            self._one = (params[0], 77) if self.exists else None
        elif compact.startswith("SELECT setup_id_a, setup_id_b FROM enj_saatlik_kayit"):
            self._one = (11, 12)
        elif compact.startswith("SELECT pisme_suresi_sn FROM enj_ab_setup"):
            self._one = (60,)
        elif compact.startswith("UPDATE enj_saatlik_kayit SET"):
            self.con.pending_update = True
            self._one = None
        else:
            self._one = None
        return self

    def fetchone(self):
        return self._one


class FakeConnection:
    def __init__(self, exists=True):
        self.sql = []
        self.cursor_obj = FakeCursor(self, exists=exists)
        self.pending_update = False
        self.persisted_update = False
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commit_count += 1
        self.persisted_update = self.pending_update
        self.pending_update = False

    def rollback(self):
        self.rollback_count += 1
        self.pending_update = False

    def close(self):
        self.close_count += 1


class SaatlikAtomicPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if HAS_FLASK:
            cls.app = Flask(__name__)
            cls.app.config.update(TESTING=True, SECRET_KEY="atomic-test")

    def invoke(self, body, con=None, freeze=None, calculate=None, guard=None, sid=101):
        con = con or FakeConnection()
        calls = []

        def freeze_default(cur, saatlik_id):
            calls.append(("freeze", saatlik_id))
            return {"ok": True}

        def calculate_default(cur, saatlik_id):
            calls.append(("calculate", saatlik_id))
            return {"uretilen_a": 20, "uretilen_b": 0}

        freeze = freeze or freeze_default
        calculate = calculate or calculate_default
        guard = guard or (lambda cur, rapor_id, slot: None)
        context = self.app.test_request_context(json=body, method="PATCH") if HAS_FLASK else None
        if not HAS_FLASK:
            routes.request.body = body
        if context:
            context.push()
        try:
            with patch.object(routes._sqlite3, "connect", return_value=con), \
                 patch.object(routes._setup_db, "guard_tur_giris", side_effect=guard), \
                 patch.object(routes._setup_db, "freeze_saatlik_snapshot", side_effect=freeze), \
                 patch.object(routes, "_ab_hesapla_saatlik", side_effect=calculate):
                result = routes.enj_api_saatlik_patch(sid)
        finally:
            if context:
                context.pop()
        if isinstance(result, tuple):
            response, status = result
        else:
            response, status = result, result.status_code
        return response.get_json(), status, con, calls

    def test_01_success_contract_preserved(self):
        data, status, _, _ = self.invoke({"cevrim_a": 10})
        self.assertEqual(200, status)
        self.assertEqual({"ok": True, "guncellenen": ["cevrim_a"]}, data)

    def test_02_success_commits_once(self):
        _, _, con, _ = self.invoke({"cevrim_a": 10})
        self.assertEqual(1, con.commit_count)
        self.assertEqual(0, con.rollback_count)
        self.assertTrue(con.persisted_update)

    def test_03_snapshot_runs_before_calculation(self):
        order = []
        def freeze(cur, sid): order.append("freeze")
        def calculate(cur, sid): order.append("calculate")
        self.invoke({"cevrim_a": 10}, freeze=freeze, calculate=calculate)
        self.assertEqual(["freeze", "calculate"], order)

    def test_04_snapshot_exception_returns_500_not_ok_true(self):
        def freeze(cur, sid): raise RuntimeError("snapshot boom")
        data, status, _, _ = self.invoke({"cevrim_a": 10}, freeze=freeze)
        self.assertEqual(500, status)
        self.assertFalse(data["ok"])
        self.assertEqual("Saatlik üretim hesabı tamamlanamadı. Kayıt geri alındı.", data["hata"])
        self.assertNotIn("snapshot boom", data["hata"])

    def test_05_snapshot_exception_rolls_back_cycle_update(self):
        def freeze(cur, sid): raise RuntimeError("snapshot boom")
        _, _, con, _ = self.invoke({"cevrim_a": 10}, freeze=freeze)
        self.assertEqual(1, con.rollback_count)
        self.assertEqual(0, con.commit_count)
        self.assertFalse(con.persisted_update)

    def test_06_calculation_exception_returns_500_not_ok_true(self):
        def calculate(cur, sid): raise ArithmeticError("calculate boom")
        data, status, _, _ = self.invoke({"cevrim_a": 10}, calculate=calculate)
        self.assertEqual(500, status)
        self.assertFalse(data["ok"])
        self.assertEqual("Saatlik üretim hesabı tamamlanamadı. Kayıt geri alındı.", data["hata"])
        self.assertNotIn("calculate boom", data["hata"])

    def test_07_calculation_exception_rolls_back_cycle_and_snapshot_transaction(self):
        def calculate(cur, sid): raise ArithmeticError("calculate boom")
        _, _, con, _ = self.invoke({"cevrim_a": 10}, calculate=calculate)
        self.assertEqual(1, con.rollback_count)
        self.assertEqual(0, con.commit_count)
        self.assertFalse(con.persisted_update)

    def test_08_missing_record_returns_404_without_write(self):
        con = FakeConnection(exists=False)
        data, status, con, _ = self.invoke({"cevrim_a": 10}, con=con)
        self.assertEqual(404, status)
        self.assertFalse(data["ok"])
        self.assertFalse(con.pending_update)
        self.assertEqual(0, con.commit_count)

    def test_09_empty_whitelist_returns_400_without_connection(self):
        data, status, con, _ = self.invoke({"not_allowed": 1})
        self.assertEqual(400, status)
        self.assertFalse(data["ok"])
        self.assertEqual([], con.sql)

    def test_10_setup_gate_returns_422_before_update(self):
        guard = lambda cur, rid, slot: {"mesaj": "SETUP_EKSIK", "mesaj_tr": "Setup eksik"}
        data, status, con, _ = self.invoke({"cevrim_a": 10}, guard=guard)
        self.assertEqual(422, status)
        self.assertEqual("SETUP_EKSIK", data["tip"])
        self.assertFalse(con.pending_update)
        self.assertEqual(0, con.commit_count)

    def test_11_max_cycle_early_return_happens_before_update(self):
        data, status, con, _ = self.invoke({"cevrim_a": 100})
        self.assertEqual(400, status)
        self.assertEqual("MAX_TUR_ASILDI", data["tip"])
        self.assertFalse(con.pending_update)
        self.assertEqual(0, con.commit_count)

    def test_12_connection_closes_on_calculation_exception(self):
        def calculate(cur, sid): raise RuntimeError("close path")
        _, _, con, _ = self.invoke({"cevrim_a": 10}, calculate=calculate)
        self.assertEqual(1, con.close_count)


if __name__ == "__main__":
    unittest.main(verbosity=2)
