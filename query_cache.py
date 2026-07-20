"""
query_cache.py — cache determinístico de pergunta → SQL/resposta.

Não é um cache semântico (embeddings/similaridade): a chave é a pergunta
normalizada de forma EXATA (mesmo strip_accents + lower que dim_food usa no
dbt para food_name_normalized). Um cache por similaridade poderia casar
"proteína do frango grelhado" com "proteína do frango cru" e devolver o
valor errado sem avisar ninguém — inaceitável num projeto cuja métrica
central é a confiabilidade da resposta (ver evals/). Aqui só se reaproveita
algo quando a pergunta é, após normalização, exatamente a mesma de antes.

Auto-verificação contra dado desatualizado: quem decide usar o cache
(agent.py) sempre reexecuta o SQL cacheado contra o DuckDB (custo zero, é
local) e só reaproveita a RESPOSTA em prosa se o resultado reexecutado bater
byte a byte com o snapshot salvo junto do cache. Se a TACO mudar, o cache de
resposta se autoinvalida sem precisar de TTL nem de invalidação manual.
"""

import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CACHE_PATH = Path(__file__).parent / "db" / "query_cache.sqlite"


def normalize_question(question: str) -> str:
    """strip_accents + lower + colapso de espaços + remoção de pontuação
    final — pra não perder um cache hit só por causa de '?' ou espaço
    duplo, sem virar um matching aproximado (fuzzy)."""
    text = unicodedata.normalize("NFKD", question)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip().rstrip("?!. ")
    return " ".join(text.split())


@dataclass
class CacheEntry:
    sql: str
    result_snapshot: Optional[str]
    response: Optional[str]


class QueryCache:
    """Cache exact-match persistido em SQLite.

    Só deve ser consultado para perguntas SEM histórico de conversa — a
    mesma pergunta literal com contexto de turnos anteriores pode significar
    outra coisa (ex.: "e de gordura?"). Essa decisão é responsabilidade de
    quem chama (agent.py), não desta classe.
    """

    def __init__(self, db_path: Path = CACHE_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS qa_cache (
                question_key    TEXT PRIMARY KEY,
                question_raw    TEXT NOT NULL,
                sql             TEXT NOT NULL,
                result_snapshot TEXT,
                response        TEXT,
                hits            INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        self._conn.commit()

    def lookup(self, question: str) -> Optional[CacheEntry]:
        """Retorna a entrada cacheada, ou None. NÃO soma ao contador `hits` —
        generate_sql/respond consultam o cache sem necessariamente reaproveitar
        (ex.: SQL existe mas ainda sem response). Quem decide reaproveitar de
        fato chama record_hit(), senão o contador mediria "achei uma linha",
        não "evitei uma chamada de LLM"."""
        key = normalize_question(question)
        row = self._conn.execute(
            "SELECT sql, result_snapshot, response FROM qa_cache WHERE question_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return CacheEntry(sql=row[0], result_snapshot=row[1], response=row[2])

    def record_hit(self, question: str) -> None:
        """Chamar só quando uma resposta cacheada REALMENTE substituiu uma
        chamada de LLM — é isso que os relatórios de eval reportam como
        'chamadas evitadas'."""
        key = normalize_question(question)
        self._conn.execute(
            "UPDATE qa_cache SET hits = hits + 1 WHERE question_key = ?", (key,)
        )
        self._conn.commit()

    def store(self, question: str, sql: str, result: Optional[str],
              response: Optional[str] = None) -> None:
        """Grava ou atualiza a entrada. Chamar só depois de uma etapa
        concluída com sucesso (sem erro) — um cache de falha transitória
        (lock do DuckDB, etc.) impediria uma tentativa nova de dar certo.

        `response=None` (caso de agent_sql_only, que nunca gera prosa) NÃO
        apaga uma resposta já cacheada por uma chamada anterior — o COALESCE
        preserva o response existente quando o valor novo é nulo, e só troca
        quando um response de verdade é passado."""
        key = normalize_question(question)
        self._conn.execute("""
            INSERT INTO qa_cache (question_key, question_raw, sql, result_snapshot, response, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(question_key) DO UPDATE SET
                sql=excluded.sql,
                result_snapshot=excluded.result_snapshot,
                response=COALESCE(excluded.response, qa_cache.response),
                updated_at=excluded.updated_at
        """, (key, question, sql, result, response))
        self._conn.commit()

    def stats(self) -> dict:
        total, hits = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(hits), 0) FROM qa_cache"
        ).fetchone()
        return {"entries": total, "total_hits": hits}
