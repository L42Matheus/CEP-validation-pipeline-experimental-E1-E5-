"""
generate_synthetic_cases.py

Gera os Conjuntos B (sintetico com erros) e C (repeticoes) do desenho
experimental (plano v2, Secao 7), a partir de uma amostra publica ja
extraida (saida de build_cnefe_sample.py).

Cada registro gerado recebe uma coluna TIPO_CASO e uma coluna
STATUS_ESPERADO, usadas depois para calcular precisao/revocacao/F1
(Secao 8 do plano -- QP5).

Uso:
    python generate_synthetic_cases.py --entrada cnefe_sample_pb.csv \
        --saida dataset_experimental.csv --repeticoes 0.15
"""

import argparse
import random
import string

import pandas as pd

random.seed(42)


def caso_ok(row) -> dict:
    return {
        "CEP": row["CEP"],
        "NM_Cidade": row["NM_Cidade"],
        "ID_UF": row["ID_UF"],
        "TIPO_CASO": "OK",
        "STATUS_ESPERADO": "OK",
    }


def caso_formato_invalido(row) -> dict:
    """CEP vazio, com letras, ou com tamanho diferente de 8 digitos."""
    variantes = [
        "",  # vazio
        "".join(random.choices(string.ascii_uppercase, k=8)),  # letras
        row["CEP"][:5],  # tamanho menor
        row["CEP"] + "99",  # tamanho maior
    ]
    return {
        "CEP": random.choice(variantes),
        "NM_Cidade": row["NM_Cidade"],
        "ID_UF": row["ID_UF"],
        "TIPO_CASO": "FORMATO_INVALIDO",
        "STATUS_ESPERADO": "FORMATO_INVALIDO",
    }


def caso_zero_esquerda_perdido(row) -> dict:
    """Simula CEP salvo como numero no Excel, perdendo o zero a esquerda."""
    cep = row["CEP"]
    if cep.startswith("0"):
        cep_sem_zero = str(int(cep))  # remove zeros a esquerda
    else:
        cep_sem_zero = cep
    return {
        "CEP": cep_sem_zero,
        "NM_Cidade": row["NM_Cidade"],
        "ID_UF": row["ID_UF"],
        "TIPO_CASO": "ZERO_ESQUERDA_PERDIDO",
        # Depende da regra de normalizacao adotada: se o pipeline reconstitui
        # o zero a esquerda (zfill), o esperado e OK; caso contrario, invalido.
        "STATUS_ESPERADO": "OK_APOS_NORMALIZACAO",
    }


def caso_cidade_divergente(row, df_pool, max_tentativas: int = 20) -> dict | None:
    """Usa um CEP real, mas troca o municipio informado. Retorna None se a
    amostra nao tiver municipios distintos suficientes (evita loop infinito)."""
    if df_pool["NM_Cidade"].nunique() < 2:
        return None
    for _ in range(max_tentativas):
        outro = df_pool.sample(1).iloc[0]
        if outro["NM_Cidade"] != row["NM_Cidade"]:
            return {
                "CEP": row["CEP"],
                "NM_Cidade": outro["NM_Cidade"],
                "ID_UF": row["ID_UF"],
                "TIPO_CASO": "CIDADE_DIVERGENTE",
                "STATUS_ESPERADO": "DIVERGENCIA",
            }
    return None


def caso_uf_divergente(row, df_pool, max_tentativas: int = 20) -> dict | None:
    """Usa um CEP real, mas troca a UF informada. Retorna None se a amostra
    tiver uma unica UF (ex: amostra de um unico estado) -- nesse caso este
    tipo de caso sintetico deve ser gerado a partir de uma amostra multi-UF,
    ou a UF trocada deve ser sorteada fora do pool (ver nota abaixo)."""
    if df_pool["ID_UF"].nunique() < 2:
        # Amostra de uma unica UF: sorteia uma UF plausivel fora do pool
        # em vez de tentar achar uma diferente dentro dele.
        outras_ufs = ["SP", "RJ", "MG", "PE", "CE", "BA", "RN"]
        outras_ufs = [uf for uf in outras_ufs if uf != row["ID_UF"]]
        return {
            "CEP": row["CEP"],
            "NM_Cidade": row["NM_Cidade"],
            "ID_UF": random.choice(outras_ufs),
            "TIPO_CASO": "UF_DIVERGENTE",
            "STATUS_ESPERADO": "DIVERGENCIA",
        }
    for _ in range(max_tentativas):
        outro = df_pool.sample(1).iloc[0]
        if outro["ID_UF"] != row["ID_UF"]:
            return {
                "CEP": row["CEP"],
                "NM_Cidade": row["NM_Cidade"],
                "ID_UF": outro["ID_UF"],
                "TIPO_CASO": "UF_DIVERGENTE",
                "STATUS_ESPERADO": "DIVERGENCIA",
            }
    return None


