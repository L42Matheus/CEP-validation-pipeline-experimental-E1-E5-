# CEP-validation — pipeline experimental (E1–E5)

## Como rodar
```bash
cd cep_project
# 1. Conjunto A (real, já validado por você)
python3 datasets/build_cnefe_sample.py --uf PB --municipios 2504009,2507507 --n 8000 --saida cnefe_sample_pb.csv

# 2. Conjuntos B+C (sintético)
python3 datasets/generate_synthetic_cases.py --entrada cnefe_sample_pb.csv --saida dataset_experimental_pb.csv

# 3. Rodar E1–E5 e gerar a tabela comparativa (Seção 5 do paper)
python3 -m experiments.run_experiment --entrada dataset_experimental_pb.csv
```

O `run_experiment.py` usa `MockDataSource` (Conjunto D — falhas simuladas), conforme a recomendação do plano de que a avaliação principal de resiliência use mocks, não APIs reais.

## O que foi testado de verdade (não é código não-verificado)
Rodei o pipeline completo aqui com um CNEFE fictício de 300 registros (não são dados reais nem números do paper — só validação de que o código funciona). Encontrei e corrigi **três bugs reais** no processo:

1. **`generate_synthetic_cases.py`** — loop infinito ao gerar `UF_DIVERGENTE` quando a amostra tem uma única UF (seu caso, amostrando só PB).
2. **`build_cnefe_sample.py`** — nomes de coluna incorretos (`COD_CEP`/`NM_MUNICIPIO` não existem; a coluna certa é `CEP` direto, e não há nome de município no CSV — vem do nome do arquivo).
3. **`core/orchestrator.py` (E5 adaptativa)** — dois bugs de lógica que faziam a estratégia "adaptativa" consultar quase tantas APIs quanto a paralela total (o oposto do objetivo):
   - Não parava em resposta 404 confirmada (diferente da E2);
   - **Cold-start lockout**: um único timeout aleatório no início derrubava o score de uma fonte a ponto dela nunca mais ser escolhida, mesmo sendo a mais confiável no longo prazo. Corrigido com suavização bayesiana (prior otimista), mas o efeito residual (uma fonte tecnicamente boa ficando sub-explorada) **permanece e é um achado real**, não um bug escondido — documentei isso abaixo porque vale citar na Seção 8 (Discussão/Ameaças à Validade) do paper.

## Resultado do teste (dados fictícios — não usar no paper)
| Estratégia | Chamadas externas | Tempo total (s) | Cobertura |
|---|---|---|---|
| E1 (única) | 305 | 3.09 | 0.985 |
| E2 (cascata) | 309 | 3.14 | 1.000 |
| E3 (paralela total) | 918 | 4.43 | 0.989 |
| E4 (paralela controlada) | 924 | 2.24 | 0.989 |
| E5 (adaptativa) | 334 | 4.07 | 0.989 |

E5 chegou perto do número de chamadas de E1/E2 (muito melhor que E3/E4), confirmando a hipótese central do paper — **mas** o log de execução mostrou que uma das três fontes mock (a com menor taxa real de timeout) ficou quase sem uso depois de um único timeout aleatório de largada. Isso é um problema de exploração-vs-explotação clássico de heurísticas gulosas, exatamente o que motiva citar literatura de *multi-armed bandit* (já está no seu `references.bib`: Russo et al. 2024, Ouyang et al. 2021) como trabalho futuro.

## Próximo passo
Rodar `experiments/run_experiment.py` de verdade com `dataset_experimental_pb.csv` (o real, gerado a partir do CNEFE de PB) assim que ele estiver pronto — aí sim os números vão pra Seção 5 do paper.
