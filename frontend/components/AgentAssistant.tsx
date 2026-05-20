'use client';

/**
 * Agent 小助手悬浮组件 (v0.9.2)
 *
 * - 图标按钮 + 面板头部均可拖拽移动
 * - 问答回复：纯文本，去除所有 markdown 格式符号（不渲染代码块）
 * - 站内信 Tab：固定问询模块（长短租/押付/中介费）+ 自定义输入框
 * - 面板根据当前位置自动判断向哪个方向展开
 */

import { useState, useRef, useEffect, useCallback } from 'react';
import {
  Bot, X, Send, Loader2, Copy, CheckCircle2,
  ExternalLink, MessageCircle, Plus, Trash2,
} from 'lucide-react';
import { postAgentAsk, postAgentInquiry } from '@/lib/api';
import type { Recommendation } from '@/lib/types';
import { cn } from '@/lib/utils';

// ── 快捷问题 ─────────────────────────────────────────────────────
const QUICK_QUESTIONS = [
  '水电费是怎么计算的？',
  '离线估算和实时精算有什么区别？',
  '押2付3是什么意思？',
  '民用电和商用电有什么区别？',
  '中介费摊销是怎么算的？',
  '怎么看这套房子通勤时间？',
];

// ── 站内信：费用明细选项（全部自主勾选）────────────────────────────
const INQUIRY_ITEMS = [
  '水费单价（民用/商用）',
  '电费单价（民用/商用）',
  '每月燃气大约多少钱',
  '物业费标准',
  '宽带费用',
  '有没有停车位及费用',
  '最短租期是多久',
  '押付方式（押几付几）',
  '是否收取中介费，费用多少',
  '是否接受短租（3-6个月）',
  '是否可以押一付一',
  '家电家具是否齐全',
];

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

interface AgentAssistantProps {
  activeListing?: Recommendation | null;
}

/**
 * 将 AI 返回文本清理为纯文本：
 * - 去掉 ```...``` 代码块（保留内容，去掉围栏）
 * - 去掉行内 `code` 反引号
 * - 去掉 **加粗** / *斜体* 的星号
 * - 保留换行
 */
