'use client';

/**
 * 牛马归栏 Landing Page (v0.9.2)
 * Tab1 推荐房源：基于收藏/历史生成推荐搜索词 + 功能介绍 + 初衷 + 更新日志 + Roadmap
 * Tab2 房补功能说明
 * Tab3 小红书 & 闲鱼
 * Tab4 保障房政策
 */

import { useState, useEffect } from 'react';
import {
  Search, MapPin, Bot, Heart, Calculator,
  MessageSquare, Layers, Star, ArrowRight, Clock, RefreshCw,
  GitBranch, Rocket, ChevronDown, ChevronUp,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import SocialMediaListings from '@/components/SocialMediaListings';
import PublicHousingPanel from '@/components/PublicHousingPanel';
import type { FavoriteItem } from '@/lib/useFavorites';

interface LandingPageProps {
  onSearch: (query: string) => void;
  isSearching?: boolean;
  favorites?: FavoriteItem[];
}

// ── 快捷搜索示例 ──────────────────────────────────────────────────
const QUICK_SEARCHES = [
  '广州天河，通勤珠江新城，预算3000',
  '深圳南山，靠近科技园，整租一居',
  '广州番禺，1小时内到天河，2000以内',
  '深圳宝安，靠近地铁，不要地下室',
];

// ── 六大核心功能 ──────────────────────────────────────────────────
const FEATURES = [
  { icon: Bot,        color: 'text-amber-500',   bg: 'bg-amber-50',   title: 'AI 对话理解需求',   desc: '自然语言描述，AI 自动解析城市、通勤目的地、预算、户型，无需手动填表。' },
  { icon: Layers,     color: 'text-sky-500',     bg: 'bg-sky-50',     title: '四平台聚合房源',   desc: '同时抓取链家 / 贝壳 / 安居客 / 58同城，去重合并，一次看全。' },
  { icon: Calculator, color: 'text-emerald-500', bg: 'bg-emerald-50', title: '真实成本测算',     desc: '把水电燃气、物业费、中介费摊销、押金利息全部算进去，告别隐藏成本。' },
  { icon: MapPin,     color: 'text-rose-500',    bg: 'bg-rose-50',    title: '实时通勤精算',     desc: '高德 / 腾讯 / 百度三地图交叉验证，公交/骑行/步行多模式，误差 <5%。' },
  { icon: Heart,      color: 'text-pink-500',    bg: 'bg-pink-50',    title: '收藏夹 & 对比',    desc: '收藏多套房，横向对比月租/通勤时间/面积/水电，快速做决定。' },
  { icon: Star,       color: 'text-violet-500',  bg: 'bg-violet-50',  title: 'AI 点评打分',      desc: 'AI 分析优缺点并给出综合评分，帮你快速过滤差房，专注好房。' },
];

// ── 4步使用指南 ───────────────────────────────────────────────────
const HOW_TO_STEPS = [
  { num: '01', title: '描述你的需求', desc: '自然语言输入，AI 自动解析城市、通勤目的地、预算、户型。' },
  { num: '02', title: 'AI 解析 & 搜索', desc: '同时抓取链家/贝壳/安居客/58同城，30-60 秒出结果。' },
  { num: '03', title: '查看真实成本', desc: '估算水电、物业、中介费摊销，算出每月真实支出。' },
  { num: '04', title: '收藏 & 对比', desc: '收藏中意房源，横向对比关键指标，快速做决定。' },
];

// ── 更新日志（全版本，每页 CHANGELOG_PAGE_SIZE 条）──────────────────
const CHANGELOG_PAGE_SIZE = 4;
const CHANGELOG = [
  {
    version: 'v0.9.1',
    date: '2026-05-20',
    title: '猜你喜欢 + 近期记录 + Tooltip修复',
    items: [
      '推荐Tab改为「猜你喜欢」，展示最近搜索+收藏近期标签，点击直接重搜',
      '4步使用指南配色从纯黑改为渐变暖色',
      'Tooltip 越界修复：自动检测视口边缘，内容不再被遮挡',
      '58同城说明：纯JS渲染+xxzl指纹验证，httpx无法绕过，需Playwright方案',
    ],
  },
  {
    version: 'v0.9.0',
    date: '2026-05-20',
    title: 'Landing重构 + 站内信简化 + 保障房缓存',
    items: [
      '首页4 Tab改版，推荐房源/房补说明/小红书闲鱼/保障房政策',
      '站内信去掉固定必选模块，全部改为费用明细自选（12项）+ 自定义',
      '保障房政策本地 SQLite 缓存，展示数据来源日期，超4个月自动提示刷新',
      '新增 GET /api/housing/stale_check 定期自查端点',
    ],
  },
  {
    version: 'v0.8.1',
    date: '2026-05-20',
    title: '三列布局 + 保障房 + 小红书闲鱼',
    items: [
      '搜索结果页改为三列布局（左:AI对话/房补，中:房源列表，右:社交/保障房）',
      '新增保障房/人才公寓/青年公寓政策查询（6城静态DB + AI兜底）',
      '新增小红书/闲鱼租房帖聚合跳转面板',
      'Landing页重构：搜索框居中Hero + 4个功能Tab',
    ],
  },
  {
    version: 'v0.7.0',
    date: '2026-05-20',
    title: '详情页写回 cost engine + 房补距离筛选',
    items: [
      '详情页押付方式/民水/商水/民电/商电自动写回成本测算引擎',
      '押金成本精算：押一付三→押金3个月×年化3%/12',
      '房补政策距离限制接入地图 Haversine 筛选',
    ],
  },
  {
    version: 'v0.6.0',
    date: '2026-05-20',
    title: '图片防盗链 + 房补智能筛房 + 腾讯地图',
    items: [
      '安居客/58同城图片防盗链：Next.js img-proxy 代理注入 Referer',
      '房补政策智能筛房：粘贴公司政策文本，AI 解析通勤限制一键过滤',
      '腾讯地图接入，三地图协同（高德→腾讯→百度），合计21000次/天免费',
    ],
  },
  {
    version: 'v0.5.4',
    date: '2026-05-18',
    title: '安居客/58同城爬虫接入',
    items: [
      '安居客爬虫（anjuke.py）',
      '58同城爬虫（wuba.py）',
      '搜索API四平台并发抓取',
      '前端平台Tab新增安居客/58同城',
    ],
  },
  {
    version: 'v0.5.3',
    date: '2026-05-18',
    title: 'AI代码块渲染 + 拖拽图标',
    items: [
      'AI问答消息代码块渲染（深色pre块）',
      'AI小助手图标可拖拽（hasDragged ref防误点）',
      '站内信标记检测加强（直接检测---站内信---）',
      'OnboardingGuide localStorage key v3→v4强制重置',
    ],
  },
  {
    version: 'v0.5.2',
    date: '2026-05-18',
    title: 'AI双重响应修复 + 批量精算SSE',
    items: [
      'AI双重响应修复（consumedQueryRef防止StrictMode双触发）',
      '批量精算SSE进度流（/search/precise_batch_stream）',
      'StickyCommuteBar显示批量精算实时进度条',
      '新手引导浮层修复',
    ],
  },
  {
    version: 'v0.5.0',
    date: '2026-05-17',
    title: 'AI悬浮小助手 + 收藏夹',
    items: [
      'AI悬浮小助手（AgentAssistant.tsx），对话/站内信/精算三Tab',
      '收藏夹持久化（useFavorites + localStorage）',
      'FavoritesPanel 展示收藏列表，支持删除和跳转详情',
    ],
  },
  {
    version: 'v0.4.0',
    date: '2026-05-16',
    title: '智能水电估算 + 就近引导重构',
    items: [
      '水电费 Wizard：AI 根据空调/洗澡/做饭习惯精准估算月费',
      '就近引导：优先匹配最近地铁站/公交站',
      'RequirementPanel 需求摘要面板',
    ],
  },
  {
    version: 'v0.3.x',
    date: '2026-05-14',
    title: '地理粗筛 + SQLite + 离线估算',
    items: [
      '地理粗筛：根据通勤目的地坐标筛选合理半径内房源',
      'SQLite session DB 持久化搜索会话和房源缓存',
      '离线成本估算引擎（cost/engine.py）',
      '高德+百度双地图通勤时间并行查询',
    ],
  },
  {
    version: 'v0.2.x',
    date: '2026-05-13',
    title: '详情弹窗 + AI点评 + 通勤优化',
    items: [
      'ListingDetailModal 详情弹窗，完整房源信息',
      'AI点评打分（DeepSeek），自动分析优缺点',
      '通勤板块：百度+高德×步行/骑行/公交',
      'TopBar 顶部导航',
    ],
  },
  {
    version: 'v0.1.0',
    date: '2026-05-12',
    title: 'MVP — AI对话解析 + 链家爬虫',
    items: [
      'AI 对话式需求理解，DeepSeek 解析自然语言为结构化 JSON',
      '链家租房爬虫（lianjia.py），抓取列表页',
      'Next.js 14 + FastAPI 基础架构',
      '基础房源卡片（ListingCard.tsx）',
    ],
  },
];

// ── Roadmap ────────────────────────────────────────────────────────
const ROADMAP = [
  {
    status: 'done',
    label: '已完成',
    color: 'text-emerald-600',
    bg: 'bg-emerald-50',
    border: 'border-emerald-200',
    dot: 'bg-emerald-500',
    items: [
      'AI 对话解析需求',
      '链家 / 贝壳聚合抓取',
      '安居客 / 58同城接入',
      '三地图通勤精算',
      '水电真实成本估算',
      '房补政策智能筛房',
      '收藏夹 & AI点评',
      '站内信自动生成',
      '保障房政策查询',
    ],
  },
  {
    status: 'wip',
    label: '进行中',
    color: 'text-amber-600',
    bg: 'bg-amber-50',
    border: 'border-amber-200',
    dot: 'bg-amber-400',
    items: [
      '58同城 Playwright 无头浏览器抓取',
      '安居客更多城市适配',
      '收藏夹横向对比表格',
    ],
  },
  {
    status: 'planned',
    label: '规划中',
    color: 'text-sky-600',
    bg: 'bg-sky-50',
    border: 'border-sky-200',
    dot: 'bg-sky-400',
    items: [
      '闲鱼 / 小红书深度集成（WebSocket爬虫）',
      '价格走势图（近30天均价）',
      'AI 自动联系房东（站内信批量发送）',
      'Tauri 桌面客户端',
      '移动端 APP（React Native）',
      '多用户 SaaS 部署',
    ],
  },
];

// ── 搜索历史 localStorage ─────────────────────────────────────────
const HISTORY_KEY = 'niumahome_search_history_v1';
const MAX_HISTORY = 8;

function loadHistory(): string[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch { return []; }
}

export function saveSearchHistory(query: string) {
  if (typeof window === 'undefined') return;
  try {
    const prev = loadHistory();
    const next = [query, ...prev.filter((q) => q !== query)].slice(0, MAX_HISTORY);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
  } catch { /* ignore */ }
}

type TabId = 'listings' | 'subsidy' | 'social' | 'housing';
const TABS: { id: TabId; label: string; icon: string }[] = [
  { id: 'listings', label: '猜你喜欢', icon: '🏠' },
  { id: 'subsidy',  label: '房补功能', icon: '🏢' },
  { id: 'social',   label: '小红书&闲鱼', icon: '📕' },
  { id: 'housing',  label: '保障房政策', icon: '🏛️' },
];

export default function LandingPage({ onSearch, isSearching, favorites = [] }: LandingPageProps) {
  const [query, setQuery] = useState('');
  const [activeTab, setActiveTab] = useState<TabId>('listings');
  const [feedbackText, setFeedbackText] = useState('');
  const [feedbackSent, setFeedbackSent] = useState(false);
  const [searchHistory, setSearchHistory] = useState<string[]>([]);
  const [changelogOpen, setChangelogOpen] = useState(false);
  const [changelogPage, setChangelogPage] = useState(0);

  useEffect(() => { setSearchHistory(loadHistory()); }, []);

  function handleSearch(q?: string) {
    const finalQ = (q ?? query).trim();
    if (!finalQ) return;
    saveSearchHistory(finalQ);
    onSearch(finalQ);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') handleSearch();
  }

  function clearHistory() {
    localStorage.removeItem(HISTORY_KEY);
    setSearchHistory([]);
  }

  function handleFeedbackSubmit() {
    if (!feedbackText.trim()) return;
    setFeedbackSent(true);
    setFeedbackText('');
    setTimeout(() => setFeedbackSent(false), 4000);
  }

  const hasFavorites = favorites.length > 0;
  const hasHistory = searchHistory.length > 0;

  return (
    <div className="min-h-screen bg-gradient-to-b from-amber-50 via-white to-stone-50">

      {/* ══ Demo 模式横幅 ════════════════════════════════════════════ */}
      {process.env.NEXT_PUBLIC_DEMO_MODE === 'true' && (
        <div className="sticky top-0 z-50 bg-amber-500 py-2 text-center text-sm font-medium text-white shadow">
          🎬 演示模式 — 展示真实 UI 和数据结构，房源为模拟数据。
          <a
            href="https://github.com/yourname/niumahome"
            target="_blank"
            rel="noopener noreferrer"
            className="ml-3 underline hover:text-amber-100"
          >
            查看源码 →
          </a>
        </div>
      )}

      {/* ══ Hero ══════════════════════════════════════════════════════ */}
      <section className="flex flex-col items-center px-4 pt-20 pb-8">
        <div className="mb-6 flex flex-col items-center gap-2">
          <div className="flex items-center gap-3">
            <span className="text-5xl">🐂</span>
            <div>
              <h1 className="text-4xl font-black tracking-tight text-stone-900">牛马归栏</h1>
              <p className="text-sm font-medium text-amber-600 tracking-widest">NiuMaHome</p>
            </div>
          </div>
          <p className="mt-1 max-w-lg text-center text-sm text-stone-500 leading-relaxed">
            打工人的 AI 租房助理 · 跨平台聚合 · 真实成本 · 通勤精算
          </p>
        </div>

        {/* 主搜索框 */}
        <div className="w-full max-w-2xl">
          <div className="flex items-center gap-2 rounded-2xl border-2 border-amber-300 bg-white px-4 py-3 shadow-lg transition focus-within:border-amber-500 focus-within:shadow-xl focus-within:shadow-amber-100/60">
            <Search className="h-5 w-5 shrink-0 text-amber-400" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="用一句话描述需求，如：广州天河，通勤珠江新城，3000以内整租..."
              className="flex-1 bg-transparent text-sm text-stone-800 placeholder-stone-400 outline-none"
              autoFocus
            />
            <button
              onClick={() => handleSearch()}
              disabled={!query.trim() || isSearching}
              className="flex items-center gap-1.5 rounded-xl bg-amber-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-amber-600 disabled:opacity-50 active:scale-95"
            >
              {isSearching ? (
                <span className="flex items-center gap-1">
                  <span className="h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
                  搜索中
                </span>
              ) : (
                <>搜索 <ArrowRight className="h-4 w-4" /></>
              )}
            </button>
          </div>

          {/* 快捷搜索 */}
          <div className="mt-3 flex flex-wrap justify-center gap-2">
            <span className="text-xs text-stone-400">试试：</span>
            {QUICK_SEARCHES.map((q) => (
              <button
                key={q}
                onClick={() => setQuery(q)}
                className="rounded-full border border-stone-200 bg-white px-3 py-1 text-xs text-stone-600 transition hover:border-amber-300 hover:text-amber-700"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* ══ 四 Tab ════════════════════════════════════════════════════ */}
      <section className="mx-auto max-w-4xl px-4 pb-4">
        <div className="flex rounded-2xl border border-stone-200 bg-white shadow-sm overflow-hidden mb-4">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                'flex-1 py-3 text-sm font-medium transition flex items-center justify-center gap-1.5',
                activeTab === tab.id
                  ? 'bg-amber-500 text-white'
                  : 'text-stone-500 hover:bg-stone-50 hover:text-stone-700',
              )}
            >
              <span>{tab.icon}</span>
              <span className="hidden sm:inline">{tab.label}</span>
            </button>
          ))}
        </div>

        {/* ── Tab1: 推荐房源 ─────────────────────────────────────────── */}
        {activeTab === 'listings' && (
          <div className="space-y-5">

            {/* 猜你喜欢：搜索历史 + 收藏夹近期 */}
            {(hasHistory || hasFavorites) ? (
              <div className="space-y-3">
                {/* 最近搜索 */}
                {hasHistory && (
                  <div className="rounded-2xl border border-stone-200 bg-white p-4">
                    <div className="mb-3 flex items-center gap-2">
                      <Clock className="h-4 w-4 text-stone-400" />
                      <span className="text-sm font-bold text-stone-700">最近搜索</span>
                      <button
                        onClick={clearHistory}
                        className="ml-auto flex items-center gap-1 text-xs text-stone-400 transition hover:text-red-400"
                      >
                        <RefreshCw className="h-3 w-3" />清除
                      </button>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {searchHistory.map((h) => (
                        <button
                          key={h}
                          onClick={() => handleSearch(h)}
                          className="flex items-center gap-1.5 rounded-full border border-stone-200 bg-stone-50 px-3 py-1 text-xs text-stone-600 transition hover:border-amber-300 hover:bg-amber-50 hover:text-amber-700"
                        >
                          <Search className="h-3 w-3" />
                          {h}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* 收藏夹近期 */}
                {hasFavorites && (
                  <div className="rounded-2xl border border-pink-200 bg-pink-50 p-4">
                    <div className="mb-3 flex items-center gap-2">
                      <Heart className="h-4 w-4 text-pink-500" />
                      <span className="text-sm font-bold text-pink-700">收藏 {favorites.length} 套</span>
                      <span className="ml-auto text-xs text-pink-400">点击重新搜索该地区</span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {favorites.slice(0, 8).map((fav) => {
                        const l = fav.rec.listing;
                        const city = (l.address || '').slice(0, 2);
                        const community = l.community || l.title?.slice(0, 12) || '';
                        const searchQ = [city, community, l.price_base ? `预算${Math.round(l.price_base * 1.3)}以内` : ''].filter(Boolean).join(' ');
                        return (
                          <button
                            key={l.id}
                            onClick={() => handleSearch(searchQ)}
                            className="flex items-center gap-1.5 rounded-full border border-pink-200 bg-white px-3 py-1.5 text-xs text-stone-700 font-medium transition hover:border-amber-300 hover:bg-amber-50 hover:text-amber-800 active:scale-95"
                          >
                            <Heart className="h-3 w-3 text-pink-400" />
                            {community || searchQ}
                            {l.price_base ? <span className="text-stone-400">¥{l.price_base}</span> : null}
                          </button>
                        );
                      })}
                    </div>
                    {favorites.length > 8 && (
                      <p className="mt-2 text-xs text-pink-400">还有 {favorites.length - 8} 套，搜索后在右侧收藏面板查看</p>
                    )}
                  </div>
                )}
              </div>
            ) : (
              /* 无记录引导 */
              <div className="rounded-2xl border-2 border-dashed border-amber-200 bg-amber-50/60 px-6 py-8 text-center">
                <div className="text-3xl mb-2">🏠</div>
                <div className="text-sm font-semibold text-amber-700 mb-1">还没有搜索记录和收藏</div>
                <p className="text-xs text-stone-500">先在上方搜索房源，搜索历史和收藏的房源会显示在这里</p>
              </div>
            )}

          </div>
        )}

        {/* ── Tab2: 房补功能 ─────────────────────────────────────────── */}
        {activeTab === 'subsidy' && (
          <div className="space-y-4">
            <div className="rounded-2xl border-2 border-violet-200 bg-violet-50 p-5">
              <div className="flex items-start gap-3">
                <span className="text-3xl flex-shrink-0">🏢</span>
                <div>
                  <div className="font-bold text-violet-900">房补政策智能筛房</div>
                  <p className="mt-1 text-sm text-violet-800 leading-relaxed">
                    先搜索房源，进入结果页后在左侧「房补政策」栏粘贴公司政策文本，
                    AI 自动识别「骑行20分钟」「公交30分钟以内」等限制条件，一键筛出符合报销条件的房源。
                  </p>
                </div>
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              {[
                { icon: '📋', title: '粘贴政策文本', desc: '把公司租房补贴政策原文粘贴进去，AI 理解自然语言' },
                { icon: '🤖', title: 'AI 识别条件', desc: '自动提取通勤方式限制（公交/骑行/步行）和时间上限' },
                { icon: '✅', title: '一键筛选',    desc: '点击「应用筛选」，只显示满足房补申请条件的房源' },
              ].map((item) => (
                <div key={item.title} className="rounded-xl border border-stone-200 bg-white p-4 text-center">
                  <div className="text-2xl mb-2">{item.icon}</div>
                  <div className="text-sm font-semibold text-stone-800 mb-1">{item.title}</div>
                  <p className="text-xs text-stone-500">{item.desc}</p>
                </div>
              ))}
            </div>
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800">
              💡 <b>使用方式：</b>先搜索房源进入结果页，在左侧「房补政策智能筛房」栏粘贴政策文本。
            </div>
          </div>
        )}

        {/* ── Tab3: 社交平台帖 ────────────────────────────────────────── */}
        {activeTab === 'social' && (
          <SocialMediaListings defaultCity="" defaultDistrict="" defaultCommunity="" />
        )}

        {/* ── Tab4: 保障房政策 ────────────────────────────────────────── */}
        {activeTab === 'housing' && (
          <PublicHousingPanel defaultCity="" />
        )}
      </section>

      {/* ══ 分割线 ════════════════════════════════════════════════════ */}
      <div className="mx-auto max-w-4xl px-4 mt-8">
        <div className="flex items-center gap-3">
          <div className="flex-1 h-px bg-stone-200" />
          <span className="text-xs text-stone-400 font-medium tracking-widest">功能介绍 · 初衷 · 路线 · 日志</span>
          <div className="flex-1 h-px bg-stone-200" />
        </div>
      </div>

      {/* ══ 六大核心功能 ══════════════════════════════════════════════ */}
      <section className="mx-auto max-w-4xl px-4 pt-8 pb-4">
        <div className="mb-5 text-center">
          <h2 className="text-xl font-bold text-stone-900">六大核心功能</h2>
          <p className="mt-1 text-sm text-stone-500">为打工人量身打造，让租房不再踩坑</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(({ icon: Icon, color, bg, title, desc }) => (
            <div key={title} className="rounded-2xl border border-stone-200 bg-white p-4 shadow-sm hover:shadow-md transition-shadow">
              <div className={cn('mb-3 inline-flex h-10 w-10 items-center justify-center rounded-xl', bg)}>
                <Icon className={cn('h-5 w-5', color)} />
              </div>
              <div className="text-sm font-semibold text-stone-800">{title}</div>
              <p className="mt-1 text-xs leading-relaxed text-stone-500">{desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ══ 4步使用指南 ══════════════════════════════════════════════ */}
      <section className="mx-auto max-w-4xl px-4 py-6">
        <div className="mb-5 text-center">
          <h2 className="text-xl font-bold text-stone-900">4 步找到好房</h2>
          <p className="mt-1 text-sm text-stone-500">从需求到决策，全程 AI 辅助</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {HOW_TO_STEPS.map((step, i) => (
            <div key={step.num} className="relative rounded-2xl border border-stone-200 bg-white p-4">
              <div
                className="mb-3 text-3xl font-black leading-none"
                style={{ color: ['#f59e0b','#f97316','#ef4444','#8b5cf6'][i] }}
              >
                {step.num}
              </div>
              <div className="text-sm font-semibold text-stone-800">{step.title}</div>
              <p className="mt-1 text-xs leading-relaxed text-stone-500">{step.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ══ 为什么要做这个产品 ════════════════════════════════════════ */}
      <section className="mx-auto max-w-4xl px-4 py-6">
        <div className="rounded-2xl border-2 border-amber-200 bg-amber-50/60 p-6">
          <div className="mb-3 flex items-center gap-2">
            <span className="text-2xl">💡</span>
            <h2 className="text-lg font-bold text-amber-900">为什么要做这个产品</h2>
          </div>
          <div className="space-y-3 text-sm leading-relaxed text-stone-700">
            <p>
              租房是每个打工人绕不开的现实。链家、贝壳、安居客、58同城——每个平台的数据都不完整，
              筛完价格还要自己算通勤，算完通勤还不知道水电多少钱，看完几十个房子脑子已经炸了。
            </p>
            <p>
              更烦的是各平台还有信息壁垒，同一套房在不同平台价格可能不一样，有的平台还藏着"商电"，
              一个月电费能多出好几百块，但在看房时根本看不出来。
            </p>
            <p>
              所以我做了这个工具：<b>跨平台聚合 + 真实成本 + 通勤精算</b>。
              用一句话描述需求，AI 帮你搞定剩下的所有事，让你把精力花在真正值得花精力的地方。
            </p>
          </div>
        </div>
      </section>

      {/* ══ Roadmap ═══════════════════════════════════════════════════ */}
      <section className="mx-auto max-w-4xl px-4 py-6">
        <div className="mb-5 text-center">
          <h2 className="text-xl font-bold text-stone-900 flex items-center justify-center gap-2">
            <GitBranch className="h-5 w-5 text-stone-400" />
            功能路线图
          </h2>
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          {ROADMAP.map((phase) => (
            <div key={phase.status} className={cn('rounded-2xl border p-4', phase.border, phase.bg)}>
              <div className={cn('mb-3 flex items-center gap-2 text-sm font-bold', phase.color)}>
                <span className={cn('h-2 w-2 rounded-full', phase.dot)} />
                {phase.label}
              </div>
              <ul className="space-y-1.5">
                {phase.items.map((item) => (
                  <li key={item} className="flex items-start gap-1.5 text-xs text-stone-700">
                    <span className="mt-0.5 shrink-0">·</span>
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      {/* ══ 更新日志 ══════════════════════════════════════════════════ */}
      <section className="mx-auto max-w-4xl px-4 py-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-xl font-bold text-stone-900 flex items-center gap-2">
            <Rocket className="h-5 w-5 text-stone-400" />
            更新日志
          </h2>
          <button
            onClick={() => setChangelogOpen(!changelogOpen)}
            className="flex items-center gap-1 text-xs text-stone-400 hover:text-stone-600 transition"
          >
            {changelogOpen ? <><ChevronUp className="h-4 w-4" />收起</> : <><ChevronDown className="h-4 w-4" />展开全部</>}
          </button>
        </div>

        <div className="space-y-3">
          {(changelogOpen ? CHANGELOG : CHANGELOG.slice(0, CHANGELOG_PAGE_SIZE)).map((entry) => (
            <div key={entry.version} className="rounded-2xl border border-stone-200 bg-white p-4">
              <div className="mb-2 flex items-center gap-3">
                <span className="rounded-full bg-stone-900 px-2.5 py-0.5 text-xs font-bold text-white">
                  {entry.version}
                </span>
                <span className="text-xs text-stone-400">{entry.date}</span>
                <span className="text-xs font-medium text-stone-700">{entry.title}</span>
              </div>
              <ul className="space-y-1">
                {entry.items.map((item, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-xs text-stone-600">
                    <span className="mt-0.5 shrink-0 text-stone-400">·</span>
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        {!changelogOpen && CHANGELOG.length > CHANGELOG_PAGE_SIZE && (
          <button
            onClick={() => setChangelogOpen(true)}
            className="mt-3 w-full rounded-xl border border-stone-200 bg-white py-2 text-xs text-stone-500 hover:bg-stone-50 transition"
          >
            查看更多版本（{CHANGELOG.length - CHANGELOG_PAGE_SIZE} 个历史版本）
          </button>
        )}
      </section>

      {/* ══ 意见反馈 ══════════════════════════════════════════════════ */}
      <section className="mx-auto max-w-3xl px-4 pt-4 pb-10 border-t border-stone-200 mt-4">
        <div className="rounded-2xl border border-stone-200 bg-white p-5">
          <div className="mb-1 text-sm font-semibold text-stone-800">遇到问题或有新想法？</div>
          <p className="mb-3 text-xs text-stone-400">
            这是个人开发项目，你的反馈会直接影响功能优先级。欢迎吐槽、提建议、报 bug。
          </p>
          <textarea
            value={feedbackText}
            onChange={(e) => setFeedbackText(e.target.value)}
            placeholder="描述你遇到的问题、想要的功能，或者任何建议……"
            rows={3}
            className="w-full resize-none rounded-xl border border-stone-200 bg-stone-50 px-4 py-3 text-sm text-stone-800 outline-none transition focus:border-amber-400 focus:ring-1 focus:ring-amber-200 placeholder-stone-400"
          />
          <div className="mt-2 flex justify-end">
            <button
              onClick={handleFeedbackSubmit}
              disabled={!feedbackText.trim() || feedbackSent}
              className={cn(
                'flex items-center gap-1.5 rounded-xl px-4 py-2 text-sm font-medium transition',
                feedbackSent
                  ? 'bg-emerald-100 text-emerald-700'
                  : 'bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50',
              )}
            >
              <MessageSquare className="h-4 w-4" />
              {feedbackSent ? '已收到，感谢！' : '提交反馈'}
            </button>
          </div>
        </div>
      </section>

      {/* ══ Footer ════════════════════════════════════════════════════ */}
      <footer className="border-t border-stone-200 bg-white py-6">
        <div className="mx-auto max-w-3xl px-4 text-center">
          <div className="flex items-center justify-center gap-2 text-stone-700 font-semibold">
            <span className="text-xl">🐂</span>
            <span>牛马归栏 NiuMaHome</span>
            <span className="rounded bg-stone-100 px-1.5 py-0.5 text-xs text-stone-500">v0.9.2</span>
          </div>
          <p className="mt-1 text-xs text-stone-400">
            个人开发项目 · 链家 / 贝壳 / 安居客 / 58同城 · 高德 / 腾讯 / 百度通勤 · AI：DeepSeek
          </p>
        </div>
      </footer>
    </div>
  );
}
