/**
 * Mock API 总入口 — 演示模式下所有后端请求由此处理
 * 路径: /api/mock/[...path]
 *
 * 覆盖的后端路由：
 *   POST /api/backend/chat              → 模拟 AI 对话解析
 *   POST /api/backend/search/start      → 返回 demo task_id
 *   GET  /api/backend/search/status/:id → 直接返回 done + mock数据
 *   POST /api/backend/search/sort       → 返回 mock数据
 *   POST /api/backend/search/precise_batch_stream → SSE mock进度
 *   POST /api/backend/listings/review   → 返回 mock AI点评
 *   POST /api/backend/agent/ask         → 返回 mock 问答
 *   POST /api/backend/agent/inquiry     → 返回 mock 站内信
 *   其余路由                             → 返回空成功响应
 */
import { NextRequest, NextResponse } from 'next/server';
import {
  MOCK_SEARCH_RESPONSE,
  MOCK_REQUIREMENT,
  MOCK_CHAT_REPLIES,
} from '@/lib/mockData';

// 模拟延迟
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ── 保障房政策数据库（多城市）──────────────────────────────────
const HOUSING_POLICY_DB: Record<string, any> = {
  广州: {
    public_rental: {
      name: '公共租赁住房',
      apply_url: 'https://fgj.gz.gov.cn',
      app: '穗好办',
      conditions: ['本市户籍或持有居住证', '家庭月人均收入低于2865元', '在穗无自有住房'],
      rent_discount: '市场租金 30%-60%',
      notes: '申请周期约3-6个月，需提供收入证明、社保证明',
    },
    talent_apartment: {
      name: '人才公寓',
      apply_url: 'https://hr.gz.gov.cn',
      app: '广州人才服务',
      conditions: ['本科及以上学历', '落户广州', '年龄45周岁以下', '在穗无自有住房'],
      rent_discount: '市场租金 70%-85%',
      notes: '各区政策不同，天河区/南沙区名额较多',
    },
    youth_apartment: {
      name: '青年公寓（新就业）',
      apply_url: 'https://house.gz.gov.cn',
      app: null,
      conditions: ['35周岁以下', '在穗就业满半年', '未在穗购房'],
      rent_discount: '市场租金 75%-90%',
      notes: '主要分布在科学城、知识城、南沙等产业园区',
    },
  },
  深圳: {
    public_rental: {
      name: '公共租赁住房',
      apply_url: 'https://zjj.sz.gov.cn',
      app: 'i深圳',
      conditions: ['深户或持深圳市居住证', '家庭月人均收入低于4814元', '在深无房'],
      rent_discount: '市场租金 30%',
      notes: '轮候排序制，户籍优先；可同时申请安居房',
    },
    talent_apartment: {
      name: '人才住房',
      apply_url: 'https://zjj.sz.gov.cn',
      app: 'i深圳',
      conditions: ['本科及以上或中级职称', '深户或持人才认定证明', '在深连续社保6个月+'],
      rent_discount: '市场租金 60%',
      notes: '可申请购买产权人才住房；最高可获租房补贴30000元',
    },
    youth_apartment: {
      name: '安居房（青年）',
      apply_url: 'https://zjj.sz.gov.cn',
      app: 'i深圳',
      conditions: ['35周岁以下未婚或新婚', '在深就业并缴纳社保', '在深无房'],
      rent_discount: '市场价 50%-60%',
      notes: '宝安、龙华、坪山供给量大；摇号选房',
    },
  },
  北京: {
    public_rental: {
      name: '公共租赁住房',
      apply_url: 'https://zjw.beijing.gov.cn',
      app: '北京住房',
      conditions: ['本市户籍3口之家年收入低于10万', '人均住房面积低于15㎡'],
      rent_discount: '市场租金 30%',
      notes: '需通过区住建委审核，轮候时间较长',
    },
    talent_apartment: {
      name: '人才公租房',
      apply_url: 'https://rsj.beijing.gov.cn',
      app: '北京人社',
      conditions: ['本科及以上或高级职称', '工作单位在京', '在京无房'],
      rent_discount: '市场租金 60%-70%',
      notes: '海淀、朝阳、昌平、大兴均有项目；可享受租金补贴',
    },
    youth_apartment: {
      name: '青年公寓',
      apply_url: 'https://zjw.beijing.gov.cn',
      app: null,
      conditions: ['35周岁以下', '在京就业', '在京无房'],
      rent_discount: '市场租金 70%-80%',
      notes: '主要在中关村、亦庄等产业园区周边',
    },
  },
  上海: {
    public_rental: {
      name: '公共租赁住房',
      apply_url: 'https://zjw.sh.gov.cn',
      app: '随申办',
      conditions: ['本市户籍或持有居住证', '在沪稳定就业满1年', '家庭住房困难'],
      rent_discount: '市场租金 80%-90%',
      notes: '区级和市级两类，市级面向产业人才',
    },
    talent_apartment: {
      name: '人才公寓',
      apply_url: 'https://rsj.sh.gov.cn',
      app: '上海人社',
      conditions: ['硕士及以上或高级职称', '在沪用人单位推荐', '在沪无房'],
      rent_discount: '市场租金 60%-80%',
      notes: '张江、临港、漕河泾等高新区配套较完善',
    },
    youth_apartment: {
      name: '租赁住房',
      apply_url: 'https://zjw.sh.gov.cn',
      app: '随申办',
      conditions: ['35周岁以下青年', '在沪就业', '无房'],
      rent_discount: '市场租金 80%-95%',
      notes: '集中式长租公寓，由上海地产、城投等国企运营',
    },
  },
  成都: {
    public_rental: {
      name: '公共租赁住房',
      apply_url: 'https://cdzj.chengdu.gov.cn',
      app: '天府市民云',
      conditions: ['本市户籍或居住证', '家庭月人均收入低于2105元', '在蓉无房'],
      rent_discount: '市场租金 50%',
      notes: '高新区、天府新区房源较多',
    },
    talent_apartment: {
      name: '人才公寓',
      apply_url: 'https://hrss.chengdu.gov.cn',
      app: '蓉e行',
      conditions: ['本科及以上学历', '在蓉用人单位工作', '在蓉无房'],
      rent_discount: '市场租金 70%；满5年可购买',
      notes: '可享每月600-1500元租房补贴；天府人才计划专项支持',
    },
    youth_apartment: {
      name: '青年人才驿站',
      apply_url: 'https://hrss.chengdu.gov.cn',
      app: '蓉漂码',
      conditions: ['35周岁以下', '来蓉求职7天内', '本科及以上学历'],
      rent_discount: '免费入住7天',
      notes: '面向应届毕业生求职，全市20+驿站',
    },
  },
  杭州: {
    public_rental: {
      name: '公共租赁住房',
      apply_url: 'https://zjj.hangzhou.gov.cn',
      app: '杭州办事服务',
      conditions: ['本市户籍或持居住证', '家庭月人均收入低于4860元', '在杭无房'],
      rent_discount: '市场租金 60%-80%',
      notes: '可申请货币补贴或实物配租',
    },
    talent_apartment: {
      name: '人才租赁房',
      apply_url: 'https://rsj.hangzhou.gov.cn',
      app: '杭州人才码',
      conditions: ['本科及以上或B-E类人才', '在杭就业', '在杭无房'],
      rent_discount: '市场租金 70%-90%',
      notes: '可享购房补贴最高800万；A类人才配套住房',
    },
    youth_apartment: {
      name: '蓝领公寓',
      apply_url: 'https://zjj.hangzhou.gov.cn',
      app: null,
      conditions: ['在杭就业的青年职工', '家庭在杭无房'],
      rent_discount: '低于市场价 30%-50%',
      notes: '主要服务于产业工人和新就业人员',
    },
  },
};

