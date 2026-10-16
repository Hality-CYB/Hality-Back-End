"""Consentimento por finalidade (US-020 / TASK-108) — SQLite em memória.

Cobre os dois consentimentos independentes, a recusa de treino que preserva o
uso, a recusa de tratamento que bloqueia o cadastro, a revogação append-only,
a exigência de nova decisão em versão nova e o RBAC por titular/admin.
"""

import dataclasses
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.consentimentos import TERMOS, Finalidade
from app.models import AuditoriaAcesso, ConsentimentoEvento, User
from app.services import consentimento_service
from tests.conftest import CONSENTIMENTOS_CADASTRO

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
TERMOS_URL = "/api/v1/consentimentos/termos"
CONSENTIMENTOS_URL = "/api/v1/users/me/consentimentos"
SENHA = "SenhaSegura123!"

TRATAMENTO = {"finalidade": "health_data", "versao": "v1", "aceito": True}
TREINO_ACEITO = {"finalidade": "image_training", "versao": "v1", "aceito": True}
TREINO_RECUSADO = {"finalidade": "image_training", "versao": "v1", "aceito": False}


def _cadastro(email: str, consentimentos: list[dict] | None) -> dict:
    corpo = {"email": email, "password": SENHA, "name": "Titular Teste"}
    if consentimentos is not None:
        corpo["consentimentos"] = consentimentos
    return corpo


async def _login(client: AsyncClient, email: str) -> dict[str, str]:
    resposta = await client.post(LOGIN_URL, data={"username": email, "password": SENHA})
    return {"Authorization": f"Bearer {resposta.json()['access_token']}"}


async def _registrar_e_logar(
    client: AsyncClient, email: str, consentimentos: list[dict] | None = None
) -> dict[str, str]:
    resposta = await client.post(
        REGISTER_URL,
        json=_cadastro(
            email, CONSENTIMENTOS_CADASTRO if consentimentos is None else consentimentos
        ),
    )
    assert resposta.status_code == 201, resposta.text
    return await _login(client, email)


async def _eventos(db: AsyncSession, email: str | None = None) -> list[ConsentimentoEvento]:
    consulta = select(ConsentimentoEvento).order_by(ConsentimentoEvento.id)
    if email is not None:
        consulta = consulta.join(User, User.id == ConsentimentoEvento.titular_id).where(
            User.email == email
        )
    db_eventos = await db.scalars(consulta)
    return list(db_eventos)


async def _contar_usuarios(db: AsyncSession, email: str) -> int:
    return await db.scalar(select(func.count()).select_from(User).where(User.email == email))


def _estado(corpo: dict, finalidade: str) -> dict:
    return next(item for item in corpo["consentimentos"] if item["finalidade"] == finalidade)


# ---------------------------------------------------------------------------
# AC-020 — controles separados, sem marcação padrão, com versão do termo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_termos_sao_publicos_separados_e_sem_aceite_padrao(client: AsyncClient) -> None:
    resposta = await client.get(TERMOS_URL)

    assert resposta.status_code == 200
    itens = {item["finalidade"]: item for item in resposta.json()["itens"]}
    assert set(itens) == {"health_data", "image_training"}
    assert itens["health_data"]["obrigatorio"] is True
    assert itens["image_training"]["obrigatorio"] is False
    assert all(item["versao"] and item["texto"] for item in itens.values())
    assert all("aceito" not in item for item in itens.values())


@pytest.mark.asyncio
async def test_usuario_sem_decisao_nao_tem_consentimento_presumido(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _registrar_e_logar(client, "so_tratamento@hality.com", [TRATAMENTO])

    corpo = (await client.get(CONSENTIMENTOS_URL, headers=headers)).json()

    treino = _estado(corpo, "image_training")
    assert treino["aceito"] is None
    assert treino["vigente"] is False
    assert treino["requer_decisao"] is True
    assert _estado(corpo, "health_data")["vigente"] is True


# ---------------------------------------------------------------------------
# AC-021 — tratamento é obrigatório; treino é opcional
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "consentimentos",
    [
        None,
        [],
        [TREINO_ACEITO],
        [{**TRATAMENTO, "aceito": False}],
        [{**TRATAMENTO, "aceito": False}, TREINO_ACEITO],
    ],
    ids=["ausente", "vazio", "so_treino", "tratamento_recusado", "treino_aceito_sem_tratamento"],
)
async def test_cadastro_sem_aceite_do_tratamento_nao_cria_conta(
    client: AsyncClient, db_session: AsyncSession, consentimentos: list[dict] | None
) -> None:
    email = "bloqueado@hality.com"

    resposta = await client.post(REGISTER_URL, json=_cadastro(email, consentimentos))

    assert resposta.status_code == 422
    assert await _contar_usuarios(db_session, email) == 0
    assert await _eventos(db_session) == []


