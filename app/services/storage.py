"""Storage de arquivos (fotos de diagnóstico e mídias de conteúdo).

Dois adaptadores com a mesma interface, escolhidos por `STORAGE_BACKEND`:
`local` (disco do container, `.data/`) e `s3` (bucket privado, via boto3).

A chave é o caminho relativo com prefixo: `uploads/`, `diagnosticos/` ou
`conteudos/`, seguido de `<uuid>.<ext>`.
"""

import asyncio
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from app.auth.policies import assinar_policy_upload_local
from app.core.config import get_settings

PREFIXOS = ("uploads", "diagnosticos", "conteudos")
ROTA_UPLOAD_LOCAL = "/uploads/local"

_CHAVE = re.compile(r"^(uploads|diagnosticos|conteudos)/[A-Za-z0-9][A-Za-z0-9._-]*$")

_RAIZ_LOCAL = Path(".data")


class ObjetoNaoEncontradoError(FileNotFoundError):
    pass


class ObjetoJaExisteError(FileExistsError):
    pass


class StorageIndisponivelError(OSError):
    pass


@dataclass(frozen=True)
class AlvoDeUpload:
    url: str
    fields: dict[str, str]


@dataclass(frozen=True)
class Metadados:
    tamanho: int
    modificado_em: datetime


@dataclass(frozen=True)
class ArquivoLocal:
    caminho: Path


@dataclass(frozen=True)
class UrlAssinada:
    url: str


def validar_chave(chave: str) -> str:
    if not _CHAVE.match(chave) or ".." in chave:
        raise ValueError("chave de storage inválida")
    return chave


def _nome_valido(nome: str) -> bool:
    try:
        validar_chave(f"conteudos/{nome}")
    except ValueError:
        return False
    return True


class Storage(Protocol):
    async def salvar(self, chave: str, dados: bytes, content_type: str) -> None: ...
    async def ler(self, chave: str) -> bytes: ...
    async def metadados(self, chave: str) -> Metadados | None: ...
    async def remover(self, chave: str) -> None: ...
    async def mover(self, origem: str, destino: str) -> None: ...
    async def listar_anteriores_a(self, prefixo: str, limite: datetime) -> list[str]: ...
    async def alvo_de_upload(
        self, chave: str, content_type: str, max_bytes: int, validade: int
    ) -> AlvoDeUpload: ...
    async def leitura(self, chave: str, validade: int) -> ArquivoLocal | UrlAssinada | None: ...


class StorageLocal:
    def _caminho(self, chave: str) -> Path:
        return _RAIZ_LOCAL / validar_chave(chave)

    async def salvar(self, chave: str, dados: bytes, content_type: str) -> None:
        caminho = self._caminho(chave)

        def _gravar() -> None:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            try:
                with caminho.open("xb") as arquivo:
                    arquivo.write(dados)
            except FileExistsError as exc:
                raise ObjetoJaExisteError(chave) from exc

        await asyncio.to_thread(_gravar)

    async def ler(self, chave: str) -> bytes:
        caminho = self._caminho(chave)

        def _ler() -> bytes:
            try:
                return caminho.read_bytes()
            except FileNotFoundError as exc:
                raise ObjetoNaoEncontradoError(chave) from exc

        return await asyncio.to_thread(_ler)

    async def metadados(self, chave: str) -> Metadados | None:
        caminho = self._caminho(chave)

        def _stat() -> Metadados | None:
            try:
                info = caminho.stat()
            except FileNotFoundError:
                return None
            return Metadados(info.st_size, datetime.fromtimestamp(info.st_mtime, UTC))

        return await asyncio.to_thread(_stat)

    async def remover(self, chave: str) -> None:
        await asyncio.to_thread(self._caminho(chave).unlink, missing_ok=True)

    async def mover(self, origem: str, destino: str) -> None:
        de, para = self._caminho(origem), self._caminho(destino)

        def _mover() -> None:
            if not de.is_file():
                raise ObjetoNaoEncontradoError(origem)
            para.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(de, para)
            except FileExistsError as exc:
                raise ObjetoJaExisteError(destino) from exc
            de.unlink(missing_ok=True)

        await asyncio.to_thread(_mover)

    async def listar_anteriores_a(self, prefixo: str, limite: datetime) -> list[str]:
        pasta = _RAIZ_LOCAL / prefixo.strip("/")

        def _listar() -> list[str]:
            if not pasta.is_dir():
                return []
            return [
                f"{prefixo.strip('/')}/{caminho.name}"
                for caminho in pasta.iterdir()
                if caminho.is_file()
                and datetime.fromtimestamp(caminho.stat().st_mtime, UTC) < limite
            ]

        return await asyncio.to_thread(_listar)

    async def alvo_de_upload(
        self, chave: str, content_type: str, max_bytes: int, validade: int
    ) -> AlvoDeUpload:
        validar_chave(chave)
        fields = assinar_policy_upload_local(
            chave=chave, content_type=content_type, max_bytes=max_bytes, validade=validade
        )
        return AlvoDeUpload(
            url=f"{get_settings().api_v1_prefix.rstrip('/')}{ROTA_UPLOAD_LOCAL}", fields=fields
        )

    async def leitura(self, chave: str, validade: int) -> ArquivoLocal | UrlAssinada | None:
        caminho = self._caminho(chave)
        eh_arquivo = await asyncio.to_thread(caminho.is_file)
        return ArquivoLocal(caminho) if eh_arquivo else None


