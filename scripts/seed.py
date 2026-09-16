"""Popula o banco local com dados de exemplo para desenvolvimento.

Uso: uv run python -m scripts.seed

Idempotente: apaga os dados das tabelas de negócio (na ordem reversa das
FKs) antes de inserir, então pode ser rodado quantas vezes for preciso.
Nunca rode contra produção.

O paciente principal (Carla) é criado com o id fixo `PACIENTE_STUB_ID`, o
mesmo que `app/api/deps.py:get_current_patient` devolve enquanto a auth da
anamnese não é unificada. Sem isso, os endpoints de anamnese e diagnóstico
não funcionam no Swagger: eles ignoram o usuário logado e sempre resolvem
para esse id.
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

from dotenv import load_dotenv
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy import delete

from app.auth.users import UserManager
from app.db.session import async_session_factory
from app.models import (
    Anamnese,
    ClassificacaoDiagnostico,
    ConteudoDiagnostico,
    Diagnostico,
    Dica,
    Imagem,
    PacienteProfissional,
    Profissional,
    Questionario,
    User,
)

load_dotenv()

SEED_PASSWORD = os.getenv("SEED_PASSWORD")

# Mesmo id fixo usado pelas suítes de teste (tests/conftest.py, tests/test_diagnostico.py).
PACIENTE_STUB_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# Parâmetros de captura são um JSONB livre: o endpoint só exige "objeto JSON
# válido" e o service repassa sem validar. Não existe schema para o campo.
PARAMETROS_CAPTURA = {"iluminacao": "natural", "distancia_cm": 20}


def _respostas(frequencia: str, avaliacao: int, *, mau_halito: bool) -> list[dict]:
    """Respostas no formato de `ItemRespostaRegistrada` (já "lexadas"), no
    formato do catálogo estático de fallback (anamnese_questionary.py,
    versão "2026-08-v1")."""
    return [
        {
            "pergunta_id": "mau_halito_ao_acordar",
            "des_pergunta": "Você sente mau hálito ao acordar?",
            "tipo_pergunta": "boolean",
            "des_resposta": "Sim" if mau_halito else "Não",
            "valor": mau_halito,
            "tipo_resposta": "bool",
        },
        {
            "pergunta_id": "frequencia_escovacao",
            "des_pergunta": "Com que frequência você escova os dentes?",
            "tipo_pergunta": "single_choice",
            "des_resposta": frequencia,
            "valor": frequencia,
            "tipo_resposta": "str",
        },
        {
            "pergunta_id": "avaliacao_propria_halito",
            "des_pergunta": "Como você avalia o cheiro da sua respiração?",
            "tipo_pergunta": "scale",
            "des_resposta": str(avaliacao),
            "valor": avaliacao,
            "tipo_resposta": "int",
        },
    ]


async def seed() -> None:
    if not SEED_PASSWORD:
        raise RuntimeError("SEED_PASSWORD não está definida no .env")

    async with async_session_factory() as db:
        # Mesmo hasher do endpoint de registro, para as senhas baterem no login.
        password_helper = UserManager(SQLAlchemyUserDatabase(db, User)).password_helper
        senha_hash = password_helper.hash(SEED_PASSWORD)

        for model in (
            Imagem,
            Diagnostico,
            Anamnese,
            Dica,
            ConteudoDiagnostico,
            PacienteProfissional,
            Profissional,
            ClassificacaoDiagnostico,
            Questionario,
            User,
        ):
            await db.execute(delete(model))

        admin = User(
            name="Admin Hality",
            email="admin@hality.com",
            hashed_password=senha_hash,
            role="admin",
        )
        dentista1 = User(
            name="Dra. Ana Souza",
            email="ana.souza@hality.com",
            hashed_password=senha_hash,
            role="profissional",
        )
        dentista2 = User(
            name="Dr. Bruno Lima",
            email="bruno.lima@hality.com",
            hashed_password=senha_hash,
            role="profissional",
        )
        paciente1 = User(
            id=PACIENTE_STUB_ID,
            name="Carla Mendes",
            email="carla.mendes@example.com",
            phone="51999990001",
            hashed_password=senha_hash,
            role="paciente",
        )
        paciente2 = User(
            name="Diego Fontana",
            email="diego.fontana@example.com",
            phone="51999990002",
            hashed_password=senha_hash,
            role="paciente",
        )
        paciente3 = User(
            name="Elisa Prado",
            email="elisa.prado@example.com",
            hashed_password=senha_hash,
            role="paciente",
        )
        db.add_all([admin, dentista1, dentista2, paciente1, paciente2, paciente3])
        await db.flush()

        # Perguntas extraídas de "Tabela anamnese Hality-2.xlsx" (colunas B a L:
        # IDADE, Q1-Q10). Tipo inferido a partir dos valores de exemplo na
        # planilha: sim/não -> boolean; Fraco/Moderado/Forte -> single_choice
        # (opções já vêm do próprio enunciado da coluna); IDADE é numérica e
        # não tem um tipo dedicado no schema, então usa scale sem rótulos.
        questionario = Questionario(
            versao="2026-09-v1",
            perguntas=[
                {
                    "id": "idade",
                    "enunciado": "Qual a sua idade?",
                    "tipo": "scale",
                    "obrigatoria": True,
                    "opcoes": None,
                    "escala_min": 0,
                    "escala_max": 120,
                    "escala_label_min": None,
                    "escala_label_max": None,
                },
                {
                    "id": "boca_seca",
                    "enunciado": "Você sente/ Tem boca seca?",
                    "tipo": "boolean",
                    "obrigatoria": True,
                    "opcoes": None,
                    "escala_min": None,
                    "escala_max": None,
                    "escala_label_min": None,
                    "escala_label_max": None,
                },
                {
                    "id": "respira_pela_boca",
                    "enunciado": "Você respira pela boca?",
                    "tipo": "boolean",
                    "obrigatoria": True,
                    "opcoes": None,
                    "escala_min": None,
                    "escala_max": None,
                    "escala_label_min": None,
                    "escala_label_max": None,
                },
                {
                    "id": "gosto_ruim_na_boca",
                    "enunciado": "Você sente/ tem frequentemente um gosto ruim na boca?",
                    "tipo": "boolean",
                    "obrigatoria": True,
                    "opcoes": None,
                    "escala_min": None,
                    "escala_max": None,
                    "escala_label_min": None,
                    "escala_label_max": None,
                },
                {
                    "id": "acha_que_tem_mau_halito",
                    "enunciado": "Você acha que tem mau hálito?",
                    "tipo": "boolean",
                    "obrigatoria": True,
                    "opcoes": None,
                    "escala_min": None,
                    "escala_max": None,
                    "escala_label_min": None,
                    "escala_label_max": None,
                },
                {
                    "id": "intensidade_mau_halito",
                    "enunciado": "Como você avalia a intensidade do seu mau hálito?",
                    "tipo": "single_choice",
                    "obrigatoria": True,
                    "opcoes": ["Fraco", "Moderado", "Forte"],
                    "escala_min": None,
                    "escala_max": None,
                    "escala_label_min": None,
                    "escala_label_max": None,
                },
                {
                    "id": "ja_falaram_que_tem_mau_halito",
                    "enunciado": "Alguém já lhe falou que você tem problema com mau hálito?",
                    "tipo": "boolean",
                    "obrigatoria": True,
                    "opcoes": None,
                    "escala_min": None,
                    "escala_max": None,
                    "escala_label_min": None,
                    "escala_label_max": None,
                },
                {
                    "id": "ja_consultou_especialista",
                    "enunciado": "Você já consultou algum especialista sobre esse problema?",
                    "tipo": "boolean",
                    "obrigatoria": True,
                    "opcoes": None,
                    "escala_min": None,
                    "escala_max": None,
                    "escala_label_min": None,
                    "escala_label_max": None,
                },
                {
                    "id": "escova_a_lingua",
                    "enunciado": "Você costuma escovar a língua?",
                    "tipo": "boolean",
                    "obrigatoria": True,
                    "opcoes": None,
                    "escala_min": None,
                    "escala_max": None,
                    "escala_label_min": None,
                    "escala_label_max": None,
                },
                {
                    "id": "se_afasta_de_pessoas",
                    "enunciado": "Você se afasta das pessoas por causa do seu mau hálito?",
                    "tipo": "boolean",
                    "obrigatoria": True,
                    "opcoes": None,
                    "escala_min": None,
                    "escala_max": None,
                    "escala_label_min": None,
                    "escala_label_max": None,
                },
                {
                    "id": "usa_algo_para_disfarcar",
                    "enunciado": (
                        "Você usa alguma coisa (hortelã, chicletes...) para disfarçar o mau hálito?"
                    ),
                    "tipo": "boolean",
                    "obrigatoria": True,
                    "opcoes": None,
                    "escala_min": None,
                    "escala_max": None,
                    "escala_label_min": None,
                    "escala_label_max": None,
                },
            ],
        )
        db.add(questionario)

        profissional1 = Profissional(
            usuario_id=dentista1.id,
            registro_profissional="CRO-RS 12345",
            especialidade="Periodontia",
            vinculado_hality=True,
        )
        profissional2 = Profissional(
            usuario_id=dentista2.id,
            registro_profissional="CRO-RS 54321",
            especialidade="Clínica Geral",
            vinculado_hality=False,
        )
        db.add_all([profissional1, profissional2])
        await db.flush()

        db.add_all(
            [
                PacienteProfissional(
                    paciente_id=paciente1.id, profissional_id=profissional1.usuario_id
                ),
                PacienteProfissional(
                    paciente_id=paciente2.id, profissional_id=profissional1.usuario_id
                ),
                PacienteProfissional(
                    paciente_id=paciente3.id, profissional_id=profissional2.usuario_id
                ),
            ]
        )

        saudavel = ClassificacaoDiagnostico(codigo="saudavel", nome_exibicao="Saudável", ordem=0)
        halitose_leve = ClassificacaoDiagnostico(
            codigo="halitose_leve", nome_exibicao="Halitose Leve", ordem=1
        )
        halitose_social = ClassificacaoDiagnostico(
            codigo="halitose_social", nome_exibicao="Halitose Social", ordem=2
        )
        halitose_severa = ClassificacaoDiagnostico(
            codigo="halitose_severa", nome_exibicao="Halitose Severa", ordem=3
        )
        db.add_all([saudavel, halitose_leve, halitose_social, halitose_severa])
        await db.flush()

        db.add_all(
            [
                ConteudoDiagnostico(
                    classificacao_id=None,
                    tipo="dica",
                    titulo="Escovação após as refeições",
                    dados={
                        "tipo_midia": "texto",
                        "corpo": "Escove os dentes em até 30 minutos após comer.",
                    },
                ),
                ConteudoDiagnostico(
                    classificacao_id=halitose_leve.id,
                    tipo="dica",
                    titulo="Use fio dental diariamente",
                    dados={
                        "tipo_midia": "texto",
                        "corpo": "O fio dental remove restos de comida que a escova não alcança.",
                    },
                ),
                ConteudoDiagnostico(
                    classificacao_id=halitose_social.id,
                    tipo="protocolo",
                    titulo="Protocolo de raspagem e limpeza",
                    dados={
                        "numero_sessoes": 2,
                        "descricao": "Raspagem supragengival seguida de reavaliação em 15 dias.",
                    },
                ),
                ConteudoDiagnostico(
                    classificacao_id=halitose_severa.id,
                    tipo="protocolo",
                    titulo="Protocolo de tratamento periodontal",
                    dados={
                        "numero_sessoes": 4,
                        "descricao": "Raspagem subgengival + acompanhamento periodontal mensal.",
                    },
                ),
            ]
        )
        await db.flush()

        agora = datetime.now(UTC)

        # Uma anamnese por diagnóstico: `diagnosticos.anamnese_id` é UNIQUE.
        anamnese_concluido = Anamnese(
            paciente_id=paciente1.id,
            data_preenchimento=agora - timedelta(days=3),
            id_versao_questionario="2026-08-v1",
            respostas=_respostas("2x ao dia", 2, mau_halito=True),
        )
        anamnese_revisado = Anamnese(
            paciente_id=paciente1.id,
            data_preenchimento=agora - timedelta(days=10),
            id_versao_questionario="2026-08-v1",
            respostas=_respostas("1x ao dia", 1, mau_halito=True),
        )
        anamnese_processando = Anamnese(
            paciente_id=paciente1.id,
            data_preenchimento=agora - timedelta(hours=6),
            id_versao_questionario="2026-08-v1",
            respostas=_respostas("3x ou mais", 4, mau_halito=False),
        )
        anamnese_falha = Anamnese(
            paciente_id=paciente1.id,
            data_preenchimento=agora - timedelta(days=1),
            id_versao_questionario="2026-08-v1",
            respostas=_respostas("2x ao dia", 3, mau_halito=True),
        )
        anamnese_diego = Anamnese(
            paciente_id=paciente2.id,
            data_preenchimento=agora - timedelta(days=5),
            id_versao_questionario="2026-08-v1",
            respostas=_respostas("1x ao dia", 1, mau_halito=True),
        )
        anamnese_elisa = Anamnese(
            paciente_id=paciente3.id,
            data_preenchimento=agora - timedelta(days=2),
            id_versao_questionario="2026-08-v1",
            respostas=_respostas("3x ou mais", 5, mau_halito=False),
        )
        db.add_all(
            [
                anamnese_concluido,
                anamnese_revisado,
                anamnese_processando,
                anamnese_falha,
                anamnese_diego,
                anamnese_elisa,
            ]
        )
        await db.flush()

        # Status conforme o código vivo (diagnostico_service/diagnostico_mock):
        # "processando", "concluido" e "falha". Só "concluido" e
        # "aguardando_revisao" estão em STATUS_COM_RESULTADO, ou seja, só eles
        # devolvem classificação/escala/conteúdos no detalhe.
        diagnostico_concluido = Diagnostico(
            paciente_id=paciente1.id,
            anamnese_id=anamnese_concluido.id,
            classificacao_id=halitose_leve.id,
            escala_saburra=24,
            confianca_ia=0.91,
            status="concluido",
            data_diagnostico=agora - timedelta(days=3),
        )
        diagnostico_revisado = Diagnostico(
            paciente_id=paciente1.id,
            anamnese_id=anamnese_revisado.id,
            classificacao_id=halitose_social.id,
            escala_saburra=49,
            confianca_ia=0.89,
            status="concluido",
            data_diagnostico=agora - timedelta(days=10),
            profissional_revisor_id=dentista1.id,
            data_revisao=agora - timedelta(days=9),
            observacoes_revisao="Confirmado clinicamente, paciente encaminhado para protocolo.",
        )
        diagnostico_processando = Diagnostico(
            paciente_id=paciente1.id,
            anamnese_id=anamnese_processando.id,
            classificacao_id=None,
            escala_saburra=None,
            confianca_ia=None,
            status="processando",
            data_diagnostico=agora - timedelta(hours=6),
        )
        diagnostico_falha = Diagnostico(
            paciente_id=paciente1.id,
            anamnese_id=anamnese_falha.id,
            classificacao_id=None,
            escala_saburra=None,
            confianca_ia=None,
            status="falha",
            erro="Imagem fora de foco: não foi possível avaliar a saburra lingual.",
            data_diagnostico=agora - timedelta(days=1),
        )
        diagnostico_diego = Diagnostico(
            paciente_id=paciente2.id,
            anamnese_id=anamnese_diego.id,
            classificacao_id=halitose_severa.id,
            escala_saburra=68,
            confianca_ia=0.87,
            status="concluido",
            data_diagnostico=agora - timedelta(days=5),
        )
        diagnostico_elisa = Diagnostico(
            paciente_id=paciente3.id,
            anamnese_id=anamnese_elisa.id,
            classificacao_id=saudavel.id,
            escala_saburra=3,
            confianca_ia=0.75,
            status="concluido",
            data_diagnostico=agora - timedelta(days=2),
        )
        db.add_all(
            [
                diagnostico_concluido,
                diagnostico_revisado,
                diagnostico_processando,
                diagnostico_falha,
                diagnostico_diego,
                diagnostico_elisa,
            ]
        )
        await db.flush()

        db.add_all(
            [
                Imagem(
                    diagnostico_id=diagnostico_concluido.id,
                    url_arquivo="https://cdn.hality.com/seed/diagnostico1-1.jpg",
                    ordem=1,
                    parametros_captura=PARAMETROS_CAPTURA,
                ),
                Imagem(
                    diagnostico_id=diagnostico_revisado.id,
                    url_arquivo="https://cdn.hality.com/seed/diagnostico2-1.jpg",
                    ordem=1,
                    parametros_captura=PARAMETROS_CAPTURA,
                ),
                Imagem(
                    diagnostico_id=diagnostico_revisado.id,
                    url_arquivo="https://cdn.hality.com/seed/diagnostico2-2.jpg",
                    ordem=2,
                    parametros_captura=PARAMETROS_CAPTURA,
                ),
                Imagem(
                    diagnostico_id=diagnostico_processando.id,
                    url_arquivo="https://cdn.hality.com/seed/diagnostico3-1.jpg",
                    ordem=1,
                    parametros_captura=PARAMETROS_CAPTURA,
                ),
                Imagem(
                    diagnostico_id=diagnostico_falha.id,
                    url_arquivo="https://cdn.hality.com/seed/diagnostico4-1.jpg",
                    ordem=1,
                    parametros_captura=PARAMETROS_CAPTURA,
                ),
                Imagem(
                    diagnostico_id=diagnostico_diego.id,
                    url_arquivo="https://cdn.hality.com/seed/diagnostico5-1.jpg",
                    ordem=1,
                    parametros_captura=PARAMETROS_CAPTURA,
                ),
                Imagem(
                    diagnostico_id=diagnostico_elisa.id,
                    url_arquivo="https://cdn.hality.com/seed/diagnostico6-1.jpg",
                    ordem=1,
                    parametros_captura=PARAMETROS_CAPTURA,
                ),
            ]
        )

        db.add_all(
            [
                Dica(
                    titulo="O que é halitose?",
                    conteudo=(
                        "Halitose é o nome dado ao mau hálito persistente. Na maioria "
                        "dos casos ela tem origem na própria boca, em restos de comida "
                        "e bactérias acumuladas na língua e entre os dentes."
                    ),
                ),
                Dica(
                    titulo="Limpe a língua todos os dias",
                    conteudo=(
                        "A saburra lingual, aquela camada esbranquiçada no fundo da "
                        "língua, é a causa mais comum de mau hálito. Use um limpador "
                        "de língua do fundo para a frente, sem forçar, uma vez ao dia."
                    ),
                ),
                Dica(
                    titulo="Beba água ao longo do dia",
                    conteudo=(
                        "A boca seca favorece o mau hálito porque a saliva é o que "
                        "limpa naturalmente os resíduos. Beba água com frequência, "
                        "principalmente ao acordar e depois de exercícios."
                    ),
                ),
                Dica(
                    titulo="Mau hálito não se resolve só com enxaguante",
                    conteudo=(
                        "Enxaguantes mascaram o odor por algumas horas, mas não removem "
                        "a causa. Se o mau hálito continua mesmo com boa higiene, "
                        "procure um dentista para investigar a origem."
                    ),
                ),
            ]
        )

        await db.commit()

        ids_carla = {
            "concluido": diagnostico_concluido.id,
            "concluido (revisado)": diagnostico_revisado.id,
            "processando": diagnostico_processando.id,
            "falha": diagnostico_falha.id,
        }

    print(
        "Seed concluído: 6 usuarios, 2 profissionais, 4 classificacoes, "
        "4 conteudos, 6 anamneses, 6 diagnosticos, 7 imagens, 4 dicas, "
        "1 questionario (11 perguntas).\n"
    )
    print(f"Senha de todos os usuarios: {SEED_PASSWORD}\n")
    print("Credenciais:")
    for email, role in (
        ("carla.mendes@example.com", "paciente  <- use este no Swagger"),
        ("diego.fontana@example.com", "paciente"),
        ("elisa.prado@example.com", "paciente"),
        ("ana.souza@hality.com", "profissional"),
        ("bruno.lima@hality.com", "profissional"),
        ("admin@hality.com", "admin"),
    ):
        print(f"  {email:<28} {role}")
    print(f"\nCarla tem o id fixo do stub: {PACIENTE_STUB_ID}")
    print("Diagnosticos da Carla (GET /api/v1/diagnosticos/{id}):")
    for rotulo, diagnostico_id in ids_carla.items():
        print(f"  id={diagnostico_id:<4} {rotulo}")


if __name__ == "__main__":
    asyncio.run(seed())
