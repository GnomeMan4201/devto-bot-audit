import csv
import os
import re
import time
import requests
from collections import defaultdict, Counter
from datetime import datetime

DEVTO_API_KEY = os.getenv("DEVTO_API_KEY")
HEADERS = {"api-key": DEVTO_API_KEY} if DEVTO_API_KEY else {}

SPIKE_START = "2026-05-13"
SPIKE_END   = "2026-05-20"

# Load your already-flagged bot usernames
def load_flagged(path="flagged_usernames.txt"):
    try:
        with open(path) as f:
            return set(line.strip() for line in f if line.strip())
    except FileNotFoundError:
        return set()

# Fetch trending articles in the spike date range
def fetch_trending_articles(per_page=30):
    print("📰 Fetching trending articles from spike window...")
    articles = []
    for page in range(1, 5):
        url = f"https://dev.to/api/articles?top=7&page={page}&per_page={per_page}"
        r = requests.get(url, headers=HEADERS)
        if r.status_code != 200:
            break
        data = r.json()
        if not data:
            break
        for a in data:
            published = a.get("published_at", "")[:10]
            if SPIKE_START <= published <= SPIKE_END:
                articles.append({
                    "id": a["id"],
                    "title": a["title"],
                    "username": a["user"]["username"],
                    "tags": a.get("tag_list", []) if isinstance(a.get("tag_list"), list) else [],
                    "reactions": a.get("positive_reactions_count", 0),
                    "published": published
                })
        time.sleep(1)
    print(f"✅ Found {len(articles)} articles in spike window")
    return articles

# Fetch followers for any username (not just yours)
def fetch_user_followers(username, max_pages=10):
    followers = []
    for page in range(1, max_pages + 1):
        url = f"https://dev.to/api/followers/users?page={page}&per_page=80"
        r = requests.get(url, headers=HEADERS)
        if r.status_code != 200:
            break
        data = r.json()
        if not data:
            break
        followers.extend([f.get("username") for f in data if f.get("username")])
        time.sleep(0.5)
    return followers

# Fetch user profile
def fetch_profile(username):
    url = f"https://dev.to/api/users/by_username?url={username}"
    r = requests.get(url, headers=HEADERS)
    if r.status_code == 200:
        return r.json()
    return {}

def run_network_audit():
    flagged_bots = load_flagged()
    print(f"🤖 Loaded {len(flagged_bots)} known bot usernames\n")

    articles = fetch_trending_articles()
    if not articles:
        print("⚠️ No articles found in spike window. Try widening the date range.")
        return

    # Get unique authors
    authors = list(set(a["username"] for a in articles))
    print(f"\n👥 Unique authors to audit: {len(authors)}")

    author_results = []
    cross_ref_hits = defaultdict(list)  # bot_username -> [authors it also follows]

    for i, author in enumerate(authors, 1):
        print(f"\n[{i}/{len(authors)}] Auditing @{author}...")
        profile = fetch_profile(author)

        tags = []
        for article in articles:
            if article["username"] == author:
                tags.extend(article["tags"])

        follower_count = profile.get("followers_count", 0)

        # Fetch their followers and cross-ref against your bot list
        their_followers = fetch_user_followers(author)
        overlap = [u for u in their_followers if u in flagged_bots]
        overlap_pct = (len(overlap) / len(their_followers) * 100) if their_followers else 0

        for bot in overlap:
            cross_ref_hits[bot].append(author)

        author_results.append({
            "Username": author,
            "Followers": follower_count,
            "TopTags": ", ".join(set(tags)),
            "ArticlesInWindow": sum(1 for a in articles if a["username"] == author),
            "TheirFollowersFetched": len(their_followers),
            "KnownBotsInFollowers": len(overlap),
            "BotOverlapPct": f"{overlap_pct:.1f}%",
            "SharedBots": "; ".join(overlap[:10])  # first 10 for preview
        })

        time.sleep(1)

    # Write author report
    with open("network_author_report.csv", "w", newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(author_results[0].keys()))
        writer.writeheader()
        writer.writerows(author_results)

    # Write cross-ref: bots that hit multiple authors
    multi_hit_bots = {bot: authors for bot, authors in cross_ref_hits.items() if len(authors) > 1}
    with open("network_crossref_bots.csv", "w", newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["BotUsername", "HitCount", "AuthorsTargeted"])
        for bot, hit_authors in sorted(multi_hit_bots.items(), key=lambda x: -len(x[1])):
            writer.writerow([bot, len(hit_authors), "; ".join(hit_authors)])

    # Tag frequency analysis
    all_tags = []
    for a in author_results:
        all_tags.extend(a["TopTags"].split(", "))
    tag_counts = Counter(t for t in all_tags if t)

    print("\n\n📊 Network Audit Summary")
    print("-" * 40)
    print(f"Authors audited          : {len(author_results)}")
    print(f"Known bots appearing in  ")
    print(f"  multiple authors' followers: {len(multi_hit_bots)}")
    print(f"\n🏷️  Top tags among targeted authors:")
    for tag, count in tag_counts.most_common(10):
        print(f"  #{tag}: {count}")
    print(f"\n✅ Reports written:")
    print(f"   network_author_report.csv")
    print(f"   network_crossref_bots.csv")

if __name__ == "__main__":
    run_network_audit()
