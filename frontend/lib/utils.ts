import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * 需要走代理的图片域名（安居客/58同城有防盗链）
 */
const PROXY_HOSTS = [
  'anjuke.com', 'ajkimg.com',
  '58.com', '58img.com', 'wangpan58.com',
];

function needsProxy(url: string): boolean {
  try {
    const { hostname } = new URL(url);
    return PROXY_HOSTS.some((h) => hostname === h || hostname.endsWith(`.${h}`));
  } catch {
    return false;
  }
}

/**
 * 将图片URL转换为代理URL（如果需要）。
 * 安居客/58同城的图片有防盗链，需要后端代理注入 Referer 才能加载。
 * 其余平台直接返回原始 URL（前端用 referrerPolicy="no-referrer" 即可）。
 */
export function getProxiedImageUrl(url: string | undefined | null): string {
  if (!url) return '';
  if (!needsProxy(url)) return url;
  return `/api/img-proxy?url=${encodeURIComponent(url)}`;
}
