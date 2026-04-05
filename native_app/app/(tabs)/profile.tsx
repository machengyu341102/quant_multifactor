import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { SectionHeading } from '@/components/app/section-heading';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRemoteResource } from '@/hooks/use-remote-resource';
import { getPushDevices } from '@/lib/api';
import { useAuth } from '@/providers/auth-provider';
import { useNotifications } from '@/providers/notification-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';

export default function ProfileScreen() {
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const router = useRouter();
  const { token, user, signOut } = useAuth();
  const { apiBaseUrl, defaultApiBaseUrl, saveApiBaseUrl, resetApiBaseUrl } = useRuntimeConfig();
  const {
    permissionState,
    remotePushState,
    requestPermission,
    registerRemotePush,
  } = useNotifications();
  const [draftBaseUrl, setDraftBaseUrl] = useState(apiBaseUrl);
  const { error: pushDevicesError, refresh: refreshPushDevices } = useRemoteResource(
    () => getPushDevices(token ?? undefined),
    [token, apiBaseUrl, remotePushState],
    { refreshOnFocus: true }
  );

  useEffect(() => {
    setDraftBaseUrl(apiBaseUrl);
  }, [apiBaseUrl]);

  return (
    <AppScreen>
      <SectionHeading title="我的" />

      <SurfaceCard style={styles.cardGap}>
        <View style={styles.row}>
          <View style={styles.main}>
            <Text style={[styles.title, { color: palette.text }]}>
              {user?.displayName ?? '未登录'}
            </Text>
            <Text style={[styles.body, { color: palette.subtext }]}>
              {user?.username ?? '--'} / {user?.role ?? '--'}
            </Text>
            <Text style={[styles.body, { color: palette.subtext }]}>
              {permissionState === 'granted' ? '通知已开' : '通知待开'}
            </Text>
          </View>
        </View>
      </SurfaceCard>

      <SurfaceCard style={styles.cardGap}>
        <Text style={[styles.body, { color: palette.subtext }]}>
          当前连接：{apiBaseUrl}
        </Text>
        {pushDevicesError ? (
          <Text style={[styles.body, { color: palette.danger }]}>{pushDevicesError}</Text>
        ) : null}
        <TextInput
          value={draftBaseUrl}
          onChangeText={setDraftBaseUrl}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          placeholder="http://42.121.222.147"
          placeholderTextColor={palette.icon}
          style={[
            styles.input,
            {
              borderColor: palette.border,
              backgroundColor: palette.surfaceMuted,
              color: palette.text,
            },
          ]}
        />
        <View style={styles.buttonRow}>
          <Pressable
            onPress={() => {
              void requestPermission();
            }}
            style={[styles.primaryButton, { backgroundColor: palette.tint }]}>
            <Text style={styles.primaryButtonText}>开启通知</Text>
          </Pressable>
          <Pressable
            onPress={() => {
              void registerRemotePush().then(() => {
                void refreshPushDevices();
              });
            }}
            style={[styles.secondaryButton, { borderColor: palette.border }]}>
            <Text style={[styles.secondaryButtonText, { color: palette.tint }]}>同步推送</Text>
          </Pressable>
        </View>
        <View style={styles.buttonRow}>
          <Pressable
            onPress={() => {
              void saveApiBaseUrl(draftBaseUrl);
            }}
            style={[styles.secondaryButton, { borderColor: palette.border }]}>
            <Text style={[styles.secondaryButtonText, { color: palette.tint }]}>保存地址</Text>
          </Pressable>
          <Pressable
            onPress={() => {
              setDraftBaseUrl(defaultApiBaseUrl);
              void resetApiBaseUrl();
            }}
            style={[styles.secondaryButton, { borderColor: palette.border }]}>
            <Text style={[styles.secondaryButtonText, { color: palette.tint }]}>恢复默认</Text>
          </Pressable>
        </View>
      </SurfaceCard>

      <View style={styles.buttonRow}>
        <Pressable
          onPress={() => {
            router.push('/messages' as never);
          }}
          style={[styles.secondaryButton, { borderColor: palette.border }]}>
          <Text style={[styles.secondaryButtonText, { color: palette.tint }]}>消息</Text>
        </Pressable>
        <Pressable
          onPress={() => {
            router.push('/operating-profile' as never);
          }}
          style={[styles.secondaryButton, { borderColor: palette.border }]}>
          <Text style={[styles.secondaryButtonText, { color: palette.tint }]}>经营画像</Text>
        </Pressable>
      </View>

      <View style={styles.buttonRow}>
        <Pressable
          onPress={() => {
            router.push('/terminal' as never);
          }}
          style={[styles.primaryButton, { backgroundColor: palette.tint }]}>
          <Text style={styles.primaryButtonText}>分析终端</Text>
        </Pressable>
      </View>

      <Pressable
        onPress={() => {
          void signOut();
        }}
        style={[styles.signOutButton, { borderColor: palette.border }]}>
        <Text style={[styles.signOutText, { color: palette.text }]}>退出登录</Text>
      </Pressable>
    </AppScreen>
  );
}

const styles = StyleSheet.create({
  cardGap: {
    gap: 12,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 12,
  },
  main: {
    flex: 1,
    gap: 4,
  },
  title: {
    fontSize: 20,
    fontWeight: '800',
    lineHeight: 26,
  },
  body: {
    fontSize: 14,
    lineHeight: 21,
  },
  input: {
    borderWidth: 1,
    borderRadius: 14,
    minHeight: 48,
    paddingHorizontal: 14,
    fontSize: 15,
  },
  buttonRow: {
    flexDirection: 'row',
    gap: 10,
  },
  primaryButton: {
    flex: 1,
    minHeight: 44,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 14,
    paddingHorizontal: 16,
  },
  primaryButtonText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '800',
  },
  secondaryButton: {
    flex: 1,
    minHeight: 44,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 14,
    borderWidth: 1,
    paddingHorizontal: 16,
  },
  secondaryButtonText: {
    fontSize: 14,
    fontWeight: '700',
  },
  signOutButton: {
    minHeight: 46,
    borderWidth: 1,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  signOutText: {
    fontSize: 14,
    fontWeight: '700',
  },
});
