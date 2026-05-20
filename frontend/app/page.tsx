'use client';

import React, { useEffect, useRef, useState } from 'react';
import ChatBox from '@/components/ChatBox';
import RequirementPanel from '@/components/RequirementPanel';
import ListingCard from '@/components/ListingCard';
import ListingDetailModal from '@/components/ListingDetailModal';
import TopBar from '@/components/TopBar';
import OnboardingGuide from '@/components/OnboardingGuide';
import AgentAssistant from '@/components/AgentAssistant';
import FavoritesPanel from '@/components/FavoritesPanel';
import LandingPage, { saveSearchHistory } from '@/components/LandingPage';
import SubsidyAnalyzer from '@/components/SubsidyAnalyzer';
import PublicHousingPanel from '@/components/PublicHousingPanel';
import SocialMediaListings from '@/components/SocialMediaListings';
import { HelpTip } from '@/components/Tooltip';
import { useFavorites } from '@/lib/useFavorites';
import {
  ApiError,
  deleteCurrentSession,
  getSessionId,
  postPreciseBatch,
  postSort,
  postSubsidyFilter,
  preciseBatchStream,
  resetSessionId,
  startSearch,
  pollSearchStatus,
  type SubsidyAnalyzeResponse,
} from '@/lib/api';
import type {
  ParsedRequirement,
  PlatformFilter,
  Recommendation,
  SearchResponse,
  SortMode,
} from '@/lib/types';
import {
  Loader2,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Clock,
  AlertTriangle,
  WifiOff,
  Zap,
  Trash2,
  Info,
} from 'lucide-react';
import { cn } from '@/lib/utils';

type ErrorKind = 'timeout' | 'network' | 'http' | 'unknown' | '';

// 精算失败原因 → 用户友好说明
function explainPreciseFail(reason: string): string {
  if (!reason) return '未知原因';
  if (reason.includes('地址') || reason.includes('位置') || reason.includes('community')) {
    return '房源缺少小区名/地址，无法定位';
  }
  if (reason.includes('geocode') || reason.includes('坐标')) {
    return '该小区名无法被地图识别（过于特殊或含特殊字符）';
  }
  if (reason.includes('配额') || reason.includes('quota')) {
    return '高德/腾讯/百度 API 配额今日已耗尽，明日 0 点恢复';
  }
  if (reason.includes('Key') || reason.includes('无效')) {
    return 'API Key 无效，请检查 .env.local 配置';
  }
  if (reason.includes('QPS') || reason.includes('限流')) {
    return '请求过于频繁，稍后再试';
  }
  return reason;
}

