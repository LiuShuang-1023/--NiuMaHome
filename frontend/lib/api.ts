import type {
  ChatMessage,
  ChatResponse,
  CommuteSummary,
  CostBreakdown,
  Listing,
  ListingReviewResponse,
  ParsedRequirement,
  PlatformFilter,
  PreciseBatchResponse,
  PreciseOneResponse,
  SearchResponse,
  SortMode,
} from './types';

const API_BASE = '/api/backend';

export class ApiError extends Error {
  kind: 'timeout' | 'network' | 'http' | 'unknown';
  status?: number;
  constructor(kind: ApiError['kind'], message: string, status?: number) {
    super(message);
    this.kind = kind;
    this.status = status;
  }
}

interface HttpOptions {
  timeoutMs?: number;
  signal?: AbortSignal;
  method?: 'GET' | 'POST' | 'DELETE';
}

async function http<T>(path: string, body: unknown, opts: HttpOptions = {}): Promise<T> {
  const timeoutMs = opts.timeoutMs ?? 180_000;
  const controller = new AbortController();
  if (opts.signal) {
    opts.signal.addEventListener('abort', () => controller.abort());
  }
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  let res: Response;
  try {
    const method = opts.method || (body !== null && body !== undefined ? 'POST' : 'GET');
    const init: RequestInit = {
      method,
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
    };
    if (body !== undefined && body !== null && method !== 'GET' && method !== 'DELETE') {
      init.body = JSON.stringify(body);
    }
    res = await fetch(`${API_BASE}${path}`, init);
  } catch (e: any) {
    clearTimeout(timer);
    if (e?.name === 'AbortError') {
      throw new ApiError(
        'timeout',
        `请求超时（已等待 ${Math.round(timeoutMs / 1000)} 秒）。后端可能正在处理大量房源，请稍后重试。`,
      );
    }
    throw new ApiError(
      'network',
      '无法连接到后端服务。请检查后端是否启动，或网络是否正常。',
    );
  }
  clearTimeout(timer);

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    let detail = text;
    try {
      const j = JSON.parse(text);
      detail = j.detail || j.message || text;
    } catch {
      // ignore
    }
    throw new ApiError('http', `服务返回错误 (${res.status}): ${detail || '未知错误'}`, res.status);
  }
  return (await res.json()) as T;
}

// ============================================================
// session_id 管理（v0.3.0）
// 浏览器 sessionStorage 存储，关闭标签页自动清空
// ============================================================
const SESSION_KEY = 'niumahome_session_id';

