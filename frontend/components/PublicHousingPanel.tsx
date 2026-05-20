'use client';

/**
 * 公共住房政策查询面板 (v0.9.2)
 * - 本地数据库缓存（housing_policy.db）
 * - 显示政策来源日期（fetched_at）
 * - is_stale=true 时提示用户刷新（>4个月）
 * - 城市可手动输入，也可从搜索地点自动推断
 */

import { useState } from 'react';
import {
  Building2, Search, Loader2, ExternalLink, ChevronDown, ChevronUp,
  Info, Smartphone, AlertCircle, RefreshCw, Calendar, ShieldCheck,
} from 'lucide-react';
import { cn } from '@/lib/utils';

const API_BASE = '/api/backend';

interface HousingTypeInfo {
  name: string;
  apply_url?: string;
  app?: string;
  conditions: string[];
  rent_discount?: string;
  notes?: string;
}

interface PolicyInfoResponse {
  city: string;
  source: 'db' | 'ai' | 'ai_cache' | 'not_found' | 'ai_unavailable';
  public_rental?: HousingTypeInfo | null;
  talent_apartment?: HousingTypeInfo | null;
  youth_apartment?: HousingTypeInfo | null;
  ai_summary?: string;
  fetched_at?: string;    // ISO8601 UTC
  updated_at?: string;
  is_stale?: boolean;
  disclaimer: string;
}

const QUICK_CITIES = ['广州', '北京', '上海', '深圳', '成都', '杭州'];

const TYPE_CONFIG: Record<string, { label: string; color: string; bg: string; border: string }> = {
  public_rental:    { label: '公共租赁住房', color: 'text-sky-700',    bg: 'bg-sky-50',    border: 'border-sky-200' },
  talent_apartment: { label: '人才公寓',     color: 'text-violet-700', bg: 'bg-violet-50', border: 'border-violet-200' },
  youth_apartment:  { label: '青年公寓',     color: 'text-emerald-700',bg: 'bg-emerald-50',border: 'border-emerald-200' },
};

/** 格式化 UTC ISO 时间为本地日期字符串 */
function fmtDate(iso?: string): string {
  if (!iso) return '';
  try {
    const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
    return d.toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' });
  } catch { return iso; }
}

