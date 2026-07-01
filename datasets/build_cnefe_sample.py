"""
build_cnefe_sample.py

Baixa arquivos publicos do CNEFE 2022 (IBGE) por UF/municipio e extrai uma
amostra contendo apenas CEP, municipio e UF -- Conjunto A do desenho
experimental (plano v2, Secao 7).

Pensado para rodar no Google Colab (mesmo padrao ja usado no pipeline
DATASUS/SIH). Estrutura real confirmada via terminal em 01/07/2026:

    https://ftp.ibge.gov.br/Cadastro_Nacional_de_Enderecos_para_Fins_Estatisticos/
    Censo_Demografico_2022/Arquivos_CNEFE/CSV/Municipio/{codigo_uf}_{SIGLA}/
    {codigo_municipio}_{NOME_MUNICIPIO}.zip

    Ex: 25_PB/2504009_CAMPINA_GRANDE.zip, 25_PB/2507507_JOAO_PESSOA.zip

O servico e servido como um indice HTTPS padrao (Apache autoindex), nao
FTP de verdade -- da pra navegar/baixar com requests/curl/wget normalmente.

Uso:
    python build_cnefe_sample.py --uf PB --municipios 2504009,2507507 --n 8000 --saida cnefe_sample_pb.csv
    python build_cnefe_sample.py --uf PB --todos-municipios --n 8000 --saida cnefe_sample_pb.csv
"""

import argparse
import io
import re
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

BASE_URL = (
    "https://ftp.ibge.gov.br/Cadastro_Nacional_de_Enderecos_para_Fins_Estatisticos/"
    "Censo_Demografico_2022/Arquivos_CNEFE/CSV/Municipio/"
)

# Codigo IBGE de UF (2 digitos) -> pasta real no FTP (confirmado via curl).
UF_PARA_PASTA = {
    "RO": "11_RO", "AC": "12_AC", "AM": "13_AM", "RR": "14_RR", "PA": "15_PA",
    "AP": "16_AP", "TO": "17_TO", "MA": "21_MA", "PI": "22_PI", "CE": "23_CE",
    "RN": "24_RN", "PB": "25_PB", "PE": "26_PE", "AL": "27_AL", "SE": "28_SE",
    "BA": "29_BA", "MG": "31_MG", "ES": "32_ES", "RJ": "33_RJ", "SP": "35_SP",
    "PR": "41_PR", "SC": "42_SC", "RS": "43_RS", "MS": "50_MS", "MT": "51_MT",
    "GO": "52_GO", "DF": "53_DF",
}

# Nomes de coluna DENTRO do CSV do CNEFE, confirmados via execucao real em
# 01/07/2026 (Campina Grande e Joao Pessoa - PB). O CSV nao tem coluna de
# nome de municipio: so COD_MUNICIPIO (numerico) e DSC_LOCALIDADE (que e
# bairro/zona, nao municipio). Por isso NM_Cidade e ID_UF sao preenchidos a
# partir do contexto do download (nome do arquivo / argumento --uf), nao de
# colunas internas do CSV.
COL_CEP_CNEFE = "CEP"


def nome_municipio_do_arquivo(nome_arquivo: str) -> str:
    """Extrai o nome do municipio a partir do nome do arquivo, ex:
    '2504009_CAMPINA_GRANDE.zip' -> 'CAMPINA GRANDE'."""
    base = nome_arquivo.rsplit(".", 1)[0]          # remove .zip
    partes = base.split("_", 1)                     # separa codigo do nome
    nome = partes[1] if len(partes) > 1 else base
    nome = nome.replace("%C3%82", "Â").replace("%c3%82", "Â")  # casos url-encoded conhecidos
    return nome.replace("_", " ").upper()


def extrair_colunas_alvo(df: pd.DataFrame, nome_municipio: str, uf: str) -> pd.DataFrame:
    """Seleciona CEP (unica coluna relevante dentro do CSV) e anexa
    municipio/UF a partir do contexto do download. Remove qualquer outro
    campo (numero, complemento, coordenadas) por cuidado de privacidade,
    conforme Secao 9 do plano."""
    if COL_CEP_CNEFE not in df.columns:
        print(f"[aviso] coluna '{COL_CEP_CNEFE}' nao encontrada. "
              f"Colunas reais no arquivo: {list(df.columns)}", file=sys.stderr)
        return pd.DataFrame(columns=["CEP", "NM_Cidade", "ID_UF"])

    df_sub = df[[COL_CEP_CNEFE]].rename(columns={COL_CEP_CNEFE: "CEP"})
    df_sub = df_sub.dropna(subset=["CEP"])
    df_sub = df_sub[df_sub["CEP"].str.strip() != ""]  # muitos enderecos rurais nao tem CEP
    df_sub = df_sub.drop_duplicates()
    df_sub["NM_Cidade"] = nome_municipio
    df_sub["ID_UF"] = uf.upper()
    return df_sub


