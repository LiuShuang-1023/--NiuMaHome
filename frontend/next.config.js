/** @type {import('next').NextConfig} */
const isDemoMode = process.env.NEXT_PUBLIC_DEMO_MODE === 'true';

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    // 演示模式：/api/backend/* → 本地 mock 路由，无需后端
    if (isDemoMode) {
      return [
        {
          source: '/api/backend/:path*',
          destination: '/api/mock/:path*',
        },
      ];
    }
    // 正常模式：转发到本地后端
    return [
      {
        source: '/api/backend/:path*',
        destination: 'http://localhost:8001/api/:path*',
      },
    ];
  },
  images: {
    remotePatterns: [
      { protocol: 'https', hostname: '**.lianjia.com' },
      { protocol: 'https', hostname: '**.ljcdn.com' },
      { protocol: 'https', hostname: '**.fang.com' },
      { protocol: 'https', hostname: '**.anjuke.com' },
      { protocol: 'https', hostname: '**.unsplash.com' },
      { protocol: 'https', hostname: 'images.unsplash.com' },
    ],
  },
};

module.exports = nextConfig;
