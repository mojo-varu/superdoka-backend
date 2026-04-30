# app/api/v1/api.py
from fastapi import APIRouter
from app.api.v1.endpoints import owners, operators, logs, groups, vfm, demo

api_router = APIRouter()

# Include all endpoint routers with their prefixes and tags
api_router.include_router(owners.owner_router, prefix="/owner", tags=["Owner Operations"])
api_router.include_router(operators.operator_router, prefix="/operator", tags=["Operator Operations"]) 
api_router.include_router(logs.logs_router, prefix="/logs", tags=["Logging Operations"])
api_router.include_router(groups.groups_router, prefix="/groups", tags=["Group Operations"])
api_router.include_router(vfm.router)
api_router.include_router(demo.router)
# api_router.include_router(ner.router, prefix="/ner", tags=["NER Extraction"])
# api_router.include_router(reports.router, prefix="/reports", tags=["Reports & Analytics"])
