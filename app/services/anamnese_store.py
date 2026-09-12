from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db.base import Base
from app.db.session import get_db
from app.schemas.anamnese import ItemRespostaRegistrada


class AnamneseORM(Base):
    __tablename__ = "anamnese"

    id_resp: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paciente_id: Mapped[int] = mapped_column(
        ForeignKey("paciente.id"), nullable=False, index=True
    )
    data_preenchimento: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    id_versao_questionario: Mapped[str] = mapped_column(String, nullable=False)
    respostas: Mapped[list[dict]] = mapped_column(JSON, nullable=False)


@dataclass
class AnamneseRecord:
    id_resp: int
    paciente_id: int
    data_preenchimento: datetime
    id_versao_questionario: str
    respostas: list[ItemRespostaRegistrada]


def _para_record(orm: AnamneseORM) -> AnamneseRecord:
    return AnamneseRecord(
        id_resp=orm.id_resp,
        paciente_id=orm.paciente_id,
        data_preenchimento=orm.data_preenchimento,
        id_versao_questionario=orm.id_versao_questionario,
        respostas=[ItemRespostaRegistrada.model_validate(r) for r in orm.respostas],
    )


def _para_json(respostas: list[ItemRespostaRegistrada]) -> list[dict]:
    return [r.model_dump(mode="json") for r in respostas]


class AnamneseRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def salvar(
        self,
        paciente_id: int,
        id_versao_questionario: str,
        respostas: list[ItemRespostaRegistrada],
    ) -> AnamneseRecord:
        orm = AnamneseORM(
            paciente_id=paciente_id,
            id_versao_questionario=id_versao_questionario,
            respostas=_para_json(respostas),
        )
        self.db.add(orm)
        self.db.commit()
        self.db.refresh(orm)
        return _para_record(orm)

    def listar_por_paciente(self, paciente_id: int) -> list[AnamneseRecord]:
        orms = self.db.query(AnamneseORM).filter(AnamneseORM.paciente_id == paciente_id).all()
        return [_para_record(orm) for orm in orms]

    def obter_por_id(self, id_resp: int) -> AnamneseRecord | None:
        orm = self.db.get(AnamneseORM, id_resp)
        return _para_record(orm) if orm is not None else None

    def atualizar(
        self,
        id_resp: int,
        id_versao_questionario: str,
        respostas: list[ItemRespostaRegistrada],
    ) -> AnamneseRecord | None:
        orm = self.db.get(AnamneseORM, id_resp)
        if orm is None:
            return None
        orm.id_versao_questionario = id_versao_questionario
        orm.respostas = _para_json(respostas)
        self.db.commit()
        self.db.refresh(orm)
        return _para_record(orm)

    def deletar(self, id_resp: int) -> None:
        orm = self.db.get(AnamneseORM, id_resp)
        if orm is not None:
            self.db.delete(orm)
            self.db.commit()


def get_anamnese_repository(db: Session = Depends(get_db)) -> AnamneseRepository:
    return AnamneseRepository(db)