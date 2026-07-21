"""
checks.py — a trilha determinística do eval. Zero LLM, zero token.

Cada eixo é uma métrica independente, não um gate único: um relatório que só
diz "passou/não passou" foi exatamente o que escondeu, por três rodadas, que
metade das perguntas nem tinha sido avaliada.

O comparador segue o modelo do `defog-ai/sql-eval`: subset é permitido **em
coluna** (o agente pode devolver `unit` a mais), nunca **em linha**. A versão
anterior fazia `set(valores_gold).issubset(set(valores_agente))` sobre todos os
numéricos achatados, o que dava 94% de aprovação para um `SELECT` sem `WHERE`.
"""

import numpy as np
import pandas as pd
import sqlglot
from sqlglot import exp
from pandas.testing import assert_series_equal

ROUND_DECIMALS = 2
NULL_SENTINEL = -99999.0

# Colunas de metadado que o gold seleciona por conveniência de leitura, mas que
# não fazem parte da resposta: a unidade é função do nutriente, não do que a
# pergunta pediu. Exigi-las transforma decoração do gold em requisito — a Q002
# ("qual fruta tem maior vitamina C") acertava alimento e valor e reprovava só
# por não ecoar `unit`.
COLUNAS_OPCIONAIS = {"unit"}

WRITE_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter)


# ─────────────────────────── comparação de resultado ───────────────────────────

def normalize_table(df: pd.DataFrame, order_matters: bool) -> pd.DataFrame:
    """Colunas em ordem alfabética; linhas ordenadas só quando a ordem não importa."""
    df = df.copy()
    df.columns = [str(c) for c in df.columns]
    df = df.reindex(sorted(df.columns), axis=1)
    for c in df.columns:
        if pd.api.types.is_float_dtype(df[c]):
            df[c] = df[c].round(ROUND_DECIMALS)
        elif pd.api.types.is_object_dtype(df[c]):
            df[c] = df[c].map(lambda v: v.strip().lower() if isinstance(v, str) else v)
    df = df.fillna(NULL_SENTINEL)
    if not order_matters:
        df = df.sort_values(by=list(df.columns), kind="mergesort")
    return df.reset_index(drop=True)


def _series_key(s: pd.Series) -> pd.Series:
    s = s.reset_index(drop=True)
    if pd.api.types.is_float_dtype(s):
        s = s.round(ROUND_DECIMALS)
    elif pd.api.types.is_object_dtype(s):
        s = s.map(lambda v: v.strip().lower() if isinstance(v, str) else v)
    return s.fillna(NULL_SENTINEL)


def compare_exact(df_gold: pd.DataFrame, df_agent: pd.DataFrame,
                  order_matters: bool) -> bool:
    """Mesma forma, mesmos valores. Nomes de coluna podem diferir."""
    if df_gold.shape != df_agent.shape:
        return False
    g = normalize_table(df_gold, order_matters)
    a = normalize_table(df_agent, order_matters)
    return bool((g.values == a.values).all())


def compare_subset(df_gold: pd.DataFrame, df_agent: pd.DataFrame,
                   order_matters: bool, optional_columns=None) -> tuple[bool, str]:
    """Cada coluna do gold existe no agente, idêntica elemento a elemento.

    Colunas extras no agente são toleradas. Linhas extras NÃO — `assert_series_equal`
    exige mesmo comprimento, que é o que impede o dump da tabela inteira de passar.

    `optional_columns` são colunas que ESTA pergunta declara como decoração do
    gold (não parte da resposta) — mesmo tratamento de `COLUNAS_OPCIONAIS`, mas
    por pergunta, para não afrouxar as perguntas onde a mesma coluna É a resposta
    (ex.: `food_group_name` é decorativo na Q016/Q017 mas é a resposta na Q003).
    """
    opcionais = COLUNAS_OPCIONAIS | {str(c).lower() for c in (optional_columns or [])}
    if df_gold.empty and df_agent.empty:
        return True, "ambos vazios"
    if df_agent.empty:
        return False, "agente devolveu vazio"
    if len(df_agent) != len(df_gold):
        return False, f"cardinalidade: agente {len(df_agent)} vs gold {len(df_gold)}"

    restantes = df_agent.copy()
    restantes.columns = [str(c) for c in restantes.columns]
    casadas, gold_cols = [], []
    for col_gold in df_gold.columns:
        achou = False
        alvo = _series_key(df_gold[col_gold]).sort_values(kind="mergesort").reset_index(drop=True)
        for col_agent in list(restantes.columns):
            cand = _series_key(restantes[col_agent]).sort_values(kind="mergesort").reset_index(drop=True)
            try:
                assert_series_equal(alvo, cand, check_dtype=False, check_names=False)
            except AssertionError:
                continue
            casadas.append(col_agent)
            gold_cols.append(col_gold)
            restantes = restantes.drop(columns=[col_agent])
            achou = True
            break
        if not achou:
            if str(col_gold).lower() in opcionais:
                continue  # metadado; não faz parte da resposta
            return False, (f"coluna '{col_gold}' do gold não tem correspondente "
                           f"no agente com os mesmos valores")

    # Colunas casadas isoladamente podem estar desalinhadas entre si — compara o
    # frame inteiro para pegar linha trocada.
    sub = df_agent[casadas]
    sub.columns = gold_cols
    if compare_exact(df_gold[gold_cols], sub, order_matters):
        return True, "subset por coluna"
    return False, "os valores existem mas as linhas não alinham entre si"


