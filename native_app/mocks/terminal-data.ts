export type TerminalMarketCategory = 'stocks' | 'crypto' | 'forex' | 'futures';
export type WatchlistMode = 'watchlist' | 'hot' | 'recent' | 'filters';
export type ChartInterval = '1m' | '5m' | '15m' | '1h' | '4h' | '1D' | '1W';
export type ChartType = 'candles' | 'area' | 'line';
export type IndicatorKey = 'MA' | 'EMA' | 'MACD' | 'RSI' | 'VOL';
export type DrawToolKey = 'trendline' | 'horizontal' | 'fibonacci' | 'note';
export type UtilityToolKey = 'crosshair' | 'compare' | 'reset' | 'fullscreen' | 'capture';
export type BottomTabKey = 'positions' | 'orders' | 'fills' | 'news' | 'events';
export type DataState = 'ready' | 'loading' | 'empty' | 'error';

export interface TerminalSymbol {
  id: string;
  code: string;
  name: string;
  marketCategory: TerminalMarketCategory;
  marketLabel: string;
  latestPrice: number;
  change: number;
  changePct: number;
  dayHigh: number;
  dayLow: number;
  volumeLabel: string;
  turnoverLabel: string;
  tags: string[];
  hotRank: number;
  recentRank: number;
  watchlist: boolean;
  filterTags: string[];
}

export interface TerminalMiniMarket {
  code: string;
  label: string;
  price: string;
  changePct: number;
  sparkline: number[];
}

export interface TerminalCandle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface TerminalChartSeries {
  candles: TerminalCandle[];
  ma: number[];
  ema: number[];
  buyMarkers: { index: number; label: string; price: number }[];
  sellMarkers: { index: number; label: string; price: number }[];
}

export interface TerminalOrderBookLevel {
  price: number;
  size: number;
  total: number;
}

export interface TerminalTradePrint {
  time: string;
  price: number;
  size: number;
  side: 'buy' | 'sell';
}

export interface TerminalPositionRow {
  account: string;
  size: string;
  entry: string;
  mark: string;
  pnl: string;
  leverage: string;
}

export interface TerminalOrderRow {
  time: string;
  side: 'buy' | 'sell';
  type: string;
  price: string;
  quantity: string;
  status: string;
}

export interface TerminalFillRow {
  time: string;
  side: 'buy' | 'sell';
  price: string;
  quantity: string;
  fee: string;
  venue: string;
}

export interface TerminalNewsRow {
  time: string;
  source: string;
  headline: string;
  impact: string;
}

export interface TerminalEventRow {
  time: string;
  event: string;
  value: string;
  consensus: string;
  status: string;
}

export interface TerminalPanelDataset {
  positions: TerminalPositionRow[];
  orders: TerminalOrderRow[];
  fills: TerminalFillRow[];
  news: TerminalNewsRow[];
  events: TerminalEventRow[];
}

export interface TerminalStateMap {
  chart: DataState;
  orderBook: DataState;
  timeSales: DataState;
  positions: DataState;
  orders: DataState;
  fills: DataState;
  news: DataState;
  events: DataState;
}

const CANDLE_COUNT = 30;

function buildCandles(
  startPrice: number,
  deltas: number[],
  baseVolume: number,
  prefix: string
): TerminalChartSeries {
  const candles: TerminalCandle[] = [];
  let cursor = startPrice;

  for (let index = 0; index < CANDLE_COUNT; index += 1) {
    const delta = deltas[index % deltas.length] ?? 0;
    const open = cursor;
    const close = Number((open + delta).toFixed(2));
    const wickTop = Math.abs(delta) * 0.55 + 0.42 + ((index % 3) * 0.08);
    const wickBottom = Math.abs(delta) * 0.48 + 0.35 + ((index % 2) * 0.07);
    const high = Number((Math.max(open, close) + wickTop).toFixed(2));
    const low = Number((Math.min(open, close) - wickBottom).toFixed(2));
    const volume = Number((baseVolume + (index % 6) * baseVolume * 0.08 + Math.abs(delta) * baseVolume * 0.16).toFixed(0));

    candles.push({
      time: `${prefix}-${String(index + 1).padStart(2, '0')}`,
      open: Number(open.toFixed(2)),
      high,
      low,
      close,
      volume,
    });

    cursor = close;
  }

  const ma = candles.map((_, index) => {
    const window = candles.slice(Math.max(0, index - 4), index + 1);
    const value = window.reduce((sum, item) => sum + item.close, 0) / window.length;
    return Number(value.toFixed(2));
  });

  const ema: number[] = [];
  const smoothing = 2 / (6 + 1);
  candles.forEach((item, index) => {
    if (index === 0) {
      ema.push(item.close);
      return;
    }
    ema.push(Number((item.close * smoothing + ema[index - 1] * (1 - smoothing)).toFixed(2)));
  });

  return {
    candles,
    ma,
    ema,
    buyMarkers: [
      { index: 6, label: 'B1', price: candles[6]?.low ?? candles[0]?.low ?? startPrice },
      { index: 18, label: 'B2', price: candles[18]?.low ?? candles[0]?.low ?? startPrice },
    ],
    sellMarkers: [
      { index: 12, label: 'S1', price: candles[12]?.high ?? candles[0]?.high ?? startPrice },
      { index: 24, label: 'S2', price: candles[24]?.high ?? candles[0]?.high ?? startPrice },
    ],
  };
}

