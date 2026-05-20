'use client';

/**
 * 智能水电估算问卷（v0.4）
 *
 * 以悬浮抽屉方式内嵌在 ListingDetailModal 的成本明细区域旁边，
 * 不弹全屏，点「精算水电」按钮展开，填完即时预览，确认后写回成本。
 */

import { useState } from 'react';
import { Zap, Droplets, Flame, ChevronDown, ChevronUp, Loader2, CheckCircle2, X } from 'lucide-react';
import {
  postUtilityEstimate,
  postUtilityApply,
  type AcLevel,
  type ShowerLevel,
  type CookLevel,
  type UtilityEstimateResponse,
} from '@/lib/api';
import { cn } from '@/lib/utils';

// ── 问卷选项 ─────────────────────────────────────────────────────
const AC_OPTIONS: { value: AcLevel; label: string; emoji: string }[] = [
  { value: 'never',    label: '基本不开（只用风扇）',    emoji: '🌬️' },
  { value: 'mild',     label: '偶尔开（睡觉，<2h/天）',  emoji: '😌' },
  { value: 'moderate', label: '正常开（早晚各 2h）',     emoji: '🌡️' },
  { value: 'heavy',    label: '长时间开（8h+/天）',      emoji: '🥶' },
];

const SHOWER_OPTIONS: { value: ShowerLevel; label: string; emoji: string }[] = [
  { value: 'quick',  label: '短冲澡（<5 分钟）',   emoji: '⚡' },
  { value: 'normal', label: '正常淋浴（约 10 分钟）', emoji: '🚿' },
  { value: 'long',   label: '喜欢长淋浴（20 分钟+）', emoji: '💧' },
  { value: 'bath',   label: '经常泡澡',             emoji: '🛁' },
];

const COOK_OPTIONS: { value: CookLevel; label: string; emoji: string }[] = [
  { value: 'never',     label: '基本不做饭（外卖为主）', emoji: '🍱' },
  { value: 'sometimes', label: '偶尔做（每周 2-3 次）',  emoji: '🥘' },
  { value: 'daily',     label: '每天做饭（1-2 餐）',     emoji: '🍳' },
  { value: 'heavy',     label: '重度厨房爱好者',         emoji: '👨‍🍳' },
];

// ── Props ─────────────────────────────────────────────────────────
interface UtilityWizardProps {
  listingId: string;
  listingArea?: number;
  /** 精算并写回成功后的回调（携带新 total），触发父组件刷新 */
  onApplied?: (newTotal: number, notes: Record<string, string>) => void;
}

