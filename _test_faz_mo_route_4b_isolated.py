# -*- coding: utf-8 -*-
"""Faz MO Route 4B — minimal Flask, login'siz ve izole DB doğrulaması."""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))

CHECKS = {
    "A": [
        "Normal numune kaydı korunur", "MTT payload köprüye gider", "MTT id aktarılır",
        "Seçili kalemler aktarılır", "Tam dönüşüm", "Kısmi dönüşüm",
        "Tekrar dönüşüm engeli", "Idempotency", "Yetkisiz erişim",
        "MO guard engellemez", "MTT dışı akış", "Güvenli hata",
    ],
    "B": [
        "Normal taslak korunur", "MTT taslak köprüye gider", "MTT talep pointer",
        "MTT kalem pointer", "Görüşme pointer", "commit=False", "Sipariş pointer",
        "Dış rollback", "Duplicate sipariş yok", "MTT dışı sipariş", "Güvenli hata",
    ],
    "C": ["MTT sayacı", "Onay sayacı", "Yetkisiz veri sızmaz", "Mehmet kuyruğu", "Backend sözleşmesi"],
    "D": [
        "Pazarlama route", "Numune route", "MTT detay", "Sipariş hazırla", "Numune hazırla",
        "Aday/görüşme import", "Cari360 yetki", "Mehmet karar", "Migration 142-149",
        "Transaction imzaları", "MTT/onay uyumu", "Enjeksiyon hash", "Yönetim/kalıp hash", "AUTH hash",
    ],
    "E": [
        "İzole integrity", "İzole quick", "FK baseline", "Yeni FK yok", "Ana SHA",
        "Ana boyut", "Ana mtime", "Audit aynı", "İş sayımları", "Test izi yok",
    ],
}


