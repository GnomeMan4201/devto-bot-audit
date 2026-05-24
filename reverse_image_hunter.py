#!/usr/bin/env python3
"""
reverse_image_hunter.py — Bot Avatar Illustration Pack Hunter
badBANANA Research Collective / GnomeMan4201

PURPOSE:
    The bot network uses vintage botanical/zoological WebP illustrations
    as avatars — curated from an asset pack, EXIF-stripped. This script:
      1. Selects high-value candidate images (from duplicate groups + clusters)
      2. Generates TinEye, Google Lens, and Yandex reverse-image-search URLs
      3. If TINEYE_API_KEY is set, fires live API queries and parses results
      4. Hashes and deduplicates so we don't submit the same image twice
      5. Produces a ranked hunt report: which images to check first and why

USAGE:
    python reverse_image_hunter.py \
        --avatar-dir ./avatar_cache \
        --dup-report ./duplicate_image_report.txt \
        --cluster-file ./avatar_clusters.txt \
        --output ./image_hunt_report.txt \
        [--tineye-key YOUR_KEY] \
        [--top N]           # default 20 — how many candidates to surface

DEPENDENCIES (already in venv):
    requests, Pillow, imagehash
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
from collections import defaultdict
from pathlib import Path

import imagehash
import requests
from PIL import Image

# ── Constants ─────────────────────────────────────────────────────────────────

TINEYE_API_BASE = "https://api.tineye.com/rest"
YANDEX_TEMPLATE  = "https://yandex.com/images/search?rpt=imageview&url={url}"
GOOGLE_LENS_TEMPLATE = "https://lens.google.com/uploadbyurl?url={url}"
# TinEye direct-upload search (browser fallback, no key needed)
TINEYE_UPLOAD_URL = "https://tineye.com/search"

# Rate limit for TinEye API (free tier: 100/month → be conservative)
TINEYE_DELAY_SEC = 2.0

# ── Candidate Selection ────────────────────────────────────────────────────────

def parse_duplicate_report(path: Path) -> dict[str, list[str]]:
    """
    Parse duplicate_image_report.txt.
    Expected format (your summarize_results.py output):
        Group N (K accounts):
            username1: path/to/avatar
            username2: path/to/avatar
    Returns: {group_id: [avatar_paths]}
    """
    groups = {}
    current_group = None
    current_paths = []

    with open(path) as f:
        for line in f:
            line = line.rstrip()
            m = re.match(r'Group\s+(\d+)\s*\((\d+)\s+accounts?\)', line, re.IGNORECASE)
            if m:
                if current_group and current_paths:
                    groups[current_group] = current_paths
                current_group = f"dup_{m.group(1)}"
                current_paths = []
                continue
            # lines like "  username: path" or just paths
            pm = re.match(r'\s+\S+:\s+(.+)', line)
            if pm:
                current_paths.append(pm.group(1).strip())
                continue
            pm2 = re.match(r'\s+(avatar_cache/\S+)', line)
            if pm2:
                current_paths.append(pm2.group(1).strip())

    if current_group and current_paths:
        groups[current_group] = current_paths
    return groups


def parse_cluster_file(path: Path) -> dict[str, list[str]]:
    """
    Parse avatar_clusters.txt (perceptual similarity clusters).
    Expected format:
        Cluster N (K members, max_dist=D):
            username1 -> avatar_cache/file.webp
            username2 -> avatar_cache/file.webp
    Returns: {cluster_id: [avatar_paths]}
    """
    clusters = {}
    current = None
    current_paths = []

    with open(path) as f:
        for line in f:
            line = line.rstrip()
            m = re.match(r'Cluster\s+(\d+)\s*\((\d+)\s+members', line, re.IGNORECASE)
            if m:
                if current and current_paths:
                    clusters[current] = current_paths
                current = f"cluster_{m.group(1)}"
                current_size = int(m.group(2))
                current_paths = []
                continue
            # "username -> path" or just path
            pm = re.match(r'\s+\S+\s+->\s+(.+)', line)
            if pm:
                current_paths.append(pm.group(1).strip())
                continue
            pm2 = re.match(r'\s+(avatar_cache/\S+)', line)
            if pm2:
                current_paths.append(pm2.group(1).strip())

    if current and current_paths:
        clusters[current] = current_paths
    return clusters


def score_candidates(
    dup_groups: dict[str, list[str]],
    clusters: dict[str, list[str]],
    avatar_dir: Path,
) -> list[dict]:
    """
    Score images by investigative value:
      - Exact duplicates (higher weight — proven shared asset)
      - Perceptual cluster members (medium weight — same illustration pack)
      - Prefer first/representative image from each group (dedup by sha256)
    Returns sorted list of candidate dicts.
    """
    seen_hashes = set()
    candidates = []

    # Helper: compute sha256 of file bytes
    def sha256(p: Path) -> str:
        try:
            return hashlib.sha256(p.read_bytes()).hexdigest()
        except Exception:
            return ""

    # Exact dup groups — highest confidence
    for gid, paths in sorted(dup_groups.items(), key=lambda x: -len(x[1])):
        for p in paths[:1]:  # one representative per group
            fp = avatar_dir / Path(p).name if not Path(p).is_absolute() else Path(p)
            if not fp.exists():
                fp = Path(p)
            if not fp.exists():
                continue
            h = sha256(fp)
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            candidates.append({
                "path": fp,
                "source": gid,
                "group_size": len(paths),
                "score": 100 + len(paths) * 10,  # bigger dup group = more interesting
                "evidence_type": "exact_duplicate",
            })

    # Perceptual clusters — medium confidence
    for cid, paths in sorted(clusters.items(), key=lambda x: -len(x[1])):
        for p in paths[:2]:  # up to 2 per cluster
            fp = avatar_dir / Path(p).name if not Path(p).is_absolute() else Path(p)
            if not fp.exists():
                fp = Path(p)
            if not fp.exists():
                continue
            h = sha256(fp)
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            candidates.append({
                "path": fp,
                "source": cid,
                "group_size": len(paths),
                "score": 50 + len(paths) * 5,
                "evidence_type": "perceptual_cluster",
            })

    # Sort by score descending
    return sorted(candidates, key=lambda x: -x["score"])


# ── URL Generators ─────────────────────────────────────────────────────────────

def make_tineye_upload_cmd(img_path: Path) -> str:
    """Browser-based TinEye — no API key needed. Returns curl command."""
    return (
        f"curl -s -F 'image=@{img_path}' "
        f"'https://tineye.com/search' -L | grep -oP '(?<=href=\")/search/[^\"]+'"
    )


def make_google_lens_manual(img_path: Path) -> str:
    """Google Lens requires the image be publicly hosted. Returns instruction."""
    return f"# Upload {img_path.name} manually at: https://lens.google.com/"


def make_yandex_upload_cmd(img_path: Path) -> str:
    """Yandex reverse image search via multipart upload."""
    return (
        f"curl -s -X POST "
        f"-F 'upfile=@{img_path};type=image/webp' "
        f"'https://yandex.com/images/search?rpt=imageview&format=json' "
        f"| python3 -c \"import sys,json; d=json.load(sys.stdin); "
        f"print(d.get('blocks',{{}}).get('cbir-page',{{}}).get('url','no result'))\""
    )


# ── TinEye API (optional) ──────────────────────────────────────────────────────

class TinEyeAPI:
    """
    TinEye API client.
    Free tier: 100 searches/month at api.tineye.com
    Docs: https://services.tineye.com/developers/tineyeapi/
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "x-api-key": api_key,
            "User-Agent": "badBANANA-BotAudit/1.0",
        })

    def search_image(self, img_path: Path) -> dict:
        """Upload image to TinEye and return parsed results."""
        url = f"{TINEYE_API_BASE}/search/"
        try:
            with open(img_path, "rb") as f:
                resp = self.session.post(
                    url,
                    files={"image": (img_path.name, f, "image/webp")},
                    timeout=30,
                )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            return {"error": str(e), "matches": []}

    def parse_results(self, data: dict) -> list[dict]:
        """Extract useful fields from TinEye API response."""
        if "error" in data:
            return [{"error": data["error"]}]

        results = []
        for match in data.get("matches", []):
            results.append({
                "domain": match.get("domain", ""),
                "image_url": match.get("image_url", ""),
                "page_url": match.get("backlinks", [{}])[0].get("url", "") if match.get("backlinks") else "",
                "crawl_date": match.get("crawl_date", ""),
                "score": match.get("score", 0),
                "tags": match.get("tags", []),
            })
        return results


