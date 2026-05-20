'use client';

/**
 * 新手引导 v0.5（全屏居中模态框）
 *
 * 分3步展示，每步一张卡片居中弹出，底部有步骤指示器：
 *   Step 0（未搜索）：AI 对话 / 搜索怎么用
 *   Step 1（搜索后）：排序 / 离线估算说明
 *   Step 2（Step1关闭后）：批量精算 / AI点评 / 水电精算
 *
 * - localStorage key: niumahome_guided_v5
 * - 全部完成后右下角"?"常驻，可重新召唤
 */

import { useEffect, useState } from 'react';
import { X, MessageSquare, Zap, BarChart2, ChevronRight, ArrowRight } from 'lucide-react';
import { cn } from '@/lib/utils';

const STORAGE_KEY = 'niumahome_guided_v5';
// 清理所有旧版 key
const OLD_KEYS = ['niumahome_guided', 'niumahome_guided_v2', 'niumahome_guided_v3', 'niumahome_guided_v4'];

interface OnboardingGuideProps {
  hasResults: boolean;
}

interface TipConfig {
  id: string;
  phase: 0 | 1;          // 0=未搜索显示, 1=搜索后才显示
  waitFor?: string;       // 需要等某个 tip 关闭后才显示
  icon: React.ReactNode;
  badge: string;
  title: string;
  desc: string;
  tip: string;
  color: { bg: string; border: string; badge: string; title: string; btn: string };
}

const TIPS: TipConfig[] = [
  {
    id: 'chat',
    phase: 0,
    icon: <MessageSquare className="h-5 w-5" />,
    badge: '第 1 步 / 共 3 步',
    title: '用自然语言描述需求',
    desc: '不需要填表单，直接说话就行。比如：\n「广州天河区，通勤珠江新城，预算 3000 以内，整租单间」\n\nAI 会自动解析城市、通勤地点、预算、户型等条件，确认后一键搜索。',
    tip: '说完点「开始搜索」，或者说「不加其他条件，直接搜」也能立即触发。',
    color: {
      bg: 'bg-amber-50',
      border: 'border-amber-300',
      badge: 'bg-amber-100 text-amber-700',
      title: 'text-amber-900',
      btn: 'bg-amber-500 hover:bg-amber-600',
    },
  },
  {
    id: 'sort',
    phase: 1,
    icon: <BarChart2 className="h-5 w-5" />,
    badge: '第 2 步 / 共 3 步',
    title: '结果出来了，来看看怎么排序',
    desc: '所有房源都已完成「📍 离线估算」通勤（基于直线距离推算，误差约 ±25%，仅供参考）。\n\n顶部可按「综合 / 价格 / 通勤 / 面积」切换排序，左侧可按链家 / 贝壳过滤平台。',
    tip: '每张卡片右上角有「⚡ 查询实时」按钮，可升级为高德精确路线数据。',
    color: {
      bg: 'bg-emerald-50',
      border: 'border-emerald-300',
      badge: 'bg-emerald-100 text-emerald-700',
      title: 'text-emerald-900',
      btn: 'bg-emerald-500 hover:bg-emerald-600',
    },
  },
  {
    id: 'precise',
    phase: 1,
    waitFor: 'sort',
    icon: <Zap className="h-5 w-5" />,
    badge: '第 3 步 / 共 3 步',
    title: '批量精算 + AI 点评 + 水电估算',
    desc: '顶部栏「⚡ 批量精算 10 条」：一次性为最近的 10 套房源调用高德 API 算精确通勤，约 10-20 秒。\n\n点击任意卡片打开详情：\n• AI 生成优缺点 + 综合评分\n• 水电燃气问卷精算（按你的生活习惯）\n• 双向通勤（家→公司 / 公司→家）',
    tip: '精算完成后通勤徽章从「📍 离线估算」变为「✓ 实时」。',
    color: {
      bg: 'bg-sky-50',
      border: 'border-sky-300',
      badge: 'bg-sky-100 text-sky-700',
      title: 'text-sky-900',
      btn: 'bg-sky-500 hover:bg-sky-600',
    },
  },
];

