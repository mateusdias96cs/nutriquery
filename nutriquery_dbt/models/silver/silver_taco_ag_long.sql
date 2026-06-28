{{ config(materialized='table') }}

SELECT
    food_id,
    food_name,
    food_group,
    nutrient_name,
    value
FROM bronze_taco_ag
UNPIVOT INCLUDE NULLS (
    value FOR nutrient_name IN (
        ag_saturados_g, ag_monoinsaturados_g, ag_poliinsaturados_g,
        ag_12_0_g, ag_14_0_g, ag_16_0_g, ag_18_0_g, ag_20_0_g,
        ag_22_0_g, ag_24_0_g, ag_14_1_g, ag_16_1_g, ag_18_1_g,
        ag_20_1_g, ag_18_2_n6_g, ag_18_3_n3_g, ag_20_4_g,
        ag_20_5_g, ag_22_5_g, ag_22_6_g, ag_18_1t_g, ag_18_2t_g
    )
)
