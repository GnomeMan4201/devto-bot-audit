#  devto-bot-audit
![Python](https://img.shields.io/badge/python-3.10+-blue)

![License](https://img.shields.io/badge/license-MIT-green)

![Dev.to](https://img.shields.io/badge/dev.to-gnomeman4201-black?logo=dev.to)


> **An AI-augmented CLI tool for auditing suspicious Dev.to follower activity.**  
Built by [@GnomeMan4201](https://dev.to/gnomeman4201) to surface patterns of automated engagement, filter out low-quality bots, and protect signal for legitimate developers and researchers.

---

##  TL;DR

This CLI tool dynamically fetches **all followers** for a given Dev.to account and analyzes them using:

-  **Heuristic scoring** (profile bio, post count, avatar, etc.)
-  **Optional AI analysis** (via GPT-4o, if you provide an API key)
-  CSV export for review, reporting, or Dev.to moderation

No authentication, scraping libraries, or complex setup needed — just Python and a few dependencies.

---

##  Features

- Scrapes **all pages** of your followers using Dev.to's HTML frontend
- Flags:
  - No bio / default avatar
  - Suspicious usernames
  - Follows many but has no followers
  - Very recent account creation
- Optional GPT-4o scoring for bot-likeness (e.g., “8/10 – looks like automated account creation”)
- Outputs structured CSV with:
  - Username, bio, join date, post count, avatar status
  - Heuristic bot score + reasoning
  - (Optional) AI score + justification

---

##  Installation

```bash
git clone https://github.com/GnomeMan4201/devto-bot-audit.git
cd devto-bot-audit
pip install -r requirements.txt

---

## Example Output

After running:

```bash
python3 devto_bot_audit_api.py --api-key YOUR_API_KEY

You'll get a CSV like this:
username	profile_score	post_count	flags
cooldev123	0.98	4	None
user8976	0.02	0	No posts, no bio
Contributing

If you spot false positives or want to suggest features, open an issue or submit a PR. Community eyes help strengthen this project.
Contact

This tool was developed by GnomeMan4201

.
Initial concerns were shared privately with the Dev.to team before this public release.


---
## Example Output

After running:
```bash
python3 devto_bot_audit_api.py --api-key YOUR_API_KEY
```

You'll get a CSV like this:
```
username        profile_score   post_count      flags
cooldev123      0.98            4               None
user8976        0.02            0               No posts, no bio
```

## Contributing

If you spot false positives or want to suggest features, open an issue or submit a PR. Community eyes help strengthen this project.

## Contact

This tool was developed by **GnomeMan4201**.

Initial concerns were shared privately with the Dev.to team before this public release.

---

## Bot Detection Summary

From a sample of **260** followers, **112** were flagged as likely bots based on multiple heuristics:
- Suspicious usernames
- Heuristic score ≥ 3 (multiple weak signals combined)

That’s approximately **43.08%** of the follower base.

This tool helps highlight the scale of inauthentic follow activity and offers visibility into community integrity.


![Bot Score](https://img.shields.io/badge/Bot%20Integrity-43.13%%25%20bots-red)
