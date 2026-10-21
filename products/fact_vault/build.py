"""Build Fact Vault: a single-file web app that holds ready-to-post Shorts scripts (a product to sell).

    python products/fact_vault/build.py              # -> products/fact_vault/dist/fact-vault.html

Input:  products/fact_vault/ideas/*.json (idea packages in the content/schema.json format).
Output: dist/fact-vault.html          the product: one self-contained file, opens in any browser
        dist/fact-vault.artifact.html the same page without the document skeleton (for a claude.ai preview)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
IDEAS = HERE / "ideas"
TEMPLATE = HERE / "template.html"
DIST = HERE / "dist"

KEEP = ("id", "topic", "title", "scenes", "description", "tags", "hashtags", "sources", "thumbnail_text")


def load_ideas() -> list[dict]:
    rows = []
    for path in sorted(IDEAS.glob("*.json")):
        pkg = json.loads(path.read_text(encoding="utf-8"))
        row = {k: pkg.get(k) for k in KEEP}
        row["scenes"] = [{"text": s["text"].strip(), "keywords": s["keywords"].strip()} for s in pkg["scenes"]]
        row["tags"] = list(pkg.get("tags") or [])
        row["hashtags"] = list(pkg.get("hashtags") or [])
        row["sources"] = list(pkg.get("sources") or [])
        if pkg.get("first_comment"):
            row["pinned_comment"] = pkg["first_comment"].strip()
        rows.append(row)
    # Mix the topics instead of grouping them: sort by title so the list reads like a magazine, not a filing cabinet.
    rows.sort(key=lambda r: r["title"].lower())
    return rows


def main() -> int:
    rows = load_ideas()
    if not rows:
        print("no ideas in", IDEAS)
        return 1
    data = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    fragment = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", data)
    DIST.mkdir(exist_ok=True)
    (DIST / "fact-vault.artifact.html").write_text(fragment, encoding="utf-8")
    standalone = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                  '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                  + fragment.replace("</style>", "</style>\n</head>\n<body>", 1) + "\n</body>\n</html>\n")
    (DIST / "fact-vault.html").write_text(standalone, encoding="utf-8")
    topics: dict[str, int] = {}
    for r in rows:
        topics[r["topic"]] = topics.get(r["topic"], 0) + 1
    print(f"fact-vault.html: {len(rows)} ideas, {len(standalone) // 1024} KB, topics {topics}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
