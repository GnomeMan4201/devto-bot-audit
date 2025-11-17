import csv

def summarize_audit_results(csv_path):
    try:
        with open(csv_path, newline='') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            print("⚠️ No rows in CSV. Nothing to summarize.")
            return

        bot_count = 0
        for row in rows:
            try:
                score = int(row.get("heuristic_score", 0))
                notes = row.get("notes", "")
                if "Suspicious username" in notes or score >= 3:
                    bot_count += 1
            except ValueError:
                continue

        total = len(rows)
        percent = (bot_count / total) * 100 if total else 0.0

        print("\n📊 Bot Detection Summary")
        print("-" * 24)
        print(f"Total accounts analyzed: {total}")
        print(f"Flagged as likely bots : {bot_count}")
        print(f"Percentage              : {percent:.2f}%")
    except FileNotFoundError:
        print("❌ CSV file not found.")
