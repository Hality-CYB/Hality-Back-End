from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.schemas.diagnostico import (
    AnamneseDiagnosticoResponse,
    ClassificacaoDiagnosticoResponse,
    ConteudoDadosResponse,
    ConteudoDiagnosticoResponse,
    DiagnosticoGetResponse,
    DiagnosticoPostResponse,
    ImagemDiagnosticoResponse,
    ParametrosCaptura,
    RespostaAnamneseResponse,
    RevisaoDiagnosticoResponse,
    StatusDiagnostico,
)

AVISO_LEGAL = (
    "Este é um pré-diagnóstico de apoio e não substitui a avaliação de um profissional "
    "de saúde."
)


class DiagnosticoError(Exception):
    pass


class ImagemInvalidaError(DiagnosticoError):
    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


class ArquivoMuitoGrandeError(DiagnosticoError):
    pass


class AnamneseNaoEncontradaError(DiagnosticoError):
    pass


class AnamneseJaUtilizadaError(DiagnosticoError):
    pass


class DiagnosticoNaoEncontradoError(DiagnosticoError):
    pass


class DiagnosticoAcessoNegadoError(DiagnosticoError):
    pass


@dataclass(slots=True)
class _MockAnamnese:
    response: AnamneseDiagnosticoResponse
    paciente_id: int


@dataclass(slots=True)
class _MockDiagnostico:
    id: int
    paciente_id: int
    anamnese_id: int
    data_diagnostico: datetime
    status: StatusDiagnostico
    imagens: list[ImagemDiagnosticoResponse]
    tem_profissional_vinculado: bool
    classificacao_id: int | None = None
    escala_saburra: int | None = None
    confianca_ia: float | None = None
    revisao: RevisaoDiagnosticoResponse | None = None
    erro: str | None = None
    auto_complete_at: datetime | None = None


