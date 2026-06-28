CREATE TABLE dim_food_group (
    food_group_id INTEGER PRIMARY KEY,
    food_group_name VARCHAR NOT NULL,
    source VARCHAR NOT NULL
);

CREATE TABLE dim_food (
    food_id INTEGER PRIMARY KEY,
    food_name VARCHAR NOT NULL,
    food_group_id INT REFERENCES dim_food_group(food_group_id),
    source VARCHAR NOT NULL,
    notes VARCHAR
);

CREATE TABLE dim_nutrient (
    nutrient_id INTEGER PRIMARY KEY,
    nutrient_name VARCHAR NOT NULL,
    unit VARCHAR NOT NULL,
    category VARCHAR NOT NULL
);

CREATE TABLE fact_nutrient_values (
    food_id INT,
    nutrient_id INT,
    value FLOAT,
    is_null_original BOOLEAN,
    PRIMARY KEY (food_id, nutrient_id)
);

