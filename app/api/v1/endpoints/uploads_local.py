"""Alvo de upload do storage `local`: imita o presigned POST do S3.

A credencial é a policy assinada (HMAC com `secret_key`), como no S3. Só é
registrada com `STORAGE_BACKEND=local` (ver `app.api.v1.api`).
"""

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile

from app.auth.policies import validar_policy_upload_local
from app.services import storage

router = APIRouter(prefix="/uploads", tags=["uploads"])


def _erro(codigo: int, motivo: str) -> JSONResponse:
    return JSONResponse(status_code=codigo, content={"motivo": motivo})


@router.post("/local", include_in_schema=False, status_code=status.HTTP_204_NO_CONTENT)
async def receber_upload_local(request: Request) -> Response:
    form = await request.form(max_files=1, max_fields=10)
    arquivo = form.get("file")
    chave = form.get("key")
    content_type = form.get("Content-Type")
    policy = form.get("policy")
    assinatura = form.get("signature")

    if not all(isinstance(v, str) for v in (chave, content_type, policy, assinatura)):
        return _erro(status.HTTP_403_FORBIDDEN, "Alvo de upload inválido.")

    alvo = validar_policy_upload_local(str(policy), str(assinatura))

    if alvo is None or alvo.chave != chave or alvo.content_type != content_type:
        return _erro(status.HTTP_403_FORBIDDEN, "Alvo de upload inválido ou expirado.")

    if not isinstance(arquivo, UploadFile):
        return _erro(status.HTTP_400_BAD_REQUEST, "Arquivo ausente.")

    dados = await arquivo.read(alvo.max_bytes + 1)

    if not dados:
        return _erro(status.HTTP_400_BAD_REQUEST, "O arquivo enviado está vazio.")

    if len(dados) > alvo.max_bytes:
        return _erro(status.HTTP_400_BAD_REQUEST, "Arquivo acima do tamanho máximo permitido.")

    try:
        await storage.atual().salvar(alvo.chave, dados, alvo.content_type)
    except storage.ObjetoJaExisteError:
        return _erro(status.HTTP_409_CONFLICT, "Este alvo de upload já foi usado.")

    return Response(status_code=status.HTTP_204_NO_CONTENT)
