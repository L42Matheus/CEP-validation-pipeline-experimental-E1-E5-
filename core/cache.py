"""
core/cache.py

Cache em memoria com TTL, usado pelo Orquestrador (camada 4 da arquitetura
do plano v2, Secao 3) para evitar consultas externas repetidas ao mesmo
CEP dentro de um mesmo lote -- e um dos mecanismos que responde a QP2
(reducao de chamadas por deduplicacao/repeticao).

Interface minima consumida pelo orchestrator:
    cache.get(chave) -> valor ou None (miss/expirado)
    cache.set(chave, valor) -> armazena com carimbo de tempo
"""

import time


class TTLCache:
    def __init__(self, ttl_segundos: float = 3600.0):
        self.ttl_segundos = ttl_segundos
        self._store: dict[str, tuple[float, object]] = {}

    def get(self, chave: str):
        item = self._store.get(chave)
        if item is None:
            return None
        expira_em, valor = item
        if time.monotonic() >= expira_em:
            del self._store[chave]
            return None
        return valor

    def set(self, chave: str, valor) -> None:
        self._store[chave] = (time.monotonic() + self.ttl_segundos, valor)
