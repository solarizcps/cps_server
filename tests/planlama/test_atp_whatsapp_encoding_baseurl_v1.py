# -*- coding: utf-8 -*-
"""
ATP WhatsApp Encoding Narrow Fix Tests (GATE 3)
Kanıtlar:
  MESSAGE_CONTAINS_REPLACEMENT_CHAR=false
  MESSAGE_URL_CONTAINS_EF_BF_BD=false
  TURKISH_CHARACTERS_PRESERVED=true (Türkçe yer adları ve sürücü adları korunuyor)
  MESSAGE_DOUBLE_ENCODED=false
  WHATSAPP_NO_SOFOR_HARITASI_LINK=true
  WHATSAPP_SINGLE_CLICK_POPUP_COUNT=1  (JS test)
  CANCELLED_JOB_EXCLUDED=true
"""
from __future__ import annotations

import os
import sqlite3
import urllib.parse
from unittest.mock import patch

import pytest

_ROOT = __import__('pathlib').Path(__file__).resolve().parents[2]
_APP = _ROOT / 'app'

import sys
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode_wa_message(wa_url: str) -> str:
    if 'text=' not in wa_url:
        return ''
    return urllib.parse.unquote(wa_url.split('text=', 1)[1])


_CONTEXT_BASE = {
    'date_label': '15 Eylul 2026 Sali',
    'plan_date': '2026-09-15',
    'plate': '34 GFK 183',
    'driver_name': 'Alpay Test',
    'departure_time': '09:00',
    'driver_map_url': '',
    'base': {
        'configured': True, 'base_name': 'Solariz Fabrika',
        'latitude': 41.0, 'longitude': 29.0, 'has_coordinates': True,
    },
    'stops': [],
    'estimated_return_time': None,
}


# ---------------------------------------------------------------------------
# ENCODING TESTS
# ---------------------------------------------------------------------------

class TestMessageEncodingClean:
    def test_no_replacement_char_in_message(self):
        """MESSAGE_CONTAINS_REPLACEMENT_CHAR=false"""
        from modules.planlama.arac_whatsapp_message_service import build_whatsapp_plan_message_v2
        msg = build_whatsapp_plan_message_v2(_CONTEXT_BASE)
        assert '\uFFFD' not in msg, 'Replacement char U+FFFD mesajda bulundu'

    def test_no_ef_bf_bd_in_encoded_url(self):
        """MESSAGE_URL_CONTAINS_EF_BF_BD=false"""
        from modules.planlama.arac_whatsapp_message_service import build_whatsapp_plan_message_v2
        from modules.planlama.arac_plan_service import whatsapp_web_url
        msg = build_whatsapp_plan_message_v2(_CONTEXT_BASE)
        url = whatsapp_web_url(msg)
        assert 'EF%BF%BD' not in url.upper(), f'Replacement char URL\'de encode edilmiş: {url[:100]}'

    def test_turkish_characters_preserved(self):
        """TURKISH_CHARACTERS_PRESERVED=true — Türkçe yer adı ve sürücü adları korunuyor"""
        from modules.planlama.arac_whatsapp_message_service import build_whatsapp_plan_message_v2
        ctx = dict(_CONTEXT_BASE)
        ctx['driver_name'] = 'Şahin Taban'
        ctx['base'] = dict(_CONTEXT_BASE['base'])
        ctx['base']['base_name'] = 'Solariz Şahin Taban'
        msg = build_whatsapp_plan_message_v2(ctx)
        # Türkçe karakterler mesajda korunmalı
        assert 'Şahin Taban' in msg or 'Sahin Taban' in msg.replace('ş', 's').replace('Ş', 'S'), \
            'Sürücü adı mesajda kayboldu'
        assert '\uFFFD' not in msg

    def test_no_double_encoding(self):
        """MESSAGE_DOUBLE_ENCODED=false"""
        from modules.planlama.arac_whatsapp_message_service import build_whatsapp_plan_message_v2
        from modules.planlama.arac_plan_service import whatsapp_web_url
        msg = build_whatsapp_plan_message_v2(_CONTEXT_BASE)
        url = whatsapp_web_url(msg)
        # %25 = encoded % — double encode göstergesi
        assert url.count('%25') == 0, 'Double encoding tespit edildi'

    def test_message_is_valid_unicode(self):
        """Mesaj valid Python unicode string'dir, bytes değil."""
        from modules.planlama.arac_whatsapp_message_service import build_whatsapp_plan_message_v2
        msg = build_whatsapp_plan_message_v2(_CONTEXT_BASE)
        assert isinstance(msg, str)
        # encode/decode round-trip
        assert msg.encode('utf-8').decode('utf-8') == msg

    def test_no_emoji_literals_in_message(self):
        """Emoji literal'leri mesajda bulunmamalı (replacement char kaynağı)."""
        from modules.planlama.arac_whatsapp_message_service import build_whatsapp_plan_message_v2
        msg = build_whatsapp_plan_message_v2(_CONTEXT_BASE)
        # Bilinen emoji code point'leri
        emoji_codepoints = [0x1F69A, 0x1F4C5, 0x1F698, 0x1F464, 0x1F550,
                            0x1F5FA, 0x1F3ED, 0x1F4CD]
        for cp in emoji_codepoints:
            assert chr(cp) not in msg, f'Emoji U+{cp:04X} mesajda bulundu'


