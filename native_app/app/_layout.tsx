import { DarkTheme, DefaultTheme, ThemeProvider } from '@react-navigation/native';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import 'react-native-reanimated';

import { NotificationRouteBridge } from '@/components/app/notification-route-bridge';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { AuthProvider } from '@/providers/auth-provider';
import { NotificationProvider } from '@/providers/notification-provider';
import { RuntimeConfigProvider } from '@/providers/runtime-config-provider';

export default function RootLayout() {
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const navigationTheme = colorScheme === 'dark'
    ? {
        ...DarkTheme,
        colors: {
          ...DarkTheme.colors,
          background: palette.background,
          border: palette.border,
          card: palette.surface,
          primary: palette.tint,
          text: palette.text,
        },
      }
    : {
        ...DefaultTheme,
        colors: {
          ...DefaultTheme.colors,
          background: palette.background,
          border: palette.border,
          card: palette.surface,
          primary: palette.tint,
          text: palette.text,
        },
      };

  return (
    <ThemeProvider value={navigationTheme}>
      <RuntimeConfigProvider>
        <AuthProvider>
          <NotificationProvider>
            <NotificationRouteBridge />
            <Stack
              screenOptions={{
                contentStyle: { backgroundColor: palette.background },
                headerStyle: { backgroundColor: palette.surface },
                headerTintColor: palette.text,
                headerShadowVisible: false,
              }}>
              <Stack.Screen name="index" options={{ headerShown: false }} />
              <Stack.Screen name="(auth)" options={{ headerShown: false }} />
              <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
              <Stack.Screen name="alerts" options={{ headerShown: false }} />
              <Stack.Screen name="feedback" options={{ headerShown: false }} />
              <Stack.Screen name="industry/[id]" options={{ headerShown: false }} />
              <Stack.Screen name="messages" options={{ headerShown: false }} />
              <Stack.Screen name="ops" options={{ headerShown: false }} />
              <Stack.Screen name="position/[code]" options={{ headerShown: false }} />
              <Stack.Screen name="records" options={{ headerShown: false }} />
              <Stack.Screen name="receipt" options={{ headerShown: false }} />
              <Stack.Screen name="signal/[id]" options={{ headerShown: false }} />
            </Stack>
          </NotificationProvider>
        </AuthProvider>
      </RuntimeConfigProvider>
      <StatusBar style={colorScheme === 'dark' ? 'light' : 'dark'} />
    </ThemeProvider>
  );
}
