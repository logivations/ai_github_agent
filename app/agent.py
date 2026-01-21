from datetime import datetime, timezone
import subprocess

from app.drone_api import get_build, extract_tests
from app.github_api import (
    upsert_pr_comment,
    find_pr_for_commit,
)
from app.llm import  ask_claude


BUILD_BY_SHA: dict[str, int] = {}

def cache_build_from_status(payload: dict):
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


def get_step_logs_cli(
    repo: str,
    build_number: int,
    stage_number: int,
    step_number: int,
) -> str:

    cmd = [
        "drone",
        "log",
        "view",
        repo,
        str(build_number),
        str(stage_number),
        str(step_number),
    ]

    return subprocess.check_output(
        cmd,
        text=True,
        stderr=subprocess.STDOUT,
    )


async def run_agent(payload: dict):
    print("[AGENT] run_agent", flush=True)

    repo = payload["repository"]["full_name"]
    sha = payload["sha"]

    build_number = BUILD_BY_SHA.get(sha)
    if not build_number:
        print("[AGENT] no build number → exit", flush=True)
        return

    pr_number = await find_pr_for_commit(repo, sha)
    if not pr_number:
        print("[AGENT] no PR → exit", flush=True)
        return

    build = await get_build(repo, build_number)
    if not build:
        print("[AGENT] failed to fetch build", flush=True)
        return

    tests = extract_tests(build)
    failed = [t for t in tests if t["status"] != "success"]

    status_emoji = "✅" if not failed else "❌"
    status_text = "SUCCESS" if not failed else "FAILURE"

    if failed:
        failed_block = "\n".join(
            f"- **{t['stage']} / {t['step']}**"
            for t in failed
        )
    else:
        failed_block = "_No failed steps_"


    suggestions = []

    if any("pre-commit" in t["step"].lower() for t in failed):
        suggestions.append(
            "- Run `pre-commit run --all-files` locally"
        )

    if any("system" in t["stage"].lower() for t in failed):
        suggestions.append(
            "- System tests failed — check available **mcap rosbags** in artifacts"
        )

    suggestions_block = (
        "\n".join(suggestions)
        if suggestions
        else "_No suggestions_"
    )

    failed_steps = []

    for stage in build.get("stages", []):
        for step in stage.get("steps", []):
            if step.get("status") == "failure":
                raw_logs = get_step_logs_cli(
                    repo,
                    build_number,
                    stage["number"],
                    step["number"],
                )

                failed_steps.append({
                    "stage": stage["name"],
                    "step": step["name"],
                    "logs": tail(raw_logs, 200),
                })

    if failed_steps:
        print(f"[AGENT] Analyzing {len(failed_steps)} failed step(s)")
        # analysis_md = await ask_claude(repo, build_number, failed_steps)
        analysis_md = f"{len(failed_steps)}failures detected_"
    else:
        analysis_md = "_No failures detected_"
        print("[AGENT] No failures to analyze")

    analysis_lower = analysis_md.lower()

    if any("pre-commit" in s["step"].lower() for s in failed_steps):
        if "pre-commit run --all-files" not in analysis_lower:
            analysis_md += "\n\n### Additional Fix\n- Run `pre-commit run --all-files` locally to fix formatting/linting"


    logs_blocks = []

    for stage in build.get("stages", []):
        for step in stage.get("steps", []):
            if step.get("status") == "failure":
                raw_logs = get_step_logs_cli(
                    repo,
                    build_number,
                    stage["number"],
                    step["number"],
                )

                logs_blocks.append(
                    f"""
<details>
<summary><b>{stage['name']} / {step['name']}</b></summary>

{tail(raw_logs, 200)}

</details>
""")

    logs_section = "\n".join(logs_blocks)

    comment = f"""
## CI Summary

{analysis_md}

 **Drone build:**  
https://drone.logivations.com/{repo}/{build_number}

_Last updated: {datetime.now(timezone.utc).isoformat()}_

<!-- CI-AGENT -->
"""

    await upsert_pr_comment(repo, pr_number, comment)
    print("[AGENT] comment posted/updated", flush=True)