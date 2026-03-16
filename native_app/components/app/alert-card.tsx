import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import type { RiskAlert } from '@/types/trading';
import { StatusPill } from '@/components/app/status-pill';

interface AlertCardProps {
  alert: RiskAlert;
  onPress?: () => void;
}

const levelLabel: Record<RiskAlert['level'], string> = {
  critical: '紧急',
  warning: '注意',
  info: '提示',
};

const levelTone: Record<RiskAlert['level'], 'danger' | 'warning' | 'info'> = {
  critical: 'danger',
  warning: 'warning',
  info: 'info',
};

export function AlertCard({ alert, onPress }: AlertCardProps) {
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const content = (
    <View style={[styles.card, { borderColor: palette.border, backgroundColor: palette.surface }]}>
      <View style={styles.header}>
        <StatusPill label={levelLabel[alert.level]} tone={levelTone[alert.level]} />
        <Text style={[styles.source, { color: palette.subtext }]}>{alert.source}</Text>
      </View>
      <Text style={[styles.title, { color: palette.text }]}>{alert.title}</Text>
      <Text style={[styles.message, { color: palette.subtext }]}>{alert.message}</Text>
      {alert.route ? <Text style={[styles.action, { color: palette.tint }]}>点开处理</Text> : null}
    </View>
  );

  if (!onPress) {
    return content;
  }

  return (
    <Pressable onPress={onPress} style={({ pressed }) => (pressed ? styles.pressed : undefined)}>
      {content}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderRadius: 24,
    padding: 18,
    gap: 10,
  },
  pressed: {
    opacity: 0.92,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  source: {
    fontSize: 12,
    fontWeight: '700',
    textTransform: 'uppercase',
  },
  title: {
    fontSize: 16,
    fontWeight: '800',
  },
  message: {
    fontSize: 14,
    lineHeight: 22,
  },
  action: {
    fontSize: 13,
    fontWeight: '700',
  },
});