function buildOrderBook(
  mid: number,
  step: number,
  sizes: number[]
): { asks: TerminalOrderBookLevel[]; bids: TerminalOrderBookLevel[]; last: number } {
  const asks = sizes.map((size, index) => ({
    price: Number((mid + step * (index + 1)).toFixed(2)),
    size,
    total: sizes.slice(0, index + 1).reduce((sum, value) => sum + value, 0),
  }));
  const bids = sizes.map((size, index) => ({
    price: Number((mid - step * (index + 1)).toFixed(2)),
    size,
    total: sizes.slice(0, index + 1).reduce((sum, value) => sum + value, 0),
  }));

  return { asks: asks.reverse(), bids, last: mid };
}

function buildTrades(mid: number, step: number, sizes: number[]): TerminalTradePrint[] {
  return sizes.map((size, index) => ({
    time: `14:${String(18 + index).padStart(2, '0')}:${index % 2 === 0 ? '06' : '42'}`,
    price: Number((mid + (index % 2 === 0 ? step : -step * 0.8) * (index % 3)).toFixed(2)),
    size,
    side: index % 2 === 0 ? 'buy' : 'sell',
  }));
}

function buildPanelData(symbol: TerminalSymbol): TerminalPanelDataset {
  const price = symbol.latestPrice;
  const signed = symbol.changePct >= 0 ? '+' : '';

  return {
    positions: Array.from({ length: 5 }, (_, index) => ({
      account: ['主仓', '策略A', '策略B', '套保', '模拟'][index] ?? `账户${index + 1}`,
      size: `${(1.2 + index * 0.4).toFixed(2)} ${symbol.code}`,
      entry: `${(price - 0.8 + index * 0.11).toFixed(2)}`,
      mark: `${price.toFixed(2)}`,
      pnl: `${signed}${(symbol.changePct * (index + 1) * 0.37).toFixed(2)}%`,
      leverage: ['1x', '2x', '3x', '1x', '5x'][index] ?? '1x',
    })),
    orders: Array.from({ length: 5 }, (_, index) => ({
      time: `14:${String(5 + index).padStart(2, '0')}`,
      side: index % 2 === 0 ? 'buy' : 'sell',
      type: ['限价', '限价', '止损', '市价', '限价'][index] ?? '限价',
      price: `${(price + (index - 2) * 0.35).toFixed(2)}`,
      quantity: `${(0.5 + index * 0.2).toFixed(2)}`,
      status: ['挂单中', '挂单中', '待触发', '部分成交', '挂单中'][index] ?? '挂单中',
    })),
    fills: Array.from({ length: 5 }, (_, index) => ({
      time: `13:${String(20 + index * 2).padStart(2, '0')}`,
      side: index % 2 === 0 ? 'buy' : 'sell',
      price: `${(price - 0.55 + index * 0.28).toFixed(2)}`,
      quantity: `${(0.24 + index * 0.08).toFixed(2)}`,
      fee: `${(0.3 + index * 0.06).toFixed(2)} USDT`,
      venue: ['主通道', '智能路由', '撮合池', '主通道', '智能路由'][index] ?? '主通道',
    })),
    news: Array.from({ length: 5 }, (_, index) => ({
      time: `${8 + index}:3${index}`,
      source: ['Bloomberg', '财联社', 'Reuters', '界面', 'Trading Desk'][index] ?? 'Desk',
      headline: `${symbol.name} 所属链条出现新的成交与预期变化，盘中关注上沿是否放量突破。`,
      impact: ['高', '中', '中', '低', '中'][index] ?? '中',
    })),
    events: Array.from({ length: 5 }, (_, index) => ({
      time: `${index + 1}h`,
      event: ['美国初请失业金', 'ETF净流入', '核心客户指引', '欧盘库存更新', '夜盘波动窗口'][index] ?? '事件',
      value: ['62.4', '1.8B', '上修', '收窄', '开启'][index] ?? '--',
      consensus: ['61.9', '1.2B', '持平', '持平', '观察'][index] ?? '--',
      status: ['待公布', '已确认', '跟进中', '待公布', '预热'][index] ?? '待公布',
    })),
  };
}