export default function Home() {
  const [requirement, setRequirement] = useState<ParsedRequirement | null>(null);
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false); // Landing → 搜索界面
  const [pendingLandingQuery, setPendingLandingQuery] = useState<string>('');
  const [searchElapsed, setSearchElapsed] = useState(0);
  const [batchPrecising, setBatchPrecising] = useState(false);
  const [batchProgress, setBatchProgress] = useState<{ current: number; total: number; label: string } | null>(null);
  const [batchMsg, setBatchMsg] = useState('');
  const [batchFailDetails, setBatchFailDetails] = useState<string[]>([]);
  const [error, setError] = useState<string>('');
  const [errorKind, setErrorKind] = useState<ErrorKind>('');
  const lastSearchReqRef = useRef<{
    type: 'search' | 'sort';
    req?: ParsedRequirement;
    opts: { platform: PlatformFilter; sort: SortMode; page: number };
  } | null>(null);
  const [selectedRec, setSelectedRec] = useState<Recommendation | null>(null);

  const { favorites, isFavorited, toggle: toggleFavorite, remove: removeFavorite, clear: clearFavorites } = useFavorites();

  // 控制
  const [platform, setPlatform] = useState<PlatformFilter>('all');
  const [sortMode, setSortMode] = useState<SortMode>('综合');
  const [page, setPage] = useState(1);

  // 房补政策筛选
  const [subsidyResult, setSubsidyResult] = useState<SubsidyAnalyzeResponse | null>(null);
  const [subsidyActive, setSubsidyActive] = useState(false);
  const [subsidyAllowedIds, setSubsidyAllowedIds] = useState<Set<string> | null>(null); // 距离筛选白名单

  // 初始化时确保 session_id 存在
  useEffect(() => {
    getSessionId();
  }, []);

  // 搜索期间计时器
  const elapsedTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (searching) {
      setSearchElapsed(0);
      const start = Date.now();
      elapsedTimerRef.current = setInterval(() => {
        setSearchElapsed(Math.floor((Date.now() - start) / 1000));
      }, 1000);
    } else if (elapsedTimerRef.current) {
      clearInterval(elapsedTimerRef.current);
      elapsedTimerRef.current = null;
    }
    return () => {
      if (elapsedTimerRef.current) clearInterval(elapsedTimerRef.current);
    };
  }, [searching]);

  // ============================================================
  // 搜索（异步任务模式：立即提交 → 每2秒轮询 → 拿到结果）
  // ============================================================
  async function runSearch(req: ParsedRequirement | null, opts: {
    platform?: PlatformFilter;
    sort?: SortMode;
    page?: number;
  } = {}) {
    if (!req) return;
    const p = opts.platform ?? platform;
    const s = opts.sort ?? sortMode;
    const pg = opts.page ?? 1;

    setSearching(true);
    setError('');
    setErrorKind('');
    setBatchMsg('');
    setBatchFailDetails([]);
    setResponse(null);
    lastSearchReqRef.current = { type: 'search', req, opts: { platform: p, sort: s, page: pg } };

    try {
      // Step1: 提交任务（<1s 返回 task_id）
      const { task_id } = await startSearch(req, {
        platform: p, sort_mode: s, page: pg, page_size: 10,
      });

      // Step2: 轮询，每2秒一次，最多等5分钟（150次）
      let attempts = 0;
      while (attempts < 150) {
        await new Promise((r) => setTimeout(r, 2000));
        attempts++;

        let status;
        try {
          status = await pollSearchStatus(task_id);
        } catch (pollErr: any) {
          // 轮询本身网络断了，继续重试
          if (pollErr instanceof ApiError && pollErr.kind === 'network') continue;
          throw pollErr;
        }

        if (status.status === 'done' && status.result) {
          setResponse(status.result);
          setPage(status.result.current_page);
          return;
        }
        if (status.status === 'error') {
          throw new ApiError('http', status.error || '搜索任务失败', 500);
        }
        // pending / running → 继续等
      }
      // 超出最大等待次数（5分钟）
      throw new ApiError('timeout', '搜索超时（已等待5分钟），后端处理异常，请重试。');
    } catch (e: any) {
      handleApiError(e);
    } finally {
      setSearching(false);
    }
  }

  // ============================================================
  // 仅排序（毫秒响应）
  // ============================================================
  async function runSort(opts: {
    platform?: PlatformFilter;
    sort?: SortMode;
    page?: number;
  } = {}) {
    const p = opts.platform ?? platform;
    const s = opts.sort ?? sortMode;
    const pg = opts.page ?? 1;

    setSearching(true);
    setError('');
    setErrorKind('');
    lastSearchReqRef.current = { type: 'sort', opts: { platform: p, sort: s, page: pg } };

    try {
      const res = await postSort({
        platform: p,
        sort_mode: s,
        page: pg,
        page_size: 10,
      });
      setResponse(res);
      setPage(res.current_page);
    } catch (e: any) {
      // 如果 session 过期，回退到完整搜索
      if (e instanceof ApiError && e.status === 404 && requirement) {
        console.warn('[runSort] session 过期，重新搜索');
        await runSearch(requirement, opts);
        return;
      }
      handleApiError(e);
    } finally {
      setSearching(false);
    }
  }

  // ============================================================
  // 超时后"刷新结果"：不重跑后端，直接尝试读取已有 session
  // ============================================================
  async function refreshAfterTimeout() {
    setError('');
    setErrorKind('');
    const last = lastSearchReqRef.current;
    if (!last) return;

    // 超时时后端大概率还在跑（或已经跑完但前端超时了）。
    // 直接用 /sort 接口读取当前 session 里已有的结果（如后端跑完则有数据，若还在跑则 session 不存在返回 404）
    setSearching(true);
    try {
      const res = await postSort({
        platform: last.opts.platform,
        sort_mode: last.opts.sort,
        page: last.opts.page,
        page_size: 10,
      });
      setResponse(res);
      setPage(res.current_page);
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 404) {
        // 后端还没跑完/已失败，提示用户等等
        setError('后端仍在处理中，请再等 10-20 秒后点「刷新结果」');
        setErrorKind('timeout');
      } else {
        handleApiError(e);
      }
    } finally {
      setSearching(false);
    }
  }

  function handleApiError(e: any) {
    if (e instanceof ApiError) {
      setError(e.message);
      setErrorKind(e.kind);
    } else {
      setError(e?.message || '请求失败');
      setErrorKind('unknown');
    }
  }

  // ============================================================
  // 用户操作
  // ============================================================
  async function onSearchTrigger(req: ParsedRequirement) {
    setPlatform('all');
    setSortMode('综合');
    setPage(1);
    setBatchMsg('');
    setBatchFailDetails([]);
    setHasSearched(true); // 切换到搜索界面
    // 保存搜索历史（供 Landing 页推荐使用）
    if (req.destination?.city || req.destination?.landmark) {
      const historyLabel = [
        req.destination.city,
        req.destination.district,
        req.destination.landmark ? `通勤${req.destination.landmark}` : '',
        req.price?.base_rent_max ? `${req.price.base_rent_max}以内` : '',
      ].filter(Boolean).join(' ');
      if (historyLabel) saveSearchHistory(historyLabel);
    }
    // 用户主动重搜：重置 session_id，旧 session 等 TTL 自动清
    resetSessionId();
    runSearch(req, { platform: 'all', sort: '综合', page: 1 });
  }

  /** 应用房补筛选条件 */
  async function applySubsidyFilter(params: {
    maxMinutes: number;
    modes: string[];
    subsidyResult: SubsidyAnalyzeResponse;
  }) {
    setSubsidyResult(params.subsidyResult);
    setSubsidyActive(true);

    // 若有距离限制，先从后端获取符合条件的 listing_id 白名单
    if (params.subsidyResult.has_distance_limit && params.subsidyResult.distance_km) {
      try {
        const filterRes = await postSubsidyFilter(params.subsidyResult.distance_km);
        setSubsidyAllowedIds(new Set(filterRes.matched_listing_ids));
      } catch (e) {
        console.warn('[subsidy] 距离筛选失败，忽略距离限制:', e);
        setSubsidyAllowedIds(null);
      }
    } else {
      setSubsidyAllowedIds(null);
    }

    // 如果已有搜索结果，用新的通勤限制重新搜索
    if (requirement) {
      const updatedReq: ParsedRequirement = {
        ...requirement,
        commute: {
          ...requirement.commute,
          max_minutes: params.maxMinutes,
          // 合并已有模式和房补要求的模式（取并集）
          modes: Array.from(new Set([
            ...(requirement.commute?.modes || ['transit', 'riding', 'walking']),
            ...params.modes,
          ])) as any,
        },
      };
      resetSessionId();
      runSearch(updatedReq, { platform: 'all', sort: sortMode, page: 1 });
    }
  }

  /** 清除房补筛选 */
  function clearSubsidyFilter() {
    setSubsidyResult(null);
    setSubsidyActive(false);
    setSubsidyAllowedIds(null);
  }

  /** Landing Page 直接输入文字搜索：先把文字发给 ChatBox 的处理逻辑 */
  function onLandingSearch(query: string) {
    setHasSearched(true);
    // 用 setTimeout 让状态先更新（ChatBox 渲染后），再自动注入查询
    setPendingLandingQuery(query);
  }

  function changePlatform(p: PlatformFilter) {
    setPlatform(p);
    setPage(1);
    runSort({ platform: p, sort: sortMode, page: 1 });
  }

  function changeSort(s: SortMode) {
    setSortMode(s);
    setPage(1);
    runSort({ platform, sort: s, page: 1 });
  }

  function changePage(newPage: number) {
    setPage(newPage);
    runSort({ platform, sort: sortMode, page: newPage });
  }

  /** 批量精算（SSE 流式进度，v0.5.2）*/
  async function runBatchPrecise() {
    if (batchPrecising) return;
    setBatchPrecising(true);
    setBatchMsg('');
    setBatchProgress(null);
    setBatchFailDetails([]);
    setError('');

    preciseBatchStream(
      { platform, sort_mode: sortMode, page, page_size: 10, max_count: 10 },
      // onProgress
      (current, total, label, _success, _fail) => {
        setBatchProgress({ current, total, label });
      },
      // onDone
      (res) => {
        setBatchPrecising(false);
        setBatchProgress(null);
        setResponse(res);
        setPage(res.current_page);

        const failCount = res.round_fail ?? 0;
        const successCount = res.round_success ?? 0;
        const attempted = res.round_attempted ?? 0;
        let msg = `本轮尝试 ${attempted} 条 · 成功 ${successCount}`;
        if (failCount > 0) msg += ` · 失败 ${failCount}`;
        setBatchMsg(msg);

        if (failCount > 0) {
          const details: string[] = [];
          for (const rec of res.recommendations) {
            const mf = rec.listing.missing_fields || [];
            const isOffline = mf.some((f: string) => f.includes('离线估算'));
            if (isOffline) {
              const addr = rec.listing.community || rec.listing.title?.slice(0, 20) || rec.listing.id;
              details.push(`「${addr}」仍为估算（小区名无法被地图精确识别）`);
            }
          }
          setBatchFailDetails(details.length > 0 ? details.slice(0, 5) : [
            '部分房源小区名过于特殊（含品牌前缀/地名不标准），高德无法匹配到精确坐标。',
            '这类房源的离线估算误差约 ±25%，如需精确通勤可点卡片上的「⚡查询实时」单独重试。',
          ]);
        }

        // 同步更新 Modal 中的 selectedRec
        setSelectedRec(prev => {
          if (!prev) return null;
          const updated = res.recommendations.find(r => r.listing.id === prev.listing.id);
          return updated ?? prev;
        });
      },
      // onError
      (msg) => {
        setBatchPrecising(false);
        setBatchProgress(null);
        handleApiError(new ApiError('http', `批量精算失败：${msg}`, 500));
      },
    );
  }

  /** 单条精算成功后刷新 */
  async function refreshAfterPrecise() {
    const p = platform;
    const s = sortMode;
    const pg = page;

    setSearching(true);
    setError('');
    setErrorKind('');

    try {
      const res = await postSort({ platform: p, sort_mode: s, page: pg, page_size: 10 });
      setResponse(res);
      setPage(res.current_page);
      // 如果 Modal 正在展示，用新数据更新 selectedRec（修复精算后Modal通勤不刷新的Bug）
      setSelectedRec(prev => {
        if (!prev) return null;
        // 先在当前页找，找不到则在全部平台里找（精算后可能换了平台）
        const updated = res.recommendations.find(r => r.listing.id === prev.listing.id);
        return updated ?? prev;
      });
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 404 && requirement) {
        await runSearch(requirement, {});
        return;
      }
      handleApiError(e);
    } finally {
      setSearching(false);
    }
  }

  /** 用户主动清空当前会话 */
  async function clearSession() {
    if (!confirm('确定清空当前搜索结果？需求条件不会丢失，但需要重新抓取房源。')) return;
    try {
      await deleteCurrentSession();
    } catch (e) {
      console.warn('清空会话失败:', e);
    }
    resetSessionId();
    setResponse(null);
    setBatchMsg('');
    setBatchFailDetails([]);
    setError('');
  }

  // 是否展示精算栏（有通勤数据 + 有 response，或者精算正在进行中）
  const showStickyPanel = !!(
    (response?.has_commute && response?.commute_source_stats) ||
    batchPrecising
  );

  return (
    <>
      <TopBar />

      {/* ── Landing Page（搜索前）── */}
      {!hasSearched && (
        <LandingPage
          onSearch={onLandingSearch}
          isSearching={searching}
          favorites={favorites}
        />
      )}

      {/* ── 搜索结果界面（搜索后）── */}
      {hasSearched && (
      <main className="px-3 py-4 md:px-6">
        <div className="mx-auto grid max-w-[1600px] gap-4 md:grid-cols-[300px_1fr_280px]">

          {/* ── 左列：AI 对话 + 需求面板 + 房补 ── */}
          <div className="flex flex-col gap-3 md:h-[calc(100vh-100px)] md:overflow-y-auto md:pr-1 md:sticky md:top-[72px] md:self-start">
            <div className="flex-1 min-h-0 md:min-h-[280px]">
              <ChatBox
                onRequirementReady={setRequirement}
                onSearch={onSearchTrigger}
                isSearching={searching}
                initialQuery={pendingLandingQuery}
                onInitialQueryConsumed={() => setPendingLandingQuery('')}
              />
            </div>
            <div className="flex-shrink-0">
              <RequirementPanel req={requirement} />
            </div>
            <div className="flex-shrink-0">
              <SubsidyAnalyzer
                currentMaxMinutes={requirement?.commute?.max_minutes}
                onApply={applySubsidyFilter}
                onClear={clearSubsidyFilter}
                isActive={subsidyActive}
              />
            </div>
            {subsidyActive && subsidyResult && (
              <div className="flex-shrink-0 rounded-xl border-2 border-amber-300 bg-amber-50 px-4 py-2.5 text-xs text-amber-900">
                <span className="font-semibold">🏢 房补筛选生效中：</span>
                {subsidyResult.summary}
              </div>
            )}
          </div>

          {/* ── 中列：推荐房源（主要区域）── */}
          <div className="flex flex-col min-h-0 md:h-[calc(100vh-100px)]">

            {/* 平台 Tab + 排序 — sticky 固定在中列顶部，不随内容滚动 */}
            {response && (
              <div className="shrink-0 sticky top-[64px] z-20 bg-white/95 backdrop-blur-sm border-b border-stone-200 px-2 pt-1 pb-2 mb-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap gap-1">
                    <PlatformTab
                      label="综合"
                      count={response.counts_by_platform?.all}
                      active={platform === 'all'}
                      onClick={() => changePlatform('all')}
                      disabled={searching}
                    />
                    <PlatformTab
                      label="🏠 链家"
                      count={response.counts_by_platform?.lianjia}
                      active={platform === 'lianjia'}
                      onClick={() => changePlatform('lianjia')}
                      disabled={searching}
                    />
                    <PlatformTab
                      label="🐚 贝壳"
                      count={response.counts_by_platform?.beike}
                      active={platform === 'beike'}
                      onClick={() => changePlatform('beike')}
                      disabled={searching}
                    />
                    <PlatformTab
                      label="🏘️ 安居客"
                      count={response.counts_by_platform?.anjuke}
                      active={platform === 'anjuke'}
                      onClick={() => changePlatform('anjuke')}
                      disabled={searching}
                    />
                    <PlatformTab
                      label={
                        <span className="flex items-center gap-1">
                          🏡 58同城
                          {(response.counts_by_platform?.wuba ?? 0) === 0 && (
                            <HelpTip content="58同城需配置 WUBA_COOKIE 才能抓取（JS渲染+反爬），在 .env.local 填入浏览器 Cookie 后重启后端" />
                          )}
                        </span>
                      }
                      count={response.counts_by_platform?.wuba}
                      active={platform === 'wuba'}
                      onClick={() => changePlatform('wuba')}
                      disabled={searching}
                    />
                  </div>

                  <div className="flex items-center gap-1 text-xs">
                    <span className="text-stone-500">排序：</span>
                    <HelpTip
                      position="bottom"
                      width="w-64"
                      content={
                        <span>
                          <b>综合</b>：成本+通勤+偏好综合打分<br />
                          <b>价格</b>：真实月支出从低到高<br />
                          <b>通勤</b>：最快通勤时长从短到长<br />
                          <b>面积</b>：人均居住面积从大到小
                        </span>
                      }
                    />
                    {(['综合', '价格', '通勤', '面积'] as SortMode[]).map((s) => (
                      <button
                        key={s}
                        onClick={() => changeSort(s)}
                        disabled={searching}
                        className={cn(
                          'rounded px-2 py-1 transition disabled:cursor-wait disabled:opacity-60',
                          sortMode === s
                            ? 'bg-stone-900 text-white'
                            : 'text-stone-600 hover:bg-stone-100',
                        )}
                      >
                        {s}
                        {searching && sortMode === s && (
                          <Loader2 className="ml-1 inline h-3 w-3 animate-spin" />
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* 精算统计栏（固定在滚动区外） */}
            {showStickyPanel && (
              <div className="shrink-0 mb-2">
                <StickyCommuteBar
                  geoStats={response!.geo_filter_stats}
                  sourceStats={response!.commute_source_stats}
                  radiusKm={response!.radius_km || 0}
                  batchPrecising={batchPrecising}
                  batchProgress={batchProgress}
                  onBatchPrecise={runBatchPrecise}
                  onClearSession={clearSession}
                  batchMsg={batchMsg}
                  batchFailDetails={batchFailDetails}
                />
              </div>
            )}

            {/* 滚动内容区 */}
            <div className="flex-1 overflow-y-auto md:pr-1">

            {/* 标题 + geocode警告 */}
            <div className="mb-3">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">🏠 推荐房源</h2>
                {response?.message && (
                  <span className="text-xs text-stone-500">{response.message}</span>
                )}
              </div>
              {response?.geocode_warning && (
                <div className="mt-2 rounded-lg border-2 border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  <div className="flex items-start gap-2">
                    <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-600" />
                    <div className="flex-1">
                      <div className="font-semibold">目的地识别警示</div>
                      <div className="mt-0.5 text-xs leading-relaxed">{response.geocode_warning}</div>
                      {response.dest_label && (
                        <div className="mt-1 text-xs text-amber-700">
                          当前用作起点参考：<b>{response.dest_label}</b>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}
              {subsidyResult && (
                <div className="mt-2 rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-xs text-violet-800">
                  <span className="font-semibold">🏢 房补筛选生效中：</span>
                  {subsidyResult.summary}
              </div>
            )}
            </div>

            {error && (
              <FriendlyError
                message={error}
                kind={errorKind}
                onRetry={
                  errorKind === 'timeout'
                    ? refreshAfterTimeout
                    : requirement
                      ? () => runSearch(requirement, { platform, sort: sortMode, page })
                      : undefined
                }
                retryLabel={errorKind === 'timeout' ? '刷新结果' : '重试'}
                onDismiss={() => { setError(''); setErrorKind(''); }}
              />
            )}

            {searching && !response ? (
              <SearchingPanel elapsed={searchElapsed} />
            ) : !response ? (
              <div className="rounded-2xl border border-dashed border-stone-300 bg-white/50 p-10 text-center text-sm text-stone-400">
                <p className="mb-2 text-base">还没有推荐</p>
                <p>请在左侧对话框中描述你的需求，AI 解析完成后点击「开始搜索」</p>
              </div>
            ) : response.recommendations.length === 0 ? (
              <div className="whitespace-pre-wrap rounded-2xl border border-dashed border-stone-300 bg-white/50 p-10 text-center text-sm text-stone-400">
                <p>{response.message || '无符合条件的房源'}</p>
                {platform === 'wuba' && (
                  <p className="mt-2 text-xs text-stone-400">
                    58同城为 JS 渲染站点，抓取成功率较低。<br />
                    若 Cookie 已填入仍无数据，可能触发了反爬，稍后重试或切换其他平台。
                  </p>
                )}
                {platform === 'anjuke' && (
                  <p className="mt-2 text-xs text-stone-400">
                    安居客数据抓取中……可切换「综合」查看链家/贝壳结果。
                  </p>
                )}
              </div>
            ) : (
              <>
                {searching && (
                  <div className="mb-2 flex items-center justify-center gap-2 rounded-md bg-amber-50 py-1.5 text-xs text-amber-700">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    刷新中（已用 {searchElapsed} 秒）
                  </div>
                )}
                <div className={cn('space-y-3', searching && 'opacity-60 pointer-events-none')}>
                  {response.recommendations
                    .filter((rec) => !subsidyAllowedIds || subsidyAllowedIds.has(rec.listing.id))
                    .map((rec) => (
                    <ListingCard
                      key={rec.listing.id}
                      rec={rec}
                      onSelect={setSelectedRec}
                      onCommuteUpdated={refreshAfterPrecise}
                      isFavorited={isFavorited(rec.listing.id)}
                      onToggleFavorite={toggleFavorite}
                    />
                  ))}
                </div>

                {response.total_pages > 1 && (
                  <div className="mt-4 flex items-center justify-center gap-2 pb-4">
                    <button
                      onClick={() => changePage(page - 1)}
                      disabled={page <= 1 || searching}
                      className="flex items-center gap-1 rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-sm text-stone-700 hover:bg-stone-50 disabled:opacity-40"
                    >
                      <ChevronLeft className="h-4 w-4" /> 上一页
                    </button>
                    <PageNumbers
                      current={page}
                      total={response.total_pages}
                      onChange={changePage}
                      disabled={searching}
                    />
                    <button
                      onClick={() => changePage(page + 1)}
                      disabled={page >= response.total_pages || searching}
                      className="flex items-center gap-1 rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-sm text-stone-700 hover:bg-stone-50 disabled:opacity-40"
                    >
                      下一页 <ChevronRight className="h-4 w-4" />
                    </button>
                  </div>
                )}
              </>
            )}
            </div>{/* end 滚动内容区 */}
          </div>

          {/* ── 右列：小红书/闲鱼 + 保障房政策（固定，内部滚动）── */}
          <div className="hidden md:flex md:flex-col md:gap-3 md:h-[calc(100vh-100px)] md:overflow-y-auto md:sticky md:top-[72px] md:self-start md:pl-1">
            <SocialMediaListings
              defaultCity={requirement?.destination?.city || ''}
              defaultDistrict={requirement?.destination?.district || ''}
              defaultCommunity=""
            />
            <PublicHousingPanel
              defaultCity={requirement?.destination?.city || ''}
            />
          </div>

        </div>
      </main>
      )} {/* end hasSearched */}

      <ListingDetailModal
        rec={selectedRec}
        requirement={requirement}
        onClose={() => setSelectedRec(null)}
      />

      {/* 新手引导：分阶段就近悬浮，未搜索只显示第一步 */}
      <OnboardingGuide hasResults={!!response} />

      {/* 收藏夹面板（右下角悬浮）*/}
      <FavoritesPanel
        favorites={favorites}
        onRemove={removeFavorite}
        onClear={clearFavorites}
        onSelectListing={(fav) => setSelectedRec(fav.rec)}
      />

      {/* Agent 小助手（右下角悬浮，在收藏按钮下方）*/}
      <AgentAssistant activeListing={selectedRec} />
    </>
  );
}

// ============================================================
// 精算统计栏（置于右侧列表顶部，sticky top 由外层 div 控制）
// ============================================================
function StickyCommuteBar({
  geoStats,
  sourceStats,
  radiusKm,
  batchPrecising,
  batchProgress,
  onBatchPrecise,
  onClearSession,
  batchMsg,
  batchFailDetails,
}: {
  geoStats?: SearchResponse['geo_filter_stats'];
  sourceStats?: SearchResponse['commute_source_stats'];
  radiusKm: number;
  batchPrecising: boolean;
  batchProgress: { current: number; total: number; label: string } | null;
  onBatchPrecise: () => void;
  onClearSession: () => void;
  batchMsg: string;
  batchFailDetails: string[];
}) {
  const [showFailDetails, setShowFailDetails] = useState(false);

  const total = sourceStats?.total || 0;
  const offline = sourceStats?.offline || 0;
  const precise = sourceStats?.precise || 0;
  const within = geoStats?.within_radius || 0;
  const out = geoStats?.out_of_radius || 0;
  const failed = geoStats?.geocode_failed || 0;
  const allPrecised = total > 0 && offline === 0;

  return (
    <div className="rounded-lg border border-stone-200 bg-white shadow-sm">
      <div className="px-3 py-2">
        {/* 失败原因展开面板 */}
        {showFailDetails && batchFailDetails.length > 0 && (
          <div className="mb-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            <div className="mb-1 flex items-center justify-between">
              <span className="font-semibold flex items-center gap-1">
                <Info className="h-3 w-3" />
                为什么有的房源无法精算实时通勤？
              </span>
              <button
                onClick={() => setShowFailDetails(false)}
                className="text-amber-600 hover:text-amber-900"
              >
                收起
              </button>
            </div>
            <ul className="space-y-0.5 leading-relaxed">
              {batchFailDetails.map((d, i) => (
                <li key={i} className="flex gap-1.5">
                  <span className="mt-0.5 shrink-0 text-amber-400">•</span>
                  <span>{d}</span>
                </li>
              ))}
            </ul>
            <p className="mt-1.5 text-amber-600">
              💡 可点卡片上的「⚡ 查询实时」对单条房源重试，或换用更标准的小区名搜索。
            </p>
          </div>
        )}

        <div className="flex items-center justify-between gap-2">
          {/* 左侧：统计数字 */}
          <div className="flex-1 min-w-0 text-xs text-stone-600">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
              <span>📐 <b>{radiusKm.toFixed(0)}km</b> 粗筛</span>
              <span className="text-stone-300">|</span>
              <span>范围内 <b className="text-emerald-700">{within}</b> 套</span>
              {out > 0 && <span className="text-stone-400">超出 {out}</span>}
              {failed > 0 && <span className="text-amber-500">定位失败 {failed}</span>}
              <span className="text-stone-300">|</span>
              <span>📍 估算 <b>{offline}</b>
                <HelpTip
                  position="bottom"
                  width="w-60"
                  content="离线估算：基于直线距离×经验系数公式，误差约 ±25%，仅供参考。点「⚡ 查询实时」可升级为高德精算。"
                />
              </span>
              <span>·</span>
              <span>✓ 实时 <b className="text-emerald-600">{precise}</b>
                <HelpTip
                  position="bottom"
                  width="w-60"
                  content="实时精算：调用高德地图 API 计算当前时刻的路线规划，误差 <5%。数据会永久保存，下次搜索同路线直接复用。"
                />
              </span>
            </div>
            {batchMsg && (
              <div className="mt-0.5 flex items-center gap-1 text-stone-500">
                <span>✓ {batchMsg}</span>
                {batchFailDetails.length > 0 && (
                  <button
                    onClick={() => setShowFailDetails((v) => !v)}
                    className="ml-1 flex items-center gap-0.5 text-amber-600 underline hover:text-amber-800"
                  >
                    <Info className="h-3 w-3" />
                    为什么有失败？
                  </button>
                )}
              </div>
            )}
            {/* 精算实时进度条 */}
            {batchPrecising && batchProgress && (
              <div className="mt-1">
                <div className="flex items-center justify-between text-xs text-stone-500 mb-0.5">
                  <span className="truncate max-w-[200px]">⚡ {batchProgress.label}</span>
                  <span className="shrink-0 ml-2 font-mono">{batchProgress.current}/{batchProgress.total}</span>
                </div>
                <div className="h-1.5 w-full rounded-full bg-stone-200 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-amber-500 transition-all duration-300"
                    style={{ width: `${Math.round((batchProgress.current / batchProgress.total) * 100)}%` }}
                  />
                </div>
              </div>
            )}
          </div>

          {/* 右侧：操作按钮 */}
          <div className="flex shrink-0 items-center gap-1.5">
            {(batchPrecising || (!allPrecised && offline > 0)) && (
              <div className="flex items-center gap-1">
                <button
                  onClick={onBatchPrecise}
                  disabled={batchPrecising}
                  className="flex items-center gap-1 rounded-md bg-amber-500 px-2.5 py-1.5 text-xs font-medium text-white transition hover:bg-amber-600 disabled:opacity-50"
                >
                  {batchPrecising ? (
                    <>
                      <Loader2 className="h-3 w-3 animate-spin" />
                      精算中…
                    </>
                  ) : (
                    <>
                      <Zap className="h-3 w-3" />
                      批量精算 10 条
                    </>
                  )}
                </button>
                <HelpTip
                  position="bottom"
                  width="w-64"
                  content={
                    <span>
                      对距离最近的 10 套房源调用<b>高德地图 API</b> 计算精确实时通勤，约 10-20 秒。
                      精算后徽章从「📍 离线估算」变为「✓ 实时」。
                      <br /><br />
                      离线估算误差 ±25%，精算误差 &lt;5%。
                    </span>
                  }
                />
              </div>
            )}
            {allPrecised && (
              <span className="text-xs text-emerald-600 font-medium">✓ 全部已精算</span>
            )}
            <button
              onClick={onClearSession}
              className="flex items-center gap-1 rounded-md border border-stone-300 bg-white px-2.5 py-1.5 text-xs text-stone-600 hover:bg-stone-100"
              title="清空当前结果（保留对话需求）"
            >
              <Trash2 className="h-3 w-3" />
              清空
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function PlatformTab({
  label, count, active, onClick, disabled,
}: {
  label: string | React.ReactNode;
  count?: number;
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'flex items-center gap-1 rounded-t-lg border-b-2 px-3 py-1.5 text-sm transition disabled:cursor-wait disabled:opacity-60',
        active
          ? 'border-amber-500 font-semibold text-amber-600'
          : 'border-transparent text-stone-600 hover:text-stone-900',
      )}
    >
      {label}
      {typeof count === 'number' && (
        <span className={cn('rounded-full px-1.5 text-xs', active ? 'bg-amber-100' : 'bg-stone-100')}>
          {count}
        </span>
      )}
    </button>
  );
}

function PageNumbers({
  current, total, onChange, disabled,
}: {
  current: number;
  total: number;
  onChange: (p: number) => void;
  disabled: boolean;
}) {
  const pages: (number | 'dots')[] = [];
  if (total <= 7) {
    for (let i = 1; i <= total; i++) pages.push(i);
  } else {
    pages.push(1);
    if (current > 3) pages.push('dots');
    for (let i = Math.max(2, current - 1); i <= Math.min(total - 1, current + 1); i++) {
      pages.push(i);
    }
    if (current < total - 2) pages.push('dots');
    pages.push(total);
  }

  return (
    <div className="flex gap-1">
      {pages.map((p, i) =>
        p === 'dots' ? (
          <span key={`dots-${i}`} className="px-2 text-stone-400">
            ...
          </span>
        ) : (
          <button
            key={p}
            onClick={() => onChange(p)}
            disabled={disabled}
            className={cn(
              'min-w-[32px] rounded-lg px-2 py-1 text-sm',
              p === current
                ? 'bg-amber-500 font-semibold text-white'
                : 'border border-stone-300 bg-white text-stone-700 hover:bg-stone-50',
            )}
          >
            {p}
          </button>
        ),
      )}
    </div>
  );
}

// ============================================================
// 搜索中阶段化提示
// ============================================================
function SearchingPanel({ elapsed }: { elapsed: number }) {
  const stages: { from: number; emoji: string; label: string; hint: string }[] = [
    { from: 0,   emoji: '📡', label: '正在跨平台抓取房源',       hint: '链家 + 贝壳并行抓取，每平台 ~150 条' },
    { from: 8,   emoji: '🧹', label: '去重 + 真实成本测算',      hint: '基于面积/区域/品牌算物业水电中介押金' },
    { from: 12,  emoji: '🗺️', label: '地理定位 + 直线距离粗筛',   hint: '目的地 geocode 后，对每套房源算直线距离' },
    { from: 30,  emoji: '⚡', label: '离线估算通勤时长',          hint: '基于直线距离 × 路网迂回系数 + 平均速度' },
    { from: 60,  emoji: '⏳', label: '后端处理时间略长',          hint: '高德 QPS 限制 ~3 次/秒，耐心等等' },
    { from: 120, emoji: '🐢', label: '可能遇到网络波动',          hint: 'DeepSeek / 高德 API 高峰期可能慢' },
  ];
  const stage = stages.reduce((acc, s) => (elapsed >= s.from ? s : acc), stages[0]);
  const showWarn = elapsed >= 90;

  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-amber-200 bg-amber-50/40 py-12 text-stone-600">
      <div className="relative mb-3">
        <Loader2 className="h-10 w-10 animate-spin text-amber-500" />
      </div>
      <p className="text-base font-medium">
        <span className="mr-1">{stage.emoji}</span>
        {stage.label}
      </p>
      <p className="mt-1 text-xs text-stone-500">{stage.hint}</p>

      <div className="mt-4 flex items-center gap-1.5 rounded-full bg-white/70 px-3 py-1 text-xs text-stone-500">
        <Clock className="h-3 w-3" />
        已用时 <span className="font-semibold tabular-nums text-stone-700">{elapsed}</span> 秒
      </div>

      <div className="mt-3 h-1 w-64 overflow-hidden rounded-full bg-stone-200">
        <div
          className="h-full bg-gradient-to-r from-amber-400 to-orange-500 transition-all"
          style={{ width: `${Math.min(95, elapsed * 1.2)}%` }}
        />
      </div>

      {showWarn && (
        <div className="mt-4 max-w-md rounded-lg bg-amber-100 px-3 py-2 text-xs text-amber-800">
          💡 所有房源加载后先做离线估算（毫秒级），精算可点击「批量精算」获取准确数字。
        </div>
      )}
    </div>
  );
}

// ============================================================
// 友好错误展示
// ============================================================
function FriendlyError({
  message, kind, onRetry, retryLabel = '重试', onDismiss,
}: {
  message: string;
  kind: ErrorKind;
  onRetry?: () => void;
  retryLabel?: string;
  onDismiss: () => void;
}) {
  const meta = (() => {
    if (kind === 'timeout') {
      return {
        title: '请求超时',
        Icon: Clock,
        bg: 'border-amber-300 bg-amber-50',
        text: 'text-amber-800',
        accent: 'text-amber-600',
        // 超时时给用户额外提示
        extra: '后端可能仍在处理中（抓取+geocode 约需 30-60 秒）。点「刷新结果」尝试读取已完成的数据，无需重新搜索。',
      };
    }
    if (kind === 'network') {
      return { title: '无法连接后端', Icon: WifiOff, bg: 'border-stone-300 bg-stone-50', text: 'text-stone-800', accent: 'text-stone-600', extra: '' };
    }
    return { title: '出错了', Icon: AlertTriangle, bg: 'border-rose-200 bg-rose-50', text: 'text-rose-800', accent: 'text-rose-600', extra: '' };
  })();

  const Icon = meta.Icon;

  return (
    <div className={cn('mb-3 rounded-lg border px-4 py-3 text-sm', meta.bg, meta.text)}>
      <div className="flex items-start gap-2">
        <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', meta.accent)} />
        <div className="flex-1">
          <div className="font-semibold">{meta.title}</div>
          <div className="mt-0.5 whitespace-pre-wrap text-xs leading-relaxed opacity-90">{message}</div>
          {meta.extra && (
            <div className="mt-1 text-xs leading-relaxed opacity-80">{meta.extra}</div>
          )}
          <div className="mt-2 flex gap-2">
            {onRetry && (
              <button
                onClick={onRetry}
                className="inline-flex items-center gap-1 rounded bg-white/80 px-2 py-1 text-xs font-medium hover:bg-white"
              >
                <RefreshCw className="h-3 w-3" />
                {retryLabel}
              </button>
            )}
            <button
              onClick={onDismiss}
              className="inline-flex items-center rounded px-2 py-1 text-xs opacity-60 hover:opacity-100"
            >
              关闭
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
