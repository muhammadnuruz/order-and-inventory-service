from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routes import auth, products, users, ws

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(products.router)
api_router.include_router(ws.router)
