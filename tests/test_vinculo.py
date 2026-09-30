import asyncio
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request, status
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.users import current_active_user
from app.core.config import get_settings
from app.main import app
from app.models import PacienteProfissional, Profissional, User
from tests.conftest import CenarioAdmin, autenticar_como

client = TestClient(app)

AUTH_HEADERS = {"Authorization": "Bearer fake-token"}
VINCULOS_URL = "/api/v1/vinculos"


async def _abrir_sessao_teste() -> tuple[AsyncSession, object]:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return session_factory(), engine


@dataclass
class Cenario:
    profissional: User
    outro_profissional: User
    paciente_ok: User
    paciente_inativo: User
    user_ids: list[uuid.UUID] = field(default_factory=list)


async def _gerar_id_livre(db: AsyncSession) -> uuid.UUID:
    for _ in range(10):
        candidato = uuid4()

        if await db.get(User, candidato) is None:
            return candidato

    raise RuntimeError("nao foi possivel gerar id unico para usuario auxiliar")


async def _criar_usuario(
    db: AsyncSession,
    *,
    role: str,
    is_active: bool = True,
) -> User:
    token = uuid4().hex
    usuario = User(
        id=await _gerar_id_livre(db),
        name=f"Usuario Teste {token[:8]}",
        email=f"vinculo.{role}.{token}@hality.com",
        hashed_password="x",
        role=role,
        is_active=is_active,
    )
    db.add(usuario)
    await db.flush()
    return usuario


async def _preparar_cenario() -> Cenario:
    db, engine = await _abrir_sessao_teste()

    try:
        async with db:
            profissional = await _criar_usuario(db, role="profissional")
            db.add(Profissional(usuario_id=profissional.id))

            outro_profissional = await _criar_usuario(db, role="profissional")
            db.add(Profissional(usuario_id=outro_profissional.id))

            paciente_ok = await _criar_usuario(db, role="paciente")
            paciente_inativo = await _criar_usuario(db, role="paciente", is_active=False)

            await db.commit()

            return Cenario(
                profissional=profissional,
                outro_profissional=outro_profissional,
                paciente_ok=paciente_ok,
                paciente_inativo=paciente_inativo,
                user_ids=[
                    profissional.id,
                    outro_profissional.id,
                    paciente_ok.id,
                    paciente_inativo.id,
                ],
            )
    finally:
        await engine.dispose()


async def _limpar_cenario(cenario: Cenario) -> None:
    db, engine = await _abrir_sessao_teste()

    try:
        async with db:
            await db.execute(
                delete(PacienteProfissional).where(
                    PacienteProfissional.paciente_id.in_(cenario.user_ids)
                    | PacienteProfissional.profissional_id.in_(cenario.user_ids)
                )
            )
            await db.execute(
                delete(Profissional).where(Profissional.usuario_id.in_(cenario.user_ids))
            )
            await db.execute(delete(User).where(User.id.in_(cenario.user_ids)))
            await db.commit()
    finally:
        await engine.dispose()


async def _contar_vinculos_ativos(paciente_id: uuid.UUID, profissional_id: uuid.UUID) -> int:
    db, engine = await _abrir_sessao_teste()

    try:
        async with db:
            resultado = await db.execute(
                select(PacienteProfissional).where(
                    PacienteProfissional.paciente_id == paciente_id,
                    PacienteProfissional.profissional_id == profissional_id,
                    PacienteProfissional.ativo.is_(True),
                )
            )
            return len(resultado.scalars().all())
    finally:
        await engine.dispose()


def _autenticar_como(usuario: User) -> None:
    async def _dependencia(request: Request) -> User:
        if not request.headers.get("authorization"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="sem token")

        return usuario

    app.dependency_overrides[current_active_user] = _dependencia


@pytest.fixture
def cenario() -> Iterator[Cenario]:
    dados = asyncio.run(_preparar_cenario())
    _autenticar_como(dados.profissional)

    try:
        yield dados
    finally:
        app.dependency_overrides.pop(current_active_user, None)
        asyncio.run(_limpar_cenario(dados))


def test_criar_vinculo_sem_token_retorna_401(cenario: Cenario) -> None:
    response = client.post(VINCULOS_URL, json={"paciente_email": cenario.paciente_ok.email})

    assert response.status_code == 401


