import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { terminalTheme } from '@/constants/terminal-theme';
import type { DataState, TerminalTradePrint } from '@/mocks/terminal-data';

interface TimeSalesCardProps {
  trades: TerminalTradePrint[];
  dataState: DataState;
}

export function TimeSalesCard({ trades, dataState }: TimeSalesCardProps) {
  return (
    <View style={styles.card}>
      <Text style={styles.title}>最近成交</Text>
      <View style={styles.head}>
        <Text style={[styles.headText, styles.timeCol]}>时间</Text>
        <Text style={[styles.headText, styles.priceCol]}>价格</Text>
        <Text style={[styles.headText, styles.sizeCol]}>数量</Text>
        <Text style={[styles.headText, styles.sideCol]}>方向</Text>
      </View>

      {dataState === 'loading' ? <CardState label="正在同步逐笔成交…" /> : null}
      {dataState === 'empty' ? <CardState label="当前品种没有逐笔成交。" /> : null}
      {dataState === 'error' ? <CardState label="逐笔成交暂时不可用。" tone="error" /> : null}

      {dataState === 'ready' ? (
        <ScrollView style={styles.scroll} contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
          {trades.map((trade) => {
            const positive = trade.side === 'buy';
            return (
              <View key={`${trade.time}-${trade.price}-${trade.size}`} style={styles.row}>
                <Text style={[styles.rowText, styles.timeCol]}>{trade.time}</Text>
                <Text
                  style={[
                    styles.rowText,
                    styles.priceCol,
                    { color: positive ? terminalTheme.colors.buy : terminalTheme.colors.sell },
                  ]}>
                  {trade.price.toLocaleString('en-US', { maximumFractionDigits: 2 })}
                </Text>
                <Text style={[styles.rowText, styles.sizeCol]}>{trade.size.toLocaleString('en-US')}</Text>
                <Text style={[styles.rowText, styles.sideCol]}>{positive ? '买' : '卖'}</Text>
              </View>
            );
          })}
        </ScrollView>
      ) : null}
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
    minHeight: 248,
  },
  title: {
    color: terminalTheme.colors.text,
    fontSize: 13,
    fontWeight: '700',
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
  timeCol: {
    width: 64,
  },
  priceCol: {
    width: 82,
    textAlign: 'right',
  },
  sizeCol: {
    flex: 1,
    textAlign: 'right',
  },
  sideCol: {
    width: 36,
    textAlign: 'right',
  },
  scroll: {
    flex: 1,
  },
  scrollContent: {
    gap: 6,
  },
  row: {
    minHeight: 28,
    borderRadius: terminalTheme.radius.xs,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.chartBg,
    paddingHorizontal: 8,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  rowText: {
    color: terminalTheme.colors.text,
    fontSize: 11,
    fontFamily: terminalTheme.fonts.mono,
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
