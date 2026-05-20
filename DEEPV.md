## DeepV Code Added Memories

- 项目路径：D:\xinwj\newwj（牛马归栏 NiuMaHome）。重要文档：docs/PRD.md（产品需求）、docs/CHANGELOG.md（版本日志）、README.md（启动说明）、.env.local（密钥，gitignore）。

- 技术栈：Next.js 14 前端 + FastAPI 后端 + DeepSeek AI + 高德/腾讯/百度地图 API + 链家/贝壳/安居客/58同城爬虫。后端启动：cd backend && uvicorn app.main:app --port 8001 --reload。前端：cd frontend && npm run dev（localhost:3000）。next.config.js 代理端口 8001。

- 当前版本 v0.9.2（2026-05-20），架构摘要：
  - 前端：LandingPage（Hero+4Tab+功能介绍+初衷+Roadmap+更新日志+意见反馈）；二级页面三列布局（左300px AI对话/需求/房补；中1fr 平台Tab+排序+批量精算+房源列表；右280px 社交媒体+保障房）。
  - 后端31条路由：chat/search（异步任务+轮询）/listings/commute/utility/agent/subsidy/housing。
  - 存储：SQLite session DB（WAL，30分钟TTL自动清理）；daily_cache（当日爬取缓存）；commute_store（精算结果持久化）；housing_policy.db（保障房政策缓存，超120天标记stale）。
  - 地图：高德→腾讯→百度三地图协同，合计21000次/天免费。离线估算覆盖100%房源，用户主动点击批量精算/单条精算升级实时数据。
  - 爬虫：链家/贝壳（需LIANJIA_COOKIE/BEIKE_COOKIE）；安居客（ANJUKE_COOKIE可选）；58同城（WUBA_COOKIE必填，JS渲染+xxzl指纹，无Cookie返回空）。

- 关键配置（.env.local）：LLM_PROVIDER=deepseek，DEEPSEEK_API_KEY，AMAP_KEY，TENCENT_KEY=ZBUBZ-3UC6A-WVXKB-CBE5H-JBTGO-2UF7O（域名白名单留空），BAIDU_AK，BAIDU_SK，LIANJIA_COOKIE，BEIKE_COOKIE，ANJUKE_COOKIE，WUBA_COOKIE。

- 前端组件清单：LandingPage.tsx（首页）、AgentAssistant.tsx（右下悬浮AI助手，可拖拽）、FavoritesPanel.tsx（收藏夹）、ChatBox.tsx（AI对话）、RequirementPanel.tsx、ListingCard.tsx、ListingDetailModal.tsx（含UtilityWizard）、SubsidyAnalyzer.tsx、PublicHousingPanel.tsx、SocialMediaListings.tsx、OnboardingGuide.tsx、TopBar.tsx、Tooltip.tsx。

- 已知限制：58同城无Cookie必返回空（JS渲染+指纹验证，需Playwright方案）；链家/贝壳Cookie过期需重新从浏览器复制；高德个人Key QPS=3（Semaphore节流已处理）；批量精算上限10条/轮（约15秒）；cost写回后卡片月支出不实时刷新（需重新排序）。
