import os

import duckdb

BUCKET = os.environ.get("BUCKET", "taobao-datalake")
RAW_PREFIX = os.environ.get("RAW_PREFIX", "raw")
PROCESSED_PREFIX = os.environ.get("PROCESSED_PREFIX", "processed")
ENDPOINT = os.environ.get("LOCALSTACK_ENDPOINT")
EPSILON = float(os.environ.get("EPSILON", "1e-6"))
NEG_RATIO = int(os.environ.get("NEG_RATIO", "4"))
TOP_POPULAR = int(os.environ.get("TOP_POPULAR", "20"))
POSITIVE_BEHAVIORS = ("buy", "cart", "fav")
BURNIN_DAYS = (1, 2, 3)
TRAIN_DAYS = (4, 5, 6)
VAL_DAYS = (7,)
TEST_DAYS = (8,)
INFER_DAYS = (9,)


def _s3_endpoint(endpoint):
    return endpoint.replace("http://", "").replace("https://", "").rstrip("/")


def _configure_s3(con, endpoint):
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    con.execute(f"SET s3_endpoint='{_s3_endpoint(endpoint)}'")
    con.execute("SET s3_access_key_id='test'")
    con.execute("SET s3_secret_access_key='test'")
    con.execute("SET s3_region='us-east-1'")
    con.execute("SET s3_url_style='path'")
    con.execute("SET s3_use_ssl=false")


def _raw_url(bucket, prefix):
    return f"s3://{bucket}/{prefix}/**/*.parquet"


def load_raw(con, bucket, raw_prefix, endpoint):
    _configure_s3(con, endpoint)
    con.execute(
        f"CREATE OR REPLACE TABLE raw AS "
        f"SELECT user_id, item_id, category_id, behavior_type, timestamp, event_date "
        f"FROM read_parquet('{_raw_url(bucket, raw_prefix)}')"
    )
    con.execute(
        "CREATE OR REPLACE TABLE day_idx AS "
        "SELECT DISTINCT event_date, DENSE_RANK() OVER (ORDER BY event_date) AS day "
        "FROM raw"
    )
    con.execute(
        "CREATE OR REPLACE TABLE events AS "
        "SELECT r.user_id, r.item_id, r.category_id, r.behavior_type, "
        "       d.day, r.event_date "
        "FROM raw r JOIN day_idx d USING (event_date)"
    )


def _split_condition(days):
    return "day IN (" + ",".join(str(d) for d in days) + ")"


def _window_expr(expr, partition, order="day"):
    return (
        f"COALESCE(SUM({expr}) OVER (PARTITION BY {partition} ORDER BY {order} "
        f"ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0)"
    )


def build_history_features(con):
    eng_expr = "SUM(CASE WHEN behavior_type IN ('buy','cart','fav') THEN 1 ELSE 0 END)"
    con.execute(
        "CREATE OR REPLACE TABLE feat_user_item AS "
        f"SELECT user_id, item_id, day, "
        f"       {_window_expr('COUNT(*)', 'user_id, item_id')} AS user_item_freq "
        "FROM events GROUP BY user_id, item_id, day"
    )
    con.execute(
        "CREATE OR REPLACE TABLE feat_user_cat AS "
        f"SELECT user_id, category_id, day, "
        f"       {_window_expr('COUNT(*)', 'user_id, category_id')} AS user_cat_freq, "
        f"       {_window_expr(eng_expr, 'user_id, category_id')} AS user_cat_eng "
        "FROM events GROUP BY user_id, category_id, day"
    )
    con.execute(
        "CREATE OR REPLACE TABLE feat_item AS "
        f"SELECT item_id, day, "
        f"       {_window_expr('COUNT(*)', 'item_id')} AS item_popularity "
        "FROM events GROUP BY item_id, day"
    )
    con.execute(
        "CREATE OR REPLACE TABLE feat_cat AS "
        f"SELECT category_id, day, "
        f"       {_window_expr('COUNT(*)', 'category_id')} AS cat_popularity "
        "FROM events GROUP BY category_id, day"
    )
    con.execute(
        "CREATE OR REPLACE TABLE feat_cat_te AS "
        "SELECT category_id, day, "
        f"       (COALESCE(SUM({eng_expr}) OVER (PARTITION BY category_id ORDER BY day "
        f"                         ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) + 1.0) / "
        f"       (COALESCE(SUM(1) OVER (PARTITION BY category_id ORDER BY day "
        f"                         ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) + 2.0) AS cat_target_enc "
        "FROM events GROUP BY category_id, day"
    )
    con.execute(
        "CREATE OR REPLACE TABLE feat_lag AS "
        "SELECT user_id, category_id, day, "
        "       LAG(COUNT(*), 1) OVER (PARTITION BY user_id, category_id ORDER BY day) AS lag_1, "
        "       LAG(COUNT(*), 2) OVER (PARTITION BY user_id, category_id ORDER BY day) AS lag_2 "
        "FROM events GROUP BY user_id, category_id, day"
    )


