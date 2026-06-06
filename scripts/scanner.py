#!/usr/bin/env python3
"""
Bounty Scanner — 24/7 GitHub bounty crawler.
Runs every 15 min via GitHub Actions. Queries 10+ search patterns.
Saves to data/bounties.json for the dashboard.
"""
import json
import re
import sys
import time
import os
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    os.system(f"{sys.executable} -m pip install requests -q")
    import requests

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

BOUNTIES_FILE = DATA_DIR / "bounties.json"
META_FILE = DATA_DIR / "meta.json"
HISTORY_FILE = DATA_DIR / "history.json"

# Track daily bounty counts
history = {}
if HISTORY_FILE.exists():
    history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))

# Multi-angle search queries
QUERIES = [
    # Direct bounty labels
    'label:bounty is:issue is:open sort:created',
    'label:bounty is:issue is:open no:assignee sort:created',
    # Amount patterns in title
    'is:issue is:open "$" in:title label:bounty',
    'is:issue is:open "bounty $100" sort:created',
    'is:issue is:open "bounty $200" sort:created',
    # Good first issue + bounty
    'label:"good first issue" label:bounty is:issue is:open',
    # Help wanted + bounty
    'label:"help wanted" label:bounty is:issue is:open',
    # By language
    'label:bounty is:issue is:open language:python',
    'label:bounty is:issue is:open language:typescript',
    'label:bounty is:issue is:open language:javascript',
    # Recently created
    'label:bounty is:issue is:open created:>=2026-06-01',
]

HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "BountyHunter/1.0",
}

# If GITHUB_TOKEN is available, use it for higher rate limits
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"


def extract_amount(title: str, body: str = "") -> int | None:
    """Extract bounty amount in USD from title or body text."""
    text = f"{title} {body}"

    patterns = [
        r'\$(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:bounty|USD|USDC|reward|prize)',
        r'(?:bounty|reward|prize).*?\$(\d{1,3}(?:,\d{3})*(?:\.\d+)?)',
        r'\/bounty\s+\$?(\d+)',
        r'\$(\d{2,4})\b',
    ]

    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            amount_str = m.group(1).replace(",", "")
            try:
                amount = int(float(amount_str))
                if 2 <= amount <= 500000:
                    return amount
            except ValueError:
                continue
    return None


def extract_language(labels: list[str]) -> str:
    """Extract programming language from labels."""
    langs = {"python", "typescript", "javascript", "rust", "go", "java", "solidity"}
    for label in labels:
        name = label.lower().strip()
        if name in langs:
            return name
        if name.startswith("lang:") or name.startswith("language:"):
            return name.split(":")[-1]
    return "unknown"


def search_issues(query: str, per_page: int = 30) -> list[dict]:
    """Execute a GitHub issue search query."""
    all_items = []
    for page in range(1, 4):  # Max 3 pages per query
        try:
            r = requests.get(
                "https://api.github.com/search/issues",
                params={"q": query, "sort": "created", "order": "desc",
                        "per_page": per_page, "page": page},
                headers=HEADERS,
                timeout=30,
            )
            if r.status_code == 200:
                items = r.json().get("items", [])
                all_items.extend(items)
                if len(items) < per_page:
                    break
            elif r.status_code == 403:
                print(f"  Rate limited on query: {query[:50]}...")
                time.sleep(10)
                break
            else:
                break
            time.sleep(1.5)  # Respect rate limits
        except Exception as e:
            print(f"  Error: {e}")
            break
    return all_items


def scan() -> list[dict]:
    """Run full scan across all queries."""
    print(f"=== Bounty Scanner Run: {datetime.now(timezone.utc).isoformat()} ===")
    seen = set()
    bounties = []

    for i, query in enumerate(QUERIES):
        print(f"[{i + 1}/{len(QUERIES)}] {query[:60]}...")
        items = search_issues(query)
        for item in items:
            url = item["html_url"]
            if url in seen:
                continue
            seen.add(url)

            labels = [l["name"] for l in item.get("labels", [])]
            amount = extract_amount(item["title"], item.get("body", ""))
            lang = extract_language(labels)

            bounty = {
                "id": f"BH-{len(bounties) + 1:06d}",
                "title": item["title"],
                "url": url,
                "repo": item["repository_url"].replace("https://api.github.com/repos/", ""),
                "number": item["number"],
                "labels": labels[:10],
                "language": lang,
                "amount_usd": amount,
                "state": item["state"],
                "comments": item.get("comments", 0),
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
                "scanned_at": datetime.now(timezone.utc).isoformat(),
                "status": "new",  # new, matched, claimed, working, submitted, paid
            }
            bounties.append(bounty)
        print(f"  Found {len(bounties)} total so far")

    # Sort by amount (high first), then by creation date
    bounties.sort(key=lambda b: (b["amount_usd"] or 0, b["created_at"]), reverse=True)

    print(f"\nTotal unique bounties: {len(bounties)}")
    total_value = sum(b.get("amount_usd") or 0 for b in bounties)
    print(f"Total tracked value: ${total_value:,.0f}")

    # Track daily stats
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if today not in history:
        history[today] = {"count": 0, "value": 0, "new": 0}
    history[today]["count"] = len(bounties)
    history[today]["value"] = total_value

    return bounties


def save(bounties: list[dict]):
    """Save results and metadata."""
    with open(BOUNTIES_FILE, "w", encoding="utf-8") as f:
        json.dump(bounties, f, indent=2, ensure_ascii=False)

    stats = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "total": len(bounties),
        "with_amount": len([b for b in bounties if b.get("amount_usd")]),
        "total_value_usd": sum(b.get("amount_usd") or 0 for b in bounties),
        "by_language": {},
        "by_label": {},
    }

    for b in bounties:
        lang = b["language"]
        stats["by_language"][lang] = stats["by_language"].get(lang, 0) + 1
        for lb in b["labels"]:
            if lb in ("bounty", "good first issue", "help wanted"):
                stats["by_label"][lb] = stats["by_label"].get(lb, 0) + 1

    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

    print(f"Saved: {BOUNTIES_FILE} ({os.path.getsize(BOUNTIES_FILE)} bytes)")
    print(f"Saved: {META_FILE}")


if __name__ == "__main__":
    try:
        bounties = scan()
        save(bounties)
        print(f"=== Scan complete: {len(bounties)} bounties ===")
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)
