from dagster import Definitions, multiprocess_executor, in_process_executor
from dagster_dbt import DbtCliResource

from .assets import (
    bronze_taco_composicao,
    bronze_taco_ag,
    bronze_taco_aa,
    nutriquery_dbt_assets,
    dbt_resource,
)

defs = Definitions(
    assets=[
        bronze_taco_composicao,
        bronze_taco_ag,
        bronze_taco_aa,
        nutriquery_dbt_assets,
    ],
    resources={
        "dbt": dbt_resource,
    },
    executor=in_process_executor,
)
