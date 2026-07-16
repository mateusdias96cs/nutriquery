{{ config(materialized='table') }}

SELECT DISTINCT
    food_id,
    food_name,
    -- ILIKE no DuckDB é sensível a acento; esta coluna existe para o agente
    -- filtrar sem depender de o LLM acertar a acentuação da TACO.
    strip_accents(lower(food_name)) AS food_name_normalized,
    g.food_group_id,
    'TACO' AS source
FROM {{ ref('silver_taco_long') }} s
JOIN {{ ref('dim_food_group') }} g
    ON s.food_group = g.food_group_name