def compare_values(df_gold: pd.DataFrame, df_agent: pd.DataFrame,
                   order_matters: bool, optional_columns=None) -> tuple[bool, str]:
    """Compara a sequência de valores numéricos, não a identidade das linhas.

    Para perguntas com empate exato na fronteira do LIMIT (Q006, Q009): qual dos
    empatados entra na última posição é decisão arbitrária do motor, então exigir
    a linha certa transforma sorte em métrica.
    """
    num_g = df_gold.select_dtypes(include=[np.number])
    num_a = df_agent.select_dtypes(include=[np.number])
    if num_g.empty:
        return compare_subset(df_gold, df_agent, order_matters, optional_columns)
    if len(df_agent) != len(df_gold):
        return False, f"cardinalidade: agente {len(df_agent)} vs gold {len(df_gold)}"

    vg = [round(float(v), ROUND_DECIMALS) for v in num_g.iloc[:, 0]]
    col_a = num_a.iloc[:, 0] if not num_a.empty else None
    if col_a is None:
        return False, "agente não devolveu coluna numérica"
    va = [round(float(v), ROUND_DECIMALS) for v in col_a]
    if not order_matters:
        vg, va = sorted(vg), sorted(va)
    if vg == va:
        return True, "sequência de valores (tolerante a empate)"
    return False, f"valores divergem: gold {vg[:3]}... vs agente {va[:3]}..."


def compare(df_gold: pd.DataFrame, df_agent: pd.DataFrame,
            order_matters: bool, mode: str = "rows",
            optional_columns=None) -> tuple[bool, str]:
    if mode == "values":
        return compare_values(df_gold, df_agent, order_matters, optional_columns)
    return compare_subset(df_gold, df_agent, order_matters, optional_columns)


# ──────────────────────────── checagens estáticas ────────────────────────────

def _nomes_locais(tree) -> set:
    """CTEs, aliases de coluna e aliases de tabela — nomes que o SQL cria e que
    portanto não devem ser cobrados do catálogo do warehouse."""
    locais = set()
    for cte in tree.find_all(exp.CTE):
        if cte.alias:
            locais.add(cte.alias.lower())
            for c in cte.find_all(exp.Alias):
                if c.alias:
                    locais.add(c.alias.lower())
    for a in tree.find_all(exp.Alias):
        if a.alias:
            locais.add(a.alias.lower())
    for t in tree.find_all(exp.TableAlias):
        if t.name:
            locais.add(t.name.lower())
    return locais


def static_checks(sql: str, catalogo: dict) -> dict:
    """Os quatro eixos que não precisam do gold: sintaxe, segurança, schema, eficiência.

    `catalogo` é {tabela: {colunas}} lido do information_schema.
    Cada chave do retorno é 'ok' ou a descrição da violação.
    """
    out = {}
    try:
        stmts = sqlglot.parse(sql, dialect="duckdb")
        tree = stmts[0]
    except Exception as e:
        return {"sintaxe": f"nao_parseia: {str(e)[:60]}", "seguranca": "n/a",
                "schema": "n/a", "eficiencia": "n/a"}
    out["sintaxe"] = "ok"

    escritas = [n for n in tree.walk() if isinstance(n, WRITE_NODES)]
    if escritas:
        out["seguranca"] = f"escrita: {type(escritas[0]).__name__.lower()}"
    elif len([s for s in stmts if s is not None]) > 1:
        out["seguranca"] = "multi_statement"
    else:
        out["seguranca"] = "ok"

    locais = _nomes_locais(tree)
    tabelas = {t.name.lower() for t in tree.find_all(exp.Table) if t.name}
    tab_ruins = {t for t in tabelas if t not in catalogo and t not in locais}
    conhecidas = set()
    for t in tabelas & catalogo.keys():
        conhecidas |= catalogo[t]
    colunas = {c.name.lower() for c in tree.find_all(exp.Column) if c.name}
    col_ruins = {c for c in colunas if c not in conhecidas and c not in locais}
    if tab_ruins or col_ruins:
        partes = []
        if tab_ruins:
            partes.append(f"tabelas={sorted(tab_ruins)}")
        if col_ruins:
            partes.append(f"colunas={sorted(col_ruins)}")
        out["schema"] = "alucinou " + " ".join(partes)
    else:
        out["schema"] = "ok"

    sem_predicado = [j for j in tree.find_all(exp.Join)
                     if not j.args.get("on") and not j.args.get("using")]
    out["eficiencia"] = "ok" if not sem_predicado else f"{len(sem_predicado)} JOIN sem ON"
    return out


def carregar_catalogo(conn) -> dict:
    cat = {}
    for t, c in conn.execute(
        "SELECT table_name, column_name FROM information_schema.columns"
    ).fetchall():
        cat.setdefault(t.lower(), set()).add(c.lower())
    return cat