def _behavior_list():
    return ",".join(f"'{b}'" for b in POSITIVE_BEHAVIORS)


def build_candidate_splits(con):
    con.execute(
        f"CREATE OR REPLACE TABLE positive_candidates AS "
        f"SELECT user_id, item_id, category_id, day, event_date, 1 AS label "
        f"FROM events "
        f"WHERE behavior_type IN ({_behavior_list()}) "
        f"  AND ({_split_condition(TRAIN_DAYS)} OR {_split_condition(VAL_DAYS)} OR {_split_condition(TEST_DAYS)}) "
        f"GROUP BY user_id, item_id, category_id, day, event_date"
    )
    con.execute(
        "CREATE OR REPLACE TABLE popular_items AS "
        "SELECT item_id, category_id, COUNT(*) AS pop "
        "FROM events "
        "GROUP BY item_id, category_id "
        "ORDER BY pop DESC "
        f"LIMIT {TOP_POPULAR}"
    )


def sample_negatives(con, ratio=NEG_RATIO):
    con.execute(
        f"CREATE OR REPLACE TABLE negatives AS "
        f"SELECT p.user_id, pi.item_id, pi.category_id, p.day, p.event_date, 0 AS label "
        f"FROM (SELECT DISTINCT user_id, day, event_date FROM positive_candidates) p "
        f"CROSS JOIN popular_items pi "
        f"WHERE NOT EXISTS ("
        f"  SELECT 1 FROM events e "
        f"  WHERE e.user_id = p.user_id AND e.item_id = pi.item_id AND e.day = p.day"
        f")"
    )
    con.execute(
        f"CREATE OR REPLACE TABLE negatives_sampled AS "
        f"SELECT n.* FROM ("
        f"  SELECT *, row_number() OVER (PARTITION BY user_id, day ORDER BY item_id) AS rn "
        f"  FROM negatives"
        f") n WHERE n.rn <= {ratio}"
    )


def _feature_select(table):
    return (
        f"COALESCE(ui.user_item_freq, 0) AS user_item_freq, "
        f"COALESCE(uc.user_cat_freq, 0) AS user_cat_freq, "
        f"COALESCE(uc.user_cat_eng, 0) AS user_cat_eng, "
        f"(COALESCE(uc.user_cat_eng, 0) + {EPSILON}) / "
        f"  (COALESCE(uc.user_cat_freq, 0) + {EPSILON}) AS intent_score, "
        f"COALESCE(it.item_popularity, 0) AS item_popularity, "
        f"COALESCE(ca.cat_popularity, 0) AS cat_popularity, "
        f"COALESCE(te.cat_target_enc, 0.5) AS cat_target_enc, "
        f"COALESCE(lf.lag_1, 0) AS lag_1, "
        f"COALESCE(lf.lag_2, 0) AS lag_2"
    )


