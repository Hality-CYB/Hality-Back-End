from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.api import api_router
from app.core.config import get_settings
from app.db.auditoria_queries import ChaveOperacaoReutilizadaError

settings = get_settings()

app = FastAPI(title=settings.project_name, debug=settings.debug)


@app.exception_handler(ChaveOperacaoReutilizadaError)
async def chave_operacao_reutilizada_handler(
    request: Request, exc: ChaveOperacaoReutilizadaError
) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": "Idempotency-Key já utilizada"})


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Hello World"}
