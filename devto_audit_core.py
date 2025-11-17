import csv
import os
import re
import time
import requests

DEVTO_API_KEY = os.getenv("DEVTO_API_KEY")
HEADERS = {"api-key": DEVTO_API_KEY} if DEVTO_API_KEY else {}

def fetch_followers():
    followers = []
    page = 1
    while True:
        url = f"https://dev.to/api/followers/users?page={page}"
        r = requests.get(url, headers=HEADERS)
        if r.status_code != 200:
            break
        data = r.json()
        if not data:
            break
        followers.extend(data)
        print(f"📦 Page {page}: +{len(data)} followers")
        page += 1
        time.sleep(1)
    print(f"✅ Total followers fetched: {len(followers)}")
    return followers

def fetch_user_profile(username):
    url = f"https://dev.to/api/users/by_username?url={username}"
    r = requests.get(url, headers=HEADERS)
    if r.status_code == 200:
        return r.json()
    return {}

def score_account(username):
    profile = fetch_user_profile(username)
    score = 0
    notes = []

    if re.match(r"^[_\\-0-9a-f]{6,}$", username):
        score += 1
        notes.append("Suspicious username")

    if not profile.get("summary"):
        score += 1
        notes.append("Empty bio")

    if profile.get("public_articles_count", 0) == 0:
        score += 1
        notes.append("No posts")

    if profile.get("profile_image", "").endswith("default_profile_image.png"):
        score += 1
        notes.append("Default profile image")

    followers = profile.get("followers_count", 1)
    following = profile.get("followed_users_count", 1)
    if following > 10 and followers / following < 0.1:
        score += 1
        notes.append("Low follower/following ratio")

    return {
        "username": username,
        "name": profile.get("name", ""),
        "bio": profile.get("summary", ""),
        "articles": profile.get("public_articles_count", 0),
        "followers": followers,
        "following": following,
        "image": profile.get("profile_image", ""),
        "heuristic_score": score,
        "notes": "; ".join(notes)
    }

def run_audit():
    followers = fetch_followers()
    results = []
    for i, f in enumerate(followers, 1):
        username = f.get("user_name")
        print(f"[{i}/{len(followers)}] Fetching {username}")
        row = score_account(username)
        results.append(row)

    with open("devto_bot_audit_full.csv", "w", newline='') as f:
    # Safety check for empty results
    if not results:
        print("\n⚠️  No follower data retrieved. Exiting audit.")
        return

    if not results:
        print("\n⚠️ No data. Exiting.")
        return

        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    print("✅ DONE. Output saved to devto_bot_audit_full.csv")
