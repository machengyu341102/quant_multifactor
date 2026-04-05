import { PropsWithChildren } from 'react';
import { StyleSheet, View, ViewStyle } from 'react-native';

import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';

interface SurfaceCardProps extends PropsWithChildren {
  style?: ViewStyle | ViewStyle[];
}

export function SurfaceCard({ children, style }: SurfaceCardProps) {
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];

  return (
    <View
      style={[
        styles.card,
        {
          backgroundColor: palette.surface,
          borderColor: palette.border,
          shadowColor: colorScheme === 'dark' ? '#000000' : '#123222',
        },
        style,
      ]}>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderRadius: 9,
    padding: 10,
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.012,
    shadowRadius: 2,
    elevation: 0,
  },
});
