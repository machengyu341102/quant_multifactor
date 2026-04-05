import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { terminalTheme } from '@/constants/terminal-theme';
import type { DataState, TerminalOrderBookLevel } from '@/mocks/terminal-data';

interface OrderBookCardProps {
  asks: TerminalOrderBookLevel[];
  bids: TerminalOrderBookLevel[];
  last: number;
  dataState: DataState;
}

export function OrderBookCard({ asks, bids, last, dataState }: OrderBookCardProps) {
  return (
    <View style={styles.card}>
      <Text style={styles.title}>订单簿</Text>
      <View style={styles.head}>
        <Text style={[styles.headText, styles.priceCol]}>价格</Text>
        <Text style={[styles.headText, styles.sizeCol]}>数量</Text>
        <Text style={[styles.headText, styles.totalCol]}>累计</Text>
      </View>

      {dataState === 'loading' ? <CardState label="正在刷新盘口深度…" /> : null}
      {dataState === 'empty' ? <CardState label="当前品种没有盘口深度数据。" /> : null}
      {dataState === 'error' ? <CardState label="盘口深度暂时不可用，请稍后重试。" tone="error" /> : null}

      {dataState === 'ready' ? (
        <ScrollView style={styles.scroll} contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
          <View style={styles.section}>
            {asks.map((row) => (
              <BookRow key={`ask-${row.price}`} row={row} side="ask" />
            ))}
          </View>
          <View style={styles.midPrice}>
            <Text style={styles.midPriceText}>{last.toLocaleString('en-US', { maximumFractionDigits: 2 })}</Text>
            <Text style={styles.midPriceLabel}>最新成交</Text>
          </View>
          <View style={styles.section}>
            {bids.map((row) => (
              <BookRow key={`bid-${row.price}`} row={row} side="bid" />
            ))}
          </View>
        </ScrollView>
      ) : null}
    </View>
  );
}

function BookRow({
  row,
  side,
}: {
  row: TerminalOrderBookLevel;
  side: 'ask' | 'bid';
}) {
  const width = `${Math.min(100, Math.max(18, row.total))}%` as `${number}%`;
  const color = side === 'ask' ? terminalTheme.colors.sellSoft : terminalTheme.colors.buySoft;

  return (
    <View style={styles.bookRow}>
      <View style={[styles.depthBar, { width, backgroundColor: color }]} />
      <Text style={[styles.bookText, styles.priceCol, { color: side === 'ask' ? terminalTheme.colors.sell : terminalTheme.colors.buy }]}>
        {row.price.toLocaleString('en-US', { maximumFractionDigits: 2 })}
      </Text>
      <Text style={[styles.bookText, styles.sizeCol]}>{row.size.toFixed(2)}</Text>
      <Text style={[styles.bookText, styles.totalCol]}>{row.total.toFixed(2)}</Text>
    </View>
  );
}

function CardState({ label, tone = 'neutral' }: { label: string; tone?: 'neutral' | 'error' }) {
  return (
    <View style={styles.state}>
      <Text style={[styles.stateText, tone === 'error' && styles.stateError]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    borderRadius: terminalTheme.radius.md,
    backgroundColor: terminalTheme.colors.panel,
    padding: terminalTheme.spacing.md,
    gap: terminalTheme.spacing.sm,
    minHeight: 318,
  },
  title: {
    color: terminalTheme.colors.text,
    fontSize: 13,
    fontWeight: '700',
    fontFamily: terminalTheme.fonts.sans,
  },
  head: {
    flexDirection: 'row',
    gap: 8,
  },
  headText: {
    color: terminalTheme.colors.muted,
    fontSize: 10,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  },
  priceCol: {
    width: 84,
  },
  sizeCol: {
    width: 62,
    textAlign: 'right',
  },
  totalCol: {
    flex: 1,
    textAlign: 'right',
  },
  scroll: {
    flex: 1,
  },
  scrollContent: {
    gap: terminalTheme.spacing.sm,
  },
  section: {
    gap: 6,
  },
  bookRow: {
    minHeight: 28,
    paddingHorizontal: 8,
    borderRadius: terminalTheme.radius.xs,
    backgroundColor: terminalTheme.colors.chartBg,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    overflow: 'hidden',
  },
  depthBar: {
    ...StyleSheet.absoluteFillObject,
    right: 'auto',
  },
  bookText: {
    color: terminalTheme.colors.text,
    fontSize: 11,
    fontFamily: terminalTheme.fonts.mono,
    zIndex: 1,
  },
  midPrice: {
    minHeight: 40,
    borderRadius: terminalTheme.radius.sm,
    borderWidth: 1,
    borderColor: terminalTheme.colors.borderStrong,
    backgroundColor: terminalTheme.colors.panelMuted,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 2,
  },
  midPriceText: {
    color: terminalTheme.colors.text,
    fontSize: 18,
    fontWeight: '700',
    fontFamily: terminalTheme.fonts.mono,
  },
  midPriceLabel: {
    color: terminalTheme.colors.subtext,
    fontSize: 10,
  },
  state: {
    minHeight: 84,
    borderRadius: terminalTheme.radius.sm,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.chartBg,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 16,
  },
  stateText: {
    color: terminalTheme.colors.subtext,
    fontSize: 12,
    textAlign: 'center',
  },
  stateError: {
    color: terminalTheme.colors.sell,
  },
});