function buildHousingResponse(city: string) {
  const cityData = HOUSING_POLICY_DB[city];
  if (cityData) {
    return {
      city,
      source: 'db' as const,
      ...cityData,
      fetched_at: new Date().toISOString(),
      is_stale: false,
      disclaimer: '政策信息以当地住建局/人社局官网公告为准，演示数据仅供参考',
    };
  }
  // 未收录城市：返回 AI 生成兜底
  return {
    city,
    source: 'ai' as const,
    ai_summary: `${city} 暂未收录到内置数据库。演示模式下提供如下通用参考：\n\n1. 公共租赁住房：面向户籍困难家庭和稳定就业外来人员\n2. 人才公寓：面向高学历人才，通常本科起步\n3. 青年公寓：面向35周岁以下新就业人员\n\n请前往 ${city} 当地住建局官网查询最新政策。`,
    fetched_at: new Date().toISOString(),
    is_stale: false,
    disclaimer: '演示模式 AI 生成内容，请以当地官网为准',
  };
}

export async function GET(
  req: NextRequest,
  { params }: { params: { path: string[] } },
) {
  const path = params.path.join('/');

  // search/status/:task_id — 模拟"搜索完成"
  if (path.startsWith('search/status/')) {
    await delay(800);
    return NextResponse.json({
      task_id: path.replace('search/status/', ''),
      status: 'done',
      progress: '完成',
      result: MOCK_SEARCH_RESPONSE,
    });
  }

  // housing/policy_info GET — 保障房政策查询
  if (path === 'housing/policy_info') {
    await delay(400);
    const city = new URL(req.url).searchParams.get('city') || '广州';
    return NextResponse.json(buildHousingResponse(city));
  }

  // housing/stale_check
  if (path === 'housing/stale_check') {
    return NextResponse.json({ stale_cities: [], total: 0 });
  }

  return NextResponse.json({ ok: true });
}

