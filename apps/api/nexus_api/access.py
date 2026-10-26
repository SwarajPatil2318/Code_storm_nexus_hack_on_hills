"""Explicit errors and shared database dependencies for authorized domain operations."""

from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session


class AccessError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


def database(request: Request) -> Generator[Session, None, None]:
    engine = request.app.state.engine
    if engine is None:
        raise AccessError(503, "database_unavailable", "The identity database is not configured")
    with Session(engine, expire_on_commit=False) as session:
        yield session
