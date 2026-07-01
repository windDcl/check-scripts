"""
Index A & Index B → Index C merge script
Reads CSV (rule_id_a, rule_id_b), queries ES for latest records by occur_time,
writes combined documents to Index C (full overwrite each run).

Usage:
    python es_merge.py --csv mapping.csv \
        --es http://localhost:9200 \
        --index-a index_a --index-b index_b --index-c index_c
"""

import csv
import argparse
import sys
from datetime import datetime, timezone
from elasticsearch import Elasticsearch

# ── 默认配置（命令行参数优先）──────────────────────────────────
DEFAULT_ES = "http://localhost:9200"
DEFAULT_INDEX_A = "alarm_ip_172.16.21.11"
DEFAULT_INDEX_B = "alarm_ip_172.16.21.222"
DEFAULT_INDEX_C = "ip_alarm_count"


def query_latest(es: Elasticsearch, index: str, rule_id: str) -> dict | None:
    """查询指定索引中 rule_id 最新的一条记录（按 occur_time 倒序）"""
    body = {
        "query": {
            "term": {"rule_id": rule_id}
        },
        "sort": [{"occur_time": "desc"}],
        "size": 1
    }
    resp = es.search(index=index, body=body)
    hits = resp["hits"]["hits"]
    if not hits:
        return None
    return hits[0]["_source"]


def main():
    parser = argparse.ArgumentParser(description="Merge index A & B into index C via CSV mapping")
    parser.add_argument("--csv", required=True, help="CSV file path (columns: rule_id_a, rule_id_b)")
    parser.add_argument("--es", default=DEFAULT_ES, help=f"ES host (default: {DEFAULT_ES})")
    parser.add_argument("--index-a", default=DEFAULT_INDEX_A, help=f"Index A name (default: {DEFAULT_INDEX_A})")
    parser.add_argument("--index-b", default=DEFAULT_INDEX_B, help=f"Index B name (default: {DEFAULT_INDEX_B})")
    parser.add_argument("--index-c", default=DEFAULT_INDEX_C, help=f"Index C name (default: {DEFAULT_INDEX_C})")
    args = parser.parse_args()

    es = Elasticsearch(args.es)
    if not es.ping():
        print(f"[ERROR] 无法连接 ES: {args.es}", file=sys.stderr)
        sys.exit(1)

    # 1. 全量删除 index C（每次覆盖）
    if es.indices.exists(index=args.index_c):
        es.indices.delete(index=args.index_c)
        print(f"[INFO] 已删除旧索引 {args.index_c}")
    es.indices.create(index=args.index_c)
    print(f"[INFO] 已创建新索引 {args.index_c}")

    # 2. 读取 CSV
    rows = []
    with open(args.csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    print(f"[INFO] 读取 {len(rows)} 条映射关系")

    # 3. 逐行查询 + 写入
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    success = 0
    skip = 0
    docs = []

    for i, row in enumerate(rows):
        rule_id_a = row["rule_id_a"].strip()
        rule_id_b = row["rule_id_b"].strip()

        src_a = query_latest(es, args.index_a, rule_id_a)
        src_b = query_latest(es, args.index_b, rule_id_b)

        if not src_a:
            print(f"  [{i+1}] rule_id_a={rule_id_a} 未找到，跳过")
            skip += 1
            continue
        if not src_b:
            print(f"  [{i+1}] rule_id_b={rule_id_b} 未找到，跳过")
            skip += 1
            continue

        doc = {
            "rule_id_a": rule_id_a,
            "rule_id_b": rule_id_b,
            "rule_name_a": src_a.get("rule_name", ""),
            "rule_name_b": src_b.get("rule_name", ""),
            "static_time": now,
            "occur_time_a": src_a.get("occur_time", ""),
            "occur_time_b": src_b.get("occur_time", ""),
            "a_cnt": src_a.get("alarm_count", 0),
            "b_cnt": src_b.get("alarm_count", 0),
        }
        docs.append(doc)
        success += 1

    # 4. 批量写入 index C
    if docs:
        from elasticsearch.helpers import bulk
        actions = [{"_index": args.index_c, "_id": str(i+1), "_source": d} for i, d in enumerate(docs)]
        bulk(es, actions)
        print(f"[INFO] 写入 {len(docs)} 条文档到 {args.index_c}")

    print(f"[DONE] 成功: {success}, 跳过: {skip}, 总计: {len(rows)}")


if __name__ == "__main__":
    main()
