"""Regra única para senha nova (cadastro, convite, redefinição, troca e criação pelo admin).

Só vale quando uma senha é definida. O login não passa por aqui, então senhas
antigas que não seguem a regra continuam funcionando até a próxima troca.
"""

from typing import Annotated

from pydantic import AfterValidator

SENHA_TAMANHO_MINIMO = 8
SENHAS_PADRAO_PROIBIDAS: frozenset[str] = frozenset(
    {"hality1234", "senha123", "12345678", "password", "admin123"}
)


def validar_senha_nova(senha: str) -> str:
    if len(senha) < SENHA_TAMANHO_MINIMO:
        raise ValueError(f"a senha precisa de pelo menos {SENHA_TAMANHO_MINIMO} caracteres")
    if not any(c.isupper() for c in senha):
        raise ValueError("a senha precisa de pelo menos uma letra maiúscula")
    if not any(c.islower() for c in senha):
        raise ValueError("a senha precisa de pelo menos uma letra minúscula")
    if not any(c.isdigit() for c in senha):
        raise ValueError("a senha precisa de pelo menos um número")
    if senha.strip().lower() in SENHAS_PADRAO_PROIBIDAS:
        raise ValueError("senha padrão não é permitida")
    return senha


SenhaNova = Annotated[str, AfterValidator(validar_senha_nova)]
