import { StyleSheet, Text, View } from 'react-native';

import { terminalTheme } from '@/constants/terminal-theme';

interface StatusBarProps {
  dataSource: string;
  network: string;
  latencyMs: number;
  timezone: string;
  environment: string;
}

export function StatusBar({
  dataSource,
  network,
  latencyMs,
  timezone,
  environment,
}: StatusBarProps) {
  return (
    <View style={styles.container}>
      <Text style={styles.item}>数据源 {dataSource}</Text>
      <Text style={styles.item}>网络 {network}</Text>
      <Text style={styles.item}>延迟 {latencyMs}ms</Text>
      <Text style={styles.item}>时区 {timezone}</Text>
      <Text style={[styles.item, styles.environment]}>{environment}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    minHeight: terminalTheme.layout.statusHeight,
    borderTopWidth: 1,
    borderTopColor: terminalTheme.colors.border,
    backgroundColor: terminalTheme.colors.page,
    paddingHorizontal: terminalTheme.spacing.lg,
    flexDirection: 'row',
    alignItems: 'center',
    gap: terminalTheme.spacing.md,
    flexWrap: 'wrap',
  },
  item: {
    color: terminalTheme.colors.subtext,
    fontSize: 11,
    fontFamily: terminalTheme.fonts.mono,
  },
  environment: {
    color: terminalTheme.colors.warning,
  },
});
