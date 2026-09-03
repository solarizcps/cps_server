#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gate 3 verified_uncommitted record generator."""
from __future__ import annotations

import hashlib
import subprocess
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "changes" / "records"
FRAGMENTS = ROOT / "changes" / "fragments"
TODAY = date.today().isoformat()


def fingerprint_for(paths: list[str]) -> str:
    parts: list[str] = []
    for rel in sorted(paths):
        p = ROOT / rel.replace("/", "\\") if "\\" not in rel else ROOT / rel
        if p.is_file():
            st = p.stat()
            parts.append(f"F:{rel}:{st.st_size}:{int(st.st_mtime)}")
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file():
                    st = f.stat()
                    parts.append(f"F:{f.relative_to(ROOT).as_posix()}:{st.st_size}:{int(st.st_mtime)}")
    if not parts:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "--"] + paths,
            cwd=ROOT, capture_output=True, text=True,
        )
        parts = [proc.stdout.strip() or "empty"]
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def write_uncommitted(rec: dict) -> None:
    fp = rec.get("fingerprint") or fingerprint_for(rec.get("watch_paths", []))
    toml = f'''schema_version = 1
module = "{rec["module"]}"
version = "{rec["version"]}"
phase_code = "{rec["phase_code"]}"
title = "{rec["title"]}"
status = "{rec["status"]}"
date = "{TODAY}"
summary = "{rec["summary"]}"
source_type = "verified_uncommitted"
commit_sha = ""
test_result = "{rec["test_result"]}"
db_write = false
server_restart = false
push_status = "WORKING"
deployment_status = "WORKING"
worktree_fingerprint = "{fp}"
verification_date = "{TODAY}"
verification_evidence = "{rec["evidence"]}"
current_work = "{rec.get("current_work", "")}"
changes = [
{"".join(f'  "{c}",\n' for c in rec["changes"])}
]
changed_files = [
{"".join(f'  "{f}",\n' for f in rec.get("changed_files", []))}
]
locked_rules = [
]
tests = [
{"".join(f'  "{t}",\n' for t in rec.get("tests", []))}
]
known_issues = [
{"".join(f'  "{k}",\n' for k in rec.get("known_issues", []))}
]
next_steps = [
{"".join(f'  "{n}",\n' for n in rec.get("next_steps", []))}
]
'''
    mod_dir = RECORDS / rec["module"]
    mod_dir.mkdir(parents=True, exist_ok=True)
    (mod_dir / f"{rec['phase_code']}.toml").write_text(toml, encoding="utf-8")
    (FRAGMENTS / f"{rec['module']}.{rec['phase_code']}.release").write_text(rec["fragment"] + "\n", encoding="utf-8")
    print("WROTE", rec["phase_code"], fp)


