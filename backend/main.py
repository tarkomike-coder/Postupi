from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.postupi import router as postupi_router
from database.migrations import ensure_schema
from workers.scheduler import start_scheduler

app = FastAPI(title="Postupi API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # публичные открытые данные, авторизации нет (см. решение пользователя)
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(postupi_router)


@app.on_event("startup")
def startup():
    ensure_schema()
    start_scheduler()


@app.get("/")
def root():
    return {"status": "ok", "service": "postupi"}