function HousingCard({ type, info }: { type: keyof typeof TYPE_CONFIG; info: HousingTypeInfo }) {
  const [expanded, setExpanded] = useState(false);
  const cfg = TYPE_CONFIG[type];
  return (
    <div className={cn('rounded-xl border p-3', cfg.border, cfg.bg)}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Building2 className={cn('h-4 w-4', cfg.color)} />
          <span className={cn('text-xs font-bold', cfg.color)}>{info.name}</span>
        </div>
        <button
          onClick={() => setExpanded(!expanded)}
          className={cn('flex items-center gap-0.5 text-xs', cfg.color)}
        >
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          {expanded ? '收起' : '查看条件'}
        </button>
      </div>
      {info.rent_discount && (
        <div className="mt-1.5 inline-block rounded-full bg-white/80 border border-current/20 px-2 py-0.5 text-[11px] font-medium">
          <span className={cfg.color}>优惠：{info.rent_discount}</span>
        </div>
      )}
      {expanded && (
        <div className="mt-2.5 space-y-2">
          <div>
            <div className="mb-1 text-[11px] font-semibold text-stone-500 uppercase tracking-wide">申请条件</div>
            <ul className="space-y-1">
              {info.conditions.map((c, i) => (
                <li key={i} className="flex gap-1.5 text-xs text-stone-700">
                  <span className={cn('mt-0.5 h-2 w-2 shrink-0 rounded-full', cfg.bg, `border ${cfg.border}`)} />
                  {c}
                </li>
              ))}
            </ul>
          </div>
          {info.notes && (
            <div className="flex gap-1.5 rounded-lg bg-white/70 px-2.5 py-2 text-xs text-stone-600">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-stone-400" />
              {info.notes}
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            {info.app && (
              <div className="flex items-center gap-1 rounded-full border border-stone-200 bg-white px-2.5 py-1 text-xs text-stone-600">
                <Smartphone className="h-3 w-3" />
                {info.app}
              </div>
            )}
            {info.apply_url && (
              <a
                href={info.apply_url}
                target="_blank"
                rel="noopener noreferrer"
                className={cn(
                  'flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition hover:bg-white',
                  cfg.border, cfg.color,
                )}
              >
                <ExternalLink className="h-3 w-3" />
                官方申请入口
              </a>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

interface PublicHousingPanelProps {
  defaultCity?: string;
}

export default function PublicHousingPanel({ defaultCity }: PublicHousingPanelProps) {
  const [cityInput, setCityInput] = useState(defaultCity || '');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PolicyInfoResponse | null>(null);
  const [error, setError] = useState('');

  async function queryPolicy(city: string, forceAI = false) {
    const c = city.trim();
    if (!c) return;
    setCityInput(c);
    setLoading(true);
    setError('');
    setResult(null);

    try {
      if (!forceAI) {
        const res = await fetch(`${API_BASE}/housing/policy_info?city=${encodeURIComponent(c)}`);
        if (!res.ok) throw new Error(`服务器错误 ${res.status}`);
        const data: PolicyInfoResponse = await res.json();

        if (data.source !== 'not_found') {
          setResult(data);
          setLoading(false);
          return;
        }
      }
      // not_found 或 forceAI：走AI
      const aiRes = await fetch(`${API_BASE}/housing/policy_ai`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ city: c }),
      });
      const aiData: PolicyInfoResponse = await aiRes.json();
      setResult(aiData);
    } catch (e: any) {
      setError(e?.message || '查询失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }

  const sourceLabel = (() => {
    if (!result) return null;
    switch (result.source) {
      case 'db':       return { text: '内置数据库', cls: 'bg-emerald-100 text-emerald-700' };
      case 'ai':       return { text: 'AI 最新生成', cls: 'bg-amber-100 text-amber-700' };
      case 'ai_cache': return { text: 'AI 缓存', cls: 'bg-sky-100 text-sky-700' };
      default:         return null;
    }
  })();

  return (
    <div className="rounded-2xl border border-stone-200 bg-white shadow-sm">
      {/* 标题栏 */}
      <div className="flex items-center gap-2 rounded-t-2xl bg-gradient-to-r from-violet-500 to-indigo-500 px-4 py-3 text-white">
        <Building2 className="h-5 w-5 shrink-0" />
        <div>
          <div className="text-sm font-bold">保障房 · 人才公寓 · 青年公寓</div>
          <div className="text-xs text-violet-100">查询申请条件 · 租金折扣 · 官方入口</div>
        </div>
      </div>

      <div className="p-4 space-y-4">
        {/* 搜索框 */}
        <div className="flex gap-2">
          <input
            type="text"
            value={cityInput}
            onChange={(e) => setCityInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') queryPolicy(cityInput); }}
            placeholder="输入城市名，如：广州、武汉、西安…"
            className="flex-1 rounded-xl border border-stone-200 bg-stone-50 px-3 py-2 text-sm outline-none focus:border-violet-400 focus:ring-1 focus:ring-violet-200"
          />
          <button
            onClick={() => queryPolicy(cityInput)}
            disabled={loading || !cityInput.trim()}
            className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500 text-white transition hover:bg-violet-600 disabled:opacity-40"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          </button>
        </div>

        {/* 快捷城市 */}
        <div className="flex flex-wrap gap-1.5">
          {QUICK_CITIES.map((city) => (
            <button
              key={city}
              onClick={() => queryPolicy(city)}
              disabled={loading}
              className={cn(
                'rounded-full border px-3 py-1 text-xs transition',
                result?.city === city
                  ? 'border-violet-400 bg-violet-50 text-violet-700 font-medium'
                  : 'border-stone-200 bg-white text-stone-500 hover:border-violet-300 hover:text-violet-600',
              )}
            >
              {city}
            </button>
          ))}
        </div>

        {error && (
          <div className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            <AlertCircle className="h-4 w-4 shrink-0" />
            {error}
          </div>
        )}

        {result && (
          <div className="space-y-3">
            {/* 城市标题 + 来源徽章 + 日期 */}
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-bold text-stone-800">{result.city} 住房保障政策</span>
              {sourceLabel && (
                <span className={cn('rounded-full px-2 py-0.5 text-[11px] font-medium', sourceLabel.cls)}>
                  {sourceLabel.text}
                </span>
              )}
            </div>

            {/* 数据日期 + 过期提示 */}
            {result.fetched_at && (
              <div className={cn(
                'flex items-start gap-2 rounded-xl border px-3 py-2 text-xs',
                result.is_stale
                  ? 'border-orange-200 bg-orange-50 text-orange-700'
                  : 'border-stone-200 bg-stone-50 text-stone-500',
              )}>
                {result.is_stale ? (
                  <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                ) : (
                  <ShieldCheck className="h-3.5 w-3.5 mt-0.5 shrink-0 text-emerald-500" />
                )}
                <div className="flex-1">
                  <div className="flex items-center gap-1">
                    <Calendar className="h-3 w-3" />
                    <span>数据来源日期：{fmtDate(result.fetched_at)}</span>
                    {result.source === 'db' && <span className="text-stone-400">（内置）</span>}
                  </div>
                  {result.is_stale && (
                    <div className="mt-1 flex items-center gap-2">
                      <span>该城市 AI 摘要已超过 4 个月，建议刷新获取最新政策。</span>
                      <button
                        onClick={() => queryPolicy(result.city, true)}
                        className="flex items-center gap-1 rounded-full bg-orange-600 text-white px-2 py-0.5 text-[11px] font-medium hover:bg-orange-700 transition"
                      >
                        <RefreshCw className="h-2.5 w-2.5" />
                        立即刷新
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* AI 摘要 */}
            {result.ai_summary && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-3 text-xs text-stone-700 leading-relaxed whitespace-pre-wrap">
                {result.ai_summary}
              </div>
            )}

            {/* 三类住房卡片 */}
            {result.public_rental && <HousingCard type="public_rental" info={result.public_rental} />}
            {result.talent_apartment && <HousingCard type="talent_apartment" info={result.talent_apartment} />}
            {result.youth_apartment && <HousingCard type="youth_apartment" info={result.youth_apartment} />}

            {/* 免责声明 */}
            <div className="flex items-start gap-1.5 rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-[11px] text-stone-500">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {result.disclaimer}
            </div>
          </div>
        )}

        {!result && !loading && !error && (
          <div className="py-4 text-center text-xs text-stone-400">
            输入城市名称，查询公租房 / 人才公寓 / 青年公寓申请政策
          </div>
        )}
      </div>
    </div>
  );
}
