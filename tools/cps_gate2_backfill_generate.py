#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gate 2 backfill generator — semantic release history records from Git."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "changes" / "records"
FRAGMENTS = ROOT / "changes" / "fragments"


def git_sha(short: str) -> str:
    return subprocess.check_output(["git", "rev-parse", short], text=True, cwd=ROOT).strip()


def git_date(short: str) -> str:
    return subprocess.check_output(["git", "log", "-1", "--format=%ci", short], text=True, cwd=ROOT).strip()[:10]


def git_files(short: str) -> list[str]:
    sha = git_sha(short)
    out = subprocess.check_output(["git", "show", sha, "--name-only", "--format="], text=True, cwd=ROOT)
    files: list[str] = []
    for line in out.splitlines():
        line = line.strip().strip('"')
        if not line or line.startswith("_"):
            continue
        line = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), line)
        files.append(line)
    return files


def write_commit_record(rec: dict) -> None:
    primary = rec["primary"]
    primary_sha = git_sha(primary)
    changed = git_files(primary)
    related = rec.get("related", [])
    related_block = ""
    if related:
        related_block = "related_commits = [\n" + "".join(f'  "{git_sha(s)}",\n' for s in related) + "]\n"
    root = f'root_cause = "{rec.get("root_cause", "")}"\n' if rec.get("root_cause") else ""
    toml = f'''schema_version = 1
module = "{rec["module"]}"
version = "{rec["version"]}"
phase_code = "{rec["phase_code"]}"
title = "{rec["title"]}"
status = "{rec["status"]}"
date = "{git_date(primary)}"
summary = "{rec["summary"]}"
source_type = "commit"
commit_sha = "{primary_sha}"
test_result = "{rec["test_result"]}"
db_write = false
server_restart = false
push_status = "DEPLOYMENT_UNKNOWN"
deployment_status = "DEPLOYMENT_UNKNOWN"
{root}evidence_summary = "{rec.get("evidence", "")}"
changes = [
{"".join(f'  "{c}",\n' for c in rec["changes"])}
]
changed_files = [
{"".join(f'  "{f}",\n' for f in changed)}
]
locked_rules = [
{"".join(f'  "{r}",\n' for r in rec.get("locked_rules", []))}
]
tests = [
{"".join(f'  "{t}",\n' for t in rec.get("tests", []))}
]
known_issues = [
]
next_steps = [
{"".join(f'  "{n}",\n' for n in rec.get("next_steps", []))}
]
{related_block}'''
    mod_dir = RECORDS / rec["module"]
    mod_dir.mkdir(parents=True, exist_ok=True)
    path = mod_dir / f"{rec['phase_code']}.toml"
    path.write_text(toml, encoding="utf-8")
    frag = FRAGMENTS / f"{rec['module']}.{rec['phase_code']}.release"
    frag.write_text(rec["fragment"] + "\n", encoding="utf-8")
    print("WROTE", rec["phase_code"])


