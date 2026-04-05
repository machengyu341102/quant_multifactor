import { StyleSheet, Text, View } from 'react-native';

import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import type { KlineBar } from '@/types/trading';

interface KlineSnapshotProps {
  bars: KlineBar[];
  emptyLabel?: string;
}

export function KlineSnapshot({
  bars,
  emptyLabel = '历史K线暂不可用，后端行情源返回为空。',
}: KlineSnapshotProps) {
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const visibleBars = bars.slice(-6).reverse();

  if (visibleBars.length === 0) {
    return <Text style={[styles.emptyText, { color: palette.subtext }]}>{emptyLabel}</Text>;
  }

  const minLow = Math.min(...visibleBars.map((bar) => bar.low));
  const maxHigh = Math.max(...visibleBars.map((bar) => bar.high));
  const scale = Math.max(maxHigh - minLow, 0.01);

  function toPercent(value: number) {
    return ((value - minLow) / scale) * 100;
  }

  return (
    <View style={styles.wrap}>
      {visibleBars.map((bar) => {
        const isUp = bar.close >= bar.open;
        const bodyLeft = Math.min(bar.open, bar.close);
        const bodyRight = Math.max(bar.open, bar.close);
        const rangeLeft = toPercent(bar.low);
        const rangeWidth = Math.max(2, toPercent(bar.high) - rangeLeft);
        const bodyStart = toPercent(bodyLeft);
        const bodyWidth = Math.max(4, toPercent(bodyRight) - bodyStart);

        return (
          <View key={bar.date} style={styles.row}>
            <Text style={[styles.date, { color: palette.subtext }]}>{bar.date.slice(5)}</Text>
            <View style={[styles.track, { backgroundColor: palette.surfaceMuted }]}>
              <View
                style={[
                  styles.range,
                  {
                    left: `${rangeLeft}%`,
                    width: `${rangeWidth}%`,
                    backgroundColor: palette.border,
                  },
                ]}
              />
              <View
                style={[
                  styles.body,
                  {
                    left: `${bodyStart}%`,
                    width: `${bodyWidth}%`,
                    backgroundColor: isUp ? palette.success : palette.danger,
                  },
                ]}
              />
            </View>
            <Text style={[styles.close, { color: palette.text }]}>{bar.close.toFixed(2)}</Text>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    gap: 8,
  },
  emptyText: {
    fontSize: 14,
    lineHeight: 22,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  date: {
    width: 42,
    fontSize: 12,
    fontWeight: '600',
  },
  track: {
    flex: 1,
    height: 16,
    borderRadius: 999,
    position: 'relative',
    overflow: 'hidden',
    justifyContent: 'center',
  },
  range: {
    position: 'absolute',
    height: 2,
    borderRadius: 999,
    top: 7,
  },
  body: {
    position: 'absolute',
    height: 7,
    borderRadius: 999,
    top: 4.5,
    minWidth: 4,
  },
  close: {
    width: 44,
    fontSize: 12,
    textAlign: 'right',
    fontWeight: '700',
  },
});
