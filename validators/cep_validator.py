"""
validators/cep_validator.py

Camadas 2 (normalizacao) e 3 (validacao sintatica) da arquitetura do plano
v2 (Secao 3). Roda ANTES de qualquer chamada externa -- e essa reducao de
chamadas que responde a QP1 do paper.
"""

import re

CEP_REGEX = re.compile(r"^\d{8}$")


def normalizar_cep(cep_raw) -> str:
    """Remove hifen, ponto, espaco; preserva zero a esquerda via zfill.
    Aceita entrada como string ou numero (Excel as vezes salva CEP como int
    e perde o zero a esquerda -- caso ZERO_ESQUERDA_PERDIDO do plano)."""
    if cep_raw is None:
        return ""
    texto = str(cep_raw).strip()
    texto = texto.replace("-", "").replace(".", "").replace(" ", "")
    if texto == "" or texto.lower() == "nan":
        return ""
    return texto.zfill(8)


def validar_sintaxe(cep_normalizado: str) -> bool:
    """True se o CEP tem exatamente 8 digitos numericos."""
    return bool(CEP_REGEX.match(cep_normalizado))


def classificar_localmente(cep_raw) -> tuple[str, str | None]:
    """Retorna (status, cep_normalizado_ou_None).

    status == 'FORMATO_INVALIDO' -> classificado localmente, NENHUMA
        chamada externa deve ser feita para este registro.
    status == 'PENDENTE' -> passou na validacao sintatica, segue para
        cache/orquestrador.
    """
    cep_norm = normalizar_cep(cep_raw)
    if not validar_sintaxe(cep_norm):
        return "FORMATO_INVALIDO", None
    return "PENDENTE", cep_norm
