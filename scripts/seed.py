"""Popula o banco local com dados de exemplo para desenvolvimento.

Uso: uv run python scripts/seed.py

Idempotente: apaga os dados das tabelas de negócio (na ordem reversa das
FKs) antes de inserir, então pode ser rodado quantas vezes for preciso.
Nunca rode contra produção.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta

from dotenv import load_dotenv
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher
from sqlalchemy import delete

from app.db.session import async_session_factory
from app.models import (
    ClassificacaoDiagnostico,
    ConteudoDiagnostico,
    Diagnostico,
    Imagem,
    PacienteProfissional,
    Profissional,
    User,
)

load_dotenv()

password_hash = PasswordHash([BcryptHasher()])
SEED_PASSWORD = password_hash.hash(os.getenv("SEED_PASSWORD"))


async def seed() -> None:
    async with async_session_factory() as db:
        for model in (
            Imagem,
            Diagnostico,
            ConteudoDiagnostico,
            PacienteProfissional,
            Profissional,
            ClassificacaoDiagnostico,
            User,
        ):
            await db.execute(delete(model))

        admin = User(
            name="Admin Hality",
            email="admin@hality.com",
            hashed_password=SEED_PASSWORD,
            role="admin",
        )
        dentista1 = User(
            name="Dra. Ana Souza",
            email="ana.souza@hality.com",
            hashed_password=SEED_PASSWORD,
            role="profissional",
        )
        dentista2 = User(
            name="Dr. Bruno Lima",
            email="bruno.lima@hality.com",
            hashed_password=SEED_PASSWORD,
            role="profissional",
        )
        paciente1 = User(
            name="Carla Mendes",
            email="carla.mendes@example.com",
            phone="51999990001",
            hashed_password=SEED_PASSWORD,
            role="paciente",
        )
        paciente2 = User(
            name="Diego Fontana",
            email="diego.fontana@example.com",
            phone="51999990002",
            hashed_password=SEED_PASSWORD,
            role="paciente",
        )
        paciente3 = User(
            name="Elisa Prado",
            email="elisa.prado@example.com",
            hashed_password=SEED_PASSWORD,
            role="paciente",
        )
        db.add_all([admin, dentista1, dentista2, paciente1, paciente2, paciente3])
        await db.flush()

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
        diagnostico1 = Diagnostico(
            paciente_id=paciente1.id,
            classificacao_id=halitose_leve.id,
            escala_saburra=2,
            confianca_ia=0.87,
            status="gerado",
            data_diagnostico=agora - timedelta(days=3),
        )
        diagnostico2 = Diagnostico(
            paciente_id=paciente2.id,
            classificacao_id=halitose_social.id,
            escala_saburra=4,
            confianca_ia=0.92,
            status="revisado",
            data_diagnostico=agora - timedelta(days=10),
            profissional_revisor_id=dentista1.id,
            data_revisao=agora - timedelta(days=9),
            observacoes_revisao="Confirmado clinicamente, paciente encaminhado para protocolo.",
        )
        diagnostico3 = Diagnostico(
            paciente_id=paciente3.id,
            classificacao_id=saudavel.id,
            escala_saburra=0,
            confianca_ia=0.75,
            status="em_revisao",
            data_diagnostico=agora - timedelta(hours=6),
        )
        db.add_all([diagnostico1, diagnostico2, diagnostico3])
        await db.flush()

        db.add_all(
            [
                Imagem(
                    diagnostico_id=diagnostico1.id,
                    url_arquivo="https://cdn.hality.com/seed/diagnostico1-1.jpg",
                    ordem=1,
                ),
                Imagem(
                    diagnostico_id=diagnostico2.id,
                    url_arquivo="https://cdn.hality.com/seed/diagnostico2-1.jpg",
                    ordem=1,
                ),
                Imagem(
                    diagnostico_id=diagnostico2.id,
                    url_arquivo="https://cdn.hality.com/seed/diagnostico2-2.jpg",
                    ordem=2,
                ),
                Imagem(
                    diagnostico_id=diagnostico3.id,
                    url_arquivo="https://cdn.hality.com/seed/diagnostico3-1.jpg",
                    ordem=1,
                ),
            ]
        )

        await db.commit()

    print(
        "Seed concluído: 6 usuarios, 2 profissionais, 4 classificacoes, "
        "4 conteudos, 3 diagnosticos, 4 imagens."
    )


if __name__ == "__main__":
    asyncio.run(seed())
