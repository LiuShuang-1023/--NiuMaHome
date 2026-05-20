'use client';

import { Sparkles } from 'lucide-react';

export default function TopBar() {
  return (
    <header className="sticky top-0 z-40 border-b border-stone-200 bg-white/80 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 md:px-8">
        {/* Logo + 名字 */}
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-amber-400 to-orange-500 text-xl shadow-sm">
            🐂
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold tracking-tight text-stone-900">牛马归栏</h1>
              <span className="text-xs text-stone-500">NiuMaHome</span>
              <span className="hidden rounded-full bg-purple-100 px-1.5 py-0.5 text-[10px] font-semibold text-purple-700 sm:inline">
                v0.9.2
              </span>
            </div>
            <p className="text-xs text-stone-500">打工人，回家路上少操点心</p>
          </div>
        </div>

        {/* 右侧标语 */}
        <div className="hidden items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs text-amber-700 md:flex">
          <Sparkles className="h-3 w-3" />
          AI 租房助理
        </div>
      </div>
    </header>
  );
}
