'use client';

import { useState } from 'react';
import type { ParsedRequirement } from '@/lib/types';
import { MapPin, Clock, Wallet, Home, ChevronDown, ChevronUp } from 'lucide-react';

const RENTAL_TYPE_LABEL: Record<string, string> = {
  entire: '整租',
  entire_1b1b: '整租一居',
  entire_2b1b: '整租两居',
  entire_3b1b: '整租三居+',
  single_room: '独立单间',
  shared: '合租',
  urban_village: '城中村',
  basement: '地下室',
  old_building: '老破小',
};

const MODE_LABEL: Record<string, string> = {
  transit: '公交',
  riding: '骑行',
  walking: '步行',
  driving: '驾车',
};

function fmt(values: string[], dict: Record<string, string>) {
  return values.map((v) => dict[v] || v).join('/');
}

export default function RequirementPanel({ req }: { req: ParsedRequirement | null }) {
  const [expanded, setExpanded] = useState(false);

  if (!req) {
    return (
      <div className="rounded-2xl border border-stone-200 bg-white/80 px-4 py-3 text-xs text-stone-400">
        AI 解析的需求会在这里实时显示
      </div>
    );
  }

  const { destination, commute, rental_type, price, hard_excludes } = req;

  const destText = [destination.city, destination.district, destination.landmark]
    .filter(Boolean)
    .join(' ') || '尚未指定';

  const commuteText = commute.max_minutes
    ? `≤${commute.max_minutes}分钟 · ${fmt(commute.modes, MODE_LABEL) || '不限'}`
    : '不限';

  const includeText = rental_type.include.length
    ? fmt(rental_type.include, RENTAL_TYPE_LABEL)
    : '不限';

  const priceParts: string[] = [];
  if (price.base_rent_max) priceParts.push(`≤¥${price.base_rent_max}`);
  if (price.total_cost_max) priceParts.push(`全包≤¥${price.total_cost_max}`);
  const priceText = priceParts.join(' · ') || '不限';

  // 单行摘要：目的地 + 通勤 + 预算
  const summary = [destText, commuteText, priceText].filter((t) => t && t !== '不限').join('  ·  ');

  return (
    <div className="flex-shrink-0 rounded-2xl border border-stone-200 bg-white/80 shadow-sm">
      {/* 折叠头：始终可见 */}
      <button
        className="flex w-full items-center justify-between px-4 py-2.5 text-left"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xs font-semibold text-stone-600 flex-shrink-0">📋 当前需求</span>
          {!expanded && summary && (
            <span className="truncate text-xs text-stone-500">{summary}</span>
          )}
        </div>
        {expanded
          ? <ChevronUp className="h-3.5 w-3.5 flex-shrink-0 text-stone-400" />
          : <ChevronDown className="h-3.5 w-3.5 flex-shrink-0 text-stone-400" />}
      </button>

      {/* 展开详情 */}
      {expanded && (
        <div className="border-t border-stone-100 px-4 pb-3 pt-2 space-y-2 text-sm">
          <Row icon={<MapPin className="h-3.5 w-3.5" />} label="目的地">
            <span className={destText === '尚未指定' ? 'text-stone-400' : ''}>{destText}</span>
          </Row>
          <Row icon={<Clock className="h-3.5 w-3.5" />} label="通勤">
            <span className={commuteText === '不限' ? 'text-stone-400' : ''}>{commuteText}</span>
          </Row>
          <Row icon={<Home className="h-3.5 w-3.5" />} label="户型">
            <span className={includeText === '不限' ? 'text-stone-400' : ''}>{includeText}</span>
            {rental_type.exclude.length > 0 && (
              <span className="ml-2 text-rose-500 text-xs">
                排除 {fmt(rental_type.exclude, RENTAL_TYPE_LABEL)}
              </span>
            )}
          </Row>
          <Row icon={<Wallet className="h-3.5 w-3.5" />} label="预算">
            <span className={priceText === '不限' ? 'text-stone-400' : ''}>{priceText}</span>
          </Row>
          {hard_excludes.length > 0 && (
            <div className="flex flex-wrap gap-1 pt-1">
              {hard_excludes.map((tag) => (
                <span key={tag} className="rounded-full bg-rose-50 px-2 py-0.5 text-xs text-rose-600">
                  ✕ {tag}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Row({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-2">
      <span className="mt-0.5 text-stone-400">{icon}</span>
      <div className="flex-1 min-w-0">
        <div className="text-xs text-stone-400">{label}</div>
        <div className="text-stone-800 text-xs leading-snug">{children}</div>
      </div>
    </div>
  );
}
