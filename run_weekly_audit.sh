#!/bin/bash
cd ~/devto-bot-audit || exit 1
source ~/.bashrc

# Replace YOUR_API_KEY with actual value or use export DEVTO_API_KEY=...
python3 devto_bot_audit_api.py --api-key "$DEVTO_API_KEY"

# Git commit + push if anything changed
git add devto_bot_audit_full.csv
git diff --cached --quiet || {
  git commit -m "🤖 Weekly audit: updated CSV with latest bot scores"
  git pull --rebase origin main
  git push origin main
}
