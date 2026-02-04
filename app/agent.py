from __future__ import annotations

from datetime import datetime, timezone
import subprocess

from app.drone_api import get_build
from app.github_api import find_pr_for_commit, upsert_pr_comment
from app.llm import ask_claude

BUILD_BY_SHA: dict[str, int] = {}

SKIP_LABELS = {
    "draft",
    "do not review",
}
PIPLENE_STAGES={
    "pre-commit"
}

def cache_build_from_status(payload: dict) -> None:
    target = payload.get("target_url")
    sha = payload.get("sha")

    if not target or not sha:
        return

    try:
        build_number = int(target.rstrip("/").split("/")[-1])
    except Exception:
        return

    BUILD_BY_SHA[sha] = build_number


def tail(text: str, n: int = 200) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def get_step_logs_cli(repo: str, build_number: int, stage_number: int, step_number: int) -> str:
    cmd = ["drone", "log", "view", repo, str(build_number), str(stage_number), str(step_number)]
    return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)


async def run_agent(payload: dict) -> None:
    print("[AGENT] run_agent", flush=True)

    repo = payload["repository"]["full_name"]
    sha = payload["sha"]

    build_number = BUILD_BY_SHA.get(sha)
    if not build_number:
        print("[AGENT] no build number - exit", flush=True)
        return

    pr = await find_pr_for_commit(repo, sha)
    if not pr:
        print("[AGENT] no PR   exit", flush=True)
        return

    if pr.get("draft"):
        print("[AGENT] draft PR skip comment", flush=True)
        return


    labels = {l.get("name", "").strip().lower() for l in pr.get("labels", []) if isinstance(l, dict)}
    if labels & SKIP_LABELS:
        print(f"[AGENT] skip by label(s): {sorted(labels & SKIP_LABELS)}", flush=True)
        return

    pr_number = pr.get("number")
    if not pr_number:
        print("[AGENT] PR has no number - exit", flush=True)
        return

    build = await get_build(repo, build_number)
    if not build:
        print("[AGENT] failed to fetch build", flush=True)
        return

    failed_steps: list[dict] = []
    logs_blocks: list[str] = []

    for stage in build.get("stages", []):
        for step in stage.get("steps", []):
            if step.get("status") != "failure":
                continue

            raw_logs = get_step_logs_cli(
                repo,
                build_number,
                stage.get("number"),
                step.get("number"),
            )
            logs_tail = tail(raw_logs, 200)

            failed_steps.append(
                {
                    "stage": stage.get("name"),
                    "step": step.get("name"),
                    "logs": logs_tail,
                }
            )

            logs_blocks.append(
                f"""<details>
<summary><b>{stage.get('name')} / {step.get('name')}</b></summary>

{logs_tail}

</details>"""
            )

    if failed_steps:
        has_pre_commit_failure = any(
            (s.get("step") or "").strip().lower() == "pre-commit"
            for s in failed_steps
        )

        if has_pre_commit_failure:
            print("[AGENT] pre-commit failure - skip LLM analysis", flush=True)
            analysis_md = (
                "### Additional Fix\n"
                "- Run `pre-commit run --all-files` locally to fix formatting/linting"
            )
        else:
            print(f"[AGENT] Analyzing {len(failed_steps)} failed step(s)", flush=True)
            analysis_md = await ask_claude(repo, build_number, failed_steps)
    else:
        analysis_md = "_No failures detected_"
        print("[AGENT] No failures to analyze", flush=True)


    logs_section = "\n".join(logs_blocks) if logs_blocks else "_No failed step logs_"

    comment = f"""## CI Summary

{analysis_md}


### Failed step logs
{logs_section}

**Drone build:**  
https://drone.logivations.com/{repo}/{build_number}

_Last updated: {datetime.now(timezone.utc).isoformat()}_

<!-- CI-AGENT -->
"""

    await upsert_pr_comment(repo, pr_number, comment)
    print("[AGENT] comment posted/updated", flush=True)