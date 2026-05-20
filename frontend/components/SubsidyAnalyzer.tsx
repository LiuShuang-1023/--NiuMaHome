'use client';

/**
 * SubsidyAnalyzer - 房补政策分析组件 (v0.6)
 *
 * 用法：
 * 1. 用户粘贴公司房补政策文本
 * 2. AI 自动识别通勤限制（骑行X分钟 / 公交Y分钟 / 步行Z分钟等）
 * 3. 一键应用 → 自动筛选符合条件的房源
 */

import { useState } from 'react';
import { postSubsidyAnalyze, type SubsidyAnalyzeResponse } from '@/lib/api';
import { Bike, Train, Footprints, CheckCircle2, ChevronDown, ChevronUp, Loader2, Sparkles, AlertCircle, X } from 'lucide-react';
import { cn } from '@/lib/utils';

// 通勤方式标签配置
const MODE_CONFIG: Record<string, { label: string; Icon: any; color: string; bg: string }> = {
  transit: { label: '公共交通', Icon: Train,     color: 'text-blue-700',  bg: 'bg-blue-50 border-blue-200' },
  riding:  { label: '骑行',     Icon: Bike,      color: 'text-green-700', bg: 'bg-green-50 border-green-200' },
  walking: { label: '步行',     Icon: Footprints, color: 'text-purple-700', bg: 'bg-purple-50 border-purple-200' },
  any:     { label: '任意方式', Icon: CheckCircle2, color: 'text-stone-700', bg: 'bg-stone-50 border-stone-200' },
};

function getModeConfig(mode: string) {
  return MODE_CONFIG[mode] || { label: mode, Icon: CheckCircle2, color: 'text-stone-700', bg: 'bg-stone-50 border-stone-200' };
}

interface SubsidyAnalyzerProps {
  /** 当前已有的最大通勤时间（来自用户需求），用于对比展示 */
  currentMaxMinutes?: number | null;
  /** 应用房补筛选条件的回调 */
  onApply: (params: {
    maxMinutes: number;
    modes: string[];
    subsidyResult: SubsidyAnalyzeResponse;
  }) => void;
  /** 清除已应用的房补筛选 */
  onClear?: () => void;
  /** 当前是否已有应用中的房补条件 */
  isActive?: boolean;
}