def test_criar_vinculo_como_paciente_retorna_403(cenario: Cenario) -> None:
    _autenticar_como(cenario.paciente_ok)

    response = client.post(
        VINCULOS_URL,
        json={"paciente_email": cenario.paciente_ok.email},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 403


def test_criar_vinculo_sucesso(cenario: Cenario) -> None:
    response = client.post(
        VINCULOS_URL,
        json={"paciente_email": cenario.paciente_ok.email},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 201
    corpo = response.json()
    assert corpo["paciente_id"] == str(cenario.paciente_ok.id)
    assert corpo["paciente_email"] == cenario.paciente_ok.email
    assert corpo["ativo"] is True


def test_criar_vinculo_paciente_inexistente_retorna_422(cenario: Cenario) -> None:
    response = client.post(
        VINCULOS_URL,
        json={"paciente_email": f"nao.existe.{uuid4().hex}@hality.com"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 422


def test_criar_vinculo_paciente_inativo_retorna_422(cenario: Cenario) -> None:
    response = client.post(
        VINCULOS_URL,
        json={"paciente_email": cenario.paciente_inativo.email},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 422


def test_criar_vinculo_com_email_de_profissional_retorna_422(cenario: Cenario) -> None:
    response = client.post(
        VINCULOS_URL,
        json={"paciente_email": cenario.outro_profissional.email},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 422


def test_criar_vinculo_repetido_retorna_409_e_preserva_uma_linha_ativa(
    cenario: Cenario,
) -> None:
    primeira = client.post(
        VINCULOS_URL,
        json={"paciente_email": cenario.paciente_ok.email},
        headers=AUTH_HEADERS,
    )
    segunda = client.post(
        VINCULOS_URL,
        json={"paciente_email": cenario.paciente_ok.email},
        headers=AUTH_HEADERS,
    )

    assert primeira.status_code == 201
    assert segunda.status_code == 409

    total_ativos = asyncio.run(
        _contar_vinculos_ativos(cenario.paciente_ok.id, cenario.profissional.id)
    )
    assert total_ativos == 1


def test_criar_vinculo_concorrente_apenas_um_sucesso(cenario: Cenario) -> None:
    barreira = threading.Barrier(2)
    resultados: list[int] = []

    def _requisitar() -> None:
        barreira.wait()
        resposta = client.post(
            VINCULOS_URL,
            json={"paciente_email": cenario.paciente_ok.email},
            headers=AUTH_HEADERS,
        )
        resultados.append(resposta.status_code)

    threads = [threading.Thread(target=_requisitar) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(resultados) == [201, 409]

    total_ativos = asyncio.run(
        _contar_vinculos_ativos(cenario.paciente_ok.id, cenario.profissional.id)
    )
    assert total_ativos == 1


def test_desvincular_paciente_nao_vinculado_retorna_404(cenario: Cenario) -> None:
    response = client.delete(
        f"{VINCULOS_URL}/{cenario.paciente_ok.id}",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 404


def test_desvincular_preserva_historico_e_bloqueia_acesso_futuro(cenario: Cenario) -> None:
    client.post(
        VINCULOS_URL,
        json={"paciente_email": cenario.paciente_ok.email},
        headers=AUTH_HEADERS,
    )

    resposta_delete = client.delete(
        f"{VINCULOS_URL}/{cenario.paciente_ok.id}",
        headers=AUTH_HEADERS,
    )
    assert resposta_delete.status_code == 204

    # Desvincular de novo falha: não há mais vínculo ativo (não apagou a linha,
    # só encerrou — por isso não reaparece como "vinculado" para o profissional).
    resposta_delete_novamente = client.delete(
        f"{VINCULOS_URL}/{cenario.paciente_ok.id}",
        headers=AUTH_HEADERS,
    )
    assert resposta_delete_novamente.status_code == 404

    listagem = client.get(VINCULOS_URL, headers=AUTH_HEADERS)
    assert listagem.status_code == 200
    assert cenario.paciente_ok.email not in [
        item["paciente_email"] for item in listagem.json()["itens"]
    ]

    # a linha original continua no banco, só marcada como encerrada.
    preservado = asyncio.run(_verificar_linha_preservada(cenario))
    assert preservado is True


async def _verificar_linha_preservada(cenario: Cenario) -> bool:
    db, engine = await _abrir_sessao_teste()

    try:
        async with db:
            vinculo = await db.scalar(
                select(PacienteProfissional).where(
                    PacienteProfissional.paciente_id == cenario.paciente_ok.id,
                    PacienteProfissional.profissional_id == cenario.profissional.id,
                )
            )
            return (
                vinculo is not None and vinculo.ativo is False and vinculo.encerrado_em is not None
            )
    finally:
        await engine.dispose()


def test_listar_vinculos_isola_por_profissional(cenario: Cenario) -> None:
    client.post(
        VINCULOS_URL,
        json={"paciente_email": cenario.paciente_ok.email},
        headers=AUTH_HEADERS,
    )

    listagem_dono = client.get(VINCULOS_URL, headers=AUTH_HEADERS)
    assert listagem_dono.status_code == 200
    assert [item["paciente_email"] for item in listagem_dono.json()["itens"]] == [
        cenario.paciente_ok.email
    ]

    _autenticar_como(cenario.outro_profissional)
    listagem_outro = client.get(VINCULOS_URL, headers=AUTH_HEADERS)
    assert listagem_outro.status_code == 200
    assert listagem_outro.json()["itens"] == []


def test_paciente_do_registro_publico_pode_ser_vinculado(cenario_admin: CenarioAdmin) -> None:
    email = cenario_admin.email("registrado")
    registro = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "SenhaSegura123!", "name": "Paciente Registrado"},
    )
    assert registro.status_code == 201
    assert registro.json()["role"] == "paciente"

    autenticar_como(cenario_admin.profissional)
    response = client.post(VINCULOS_URL, json={"paciente_email": email}, headers=AUTH_HEADERS)

    assert response.status_code == 201
    assert response.json()["paciente_email"] == email
