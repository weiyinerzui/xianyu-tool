import axios from 'axios';

const api = axios.create({ baseURL: '/api/v1' });

// 违禁词检测
export const bannedCheck = (text: string) =>
  api.post('/banned/check', { text }).then(r => r.data);
export const bannedCheckBatch = (texts: string[]) =>
  api.post('/banned/check-batch', { texts }).then(r => r.data);

// 曝光诊断
export const diagnose = (item: Record<string, unknown>) =>
  api.post('/diagnosis/diagnose', item).then(r => r.data);

// 标题优化
export const titleScore = (title: string, core_keyword = '') =>
  api.post('/title/score', { title, core_keyword }).then(r => r.data);
export const titleGenerate = (params: Record<string, string>) =>
  api.post('/title/generate', params).then(r => r.data);

// 采集与选品
export const crawlSearch = (keyword: string, category?: string) =>
  api.post('/crawl/search', { keyword, category }).then(r => r.data);
export const productsSearch = (params: Record<string, unknown>) =>
  api.get('/products/search', { params }).then(r => r.data);
export const productsStats = (keyword?: string) =>
  api.get('/products/stats', { params: { keyword } }).then(r => r.data);

// 风控
export const guardStatus = () => api.get('/guard/status').then(r => r.data);
export const guardReset = () => api.post('/guard/reset').then(r => r.data);

// 登录态
export const sessionStatus = () => api.get('/session/status').then(r => r.data);
export const sessionImport = (cookies: Record<string, string>) =>
  api.post('/session/import', { cookies }).then(r => r.data);

// 调度器
export const schedulerStatus = () => api.get('/scheduler/status').then(r => r.data);
export const schedulerRun = () => api.post('/scheduler/run').then(r => r.data);
export const schedulerSetKeywords = (keywords: string[]) =>
  api.post('/scheduler/keywords', { keywords }).then(r => r.data);

// 看板
export const dashboardOverview = (keyword?: string) =>
  api.get('/dashboard/overview', { params: { keyword } }).then(r => r.data);
export const dashboardPriceDist = (keyword?: string, bins = 10) =>
  api.get('/dashboard/price-distribution', { params: { keyword, bins } }).then(r => r.data);
export const dashboardTopProducts = (sort_by = 'hot_score', limit = 20) =>
  api.get('/dashboard/top-products', { params: { sort_by, limit } }).then(r => r.data);
export const dashboardKeywordRanking = (limit = 20) =>
  api.get('/dashboard/keyword-ranking', { params: { limit } }).then(r => r.data);
export const dashboardCategoryDist = () =>
  api.get('/dashboard/category-distribution').then(r => r.data);
export const dashboardPublishTrend = (keyword?: string) =>
  api.get('/dashboard/publish-trend', { params: { keyword } }).then(r => r.data);

// 竞品
export const competitorsTopSellers = (limit = 20) =>
  api.get('/competitors/top-sellers', { params: { limit } }).then(r => r.data);
export const competitorsNewListings = (hours = 24, limit = 50) =>
  api.get('/competitors/new-listings', { params: { hours, limit } }).then(r => r.data);
export const competitorsPriceChanges = (keyword?: string) =>
  api.get('/competitors/price-changes', { params: { keyword } }).then(r => r.data);

// LLM
export const llmStatus = () => api.get('/llm/status').then(r => r.data);
export const llmOptimizeTitle = (title: string, core_keyword = '', category = '') =>
  api.post('/llm/optimize-title', { title, core_keyword, category }).then(r => r.data);
export const llmGenerateDescription = (title: string, category = '', key_features = '') =>
  api.post('/llm/generate-description', { title, category, key_features }).then(r => r.data);

export default api;
