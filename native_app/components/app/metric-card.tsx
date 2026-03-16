import { StyleSheet, Text, View } from 'react-native';

import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { SurfaceCard } from '@/components/app/surface-card';

type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

interface MetricCardProps {
  label: string;
  value: string;
  tone?: Tone;
  compact?: boolean;
}

const toneColors: Record<Tone, string> = {
  neutral: '#09131F',
  info: '#155EEF',
  success: '#0E9F6E',
  warning: '#D97706',
  danger: '#C2410C',
};

export function MetricCard({ label, value, tone = 'neutral', compact = false }: MetricCardProps) {
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];

  return (
    <SurfaceCard style={[styles.card, compact ? styles.compact : styles.regular]}>
      <Text style={[styles.label, { color: palette.subtext }]}>{label}</Text>
      <View style={styles.valueWrap}>
        <Text style={[styles.value, { color: toneColors[tone] }]} numberOfLines={1}>
          {value}
        </Text>
      </View>
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  card: {
    gap: 10,
  },
  regular: {
    minWidth: '47%',
    flex: 1,
  },
  compact: {
    flex: 1,
  },
  label: {
    fontSize: 12,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
  },
  valueWrap: {
    minHeight: 36,
    justifyContent: 'flex-end',
  },
  value: {
    fontSize: 28,
    fontWeight: '800',
  },
});
