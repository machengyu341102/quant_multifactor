import { useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';

import { terminalTheme } from '@/constants/terminal-theme';
import {
  defaultTerminalState,
  terminalChartBySymbol,
  terminalMiniMarkets,
  terminalOrderBookBySymbol,
  terminalPanelDataBySymbol,
  terminalStateMapBySymbol,
  terminalStatusMeta,
  terminalSymbols,
  terminalTradesBySymbol,
  type BottomTabKey,
  type ChartInterval,
  type ChartType,
  type DrawToolKey,
  type IndicatorKey,
  type TerminalMarketCategory,
  type UtilityToolKey,
  type WatchlistMode,
} from '@/mocks/terminal-data';
import { AdvancedChartArea } from './AdvancedChartArea';
import { BottomDataTabs } from './BottomDataTabs';
import { ChartToolbar } from './ChartToolbar';
import { OrderBookCard } from './OrderBookCard';
import { QuickTradeCard } from './QuickTradeCard';
import { StatusBar as TerminalStatusBar } from './StatusBar';
import { SymbolSummaryBar } from './SymbolSummaryBar';
import { TerminalHeader } from './TerminalHeader';
import { TimeSalesCard } from './TimeSalesCard';
import { WatchlistSidebar } from './WatchlistSidebar';

type MobilePane = 'watchlist' | 'trade' | 'book' | 'data';
type TradeSide = 'buy' | 'sell';
type TradeOrderType = 'limit' | 'market' | 'stop';

const MOBILE_PANES: { key: MobilePane; label: string }[] = [
  { key: 'watchlist', label: '列表' },
  { key: 'trade', label: '下单' },
  { key: 'book', label: '盘口' },
  { key: 'data', label: '明细' },
];

export function TradingViewStyleTerminalPage() {
  const { width } = useWindowDimensions();
  const isWide = width >= 1440;
  const isTablet = width >= 900 && width < 1200;
  const isMobile = width < 900;

  const [marketCategory, setMarketCategory] = useState<TerminalMarketCategory>(defaultTerminalState.marketCategory);
  const [watchlistMode, setWatchlistMode] = useState<WatchlistMode>(defaultTerminalState.watchlistMode);
  const [searchValue, setSearchValue] = useState('');
  const [selectedSymbolId, setSelectedSymbolId] = useState(defaultTerminalState.symbolId);
  const [interval, setSelectedInterval] = useState<ChartInterval>(defaultTerminalState.interval);
  const [chartType, setChartType] = useState<ChartType>(defaultTerminalState.chartType);
  const [indicators, setIndicators] = useState<IndicatorKey[]>(defaultTerminalState.indicators);
  const [drawTool, setDrawTool] = useState<DrawToolKey>(defaultTerminalState.drawTool);
  const [utilityTools, setUtilityTools] = useState<UtilityToolKey[]>(defaultTerminalState.utilityTools);
  const [transientTools, setTransientTools] = useState<UtilityToolKey[]>([]);
  const [bottomTab, setBottomTab] = useState<BottomTabKey>(defaultTerminalState.bottomTab);
  const [mobilePane, setMobilePane] = useState<MobilePane>('watchlist');
  const [orderSide, setOrderSide] = useState<TradeSide>('buy');
  const [orderType, setOrderType] = useState<TradeOrderType>('limit');
  const [priceValue, setPriceValue] = useState('98234.42');
  const [quantityValue, setQuantityValue] = useState('0.50');
  const [activeAllocation, setActiveAllocation] = useState<number | null>(50);
  const [flashDirection, setFlashDirection] = useState<'buy' | 'sell' | null>('buy');
  const [currentTimeLabel, setCurrentTimeLabel] = useState(buildTimeLabel());
  const [chartBusy, setChartBusy] = useState(false);

  const filteredSymbols = buildWatchlistSymbols({
    marketCategory,
    watchlistMode,
    searchValue,
  });

  const selectedSymbol =
    terminalSymbols.find((item) => item.id === selectedSymbolId) ??
    filteredSymbols[0] ??
    terminalSymbols[0];

  useEffect(() => {
    if (!filteredSymbols.length) {
      return;
    }
    if (!filteredSymbols.some((item) => item.id === selectedSymbolId)) {
      setSelectedSymbolId(filteredSymbols[0]?.id ?? terminalSymbols[0].id);
    }
  }, [filteredSymbols, selectedSymbolId]);

  useEffect(() => {
    const timer = globalThis.setInterval(() => {
      setCurrentTimeLabel(buildTimeLabel());
    }, 1000);

    return () => globalThis.clearInterval(timer);
  }, []);

  useEffect(() => {
    setPriceValue(selectedSymbol.latestPrice.toFixed(selectedSymbol.latestPrice >= 10 ? 2 : 4));
    setQuantityValue(
      selectedSymbol.marketCategory === 'crypto'
        ? '0.50'
        : selectedSymbol.marketCategory === 'forex'
          ? '10000'
          : selectedSymbol.marketCategory === 'futures'
            ? '3'
            : '100'
    );
    setActiveAllocation(50);
    setOrderType('limit');
    setFlashDirection(selectedSymbol.changePct >= 0 ? 'buy' : 'sell');
    const flashTimer = setTimeout(() => setFlashDirection(null), 620);
    const chartTimer = setTimeout(() => setChartBusy(false), 220);
    setChartBusy(true);
    return () => {
      clearTimeout(flashTimer);
      clearTimeout(chartTimer);
    };
  }, [selectedSymbol.changePct, selectedSymbol.id, selectedSymbol.latestPrice, selectedSymbol.marketCategory]);

  useEffect(() => {
    setChartBusy(true);
    const timer = setTimeout(() => setChartBusy(false), 180);
    return () => clearTimeout(timer);
  }, [interval, chartType]);

  const baseStateMap = terminalStateMapBySymbol[selectedSymbol.id] ?? terminalStateMapBySymbol.BTCUSDT;
  const effectiveStateMap = {
    ...baseStateMap,
    chart: chartBusy ? 'loading' : baseStateMap.chart,
  };
  const chartSeries = terminalChartBySymbol[selectedSymbol.id] ?? terminalChartBySymbol.BTCUSDT;
  const orderBook = terminalOrderBookBySymbol[selectedSymbol.id] ?? terminalOrderBookBySymbol.BTCUSDT;
  const trades = terminalTradesBySymbol[selectedSymbol.id] ?? terminalTradesBySymbol.BTCUSDT;
  const panelData = terminalPanelDataBySymbol[selectedSymbol.id] ?? terminalPanelDataBySymbol.BTCUSDT;
  const chartHeight = isMobile
    ? terminalTheme.layout.chartMobileHeight
    : isWide
      ? terminalTheme.layout.chartDesktopHeight
      : terminalTheme.layout.chartDesktopHeight - 40;

  const fullscreen = utilityTools.includes('fullscreen');
  const latency = terminalStatusMeta.latencyMs + (chartBusy ? 8 : 0);

  function toggleIndicator(indicator: IndicatorKey) {
    setIndicators((current) =>
      current.includes(indicator)
        ? current.filter((item) => item !== indicator)
        : [...current, indicator]
    );
  }

  function pulseTool(tool: UtilityToolKey) {
    setTransientTools((current) => Array.from(new Set([...current, tool])));
    setTimeout(() => {
      setTransientTools((current) => current.filter((item) => item !== tool));
    }, 520);
  }

  function toggleUtilityTool(tool: UtilityToolKey) {
    if (tool === 'reset') {
      setSelectedInterval(defaultTerminalState.interval);
      setChartType(defaultTerminalState.chartType);
      setIndicators(defaultTerminalState.indicators);
      setDrawTool(defaultTerminalState.drawTool);
      pulseTool(tool);
      return;
    }

    if (tool === 'capture') {
      pulseTool(tool);
      return;
    }

    setUtilityTools((current) =>
      current.includes(tool) ? current.filter((item) => item !== tool) : [...current, tool]
    );
  }

  function handleAllocation(value: number) {
    setActiveAllocation(value);
    const numericPrice = Number(priceValue || selectedSymbol.latestPrice);
    const balance = getAvailableBalance(selectedSymbol.marketCategory);
    const estimate = (balance * value) / 100;
    const derivedQuantity = numericPrice > 0 ? estimate / numericPrice : 0;
    setQuantityValue(
      derivedQuantity.toFixed(
        selectedSymbol.marketCategory === 'crypto' || selectedSymbol.marketCategory === 'forex' ? 4 : 2
      )
    );
  }

  return (
    <View style={styles.page}>
      <TerminalHeader
        marketCategory={marketCategory}
        searchValue={searchValue}
        currentTimeLabel={currentTimeLabel}
        marketStatusLabel={terminalStatusMeta.marketStatus}
        onChangeMarketCategory={setMarketCategory}
        onChangeSearchValue={setSearchValue}
      />

      <View style={styles.mainShell}>
        {!isMobile && !fullscreen ? (
          <WatchlistSidebar
            symbols={filteredSymbols}
            miniMarkets={terminalMiniMarkets}
            watchlistMode={watchlistMode}
            filterValue={searchValue}
            selectedSymbolId={selectedSymbol.id}
            compact={!isWide}
            onChangeWatchlistMode={setWatchlistMode}
            onChangeFilterValue={setSearchValue}
            onSelectSymbol={setSelectedSymbolId}
          />
        ) : null}

        <ScrollView
          style={styles.centerScroll}
          contentContainerStyle={styles.centerContent}
          showsVerticalScrollIndicator={false}>
          <SymbolSummaryBar symbol={selectedSymbol} flashDirection={flashDirection} />
          <ChartToolbar
            interval={interval}
            chartType={chartType}
            indicators={indicators}
            drawTool={drawTool}
            utilityTools={utilityTools}
            transientTools={transientTools}
            onChangeInterval={setSelectedInterval}
            onChangeChartType={setChartType}
            onToggleIndicator={toggleIndicator}
            onSelectDrawTool={setDrawTool}
            onToggleUtilityTool={toggleUtilityTool}
          />
          <AdvancedChartArea
            symbol={selectedSymbol}
            series={chartSeries}
            chartType={chartType}
            indicators={indicators}
            drawTool={drawTool}
            utilityTools={utilityTools}
            dataState={effectiveStateMap.chart}
            height={fullscreen ? chartHeight + 180 : chartHeight}
          />

          {isMobile ? (
            <View style={styles.mobilePaneShell}>
              <View style={styles.mobileTabRow}>
                {MOBILE_PANES.map((pane) => {
                  const active = pane.key === mobilePane;
                  return (
                    <Pressable
                      key={pane.key}
                      onPress={() => setMobilePane(pane.key)}
                      style={({ hovered, pressed }) => [
                        styles.mobileTab,
                        active && styles.mobileTabActive,
                        hovered && !active && styles.mobileTabHover,
                        pressed && styles.mobileTabPressed,
                      ]}>
                      <Text style={[styles.mobileTabText, active && styles.mobileTabTextActive]}>{pane.label}</Text>
                    </Pressable>
                  );
                })}
              </View>

              {mobilePane === 'watchlist' ? (
                <WatchlistSidebar
                  symbols={filteredSymbols}
                  miniMarkets={terminalMiniMarkets}
                  watchlistMode={watchlistMode}
                  filterValue={searchValue}
                  selectedSymbolId={selectedSymbol.id}
                  compact
                  embedded
                  onChangeWatchlistMode={setWatchlistMode}
                  onChangeFilterValue={setSearchValue}
                  onSelectSymbol={setSelectedSymbolId}
                />
              ) : null}

              {mobilePane === 'trade' ? (
                <QuickTradeCard
                  latestPrice={selectedSymbol.latestPrice}
                  orderSide={orderSide}
                  orderType={orderType}
                  priceValue={priceValue}
                  quantityValue={quantityValue}
                  activeAllocation={activeAllocation}
                  availableBalance={formatAvailableBalance(selectedSymbol.marketCategory)}
                  onChangeOrderSide={setOrderSide}
                  onChangeOrderType={setOrderType}
                  onChangePriceValue={setPriceValue}
                  onChangeQuantityValue={setQuantityValue}
                  onChangeAllocation={handleAllocation}
                />
              ) : null}

              {mobilePane === 'book' ? (
                <View style={styles.mobileStack}>
                  <OrderBookCard
                    asks={orderBook.asks}
                    bids={orderBook.bids}
                    last={orderBook.last}
                    dataState={baseStateMap.orderBook}
                  />
                  <TimeSalesCard trades={trades} dataState={baseStateMap.timeSales} />
                </View>
              ) : null}

              {mobilePane === 'data' ? (
                <BottomDataTabs
                  activeTab={bottomTab}
                  dataset={panelData}
                  stateMap={baseStateMap}
                  onChangeTab={setBottomTab}
                />
              ) : null}
            </View>
          ) : null}

          {!isMobile && !fullscreen ? (
            <BottomDataTabs
              activeTab={bottomTab}
              dataset={panelData}
              stateMap={baseStateMap}
              onChangeTab={setBottomTab}
            />
          ) : null}

          {isTablet && !fullscreen ? (
            <View style={styles.compactRail}>
              <QuickTradeCard
                latestPrice={selectedSymbol.latestPrice}
                orderSide={orderSide}
                orderType={orderType}
                priceValue={priceValue}
                quantityValue={quantityValue}
                activeAllocation={activeAllocation}
                availableBalance={formatAvailableBalance(selectedSymbol.marketCategory)}
                onChangeOrderSide={setOrderSide}
                onChangeOrderType={setOrderType}
                onChangePriceValue={setPriceValue}
                onChangeQuantityValue={setQuantityValue}
                onChangeAllocation={handleAllocation}
              />
              <OrderBookCard
                asks={orderBook.asks}
                bids={orderBook.bids}
                last={orderBook.last}
                dataState={baseStateMap.orderBook}
              />
              <TimeSalesCard trades={trades} dataState={baseStateMap.timeSales} />
            </View>
          ) : null}
        </ScrollView>

        {!isMobile && !isTablet && !fullscreen ? (
          <View style={[styles.rightRail, { width: isWide ? terminalTheme.layout.rightRailWidth : terminalTheme.layout.rightRailCompactWidth }]}>
            <QuickTradeCard
              latestPrice={selectedSymbol.latestPrice}
              orderSide={orderSide}
              orderType={orderType}
              priceValue={priceValue}
              quantityValue={quantityValue}
              activeAllocation={activeAllocation}
              availableBalance={formatAvailableBalance(selectedSymbol.marketCategory)}
              onChangeOrderSide={setOrderSide}
              onChangeOrderType={setOrderType}
              onChangePriceValue={setPriceValue}
              onChangeQuantityValue={setQuantityValue}
              onChangeAllocation={handleAllocation}
            />
            <OrderBookCard
              asks={orderBook.asks}
              bids={orderBook.bids}
              last={orderBook.last}
              dataState={baseStateMap.orderBook}
            />
            <TimeSalesCard trades={trades} dataState={baseStateMap.timeSales} />
          </View>
        ) : null}
      </View>

      <TerminalStatusBar
        dataSource={terminalStatusMeta.dataSource}
        network={terminalStatusMeta.network}
        latencyMs={latency}
        timezone={terminalStatusMeta.timezone}
        environment={terminalStatusMeta.environment}
      />
    </View>
  );
}

function buildWatchlistSymbols({
  marketCategory,
  watchlistMode,
  searchValue,
}: {
  marketCategory: TerminalMarketCategory;
  watchlistMode: WatchlistMode;
  searchValue: string;
}) {
  const scoped = terminalSymbols.filter((symbol) => symbol.marketCategory === marketCategory);
  const normalizedSearch = searchValue.trim().toUpperCase();

  const byMode = scoped.filter((symbol) => {
    if (watchlistMode === 'watchlist') {
      return symbol.watchlist;
    }
    if (watchlistMode === 'hot') {
      return symbol.hotRank <= 5;
    }
    if (watchlistMode === 'recent') {
      return symbol.recentRank <= 5;
    }
    return symbol.filterTags.length > 0;
  });

  const searched = normalizedSearch
    ? byMode.filter((symbol) =>
        [symbol.code, symbol.name, symbol.marketLabel, ...symbol.filterTags]
          .join(' ')
          .toUpperCase()
          .includes(normalizedSearch)
      )
    : byMode;

  return [...searched].sort((left, right) => {
    if (watchlistMode === 'recent') {
      return left.recentRank - right.recentRank;
    }
    return left.hotRank - right.hotRank;
  });
}

function buildTimeLabel() {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date());
}

