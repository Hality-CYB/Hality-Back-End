import asyncio
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
from app.models import (
    Anamnese,
    ClassificacaoDiagnostico,
    Diagnostico,
    Imagem,
    PacienteProfissional,
    Profissional,
    User,
)

client = TestClient(app)

AUTH_HEADERS = {"Authorization": "Bearer fake-token"}
PACIENTES_URL = "/api/v1/pacientes"
VERSAO_QUESTIONARIO_TESTE = "2026-08-v1"
DATA_D1 = datetime(2099, 1, 1, 10, 0, tzinfo=UTC)
DATA_D2 = datetime(2099, 2, 1, 10, 0, tzinfo=UTC)
DATA_D3 = datetime(2099, 3, 1, 10, 0, tzinfo=UTC)


async def _abrir_sessao_teste() -> tuple[AsyncSession, object]:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return session_factory(), engine


@dataclass
class Cenario:
    token: str
    profissional_a: User
    profissional_b: User
    admin: User
    ana_1: User
    ana_2: User
    bruno: User
    carla: User
    daniel: User
    elisa: User
    fabio: User
    url_imagem: str
    resposta_sensivel: str
    user_ids: list[uuid.UUID] = field(default_factory=list)
    diagnostico_ids: list[int] = field(default_factory=list)


async def _gerar_id_livre(db: AsyncSession) -> uuid.UUID:
    for _ in range(10):
        candidato = uuid4()

        if await db.get(User, candidato) is None:
            return candidato

    raise RuntimeError("nao foi possivel gerar id unico para usuario auxiliar")


async def _criar_usuario(
    db: AsyncSession,
    *,
    nome: str,
    role: str,
    is_active: bool = True,
) -> User:
    usuario = User(
        id=await _gerar_id_livre(db),
        name=nome,
        email=f"paciente.{role}.{uuid4().hex}@hality.com",
        hashed_password="hash-secreto-nao-exposto",
        phone="(51) 99999-0000",
        role=role,
        is_active=is_active,
    )
    db.add(usuario)
    await db.flush()
    return usuario


async def _criar_diagnostico(
    db: AsyncSession,
    *,
    paciente: User,
    data: datetime,
    status_diagnostico: str,
    classificacao_id: int | None,
    resposta_sensivel: str,
) -> Diagnostico:
    anamnese = Anamnese(
        paciente_id=paciente.id,
        id_versao_questionario=VERSAO_QUESTIONARIO_TESTE,
        respostas=[
            {
                "pergunta_id": "teste_pacientes",
                "enunciado": "Teste pacientes",
                "tipo": "text",
                "valor": resposta_sensivel,
            }
        ],
    )
    db.add(anamnese)
    await db.flush()

    diagnostico = Diagnostico(
        paciente_id=paciente.id,
        anamnese_id=anamnese.id,
        classificacao_id=classificacao_id,
        escala_saburra=2 if classificacao_id is not None else None,
        confianca_ia=0.9 if classificacao_id is not None else None,
        status=status_diagnostico,
        data_diagnostico=data,
    )
    db.add(diagnostico)
    await db.flush()
    return diagnostico


async def _classificacao_por_ordem(db: AsyncSession, ordem: int) -> int:
    classificacao_id = await db.scalar(
        select(ClassificacaoDiagnostico.id).where(ClassificacaoDiagnostico.ordem == ordem)
    )
    assert classificacao_id is not None
    return classificacao_id


