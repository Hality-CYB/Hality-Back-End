"""Cadastro de paciente novo pelo profissional — POST /pacientes."""

from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.users import password_helper
from app.main import app
from app.models import ConsentimentoEvento, EmailOutbox, IdentityAction, PacienteProfissional, User
from app.schemas.paciente import SENHA_PADRAO_PACIENTE
from app.services.identity_token_service import INVITATION, _token_for
from tests.conftest import CenarioAdmin, autenticar_como, executar_no_banco

client = TestClient(app)

AUTH_HEADERS = {"Authorization": "Bearer fake-token"}
PACIENTES_URL = "/api/v1/pacientes"


def _payload(cenario: CenarioAdmin, **extras: Any) -> dict[str, Any]:
    return {
        "nome": "Paciente Novo",
        "email": cenario.email("novo"),
        "telefone": "(51) 98888-7777",
        **extras,
    }


def _buscar_por_email(email: str) -> tuple[User | None, list[PacienteProfissional]]:
    async def _buscar(db: AsyncSession) -> tuple[User | None, list[PacienteProfissional]]:
        usuario = await db.scalar(select(User).where(User.email == email))
        if usuario is None:
            return None, []
        vinculos = await db.scalars(
            select(PacienteProfissional).where(PacienteProfissional.paciente_id == usuario.id)
        )
        return usuario, list(vinculos)

    return executar_no_banco(_buscar)


def test_profissional_cadastra_paciente_ja_vinculado(cenario_admin: CenarioAdmin) -> None:
    autenticar_como(cenario_admin.profissional)
    payload = _payload(cenario_admin)

    resposta = client.post(PACIENTES_URL, json=payload, headers=AUTH_HEADERS)

    assert resposta.status_code == status.HTTP_201_CREATED
    corpo = resposta.json()
    assert corpo["paciente_nome"] == "Paciente Novo"
    assert corpo["paciente_email"] == payload["email"]
    assert corpo["ativo"] is True
    assert corpo["role"] == "paciente"
    assert corpo["convite_pendente"] is True
    assert "senha" not in corpo and "hashed_password" not in corpo

    paciente, vinculos = _buscar_por_email(payload["email"])
    assert paciente is not None
    assert str(paciente.id) == corpo["paciente_id"]
    assert vinculos[0].id == corpo["id"]
    assert paciente.role == "paciente"
    assert paciente.is_active is False
    assert paciente.phone == "(51) 98888-7777"
    assert [(v.profissional_id, v.ativo) for v in vinculos] == [
        (cenario_admin.profissional.id, True)
    ]

    async def _buscar_outbox(db: AsyncSession) -> EmailOutbox | None:
        return await db.scalar(
            select(EmailOutbox).where(EmailOutbox.recipient_email == payload["email"])
        )

    outbox = executar_no_banco(_buscar_outbox)
    assert outbox is not None
    assert outbox.purpose == INVITATION
    assert outbox.status == "queued"


def test_cadastro_sem_senha_nao_grava_senha_padrao_e_emite_convite(
    cenario_admin: CenarioAdmin,
) -> None:
    autenticar_como(cenario_admin.profissional)
    payload = _payload(cenario_admin)

    resposta = client.post(PACIENTES_URL, json=payload, headers=AUTH_HEADERS)

    assert resposta.status_code == status.HTTP_201_CREATED
    paciente, _ = _buscar_por_email(payload["email"])
    assert paciente is not None
    assert not password_helper.verify_and_update(SENHA_PADRAO_PACIENTE, paciente.hashed_password)[0]


def test_cadastro_rejeita_senha_padrao_com_422(cenario_admin: CenarioAdmin) -> None:
    autenticar_como(cenario_admin.profissional)
    payload = _payload(cenario_admin, senha=SENHA_PADRAO_PACIENTE)

    resposta = client.post(PACIENTES_URL, json=payload, headers=AUTH_HEADERS)

    assert resposta.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    paciente, _ = _buscar_por_email(payload["email"])
    assert paciente is None


