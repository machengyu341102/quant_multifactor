import { StyleSheet, Text, View } from 'react-native';

import { terminalTheme } from '@/constants/terminal-theme';
import type { TerminalMiniMarket } from '@/mocks/terminal-data';

interface MarketMiniStripProps {
  items: TerminalMiniMarket[];
}

export function MarketMiniStrip({ items }: MarketMiniStripProps) {
  return (
    <View style={styles.container}>
      {items.map((item) => {
        const positive = item.changePct >= 0;
        return (
          <View key={item.code} style={styles.row}>
            <View style={styles.main}>
              <Text style={styles.code}>{item.code}</Text>
              <Text style={styles.label}>{item.label}</Text>
            </View>
            <View style={styles.right}>
              <Text style={styles.price}>{item.price}</Text>
              <Text style={[styles.change, { color: positive ? terminalTheme.colors.buy : terminalTheme.colors.sell }]}>
                {positive ? '+' : ''}
                {item.changePct.toFixed(2)}%
              </Text>
            </View>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    gap: 8,
  },
  row: {
    minHeight: 42,
    borderRadius: terminalTheme.radius.sm,
    borderWidth: 1,
    borderColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.panel,
    paddingHorizontal: 10,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  main: {
    gap: 2,
  },
  right: {
    alignItems: 'flex-end',
    gap: 2,
  },
  code: {
    color: terminalTheme.colors.text,
    fontSize: 11,
    fontWeight: '700',
    fontFamily: terminalTheme.fonts.mono,
  },
  label: {
    color: terminalTheme.colors.subtext,
    fontSize: 10,
    fontFamily: terminalTheme.fonts.sans,
  },
  price: {
    color: terminalTheme.colors.text,
    fontSize: 11,
    fontWeight: '600',
    fontFamily: terminalTheme.fonts.mono,
  },
  change: {
    fontSize: 10,
    fontWeight: '700',
    fontFamily: terminalTheme.fonts.mono,
  },
});
