# Server Runbook — FAZ-NEXGEN-TAM-SERVER-PARITE-1
1. RDP -> C:\Solariz_CPS_SERVER
2. Stop CPS
3. Copy-Item app\mock_data.db app\mock_data.BACKUP_20260720_120416.db
4. git fetch origin && git pull --ff-only origin main
5. =1
6. python app\tools\nexgen_schema_upgrade.py --db app\mock_data.db --verify
7. python app\tools\nexgen_server_profile.py --db app\mock_data.db --out deploy\server_profile.json
8. python app\tools\nexgen_master_data_sync.py --target-db app\mock_data.db --package deploy\nexgen_master_data_package.json --check
9. python app\tools\nexgen_master_data_sync.py --target-db app\mock_data.db --package deploy\nexgen_master_data_package.json --dry-run
10. Onay -> --apply then --verify
11. python app\tools\nexgen_pazarlama_kalem_backfill.py --db app\mock_data.db --check
12. .\scripts\deploy_preflight_nexgen.ps1
13. Restart CPS, Ctrl+F5 smoke
