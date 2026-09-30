"""CRUD administrativo de usuários e profissionais (US-110) — Postgres real."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.users import current_active_user, password_helper
from app.db import user_queries
from app.main import app
from app.models import PacienteProfissional, Profissional, User
from tests.conftest import CenarioAdmin, autenticar_como, executar_no_banco

client = TestClient(app)

AUTH = {"Authorization": "Bearer fake-token"}
USUARIOS_URL = "/api/v1/admin/usuarios"
PROFISSIONAIS_URL = "/api/v1/admin/profissionais"


def _payload(cenario: CenarioAdmin, nome: str, role: str, **extras: object) -> dict:
    return {
        "nome": f"Novo {nome}",
        "email": cenario.email(nome),
        "telefone": "51999990000",
        "role": role,
        "senha": "SenhaInicial123",
        **extras,
    }


def _buscar_usuario_e_profissional(email: str) -> tuple[User | None, Profissional | None]:
    async def _buscar(db: AsyncSession) -> tuple[User | None, Profissional | None]:
        usuario = await db.scalar(select(User).where(User.email == email))
        if usuario is None:
            return None, None
        return usuario, await db.get(Profissional, usuario.id)

    return executar_no_banco(_buscar)


def _criar_vinculo(paciente: User, profissional: User, *, ativo: bool) -> None:
    async def _criar(db: AsyncSession) -> None:
        db.add(
            PacienteProfissional(
                paciente_id=paciente.id, profissional_id=profissional.id, ativo=ativo
            )
        )
        await db.commit()

    executar_no_banco(_criar)


def _assert_sem_segredos(corpo: dict) -> None:
    for campo in ("senha", "password", "hashed_password", "is_superuser", "is_verified"):
        assert campo not in corpo


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


def test_sem_token_retorna_401(cenario_admin: CenarioAdmin) -> None:
    assert client.get(USUARIOS_URL).status_code == 401


@pytest.mark.parametrize("perfil", ["admin", "superuser_sem_role_admin"])
def test_role_admin_ou_superuser_tem_acesso(cenario_admin: CenarioAdmin, perfil: str) -> None:
    autenticar_como(getattr(cenario_admin, perfil))

    assert client.get(USUARIOS_URL, headers=AUTH).status_code == 200


@pytest.mark.parametrize("perfil", ["paciente", "profissional"])
def test_quem_nao_e_admin_recebe_403(cenario_admin: CenarioAdmin, perfil: str) -> None:
    autenticar_como(getattr(cenario_admin, perfil))

    respostas = [
        client.get(USUARIOS_URL, headers=AUTH),
        client.get(f"{USUARIOS_URL}/{cenario_admin.paciente.id}", headers=AUTH),
        client.post(USUARIOS_URL, json=_payload(cenario_admin, "x", "admin"), headers=AUTH),
        client.patch(
            f"{USUARIOS_URL}/{cenario_admin.paciente.id}", json={"role": "admin"}, headers=AUTH
        ),
        client.patch(f"{PROFISSIONAIS_URL}/{cenario_admin.profissional.id}", json={}, headers=AUTH),
    ]

    assert [r.status_code for r in respostas] == [403] * len(respostas)
    assert _buscar_usuario_e_profissional(cenario_admin.email("x")) == (None, None)


# ---------------------------------------------------------------------------
# RBAC com JWT real (sem override de `current_active_user`)
# ---------------------------------------------------------------------------

SENHA_REAL = "SenhaReal123"


def _definir_senha_real(usuario: User) -> None:
    hashed_password = password_helper.hash(SENHA_REAL)

    async def _atualizar(db: AsyncSession) -> None:
        await db.execute(
            update(User).where(User.id == usuario.id).values(hashed_password=hashed_password)
        )
        await db.commit()

    executar_no_banco(_atualizar)


@pytest.mark.parametrize("perfil", ["admin", "superuser_sem_role_admin"])
def test_jwt_real_de_admin_ou_superuser_acessa_admin(
    cenario_admin: CenarioAdmin, perfil: str
) -> None:
    app.dependency_overrides.pop(current_active_user, None)
    usuario = getattr(cenario_admin, perfil)
    _definir_senha_real(usuario)

    login = client.post(
        "/api/v1/auth/login", data={"username": usuario.email, "password": SENHA_REAL}
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    resposta = client.get(USUARIOS_URL, headers={"Authorization": f"Bearer {token}"})

    assert resposta.status_code == 200


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer token-invalido"}])
def test_jwt_real_sem_token_ou_invalido_retorna_401(headers: dict) -> None:
    assert current_active_user not in app.dependency_overrides

    assert client.get(USUARIOS_URL, headers=headers).status_code == 401


# ---------------------------------------------------------------------------
# Listagem e detalhe
# ---------------------------------------------------------------------------


def test_listar_filtra_e_pagina_no_banco(cenario_admin: CenarioAdmin) -> None:
    busca = {"busca": cenario_admin.token}

    pagina = client.get(USUARIOS_URL, params={**busca, "limite": 4}, headers=AUTH)
    assert pagina.status_code == 200
    corpo = pagina.json()
    assert (corpo["total"], corpo["total_paginas"], len(corpo["itens"])) == (6, 2, 4)
    for item in corpo["itens"]:
        _assert_sem_segredos(item)

    segunda = client.get(USUARIOS_URL, params={**busca, "limite": 4, "pagina": 2}, headers=AUTH)
    assert len(segunda.json()["itens"]) == 2

    profissionais = client.get(
        USUARIOS_URL, params={**busca, "role": "profissional"}, headers=AUTH
    ).json()
    assert {item["id"] for item in profissionais["itens"]} == {
        str(cenario_admin.profissional.id),
        str(cenario_admin.profissional_sem_registro.id),
    }

    inativos = client.get(USUARIOS_URL, params={**busca, "ativo": False}, headers=AUTH).json()
    assert [item["id"] for item in inativos["itens"]] == [str(cenario_admin.paciente_inativo.id)]


@pytest.mark.parametrize(
    "params", [{"limite": 51}, {"limite": 0}, {"pagina": 0}, {"role": "patient"}]
)
def test_listar_parametros_invalidos_retorna_422(cenario_admin: CenarioAdmin, params: dict) -> None:
    assert client.get(USUARIOS_URL, params=params, headers=AUTH).status_code == 422


def test_detalhe_inclui_dados_de_profissional(cenario_admin: CenarioAdmin) -> None:
    resposta = client.get(f"{USUARIOS_URL}/{cenario_admin.profissional.id}", headers=AUTH)

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["role"] == "profissional"
    assert corpo["profissional"]["especialidade"] == "Periodontia"
    _assert_sem_segredos(corpo)

    paciente = client.get(f"{USUARIOS_URL}/{cenario_admin.paciente.id}", headers=AUTH).json()
    assert paciente["profissional"] is None


def test_detalhe_uuid_invalido_retorna_422(cenario_admin: CenarioAdmin) -> None:
    assert client.get(f"{USUARIOS_URL}/nao-e-uuid", headers=AUTH).status_code == 422


def test_detalhe_uuid_inexistente_retorna_404(cenario_admin: CenarioAdmin) -> None:
    assert client.get(f"{USUARIOS_URL}/{uuid.uuid4()}", headers=AUTH).status_code == 404


# ---------------------------------------------------------------------------
# Criação
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["paciente", "admin"])
def test_criar_usuario_sem_dados_de_profissional(cenario_admin: CenarioAdmin, role: str) -> None:
    payload = _payload(cenario_admin, f"novo{role}", role)

    resposta = client.post(USUARIOS_URL, json=payload, headers=AUTH)

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert (corpo["role"], corpo["ativo"], corpo["profissional"]) == (role, True, None)
    _assert_sem_segredos(corpo)

    usuario, profissional = _buscar_usuario_e_profissional(payload["email"])
    assert profissional is None
    assert usuario.hashed_password != payload["senha"]
    assert password_helper.verify_and_update(payload["senha"], usuario.hashed_password)[0]
    assert usuario.is_superuser is False


def test_usuario_criado_pelo_admin_consegue_logar(cenario_admin: CenarioAdmin) -> None:
    payload = _payload(cenario_admin, "login", "paciente")
    client.post(USUARIOS_URL, json=payload, headers=AUTH)

    resposta = client.post(
        "/api/v1/auth/login", data={"username": payload["email"], "password": payload["senha"]}
    )

    assert resposta.status_code == 200


def test_criar_profissional_cria_user_e_profissional(cenario_admin: CenarioAdmin) -> None:
    payload = _payload(
        cenario_admin,
        "dentista",
        "profissional",
        profissional={"registro_profissional": "CRO-RS 1", "especialidade": "Ortodontia"},
    )

    resposta = client.post(USUARIOS_URL, json=payload, headers=AUTH)

    assert resposta.status_code == 201
    assert resposta.json()["profissional"] == {
        "registro_profissional": "CRO-RS 1",
        "especialidade": "Ortodontia",
        "vinculado_hality": False,
    }
    usuario, profissional = _buscar_usuario_e_profissional(payload["email"])
    assert usuario.role == "profissional"
    assert profissional.especialidade == "Ortodontia"


def test_criar_profissional_sem_dados_opcionais_cria_linha_vazia(
    cenario_admin: CenarioAdmin,
) -> None:
    payload = _payload(cenario_admin, "dentista", "profissional")

    resposta = client.post(USUARIOS_URL, json=payload, headers=AUTH)

    assert resposta.status_code == 201
    _, profissional = _buscar_usuario_e_profissional(payload["email"])
    assert profissional is not None
    assert profissional.registro_profissional is None


def test_criar_profissional_faz_rollback_se_profissional_falhar(
    cenario_admin: CenarioAdmin, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _falhar(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(user_queries, "criar_profissional", _falhar)
    payload = _payload(cenario_admin, "rollback", "profissional")

    with pytest.raises(RuntimeError, match="falha simulada"):
        client.post(USUARIOS_URL, json=payload, headers=AUTH)

    assert _buscar_usuario_e_profissional(payload["email"]) == (None, None)


def test_dados_de_profissional_com_outra_role_retorna_422(cenario_admin: CenarioAdmin) -> None:
    payload = _payload(cenario_admin, "x", "paciente", profissional={"especialidade": "X"})

    assert client.post(USUARIOS_URL, json=payload, headers=AUTH).status_code == 422


def test_email_duplicado_retorna_409(cenario_admin: CenarioAdmin) -> None:
    payload = _payload(cenario_admin, "dup", "paciente")

    primeira = client.post(USUARIOS_URL, json=payload, headers=AUTH)
    segunda = client.post(USUARIOS_URL, json=payload, headers=AUTH)

    assert (primeira.status_code, segunda.status_code) == (201, 409)


def test_email_duplicado_com_caixa_diferente_retorna_409(cenario_admin: CenarioAdmin) -> None:
    payload = _payload(cenario_admin, "caixa", "paciente", email=cenario_admin.paciente.email)
    payload["email"] = payload["email"].upper()

    assert client.post(USUARIOS_URL, json=payload, headers=AUTH).status_code == 409


def test_senha_curta_retorna_422(cenario_admin: CenarioAdmin) -> None:
    payload = _payload(cenario_admin, "curta", "paciente", senha="1234567")

    assert client.post(USUARIOS_URL, json=payload, headers=AUTH).status_code == 422


@pytest.mark.parametrize(
    "extra",
    [
        {"id": str(uuid.uuid4())},
        {"hashed_password": "hash"},
        {"is_superuser": True},
        {"is_verified": True},
        {"created_at": "2026-01-01T00:00:00Z"},
    ],
)
def test_criar_com_campo_proibido_retorna_422(cenario_admin: CenarioAdmin, extra: dict) -> None:
    payload = _payload(cenario_admin, "proibido", "paciente", **extra)

    assert client.post(USUARIOS_URL, json=payload, headers=AUTH).status_code == 422
    assert _buscar_usuario_e_profissional(payload["email"]) == (None, None)


# ---------------------------------------------------------------------------
# Atualização
# ---------------------------------------------------------------------------


def test_desativar_usuario(cenario_admin: CenarioAdmin) -> None:
    resposta = client.patch(
        f"{USUARIOS_URL}/{cenario_admin.paciente.id}", json={"ativo": False}, headers=AUTH
    )

    assert resposta.status_code == 200
    assert resposta.json()["ativo"] is False
    usuario, _ = _buscar_usuario_e_profissional(cenario_admin.paciente.email)
    assert usuario.is_active is False


def test_atualizar_usuario_inexistente_retorna_404(cenario_admin: CenarioAdmin) -> None:
    resposta = client.patch(f"{USUARIOS_URL}/{uuid.uuid4()}", json={"nome": "X Y"}, headers=AUTH)

    assert resposta.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "outro@hality.com"},
        {"senha": "OutraSenha123"},
        {"is_superuser": True},
        {"hashed_password": "hash"},
        {"nome": None},
        {"ativo": None},
        {"role": None},
        {"role": "superadmin"},
    ],
)
def test_atualizar_com_campo_proibido_ou_invalido_retorna_422(
    cenario_admin: CenarioAdmin, payload: dict
) -> None:
    resposta = client.patch(
        f"{USUARIOS_URL}/{cenario_admin.paciente.id}", json=payload, headers=AUTH
    )

    assert resposta.status_code == 422


def test_alterar_role_paciente_para_admin(cenario_admin: CenarioAdmin) -> None:
    resposta = client.patch(
        f"{USUARIOS_URL}/{cenario_admin.paciente.id}", json={"role": "admin"}, headers=AUTH
    )

    assert resposta.status_code == 200
    usuario, _ = _buscar_usuario_e_profissional(cenario_admin.paciente.email)
    assert (usuario.role, usuario.is_superuser) == ("admin", False)


def test_paciente_para_profissional_cria_registro(cenario_admin: CenarioAdmin) -> None:
    resposta = client.patch(
        f"{USUARIOS_URL}/{cenario_admin.paciente.id}",
        json={"role": "profissional"},
        headers=AUTH,
    )

    assert resposta.status_code == 200
    assert resposta.json()["profissional"] is not None
    _, profissional = _buscar_usuario_e_profissional(cenario_admin.paciente.email)
    assert profissional is not None


def test_paciente_com_vinculo_ativo_nao_troca_de_role(cenario_admin: CenarioAdmin) -> None:
    _criar_vinculo(cenario_admin.paciente, cenario_admin.profissional, ativo=True)

    resposta = client.patch(
        f"{USUARIOS_URL}/{cenario_admin.paciente.id}", json={"role": "admin"}, headers=AUTH
    )

    assert resposta.status_code == 409
    usuario, _ = _buscar_usuario_e_profissional(cenario_admin.paciente.email)
    assert usuario.role == "paciente"


def test_profissional_sem_vinculos_troca_de_role_e_remove_registro(
    cenario_admin: CenarioAdmin,
) -> None:
    resposta = client.patch(
        f"{USUARIOS_URL}/{cenario_admin.profissional.id}", json={"role": "paciente"}, headers=AUTH
    )

    assert resposta.status_code == 200
    assert resposta.json()["profissional"] is None
    usuario, profissional = _buscar_usuario_e_profissional(cenario_admin.profissional.email)
    assert (usuario.role, profissional) == ("paciente", None)


@pytest.mark.parametrize("vinculo_ativo", [True, False])
def test_profissional_com_vinculos_nao_troca_de_role(
    cenario_admin: CenarioAdmin, vinculo_ativo: bool
) -> None:
    _criar_vinculo(cenario_admin.paciente, cenario_admin.profissional, ativo=vinculo_ativo)

    resposta = client.patch(
        f"{USUARIOS_URL}/{cenario_admin.profissional.id}", json={"role": "admin"}, headers=AUTH
    )

    assert resposta.status_code == 409
    usuario, profissional = _buscar_usuario_e_profissional(cenario_admin.profissional.email)
    assert usuario.role == "profissional"
    assert profissional is not None


# ---------------------------------------------------------------------------
# Dados de profissional
# ---------------------------------------------------------------------------


def test_atualizar_dados_de_profissional(cenario_admin: CenarioAdmin) -> None:
    resposta = client.patch(
        f"{PROFISSIONAIS_URL}/{cenario_admin.profissional.id}",
        json={"registro_profissional": "CRO-RS 999", "vinculado_hality": True},
        headers=AUTH,
    )

    assert resposta.status_code == 200
    assert resposta.json()["profissional"] == {
        "registro_profissional": "CRO-RS 999",
        "especialidade": "Periodontia",
        "vinculado_hality": True,
    }


def test_atualizar_dados_de_profissional_de_nao_profissional_retorna_404(
    cenario_admin: CenarioAdmin,
) -> None:
    resposta = client.patch(
        f"{PROFISSIONAIS_URL}/{cenario_admin.paciente.id}",
        json={"especialidade": "X"},
        headers=AUTH,
    )

    assert resposta.status_code == 404


@pytest.mark.parametrize("payload", [{"role": "admin"}, {"vinculado_hality": None}])
def test_atualizar_dados_de_profissional_invalidos_retorna_422(
    cenario_admin: CenarioAdmin, payload: dict
) -> None:
    resposta = client.patch(
        f"{PROFISSIONAIS_URL}/{cenario_admin.profissional.id}", json=payload, headers=AUTH
    )

    assert resposta.status_code == 422