# ── Image Metadata Extraction ──────────────────────────────────────────────────

def extract_image_meta(img_path: Path) -> dict:
    """Extract perceptual hashes and basic metadata for the report."""
    try:
        img = Image.open(img_path)
        phash = str(imagehash.phash(img))
        dhash = str(imagehash.dhash(img))
        ahash = str(imagehash.average_hash(img))
        return {
            "size": img.size,
            "mode": img.mode,
            "format": img.format or img_path.suffix.upper().lstrip("."),
            "phash": phash,
            "dhash": dhash,
            "ahash": ahash,
            "file_bytes": img_path.stat().st_size,
        }
    except Exception as e:
        return {"error": str(e)}


# ── Report Generation ──────────────────────────────────────────────────────────

REPORT_HEADER = """
╔══════════════════════════════════════════════════════════════════════════════╗
║         ILLUSTRATION PACK HUNT REPORT — badBANANA Bot Audit                ║
║         Generated: {timestamp}                                 ║
╚══════════════════════════════════════════════════════════════════════════════╝

OBJECTIVE: Identify the asset pack/marketplace the bot operator used for
           vintage botanical/zoological WebP avatars. A hit links the
           infrastructure to a specific seller or service bundle.

SEARCH PRIORITY ORDER:
  1. Exact duplicate groups (proven shared source image → highest signal)
  2. Perceptual cluster representatives (same illustration style → pack match)

TOOLS TO USE:
  • TinEye      — best for finding earliest/original image source
  • Yandex      — best for non-English illustration packs, Russian storefronts
  • Google Lens — best for commercial stock/illustration sites (Shutterstock etc)

NOTE: All images are EXIF-stripped. Focus on visual content matching,
      not metadata. Look for: illustration bundle sites, Etsy shops selling
      vintage engravings, stock sites, Telegram channels selling account kits.

══════════════════════════════════════════════════════════════════════════════
CANDIDATE IMAGES (ranked by investigative value)
══════════════════════════════════════════════════════════════════════════════
""".strip()


