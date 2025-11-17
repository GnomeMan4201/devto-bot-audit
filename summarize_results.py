import csv

def summarize_audit_results(csv_path):
    with open(csv_path, newline='') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    bot_count = 0
    for row in rows:
        try:
            score = int(row["heuristic_score"])
            notes = row["notes"]
            if "Suspicious username" in notes or score >= 3:
                bot_count += 1
        except (KeyError, ValueError):
            continue

    total = len(rows)
    percent = (bot_count / total) * 100 if total else 0.0

    print("\n📊 Bot Detection Summary")
    print("-" * 24)
    print(f"Total accounts analyzed: {total}")
    print(f"Flagged as likely bots : {bot_count}")
    print(f"Percentage              : {percent:.2f}%")
