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
import json
import argparse
import sys
from datetime import datetime, timezone
import requests
from requests.auth import HTTPBasicAuth

# ── 默认配置（命令行参数优先）──────────────────────────────────
DEFAULT_ES = "http://localhost:9200"
DEFAULT_INDEX_A = "alarm_ip_172.16.21.11"
DEFAULT_INDEX_B = "alarm_ip_172.16.21.222"
DEFAULT_INDEX_C = "ip_alarm_count"
ES_USER = "elastic"
ES_PASSWORD = ""  # ← 填入密码


def es_get(es_url: str, path: str, auth: HTTPBasicAuth) -> dict:
    resp = requests.get(f"{es_url}/{path}", auth=auth, timeout=10)
    resp.raise_for_status()
    return resp.json()


def es_put(es_url: str, path: str, auth: HTTPBasicAuth, body: dict = None) -> dict:
    resp = requests.put(f"{es_url}/{path}", json=body or {}, auth=auth, timeout=10)
    resp.raise_for_status()
    return resp.json()


def es_post(es_url: str, path: str, auth: HTTPBasicAuth, body: dict) -> dict:
    resp = requests.post(f"{es_url}/{path}", json=body, auth=auth, timeout=10)
    resp.raise_for_status()
    return resp.json()


def query_latest(es_url: str, auth: HTTPBasicAuth, index: str, rule_id: str) -> dict | None:
    """查询指定索引中 rule_id 最新的一条记录（按 occur_time 倒序）"""
    body = {
        "query": {"term": {"rule_id": rule_id}},
        "sort": [{"occur_time": "desc"}],
        "size": 1
    }
    resp = es_post(es_url, f"{index}/_search", auth, body)
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

    auth = HTTPBasicAuth(ES_USER, ES_PASSWORD)
    es_url = args.es.rstrip("/")

    # 检查连接
    try:
        requests.get(f"{es_url}/_cat/health", auth=auth, timeout=5)
    except Exception as e:
        print(f"[ERROR] 无法连接 ES: {es_url} — {e}", file=sys.stderr)
        sys.exit(1)

    # 1. 全量删除 index C（每次覆盖）
    try:
        requests.delete(f"{es_url}/{args.index_c}", auth=auth, timeout=10).raise_for_status()
        print(f"[INFO] 已删除旧索引 {args.index_c}")
    except requests.HTTPError as e:
        if e.response.status_code != 404:
            raise
    requests.put(f"{es_url}/{args.index_c}", json={}, auth=auth, timeout=10).raise_for_status()
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

        src_a = query_latest(es_url, auth, args.index_a, rule_id_a)
        src_b = query_latest(es_url, auth, args.index_b, rule_id_b)

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
        lines = []
        for i, d in enumerate(docs):
            lines.append(json.dumps({"index": {"_index": args.index_c, "_id": str(i + 1)}}))
            lines.append(json.dumps(d))
        ndjson = "\n".join(lines) + "\n"
        resp = requests.post(
            f"{es_url}/_bulk",
            data=ndjson,
            headers={"Content-Type": "application/x-ndjson"},
            auth=auth,
            timeout=30
        )
        result = resp.json()
        if result.get("errors"):
            print(f"[WARN] 部分写入失败: {result['items']}", file=sys.stderr)
        print(f"[INFO] 写入 {len(docs)} 条文档到 {args.index_c}")

    print(f"[DONE] 成功: {success}, 跳过: {skip}, 总计: {len(rows)}")


if __name__ == "__main__":
    main()
