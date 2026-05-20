'use client';

/**
 * Tooltip 组件 (v3) — fixed定位防越界 + 防闪屏
 *
 * 防闪屏方案：
 *   - hide 用 setTimeout 延迟 80ms
 *   - tooltip 本身可悬停（pointer-events-auto），悬停时取消 hide timer
 *   - 这样鼠标从触发元素滑向 tooltip 时不会闪
 */

import { ReactNode, useRef, useState, useCallback } from 'react';
import { cn } from '@/lib/utils';

interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
  position?: 'top' | 'bottom';
  width?: string;
  className?: string;
}

export default function Tooltip({
  content,
  children,
  position = 'top',
  width = 'w-64',
  className,
}: TooltipProps) {
  const [visible, setVisible] = useState(false);
  const [tooltipStyle, setTooltipStyle] = useState<React.CSSProperties>({});
  const triggerRef = useRef<HTMLSpanElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearHide = useCallback(() => {
    if (hideTimer.current) {
      clearTimeout(hideTimer.current);
      hideTimer.current = null;
    }
  }, []);

  const scheduleHide = useCallback(() => {
    hideTimer.current = setTimeout(() => setVisible(false), 80);
  }, []);

  const show = useCallback(() => {
    clearHide();
    setVisible(true);
    // 等 DOM 更新后再测量位置
    requestAnimationFrame(() => {
      if (!triggerRef.current || !tooltipRef.current) return;
      const tr = triggerRef.current.getBoundingClientRect();
      const tt = tooltipRef.current.getBoundingClientRect();
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const MARGIN = 10;

      // 垂直方向
      let top: number;
      if (position === 'top') {
        top = tr.top - tt.height - 6;
        if (top < MARGIN) top = tr.bottom + 6;
      } else {
        top = tr.bottom + 6;
        if (top + tt.height > vh - MARGIN) top = tr.top - tt.height - 6;
      }

      // 水平居中后夹紧
      let left = tr.left + tr.width / 2 - tt.width / 2;
      if (left < MARGIN) left = MARGIN;
      if (left + tt.width > vw - MARGIN) left = vw - tt.width - MARGIN;

      setTooltipStyle({ top, left });
    });
  }, [position, clearHide]);

  return (
    <span
      ref={triggerRef}
      className={cn('relative inline-flex', className)}
      onMouseEnter={show}
      onMouseLeave={scheduleHide}
      onFocus={show}
      onBlur={scheduleHide}
    >
      {children}

      {visible && (
        <div
          ref={tooltipRef}
          style={{ position: 'fixed', zIndex: 9999, ...tooltipStyle }}
          className={cn(
            'rounded-lg bg-stone-800 px-3 py-2 text-xs leading-relaxed text-white shadow-xl',
            width,
          )}
          onMouseEnter={clearHide}
          onMouseLeave={scheduleHide}
        >
          {content}
        </div>
      )}
    </span>
  );
}

/** 带问号图标的帮助按钮 */
export function HelpTip({
  content,
  position = 'top',
  width = 'w-64',
}: {
  content: ReactNode;
  position?: 'top' | 'bottom';
  width?: string;
}) {
  return (
    <Tooltip content={content} position={position} width={width}>
      <span className="ml-1 inline-flex h-4 w-4 cursor-help items-center justify-center rounded-full bg-stone-200 text-[10px] font-bold text-stone-500 hover:bg-amber-200 hover:text-amber-700">
        ?
      </span>
    </Tooltip>
  );
}
