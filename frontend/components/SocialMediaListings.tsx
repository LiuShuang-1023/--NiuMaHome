'use client';

/**
 * 社交媒体租房帖聚合面板 (v0.9.2)
 * 小红书 + 闲鱼 租房帖搜索跳转
 * - 由于两平台均无公开 API，采用「构造搜索URL → 新窗口打开」方式
 * - 提供搜索关键词模板，用户可自定义
 */

import { useState } from 'react';
import { Search, ExternalLink, BookOpen, Tag } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Platform {
  id: string;
  name: string;
  icon: string;
  color: string;
  bg: string;
  border: string;
  desc: string;
  buildUrl: (keyword: string) => string;
  tips: string[];
}

const PLATFORMS: Platform[] = [
  {
    id: 'xhs',
    name: '小红书',
    icon: '📕',
    color: 'text-red-600',
    bg: 'bg-red-50',
    border: 'border-red-200',
    desc: '真实租客分享踩坑经验、房东联系方式、实景照片',
    buildUrl: (kw) =>
      `https://www.xiaohongshu.com/search_result?keyword=${encodeURIComponent(kw)}&source=web_search_result_notes`,
    tips: [
      '搜索「城市+小区名+转租」找真实房源',
      '帖子里常有房东电话，可绕开中介直租',
      '搜「城市+租房避坑」了解真实情况',
    ],
  },
  {
    id: 'xianyu',
    name: '闲鱼',
    icon: '🐟',
    color: 'text-orange-600',
    bg: 'bg-orange-50',
    border: 'border-orange-200',
    desc: '个人转租/直租房源，价格透明，可议价',
    buildUrl: (kw) =>
      `https://www.goofish.com/search?q=${encodeURIComponent(kw)}&catId=50017494`,
    tips: [
      '搜索「城市+区域+合租/整租」找真实源',
      '转租房源通常可短租，押金更灵活',
      '注意核实房东身份证和租约再付款',
    ],
  },
];

// 关键词模板
const KW_TEMPLATES = [
  '{city}租房 直租',
  '{city}{district}整租',
  '{city}{district}合租',
  '{city}转租 押一付一',
  '{community}出租',
];

interface SocialMediaListingsProps {
  /** 从主搜索自动填入的城市/地区 */
  defaultCity?: string;
  defaultDistrict?: string;
  defaultCommunity?: string;
}

export default function SocialMediaListings({
  defaultCity = '',
  defaultDistrict = '',
  defaultCommunity = '',
}: SocialMediaListingsProps) {
  const [keyword, setKeyword] = useState('');
  const [activePlatform, setActivePlatform] = useState<string | null>(null);

  // 渲染关键词模板（替换占位符）
  function renderTemplate(tpl: string): string {
    return tpl
      .replace('{city}', defaultCity || '城市')
      .replace('{district}', defaultDistrict || '区域')
      .replace('{community}', defaultCommunity || '小区名')
      .trim();
  }

  function openSearch(platform: Platform, kw: string) {
    const trimmed = kw.trim();
    if (!trimmed) return;
    window.open(platform.buildUrl(trimmed), '_blank', 'noopener,noreferrer');
  }

  const effectiveKeyword = keyword.trim() || `${defaultCity}${defaultDistrict} 租房`.trim();

  return (
    <div className="rounded-2xl border border-stone-200 bg-white shadow-sm">
      {/* 标题 */}
      <div className="flex items-center gap-2 rounded-t-2xl bg-gradient-to-r from-rose-500 to-orange-500 px-4 py-3 text-white">
        <BookOpen className="h-5 w-5 shrink-0" />
        <div>
          <div className="text-sm font-bold">小红书 &amp; 闲鱼 租房帖</div>
          <div className="text-xs text-rose-100">真实房东直租 · 转租 · 避坑经验</div>
        </div>
      </div>

      <div className="p-4 space-y-4">
        {/* 搜索框 */}
        <div className="flex gap-2">
          <input
            type="text"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && activePlatform) {
                const p = PLATFORMS.find((p) => p.id === activePlatform);
                if (p) openSearch(p, effectiveKeyword);
              }
            }}
            placeholder={effectiveKeyword || '输入搜索关键词，如：广州天河 整租'}
            className="flex-1 rounded-xl border border-stone-200 bg-stone-50 px-3 py-2 text-sm outline-none focus:border-rose-400 focus:ring-1 focus:ring-rose-200"
          />
        </div>

        {/* 关键词模板 */}
        {(defaultCity || defaultDistrict || defaultCommunity) && (
          <div>
            <div className="mb-1.5 flex items-center gap-1 text-xs text-stone-500">
              <Tag className="h-3.5 w-3.5" />
              根据你的搜索地点，推荐关键词：
            </div>
            <div className="flex flex-wrap gap-1.5">
              {KW_TEMPLATES.map((tpl) => {
                const rendered = renderTemplate(tpl);
                if (rendered.includes('城市') && !defaultCity) return null;
                return (
                  <button
                    key={tpl}
                    onClick={() => setKeyword(rendered)}
                    className={cn(
                      'rounded-full border px-2.5 py-1 text-xs transition',
                      keyword === rendered
                        ? 'border-rose-400 bg-rose-50 text-rose-700 font-medium'
                        : 'border-stone-200 bg-white text-stone-500 hover:border-rose-300 hover:text-rose-600',
                    )}
                  >
                    {rendered}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* 平台卡片（上下排列，避免右侧栏过拥挤）*/}
        <div className="flex flex-col gap-3">
          {PLATFORMS.map((platform) => (
            <div
              key={platform.id}
              className={cn(
                'rounded-xl border p-3 transition cursor-pointer',
                platform.border,
                platform.bg,
                activePlatform === platform.id ? 'ring-2 ring-offset-1 ring-rose-300' : '',
              )}
              onClick={() => setActivePlatform(platform.id)}
            >
              {/* 平台标题 */}
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-1.5">
                  <span className="text-base">{platform.icon}</span>
                  <span className={cn('text-sm font-bold', platform.color)}>{platform.name}</span>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    openSearch(platform, effectiveKeyword);
                  }}
                  className={cn(
                    'flex items-center gap-1 rounded-lg border px-2.5 py-1 text-xs font-medium transition',
                    platform.border,
                    platform.color,
                    'bg-white hover:opacity-80 active:scale-95',
                  )}
                >
                  <Search className="h-3 w-3" />
                  搜索
                  <ExternalLink className="h-3 w-3" />
                </button>
              </div>

              {/* 描述 */}
              <div className="text-xs text-stone-600 mb-2">{platform.desc}</div>

              {/* 使用技巧 */}
              <div className="space-y-1">
                {platform.tips.map((tip, i) => (
                  <div key={i} className="flex gap-1.5 text-xs text-stone-500">
                    <span className={cn('shrink-0 font-bold', platform.color)}>·</span>
                    {tip}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* 免责说明 */}
        <div className="rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-[11px] text-stone-400">
          ⚠️ 社交媒体房源未经平台核验，交易前请核实房东证件与产权，谨防诈骗。付款前务必签订正式租房合同。
        </div>
      </div>
    </div>
  );
}
