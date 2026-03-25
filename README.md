# devto-bot-audit

**Automated bot detection and community authenticity analysis for DEV.to.**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](#)
[![DEV.to](https://img.shields.io/badge/dev.to-gnomeman4201-black?logo=dev.to)](https://dev.to/gnomeman4201)

---

A research tool for auditing DEV.to follower and engagement authenticity. Pulls account data via the DEV.to API, scores accounts against behavioral indicators, flags suspicious usernames and engagement patterns, and exports results to CSV and Markdown reports.

Built after noticing unusual follower patterns on the platform. Findings documented at [dev.to/gnomeman4201](https://dev.to/gnomeman4201).

---

## What it does

- Fetches follower/following lists via DEV.to API
- Scores accounts on multiple bot indicators: username entropy, post frequency, engagement ratios, account age, comment patterns
- Flags accounts scoring above threshold
- Exports full audit to `devto_bot_audit_full.csv`
- Generates `devto_bot_audit_report.md` with summary statistics
- Exports flagged usernames to `flagged_usernames.txt`
- Weekly automated audit runner via `run_weekly_audit.sh`

---

## Usage
```bash
git clone https://github.com/GnomeMan4201/devto-bot-audit.git
cd devto-bot-audit
pip install -r requirements.txt
export DEVTO_API_KEY=your_key_here
python3 devto_audit_core.py
# or full pipeline:
./run_audit.sh
```

---

## Output

| File | Contents |
|---|---|
| `devto_bot_audit_full.csv` | Full account data with scores |
| `devto_bot_audit_report.md` | Summary statistics |
| `flagged_usernames.txt` | Accounts above bot threshold |

---

*devto-bot-audit // badBANANA research // GnomeMan4201*

---

## Sample Output
```
🔍 DEV.to Bot Audit Report: 43.08% Likely Bots

Audited 260 followers — 112 accounts (43.08%) flagged as likely bots.

HEURISTICS
  ✗ No bio
  ✗ No posts
  ✗ Suspicious username pattern (high-entropy / default)
  ✗ Heuristic score ≥ 3

RESULTS
  Total Followers : 260
  Likely Bots     : 112
  Bot Rate        : 43.08%

SAMPLE FLAGGED
  _07539bcc4c62f7fb654f
  __38872adbefc
  _eb9bd59fc267acb3d322e
  abdisamed_abdi_6c6cfabe1f
  abhijeet_mukherjee_fd304d
```
