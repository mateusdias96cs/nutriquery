{{ config(materialized='table') }}

SELECT
    ROW_NUMBER() OVER (ORDER BY food_group_name) AS food_group_id,
    food_group_name,
    strip_accents(lower(food_group_name)) AS food_group_name_normalized,
    source
FROM (
    SELECT DISTINCT
        food_group AS food_group_name,
        'TACO' AS source
    FROM {{ ref('silver_taco_long') }}
) grupos
ORDER BY food_group_id
