#!/usr/bin/env python3
"""Extract PlayStation Network game and trophy data for a PSN user.

Authentication uses the NPSSO token flow (no third-party libraries required):
  1. Log in to PlayStation at https://www.playstation.com
  2. In the same browser, open:
     https://ca.account.sony.com/api/v1/ssocookie
  3. Copy the "npsso" value from the JSON response.
  4. Pass it via --npsso or the NPSSO env var.

The script exchanges the NPSSO token for a PSN OAuth2 access token, then
calls the official PSN Trophy API to list all games the user has played
together with their trophy counts and completion percentages.

Usage:
    python src/psn_extractor.py [OPTIONS]

Options:
    --npsso     TOKEN   NPSSO cookie value (default: env NPSSO)
    --username  NAME    PSN Online ID to look up (default: own profile)
    --output    FILE    Write JSON output to FILE (default: stdout)
    --csv       FILE    Also write CSV output to FILE
    --limit     N       Max number of titles to fetch (default: all)
"""

import argparse
import csv
import json
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------
_OAUTH_CODE_URL = (
    "https://ca.account.sony.com/api/v1/oauth/code"
    "?access_type=offline"
    "&client_id=09515159-7237-4370-9b40-3806e67c0891"
    "&redirect_uri=com.scee.psxandroid.scecompcall%3A%2F%2Fredirect"
    "&response_type=code"
    "&scope=psn%3Amobile.v1.core+psn%3Aclientapp"
)
_OAUTH_TOKEN_URL = "https://ca.account.sony.com/api/v1/oauth/token"
_NPSSO_EXCHANGE_URL = (
    "https://ca.account.sony.com/api/v1/ssocookie"
)

# ---------------------------------------------------------------------------
# Trophy API endpoints
# ---------------------------------------------------------------------------
_TROPHY_TITLES_URL = (
    "https://m.np.playstation.com/api/trophy/v1/users/{account_id}/trophyTitles"
)
_PROFILE_URL = (
    "https://m.np.playstation.com/api/userProfile/v1/internal/users/{username}/profiles"
)

_CLIENT_ID = "09515159-7237-4370-9b40-3806e67c0891"
_CLIENT_SECRET = "ucybISyx57th9tup"  # public / well-known mobile client secret
_REDIRECT_URI = "com.scee.psxandroid.scecompcall://redirect"


def _post(url: str, data: dict, headers: dict | None = None) -> dict:
    body = urlencode(data).encode()
    req = Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as exc:
        body_text = exc.read().decode(errors="replace")
        raise SystemExit(
            f"HTTP {exc.code} from {url}: {exc.reason}\n{body_text}"
        ) from exc
    except URLError as exc:
        raise SystemExit(f"Network error: {exc.reason}") from exc


def _get(url: str, headers: dict | None = None, params: dict | None = None) -> dict:
    if params:
        url = f"{url}?{urlencode(params)}"
    req = Request(url)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as exc:
        body_text = exc.read().decode(errors="replace")
        raise SystemExit(
            f"HTTP {exc.code} from {url}: {exc.reason}\n{body_text}"
        ) from exc
    except URLError as exc:
        raise SystemExit(f"Network error: {exc.reason}") from exc


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def exchange_npsso_for_code(npsso: str) -> str:
    """Exchange NPSSO cookie for an OAuth authorisation code."""
    req = Request(_OAUTH_CODE_URL)
    req.add_header("Cookie", f"npsso={npsso}")
    req.add_header(
        "User-Agent",
        "Mozilla/5.0 (Linux; Android 11; SDK_GPHONE_X86) AppleWebKit/537.36",
    )
    try:
        with urlopen(req, timeout=15) as resp:
            # Sony returns a redirect; we need the 'code' query param
            final_url = resp.geturl()
    except HTTPError as exc:
        if exc.code in (302, 307):
            final_url = exc.headers.get("Location", "")
        else:
            raise SystemExit(
                f"Failed to get auth code (HTTP {exc.code}). "
                "Check that your NPSSO token is valid and not expired."
            ) from exc

    if "code=" not in final_url:
        raise SystemExit(
            f"Unexpected redirect URL — no 'code' param found: {final_url}\n"
            "Your NPSSO token may have expired. Please obtain a fresh one."
        )

    code = final_url.split("code=")[1].split("&")[0]
    return code


def exchange_code_for_token(code: str) -> dict:
    """Exchange OAuth code for access + refresh tokens."""
    return _post(_OAUTH_TOKEN_URL, {
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": _REDIRECT_URI,
        "client_id": _CLIENT_ID,
        "client_secret": _CLIENT_SECRET,
    })


def get_access_token(npsso: str) -> str:
    """Full NPSSO → access_token flow."""
    print("[psn] Authenticating with NPSSO token…", file=sys.stderr)
    code = exchange_npsso_for_code(npsso)
    tokens = exchange_code_for_token(code)
    access_token = tokens.get("access_token")
    if not access_token:
        raise SystemExit(f"No access_token in response: {tokens}")
    print("[psn] Authenticated successfully.", file=sys.stderr)
    return access_token


