"""
experiments/run_experiment.py

Roda as 5 estrategias (E1-E5) sobre um dataset experimental e imprime uma
tabela comparativa de metricas -- alimenta diretamente a Secao 5
(Avaliacao) do paper.

Por padrao usa MockDataSource (Conjunto D do plano: mocks com timeout e
respostas divergentes), conforme a recomendacao metodologica do plano de
que a avaliacao principal de resiliencia use mocks, nao APIs reais.

Uso:
    python -m experiments.run_experiment --entrada dataset_experimental_pb.csv
"""

import argparse
import sys

import pandas as pd

from core.cache import TTLCache
from core.datasource import MockDataSource
from core.orchestrator import Orquestrador, Registro


def montar_fontes_mock(df: pd.DataFrame, seed: int = 42) -> list[MockDataSource]:
    """Constroi 3 fontes mock a partir dos proprios dados do dataset (a
    'verdade' que uma API real retornaria), cada uma com taxas de falha e
    latencia diferentes para simular heterogeneidade real entre
    BrasilAPI/ViaCEP/OpenCEP."""
    registros_verdade = {}
    for _, row in df.iterrows():
        cep = str(row["CEP"]).strip()
        if len(cep) == 8 and cep.isdigit():
            registros_verdade[cep] = (row["NM_Cidade"], row["ID_UF"])

    return [
        MockDataSource("BrasilAPI", registros_verdade, taxa_timeout=0.03,
                        taxa_divergencia=0.01, latencia_base_s=0.005, seed=seed),
        MockDataSource("ViaCEP", registros_verdade, taxa_timeout=0.08,
                        taxa_divergencia=0.03, latencia_base_s=0.008, seed=seed + 1),
        MockDataSource("OpenCEP", registros_verdade, taxa_timeout=0.05,
                        taxa_divergencia=0.02, latencia_base_s=0.006, seed=seed + 2),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entrada", required=True, help="CSV de saida do generate_synthetic_cases.py")
    parser.add_argument("--estrategias", default="E1,E2,E3,E4,E5")
    args = parser.parse_args()

    df = pd.read_csv(args.entrada, dtype=str)
    for col in ["CEP", "NM_Cidade", "ID_UF"]:
        if col not in df.columns:
            print(f"Coluna obrigatoria '{col}' ausente no dataset.", file=sys.stderr)
            sys.exit(1)

    registros = [
        Registro(cep_raw=row["CEP"], cidade_informada=row.get("NM_Cidade", ""), uf_informada=row.get("ID_UF", ""))
        for _, row in df.iterrows()
    ]

    resultados = []
    for estrategia in args.estrategias.split(","):
        fontes = montar_fontes_mock(df)  # fontes novas por estrategia -> comparacao justa (mesmo estado inicial)
        orquestrador = Orquestrador(fontes=fontes, cache=TTLCache(ttl_segundos=3600))
        m = orquestrador.processar_lote(registros, estrategia)
        resultados.append(m.resumo())
        print(f"\n=== {estrategia} ===")
        for k, v in m.resumo().items():
            print(f"  {k}: {v}")

    tabela = pd.DataFrame(resultados)
    print("\n\n=== TABELA COMPARATIVA ===")
    print(tabela.to_string(index=False))
    tabela.to_csv("resultado_comparativo.csv", index=False)
    print("\nSalvo em resultado_comparativo.csv")


if __name__ == "__main__":
    main()
