#!/usr/bin/env python3
"""
Elasticsearch 索引读取工具
支持用户名密码认证，可查询索引信息、文档数据、字段映射等
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from urllib.parse import quote

import requests
from requests.auth import HTTPBasicAuth


class ESClient:
    """Elasticsearch REST API 客户端"""

    def __init__(self, hosts, username, password, timeout=30, verify_ssl=True):
        """
        初始化 ES 客户端

        Args:
            hosts: ES 地址列表，如 ["http://localhost:9200"] 或 "http://localhost:9200"
            username: 用户名
            password: 密码
            timeout: 请求超时时间（秒）
            verify_ssl: 是否验证 SSL 证书
        """
        if isinstance(hosts, str):
            hosts = [h.strip() for h in hosts.split(",")]
        self.hosts = hosts
        self.auth = HTTPBasicAuth(username, password)
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.verify = self.verify_ssl
        self.session.headers.update({"Content-Type": "application/json"})

    def _request(self, method, path, body=None, host_idx=0):
        """发送请求，自动尝试其他节点"""
        last_err = None
        for i in range(len(self.hosts)):
            idx = (host_idx + i) % len(self.hosts)
            url = f"{self.hosts[idx]}{path}"
            try:
                resp = self.session.request(
                    method, url, json=body, timeout=self.timeout
                )
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.RequestException as e:
                last_err = e
                print(f"[WARN] {self.hosts[idx]} 请求失败: {e}", file=sys.stderr)
                continue
        raise ConnectionError(f"所有节点均不可用: {last_err}")

    def cat_indices(self, index_pattern="*", h=None, s=None):
        """
        查询索引列表

        Args:
            index_pattern: 索引匹配模式，如 "log-*"
            h: 显示列，如 "index,health,pri,rep,docs.count,store.size"
            s: 排序字段
        """
        params = []
        if h:
            params.append(f"h={h}")
        if s:
            params.append(f"s={s}")
        qs = f"?{'&'.join(params)}" if params else ""
        path = f"/_cat/indices/{quote(index_pattern, safe='*-,')}{qs}&format=json"
        return self._request("GET", path)

    def get_index_settings(self, index):
        """获取索引 settings"""
        return self._request("GET", f"/{index}/_settings")

    def get_index_mapping(self, index):
        """获取索引 mapping（字段定义）"""
        return self._request("GET", f"/{index}/_mapping")

    def search(self, index, body=None, size=10):
        """
        搜索文档

        Args:
            index: 索引名
            body: 查询 DSL（JSON），为空则 match_all
            size: 返回条数
        """
        if body is None:
            body = {"query": {"match_all": {}}, "size": size}
        elif "size" not in body:
            body["size"] = size
        return self._request("POST", f"/{index}/_search", body)

    def count(self, index, body=None):
        """统计文档数"""
        body = body or {"query": {"match_all": {}}}
        return self._request("POST", f"/{index}/_count", body)

    def cluster_health(self):
        """集群健康状态"""
        return self._request("GET", "/_cluster/health")

    def cluster_stats(self):
        """集群统计信息"""
        return self._request("GET", "/_cluster/stats")

    def node_stats(self):
        """节点统计信息"""
        return self._request("GET", "/_nodes/stats")


def format_docs(hits, fields=None):
    """格式化搜索结果"""
    results = []
    for hit in hits:
        src = hit.get("_source", {})
        if fields:
            src = {k: v for k, v in src.items() if k in fields}
        results.append(src)
    return results


def print_json(data, indent=2):
    """美化 JSON 输出"""
    print(json.dumps(data, indent=indent, ensure_ascii=False, default=str))


def cmd_indices(args, es):
    """列出索引"""
    h = args.fields or "index,health,status,pri,rep,docs.count,store.size"
    data = es.cat_indices(args.pattern, h=h, s=args.sort)
    if args.json:
        print_json(data)
    else:
        if not data:
            print("没有匹配的索引")
            return
        # 表格输出
        cols = [c.strip() for c in h.split(",")]
        header = " | ".join(f"{c:>14}" for c in cols)
        print(header)
        print("-" * len(header))
        for row in data:
            print(" | ".join(f"{str(row.get(c, '')):>14}" for c in cols))
        print(f"\n共 {len(data)} 个索引")


def cmd_search(args, es):
    """搜索文档"""
    body = None
    if args.query:
        body = json.loads(args.query)

    data = es.search(args.index, body=body, size=args.size)
    total = data.get("hits", {}).get("total", {})
    if isinstance(total, dict):
        total = total.get("value", 0)

    hits = data.get("hits", {}).get("hits", [])
    fields = args.fields.split(",") if args.fields else None
    docs = format_docs(hits, fields)

    if args.json:
        print_json({"total": total, "hits": docs})
    else:
        print(f"匹配文档数: {total}\n")
        for i, doc in enumerate(docs):
            print(f"--- [{i + 1}] ---")
            print_json(doc)


def cmd_count(args, es):
    """统计文档数"""
    body = None
    if args.query:
        body = json.loads(args.query)
    data = es.count(args.index, body=body)
    print(f"索引 [{args.index}] 文档数: {data.get('count', 0)}")
    if args.json:
        print_json(data)


def cmd_mapping(args, es):
    """查看索引 mapping"""
    data = es.get_index_mapping(args.index)
    if args.json:
        print_json(data)
    else:
        for idx_name, idx_data in data.items():
            props = idx_data.get("mappings", {}).get("properties", {})
            print(f"索引: {idx_name}")
            print(f"字段数: {len(props)}\n")
            print(f"{'字段名':<30} {'类型':<20} {'说明'}")
            print("-" * 80)
            for field, meta in sorted(props.items()):
                ftype = meta.get("type", "object")
                desc = meta.get("copy_to", "")
                print(f"{field:<30} {ftype:<20} {desc}")


def cmd_settings(args, es):
    """查看索引 settings"""
    data = es.get_index_settings(args.index)
    print_json(data)


def cmd_health(args, es):
    """集群健康状态"""
    data = es.cluster_health()
    if args.json:
        print_json(data)
    else:
        print(f"集群名称: {data.get('cluster_name')}")
        print(f"状态: {data.get('status')}")
        print(f"节点数: {data.get('number_of_nodes')}")
        print(f"分片数: {data.get('active_primary_shards')}/{data.get('active_shards')}")
        print(f"未分配分片: {data.get('unassigned_shards')}")


def cmd_stats(args, es):
    """集群/节点统计"""
    data = es.cluster_stats()
    if args.json:
        print_json(data)
    else:
        nodes = data.get("nodes", {})
        print(f"集群名称: {data.get('cluster_name')}")
        print(f"版本: {data.get('version')}")
        print(f"节点数: {nodes.get('count', {}).get('total')}")
        indices = data.get("indices", {})
        print(f"索引总数: {indices.get('count')}")
        print(f"文档总数: {indices.get('docs', {}).get('count')}")
        print(f"存储大小: {indices.get('store', {}).get('size_in_bytes', 0) / 1024 / 1024:.2f} MB")


def cmd_export(args, es):
    """导出索引数据到 JSON 文件"""
    body = None
    if args.query:
        body = json.loads(args.query)
    else:
        body = {"query": {"match_all": {}}, "size": args.size}

    scroll_id = None
    all_docs = []
    batch_size = min(args.size, 1000)

    # 使用 scroll API 批量拉取
    if args.size > batch_size:
        body["size"] = batch_size
        data = es.search(args.index, body=body, size=batch_size)
        scroll_id = data.get("_scroll_id")
        hits = data.get("hits", {}).get("hits", [])
        all_docs.extend(hits)

        while len(hits) == batch_size and len(all_docs) < args.size:
            data = es._request(
                "POST", f"/_search/scroll",
                {"scroll": "2m", "scroll_id": scroll_id}
            )
            scroll_id = data.get("_scroll_id")
            hits = data.get("hits", {}).get("hits", [])
            all_docs.extend(hits)
            if len(all_docs) >= args.size:
                all_docs = all_docs[:args.size]
                break

        # 清理 scroll
        if scroll_id:
            try:
                es._request("DELETE", f"/_search/scroll", {"scroll_id": scroll_id})
            except Exception:
                pass
    else:
        data = es.search(args.index, body=body, size=batch_size)
        all_docs = data.get("hits", {}).get("hits", [])

    # 提取 _source
    fields = args.fields.split(",") if args.fields else None
    results = format_docs(all_docs, fields)

    output_file = args.output or f"{args.index.replace('*', 'all')}_{datetime.now():%Y%m%d_%H%M%S}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    print(f"已导出 {len(results)} 条文档到 {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Elasticsearch 索引读取工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 列出所有索引
  python es_reader.py indices

  # 搜索文档
  python es_reader.py search log-2026.06.* --size 20

  # 带条件搜索
  python es_reader.py search log-* --query '{"query":{"term":{"level":"ERROR"}},"size":10}'

  # 查看字段映射
  python es_reader.py mapping log-2026.06.30

  # 统计文档数
  python es_reader.py count log-*

  # 导出数据
  python es_reader.py export log-* --size 5000 --output data.json
        """,
    )

    parser.add_argument(
        "-u", "--url", default="http://localhost:9200",
        help="ES 地址，多个用逗号分隔 (默认: http://localhost:9200)",
    )
    parser.add_argument("--user", default="elastic", help="用户名 (默认: elastic)")
    parser.add_argument("--password", required=True, help="密码")
    parser.add_argument("--timeout", type=int, default=30, help="请求超时(秒)")
    parser.add_argument("--no-verify-ssl", action="store_true", help="跳过 SSL 验证")

    sub = parser.add_subparsers(dest="command", help="子命令")

    # indices
    p_idx = sub.add_parser("indices", help="列出索引")
    p_idx.add_argument("pattern", nargs="?", default="*", help="索引匹配模式")
    p_idx.add_argument("-f", "--fields", help="显示列 (逗号分隔)")
    p_idx.add_argument("-s", "--sort", help="排序字段")
    p_idx.add_argument("--json", action="store_true", help="JSON 输出")

    # search
    p_search = sub.add_parser("search", help="搜索文档")
    p_search.add_argument("index", help="索引名")
    p_search.add_argument("-q", "--query", help="查询 DSL (JSON)")
    p_search.add_argument("-n", "--size", type=int, default=10, help="返回条数")
    p_search.add_argument("-f", "--fields", help="只返回指定字段 (逗号分隔)")
    p_search.add_argument("--json", action="store_true", help="JSON 输出")

    # count
    p_count = sub.add_parser("count", help="统计文档数")
    p_count.add_argument("index", help="索引名")
    p_count.add_argument("-q", "--query", help="查询 DSL (JSON)")
    p_count.add_argument("--json", action="store_true", help="JSON 输出")

    # mapping
    p_map = sub.add_parser("mapping", help="查看索引 mapping")
    p_map.add_argument("index", help="索引名")
    p_map.add_argument("--json", action="store_true", help="JSON 输出")

    # settings
    p_set = sub.add_parser("settings", help="查看索引 settings")
    p_set.add_argument("index", help="索引名")
    p_set.add_argument("--json", action="store_true", help="JSON 输出")

    # health
    p_health = sub.add_parser("health", help="集群健康状态")
    p_health.add_argument("--json", action="store_true", help="JSON 输出")

    # stats
    p_stats = sub.add_parser("stats", help="集群统计")
    p_stats.add_argument("--json", action="store_true", help="JSON 输出")

    # export
    p_export = sub.add_parser("export", help="导出索引数据")
    p_export.add_argument("index", help="索引名")
    p_export.add_argument("-q", "--query", help="查询 DSL (JSON)")
    p_export.add_argument("-n", "--size", type=int, default=10000, help="导出条数")
    p_export.add_argument("-o", "--output", help="输出文件路径")
    p_export.add_argument("-f", "--fields", help="只导出指定字段 (逗号分隔)")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    es = ESClient(
        hosts=args.url,
        username=args.user,
        password=args.password,
        timeout=args.timeout,
        verify_ssl=not args.no_verify_ssl,
    )

    commands = {
        "indices": cmd_indices,
        "search": cmd_search,
        "count": cmd_count,
        "mapping": cmd_mapping,
        "settings": cmd_settings,
        "health": cmd_health,
        "stats": cmd_stats,
        "export": cmd_export,
    }

    try:
        commands[args.command](args, es)
    except ConnectionError as e:
        print(f"[ERROR] 连接失败: {e}", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        print(f"[ERROR] HTTP 错误: {e.response.status_code} {e.response.text}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