def _feature_joins(src, alias):
    return (
        f"FROM {src} {alias} "
        f"LEFT JOIN feat_user_item ui ON ui.user_id = {alias}.user_id AND ui.item_id = {alias}.item_id AND ui.day = {alias}.day "
        f"LEFT JOIN feat_user_cat uc ON uc.user_id = {alias}.user_id AND uc.category_id = {alias}.category_id AND uc.day = {alias}.day "
        f"LEFT JOIN feat_item it ON it.item_id = {alias}.item_id AND it.day = {alias}.day "
        f"LEFT JOIN feat_cat ca ON ca.category_id = {alias}.category_id AND ca.day = {alias}.day "
        f"LEFT JOIN feat_cat_te te ON te.category_id = {alias}.category_id AND te.day = {alias}.day "
        f"LEFT JOIN feat_lag lf ON lf.user_id = {alias}.user_id AND lf.category_id = {alias}.category_id AND lf.day = {alias}.day"
    )


def build_train_val_test(con):
    con.execute(
        f"CREATE OR REPLACE TABLE candidates AS "
        f"SELECT user_id, item_id, category_id, day, event_date, label, "
        f"       CASE WHEN {_split_condition(TRAIN_DAYS)} THEN 'train' "
        f"            WHEN {_split_condition(VAL_DAYS)} THEN 'val' "
        f"            WHEN {_split_condition(TEST_DAYS)} THEN 'test' END AS split "
        f"FROM ("
        f"  SELECT user_id, item_id, category_id, day, event_date, label FROM positive_candidates "
        f"  UNION ALL "
        f"  SELECT user_id, item_id, category_id, day, event_date, label FROM negatives_sampled"
        f")"
    )
    con.execute(
        f"CREATE OR REPLACE TABLE features_all AS "
        f"SELECT c.user_id, c.item_id, c.category_id, c.day, c.event_date, c.label, c.split, "
        f"       {_feature_select('c')} "
        f"{_feature_joins('candidates', 'c')}"
    )


def build_inference(con):
    con.execute(
        f"CREATE OR REPLACE TABLE inference AS "
        f"SELECT DISTINCT e.user_id, e.item_id, e.category_id, e.day, e.event_date, NULL AS label, 'infer' AS split, "
        f"       {_feature_select('e')} "
        f"{_feature_joins('events', 'e')} "
        f"WHERE e.{_split_condition(INFER_DAYS)}"
    )


def write_processed(con, bucket, prefix):
    con.execute(
        f"COPY (SELECT * FROM features_all) "
        f"TO 's3://{bucket}/{prefix}/' (FORMAT PARQUET, PARTITION_BY (split), OVERWRITE_OR_IGNORE TRUE)"
    )
    con.execute(
        f"COPY (SELECT * FROM inference) "
        f"TO 's3://{bucket}/{prefix}/' (FORMAT PARQUET, PARTITION_BY (split), OVERWRITE_OR_IGNORE TRUE)"
    )


def run_pipeline(
    bucket=BUCKET,
    raw_prefix=RAW_PREFIX,
    processed_prefix=PROCESSED_PREFIX,
    endpoint=ENDPOINT,
    neg_ratio=NEG_RATIO,
):
    con = duckdb.connect()
    try:
        load_raw(con, bucket, raw_prefix, endpoint)
        build_history_features(con)
        build_candidate_splits(con)
        sample_negatives(con, ratio=neg_ratio)
        build_train_val_test(con)
        build_inference(con)
        write_processed(con, bucket, processed_prefix)
        counts = {
            "train_pos": con.execute(
                "SELECT COUNT(*) FROM features_all WHERE label = 1 AND split = 'train'"
            ).fetchone()[0],
            "train_neg": con.execute(
                "SELECT COUNT(*) FROM features_all WHERE label = 0 AND split = 'train'"
            ).fetchone()[0],
            "val": con.execute(
                "SELECT COUNT(*) FROM features_all WHERE split = 'val'"
            ).fetchone()[0],
            "test": con.execute(
                "SELECT COUNT(*) FROM features_all WHERE split = 'test'"
            ).fetchone()[0],
            "infer": con.execute(
                "SELECT COUNT(*) FROM inference"
            ).fetchone()[0],
        }
    finally:
        con.close()
    return counts


def main():
    result = run_pipeline()
    print(
        f"train_pos={result['train_pos']} train_neg={result['train_neg']} "
        f"val={result['val']} test={result['test']} infer={result['infer']}"
    )
    print(f"Matrices escritas en s3://{BUCKET}/{PROCESSED_PREFIX}/")


if __name__ == "__main__":
    main()