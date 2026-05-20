# 牛马归栏 (NiuMaHome) v0.9.2

> 打工人，回家路上少操点心。

AI 租房助理：自然语言描述需求 → 四平台聚合（链家/贝壳/安居客/58同城）→ 真实月支出测算 → 三地图通勤精算 → 智能排序推荐。

---

## 🚀 快速启动（本地开发）

### 环境要求
- Node.js 18+
- Python 3.11+

### 1. 安装依赖

```cmd
:: 后端
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

:: 前端
cd frontend
npm install
```

### 2. 配置密钥

复制 `.env.example` 为 `.env.local`，填写以下字段：

```env
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-xxx
AMAP_KEY=xxx
TENCENT_KEY=xxx
BAIDU_AK=xxx
BAIDU_SK=xxx
LIANJIA_COOKIE=xxx    # 从浏览器 F12 复制
BEIKE_COOKIE=xxx
ANJUKE_COOKIE=        # 可选
WUBA_COOKIE=          # 可选，JS渲染站点，填入后才有58同城房源
```

### 3. 启动

```cmd
:: 后端（新窗口）
cd backend && .venv\Scripts\uvicorn app.main:app --port 8001 --reload

:: 前端（新窗口）
cd frontend && npm run dev
```

访问 http://localhost:3000

---

## 🌐 演示模式部署（Vercel，无需后端）

演示模式使用内置 Mock 数据，完全不需要后端服务器、Cookie 或 API Key。
适合作品集展示和 Demo。

### 方式一：Vercel CLI（推荐）

```bash
npm i -g vercel
cd newwj   # 项目根目录（含 vercel.json）
vercel      # 按提示登录后自动部署
# 或直接指定演示模式环境变量：
vercel --env NEXT_PUBLIC_DEMO_MODE=true
```

部署完成后 Vercel 会给你一个 `xxx.vercel.app` 的公网域名。

### 方式二：Vercel 网页操作

1. 注册 [vercel.com](https://vercel.com)（免费）
2. 新建项目 → Import Git Repository（或直接 Upload 项目文件夹）
3. 设置 **Environment Variables**：
   - `NEXT_PUBLIC_DEMO_MODE` = `true`
4. **Root Directory** 设为 `frontend`
5. Framework Preset 选 `Next.js`
6. 点击 Deploy，等待 1-2 分钟

### 方式三：本地预览演示模式

```cmd
cd frontend
set NEXT_PUBLIC_DEMO_MODE=true && npm run dev
```

---

## 🖥️ 生产部署（真实数据，需服务器）

推荐：腾讯云/阿里云轻量应用服务器（2核2G，~60元/月）

```bash
# 服务器上
git clone <你的仓库> / 或解压上传的 tar.gz

# 安装依赖（同本地开发）
# 配置 .env.local（含 Cookie 和 API Key）

# 用 PM2 守护进程
npm i -g pm2
pm2 start "cd backend && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8001" --name niumahome-backend
pm2 start "cd frontend && npm run build && npm run start" --name niumahome-frontend

# Nginx 反向代理（参考）
# location / { proxy_pass http://localhost:3000; }
```

---

## 📁 项目结构

```
newwj/
├── backend/              # FastAPI 后端
│   ├── app/
│   │   ├── api/          # 路由：chat/search/listings/commute/utility/agent/subsidy/housing
│   │   ├── services/
│   │   │   ├── crawler/  # 链家/贝壳/安居客/58同城 爬虫
│   │   │   ├── map/      # 高德/腾讯/百度 地图通勤
│   │   │   ├── cost/     # 真实成本测算引擎
│   │   │   ├── llm/      # DeepSeek AI 客户端
│   │   │   ├── ranker/   # 房源排序引擎
│   │   │   └── storage/  # SQLite session/cache/commute_store
│   │   └── models/       # Pydantic 数据模型
│   └── data/             # 运行时 DB（自动创建）
├── frontend/             # Next.js 14 前端
│   ├── app/
│   │   ├── api/
│   │   │   ├── img-proxy/ # 图片防盗链代理（安居客/58）
│   │   │   └── mock/      # 演示模式 Mock API
│   │   └── page.tsx       # 主页面（Landing + 搜索结果三列布局）
│   ├── components/        # React 组件
│   └── lib/               # API封装/类型/工具
├── docs/
│   ├── CHANGELOG.md       # 完整版本日志
│   └── PRD.md             # 产品需求文档
├── vercel.json            # Vercel 演示部署配置
└── .env.local             # 密钥（不提交，需手动配置）
```

---

## 🛠️ 技术栈

| 层级 | 技术 |
|---|---|
| 前端 | Next.js 14 + TypeScript + Tailwind CSS |
| 后端 | FastAPI + Python 3.11 + Pydantic v2 |
| AI | DeepSeek Chat（OpenAI 兼容协议） |
| 地图 | 高德 + 腾讯 + 百度（三地图协同，21000次/天免费） |
| 存储 | SQLite（session/cache/commute/housing_policy） |
| 爬虫 | httpx + BeautifulSoup4 + brotli |

---

## ⚠️ 注意事项

- **58同城**：纯 JS 渲染 + xxzl 指纹验证，httpx 无法绕过，需填入 `WUBA_COOKIE` 才有数据
- **链家/贝壳 Cookie**：约 7-14 天失效，需从浏览器重新复制
- **高德 Key**：个人版 QPS=3，系统已做 Semaphore 节流，无需升级
- **演示模式**：所有房源为模拟数据，图片来自 Unsplash，无真实房源 URL
