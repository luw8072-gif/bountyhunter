#!/usr/bin/env python3
"""
Earnings Tracker — checks wallet balance, PR status, and claimed bounties.
Updates data/earnings.json for the dashboard.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    os.system(f"{sys.executable} -m pip install requests -q")
    import requests

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
EARNINGS_FILE = DATA_DIR / "earnings.json"

WALLET = "0x76485924c7CA4EFcC03e622441fF3ab633c86143"
ETHERSCAN_API_KEY = os.environ.get("ETHERSCAN_API_KEY", "")

# Known PRs we've submitted
OUR_PRS = [
    {"repo": "moorcheh-ai/memanto", "pr": 672, "bounty": 100, "issue": 639,
     "title": "Memanto vs Letta Benchmark"},
    {"repo": "xevrion-v2/agent-playground", "pr": 1015, "bounty": 150, "issue": "6/9/12",
     "title": "Validation + Tests + Body Limit"},
    {"repo": "xevrion-v2/agent-playground", "pr": 1017, "bounty": 250, "issue": "7/8/10/11/13",
     "title": "Error Handler + Routes + Tests"},
    {"repo": "xevrion-v2/agent-playground", "pr": 1021, "bounty": 400, "issue": "1-5/14/15/17",
     "title": "JSDoc + Types + Env + Prisma + PI + Sequences"},
    {"repo": "ritik4ever/stellar-bounty-board", "pr": 637, "bounty": 0, "issue": "258/246/245",
     "title": "Bounty Filters + Lookup"},
    {"repo": "promptpolish-ai/git-context", "pr": 31, "bounty": 2, "issue": 2,
     "title": "JSON Output Mode"},
]

HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "BountyHunter/1.0",
}

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"


def check_wallet() -> dict:
    """Check ETH balance and recent transactions."""
    result = {
        "address": WALLET,
        "eth_balance": 0,
        "usdc_balance": 0,
        "transactions": [],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

    if not ETHERSCAN_API_KEY:
        result["error"] = "No Etherscan API key configured"
        return result

    try:
        # ETH balance
        r = requests.get("https://api.etherscan.io/api", params={
            "module": "account", "action": "balance",
            "address": WALLET, "tag": "latest",
            "apikey": ETHERSCAN_API_KEY,
        }, timeout=15)
        if r.status_code == 200 and r.json().get("status") == "1":
            result["eth_balance"] = int(r.json()["result"]) / 1e18

        # Recent transactions
        r2 = requests.get("https://api.etherscan.io/api", params={
            "module": "account", "action": "txlist",
            "address": WALLET, "startblock": 0, "endblock": 99999999,
            "page": 1, "offset": 10, "sort": "desc",
            "apikey": ETHERSCAN_API_KEY,
        }, timeout=15)
        if r2.status_code == 200 and r2.json().get("status") == "1":
            result["transactions"] = [
                {
                    "hash": tx["hash"],
                    "from": tx["from"],
                    "to": tx["to"],
                    "value_eth": int(tx["value"]) / 1e18,
                    "timestamp": int(tx["timeStamp"]),
                    "date": datetime.fromtimestamp(int(tx["timeStamp"]), tz=timezone.utc).isoformat(),
                }
                for tx in r2.json()["result"][:10]
            ]
    except Exception as e:
        result["error"] = str(e)

    return result


def check_prs() -> list[dict]:
    """Check status of all our submitted PRs."""
    updated_prs = []
    for pr_info in OUR_PRS:
        try:
            r = requests.get(
                f"https://api.github.com/repos/{pr_info['repo']}/pulls/{pr_info['pr']}",
                headers=HEADERS, timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                pr_info["state"] = data["state"]
                pr_info["merged"] = data.get("merged_at") is not None
                pr_info["merged_at"] = data.get("merged_at")
                pr_info["closed_at"] = data.get("closed_at")
                pr_info["mergeable"] = data.get("mergeable_state", "unknown")
                pr_info["reviews"] = data.get("comments", 0) + data.get("review_comments", 0)
                pr_info["checked_at"] = datetime.now(timezone.utc).isoformat()
            else:
                pr_info["state"] = "error"
                pr_info["error"] = f"HTTP {r.status_code}"
            updated_prs.append(pr_info)
            time.sleep(0.5)
        except Exception as e:
            pr_info["state"] = "error"
            pr_info["error"] = str(e)
            updated_prs.append(pr_info)

    return updated_prs


def build_earnings():
    """Build complete earnings report."""
    print("=== Earnings Tracker ===")

    # Load previous state
    previous = {}
    if EARNINGS_FILE.exists():
        previous = json.loads(EARNINGS_FILE.read_text())

    # Check wallet
    print("Checking wallet...")
    wallet = check_wallet()
    print(f"  ETH: {wallet['eth_balance']}")

    # Check PRs
    print("Checking PRs...")
    prs = check_prs()

    # Calculate totals
    total_claimed = sum(p["bounty"] for p in prs)
    merged_prs = [p for p in prs if p.get("merged")]
    total_earned = sum(p["bounty"] for p in merged_prs)
    open_prs = [p for p in prs if p.get("state") == "open"]
    closed_not_merged = [p for p in prs if p.get("state") == "closed" and not p.get("merged")]

    earnings = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "wallet": wallet,
        "summary": {
            "total_prs": len(prs),
            "open_prs": len(open_prs),
            "merged_prs": len(merged_prs),
            "closed_not_merged": len(closed_not_merged),
            "total_claimed_usd": total_claimed,
            "total_earned_usd": total_earned,
            "pending_usd": total_claimed - total_earned,
        },
        "prs": prs,
        "history": previous.get("history", []),
    }

    # Add to history if changed
    prev_summary = previous.get("summary", {})
    if (
        prev_summary.get("merged_prs") != earnings["summary"]["merged_prs"]
        or prev_summary.get("total_earned_usd") != earnings["summary"]["total_earned_usd"]
    ):
        entry = {
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "event": "",
        }
        newly_merged = [p for p in merged_prs if not any(
            hp.get("pr") == p["pr"] and hp.get("merged")
            for hp in previous.get("prs", [])
        )]
        if newly_merged:
            entry["event"] = f"MERGED: {', '.join(p['title'] for p in newly_merged)} (${sum(p['bounty'] for p in newly_merged)})"

        earnings["history"].append(entry)
        # Keep only last 100 entries
        earnings["history"] = earnings["history"][-100:]

    with open(EARNINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(earnings, f, indent=2, ensure_ascii=False)

    print(f"  Total claimed: ${total_claimed:,}")
    print(f"  Merged (earned): {len(merged_prs)} PRs, ${total_earned:,}")
    print(f"  Pending: ${total_claimed - total_earned:,}")
    print(f"  Saved to: {EARNINGS_FILE}")


if __name__ == "__main__":
    build_earnings()
