/**
 * 图片代理 API Route
 * GET /api/img-proxy?url=<encoded_url>
 *
 * 解决安居客/58同城图片防盗链问题：
 * 这两个平台的图片服务器检查 Referer 头，浏览器直接加载会被403。
 * 通过后端代理转发，自动注入对应平台的 Referer 头。
 *
 * 支持的域名映射：
 *   *.anjuke.com / *.ajkimg.com → Referer: https://www.anjuke.com/
 *   *.58.com / *.58img.com / *.wangpan58.com → Referer: https://bj.58.com/
 *   *.lianjia.com / *.ljcdn.com → Referer: https://www.lianjia.com/
 *   *.ke.com / *.bikecdn.com   → Referer: https://www.ke.com/
 */

import { NextRequest, NextResponse } from 'next/server';

// Cloudflare Pages 必须用 Edge Runtime
export const runtime = 'edge';

// 域名 → Referer 映射表
const REFERER_MAP: Array<{ pattern: RegExp; referer: string }> = [
  { pattern: /anjuke\.com|ajkimg\.com/i,          referer: 'https://www.anjuke.com/' },
  { pattern: /58\.com|58img\.com|wangpan58\.com/i, referer: 'https://bj.58.com/' },
  { pattern: /lianjia\.com|ljcdn\.com/i,           referer: 'https://www.lianjia.com/' },
  { pattern: /ke\.com|bikecdn\.com/i,              referer: 'https://www.ke.com/' },
];

// 允许代理的域名白名单（防止被滥用代理任意 URL）
const ALLOWED_HOSTS = [
  'anjuke.com', 'ajkimg.com',
  '58.com', '58img.com', 'wangpan58.com',
  'lianjia.com', 'ljcdn.com',
  'ke.com', 'bikecdn.com', 'beke.com',
];

function isAllowedHost(hostname: string): boolean {
  return ALLOWED_HOSTS.some((h) => hostname === h || hostname.endsWith(`.${h}`));
}

function getReferer(url: string): string {
  for (const { pattern, referer } of REFERER_MAP) {
    if (pattern.test(url)) return referer;
  }
  return '';
}

export async function GET(req: NextRequest) {
  const rawUrl = req.nextUrl.searchParams.get('url');
  if (!rawUrl) {
    return new NextResponse('Missing url parameter', { status: 400 });
  }

  let targetUrl: URL;
  try {
    targetUrl = new URL(rawUrl);
  } catch {
    return new NextResponse('Invalid url', { status: 400 });
  }

  // 安全检查：只允许 https，且在白名单域名内
  if (targetUrl.protocol !== 'https:') {
    return new NextResponse('Only https URLs allowed', { status: 403 });
  }
  if (!isAllowedHost(targetUrl.hostname)) {
    return new NextResponse('Host not allowed', { status: 403 });
  }

  const referer = getReferer(rawUrl);

  try {
    const upstream = await fetch(rawUrl, {
      headers: {
        'User-Agent':
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        Referer: referer,
        Accept: 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
      },
      // Next.js App Router fetch 默认缓存，图片缓存 1 小时
      next: { revalidate: 3600 },
    });

    if (!upstream.ok) {
      return new NextResponse(`Upstream ${upstream.status}`, { status: upstream.status });
    }

    const contentType = upstream.headers.get('content-type') || 'image/jpeg';
    const buffer = await upstream.arrayBuffer();

    return new NextResponse(buffer, {
      status: 200,
      headers: {
        'Content-Type': contentType,
        'Cache-Control': 'public, max-age=3600, s-maxage=3600',
        'Access-Control-Allow-Origin': '*',
      },
    });
  } catch (e: any) {
    console.error('[img-proxy] fetch error:', e?.message);
    return new NextResponse('Proxy fetch failed', { status: 502 });
  }
}
