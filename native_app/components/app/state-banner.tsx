import { StyleSheet, Text } from 'react-native';

import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { SurfaceCard } from '@/components/app/surface-card';

interface StateBannerProps {
  error: string | null;
  isPending: boolean;
  loadingLabel: string;
}

export function StateBanner({ error, isPending, loadingLabel }: StateBannerProps) {
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];

  if (error) {
    return (
      <SurfaceCard style={[styles.card, { borderColor: palette.danger }]}>
        <Text style={[styles.text, { color: palette.danger }]}>加载失败: {error}</Text>
      </SurfaceCard>
    );
  }

  if (!isPending) {
    return null;
  }

  return (
    <SurfaceCard style={styles.card}>
      <Text style={[styles.text, { color: palette.subtext }]}>{loadingLabel}...</Text>
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  card: {
    paddingVertical: 14,
  },
  text: {
    fontSize: 14,
  },
});
