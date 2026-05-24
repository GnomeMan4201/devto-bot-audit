import csv
from datetime import datetime
from collections import Counter

CSV_PATH = "devto_bot_audit_full.csv"
REPORT_PATH = "devto_bot_audit_report.md"
FLAGGED_PATH = "flagged_usernames.txt"
SCORE_THRESHOLD = 2

def summarize():
    with open(CSV_PATH, newline='') as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("⚠️ No rows found.")
        return

    total = len(rows)
    flagged = []
    suspicious = []
    likely_real = []
    zero_activity = 0
    no_avatar = 0
    join_dates = []

    for row in rows:
        try:
            score = int(row.get("HeuristicScore", 0))
        except ValueError:
            score = 0

        posts = row.get("PostCount", "0")
        try:
            posts = int(posts)
        except ValueError:
            posts = 0

        avatar_default = row.get("AvatarDefault", "true").lower() == "true"
        bio = row.get("Bio", "").strip()
        joined = row.get("JoinedDate", "").strip()
        username = row.get("Username", "").strip()

        if joined:
            join_dates.append(joined[:10])  # YYYY-MM-DD

        if posts == 0 and not bio:
            zero_activity += 1
        if avatar_default:
            no_avatar += 1

        if score >= SCORE_THRESHOLD:
            flagged.append(username)
        elif score >= 1:
            suspicious.append(username)
        else:
            likely_real.append(username)

    # Date clustering
    date_counts = Counter(join_dates)
    top_dates = date_counts.most_common(5)

    bot_pct = (len(flagged) / total) * 100
    suspicious_pct = (len(suspicious) / total) * 100
    real_pct = (len(likely_real) / total) * 100

    # Print summary
    print("\n📊 Bot Detection Summary")
    print("-" * 40)
    print(f"Total accounts analyzed : {total}")
    print(f"Flagged as bots         : {len(flagged)} ({bot_pct:.1f}%)")
    print(f"Suspicious              : {len(suspicious)} ({suspicious_pct:.1f}%)")
    print(f"Likely real             : {len(likely_real)} ({real_pct:.1f}%)")
    print(f"Zero posts + no bio     : {zero_activity}")
    print(f"Default/no avatar       : {no_avatar}")
    print("\n📅 Top join date clusters:")
    for date, count in top_dates:
        print(f"  {date}: {count} accounts")

    # Write report
    with open(REPORT_PATH, "w") as f:
        f.write("# DEV.to Bot Audit Report\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write("## Summary\n\n")
        f.write(f"| Metric | Value |\n|---|---|\n")
        f.write(f"| Total followers audited | {total} |\n")
        f.write(f"| Flagged as bots (score ≥ {SCORE_THRESHOLD}) | {len(flagged)} ({bot_pct:.1f}%) |\n")
        f.write(f"| Suspicious (score 1-2) | {len(suspicious)} ({suspicious_pct:.1f}%) |\n")
        f.write(f"| Likely real | {len(likely_real)} ({real_pct:.1f}%) |\n")
        f.write(f"| Zero posts + no bio | {zero_activity} |\n")
        f.write(f"| Default/no avatar | {no_avatar} |\n\n")
        f.write("## Account Creation Clustering\n\n")
        f.write("Accounts created on the same dates (bot batch indicator):\n\n")
        for date, count in top_dates:
            f.write(f"- `{date}`: {count} accounts\n")
        f.write("\n## Notes\n\n")
        f.write("Follower count spiked from ~600 to 1,393 in a matter of days.\n")
        f.write("GitHub follower count does not reflect this spike, suggesting artificial inflation.\n")
        f.write("Flagged accounts exhibit: auto-generated usernames, zero post/comment activity, ")
        f.write("default avatars, and no bio.\n")

    # Write flagged list
    with open(FLAGGED_PATH, "w") as f:
        f.write("\n".join(flagged))

    print(f"\n✅ Report written: {REPORT_PATH}")
    print(f"📁 Flagged usernames: {FLAGGED_PATH} ({len(flagged)} accounts)")

if __name__ == "__main__":
    summarize()
