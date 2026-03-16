import { Pressable, StyleSheet, Text, View, type ViewStyle } from 'react-native';

import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { StatusPill } from '@/components/app/status-pill';

type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

export interface ExecutiveSummaryItem {
  key: string;
  step: string;
  title: string;
  meta?: string;
  body: string;
  onPress?: () => void;
  badgeLabel?: string;
  badgeTone?: Tone;
}

interface ExecutiveSummaryGridProps {
  items: ExecutiveSummaryItem[];
  style?: ViewStyle | ViewStyle[];
}

export function ExecutiveSummaryGrid({ items, style }: ExecutiveSummaryGridProps) {
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];

  return (
    <View style={[styles.grid, style]}>
      {items.map((item) => {
        const content = (
          <View
            style={[
              styles.card,
              {
                backgroundColor: palette.surfaceMuted,
                borderColor: palette.border,
              },
            ]}>
            <View style={styles.head}>
              <Text style={[styles.step, { color: palette.tint }]}>{item.step}</Text>
              {item.badgeLabel ? (
                <StatusPill label={item.badgeLabel} tone={item.badgeTone ?? 'neutral'} />
              ) : null}
            </View>
            <Text style={[styles.title, { color: palette.text }]}>{item.title}</Text>
            {item.meta ? (
              <Text style={[styles.meta, { color: palette.subtext }]}>{item.meta}</Text>
            ) : null}
            <Text style={[styles.body, { color: palette.text }]}>{item.body}</Text>
          </View>
        );

        if (item.onPress) {
          return (
            <Pressable key={item.key} onPress={item.onPress}>
              {content}
            </Pressable>
          );
        }

        return <View key={item.key}>{content}</View>;
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  grid: {
    gap: 12,
  },
  card: {
    borderWidth: 1,
    borderRadius: 22,
    padding: 16,
    gap: 8,
  },
  head: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    alignItems: 'center',
  },
  step: {
    flex: 1,
    fontSize: 12,
    fontWeight: '800',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  title: {
    fontSize: 18,
    fontWeight: '800',
    lineHeight: 24,
  },
  meta: {
    fontSize: 13,
    lineHeight: 20,
  },
  body: {
    fontSize: 14,
    lineHeight: 22,
  },
});
