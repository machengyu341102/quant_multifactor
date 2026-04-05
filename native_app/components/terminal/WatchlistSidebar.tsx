import { Ionicons } from '@expo/vector-icons';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { terminalTheme } from '@/constants/terminal-theme';
import type { TerminalMiniMarket, TerminalSymbol, WatchlistMode } from '@/mocks/terminal-data';
import { MarketMiniStrip } from './MarketMiniStrip';

const WATCHLIST_TABS: { key: WatchlistMode; label: string }[] = [
  { key: 'watchlist', label: '自选' },
  { key: 'hot', label: '热门' },
  { key: 'recent', label: '最近' },
  { key: 'filters', label: '筛选器' },
];

interface WatchlistSidebarProps {
  symbols: TerminalSymbol[];
  miniMarkets: TerminalMiniMarket[];
  watchlistMode: WatchlistMode;
  filterValue: string;
  selectedSymbolId: string;
  compact?: boolean;
  embedded?: boolean;
  onChangeWatchlistMode: (mode: WatchlistMode) => void;
  onChangeFilterValue: (value: string) => void;
  onSelectSymbol: (symbolId: string) => void;
}

export function WatchlistSidebar({
  symbols,
  miniMarkets,
  watchlistMode,
  filterValue,
  selectedSymbolId,
  compact = false,
  embedded = false,
  onChangeWatchlistMode,
  onChangeFilterValue,
  onSelectSymbol,
}: WatchlistSidebarProps) {
  return (
    <View style={[styles.container, compact && styles.containerCompact, embedded && styles.containerEmbedded]}>
      <View style={styles.section}>
        <View style={styles.tabRow}>
          {WATCHLIST_TABS.map((tab) => {
            const active = tab.key === watchlistMode;
            return (
              <Pressable
                key={tab.key}
                accessibilityRole="tab"
                accessibilityState={{ selected: active }}
                onPress={() => onChangeWatchlistMode(tab.key)}
                style={({ hovered, pressed }) => [
                  styles.tabButton,
                  active && styles.tabButtonActive,
                    hovered && !active && styles.tabButtonHover,
                    pressed && styles.tabButtonPressed,
                  ]}>
                <Text style={[styles.tabButtonText, active && styles.tabButtonTextActive]}>{tab.label}</Text>
              </Pressable>
            );
          })}
        </View>

        <View style={styles.filterInputShell}>
          <Ionicons name="search-outline" size={14} color={terminalTheme.colors.subtext} />
          <TextInput
            accessibilityLabel="筛选自选列表"
            value={filterValue}
            onChangeText={onChangeFilterValue}
            placeholder="过滤代码 / 名称"
            placeholderTextColor={terminalTheme.colors.muted}
            autoCorrect={false}
            autoCapitalize="characters"
            style={styles.filterInput}
          />
        </View>

        <View style={styles.tableHead}>
          <Text style={[styles.headText, styles.codeCol]}>代码</Text>
          <Text style={[styles.headText, styles.nameCol]}>名称</Text>
          <Text style={[styles.headText, styles.priceCol]}>最新</Text>
          <Text style={[styles.headText, styles.changeCol]}>涨跌</Text>
        </View>

        {symbols.length ? (
          <View style={styles.list}>
            {symbols.map((symbol) => {
              const active = symbol.id === selectedSymbolId;
              const positive = symbol.changePct >= 0;
              return (
                <Pressable
                  key={symbol.id}
                  accessibilityRole="button"
                  accessibilityState={{ selected: active }}
                  onPress={() => onSelectSymbol(symbol.id)}
                  style={({ hovered, pressed }) => [
                    styles.row,
                    active && styles.rowActive,
                    hovered && !active && styles.rowHover,
                    pressed && styles.rowPressed,
                  ]}>
                  <Text style={[styles.cellCode, styles.codeCol]}>{symbol.code}</Text>
                  <View style={styles.nameCol}>
                    <Text numberOfLines={1} style={styles.cellName}>
                      {symbol.name}
                    </Text>
                  </View>
                  <Text style={[styles.cellPrice, styles.priceCol]}>{formatCompactPrice(symbol.latestPrice)}</Text>
                  <Text
                    style={[
                      styles.cellChange,
                      styles.changeCol,
                      { color: positive ? terminalTheme.colors.buy : terminalTheme.colors.sell },
                    ]}>
                    {positive ? '+' : ''}
                    {symbol.changePct.toFixed(2)}%
                  </Text>
                </Pressable>
              );
            })}
          </View>
        ) : (
          <View style={styles.emptyState}>
            <Ionicons name="list-outline" size={18} color={terminalTheme.colors.muted} />
            <Text style={styles.emptyText}>当前筛选没有匹配品种</Text>
          </View>
        )}
      </View>

      <View style={styles.section}>
        <View style={styles.quickHead}>
          <Text style={styles.quickTitle}>市场快照</Text>
          <Text style={styles.quickHint}>核心品种</Text>
        </View>
        <MarketMiniStrip items={miniMarkets} />
      </View>
    </View>
  );
}

