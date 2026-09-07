# ATP Lock Enforcement

## Forensic finding (baseline `21b8a21`)

| Entry point | Exists at baseline? | Calls ATP lock? |
|-------------|---------------------|-----------------|
| `deploy_preflight.ps1` | **Yes** | **Yes** (step 0, when manifest present) |
| `tools/deploy_cps_with_release_state.ps1` | No (main branch only) | Indirect via `deploy_preflight.ps1` on `-Execute` |
| `.githooks/pre-commit` | No | No |
| `tools/validate_release_history.py` | No | No |
| `_start_8080_clean.ps1` | Yes | **No** (intentionally — must not block CPS startup) |
| CI workflow (`.github/`) | No | No |

## Automatic enforcement answer

**Deploy path (production):** When `deploy_preflight.ps1` runs (including via `deploy_cps_with_release_state.ps1 -Execute` on branches that have that wrapper), ATP lock validator runs automatically if `docs/atp-lock/atp_stabilization_manifest.sha256` exists. Tamper → non-zero exit → preflight FAIL → deploy blocked.

**Commit-only / local dev / `_start_8080_clean.ps1`:** ATP lock does **not** run automatically. Bypass risk remains unless operator runs `python tools/validate_atp_stabilization_lock.py` manually or future pre-commit hook is installed separately.

## Operator commands

```powershell
python tools/validate_atp_stabilization_lock.py
.\deploy_preflight.ps1
```

## Unlock

See `ATP_STABILIZATION_LOCK_POLICY.md`.