function stripMarkdown(text: string): string {
  return text
    // 代码块：保留内容，去掉围栏行
    .replace(/```[\w]*\n?([\s\S]*?)```/g, (_m, code: string) => code.trim())
    // 行内代码
    .replace(/`([^`]+)`/g, '$1')
    // 加粗 / 斜体
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/__([^_]+)__/g, '$1')
    .replace(/_([^_]+)_/g, '$1')
    // 标题 # ## ###
    .replace(/^#{1,3}\s+/gm, '')
    .trim();
}

export default function AgentAssistant({ activeListing }: AgentAssistantProps) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<'chat' | 'inquiry'>('chat');
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content:
        '你好！我是牛马归栏小助手 🐂\n\n可以问我水电怎么算、通勤怎么查、租房术语解释等问题。如果你正在看某套房，也可以让我帮你生成询问费用的站内信！',
    },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);

  // 站内信
  const [selectedItems, setSelectedItems] = useState<string[]>([]);
  // 自定义问题列表
  const [customItems, setCustomItems] = useState<string[]>([]);
  const [customInput, setCustomInput] = useState('');
  const [inquiryResult, setInquiryResult] = useState<string>('');
  const [inquiryHint, setInquiryHint] = useState('');
  const [inquiryUrl, setInquiryUrl] = useState('');
  const [generatingInquiry, setGeneratingInquiry] = useState(false);
  const [copied, setCopied] = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const inquiryScrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, open]);

  useEffect(() => {
    if (open && tab === 'chat') setTimeout(() => inputRef.current?.focus(), 100);
  }, [open, tab]);

  useEffect(() => {
    if (tab === 'inquiry' && selectedItems.length === 0) {
      setSelectedItems(INQUIRY_ITEMS.slice(0, 6));
    }
    setInquiryResult('');
    setCopied(false);
  }, [tab]);

  // ── 拖拽（统一逻辑，按钮和面板头部共用）─────────────────────────
  // pos: 面板/按钮左上角距视口的坐标（left, top）
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null); // null = 默认右下角
  const dragging = useRef(false);
  const dragStart = useRef({ mouseX: 0, mouseY: 0, posLeft: 0, posTop: 0 });
  const hasDragged = useRef(false);

  // 初始化默认位置（右侧垂直居中）
  const getDefaultPos = useCallback(() => {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    return { left: vw - 16 - 56, top: Math.round(vh / 2) - 28 }; // 56=按钮尺寸，右边距16px，垂直居中
  }, []);

  const startDrag = useCallback(
    (e: React.MouseEvent, currentLeft: number, currentTop: number) => {
      e.preventDefault();
      e.stopPropagation();
      dragging.current = true;
      hasDragged.current = false;
      dragStart.current = {
        mouseX: e.clientX,
        mouseY: e.clientY,
        posLeft: currentLeft,
        posTop: currentTop,
      };

      const onMove = (ev: MouseEvent) => {
        if (!dragging.current) return;
        const dx = ev.clientX - dragStart.current.mouseX;
        const dy = ev.clientY - dragStart.current.mouseY;
        if (Math.abs(dx) > 3 || Math.abs(dy) > 3) hasDragged.current = true;
        const PANEL_W = open ? 360 : 56;
        const PANEL_H = open ? 600 : 56;
        const newLeft = Math.max(0, Math.min(window.innerWidth - PANEL_W, dragStart.current.posLeft + dx));
        const newTop = Math.max(0, Math.min(window.innerHeight - PANEL_H, dragStart.current.posTop + dy));
        setPos({ left: newLeft, top: newTop });
      };

      const onUp = () => {
        dragging.current = false;
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
      };
      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', onUp);
    },
    [open],
  );

  // 当前位置（px from left/top）
  const currentPos = pos ?? (typeof window !== 'undefined' ? getDefaultPos() : { left: 0, top: 0 });

  // 打开/关闭面板时调整 pos，保证面板在屏幕内
  const handleToggleOpen = useCallback(() => {
    if (hasDragged.current) return;
    setOpen((prev) => {
      const nextOpen = !prev;
      if (nextOpen) {
        // 打开时确保面板在屏幕内
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        const PANEL_W = 360;
        const PANEL_H = 600;
        const base = pos ?? getDefaultPos();
        setPos({
          left: Math.max(0, Math.min(vw - PANEL_W, base.left - (PANEL_W - 56) / 2)),
          top: Math.max(0, Math.min(vh - PANEL_H, base.top - (PANEL_H - 56))),
        });
      }
      return nextOpen;
    });
  }, [pos, getDefaultPos]);

  // ── 发送消息 ─────────────────────────────────────────────────────
  async function sendMessage(text?: string) {
    const q = (text ?? input).trim();
    if (!q || loading) return;
    setInput('');
    setMessages((prev) => [...prev, { role: 'user', content: q }]);
    setLoading(true);

    try {
      const ctx = activeListing
        ? {
            title: activeListing.listing.title,
            community: activeListing.listing.community,
            price_base: activeListing.listing.price_base,
            platform: activeListing.listing.platform,
            url: activeListing.listing.url,
            cost: activeListing.cost
              ? {
                  total: activeListing.cost.total,
                  water: activeListing.cost.water,
                  electricity: activeListing.cost.electricity,
                  gas: activeListing.cost.gas,
                }
              : null,
          }
        : null;

      const res = await postAgentAsk({ question: q, listing_context: ctx });
      // 去掉所有 markdown 格式，纯文本展示
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: stripMarkdown(res.answer) },
      ]);
    } catch (e: any) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `出错了：${e?.message || '请稍后重试'}` },
      ]);
    } finally {
      setLoading(false);
    }
  }

  // ── 生成站内信 ────────────────────────────────────────────────────
  async function generateInquiry() {
    setGeneratingInquiry(true);
    setInquiryResult('');
    setCopied(false);
    try {
      const listing = activeListing?.listing;
      // 合并所有询问项：费用明细勾选 + 自定义
      const allItems = [...selectedItems, ...customItems];
      const res = await postAgentInquiry({
        listing_id: listing?.id ?? 'unknown',
        listing_title: listing?.title ?? '',
        listing_community: listing?.community ?? '',
        listing_url: listing?.url ?? '',
        platform: listing?.platform ?? '',
        items_to_ask: allItems,
        use_ai: true,
      });
      setInquiryResult(res.message);
      setInquiryHint(res.copy_hint);
      setInquiryUrl(res.listing_url);
      setTimeout(() => {
        inquiryScrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
      }, 80);
    } catch (e: any) {
      setInquiryResult(`生成失败：${e?.message || '请稍后重试'}`);
    } finally {
      setGeneratingInquiry(false);
    }
  }

  async function copyToClipboard(text: string) {
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
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  }

  const toggleItem = (item: string) => {
    setSelectedItems((prev) =>
      prev.includes(item) ? prev.filter((i) => i !== item) : [...prev, item],
    );
  };

  // 自定义问题管理
  const addCustomItem = () => {
    const trimmed = customInput.trim();
    if (!trimmed || customItems.includes(trimmed)) return;
    setCustomItems((prev) => [...prev, trimmed]);
    setCustomInput('');
  };

  const removeCustomItem = (item: string) => {
    setCustomItems((prev) => prev.filter((i) => i !== item));
  };

  // 计算本次将询问的总项数
  const totalAskCount = selectedItems.length + customItems.length;

  // ── 渲染 ──────────────────────────────────────────────────────────
  if (!open) {
    // 悬浮按钮（可拖拽）
    return (
      <button
        onMouseDown={(e) => startDrag(e, currentPos.left, currentPos.top)}
        onClick={handleToggleOpen}
        style={{ left: currentPos.left, top: currentPos.top, position: 'fixed' }}
        className="z-50 flex h-14 w-14 cursor-grab items-center justify-center rounded-full bg-gradient-to-br from-amber-500 to-orange-500 text-white shadow-lg transition-shadow hover:shadow-xl active:cursor-grabbing select-none"
        title="AI 小助手（可拖拽移动）"
      >
        <Bot className="h-6 w-6" />
        <span className="absolute -right-0.5 -top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-emerald-500 text-[10px] font-bold">
          AI
        </span>
      </button>
    );
  }

  // 面板
  return (
    <div
      className="fixed z-50 flex flex-col rounded-2xl border border-stone-200 bg-white shadow-2xl"
      style={{
        left: currentPos.left,
        top: currentPos.top,
        width: 360,
        height: Math.min(600, (typeof window !== 'undefined' ? window.innerHeight : 800) - 16),
        maxWidth: 'calc(100vw - 8px)',
      }}
    >
      {/* 头部（可拖拽）*/}
      <div
        onMouseDown={(e) => startDrag(e, currentPos.left, currentPos.top)}
        className="flex cursor-grab items-center gap-2 rounded-t-2xl bg-gradient-to-r from-amber-500 to-orange-500 px-4 py-3 text-white active:cursor-grabbing select-none"
      >
        <Bot className="h-5 w-5 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-bold">牛马归栏小助手</div>
          {activeListing && (
            <div className="truncate text-xs text-orange-100">
              当前：{activeListing.listing.community || activeListing.listing.title?.slice(0, 20)}
            </div>
          )}
        </div>
        <button
          onMouseDown={(e) => e.stopPropagation()}
          onClick={() => setOpen(false)}
          className="rounded-full p-1 hover:bg-white/20"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Tab */}
      <div className="flex shrink-0 border-b border-stone-200">
        <button
          onClick={() => setTab('chat')}
          className={cn(
            'flex-1 py-2 text-xs font-medium transition',
            tab === 'chat'
              ? 'border-b-2 border-amber-500 text-amber-700'
              : 'text-stone-500 hover:text-stone-700',
          )}
        >
          <MessageCircle className="mr-1 inline h-3.5 w-3.5" />
          问答
        </button>
        <button
          onClick={() => setTab('inquiry')}
          className={cn(
            'flex-1 py-2 text-xs font-medium transition',
            tab === 'inquiry'
              ? 'border-b-2 border-amber-500 text-amber-700'
              : 'text-stone-500 hover:text-stone-700',
          )}
        >
          <Send className="mr-1 inline h-3.5 w-3.5" />
          代发站内信
        </button>
      </div>

      {/* ── Chat ─────────────────────────────────────────────────── */}
      {tab === 'chat' && (
        <div className="flex flex-1 flex-col min-h-0 overflow-hidden">
          <div className="flex-1 overflow-y-auto p-3 space-y-3">
            {messages.map((msg, i) => (
              <div
                key={i}
                className={cn('flex gap-2', msg.role === 'user' ? 'flex-row-reverse' : 'flex-row')}
              >
                {msg.role === 'assistant' && (
                  <div className="mt-0.5 h-6 w-6 shrink-0 rounded-full bg-amber-100 flex items-center justify-center">
                    <Bot className="h-3.5 w-3.5 text-amber-600" />
                  </div>
                )}
                <div
                  className={cn(
                    'max-w-[78%] rounded-2xl px-3 py-2 text-xs leading-relaxed',
                    msg.role === 'user'
                      ? 'rounded-tr-sm bg-amber-500 text-white'
                      : 'rounded-tl-sm bg-stone-100 text-stone-800',
                  )}
                >
                  <span className="whitespace-pre-wrap">{msg.content}</span>
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex gap-2">
                <div className="h-6 w-6 shrink-0 rounded-full bg-amber-100 flex items-center justify-center">
                  <Bot className="h-3.5 w-3.5 text-amber-600" />
                </div>
                <div className="rounded-2xl rounded-tl-sm bg-stone-100 px-3 py-2">
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-stone-400" />
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* 快捷问题 */}
          <div className="shrink-0 border-t border-stone-100 px-3 py-2">
            <div className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-none">
              {QUICK_QUESTIONS.map((q) => (
                <button
                  key={q}
                  onClick={() => sendMessage(q)}
                  disabled={loading}
                  className="shrink-0 rounded-full border border-stone-200 bg-stone-50 px-2.5 py-1 text-xs text-stone-600 hover:border-amber-400 hover:bg-amber-50 hover:text-amber-700 transition disabled:opacity-50"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>

          {/* 输入框 */}
          <div className="shrink-0 flex gap-2 border-t border-stone-200 px-3 py-3">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  sendMessage();
                }
              }}
              placeholder="问任何租房问题…"
              className="flex-1 rounded-xl border border-stone-200 bg-stone-50 px-3 py-2 text-xs outline-none focus:border-amber-400 focus:ring-1 focus:ring-amber-200"
            />
            <button
              onClick={() => sendMessage()}
              disabled={!input.trim() || loading}
              className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-500 text-white transition hover:bg-amber-600 disabled:opacity-40"
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
            </button>
          </div>
        </div>
      )}

      {/* ── 站内信 Tab ───────────────────────────────────────────── */}
      {tab === 'inquiry' && (
        <div className="flex flex-1 flex-col min-h-0">
          {/* 顶部说明 */}
          <div className="mx-3 mt-3 shrink-0 rounded-lg bg-blue-50 border border-blue-200 px-3 py-2 text-xs text-blue-800">
            <span className="font-semibold">📋 </span>
            勾选/填写问题 → 生成 →{' '}
            <span className="font-semibold text-emerald-700">复制文案</span> → 去房源页手动发送
            <span className="ml-1 text-blue-400">（不会自动发送）</span>
          </div>

          {/* 中间滚动区 */}
          <div
            ref={inquiryScrollRef}
            className="flex-1 overflow-y-auto px-3 py-3 space-y-3 min-h-0"
          >
            {/* 生成结果 */}
            {inquiryResult && (
              <div className="rounded-xl border-2 border-emerald-400 bg-emerald-50 p-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-xs font-bold text-emerald-800">✅ 文案已生成！</span>
                  <button
                    onClick={() => { setInquiryResult(''); setCopied(false); }}
                    className="text-xs text-stone-400 hover:text-stone-600 underline"
                  >
                    清除
                  </button>
                </div>
                <textarea
                  readOnly
                  value={inquiryResult}
                  className="w-full resize-none rounded-lg border border-emerald-200 bg-white px-3 py-2 text-xs text-stone-800 leading-relaxed focus:outline-none"
                  rows={8}
                  onClick={(e) => (e.target as HTMLTextAreaElement).select()}
                />
                <div className="mt-2 flex items-center gap-2">
                  <button
                    onClick={() => copyToClipboard(inquiryResult)}
                    className={cn(
                      'flex flex-1 items-center justify-center gap-1.5 rounded-lg py-2 text-xs font-bold transition',
                      copied
                        ? 'bg-emerald-200 text-emerald-800'
                        : 'bg-emerald-500 text-white hover:bg-emerald-600 active:scale-95',
                    )}
                  >
                    {copied ? (
                      <><CheckCircle2 className="h-3.5 w-3.5" />已复制！粘贴到平台发送吧</>
                    ) : (
                      <><Copy className="h-3.5 w-3.5" />点击复制文案</>
                    )}
                  </button>
                  {inquiryUrl && (
                    <a
                      href={inquiryUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1 rounded-lg border border-blue-300 bg-white px-3 py-2 text-xs text-blue-600 hover:bg-blue-50"
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                      打开房源
                    </a>
                  )}
                </div>
                {inquiryHint && (
                  <p className="mt-2 rounded bg-white/60 px-2 py-1 text-xs text-emerald-700">
                    💡 {inquiryHint}
                  </p>
                )}
              </div>
            )}

            {/* 当前房源 */}
            {activeListing ? (
              <div className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs">
                <div className="font-semibold text-amber-800">当前房源</div>
                <div className="truncate font-medium text-stone-700">
                  {activeListing.listing.community || activeListing.listing.title}
                </div>
                <div className="mt-0.5 text-stone-400">
                  ¥{activeListing.listing.price_base}/月 · {activeListing.listing.platform}
                </div>
              </div>
            ) : (
              <div className="rounded-lg bg-stone-50 border border-stone-200 px-3 py-2 text-xs text-stone-500">
                💡 打开某套房源的详情后再来这里，可生成针对该房源的专属询问文案
              </div>
            )}

            {/* ── 费用明细勾选项 ───────────────────────────────── */}
            <div>
              <div className="mb-1.5 text-xs font-semibold text-stone-700">费用明细（勾选你想问的）：</div>
              <div className="flex flex-wrap gap-1.5">
                {INQUIRY_ITEMS.map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() => toggleItem(item)}
                    className={cn(
                      'rounded-full border px-2.5 py-1 text-xs transition',
                      selectedItems.includes(item)
                        ? 'border-amber-400 bg-amber-50 text-amber-700 font-medium'
                        : 'border-stone-200 bg-white text-stone-500 hover:border-stone-300',
                    )}
                  >
                    {selectedItems.includes(item) ? '✓ ' : ''}
                    {item}
                  </button>
                ))}
              </div>
            </div>

            {/* ── 自定义问题 ────────────────────────────────────── */}
            <div>
              <div className="mb-1.5 text-xs font-semibold text-stone-700">自定义问题：</div>
              {customItems.length > 0 && (
                <div className="mb-2 flex flex-wrap gap-1.5">
                  {customItems.map((item) => (
                    <span
                      key={item}
                      className="flex items-center gap-1 rounded-full border border-purple-200 bg-purple-50 px-2.5 py-0.5 text-xs text-purple-700"
                    >
                      {item}
                      <button
                        onClick={() => removeCustomItem(item)}
                        className="ml-0.5 text-purple-400 hover:text-purple-700"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </span>
                  ))}
                </div>
              )}
              <div className="flex gap-1.5">
                <input
                  type="text"
                  value={customInput}
                  onChange={(e) => setCustomInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') { e.preventDefault(); addCustomItem(); }
                  }}
                  placeholder="输入自定义问题，回车添加…"
                  maxLength={60}
                  className="flex-1 rounded-lg border border-stone-200 bg-stone-50 px-2.5 py-1.5 text-xs outline-none focus:border-purple-400 focus:ring-1 focus:ring-purple-200"
                />
                <button
                  onClick={addCustomItem}
                  disabled={!customInput.trim()}
                  className="flex h-8 w-8 items-center justify-center rounded-lg bg-purple-500 text-white hover:bg-purple-600 disabled:opacity-40 transition"
                >
                  <Plus className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>

          {/* 底部生成按钮 */}
          <div className="shrink-0 border-t border-stone-100 bg-white px-3 py-3">
            {totalAskCount > 0 && (
              <div className="mb-2 text-center text-xs text-stone-400">
                共 {totalAskCount} 个问题将包含在站内信中
              </div>
            )}
            <button
              onClick={generateInquiry}
              disabled={generatingInquiry || totalAskCount === 0}
              className="w-full flex items-center justify-center gap-1.5 rounded-xl bg-amber-500 py-2.5 text-sm font-semibold text-white transition hover:bg-amber-600 disabled:opacity-50 active:scale-95"
            >
              {generatingInquiry ? (
                <><Loader2 className="h-4 w-4 animate-spin" />AI 生成中，约 5 秒…</>
              ) : (
                <><Bot className="h-4 w-4" />{inquiryResult ? '重新生成' : 'AI 生成询问站内信'}</>
              )}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
