"""
core/datasource.py

Contrato das fontes externas (camada 6 da arquitetura) + uma implementacao
mock configuravel, usada para o Conjunto D do desenho experimental
(Secao 7 do plano): "mocks com timeout, 404, 500 e respostas conflitantes".

O plano e explicito: "a avaliacao principal de resiliencia deve usar mocks
e respostas gravadas" (Secao 9). Por isso o MockDataSource, e nao chamadas
reais, e a fonte usada nos experimentos de E1-E5.

Uma implementacao real (RealAPIDataSource) e fornecida separadamente e usa
a mesma interface -- troque MockDataSource por ela na amostra pequena e
controlada (Conjunto E do plano), sem mudar o orquestrador.
"""

import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass


class TimeoutErro(Exception):
    """Levantado quando a fonte simula um timeout."""


@dataclass
class RespostaFonte:
    localidade: str
    uf: str
    fonte: str


class DataSource(ABC):
    nome: str

    @abstractmethod
    def consultar(self, cep: str) -> RespostaFonte | None:
        """Retorna RespostaFonte, ou None se o CEP for confirmado como
        inexistente (404). Levanta TimeoutErro em caso de timeout/500."""


class MockDataSource(DataSource):
    """Fonte simulada com taxas configuraveis de falha, latencia e ruido
    na resposta (Conjunto D do plano).

    - registros: dict CEP -> (localidade, uf) representando a "verdade"
      que esta fonte especifica retornaria se respondesse com sucesso.
    - taxa_timeout: probabilidade de simular timeout/instabilidade.
    - taxa_divergencia: probabilidade de retornar uma localidade/UF
      diferente da verdade (simula fontes com cadastro desatualizado).
    - latencia_base_s / latencia_jitter_s: latencia simulada por chamada,
      usada para medir tempo total/medio nas metricas.
    """

    def __init__(
        self,
        nome: str,
        registros: dict[str, tuple[str, str]],
        taxa_timeout: float = 0.05,
        taxa_divergencia: float = 0.02,
        latencia_base_s: float = 0.01,
        latencia_jitter_s: float = 0.01,
        seed: int | None = None,
    ):
        self.nome = nome
        self.registros = registros
        self.taxa_timeout = taxa_timeout
        self.taxa_divergencia = taxa_divergencia
        self.latencia_base_s = latencia_base_s
        self.latencia_jitter_s = latencia_jitter_s
        self._rng = random.Random(seed)

    def consultar(self, cep: str) -> RespostaFonte | None:
        latencia = self.latencia_base_s + self._rng.uniform(0, self.latencia_jitter_s)
        time.sleep(latencia)

        if self._rng.random() < self.taxa_timeout:
            raise TimeoutErro(f"{self.nome}: timeout simulado para CEP {cep}")

        if cep not in self.registros:
            return None  # 404 -- CEP nao encontrado nesta fonte

        localidade, uf = self.registros[cep]
        if self._rng.random() < self.taxa_divergencia:
            # Simula resposta divergente (cadastro desatualizado na fonte)
            localidade = localidade + " (DIVERGENTE)"

        return RespostaFonte(localidade=localidade, uf=uf, fonte=self.nome)
