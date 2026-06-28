{{ config(materialized='table') }}

SELECT DISTINCT
    food_id,
    food_name,
    g.food_group_id,
    'TACO' AS source
FROM {{ ref('silver_taco_long') }} s
JOIN {{ ref('dim_food_group') }} g
    ON s.food_group = g.food_group_name