UNCOMMITTED = [
    dict(module="nexgen.etiket", version="v4.3.0", phase_code="UNCOMMITTED_ETIKET_V430_CORE",
         title="Etiket Basım çekirdek servis ve route (commit bekliyor).",
         summary="Etiket basım servis, route ve template dosyaları working tree'de doğrulandı; commit bekliyor.",
         status="TEST", test_result="Manuel smoke; otomatik pytest yok",
         evidence="Untracked etiket_basim routes/service/templates; browser smoke",
         current_work="Etiket basım çekirdek akış geliştirme",
         changed_files=["app/modules/nexgen/etiket_basim_routes.py", "app/modules/nexgen/etiket_basim_service.py",
                        "app/templates/nexgen/etiket_basim.html", "app/templates/nexgen/etiket_basim_print.html"],
         changes=["Etiket basım route eklendi.", "Servis katmanı.", "Print template."],
         known_issues=["QR offline qrcode kütüphanesi eksik — offline mod sınırlı"],
         next_steps=["v4.3.1 layout parity", "Commit ve fragment eşleştirme"],
         watch_paths=["app/modules/nexgen/etiket_basim_routes.py", "app/modules/nexgen/etiket_basim_service.py"],
         fragment="Etiket Basım v4.3.0 çekirdek (commit bekliyor)."),
    dict(module="nexgen.etiket", version="v4.3.1", phase_code="UNCOMMITTED_ETIKET_V431_LAYOUT",
         title="Etiket layout parity (commit bekliyor).",
         summary="Etiket basım layout düzeni working tree'de; commit bekliyor.",
         status="TEST", test_result="Görsel smoke",
         evidence="Template layout değişiklikleri doğrulandı",
         current_work="Layout parity ince ayarı",
         changed_files=["app/templates/nexgen/etiket_basim.html"],
         changes=["Layout parity düzeltmeleri."],
         known_issues=["QR offline qrcode eksikliği devam ediyor"],
         next_steps=["v4.3.2 barcode entegrasyonu"],
         watch_paths=["app/templates/nexgen/etiket_basim.html"],
         fragment="Etiket Basım v4.3.1 layout (commit bekliyor)."),
    dict(module="nexgen.etiket", version="v4.3.2", phase_code="UNCOMMITTED_ETIKET_V432_BARCODE",
         title="Etiket barcode entegrasyonu (commit bekliyor).",
         summary="Barcode render entegrasyonu geliştirme aşamasında.",
         status="TEST", test_result="Kısmi smoke",
         evidence="Barcode demo entegrasyonu incelendi",
         current_work="Barcode render bağlantısı",
         changes=["Barcode render hook."],
         known_issues=["QR offline qrcode eksik — qrcode offline modu çalışmıyor"],
         next_steps=["v4.3.3 print parity"],
         watch_paths=["app/modules/nexgen/etiket_basim_service.py"],
         fragment="Etiket Basım v4.3.2 barcode (commit bekliyor)."),
    dict(module="nexgen.etiket", version="v4.3.3", phase_code="UNCOMMITTED_ETIKET_V433_PRINT",
         title="Etiket print parity (commit bekliyor).",
         summary="Print template parity geliştirme aşamasında.",
         status="TEST", test_result="Print preview smoke",
         evidence="Print template doğrulandı",
         current_work="Print CSS parity",
         changed_files=["app/templates/nexgen/etiket_basim_print.html"],
         changes=["Print template parity."],
         known_issues=["QR offline qrcode eksikliği"],
         next_steps=["v4.3.4 tablet bridge"],
         watch_paths=["app/templates/nexgen/etiket_basim_print.html"],
         fragment="Etiket Basım v4.3.3 print (commit bekliyor)."),
    dict(module="nexgen.etiket", version="v4.3.4", phase_code="UNCOMMITTED_ETIKET_V434_TABLET",
         title="Etiket tablet bridge (commit bekliyor).",
         summary="Tablet print bridge entegrasyonu planlama aşamasında.",
         status="ONAYLANDI", test_result="Tasarım onaylandı; commit bekliyor",
         evidence="Tablet bridge gereksinimleri doğrulandı",
         current_work="Tablet bridge API taslağı",
         changes=["Tablet bridge API taslağı."],
         known_issues=["QR offline qrcode eksikliği açık"],
         next_steps=["v4.3.5 regression lock"],
         watch_paths=["app/modules/nexgen/etiket_basim_service.py"],
         fragment="Etiket Basım v4.3.4 tablet bridge (commit bekliyor)."),
    dict(module="nexgen.etiket", version="v4.3.5", phase_code="UNCOMMITTED_ETIKET_V435_REGRESSION",
         title="Etiket regression hazırlığı (commit bekliyor).",
         summary="Etiket basım regression test paketi hazırlanıyor.",
         status="TEST", test_result="Regression paketi yazılıyor",
         evidence="Test planı doğrulandı",
         current_work="Regression test paketi",
         changes=["Regression test planı."],
         known_issues=["QR offline/qrcode eksikliği — bilinen açık sorun", "Commit bekliyor"],
         next_steps=["Commit sonrası KILITLI aday"],
         watch_paths=["app/modules/nexgen/etiket_basim_service.py"],
         fragment="Etiket Basım v4.3.5 regression hazırlığı (commit bekliyor)."),
    dict(module="planlama.aps", version="v1.1.0", phase_code="UNCOMMITTED_APS_P58_Z2_TIMELINE",
         title="APS P5.8 anchor zoom ve Z2 timeline genişletmesi (commit bekliyor).",
         summary="Working tree'de APS P5.8 anchor zoom ve Z2G timeline genişletmesi devam ediyor.",
         status="TEST", test_result="Browser harness kısmi",
         evidence="27 planlama dosyası dirty; capacity resolver ve dhtmlx contract untracked",
         current_work="P5.8 anchor zoom + Z2G timeline genişletmesi",
         changed_files=["app/modules/planlama/aps_enj_timeline_service.py", "app/modules/planlama/aps_pilot_data_service.py"],
         changes=["Anchor zoom genişletmesi.", "Z2 timeline contract.", "Capacity resolver taslak."],
         known_issues=["Commit bekliyor — canonical geçmişe tamamlanmış olarak eklenmedi"],
         next_steps=["Regression tamamla", "Commit + fragment"],
         watch_paths=["app/modules/planlama/aps_enj_timeline_service.py", "app/modules/planlama/aps_pilot_data_service.py",
                      "app/modules/planlama/aps_calendar_resolver.py"],
         fragment="APS P5.8/Z2 devam durumu (commit bekliyor)."),
    dict(module="cari360", version="v1.1.0", phase_code="UNCOMMITTED_C360_A1_BUNDLE",
         title="C360-A1 worktree ticari veri bundle (commit bekliyor).",
         summary="WT-C360A1 worktree'de ticari özet, timeline ve data scope değişiklikleri doğrulandı.",
         status="ONAYLANDI", test_result="A1/A3 test scriptleri mevcut",
         evidence="WT-C360A1: cari360 servisleri + data_scope + excel import",
         current_work="C360-A1 canonical veri hizalama",
         changed_files=["app/modules/nexgen/cari360_ticari_ozet_service.py", "app/modules/nexgen/cari360_timeline_service.py"],
         changes=["Ticari özet servisi.", "Timeline servisi.", "Data scope modülü."],
         known_issues=["Ana repo temiz; bundle ayrı worktree'de commit bekliyor"],
         next_steps=["Worktree commit", "Canonical kayda dönüştürme"],
         watch_paths=["app/modules/nexgen/cari360_ticari_ozet_service.py"],
         fragment="C360-A1 bundle (commit bekliyor)."),
]


if __name__ == "__main__":
    for rec in UNCOMMITTED:
        write_uncommitted(rec)
    print("TOTAL", len(UNCOMMITTED))