def test_paciente_aceita_convite_com_nova_senha_e_consentimentos(
    cenario_admin: CenarioAdmin,
) -> None:
    autenticar_como(cenario_admin.profissional)
    payload = _payload(cenario_admin)

    resposta = client.post(PACIENTES_URL, json=payload, headers=AUTH_HEADERS)
    assert resposta.status_code == status.HTTP_201_CREATED

    async def _buscar_acao_e_outbox(
        db: AsyncSession,
    ) -> tuple[IdentityAction | None, EmailOutbox | None]:
        acao = await db.scalar(
            select(IdentityAction)
            .join(User, User.id == IdentityAction.user_id)
            .where(
                User.email == payload["email"],
                IdentityAction.purpose == INVITATION,
            )
        )
        outbox = await db.scalar(
            select(EmailOutbox).where(EmailOutbox.recipient_email == payload["email"])
        )
        return acao, outbox

    acao, outbox = executar_no_banco(_buscar_acao_e_outbox)
    assert acao is not None and outbox is not None
    token = _token_for(acao.id, acao.purpose)

    # Rejeita senha padrão no aceite
    resp_padrao = client.post(
        "/api/v1/auth/invitation/confirm",
        json={"token": token, "senha": "hality1234"},
    )
    assert resp_padrao.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # Aceite válido com consentimento obrigatório de dados de saúde
    aceite = client.post(
        "/api/v1/auth/invitation/confirm",
        json={
            "token": token,
            "senha": "NovaSenhaSegura123!",
            "consentimentos": [
                {"finalidade": "health_data", "versao": "v1", "aceito": True},
                {"finalidade": "image_training", "versao": "v1", "aceito": False},
            ],
        },
    )
    assert aceite.status_code == status.HTTP_204_NO_CONTENT

    paciente, _ = _buscar_por_email(payload["email"])
    assert paciente is not None
    assert paciente.is_active is True
    assert password_helper.verify_and_update("NovaSenhaSegura123!", paciente.hashed_password)[0]

    # Outbox consumida
    _, outbox_depois = executar_no_banco(_buscar_acao_e_outbox)
    assert outbox_depois is not None and outbox_depois.status == "consumed"

    # Consentimentos gravados com origem convite
    eventos = _eventos_de_consentimento(payload["email"])
    assert len(eventos) == 2
    assert {e.origem for e in eventos} == {"convite"}

    # Tentativa de reutilizar token falha com 400
    reuso = client.post(
        "/api/v1/auth/invitation/confirm",
        json={"token": token, "senha": "OutraSenhaValida123!"},
    )
    assert reuso.status_code == status.HTTP_400_BAD_REQUEST
    assert reuso.json()["detail"] == "TOKEN_DE_CONVITE_INVALIDO"

    # Paciente consegue logar com a nova senha
    login = client.post(
        "/api/v1/auth/login",
        data={"username": payload["email"], "password": "NovaSenhaSegura123!"},
    )
    assert login.status_code == status.HTTP_200_OK


def test_paciente_cadastrado_aparece_na_listagem_do_profissional(
    cenario_admin: CenarioAdmin,
) -> None:
    autenticar_como(cenario_admin.profissional)
    criado = client.post(PACIENTES_URL, json=_payload(cenario_admin), headers=AUTH_HEADERS)

    resposta = client.get(f"{PACIENTES_URL}/{criado.json()['paciente_id']}", headers=AUTH_HEADERS)

    assert resposta.status_code == status.HTTP_200_OK


def test_email_ja_cadastrado_retorna_409(cenario_admin: CenarioAdmin) -> None:
    autenticar_como(cenario_admin.profissional)
    payload = _payload(cenario_admin, email=cenario_admin.paciente.email.upper())

    resposta = client.post(PACIENTES_URL, json=payload, headers=AUTH_HEADERS)

    assert resposta.status_code == status.HTTP_409_CONFLICT
    assert resposta.json()["detail"] == "e-mail já cadastrado"
    _, vinculos = _buscar_por_email(cenario_admin.paciente.email)
    assert vinculos == []


@pytest.mark.parametrize("papel", ["paciente", "admin"])
def test_so_profissional_pode_cadastrar(cenario_admin: CenarioAdmin, papel: str) -> None:
    autenticar_como(getattr(cenario_admin, papel))
    payload = _payload(cenario_admin)

    resposta = client.post(PACIENTES_URL, json=payload, headers=AUTH_HEADERS)

    assert resposta.status_code == status.HTTP_403_FORBIDDEN
    assert _buscar_por_email(payload["email"])[0] is None


