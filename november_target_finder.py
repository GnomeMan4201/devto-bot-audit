#!/usr/bin/env python3
"""
november_target_finder.py — Bot Network November 2025 Target Identification
badBANANA Research Collective / GnomeMan4201

HYPOTHESIS:
    The November 2025 bot wave (IDs ~3,600,000–3,700,000, created Nov 14-19)
    was deployed against a DEV.to target before GnomeMan4201. User IDs are
    sequential — accounts in that range were created ~Nov 2025. The operator
    used them in November, meaning they followed someone then.

    We find the November target by:
      1. Taking our flagged bot accounts with Nov 2025 creation dates
      2. Querying DEV.to API for their following lists
      3. Finding common followees (excluding ourselves) — that's the target
      4. Corroborating via follower spike analysis on candidate authors
      5. Cross-referencing with known security/AI authors (most likely targets)

    S3 ID SEQUENCING (secondary signal):
      Avatar URLs contain S3 numeric IDs. Accounts from the same creation
      batch cluster together. We can map ID→username and infer creation order
      to anchor the November wave precisely.

USAGE:
    python november_target_finder.py \
        --csv ./devto_bot_audit_full.csv \
        --flagged ./flagged_usernames.txt \
        --output ./november_target_report.txt \
        [--api-key $DEVTO_API_KEY] \
        [--sample N]   # how many Nov bots to query following-lists for (default 50)
        [--verbose]

RATE LIMITS:
    DEV.to public API: ~10 req/sec, no hard published limit.
    We use 0.2s delay between calls to stay well clear.

DEPENDENCIES: requests, pandas (standard in venv)
"""

import argparse
import csv
import json
import os
import re
import urllib.parse
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

import requests

# ── Config ────────────────────────────────────────────────────────────────────

DEVTO_API_BASE = "https://dev.to/api"
REQUEST_DELAY  = 0.25   # seconds between API calls
TIMEOUT        = 15

# Months we're interested in (creation dates)
NOVEMBER_MONTHS = {"2025-11", "November 2025"}

# S3 ID ranges extracted from your recon (avatar URL numeric IDs)
# johnmaveric=3611242 ... anolting=3940515 → November wave ~3600000-3700000
NOV_S3_ID_MIN = 3_550_000
NOV_S3_ID_MAX = 3_750_000

# Known anchor accounts (from your S3 ID extraction)
KNOWN_S3_ANCHORS = {
    3611242: "johnmaveric",
    3701866: "andreasm",
    3732432: "vijayganesh1610",
    3928832: "mousefilter",
    3940515: "anolting",
}

# ── DEV.to API Client ─────────────────────────────────────────────────────────

class DevToClient:
    def __init__(self, api_key: Optional[str] = None):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.forem.api-v1+json",
            "User-Agent": "badBANANA-BotAudit/1.0 (security research)",
        })
        if api_key:
            self.session.headers["api-key"] = api_key
        self._call_count = 0

    def _get(self, endpoint: str, params: dict = None) -> Optional[dict | list]:
        url = f"{DEVTO_API_BASE}/{endpoint.lstrip('/')}"
        try:
            resp = self.session.get(url, params=params, timeout=TIMEOUT)
            self._call_count += 1
            time.sleep(REQUEST_DELAY)
            if resp.status_code == 429:
                print(f"    [rate-limit] backing off 10s...", flush=True)
                time.sleep(10)
                resp = self.session.get(url, params=params, timeout=TIMEOUT)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            print(f"    [!] API error {endpoint}: {e}", file=sys.stderr)
            return None

    def get_user(self, username: str) -> Optional[dict]:
        return self._get(f"/users/by_username", {"url": username})

    def get_user_by_id(self, user_id: int) -> Optional[dict]:
        return self._get(f"/users/{user_id}")

    def get_followers(self, page: int = 1, per_page: int = 1000) -> Optional[list]:
        """Get YOUR followers (authenticated)."""
        return self._get("/followers/users", {"page": page, "per_page": per_page})

    def get_following(self, username: str) -> Optional[list]:
        """
        DEV.to does NOT expose a public /following endpoint.
        Workaround: scrape profile page for 'following' count signal,
        OR use the undocumented /{username}/following_tags and user
        activity heuristics.

        Real approach: check if bot accounts appear in the followers
        list of candidate target accounts — that's the reliable path.
        """
        # The API doesn't give us following lists directly.
        # We return None to trigger the fallback strategy.
        return None

    def get_user_followers(self, user_id: int, page: int = 1) -> Optional[list]:
        """
        Undocumented but works: /api/users/{id}/followers
        Returns list of follower user objects.
        """
        return self._get(f"/users/{user_id}/followers", {"page": page, "per_page": 100})

    def search_users(self, query: str, page: int = 1) -> Optional[list]:
        """Search DEV.to users by username fragment."""
        return self._get("/search/users", {"q": query, "page": page})

    def get_articles_by_user(self, username: str, page: int = 1) -> Optional[list]:
        return self._get("/articles", {"username": username, "page": page, "per_page": 30})

    def get_top_articles(self, tag: str = None, top: int = 365) -> Optional[list]:
        """Get top articles from the past N days."""
        params = {"top": top, "per_page": 30}
        if tag:
            params["tag"] = tag
        return self._get("/articles", params)