function getAvailableBalance(category: TerminalMarketCategory) {
  if (category === 'crypto') {
    return 24580;
  }
  if (category === 'forex') {
    return 100000;
  }
  if (category === 'futures') {
    return 54000;
  }
  return 180000;
}

function formatAvailableBalance(category: TerminalMarketCategory) {
  const balance = getAvailableBalance(category);
  if (category === 'crypto') {
    return `${balance.toLocaleString('en-US')} USDT`;
  }
  if (category === 'forex') {
    return `${balance.toLocaleString('en-US')} USD`;
  }
  if (category === 'futures') {
    return `${balance.toLocaleString('en-US')} 保证金`;
  }
  return `${balance.toLocaleString('en-US')} CNY`;
}

const styles = StyleSheet.create({
  page: {
    flex: 1,
    backgroundColor: terminalTheme.colors.page,
  },
  mainShell: {
    flex: 1,
    flexDirection: 'row',
    minHeight: 0,
  },
  centerScroll: {
    flex: 1,
    minHeight: 0,
  },
  centerContent: {
    padding: terminalTheme.spacing.lg,
    gap: terminalTheme.spacing.md,
  },
  rightRail: {
    borderLeftWidth: 1,
    borderLeftColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.panel,
    padding: terminalTheme.spacing.md,
    gap: terminalTheme.spacing.md,
  },
  compactRail: {
    gap: terminalTheme.spacing.md,
  },
  mobilePaneShell: {
    gap: terminalTheme.spacing.md,
  },
  mobileTabRow: {
    flexDirection: 'row',
    gap: terminalTheme.spacing.xs,
    flexWrap: 'wrap',
  },
  mobileTab: {
    flex: 1,
    minWidth: 72,
    minHeight: 34,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    borderRadius: terminalTheme.radius.sm,
    backgroundColor: terminalTheme.colors.panel,
    alignItems: 'center',
    justifyContent: 'center',
  },
  mobileTabActive: {
    backgroundColor: terminalTheme.colors.accentSoft,
    borderColor: terminalTheme.colors.accent,
  },
  mobileTabHover: {
    backgroundColor: terminalTheme.colors.hover,
  },
  mobileTabPressed: {
    backgroundColor: terminalTheme.colors.active,
  },
  mobileTabText: {
    color: terminalTheme.colors.subtext,
    fontSize: 12,
    fontWeight: '600',
  },
  mobileTabTextActive: {
    color: terminalTheme.colors.text,
  },
  mobileStack: {
    gap: terminalTheme.spacing.md,
  },
  focusRing: {
    borderColor: terminalTheme.colors.focus,
  },
});
