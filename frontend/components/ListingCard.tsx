'use client';

import { useState } from 'react';
import type { CommuteSummary, Recommendation } from '@/lib/types';
import { postPreciseOne } from '@/lib/api';
import {
  ExternalLink,
  Train,
  Bike,
  Footprints,
  AlertCircle,
  ImageOff,
  MapPin,
  Zap,
  Loader2,
  Heart,
} from 'lucide-react';
import Tooltip from '@/components/Tooltip';
import { cn, getProxiedImageUrl } from '@/lib/utils';

const PLATFORM_LABEL: Record<string, { name: string; color: string; emoji: string }> = {
  lianjia:     { name: '链家',   color: 'bg-emerald-100 text-emerald-700 border-emerald-300', emoji: '🏠' },
  beike:       { name: '贝壳',   color: 'bg-sky-100 text-sky-700 border-sky-300',             emoji: '🐚' },
  anjuke:      { name: '安居客', color: 'bg-amber-100 text-amber-700 border-amber-300',       emoji: '🏘️' },
  wuba:        { name: '58同城', color: 'bg-orange-100 text-orange-700 border-orange-300',    emoji: '🏡' },
  ziroom:      { name: '自如',   color: 'bg-purple-100 text-purple-700 border-purple-300',    emoji: '🛋️' },
  xianyu:      { name: '闲鱼',   color: 'bg-orange-100 text-orange-700 border-orange-300',    emoji: '🐟' },
  xiaohongshu: { name: '小红书', color: 'bg-rose-100 text-rose-700 border-rose-300',          emoji: '📕' },
};

function detectIsOffline(missingFields: string[] | undefined): boolean {
  return (missingFields || []).some((f) => f.includes('离线估算'));
}

