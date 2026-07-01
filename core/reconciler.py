"""
core/reconciler.py

Camada 7 da arquitetura (plano v2, Secao 3): compara respostas de fontes
diferentes e decide se ha divergencia, sem depender do valor informado na
planilha de entrada -- isso e o que falta no script original (main.py do
repo), que so compara planilha-vs-1-API.
"""

from core.datasource import RespostaFonte


def normalizar_uf(uf: str) -> str:
    return (uf or "").strip().upper()


def divergem(r1: RespostaFonte, r2: RespostaFonte) -> bool:
    """True se duas respostas de fontes diferentes discordam em UF (checagem
    forte) -- localidade e mais ruidosa entre fontes (bairro vs cidade,
    grafias diferentes) e nao e usada isoladamente para marcar divergencia
    dura, mas fica registrada para inspecao manual."""
    return normalizar_uf(r1.uf) != normalizar_uf(r2.uf)
