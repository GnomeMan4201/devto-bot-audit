# I Found 899 Fake Followers on DEV.to. Here's How I Proved It.

*A full technical audit of a coordinated follower inflation network — methodology, findings, and a detection rule simple enough to run in one query.*

---

On May 19, 2026, I published ["Found a Coordinated GitHub Follow Botnet"](https://dev.to/gnomeman4201) — a piece documenting fake follower infrastructure on GitHub. The next day, my DEV.to follower count started climbing.

Fast.

| Date    | New Followers |
|---------|--------------|
| May 19  | 75           |
| May 20  | 288          |
| May 21  | 447          |
| May 22  | 399          |
| May 23  | 311+         |

From ~600 followers to 2,944 as of May 24 — and still climbing. Not from a viral post. Not from a mention by a big account. The deployment timing closely followed publication of the article.

So I audited every single one.

The short version of what I found: every single one of the 1,409 accounts audited was following exactly one person — me. Not two. Not ten. One. Across all 1,409 accounts, across four separate account creation waves spanning six months, the `Following` count was uniformly 1. That's not a heuristic suspicion. That's a graph signature. The rest of this post is the full methodology showing how I got there.

---

## The Setup

```bash
# Environment
# Pop!_OS, Python 3.12, venv
pip install requests Pillow imagehash
export DEVTO_API_KEY='your_key'
```

The full codebase lives at [github.com/GnomeMan4201/devto-bot-audit](https://github.com/GnomeMan4201). Here's the methodology end-to-end.

---

## Step 1: Pull Every Follower

DEV.to's public API exposes your follower list. Paginate through it and store everything:

```python
import requests, time

API_KEY = 'your_devto_api_key'
BASE    = 'https://dev.to/api'

def get_all_followers():
    followers = []
    page = 1
    while True:
        resp = requests.get(
            f'{BASE}/followers/users',
            headers={'api-key': API_KEY},
            params={'page': page, 'per_page': 1000},
        )
        data = resp.json()
        if not data:
            break
        followers.extend(data)
        page += 1
        time.sleep(0.25)
    return followers
```

Then for each follower, fetch their full profile:

```python
def get_profile(username):
    resp = requests.get(
        f'{BASE}/users/by_username',
        headers={'api-key': API_KEY},
        params={'url': username},
        timeout=15,
    )
    return resp.json() if resp.status_code == 200 else None
```

Total audited: **1,409 followers**.

---

## Step 2: Score Each Account

> **Note on username patterns:** S3 ID analysis reveals the operator runs two username generators simultaneously — `firstname_lastname_[random_hex]` (458 accounts) and short simple handles like `mousefilter`, `johnmaveric`, `dronplane` (295 accounts). Both styles cluster in the same S3 ID range (3.4M–3.94M), confirming they were created in the same waves. The mixed naming is consistent with deliberate obfuscation — varying username style reduces pattern detectability across the network.

Seven heuristic signals, each worth 1 point. Score ≥ 3 = flagged:

```python
def score_account(profile):
    score = 0
    reasons = []

    username = profile.get('username', '')
    followers = profile.get('followers_count', 0)
    following = profile.get('following_count', 0)
    articles  = profile.get('public_articles_count', 0)
    bio       = profile.get('summary', '') or ''
    avatar    = profile.get('profile_image', '')

    import re
    if re.search(r'_[a-f0-9]{6,}$', username):
        score += 1; reasons.append('hash_username')
    if not bio.strip():
        score += 1; reasons.append('empty_bio')
    if articles == 0:
        score += 1; reasons.append('zero_articles')
    if avatar.endswith('default_profile_image.png'):
        score += 1; reasons.append('default_avatar')
    if following == 1:
        score += 1; reasons.append('following_one')
    if followers == 0:
        score += 1; reasons.append('zero_followers')

    return score, reasons
```

Results across 1,409 accounts:

| Tier | Count |
|------|-------|
| High-confidence coordinated pattern match (score ≥ 3) | 897 (63.7%) |
| Low-confidence / insufficient evidence (score 1–2) | 510 (36.2%) |
| Clear indicators of sustained organic participation (posting, commenting, multi-account follow graph, or profile customization) | 0 |

Every account audited scored suspicious to some degree. None showed strong indicators of sustained organic participation such as posting history, meaningful social graph expansion, or long-term engagement activity. That said, heuristic scoring indicates a pattern, not a proven fact — some dormant real users can superficially resemble low-effort inauthentic accounts. Two accounts (`@leob`, S3 ID 28,704; `@bah123`, S3 ID 2,707,292) were removed from the flagged list after S3 ID analysis confirmed their creation predates the operator network by years — legitimate dormant accounts swept in by heuristic scoring. What makes this case different is what came next.

---

## Step 3: The Following=1 Discovery

While reviewing the scored data, I checked the `Following` field distribution across all 1,409 accounts:

```python
from collections import Counter
import csv

with open('devto_bot_audit_full.csv') as f:
    rows = list(csv.DictReader(f))

dist = Counter(r.get('Following', '0') for r in rows)
for val, cnt in sorted(dist.items(), key=lambda x: -x[1]):
    print(f'Following={val}: {cnt} accounts')
```

Output:
```
Following=1: 1409 accounts
```

Every single account. All 1,409. Following exactly one person: me.

At that point the investigation stopped being heuristic classification and became graph-pattern detection.

The core invariant: every account in the dataset collapses to a single outgoing follow edge. That is the structural fact from which everything else follows.

A real user who follows only one account is plausible. A thousand accounts — each independently created, each with different usernames, different join dates, different avatars — all following exactly one person, with zero other activity? That's not a coincidence. That's consistent with a follower-inflation deployment pattern rather than organic social behavior — pure follower-count inflation with no engagement attached.

This is a candidate-generation filter — not enforcement logic. Matching accounts should be reviewed, not automatically actioned. With that framing clear:

```sql
-- Triage filter for coordinated follower investigation
-- Produces candidates for review, not a ban list
SELECT username FROM users
WHERE following_count = 1
  AND public_articles_count = 0
  AND comments_count = 0
  AND joined_at >= '2025-11-01'
```

On large platforms, this query will surface dormant newcomers, abandoned accounts, and legitimate lurkers alongside coordinated accounts — expected false positives at scale. The value is not precision enforcement but rapid candidate generation: every account in this network would appear in that result set, making it an extremely effective first pass for a coordinated-follower investigation.

---

## Step 4: Batch Creation Waves

Join dates cluster in ways that organic growth doesn't. I parsed the `JoinedDate` field across the flagged accounts:

```python
from collections import Counter

dates = Counter()
for r in rows:
    d = r.get('JoinedDate', '')
    if d:
        dates[d[:6].strip()] += 1

for date, count in sorted(dates.items(), key=lambda x: -x[1])[:10]:
    print(f'{date}: {count} accounts')
```

Four distinct creation waves:

| Wave | Period | Accounts | Notes |
|------|--------|----------|-------|
| November 2025 | Nov 13–19, 2025 | 218 high-confidence / 339 full cohort | Dormant 187 days before activation |
| January 2026 | Jan 2026 | 17 | Small batch |
| April 2026 | Apr 2026 | 92 | Mid-size batch |
| May 2026 | May 13–19, 2026 | 615 | Active deployment wave |

194 accounts were created on a single day — May 14, 2026. This clustering significantly deviates from typical organic signup dispersion.

---

## Step 5: S3 User ID Sequencing

DEV.to avatar URLs route through a CDN proxy that URL-encodes the original S3 path. Decoding them reveals the underlying user ID — a monotonically increasing integer that reflects account creation order:

```python
import urllib.parse, re

def extract_s3_id(avatar_url):
    """
    Input:  https://media2.dev.to/dynamic/image/.../
            https%3A%2F%2Fdev-to-uploads.s3.amazonaws.com%2F
            uploads%2Fuser%2Fprofile_image%2F3611242%2F...
    Output: 3611242
    """
    decoded = urllib.parse.unquote(avatar_url)
    m = re.search(r'/profile_image/(\d+)/', decoded)
    return int(m.group(1)) if m else None
```

The November 2025 wave extracted to:

```
S3 ID range : 3,610,947 → 3,619,885
Span        : 8,938 IDs across 5 days
Gaps        : 0 significant sequence breaks
```

218 accounts spread across a span of 8,938 sequential IDs with no significant gaps. The pattern is consistent with accounts created in a single continuous run. The May 2026 wave begins around ID ~3,940,000. The ~320,000 ID gap between the two waves over 6 months tracks with DEV.to's organic signup rate, giving this sequencing value as a rough timestamp proxy for future attribution work.

---

## Step 6: The 187-Day Dormancy

The November 2025 cohort (218 high-confidence flagged accounts, S3 IDs 3,610,947–3,619,885) was created November 13–14.

Two numbers matter here: **218** is the high-confidence flagged subset (score ≥ 3); **339** is all audited accounts with a November join date, including the lower-confidence suspicious tier. I checked `Following` across all 339 — both tiers:

```python
nov_bots = [r for r in rows if r.get('JoinedDate','').startswith('Nov')]
following = Counter(r.get('Following','0') for r in nov_bots)
print(following)
# Counter({'1': 339})
```

All 339 November accounts — high-confidence and suspicious tier alike — had Following=1, pointing at me. The behavioral uniformity holds across both scoring tiers.

The evidence is consistent with a warehoused aged-account inventory: accounts from multiple cohorts manufactured in bulk, held dormant to accumulate age, then deployed on demand. Aged accounts are more valuable to follower inflation services because they appear to have existed before the deployment event. A November 2025 account following you in May 2026 looks 6 months old to a casual observer.

The timing is consistent with a deployment event temporally associated with the publication of the botnet article. I don't have access to purchase records or session logs — only DEV.to's internal telemetry could confirm that directly. But the behavioral evidence is consistent with an on-demand fulfillment event: pre-staged inventory activated in response to a specific trigger.

---

## Step 7: Avatar Fingerprinting

Most accounts that never uploaded a custom avatar (821 of 895) ended up with DEV.to's default letter placeholder — a 96×96 colored square. Not useful for fingerprinting. But the remaining 74 accounts used real custom images, and those tell a different story.

```python
from PIL import Image
import imagehash, hashlib
from pathlib import Path

def fingerprint(path):
    img = Image.open(path)
    return {
        'md5':   hashlib.md5(path.read_bytes()).hexdigest(),
        'phash': str(imagehash.phash(img)),
        'mode':  img.mode,
        'size':  img.size,
    }
```

Three distinct layers of evidence from the image analysis:

**Exact duplicates** (same MD5 hash): 55 groups across 131 accounts. Different usernames, different join dates, same bytes. Large-scale exact avatar duplication across otherwise unrelated accounts is difficult to explain organically.

**Perceptual similarity clusters** (pHash distance ≤ 10): 56 clusters. Images that aren't identical but are visually close — same style, same source material, minor encoding differences from re-uploads.

**Stylistic provenance**: All 74 real illustrations share a consistent aesthetic — black crosshatch/stipple engravings on transparent backgrounds, natural history subjects (insects, fish, bears, mushrooms). Classic 19th century scientific illustration style. Most accounts used default avatars; the custom-avatar subset exhibited repeated reuse patterns and shared artistic provenance pointing to a single asset source. Independent organic users rarely converge on the same narrow set of obscure public-domain engravings across dozens of otherwise unrelated accounts — the convergence here is consistent with shared asset sourcing rather than independent selection.

---

## Step 8: Tracing the Asset Source

The bear engraving was the most distinctive image — used by `@machatter1` and `@minakshisrivastava001` among others. I converted it to PNG and ran it through Google Lens.

Two source hits:

**DepositPhotos** — "American Black bear (Ursus americanus), vintage engraving — Vector", uploaded September 12, 2011.

**ClipArt ETC** (Florida Center for Instructional Technology) — `etc.usf.edu/clipart/2100/2134/grizzly-bear_1.htm` — a free public domain archive maintained by the University of South Florida, organized by taxonomy: Animals → Mammals → Bears, with equivalent galleries for fish, insects, birds, reptiles, fungi, and marine invertebrates.

Lens also returned the same bear image appearing as a DEV.to profile avatar going back to **December 2023** — across multiple unrelated accounts in what appear to be separate campaigns. The same asset library has been in use for at least 2.5 years across multiple deployments.

Visual survey of the 74 illustration avatars confirms subjects drawn from across the ClipArt ETC natural history collection: bear, grizzly bear, fish, mushroom, chameleon, pelican, horse, death's-head hawk moth, axolotl, deer/stag, jellyfish, stink bug, bat, and fly. The operator browsed multiple ETC galleries and hand-selected images — not a single bulk download. The selection spans 6+ taxonomic categories, consistent with deliberate curation of a varied avatar library designed to avoid visual repetition at scale.

No paid pack. No proprietary license to protect. Entirely public domain, EXIF metadata stripped, deployed across accounts and campaigns spanning at least 2.5 years.

---

## Step 9: The Marketplace

With the behavioral signatures mapped, the next question is where this service is sold.

A Google search for "buy DEV.to followers" surfaces an active commercial listing at **upvote.club** — a points-exchange engagement marketplace that explicitly sells DEV.to followers at **$0.90 per follow**, with 24-hour delivery. The same platform sells GitHub followers. That cross-platform coverage directly matches the infrastructure pattern in this investigation: separate account pools per platform, coordinated deployment.

The platform operates on a community points model: users register, earn points by completing follow tasks for others, and spend points to receive follows back. Paid tiers let buyers purchase points directly. New accounts receive 13 free points on registration — an incentive structure that encourages bulk account creation.

This model explains every behavioral signature the audit detected:

* **Following=1** — accounts complete one follow task (the target) and stop. Task fulfilled, points spent.
* **187-day dormancy** — the November accounts weren't sitting idle. They were likely earning points by completing follow tasks across the network for six months before being redeemed against this account.
* **Batch creation waves** — bulk account registration maximizes free starting points. 218 accounts × 13 free points = 2,834 free points on signup alone.
* **Zero engagement beyond the follow** — task completion, not organic interest. The follow is the deliverable.
* **Synchronized activation** — a single purchase order pointing all available inventory at one target simultaneously.

At $0.90 per follow, the ~920 accounts that followed this account during the spike represent an estimated **~$828 order**. The platform accepts Visa, Mastercard, and USDT (Tether) — cryptocurrency payment leaves a lighter paper trail.

**Important framing note:** This analysis identifies upvote.club as a marketplace whose model and pricing are consistent with the deployment pattern observed. I don't have access to purchase records, account registration logs, or payment data — only DEV.to's backend telemetry could confirm which specific service was used. What the behavioral evidence supports is this: the accounts behave exactly as task-completion accounts from a points-exchange follower service would behave, and upvote.club is an active, public-facing service matching that profile for DEV.to and GitHub simultaneously.

---

## Step 10: The Infrastructure Behind the Network

With the marketplace identified, I downloaded and decompiled the upvote.club Chrome extension (ID: `fkiaohmeeoiipoknngcppjbkinaamnof`, version 1.1.26) directly from the Chrome Web Store to understand how task verification actually works.

The extension is published under the name **"Helper App"** with the description "Just Helper App." No mention of upvote.club in the listing.

### Permissions

The manifest requests the following:

```
<all_urls>       — content scripts run on every website
webRequest       — intercepts all network requests
tabs             — access to all open tabs and URLs
scripting        — can inject code into any page
storage          — persistent local data
activeTab        — access to current tab
sidePanel        — persistent browser sidebar
webNavigation    — monitors all navigation events
```

This is the maximum surveillance permission set available in Chrome MV3. It is substantially broader than what task verification requires.

### What It Actually Does

**On DEV.to** (`social/devto.js`): The content script attaches a click listener to every button on every DEV.to page. It detects follow, like, unicorn, save, comment, and reaction actions by inspecting `aria-label`, `className`, `data-testid`, and button text. It also intercepts POST requests to `dev.to/follows`, `dev.to/reactions`, and `dev.to/comments` via the network request layer. Detected actions are reported to the upvote.club backend.

**Screenshot capture**: The background worker includes `captureVisibleTabAsDataUrl()` — it takes a PNG screenshot of the active browser window and uploads it to `api.upvote.club/api/social-profiles/upload-verification-screenshot/` along with the full extracted text of the page.

**Request body interception**: The extension intercepts raw POST bodies across 30+ platforms — Twitter/X, Facebook, LinkedIn, Reddit, GitHub, Instagram, TikTok, YouTube, Threads, DEV.to, Quora, Medium, Substack, Mastodon, Hacker News, Bluesky, and Indie Hackers. For each platform it decodes and parses the request body to identify the action type.

**Token extraction**: When the extension detects an upvote.club tab, it executes `localStorage.getItem("accessToken")` via `chrome.scripting.executeScript` to read the user's auth token and sync it to extension storage.

**Google redirect interception**: The background worker monitors `www.google.com/url` redirects and extracts task parameters embedded in the destination URLs.

### The Shadow Domain

The extension source contains a production config referencing an undisclosed second domain:

```javascript
production: {
  API_URL: "https://api.upvote.club",
  NS_API_URL: "https://ns.upvote.club",
  SITE_URL: "https://upvote.club",
  NS_SITE_URL: "https://nsboost.xyz"   // not mentioned publicly
}
```

`nsboost.xyz` resolves to a separate IP (`216.150.16.129`) from upvote.club (`172.67.182.120`). Its page title is "NS Boost | Grow Socials with the Community" — an identical service under a different brand. The page HTML includes a Yandex Metrica analytics pixel (`mc.yandex.ru/watch/98568698`). The same Chrome extension handles both domains transparently — members logged into nsboost.xyz complete tasks that fulfill upvote.club orders and vice versa. The extension currently shows **2,000 active installs**.

### Hardcoded Secret

The extension ships with a hardcoded API secret visible in plaintext source. This authenticates screenshot uploads to their backend. Anyone who downloads the CRX file — which is public — has this key. The value has been redacted here and disclosed directly to the vendor.

### What This Means for the Network

The accounts completing follow tasks on your DEV.to profile are running a browser extension with surveillance-level permissions. The extension monitors their activity across every major social platform, captures screenshots of their browser, reads their auth tokens, and intercepts their network requests — all while branded as "Helper App."

The behavioral uniformity observed in the audit (Following=1, zero engagement, synchronized activation) is a direct consequence of this architecture: every follow action is mechanically dispatched by the extension in response to a task assignment, with no organic browsing behavior attached.


## Why This Account, Why Now

The deployment timing raises a question worth addressing directly: why did a follower flood targeting a security researcher begin one day after that researcher published botnet exposure work?

Two interpretations are consistent with the evidence:

**Targeted retaliation.** Someone connected to the fake engagement ecosystem purchased a follower inflation order specifically against this account in response to the GitHub botnet article. The 24-hour lag is consistent with a human purchasing decision rather than automated monitoring.

**Reputation poisoning as an attack vector.** A DEV.to account that gains 900 followers in four days from accounts with no organic activity could trigger automated platform integrity systems — potentially flagging the *target* as the bad actor. For security researchers specifically, having your account suspended for artificial follower inflation immediately after publishing botnet research would be a highly effective way to discredit the work. Whether or not this was the intent, it is the structural effect.

On the single-use account question: the November 2025 accounts show no sign of having followed and unfollowed previous targets. The platform appears to operate on a single-use model — accounts are created, aged, deployed once against one target, then warehoused indefinitely. That makes the aged-account inventory more valuable but also more wasteful: 897 accounts burned for one ~$828 order.

---

## End-to-End Timeline

```
Nov 13-14, 2025  ──  218 accounts created (S3 IDs 3,610,947–3,619,885)
                      Zero activity. Warehoused.

Jan 2026         ──  17 more accounts created. Warehoused.

Apr 2026         ──  92 more accounts created. Warehoused.

May 13-14, 2026  ──  615 accounts created across 2 days.

May 19, 2026     ──  "Found a Coordinated GitHub Follow Botnet" published.

May 20, 2026     ──  Deployment begins. 288 new followers in one day.
                      All four waves activated. Following=1, target=GnomeMan4201.

May 19–24, 2026  ──  2,300+ accounts added. Count: ~600 → 2,944. Still active.
```

The timing is consistent with a targeted follower inflation deployment temporally associated with the article publication. Four account batches created across six months, warehoused, then activated in close temporal proximity to a specific publication event.

---

## How to Audit Your Own Followers

You don't need my full toolchain. The Following=1 signal is enough to get started:

```python
import requests, time

API_KEY = 'your_key'

def audit_your_followers():
    page, flagged = 1, []
    while True:
        resp = requests.get(
            'https://dev.to/api/followers/users',
            headers={'api-key': API_KEY},
            params={'page': page, 'per_page': 1000},
        )
        batch = resp.json()
        if not batch:
            break

        for user in batch:
            u = requests.get(
                'https://dev.to/api/users/by_username',
                headers={'api-key': API_KEY},
                params={'url': user['username']},
            ).json()
            time.sleep(0.25)

            if (u.get('following_count') == 1
                    and u.get('public_articles_count') == 0
                    and u.get('followers_count') == 0):
                flagged.append(user['username'])
                print(f'[FLAGGED] @{user["username"]}')

        page += 1

    print(f'\n{len(flagged)} accounts matching coordinated inauthentic pattern')
    return flagged

audit_your_followers()
```

If you see a sudden follower spike after publishing — especially security or platform research — run this. Accounts matching this behavioral profile will surface immediately. For deeper analysis (batch wave detection, image fingerprinting, S3 sequencing), the full toolchain is in the repo.

---

## What I Reported

I disclosed everything across four channels:

1. **DEV.to security** (three emails) — 897 flagged usernames, scored CSV, audit scripts, S3 sequencing, dormancy timeline, image fingerprinting, asset attribution, extension analysis. DEV.to previously suspended a related fraud marketplace (3 accounts, 34 articles) the same day I reported it and has been responsive throughout. Notably, the follower flood remained active through the entire investigation and disclosure period — from first detection May 19 through at least May 24, reaching 2,944 total followers while this research was being compiled and reported.

2. **Google Chrome Web Store** — policy violation report filed against the "Helper App" extension for misleading name/description and undisclosed data collection.

I'm publishing this now because developers deserve to know what these campaigns look like and how to detect them. Follower counts carry real social weight — they affect credibility signals, algorithm visibility, and how new readers decide whether to trust your work. Artificially inflating those numbers is platform manipulation, and it's more technically sophisticated than most people expect.

The more developers understand these mechanics, the harder these networks are to run quietly. Transparency makes the community harder to exploit.

---

## Limitations

This audit used publicly observable metadata and heuristic scoring — not internal platform telemetry. I don't have access to:

- IP address or device fingerprints
- Session linkage data
- Payment or purchase records
- Internal moderation signals

As a result, this analysis identifies coordinated inauthentic behavior patterns rather than attributing activity to a specific individual or organization. The findings are strong enough to act on at the platform level, but the full picture requires data that only DEV.to's backend can provide.

---

## Full Findings Summary

| Metric | Value |
|--------|-------|
| Total followers audited | 1,409 (snapshot May 23) |
| Flagged as likely coordinated inauthentic | 897 (63.7%) |
| False positives identified and removed | 2 (via S3 ID analysis) |
| Accounts with Following=1 | 1,409 (100%) |
| Accounts with zero posts | 1,393+ |
| Exact duplicate image groups | 55 |
| Perceptual similarity clusters | 56 |
| Custom illustration avatars | 74 |
| Creation waves identified | 4 |
| November wave dormancy | 187 days |
| GitHub follower crossover | 0 of 897 |
| Asset source | Public domain (ClipArt ETC / DepositPhotos) |
| Asset library in use since | At least Dec 2023 |
| Marketplace identified | upvote.club ($0.90/follow, 24hr delivery) |
| Extension active installs | 2,000 |
| Extension published as | "Helper App" / "Just Helper App" |
| Estimated order value | ~$828 |

---

*Full toolchain at [github.com/GnomeMan4201/devto-bot-audit](https://github.com/GnomeMan4201). Methodology critiques and PRs welcome.*

*Tags: #security #cybersecurity #python #webdev*

---

Coordinated follower inflation looks organic at the individual-account level. At graph scale, it becomes a structurally degenerate pattern — detectable not by individual account properties, but by the topology of the graph itself.
