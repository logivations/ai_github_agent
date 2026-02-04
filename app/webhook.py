from fastapi import APIRouter
from fastapi import FastAPI, Request
import asyncio

app = FastAPI()
from app.agent import (
    run_agent,
    cache_build_from_status,
)

router = APIRouter()

print(1)

@router.post("/github/webhook")
async def github_webhook(request: Request):
    event = request.headers.get("x-github-event")
    payload = await request.json()

    print("EVENT:", event, flush=True)

    if event == "status":
        state = payload.get("state")
        print("STATUS state:", state, flush=True)

        if state not in ("success", "failure", "error"):
            return {"ignored": "intermediate"}

        cache_build_from_status(payload)

        asyncio.create_task(run_agent(payload))
        return {"handled": "status"}

    return {"ignored": True}
