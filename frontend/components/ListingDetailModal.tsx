'use client';

import { useEffect, useState } from 'react';
import {
  X,
  ExternalLink,
  Train,
  Bike,
  Footprints,
  Car,
  MapPin,
  Sparkles,
  Loader2,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  ImageOff,
  Star,
  ThumbsUp,
  ThumbsDown,
  RefreshCw,
} from 'lucide-react';
import type {
  CommuteResult,
  CommuteSummary,
  CostBreakdown,
  Listing,
  ListingReview,
  ParsedRequirement,
  Recommendation,
} from '@/lib/types';
import { fetchListingDetail, postListingReview, type ListingDetailResult } from '@/lib/api';
import { cn, getProxiedImageUrl } from '@/lib/utils';
import UtilityWizard from '@/components/UtilityWizard';

interface ListingDetailModalProps {
  rec: Recommendation | null;
  requirement: ParsedRequirement | null;
  onClose: () => void;
}

const PLATFORM_LABEL: Record<string, { name: string; emoji: string; bg: string }> = {
  lianjia:     { name: '链家',   emoji: '🏠',  bg: 'bg-emerald-500' },
  beike:       { name: '贝壳',   emoji: '🐚',  bg: 'bg-sky-500' },
  anjuke:      { name: '安居客', emoji: '🏘️', bg: 'bg-amber-500' },
  wuba:        { name: '58同城', emoji: '🏡',  bg: 'bg-orange-500' },
  ziroom:      { name: '自如',   emoji: '🛋️', bg: 'bg-purple-500' },
  xianyu:      { name: '闲鱼',   emoji: '🐟',  bg: 'bg-orange-400' },
  xiaohongshu: { name: '小红书', emoji: '📕',  bg: 'bg-rose-500' },
};

const MODE_LABEL: Record<string, { name: string; Icon: any; color: string }> = {
  transit: { name: '公共交通', Icon: Train, color: 'text-blue-600' },
  riding: { name: '骑行', Icon: Bike, color: 'text-green-600' },
  walking: { name: '步行', Icon: Footprints, color: 'text-purple-600' },
  driving: { name: '驾车', Icon: Car, color: 'text-stone-600' },
};

const PROVIDER_LABEL: Record<string, string> = {
  amap: '高德',
  baidu: '百度',
  tencent: '腾讯',
  stable_baseline: '固化基准',
};

export default function ListingDetailModal({ rec, requirement, onClose }: ListingDetailModalProps) {
  if (!rec) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative max-h-[92vh] w-full max-w-4xl overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute right-3 top-3 z-10 rounded-full bg-white/90 p-1.5 text-stone-500 shadow hover:text-stone-900"
          aria-label="关闭"
        >
          <X className="h-5 w-5" />
        </button>

        <div className="max-h-[92vh] overflow-y-auto">
          <ModalContent rec={rec} requirement={requirement} />
        </div>
      </div>
    </div>
  );
}

