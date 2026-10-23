"""Data de nascimento do paciente: obrigatória no cadastro público e no feito pelo profissional."""

from datetime import date
from typing import Annotated

from pydantic import AfterValidator

DATA_NASCIMENTO_MINIMA = date(1900, 1, 1)


def validar_data_nascimento(valor: date) -> date:
    if valor > date.today():
        raise ValueError("a data de nascimento não pode estar no futuro")
    if valor < DATA_NASCIMENTO_MINIMA:
        raise ValueError("a data de nascimento precisa ser a partir de 1900")
    return valor


DataNascimento = Annotated[date, AfterValidator(validar_data_nascimento)]
