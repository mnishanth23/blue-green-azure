import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

DATABASE_URL = os.environ["DATABASE_URL"]
APP_VERSION = os.getenv("APP_VERSION", "dev")
APP_COLOR = os.getenv("APP_COLOR", "blue")

pool = ConnectionPool(
    DATABASE_URL,
    min_size=1,
    max_size=5,
    open=False,
    check=ConnectionPool.check_connection,  # drop dead connections before use
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool.open()
    # Temporary: schema lives in the app until Phase 9 moves it to proper migrations
    with pool.connection() as conn, conn.transaction():
        # Serialize schema setup across replicas starting at the same time
        conn.execute("SELECT pg_advisory_xact_lock(424242)")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS items (
                   id SERIAL PRIMARY KEY,
                   name TEXT NOT NULL,
                   created_at TIMESTAMPTZ NOT NULL DEFAULT now()
               )"""
        )
    yield
    pool.close()


app = FastAPI(title="bluegreen-api", lifespan=lifespan)


class ItemIn(BaseModel):
    name: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    try:
        with pool.connection(timeout=2) as conn:
            conn.execute("SELECT 1")
    except Exception:
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ready"}


@app.get("/version")
def version():
    return {"version": APP_VERSION, "color": APP_COLOR}


@app.get("/items")
def list_items():
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT id, name, created_at FROM items ORDER BY id DESC LIMIT 50"
        ).fetchall()
    return [{"id": r[0], "name": r[1], "created_at": r[2].isoformat()} for r in rows]


@app.post("/items", status_code=201)
def create_item(item: ItemIn):
    with pool.connection() as conn:
        row = conn.execute(
            "INSERT INTO items (name) VALUES (%s) RETURNING id", (item.name,)
        ).fetchone()
    return {"id": row[0], "name": item.name, "served_by": APP_COLOR}
