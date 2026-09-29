from fastapi import APIRouter

from . import activity, backup, favorites, listings, products, sets, stores, system

router = APIRouter()
for module in (products, listings, stores, sets, favorites, activity, system, backup):
    router.include_router(module.router)