class StorageS3:
    def __init__(self, bucket: str, regiao: str, cliente: Any | None = None) -> None:
        self._bucket = bucket
        self._regiao = regiao
        self._cliente = cliente

    @property
    def cliente(self) -> Any:
        if self._cliente is None:
            import boto3
            from botocore.config import Config

            self._cliente = boto3.client(
                "s3",
                region_name=self._regiao,
                endpoint_url=f"https://s3.{self._regiao}.amazonaws.com",
                config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
            )
        return self._cliente

    async def _executar(self, funcao: Any, *args: Any, **kwargs: Any) -> Any:
        from botocore.exceptions import BotoCoreError, ClientError

        def _chamar() -> Any:
            return funcao(*args, **kwargs)

        try:
            return await asyncio.to_thread(_chamar)
        except ClientError as exc:
            codigo = str(exc.response.get("Error", {}).get("Code", ""))
            if codigo in {"404", "NoSuchKey", "NotFound"}:
                raise ObjetoNaoEncontradoError(codigo) from exc
            if codigo in {"PreconditionFailed", "412"}:
                raise ObjetoJaExisteError(codigo) from exc
            raise StorageIndisponivelError(codigo or "erro no storage") from exc
        except BotoCoreError as exc:
            raise StorageIndisponivelError(str(exc)) from exc

    async def salvar(self, chave: str, dados: bytes, content_type: str) -> None:
        validar_chave(chave)
        await self._executar(
            self.cliente.put_object,
            Bucket=self._bucket,
            Key=chave,
            Body=dados,
            ContentType=content_type,
            IfNoneMatch="*",
        )

    async def ler(self, chave: str) -> bytes:
        validar_chave(chave)
        resposta = await self._executar(self.cliente.get_object, Bucket=self._bucket, Key=chave)
        return await asyncio.to_thread(resposta["Body"].read)

    async def metadados(self, chave: str) -> Metadados | None:
        validar_chave(chave)
        try:
            resposta = await self._executar(
                self.cliente.head_object, Bucket=self._bucket, Key=chave
            )
        except ObjetoNaoEncontradoError:
            return None
        return Metadados(resposta["ContentLength"], resposta["LastModified"])

    async def remover(self, chave: str) -> None:
        validar_chave(chave)
        await self._executar(self.cliente.delete_object, Bucket=self._bucket, Key=chave)

    async def mover(self, origem: str, destino: str) -> None:
        validar_chave(origem)
        validar_chave(destino)
        # CopyObject não tem escrita condicional no destino. As chaves levam um
        # uuid novo, então checar antes basta; o versionamento do bucket cobre o resto.
        if await self.metadados(destino) is not None:
            raise ObjetoJaExisteError(destino)
        await self._executar(
            self.cliente.copy_object,
            Bucket=self._bucket,
            Key=destino,
            CopySource={"Bucket": self._bucket, "Key": origem},
        )
        await self.remover(origem)

    async def listar_anteriores_a(self, prefixo: str, limite: datetime) -> list[str]:
        prefixo = prefixo.strip("/") + "/"
        chaves: list[str] = []
        token: str | None = None
        while True:
            args: dict[str, Any] = {"Bucket": self._bucket, "Prefix": prefixo}
            if token:
                args["ContinuationToken"] = token
            resposta = await self._executar(self.cliente.list_objects_v2, **args)
            chaves += [
                item["Key"]
                for item in resposta.get("Contents", [])
                if item["LastModified"] < limite
            ]
            if not resposta.get("IsTruncated"):
                return chaves
            token = resposta["NextContinuationToken"]

    async def alvo_de_upload(
        self, chave: str, content_type: str, max_bytes: int, validade: int
    ) -> AlvoDeUpload:
        validar_chave(chave)
        post = await asyncio.to_thread(
            self.cliente.generate_presigned_post,
            Bucket=self._bucket,
            Key=chave,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, max_bytes],
            ],
            ExpiresIn=validade,
        )
        return AlvoDeUpload(url=post["url"], fields=dict(post["fields"]))

    async def leitura(self, chave: str, validade: int) -> ArquivoLocal | UrlAssinada | None:
        if await self.metadados(chave) is None:
            return None
        url = await asyncio.to_thread(
            self.cliente.generate_presigned_url,
            "get_object",
            Params={"Bucket": self._bucket, "Key": chave},
            ExpiresIn=validade,
        )
        return UrlAssinada(url)


_instancia: Storage | None = None


def atual() -> Storage:
    global _instancia
    if _instancia is None:
        settings = get_settings()
        if settings.storage_backend == "s3":
            _instancia = StorageS3(settings.s3_bucket or "", settings.aws_region or "")
        else:
            _instancia = StorageLocal()
    return _instancia


def _redefinir(instancia: Storage | None = None) -> None:
    global _instancia
    _instancia = instancia
