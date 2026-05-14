from fastapi import APIRouter

from app.api.routes import auth, exams, ops, proctoring, provider, student, tools

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(provider.router)
api_router.include_router(exams.router)
api_router.include_router(student.router)
api_router.include_router(proctoring.router)
api_router.include_router(ops.router)
api_router.include_router(tools.router)
