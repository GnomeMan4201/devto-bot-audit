import re
import os
import csv
import time
import requests
from bs4 import BeautifulSoup

#####################
# CONFIGURATION
#####################
USE_AI = False
RATE_LIMIT_DELAY = 1
USERNAME = "gnomeman4201"
API_KEY = os.getenv("DEVTO_API_KEY")
OUTPUT_CSV = "devto_bot_audit_full.csv"
#####################

HEADERS = {
    "api-key": API_KEY,
    "User-Agent": "Mozilla/5.0"
}


def get_all_followers_api(username):
    print("🔐 Using DEV.to API to retrieve followers...")
    followers = []
    page = 1

    while True:
        url = f"https://dev.to/api/followers/users?page={page}"
        resp = requests.get(url, headers=HEADERS)

        if resp.status_code != 200:
            print(f"❌ Error fetching page {page}: {resp.status_code}")
            break

        data = resp.json()
        if not data:
            break

        for user in data:
            followers.append(user["username"])

        print(f"📦 Page {page}: +{len(data)} followers")
        page += 1
        time.sleep(1)

    print(f"✅ Total followers fetched: {len(followers)}")
    return sorted(set(followers))


def fetch_profile(username):
    url = f"https://dev.to/{username}"
    resp = requests.get(url, headers=HEADERS)
    soup = BeautifulSoup(resp.text, "html.parser")

    bio_elem = soup.find("div", class_="profile-metadata__bio")
    bio = bio_elem.text.strip() if bio_elem else ""

    post_count = len(soup.find_all("div", class_="crayons-story"))

    avatar_elem = soup.find("img", class_="profile-pic")
    avatar_url = avatar_elem["src"] if avatar_elem else ""
    avatar_default = ("default" in avatar_url or "avatar" in avatar_url)

    joined_elem = soup.find("span", string=re.compile(r"Joined"))
    joined_date = joined_elem.text.strip() if joined_elem else ""

    stats = soup.find_all("span", class_="profile-metadata__stat")
    followers = following = 0
    if len(stats) >= 2:
        try:
            followers = int(stats[0].text.strip())
            following = int(stats[1].text.strip())
        except:
            pass

    return {
        "username": username,
        "bio": bio,
        "post_count": post_count,
        "avatar_default": avatar_default,
        "avatar_url": avatar_url,
        "joined_date": joined_date,
        "followers": followers,
        "following": following,
    }


def heuristic_bot_score(profile):
    score = 0
    reasons = []
    if profile["bio"] == "":
        score += 1
        reasons.append("No bio")
    if profile["post_count"] == 0:
        score += 1
        reasons.append("No posts")
    if profile["avatar_default"]:
        score += 1
        reasons.append("Default avatar")
    if re.match(r".*(_[a-f0-9]{6,}|[0-9]{4,})$", profile["username"]):
        score += 1
        reasons.append("Suspicious username")
    if profile["followers"] == 0 and profile["following"] > 10:
        score += 1
        reasons.append("Mass follow")
    if profile["joined_date"] and re.search(r"2024|2025", profile["joined_date"]):
        score += 1
        reasons.append("Very new account")
    return score, reasons


def ai_bot_score(profile):
    import openai
    openai.api_key = os.getenv("OPENAI_API_KEY")
    prompt = f"""
Dev.to user profile analysis:
- Username: {profile['username']}
- Bio: {profile['bio']}
- Post count: {profile['post_count']}
- Avatar default: {profile['avatar_default']}
- Joined date: {profile['joined_date']}
- Followers: {profile['followers']}
- Following: {profile['following']}
Score the likelihood (0-10) that this account is a bot, and justify your score.
"""
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        reply = response.choices[0].message.content
        match = re.search(r"\d+", reply)
        score = int(match.group()) if match else ""
        return score, reply.strip()
    except Exception as e:
        return "", f"AI error: {e}"


