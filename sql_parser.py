"""
sql_parser.py — extração do SQL a partir da resposta bruta do LLM.

Centraliza o parsing num único lugar em vez de string-stripping ad hoc dentro
do agente: a regra 10 do SYSTEM_PROMPT pede "só o SQL, sem markdown, sem
explicações", mas o modelo nem sempre obedece à risca — às vezes cerca o SQL
com ```sql ... ```, às vezes antepõe uma frase antes do bloco. Este parser
tenta, em ordem, as formas mais confiáveis de recuperar a query e falha de
forma explícita (SQLParsingError) quando nenhuma delas encontra um
SELECT/WITH — melhor falhar cedo e alimentar o loop de auto-correção do
agente do que executar lixo contra o warehouse.
"""

import re
from typing import Optional


class SQLParsingError(ValueError):
    """A resposta do LLM não contém uma query SQL utilizável."""


class SQLResponseParser:
    """Extrai uma única statement SQL executável de uma resposta de LLM."""

    _FENCE_RE = re.compile(r"```(?:sql)?\s*\n?(.*?)```", re.IGNORECASE | re.DOTALL)
    _STATEMENT_RE = re.compile(r"\b(SELECT|WITH)\b", re.IGNORECASE)
    # Defesa em profundidade: a conexão DuckDB já é read_only=True, mas rejeitar
    # aqui dá um erro claro e instantâneo em vez de estourar lá na execução.
    _WRITE_RE = re.compile(
        r"^\s*(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE|REPLACE"
        r"|ATTACH|DETACH|COPY|EXPORT|IMPORT|CALL|PRAGMA|SET)\b",
        re.IGNORECASE,
    )

    @classmethod
    def parse(cls, raw: str) -> str:
        """Retorna a query SQL limpa e pronta para execução.

        Levanta SQLParsingError se não achar um SELECT/WITH ou se a statement
        encontrada não for de leitura.
        """
        if not raw or not raw.strip():
            raise SQLParsingError("resposta vazia do modelo")

        text = raw.strip()
        sql = cls._from_fence(text) or cls._from_statement_keyword(text)
        if sql is None:
            raise SQLParsingError(
                f"nenhum SELECT/WITH encontrado na resposta: {text[:200]!r}"
            )

        sql = sql.strip().rstrip(";").strip()
        if not cls._STATEMENT_RE.match(sql):
            raise SQLParsingError(
                f"conteúdo extraído não começa com SELECT/WITH: {sql[:200]!r}"
            )
        if cls._WRITE_RE.match(sql):
            raise SQLParsingError(f"statement de escrita rejeitada: {sql[:80]!r}")

        return sql

    @classmethod
    def _from_fence(cls, text: str) -> Optional[str]:
        """Bloco ```sql ... ``` ou ``` ... ``` em qualquer posição do texto —
        ao contrário do startswith("```") original, não exige que o bloco
        abra logo no primeiro caractere da resposta."""
        matches = cls._FENCE_RE.findall(text)
        if not matches:
            return None
        # O primeiro bloco é o que a regra 10 do prompt pede; blocos extras
        # costumam ser a mesma query repetida numa explicação indevida.
        return matches[0].strip()

    @classmethod
    def _from_statement_keyword(cls, text: str) -> Optional[str]:
        """Fallback sem cerca: corta a partir do primeiro SELECT/WITH,
        descartando prosa que o modelo tenha colocado antes."""
        m = cls._STATEMENT_RE.search(text)
        return text[m.start():].strip() if m else None
