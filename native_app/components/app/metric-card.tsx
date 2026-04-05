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

const toneColors: Record<Tone, { light: string; dark: string }> = {
  neutral: { light: '#183225', dark: '#F3FBF5' },
  info: { light: '#14804A', dark: '#7EE2A8' },
  success: { light: '#157347', dark: '#45D28A' },
  warning: { light: '#A16207', dark: '#F0BD63' },
  danger: { light: '#B42318', dark: '#FF7B72' },
};

export function MetricCard({ label, value, tone = 'neutral', compact = false }: MetricCardProps) {
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const toneKey = colorScheme === 'dark' ? 'dark' : 'light';

  return (
    <SurfaceCard style={[styles.card, compact ? styles.compact : styles.regular]}>
      <Text style={[styles.label, { color: palette.subtext }]}>{label}</Text>
      <View style={styles.valueWrap}>
        <Text style={[styles.value, { color: toneColors[tone][toneKey] }]} numberOfLines={1}>
          {value}
        </Text>
      </View>
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  card: {
    gap: 6,
  },
  regular: {
    minWidth: '47%',
    flex: 1,
  },
  compact: {
    flex: 1,
  },
  label: {
    fontSize: 11,
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  valueWrap: {
    minHeight: 28,
    justifyContent: 'flex-end',
  },
  value: {
    fontSize: 22,
    fontWeight: '800',
  },
});
