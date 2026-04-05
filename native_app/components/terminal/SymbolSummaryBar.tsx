import { Animated, StyleSheet, Text, View } from 'react-native';
import { useEffect, useRef } from 'react';

import { terminalTheme } from '@/constants/terminal-theme';
import type { TerminalSymbol } from '@/mocks/terminal-data';

interface SymbolSummaryBarProps {
  symbol: TerminalSymbol;
  flashDirection: 'buy' | 'sell' | null;
}

export function SymbolSummaryBar({ symbol, flashDirection }: SymbolSummaryBarProps) {
  const flashValue = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (!flashDirection) {
      return;
    }
    flashValue.setValue(1);
    Animated.timing(flashValue, {
      toValue: 0,
      duration: 520,
      useNativeDriver: false,
    }).start();
  }, [flashDirection, flashValue, symbol.id, symbol.latestPrice]);

  const positive = symbol.changePct >= 0;
  const flashColor = flashDirection === 'buy' ? terminalTheme.colors.buySoft : terminalTheme.colors.sellSoft;
  const priceBackground = flashValue.interpolate({
    inputRange: [0, 1],
    outputRange: [terminalTheme.colors.panelMuted, flashColor],
  });

  return (
    <View style={styles.container}>
      <View style={styles.leftBlock}>
        <Text style={styles.symbolName}>{symbol.name}</Text>
        <View style={styles.codeRow}>
          <Text style={styles.symbolCode}>{symbol.code}</Text>
          <Text style={styles.marketText}>{symbol.marketLabel}</Text>
          {symbol.tags.map((tag) => (
            <View key={tag} style={styles.tag}>
              <Text style={styles.tagText}>{tag}</Text>
            </View>
          ))}
        </View>
      </View>

      <Animated.View style={[styles.priceBlock, { backgroundColor: priceBackground }]}>
        <Text style={styles.latestPrice}>{symbol.latestPrice.toLocaleString('en-US', { maximumFractionDigits: 2 })}</Text>
        <Text style={[styles.changeText, { color: positive ? terminalTheme.colors.buy : terminalTheme.colors.sell }]}>
          {positive ? '+' : ''}
          {symbol.change.toFixed(2)} / {positive ? '+' : ''}
          {symbol.changePct.toFixed(2)}%
        </Text>
      </Animated.View>

      <View style={styles.metricRow}>
        <Metric label="今日高" value={symbol.dayHigh.toLocaleString('en-US', { maximumFractionDigits: 2 })} />
        <Metric label="今日低" value={symbol.dayLow.toLocaleString('en-US', { maximumFractionDigits: 2 })} />
        <Metric label="成交量" value={symbol.volumeLabel} />
        <Metric label="成交额" value={symbol.turnoverLabel} />
      </View>
    </View>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.metric}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.metricValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.panel,
    borderRadius: terminalTheme.radius.md,
    paddingHorizontal: terminalTheme.spacing.lg,
    paddingVertical: terminalTheme.spacing.md,
    flexDirection: 'row',
    alignItems: 'center',
    gap: terminalTheme.spacing.lg,
  },
  leftBlock: {
    minWidth: 220,
    gap: 6,
  },
  symbolName: {
    color: terminalTheme.colors.text,
    fontSize: 18,
    lineHeight: 22,
    fontWeight: '700',
    fontFamily: terminalTheme.fonts.sans,
  },
  codeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    flexWrap: 'wrap',
  },
  symbolCode: {
    color: terminalTheme.colors.subtext,
    fontSize: 12,
    fontWeight: '700',
    fontFamily: terminalTheme.fonts.mono,
  },
  marketText: {
    color: terminalTheme.colors.subtext,
    fontSize: 12,
    fontFamily: terminalTheme.fonts.sans,
  },
  tag: {
    minHeight: 20,
    paddingHorizontal: 8,
    borderRadius: terminalTheme.radius.xs,
    backgroundColor: terminalTheme.colors.panelSoft,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  tagText: {
    color: terminalTheme.colors.text,
    fontSize: 10,
    fontWeight: '600',
  },
  priceBlock: {
    minWidth: 170,
    borderRadius: terminalTheme.radius.sm,
    borderWidth: 1,
    borderColor: terminalTheme.colors.borderStrong,
    paddingHorizontal: 14,
    paddingVertical: 10,
    gap: 4,
  },
  latestPrice: {
    color: terminalTheme.colors.text,
    fontSize: 24,
    lineHeight: 28,
    fontWeight: '800',
    fontFamily: terminalTheme.fonts.mono,
    fontVariant: ['tabular-nums'],
  },
  changeText: {
    fontSize: 12,
    fontWeight: '700',
    fontFamily: terminalTheme.fonts.mono,
  },
  metricRow: {
    flex: 1,
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: terminalTheme.spacing.md,
    justifyContent: 'flex-end',
  },
  metric: {
    minWidth: 88,
    gap: 4,
  },
  metricLabel: {
    color: terminalTheme.colors.subtext,
    fontSize: 11,
    fontFamily: terminalTheme.fonts.sans,
  },
  metricValue: {
    color: terminalTheme.colors.text,
    fontSize: 12,
    fontWeight: '600',
    fontFamily: terminalTheme.fonts.mono,
  },
});