# ── CSV Parsing ───────────────────────────────────────────────────────────────

def load_audit_csv(csv_path: Path) -> list[dict]:
    """Load devto_bot_audit_full.csv — all 1,409 followers with scores."""
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    print(f"[*] Loaded {len(rows)} rows from audit CSV")
    return rows


def load_flagged(flagged_path: Path) -> set[str]:
    """Load flagged_usernames.txt."""
    with open(flagged_path) as f:
        return {line.strip() for line in f if line.strip()}


def filter_november_bots(
    rows: list[dict],
    flagged: set[str],
) -> list[dict]:
    """
    Filter to bots created in November 2025.
    Handles various date column names your audit scripts might use.
    """
    nov_bots = []
    date_fields = ["JoinedDate", "created_at", "joined_at", "account_created", "creation_date"]

    for row in rows:
        username = row.get("Username", row.get("username", row.get("user", ""))).strip().lower()
        if username not in flagged:
            continue

        # Find whichever date field exists
        created = None
        for f in date_fields:
            if row.get(f):
                created = row[f].strip()
                break

        if not created:
            continue

        # Match November 2025
        if created.startswith("Nov"):
            # Extract S3 ID from avatar URL if present
            s3_id = None
            avatar_url = row.get("AvatarURL", row.get("profile_image", row.get("avatar_url", row.get("avatar", ""))))
            if avatar_url:
                avatar_decoded = urllib.parse.unquote(avatar_url)
                m = re.search(r'/profile_image/(\d+)/', avatar_decoded)
                if m:
                    s3_id = int(m.group(1))

            nov_bots.append({
                "username": username,
                "created_at": created,
                "s3_id": s3_id,
                "avatar_url": avatar_url,
                "bot_score": row.get("bot_score", row.get("score", "?")),
            })

    return nov_bots


def extract_s3_id_from_url(url: str) -> Optional[int]:
    """Extract numeric S3 user ID from DEV.to avatar URL.
    Handles media2.dev.to proxy URLs — S3 path is URL-encoded inside.
    """
    if not url:
        return None
    import urllib.parse
    decoded = urllib.parse.unquote(url)
    m = re.search(r'/profile_image/(\d+)/', decoded)
    if m:
        return int(m.group(1))
    return None


# ── Strategy 1: Following-List Cross-Reference ────────────────────────────────