async def _preparar_cenario() -> Cenario:
    db, engine = await _abrir_sessao_teste()
    token = uuid4().hex[:12]

    try:
        async with db:
            profissional_a = await _criar_usuario(db, nome=f"Prof A {token}", role="profissional")
            profissional_b = await _criar_usuario(
                db, nome=f"Zeca Prof B {token}", role="profissional"
            )
            db.add(Profissional(usuario_id=profissional_a.id))
            db.add(Profissional(usuario_id=profissional_b.id))
            admin = await _criar_usuario(db, nome=f"Admin {token}", role="admin")

            ana_1 = await _criar_usuario(db, nome=f"Ana {token}", role="paciente")
            ana_2 = await _criar_usuario(db, nome=f"Ana {token}", role="paciente")
            bruno = await _criar_usuario(db, nome=f"Bruno {token}", role="paciente")
            carla = await _criar_usuario(
                db, nome=f"Carla {token}", role="paciente", is_active=False
            )
            daniel = await _criar_usuario(db, nome=f"Daniel {token}", role="paciente")
            elisa = await _criar_usuario(db, nome=f"Elisa {token}", role="paciente")
            fabio = await _criar_usuario(db, nome=f"Fabio {token}", role="paciente")
            await db.flush()

            for paciente in (ana_1, ana_2, bruno, carla, elisa):
                db.add(
                    PacienteProfissional(paciente_id=paciente.id, profissional_id=profissional_a.id)
                )

            for paciente in (daniel, elisa):
                db.add(
                    PacienteProfissional(paciente_id=paciente.id, profissional_id=profissional_b.id)
                )

            db.add(
                PacienteProfissional(
                    paciente_id=fabio.id,
                    profissional_id=profissional_a.id,
                    ativo=False,
                    encerrado_em=datetime.now(UTC),
                )
            )
            db.add(
                PacienteProfissional(
                    paciente_id=profissional_b.id,
                    profissional_id=profissional_a.id,
                )
            )
            await db.flush()

            nivel_1 = await _classificacao_por_ordem(db, 1)
            nivel_2 = await _classificacao_por_ordem(db, 2)
            nivel_3 = await _classificacao_por_ordem(db, 3)
            resposta_sensivel = f"RESPOSTA_SENSIVEL_{token}"
            url_imagem = f"/api/v1/diagnosticos/imagens/teste-{token}.png"

            d1 = await _criar_diagnostico(
                db,
                paciente=ana_1,
                data=DATA_D1,
                status_diagnostico="concluido",
                classificacao_id=nivel_1,
                resposta_sensivel=resposta_sensivel,
            )
            d2 = await _criar_diagnostico(
                db,
                paciente=ana_1,
                data=DATA_D2,
                status_diagnostico="concluido",
                classificacao_id=nivel_3,
                resposta_sensivel=resposta_sensivel,
            )
            db.add(
                Imagem(
                    diagnostico_id=d2.id,
                    url_arquivo=url_imagem,
                    ordem=1,
                    parametros_captura={"origem": "teste"},
                )
            )
            d3 = await _criar_diagnostico(
                db,
                paciente=bruno,
                data=DATA_D1,
                status_diagnostico="concluido",
                classificacao_id=nivel_2,
                resposta_sensivel=resposta_sensivel,
            )
            d4 = await _criar_diagnostico(
                db,
                paciente=bruno,
                data=DATA_D3,
                status_diagnostico="processando",
                classificacao_id=None,
                resposta_sensivel=resposta_sensivel,
            )

            await db.commit()

            return Cenario(
                token=token,
                profissional_a=profissional_a,
                profissional_b=profissional_b,
                admin=admin,
                ana_1=ana_1,
                ana_2=ana_2,
                bruno=bruno,
                carla=carla,
                daniel=daniel,
                elisa=elisa,
                fabio=fabio,
                url_imagem=url_imagem,
                resposta_sensivel=resposta_sensivel,
                user_ids=[
                    profissional_a.id,
                    profissional_b.id,
                    admin.id,
                    ana_1.id,
                    ana_2.id,
                    bruno.id,
                    carla.id,
                    daniel.id,
                    elisa.id,
                    fabio.id,
                ],
                diagnostico_ids=[d1.id, d2.id, d3.id, d4.id],
            )
    finally:
        await engine.dispose()


async def _limpar_cenario(cenario: Cenario) -> None:
    db, engine = await _abrir_sessao_teste()

    try:
        async with db:
            await db.execute(
                delete(Imagem).where(Imagem.diagnostico_id.in_(cenario.diagnostico_ids))
            )
            await db.execute(
                delete(Diagnostico).where(Diagnostico.paciente_id.in_(cenario.user_ids))
            )
            await db.execute(delete(Anamnese).where(Anamnese.paciente_id.in_(cenario.user_ids)))
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


def _autenticar_como(usuario: User) -> None:
    async def _dependencia(request: Request) -> User:
        if not request.headers.get("authorization"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="sem token")

        return usuario

    app.dependency_overrides[current_active_user] = _dependencia


