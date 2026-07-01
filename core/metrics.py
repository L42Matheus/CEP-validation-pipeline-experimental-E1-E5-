"""
core/metrics.py

Coletor de metricas por estrategia, cobrindo exatamente a lista da
Secao 8 do plano: tempo total/medio, chamadas externas por API, chamadas
evitadas, cache hit rate, timeouts/falhas, cobertura, conflitos entre
fontes.
"""

import time
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class MetricasExecucao:
    estrategia: str
    tempo_total_s: float = 0.0
    total_registros: int = 0
    chamadas_por_api: Counter = field(default_factory=Counter)
    chamadas_evitadas: int = 0          # validacao local + cache
    cache_hits: int = 0
    cache_misses: int = 0
    timeouts_por_api: Counter = field(default_factory=Counter)
    status_final: Counter = field(default_factory=Counter)
    conflitos_entre_fontes: int = 0

    @property
    def total_chamadas_externas(self) -> int:
        return sum(self.chamadas_por_api.values())

    @property
    def tempo_medio_por_registro_s(self) -> float:
        return self.tempo_total_s / self.total_registros if self.total_registros else 0.0

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total else 0.0

    @property
    def cobertura(self) -> float:
        classificados = self.total_registros - self.status_final.get("NAO_CONSULTADO", 0)
        return classificados / self.total_registros if self.total_registros else 0.0

    def resumo(self) -> dict:
        return {
            "estrategia": self.estrategia,
            "tempo_total_s": round(self.tempo_total_s, 4),
            "tempo_medio_por_registro_s": round(self.tempo_medio_por_registro_s, 5),
            "total_chamadas_externas": self.total_chamadas_externas,
            "chamadas_por_api": dict(self.chamadas_por_api),
            "chamadas_evitadas": self.chamadas_evitadas,
            "cache_hit_rate": round(self.cache_hit_rate, 3),
            "timeouts_por_api": dict(self.timeouts_por_api),
            "cobertura": round(self.cobertura, 3),
            "conflitos_entre_fontes": self.conflitos_entre_fontes,
            "status_final": dict(self.status_final),
        }


class Cronometro:
    """Context manager simples para medir tempo de execucao."""

    def __enter__(self):
        self._inicio = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.duracao_s = time.perf_counter() - self._inicio
