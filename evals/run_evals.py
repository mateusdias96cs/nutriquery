"""
run_evals.py — v3
Comparação inteligente: subset match + tolerância numérica + colunas flexíveis.
"""

import json
import time
import duckdb
import pandas as pd
import numpy as np
import sys, os
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from agent import agent_stateless, agent_sql_only

DATASET_PATH   = Path(__file__).parent / "gold_dataset.json"
RESULTS_DIR    = Path(__file__).parent / "gold_results"
REPORTS_DIR    = Path(__file__).parent / "reports"
DB_PATH        = Path(__file__).parent.parent / "db" / "nutriquery.duckdb"
ROUND_DECIMALS = 2
DELAY_SECONDS  = 15

REPORTS_DIR.mkdir(exist_ok=True)

def normalize_value(v):
    """Normaliza um valor para comparação: float arredondado ou string lower."""
    if isinstance(v, float) or isinstance(v, np.floating):
        return round(float(v), ROUND_DECIMALS)
    if isinstance(v, str):
        return v.strip().lower()
    return v

def row_to_key(row: pd.Series) -> tuple:
    """Converte uma linha em tupla normalizável para comparação set-based."""
    return tuple(normalize_value(v) for v in row.values)

def get_numeric_columns(df: pd.DataFrame) -> list:
    return df.select_dtypes(include=[np.number, np.floating]).columns.tolist()

def smart_compare(df_agent: pd.DataFrame, df_ref: pd.DataFrame) -> tuple[bool, str]:
    """
    Comparação inteligente em 3 níveis:
    1. Exact match (após normalização)
    2. Subset match — ref está contida no agente (agente pode ter mais colunas/linhas)
    3. Numeric subset — valores numéricos do ref aparecem no agente com tolerância
    """
    if df_agent.empty and df_ref.empty:
        return True, "ambos vazios"
    if df_agent.empty:
        return False, "agente retornou vazio"

    # Pega só colunas numéricas e a primeira coluna de texto (food_name) para comparar
    # Identifica coluna de nome do alimento no ref
    str_cols_ref   = df_ref.select_dtypes(include=["object"]).columns.tolist()
    num_cols_ref   = get_numeric_columns(df_ref)

    str_cols_agent = df_agent.select_dtypes(include=["object"]).columns.tolist()
    num_cols_agent = get_numeric_columns(df_agent)

    # Se não há colunas numéricas (ex: Q010 — COUNT)
    if not num_cols_ref:
        val_ref   = set(str(v).strip().lower() for v in df_ref.values.flatten())
        val_agent = set(str(v).strip().lower() for v in df_agent.values.flatten())
        if val_ref == val_agent:
            return True, "exact match (sem numéricos)"
        if val_ref.issubset(val_agent):
            return True, "subset match (sem numéricos)"
        return False, f"valores divergem: ref={val_ref} agente={val_agent}"

    # Nível 1 — exact match por valores numéricos (ignora nomes de colunas)
    if len(num_cols_ref) <= len(num_cols_agent) and len(df_ref) == len(df_agent):
        try:
            vals_ref   = np.sort(df_ref[num_cols_ref].values.astype(float).flatten())
            vals_agent = np.sort(df_agent[num_cols_agent[:len(num_cols_ref)]].values.astype(float).flatten())
            if np.allclose(vals_ref, vals_agent, atol=0.01, equal_nan=True):
                return True, "exact match numérico"
        except Exception:
            pass

    # Nível 2 — subset match: todos os valores numéricos do ref aparecem no agente
    try:
        ref_vals   = set(round(float(v), ROUND_DECIMALS)
                        for v in df_ref[num_cols_ref].values.flatten()
                        if v is not None and not (isinstance(v, float) and np.isnan(v)))
        agent_vals = set(round(float(v), ROUND_DECIMALS)
                        for v in df_agent[num_cols_agent].values.flatten()
                        if v is not None and not (isinstance(v, float) and np.isnan(v)))
        if ref_vals.issubset(agent_vals):
            return True, "subset match numérico"
    except Exception:
        pass

    # Nível 3 — verifica se food_names do ref aparecem no agente (quando ambos têm coluna texto)
    if str_cols_ref and str_cols_agent:
        try:
            names_ref   = set(df_ref[str_cols_ref[0]].str.strip().str.lower())
            names_agent = set(df_agent[str_cols_agent[0]].str.strip().str.lower())
            overlap = len(names_ref & names_agent) / len(names_ref)
            if overlap >= 0.8:
                return True, f"food_name match {overlap*100:.0f}%"
            return False, f"food_name overlap baixo: {overlap*100:.0f}% ({len(names_ref & names_agent)}/{len(names_ref)})"
        except Exception:
            pass

    return False, f"linhas ref={len(df_ref)} agente={len(df_agent)}, sem match"


