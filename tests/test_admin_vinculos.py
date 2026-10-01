"""Administração dos vínculos paciente-profissional (US-110) — Postgres real."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models import PacienteProfissional, User
from tests.conftest import CenarioAdmin, autenticar_como, executar_no_banco

client = TestClient(app)

AUTH = {"Authorization": "Bearer fake-token"}
VINCULOS_URL = "/api/v1/admin/vinculos"


def _criar(paciente_id: uuid.UUID, profissional_id: uuid.UUID):
    return client.post(
        VINCULOS_URL,
        json={"paciente_id": str(paciente_id), "profissional_id": str(profissional_id)},
        headers=AUTH,
    )


def _criar_ok(cenario: CenarioAdmin) -> dict:
    resposta = _criar(cenario.paciente.id, cenario.profissional.id)
    assert resposta.status_code == 201
    return resposta.json()


def _buscar_vinculo(vinculo_id: int) -> PacienteProfissional | None:
    async def _buscar(db: AsyncSession) -> PacienteProfissional | None:
        return await db.get(PacienteProfissional, vinculo_id)

    return executar_no_banco(_buscar)


def test_profissional_nao_administra_vinculos(cenario_admin: CenarioAdmin) -> None:
    autenticar_como(cenario_admin.profissional)

    assert _criar(cenario_admin.paciente.id, cenario_admin.profissional.id).status_code == 403
    assert client.get(VINCULOS_URL, headers=AUTH).status_code == 403


def test_sem_token_retorna_401(cenario_admin: CenarioAdmin) -> None:
    assert client.get(VINCULOS_URL).status_code == 401


def test_criar_vinculo_valido(cenario_admin: CenarioAdmin) -> None:
    corpo = _criar_ok(cenario_admin)

    assert corpo["paciente_id"] == str(cenario_admin.paciente.id)
    assert corpo["profissional_id"] == str(cenario_admin.profissional.id)
    assert corpo["paciente_nome"] == cenario_admin.paciente.name
    assert corpo["profissional_nome"] == cenario_admin.profissional.name
    assert (corpo["ativo"], corpo["encerrado_em"]) == (True, None)


def test_criar_vinculo_duplicado_retorna_409(cenario_admin: CenarioAdmin) -> None:
    _criar_ok(cenario_admin)

    resposta = _criar(cenario_admin.paciente.id, cenario_admin.profissional.id)

    assert resposta.status_code == 409


@pytest.mark.parametrize(
    ("paciente", "profissional"),
    [
        ("inexistente", "profissional"),
        ("paciente_inativo", "profissional"),
        ("admin", "profissional"),
        ("paciente", "inexistente"),
        ("paciente", "admin"),
        ("paciente", "profissional_sem_registro"),
    ],
)
def test_criar_vinculo_com_entidade_invalida_retorna_422(
    cenario_admin: CenarioAdmin, paciente: str, profissional: str
) -> None:
    def _id(nome: str) -> uuid.UUID:
        return uuid.uuid4() if nome == "inexistente" else getattr(cenario_admin, nome).id

    resposta = _criar(_id(paciente), _id(profissional))

    assert resposta.status_code == 422


def test_criar_vinculo_com_campo_extra_retorna_422(cenario_admin: CenarioAdmin) -> None:
    resposta = client.post(
        VINCULOS_URL,
        json={
            "paciente_id": str(cenario_admin.paciente.id),
            "profissional_id": str(cenario_admin.profissional.id),
            "ativo": False,
        },
        headers=AUTH,
    )

    assert resposta.status_code == 422


def test_listar_filtra_por_profissional_e_estado(cenario_admin: CenarioAdmin) -> None:
    vinculo = _criar_ok(cenario_admin)
    filtro = {"profissional_id": str(cenario_admin.profissional.id)}

    ativos = client.get(VINCULOS_URL, params={**filtro, "ativo": True}, headers=AUTH).json()
    inativos = client.get(VINCULOS_URL, params={**filtro, "ativo": False}, headers=AUTH).json()

    assert [item["id"] for item in ativos["itens"]] == [vinculo["id"]]
    assert (ativos["total"], ativos["total_paginas"]) == (1, 1)
    assert inativos["itens"] == []


def test_patch_ativo_false_encerra_e_true_reativa(cenario_admin: CenarioAdmin) -> None:
    vinculo_id = _criar_ok(cenario_admin)["id"]
    url = f"{VINCULOS_URL}/{vinculo_id}"

    encerrado = client.patch(url, json={"ativo": False}, headers=AUTH)
    assert encerrado.status_code == 200
    assert encerrado.json()["ativo"] is False
    assert encerrado.json()["encerrado_em"] is not None

    reativado = client.patch(url, json={"ativo": True}, headers=AUTH)
    assert reativado.status_code == 200
    assert (reativado.json()["ativo"], reativado.json()["encerrado_em"]) == (True, None)


def test_reativar_com_outro_vinculo_ativo_retorna_409(cenario_admin: CenarioAdmin) -> None:
    antigo_id = _criar_ok(cenario_admin)["id"]
    client.delete(f"{VINCULOS_URL}/{antigo_id}", headers=AUTH)
    _criar_ok(cenario_admin)

    resposta = client.patch(f"{VINCULOS_URL}/{antigo_id}", json={"ativo": True}, headers=AUTH)

    assert resposta.status_code == 409
    assert _buscar_vinculo(antigo_id).ativo is False


def _desativar_usuario(usuario_id: uuid.UUID) -> None:
    async def _desativar(db: AsyncSession) -> None:
        await db.execute(update(User).where(User.id == usuario_id).values(is_active=False))
        await db.commit()

    executar_no_banco(_desativar)


@pytest.mark.parametrize("perfil", ["paciente", "profissional"])
def test_reativar_com_entidade_desativada_retorna_422(
    cenario_admin: CenarioAdmin, perfil: str
) -> None:
    vinculo_id = _criar_ok(cenario_admin)["id"]
    client.delete(f"{VINCULOS_URL}/{vinculo_id}", headers=AUTH)
    _desativar_usuario(getattr(cenario_admin, perfil).id)

    resposta = client.patch(f"{VINCULOS_URL}/{vinculo_id}", json={"ativo": True}, headers=AUTH)

    assert resposta.status_code == 422
    vinculo = _buscar_vinculo(vinculo_id)
    assert vinculo.ativo is False
    assert vinculo.encerrado_em is not None


@pytest.mark.parametrize(
    "payload",
    [
        {"ativo": False, "paciente_id": str(uuid.uuid4())},
        {"ativo": False, "profissional_id": str(uuid.uuid4())},
        {"ativo": False, "encerrado_em": "2026-01-01T00:00:00Z"},
        {"ativo": None},
        {},
    ],
)
def test_patch_com_campo_nao_permitido_retorna_422(
    cenario_admin: CenarioAdmin, payload: dict
) -> None:
    vinculo_id = _criar_ok(cenario_admin)["id"]

    resposta = client.patch(f"{VINCULOS_URL}/{vinculo_id}", json=payload, headers=AUTH)

    assert resposta.status_code == 422
    assert _buscar_vinculo(vinculo_id).ativo is True


def test_patch_vinculo_inexistente_retorna_404(cenario_admin: CenarioAdmin) -> None:
    resposta = client.patch(f"{VINCULOS_URL}/999999999", json={"ativo": False}, headers=AUTH)

    assert resposta.status_code == 404


def test_delete_faz_soft_delete_e_preserva_linha(cenario_admin: CenarioAdmin) -> None:
    vinculo_id = _criar_ok(cenario_admin)["id"]

    resposta = client.delete(f"{VINCULOS_URL}/{vinculo_id}", headers=AUTH)

    assert resposta.status_code == 204
    vinculo = _buscar_vinculo(vinculo_id)
    assert vinculo is not None
    assert vinculo.ativo is False
    assert vinculo.encerrado_em is not None

    assert client.delete(f"{VINCULOS_URL}/{vinculo_id}", headers=AUTH).status_code == 404
