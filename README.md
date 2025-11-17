# 🔎 devto-bot-audit

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
