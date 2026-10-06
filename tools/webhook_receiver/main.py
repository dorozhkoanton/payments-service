from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Webhook receiver")
received: list[dict[str, Any]] = []


@app.post("/webhook")
async def accept(request: Request) -> dict[str, bool]:
    received.append(await request.json())
    return {"ok": True}


@app.post("/webhook/fail")
async def fail() -> JSONResponse:
    return JSONResponse({"error": "unavailable"}, status_code=500)


@app.get("/webhook/received")
async def list_received() -> list[dict[str, Any]]:
    return received
