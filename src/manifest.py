#!/usr/bin/env python3
"""Append a generated-asset entry to manifest.json in the output directory.

Usage (called by generate_asset.sh after each successful save):
    python3 src/manifest.py <output_dir> <type> <prompt> <backend> <filename>
"""

import json
import os
import sys
import time


def append_entry(
    output_dir: str,
    asset_type: str,
    prompt: str,
    backend: str,
    filename: str,
    *,
    _now: int | None = None,
) -> None:
    """Append one entry to <output_dir>/manifest.json, creating it if needed."""
    manifest_path = os.path.join(output_dir, "manifest.json")
    try:
        with open(manifest_path) as fh:
            entries = json.load(fh)
        if not isinstance(entries, list):
            entries = []
    except (FileNotFoundError, json.JSONDecodeError):
        entries = []

    entries.append(
        {
            "type": asset_type,
            "prompt": prompt,
            "backend": backend,
            "file": filename,
            "timestamp": _now if _now is not None else int(time.time()),
        }
    )

    os.makedirs(output_dir, exist_ok=True)
    with open(manifest_path, "w") as fh:
        json.dump(entries, fh, indent=2)


if __name__ == "__main__":
    if len(sys.argv) != 6:
        print(
            "Usage: manifest.py <output_dir> <type> <prompt> <backend> <filename>",
            file=sys.stderr,
        )
        sys.exit(1)
    append_entry(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