def listar_municipios_uf(uf: str, timeout: int = 30) -> dict:
    """Busca a listagem real da pasta da UF e retorna {codigo_municipio: nome_arquivo}."""
    pasta = UF_PARA_PASTA.get(uf.upper())
    if not pasta:
        raise ValueError(f"UF '{uf}' nao mapeada. UFs disponiveis: {list(UF_PARA_PASTA)}")
    url = f"{BASE_URL}{pasta}/"
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    # Pega hrefs terminados em .zip, ex: href="2504009_CAMPINA_GRANDE.zip"
    arquivos = re.findall(r'href="(\d{7}_[^"]+\.zip)"', resp.text)
    return {a.split("_")[0]: a for a in arquivos}


def baixar_municipio_zip(uf: str, nome_arquivo: str, timeout: int = 60) -> pd.DataFrame:
    """Baixa e le o CSV de um municipio a partir do nome de arquivo exato
    (obtido via listar_municipios_uf, ja url-safe)."""
    pasta = UF_PARA_PASTA[uf.upper()]
    url = f"{BASE_URL}{pasta}/{nome_arquivo}"
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        csv_name = [n for n in zf.namelist() if n.lower().endswith(".csv")][0]
        with zf.open(csv_name) as f:
            df = pd.read_csv(f, sep=";", encoding="latin1", dtype=str)
    return df


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uf", required=True, help="UF a amostrar (ex: PB)")
    parser.add_argument("--municipios", default=None,
                         help="codigos de municipio (7 digitos) separados por virgula, ex: 2504009,2507507")
    parser.add_argument("--todos-municipios", action="store_true",
                         help="baixa TODOS os municipios da UF (cuidado: pode ser muitos MB e demorar)")
    parser.add_argument("--n", type=int, default=8000, help="tamanho maximo da amostra final")
    parser.add_argument("--saida", default="cnefe_sample.csv")
    args = parser.parse_args()

    print(f"Listando municipios disponiveis para UF={args.uf}...")
    disponiveis = listar_municipios_uf(args.uf)
    print(f"{len(disponiveis)} municipios encontrados na pasta {UF_PARA_PASTA[args.uf.upper()]}/")

    if args.todos_municipios:
        alvos = disponiveis
    elif args.municipios:
        codigos = [c.strip() for c in args.municipios.split(",")]
        alvos = {c: disponiveis[c] for c in codigos if c in disponiveis}
        faltando = set(codigos) - set(alvos)
        if faltando:
            print(f"[aviso] codigos nao encontrados na listagem: {faltando}", file=sys.stderr)
    else:
        print("Informe --municipios codigo1,codigo2 ou --todos-municipios.", file=sys.stderr)
        sys.exit(1)

    frames = []
    for codigo, nome_arquivo in alvos.items():
        print(f"Baixando {nome_arquivo}...")
        try:
            df_mun = baixar_municipio_zip(args.uf, nome_arquivo)
            nome_cidade = nome_municipio_do_arquivo(nome_arquivo)
            frames.append(extrair_colunas_alvo(df_mun, nome_cidade, args.uf))
        except Exception as e:
            print(f"[erro] falha ao baixar {nome_arquivo}: {e}", file=sys.stderr)
        time.sleep(1)  # gentileza com o servidor do IBGE

    if not frames:
        print("Nenhum dado baixado.", file=sys.stderr)
        sys.exit(1)

    df_final = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["CEP"])
    if len(df_final) > args.n:
        df_final = df_final.sample(n=args.n, random_state=42)

    Path(args.saida).parent.mkdir(parents=True, exist_ok=True)
    df_final.to_csv(args.saida, index=False)
    print(f"Amostra final: {len(df_final):,} registros -> {args.saida}")


if __name__ == "__main__":
    main()

