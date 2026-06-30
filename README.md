# check-scripts

运维/数据检查脚本集合

## elasticsearch 索引读取工具

基于 `requests` 的轻量级 ES 读取脚本，支持用户名密码认证。

### 依赖安装

```bash
pip install requests
```

### 用法

```bash
# 列出所有索引
python es_reader.py -u http://localhost:9200 --user elastic --password YOUR_PASSWORD indices

# 查看索引字段映射
python es_reader.py -u http://localhost:9200 --user elastic --password YOUR_PASSWORD mapping log-2026.06.30

# 搜索文档
python es_reader.py -u http://localhost:9200 --user elastic --password YOUR_PASSWORD search log-* --size 20

# 带条件搜索
python es_reader.py -u http://localhost:9200 --user elastic --password YOUR_PASSWORD search log-* \
  --query '{"query":{"term":{"level":"ERROR"}},"size":10}'

# 统计文档数
python es_reader.py -u http://localhost:9200 --user elastic --password YOUR_PASSWORD count log-*

# 查看集群健康状态
python es_reader.py -u http://localhost:9200 --user elastic --password YOUR_PASSWORD health

# 导出数据到 JSON 文件
python es_reader.py -u http://localhost:9200 --user elastic --password YOUR_PASSWORD export log-* -n 5000 -o data.json

# JSON 格式输出
python es_reader.py -u http://localhost:9200 --user elastic --password YOUR_PASSWORD indices --json
```

### 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-u / --url` | ES 地址，多个逗号分隔 | http://localhost:9200 |
| `--user` | 用户名 | elastic |
| `--password` | 密码（必填） | - |
| `--timeout` | 请求超时（秒） | 30 |
| `--no-verify-ssl` | 跳过 SSL 验证 | false |

### 子命令

| 命令 | 说明 |
|------|------|
| `indices` | 列出索引 |
| `search` | 搜索文档 |
| `count` | 统计文档数 |
| `mapping` | 查看字段映射 |
| `settings` | 查看索引 settings |
| `health` | 集群健康状态 |
| `stats` | 集群统计 |
| `export` | 导出数据到 JSON |