@pytest.fixture
def cenario() -> Iterator[Cenario]:
    dados = asyncio.run(_preparar_cenario())
    _autenticar_como(dados.profissional_a)

    try:
        yield dados
    finally:
        app.dependency_overrides.pop(current_active_user, None)
        asyncio.run(_limpar_cenario(dados))


def _listar(**params: object) -> dict:
    response = client.get(PACIENTES_URL, params=params, headers=AUTH_HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def _ids(corpo: dict) -> list[str]:
    return [item["id"] for item in corpo["itens"]]


def _item(corpo: dict, usuario: User) -> dict:
    return next(item for item in corpo["itens"] if item["id"] == str(usuario.id))


def _anas_ordenadas(cenario: Cenario) -> list[str]:
    return [str(i) for i in sorted([cenario.ana_1.id, cenario.ana_2.id])]


def test_listar_pacientes_sem_token_retorna_401(cenario: Cenario) -> None:
    response = client.get(PACIENTES_URL)

    assert response.status_code == 401


def test_detalhe_paciente_sem_token_retorna_401(cenario: Cenario) -> None:
    response = client.get(f"{PACIENTES_URL}/{cenario.ana_1.id}")

    assert response.status_code == 401


def test_paciente_nao_pode_listar_nem_detalhar(cenario: Cenario) -> None:
    _autenticar_como(cenario.ana_1)

    listagem = client.get(PACIENTES_URL, headers=AUTH_HEADERS)
    detalhe = client.get(f"{PACIENTES_URL}/{cenario.ana_1.id}", headers=AUTH_HEADERS)

    assert listagem.status_code == 403
    assert detalhe.status_code == 403


def test_profissional_a_lista_somente_pacientes_vinculados_ativos(cenario: Cenario) -> None:
    corpo = _listar()

    assert _ids(corpo) == [
        *_anas_ordenadas(cenario),
        str(cenario.bruno.id),
        str(cenario.carla.id),
        str(cenario.elisa.id),
    ]
    assert corpo["total"] == 5
    assert corpo["pagina"] == 1
    assert corpo["limite"] == 20
    assert corpo["total_paginas"] == 1
    assert str(cenario.daniel.id) not in _ids(corpo)
    assert str(cenario.fabio.id) not in _ids(corpo)
    assert str(cenario.profissional_b.id) not in _ids(corpo)


def test_profissional_b_lista_seus_proprios_pacientes(cenario: Cenario) -> None:
    _autenticar_como(cenario.profissional_b)

    corpo = _listar()

    assert _ids(corpo) == [str(cenario.daniel.id), str(cenario.elisa.id)]
    assert corpo["total"] == 2


def test_pacientes_cruzados_entre_dois_profissionais(cenario: Cenario) -> None:
    corpo_a = _listar()
    _autenticar_como(cenario.profissional_b)
    corpo_b = _listar()

    assert str(cenario.elisa.id) in _ids(corpo_a)
    assert str(cenario.elisa.id) in _ids(corpo_b)
    assert str(cenario.daniel.id) not in _ids(corpo_a)
    assert str(cenario.ana_1.id) not in _ids(corpo_b)


def test_profissional_a_nao_acessa_detalhe_de_paciente_exclusivo_de_b(cenario: Cenario) -> None:
    fora_do_escopo = client.get(f"{PACIENTES_URL}/{cenario.daniel.id}", headers=AUTH_HEADERS)
    inexistente = client.get(f"{PACIENTES_URL}/{uuid4()}", headers=AUTH_HEADERS)

    assert fora_do_escopo.status_code == 404
    assert inexistente.status_code == 404
    assert fora_do_escopo.json() == inexistente.json()


def test_vinculo_inativo_nao_autoriza_acesso(cenario: Cenario) -> None:
    response = client.get(f"{PACIENTES_URL}/{cenario.fabio.id}", headers=AUTH_HEADERS)

    assert response.status_code == 404
    assert str(cenario.fabio.id) not in _ids(_listar(busca="Fabio"))


def test_usuario_nao_paciente_vinculado_nao_aparece(cenario: Cenario) -> None:
    response = client.get(
        f"{PACIENTES_URL}/{cenario.profissional_b.id}",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 404
    assert _listar(busca="Zeca")["itens"] == []


def test_admin_lista_todos_os_pacientes_e_somente_role_paciente(cenario: Cenario) -> None:
    _autenticar_como(cenario.admin)

    corpo = _listar(busca=cenario.token)

    assert _ids(corpo) == [
        *_anas_ordenadas(cenario),
        str(cenario.bruno.id),
        str(cenario.carla.id),
        str(cenario.daniel.id),
        str(cenario.elisa.id),
        str(cenario.fabio.id),
    ]
    assert corpo["total"] == 7
    assert str(cenario.profissional_a.id) not in _ids(corpo)
    assert str(cenario.profissional_b.id) not in _ids(corpo)
    assert str(cenario.admin.id) not in _ids(corpo)


def test_admin_acessa_detalhe_com_todos_os_vinculos(cenario: Cenario) -> None:
    _autenticar_como(cenario.admin)

    response = client.get(f"{PACIENTES_URL}/{cenario.elisa.id}", headers=AUTH_HEADERS)

    assert response.status_code == 200
    profissionais = {vinculo["profissional_id"] for vinculo in response.json()["vinculos"]}
    assert profissionais == {str(cenario.profissional_a.id), str(cenario.profissional_b.id)}


def test_admin_acessa_paciente_sem_vinculo_ativo(cenario: Cenario) -> None:
    _autenticar_como(cenario.admin)

    response = client.get(f"{PACIENTES_URL}/{cenario.fabio.id}", headers=AUTH_HEADERS)

    assert response.status_code == 200
    vinculos = response.json()["vinculos"]
    assert len(vinculos) == 1
    assert vinculos[0]["ativo"] is False
    assert vinculos[0]["encerrado_em"] is not None


def test_profissional_ve_somente_seu_vinculo_no_detalhe(cenario: Cenario) -> None:
    response = client.get(f"{PACIENTES_URL}/{cenario.elisa.id}", headers=AUTH_HEADERS)

    assert response.status_code == 200
    vinculos = response.json()["vinculos"]
    assert [vinculo["profissional_id"] for vinculo in vinculos] == [str(cenario.profissional_a.id)]
    assert vinculos[0]["profissional_nome"] == cenario.profissional_a.name
    assert vinculos[0]["ativo"] is True


def test_busca_por_nome_sem_diferenciar_maiusculas(cenario: Cenario) -> None:
    corpo = _listar(busca="BRUNO")

    assert _ids(corpo) == [str(cenario.bruno.id)]
    assert corpo["total"] == 1
    assert corpo["total_paginas"] == 1


def test_busca_por_email(cenario: Cenario) -> None:
    corpo = _listar(busca=cenario.bruno.email)

    assert _ids(corpo) == [str(cenario.bruno.id)]


def test_busca_trata_curingas_como_texto(cenario: Cenario) -> None:
    corpo = _listar(busca="%")

    assert corpo["itens"] == []
    assert corpo["total"] == 0
    assert corpo["total_paginas"] == 0


def test_busca_vazia_retorna_todos_do_escopo(cenario: Cenario) -> None:
    sem_busca = _listar()

    assert _ids(_listar(busca="")) == _ids(sem_busca)
    assert _ids(_listar(busca="   ")) == _ids(sem_busca)


def test_paginacao_total_e_total_paginas(cenario: Cenario) -> None:
    pagina_1 = _listar(pagina=1, limite=2)
    pagina_2 = _listar(pagina=2, limite=2)
    pagina_3 = _listar(pagina=3, limite=2)
    pagina_4 = _listar(pagina=4, limite=2)

    assert _ids(pagina_1) == _anas_ordenadas(cenario)
    assert _ids(pagina_2) == [str(cenario.bruno.id), str(cenario.carla.id)]
    assert _ids(pagina_3) == [str(cenario.elisa.id)]
    assert pagina_4["itens"] == []

    for corpo in (pagina_1, pagina_2, pagina_3, pagina_4):
        assert corpo["total"] == 5
        assert corpo["total_paginas"] == 3
        assert corpo["limite"] == 2


def test_ordenacao_estavel_desempata_por_id(cenario: Cenario) -> None:
    primeira = _listar(busca="Ana", ordem="nome_asc")
    segunda = _listar(busca="Ana", ordem="nome_asc")

    assert _ids(primeira) == _anas_ordenadas(cenario)
    assert _ids(primeira) == _ids(segunda)


def test_limite_maximo_aceito(cenario: Cenario) -> None:
    corpo = _listar(limite=50)

    assert corpo["limite"] == 50
    assert corpo["total"] == 5


@pytest.mark.parametrize(
    "params",
    [
        {"limite": 51},
        {"limite": 0},
        {"pagina": 0},
        {"ordem": "nome_desc"},
        {"busca": "x" * 101},
    ],
)
def test_filtros_invalidos_retornam_400(cenario: Cenario, params: dict) -> None:
    response = client.get(PACIENTES_URL, params=params, headers=AUTH_HEADERS)

    assert response.status_code == 400


def test_resumo_de_diagnosticos_na_listagem(cenario: Cenario) -> None:
    corpo = _listar()

    ana = _item(corpo, cenario.ana_1)
    assert ana["total_diagnosticos"] == 2
    assert datetime.fromisoformat(ana["ultimo_diagnostico_em"]) == DATA_D2
    assert ana["ultimo_nivel"] == 3

    bruno = _item(corpo, cenario.bruno)
    assert bruno["total_diagnosticos"] == 2
    assert datetime.fromisoformat(bruno["ultimo_diagnostico_em"]) == DATA_D3
    assert bruno["ultimo_nivel"] is None

    carla = _item(corpo, cenario.carla)
    assert carla["total_diagnosticos"] == 0
    assert carla["ultimo_diagnostico_em"] is None
    assert carla["ultimo_nivel"] is None
    assert carla["ativo"] is False


def test_item_da_listagem_contem_somente_dados_minimos(cenario: Cenario) -> None:
    response = client.get(PACIENTES_URL, headers=AUTH_HEADERS)

    ana = _item(response.json(), cenario.ana_1)
    assert set(ana) == {
        "id",
        "nome",
        "email",
        "telefone",
        "ativo",
        "total_diagnosticos",
        "ultimo_diagnostico_em",
        "ultimo_nivel",
    }
    assert ana["nome"] == cenario.ana_1.name
    assert ana["email"] == cenario.ana_1.email
    assert ana["telefone"] == cenario.ana_1.phone
    assert ana["ativo"] is True
    assert "password" not in response.text
    assert "hash-secreto-nao-exposto" not in response.text


def test_detalhe_retorna_resumo_sem_dados_sensiveis(cenario: Cenario) -> None:
    response = client.get(f"{PACIENTES_URL}/{cenario.ana_1.id}", headers=AUTH_HEADERS)

    assert response.status_code == 200
    corpo = response.json()
    assert set(corpo) == {
        "id",
        "nome",
        "email",
        "telefone",
        "ativo",
        "total_diagnosticos",
        "ultimo_diagnostico_em",
        "ultimo_nivel",
        "vinculos",
        "diagnosticos",
    }
    assert corpo["id"] == str(cenario.ana_1.id)
    assert corpo["total_diagnosticos"] == 2
    assert datetime.fromisoformat(corpo["ultimo_diagnostico_em"]) == DATA_D2
    assert corpo["ultimo_nivel"] == 3
    assert [item["classificacao"]["ordem"] for item in corpo["diagnosticos"]["itens"]] == [3, 1]
    assert corpo["diagnosticos"]["total"] == 2

    for item in corpo["diagnosticos"]["itens"]:
        assert "anamnese" not in item
        assert "imagens" not in item

    for proibido in (
        "password",
        "hash-secreto-nao-exposto",
        "anamnese",
        "respostas",
        "imagens",
        "url_arquivo",
        cenario.url_imagem,
        cenario.resposta_sensivel,
    ):
        assert proibido not in response.text


def test_detalhe_pagina_historico_de_diagnosticos(cenario: Cenario) -> None:
    response = client.get(
        f"{PACIENTES_URL}/{cenario.ana_1.id}",
        params={"pagina": 2, "limite": 1},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    historico = response.json()["diagnosticos"]
    assert historico["pagina"] == 2
    assert historico["limite"] == 1
    assert historico["total"] == 2
    assert historico["total_paginas"] == 2
    assert [item["classificacao"]["ordem"] for item in historico["itens"]] == [1]


def test_detalhe_com_paginacao_invalida_retorna_400(cenario: Cenario) -> None:
    response = client.get(
        f"{PACIENTES_URL}/{cenario.ana_1.id}",
        params={"limite": 51},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 400
