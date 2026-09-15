# Deployment State Sistemi

## Dosyalar

| Dosya | Git | Açıklama |
|-------|-----|----------|
| `var/release/deployment_state.json` | Hayır | Runtime push/deploy durumu cache |
| `var/release/deployment_manifest.json` | Hayır | Son deploy olayı kanıtı |
| `tools/release_state.py` | Evet | Durum üretici (Git okur, JSON yazar) |
| `tools/check_release_fragment.py` | Evet | Pre-commit production guard |
| `tools/deploy_cps_with_release_state.ps1` | Evet | Resmi deploy wrapper (DRY-RUN default) |
| `.githooks/pre-commit` | Evet | Hook şablonu |

## Wrapper sözleşmesi

| Soru | Cevap |
|------|-------|
| Kodu servera aktarır mı? | **Hayır** — kod önceden server repo'sunda olmalı (git pull / rsync ayrı adım) |
| Ne yapar? | Preflight, DB backup, restart, HTTP smoke, manifest + state yazar |
| Nerede çalışır? | `C:\Solariz_CPS_SERVER` (RepoRoot doğrulaması zorunlu) |
| Server HEAD | `--commit` / `--server-head` (default: local HEAD) |
| Push yapılmamış commit | Prod `-Execute` deploy **engellenir** (ahead > 0) |
| Dirty tracked worktree | **FAIL** — deploy durur |
| Fast-forward değilse | **FAIL** — reset/clean yok |
| DB backup | Execute modunda `logs/deploy_backup/` altına kopya |
| Restart sırası | Preflight → DB backup → restart script → HTTP smoke → manifest |
| Başarısızlık | Eski proses çalışmaya devam eder; rollback **manuel** |
| DEPLOYED_VERIFIED | Yalnız HTTP 200 smoke + geçerli SHA sonrası |
| DEPLOY_FAILED | Smoke/manifest hatasında otomatik flag |
| Manuel state komutu | **Gerekmez** — wrapper otomatik `record_deploy_event.py` çağırır |

## Pazartesi resmi deploy komutu

**DRY-RUN (default — güvenli):**

```powershell
powershell -File tools/deploy_cps_with_release_state.ps1
```

**Gerçek deploy (Adem onayı + `-Execute`):**

```powershell
powershell -File tools/deploy_cps_with_release_state.ps1 -Execute
```

Smoke-only (restart yok):

```powershell
powershell -File tools/deploy_cps_with_release_state.ps1 -Execute -SmokeOnly
```

## Durumlar

- `WORKING` — commit bekleyen working tree (modül bazında yalnız ilgili modül)
- `COMMIT_PENDING` — staged relevant files
- `LOCAL_COMMITTED_NOT_PUSHED` — local ahead of upstream
- `PUSHED_NOT_DEPLOYED` — push yapıldı, deploy bekliyor
- `DEPLOYED_VERIFIED` — manifest SHA + HTTP smoke PASS
- `DEPLOY_FAILED` — deploy başarısız
- `DEPLOYMENT_UNKNOWN` — kanıt yok

## Durum önceliği

1. `COMMIT_PENDING` — staged relevant production/history
2. `WORKING` — dirty relevant (unstaged/untracked) files
3. `DEPLOY_FAILED` — manifest deploy_failed
4. `DEPLOYED_VERIFIED` — manifest SHA = server_head + HTTP 200 smoke
5. `PUSHED_NOT_DEPLOYED` — clean, synced upstream, manifest geride
6. `LOCAL_COMMITTED_NOT_PUSHED` — clean, ahead of upstream

Unrelated dirty files (ör. `_audit_out`, kök temp scriptler) global state'i etkilemez.

## Hook kurulumu

```powershell
powershell -File tools/install_release_hooks.ps1
git config --get core.hooksPath   # beklenen: .githooks
```

## Güvenlik

- Atomic write: temp + replace
- Path traversal: kayıt yükleyici symlink ve `..` reddeder
- Hardcoded credential/path yok (RepoRoot parametre veya otomatik tespit)
- Broad process kill yok
- Manifest SHA Git'te doğrulanır; fake PASS engellenir
- `locked_rules` değişimi `locked_rules_approval` veya `approved_by`+`breaking_rules` olmadan hook FAIL

Production dosyası (`app/modules/`, `app/templates/`, `app/migrations/`) staged ise eşleşen TOML+fragment zorunlu.

İstisna: `docs/`, `tests/`, `changes/`, release history servis dosyaları.
