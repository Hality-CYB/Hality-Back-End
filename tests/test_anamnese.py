import asyncio

from fastapi.testclient import TestClient

from app.db.session import async_session_factory
from app.main import app
from app.models import Questionario

client = TestClient(app)

AUTH_HEADERS = {"Authorization": "Bearer fake-token"}


def _payload_valido() -> dict:
    return {
        "versao_questionario": "2026-08-v1",
        "respostas": [
            {
                "pergunta_id": "mau_halito_ao_acordar",
                "enunciado": "Você sente mau hálito ao acordar?",
                "tipo": "boolean",
                "valor": True,
            },
            {
                "pergunta_id": "frequencia_escovacao",
                "enunciado": "Com que frequência você escova os dentes?",
                "tipo": "single_choice",
                "valor": "2x ao dia",
            },
            {
                "pergunta_id": "avaliacao_propria_halito",
                "enunciado": "Como você avalia o cheiro da sua respiração?",
                "tipo": "scale",
                "valor": 3,
            },
        ],
    }


def test_obter_questionario() -> None:
    response = client.get("/api/v1/anamneses/questionario")

    assert response.status_code == 200
    corpo = response.json()
    tipos = {p["tipo"] for p in corpo["perguntas"]}
    assert tipos == {"boolean", "single_choice", "text", "scale"}


def test_obter_questionario_usa_fallback_estatico_quando_banco_esta_vazio() -> None:
    # tests/conftest.py garante a tabela `questionarios` vazia em cada teste,
    # então aqui o fallback (anamnese_questionary.py) tem que ser usado.
    response = client.get("/api/v1/anamneses/questionario")

    assert response.status_code == 200
    assert response.json()["versao"] == "2026-08-v1"


def test_obter_questionario_usa_o_banco_quando_ha_um_cadastrado() -> None:
    pergunta_do_banco = {
        "id": "pergunta_so_do_banco",
        "enunciado": "Essa pergunta só existe se vier do banco, não do mock.",
        "tipo": "boolean",
        "obrigatoria": True,
        "opcoes": None,
        "escala_min": None,
        "escala_max": None,
        "escala_label_min": None,
        "escala_label_max": None,
    }

    async def _inserir_questionario_de_teste() -> None:
        async with async_session_factory() as db:
            db.add(Questionario(versao="teste-banco-v1", perguntas=[pergunta_do_banco]))
            await db.commit()

    asyncio.run(_inserir_questionario_de_teste())

    response = client.get("/api/v1/anamneses/questionario")

    assert response.status_code == 200
    corpo = response.json()
    # se ainda viesse do catálogo estático, a versão seria "2026-08-v1"
    assert corpo["versao"] == "teste-banco-v1"
    assert corpo["perguntas"] == [pergunta_do_banco]


def test_criar_anamnese_sem_token_retorna_401() -> None:
    response = client.post("/api/v1/anamneses", json=_payload_valido())

    assert response.status_code == 401


def test_criar_anamnese_sem_pergunta_obrigatoria_retorna_400() -> None:
    payload = _payload_valido()
    payload["respostas"] = [
        r for r in payload["respostas"] if r["pergunta_id"] != "frequencia_escovacao"
    ]

    response = client.post("/api/v1/anamneses", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 400


def test_criar_anamnese_com_valor_fora_da_escala_retorna_400() -> None:
    payload = _payload_valido()
    for resposta in payload["respostas"]:
        if resposta["pergunta_id"] == "avaliacao_propria_halito":
            resposta["valor"] = 7

    response = client.post("/api/v1/anamneses", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 400


def test_criar_anamnese_com_versao_desatualizada_retorna_400() -> None:
    payload = _payload_valido()
    payload["versao_questionario"] = "2020-01-v0"

    response = client.post("/api/v1/anamneses", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 400


def test_criar_anamnese_com_resposta_duplicada_retorna_400() -> None:
    payload = _payload_valido()
    payload["respostas"].append(payload["respostas"][0])

    response = client.post("/api/v1/anamneses", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 400


def test_criar_anamnese_com_opcao_invalida_retorna_400() -> None:
    payload = _payload_valido()
    for resposta in payload["respostas"]:
        if resposta["pergunta_id"] == "frequencia_escovacao":
            resposta["valor"] = "nunca escovo"

    response = client.post("/api/v1/anamneses", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 400


def test_criar_anamnese_ignora_enunciado_do_front_e_usa_catalogo() -> None:
    payload = _payload_valido()
    for resposta in payload["respostas"]:
        if resposta["pergunta_id"] == "mau_halito_ao_acordar":
            resposta["enunciado"] = "texto divergente mandado pelo front"

    criada = client.post("/api/v1/anamneses", json=payload, headers=AUTH_HEADERS).json()

    response = client.get(f"/api/v1/anamneses/{criada['id']}", headers=AUTH_HEADERS)

    assert response.status_code == 200
    respostas = {r["pergunta_id"]: r["enunciado"] for r in response.json()["respostas"]}
    assert respostas["mau_halito_ao_acordar"] == "Você sente mau hálito ao acordar?"


def test_criar_anamnese_valida_retorna_201_com_corpo_minimo() -> None:
    response = client.post("/api/v1/anamneses", json=_payload_valido(), headers=AUTH_HEADERS)

    assert response.status_code == 201
    assert response.json().keys() == {"id", "paciente_id", "data_preenchimento"}


def test_paciente_id_do_body_e_ignorado() -> None:
    payload = _payload_valido()
    payload["paciente_id"] = 999

    response = client.post("/api/v1/anamneses", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 201
    assert response.json()["paciente_id"] != 999


def test_listar_anamneses_inclui_criada_e_paciente_pode_ter_varias() -> None:
    client.post("/api/v1/anamneses", json=_payload_valido(), headers=AUTH_HEADERS)
    client.post("/api/v1/anamneses", json=_payload_valido(), headers=AUTH_HEADERS)

    response = client.get("/api/v1/anamneses", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert len(response.json()) >= 2


def test_obter_anamnese_por_id() -> None:
    criada = client.post("/api/v1/anamneses", json=_payload_valido(), headers=AUTH_HEADERS).json()

    response = client.get(f"/api/v1/anamneses/{criada['id']}", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["respostas"][0]["enunciado"] == "Você sente mau hálito ao acordar?"


def test_obter_anamnese_inexistente_retorna_404() -> None:
    response = client.get("/api/v1/anamneses/999999", headers=AUTH_HEADERS)

    assert response.status_code == 404


def test_atualizar_anamnese() -> None:
    criada = client.post("/api/v1/anamneses", json=_payload_valido(), headers=AUTH_HEADERS).json()
    payload_atualizado = _payload_valido()
    for resposta in payload_atualizado["respostas"]:
        if resposta["pergunta_id"] == "avaliacao_propria_halito":
            resposta["valor"] = 5

    response = client.put(
        f"/api/v1/anamneses/{criada['id']}", json=payload_atualizado, headers=AUTH_HEADERS
    )

    assert response.status_code == 200
    respostas = {r["pergunta_id"]: r["valor"] for r in response.json()["respostas"]}
    assert respostas["avaliacao_propria_halito"] == 5


def test_deletar_anamnese() -> None:
    criada = client.post("/api/v1/anamneses", json=_payload_valido(), headers=AUTH_HEADERS).json()

    delete_response = client.delete(f"/api/v1/anamneses/{criada['id']}", headers=AUTH_HEADERS)
    get_response = client.get(f"/api/v1/anamneses/{criada['id']}", headers=AUTH_HEADERS)

    assert delete_response.status_code == 204
    assert get_response.status_code == 404