def caso_cep_inexistente(row) -> dict:
    """CEP com 8 digitos mas fora de qualquer faixa valida conhecida.
    Usa 00000-000 como marcador didatico; ajuste para faixas plausiveis
    do dominio se quiser um caso mais realista."""
    return {
        "CEP": "00000000",
        "NM_Cidade": row["NM_Cidade"],
        "ID_UF": row["ID_UF"],
        "TIPO_CASO": "CEP_INEXISTENTE",
        "STATUS_ESPERADO": "CEP_INVALIDO",
    }


GERADORES_SEM_POOL = {
    "OK": caso_ok,
    "FORMATO_INVALIDO": caso_formato_invalido,
    "ZERO_ESQUERDA_PERDIDO": caso_zero_esquerda_perdido,
    "CEP_INEXISTENTE": caso_cep_inexistente,
}
GERADORES_COM_POOL = {
    "CIDADE_DIVERGENTE": caso_cidade_divergente,
    "UF_DIVERGENTE": caso_uf_divergente,
}


def gerar_conjunto_b(df_base: pd.DataFrame, n_por_tipo: int) -> pd.DataFrame:
    linhas = []
    for tipo, gerador in GERADORES_SEM_POOL.items():
        amostra = df_base.sample(n=min(n_por_tipo, len(df_base)), replace=True, random_state=hash(tipo) % (2**32))
        linhas += [gerador(row) for _, row in amostra.iterrows()]
    for tipo, gerador in GERADORES_COM_POOL.items():
        amostra = df_base.sample(n=min(n_por_tipo, len(df_base)), replace=True, random_state=hash(tipo) % (2**32))
        novas = [gerador(row, df_base) for _, row in amostra.iterrows()]
        linhas += [n for n in novas if n is not None]
    return pd.DataFrame(linhas)


def gerar_conjunto_c(df_base: pd.DataFrame, proporcao_repeticoes: float) -> pd.DataFrame:
    """Duplicacao controlada de registros do conjunto A, para medir cache
    hit rate (QP2)."""
    n_rep = int(len(df_base) * proporcao_repeticoes)
    repetidos = df_base.sample(n=n_rep, replace=True, random_state=7).copy()
    repetidos["TIPO_CASO"] = "REPETICAO"
    repetidos["STATUS_ESPERADO"] = "OK"
    return repetidos


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entrada", required=True, help="CSV de saida do build_cnefe_sample.py")
    parser.add_argument("--saida", default="dataset_experimental.csv")
    parser.add_argument("--n-por-tipo", type=int, default=200,
                         help="quantos casos sinteticos gerar por tipo de erro")
    parser.add_argument("--repeticoes", type=float, default=0.15,
                         help="proporcao de registros duplicados (conjunto C)")
    args = parser.parse_args()

    df_a = pd.read_csv(args.entrada, dtype=str)
    df_a["TIPO_CASO"] = "OK"
    df_a["STATUS_ESPERADO"] = "OK"

    df_b = gerar_conjunto_b(df_a, args.n_por_tipo)
    df_c = gerar_conjunto_c(df_a, args.repeticoes)

    df_final = pd.concat([df_a, df_b, df_c], ignore_index=True)
    df_final = df_final.sample(frac=1, random_state=1).reset_index(drop=True)  # embaralha

    df_final.to_csv(args.saida, index=False)

    print("Dataset experimental gerado:")
    print(df_final["TIPO_CASO"].value_counts())
    print(f"\nTotal: {len(df_final):,} registros -> {args.saida}")


if __name__ == "__main__":
    main()