export default function OnboardingGuide({ hasResults }: OnboardingGuideProps) {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [ready, setReady] = useState(false);
  const [showHelp, setShowHelp] = useState(false);

  useEffect(() => {
    // 清理旧版引导 key，避免残留干扰
    OLD_KEYS.forEach((k) => localStorage.removeItem(k));

    // URL 带 ?reset_guide=1 时强制重置
    if (typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('reset_guide') === '1') {
      localStorage.removeItem(STORAGE_KEY);
      // 清掉参数，避免刷新再次触发
      const url = new URL(window.location.href);
      url.searchParams.delete('reset_guide');
      window.history.replaceState({}, '', url.toString());
    }

    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw === 'all') {
        setDismissed(new Set(TIPS.map((t) => t.id)));
      } else if (raw) {
        setDismissed(new Set(JSON.parse(raw) as string[]));
      }
      // 没有任何记录（首次访问）→ dismissed 保持空集合，引导会正常显示
    } catch { /* ignore */ }
    const t = setTimeout(() => setReady(true), 200);
    return () => clearTimeout(t);
  }, []);

  // 搜索完成 → 自动关闭 phase-0 的 tips
  useEffect(() => {
    if (!hasResults) return;
    setDismissed((prev) => {
      if (prev.has('chat')) return prev;
      const next = new Set(prev);
      next.add('chat');
      persist(next);
      return next;
    });
  }, [hasResults]);

  function persist(ids: Set<string>) {
    localStorage.setItem(
      STORAGE_KEY,
      ids.size >= TIPS.length ? 'all' : JSON.stringify(Array.from(ids)),
    );
  }

  function dismiss(id: string) {
    setDismissed((prev) => {
      const next = new Set(prev);
      next.add(id);
      persist(next);
      return next;
    });
  }

  function dismissAll() {
    const all = new Set(TIPS.map((t) => t.id));
    persist(all);
    setDismissed(all);
  }

  function resetAll() {
    localStorage.removeItem(STORAGE_KEY);
    setDismissed(new Set());
    setShowHelp(false);
  }

  if (!ready) return null;

  const allDone = TIPS.every((t) => dismissed.has(t.id));

  // 当前应展示的 tip（每次只展示一个）
  const activeTip = TIPS.find((tip) => {
    if (dismissed.has(tip.id)) return false;
    if (tip.phase === 0) return !hasResults;
    if (tip.phase === 1) {
      if (!hasResults) return false;
      if (tip.waitFor && !dismissed.has(tip.waitFor)) return false;
      return true;
    }
    return false;
  });

  // 计算当前是第几步
  const currentStepIndex = activeTip ? TIPS.findIndex((t) => t.id === activeTip.id) : -1;

  return (
    <>
      {/* ── 全屏遮罩 + 居中模态框 ── */}
      {activeTip && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
          {/* 遮罩（点击关闭当前 tip） */}
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-[2px]"
            onClick={() => dismiss(activeTip.id)}
          />

          {/* 卡片 */}
          <div
            className={cn(
              'relative z-10 w-full max-w-md rounded-2xl border-2 p-6 shadow-2xl',
              activeTip.color.bg,
              activeTip.color.border,
            )}
          >
            {/* 步骤徽章 */}
            <span
              className={cn(
                'mb-3 inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold',
                activeTip.color.badge,
              )}
            >
              {activeTip.badge}
            </span>

            {/* 关闭（全部跳过） */}
            <button
              onClick={dismissAll}
              title="跳过所有引导"
              className="absolute right-3 top-3 rounded-full p-1.5 text-stone-400 hover:bg-black/10"
            >
              <X className="h-4 w-4" />
            </button>

            {/* 图标 + 标题 */}
            <div className={cn('mb-3 flex items-center gap-2 text-lg font-bold', activeTip.color.title)}>
              {activeTip.icon}
              {activeTip.title}
            </div>

            {/* 正文 */}
            <p className="mb-3 whitespace-pre-line text-sm leading-relaxed text-stone-700">
              {activeTip.desc}
            </p>

            {/* 提示框 */}
            <div className="mb-5 rounded-lg bg-white/70 px-3 py-2 text-xs text-stone-600">
              💡 {activeTip.tip}
            </div>

            {/* 步骤点 */}
            <div className="mb-5 flex justify-center gap-2">
              {TIPS.map((t, i) => (
                <div
                  key={t.id}
                  className={cn(
                    'h-2 rounded-full transition-all',
                    i === currentStepIndex
                      ? 'w-6 bg-stone-700'
                      : dismissed.has(t.id)
                      ? 'w-2 bg-stone-300'
                      : 'w-2 bg-stone-200',
                  )}
                />
              ))}
            </div>

            {/* 操作按钮 */}
            <div className="flex items-center gap-2">
              <button
                onClick={() => dismiss(activeTip.id)}
                className={cn(
                  'flex flex-1 items-center justify-center gap-1.5 rounded-xl py-2.5 text-sm font-semibold text-white transition',
                  activeTip.color.btn,
                )}
              >
                {currentStepIndex < TIPS.length - 1 ? (
                  <>知道了，看下一步 <ChevronRight className="h-4 w-4" /></>
                ) : (
                  <>开始使用 <ArrowRight className="h-4 w-4" /></>
                )}
              </button>
              <button
                onClick={dismissAll}
                className="rounded-xl border border-stone-300 bg-white/60 px-4 py-2.5 text-sm text-stone-500 hover:bg-white"
              >
                跳过
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── 右下角"?"常驻 ── */}
      {allDone && !showHelp && (
        <button
          onClick={() => setShowHelp(true)}
          title="使用指南 / 重新显示引导"
          className="fixed bottom-6 left-6 z-50 flex h-10 w-10 items-center justify-center rounded-full bg-stone-700 text-white shadow-lg transition hover:bg-amber-500"
        >
          <span className="text-sm font-bold">?</span>
        </button>
      )}

      {/* ── 迷你使用指南面板 ── */}
      {showHelp && (
        <div className="fixed bottom-20 left-6 z-[60] w-72 rounded-xl border-2 border-stone-200 bg-white p-4 shadow-xl">
          <button
            onClick={() => setShowHelp(false)}
            className="absolute right-2 top-2 rounded-full p-0.5 text-stone-400 hover:bg-stone-200"
          >
            <X className="h-4 w-4" />
          </button>
          <div className="mb-3 text-sm font-semibold text-stone-800">使用指南</div>
          <div className="space-y-3 text-xs text-stone-600">
            {TIPS.map((t) => (
              <div key={t.id} className="flex items-start gap-2">
                <span className={cn('mt-0.5 shrink-0', t.color.title)}>{t.icon}</span>
                <div>
                  <div className="font-semibold text-stone-700">{t.title}</div>
                  <div className="leading-relaxed text-stone-400">{t.tip}</div>
                </div>
              </div>
            ))}
          </div>
          <button
            onClick={resetAll}
            className="mt-4 w-full rounded-lg bg-amber-500 py-1.5 text-xs font-semibold text-white hover:bg-amber-600"
          >
            重新显示引导
          </button>
        </div>
      )}
    </>
  );
}
