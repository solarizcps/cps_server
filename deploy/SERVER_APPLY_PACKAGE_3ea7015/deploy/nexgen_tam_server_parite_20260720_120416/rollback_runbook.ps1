# Rollback
Copy-Item app\mock_data.BACKUP_*.db app\mock_data.db -Force
git reset --hard <PREVIOUS_SHA>
Restart CPS