function genUuid(): string {
  // 简易 UUID v4（兼容 SSR）
  if (typeof crypto !== 'undefined' && (crypto as any).randomUUID) {
    return (crypto as any).randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export function getSessionId(): string {
  if (typeof window === 'undefined') return '';
  let sid = sessionStorage.getItem(SESSION_KEY);
  if (!sid) {
    sid = genUuid();
    sessionStorage.setItem(SESSION_KEY, sid);
  }
  return sid;
}

export function resetSessionId(): string {
  if (typeof window === 'undefined') return '';
  const sid = genUuid();
  sessionStorage.setItem(SESSION_KEY, sid);
  return sid;
}

// ============================================================
// 业务接口
// ============================================================
export async function postChat(
  messages: ChatMessage[],
  current_requirement: ParsedRequirement | null,
): Promise<ChatResponse> {
  return http<ChatResponse>('/chat', { messages, current_requirement }, {
    timeoutMs: 90_000,
  });
}

export interface SearchOptions {
  sort_mode?: SortMode;
  platform?: PlatformFilter;
  page?: number;
  page_size?: number;
}

// ============================================================
// 异步搜索（解决 Next.js 代理 60s 超时问题）
// /search/start → task_id → 轮询 /search/status/{task_id}
// ============================================================
export interface SearchTaskStatus {
  task_id: string;
  status: 'pending' | 'running' | 'done' | 'error';
  progress: string;
  result?: SearchResponse;
  error?: string;
}

/** 提交搜索任务，立即返回 task_id（<1s）*/
export async function startSearch(
  requirement: ParsedRequirement,
  options: SearchOptions = {},
): Promise<{ task_id: string }> {
  return http<{ task_id: string }>(
    '/search/start',
    {
      session_id: getSessionId(),
      requirement,
      sort_mode: options.sort_mode || '综合',
      platform: options.platform || 'all',
      page: options.page || 1,
      page_size: options.page_size || 10,
    },
    { timeoutMs: 10_000 },  // 提交本身应 <1s
  );
}

/** 轮询一次任务状态 */
export async function pollSearchStatus(task_id: string): Promise<SearchTaskStatus> {
  return http<SearchTaskStatus>(
    `/search/status/${task_id}`,
    null,
    { method: 'GET', timeoutMs: 10_000 },
  );
}

/** v0.3.0: 仅排序（毫秒响应，不重抓不重算） */
export async function postSort(options: SearchOptions = {}): Promise<SearchResponse> {
  return http<SearchResponse>(
    '/search/sort',
    {
      session_id: getSessionId(),
      sort_mode: options.sort_mode || '综合',
      platform: options.platform || 'all',
      page: options.page || 1,
      page_size: options.page_size || 10,
    },
    { timeoutMs: 30_000 },
  );
}

/** v0.3.0: 单条精算 */
export async function postPreciseOne(
  listing_id: string,
): Promise<PreciseOneResponse> {
  return http<PreciseOneResponse>(
    '/search/precise_one',
    { session_id: getSessionId(), listing_id },
    { timeoutMs: 60_000 },
  );
}

/** v0.3.0: 批量精算（按距离从近到远） */
export async function postPreciseBatch(
  options: SearchOptions & { max_count?: number } = {},
): Promise<PreciseBatchResponse> {
  return http<PreciseBatchResponse>(
    '/search/precise_batch',
    {
      session_id: getSessionId(),
      max_count: options.max_count ?? 10,
      sort_mode: options.sort_mode || '综合',
      platform: options.platform || 'all',
      page: options.page || 1,
      page_size: options.page_size || 10,
    },
    { timeoutMs: 180_000 },
  );
}

/** v0.5.1: SSE 流式批量精算 — 实时进度回调 */
export function preciseBatchStream(
  options: SearchOptions & { max_count?: number } = {},
  onProgress: (current: number, total: number, label: string, success: number, fail: number) => void,
  onDone: (result: PreciseBatchResponse) => void,
  onError: (msg: string) => void,
): () => void /* 返回取消函数 */ {
  const body = JSON.stringify({
    session_id: getSessionId(),
    max_count: options.max_count ?? 10,
    sort_mode: options.sort_mode || '综合',
    platform: options.platform || 'all',
    page: options.page || 1,
    page_size: options.page_size || 10,
  });

  const abortCtrl = new AbortController();

  fetch(`${API_BASE}/search/precise_batch_stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
    signal: abortCtrl.signal,
  }).then(async (resp) => {
    if (!resp.ok) {
      onError(`精算接口错误 ${resp.status}`);
      return;
    }
    const reader = resp.body!.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop()!; // 最后一行可能不完整
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const evt = JSON.parse(line.slice(6));
          if (evt.type === 'progress') {
            onProgress(evt.current, evt.total, evt.label, evt.success, evt.fail);
          } else if (evt.type === 'done') {
            onDone(evt.result as PreciseBatchResponse);
          }
        } catch { /* ignore malformed */ }
      }
    }
  }).catch((e) => {
    if (e?.name !== 'AbortError') onError(e?.message || '精算失败');
  });

  return () => abortCtrl.abort();
}

/** v0.3.0: 清空当前会话 */
export async function deleteCurrentSession(): Promise<{ message: string; deleted: number }> {
  const sid = getSessionId();
  return http<{ message: string; deleted: number }>(
    `/search/session/${sid}`,
    null,
    { method: 'DELETE', timeoutMs: 10_000 },
  );
}

export async function postListingReview(params: {
  listing: Listing;
  cost: CostBreakdown;
  commute?: CommuteSummary | null;
  requirement?: ParsedRequirement | null;
  force_refresh?: boolean;
}): Promise<ListingReviewResponse> {
  return http<ListingReviewResponse>('/listings/review', {
    listing: params.listing,
    cost: params.cost,
    commute: params.commute ?? null,
    requirement: params.requirement ?? null,
    force_refresh: params.force_refresh ?? false,
  });
}

// ── 详情页二次抓取 (v0.3/v0.7) ────────────────────────────────────────
export interface ListingDetailResult {
  success: boolean;
  deposit_type?: string | null;
  heating_type?: string | null;
  water_type?: string | null;
  electricity_type?: string | null;
  gas_type?: string | null;
  elevator?: boolean | null;
  move_in?: string | null;
  facilities: string[];
  images: string[];
  description?: string | null;
  fail_reason?: string;
  // v0.7: cost 写回状态
  cost_updated?: boolean;
  cost_update_note?: string;
}

export async function fetchListingDetail(params: {
  url: string;
  platform: string;
  listing_id?: string;  // v0.7: 有则触发cost写回
}): Promise<ListingDetailResult> {
  return http<ListingDetailResult>('/listings/detail', {
    url: params.url,
    platform: params.platform,
    session_id: params.listing_id ? getSessionId() : undefined,
    listing_id: params.listing_id,
  }, { timeoutMs: 20000 });
}

// ── 智能水电估算 (v0.4) ────────────────────────────────────────
export type AcLevel = 'never' | 'mild' | 'moderate' | 'heavy';
export type ShowerLevel = 'quick' | 'normal' | 'long' | 'bath';
export type CookLevel = 'never' | 'sometimes' | 'daily' | 'heavy';

export interface UtilityEstimateRequest {
  ac_level: AcLevel;
  shower_level: ShowerLevel;
  cook_level: CookLevel;
  people_count: number;
  has_gas: boolean;
  water_heater_type: 'gas' | 'electric' | 'central';
  listing_area?: number;
}

export interface UtilityEstimateResponse {
  electricity: number;
  water: number;
  gas: number;
  total_utility: number;
  electricity_kwh: number;
  water_tons: number;
  gas_m3: number;
  notes: Record<string, string>;
  delta_vs_default: number;
  delta_label: string;
}

export async function postUtilityEstimate(
  req: UtilityEstimateRequest,
): Promise<UtilityEstimateResponse> {
  return http<UtilityEstimateResponse>('/utility/estimate', req, { timeoutMs: 10_000 });
}

export async function postUtilityApply(params: {
  listing_id: string;
} & UtilityEstimateRequest): Promise<{ listing_id: string; success: boolean; new_total: number; message: string }> {
  return http('/utility/apply', {
    session_id: getSessionId(),
    ...params,
  }, { timeoutMs: 10_000 });
}

// ── Agent 小助手 (v0.5) ────────────────────────────────────────
export interface AgentAskResponse {
  answer: string;
  is_inquiry_template: boolean;
}

export async function postAgentAsk(params: {
  question: string;
  listing_context?: Record<string, any> | null;
}): Promise<AgentAskResponse> {
  return http<AgentAskResponse>('/agent/ask', params, { timeoutMs: 30_000 });
}

export interface InquiryResponse {
  listing_id: string;
  message: string;
  listing_url: string;
  platform_label: string;
  copy_hint: string;
}

export async function postAgentInquiry(params: {
  listing_id: string;
  listing_title?: string;
  listing_community?: string;
  listing_url?: string;
  platform?: string;
  items_to_ask?: string[];
  use_ai?: boolean;
}): Promise<InquiryResponse> {
  return http<InquiryResponse>('/agent/inquiry', params, { timeoutMs: 30_000 });
}

export async function postAgentBatchInquiry(params: {
  listings: Array<{
    listing_id: string;
    listing_title?: string;
    listing_community?: string;
    listing_url?: string;
    platform?: string;
    items_to_ask?: string[];
  }>;
  use_ai?: boolean;
}): Promise<{ results: InquiryResponse[]; total: number }> {
  return http('/agent/batch_inquiry', params, { timeoutMs: 60_000 });
}

// ── 保障房政策查询 (v0.8) ──────────────────────────────────────
export interface HousingTypeInfo {
  name: string;
  apply_url?: string;
  app?: string;
  conditions: string[];
  rent_discount?: string;
  notes?: string;
}

export interface PolicyInfoResponse {
  city: string;
  source: 'db' | 'ai' | 'not_found' | 'ai_unavailable';
  public_rental?: HousingTypeInfo | null;
  talent_apartment?: HousingTypeInfo | null;
  youth_apartment?: HousingTypeInfo | null;
  ai_summary?: string;
  disclaimer: string;
}

export async function getHousingPolicyInfo(city: string): Promise<PolicyInfoResponse> {
  return http<PolicyInfoResponse>(`/housing/policy_info?city=${encodeURIComponent(city)}`, null, {
    method: 'GET',
    timeoutMs: 10_000,
  });
}

export async function postHousingPolicyAI(city: string): Promise<PolicyInfoResponse> {
  return http<PolicyInfoResponse>('/housing/policy_ai', { city }, { timeoutMs: 30_000 });
}
export interface CommuteCondition {
  mode: 'transit' | 'riding' | 'walking' | 'any' | string;
  max_minutes: number;
  description: string;
}

export interface SubsidyAnalyzeResponse {
  summary: string;
  conditions: CommuteCondition[];
  logic: 'any' | 'all';
  recommended_max_minutes: number;
  recommended_modes: string[];
  has_distance_limit: boolean;
  distance_km: number | null;
  notes: string;
  raw_parsed: Record<string, unknown>;
}

export async function postSubsidyAnalyze(
  policy_text: string,
): Promise<SubsidyAnalyzeResponse> {
  return http<SubsidyAnalyzeResponse>('/subsidy/analyze', { policy_text }, { timeoutMs: 30_000 });
}

export interface SubsidyFilterResponse {
  matched_listing_ids: string[];
  total_checked: number;
  total_matched: number;
  no_coord_count: number;
  dest_coord: [number, number] | null;
  message: string;
}

export async function postSubsidyFilter(distance_km: number): Promise<SubsidyFilterResponse> {
  return http<SubsidyFilterResponse>('/subsidy/filter', {
    session_id: getSessionId(),
    distance_km,
  }, { timeoutMs: 10_000 });
}
