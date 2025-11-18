#!/bin/bash
set -e

echo "🔍 Starting DEV.to Bot Audit..."

# Step 1: Run scraper + audit
python3 devto_audit_core.py

# Step 2: Count bot results
BOT_COUNT=$(awk -F',' 'NR>1 && ($10 ~ /Suspicious username/ || $9 >= 3) {count++} END {print count}' devto_bot_audit_full.csv)
TOTAL_COUNT=$(($(wc -l < devto_bot_audit_full.csv) - 1))
if [[ "$TOTAL_COUNT" -eq 0 ]]; then
  PERCENT=0
else
  PERCENT=$(awk "BEGIN { printf \"%.2f\", ($BOT_COUNT/$TOTAL_COUNT)*100 }")
fi

echo "📊 Results:"
echo "  ├─ Total accounts: $TOTAL_COUNT"
echo "  ├─ Flagged bots  : $BOT_COUNT"
echo "  └─ Percentage    : $PERCENT%"

# Step 3: Replace badge in README (not append)
BADGE_LINE="![Bot Score](https://img.shields.io/badge/Bot%20Integrity-${PERCENT}%25%20bots-red)"
if grep -q '!\[Bot Score\]' README.md; then
    sed -i "s|!\[Bot Score\].*|$BADGE_LINE|" README.md
else
    echo -e "\n$BADGE_LINE" >> README.md
fi
echo "📝 README badge updated."

# Step 4: Export usernames
awk -F',' 'NR>1 && ($10 ~ /Suspicious username/ || $9 >= 3) { print $1 }' devto_bot_audit_full.csv > flagged_usernames.txt
echo "📁 Exported $(wc -l < flagged_usernames.txt) flagged usernames."

# Step 5: Warn if counts mismatch
EXPECTED=$(python3 -c 'from devto_bot_audit_api import get_follower_count; print(get_follower_count())')
if [[ "$EXPECTED" -ge 0 && "$EXPECTED" != "$TOTAL_COUNT" ]]; then
    echo "⚠️  WARNING: Expected $EXPECTED followers but parsed $TOTAL_COUNT. Possible HTML layout issue."
fi
    echo "⚠️  WARNING: Expected $EXPECTED followers but parsed $TOTAL_COUNT. Possible HTML layout issue."
fi

echo "✅ Audit complete."