export const terminalSymbols: TerminalSymbol[] = [
  {
    id: 'BTCUSDT',
    code: 'BTCUSDT',
    name: 'Bitcoin',
    marketCategory: 'crypto',
    marketLabel: '加密',
    latestPrice: 98234.42,
    change: 1248.36,
    changePct: 1.29,
    dayHigh: 98980.4,
    dayLow: 96420.18,
    volumeLabel: '24h 18.4B',
    turnoverLabel: 'OI 7.2B',
    tags: ['现货', '永续', '龙头'],
    hotRank: 1,
    recentRank: 2,
    watchlist: true,
    filterTags: ['高流动', '强趋势'],
  },
  {
    id: 'ETHUSDT',
    code: 'ETHUSDT',
    name: 'Ethereum',
    marketCategory: 'crypto',
    marketLabel: '加密',
    latestPrice: 5148.77,
    change: 83.12,
    changePct: 1.64,
    dayHigh: 5199.2,
    dayLow: 5010.4,
    volumeLabel: '24h 9.8B',
    turnoverLabel: 'OI 3.1B',
    tags: ['现货', 'Layer1'],
    hotRank: 2,
    recentRank: 1,
    watchlist: true,
    filterTags: ['高流动', '主升'],
  },
  {
    id: 'NVDA',
    code: 'NVDA',
    name: 'NVIDIA',
    marketCategory: 'stocks',
    marketLabel: '股票',
    latestPrice: 1184.26,
    change: -12.44,
    changePct: -1.04,
    dayHigh: 1208.12,
    dayLow: 1171.44,
    volumeLabel: 'Vol 31.6M',
    turnoverLabel: 'Amt 37.9B',
    tags: ['NASDAQ', '主板', 'AI'],
    hotRank: 3,
    recentRank: 4,
    watchlist: true,
    filterTags: ['高关注', '算力'],
  },
  {
    id: 'TSLA',
    code: 'TSLA',
    name: 'Tesla',
    marketCategory: 'stocks',
    marketLabel: '股票',
    latestPrice: 282.74,
    change: 4.38,
    changePct: 1.57,
    dayHigh: 286.21,
    dayLow: 276.42,
    volumeLabel: 'Vol 88.2M',
    turnoverLabel: 'Amt 24.8B',
    tags: ['NASDAQ', '主板', '汽车'],
    hotRank: 4,
    recentRank: 3,
    watchlist: true,
    filterTags: ['热门', '波段'],
  },
  {
    id: 'EURUSD',
    code: 'EURUSD',
    name: 'Euro / US Dollar',
    marketCategory: 'forex',
    marketLabel: '外汇',
    latestPrice: 1.0942,
    change: 0.0019,
    changePct: 0.17,
    dayHigh: 1.0968,
    dayLow: 1.0912,
    volumeLabel: '24h FX 312B',
    turnoverLabel: 'DXY -0.21%',
    tags: ['现汇', '伦敦盘'],
    hotRank: 5,
    recentRank: 6,
    watchlist: false,
    filterTags: ['宏观', '趋势'],
  },
  {
    id: 'XAUUSD',
    code: 'XAUUSD',
    name: 'Gold Spot',
    marketCategory: 'forex',
    marketLabel: '外汇',
    latestPrice: 2388.6,
    change: 16.2,
    changePct: 0.68,
    dayHigh: 2394.8,
    dayLow: 2367.4,
    volumeLabel: '24h OTC 76B',
    turnoverLabel: 'Risk-off',
    tags: ['现货', '避险'],
    hotRank: 6,
    recentRank: 5,
    watchlist: true,
    filterTags: ['避险', '宏观'],
  },
  {
    id: 'NQ1!',
    code: 'NQ1!',
    name: 'Nasdaq Futures',
    marketCategory: 'futures',
    marketLabel: '期货',
    latestPrice: 18542.5,
    change: -74.2,
    changePct: -0.4,
    dayHigh: 18658.2,
    dayLow: 18488.1,
    volumeLabel: 'Vol 521k',
    turnoverLabel: 'Globex',
    tags: ['永续', '指数'],
    hotRank: 7,
    recentRank: 7,
    watchlist: false,
    filterTags: ['指数', '夜盘'],
  },
  {
    id: 'CL1!',
    code: 'CL1!',
    name: 'WTI Crude',
    marketCategory: 'futures',
    marketLabel: '期货',
    latestPrice: 88.42,
    change: 1.98,
    changePct: 2.29,
    dayHigh: 89.16,
    dayLow: 85.73,
    volumeLabel: 'Vol 612k',
    turnoverLabel: 'OI 1.8M',
    tags: ['期货', '能源'],
    hotRank: 8,
    recentRank: 8,
    watchlist: true,
    filterTags: ['商品', '地缘'],
  },
];

