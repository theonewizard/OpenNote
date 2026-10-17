"""Liveness and readiness probes (keyless). The body says only ok or fail."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ProbeStatus(BaseModel):
    status: Literal["ok", "fail"]


@router.get("/healthz")
async def healthz() -> ProbeStatus:
    return ProbeStatus(status="ok")


@router.get("/readyz")
async def readyz() -> ProbeStatus:
    return ProbeStatus(status="ok")
