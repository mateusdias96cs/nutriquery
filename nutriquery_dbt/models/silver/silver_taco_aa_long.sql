{{ config(materialized='table') }}

SELECT
    food_id,
    food_name,
    food_group,
    nutrient_name,
    value
FROM bronze_taco_aa
UNPIVOT INCLUDE NULLS (
    value FOR nutrient_name IN (
        aa_triptofano_g, aa_treonina_g, aa_isoleucina_g,
        aa_leucina_g, aa_lisina_g, aa_metionina_g, aa_cistina_g,
        aa_fenilalanina_g, aa_tirosina_g, aa_valina_g, aa_arginina_g,
        aa_histidina_g, aa_alanina_g, aa_acido_aspartico_g,
        aa_acido_glutamico_g, aa_glicina_g, aa_prolina_g, aa_serina_g
    )
)










