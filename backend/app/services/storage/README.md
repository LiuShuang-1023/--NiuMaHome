# 模块：storage（数据存储）

## 负责什么

管理所有本地 SQLite 数据库，分三个独立数据库，职责不交叉：

| 数据库文件 | 类 | 生命周期 | 负责内容 |
|------------|-----|----------|----------|
| `session.db` | `SessionDB` | 会话级（关闭即清） | 当前会话的房源列表、通勤结果、评分 |
| `daily_cache.db` | `DailyCache` | 每日（次日自动清理） | 今日爬取的房源 + geocode 坐标 |
| `commute_store.db` | `CommuteStore` | 永久（只增不删） | 精算原始记录 + 7日滚动均值基准线 |

## 包含文件

| 文件 | 作用 |
|------|------|
| `__init__.py` | 导出 `init_db()`、`session_db` 全局对象 |
| `session_db.py` | 管理 session 级数据：房源、通勤、成本、评分 |
| `daily_cache.py` | 管理今日缓存：房源列表 + geocode 坐标 |
| `commute_store.py` | 永久通勤知识库：精算记录 + 7日均值 + 固化标记 |

## 数据流向

```
用户搜索
  → crawler 爬取房源 → daily_cache.cache_listings（当日有效）
  → amap.geocode()   → daily_cache.cache_geocode（当日有效）
  → geo_filter 离线估算 → session_db.commutes（本次会话）

用户触发精算
  → map/engine.py 调高德/百度 API
  → commute_store.record_precise()（永久保存原始精算值）
  → session_db.commutes 更新（本次会话显示最新值）

每天00:00（后台任务）
  → daily_cache 清理前日房源+geocode缓存
  → commute_store.daily_update()
      ├── 计算7日均值 → 更新 commute_baseline
      ├── 检查固化条件（样本数+CV）→ 更新 is_stable
      └── 删除7天前的原始精算记录
```

## 通勤数据来源标签（source）

| 标签 | 含义 | 精度 |
|------|------|------|
| `stable_baseline` | 已固化路线，直接用均值，跳过API | 高（历史精算均值，波动<阈值） |
| `baseline` | 有历史精算均值但尚未固化 | 中高 |
| `amap` / `baidu` | 本次实时精算 | 高（当前时刻） |
| `offline` | 无历史数据，离线公式估算 | 低（±15~35%） |

## 最近更新

- v0.3: 拆分 session_db / daily_cache，按职责分离
- v0.3.1: 新增 commute_store（永久通勤知识库）
- v0.3.2: daily_cache 删除 cache_commute 表（通勤统一由 commute_store 管）；commute_store 增加 is_stable 固化字段和 CV 计算；daily_update 改用 last_run_date 标记防重复执行
