{{ config(materialized='table') }}

SELECT DISTINCT
    s.food_id,
    n.nutrient_id,
    s.value,
    FALSE AS is_null_original
FROM {{ ref('silver_taco_long') }} s
JOIN {{ ref('dim_nutrient') }} n
    ON s.nutrient_name = n.nutrient_name

UNION ALL

SELECT DISTINCT
    s.food_id,
    n.nutrient_id,
    s.value,
    FALSE AS is_null_original
FROM {{ ref('silver_taco_ag_long') }} s
JOIN {{ ref('dim_nutrient') }} n
    ON s.nutrient_name = n.nutrient_name

UNION ALL

SELECT DISTINCT
    s.food_id,
    n.nutrient_id,
    s.value,
    FALSE AS is_null_original
FROM {{ ref('silver_taco_aa_long') }} s
JOIN {{ ref('dim_nutrient') }} n
    ON s.nutrient_name = n.nutrient_name
