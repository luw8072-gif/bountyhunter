#!/usr/bin/env python3
"""
Auto-Fixer — takes matched bounties and attempts to generate fixes.
Requires ANTHROPIC_API_KEY to use Claude for code generation.
Currently: mode=auto (generates fix) or mode=dry-run (analyzes only).

Full automation chain:
  1. Scanner finds bounties → data/bounties.json
  2. Matcher ranks by fit → data/matches.json
  3. Fixer generates solutions → data/fixes/
  4. PR submitter pushes to GitHub → PR created
  5. Tracker monitors earnings → data/earnings.json
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
FIXES_DIR = DATA_DIR / "fixes"
FIXES_DIR.mkdir(exist_ok=True)

MATCHES_FILE = DATA_DIR / "matches.json"
CLAIMED_FILE = DATA_DIR / "claimed.json"
EARNINGS_FILE = DATA_DIR / "earnings.json"

GH_BIN = os.environ.get("GH_BIN", "gh")


def load_claimed() -> set:
    """Load set of already-claimed bounty URLs."""
    if CLAIMED_FILE.exists():
        return {c["url"] for c in json.loads(CLAIMED_FILE.read_text(encoding="utf-8"))}
    return set()


def save_claimed(claimed: list[dict]):
    """Save updated claimed list."""
    with open(CLAIMED_FILE, "w", encoding="utf-8") as f:
        json.dump(claimed, f, indent=2, ensure_ascii=False)


def analyze_bounty(bounty: dict) -> dict:
    """Analyze a bounty to determine if we can fix it."""
    title = bounty["title"].lower()
    labels = [l.lower() for l in bounty.get("labels", [])]
    url = bounty["url"]
    amount = bounty.get("amount_usd") or 0

    analysis = {
        "url": url,
        "title": bounty["title"],
        "amount": amount,
        "feasible": False,
        "reason": "",
        "estimated_minutes": 0,
    }

    # Quick feasibility checks
    if any(kw in title for kw in ["solidity", "smart contract", "defi", "blockchain"]):
        analysis["reason"] = "Requires blockchain expertise"
        return analysis

    if any(kw in title for kw in ["ford f-150", "can bus", "automotive"]):
        analysis["reason"] = "Requires hardware/CAN bus expertise"
        return analysis

    if amount < 2:
        analysis["reason"] = "Bounty too small"
        return analysis

    # Good candidates
    if any(kw in title for kw in ["unit test", "test", "testing"]):
        analysis["feasible"] = True
        analysis["reason"] = "Test writing — quick turnaround"
        analysis["estimated_minutes"] = 15
    elif any(kw in title for kw in ["json", "output mode", "flag", "cli"]):
        analysis["feasible"] = True
        analysis["reason"] = "CLI/flag addition — isolated change"
        analysis["estimated_minutes"] = 20
    elif any(kw in title for kw in ["validation", "input", "error handling"]):
        analysis["feasible"] = True
        analysis["reason"] = "Validation pattern — predictable"
        analysis["estimated_minutes"] = 20
    elif any(kw in title for kw in ["documentation", "docs", "readme"]):
        analysis["feasible"] = True
        analysis["reason"] = "Documentation — low risk"
        analysis["estimated_minutes"] = 10
    elif any(kw in title for kw in ["fix", "bug", "patch"]):
        analysis["feasible"] = True
        analysis["reason"] = "Bug fix — needs investigation"
        analysis["estimated_minutes"] = 30
    elif any(kw in title for kw in ["refactor", "optimize", "cleanup"]):
        analysis["feasible"] = True
        analysis["reason"] = "Refactor — medium effort"
        analysis["estimated_minutes"] = 45
    else:
        analysis["reason"] = "Unknown scope, needs manual review"
        # Still mark as feasible if high reward
        if amount >= 100:
            analysis["feasible"] = True
            analysis["reason"] += " but high reward"

    return analysis


def fork_repo(repo: str) -> bool:
    """Fork a repo if not already forked."""
    try:
        result = subprocess.run(
            [GH_BIN, "repo", "fork", repo, "--clone=false", "--remote=false"],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "GH_TOKEN": os.environ.get("GITHUB_TOKEN", "")},
        )
        return result.returncode == 0
    except Exception:
        return False


def process_bounty(bounty: dict) -> dict | None:
    """
    Process a single bounty: analyze → decide → (attempt fix).
    Returns processing result or None if skipped.
    """
    analysis = analyze_bounty(bounty)

    if not analysis["feasible"]:
        return {
            "bounty": bounty,
            "action": "skipped",
            "analysis": analysis,
        }

    # For now: analyze and prepare. Auto-fix requires ANTHROPIC_API_KEY.
    has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not has_api_key:
        return {
            "bounty": bounty,
            "action": "analyzed",
            "analysis": analysis,
            "note": "Set ANTHROPIC_API_KEY to enable auto-fix. "
                    "Manual fix: fork repo, write code, submit PR.",
        }

    # TODO: Full auto-fix pipeline when API key is set
    # 1. Clone/fork repo
    # 2. Read relevant files
    # 3. Generate fix with Claude API
    # 4. Write changes
    # 5. Create branch and PR
    # 6. Claim bounty with /claim command

    return {
        "bounty": bounty,
        "action": "api_ready",
        "analysis": analysis,
    }


def run():
    """Process top matches."""
    print(f"=== Auto-Fixer Run: {datetime.now(timezone.utc).isoformat()} ===")

    if not MATCHES_FILE.exists():
        print("No matches file. Run matcher first.")
        return

    matches = json.loads(MATCHES_FILE.read_text(encoding="utf-8"))
    claimed = load_claimed()

    # Focus on S and A tier, skip already claimed
    candidates = [
        m for m in matches
        if m["tier"] in ("S", "A") and m["url"] not in claimed
    ]

    print(f"Candidates: {len(candidates)} ({len([m for m in candidates if m['tier']=='S'])} S-tier, "
          f"{len([m for m in candidates if m['tier']=='A'])} A-tier)")

    results = []
    for i, bounty in enumerate(candidates[:5]):  # Process top 5 per run
        print(f"\n[{i + 1}/5] Analyzing: {bounty['title'][:70]}")
        print(f"  ${bounty.get('amount_usd') or '?'} | {bounty['language']} | {bounty['url']}")

        result = process_bounty(bounty)
        if result:
            results.append(result)
            print(f"  → {result['action']}: {result['analysis']['reason']}")
            print(f"  Est. time: {result['analysis']['estimated_minutes']} min")

            if result["action"] in ("analyzed", "api_ready"):
                new_claimed = json.loads(CLAIMED_FILE.read_text(encoding="utf-8")) if CLAIMED_FILE.exists() else []
                new_claimed.append({
                    "url": bounty["url"],
                    "title": bounty["title"],
                    "amount": bounty.get("amount_usd"),
                    "claimed_at": datetime.now(timezone.utc).isoformat(),
                    "action": result["action"],
                    "analysis": result["analysis"],
                })
                save_claimed(new_claimed)
        time.sleep(1)

    # Save results
    fix_file = FIXES_DIR / f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.json"
    with open(fix_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\nResults saved to: {fix_file}")
    print(f"Total analyzed: {len(results)}")
    print("Run with ANTHROPIC_API_KEY to enable full auto-fix pipeline.")


if __name__ == "__main__":
    run()
