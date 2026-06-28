import subprocess
from pathlib import Path

from dagster import asset
from dagster_dbt import DbtCliResource, dbt_assets

DBT_PROJECT_DIR = Path("/home/wsl/nutriquery/nutriquery_dbt")
PYTHON = "/home/wsl/nutriquery/.venv/bin/python3"

@asset
def bronze_taco_composicao():
    """Ingere a aba principal do TACO (composição centesimal)."""
    subprocess.run(
        [PYTHON, "/home/wsl/nutriquery/ingest_taco.py"],
        check=True
    )

@asset(deps=[bronze_taco_composicao])
def bronze_taco_ag():
    """Ingere os ácidos graxos do TACO. Roda após bronze_taco_composicao."""
    subprocess.run(
        [PYTHON, "/home/wsl/nutriquery/ingest_taco_ag.py"],
        check=True
    )

@asset(deps=[bronze_taco_ag])
def bronze_taco_aa():
    """Ingere os aminoácidos do TACO. Roda após bronze_taco_ag."""
    subprocess.run(
        [PYTHON, "/home/wsl/nutriquery/ingest_taco_aa.py"],
        check=True
    )

dbt_resource = DbtCliResource(project_dir=DBT_PROJECT_DIR)

@dbt_assets(manifest=DBT_PROJECT_DIR / "target" / "manifest.json")
def nutriquery_dbt_assets(context, dbt: DbtCliResource):
    yield from dbt.cli(
        ["run", "--profiles-dir", str(Path.home() / ".dbt")],
        context=context
    ).stream()