def write_report(
    candidates: list[dict],
    tineye_results: dict[str, list],
    output_path: Path,
    top_n: int,
) -> None:
    import datetime

    lines = []
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append(REPORT_HEADER.format(timestamp=ts))
    lines.append("")

    for i, cand in enumerate(candidates[:top_n], 1):
        fp: Path = cand["path"]
        meta = extract_image_meta(fp)
        te_results = tineye_results.get(str(fp), [])

        lines.append(f"{'─'*78}")
        lines.append(f"[{i:02d}] {fp.name}")
        lines.append(f"     Source    : {cand['source']}  ({cand['evidence_type']})")
        lines.append(f"     Group size: {cand['group_size']} accounts sharing this image")
        lines.append(f"     Priority  : {cand['score']}")

        if "error" not in meta:
            lines.append(f"     Dimensions: {meta['size'][0]}x{meta['size'][1]}  {meta['file_bytes']} bytes")
            lines.append(f"     pHash     : {meta['phash']}  (compare against known packs)")
            lines.append(f"     dHash     : {meta['dhash']}")

        lines.append("")
        lines.append("  ┌─ SEARCH COMMANDS ─────────────────────────────────────────────────────")

        # TinEye CLI
        lines.append(f"  │  [TinEye upload]")
        lines.append(f"  │  {make_tineye_upload_cmd(fp)}")
        lines.append("  │")

        # Yandex
        lines.append(f"  │  [Yandex upload]")
        lines.append(f"  │  {make_yandex_upload_cmd(fp)}")
        lines.append("  │")

        # Google Lens (manual — requires public URL)
        lines.append(f"  │  [Google Lens — manual]")
        lines.append(f"  │  python3 -m http.server 8888 &  # serve locally")
        lines.append(f"  │  # then: https://lens.google.com/  → upload {fp.name}")
        lines.append("  └───────────────────────────────────────────────────────────────────────")

        # TinEye API results (if we ran them)
        if te_results and not (len(te_results) == 1 and "error" in te_results[0]):
            lines.append("")
            lines.append(f"  ┌─ TINEYE API RESULTS ({len(te_results)} matches) ─────────────────────────────")
            for r in te_results[:5]:
                if "error" in r:
                    lines.append(f"  │  ERROR: {r['error']}")
                else:
                    lines.append(f"  │  [{r.get('score',0):.0f}] {r.get('domain','')} — {r.get('page_url','')[:70]}")
            lines.append("  └───────────────────────────────────────────────────────────────────────")
        elif te_results and "error" in te_results[0]:
            lines.append(f"  TinEye API error: {te_results[0]['error']}")

        lines.append("")

    lines.append("══════════════════════════════════════════════════════════════════════════════")
    lines.append("WHAT TO LOOK FOR IN RESULTS:")
    lines.append("")
    lines.append("  HIGH VALUE HITS:")
    lines.append("  • Bulk illustration bundle downloads (Gumroad, Creative Market, Etsy)")
    lines.append("  • 'Vintage botanical clip art pack' — common PayHip/Gumroad product")
    lines.append("  • Telegram channels selling 'aged account kits' with bundled avatars")
    lines.append("  • AliExpress / SEOClerks / Fiverr seller using identical images")
    lines.append("  • GitHub repos containing the images (operator may have forked an asset repo)")
    lines.append("")
    lines.append("  PIVOT PATHS:")
    lines.append("  • Image URL domain → find seller/uploader account → cross-ref other platforms")
    lines.append("  • If stock site hit: search license purchase records or watermark patterns")
    lines.append("  • If Etsy/Gumroad: buyer reviews may name the bot service")
    lines.append("")
    lines.append("  RECORD FOR FINAL REPORT:")
    lines.append("  • Original upload date (proves pre-staging timeline)")
    lines.append("  • Number of TinEye appearances (spread = commercial distribution)")
    lines.append("  • Any co-located images from the same pack (map the full library)")

    output_path.write_text("\n".join(lines))
    print(f"[+] Report written to {output_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Bot avatar reverse-image hunter")
    parser.add_argument("--avatar-dir", default="./avatar_cache", type=Path)
    parser.add_argument("--dup-report", default="./duplicate_image_report.txt", type=Path)
    parser.add_argument("--cluster-file", default="./avatar_clusters.txt", type=Path)
    parser.add_argument("--output", default="./image_hunt_report.txt", type=Path)
    parser.add_argument("--tineye-key", default=os.environ.get("TINEYE_API_KEY", ""))
    parser.add_argument("--top", default=20, type=int, help="Candidates to surface")
    parser.add_argument("--live-tineye", action="store_true",
                        help="Fire live TinEye API queries (consumes monthly quota)")
    args = parser.parse_args()

    # Validate inputs
    for p, name in [(args.avatar_dir, "avatar-dir"),
                    (args.dup_report, "dup-report"),
                    (args.cluster_file, "cluster-file")]:
        if not p.exists():
            print(f"[!] {name} not found: {p}", file=sys.stderr)
            sys.exit(1)

    print(f"[*] Parsing duplicate report: {args.dup_report}")
    dup_groups = parse_duplicate_report(args.dup_report)
    print(f"    {len(dup_groups)} exact-duplicate groups parsed")

    print(f"[*] Parsing cluster file: {args.cluster_file}")
    clusters = parse_cluster_file(args.cluster_file)
    print(f"    {len(clusters)} perceptual clusters parsed")

    print(f"[*] Scoring candidates...")
    candidates = score_candidates(dup_groups, clusters, args.avatar_dir)
    print(f"    {len(candidates)} unique candidates ranked")

    tineye_results = {}

    if args.live_tineye and args.tineye_key:
        api = TinEyeAPI(args.tineye_key)
        top = candidates[:min(args.top, 20)]  # cap API calls
        print(f"[*] Running TinEye API queries for top {len(top)} images...")
        for cand in top:
            fp = cand["path"]
            print(f"    querying: {fp.name} ...", end=" ", flush=True)
            result = api.search_image(fp)
            parsed = api.parse_results(result)
            tineye_results[str(fp)] = parsed
            n = len(parsed)
            print(f"{n} matches" if not (n == 1 and "error" in parsed[0]) else f"ERROR")
            time.sleep(TINEYE_DELAY_SEC)
    elif args.live_tineye and not args.tineye_key:
        print("[!] --live-tineye set but no TINEYE_API_KEY found. Set env var or pass --tineye-key.")

    print(f"[*] Writing report...")
    write_report(candidates, tineye_results, args.output, args.top)

    # Quick-start summary
    print("\n[+] QUICK START — run these manually for fastest results:")
    for cand in candidates[:3]:
        fp = cand["path"]
        print(f"\n  # {fp.name}  [{cand['evidence_type']}, {cand['group_size']} accounts]")
        print(f"  # TinEye:")
        print(f"  {make_tineye_upload_cmd(fp)}")


if __name__ == "__main__":
    main()
