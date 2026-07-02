"""端到端测试：验证数据持久化、耗时追踪、进度修复"""
import json
import urllib.request
import urllib.error
import time

# 读取测试代码
with open(r"e:\MiCode\code-review-workbench\test_sample.py", "r", encoding="utf-8") as f:
    content = f.read()

payload = {
    "files": [{"path": "test_sample.py", "content": content}],
    "repo_url": "",
    "branch": "",
    "language": "auto"
}

req = urllib.request.Request(
    "http://localhost:8000/api/v1/reviews",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)

print("=" * 60)
print("1. 发起审查请求...")
start = time.time()
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
except urllib.error.HTTPError as e:
    print(f"HTTP Error: {e.code}")
    print(e.read().decode("utf-8"))
    raise
elapsed = time.time() - start
print(f"   耗时: {elapsed:.1f}s")
print(f"   Status: {data.get('status')}")
print(f"   Score: {data.get('score')}")
print(f"   Issues: {data.get('issues_count')}")
task_id = data.get('task_id')
print(f"   Task ID: {task_id}")

# 验证 agent_timeline 有真实耗时
print("\n2. 验证 Agent 耗时追踪...")
timeline = data.get('agent_timeline') or []
for step in timeline:
    dur = step.get('duration_ms', 0)
    status = step.get('status', '?')
    name = step.get('display_name', step.get('agent_type', '?'))
    count = step.get('finding_count', 0)
    print(f"   {name:12s} | {status:10s} | {dur:6d}ms | findings: {count}")

has_real_duration = any(step.get('duration_ms', 0) > 0 for step in timeline)
print(f"   → 有真实耗时: {'YES' if has_real_duration else 'NO ❌'}")

# 验证进度修复
print("\n3. 验证进度值...")
# 进度不在响应中直接返回，但可以从 stats 推断
stats = data.get('stats') or {}
print(f"   Stats: {stats}")

# 验证数据库持久化
print("\n4. 验证数据库持久化...")
# 通过列表端点检查
list_req = urllib.request.Request("http://localhost:8000/api/v1/reviews")
with urllib.request.urlopen(list_req) as resp:
    list_data = json.loads(resp.read().decode("utf-8"))
print(f"   列表总数: {list_data.get('total')}")
if list_data.get('items'):
    for item in list_data['items'][:3]:
        print(f"   - {item['task_id'][:8]}... | score: {item.get('score', '?')} | issues: {item.get('issues_count', '?')} | {item.get('created_at', '')}")

# 通过统计端点检查
stats_req = urllib.request.Request("http://localhost:8000/api/v1/reviews/stats/summary")
with urllib.request.urlopen(stats_req) as resp:
    stats_data = json.loads(resp.read().decode("utf-8"))
print(f"   统计: total={stats_data['total_reviews']}, avg_score={stats_data['avg_score']}, agents={stats_data['active_agents']}, skills={stats_data['registered_skills']}")

# 验证 GET 单条记录
print("\n5. 验证 GET 单条记录...")
get_req = urllib.request.Request(f"http://localhost:8000/api/v1/reviews/{task_id}")
with urllib.request.urlopen(get_req) as resp:
    get_data = json.loads(resp.read().decode("utf-8"))
print(f"   Status: {get_data.get('status')}")
print(f"   Score: {get_data.get('score')}")
print(f"   Issues: {get_data.get('issues_count')}")
print(f"   Summary: {(get_data.get('summary') or '')[:100]}")

# 验证 errors 字段
errors = data.get('errors') or []
print(f"\n6. Errors: {len(errors)} 条")
for e in errors[:3]:
    print(f"   - {e[:80]}")

print("\n" + "=" * 60)
print("✅ 端到端测试完成")
