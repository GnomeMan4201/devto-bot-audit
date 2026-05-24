#!/usr/bin/env bash
set -euo pipefail

echo "🔍 Starting DEV.to Bot Audit..."

rm -f devto_bot_audit_full.csv
rm -f flagged_usernames.txt
rm -f devto_bot_audit_report.md

python3 devto_bot_audit_api.py

if [[ ! -f devto_bot_audit_full.csv ]]; then
  echo "❌ devto_bot_audit_full.csv was not created"
  exit 1
fi

rows=$(($(wc -l < devto_bot_audit_full.csv) - 1))

if [[ "$rows" -lt 1 ]]; then
  echo "❌ No account rows were written to devto_bot_audit_full.csv"
  echo "   Follower discovery may work, but profile scoring/export is broken."
  echo
  echo "Debug:"
  echo "  wc -l devto_bot_audit_full.csv"
  echo "  head -5 devto_bot_audit_full.csv"
  echo "  grep -R \"writerow\\|append\\|devto_bot_audit_full.csv\" -n *.py"
  exit 1
fi

echo "✅ Account rows written: $rows"

python3 summarize_results.py

echo "📝 Report written: devto_bot_audit_report.md"
echo "📁 Flagged usernames written: flagged_usernames.txt"

echo
echo "📊 Final report preview:"
head -40 devto_bot_audit_report.md || true
