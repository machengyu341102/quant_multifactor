import { Redirect } from 'expo-router';
import { Text } from 'react-native';

import { AppScreen } from '@/components/app/app-screen';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useAuth } from '@/providers/auth-provider';

export default function IndexScreen() {
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const { isBooting, token } = useAuth();

  if (isBooting) {
    return (
      <AppScreen>
        <SurfaceCard>
          <Text style={{ color: palette.text, fontSize: 16, fontWeight: '700' }}>
            正在校验登录状态...
          </Text>
        </SurfaceCard>
      </AppScreen>
    );
  }

  return <Redirect href={token ? '/(tabs)' : '/(auth)/login'} />;
}
