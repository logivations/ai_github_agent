import os
import httpx

DRONE_SERVER = os.environ["DRONE_SERVER"]
DRONE_TOKEN = os.environ["DRONE_TOKEN"]

async def get_build(repo: str, build_number: int) -> dict | None:
    url = f"{DRONE_SERVER}/api/repos/{repo}/builds/{build_number}"
    headers = {"Authorization": f"Bearer {DRONE_TOKEN}"}

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, headers=headers)
        if r.status_code != 200:
            return None
        return r.json()

def extract_tests(build: dict) -> list[dict]:
    results = []

    for stage in build.get("stages", []):
        stage_name = stage.get("name")
        stage_status = stage.get("status")

        for step in stage.get("steps", []):
            results.append({
                "stage": stage_name,
                "step": step.get("name"),
                "status": step.get("status"),
                "exit_code": step.get("exit_code"),
            })

    return results

DRONE_BASE = "https://drone.logivations.com"

HEADERS = {
    "Authorization": f"Bearer {DRONE_TOKEN}",
}

import subprocess

def get_step_logs_cli(repo: str, build_number: int, stage_num: int, step_num: int) -> str:
    cmd = [
        "drone",
        "log",
        "view",
        repo,
        str(build_number),
        str(stage_num),
        str(step_num),
    ]
    return subprocess.check_output(
        cmd,
        text=True,
        stderr=subprocess.STDOUT,
    )