def test_sem_token_retorna_401(cenario_admin: CenarioAdmin) -> None:
    autenticar_como(cenario_admin.profissional)

    resposta = client.post(PACIENTES_URL, json=_payload(cenario_admin))

    assert resposta.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.parametrize(
    "extras",
    [
        {"senha": "curta"},
        {"nome": "A"},
        {"email": "nao-e-email"},
        {"role": "admin"},
        {"ativo": False},
    ],
)
def test_payload_invalido_retorna_422(cenario_admin: CenarioAdmin, extras: dict) -> None:
    autenticar_como(cenario_admin.profissional)

    resposta = client.post(
        PACIENTES_URL, json=_payload(cenario_admin, **extras), headers=AUTH_HEADERS
    )

    assert resposta.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def _eventos_de_consentimento(email: str) -> list[ConsentimentoEvento]:
    async def _buscar(db: AsyncSession) -> list[ConsentimentoEvento]:
        eventos = await db.scalars(
            select(ConsentimentoEvento)
            .join(User, User.id == ConsentimentoEvento.titular_id)
            .where(User.email == email)
        )
        return list(eventos)

    return executar_no_banco(_buscar)


def test_cadastro_pelo_profissional_nao_registra_consentimento_pelo_paciente(
    cenario_admin: CenarioAdmin,
) -> None:
    autenticar_como(cenario_admin.profissional)
    payload = _payload(cenario_admin)

    resposta = client.post(PACIENTES_URL, json=payload, headers=AUTH_HEADERS)

    assert resposta.status_code == status.HTTP_201_CREATED
    assert _eventos_de_consentimento(payload["email"]) == []


def test_profissional_nao_consegue_enviar_consentimento_em_nome_do_paciente(
    cenario_admin: CenarioAdmin,
) -> None:
    autenticar_como(cenario_admin.profissional)
    payload = _payload(
        cenario_admin,
        consentimentos=[{"finalidade": "health_data", "versao": "v1", "aceito": True}],
    )

    resposta = client.post(PACIENTES_URL, json=payload, headers=AUTH_HEADERS)

    assert resposta.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    paciente, _ = _buscar_por_email(payload["email"])
    assert paciente is None


def _token_do_convite(email: str) -> str:
    async def _buscar(db: AsyncSession) -> IdentityAction | None:
        return await db.scalar(
            select(IdentityAction)
            .join(User, User.id == IdentityAction.user_id)
            .where(User.email == email, IdentityAction.purpose == INVITATION)
        )

    acao = executar_no_banco(_buscar)
    assert acao is not None
    return _token_for(acao.id, acao.purpose)


@pytest.mark.parametrize(
    ("consentimentos", "status_esperado", "detalhe"),
    [
        (
            [
                {"finalidade": "health_data", "versao": "v1", "aceito": True},
                {"finalidade": "health_data", "versao": "v1", "aceito": True},
            ],
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "finalidade de consentimento repetida",
        ),
        (
            [{"finalidade": "health_data", "versao": "v0", "aceito": True}],
            status.HTTP_409_CONFLICT,
            "versão do termo desatualizada; versão vigente: v1",
        ),
    ],
    ids=["finalidade_repetida", "versao_desatualizada"],
)
def test_aceite_com_consentimento_invalido_nao_consome_o_convite(
    cenario_admin: CenarioAdmin,
    consentimentos: list[dict[str, Any]],
    status_esperado: int,
    detalhe: str,
) -> None:
    autenticar_como(cenario_admin.profissional)
    payload = _payload(cenario_admin)
    assert client.post(PACIENTES_URL, json=payload, headers=AUTH_HEADERS).status_code == 201
    token = _token_do_convite(payload["email"])

    recusado = client.post(
        "/api/v1/auth/invitation/confirm",
        json={"token": token, "senha": "SenhaForte!2026", "consentimentos": consentimentos},
    )
    assert recusado.status_code == status_esperado
    assert recusado.json()["detail"] == detalhe

    # O convite segue válido: a pessoa corrige o consentimento e aceita.
    aceito = client.post(
        "/api/v1/auth/invitation/confirm",
        json={
            "token": token,
            "senha": "SenhaForte!2026",
            "consentimentos": [{"finalidade": "health_data", "versao": "v1", "aceito": True}],
        },
    )
    assert aceito.status_code == status.HTTP_204_NO_CONTENT
    usuario, _ = _buscar_por_email(payload["email"])
    assert usuario is not None and usuario.is_active
