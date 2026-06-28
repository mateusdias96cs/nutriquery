import pandas as pd
import duckdb

df_raw = pd.read_excel(
    '/home/wsl/nutriquery/data/raw/taco.xlsx',
    sheet_name='Aminoácidos TACO3',
    header=None
)

# carry-forward de grupos alimentares
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

# mapeamento — coluna 11 ignorada (food_id repetido)
colunas_aa = {
    0:  'food_id',
    1:  'food_name',
    2:  'aa_triptofano_g',
    3:  'aa_treonina_g',
    4:  'aa_isoleucina_g',
    5:  'aa_leucina_g',
    6:  'aa_lisina_g',
    7:  'aa_metionina_g',
    8:  'aa_cistina_g',
    9:  'aa_fenilalanina_g',
    10: 'aa_tirosina_g',
    12: 'aa_valina_g',
    13: 'aa_arginina_g',
    14: 'aa_histidina_g',
    15: 'aa_alanina_g',
    16: 'aa_acido_aspartico_g',
    17: 'aa_acido_glutamico_g',
    18: 'aa_glicina_g',
    19: 'aa_prolina_g',
    20: 'aa_serina_g'
}

df_foods = df_foods[list(colunas_aa.keys())].rename(columns=colunas_aa)

# Tr → 0, NA → null, forçar numérico
nutrient_cols = [c for c in df_foods.columns if c not in ('food_id', 'food_name')]
for col in nutrient_cols:
    df_foods[col] = df_foods[col].replace('Tr', 0)
    df_foods[col] = df_foods[col].replace('NA', None)
    df_foods[col] = pd.to_numeric(df_foods[col], errors='coerce')

df_foods['food_id'] = df_foods['food_id'].astype(int)
df_foods['food_group'] = df_foods['food_id'].map(food_group_map)

conn = duckdb.connect('/home/wsl/nutriquery/db/nutriquery.duckdb')
conn.execute("DROP TABLE IF EXISTS bronze_taco_aa")
conn.execute("CREATE TABLE bronze_taco_aa AS SELECT * FROM df_foods")
count = conn.execute("SELECT COUNT(*) FROM bronze_taco_aa").fetchone()[0]
print(f"Bronze AA carregado: {count} linhas")

print("\nPrimeiras 3 linhas:")
print(conn.execute("""
    SELECT food_id, food_name, aa_triptofano_g, aa_leucina_g, aa_acido_glutamico_g
    FROM bronze_taco_aa LIMIT 3
""").df())
conn.close()