class DiagnosticoService:
    def __init__(
        self,
        storage_dir: str,
        storage_url_prefix: str,
        max_image_bytes: int,
        mock_processing_seconds: float,
    ) -> None:
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._storage_url_prefix = storage_url_prefix.rstrip("/")
        self._max_image_bytes = max_image_bytes
        self._mock_processing_seconds = mock_processing_seconds

        self._classificacoes = self._build_classificacoes()
        self._conteudos = self._build_conteudos()
        self._anamneses = self._build_anamneses()
        self._diagnosticos: dict[int, _MockDiagnostico] = {}
        self._parametros_captura_por_imagem: dict[int, dict[str, object]] = {}
        self._next_diagnostico_id = 1
        self._next_imagem_id = 1

        self._seed_fixtures()

    def criar_diagnostico(
        self,
        *,
        paciente_id: int,
        anamnese_id: int,
        imagem_bytes: bytes,
        imagem_content_type: str | None,
        parametros_captura: ParametrosCaptura,
    ) -> DiagnosticoPostResponse:
        anamnese = self._anamneses.get(anamnese_id)
        if anamnese is None or anamnese.paciente_id != paciente_id:
            raise AnamneseNaoEncontradaError

        if self._anamnese_ja_utilizada(anamnese_id):
            raise AnamneseJaUtilizadaError

        self._validar_imagem(imagem_bytes, imagem_content_type)

        agora = datetime.now(UTC)
        diagnostico_id = self._next_diagnostico_id
        self._next_diagnostico_id += 1

        imagem = self._persistir_imagem(
            diagnostico_id=diagnostico_id,
            imagem_bytes=imagem_bytes,
            content_type=imagem_content_type,
            data_captura=agora,
            parametros_captura=parametros_captura,
        )

        classificacao_id = (anamnese_id % 3) + 1
        diagnostico = _MockDiagnostico(
            id=diagnostico_id,
            paciente_id=paciente_id,
            anamnese_id=anamnese_id,
            data_diagnostico=agora,
            status="processando",
            imagens=[imagem],
            tem_profissional_vinculado=paciente_id == 1,
            classificacao_id=classificacao_id,
            auto_complete_at=agora + timedelta(seconds=self._mock_processing_seconds),
        )
        self._diagnosticos[diagnostico_id] = diagnostico

        return DiagnosticoPostResponse(
            id=diagnostico.id,
            status=diagnostico.status,
            data_diagnostico=diagnostico.data_diagnostico,
            anamnese_id=diagnostico.anamnese_id,
        )

    def obter_diagnostico(self, *, diagnostico_id: int, paciente_id: int) -> DiagnosticoGetResponse:
        diagnostico = self._diagnosticos.get(diagnostico_id)
        if diagnostico is None:
            raise DiagnosticoNaoEncontradoError

        if diagnostico.paciente_id != paciente_id:
            raise DiagnosticoAcessoNegadoError

        self._atualizar_mock_se_necessario(diagnostico)
        return self._montar_response(diagnostico)

    def _validar_imagem(self, imagem_bytes: bytes, content_type: str | None) -> None:
        if not imagem_bytes:
            raise ImagemInvalidaError("A imagem enviada está vazia.")

        if len(imagem_bytes) > self._max_image_bytes:
            raise ArquivoMuitoGrandeError

        tipos_permitidos = {"image/jpeg", "image/png", "image/webp"}
        if content_type not in tipos_permitidos:
            raise ImagemInvalidaError(
                "Formato de imagem inválido. Envie JPEG, PNG ou WEBP."
            )

    def _persistir_imagem(
        self,
        *,
        diagnostico_id: int,
        imagem_bytes: bytes,
        content_type: str | None,
        data_captura: datetime,
        parametros_captura: ParametrosCaptura,
    ) -> ImagemDiagnosticoResponse:
        extensao_por_tipo = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }
        extensao = extensao_por_tipo[content_type or "image/jpeg"]
        nome_arquivo = f"{diagnostico_id}_{uuid4().hex}{extensao}"
        caminho = self._storage_dir / nome_arquivo

        caminho.write_bytes(imagem_bytes)

        imagem_id = self._next_imagem_id
        self._next_imagem_id += 1
        self._parametros_captura_por_imagem[imagem_id] = parametros_captura.model_dump(mode="json")
        return ImagemDiagnosticoResponse(
            id=imagem_id,
            url_arquivo=f"{self._storage_url_prefix}/{nome_arquivo}",
            ordem=1,
            data_captura=data_captura,
        )

    def _anamnese_ja_utilizada(self, anamnese_id: int) -> bool:
        return any(item.anamnese_id == anamnese_id for item in self._diagnosticos.values())

    def _atualizar_mock_se_necessario(self, diagnostico: _MockDiagnostico) -> None:
        if diagnostico.status != "processando" or diagnostico.auto_complete_at is None:
            return

        if datetime.now(UTC) < diagnostico.auto_complete_at:
            return

        diagnostico.status = "concluido"
        diagnostico.escala_saburra = {1: 24, 2: 49, 3: 68}[diagnostico.classificacao_id or 1]
        diagnostico.confianca_ia = {1: 0.91, 2: 0.89, 3: 0.87}[
            diagnostico.classificacao_id or 1
        ]
        diagnostico.revisao = RevisaoDiagnosticoResponse(
            revisado=True,
            profissional_nome="Dra. Ana Souza" if diagnostico.tem_profissional_vinculado else None,
            data_revisao=datetime.now(UTC) if diagnostico.tem_profissional_vinculado else None,
            observacoes=(
                "Resultado mock revisado."
                if diagnostico.tem_profissional_vinculado
                else "Resultado mock concluído sem profissional vinculado."
            ),
            nivel_corrigido=False,
        )
        diagnostico.auto_complete_at = None

    def _montar_response(self, diagnostico: _MockDiagnostico) -> DiagnosticoGetResponse:
        classificacao = None
        conteudos: list[ConteudoDiagnosticoResponse] = []

        if diagnostico.status in {"aguardando_revisao", "concluido"}:
            if diagnostico.classificacao_id is not None:
                classificacao = self._classificacoes[diagnostico.classificacao_id]
                conteudos = self._conteudos.get(diagnostico.classificacao_id, [])

        return DiagnosticoGetResponse(
            id=diagnostico.id,
            data_diagnostico=diagnostico.data_diagnostico,
            status=diagnostico.status,
            classificacao=classificacao,
            escala_saburra=diagnostico.escala_saburra,
            confianca_ia=diagnostico.confianca_ia,
            imagens=diagnostico.imagens,
            anamnese=self._anamneses[diagnostico.anamnese_id].response,
            revisao=diagnostico.revisao,
            tem_profissional_vinculado=diagnostico.tem_profissional_vinculado,
            conteudos=conteudos,
            aviso_legal=AVISO_LEGAL,
            erro=diagnostico.erro,
        )

    def _seed_fixtures(self) -> None:
        agora = datetime.now(UTC)

        fixtures = [
            _MockDiagnostico(
                id=1,
                paciente_id=1,
                anamnese_id=101,
                data_diagnostico=agora,
                status="processando",
                imagens=[self._fixture_image(1, agora)],
                tem_profissional_vinculado=True,
            ),
            _MockDiagnostico(
                id=2,
                paciente_id=1,
                anamnese_id=102,
                data_diagnostico=agora,
                status="aguardando_analise",
                imagens=[self._fixture_image(2, agora)],
                tem_profissional_vinculado=True,
            ),
            _MockDiagnostico(
                id=3,
                paciente_id=1,
                anamnese_id=103,
                data_diagnostico=agora,
                status="aguardando_revisao",
                imagens=[self._fixture_image(3, agora)],
                tem_profissional_vinculado=True,
                classificacao_id=1,
                escala_saburra=24,
                confianca_ia=0.91,
                revisao=RevisaoDiagnosticoResponse(revisado=False),
            ),
            _MockDiagnostico(
                id=4,
                paciente_id=1,
                anamnese_id=104,
                data_diagnostico=agora,
                status="concluido",
                imagens=[self._fixture_image(4, agora)],
                tem_profissional_vinculado=True,
                classificacao_id=2,
                escala_saburra=49,
                confianca_ia=0.89,
                revisao=RevisaoDiagnosticoResponse(
                    revisado=True,
                    profissional_nome="Dra. Ana Souza",
                    data_revisao=agora,
                    observacoes="Resultado mock confirmado.",
                    nivel_corrigido=False,
                ),
            ),
            _MockDiagnostico(
                id=5,
                paciente_id=1,
                anamnese_id=105,
                data_diagnostico=agora,
                status="falha",
                imagens=[self._fixture_image(5, agora)],
                tem_profissional_vinculado=True,
                erro="Não foi possível concluir o pré-diagnóstico.",
            ),
            _MockDiagnostico(
                id=6,
                paciente_id=2,
                anamnese_id=206,
                data_diagnostico=agora,
                status="concluido",
                imagens=[self._fixture_image(6, agora)],
                tem_profissional_vinculado=False,
                classificacao_id=3,
                escala_saburra=68,
                confianca_ia=0.87,
                revisao=RevisaoDiagnosticoResponse(
                    revisado=True,
                    profissional_nome=None,
                    data_revisao=None,
                    observacoes="Resultado mock concluído sem profissional vinculado.",
                    nivel_corrigido=False,
                ),
            ),
        ]

        self._diagnosticos = {item.id: item for item in fixtures}
        self._next_diagnostico_id = max(self._diagnosticos) + 1

    def _fixture_image(
        self, diagnostico_id: int, data_captura: datetime
    ) -> ImagemDiagnosticoResponse:
        png_1x1 = bytes.fromhex(
            "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
            "0000000D49444154789C6360000000020001E221BC330000000049454E44AE426082"
        )
        nome_arquivo = f"fixture_{diagnostico_id}.png"
        caminho = self._storage_dir / nome_arquivo
        if not caminho.exists():
            caminho.write_bytes(png_1x1)

        imagem_id = self._next_imagem_id
        self._next_imagem_id += 1
        return ImagemDiagnosticoResponse(
            id=imagem_id,
            url_arquivo=f"{self._storage_url_prefix}/{nome_arquivo}",
            ordem=1,
            data_captura=data_captura,
        )

    @staticmethod
    def _build_classificacoes() -> dict[int, ClassificacaoDiagnosticoResponse]:
        return {
            1: ClassificacaoDiagnosticoResponse(
                id=1,
                codigo="NIVEL_1",
                nome_exibicao="Nível 1",
                ordem=1,
            ),
            2: ClassificacaoDiagnosticoResponse(
                id=2,
                codigo="NIVEL_2",
                nome_exibicao="Nível 2",
                ordem=2,
            ),
            3: ClassificacaoDiagnosticoResponse(
                id=3,
                codigo="NIVEL_3",
                nome_exibicao="Halitose Severa",
                ordem=3,
            ),
        }

    @staticmethod
    def _build_conteudos() -> dict[int, list[ConteudoDiagnosticoResponse]]:
        return {
            1: [
                ConteudoDiagnosticoResponse(
                    id=10,
                    tipo="texto",
                    titulo="Orientação nível 1",
                    dados=ConteudoDadosResponse(
                        icone="sparkles",
                        corpo="Conteúdo mock associado exclusivamente ao nível 1.",
                    ),
                )
            ],
            2: [
                ConteudoDiagnosticoResponse(
                    id=11,
                    tipo="texto",
                    titulo="Orientação nível 2",
                    dados=ConteudoDadosResponse(
                        icone="drop",
                        corpo="Conteúdo mock associado exclusivamente ao nível 2.",
                    ),
                )
            ],
            3: [
                ConteudoDiagnosticoResponse(
                    id=12,
                    tipo="texto",
                    titulo="Higiene da Língua",
                    dados=ConteudoDadosResponse(
                        icone="sparkles",
                        corpo="Use um limpador de língua pela manhã...",
                    ),
                ),
                ConteudoDiagnosticoResponse(
                    id=13,
                    tipo="texto",
                    titulo="Hidratação",
                    dados=ConteudoDadosResponse(
                        icone="drop",
                        corpo="Beba 2 litros de água por dia...",
                    ),
                ),
            ],
        }

    @staticmethod
    def _build_anamneses() -> dict[int, _MockAnamnese]:
        agora = datetime.now(UTC)

        def criar(anamnese_id: int, paciente_id: int) -> _MockAnamnese:
            return _MockAnamnese(
                paciente_id=paciente_id,
                response=AnamneseDiagnosticoResponse(
                    id=anamnese_id,
                    data_preenchimento=agora,
                    respostas=[
                        RespostaAnamneseResponse(
                            pergunta_id="fumante",
                            enunciado="Você é fumante?",
                            tipo="boolean",
                            valor=False,
                        )
                    ],
                ),
            )

        return {
            101: criar(101, 1),
            102: criar(102, 1),
            103: criar(103, 1),
            104: criar(104, 1),
            105: criar(105, 1),
            128: criar(128, 1),
            129: criar(129, 1),
            206: criar(206, 2),
            228: criar(228, 2),
        }