def check_regra11(response_text: str) -> bool:
    keywords = ["insuficientes", "não apresenta quantidade significativa",
                "limitação", "não possui dados", "taco não", "dados insuficientes"]
    return any(k in response_text.lower() for k in keywords)


def run_eval(q: dict, conn) -> dict:
    qid      = q["id"]
    question = q["question"]
    behavior = q.get("expected_behavior", None)
    diff     = q["difficulty"]

    print(f"\n{'─'*60}")
    print(f"[{qid}] {question}")

    # Só as perguntas de regra 11 avaliam a resposta em prosa; as demais são
    # julgadas reexecutando o SQL, então pulam o nó `respond`.
    needs_prose = behavior == "regra_11_dados_insuficientes"
    graph = agent_stateless if needs_prose else agent_sql_only

    try:
        result = graph.invoke({
            "messages": [{"role": "user", "content": question}],
            "question": question,
            "sql": None, "result": None,
            "error": None, "attempts": 0
        })
        sql_gerado = result.get("sql", "")
        resposta   = result.get("result", "") if needs_prose else ""
    except Exception as e:
        print(f"  ❌ ERRO no agente: {e}")
        return {"id": qid, "difficulty": diff, "question": question,
                "status": "agent_error", "passed": False,
                "sql_gerado": "", "error": str(e)}

    print(f"  SQL: {sql_gerado[:100]}{'...' if len(sql_gerado) > 100 else ''}")

    # Regra 11
    if behavior == "regra_11_dados_insuficientes":
        passed = check_regra11(resposta)
        emoji  = "✅" if passed else "❌"
        status = "regra11_ok" if passed else "regra11_fail"
        print(f"  {emoji} Regra 11 — {'detectada' if passed else 'NÃO detectada'}")
        return {"id": qid, "difficulty": diff, "question": question,
                "status": status, "passed": passed,
                "sql_gerado": sql_gerado, "resposta_preview": resposta[:300]}

    # Execution accuracy
    ref_path = RESULTS_DIR / f"{qid}.parquet"
    if not ref_path.exists():
        print(f"  ⚠️  Parquet não encontrado")
        return {"id": qid, "difficulty": diff, "question": question,
                "status": "ref_missing", "passed": False, "sql_gerado": sql_gerado}

    df_ref = pd.read_parquet(ref_path)

    try:
        df_agent = conn.execute(sql_gerado).df()
    except Exception as e:
        print(f"  ❌ SQL falhou: {e}")
        return {"id": qid, "difficulty": diff, "question": question,
                "status": "sql_error", "passed": False,
                "sql_gerado": sql_gerado, "error": str(e)}

    passed, motivo = smart_compare(df_agent, df_ref)
    emoji = "✅" if passed else "❌"
    print(f"  {emoji} ref:{len(df_ref)}L agente:{len(df_agent)}L — {motivo}")

    return {"id": qid, "difficulty": diff, "question": question,
            "status": "pass" if passed else "fail", "passed": passed,
            "sql_gerado": sql_gerado, "rows_ref": len(df_ref),
            "rows_agent": len(df_agent), "motivo": motivo}


def main():
    with open(DATASET_PATH, encoding="utf-8") as f:
        dataset = json.load(f)

    conn    = duckdb.connect(str(DB_PATH), read_only=True)
    results = []

    for i, q in enumerate(dataset["questions"]):
        r = run_eval(q, conn)
        results.append(r)
        if i < len(dataset["questions"]) - 1:
            print(f"  ⏳ aguardando {DELAY_SECONDS}s...")
            time.sleep(DELAY_SECONDS)

    conn.close()

    total  = len(results)
    passed = sum(1 for r in results if r["passed"])
    by_diff = {}
    for r in results:
        d = r["difficulty"]
        by_diff.setdefault(d, {"total": 0, "passed": 0})
        by_diff[d]["total"] += 1
        if r["passed"]:
            by_diff[d]["passed"] += 1

    report = {
        "run_at": datetime.now().isoformat(),
        "total": total, "passed": passed,
        "accuracy": round(passed / total, 4),
        "by_difficulty": by_diff,
        "details": results
    }

    report_path = REPORTS_DIR / f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n{'═'*60}")
    print(f"  EXECUTION ACCURACY: {passed}/{total} = {report['accuracy']*100:.1f}%")
    print(f"{'═'*60}")
    for d, m in sorted(by_diff.items()):
        pct = m['passed'] / m['total'] * 100
        bar = "█" * m['passed'] + "░" * (m['total'] - m['passed'])
        print(f"  {d:20} {bar}  {m['passed']}/{m['total']} ({pct:.0f}%)")
    print(f"\n  Relatório: {report_path.name}")
    print(f"{'═'*60}")

if __name__ == "__main__":
    main()