// ── 单选组件 ─────────────────────────────────────────────────────
function RadioGroup<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: string; emoji: string }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="mb-3">
      <div className="mb-1.5 text-xs font-semibold text-stone-600">{label}</div>
      <div className="grid grid-cols-2 gap-1.5">
        {options.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            className={cn(
              'flex items-center gap-1.5 rounded-lg border px-2.5 py-2 text-left text-xs transition',
              value === opt.value
                ? 'border-amber-400 bg-amber-50 font-semibold text-amber-700 shadow-sm'
                : 'border-stone-200 bg-white text-stone-600 hover:border-stone-300 hover:bg-stone-50',
            )}
          >
            <span className="text-base">{opt.emoji}</span>
            <span className="leading-snug">{opt.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ── 主组件 ───────────────────────────────────────────────────────
export default function UtilityWizard({ listingId, listingArea = 70, onApplied }: UtilityWizardProps) {
  const [open, setOpen] = useState(false);

  // 问卷状态
  const [acLevel, setAcLevel] = useState<AcLevel>('moderate');
  const [showerLevel, setShowerLevel] = useState<ShowerLevel>('normal');
  const [cookLevel, setCookLevel] = useState<CookLevel>('daily');
  const [peopleCount, setPeopleCount] = useState(1);
  const [hasGas, setHasGas] = useState(true);
  const [waterHeater, setWaterHeater] = useState<'gas' | 'electric' | 'central'>('gas');

  // 估算结果
  const [estimate, setEstimate] = useState<UtilityEstimateResponse | null>(null);
  const [estimating, setEstimating] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState(false);
  const [error, setError] = useState('');

  // 手动覆盖值（用户可直接修改，覆盖问卷计算结果）
  const [manualElec, setManualElec] = useState<string>('');
  const [manualWater, setManualWater] = useState<string>('');
  const [manualGas, setManualGas] = useState<string>('');
  const [manualMode, setManualMode] = useState(false); // 是否进入手动模式

  // 实际生效的三项值（手动覆盖优先，否则用问卷估算）
  const effectiveElec  = manualMode && manualElec  !== '' ? parseInt(manualElec)  || 0 : estimate?.electricity  ?? 0;
  const effectiveWater = manualMode && manualWater !== '' ? parseInt(manualWater) || 0 : estimate?.water        ?? 0;
  const effectiveGas   = manualMode && manualGas   !== '' ? parseInt(manualGas)   || 0 : estimate?.gas          ?? 0;
  const effectiveTotal = effectiveElec + effectiveWater + effectiveGas;

  const buildReq = () => ({
    ac_level: acLevel,
    shower_level: showerLevel,
    cook_level: cookLevel,
    people_count: peopleCount,
    has_gas: hasGas,
    water_heater_type: waterHeater,
    listing_area: listingArea,
  });

  async function handleEstimate() {
    setEstimating(true);
    setError('');
    setApplied(false);
    try {
      const res = await postUtilityEstimate(buildReq());
      setEstimate(res);
      // 同步更新手动输入框为估算值（方便用户基于此微调）
      setManualElec(String(res.electricity));
      setManualWater(String(res.water));
      setManualGas(String(res.gas));
    } catch (e: any) {
      setError(e?.message || '估算失败');
    } finally {
      setEstimating(false);
    }
  }

  async function handleApply() {
    setApplying(true);
    setError('');
    try {
      // 如果是手动模式，直接 patch 成本；否则走问卷接口
      if (manualMode) {
        // 手动模式：直接调 apply，但用手动值覆盖（通过 POST body 传入 override）
        const res = await postUtilityApply({
          listing_id: listingId,
          ...buildReq(),
          override_electricity: effectiveElec,
          override_water: effectiveWater,
          override_gas: effectiveGas,
        } as any);
        if (res.success) {
          setApplied(true);
          const notes = estimate?.notes ?? {};
          onApplied?.(res.new_total, {
            ...notes,
            electricity: `手动填写 ¥${effectiveElec}`,
            water: `手动填写 ¥${effectiveWater}`,
            gas: `手动填写 ¥${effectiveGas}`,
          });
        }
      } else {
        if (!estimate) return;
        const res = await postUtilityApply({ listing_id: listingId, ...buildReq() });
        if (res.success) {
          setApplied(true);
          onApplied?.(res.new_total, estimate.notes);
        }
      }
    } catch (e: any) {
      setError(e?.message || '写入失败');
    } finally {
      setApplying(false);
    }
  }

  return (
    <div className="mt-3 rounded-xl border border-dashed border-amber-300 bg-amber-50/50">
      {/* 折叠标题 */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-4 py-2.5 text-sm font-semibold text-amber-700"
      >
        <span className="flex items-center gap-1.5">
          <Zap className="h-4 w-4" />
          {applied
            ? '✅ 水电燃气已按你的习惯精算'
            : '⚡ 按我的生活习惯精算水电（可选）'}
        </span>
        {open ? (
          <ChevronUp className="h-4 w-4 text-amber-500" />
        ) : (
          <ChevronDown className="h-4 w-4 text-amber-500" />
        )}
      </button>

      {open && (
        <div className="border-t border-amber-200 px-4 pb-4 pt-3">
          <p className="mb-3 text-xs text-stone-500 leading-relaxed">
            默认估算按广州均值（100度电/月、4吨水/月）。填写你的习惯可得更准确的月支出估算。
          </p>

          {/* 问卷 */}
          <RadioGroup
            label="❄️ 空调使用习惯"
            options={AC_OPTIONS}
            value={acLevel}
            onChange={setAcLevel}
          />
          <RadioGroup
            label="🚿 洗澡习惯"
            options={SHOWER_OPTIONS}
            value={showerLevel}
            onChange={setShowerLevel}
          />
          <RadioGroup
            label="🍳 做饭习惯"
            options={COOK_OPTIONS}
            value={cookLevel}
            onChange={setCookLevel}
          />

          {/* 附加选项 */}
          <div className="mb-3 flex flex-wrap gap-3 text-xs">
            <label className="flex items-center gap-1.5 text-stone-600">
              <span className="font-semibold">居住人数：</span>
              <select
                value={peopleCount}
                onChange={(e) => setPeopleCount(Number(e.target.value))}
                className="rounded border border-stone-300 px-2 py-1 text-xs"
              >
                {[1, 2, 3, 4].map((n) => (
                  <option key={n} value={n}>{n} 人</option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-1.5 text-stone-600">
              <span className="font-semibold">热水器类型：</span>
              <select
                value={waterHeater}
                onChange={(e) => setWaterHeater(e.target.value as any)}
                className="rounded border border-stone-300 px-2 py-1 text-xs"
              >
                <option value="gas">燃气热水器</option>
                <option value="electric">电热水器</option>
                <option value="central">集中供热/太阳能</option>
              </select>
            </label>
            <label className="flex items-center gap-1.5 text-stone-600">
              <input
                type="checkbox"
                checked={hasGas}
                onChange={(e) => setHasGas(e.target.checked)}
                className="rounded"
              />
              有燃气
            </label>
          </div>

          {/* 预览 + 手动修改 */}
          {estimate && (
            <div className="mb-3 rounded-lg border border-amber-200 bg-white p-3 text-xs">
              <div className="mb-2 flex items-center justify-between">
                <span className="font-semibold text-stone-700">精算预览</span>
                <button
                  type="button"
                  onClick={() => setManualMode((v) => !v)}
                  className={cn(
                    'rounded-md px-2 py-0.5 text-xs font-medium transition',
                    manualMode
                      ? 'bg-amber-100 text-amber-700 ring-1 ring-amber-400'
                      : 'bg-stone-100 text-stone-500 hover:bg-stone-200',
                  )}
                >
                  ✏️ {manualMode ? '手动模式（点击关闭）' : '手动修改金额'}
                </button>
              </div>

              <div className="grid grid-cols-3 gap-2 text-center">
                {/* 电费卡片 */}
                <div className="rounded-lg bg-blue-50 px-2 py-2">
                  <Zap className="mx-auto mb-0.5 h-3.5 w-3.5 text-blue-500" />
                  {manualMode ? (
                    <div className="flex items-center justify-center gap-0.5">
                      <span className="text-blue-600 font-bold">¥</span>
                      <input
                        type="number"
                        min={0}
                        value={manualElec}
                        onChange={(e) => setManualElec(e.target.value)}
                        className="w-14 rounded border border-blue-300 bg-white px-1 py-0.5 text-center text-sm font-bold text-blue-700 focus:outline-none focus:ring-1 focus:ring-blue-400"
                      />
                    </div>
                  ) : (
                    <div className="font-bold text-blue-700">¥{estimate.electricity}</div>
                  )}
                  <div className="text-stone-500">电费</div>
                  <div className="text-stone-400">{estimate.electricity_kwh}度</div>
                </div>

                {/* 水费卡片 */}
                <div className="rounded-lg bg-cyan-50 px-2 py-2">
                  <Droplets className="mx-auto mb-0.5 h-3.5 w-3.5 text-cyan-500" />
                  {manualMode ? (
                    <div className="flex items-center justify-center gap-0.5">
                      <span className="text-cyan-600 font-bold">¥</span>
                      <input
                        type="number"
                        min={0}
                        value={manualWater}
                        onChange={(e) => setManualWater(e.target.value)}
                        className="w-14 rounded border border-cyan-300 bg-white px-1 py-0.5 text-center text-sm font-bold text-cyan-700 focus:outline-none focus:ring-1 focus:ring-cyan-400"
                      />
                    </div>
                  ) : (
                    <div className="font-bold text-cyan-700">¥{estimate.water}</div>
                  )}
                  <div className="text-stone-500">水费</div>
                  <div className="text-stone-400">{estimate.water_tons}吨</div>
                </div>

                {/* 燃气卡片 */}
                <div className="rounded-lg bg-orange-50 px-2 py-2">
                  <Flame className="mx-auto mb-0.5 h-3.5 w-3.5 text-orange-500" />
                  {manualMode ? (
                    <div className="flex items-center justify-center gap-0.5">
                      <span className="text-orange-600 font-bold">¥</span>
                      <input
                        type="number"
                        min={0}
                        value={manualGas}
                        onChange={(e) => setManualGas(e.target.value)}
                        className="w-14 rounded border border-orange-300 bg-white px-1 py-0.5 text-center text-sm font-bold text-orange-700 focus:outline-none focus:ring-1 focus:ring-orange-400"
                      />
                    </div>
                  ) : (
                    <div className="font-bold text-orange-700">¥{estimate.gas}</div>
                  )}
                  <div className="text-stone-500">燃气</div>
                  <div className="text-stone-400">{estimate.gas_m3}m³</div>
                </div>
              </div>

              {/* 手动模式：实时合计 */}
              {manualMode && (
                <div className="mt-2 rounded-md bg-amber-50 px-3 py-1.5 text-center text-xs font-semibold text-amber-700">
                  手动合计：¥{effectiveElec} + ¥{effectiveWater} + ¥{effectiveGas} = <span className="text-base">¥{effectiveTotal}</span>/月
                </div>
              )}

              {!manualMode && (
                <div
                  className={cn(
                    'mt-2 rounded-md px-2 py-1 text-center text-xs font-semibold',
                    estimate.delta_vs_default > 0
                      ? 'bg-rose-50 text-rose-700'
                      : estimate.delta_vs_default < 0
                        ? 'bg-emerald-50 text-emerald-700'
                        : 'bg-stone-50 text-stone-600',
                  )}
                >
                  {estimate.delta_label}
                </div>
              )}

              {/* 计算依据（非手动模式显示） */}
              {!manualMode && (
                <div className="mt-2 space-y-0.5 text-stone-400 leading-relaxed">
                  {estimate.notes.electricity && <div>⚡ {estimate.notes.electricity}</div>}
                  {estimate.notes.water && <div>💧 {estimate.notes.water}</div>}
                  {estimate.notes.gas && <div>🔥 {estimate.notes.gas}</div>}
                </div>
              )}

              {manualMode && (
                <p className="mt-2 text-center text-stone-400 leading-relaxed">
                  直接输入你知道的实际金额，点「确认更新」写入成本。
                </p>
              )}
            </div>
          )}

          {/* 未估算时的纯手动入口 */}
          {!estimate && (
            <div className="mb-3">
              <button
                type="button"
                onClick={() => setManualMode(true)}
                className="w-full rounded-lg border border-dashed border-stone-300 py-2 text-xs text-stone-500 hover:border-amber-400 hover:text-amber-600 transition"
              >
                ✏️ 我知道实际水电费，直接手动填写
              </button>
              {manualMode && (
                <div className="mt-2 rounded-lg border border-amber-200 bg-white p-3">
                  <div className="mb-2 text-xs font-semibold text-stone-700">手动填写月均费用</div>
                  <div className="grid grid-cols-3 gap-2 text-center">
                    <div className="rounded-lg bg-blue-50 px-2 py-2">
                      <Zap className="mx-auto mb-0.5 h-3.5 w-3.5 text-blue-500" />
                      <div className="flex items-center justify-center gap-0.5">
                        <span className="text-blue-600 font-bold text-xs">¥</span>
                        <input
                          type="number"
                          min={0}
                          placeholder="如 150"
                          value={manualElec}
                          onChange={(e) => setManualElec(e.target.value)}
                          className="w-14 rounded border border-blue-300 bg-white px-1 py-0.5 text-center text-sm font-bold text-blue-700 focus:outline-none focus:ring-1 focus:ring-blue-400"
                        />
                      </div>
                      <div className="mt-0.5 text-stone-500">电费/月</div>
                    </div>
                    <div className="rounded-lg bg-cyan-50 px-2 py-2">
                      <Droplets className="mx-auto mb-0.5 h-3.5 w-3.5 text-cyan-500" />
                      <div className="flex items-center justify-center gap-0.5">
                        <span className="text-cyan-600 font-bold text-xs">¥</span>
                        <input
                          type="number"
                          min={0}
                          placeholder="如 30"
                          value={manualWater}
                          onChange={(e) => setManualWater(e.target.value)}
                          className="w-14 rounded border border-cyan-300 bg-white px-1 py-0.5 text-center text-sm font-bold text-cyan-700 focus:outline-none focus:ring-1 focus:ring-cyan-400"
                        />
                      </div>
                      <div className="mt-0.5 text-stone-500">水费/月</div>
                    </div>
                    <div className="rounded-lg bg-orange-50 px-2 py-2">
                      <Flame className="mx-auto mb-0.5 h-3.5 w-3.5 text-orange-500" />
                      <div className="flex items-center justify-center gap-0.5">
                        <span className="text-orange-600 font-bold text-xs">¥</span>
                        <input
                          type="number"
                          min={0}
                          placeholder="如 25"
                          value={manualGas}
                          onChange={(e) => setManualGas(e.target.value)}
                          className="w-14 rounded border border-orange-300 bg-white px-1 py-0.5 text-center text-sm font-bold text-orange-700 focus:outline-none focus:ring-1 focus:ring-orange-400"
                        />
                      </div>
                      <div className="mt-0.5 text-stone-500">燃气/月</div>
                    </div>
                  </div>
                  {(manualElec || manualWater || manualGas) && (
                    <div className="mt-2 rounded-md bg-amber-50 px-3 py-1.5 text-center text-xs font-semibold text-amber-700">
                      合计：¥{effectiveTotal}/月
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {error && (
            <div className="mb-2 rounded border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
              {error}
            </div>
          )}

          {applied && (
            <div className="mb-2 flex items-center gap-1.5 rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
              <CheckCircle2 className="h-4 w-4" />
              成本明细已更新！月总支出已按你的习惯重新计算。
            </div>
          )}

          {/* 操作按钮 */}
          <div className="flex gap-2">
            {!manualMode && (
              <button
                type="button"
                onClick={handleEstimate}
                disabled={estimating}
                className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-amber-500 py-2 text-xs font-semibold text-white transition hover:bg-amber-600 disabled:opacity-50"
              >
                {estimating ? (
                  <><Loader2 className="h-3.5 w-3.5 animate-spin" />计算中…</>
                ) : (
                  <><Zap className="h-3.5 w-3.5" />预览精算结果</>
                )}
              </button>
            )}
            {(estimate || manualMode) && !applied && (
              <button
                type="button"
                onClick={handleApply}
                disabled={applying || (manualMode && !manualElec && !manualWater && !manualGas)}
                className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-emerald-600 py-2 text-xs font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-50"
              >
                {applying ? (
                  <><Loader2 className="h-3.5 w-3.5 animate-spin" />写入中…</>
                ) : (
                  <><CheckCircle2 className="h-3.5 w-3.5" />确认更新成本</>
                )}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
