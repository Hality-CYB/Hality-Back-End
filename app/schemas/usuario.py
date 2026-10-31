from enum import StrEnum


class TipoUsuario(StrEnum):
    PACIENTE = "paciente"
    PROFISSIONAL = "profissional"
    ADMIN = "admin"