function ModalContent({
  rec,
  requirement,
}: {
  rec: Recommendation;
  requirement: ParsedRequirement | null;
}) {
  const { listing, cost, commute } = rec;
  const platform = PLATFORM_LABEL[listing.platform] || {
    name: listing.platform,
    emoji: '📋',
    bg: 'bg-stone-500',
  };

  // ── 二次抓取详情页增量字段 ────────────────────────────
  const [detail, setDetail] = useState<ListingDetailResult | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    // 只对链家/贝壳触发（其他平台暂不支持）
    if (!['lianjia', 'beike'].includes(listing.platform)) return;
    if (!listing.url) return;

    setDetail(null);
    setDetailLoading(true);
    fetchListingDetail({
      url: listing.url,
      platform: listing.platform,
      listing_id: listing.id,  // v0.7: 触发cost写回
    })
      .then((res) => {
        if (res.success) setDetail(res);
      })
      .catch(() => { /* 静默失败，不影响已有数据展示 */ })
      .finally(() => setDetailLoading(false));
  }, [listing.id, listing.url, listing.platform]);

  // 合并图片：优先使用详情页的高清大图
  const allImages = detail?.images?.length
    ? detail.images
    : listing.images ?? [];

  return (
    <div>
      {/* 顶部彩条 + 标题 */}
      <div className={cn('flex items-center gap-2 px-5 py-2 text-sm text-white', platform.bg)}>
        <span>
          {platform.emoji} 来源：{platform.name}
        </span>
        <span className="ml-auto rounded bg-white/25 px-2 py-0.5 font-semibold">
          推荐 #{rec.rank}
        </span>
      </div>

      <div className="px-6 pt-5 pb-3">
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-xl font-bold text-stone-900">{listing.title}</h2>
          <a
            href={listing.url}
            target="_blank"
            rel="noreferrer"
            className="flex shrink-0 items-center gap-1 text-sm text-amber-600 hover:underline"
          >
            原页面 <ExternalLink className="h-3.5 w-3.5" />
          </a>
        </div>
        {listing.community && (
          <div className="mt-1 flex items-center gap-1 text-sm text-stone-600">
            <MapPin className="h-3.5 w-3.5" />
            {listing.community}
            {listing.address && <span className="text-stone-400">· {listing.address}</span>}
          </div>
        )}
      </div>

      {/* 图片画廊（优先详情页高清图）*/}
      <ImageGallery images={allImages} title={listing.title} />

      {/* 价格大块 */}
      <div className="mx-6 mt-4 grid grid-cols-2 gap-3">
        <div className="rounded-xl border border-stone-200 bg-stone-50 p-4">
          <div className="text-xs text-stone-500">基础房租</div>
          <div className="mt-1 text-2xl font-bold text-stone-900">
            {listing.price_base > 0 ? `¥${listing.price_base}` : '—'}
            <span className="text-sm font-normal text-stone-400">/月</span>
          </div>
        </div>
        <div className="rounded-xl border border-amber-300 bg-amber-50 p-4">
          <div className="text-xs text-amber-700">真实月支出（估算）</div>
          <div className="mt-1 text-2xl font-bold text-amber-700">
            {cost.total > 0 ? `¥${cost.total}` : '—'}
            <span className="text-sm font-normal">/月</span>
          </div>
        </div>
      </div>

      {/* 信息网格：基础字段 + 详情页增量字段 */}
      <div className="mx-6 mt-5 rounded-xl border border-stone-200 bg-white p-4">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-semibold text-stone-500 uppercase tracking-wide">房源信息</span>
          {detailLoading && (
            <span className="flex items-center gap-1 text-xs text-stone-400">
              <Loader2 className="h-3 w-3 animate-spin" />
              补全详情中…
            </span>
          )}
          {detail?.success && !detailLoading && (
            <span className="flex items-center gap-1 text-xs text-emerald-600">
              ✓ 详情已补全
              {detail.cost_updated && (
                <span className="ml-1 rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] text-emerald-700 font-medium">
                  成本已更新
                </span>
              )}
            </span>
          )}
        </div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm md:grid-cols-3">
          <InfoRow label="户型" value={listing.layout} />
          <InfoRow label="面积" value={listing.area ? `${listing.area} ㎡` : null} />
          <InfoRow label="朝向" value={listing.orientation} />
          <InfoRow label="楼层" value={listing.floor} />
          <InfoRow
            label="电梯"
            value={
              detail?.elevator != null
                ? (detail.elevator ? '有电梯' : '无电梯')
                : listing.has_elevator === true
                  ? '有'
                  : listing.has_elevator === false
                    ? '无'
                    : null
            }
          />
          <InfoRow label="租赁形态" value={listing.rental_type_tag} />
          {/* 详情页增量字段 */}
          <InfoRow label="押付方式" value={detail?.deposit_type ?? null} />
          <InfoRow label="入住时间" value={detail?.move_in ?? null} />
          <InfoRow label="用水" value={detail?.water_type ?? null} />
          <InfoRow label="用电" value={detail?.electricity_type ?? null} />
          <InfoRow label="燃气" value={detail?.gas_type ?? null} />
          <InfoRow label="供暖" value={detail?.heating_type ?? null} />
        </div>

        {/* 配套设施 */}
        {detail?.facilities && detail.facilities.length > 0 && (
          <div className="mt-3 border-t border-stone-100 pt-3">
            <div className="mb-1.5 text-xs text-stone-500">配套设施</div>
            <div className="flex flex-wrap gap-1.5">
              {detail.facilities.map((f) => (
                <span key={f} className="rounded-full bg-stone-100 px-2.5 py-1 text-xs text-stone-700">
                  {f}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* 房东描述 */}
        {detail?.description && (
          <div className="mt-3 border-t border-stone-100 pt-3 text-xs text-stone-500 leading-relaxed">
            <span className="font-medium text-stone-600">房东/中介说：</span>
            {detail.description}
          </div>
        )}
      </div>

      {/* AI 点评 */}
      <AIReviewSection rec={rec} requirement={requirement} />

      {/* 通勤板块（详细） */}
      <CommuteDetailSection commute={commute} missingFields={listing.missing_fields} />

      {/* 成本明细 + 水电精算 */}
      <CostDetailSection
        cost={cost}
        listingId={listing.id}
        listingArea={listing.area}
      />

      <div className="px-6 pb-5 pt-3 text-center text-xs text-stone-400">
        ⚠️ 数据来自平台公开页面，最终请以中介/房东沟通为准
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <div className="text-xs text-stone-500">{label}</div>
      <div className={cn('mt-0.5', value ? 'text-stone-900' : 'text-stone-400')}>
        {value || '未提供'}
      </div>
    </div>
  );
}

// ============================================================
// 图片画廊
// ============================================================
function ImageGallery({ images, title }: { images: string[]; title: string }) {
  const valid = (images || []).filter(Boolean);
  const proxied = valid.map(getProxiedImageUrl);
  const [idx, setIdx] = useState(0);
  const [errored, setErrored] = useState<Record<number, boolean>>({});

  if (valid.length === 0) {
    return (
      <div className="mx-6 mt-3 flex h-48 items-center justify-center rounded-xl bg-stone-100 text-stone-400">
        <ImageOff className="mr-2 h-6 w-6" />
        暂无图片
      </div>
    );
  }

  const current = proxied[idx];

  return (
    <div className="mx-6 mt-3">
      <div className="relative h-64 overflow-hidden rounded-xl bg-stone-100 md:h-80">
        {errored[idx] ? (
          <div className="flex h-full w-full flex-col items-center justify-center text-stone-400">
            <ImageOff className="h-8 w-8" />
            <p className="mt-1 text-xs">图片加载失败</p>
          </div>
        ) : (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={current}
            alt={title}
            className="h-full w-full object-cover"
            referrerPolicy="no-referrer"
            onError={() => setErrored((p) => ({ ...p, [idx]: true }))}
          />
        )}
        {valid.length > 1 && (
          <>
            <button
              onClick={() => setIdx((i) => (i - 1 + valid.length) % valid.length)}
              className="absolute left-2 top-1/2 -translate-y-1/2 rounded-full bg-white/90 p-1.5 text-stone-700 shadow hover:bg-white"
              aria-label="上一张"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <button
              onClick={() => setIdx((i) => (i + 1) % valid.length)}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full bg-white/90 p-1.5 text-stone-700 shadow hover:bg-white"
              aria-label="下一张"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
            <div className="absolute bottom-2 right-2 rounded-full bg-black/50 px-2 py-0.5 text-xs text-white">
              {idx + 1} / {valid.length}
            </div>
          </>
        )}
      </div>
      {valid.length > 1 && (
        <div className="mt-2 flex gap-1.5 overflow-x-auto">
          {proxied.map((url, i) => (
            <button
              key={i}
              onClick={() => setIdx(i)}
              className={cn(
                'h-12 w-16 shrink-0 overflow-hidden rounded border-2',
                i === idx ? 'border-amber-500' : 'border-transparent opacity-60 hover:opacity-100',
              )}
            >
              {errored[i] ? (
                <div className="flex h-full w-full items-center justify-center bg-stone-100 text-stone-400">
                  <ImageOff className="h-3 w-3" />
                </div>
              ) : (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={url}
                  alt=""
                  className="h-full w-full object-cover"
                  referrerPolicy="no-referrer"
                  onError={() => setErrored((p) => ({ ...p, [i]: true }))}
                />
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================================
// AI 点评
// ============================================================
function AIReviewSection({
  rec,
  requirement,
}: {
  rec: Recommendation;
  requirement: ParsedRequirement | null;
}) {
  const [review, setReview] = useState<ListingReview | null>(rec.ai_review || null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function handleGenerate(force = false) {
    setLoading(true);
    setError('');
    try {
      const res = await postListingReview({
        listing: rec.listing,
        cost: rec.cost,
        commute: rec.commute,
        requirement: requirement,
        force_refresh: force,
      });
      setReview(res.review);
    } catch (e: any) {
      setError(e?.message || '生成失败');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-6 mt-5 rounded-xl border border-purple-200 bg-gradient-to-br from-purple-50 to-amber-50 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-purple-700">
          <Sparkles className="h-4 w-4" />
          AI 点评
        </h3>
        {review && !loading && (
          <button
            onClick={() => handleGenerate(true)}
            className="flex items-center gap-1 text-xs text-stone-500 hover:text-purple-600"
            title="重新生成"
          >
            <RefreshCw className="h-3 w-3" />
            重新生成
          </button>
        )}
      </div>

      {!review && !loading && !error && (
        <button
          onClick={() => handleGenerate(false)}
          className="w-full rounded-lg bg-purple-600 py-2.5 text-sm font-medium text-white transition hover:bg-purple-700"
        >
          ✨ 让 AI 帮我点评这套房（综合需求/成本/通勤）
        </button>
      )}

      {loading && (
        <div className="flex items-center gap-2 py-3 text-sm text-stone-600">
          <Loader2 className="h-4 w-4 animate-spin text-purple-600" />
          AI 正在综合分析（约 5-15 秒）...
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
          ❌ {error}
          <button
            onClick={() => handleGenerate(false)}
            className="ml-2 underline hover:text-rose-900"
          >
            重试
          </button>
        </div>
      )}

      {review && (
        <div className="space-y-3">
          {/* 评分 + 总结 */}
          <div className="flex items-start gap-3">
            <ScoreBadge score={review.score} />
            <div className="flex-1 text-sm text-stone-800">{review.summary || '（无总结）'}</div>
          </div>

          {/* 标签 */}
          {review.tags?.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {review.tags.map((t) => (
                <span
                  key={t}
                  className="rounded-full bg-white/70 px-2 py-0.5 text-xs text-purple-700 ring-1 ring-purple-200"
                >
                  #{t}
                </span>
              ))}
            </div>
          )}

          {/* 优缺点 */}
          <div className="grid gap-3 md:grid-cols-2">
            <ProsConsList items={review.pros} type="pros" />
            <ProsConsList items={review.cons} type="cons" />
          </div>

          <div className="text-right text-xs text-stone-400">
            {review.model && <>by {review.model}</>}
            {review.generated_at && (
              <span className="ml-2">{review.generated_at.replace('T', ' ')}</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ScoreBadge({ score }: { score: number }) {
  const color =
    score >= 8
      ? 'bg-emerald-500'
      : score >= 6
        ? 'bg-amber-500'
        : score >= 4
          ? 'bg-orange-500'
          : 'bg-rose-500';
  return (
    <div className={cn('flex h-14 w-14 shrink-0 flex-col items-center justify-center rounded-xl text-white', color)}>
      <Star className="h-3 w-3" />
      <div className="mt-0.5 text-lg font-bold leading-none">{score.toFixed(1)}</div>
      <div className="text-[10px] opacity-80">/10</div>
    </div>
  );
}

function ProsConsList({ items, type }: { items: string[]; type: 'pros' | 'cons' }) {
  if (!items || items.length === 0) return null;
  const isPros = type === 'pros';
  const Icon = isPros ? ThumbsUp : ThumbsDown;
  return (
    <div className={cn('rounded-lg p-3', isPros ? 'bg-emerald-50' : 'bg-rose-50')}>
      <div
        className={cn(
          'mb-1.5 flex items-center gap-1 text-xs font-semibold',
          isPros ? 'text-emerald-700' : 'text-rose-700',
        )}
      >
        <Icon className="h-3 w-3" />
        {isPros ? '优点' : '需注意'}
      </div>
      <ul className="space-y-1 text-sm text-stone-800">
        {items.map((it, i) => (
          <li key={i} className="flex gap-1.5">
            <span className={cn('mt-1.5 h-1 w-1 shrink-0 rounded-full', isPros ? 'bg-emerald-500' : 'bg-rose-500')} />
            <span>{it}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ============================================================
// 通勤详细板块
// ============================================================
function CommuteDetailSection({
  commute,
  missingFields,
}: {
  commute: CommuteSummary | null;
  missingFields?: string[];
}) {
  if (!commute || !commute.results || commute.results.length === 0) {
    const commuteFlag = (missingFields || []).find((f) => f.startsWith('通勤'));
    let reasonText = '尚未测算，请回到列表页点击右上角「继续测算」按钮';
    if (commuteFlag) {
      const m = commuteFlag.match(/（(.+?)）/);
      if (m) reasonText = m[1];
      else reasonText = commuteFlag.replace(/^通勤[：:]?/, '');
    }
    return (
      <div className="mx-6 mt-5 rounded-xl border border-stone-200 bg-stone-50 p-4 text-sm text-stone-500">
        🚇 通勤数据未测算 · <span className="text-stone-600">{reasonText}</span>
      </div>
    );
  }

  // 按 (mode, direction) 聚合，按 provider 拆开
  const groups: Record<string, Record<string, CommuteResult[]>> = {};
  for (const r of commute.results) {
    const key = `${r.mode}__${r.direction}`;
    if (!groups[key]) groups[key] = {};
    if (!groups[key][r.map_provider]) groups[key][r.map_provider] = [];
    groups[key][r.map_provider].push(r);
  }

  // 收集所有 direction 用于切换（过滤空值）
  const directions = Array.from(
    new Set(commute.results.map((r) => r.direction).filter((d) => !!d))
  );
  if (directions.length === 0) directions.push('home_to_work');

  const [direction, setDirection] = useState(directions[0]);

  // commute 数据更新时（精算后）重置到第一个有效方向
  useEffect(() => {
    if (!directions.includes(direction)) {
      setDirection(directions[0]);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [commute.results.length, commute.results.map(r => r.direction).join(',')]);

  const dirLabel: Record<string, string> = {
    home_to_work: '家 → 公司',
    work_to_home: '公司 → 家',
  };

  // 当前方向的数据
  const filteredResults = commute.results.filter((r) => r.direction === direction);
  const modes = Array.from(new Set(filteredResults.map((r) => r.mode)));

  return (
    <div className="mx-6 mt-5 rounded-xl border border-stone-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-stone-700">
          🚇 通勤详情
          <span className="ml-2 text-xs font-normal text-stone-500">
            最快 {commute.best_duration_min} 分钟
          </span>
        </h3>
        {directions.length > 1 && (
          <div className="flex gap-1 text-xs">
            {directions.map((d) => (
              <button
                key={d}
                onClick={() => setDirection(d)}
                className={cn(
                  'rounded px-2 py-1',
                  direction === d
                    ? 'bg-stone-900 text-white'
                    : 'bg-stone-100 text-stone-600 hover:bg-stone-200',
                )}
              >
                {dirLabel[d] || d}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="text-xs text-stone-500">
        目的地：{commute.destination_address || '未提供'}
      </div>

      {/* 表格：行=模式，列=地图 */}
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-stone-200 text-xs text-stone-500">
              <th className="py-1.5 text-left font-normal">方式</th>
              <th className="py-1.5 text-center font-normal">高德</th>
              <th className="py-1.5 text-center font-normal">腾讯</th>
              <th className="py-1.5 text-center font-normal">百度</th>
              <th className="py-1.5 text-right font-normal">距离</th>
            </tr>
          </thead>
          <tbody>
            {modes.map((mode) => {
              const meta = MODE_LABEL[mode] || { name: mode, Icon: Footprints, color: 'text-stone-600' };
              const Icon = meta.Icon;
              // stable_baseline 归入高德列显示（离线固化数据，优先级等同高德）
              const amap = filteredResults.find(
                (r) => r.mode === mode && (r.map_provider === 'amap' || r.map_provider === 'stable_baseline')
              );
              const tencent = filteredResults.find((r) => r.mode === mode && r.map_provider === 'tencent');
              const baidu = filteredResults.find((r) => r.mode === mode && r.map_provider === 'baidu');
              const dist = amap?.distance_km || tencent?.distance_km || baidu?.distance_km;
              return (
                <tr key={mode} className="border-b border-stone-100 last:border-0">
                  <td className="py-2">
                    <div className={cn('flex items-center gap-1.5', meta.color)}>
                      <Icon className="h-3.5 w-3.5" />
                      <span className="text-stone-800">{meta.name}</span>
                    </div>
                  </td>
                  <td className="py-2 text-center tabular-nums">
                    {amap ? (
                      <span title={amap.map_provider === 'stable_baseline' ? '固化基准（历史多次精算均值）' : '高德实时'}>
                        {amap.duration_min} min
                        {amap.map_provider === 'stable_baseline' && (
                          <span className="ml-0.5 text-stone-400 text-xs">*</span>
                        )}
                      </span>
                    ) : <span className="text-stone-300">—</span>}
                  </td>
                  <td className="py-2 text-center tabular-nums">
                    {tencent ? `${tencent.duration_min} min` : <span className="text-stone-300">—</span>}
                  </td>
                  <td className="py-2 text-center tabular-nums">
                    {baidu ? `${baidu.duration_min} min` : <span className="text-stone-300">—</span>}
                  </td>
                  <td className="py-2 text-right text-xs tabular-nums text-stone-500">
                    {dist ? `${dist.toFixed(1)} km` : '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {commute.nearest_metro && (
        <div className="mt-3 rounded-lg bg-blue-50 px-3 py-2 text-xs text-blue-700">
          🚇 最近地铁：<span className="font-semibold">{commute.nearest_metro}</span>
          {commute.metro_walk_min && (
            <span className="ml-1">（步行约 {commute.metro_walk_min} 分钟）</span>
          )}
        </div>
      )}

      <div className="mt-2 text-xs text-stone-400">
        {directions.length <= 1
          ? '💡 双向通勤（家→公司 / 公司→家）需点卡片上「⚡ 查询实时」精算后显示'
          : '💡 数据来自高德/腾讯/百度三家地图，结果可能略有差异，以实际出行为准'}
      </div>
    </div>
  );
}

// ============================================================
// 成本明细 + 智能水电精算
// ============================================================
function CostDetailSection({
  cost: initialCost,
  listingId,
  listingArea,
}: {
  cost: CostBreakdown;
  listingId: string;
  listingArea?: number | null;
}) {
  const [cost, setCost] = useState<CostBreakdown>(initialCost);

  // 水电精算写回后，用新的 notes 更新成本展示
  function handleUtilityApplied(newTotal: number, newNotes: Record<string, string>) {
    setCost((prev) => ({
      ...prev,
      notes: { ...prev.notes, ...newNotes },
      // 前端侧同步更新三项费用（通过 delta 反推，或直接靠后端返回 total）
      // 这里简单靠 total 展示更新即可，细节由后端写回 DB
    }));
  }

  const items = [
    { key: 'base_rent', label: '基础房租', value: cost.base_rent, note: cost.notes?.base_rent },
    { key: 'property_fee', label: '物业费', value: cost.property_fee, note: cost.notes?.property_fee },
    { key: 'water', label: '水费', value: cost.water, note: cost.notes?.water },
    { key: 'electricity', label: '电费', value: cost.electricity, note: cost.notes?.electricity },
    { key: 'gas', label: '燃气', value: cost.gas, note: cost.notes?.gas },
    { key: 'internet', label: '网络', value: cost.internet, note: cost.notes?.internet },
    {
      key: 'agency_fee_monthly',
      label: '中介摊销',
      value: cost.agency_fee_monthly,
      note: cost.notes?.agency_fee_monthly,
    },
    {
      key: 'deposit_cost',
      label: '押金占用',
      value: cost.deposit_cost,
      note: cost.notes?.deposit_cost,
    },
  ];

  return (
    <div className="mx-6 mt-5 mb-2 rounded-xl border border-stone-200 bg-white p-4">
      <h3 className="mb-3 text-sm font-semibold text-stone-700">📊 成本明细（含计算依据）</h3>
      <div className="space-y-2 text-sm">
        {items.map((it) =>
          it.value > 0 || it.note ? (
            <div
              key={it.key}
              className="flex items-start justify-between gap-3 border-b border-dashed border-stone-100 pb-2 last:border-0"
            >
              <div className="flex-1">
                <span className="text-stone-700">{it.label}</span>
                {it.note && <div className="mt-0.5 text-xs text-stone-400">└ {it.note}</div>}
              </div>
              <span className="shrink-0 tabular-nums text-stone-900">¥{it.value}</span>
            </div>
          ) : null,
        )}
        <div className="mt-3 flex items-center justify-between rounded-lg bg-amber-50 px-3 py-2 font-semibold text-amber-700">
          <span>合计 (估算)</span>
          <span className="text-lg">¥{cost.total}/月</span>
        </div>
      </div>

      {/* 智能水电精算入口（就近悬浮在成本明细下方）*/}
      <UtilityWizard
        listingId={listingId}
        listingArea={listingArea ?? 70}
        onApplied={handleUtilityApplied}
      />
    </div>
  );
}