export default function ListingCard({
  rec,
  onSelect,
  onCommuteUpdated,
  isFavorited,
  onToggleFavorite,
}: {
  rec: Recommendation;
  onSelect?: (rec: Recommendation) => void;
  onCommuteUpdated?: () => void;
  isFavorited?: boolean;
  onToggleFavorite?: (rec: Recommendation) => void;
}) {
  const { listing, cost, commute } = rec;
  const platform = PLATFORM_LABEL[listing.platform] || {
    name: listing.platform,
    color: 'bg-stone-100 text-stone-700 border-stone-300',
    emoji: '📋',
  };
  const isOffline = detectIsOffline(listing.missing_fields);
  const distanceKm = (listing as any).distance_km as number | undefined;

  const handleCardClick = () => onSelect?.(rec);

  return (
    <div
      onClick={handleCardClick}
      className="cursor-pointer overflow-hidden rounded-2xl border-2 border-stone-200 bg-white shadow-sm transition hover:border-amber-300 hover:shadow-md"
    >
      <div
        className={`flex items-center justify-between border-b ${platform.color
          .replace('bg-', 'border-')
          .split(' ')[0]} px-4 py-1.5 text-xs ${platform.color}`}
      >
        <span className="font-medium">
          {platform.emoji} 来源：{platform.name}
        </span>
        <span className="rounded bg-white/60 px-2 py-0.5 font-semibold">推荐 #{rec.rank}</span>
        {onToggleFavorite && (
          <button
            onClick={(e) => { e.stopPropagation(); onToggleFavorite(rec); }}
            className={cn(
              'ml-1 rounded-full p-1 transition',
              isFavorited
                ? 'text-rose-500 hover:text-rose-600'
                : 'text-stone-400 hover:text-rose-400',
            )}
            title={isFavorited ? '取消收藏' : '收藏'}
          >
            <Heart className={cn('h-3.5 w-3.5', isFavorited && 'fill-rose-500')} />
          </button>
        )}
      </div>

      <div className="flex gap-4 p-4">
        <CardImage url={listing.images?.[0]} title={listing.title} priceBase={listing.price_base} platform={listing.platform} />

        <div className="flex flex-1 flex-col">
          <div className="flex items-start justify-between gap-2">
            <a
              href={listing.url}
              target="_blank"
              rel="noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="line-clamp-2 text-base font-semibold text-stone-900 hover:text-amber-600"
            >
              {listing.title}
              <ExternalLink className="ml-1 inline h-3.5 w-3.5" />
            </a>
          </div>

          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-stone-600">
            {listing.community && (
              <span className="flex items-center gap-0.5">
                <MapPin className="h-3 w-3" />
                {listing.community}
              </span>
            )}
            {listing.layout && <span>🏠 {listing.layout}</span>}
            {listing.area && <span>📐 {listing.area}㎡</span>}
            {listing.floor && <span>🏢 {listing.floor}</span>}
            {listing.orientation && <span>☀️ 朝{listing.orientation}</span>}
            {typeof distanceKm === 'number' && (
              <span className="rounded bg-stone-50 px-1.5 text-stone-600">
                直线 {distanceKm.toFixed(1)}km
              </span>
            )}
            {listing.rental_type_tag && (
              <span className="rounded bg-amber-50 px-1.5 text-amber-700">{listing.rental_type_tag}</span>
            )}
          </div>

          <div className="mt-2 flex items-baseline gap-3">
            <div>
              <span className="text-xs text-stone-500">基础房租</span>
              <div className="text-lg font-bold text-stone-900">
                {listing.price_base > 0 ? `¥${listing.price_base}` : '—'}
                <span className="text-xs font-normal text-stone-400">/月</span>
              </div>
            </div>
            <div className="rounded-lg bg-amber-50 px-3 py-1">
              <span className="text-xs text-amber-700">真实月支出 (估算)</span>
              <div className="text-lg font-bold text-amber-700">
                {cost.total > 0 ? `¥${cost.total}` : '—'}
                <span className="text-xs font-normal">/月</span>
              </div>
            </div>
          </div>

          <CommuteSection
            commute={commute}
            missingFields={listing.missing_fields}
            isOffline={isOffline}
            listingId={listing.id}
            onCommuteUpdated={onCommuteUpdated}
          />

          {rec.reason && <div className="mt-2 text-xs text-stone-500">💡 {rec.reason}</div>}

          <div className="mt-2 text-right text-[11px] text-amber-600">点击查看详情 + AI 点评 →</div>
        </div>
      </div>

      <CostDetail cost={cost} />
    </div>
  );
}

function CardImage({ url, title, priceBase, platform }: { url?: string; title: string; priceBase: number; platform?: string }) {
  const [error, setError] = useState(false);
  const proxiedUrl = getProxiedImageUrl(url);

  if (!url || error) {
    return (
      <div className="flex h-32 w-44 flex-shrink-0 flex-col items-center justify-center rounded-lg bg-stone-100 text-stone-400">
        <ImageOff className="h-8 w-8" />
        <p className="mt-1 text-xs">暂无图片</p>
        {priceBase > 0 && <p className="mt-1 text-xs text-stone-500">¥{priceBase}/月</p>}
      </div>
    );
  }

  return (
    <div className="h-32 w-44 flex-shrink-0 overflow-hidden rounded-lg bg-stone-100">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={proxiedUrl}
        alt={title}
        className="h-full w-full object-cover"
        onError={() => setError(true)}
        loading="lazy"
        referrerPolicy="no-referrer"
      />
    </div>
  );
}

