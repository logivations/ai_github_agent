import os
import httpx
from typing import Any

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
MARKER = "<!-- CI-AGENT -->"

HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}


async def find_pr_for_commit(repo: str, sha: str) -> dict[str, Any] | None:
    url = f"https://api.github.com/repos/{repo}/commits/{sha}/pulls"

    headers = {
        **HEADERS,
        "Accept": "application/vnd.github.groot-preview+json",
    }

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, headers=headers)

        if r.status_code != 200:
            print("GitHub API error:", r.text, flush=True)
            return None

        prs = r.json()
        if not prs:
            return None

        pr = prs[0]
        return pr if isinstance(pr, dict) else None


async def upsert_pr_comment(repo: str, pr_number: int, body: str):
    list_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"

    async with httpx.AsyncClient() as client:
        r = await client.get(list_url, headers=HEADERS)
        r.raise_for_status()
        comments = r.json()

        for c in comments:
            if MARKER in c["body"]:
                await client.patch(
                    f"https://api.github.com/repos/{repo}/issues/comments/{c['id']}",
                    headers=HEADERS,
                    json={"body": body},
                )
                return

        await client.post(list_url, headers=HEADERS, json={"body": body})
