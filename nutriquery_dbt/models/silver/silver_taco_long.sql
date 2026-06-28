{{ config(materialized='table') }}

SELECT
    food_id,
    food_name,
    food_group,
    nutrient_name,
    value,
    FALSE AS is_null_original
FROM bronze_taco_composicao
UNPIVOT INCLUDE NULLS (
    value FOR nutrient_name IN (
        umidade_pct, energia_kcal, energia_kj, proteina_g,
        lipideos_g, colesterol_mg, carboidrato_g, fibra_alimentar_g,
        cinzas_g, calcio_mg, magnesio_mg, manganes_mg, fosforo_mg,
        ferro_mg, sodio_mg, potassio_mg, cobre_mg, zinco_mg,
        retinol_mcg, re_mcg, rae_mcg, tiamina_mg, riboflavina_mg,
        piridoxina_mg, niacina_mg, vitamina_c_mg
    )
)