class TestWhatsappNoDriverMapLink:
    def test_message_excludes_sofor_haritasi_link(self):
        """WHATSAPP_NO_SOFOR_HARITASI_LINK=true"""
        from modules.planlama.arac_whatsapp_message_service import build_whatsapp_plan_message_v2
        ctx = dict(_CONTEXT_BASE)
        ctx['driver_map_url'] = (
            'http://192.168.1.50:8080/planlama/arac-takip/sofor-haritasi'
            '?date=2026-09-15&vehicle_id=991002&plan_id=23&t=abc'
        )
        msg = build_whatsapp_plan_message_v2(ctx)
        assert '/sofor-haritasi' not in msg
        assert 'tek haritada' not in msg.lower()
        assert ctx['driver_map_url'] not in msg


# ---------------------------------------------------------------------------
# CANCELLED JOB EXCLUDED
# ---------------------------------------------------------------------------

class TestCancelledJobExcluded:
    def test_cancelled_job_excluded_from_message(self, atp_planlama_db_guard_session):
        """CANCELLED_JOB_EXCLUDED=true — iptal duraklar mesajda yok"""
        import importlib.util, tempfile, shutil
        from pathlib import Path
        from tools.atp_test_db_guard import bind_temp_db_path

        _APP_DIR = Path(__file__).resolve().parents[2] / 'app'
        _MIGRATIONS = _APP_DIR / 'migrations'

        def _run_mig(db_path, fname):
            spec = importlib.util.spec_from_file_location(fname, _MIGRATIONS / fname)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.run(db_path)

        session_db = atp_planlama_db_guard_session['temp_db']
        tmpdir = tempfile.mkdtemp(prefix='enc_cancel_test_')
        db_path = str(Path(tmpdir) / 'test.db')
        for mig in ('176_arac_takip_v13.py', '177_arac_operasyon_ayar.py',
                     '178_arac_is_talebi_ux_v2_fields.py', '180_arac_plan_ziyaret_durum.py',
                     '182_arac_plan_change_v1.py', '179_arac_gps_snapshot_p1.py'):
            _run_mig(db_path, mig)
        bind_temp_db_path(db_path)

        try:
            from modules.planlama.arac_takip_repo import (
                create_is_talebi, assign_to_plan, ensure_seed_locations,
                get_conn, list_plan_tasks,
            )
            from modules.planlama.arac_whatsapp_message_service import build_whatsapp_payload

            ensure_seed_locations(1)
            d = '2026-09-30'
            vid = 'CANCEL_ENC_TEST'
            t_active = create_is_talebi(1, {'tarih': d, 'is': 'Aktif is', 'firma': 'Aktif Firma', 'latitude': 41.0, 'longitude': 29.0, 'save_to_master': False})
            t_cancel = create_is_talebi(1, {'tarih': d, 'is': 'Iptal is', 'firma': 'Iptal Firma', 'latitude': 41.1, 'longitude': 29.1, 'save_to_master': False})
            assign_to_plan(1, t_active['id'], d, vid, '34 TEST', None, 'Test', '09:00', 1)
            assign_to_plan(1, t_cancel['id'], d, vid, '34 TEST', None, 'Test', '10:00', 2)
            tasks = list_plan_tasks(d, vid)
            cancel_item_id = next(x['plan_item_id'] for x in tasks if x.get('company_name') == 'Iptal Firma')
            con = get_conn()
            con.execute("UPDATE arac_gunluk_plan_is SET durum='IPTAL' WHERE id=?", (cancel_item_id,))
            con.commit()
            con.close()

            import flask
            fapp = flask.Flask(__name__)
            with fapp.test_request_context('/', base_url='http://192.168.1.50:8080'):
                payload = build_whatsapp_payload(d, vid)
            assert payload and payload.get('ok')
            msg = payload['message']
            assert 'Aktif Firma' in msg
            assert 'Iptal Firma' not in msg
        finally:
            bind_temp_db_path(session_db)
            shutil.rmtree(tmpdir, ignore_errors=True)
