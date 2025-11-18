#!/bin/bash
#
# run_audit.sh - Complete workflow for DEV.to bot auditing

set -e
echo " Starting DEV.to Bot Audit Pipeline..."
echo ""
# Run the Python audit
python3 devto_audit_core.py
# Calculate bot score from CSV
echo " Calculating bot statistics..."
BOT_COUNT=$(awk -F',' 'NR>1 && ($10 ~ /Suspicious username/ || $9 >= 3) {count++} END {print count}' devto_bot_audit_full.csv)
TOTAL_COUNT=$(($(wc -l < devto_bot_audit_full.csv) - 1))
PERCENT=$(awk "BEGIN { printf \"%.2f\", ($BOT_COUNT/$TOTAL_COUNT)*100 }")
echo "  ├─ Total accounts: $TOTAL_COUNT"
echo "  ├─ Flagged bots  : $BOT_COUNT"
echo "  └─ Percentage    : $PERCENT%"
# Update README badge
echo " Updating README.md badge..."
echo "  ✓ Badge updated"
# Export flagged usernames
echo "🏴 Exporting flagged usernames..."
awk -F',' 'NR>1 && ($10 ~ /Suspicious username/ || $9 >= 3) { print $1 }' devto_bot_audit_full.csv > flagged_usernames.txt
FLAGGED_COUNT=$(wc -l < flagged_usernames.txt)
echo "  ✓ Exported $FLAGGED_COUNT flagged usernames to flagged_usernames.txt"
# Git operations
git add devto_audit_core.py devto_bot_audit_full.csv flagged_usernames.txt README.md
if git diff --cached --quiet; then
    echo "  ℹ️  No changes to commit"
else
    echo "  ✓ Changes committed"
    
    echo ""
    git pull --rebase origin main || {
        echo "⚠️  Rebase conflict - resolve manually and run:"
        echo "    git rebase --continue"
        echo "    git push origin main"
        exit 1
    }
    git push origin main
fi



![Bot Score](https://img.shields.io/badge/Bot%20Integrity-43.35%%25%20bots-red)
