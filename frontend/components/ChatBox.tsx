'use client';

import { useEffect, useRef, useState } from 'react';
import { Send, Sparkles, Search } from 'lucide-react';
import { cn } from '@/lib/utils';
import { ApiError, postChat } from '@/lib/api';
import type { ChatMessage, ParsedRequirement } from '@/lib/types';

interface ChatBoxProps {
  onRequirementReady: (req: ParsedRequirement) => void;
  onSearch: (req: ParsedRequirement) => void;
  isSearching: boolean;
  initialQuery?: string;  // Landing Page 传入的初始查询
  onInitialQueryConsumed?: () => void; // 消费后通知父组件清空
}

const SAMPLE_QUERY =
  '我想找通勤广州番禺南村万博 20 分钟以内的整租一居室或者单间，不要城中村不要合租，纯房租 2000 以内，实际全部房租包含其他费用 2700 以内的房子';

export default function ChatBox({ onRequirementReady, onSearch, isSearching, initialQuery, onInitialQueryConsumed }: ChatBoxProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: 'assistant',
      content:
        '你好！我是「牛马归栏」AI 租房助理 🐂\n\n用一句话告诉我你的租房需求即可，比如：\n通勤目的地、最大通勤时长、户型偏好、预算上限。\n\n我会帮你解析需求、跨平台聚合房源、计算真实月支出和多维通勤时长。',
    },
  ]);
  const [input, setInput] = useState('');
  const [requirement, setRequirement] = useState<ParsedRequirement | null>(null);
  const [isReady, setIsReady] = useState(false);
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  // 防止 StrictMode 双重触发：用 ref 记录已消费的 query
  const consumedQueryRef = useRef<string>('');

  // Landing Page 传入初始 query，自动发送（只消费一次）
  useEffect(() => {
    if (initialQuery && initialQuery !== consumedQueryRef.current) {
      consumedQueryRef.current = initialQuery;
      onInitialQueryConsumed?.();
      // 用 setTimeout 确保组件已完成渲染后再发送
      setTimeout(() => handleSend(initialQuery), 0);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuery]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  async function handleSend(text?: string) {
    const content = (text ?? input).trim();
    if (!content || loading) return;
    setInput('');

    const newMessages: ChatMessage[] = [...messages, { role: 'user', content }];
    setMessages(newMessages);
    setLoading(true);

    try {
      const res = await postChat(newMessages, requirement);
      setMessages((prev) => [...prev, { role: 'assistant', content: res.reply }]);
      if (res.requirement) {
        setRequirement(res.requirement);
        onRequirementReady(res.requirement);
      }
      setIsReady(res.is_ready);
    } catch (e: any) {
      let msg = e?.message || String(e);
      // ApiError 已经是友好文案，直接用；其他类型加前缀
      if (!(e instanceof ApiError)) {
        msg = `出错：${msg}`;
      }
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `⚠️ ${msg}\n\n你之前输入的内容已保留，可重新发送` },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleSearch() {
    if (requirement) onSearch(requirement);
  }

  return (
    <div className="flex h-full flex-col rounded-2xl border border-stone-200 bg-white/80 shadow-lg backdrop-blur">
      {/* 标题 */}
      <div className="flex items-center justify-between border-b border-stone-200 px-5 py-3">
        <div className="flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-amber-500" />
          <h2 className="text-lg font-semibold">AI 对话</h2>
        </div>
        {requirement && (requirement.destination.city || requirement.destination.landmark) && (
          <button
            onClick={handleSearch}
            disabled={isSearching}
            className={cn(
              'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:opacity-60',
              isReady
                ? 'bg-amber-500 text-white hover:bg-amber-600'
                : 'border border-amber-400 bg-white text-amber-600 hover:bg-amber-50',
            )}
            title={isReady ? '需求完整，立即搜索' : '即使信息不完整，你也可以现在就搜（按当前条件）'}
          >
            <Search className="h-4 w-4" />
            {isSearching ? '搜索中...' : isReady ? '开始搜索' : '直接搜索（按当前条件）'}
          </button>
        )}
      </div>

      {/* 对话区 */}
      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
        {messages.map((m, i) => (
          <MessageBubble key={i} message={m} />
        ))}
        {loading && (
          <div className="flex items-center gap-2 text-sm text-stone-500">
            <div className="h-2 w-2 animate-bounce rounded-full bg-stone-400" />
            <div className="h-2 w-2 animate-bounce rounded-full bg-stone-400 [animation-delay:120ms]" />
            <div className="h-2 w-2 animate-bounce rounded-full bg-stone-400 [animation-delay:240ms]" />
            <span>AI 正在思考...</span>
          </div>
        )}
      </div>

      {/* 快捷示例 */}
      {messages.length <= 1 && !loading && (
        <div className="border-t border-stone-200 px-5 py-2">
          <button
            onClick={() => handleSend(SAMPLE_QUERY)}
            className="text-left text-xs text-stone-500 hover:text-amber-600"
          >
            💡 试试：{SAMPLE_QUERY.slice(0, 40)}...
          </button>
        </div>
      )}

      {/* 输入区 */}
      <div className="border-t border-stone-200 p-3">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="描述你的租房需求...（Enter 发送，Shift+Enter 换行）"
            rows={2}
            className="flex-1 resize-none rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm focus:border-amber-500 focus:outline-none"
          />
          <button
            onClick={() => handleSend()}
            disabled={!input.trim() || loading}
            className="flex items-center justify-center rounded-lg bg-stone-900 px-4 text-white hover:bg-stone-700 disabled:opacity-40"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user';
  return (
    <div className={cn('flex', isUser ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm',
          isUser
            ? 'bg-stone-900 text-white'
            : 'bg-stone-100 text-stone-900',
        )}
      >
        {message.content}
      </div>
    </div>
  );
}
