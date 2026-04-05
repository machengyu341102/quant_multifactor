import { ActivityIndicator, ScrollView, StyleSheet, Text, View, Pressable } from 'react-native';

import { terminalTheme } from '@/constants/terminal-theme';
import type { BottomTabKey, TerminalPanelDataset, TerminalStateMap } from '@/mocks/terminal-data';

const TAB_LABELS: Record<BottomTabKey, string> = {
  positions: '持仓',
  orders: '当前委托',
  fills: '历史成交',
  news: '新闻',
  events: '事件/公告',
};

interface BottomDataTabsProps {
  activeTab: BottomTabKey;
  dataset: TerminalPanelDataset;
  stateMap: TerminalStateMap;
  onChangeTab: (tab: BottomTabKey) => void;
}

interface TableColumn {
  key: string;
  label: string;
  width?: number;
  flex?: number;
  alignRight?: boolean;
  tint?: 'buy' | 'sell';
}

interface TableConfig {
  columns: TableColumn[];
  rows: Record<string, string>[];
}

export function BottomDataTabs({
  activeTab,
  dataset,
  stateMap,
  onChangeTab,
}: BottomDataTabsProps) {
  const table = buildTable(activeTab, dataset);
  const state = stateMap[activeTab];

  return (
    <View style={styles.card}>
      <View style={styles.tabRow}>
        {(Object.keys(TAB_LABELS) as BottomTabKey[]).map((tab) => {
          const active = tab === activeTab;
          return (
            <Pressable
              key={tab}
              accessibilityRole="tab"
              accessibilityState={{ selected: active }}
              onPress={() => onChangeTab(tab)}
              style={({ hovered, pressed }) => [
                styles.tabButton,
                active && styles.tabButtonActive,
                hovered && !active && styles.tabButtonHover,
                pressed && styles.tabButtonPressed,
              ]}>
              <Text style={[styles.tabText, active && styles.tabTextActive]}>{TAB_LABELS[tab]}</Text>
            </Pressable>
          );
        })}
      </View>

      <View style={styles.tableHead}>
        {table.columns.map((column) => (
          <Text key={column.key} style={[styles.headText, column.alignRight && styles.alignRight, column.flex ? { flex: column.flex } : { width: column.width }]}>
            {column.label}
          </Text>
        ))}
      </View>

      {state === 'loading' ? (
        <View style={styles.stateBody}>
          <ActivityIndicator color={terminalTheme.colors.accent} />
          <Text style={styles.stateText}>正在加载 {TAB_LABELS[activeTab]}…</Text>
          <View style={styles.placeholderList}>
            {Array.from({ length: 5 }).map((_, index) => (
              <View key={`loading-${index}`} style={styles.loadingRow} />
            ))}
          </View>
        </View>
      ) : null}

      {state === 'empty' ? (
        <View style={styles.stateBody}>
          <Text style={styles.stateText}>当前没有 {TAB_LABELS[activeTab]} 数据。</Text>
        </View>
      ) : null}

      {state === 'error' ? (
        <View style={styles.stateBody}>
          <Text style={[styles.stateText, styles.errorText]}>{TAB_LABELS[activeTab]} 加载失败，请稍后重试。</Text>
        </View>
      ) : null}

      {state === 'ready' ? (
        <ScrollView horizontal style={styles.tableBody} contentContainerStyle={styles.tableBodyContent} showsHorizontalScrollIndicator={false}>
          <View style={styles.tableColumn}>
            {table.rows.map((row, rowIndex) => (
              <View key={`${activeTab}-${rowIndex}`} style={styles.row}>
                {table.columns.map((column) => (
                  <Text
                    key={`${rowIndex}-${column.key}`}
                    numberOfLines={1}
                    style={[
                      styles.rowText,
                      column.alignRight && styles.alignRight,
                      column.flex ? { flex: column.flex } : { width: column.width },
                      column.tint === 'buy' && styles.buyText,
                      column.tint === 'sell' && styles.sellText,
                    ]}>
                    {String(row[column.key] ?? '--')}
                  </Text>
                ))}
              </View>
            ))}
          </View>
        </ScrollView>
      ) : null}

      <View style={styles.reserveStates}>
        <ReserveState label="Loading" />
        <ReserveState label="Empty" />
        <ReserveState label="Error" tone="error" />
      </View>
    </View>
  );
}

function ReserveState({ label, tone = 'neutral' }: { label: string; tone?: 'neutral' | 'error' }) {
  return (
    <View style={[styles.reserveState, tone === 'error' && styles.reserveStateError]}>
      <Text style={[styles.reserveText, tone === 'error' && styles.errorText]}>{label}</Text>
    </View>
  );
}

