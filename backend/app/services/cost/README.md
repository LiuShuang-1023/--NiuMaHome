# 模块：cost（成本测算）

## 负责什么

给每一套房源计算「全包月成本」，即用户每月实际需要支付的所有费用之和。不调用外部 API，全部基于房源字段和用户习惯做本地计算。

## 包含文件

| 文件 | 作用 |
|------|------|
| `engine.py` | 核心计算引擎，输入 `Listing` + 用户需求，输出 `CostBreakdown` |

## 计算内容

| 费用项 | 来源 |
|--------|------|
| 基础房租 | 房源标价 |
| 物业费 | 房源字段（无则估算） |
| 水电费 | 根据用户空调/洗澡/做饭习惯智能估算 |
| 网络费 | 固定估算 |
| 押金摊销 | 押金总额 ÷ 租期（月），算作月均成本 |
| 中介费摊销 | 中介费 ÷ 租期（月） |

## 工作流程

1. 从 `Listing` 提取价格、押金、物业费等字段
2. 根据用户在 `ParsedRequirement.cost_habits` 里填写的生活习惯估算水电
3. 汇总所有费用项生成 `CostBreakdown`
4. `CostBreakdown` 包含每一项的明细，前端可展示费用拆分

## 数据模型

```python
CostBreakdown:
  base_rent: float       # 基础房租
  utilities: float       # 水电费（估算）
  management_fee: float  # 物业费
  internet_fee: float    # 网费
  deposit_monthly: float # 押金摊销
  agent_fee_monthly: float # 中介费摊销
  total: float           # 全包月成本合计
```

## 最近更新

- v0.1: 基础成本计算
- v0.2: 加入押金/中介费摊销
- v0.3: `@computed_field` 改造，字段自动计算