GATE2_RECORDS = [
    # ── planlama.atp Aug 21-25 (5 groups, 16 commits) ──
    dict(module="planlama.atp", version="v0.3.0", phase_code="BACKFILL_ATP_VEHICLE_OPS_V13_V14",
         primary="d835866", related=["8ebc1e6"],
         title="Araç operasyonları v1.3 ve plan harita v1.4a kilitlendi.",
         summary="Araç operasyonları faz v1.3 ve plan harita v1.4a commitlendi.",
         status="ONAYLANDI", test_result="Commit doğrulandı; otomatik pytest yok",
         changes=["Araç operasyonları v1.3 eklendi.", "Plan harita v1.4a bağlandı."],
         fragment="ATP araç operasyonları v1.3-v1.4a kilitlendi."),
    dict(module="planlama.atp", version="v0.4.0", phase_code="BACKFILL_ATP_GPS_FOUNDATION_P3",
         primary="c3e61e0", related=["a65a959"],
         title="ATP GPS temel v1-v2 ve günlük plan okuma modeli kilitlendi.",
         summary="GPS geçmiş atomik yazım, rota sapma motoru ve günlük plan read model pytest ile doğrulandı.",
         status="KILITLI", test_result="GPS foundation pytest PASS",
         changes=["GPS geçmiş atomik yazım.", "Rota sapma motoru.", "Günlük plan read model."],
         tests=["GPS foundation pytest"], fragment="ATP GPS temel P3 kilitlendi."),
    dict(module="planlama.atp", version="v0.5.0", phase_code="BACKFILL_ATP_LIVE_GPS_WORKER_V1",
         primary="3b55262", related=["5cb7f42", "63445a8", "f55af48", "cf6940b"],
         title="Canlı GPS ziyaret ve worker görev sertleştirmesi kilitlendi.",
         summary="Canlı GPS ziyaret takibi, Mehmet V2 ops UI ve GPS worker görev yapılandırması commitlendi.",
         status="KILITLI", test_result="Live GPS worker pytest 4 dosya PASS",
         changes=["Canlı GPS ziyaret takibi.", "GPS worker scheduled task.", "Canonical worker config."],
         tests=["Live GPS worker pytest"], fragment="ATP canlı GPS worker kilitlendi."),
    dict(module="planlama.atp", version="v0.6.0", phase_code="BACKFILL_ATP_MANUAL_REORDER_UI_V1",
         primary="861d39c", related=["d27324d"],
         title="Araç rota sıralama ve plan modal düzeni kilitlendi.",
         summary="Manuel rota sıralama güvenliği ve plan modal layout restore commitlendi.",
         status="ONAYLANDI", test_result="Commit doğrulandı; otomatik pytest yok",
         changes=["Rota sıralama güvenliği.", "Plan modal layout restore."],
         fragment="ATP manuel rota sıralama UI kilitlendi."),
    dict(module="planlama.atp", version="v0.7.0", phase_code="BACKFILL_ATP_ROUTE_DECISION_UX_V1",
         primary="e0f7cb3", related=["d362720", "478d7a5", "75f1e2c", "45eb22e"],
         title="Rota karar UX parity ve çoklu iş ekleme kilitlendi.",
         summary="Rota karar açıklayıcı, fabrika dönüş bacağı, KPI parity ve multi-add popup commitlendi.",
         status="ONAYLANDI", test_result="Commit doğrulandı; otomatik pytest yok",
         changes=["Rota karar açıklayıcı.", "Fabrika dönüş bacağı.", "Header KPI parity.", "Multi-add popup."],
         fragment="ATP rota karar UX parity kilitlendi."),
    # ── nexgen.mo (6 groups) ──
    dict(module="nexgen.mo", version="v0.1.0", phase_code="BACKFILL_MO_FOUNDATION_V1",
         primary="05be629", related=["87bdcb4"],
         title="MO müşteri aday ve görüşme çekirdeği eklendi.",
         summary="Müşteri aday kaydı, görüşme çekirdeği ve operasyon merkezi UI commitlendi.",
         status="ONAYLANDI", test_result="Commit doğrulandı; otomatik pytest yok",
         changes=["Müşteri aday çekirdeği.", "Görüşme modülü.", "Operasyon merkezi UI."],
         fragment="MO müşteri aday temeli eklendi."),
    dict(module="nexgen.mo", version="v0.2.0", phase_code="BACKFILL_MO_WORKFLOW_V1",
         primary="7769ff5", related=["d73513b", "70bc0d9"],
         title="MO müşteri operasyon iş akışı tamamlandı.",
         summary="Müşteri operasyon iş akışı boşluk kapatma ve ajanda entegrasyonu commitlendi.",
         status="ONAYLANDI", test_result="Commit doğrulandı; otomatik pytest yok",
         changes=["Operasyon iş akışı tamamlandı.", "Ajanda entegrasyonu."],
         fragment="MO müşteri operasyon iş akışı tamamlandı."),
    dict(module="nexgen.mo", version="v0.3.0", phase_code="BACKFILL_MO_PAZARLAMA_CENTER_V1",
         primary="6756d78", related=["67cfc84", "573d8b1", "776ab7a", "5264223"],
         title="Pazarlama sipariş merkezi ve form doğrulama kilitlendi.",
         summary="Pazarlama sipariş merkezi, legacy fiyat şeması ve MTT form doğrulama commitlendi.",
         status="ONAYLANDI", test_result="Commit doğrulandı; otomatik pytest yok",
         changes=["Sipariş merkezi arayüzü.", "Legacy fiyat şeması.", "Form doğrulama."],
         fragment="Pazarlama sipariş merkezi kilitlendi."),
    dict(module="nexgen.mo", version="v0.4.0", phase_code="BACKFILL_MO_PAZARLAMA_DETAIL_V1",
         primary="f5db195", related=["8a843f1"],
         title="Pazarlama MTT detay UI ve sipariş detay parity kilitlendi.",
         summary="MTT detay UI browser navigasyonu ve sipariş detay workflow parity commitlendi.",
         status="ONAYLANDI", test_result="Commit doğrulandı; otomatik pytest yok",
         changes=["MTT detay UI.", "Browser navigasyon.", "Sipariş detay parity."],
         fragment="Pazarlama MTT detay UI kilitlendi."),
    dict(module="nexgen.mo", version="v0.5.0", phase_code="BACKFILL_MO_AGENDA_WORKFLOW_V1",
         primary="1eae5c1", related=[],
         title="MO müşteri ajanda iş akışı kilitlendi.",
         summary="Müşteri operasyon ajanda UI ve iş akışı pytest ile doğrulandı.",
         status="KILITLI", test_result="MO ajanda pytest PASS",
         changes=["Ajanda UI kilidi.", "Müşteri workflow sync."],
         tests=["MO ajanda pytest"], fragment="MO ajanda iş akışı kilitlendi."),
    dict(module="nexgen.mo", version="v0.6.0", phase_code="BACKFILL_MO_AVANS_V1",
         primary="2c57ea7", related=[],
         title="Avans tahsilat sevkiyat öncesi akışı kilitlendi.",
         summary="Sevkiyat öncesi avans tahsilat akışı pytest ile kilitlendi.",
         status="KILITLI", test_result="Avans tahsilat pytest PASS",
         changes=["Avans tahsilat akışı.", "Sevkiyat öncesi kontrol."],
         tests=["Avans tahsilat pytest"], fragment="Avans tahsilat akışı kilitlendi."),
    # ── test.infra (4 records) ──
    dict(module="test.infra", version="v1.3.0", phase_code="BACKFILL_TEST_INFRA_NEXGEN_ISOLATION",
         primary="2643fa2", related=[],
         title="NexGen test izolasyonu ve canonical DB kilidi.",
         summary="NexGen test isolation hardening ve canonical DB lock pytest ile doğrulandı.",
         status="KILITLI", test_result="NexGen isolation pytest PASS",
         changes=["Test izolasyonu sertleştirildi.", "Canonical DB lock."],
         tests=["NexGen isolation pytest"], fragment="NexGen test izolasyonu kilitlendi."),
    dict(module="test.infra", version="v1.4.0", phase_code="BACKFILL_TEST_INFRA_BROWSER_SAFETY",
         primary="2c2fc1d", related=[],
         title="Browser yazımları canonical DB'den izole edildi.",
         summary="Browser test yazımları canonical DB'den izole edildi; pytest PASS.",
         status="KILITLI", test_result="Browser safety pytest PASS",
         changes=["Browser DB izolasyonu.", "Canonical DB koruma."],
         tests=["Browser safety pytest"], fragment="Browser DB izolasyonu kilitlendi."),
    dict(module="test.infra", version="v1.5.0", phase_code="BACKFILL_TEST_INFRA_C360_CONTRACTS",
         primary="6c6e99f", related=["aeed412", "d278e6e"],
         title="C360 üretim bütünlüğü ve konuşma contract testleri kilitlendi.",
         summary="C360 production integrity, sevkiyat parity ve konuşma contract testleri commitlendi.",
         status="KILITLI", test_result="C360 contract pytest PASS",
         changes=["Üretim bütünlüğü contract.", "Sevkiyat parity test.", "Konuşma contract."],
         tests=["C360 contract pytest"], fragment="C360 contract testleri kilitlendi."),
    dict(module="test.infra", version="v1.6.0", phase_code="BACKFILL_TEST_INFRA_TAHSILAT_ISOLATE",
         primary="8a42567", related=["d3ac8c7"],
         title="Tahsilat browser regresyon DB izolasyonu.",
         summary="Tahsilat browser regression DB isolate ve duplicate hydrate trigger temizliği.",
         status="ONAYLANDI", test_result="Commit doğrulandı; script mevcut",
         changes=["Tahsilat DB izolasyonu.", "Duplicate hydrate trigger kaldırıldı."],
         fragment="Tahsilat test DB izolasyonu eklendi."),
    # ── ajanda ──
    dict(module="ajanda", version="v0.1.0", phase_code="BACKFILL_AJANDA_MIGRATION151_V1",
         primary="e64f8d5", related=["ae45fb1", "8ef883d"],
         title="Ajanda migration 151 ve görüşme detay parity kilitlendi.",
         summary="Migration 151 güvenli uygulama yolu, admin görünüm parity ve görüşme detay birleştirme commitlendi.",
         status="ONAYLANDI", test_result="Commit doğrulandı",
         changes=["Migration 151.", "Admin görünüm parity.", "Görüşme detay birleştirme."],
         fragment="Ajanda migration 151 kilitlendi."),
    # ── uretim.enjeksiyon ──
    dict(module="uretim.enjeksiyon", version="v0.1.0", phase_code="BACKFILL_ENJ_HOURLY_ATOMIC_V1",
         primary="dc1762e", related=["03f3092"],
         title="Enjeksiyon saatlik atomik yazım kilidi.",
         summary="Saatlik üretim atomik yazım ve Ferhat home contract pytest ile kilitlendi.",
         status="KILITLI", test_result="Enjeksiyon hourly pytest PASS",
         changes=["Saatlik atomik yazım.", "Ferhat home contract."],
         tests=["Enjeksiyon hourly pytest"], fragment="Enjeksiyon saatlik atomik yazım kilitlendi."),
    # ── cps.release.history meta ──
    dict(module="cps.release.history", version="v1.2.0", phase_code="BACKFILL_CPS_RELEASE_HISTORY_9941CDC",
         primary="9941cdc", related=[],
         title="Release history doğrulanmış backfill commitlendi.",
         summary="22 kayıtlı ATP backfill, validator ve test stabilizasyonu commitlendi.",
         status="KILITLI", test_result="Validator 22 kayıt PASS; 33/33 pytest PASS",
         changes=["Backfill kayıtları.", "Validator.", "Test stabilizasyonu."],
         tests=["test_validate_release_history_v1", "test_release_history_ui_v2"],
         fragment="Release history backfill commitlendi."),
    # ── nexgen.numune gap ──
    dict(module="nexgen.numune", version="v0.4.0", phase_code="BACKFILL_NUMUNE_ROUTE_BRIDGE_V1",
         primary="07d3b16", related=[],
         title="Numune rota-sipariş köprüsü eklendi.",
         summary="Route-to-sample bridge servisi pytest ile doğrulandı.",
         status="KILITLI", test_result="Numune route bridge pytest PASS",
         changes=["Route-sample bridge.", "Servis bağlantısı."],
         tests=["Numune route bridge pytest"], fragment="Numune rota köprüsü eklendi."),
]


if __name__ == "__main__":
    for rec in GATE2_RECORDS:
        write_commit_record(rec)
    print("TOTAL", len(GATE2_RECORDS))