export const terminalMiniMarkets: TerminalMiniMarket[] = [
  { code: 'BTC', label: 'Bitcoin', price: '98.2k', changePct: 1.29, sparkline: [4, 5, 5.5, 6.2, 6.1, 6.6] },
  { code: 'ETH', label: 'Ethereum', price: '5.1k', changePct: 1.64, sparkline: [3.8, 4.1, 4.6, 4.5, 4.8, 5.0] },
  { code: 'SPX', label: 'S&P 500', price: '5,128', changePct: -0.26, sparkline: [6.1, 6.0, 5.9, 5.7, 5.8, 5.6] },
  { code: 'NDQ', label: 'Nasdaq', price: '18,542', changePct: -0.4, sparkline: [6.2, 6.4, 6.0, 5.9, 5.6, 5.4] },
  { code: 'GOLD', label: 'Gold', price: '2,388', changePct: 0.68, sparkline: [4.2, 4.4, 4.7, 4.8, 5.0, 5.2] },
];

export const terminalChartBySymbol: Record<string, TerminalChartSeries> = {
  BTCUSDT: buildCandles(95420, [210, -88, 132, 190, -64, 144, 118, -32, 168, 98], 68000, 'Apr'),
  ETHUSDT: buildCandles(4888, [18, -9, 11, 14, -6, 22, 9, -4, 12, 8], 42000, 'Apr'),
  NVDA: buildCandles(1216, [-6.4, 3.8, -4.6, 5.1, -3.2, -2.9, 4.8, -1.6, 2.1, -5.2], 18000, 'Apr'),
  TSLA: buildCandles(268, [2.2, 1.1, -0.8, 3.3, 2.5, -1.4, 1.6, 0.9, 1.8, -0.5], 26000, 'Apr'),
  EURUSD: buildCandles(1.087, [0.0012, -0.0004, 0.0006, 0.0011, -0.0003, 0.0008, -0.0002, 0.0005, 0.0003, -0.0001], 9000, 'Apr'),
  XAUUSD: buildCandles(2346, [8.2, 3.4, -2.8, 5.6, 4.2, -1.6, 6.8, 3.1, -0.9, 4.4], 24000, 'Apr'),
  'NQ1!': buildCandles(18760, [-42, 16, -28, 34, -24, -12, 26, -18, 14, -22], 18000, 'Apr'),
  'CL1!': buildCandles(82.4, [0.88, 0.42, -0.22, 1.16, 0.94, -0.18, 0.72, 0.36, -0.12, 0.64], 28000, 'Apr'),
};

export const terminalOrderBookBySymbol: Record<
  string,
  { asks: TerminalOrderBookLevel[]; bids: TerminalOrderBookLevel[]; last: number }
> = {
  BTCUSDT: buildOrderBook(98234.4, 8.5, [1.2, 1.4, 1.8, 2.4, 3.1]),
  ETHUSDT: buildOrderBook(5148.8, 0.8, [12, 18, 26, 31, 40]),
  NVDA: buildOrderBook(1184.2, 0.45, [260, 340, 420, 510, 620]),
  TSLA: buildOrderBook(282.7, 0.12, [180, 220, 260, 340, 430]),
  EURUSD: buildOrderBook(1.0942, 0.0001, [120, 180, 220, 260, 300]),
  XAUUSD: buildOrderBook(2388.6, 0.5, [34, 41, 48, 56, 62]),
  'NQ1!': buildOrderBook(18542.5, 1.25, [11, 13, 18, 24, 31]),
  'CL1!': buildOrderBook(88.42, 0.03, [84, 92, 108, 130, 154]),
};

