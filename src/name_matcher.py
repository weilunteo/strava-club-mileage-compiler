"""
Fuzzy name matcher using rapidfuzz.

Uses token_set_ratio which handles:
- Different word order (Ting Yuan Yi <-> Yuan Yi Ting)
- Extra/missing tokens (Andrew Ernest Wong <-> Andrew Wong)
- Case differences
"""

import re
from rapidfuzz import fuzz, process


def normalize(name: str) -> str:
    """Lowercase, remove punctuation, collapse whitespace, expand concatenated names."""
    if not name:
        return ''
    name = name.lower().strip()
    # Insert space before capital letters in original (already lowered, so use camel case hint later)
    name = re.sub(r'[^\w\s]', ' ', name)
    name = re.sub(r'\s+', ' ', name)
    return name.strip()


def _matches_as_initials(short: str, long: str) -> bool:
    """Check if short is initials of long (e.g. 'TF' matches 'tomas fong')."""
    short_clean = short.replace(' ', '')
    long_tokens = long.split()
    if len(short_clean) != len(long_tokens) or len(short_clean) < 2:
        return False
    return all(s == t[0] for s, t in zip(short_clean, long_tokens))


def similarity(name1: str, name2: str) -> float:
    """
    Return similarity score 0-1 using rapidfuzz + initials heuristic.
    """
    n1 = normalize(name1)
    n2 = normalize(name2)
    if not n1 or not n2:
        return 0.0

    # Initials match (e.g., 'TF' <-> 'Tomas Fong', 'SO' <-> 'Shaun Ong')
    if _matches_as_initials(n1, n2) or _matches_as_initials(n2, n1):
        return 0.9

    score_token_set = fuzz.token_set_ratio(n1, n2) / 100.0
    score_partial = fuzz.partial_ratio(n1.replace(' ', ''), n2.replace(' ', '')) / 100.0
    score_wratio = fuzz.WRatio(n1, n2) / 100.0

    return max(score_token_set, score_partial, score_wratio)


def match_roster_to_strava(
    roster: dict[str, list[str]],
    strava_members: list[dict],
    threshold: float = 0.7,
) -> tuple[dict[str, list[str]], list[dict]]:
    """
    Match roster names to Strava members.

    Uses greedy assignment: computes all pairwise scores, then assigns
    highest-scoring matches first, ensuring each Strava member is used only once.

    Returns:
        division_teams: {'FMD': ['athlete_id1', ...], ...}
        unmatched: [{'roster_name', 'division', 'best_match_name', 'best_match_id', 'score'}]
    """
    all_matches = []
    for div, names in roster.items():
        for roster_name in names:
            for member in strava_members:
                score = similarity(roster_name, member['athlete_name'])
                all_matches.append((div, roster_name, member, score))

    # Sort by score descending
    all_matches.sort(key=lambda x: -x[3])

    used_ids = set()
    assigned = set()  # (div, roster_name)
    division_teams = {div: [] for div in roster}

    for div, roster_name, member, score in all_matches:
        if score < threshold:
            break
        key = (div, roster_name)
        if key in assigned or member['athlete_id'] in used_ids:
            continue
        division_teams[div].append(member['athlete_id'])
        used_ids.add(member['athlete_id'])
        assigned.add(key)

    # Build unmatched report
    unmatched = []
    for div, names in roster.items():
        for roster_name in names:
            if (div, roster_name) in assigned:
                continue
            best_score = 0.0
            best_member = None
            for member in strava_members:
                score = similarity(roster_name, member['athlete_name'])
                if score > best_score:
                    best_score = score
                    best_member = member
            unmatched.append({
                'roster_name': roster_name,
                'division': div,
                'best_match_name': best_member['athlete_name'] if best_member else None,
                'best_match_id': best_member['athlete_id'] if best_member else None,
                'score': round(best_score, 3),
            })

    return division_teams, unmatched
