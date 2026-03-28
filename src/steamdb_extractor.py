#!/usr/bin/env python3
"""Extract Steam game library data for a given Steam user.

Uses the official Steam Web API — the same data source SteamDB calculator
builds on — to fetch owned games, playtime, and (optionally) EU store prices.

Usage:
    python src/steamdb_extractor.py [OPTIONS]

Options:
    --steam-id  STEAM_ID   64-bit Steam ID (default: env STEAM_ID)
    --key       API_KEY    Steam Web API key (default: env STEAM_API_KEY)
    --cc        CC         Country code for prices, e.g. eu, us (default: eu)
    --prices               Also fetch current store price per game (slow)
    --output    FILE       Write JSON output to FILE (default: stdout)
    --csv       FILE       Also write CSV output to FILE

Get a free Steam API key at https://steamcommunity.com/dev/apikey
"""

import argparse
import csv
import json
import os
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

OWNED_GAMES_URL = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"

# Steam rate-limit is ~200 req/5 min; stay well below it
PRICE_FETCH_DELAY = 1.5  # seconds between price requests


def _get(url: str, params: dict[str, Any]) -> dict:
    full_url = f"{url}?{urlencode(params)}"
    try:
        with urlopen(full_url, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code} fetching {url}: {exc.reason}") from exc
    except URLError as exc:
        raise SystemExit(f"Network error fetching {url}: {exc.reason}") from exc


def fetch_owned_games(steam_id: str, api_key: str) -> list[dict]:
    """Return list of owned games with appid, name, playtime_forever (minutes)."""
    data = _get(OWNED_GAMES_URL, {
        "key": api_key,
        "steamid": steam_id,
        "include_appinfo": 1,
        "include_played_free_games": 1,
        "format": "json",
    })
    response = data.get("response", {})
    if not response:
        raise SystemExit(
            "Steam API returned an empty response. "
            "Check that the profile is public and the API key is valid."
        )
    games = response.get("games", [])
    print(f"[steamdb] Found {len(games)} games.", file=sys.stderr)
    return games


def fetch_price(appid: int, cc: str) -> dict | None:
    """Return price overview dict for a single app, or None if unavailable."""
    try:
        data = _get(APP_DETAILS_URL, {
            "appids": appid,
            "cc": cc,
            "filters": "price_overview",
        })
    except SystemExit:
        return None

    app_data = data.get(str(appid), {})
    if not app_data.get("success"):
        return None
    return app_data.get("data", {}).get("price_overview")


def build_records(games: list[dict], cc: str, fetch_prices: bool) -> list[dict]:
    records = []
    total = len(games)
    for i, game in enumerate(games, 1):
        appid = game["appid"]
        hours = round(game.get("playtime_forever", 0) / 60, 1)

        record: dict[str, Any] = {
            "appid": appid,
            "name": game.get("name", ""),
            "hours_played": hours,
            "img_icon_url": (
                f"https://media.steampowered.com/steamcommunity/public/images/apps"
                f"/{appid}/{game['img_icon_url']}.jpg"
                if game.get("img_icon_url") else ""
            ),
        }

        if fetch_prices:
            print(
                f"[steamdb] Fetching price {i}/{total}: {record['name']} ({appid})",
                file=sys.stderr,
            )
            price = fetch_price(appid, cc)
            if price:
                record["price_initial"] = price.get("initial", 0) / 100
                record["price_final"] = price.get("final", 0) / 100
                record["discount_percent"] = price.get("discount_percent", 0)
                record["currency"] = price.get("currency", "")
            else:
                record["price_initial"] = None
                record["price_final"] = None
                record["discount_percent"] = None
                record["currency"] = None
            time.sleep(PRICE_FETCH_DELAY)

        records.append(record)

    return records


def write_csv(records: list[dict], path: str) -> None:
    if not records:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)
    print(f"[steamdb] CSV written to {path}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract Steam game library data via the Steam Web API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--steam-id", default=os.environ.get("STEAM_ID", ""))
    parser.add_argument("--key", default=os.environ.get("STEAM_API_KEY", ""))
    parser.add_argument("--cc", default="eu")
    parser.add_argument("--prices", action="store_true",
                        help="Fetch current EU store price for each game (slow)")
    parser.add_argument("--output", default="-",
                        help="JSON output file path (default: stdout)")
    parser.add_argument("--csv", dest="csv_path", default="",
                        help="Also write CSV to this path")
    args = parser.parse_args()

    if not args.steam_id:
        parser.error(
            "Steam ID required: pass --steam-id or set STEAM_ID env var.\n"
            "Example: --steam-id 76561198015238798"
        )
    if not args.key:
        parser.error(
            "Steam API key required: pass --key or set STEAM_API_KEY env var.\n"
            "Get a free key at https://steamcommunity.com/dev/apikey"
        )

    games = fetch_owned_games(args.steam_id, args.key)
    records = build_records(games, args.cc, args.prices)

    # Sort by hours played descending
    records.sort(key=lambda r: r["hours_played"], reverse=True)

    output = json.dumps(records, indent=2, ensure_ascii=False)

    if args.output == "-":
        print(output)
    else:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"[steamdb] JSON written to {args.output}", file=sys.stderr)

    if args.csv_path:
        write_csv(records, args.csv_path)


if __name__ == "__main__":
    main()