# ---------------------------------------------------------------------------
# Profile / trophy helpers
# ---------------------------------------------------------------------------

def resolve_account_id(username: str, access_token: str) -> str:
    """Look up the PSN account ID for a given Online ID."""
    url = _PROFILE_URL.format(username=username)
    data = _get(url, headers={"Authorization": f"Bearer {access_token}"})
    account_id = data.get("profile", {}).get("accountId", "")
    if not account_id:
        raise SystemExit(
            f"Could not resolve account ID for '{username}'. "
            "Check the username and that your token has the right scope."
        )
    return account_id


def fetch_trophy_titles(account_id: str, access_token: str, limit: int | None) -> list[dict]:
    """Fetch all (or up to *limit*) trophy title records for an account."""
    auth = {"Authorization": f"Bearer {access_token}"}
    url = _TROPHY_TITLES_URL.format(account_id=account_id)

    titles: list[dict] = []
    offset = 0
    page_size = 100  # PSN max per page

    while True:
        params: dict[str, Any] = {"limit": page_size, "offset": offset}
        data = _get(url, headers=auth, params=params)
        page = data.get("trophyTitles", [])
        titles.extend(page)

        total = data.get("totalItemCount", len(titles))
        print(
            f"[psn] Fetched {len(titles)}/{total} titles…",
            file=sys.stderr,
        )

        if limit and len(titles) >= limit:
            titles = titles[:limit]
            break
        if len(titles) >= total or not page:
            break
        offset += page_size

    return titles


def build_records(titles: list[dict]) -> list[dict]:
    """Convert raw PSN trophy title dicts to clean output records."""
    records = []
    for t in titles:
        earned = t.get("earnedTrophies", {})
        defined = t.get("definedTrophies", {})

        total_earned = sum(earned.values())
        total_defined = sum(defined.values())
        completion = round(total_earned / total_defined * 100, 1) if total_defined else 0.0

        records.append({
            "np_communication_id": t.get("npCommunicationId", ""),
            "name": t.get("trophyTitleName", ""),
            "platform": t.get("trophyTitlePlatform", ""),
            "has_trophy_groups": t.get("hasTrophyGroups", False),
            "completion_percent": completion,
            "trophies_earned_bronze": earned.get("bronze", 0),
            "trophies_earned_silver": earned.get("silver", 0),
            "trophies_earned_gold": earned.get("gold", 0),
            "trophies_earned_platinum": earned.get("platinum", 0),
            "trophies_defined_bronze": defined.get("bronze", 0),
            "trophies_defined_silver": defined.get("silver", 0),
            "trophies_defined_gold": defined.get("gold", 0),
            "trophies_defined_platinum": defined.get("platinum", 0),
            "last_updated": t.get("lastUpdatedDateTime", ""),
        })

    return records


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def write_csv(records: list[dict], path: str) -> None:
    if not records:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)
    print(f"[psn] CSV written to {path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract PSN game/trophy data via the official PSN Trophy API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--npsso", default=os.environ.get("NPSSO", ""),
                        help="NPSSO token (default: env NPSSO)")
    parser.add_argument("--username", default=os.environ.get("PSN_USERNAME", ""),
                        help="PSN Online ID to look up (default: own profile via 'me')")
    parser.add_argument("--output", default="-",
                        help="JSON output file (default: stdout)")
    parser.add_argument("--csv", dest="csv_path", default="",
                        help="Also write CSV to this path")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max number of titles to fetch")
    args = parser.parse_args()

    if not args.npsso:
        parser.error(
            "NPSSO token required: pass --npsso or set NPSSO env var.\n\n"
            "How to get your NPSSO token:\n"
            "  1. Log in at https://www.playstation.com\n"
            "  2. Open: https://ca.account.sony.com/api/v1/ssocookie\n"
            "  3. Copy the 'npsso' value from the JSON response."
        )

    access_token = get_access_token(args.npsso)

    # Resolve account ID — use "me" shorthand or look up by username
    if args.username:
        print(f"[psn] Resolving account ID for '{args.username}'…", file=sys.stderr)
        account_id = resolve_account_id(args.username, access_token)
    else:
        account_id = "me"

    titles = fetch_trophy_titles(account_id, access_token, args.limit)
    records = build_records(titles)

    # Sort by completion descending, then by name
    records.sort(key=lambda r: (-r["completion_percent"], r["name"]))

    output = json.dumps(records, indent=2, ensure_ascii=False)
    if args.output == "-":
        print(output)
    else:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"[psn] JSON written to {args.output}", file=sys.stderr)

    if args.csv_path:
        write_csv(records, args.csv_path)

    print(
        f"[psn] Done — {len(records)} titles extracted.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
