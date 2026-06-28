import pandas as pd
import duckdb

df_raw = pd.read_excel(
    '/home/wsl/nutriquery/data/raw/taco.xlsx',
    sheet_name='AGtaco3',
    header=None
)

# carry-forward de grupos alimentares (mesmo algoritmo do ingest_taco.py)
CABECALHOS_CONHECIDOS = {'Número do', 'Alimento', 'nan', 'Descrição dos alimentos'}
grupo_atual = None
food_group_map = {}

for _, row in df_raw.iterrows():
    val_col0 = str(row[0]).strip()
    val_col1 = row[1]
    try:
        food_id = int(float(val_col0))
        food_group_map[food_id] = grupo_atual
    except ValueError:
        if val_col0 not in CABECALHOS_CONHECIDOS and pd.isna(val_col1):
            grupo_atual = val_col0

# filtrar só linhas de alimentos
mask = pd.to_numeric(df_raw[0], errors='coerce').notna()
df_foods = df_raw[mask].copy()

# mapeamento de colunas — coluna 12 ignorada (food_id repetido)
colunas_ag = {
    0:  'food_id',
    1:  'food_name',
    2:  'ag_saturados_g',
    3:  'ag_monoinsaturados_g',
    4:  'ag_poliinsaturados_g',
    5:  'ag_12_0_g',
    6:  'ag_14_0_g',
    7:  'ag_16_0_g',
    8:  'ag_18_0_g',
    9:  'ag_20_0_g',
    10: 'ag_22_0_g',
    11: 'ag_24_0_g',
    13: 'ag_14_1_g',
    14: 'ag_16_1_g',
    15: 'ag_18_1_g',
    16: 'ag_20_1_g',
    17: 'ag_18_2_n6_g',
    18: 'ag_18_3_n3_g',
    19: 'ag_20_4_g',
    20: 'ag_20_5_g',
    21: 'ag_22_5_g',
    22: 'ag_22_6_g',
    23: 'ag_18_1t_g',
    24: 'ag_18_2t_g'
}

df_foods = df_foods[list(colunas_ag.keys())].rename(columns=colunas_ag)

# Tr → 0, NA → null, forçar numérico
nutrient_cols = [c for c in df_foods.columns if c not in ('food_id', 'food_name')]
for col in nutrient_cols:
    df_foods[col] = df_foods[col].replace('Tr', 0)
    df_foods[col] = df_foods[col].replace('NA', None)
    df_foods[col] = pd.to_numeric(df_foods[col], errors='coerce')

df_foods['food_id'] = df_foods['food_id'].astype(int)
df_foods['food_group'] = df_foods['food_id'].map(food_group_map)

conn = duckdb.connect('/home/wsl/nutriquery/db/nutriquery.duckdb')
conn.execute("DROP TABLE IF EXISTS bronze_taco_ag")
conn.execute("CREATE TABLE bronze_taco_ag AS SELECT * FROM df_foods")
count = conn.execute("SELECT COUNT(*) FROM bronze_taco_ag").fetchone()[0]
print(f"Bronze AG carregado: {count} linhas")

# verificação rápida
print("\nPrimeiras 3 linhas:")
print(conn.execute("SELECT food_id, food_name, ag_saturados_g, ag_18_2_n6_g FROM bronze_taco_ag LIMIT 3").df())
conn.close()