export const terminalTradesBySymbol: Record<string, TerminalTradePrint[]> = {
  BTCUSDT: buildTrades(98234.4, 4.6, [0.12, 0.18, 0.24, 0.32, 0.28, 0.44, 0.36, 0.52, 0.48, 0.62]),
  ETHUSDT: buildTrades(5148.8, 0.45, [1.2, 1.6, 1.9, 2.2, 2.7, 2.4, 2.9, 3.4, 3.8, 4.2]),
  NVDA: buildTrades(1184.2, 0.18, [120, 160, 220, 260, 300, 340, 280, 240, 190, 160]),
  TSLA: buildTrades(282.7, 0.08, [180, 210, 260, 300, 340, 380, 420, 460, 400, 360]),
  EURUSD: buildTrades(1.0942, 0.0001, [420000, 380000, 460000, 520000, 610000, 490000, 540000, 630000, 720000, 680000]),
  XAUUSD: buildTrades(2388.6, 0.2, [12, 16, 20, 18, 21, 24, 27, 31, 35, 39]),
  'NQ1!': buildTrades(18542.5, 0.9, [3, 4, 5, 6, 7, 8, 6, 5, 4, 3]),
  'CL1!': buildTrades(88.42, 0.02, [16, 18, 21, 24, 28, 30, 34, 38, 42, 46]),
};

export const terminalPanelDataBySymbol: Record<string, TerminalPanelDataset> = Object.fromEntries(
  terminalSymbols.map((symbol) => [symbol.id, buildPanelData(symbol)])
) as Record<string, TerminalPanelDataset>;

export const terminalStateMapBySymbol: Record<string, TerminalStateMap> = {
  BTCUSDT: {
    chart: 'ready',
    orderBook: 'ready',
    timeSales: 'ready',
    positions: 'ready',
    orders: 'ready',
    fills: 'ready',
    news: 'ready',
    events: 'ready',
  },
  ETHUSDT: {
    chart: 'ready',
    orderBook: 'ready',
    timeSales: 'ready',
    positions: 'ready',
    orders: 'ready',
    fills: 'ready',
    news: 'loading',
    events: 'ready',
  },
  NVDA: {
    chart: 'ready',
    orderBook: 'ready',
    timeSales: 'ready',
    positions: 'ready',
    orders: 'ready',
    fills: 'ready',
    news: 'ready',
    events: 'loading',
  },
  TSLA: {
    chart: 'ready',
    orderBook: 'ready',
    timeSales: 'ready',
    positions: 'ready',
    orders: 'ready',
    fills: 'ready',
    news: 'ready',
    events: 'ready',
  },
  EURUSD: {
    chart: 'ready',
    orderBook: 'empty',
    timeSales: 'ready',
    positions: 'ready',
    orders: 'ready',
    fills: 'ready',
    news: 'loading',
    events: 'ready',
  },
  XAUUSD: {
    chart: 'ready',
    orderBook: 'ready',
    timeSales: 'ready',
    positions: 'ready',
    orders: 'ready',
    fills: 'ready',
    news: 'empty',
    events: 'error',
  },
  'NQ1!': {
    chart: 'ready',
    orderBook: 'ready',
    timeSales: 'ready',
    positions: 'ready',
    orders: 'ready',
    fills: 'ready',
    news: 'ready',
    events: 'ready',
  },
  'CL1!': {
    chart: 'ready',
    orderBook: 'ready',
    timeSales: 'ready',
    positions: 'ready',
    orders: 'ready',
    fills: 'ready',
    news: 'ready',
    events: 'loading',
  },
};

export const defaultTerminalState = {
  symbolId: 'BTCUSDT',
  marketCategory: 'crypto' as TerminalMarketCategory,
  watchlistMode: 'watchlist' as WatchlistMode,
  interval: '15m' as ChartInterval,
  chartType: 'candles' as ChartType,
  indicators: ['MA', 'EMA', 'VOL'] as IndicatorKey[],
  drawTool: 'trendline' as DrawToolKey,
  utilityTools: ['crosshair'] as UtilityToolKey[],
  bottomTab: 'positions' as BottomTabKey,
};

export const terminalStatusMeta = {
  dataSource: 'Alpha Stream Mock Feed',
  network: 'Private Bridge',
  latencyMs: 42,
  timezone: 'UTC+8 / Asia-Shanghai',
  environment: '模拟交易',
  marketStatus: '实时',
};
