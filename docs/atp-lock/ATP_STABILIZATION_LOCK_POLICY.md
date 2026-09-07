# ATP Production Stabilization Lock Policy

## Baseline

| Field | Value |
|-------|-------|
| Host | SOLARIZDB |
| Repo | `C:\Solariz_CPS_SERVER` |
| Branch | `main` |
| Baseline commit | `21b8a2100ba34db92172f300f246c2a67b319e94` |
| Release source | `origin/release/atp-filom-worker-redirect-v1` |
| Phase | `ATP_PRODUCTION_STABILIZATION_LOCK_V1` |

Production ATP (Araç Takip & Plan) is **frozen** at this baseline until Adem provides explicit written approval to unlock.

## Rules

1. **No ATP changes without unlock** — Application code, UI, worker scripts, adapter, geofence, route logic, and ATP-specific tests must not change unless an explicit unlock phase is approved and a new baseline manifest is published.

2. **Non-ATP releases require ATP diff = 0** — Any release touching Finans, NexGen, Etiket Basım, or other modules must leave every manifest-listed ATP file byte-identical to the baseline SHA256.

3. **Fail-closed validation** — `tools/validate_atp_stabilization_lock.py` must PASS before release history validation completes. Hash mismatch, missing manifest file, forbidden path in manifest, or undeclared ATP dependency → FAIL (non-zero exit).

4. **Unlock procedure** — To change ATP after lock:
   - Open a dedicated unlock phase (new TOML + fragment).
   - Adem approval required.
   - Deploy and verify production.
   - Regenerate manifest with `tools/build_atp_lock_manifest.py` at the new commit.
   - Update `lock_baseline_commit` in manifest header.

5. **Out of scope (never hashed)** — Runtime DB rows, GPS snapshots, logs, cache, `.env`, DPAPI secrets, passwords, usernames, tokens, `mock_data.db` content at runtime, screenshots, `__pycache__`, `.pyc`.

6. **Secrets** — Secret **values** and **hashes** are never stored in the manifest or release records. Root cause may reference “DPAPI password mismatch” without credential material.

7. **Shared files** — `app/app.py`, `app/templates/base.html`, and `app/migrations/nexgen_manifest.py` are not fully locked (non-ATP edits allowed). Only declared **touchpoints** (line-range hashes) are enforced. See `docs/atp-lock/atp_touchpoints.sha256`.

8. **Known accepted gaps (baseline)** — Past-departure ORS snapshot UX button missing; production geofence enter/exit not yet fully observed; V2 unresolved-3xx hardening not in production.

## Enforcement

- **Deploy gate:** `deploy_preflight.ps1` step 0 runs `tools/validate_atp_stabilization_lock.py` when the manifest exists (fail-closed).
- **Deploy wrapper (main):** `tools/deploy_cps_with_release_state.ps1 -Execute` invokes `deploy_preflight.ps1` before restart/backup.
- **Not wired:** `_start_8080_clean.ps1`, pre-commit, CI (absent at baseline `21b8a21`).
- Inventory: `docs/atp-lock/atp_inventory.json` (forensic dependency graph).
- Manifest: `docs/atp-lock/atp_stabilization_manifest.sha256`.

## Forensic scope summary

Locked via full-file SHA256:

- `app/modules/planlama/arac_*` services/repos (import closure from routes)
- `app/modules/planlama/arac_operasyonu/**` (Filom adapter)
- `app/modules/planlama/road_routing/**` (route planner used by ATP)
- ATP UI template, CSS, JS
- ATP migrations `176`–`188` + `189_planlama_arac_takip_rol32_yetki.py`
- GPS worker scripts (`Start-Arac-GPS-Worker.ps1`, `Register-Arac-GPS-Worker-Task.ps1`, `app/tools/arac_gps_poll_*.py`)
- ATP test suite under `tests/planlama/`
- `app/tools/atp_test_db_guard.py`

Not locked (shared infrastructure): `app/db.py`, `modules/auth`, full `app/app.py`, full `base.html`, full `nexgen_manifest.py`.