@pytest.mark.asyncio
async def test_recusar_treino_nao_impede_cadastro_nem_uso(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "recusa_treino@hality.com"

    headers = await _registrar_e_logar(client, email, [TRATAMENTO, TREINO_RECUSADO])

    me = await client.get("/api/v1/users/me", headers=headers)
    assert me.status_code == 200
    corpo = (await client.get(CONSENTIMENTOS_URL, headers=headers)).json()
    assert _estado(corpo, "health_data")["vigente"] is True
    treino = _estado(corpo, "image_training")
    assert treino["aceito"] is False
    assert treino["vigente"] is False
    assert treino["requer_decisao"] is False  # recusou na versão vigente: decisão tomada
    usuario = await db_session.scalar(select(User).where(User.email == email))
    assert not await consentimento_service.finalidade_vigente(
        db_session, usuario.id, Finalidade.IMAGE_TRAINING
    )
    assert await consentimento_service.finalidade_vigente(
        db_session, usuario.id, Finalidade.HEALTH_DATA
    )


@pytest.mark.asyncio
async def test_cadastro_com_versao_desatualizada_nao_cria_conta(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "versao_velha@hality.com"

    resposta = await client.post(
        REGISTER_URL, json=_cadastro(email, [{**TRATAMENTO, "versao": "v0"}])
    )

    assert resposta.status_code == 409
    assert await _contar_usuarios(db_session, email) == 0


@pytest.mark.asyncio
async def test_cadastro_com_finalidade_repetida_e_rejeitado(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "repetida@hality.com"

    resposta = await client.post(
        REGISTER_URL, json=_cadastro(email, [TRATAMENTO, {**TRATAMENTO, "aceito": False}])
    )

    assert resposta.status_code == 422
    assert await _contar_usuarios(db_session, email) == 0


@pytest.mark.asyncio
async def test_cadastro_com_finalidade_desconhecida_e_rejeitado(client: AsyncClient) -> None:
    resposta = await client.post(
        REGISTER_URL,
        json=_cadastro("desconhecida@hality.com", [TRATAMENTO, {**TRATAMENTO, "finalidade": "x"}]),
    )

    assert resposta.status_code == 422


# ---------------------------------------------------------------------------
# AC-022 — cada decisão grava titular, finalidade, versão, hora, origem e ator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cadastro_grava_um_evento_por_finalidade_com_origem_e_ator(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "eventos@hality.com"
    await _registrar_e_logar(client, email, [TRATAMENTO, TREINO_RECUSADO])

    usuario = await db_session.scalar(select(User).where(User.email == email))
    eventos = await _eventos(db_session, email)

    assert [(e.finalidade, e.versao, e.aceito) for e in eventos] == [
        ("health_data", "v1", True),
        ("image_training", "v1", False),
    ]
    for evento in eventos:
        assert evento.titular_id == usuario.id
        assert evento.ator_id == usuario.id
        assert evento.ator_papel == "paciente"
        assert evento.origem == "registro"
        assert evento.registrado_em is not None
        assert evento.referencia_coleta  # correlation id da coleta


@pytest.mark.asyncio
async def test_referencia_da_coleta_usa_o_correlation_id_enviado(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _registrar_e_logar(client, "ref@hality.com")

    await client.post(
        CONSENTIMENTOS_URL, json=TREINO_ACEITO, headers={**headers, "X-Correlation-ID": "coleta-42"}
    )

    ultimo = (await _eventos(db_session, "ref@hality.com"))[-1]
    assert ultimo.referencia_coleta == "coleta-42"
    assert ultimo.origem == "perfil"


@pytest.mark.asyncio
async def test_revogacao_nao_sobrescreve_o_evento_anterior(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "revoga@hality.com"
    headers = await _registrar_e_logar(client, email, [TRATAMENTO, TREINO_ACEITO])
    antes = await _eventos(db_session, email)
    primeiro_treino = antes[1]
    aceito_original, registrado_original = primeiro_treino.aceito, primeiro_treino.registrado_em

    resposta = await client.post(CONSENTIMENTOS_URL, json=TREINO_RECUSADO, headers=headers)

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["recorded_at"] is not None
    treino = _estado(corpo, "image_training")
    assert treino["aceito"] is False and treino["vigente"] is False
    depois = await _eventos(db_session, email)
    assert len(depois) == len(antes) + 1
    await db_session.refresh(primeiro_treino)
    assert primeiro_treino.aceito is aceito_original is True
    assert primeiro_treino.registrado_em == registrado_original
    assert depois[-1].aceito is False and depois[-1].id > primeiro_treino.id


@pytest.mark.asyncio
async def test_revogar_treino_nao_altera_o_tratamento_e_da_para_aceitar_de_novo(
    client: AsyncClient,
) -> None:
    headers = await _registrar_e_logar(
        client, "independentes@hality.com", [TRATAMENTO, TREINO_ACEITO]
    )

    revogado = (await client.post(CONSENTIMENTOS_URL, json=TREINO_RECUSADO, headers=headers)).json()
    assert _estado(revogado, "health_data")["vigente"] is True
    assert _estado(revogado, "image_training")["vigente"] is False

    reaceito = (await client.post(CONSENTIMENTOS_URL, json=TREINO_ACEITO, headers=headers)).json()
    assert _estado(reaceito, "image_training")["vigente"] is True
    assert _estado(reaceito, "health_data")["vigente"] is True


@pytest.mark.asyncio
async def test_post_com_versao_desatualizada_ou_finalidade_invalida_nao_grava(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "post_invalido@hality.com"
    headers = await _registrar_e_logar(client, email)
    total = len(await _eventos(db_session, email))

    velha = await client.post(
        CONSENTIMENTOS_URL, json={**TREINO_ACEITO, "versao": "v0"}, headers=headers
    )
    invalida = await client.post(
        CONSENTIMENTOS_URL, json={**TREINO_ACEITO, "finalidade": "outra"}, headers=headers
    )
    sem_campo = await client.post(
        CONSENTIMENTOS_URL, json={"finalidade": "image_training"}, headers=headers
    )

    assert velha.status_code == 409
    assert invalida.status_code == 422
    assert sem_campo.status_code == 422
    assert len(await _eventos(db_session, email)) == total


@pytest.mark.asyncio
async def test_endpoints_de_consentimento_exigem_autenticacao(client: AsyncClient) -> None:
    assert (await client.get(CONSENTIMENTOS_URL)).status_code == 401
    assert (await client.post(CONSENTIMENTOS_URL, json=TREINO_ACEITO)).status_code == 401


# ---------------------------------------------------------------------------
# Versão nova do termo exige nova decisão
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_versao_nova_do_termo_exige_nova_decisao(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = "versao_nova@hality.com"
    headers = await _registrar_e_logar(client, email, [TRATAMENTO, TREINO_ACEITO])
    usuario = await db_session.scalar(select(User).where(User.email == email))

    monkeypatch.setitem(
        TERMOS,
        Finalidade.IMAGE_TRAINING,
        dataclasses.replace(TERMOS[Finalidade.IMAGE_TRAINING], versao="v2"),
    )

    corpo = (await client.get(CONSENTIMENTOS_URL, headers=headers)).json()
    treino = _estado(corpo, "image_training")
    assert treino["versao_vigente"] == "v2"
    assert treino["versao_decidida"] == "v1"
    assert treino["vigente"] is False  # o aceite de v1 não vale para v2
    assert treino["requer_decisao"] is True
    assert _estado(corpo, "health_data")["vigente"] is True  # outra finalidade não muda
    assert not await consentimento_service.finalidade_vigente(
        db_session, usuario.id, Finalidade.IMAGE_TRAINING
    )

    antiga = await client.post(CONSENTIMENTOS_URL, json=TREINO_ACEITO, headers=headers)
    assert antiga.status_code == 409

    nova = await client.post(
        CONSENTIMENTOS_URL, json={**TREINO_ACEITO, "versao": "v2"}, headers=headers
    )
    assert nova.status_code == 200
    assert _estado(nova.json(), "image_training")["vigente"] is True


# ---------------------------------------------------------------------------
# RBAC — titular só vê/decide o próprio; admin só lê
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cada_titular_ve_apenas_o_proprio_estado(client: AsyncClient) -> None:
    com_treino = await _registrar_e_logar(client, "a@hality.com", [TRATAMENTO, TREINO_ACEITO])
    sem_treino = await _registrar_e_logar(client, "b@hality.com", [TRATAMENTO])

    a = (await client.get(CONSENTIMENTOS_URL, headers=com_treino)).json()
    b = (await client.get(CONSENTIMENTOS_URL, headers=sem_treino)).json()

    assert _estado(a, "image_training")["vigente"] is True
    assert _estado(b, "image_training")["vigente"] is False


@pytest.mark.asyncio
async def test_payload_nao_aceita_titular_para_decidir_por_outro(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _registrar_e_logar(client, "vitima@hality.com")
    outro = await _registrar_e_logar(client, "atacante@hality.com")
    vitima = await db_session.scalar(select(User).where(User.email == "vitima@hality.com"))

    resposta = await client.post(
        CONSENTIMENTOS_URL, json={**TREINO_ACEITO, "titular_id": str(vitima.id)}, headers=outro
    )

    assert resposta.status_code == 422
    assert [e.finalidade for e in await _eventos(db_session, "vitima@hality.com")] == [
        "health_data"
    ]


async def _admin_logado(client: AsyncClient, db: AsyncSession, email: str) -> dict[str, str]:
    headers = await _registrar_e_logar(client, email)
    usuario = await db.scalar(select(User).where(User.email == email))
    usuario.role = "admin"
    await db.commit()
    return headers


@pytest.mark.asyncio
async def test_admin_le_o_estado_de_um_titular_e_a_leitura_e_auditada(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _registrar_e_logar(client, "titular@hality.com", [TRATAMENTO, TREINO_ACEITO])
    titular = await db_session.scalar(select(User).where(User.email == "titular@hality.com"))
    admin = await _admin_logado(client, db_session, "admin@hality.com")

    resposta = await client.get(
        f"/api/v1/admin/usuarios/{titular.id}/consentimentos", headers=admin
    )

    assert resposta.status_code == 200
    assert _estado(resposta.json(), "image_training")["vigente"] is True
    leitura = await db_session.scalar(
        select(AuditoriaAcesso).where(AuditoriaAcesso.acao == "consentimento.consultar")
    )
    assert leitura is not None and leitura.recurso_id == str(titular.id)


@pytest.mark.asyncio
async def test_admin_nao_grava_consentimento_pelo_titular_e_inexistente_da_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _registrar_e_logar(client, "alvo@hality.com")
    alvo = await db_session.scalar(select(User).where(User.email == "alvo@hality.com"))
    admin = await _admin_logado(client, db_session, "admin2@hality.com")
    total = len(await _eventos(db_session, "alvo@hality.com"))

    escrita = await client.post(
        f"/api/v1/admin/usuarios/{alvo.id}/consentimentos", json=TREINO_ACEITO, headers=admin
    )
    inexistente = await client.get(
        f"/api/v1/admin/usuarios/{uuid.uuid4()}/consentimentos", headers=admin
    )

    assert escrita.status_code == 405
    assert inexistente.status_code == 404
    assert len(await _eventos(db_session, "alvo@hality.com")) == total


@pytest.mark.asyncio
async def test_nao_admin_nao_le_consentimento_de_outro_usuario(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    alvo_headers = await _registrar_e_logar(client, "alvo2@hality.com")
    alvo = await db_session.scalar(select(User).where(User.email == "alvo2@hality.com"))
    outro = await _registrar_e_logar(client, "curioso@hality.com")

    for headers in (outro, alvo_headers):
        resposta = await client.get(
            f"/api/v1/admin/usuarios/{alvo.id}/consentimentos", headers=headers
        )
        assert resposta.status_code == 403


# ---------------------------------------------------------------------------
# Auditoria — mesma transação, sem texto clínico, idempotente
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cada_evento_gera_exatamente_uma_auditoria_sem_texto(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "auditoria@hality.com"
    headers = await _registrar_e_logar(client, email, [TRATAMENTO, TREINO_ACEITO])
    await client.post(CONSENTIMENTOS_URL, json=TREINO_RECUSADO, headers=headers)

    eventos = await _eventos(db_session, email)
    auditorias = list(
        await db_session.scalars(
            select(AuditoriaAcesso)
            .where(AuditoriaAcesso.acao == "consentimento.registrar")
            .order_by(AuditoriaAcesso.id)
        )
    )

    assert [a.recurso_id for a in auditorias] == [str(e.id) for e in eventos]
    assert all(a.recurso_tipo == "consentimento" and a.resultado == "sucesso" for a in auditorias)
    for auditoria in auditorias:
        assert set(auditoria.metadados) == {"finalidade", "versao", "aceito", "origem", "titular"}
        assert not any(termo.texto in str(auditoria.metadados) for termo in TERMOS.values())


@pytest.mark.asyncio
async def test_idempotency_key_nao_duplica_o_evento(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "idem@hality.com"
    headers = {**(await _registrar_e_logar(client, email)), "Idempotency-Key": "chave-consent-1"}
    total = len(await _eventos(db_session, email))

    primeira = await client.post(CONSENTIMENTOS_URL, json=TREINO_ACEITO, headers=headers)
    repetida = await client.post(CONSENTIMENTOS_URL, json=TREINO_ACEITO, headers=headers)

    assert primeira.status_code == 200
    assert repetida.status_code == 409
    assert len(await _eventos(db_session, email)) == total + 1


# ---------------------------------------------------------------------------
# Revogação do tratamento barra operações novas com dados de saúde
# ---------------------------------------------------------------------------

TRATAMENTO_REVOGADO = {**TRATAMENTO, "aceito": False}


@pytest.mark.asyncio
async def test_exigir_tratamento_nao_revogado_segue_a_decisao_mais_recente(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "revoga_tratamento@hality.com"
    headers = await _registrar_e_logar(client, email)
    usuario = await db_session.scalar(select(User).where(User.email == email))

    await consentimento_service.exigir_tratamento_nao_revogado(db_session, usuario.id)

    await client.post(CONSENTIMENTOS_URL, json=TRATAMENTO_REVOGADO, headers=headers)
    with pytest.raises(consentimento_service.TratamentoRevogadoError):
        await consentimento_service.exigir_tratamento_nao_revogado(db_session, usuario.id)

    await client.post(CONSENTIMENTOS_URL, json=TRATAMENTO, headers=headers)
    await consentimento_service.exigir_tratamento_nao_revogado(db_session, usuario.id)


@pytest.mark.asyncio
async def test_revogar_so_o_treino_nao_barra_dados_de_saude(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    email = "so_treino_revogado@hality.com"
    headers = await _registrar_e_logar(client, email, [TRATAMENTO, TREINO_ACEITO])
    usuario = await db_session.scalar(select(User).where(User.email == email))

    await client.post(CONSENTIMENTOS_URL, json=TREINO_RECUSADO, headers=headers)

    await consentimento_service.exigir_tratamento_nao_revogado(db_session, usuario.id)


@pytest.mark.asyncio
async def test_quem_nao_decidiu_ainda_nao_e_barrado(db_session: AsyncSession) -> None:
    usuario = User(name="Sem Decisao", email="sem_decisao@hality.com", hashed_password="x")
    db_session.add(usuario)
    await db_session.commit()

    await consentimento_service.exigir_tratamento_nao_revogado(db_session, usuario.id)
