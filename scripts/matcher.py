#!/usr/bin/env python3
"""
Smart Matcher — filters bounties by our capabilities and ROI potential.
Prioritizes: high reward, our language, low competition, quick turnaround.
"""
import json
import sys
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
BOUNTIES_FILE = DATA_DIR / "bounties.json"
MATCHES_FILE = DATA_DIR / "matches.json"

# Our capabilities
OUR_LANGUAGES = {"python", "typescript", "javascript"}
OUR_LABELS = {
    "good first issue": 1.5,   # Easy → high success rate
    "help wanted": 1.2,        # Maintainer engaged
    "bug": 0.9,                # Slightly harder but common
    "enhancement": 0.8,        # Feature work → more effort
    "documentation": 1.0,      # Easy but less valuable
    "testing": 1.3,            # Easy, good fit for AI
    "api": 1.1,                # Well-defined
}

OUR_WALLET = "0x43552E59Be74AE4e0856ECC9aF600cF74b3F5e21"


def score_bounty(b: dict) -> float:
    """Score a bounty by our fit. Higher = better for us."""
    score = 0.0

    # 1. Language match (0-30 points)
    if b["language"] in OUR_LANGUAGES:
        score += 30
    elif b["language"] == "unknown":
        score += 10  # Might be anything

    # 2. Amount match (0-40 points, capped)
    amount = b.get("amount_usd") or 0
    if amount >= 2000:
        score += 40
    elif amount >= 500:
        score += 30
    elif amount >= 100:
        score += 20
    elif amount >= 10:
        score += 10
    elif amount > 0:
        score += 3

    # 3. Label bonus (0-20 points)
    for label in b.get("labels", []):
        name = label.lower().strip()
        if name in OUR_LABELS:
            score += OUR_LABELS[name] * 3

    # 4. Recency bonus (0-10 points) — newer = less competition
    created = b.get("created_at", "")
    if "2026-06" in created:
        score += 10
    elif "2026-05" in created:
        score += 5

    # 5. Less comments = less competition
    comments = b.get("comments", 0)
    if comments == 0:
        score += 5
    elif comments < 5:
        score += 3

    # 6. Has assignee = already taken, penalize
    if b.get("assignee"):
        score -= 50

    return round(score, 1)


def match():
    """Load bounties, score, filter, and rank."""
    if not BOUNTIES_FILE.exists():
        print("No bounties file found. Run scanner first.")
        return []

    bounties = json.loads(BOUNTIES_FILE.read_text(encoding="utf-8"))

    # Score all
    for b in bounties:
        b["_score"] = score_bounty(b)

    # Filter: score >= 30, not already claimed
    candidates = [
        b for b in bounties
        if b["_score"] >= 30 and b.get("status") != "claimed"
    ]

    # Sort by score descending
    candidates.sort(key=lambda b: b["_score"], reverse=True)

    # Categorize
    for b in candidates:
        score = b["_score"]
        if score >= 60:
            b["tier"] = "S"       # Best — do immediately
        elif score >= 45:
            b["tier"] = "A"       # Good — do today
        elif score >= 30:
            b["tier"] = "B"       # OK — do if time

    # Save matches
    with open(MATCHES_FILE, "w", encoding="utf-8") as f:
        json.dump(candidates[:50], f, indent=2, ensure_ascii=False)

    print(f"Matched {len(candidates)} bounties ({len([b for b in candidates if b['tier']=='S'])} S-tier, "
          f"{len([b for b in candidates if b['tier']=='A'])} A-tier, "
          f"{len([b for b in candidates if b['tier']=='B'])} B-tier)")

    # Print top 10
    print("\n=== TOP MATCHES ===")
    for b in candidates[:10]:
        print(f"[{b['tier']}] ${b.get('amount_usd') or '?'} | "
              f"{b['language']:12} | {b['title'][:70]} | {b['url']}")

    return candidates


if __name__ == "__main__":
    match()
