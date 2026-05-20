'use client';

/**
 * 收藏夹面板 (v0.5)
 *
 * 功能：
 * 1. 收藏列表：展示已收藏房源（价格/通勤/成本对比）
 * 2. 对比视图：横向对比多套房源核心指标
 * 3. 批量站内信：为所有/选中收藏房源一键生成询问站内信
 */

import { useState } from 'react';
import {
  Heart, X, BarChart2, Send, Loader2, Copy,
  CheckCircle2, ExternalLink, Trash2, ChevronRight,
} from 'lucide-react';
import type { FavoriteItem } from '@/lib/useFavorites';
import { postAgentBatchInquiry, type InquiryResponse } from '@/lib/api';
import { cn } from '@/lib/utils';

interface FavoritesPanelProps {
  favorites: FavoriteItem[];
  onRemove: (listingId: string) => void;
  onClear: () => void;
  onSelectListing?: (fav: FavoriteItem) => void; // 点击卡片打开详情
}

export default function FavoritesPanel({
  favorites,
  onRemove,
  onClear,
  onSelectListing,
}: FavoritesPanelProps) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<'list' | 'compare' | 'inquiry'>('list');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [inquiryResults, setInquiryResults] = useState<InquiryResponse[]>([]);
  const [generating, setGenerating] = useState(false);
  const [copiedId, setCopiedId] = useState<string>('');

  // 选中/全选
  const allSelected = favorites.length > 0 && selectedIds.size === favorites.length;
  const toggleSelect = (id: string) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  const toggleAll = () =>
    setSelectedIds(allSelected ? new Set() : new Set(favorites.map((f) => f.rec.listing.id)));

  // 批量生成站内信
  async function handleBatchInquiry() {
    const targets = favorites.filter(
      (f) => selectedIds.size === 0 || selectedIds.has(f.rec.listing.id),
    );
    if (targets.length === 0) return;
    setGenerating(true);
    setInquiryResults([]);
    try {
      const res = await postAgentBatchInquiry({
        listings: targets.map((f) => ({
          listing_id: f.rec.listing.id,
          listing_title: f.rec.listing.title ?? '',
          listing_community: f.rec.listing.community ?? '',
          listing_url: f.rec.listing.url ?? '',
          platform: f.rec.listing.platform ?? '',
        })),
        use_ai: false,
      });
      setInquiryResults(res.results);
      setTab('inquiry');
    } catch (e: any) {
      alert(`生成失败：${e?.message || '请稍后重试'}`);
    } finally {
      setGenerating(false);
    }
  }

  async function copyText(text: string, id: string) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const el = document.createElement('textarea');
      el.value = text;
      document.body.appendChild(el);
      el.select();
      document.execCommand('copy');
      document.body.removeChild(el);
    }
    setCopiedId(id);
    setTimeout(() => setCopiedId(''), 2500);
  }

  return (
    <>
      {/* 悬浮收藏按钮（固定在右下角，Agent 按钮上方）*/}
      <button
        onClick={() => setOpen(true)}
        className={cn(
          'fixed bottom-24 right-6 z-50 flex items-center gap-1.5 rounded-full px-3 py-2.5 text-sm font-semibold shadow-lg transition hover:scale-105',
          favorites.length > 0
            ? 'bg-rose-500 text-white hover:bg-rose-600'
            : 'bg-white border border-stone-300 text-stone-600 hover:bg-stone-50',
        )}
        title="收藏夹"
      >
        <Heart className={cn('h-4 w-4', favorites.length > 0 && 'fill-white')} />
        {favorites.length > 0 ? (
          <span>{favorites.length}</span>
        ) : (
          <span className="text-xs">收藏</span>
        )}
      </button>

      {/* 抽屉面板 */}
      {open && (
        <div
          className="fixed inset-0 z-[70] flex justify-end"
          onClick={(e) => { if (e.target === e.currentTarget) setOpen(false); }}
        >
          {/* 遮罩 */}
          <div className="absolute inset-0 bg-black/20" onClick={() => setOpen(false)} />

          {/* 面板本体 */}
          <div className="relative flex h-full w-full max-w-[460px] flex-col bg-white shadow-2xl">
            {/* 头部 */}
            <div className="flex items-center gap-2 border-b border-stone-200 px-4 py-3">
              <Heart className="h-5 w-5 fill-rose-500 text-rose-500" />
              <div className="flex-1">
                <span className="text-sm font-bold text-stone-800">收藏夹</span>
                <span className="ml-2 text-xs text-stone-500">{favorites.length} 套</span>
              </div>
              {favorites.length > 0 && (
                <button
                  onClick={() => { if (confirm('清空全部收藏？')) { onClear(); setOpen(false); } }}
                  className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-stone-400 hover:text-rose-500"
                >
                  <Trash2 className="h-3.5 w-3.5" /> 清空
                </button>
              )}
              <button onClick={() => setOpen(false)} className="rounded-full p-1 hover:bg-stone-100">
                <X className="h-4 w-4 text-stone-500" />
              </button>
            </div>

            {favorites.length === 0 ? (
              <div className="flex flex-1 flex-col items-center justify-center gap-3 text-stone-400">
                <Heart className="h-12 w-12 text-stone-200" />
                <p className="text-sm">还没有收藏</p>
                <p className="text-xs text-center px-8">点击房源卡片右上角的 ♡ 即可收藏，最多保存 20 套</p>
              </div>
            ) : (
              <>
                {/* Tab */}
                <div className="flex border-b border-stone-100">
                  {[
                    { key: 'list', icon: Heart, label: '列表' },
                    { key: 'compare', icon: BarChart2, label: '对比' },
                    { key: 'inquiry', icon: Send, label: '站内信' },
                  ].map(({ key, icon: Icon, label }) => (
                    <button
                      key={key}
                      onClick={() => setTab(key as any)}
                      className={cn(
                        'flex flex-1 items-center justify-center gap-1 py-2 text-xs font-medium transition',
                        tab === key
                          ? 'border-b-2 border-rose-400 text-rose-600'
                          : 'text-stone-400 hover:text-stone-600',
                      )}
                    >
                      <Icon className="h-3.5 w-3.5" />{label}
                    </button>
                  ))}
                </div>

                {/* ── 列表 Tab ────────────────────────────────── */}
                {tab === 'list' && (
                  <div className="flex flex-1 flex-col overflow-hidden">
                    <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
                      {favorites.map((fav) => {
                        const l = fav.rec.listing;
                        const cost = fav.rec.cost;
                        const commute = fav.rec.commute;
                        const bestMin = commute?.best_duration_min;
                        return (
                          <div
                            key={l.id}
                            className="group flex gap-3 rounded-xl border border-stone-200 bg-white p-3 hover:border-rose-200 hover:shadow-sm transition cursor-pointer"
                            onClick={() => onSelectListing?.(fav)}
                          >
                            {/* 图片 */}
                            {l.images?.[0] ? (
                              <img
                                src={l.images[0]}
                                alt={l.title}
                                className="h-16 w-20 shrink-0 rounded-lg object-cover"
                              />
                            ) : (
                              <div className="h-16 w-20 shrink-0 rounded-lg bg-stone-100 flex items-center justify-center text-stone-300 text-xs">无图</div>
                            )}
                            <div className="flex-1 min-w-0">
                              <div className="flex items-start justify-between gap-1">
                                <div className="truncate text-sm font-semibold text-stone-800">
                                  {l.community || l.title}
                                </div>
                                <button
                                  onClick={(e) => { e.stopPropagation(); onRemove(l.id); }}
                                  className="shrink-0 rounded-full p-0.5 text-stone-300 hover:text-rose-400 opacity-0 group-hover:opacity-100 transition"
                                >
                                  <X className="h-3.5 w-3.5" />
                                </button>
                              </div>
                              <div className="mt-0.5 flex items-center gap-2 text-xs">
                                <span className="font-bold text-amber-600">¥{l.price_base}/月</span>
                                {cost && <span className="text-stone-400">全包约¥{cost.total}</span>}
                              </div>
                              <div className="mt-0.5 flex items-center gap-2 text-xs text-stone-500">
                                {bestMin && <span>🚇 {bestMin}min</span>}
                                {l.layout && <span>{l.layout}</span>}
                                {l.area && <span>{l.area}㎡</span>}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>

                    {/* 底部操作栏 */}
                    <div className="border-t border-stone-100 px-3 py-2.5 flex gap-2">
                      <button
                        onClick={() => setTab('compare')}
                        className="flex flex-1 items-center justify-center gap-1.5 rounded-xl border border-stone-300 py-2 text-xs font-medium text-stone-600 hover:bg-stone-50"
                      >
                        <BarChart2 className="h-3.5 w-3.5" />横向对比
                      </button>
                      <button
                        onClick={() => { setSelectedIds(new Set(favorites.map(f => f.rec.listing.id))); handleBatchInquiry(); }}
                        disabled={generating}
                        className="flex flex-1 items-center justify-center gap-1.5 rounded-xl bg-amber-500 py-2 text-xs font-semibold text-white hover:bg-amber-600 disabled:opacity-50"
                      >
                        {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
                        批量生成站内信
                      </button>
                    </div>
                  </div>
                )}

                {/* ── 对比 Tab ────────────────────────────────── */}
                {tab === 'compare' && (
                  <div className="flex-1 overflow-auto p-3">
                    <CompareTable favorites={favorites} onSelect={onSelectListing} />
                  </div>
                )}

                {/* ── 站内信 Tab ──────────────────────────────── */}
                {tab === 'inquiry' && (
                  <div className="flex flex-1 flex-col overflow-hidden">
                    {inquiryResults.length === 0 ? (
                      <div className="flex flex-1 flex-col gap-3 overflow-y-auto p-3">
                        <p className="text-xs text-stone-500 leading-relaxed">
                          选择要发送站内信的房源，AI 会为每套房源生成一条询问水电/物业/网费等信息的私信文案，你复制后在对应平台粘贴发送即可。
                        </p>
                        {/* 选择列表 */}
                        <div className="space-y-1.5">
                          <div className="flex items-center justify-between text-xs text-stone-500">
                            <span>选择房源（{selectedIds.size}/{favorites.length}）</span>
                            <button onClick={toggleAll} className="text-amber-600 hover:underline">
                              {allSelected ? '取消全选' : '全选'}
                            </button>
                          </div>
                          {favorites.map((fav) => {
                            const l = fav.rec.listing;
                            const checked = selectedIds.has(l.id);
                            return (
                              <label
                                key={l.id}
                                className={cn(
                                  'flex cursor-pointer items-center gap-2.5 rounded-lg border px-3 py-2 transition',
                                  checked ? 'border-amber-400 bg-amber-50' : 'border-stone-200 bg-white hover:bg-stone-50',
                                )}
                              >
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={() => toggleSelect(l.id)}
                                  className="h-3.5 w-3.5 accent-amber-500"
                                />
                                <div className="flex-1 min-w-0">
                                  <div className="truncate text-xs font-semibold text-stone-700">
                                    {l.community || l.title}
                                  </div>
                                  <div className="text-xs text-stone-400">¥{l.price_base}/月 · {l.platform}</div>
                                </div>
                              </label>
                            );
                          })}
                        </div>
                      </div>
                    ) : (
                      <div className="flex-1 overflow-y-auto p-3 space-y-4">
                        {inquiryResults.map((res) => (
                          <div key={res.listing_id} className="rounded-xl border border-stone-200 p-3">
                            <div className="mb-1.5 flex items-center justify-between">
                              <span className="text-xs font-semibold text-stone-700">
                                {favorites.find(f => f.rec.listing.id === res.listing_id)?.rec.listing.community || res.listing_id.slice(0, 12)}
                              </span>
                              <span className="text-xs text-stone-400">{res.platform_label}</span>
                            </div>
                            <pre className="mb-2 whitespace-pre-wrap rounded-lg bg-stone-50 p-2 text-xs text-stone-700 leading-relaxed border border-stone-100">
                              {res.message}
                            </pre>
                            <div className="flex items-center gap-2">
                              <button
                                onClick={() => copyText(res.message, res.listing_id)}
                                className={cn(
                                  'flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium transition',
                                  copiedId === res.listing_id
                                    ? 'bg-emerald-100 text-emerald-700'
                                    : 'bg-amber-500 text-white hover:bg-amber-600',
                                )}
                              >
                                {copiedId === res.listing_id
                                  ? <><CheckCircle2 className="h-3 w-3" />已复制</>
                                  : <><Copy className="h-3 w-3" />复制文案</>}
                              </button>
                              {res.listing_url && (
                                <a
                                  href={res.listing_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="flex items-center gap-1 text-xs text-blue-600 hover:underline"
                                >
                                  <ExternalLink className="h-3 w-3" />
                                  打开房源
                                </a>
                              )}
                            </div>
                            {res.copy_hint && (
                              <p className="mt-1.5 text-xs text-stone-400 leading-relaxed">{res.copy_hint}</p>
                            )}
                          </div>
                        ))}
                      </div>
                    )}

                    <div className="border-t border-stone-100 px-3 py-2.5">
                      {inquiryResults.length === 0 ? (
                        <button
                          onClick={handleBatchInquiry}
                          disabled={generating || selectedIds.size === 0}
                          className="w-full flex items-center justify-center gap-1.5 rounded-xl bg-amber-500 py-2.5 text-sm font-semibold text-white hover:bg-amber-600 disabled:opacity-50"
                        >
                          {generating
                            ? <><Loader2 className="h-4 w-4 animate-spin" />生成中…</>
                            : <><Send className="h-4 w-4" />为 {selectedIds.size} 套房源生成站内信</>}
                        </button>
                      ) : (
                        <button
                          onClick={() => setInquiryResults([])}
                          className="w-full rounded-xl border border-stone-300 py-2 text-xs text-stone-600 hover:bg-stone-50"
                        >
                          重新生成
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}

// ── 对比表格 ─────────────────────────────────────────────────────
function CompareTable({
  favorites,
  onSelect,
}: {
  favorites: FavoriteItem[];
  onSelect?: (fav: FavoriteItem) => void;
}) {
  if (favorites.length < 2) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-10 text-stone-400">
        <BarChart2 className="h-8 w-8 text-stone-200" />
        <p className="text-sm">至少收藏 2 套才能对比</p>
      </div>
    );
  }

  const rows = [
    { label: '月租', getValue: (f: FavoriteItem) => `¥${f.rec.listing.price_base}` },
    { label: '估算月支出', getValue: (f: FavoriteItem) => f.rec.cost ? `¥${f.rec.cost.total}` : '—' },
    { label: '通勤最快', getValue: (f: FavoriteItem) => f.rec.commute?.best_duration_min ? `${f.rec.commute.best_duration_min}min` : '—' },
    { label: '面积', getValue: (f: FavoriteItem) => f.rec.listing.area ? `${f.rec.listing.area}㎡` : '—' },
    { label: '户型', getValue: (f: FavoriteItem) => f.rec.listing.layout || '—' },
    { label: '楼层', getValue: (f: FavoriteItem) => f.rec.listing.floor || '—' },
    { label: '电梯', getValue: (f: FavoriteItem) => f.rec.listing.has_elevator === true ? '有' : f.rec.listing.has_elevator === false ? '无' : '—' },
    {
      label: '水费',
      getValue: (f: FavoriteItem) => f.rec.cost?.water ? `¥${f.rec.cost.water}` : '—',
    },
    {
      label: '电费',
      getValue: (f: FavoriteItem) => f.rec.cost?.electricity ? `¥${f.rec.cost.electricity}` : '—',
    },
    { label: '平台', getValue: (f: FavoriteItem) => f.rec.listing.platform || '—' },
  ];

  // 找最优值（数字）
  function isMin(value: string, allValues: string[]) {
    const nums = allValues.map((v) => parseFloat(v.replace(/[^0-9.]/g, ''))).filter((n) => !isNaN(n));
    const myNum = parseFloat(value.replace(/[^0-9.]/g, ''));
    return !isNaN(myNum) && nums.length > 1 && myNum === Math.min(...nums);
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr>
            <th className="w-20 py-1.5 text-left text-stone-500 font-medium sticky left-0 bg-white">项目</th>
            {favorites.map((fav) => (
              <th
                key={fav.rec.listing.id}
                className="min-w-[110px] px-2 py-1.5 text-center cursor-pointer hover:bg-amber-50 rounded-lg transition"
                onClick={() => onSelect?.(fav)}
              >
                <div className="font-semibold text-stone-800 truncate max-w-[100px] mx-auto">
                  {fav.rec.listing.community || fav.rec.listing.title?.slice(0, 8)}
                </div>
                <div className="text-stone-400 font-normal">点击查看详情</div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const values = favorites.map((f) => row.getValue(f));
            return (
              <tr key={row.label} className="border-t border-stone-100">
                <td className="py-2 text-stone-500 sticky left-0 bg-white">{row.label}</td>
                {favorites.map((fav, i) => {
                  const val = values[i];
                  const highlight = val !== '—' && isMin(val, values);
                  return (
                    <td
                      key={fav.rec.listing.id}
                      className={cn(
                        'px-2 py-2 text-center tabular-nums',
                        highlight ? 'font-bold text-emerald-700' : 'text-stone-700',
                      )}
                    >
                      {highlight ? `✓ ${val}` : val}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-stone-400">✓ 绿色加粗 = 该项最优</p>
    </div>
  );
}