def find_common_followees_via_followers_api(
    client: DevToClient,
    nov_bots: list[dict],
    candidate_usernames: list[str],
    verbose: bool = False,
) -> Counter:
    """
    For each candidate author, check if our known November bots
    appear in their follower list. Count hits per candidate.

    This is the REVERSE of what we want (we can't get who bots follow),
    but DEV.to exposes follower lists for users. We iterate candidates
    and check for bot presence.
    """
    bot_usernames = {b["username"] for b in nov_bots}
    overlap_counter = Counter()

    print(f"\n[*] Checking {len(candidate_usernames)} candidate authors for bot overlap...")
    print(f"    Bot pool: {len(bot_usernames)} November accounts")

    for username in candidate_usernames:
        user_data = client.get_user(username)
        if not user_data:
            if verbose:
                print(f"    {username}: not found")
            continue

        user_id = user_data.get("id")
        follower_count = user_data.get("followers_count", 0)

        if verbose:
            print(f"    {username} (id={user_id}, followers={follower_count}): scanning...", end=" ", flush=True)

        # Paginate through their followers looking for our bots
        page = 1
        found = 0
        found_names = []
        max_pages = min(20, (follower_count // 100) + 1)  # don't over-paginate

        while page <= max_pages:
            followers = client.get_user_followers(user_id, page=page)
            if not followers:
                break

            for f in followers:
                fname = f.get("username", "")
                if fname in bot_usernames:
                    found += 1
                    found_names.append(fname)

            if len(followers) < 100:
                break
            page += 1

        if found > 0:
            overlap_counter[username] = found
            if verbose:
                print(f"{found} bot overlap — CANDIDATE")
            else:
                print(f"    [HIT] {username}: {found} November bots in followers")
        else:
            if verbose:
                print(f"0 overlap")

    return overlap_counter


# ── Strategy 2: S3 ID Sequencing ─────────────────────────────────────────────

def analyze_s3_sequences(nov_bots: list[dict]) -> dict:
    """
    Sort November bots by S3 ID to reconstruct creation order.
    S3 IDs are monotonically increasing → lower ID = created earlier.
    Find gaps that suggest separate batch deployments.
    """
    bots_with_ids = [b for b in nov_bots if b.get("s3_id")]
    bots_with_ids.sort(key=lambda x: x["s3_id"])

    if not bots_with_ids:
        return {"error": "No S3 IDs extracted from November bots"}

    ids = [b["s3_id"] for b in bots_with_ids]
    min_id, max_id = ids[0], ids[-1]
    span = max_id - min_id

    # Detect batch gaps (large jumps in sequence)
    gaps = []
    for i in range(1, len(ids)):
        delta = ids[i] - ids[i-1]
        if delta > 5000:  # threshold: 5000 ID gap = separate batch
            gaps.append({
                "after_username": bots_with_ids[i-1]["username"],
                "before_username": bots_with_ids[i]["username"],
                "gap_size": delta,
                "id_before": ids[i-1],
                "id_after": ids[i],
            })

    # Known anchors in range
    anchors_in_range = {
        uid: uname for uid, uname in KNOWN_S3_ANCHORS.items()
        if min_id <= uid <= max_id
    }

    return {
        "total_with_s3_ids": len(bots_with_ids),
        "s3_id_range": (min_id, max_id),
        "span": span,
        "estimated_real_accounts_in_range": span,  # S3 IDs include non-bot accounts
        "batch_gaps": gaps,
        "anchor_accounts_in_range": anchors_in_range,
        "first_bot": bots_with_ids[0],
        "last_bot": bots_with_ids[-1],
        "sample_sequence": [(b["username"], b["s3_id"]) for b in bots_with_ids[:10]],
    }


# ── Strategy 3: Candidate Author Discovery ───────────────────────────────────

def discover_candidate_authors(client: DevToClient) -> list[str]:
    """
    Find DEV.to security/AI authors who were active and popular
    around November 2025. These are the most likely bot targets.

    Approach:
      - Search top articles in security, AI, cybersecurity tags
      - Look for authors with high follower counts (bot services target visibility)
      - Cross-ref with anyone who published about bots/GitHub/security in that window
    """
    tags = ["security", "cybersecurity", "hacking", "ai", "machinelearning", "botnet"]
    authors = set()

    print("\n[*] Discovering candidate authors via top articles...")
    for tag in tags:
        articles = client.get_top_articles(tag=tag, top=400)
        if not articles:
            continue
        for article in articles:
            user = article.get("user", {})
            uname = user.get("username", "")
            if uname:
                authors.add(uname)
        print(f"    tag={tag}: {len(articles)} articles → running author pool: {len(authors)}")

    # Also check known security authors who are likely targets
    known_security_authors = [
        # Add usernames of prominent DEV.to security authors here as you find them
        # These are examples — populate from your network_author_report.csv
    ]
    authors.update(known_security_authors)

    return list(authors)


def load_network_authors(csv_path: Path) -> list[str]:
    """Load authors from your existing network_author_report.csv."""
    if not csv_path.exists():
        return []
    authors = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            username = row.get("username", row.get("author", "")).strip()
            if username:
                authors.append(username)
    print(f"[*] Loaded {len(authors)} authors from network report")
    return authors


# ── Report ────────────────────────────────────────────────────────────────────

def write_november_report(
    nov_bots: list[dict],
    s3_analysis: dict,
    overlap_results: Counter,
    output_path: Path,
) -> None:
    import datetime

    lines = []
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    lines.append("=" * 78)
    lines.append("NOVEMBER 2025 TARGET IDENTIFICATION REPORT")
    lines.append(f"badBANANA Research Collective / {ts}")
    lines.append("=" * 78)
    lines.append("")
    lines.append(f"November bot pool: {len(nov_bots)} accounts")
    lines.append("")

    # S3 Analysis
    lines.append("── S3 USER ID SEQUENCE ANALYSIS ──────────────────────────────────────────────")
    if "error" in s3_analysis:
        lines.append(f"  {s3_analysis['error']}")
    else:
        r = s3_analysis
        lines.append(f"  Accounts with extractable S3 IDs: {r['total_with_s3_ids']}")
        lines.append(f"  S3 ID range: {r['s3_id_range'][0]:,} → {r['s3_id_range'][1]:,}")
        lines.append(f"  Span: {r['span']:,} (accounts created between these IDs, including non-bots)")
        lines.append(f"  First bot in sequence : {r['first_bot']['username']}  (ID {r['first_bot']['s3_id']:,})")
        lines.append(f"  Last bot in sequence  : {r['last_bot']['username']}  (ID {r['last_bot']['s3_id']:,})")
        lines.append("")

        if r["anchor_accounts_in_range"]:
            lines.append("  ANCHOR ACCOUNTS IN RANGE (known S3 IDs):")
            for uid, uname in sorted(r["anchor_accounts_in_range"].items()):
                lines.append(f"    {uid:>10,}  →  @{uname}")
        lines.append("")

        if r["batch_gaps"]:
            lines.append(f"  BATCH GAPS DETECTED ({len(r['batch_gaps'])}):")
            for gap in r["batch_gaps"]:
                lines.append(
                    f"    Gap of {gap['gap_size']:,} IDs between "
                    f"@{gap['after_username']} (ID {gap['id_before']:,}) "
                    f"and @{gap['before_username']} (ID {gap['id_after']:,})"
                )
            lines.append("  → Gaps suggest multiple batch purchases from operator's account inventory")
        else:
            lines.append("  No significant batch gaps — accounts created in continuous sequence")

        lines.append("")
        lines.append("  SEQUENCE SAMPLE (first 10 by S3 ID order):")
        for uname, sid in r["sample_sequence"]:
            anchor_note = f" ← KNOWN ANCHOR" if sid in KNOWN_S3_ANCHORS else ""
            lines.append(f"    {sid:>10,}  @{uname}{anchor_note}")

    lines.append("")

    # Overlap results
    lines.append("── NOVEMBER TARGET IDENTIFICATION (follower overlap) ──────────────────────────")
    if not overlap_results:
        lines.append("  No overlap queries run (no --sample or no candidates found)")
        lines.append("  Run with --sample 50 --verbose to execute")
    else:
        lines.append(f"  Candidates with bot overlap ({len(overlap_results)} found):")
        lines.append("")
        for username, count in overlap_results.most_common():
            confidence = "HIGH" if count >= 10 else "MEDIUM" if count >= 3 else "LOW"
            lines.append(f"  [{confidence}] @{username}  —  {count} November bots in their followers")
        lines.append("")
        if overlap_results:
            top_target = overlap_results.most_common(1)[0]
            lines.append(f"  ★ PRIMARY NOVEMBER TARGET: @{top_target[0]}  ({top_target[1]} bot overlap)")

    lines.append("")
    lines.append("── NEXT STEPS ─────────────────────────────────────────────────────────────────")
    lines.append("""
  1. VERIFY PRIMARY TARGET:
     - Check their follower count history (Social Blade alternative for DEV.to:
       inspect the Wayback Machine for their /username page from Nov 2025)
     - Look for a sudden follower spike in their Nov 2025 DEV.to activity feed
     - Direct contact: reach out privately — they may not know they were targeted

  2. S3 ID PIVOTING:
     - The accounts just BELOW your lowest November bot S3 ID are real DEV.to
       accounts created around the same time. Enumerate them:
         GET https://dev.to/api/users/{id} for ID in range(MIN_ID-100, MIN_ID)
       These are legitimate users who can corroborate the account creation timeline.

  3. CROSS-PLATFORM CHECK:
     - Did the November target also get GitHub bot followers? (your GitHub data
       only covers your own account — check if the November target shows up in
       any of the bot accounts' bio/location data)

  4. TIMELINE RECONSTRUCTION:
     - November wave creation: Nov 14-19, 2025
     - Deployment: November 2025 (followed target then)
     - Redeployment: May 2026 (followed GnomeMan4201 after botnet article)
     - This confirms: operator maintains a REUSABLE INVENTORY deployed on demand
     - The same 339 accounts sat dormant for ~6 months then were reactivated

  5. CONTACT DEV.TO:
     - If confirmed: the November target is also a victim
     - Include November target data in your disclosure update to DEV.to
     - Their follower count spike would add a second confirmed deployment event
""")

    output_path.write_text("\n".join(lines))
    print(f"[+] Report written to {output_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Find the November 2025 bot deployment target")
    parser.add_argument("--csv",      default="./devto_bot_audit_full.csv",  type=Path)
    parser.add_argument("--flagged",  default="./flagged_usernames.txt",     type=Path)
    parser.add_argument("--network",  default="./network_author_report.csv", type=Path)
    parser.add_argument("--output",   default="./november_target_report.txt",type=Path)
    parser.add_argument("--api-key",  default=os.environ.get("DEVTO_API_KEY", ""))
    parser.add_argument("--sample",   default=50, type=int,
                        help="How many November bots to use for overlap queries")
    parser.add_argument("--no-query", action="store_true",
                        help="Skip API queries — S3 analysis only")
    parser.add_argument("--verbose",  action="store_true")
    args = parser.parse_args()

    for p, name in [(args.csv, "csv"), (args.flagged, "flagged")]:
        if not p.exists():
            print(f"[!] {name} not found: {p}", file=sys.stderr)
            sys.exit(1)

    client = DevToClient(api_key=args.api_key)
    if not args.api_key:
        print("[!] No DEVTO_API_KEY — some endpoints may be rate-limited faster")

    # Load data
    rows = load_audit_csv(args.csv)
    flagged = load_flagged(args.flagged)

    # Filter November bots
    nov_bots = filter_november_bots(rows, flagged)
    print(f"[*] November 2025 bots identified: {len(nov_bots)}")

    if not nov_bots:
        print("[!] No November bots found. Check date column names in your CSV.")
        print("    Expected column names: created_at, joined_at, account_created, creation_date")
        print("    First row of CSV for debugging:")
        if rows:
            print(f"    Columns: {list(rows[0].keys())}")
            print(f"    Sample: {dict(list(rows[0].items())[:5])}")
        sys.exit(1)

    # S3 analysis (offline — no API needed)
    print(f"\n[*] Running S3 ID sequence analysis...")
    s3_analysis = analyze_s3_sequences(nov_bots)

    if args.verbose and "error" not in s3_analysis:
        print(f"    S3 range: {s3_analysis['s3_id_range']}")
        print(f"    Batch gaps: {len(s3_analysis['batch_gaps'])}")

    # Candidate author discovery + overlap queries
    overlap_results = Counter()

    if not args.no_query:
        # Load from existing network report first (saves API calls)
        candidates = load_network_authors(args.network)

        if not candidates:
            print("[*] No network report found — discovering authors via API...")
            candidates = discover_candidate_authors(client)

        print(f"[*] Author candidate pool: {len(candidates)}")

        if candidates:
            overlap_results = find_common_followees_via_followers_api(
                client,
                nov_bots[:args.sample],
                candidates,
                verbose=args.verbose,
            )
            print(f"\n[*] API calls made: {client._call_count}")
            print(f"[*] Candidates with bot overlap: {len(overlap_results)}")
    else:
        print("[*] Skipping API queries (--no-query set)")

    # Write report
    write_november_report(nov_bots, s3_analysis, overlap_results, args.output)

    # Print summary
    if overlap_results:
        print("\n[+] TOP NOVEMBER TARGETS:")
        for username, count in overlap_results.most_common(5):
            print(f"    @{username}: {count} November bot overlap")
    else:
        print("\n[*] Run without --no-query and with --api-key to perform overlap analysis")


if __name__ == "__main__":
    main()
