"""
core/orchestrator.py

Implementa as 5 estrategias de orquestracao comparadas no paper (Secao 4
do plano): E1 (API unica), E2 (cascata sequencial), E3 (paralela total),
E4 (paralela controlada), E5 (adaptativa).

Todas as estrategias passam primeiro por validacao sintatica local
(validators/cep_validator.py) e cache (core/cache.py) -- so registros que
sobrevivem a essas duas camadas geram chamada externa. Isso e o que
responde QP1 e QP2 do paper.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from core.cache import TTLCache
from core.datasource import DataSource, RespostaFonte, TimeoutErro
from core.metrics import MetricasExecucao
from core.reconciler import divergem
from validators.cep_validator import classificar_localmente


@dataclass
class Registro:
    cep_raw: str
    cidade_informada: str
    uf_informada: str


class ScoreConfiabilidade:
    """Mantem uma janela movel de sucesso/falha por fonte, usada pela
    estrategia E5 para ordenar prioridade de consulta (camada de decisao
    adaptativa, Secao 3.2 do plano).

    O score usa suavizacao bayesiana simples (prior otimista, alpha=3) em
    vez da taxa de sucesso bruta. Sem isso, uma UNICA falha aleatoria no
    inicio da execucao derruba o score da fonte a quase zero -- e, como a
    fonte passa a ser evitada, ela nunca mais e consultada para reconstruir
    o historico ("cold-start lockout"). Esse era exatamente o problema
    observado em teste: apos 1 timeout isolado, uma fonte tecnicamente
    saudavel ficava permanentemente de fora, inflando o numero de chamadas
    das outras duas fontes muito acima do esperado. A suavizacao evita que
    1-2 amostras isoladas dominem a decisao, mantendo o espirito de uma
    politica adaptativa simples sem precisar de um algoritmo de bandit
    completo (ver trabalhos futuros, Secao 6 do paper)."""

    def __init__(self, janela: int = 20, alpha: float = 3.0):
        self.janela = janela
        self.alpha = alpha  # forca do prior otimista (equivalente a "alpha sucessos" ficticios)
        self._historico: dict[str, list[bool]] = {}

    def registrar(self, fonte: str, sucesso: bool) -> None:
        h = self._historico.setdefault(fonte, [])
        h.append(sucesso)
        if len(h) > self.janela:
            h.pop(0)

    def score(self, fonte: str) -> float:
        h = self._historico.get(fonte, [])
        sucessos = sum(h)
        total = len(h)
        # Suavizacao: comeca em 1.0 sem dados, e converge para a taxa de
        # sucesso real conforme mais amostras se acumulam.
        return (sucessos + self.alpha) / (total + self.alpha)

    def ordenar_fontes(self, fontes: list[DataSource]) -> list[DataSource]:
        return sorted(fontes, key=lambda f: self.score(f.nome), reverse=True)


class Orquestrador:
    def __init__(
        self,
        fontes: list[DataSource],
        cache: TTLCache | None = None,
        max_workers_e4: int = 2,
    ):
        self.fontes = fontes
        self.cache = cache if cache is not None else TTLCache()
        self.max_workers_e4 = max_workers_e4
        self.score = ScoreConfiabilidade()

    # ------------------------------------------------------------------
    # Ponto de entrada comum a todas as estrategias
    # ------------------------------------------------------------------
    def processar_lote(self, registros: list[Registro], estrategia: str) -> MetricasExecucao:
        metodo = {
            "E1": self._processar_registro_e1,
            "E2": self._processar_registro_e2,
            "E3": self._processar_registro_e3,
            "E4": self._processar_registro_e3,  # E4 usa a mesma logica por-registro; a diferenca é o limite de concorrência no lote
            "E5": self._processar_registro_e5,
        }.get(estrategia)
        if metodo is None:
            raise ValueError(f"Estrategia desconhecida: {estrategia}")

        m = MetricasExecucao(estrategia=estrategia, total_registros=len(registros))
        inicio = time.perf_counter()

        if estrategia == "E4":
            with ThreadPoolExecutor(max_workers=self.max_workers_e4) as executor:
                futuros = [executor.submit(self._processar_com_camadas, r, metodo, m) for r in registros]
                for f in as_completed(futuros):
                    f.result()
        else:
            for r in registros:
                self._processar_com_camadas(r, metodo, m)

        m.tempo_total_s = time.perf_counter() - inicio
        return m

    # ------------------------------------------------------------------
    # Camadas comuns: validacao sintatica local + cache (antes de qualquer
    # estrategia especifica de orquestracao externa)
    # ------------------------------------------------------------------
    def _processar_com_camadas(self, registro: Registro, metodo_orquestracao, m: MetricasExecucao):
        status_local, cep_norm = classificar_localmente(registro.cep_raw)
        if status_local == "FORMATO_INVALIDO":
            m.chamadas_evitadas += 1
            m.status_final["FORMATO_INVALIDO"] += 1
            return

        cache_key = cep_norm
        cacheado = self.cache.get(cache_key)
        if cacheado is not None:
            m.cache_hits += 1
            m.chamadas_evitadas += 1
            self._classificar_final(cacheado, registro, m)
            return
        m.cache_misses += 1

        resultado = metodo_orquestracao(cep_norm, m)
        if resultado is not None:
            self.cache.set(cache_key, resultado)
        self._classificar_final(resultado, registro, m)

    def _classificar_final(self, respostas: list[RespostaFonte] | None, registro: Registro, m: MetricasExecucao):
        if respostas is None:
            m.status_final["NAO_CONSULTADO"] += 1
            return
        if len(respostas) == 0:
            m.status_final["CEP_INVALIDO"] += 1
            return
        principal = respostas[0]
        if len(respostas) > 1 and divergem(respostas[0], respostas[1]):
            m.conflitos_entre_fontes += 1
            m.status_final["DIVERGENCIA"] += 1
            return
        if registro.uf_informada and principal.uf.upper() != registro.uf_informada.upper():
            m.status_final["DIVERGENCIA"] += 1
            return
        m.status_final["OK"] += 1

    # ------------------------------------------------------------------
    # E1 -- API unica
    # ------------------------------------------------------------------
    def _processar_registro_e1(self, cep: str, m: MetricasExecucao):
        fonte = self.fontes[0]
        return self._consultar_uma(fonte, cep, m)

    # ------------------------------------------------------------------
    # E2 -- cascata sequencial
    # ------------------------------------------------------------------
    def _processar_registro_e2(self, cep: str, m: MetricasExecucao):
        for fonte in self.fontes:
            resposta = self._consultar_uma(fonte, cep, m)
            if resposta is not None:
                return resposta
        return None

    # ------------------------------------------------------------------
    # E3 / E4 -- paralela (a diferenca entre elas e o limite de
    # concorrencia no LOTE, tratado em processar_lote)
    # ------------------------------------------------------------------
    def _processar_registro_e3(self, cep: str, m: MetricasExecucao):
        respostas_validas: list[RespostaFonte] = []
        with ThreadPoolExecutor(max_workers=len(self.fontes)) as executor:
            futuros = {executor.submit(self._consultar_uma, f, cep, m): f for f in self.fontes}
            for fut in as_completed(futuros):
                r = fut.result()
                if r:
                    respostas_validas.extend(r)
        return respostas_validas if respostas_validas else None

    # ------------------------------------------------------------------
    # E5 -- adaptativa
    # ------------------------------------------------------------------
    def _processar_registro_e5(self, cep: str, m: MetricasExecucao):
        fontes_ordenadas = self.score.ordenar_fontes(self.fontes)
        respostas: list[RespostaFonte] = []

        for fonte in fontes_ordenadas:
            resultado = self._consultar_uma(fonte, cep, m)
            if resultado is None:
                # timeout -- tenta a proxima fonte da ordem de prioridade
                continue

            respostas.extend(resultado)

            if len(resultado) == 0:
                # 404 confirmado por esta fonte: resposta definitiva, mesmo
                # criterio de parada usado na cascata E2 -- nao ha motivo
                # para consultar as demais fontes so por causa disso.
                break

            # Resposta valida encontrada. So busca uma 2a fonte como
            # tiebreaker se esta fonte tem historico recente de
            # instabilidade (score baixo) -- nao sempre.
            if self.score.score(fonte.nome) < 0.8 and len(fontes_ordenadas) > 1:
                continue
            break

        return respostas if respostas else None

    # ------------------------------------------------------------------
    def _consultar_uma(self, fonte: DataSource, cep: str, m: MetricasExecucao):
        m.chamadas_por_api[fonte.nome] += 1
        try:
            resposta = fonte.consultar(cep)
            # Confiabilidade mede falha TECNICA (a fonte respondeu ou nao),
            # nao se o CEP existe. Um 404 legitimo e uma resposta valida da
            # fonte, nao deve penalizar o score -- so timeout/instabilidade
            # penaliza.
            self.score.registrar(fonte.nome, sucesso=True)
            return [resposta] if resposta is not None else []
        except TimeoutErro:
            m.timeouts_por_api[fonte.nome] += 1
            self.score.registrar(fonte.nome, sucesso=False)
            return None
