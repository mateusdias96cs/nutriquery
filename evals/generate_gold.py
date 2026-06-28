"""
generate_gold.py
Executa cada sql_reference do gold_dataset.json no DuckDB
e salva o resultado como parquet em evals/gold_results/.
Perguntas com expected_behavior = "regra_11_dados_insuficientes"
são marcadas mas não geram parquet (resultado esperado é mensagem, não dados).
"""

import json
import duckdb
import pandas as pd
from pathlib import Path

DATASET_PATH = Path(__file__).parent / "gold_dataset.json"
RESULTS_DIR  = Path(__file__).parent / "gold_results"
DB_PATH      = Path(__file__).parent.parent / "db" / "nutriquery.duckdb"

RESULTS_DIR.mkdir(exist_ok=True)

def main():
    with open(DATASET_PATH, encoding="utf-8") as f:
        dataset = json.load(f)

    conn = duckdb.connect(str(DB_PATH), read_only=True)

    summary = {"ok": [], "skipped": [], "error": []}

    for q in dataset["questions"]:
        qid        = q["id"]
        question   = q["question"]
        sql        = q["sql_reference"]
        behavior   = q.get("expected_behavior", None)
        out_path   = RESULTS_DIR / f"{qid}.parquet"

        # Perguntas que esperam mensagem de dados insuficientes — não geram parquet
        if behavior == "regra_11_dados_insuficientes":
            print(f"[SKIP] {qid} — expected_behavior=regra_11 (sem parquet)")
            summary["skipped"].append(qid)
            continue

        try:
            df = conn.execute(sql).df()
            df.to_parquet(out_path, index=False)
            print(f"[OK]   {qid} — {len(df)} linhas → {out_path.name}")
            summary["ok"].append(qid)
        except Exception as e:
            print(f"[ERR]  {qid} — {e}")
            summary["error"].append(qid)

    conn.close()

    print("\n─── Resumo ───────────────────────────────")
    print(f"  OK:      {len(summary['ok'])}  {summary['ok']}")
    print(f"  Skipped: {len(summary['skipped'])}  {summary['skipped']}")
    print(f"  Errors:  {len(summary['error'])}  {summary['error']}")

if __name__ == "__main__":
    main()
