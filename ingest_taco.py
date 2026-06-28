import pandas as pd
import duckdb

df_raw = pd.read_excel(
    '/home/wsl/nutriquery/data/raw/taco.xlsx',
    sheet_name='CMVCol taco3',
    header=None
)

# === EXTRAIR GRUPOS ALIMENTARES COM CARRY FORWARD ===
CABECALHOS_CONHECIDOS = {
    'Número do', 'Alimento', 'nan',
    'Descrição dos alimentos'
}

grupo_atual = None
food_group_map = {}  # food_id → grupo

for _, row in df_raw.iterrows():
    val_col0 = str(row[0]).strip()
    val_col1 = row[1]

    # É um alimento real — coluna 0 é número inteiro
    try:
        food_id = int(float(val_col0))
        food_group_map[food_id] = grupo_atual
    except ValueError:
        # É texto — verifica se é separador de grupo
        if val_col0 not in CABECALHOS_CONHECIDOS and pd.isna(val_col1):
            grupo_atual = val_col0

# Verificar resultado
print("=== GRUPOS ENCONTRADOS ===")
grupos_unicos = list(dict.fromkeys(food_group_map.values()))
for g in grupos_unicos:
    print(f"  {g}")

print()
print("=== AMOSTRA food_group_map ===")
for fid in [1, 2, 70, 71]:
    print(f"  food_id {fid} → {food_group_map.get(fid)}")

# Filtrar só linhas de dados reais
mask = pd.to_numeric(df_raw[0], errors='coerce').notna()
df_foods = df_raw[mask].copy()

# Mapeamento de colunas
colunas = {
    0: 'food_id',
    1: 'food_name',
    2: 'umidade_pct',
    3: 'energia_kcal',
    4: 'energia_kj',
    5: 'proteina_g',
    6: 'lipideos_g',
    7: 'colesterol_mg',
    8: 'carboidrato_g',
    9: 'fibra_alimentar_g',
    10: 'cinzas_g',
    11: 'calcio_mg',
    12: 'magnesio_mg',
    # 13 ignorado — cabeçalho repetido
    14: 'manganes_mg',
    15: 'fosforo_mg',
    16: 'ferro_mg',
    17: 'sodio_mg',
    18: 'potassio_mg',
    19: 'cobre_mg',
    20: 'zinco_mg',
    21: 'retinol_mcg',
    22: 're_mcg',
    23: 'rae_mcg',
    24: 'tiamina_mg',
    25: 'riboflavina_mg',
    26: 'piridoxina_mg',
    27: 'niacina_mg',
    28: 'vitamina_c_mg',
}

df_foods = df_foods[list(colunas.keys())].rename(columns=colunas)

# === LIMPEZA DE VALORES ESPECIAIS ===
nutrient_cols = [c for c in df_foods.columns if c not in ('food_id', 'food_name')]

for col in nutrient_cols:
    # Tr = traços = 0 (decisão de domínio: irrelevante clinicamente)
    df_foods[col] = df_foods[col].replace('Tr', 0)
    # NA = não analisado = null
    df_foods[col] = df_foods[col].replace('NA', None)
    # Converter para float
    df_foods[col] = pd.to_numeric(df_foods[col], errors='coerce')

df_foods['food_id'] = df_foods['food_id'].astype(int)
df_foods['food_group'] = df_foods['food_id'].map(food_group_map)

print(f"Shape: {df_foods.shape}")
print()
print("=== TIPOS APÓS LIMPEZA ===")
print(df_foods.dtypes)
print()
print("=== AMOSTRA DE DADOS ===")
print(df_foods[['food_id', 'food_name', 'proteina_g', 'calcio_mg', 'vitamina_c_mg']].head(5).to_string())
print()
print("=== VALORES NULOS POR COLUNA ===")
print(df_foods.isnull().sum())

# === SALVAR NO BRONZE (DuckDB) ===
conn = duckdb.connect('/home/wsl/nutriquery/db/nutriquery.duckdb')

# Apaga a tabela se já existir (idempotência)
conn.execute("DROP TABLE IF EXISTS bronze_taco_composicao")

# Cria a tabela direto do dataframe pandas
conn.execute("""
    CREATE TABLE bronze_taco_composicao AS
    SELECT * FROM df_foods
""")

count = conn.execute("SELECT COUNT(*) FROM bronze_taco_composicao").fetchone()[0]
print(f"\n=== BRONZE CARREGADO ===")
print(f"Linhas na tabela bronze_taco_composicao: {count}")
print(df_foods[['food_id', 'food_name', 'food_group', 'proteina_g', 'vitamina_c_mg']].head(5).to_string())

conn.close()





