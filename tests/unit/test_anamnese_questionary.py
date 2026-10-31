import logging

import pytest

from app.services.anamnese_questionary import get_questionario_ativo


class SessaoComFalhaSensivel:
    rollback_executado = False

    async def execute(self, _consulta):
        raise RuntimeError(
            "password=senha-super-secreta token=token-super-secreto "
            "imagem=base64-secreta anamnese=resposta-clinica-secreta"
        )

    async def rollback(self) -> None:
        self.rollback_executado = True


@pytest.mark.asyncio
async def test_fallback_nao_registra_dados_da_excecao(caplog: pytest.LogCaptureFixture) -> None:
    sessao = SessaoComFalhaSensivel()
    caplog.set_level(logging.WARNING, logger="app.services.anamnese_questionary")

    questionario = await get_questionario_ativo(sessao)  # type: ignore[arg-type]

    assert questionario.versao == "2026-08-v1"
    assert sessao.rollback_executado is True
    assert "usando fallback estático" in caplog.text
    for segredo in (
        "senha-super-secreta",
        "token-super-secreto",
        "base64-secreta",
        "resposta-clinica-secreta",
    ):
        assert segredo not in caplog.text