function formatCompactPrice(value: number) {
  if (value >= 1000) {
    return value.toLocaleString('en-US', { maximumFractionDigits: 2 });
  }
  return value.toFixed(value < 10 ? 4 : 2);
}

const styles = StyleSheet.create({
  container: {
    width: terminalTheme.layout.sidebarWidth,
    padding: terminalTheme.spacing.md,
    borderRightWidth: 1,
    borderRightColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.panel,
    gap: terminalTheme.spacing.md,
  },
  containerCompact: {
    width: terminalTheme.layout.sidebarCompactWidth,
  },
  containerEmbedded: {
    width: '100%',
    borderRightWidth: 0,
    borderRadius: terminalTheme.radius.md,
  },
  section: {
    gap: terminalTheme.spacing.sm,
  },
  tabRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: terminalTheme.spacing.xs,
  },
  tabButton: {
    minHeight: 28,
    paddingHorizontal: 10,
    borderRadius: terminalTheme.radius.sm,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.panelMuted,
    alignItems: 'center',
    justifyContent: 'center',
  },
  tabButtonActive: {
    backgroundColor: terminalTheme.colors.active,
    borderColor: terminalTheme.colors.accent,
  },
  tabButtonHover: {
    backgroundColor: terminalTheme.colors.hover,
  },
  tabButtonPressed: {
    backgroundColor: terminalTheme.colors.active,
  },
  tabButtonText: {
    color: terminalTheme.colors.subtext,
    fontSize: 11,
    fontWeight: '600',
    fontFamily: terminalTheme.fonts.sans,
  },
  tabButtonTextActive: {
    color: terminalTheme.colors.text,
  },
  filterInputShell: {
    minHeight: 36,
    borderRadius: terminalTheme.radius.sm,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.chartBg,
    paddingHorizontal: 10,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  filterInput: {
    flex: 1,
    color: terminalTheme.colors.text,
    fontSize: 12,
    paddingVertical: 0,
    fontFamily: terminalTheme.fonts.sans,
  },
  tableHead: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 6,
  },
  headText: {
    color: terminalTheme.colors.muted,
    fontSize: 10,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  codeCol: {
    width: 66,
  },
  nameCol: {
    flex: 1,
  },
  priceCol: {
    width: 72,
    textAlign: 'right',
  },
  changeCol: {
    width: 62,
    textAlign: 'right',
  },
  list: {
    gap: 6,
  },
  row: {
    minHeight: 48,
    borderRadius: terminalTheme.radius.sm,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.chartBg,
    paddingHorizontal: 8,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  rowActive: {
    backgroundColor: terminalTheme.colors.active,
    borderColor: terminalTheme.colors.accent,
  },
  rowHover: {
    backgroundColor: terminalTheme.colors.hover,
  },
  rowPressed: {
    backgroundColor: terminalTheme.colors.active,
  },
  cellCode: {
    color: terminalTheme.colors.text,
    fontSize: 11,
    fontWeight: '700',
    fontFamily: terminalTheme.fonts.mono,
  },
  cellName: {
    color: terminalTheme.colors.text,
    fontSize: 12,
    fontWeight: '600',
    fontFamily: terminalTheme.fonts.sans,
  },
  cellPrice: {
    color: terminalTheme.colors.text,
    fontSize: 11,
    fontWeight: '600',
    fontFamily: terminalTheme.fonts.mono,
  },
  cellChange: {
    fontSize: 11,
    fontWeight: '700',
    fontFamily: terminalTheme.fonts.mono,
  },
  emptyState: {
    minHeight: 124,
    borderRadius: terminalTheme.radius.md,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.chartBg,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  emptyText: {
    color: terminalTheme.colors.subtext,
    fontSize: 12,
    fontFamily: terminalTheme.fonts.sans,
  },
  quickHead: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  quickTitle: {
    color: terminalTheme.colors.text,
    fontSize: 12,
    fontWeight: '700',
    fontFamily: terminalTheme.fonts.sans,
  },
  quickHint: {
    color: terminalTheme.colors.subtext,
    fontSize: 11,
    fontFamily: terminalTheme.fonts.sans,
  },
  focusRing: {
    borderColor: terminalTheme.colors.focus,
  },
});