function buildTable(activeTab: BottomTabKey, dataset: TerminalPanelDataset): TableConfig {
  if (activeTab === 'positions') {
    return {
      columns: [
        { key: 'account', label: '账户', width: 88 },
        { key: 'size', label: '数量', width: 118 },
        { key: 'entry', label: '开仓', width: 84, alignRight: true },
        { key: 'mark', label: '现价', width: 84, alignRight: true },
        { key: 'pnl', label: '浮盈亏', width: 84, alignRight: true, tint: 'buy' as const },
        { key: 'leverage', label: '杠杆', width: 66, alignRight: true },
      ],
      rows: dataset.positions.map((row) => ({ ...row })),
    };
  }

  if (activeTab === 'orders') {
    return {
      columns: [
        { key: 'time', label: '时间', width: 68 },
        { key: 'side', label: '方向', width: 58 },
        { key: 'type', label: '类型', width: 64 },
        { key: 'price', label: '价格', width: 88, alignRight: true },
        { key: 'quantity', label: '数量', width: 88, alignRight: true },
        { key: 'status', label: '状态', flex: 1 },
      ],
      rows: dataset.orders.map((row) => ({ ...row })),
    };
  }

  if (activeTab === 'fills') {
    return {
      columns: [
        { key: 'time', label: '时间', width: 68 },
        { key: 'side', label: '方向', width: 58 },
        { key: 'price', label: '价格', width: 88, alignRight: true },
        { key: 'quantity', label: '数量', width: 86, alignRight: true },
        { key: 'fee', label: '费用', width: 90, alignRight: true },
        { key: 'venue', label: '通道', flex: 1 },
      ],
      rows: dataset.fills.map((row) => ({ ...row })),
    };
  }

  if (activeTab === 'news') {
    return {
      columns: [
        { key: 'time', label: '时间', width: 68 },
        { key: 'source', label: '来源', width: 84 },
        { key: 'headline', label: '标题', flex: 1 },
        { key: 'impact', label: '影响', width: 58, alignRight: true },
      ],
      rows: dataset.news.map((row) => ({ ...row })),
    };
  }

  return {
    columns: [
      { key: 'time', label: '时间', width: 68 },
      { key: 'event', label: '事件', flex: 1 },
      { key: 'value', label: '结果', width: 84, alignRight: true },
      { key: 'consensus', label: '预期', width: 84, alignRight: true },
      { key: 'status', label: '状态', width: 84, alignRight: true },
    ],
    rows: dataset.events.map((row) => ({ ...row })),
  };
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    borderRadius: terminalTheme.radius.md,
    backgroundColor: terminalTheme.colors.panel,
    padding: terminalTheme.spacing.md,
    gap: terminalTheme.spacing.sm,
    minHeight: 260,
  },
  tabRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: terminalTheme.spacing.xs,
  },
  tabButton: {
    minHeight: 30,
    paddingHorizontal: 12,
    borderRadius: terminalTheme.radius.sm,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.panelMuted,
    alignItems: 'center',
    justifyContent: 'center',
  },
  tabButtonActive: {
    borderColor: terminalTheme.colors.accent,
    backgroundColor: terminalTheme.colors.accentSoft,
  },
  tabButtonHover: {
    backgroundColor: terminalTheme.colors.hover,
  },
  tabButtonPressed: {
    backgroundColor: terminalTheme.colors.active,
  },
  tabText: {
    color: terminalTheme.colors.subtext,
    fontSize: 12,
    fontWeight: '600',
  },
  tabTextActive: {
    color: terminalTheme.colors.text,
  },
  tableHead: {
    minHeight: 28,
    borderRadius: terminalTheme.radius.sm,
    backgroundColor: terminalTheme.colors.chartBg,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    paddingHorizontal: 10,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  headText: {
    color: terminalTheme.colors.muted,
    fontSize: 10,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  },
  tableBody: {
    flex: 1,
  },
  tableBodyContent: {
    minWidth: '100%',
  },
  tableColumn: {
    gap: 6,
    minWidth: '100%',
  },
  row: {
    minHeight: 34,
    borderRadius: terminalTheme.radius.xs,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.chartBg,
    paddingHorizontal: 10,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  rowText: {
    color: terminalTheme.colors.text,
    fontSize: 11,
    fontFamily: terminalTheme.fonts.mono,
  },
  buyText: {
    color: terminalTheme.colors.buy,
  },
  sellText: {
    color: terminalTheme.colors.sell,
  },
  alignRight: {
    textAlign: 'right',
  },
  stateBody: {
    minHeight: 156,
    borderRadius: terminalTheme.radius.sm,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.chartBg,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 16,
    gap: 10,
  },
  stateText: {
    color: terminalTheme.colors.subtext,
    fontSize: 12,
    textAlign: 'center',
  },
  errorText: {
    color: terminalTheme.colors.sell,
  },
  placeholderList: {
    width: '100%',
    gap: 8,
  },
  loadingRow: {
    minHeight: 12,
    borderRadius: terminalTheme.radius.xs,
    backgroundColor: terminalTheme.colors.panelSoft,
  },
  reserveStates: {
    flexDirection: 'row',
    gap: terminalTheme.spacing.xs,
  },
  reserveState: {
    flex: 1,
    minHeight: 28,
    borderRadius: terminalTheme.radius.sm,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.panelMuted,
    alignItems: 'center',
    justifyContent: 'center',
  },
  reserveStateError: {
    borderColor: terminalTheme.colors.sell,
  },
  reserveText: {
    color: terminalTheme.colors.subtext,
    fontSize: 10,
    fontWeight: '600',
  },
  focusRing: {
    borderColor: terminalTheme.colors.focus,
  },
});