def main():
    if not API_KEY:
        print("❌ DEVTO_API_KEY not found. Please run:\nexport DEVTO_API_KEY='your_key_here'")
        return

    usernames = get_all_followers_api(USERNAME)
    results = []

    for idx, u in enumerate(usernames):
        print(f"[{idx+1}/{len(usernames)}] Fetching {u}")
        try:
            profile = fetch_profile(u)
            hscore, hreasons = heuristic_bot_score(profile)
            profile["heuristic_score"] = hscore
            profile["heuristic_reasons"] = "; ".join(hreasons)
            if USE_AI:
                aiscore, aijust = ai_bot_score(profile)
                profile["ai_score"] = aiscore
                profile["ai_justification"] = aijust
            else:
                profile["ai_score"] = ""
                profile["ai_justification"] = ""
            results.append(profile)
        except Exception as e:
            print(f"❌ Error for {u}: {e}")
        time.sleep(RATE_LIMIT_DELAY)

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Username", "Bio", "PostCount", "AvatarDefault", "AvatarURL",
            "JoinedDate", "Followers", "Following",
            "HeuristicScore", "HeuristicReasons", "AIScore", "AIJustification"
        ])
        for p in results:
            writer.writerow([
                p["username"], p["bio"], p["post_count"], p["avatar_default"], p["avatar_url"],
                p["joined_date"], p["followers"], p["following"],
                p.get("heuristic_score", ""), p.get("heuristic_reasons", ""),
                p.get("ai_score", ""), p.get("ai_justification", "")
            ])
    print(f"\n✅ DONE. Output saved to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()

# --- Bot Detection Summary Logic ---
import csv

def summarize_bot_stats(filename="devto_bot_audit_full.csv"):
    try:
        with open(filename, newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            total = bots = 0
            for row in reader:
                total += 1
                if 'Suspicious username' in row.get('notes', '') or int(row.get('heuristic_score', 0)) >= 3:
                    bots += 1
            percent = (bots / total) * 100 if total else 0
            print("\n🔎 Bot Detection Summary")
            print("-----------------------")
            print(f"Total accounts analyzed: {total}")
            print(f"Flagged as likely bots : {bots}")
            print(f"Percentage              : {percent:.2f}%\n")
    except Exception as e:
        print(f"[!] Error while summarizing: {e}")

# --- Append to CLI ---
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--api-key', help="Your DEV API key")
    parser.add_argument('--summary', action='store_true', help="Show bot detection summary after audit")
    args = parser.parse_args()

    if args.api_key:
        # Your existing audit logic here (assuming it creates devto_bot_audit_full.csv)
        pass  # Replace with actual call like: run_audit(args.api_key)

    if args.summary:
        summarize_bot_stats()

# --- CLI Entry Point ---
if __name__ == "__main__":
    import argparse
    import os

    def summarize_bot_stats():
        import csv

        try:
            with open("devto_bot_audit_full.csv", "r") as f:
                reader = csv.reader(f)
                headers = next(reader)
                total = 0
                bots = 0
                for row in reader:
                    total += 1
                    score = int(row[9])
                    flag = row[10]
                    if score >= 3 or "Suspicious username" in flag:
                        bots += 1
                percent = round((bots / total) * 100, 2)
                print(f"\n📊 Summary: {bots} likely bots out of {total} total followers ({percent}%)\n")
        except FileNotFoundError:
            print("❌ Could not find devto_bot_audit_full.csv. Run the audit first with --api-key.")
        except Exception as e:
            print(f"❌ Error during summary: {e}")

    parser = argparse.ArgumentParser(description="DEV.to Bot Audit Tool")
    parser.add_argument('--api-key', help="Your DEV.to API key")
    parser.add_argument('--summary', action='store_true', help="Print bot detection summary after audit")
    args = parser.parse_args()

    if args.api_key:
        print("🔐 Starting bot audit using DEV.to API...")
        os.environ["DEVTO_API_KEY"] = args.api_key
        from devto_audit_core import run_audit
        run_audit()
        print("✅ Audit complete.")

    if args.summary:
        summarize_bot_stats()