export async function POST(
  req: NextRequest,
  { params }: { params: { path: string[] } },
) {
  const path = params.path.join('/');
  let body: any = {};
  try { body = await req.json(); } catch { /* empty body */ }

  // ── AI 对话 ──────────────────────────────────────────────────
  if (path === 'chat') {
    await delay(600);
    const lastMsg = body?.messages?.at(-1)?.content || '';
    const lc = lastMsg.toLowerCase();
    let replyKey = 'default';
    if (lc.includes('价格') || lc.includes('预算') || lc.includes('多少钱')) replyKey = 'price';
    else if (lc.includes('通勤') || lc.includes('分钟') || lc.includes('远近')) replyKey = 'commute';
    else if (lc.includes('重置') || lc.includes('换个') || lc.includes('重新')) replyKey = 'reset';

    return NextResponse.json({
      reply: MOCK_CHAT_REPLIES[replyKey],
      requirement: MOCK_REQUIREMENT,
      is_ready: true,
      clarifying_questions: [],
    });
  }

  // ── 搜索提交（异步任务模式）────────────────────────────────────
  if (path === 'search/start') {
    await delay(300);
    return NextResponse.json({ task_id: 'demo-task-001' });
  }

  // ── 仅排序 ─────────────────────────────────────────────────────
  if (path === 'search/sort') {
    await delay(200);
    const sortMode = body?.sort_mode || '综合';
    const recs = [...MOCK_SEARCH_RESPONSE.recommendations];
    if (sortMode === '价格') {
      recs.sort((a, b) => a.cost.total - b.cost.total);
    } else if (sortMode === '通勤') {
      recs.sort((a, b) => (a.commute?.best_duration_min ?? 99) - (b.commute?.best_duration_min ?? 99));
    } else if (sortMode === '面积') {
      recs.sort((a, b) => (b.listing.area ?? 0) - (a.listing.area ?? 0));
    }
    return NextResponse.json({
      ...MOCK_SEARCH_RESPONSE,
      recommendations: recs.map((r, i) => ({ ...r, rank: i + 1 })),
    });
  }

  // ── 批量精算 SSE 流（mock进度动画）────────────────────────────
  if (path === 'search/precise_batch_stream') {
    const encoder = new TextEncoder();
    const listings = MOCK_SEARCH_RESPONSE.recommendations;
    const total = Math.min(listings.length, 5);

    const stream = new ReadableStream({
      async start(controller) {
        for (let i = 0; i < total; i++) {
          await delay(700);
          const label = listings[i].listing.community || `房源${i + 1}`;
          controller.enqueue(encoder.encode(
            `data: ${JSON.stringify({ type: 'progress', current: i + 1, total, label, success: i + 1, fail: 0 })}\n\n`,
          ));
        }
        await delay(400);
        // done 事件携带完整结果
        const doneResult = {
          ...MOCK_SEARCH_RESPONSE,
          recommendations: MOCK_SEARCH_RESPONSE.recommendations.map((r) => ({
            ...r,
            commute: r.commute
              ? { ...r.commute, results: r.commute.results.map((c) => ({ ...c, map_provider: 'amap' as const })) }
              : r.commute,
          })),
          round_attempted: total,
          round_success: total,
          round_fail: 0,
        };
        controller.enqueue(encoder.encode(
          `data: ${JSON.stringify({ type: 'done', result: doneResult })}\n\n`,
        ));
        controller.close();
      },
    });

    return new Response(stream, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
      },
    });
  }

  // ── 单条精算 ────────────────────────────────────────────────
  if (path === 'search/precise_one') {
    await delay(1200);
    return NextResponse.json({
      listing_id: body?.listing_id || 'demo-001',
      success: true,
      source: 'amap',
      duration_min: 18,
    });
  }

  // ── AI 房源点评 ─────────────────────────────────────────────
  if (path === 'listings/review') {
    await delay(1500);
    const listing = body?.listing;
    const price = listing?.price_base || 3000;
    const area = listing?.area || 60;
    const score = price < 3000 ? 8.2 : price < 4000 ? 7.8 : 7.2;
    return NextResponse.json({
      review: {
        score,
        summary: `${area}㎡整租，月租¥${price}，性价比${score >= 8 ? '较高' : '中等'}，通勤便利`,
        pros: ['精装修拎包入住', '有电梯高楼层', '近地铁步行可达', '小区物业正规'],
        cons: ['中介费需确认', '周边餐饮一般'],
        tags: ['精装修', '近地铁', '电梯房'],
        generated_at: new Date().toISOString(),
        model: 'deepseek-chat (demo)',
      },
      cached: false,
    });
  }

  // ── 详情页二次抓取 ───────────────────────────────────────────
  if (path === 'listings/detail') {
    await delay(800);
    return NextResponse.json({
      success: true,
      deposit_type: '押一付三',
      water_type: '民水',
      electricity_type: '民电',
      gas_type: '天然气',
      elevator: true,
      move_in: '随时',
      facilities: ['冰箱', '洗衣机', '空调', '热水器', '宽带', '天然气'],
      images: [
        'https://images.unsplash.com/photo-1555041469-a586c61ea9bc?w=800&h=600&fit=crop',
        'https://images.unsplash.com/photo-1484154218962-a197022b5858?w=800&h=600&fit=crop',
        'https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?w=800&h=600&fit=crop',
        'https://images.unsplash.com/photo-1507089947368-19c1da9775ae?w=800&h=600&fit=crop',
      ],
      description: '（演示数据）精装修两房，南北通透，采光好，家电齐全，拎包入住。小区环境优美，24小时保安。',
      cost_updated: false,
    });
  }

  // ── Agent 问答 ─────────────────────────────────────────────
  if (path === 'agent/ask') {
    await delay(800);
    const q = (body?.question || '').toLowerCase();
    let answer = '好问题！根据当前房源的信息，综合水电、物业、中介费摊销后，真实月支出比标价高约 10-15%。建议重点关注水电类型（民水民电 vs 商水商电），商电比民电贵约 50%。';
    if (q.includes('水电')) answer = '【水电费说明】\n\n民水：约 7.5元/吨，单人每月约 4吨，合计约 30元\n民电：约 0.8元/度，正常使用约 100度/月，合计约 80元\n商电：约 1.2元/度，比民电贵 50%，每月多支出约 40元\n\n建议看房时直接问中介：用的是民水民电还是商水商电？';
    if (q.includes('押金') || q.includes('押付')) answer = '【押付方式说明】\n\n押一付一：押金1个月，每月付1个月\n押一付三：押金1个月，每次付3个月（最常见）\n押二付一：押金2个月，每月付1个月\n押二付三：押金2个月，每次付3个月\n\n押金越多，资金占用成本越高（按年化3%估算）。押一付三的年化成本约 月租×3%÷12。';
    return NextResponse.json({ answer, is_inquiry_template: false });
  }

  // ── 站内信生成 ────────────────────────────────────────────
  if (path === 'agent/inquiry' || path === 'agent/batch_inquiry') {
    await delay(600);
    return NextResponse.json({
      listing_id: body?.listing_id || 'demo-001',
      message: `您好，我在平台上看到您发布的房源，有几个问题想确认一下：\n\n1. 请问用的是民水民电还是商水商电？每月水电大概多少钱？\n2. 燃气和网费是否包含在内？\n3. 物业费每月大概多少？\n4. 是否支持押一付一？最短租期是多久？\n5. 房间的设施是否如图所示完整？空调、热水器是否正常使用？\n\n期待您的回复，谢谢！\n\n---站内信---\n（演示模式生成的站内信模板）`,
      listing_url: 'https://gz.lianjia.com/zufang/demo',
      platform_label: '链家',
      copy_hint: '复制上方文字，前往链家房源页粘贴发送给房东',
      results: [],
      total: 1,
    });
  }

  // ── 水电估算 ──────────────────────────────────────────────
  if (path === 'utility/estimate' || path === 'utility/apply') {
    await delay(400);
    return NextResponse.json({
      electricity: 120, water: 35, gas: 25,
      total_utility: 180, electricity_kwh: 150, water_tons: 4.5, gas_m3: 6.5,
      notes: { electricity: '基础40度 + 空调80度(正常开) + 热水器30度 = 150度 × ¥0.8/度' },
      delta_vs_default: 20, delta_label: '比默认估算多 ¥20/月',
      listing_id: body?.listing_id, success: true, new_total: 3700, message: '已更新',
    });
  }

  // ── 房补分析 ─────────────────────────────────────────────
  if (path === 'subsidy/analyze') {
    await delay(800);
    return NextResponse.json({
      summary: '骑行 20 分钟以内或公共交通 30 分钟以内',
      conditions: [
        { mode: 'riding', max_minutes: 20, description: '骑行不超过20分钟' },
        { mode: 'transit', max_minutes: 30, description: '公共交通不超过30分钟' },
      ],
      logic: 'any',
      recommended_max_minutes: 30,
      recommended_modes: ['riding', 'transit'],
      has_distance_limit: false,
      distance_km: null,
      notes: '（演示模式：已解析为骑行20分钟或公交30分钟）',
      raw_parsed: {},
    });
  }

  // ── 保障房政策（POST：policy_ai 兜底）────────────────────────
  if (path === 'housing/policy_info' || path === 'housing/policy_ai') {
    await delay(600);
    const city = body?.city || new URL(req.url).searchParams.get('city') || '广州';
    return NextResponse.json(buildHousingResponse(city));
  }

  // ── session 操作 ──────────────────────────────────────────
  if (path.startsWith('search/session/') || path === 'search/cache') {
    return NextResponse.json({ message: 'ok', deleted: 1 });
  }

  // ── subsidy/filter ─────────────────────────────────────────
  if (path === 'subsidy/filter') {
    await delay(300);
    return NextResponse.json({
      matched_listing_ids: MOCK_SEARCH_RESPONSE.recommendations.map((r) => r.listing.id),
      total_checked: 5, total_matched: 4, no_coord_count: 1,
      dest_coord: [113.3233, 23.1201] as [number, number],
      message: '演示：4套房源在距离范围内',
    });
  }

  // 其余路由：返回空成功
  return NextResponse.json({ ok: true, demo: true });
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: { path: string[] } },
) {
  return NextResponse.json({ message: 'ok', deleted: 1 });
}