function CommuteSection({
  commute,
  missingFields,
  isOffline,
  listingId,
  onCommuteUpdated,
}: {
  commute: CommuteSummary | null;
  missingFields?: string[];
  isOffline: boolean;
  listingId: string;
  onCommuteUpdated?: () => void;
}) {
  const [precising, setPrecising] = useState(false);
  const [preciseErr, setPreciseErr] = useState('');

  async function handlePrecise(e: React.MouseEvent) {
    e.stopPropagation();
    if (precising) return;
    setPrecising(true);
    setPreciseErr('');
    try {
      const res = await postPreciseOne(listingId);
      if (!res.success) {
        setPreciseErr(res.fail_reason || '精算失败');
      } else {
        onCommuteUpdated?.();
      }
    } catch (err: any) {
      setPreciseErr(err?.message || '精算失败');
    } finally {
      setPrecising(false);
    }
  }

  if (!commute || commute.results.length === 0) {
    const commuteFlag = (missingFields || []).find((f) => f.startsWith('通勤'));
    let reasonText = '尚未估算';
    if (commuteFlag) {
      const m = commuteFlag.match(/（(.+?)）/);
      if (m) reasonText = m[1];
      else reasonText = commuteFlag.replace(/^通勤[：:]?/, '');
    }
    return (
      <div className="mt-2 rounded-lg bg-stone-50 px-2 py-1.5 text-xs text-stone-500">
        🚇 通勤：<span className="text-stone-600">{reasonText}</span>
      </div>
    );
  }

  const grouped: Record<string, { durations: number[]; sources: Set<string> }> = {};
  // 卡片只展示"家→公司"方向（避免双向混合导致均值偏大/偏小）
  const h2wResults = commute.results.filter(
    (r) => !r.direction || r.direction === 'home_to_work'
  );
  const displayResults = h2wResults.length > 0 ? h2wResults : commute.results;
  for (const r of displayResults) {
    if (!grouped[r.mode]) grouped[r.mode] = { durations: [], sources: new Set() };
    grouped[r.mode].durations.push(r.duration_min);
    grouped[r.mode].sources.add(r.map_provider);
  }

  // 按 source 区分整个面板的视觉风格
  const panelClass = isOffline
    ? 'border border-stone-200 bg-stone-50/60'
    : 'border border-emerald-200 bg-emerald-50/60';

  return (
    <div className={`mt-2 rounded-lg ${panelClass} px-2 py-1.5`}>
      <div className="mb-1 flex items-center justify-between text-xs">
        <div className="flex items-center gap-1.5">
          <span className="text-stone-700 font-medium">
            🚇 通勤（最快 {commute.best_duration_min} 分钟）
          </span>
          {isOffline ? (
            <Tooltip
              position="top"
              width="w-64"
              content={
                <span>
                  <b>📍 离线估算</b>：基于直线距离 × 经验系数计算，误差约 ±25%。
                  <br /><br />
                  点右侧「⚡ 查询实时」升级为高德精算（误差 &lt;5%）。
                </span>
              }
            >
              <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold text-amber-800 cursor-help">
                📍 离线估算
              </span>
            </Tooltip>
          ) : (
            <Tooltip
              position="top"
              width="w-52"
              content="✓ 高德/百度地图实时路径规划，当前时刻数据，误差 <5%。"
            >
              <span className="rounded bg-emerald-500 px-1.5 py-0.5 text-[10px] font-bold text-white cursor-help">
                ✓ 实时数据
              </span>
            </Tooltip>
          )}
        </div>
        {isOffline && (
          <button
            onClick={handlePrecise}
            disabled={precising}
            className="flex items-center gap-0.5 rounded bg-emerald-500 px-2 py-0.5 text-[10px] font-bold text-white shadow-sm transition hover:bg-emerald-600 disabled:opacity-50"
            title="对这条房源调用高德地图算精确通勤"
          >
            {precising ? (
              <>
                <Loader2 className="h-2.5 w-2.5 animate-spin" />
                查询中
              </>
            ) : (
              <>
                <Zap className="h-2.5 w-2.5" />
                ⚡ 查询实时
              </>
            )}
          </button>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {Object.entries(grouped).map(([mode, { durations, sources }]) => {
          const avg = Math.round(durations.reduce((a, b) => a + b, 0) / durations.length);
          const sourceLabel = sources.size === 2 ? '高德+百度均值' : Array.from(sources)[0];
          return <CommuteChip key={mode} mode={mode} duration={avg} source={sourceLabel} />;
        })}
      </div>
      {isOffline && (
        <div className="mt-1 text-[10px] text-stone-500">
          ⓘ 估算基于直线距离，仅供参考。实际地铁/绕路可能让数据偏低，建议点「⚡ 查询实时」
        </div>
      )}
      {preciseErr && (
        <div className="mt-1 flex items-start gap-1 text-[11px] text-rose-600">
          <AlertCircle className="mt-0.5 h-3 w-3 flex-shrink-0" />
          <span>{preciseErr}</span>
        </div>
      )}
    </div>
  );
}

function CommuteChip({ mode, duration, source }: { mode: string; duration: number; source: string }) {
  const Icon = mode === 'transit' ? Train : mode === 'riding' ? Bike : Footprints;
  const label =
    mode === 'transit' ? '公交' : mode === 'riding' ? '骑行' : mode === 'walking' ? '步行' : mode;
  const color =
    mode === 'transit'
      ? 'bg-blue-50 text-blue-700'
      : mode === 'riding'
        ? 'bg-green-50 text-green-700'
        : 'bg-purple-50 text-purple-700';

  return (
    <div className={`flex items-center gap-1 rounded-full ${color} px-2 py-0.5 text-xs`}>
      <Icon className="h-3 w-3" />
      <span>{label}</span>
      <span className="font-semibold">{duration}min</span>
      <span
        className="text-stone-400"
        title={source === '高德+百度均值' ? '高德和百度地图取均值' : `数据来自${source}`}
      >
        ·
      </span>
    </div>
  );
}

function CostDetail({ cost }: { cost: Recommendation['cost'] }) {
  const items = [
    { key: 'base_rent', label: '基础房租', value: cost.base_rent, note: cost.notes?.base_rent },
    { key: 'property_fee', label: '物业费', value: cost.property_fee, note: cost.notes?.property_fee },
    { key: 'water', label: '水费', value: cost.water, note: cost.notes?.water },
    { key: 'electricity', label: '电费', value: cost.electricity, note: cost.notes?.electricity },
    { key: 'gas', label: '燃气', value: cost.gas, note: cost.notes?.gas },
    { key: 'internet', label: '网络', value: cost.internet, note: cost.notes?.internet },
    { key: 'agency_fee_monthly', label: '中介摊销', value: cost.agency_fee_monthly, note: cost.notes?.agency_fee_monthly },
    { key: 'deposit_cost', label: '押金占用', value: cost.deposit_cost, note: cost.notes?.deposit_cost },
  ];

  return (
    <details
      className="border-t border-stone-100 px-4 py-2 text-xs text-stone-700"
      onClick={(e) => e.stopPropagation()}
    >
      <summary className="cursor-pointer select-none font-medium hover:text-amber-600">
        📊 查看成本明细（含计算依据）
      </summary>
      <div className="mt-3 space-y-1.5">
        {items.map((it) =>
          it.value > 0 || it.note ? (
            <div
              key={it.key}
              className="flex items-start justify-between border-b border-dashed border-stone-100 pb-1"
            >
              <div>
                <span className="font-medium">{it.label}</span>
                {it.note && <div className="mt-0.5 text-stone-400">└ {it.note}</div>}
              </div>
              <span className="ml-2 font-semibold tabular-nums">¥{it.value}</span>
            </div>
          ) : null,
        )}
        <div className="mt-2 flex items-center justify-between rounded-md bg-amber-50 px-2 py-1.5 font-bold text-amber-700">
          <span>合计 (估算)</span>
          <span>¥{cost.total}/月</span>
        </div>
        <p className="mt-2 text-stone-400">
          ⚠️ 成本基于广州地区均价估算，实际请以中介/房东沟通为准。
          后续版本将根据你的生活习惯（空调使用、做饭频率等）精算。
        </p>
      </div>
    </details>
  );
}
