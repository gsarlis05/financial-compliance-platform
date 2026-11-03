"""Sync GitHub milestones and labels from docs/tracker/milestones.json (idempotent).

Also assigns every issue whose title starts with a backlog key ("M2-5: ...", "M7: ...") to the
milestone of that key, so an issue can never sit in the wrong milestone for long.

Runs in GitHub Actions (.github/workflows/tracker-sync.yml) with the built-in GITHUB_TOKEN
(issues: write). Standard library only. Never deletes milestones, labels or issues.

    GITHUB_TOKEN=... GITHUB_REPOSITORY=owner/repo python scripts/tracker/sync.py [--dry-run]
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API = "https://api.github.com"
SPEC = Path(__file__).resolve().parents[2] / "docs" / "tracker" / "milestones.json"
KEY = re.compile(r"^\[?(M\d+)(?:-\d+)?\]?[:\s]")


def request(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    req = urllib.request.Request(  # noqa: S310 - fixed https API host
        API + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "fcp-tracker-sync",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310
            text = response.read().decode()
            return json.loads(text) if text else None
    except urllib.error.HTTPError as error:
        sys.stderr.write(f"{method} {path} -> {error.code}: {error.read().decode()[:300]}\n")
        raise


def paged(path: str) -> list[Any]:
    items: list[Any] = []
    page = 1
    while True:
        sep = "&" if "?" in path else "?"
        batch = request("GET", f"{path}{sep}per_page=100&page={page}")
        items.extend(batch)
        if len(batch) < 100:
            return items
        page += 1


def main() -> int:
    dry = "--dry-run" in sys.argv
    repo = os.environ["GITHUB_REPOSITORY"]
    spec = json.loads(SPEC.read_text(encoding="utf-8"))

    labels = {lb["name"]: lb for lb in paged(f"/repos/{repo}/labels")}
    for label in spec["labels"]:
        current = labels.get(label["name"])
        body = {"color": label["color"], "description": label["description"]}
        if current is None:
            print(f"create label {label['name']}")
            if not dry:
                request("POST", f"/repos/{repo}/labels", {"name": label["name"], **body})
        elif (
            current["color"] != label["color"] or current.get("description") != body["description"]
        ):
            print(f"update label {label['name']}")
            if not dry:
                name = urllib.parse.quote(label["name"], safe="")
                request("PATCH", f"/repos/{repo}/labels/{name}", body)

    existing = {m["title"].split(" ")[0]: m for m in paged(f"/repos/{repo}/milestones?state=all")}
    numbers: dict[str, int] = {}
    for item in spec["milestones"]:
        current = existing.get(item["key"])
        body = {"title": item["title"], "description": item["description"]}
        if current is None:
            print(f"create milestone {item['title']}")
            if not dry:
                numbers[item["key"]] = request("POST", f"/repos/{repo}/milestones", body)["number"]
        else:
            numbers[item["key"]] = current["number"]
            if (
                current["title"] != body["title"]
                or current.get("description") != body["description"]
            ):
                print(f"update milestone {item['title']}")
                if not dry:
                    request("PATCH", f"/repos/{repo}/milestones/{current['number']}", body)

    for issue in paged(f"/repos/{repo}/issues?state=all"):
        if "pull_request" in issue:
            continue
        match = KEY.match(issue["title"])
        if not match or match.group(1) not in numbers:
            continue
        wanted = numbers[match.group(1)]
        if (issue.get("milestone") or {}).get("number") != wanted:
            print(f"issue #{issue['number']} -> milestone {match.group(1)}")
            if not dry:
                request("PATCH", f"/repos/{repo}/issues/{issue['number']}", {"milestone": wanted})

    print(json.dumps({"milestones": numbers}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
