import json
import os

import asyncpg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Taobao Recommender API")


class RecommendationItem(BaseModel):
    item_id: int
    score: float


class RecommendationResponse(BaseModel):
    user_id: int
    recommended_items: list[RecommendationItem]


@app.on_event("startup")
async def startup():
    app.state.pool = await asyncpg.create_pool(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5432")),
        user=os.environ.get("PGUSER", "taobao"),
        password=os.environ.get("PGPASSWORD", "taobao123"),
        database=os.environ.get("PGDATABASE", "taobao"),
        min_size=1,
        max_size=10,
    )


@app.on_event("shutdown")
async def shutdown():
    await app.state.pool.close()


@app.get("/recommendations/{user_id}", response_model=RecommendationResponse)
async def get_recommendations(user_id: int):
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, recommended_items FROM inference_results WHERE user_id = $1",
            user_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail=f"Usuario {user_id} no encontrado")
    items = json.loads(row["recommended_items"]) if isinstance(row["recommended_items"], str) else row["recommended_items"]
    return RecommendationResponse(user_id=row["user_id"], recommended_items=items)