# 模块：llm（AI 对话）

## 负责什么

管理与大语言模型（LLM）的通信，负责：
1. 解析用户的自然语言需求 → 结构化的 `ParsedRequirement`
2. 生成房源的 AI 点评（优缺点分析 + 综合打分）
3. 多轮对话上下文管理

## 包含文件

| 文件 | 作用 |
|------|------|
| `factory.py` | LLM 工厂：根据配置选择 DeepSeek 或 Claude |
| `base.py` | 抽象基类，定义 LLM 客户端接口 |
| `deepseek.py` | DeepSeek API 客户端（当前默认，兼容 OpenAI 格式） |
| `claude.py` | Anthropic Claude API 客户端 |

## 工作流程

### 需求解析
```
用户输入: "找番禺南村附近2000以内的整租一居，上班在珠江新城，通勤不超过40分钟"
  ↓
LLM 解析 → ParsedRequirement:
  city: 广州, district: 番禺/南村
  price: base_rent_max=2000
  rental_type: 整租
  destination: 珠江新城
  commute: max_minutes=40
```

### 房源点评
```
输入: Listing + CostBreakdown + CommuteSummary + ParsedRequirement
  ↓
LLM 生成: 优点列表 + 缺点列表 + 综合建议 + 0-10分评分
```

## 当前默认模型

- **DeepSeek**（`deepseek-chat`）：性价比高，中文理解强，API 成本低
- **Claude**（备选）：推理能力更强，适合复杂需求解析场景

切换方式：修改 `.env.local` 中的 `LLM_PROVIDER` 字段。

## 最近更新

- v0.1: Claude API 集成
- v0.2: 切换默认为 DeepSeek，降低成本
- v0.3: 加入 factory 模式，支持运行时切换 LLM
