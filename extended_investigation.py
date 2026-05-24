#!/usr/bin/env python3
"""
extended_investigation.py — Four-thread parallel investigation
badBANANA Research Collective / GnomeMan4201

THREADS:
  A — upvote.club account pool enumeration
  B — December 2023 campaign target identification  
  C — Username pattern analysis + generator reverse engineering
  D — upvote.club API probe

USAGE:
    python extended_investigation.py \
        --csv ./devto_bot_audit_full.csv \
        --flagged ./flagged_usernames.txt \
        [--api-key $DEVTO_API_KEY] \
        [--threads A,B,C,D]   # default: all
        [--output ./extended_report.txt]
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

import requests

# ── Shared utilities ──────────────────────────────────────────────────────────

def load_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def load_flagged(path: Path) -> set[str]:
    with open(path) as f:
        return {l.strip().lower() for l in f if l.strip()}

def devto_get(session, endpoint, params=None):
    try:
        r = session.get(
            f"https://dev.to/api/{endpoint.lstrip('/')}",
            params=params, timeout=15
        )
        time.sleep(0.25)
        if r.status_code == 429:
            print("    [rate-limit] backing off 10s...")
            time.sleep(10)
            r = session.get(f"https://dev.to/api/{endpoint.lstrip('/')}", params=params, timeout=15)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# THREAD D — upvote.club API probe
# ══════════════════════════════════════════════════════════════════════════════

def thread_d_api_probe() -> dict:
    """
    Probe upvote.club API endpoints without auth.
    Goals:
      - Discover endpoint structure
      - Find any public task/order data
      - Identify platform codes (what ID does DEV.to use internally?)
      - Find rate limit / pagination signals
    """
    print("\n" + "═"*60)
    print("THREAD D — upvote.club API probe")
    print("═"*60)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:124.0)",
        "Accept": "application/json",
    })

    base = "https://upvote.club"
    findings = {}

    # Common API endpoint patterns to probe
    endpoints = [
        "/api",
        "/api/v1",
        "/api/platforms",
        "/api/networks",
        "/api/tasks",
        "/api/actions",
        "/api/stats",
        "/api/devto",
        "/api/dev.to",
        "/api/public/stats",
        "/api/public/platforms",
        "/api/public/tasks",
        "/_next/data",
        "/api/health",
        "/api/status",
    ]

    print("\n[*] Probing endpoints...")
    for ep in endpoints:
        try:
            r = session.get(f"{base}{ep}", timeout=8)
            ct = r.headers.get("content-type", "")
            size = len(r.content)
            status = r.status_code

            if status == 200 and size > 50:
                findings[ep] = {
                    "status": status,
                    "content_type": ct,
                    "size": size,
                    "preview": r.text[:300],
                }
                print(f"  [HIT {status}] {ep} — {size} bytes — {ct[:40]}")
                print(f"    Preview: {r.text[:150]}")
            else:
                print(f"  [{status}] {ep} — {size} bytes")
            time.sleep(0.3)
        except Exception as e:
            print(f"  [ERR] {ep}: {e}")

    # Try Next.js data endpoints (they use Next.js)
    print("\n[*] Probing Next.js build manifest...")
    try:
        r = session.get(f"{base}/_next/static/chunks/pages/index.js", timeout=8)
        if r.status_code == 200:
            # Extract API routes from JS bundle
            api_routes = re.findall(r'["\']/(api/[^"\']+)["\']', r.text)
            if api_routes:
                print(f"  Found {len(api_routes)} API routes in bundle:")
                for route in sorted(set(api_routes))[:20]:
                    print(f"    /{route}")
                findings["bundle_routes"] = list(set(api_routes))
    except:
        pass

    # Check robots.txt for hidden paths
    print("\n[*] Checking robots.txt...")
    try:
        r = session.get(f"{base}/robots.txt", timeout=8)
        if r.status_code == 200:
            print(f"  robots.txt:\n{r.text[:500]}")
            findings["robots"] = r.text
    except:
        pass

    # Check sitemap
    print("\n[*] Checking sitemap...")
    try:
        r = session.get(f"{base}/sitemap.xml", timeout=8)
        if r.status_code == 200:
            urls = re.findall(r'<loc>([^<]+)</loc>', r.text)
            print(f"  {len(urls)} URLs in sitemap")
            api_urls = [u for u in urls if '/api/' in u]
            if api_urls:
                print(f"  API URLs in sitemap:")
                for u in api_urls[:10]:
                    print(f"    {u}")
            findings["sitemap_urls"] = urls
    except:
        pass

    return findings


# ══════════════════════════════════════════════════════════════════════════════
# THREAD A — upvote.club account pool enumeration
# ══════════════════════════════════════════════════════════════════════════════

def thread_a_account_pool(flagged: set[str], rows: list[dict]) -> dict:
    """
    Cross-reference flagged bot accounts against upvote.club's visible community.
    
    Approach:
      1. Check if any flagged usernames appear on upvote.club directly
      2. Look for upvote.club user profiles / leaderboards
      3. Check if bot accounts have upvote.club in their DEV.to bio/links
      4. Look for shared identifiers between upvote.club and DEV.to accounts
    """
    print("\n" + "═"*60)
    print("THREAD A — upvote.club account pool enumeration")
    print("═"*60)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:124.0)",
    })

    findings = {
        "upvoteclub_profile_hits": [],
        "bio_mentions": [],
        "leaderboard_data": None,
    }

    # Check for upvote.club mentions in bot account bios
    print("\n[*] Scanning bot bios for upvote.club mentions...")
    bio_field = "Bio"
    for r in rows:
        username = r.get("Username", "").lower()
        if username not in flagged:
            continue
        bio = r.get(bio_field, "") or ""
        if "upvote" in bio.lower() or "upvote.club" in bio.lower():
            findings["bio_mentions"].append({
                "username": username,
                "bio": bio,
            })
            print(f"  [BIO HIT] @{username}: {bio[:100]}")

    if not findings["bio_mentions"]:
        print("  No upvote.club mentions in bot bios")

    # Try upvote.club public leaderboard / user list
    print("\n[*] Probing upvote.club for public user data...")
    public_endpoints = [
        "/leaderboard",
        "/community",
        "/members",
        "/users",
        "/top",
        "/devto/leaderboard",
        "/devto/top",
    ]
    for ep in public_endpoints:
        try:
            r = session.get(f"https://upvote.club{ep}", timeout=8)
            if r.status_code == 200 and len(r.content) > 500:
                # Look for DEV.to usernames in the response
                usernames = re.findall(r'dev\.to/([a-z0-9_\-]{3,})', r.text, re.I)
                if usernames:
                    overlaps = [u for u in usernames if u.lower() in flagged]
                    print(f"  {ep}: {len(usernames)} DEV.to usernames found, {len(overlaps)} overlap with flagged bots")
                    if overlaps:
                        findings["upvoteclub_profile_hits"].extend(overlaps)
                        for u in overlaps[:5]:
                            print(f"    OVERLAP: @{u}")
                else:
                    print(f"  {ep}: HTTP 200, no DEV.to usernames found")
            time.sleep(0.3)
        except:
            pass

    # Check if any flagged accounts have upvote.club profiles
    # upvote.club profile URLs: upvote.club/u/{username} or upvote.club/profile/{username}
    print("\n[*] Checking upvote.club profile existence for sample of flagged accounts...")
    sample = list(flagged)[:30]
    profile_hits = []
    for username in sample:
        for profile_pattern in [f"/u/{username}", f"/profile/{username}", f"/@{username}"]:
            try:
                r = session.get(f"https://upvote.club{profile_pattern}", timeout=5)
                if r.status_code == 200 and len(r.content) > 1000:
                    profile_hits.append({
                        "username": username,
                        "url": f"https://upvote.club{profile_pattern}",
                    })
                    print(f"  [PROFILE HIT] @{username}: upvote.club{profile_pattern}")
                time.sleep(0.1)
            except:
                pass

    findings["profile_hits"] = profile_hits
    if not profile_hits:
        print("  No upvote.club profiles found for sampled flagged accounts")

    return findings


# ══════════════════════════════════════════════════════════════════════════════
# THREAD B — December 2023 campaign target identification
# ══════════════════════════════════════════════════════════════════════════════

def thread_b_prior_campaign(session, flagged: set[str]) -> dict:
    """
    The same bear avatar appeared on DEV.to as far back as December 2023.
    Find who was targeted in that earlier campaign.
    
    Approach:
      1. Find the Dec 2023 DEV.to accounts using the bear avatar (via Lens results)
      2. Check their follower lists for bot overlap
      3. Look for other security/AI authors who got suspicious follower spikes in 2023
      4. Wayback Machine CDX API to check archived follower counts
    """
    print("\n" + "═"*60)
    print("THREAD B — December 2023 campaign target identification")
    print("═"*60)

    findings = {
        "dec2023_accounts": [],
        "wayback_spikes": [],
        "candidate_targets": [],
    }

    # Accounts we know used the bear avatar in Dec 2023 (from Google Lens results)
    # tontonastro — Dec 14, 2023
    # Prem Kumar Chedella — Aug 4, 2024
    # Nahuel Leiva — Feb 29, 2024
    # BoyQuang — Jun 22, 2025
    # Prabhat Kumar — Dec 24, 2024
    known_bear_users = [
        ("tontonastro", "Dec 14, 2023"),
        ("premskumar", "Aug 4, 2024"),     # Prem Kumar Chedella
        ("nahuelleiva", "Feb 29, 2024"),   # Nahuel Leiva
        ("boyquang", "Jun 22, 2025"),
        ("prabhat", "Dec 24, 2024"),       # Prabhat Kumar
    ]

    print("\n[*] Checking known bear-avatar accounts from Google Lens results...")
    for username, date in known_bear_users:
        user = devto_get(session, f"/users/by_username", {"url": username})
        if user:
            findings["dec2023_accounts"].append({
                "username": username,
                "lens_date": date,
                "followers": user.get("followers_count", 0),
                "articles": user.get("public_articles_count", 0),
                "joined": user.get("joined_at", "")[:10],
            })
            print(f"  @{username}: followers={user.get('followers_count',0)} "
                  f"articles={user.get('public_articles_count',0)} "
                  f"joined={user.get('joined_at','')[:10]}")
        else:
            print(f"  @{username}: not found")

    # Check Wayback Machine for follower count history on Dec 2023 accounts
    print("\n[*] Checking Wayback Machine CDX for archived DEV.to profile snapshots...")
    cdx_base = "http://web.archive.org/cdx/search/cdx"

    for account in findings["dec2023_accounts"]:
        username = account["username"]
        try:
            r = requests.get(cdx_base, params={
                "url": f"dev.to/{username}",
                "output": "json",
                "fl": "timestamp,statuscode",
                "from": "20231101",
                "to": "20240301",
                "limit": 20,
            }, timeout=15)
            if r.status_code == 200:
                data = r.json()
                if len(data) > 1:  # first row is header
                    snapshots = data[1:]
                    print(f"  @{username}: {len(snapshots)} Wayback snapshots (Nov 2023 - Mar 2024)")
                    account["wayback_snapshots"] = snapshots[:5]
                else:
                    print(f"  @{username}: no Wayback snapshots in range")
            time.sleep(0.5)
        except Exception as e:
            print(f"  @{username}: Wayback error: {e}")

    # Search for security authors who were active Dec 2023 with potential spikes
    print("\n[*] Finding active security authors from Dec 2023...")
    try:
        articles = devto_get(session, "/articles", {
            "tag": "security",
            "top": 365,
            "per_page": 30,
        })
        if articles:
            for a in articles[:20]:
                user = a.get("user", {})
                uname = user.get("username", "")
                if uname:
                    findings["candidate_targets"].append({
                        "username": uname,
                        "article": a.get("title", "")[:60],
                        "published": a.get("published_at", "")[:10],
                    })
            print(f"  Found {len(findings['candidate_targets'])} security authors")
    except:
        pass

    return findings


# ══════════════════════════════════════════════════════════════════════════════
# THREAD C — Username pattern analysis
# ══════════════════════════════════════════════════════════════════════════════

def thread_c_username_patterns(rows: list[dict], flagged: set[str]) -> dict:
    """
    Reverse engineer the username generation algorithm.
    
    Observed patterns:
      - firstname_lastname_[hex8]     e.g. john_smith_a1b2c3d4
      - firstname_lastname_[hex12+]   e.g. dana_ivanov_cdb6183a6fe6f
      - __[hex10]                     e.g. __2cbc04058
      - _[hex20]                      e.g. _07539bcc4c62f7fb654f
      - simple handles                e.g. mousefilter, johnmaveric
    
    Goals:
      1. Classify all 899 flagged usernames into pattern types
      2. Identify the hash function (MD5? SHA1? random hex?)
      3. Find the seed/input — is the hex derived from the name or random?
      4. Predict undeployed accounts: if pattern is deterministic,
         we can generate candidate usernames and check if they exist
      5. Find same-pattern accounts on GitHub/other platforms
    """
    print("\n" + "═"*60)
    print("THREAD C — Username pattern analysis")
    print("═"*60)

    findings = {
        "pattern_distribution": {},
        "hex_analysis": {},
        "name_components": {},
        "predicted_accounts": [],
        "cross_platform_candidates": [],
    }

    # Pattern classifiers
    patterns = {
        "name_hex_long":   re.compile(r'^[a-z]+_[a-z]+_[a-f0-9]{10,}$'),
        "name_hex_short":  re.compile(r'^[a-z]+_[a-z]+_[a-f0-9]{6,9}$'),
        "name_num_hex":    re.compile(r'^[a-z]+[0-9]+_[a-f0-9]{6,}$'),
        "double_under":    re.compile(r'^__[a-f0-9]{8,}$'),
        "single_under":    re.compile(r'^_[a-f0-9]{16,}$'),
        "triple_part":     re.compile(r'^[a-z]+_[a-z]+_[a-z0-9]+$'),
        "simple":          re.compile(r'^[a-z][a-z0-9]{3,15}$'),
        "other":           re.compile(r'.+'),
    }

    pattern_counts = defaultdict(list)
    hex_lengths = Counter()
    first_names = Counter()
    last_names = Counter()
    hex_samples = defaultdict(list)

    flagged_rows = [r for r in rows if r.get("Username","").lower() in flagged]
    print(f"\n[*] Analyzing {len(flagged_rows)} flagged usernames...")

    for row in flagged_rows:
        username = row.get("Username", "").lower()

        # Classify
        matched = False
        for pname, pattern in patterns.items():
            if pattern.match(username):
                pattern_counts[pname].append(username)
                matched = True
                break

        # Extract hex component
        hex_match = re.search(r'_([a-f0-9]{6,})$', username)
        if hex_match:
            hx = hex_match.group(1)
            hex_lengths[len(hx)] += 1
            hex_samples[len(hx)].append((username, hx))

        # Extract name components
        parts = username.split('_')
        if len(parts) >= 2:
            # Remove trailing hex
            name_parts = [p for p in parts if not re.match(r'^[a-f0-9]{6,}$', p)]
            if name_parts:
                first_names[name_parts[0]] += 1
            if len(name_parts) >= 2:
                last_names[name_parts[1]] += 1

    # Report pattern distribution
    print("\n[*] Pattern distribution:")
    for pname, usernames in sorted(pattern_counts.items(), key=lambda x: -len(x[1])):
        pct = len(usernames)/len(flagged_rows)*100
        print(f"  {pname:20s}: {len(usernames):4d} ({pct:.1f}%)")
        findings["pattern_distribution"][pname] = len(usernames)

    # Analyze hex component lengths
    print("\n[*] Hex suffix length distribution:")
    for length, count in sorted(hex_lengths.items()):
        print(f"  {length:3d} chars: {count:4d} accounts")
        # Show sample
        samples = hex_samples[length][:2]
        for uname, hx in samples:
            print(f"    e.g. {uname} → hex={hx}")
    findings["hex_analysis"] = dict(hex_lengths)

    # Test if hex is derived from name components
    print("\n[*] Testing if hex is derived from username components...")
    import hashlib

    derivation_hits = 0
    derivation_samples = []

    for row in flagged_rows[:200]:
        username = row.get("Username", "").lower()
        hex_match = re.search(r'_([a-f0-9]{8,})$', username)
        if not hex_match:
            continue
        observed_hex = hex_match.group(1)
        base_name = username[:username.rfind('_')]

        # Test common hash derivations
        candidates = {
            "md5_full":    hashlib.md5(base_name.encode()).hexdigest(),
            "md5_no_under":hashlib.md5(base_name.replace('_','').encode()).hexdigest(),
            "sha1_full":   hashlib.sha1(base_name.encode()).hexdigest(),
            "sha256_full": hashlib.sha256(base_name.encode()).hexdigest(),
        }

        for method, full_hash in candidates.items():
            # Check if observed hex is a prefix of the computed hash
            if full_hash.startswith(observed_hex):
                derivation_hits += 1
                derivation_samples.append({
                    "username": username,
                    "method": method,
                    "observed": observed_hex,
                    "computed": full_hash[:len(observed_hex)],
                })
                print(f"  [DERIVATION HIT] {username}")
                print(f"    Method: {method}, prefix match: {observed_hex}")
                break

    if derivation_hits == 0:
        print("  No deterministic hash derivation found — hex appears random")
        print("  This suggests: UUIDs, random generation, or platform-assigned IDs")
    else:
        print(f"\n  {derivation_hits} derivation matches found")
    findings["derivation_hits"] = derivation_hits
    findings["derivation_samples"] = derivation_samples

    # Name frequency analysis — are these real names or generated?
    print("\n[*] Most common first name components:")
    for name, count in first_names.most_common(15):
        print(f"  {name:20s}: {count}")

    print("\n[*] Most common last name components:")
    for name, count in last_names.most_common(15):
        print(f"  {name:20s}: {count}")

    findings["name_components"] = {
        "top_first": dict(first_names.most_common(20)),
        "top_last": dict(last_names.most_common(20)),
    }

    # Check for same-pattern usernames on GitHub
    print("\n[*] Checking cross-platform presence — sample on GitHub...")
    gh_session = requests.Session()
    gh_session.headers.update({
        "Authorization": f"token {os.environ.get('GITHUB_TOKEN','')}",
        "Accept": "application/vnd.github+json",
    })

    # Pick 10 hash-style usernames and check GitHub
    hash_style = [u for u in pattern_counts.get("name_hex_long", [])[:10]]
    gh_hits = []
    for username in hash_style:
        try:
            r = gh_session.get(
                f"https://api.github.com/users/{username}",
                timeout=8
            )
            time.sleep(0.3)
            if r.status_code == 200:
                data = r.json()
                gh_hits.append({
                    "username": username,
                    "github_id": data.get("id"),
                    "created": data.get("created_at", "")[:10],
                    "followers": data.get("followers", 0),
                })
                print(f"  [GH HIT] @{username}: id={data.get('id')} created={data.get('created_at','')[:10]}")
        except:
            pass

    findings["github_crossover"] = gh_hits
    if not gh_hits:
        print("  No GitHub crossover found for hash-style username sample")

    return findings


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv",     default="./devto_bot_audit_full.csv",  type=Path)
    parser.add_argument("--flagged", default="./flagged_usernames.txt",     type=Path)
    parser.add_argument("--api-key", default=os.environ.get("DEVTO_API_KEY",""))
    parser.add_argument("--output",  default="./extended_report.txt",       type=Path)
    parser.add_argument("--threads", default="A,B,C,D")
    args = parser.parse_args()

    threads = [t.strip().upper() for t in args.threads.split(",")]

    rows    = load_csv(args.csv)
    flagged = load_flagged(args.flagged)
    print(f"[*] Loaded {len(rows)} rows, {len(flagged)} flagged accounts")

    devto_session = requests.Session()
    devto_session.headers.update({
        "Accept": "application/vnd.forem.api-v1+json",
        "User-Agent": "badBANANA-BotAudit/1.0",
    })
    if args.api_key:
        devto_session.headers["api-key"] = args.api_key

    all_findings = {}

    if "D" in threads:
        all_findings["D"] = thread_d_api_probe()

    if "A" in threads:
        all_findings["A"] = thread_a_account_pool(flagged, rows)

    if "B" in threads:
        all_findings["B"] = thread_b_prior_campaign(devto_session, flagged)

    if "C" in threads:
        all_findings["C"] = thread_c_username_patterns(rows, flagged)

    # Write report
    with open(args.output, "w") as f:
        f.write("EXTENDED INVESTIGATION REPORT\n")
        f.write("badBANANA Research Collective\n")
        f.write("="*60 + "\n\n")
        f.write(json.dumps(all_findings, indent=2, default=str))

    print(f"\n[+] Report written to {args.output}")


if __name__ == "__main__":
    main()