export default function SubsidyAnalyzer({
  currentMaxMinutes,
  onApply,
  onClear,
  isActive = false,
}: SubsidyAnalyzerProps) {
  const [expanded, setExpanded] = useState(false);
  const [policyText, setPolicyText] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<SubsidyAnalyzeResponse | null>(null);
  const [applied, setApplied] = useState(false);

  async function handleAnalyze() {
    if (!policyText.trim()) return;
    setLoading(true);
    setError('');
    setResult(null);
    setApplied(false);

    try {
      const res = await postSubsidyAnalyze(policyText.trim());
      setResult(res);
    } catch (e: any) {
      setError(e?.message || '分析失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  }

  function handleApply() {
    if (!result) return;
    onApply({
      maxMinutes: result.recommended_max_minutes,
      modes: result.recommended_modes,
      subsidyResult: result,
    });
    setApplied(true);
  }

  function handleClear() {
    setResult(null);
    setPolicyText('');
    setApplied(false);
    setError('');
    onClear?.();
  }

  return (
    <div className={cn(
      'rounded-xl border-2 bg-white transition-all',
      isActive ? 'border-amber-400 bg-amber-50/50' : 'border-stone-200',
    )}>
      {/* Header */}
      <button
        className="flex w-full items-center justify-between px-4 py-3 text-left"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex items-center gap-2">
          <span className="text-lg">🏢</span>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-semibold text-stone-900 text-sm">房补政策智能筛房</span>
              {isActive && (
                <span className="rounded-full bg-amber-500 px-2 py-0.5 text-[10px] font-bold text-white">
                  筛选中
                </span>
              )}
            </div>
            <p className="text-xs text-stone-500 mt-0.5">
              粘贴公司房补政策 → AI 一键识别通勤限制 → 自动筛选符合房源
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 text-stone-400">
          {isActive && onClear && (
            <button
              onClick={(e) => { e.stopPropagation(); handleClear(); }}
              className="rounded-full p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-600"
              title="清除房补筛选"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
          {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </div>
      </button>

      {/* Body */}
      {expanded && (
        <div className="border-t border-stone-100 px-4 pb-4 pt-3">
          {/* 说明：以搜索时填的目的地为通勤起点 */}
          <p className="mb-3 flex items-center gap-1.5 rounded-lg bg-stone-50 border border-stone-200 px-3 py-2 text-xs text-stone-500">
            <span>📍</span>
            <span>通勤距离以<b className="text-stone-700">上一步对话中的目的地</b>（公司/学校地址）为起点测算</span>
          </p>

          {/* 分析结果展示区 */}
          {result && (
            <ResultCard
              result={result}
              currentMaxMinutes={currentMaxMinutes}
              applied={applied}
              onApply={handleApply}
              onReset={() => { setResult(null); setApplied(false); }}
            />
          )}

          {/* 输入区（结果出来后折叠，用户也可重新粘贴） */}
          {(!result || !applied) && (
            <div className="space-y-2">
              {result && (
                <p className="text-xs text-stone-500 mb-1">
                  如需重新分析，修改下方文本后再次点击「AI解析」
                </p>
              )}
              <textarea
                value={policyText}
                onChange={(e) => setPolicyText(e.target.value)}
                placeholder={`粘贴你们公司的房补政策文本，例如：\n\n"员工住房补贴要求：居住地点距公司骑行20分钟以内（仅限自行车），或公共交通30分钟以内。每月补贴500元，需每季度提交通勤截图。"`}
                className="w-full rounded-lg border border-stone-200 bg-stone-50 p-3 text-sm text-stone-800 placeholder-stone-400 focus:border-amber-400 focus:outline-none focus:ring-1 focus:ring-amber-400 resize-none"
                rows={5}
              />

              {error && (
                <div className="flex items-start gap-2 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">
                  <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              <button
                onClick={handleAnalyze}
                disabled={loading || !policyText.trim()}
                className={cn(
                  'flex w-full items-center justify-center gap-2 rounded-lg py-2.5 text-sm font-semibold transition',
                  loading || !policyText.trim()
                    ? 'cursor-not-allowed bg-stone-100 text-stone-400'
                    : 'bg-amber-500 text-white hover:bg-amber-600 active:bg-amber-700',
                )}
              >
                {loading ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    AI 正在识别政策条件...
                  </>
                ) : (
                  <>
                    <Sparkles className="h-4 w-4" />
                    AI 解析房补政策
                  </>
                )}
              </button>
            </div>
          )}

          {/* 已应用后的简化操作 */}
          {result && applied && (
            <div className="mt-3 flex gap-2">
              <button
                onClick={() => { setApplied(false); }}
                className="flex-1 rounded-lg border border-stone-200 py-2 text-xs text-stone-600 hover:bg-stone-50"
              >
                重新修改
              </button>
              <button
                onClick={handleClear}
                className="flex-1 rounded-lg border border-rose-200 py-2 text-xs text-rose-600 hover:bg-rose-50"
              >
                清除房补筛选
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── 分析结果展示卡片 ─────────────────────────────────────────────

function ResultCard({
  result,
  currentMaxMinutes,
  applied,
  onApply,
  onReset,
}: {
  result: SubsidyAnalyzeResponse;
  currentMaxMinutes?: number | null;
  applied: boolean;
  onApply: () => void;
  onReset: () => void;
}) {
  return (
    <div className="mb-4 rounded-xl border-2 border-amber-200 bg-amber-50 p-4 space-y-3">
      {/* 摘要 */}
      <div className="flex items-start gap-2">
        <span className="text-xl flex-shrink-0">✅</span>
        <div>
          <p className="font-semibold text-amber-900 text-sm">识别结果</p>
          <p className="text-sm text-amber-800 mt-0.5">{result.summary}</p>
        </div>
      </div>

      {/* 条件列表 */}
      {result.conditions.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-stone-600 uppercase tracking-wide">
            通勤限制条件
            {result.conditions.length > 1 && (
              <span className="ml-1 rounded bg-stone-200 px-1.5 py-0.5 text-[10px] normal-case font-normal">
                满足{result.logic === 'any' ? '任一' : '全部'}即可
              </span>
            )}
          </p>
          <div className="flex flex-wrap gap-2">
            {result.conditions.map((c, i) => {
              const cfg = getModeConfig(c.mode);
              const Icon = cfg.Icon;
              return (
                <div
                  key={i}
                  className={cn('flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm', cfg.bg)}
                >
                  <Icon className={cn('h-4 w-4', cfg.color)} />
                  <span className={cn('font-medium', cfg.color)}>{cfg.label}</span>
                  <span className="font-bold text-stone-900">{c.max_minutes}分钟以内</span>
                </div>
              );
            })}
          </div>
          {result.conditions.some((c) => c.description) && (
            <div className="space-y-0.5">
              {result.conditions.map((c, i) => (
                c.description ? (
                  <p key={i} className="text-xs text-stone-500">· {c.description}</p>
                ) : null
              ))}
            </div>
          )}
        </div>
      )}

      {/* 距离限制 */}
      {result.has_distance_limit && result.distance_km && (
        <div className="rounded-lg bg-orange-50 border border-orange-200 px-3 py-2 text-sm text-orange-800">
          📍 另有距离限制：{result.distance_km} 公里以内
        </div>
      )}

      {/* 备注 */}
      {result.notes && (
        <p className="text-xs text-stone-500 italic">⚠️ {result.notes}</p>
      )}

      {/* 与当前设置对比 */}
      {currentMaxMinutes != null && result.recommended_max_minutes > 0 && (
        <div className={cn(
          'rounded-lg px-3 py-2 text-xs',
          result.recommended_max_minutes < currentMaxMinutes
            ? 'bg-blue-50 text-blue-800'
            : result.recommended_max_minutes > currentMaxMinutes
              ? 'bg-amber-100 text-amber-800'
              : 'bg-green-50 text-green-800',
        )}>
          {result.recommended_max_minutes < currentMaxMinutes
            ? `📉 房补条件比你设的限制更严格（${currentMaxMinutes}min → ${result.recommended_max_minutes}min），应用后房源会减少`
            : result.recommended_max_minutes > currentMaxMinutes
              ? `📈 房补条件比你设的限制更宽松（${currentMaxMinutes}min → ${result.recommended_max_minutes}min）`
              : `✓ 与你当前设置一致（${currentMaxMinutes}min）`}
        </div>
      )}

      {/* 操作按钮 */}
      {!applied ? (
        <button
          onClick={onApply}
          className="w-full rounded-lg bg-amber-500 py-2.5 text-sm font-semibold text-white hover:bg-amber-600 transition flex items-center justify-center gap-2"
        >
          <Sparkles className="h-4 w-4" />
          应用房补条件，重新筛选房源
        </button>
      ) : (
        <div className="flex items-center justify-center gap-2 rounded-lg bg-emerald-50 border border-emerald-200 py-2.5 text-sm text-emerald-700 font-medium">
          <CheckCircle2 className="h-4 w-4" />
          已应用 · 正在按房补条件筛选房源
        </div>
      )}
    </div>
  );
}