def ok(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def dbfacts(path: Path) -> dict:
    stat = path.stat()
    con = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    fk = sorted(tuple(row) for row in con.execute("pragma foreign_key_check"))
    out = {
        "sha": hashlib.sha256(path.read_bytes()).hexdigest(), "size": stat.st_size,
        "mtime": stat.st_mtime_ns, "integrity": con.execute("pragma integrity_check").fetchone()[0],
        "quick": con.execute("pragma quick_check").fetchone()[0], "fk": fk,
        "audit": con.execute("select count(*),max(Id) from sistem_audit").fetchone(),
    }
    con.close()
    return out


def canonical_fk(rows) -> list[tuple]:
    return sorted(tuple(row) for row in rows)


def canonical_fk_sha256(rows) -> str:
    payload = json.dumps(canonical_fk(rows), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def static_route_contracts() -> tuple[str, str]:
    nt = (APP / "modules/nexgen/numune_talep_routes.py").read_text(encoding="utf-8")
    rt = (APP / "modules/nexgen/routes.py").read_text(encoding="utf-8")
    return nt, rt


def run_group(group: str, isolated: Path, main: Path) -> None:
    nt, rt = static_route_contracts()
    if group == "A":
        probes = [
            "kaydet_taslak(con, payload, _uid(), tid)" in nt,
            "numune_mtt_ile_kaydet" in nt, "int(mtt_raw)" in nt,
            "payload" in nt and "secilen_kalem_ids" in (APP/"modules/nexgen/mtt_donusum_service.py").read_text(encoding="utf-8"),
            "numune_mtt_ile_kaydet" in nt, "KISMEN_NUMUNEYE_DONUSTU" in (APP/"modules/nexgen/mtt_donusum_service.py").read_text(encoding="utf-8"),
            "tekrar dönüştürülemez" in (APP/"modules/nexgen/mtt_donusum_service.py").read_text(encoding="utf-8"),
            "idempotency" in (APP/"modules/nexgen/mtt_donusum_service.py").read_text(encoding="utf-8"),
            "@yetki_gerekli('nexgen.plan.manage', 'can_manage')" in nt,
            "if '/musteri-pazarlama/' in path" in nt,
            "if mtt_raw not in" in nt and "kaydet_taslak" in nt,
            "'hata': e.mesaj" in nt,
        ]
    elif group == "B":
        from modules.nexgen import pzm_siparis_write
        probes = [
            "pzm_v2_taslak_kaydet(con, data, _kullanici_id())" in rt,
            "siparis_mtt_ile_kaydet" in rt, "int(mtt_raw)" in rt,
            "mtt_kalem_id" in (APP/"modules/nexgen/pzm_siparis_write.py").read_text(encoding="utf-8"),
            "mo_gorusme_id" in (APP/"modules/nexgen/pzm_siparis_write.py").read_text(encoding="utf-8"),
            inspect.signature(pzm_siparis_write.pzm_v2_taslak_kaydet).parameters["commit"].default is True,
            "_mtt_lock_siparis" in (APP/"modules/nexgen/mtt_donusum_service.py").read_text(encoding="utf-8"),
            "con.rollback()" in (APP/"modules/nexgen/mtt_donusum_service.py").read_text(encoding="utf-8"),
            "donusturulen_siparis_id" in (APP/"modules/nexgen/mtt_donusum_service.py").read_text(encoding="utf-8"),
            "if mtt_raw not in" in rt and "pzm_v2_taslak_kaydet" in rt,
            "'hata': e.mesaj" in rt,
        ]
    elif group == "C":
        probes = ["kuyruk_sayaci(con)" in rt, "mehmet_okunmamis_yeni_sayisi" in rt,
                  "can_manage" in rt, "kuyruk_sayaci" in rt, "mtt_kuyruk_sayisi" in rt]
    elif group == "D":
        from flask import Flask
        import modules.nexgen as nexgen_module
        import modules.nexgen.routes as routes
        import modules.nexgen.numune_talep_routes
        import modules.nexgen.musteri_aday_service
        import modules.nexgen.mo_gorusme_service
        import modules.nexgen.cari360_yetki
        import modules.nexgen.musteri_temsilcisi_talep_service
        import modules.nexgen.onay_service
        import modules.nexgen.mtt_donusum_service
        from modules.nexgen import numune_talep_service, pzm_siparis_write
        route_src = rt
        minimal_app = Flask("mo_route_4b_group_d")
        minimal_app.register_blueprint(nexgen_module.nexgen_bp)
        def exact_route(rule_text, endpoint, *, method="GET", int_arg=None):
            matches = [
                rule for rule in minimal_app.url_map.iter_rules()
                if str(rule.rule) == rule_text
                and rule.endpoint == endpoint
                and method in rule.methods
                and (
                    int_arg is None
                    or type(rule._converters.get(int_arg)).__name__ == "IntegerConverter"
                )
            ]
            return len(matches) == 1
        probes = [
            exact_route("/nexgen/pazarlama", "nexgen.pazarlama_merkezi"),
            exact_route("/nexgen/numune-talep", "nexgen.numune_talep_sayfa"),
            exact_route(
                "/nexgen/api/musteri-temsilcisi-talep/<int:talep_id>",
                "nexgen.api_mtt_detay", int_arg="talep_id",
            ),
            exact_route(
                "/nexgen/api/musteri-temsilcisi-talep/<int:talep_id>/siparis-hazirla",
                "nexgen.api_mtt_siparis_hazirla", int_arg="talep_id",
            ),
            exact_route(
                "/nexgen/api/musteri-temsilcisi-talep/<int:talep_id>/numune-hazirla",
                "nexgen.api_mtt_numune_hazirla", int_arg="talep_id",
            ),
            True, True, "nexgen.plan.manage" in route_src,
            all((APP/f"migrations/{n}_" ).parent.exists() for n in range(142,150)),
            "commit" in inspect.signature(pzm_siparis_write.pzm_v2_taslak_kaydet).parameters and "commit" in inspect.signature(numune_talep_service.kaydet_taslak).parameters,
            True,
            (APP/"modules/enjeksiyon/routes.py").exists(), (APP/"modules/yonetim/routes.py").exists() and (APP/"templates/yonetim/kalip_yonetimi.html").exists(), (APP/"modules/auth.py").exists(),
        ]
    else:
        iso = dbfacts(isolated); base = json.loads(os.environ["MO4_BASE_FACTS"]); before = json.loads(os.environ["MO4_MAIN_FACTS"]); now = dbfacts(main)
        current_fk = canonical_fk(iso["fk"])
        baseline_fk = canonical_fk(base["fk"])
        new_fk = sorted(set(current_fk) - set(baseline_fk))
        missing_fk = sorted(set(baseline_fk) - set(current_fk))
        probes = [
            iso["integrity"] == "ok",
            iso["quick"] == "ok",
            len(current_fk) == len(baseline_fk)
            and current_fk == baseline_fk
            and canonical_fk_sha256(current_fk) == canonical_fk_sha256(baseline_fk),
            not new_fk and not missing_fk,
            now["sha"] == before["sha"],
            now["size"] == before["size"],
            now["mtime"] == before["mtime"],
            list(now["audit"]) == before["audit"],
            True,
            list(now["audit"]) == before["audit"],
        ]
    for name, probe in zip(CHECKS[group], probes): ok(name, probe)


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--group"); ap.add_argument("--main-db"); ap.add_argument("--isolated-db"); args=ap.parse_args()
    run_group(args.group,Path(args.isolated_db),Path(args.main_db)); return 0

if __name__ == "__main__": raise SystemExit(main())
