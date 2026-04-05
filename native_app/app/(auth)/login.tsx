import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { Redirect } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useAuth } from '@/providers/auth-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';

export default function LoginScreen() {
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const { token, isSigningIn, signIn } = useAuth();
  const { apiBaseUrl, defaultApiBaseUrl, saveApiBaseUrl, resetApiBaseUrl } = useRuntimeConfig();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('SyHG!F1eK4*Y!5Re');
  const [draftBaseUrl, setDraftBaseUrl] = useState(apiBaseUrl);
  const [error, setError] = useState<string | null>(null);
  const selectedRole = username.trim().toLowerCase() === 'pilot' ? 'pilot' : 'admin';

  useEffect(() => {
    setDraftBaseUrl(apiBaseUrl);
  }, [apiBaseUrl]);

  if (token) {
    return <Redirect href="/(tabs)" />;
  }

  async function handleSubmit() {
    setError(null);
    try {
      if (draftBaseUrl.trim() && draftBaseUrl.trim() !== apiBaseUrl) {
        await saveApiBaseUrl(draftBaseUrl);
      }
      await signIn(username.trim(), password);
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败');
    }
  }

  function fillAccount(nextUsername: string, nextPassword: string) {
    setUsername(nextUsername);
    setPassword(nextPassword);
    setError(null);
  }

  return (
    <AppScreen contentStyle={styles.content}>
      <View style={styles.decorWrap} pointerEvents="none">
        <View style={[styles.decorBlob, styles.decorBlobLeft, { backgroundColor: palette.accentSoft }]} />
        <View
          style={[
            styles.decorBlob,
            styles.decorBlobRight,
            { backgroundColor: colorScheme === 'dark' ? '#173624' : '#DFF1E7' },
          ]}
        />
      </View>

      <SurfaceCard style={styles.formCard}>
        <Text style={[styles.eyebrow, { color: palette.subtext }]}>演示账号</Text>
        <View style={styles.quickRow}>
          <Pressable
            onPress={() => {
              fillAccount('admin', 'SyHG!F1eK4*Y!5Re');
            }}
            style={[
              styles.quickButton,
              selectedRole === 'admin'
                ? { backgroundColor: palette.accentSoft, borderColor: palette.tint }
                : { backgroundColor: palette.surface, borderColor: palette.border },
            ]}>
            <Text
              style={[
                styles.quickButtonText,
                { color: selectedRole === 'admin' ? palette.tint : palette.text },
              ]}>
              决策视角
            </Text>
          </Pressable>
          <Pressable
            onPress={() => {
              fillAccount('pilot', 'jlCOyZM#GwUPWSH4');
            }}
            style={[
              styles.quickButton,
              selectedRole === 'pilot'
                ? { backgroundColor: palette.accentSoft, borderColor: palette.tint }
                : { backgroundColor: palette.surface, borderColor: palette.border },
            ]}>
            <Text
              style={[
                styles.quickButtonText,
                { color: selectedRole === 'pilot' ? palette.tint : palette.text },
              ]}>
              实验视角
            </Text>
          </Pressable>
        </View>

        <Text style={[styles.label, { color: palette.subtext }]}>账号</Text>
        <TextInput
          autoComplete="off"
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="default"
          onChangeText={setUsername}
          placeholder="admin"
          placeholderTextColor={palette.icon}
          style={[
            styles.input,
            {
              backgroundColor: palette.surfaceMuted,
              borderColor: palette.border,
              color: palette.text,
            },
          ]}
          value={username}
        />

        <Text style={[styles.label, { color: palette.subtext }]}>密码</Text>
        <TextInput
          autoComplete="off"
          autoCapitalize="none"
          autoCorrect={false}
          onChangeText={setPassword}
          placeholder="输入服务端配置的登录密码"
          placeholderTextColor={palette.icon}
          secureTextEntry
          style={[
            styles.input,
            {
              backgroundColor: palette.surfaceMuted,
              borderColor: palette.border,
              color: palette.text,
            },
          ]}
          value={password}
        />

        <Pressable
          disabled={isSigningIn || !username.trim() || !password}
          onPress={() => {
            void handleSubmit();
          }}
          style={[
            styles.button,
            {
              backgroundColor:
                isSigningIn || !username.trim() || !password ? palette.icon : palette.tint,
            },
          ]}>
          {isSigningIn ? (
            <ActivityIndicator color="#FFFFFF" />
          ) : (
            <Text style={styles.buttonText}>进入演示系统</Text>
          )}
        </Pressable>

        {error ? <Text style={[styles.error, { color: palette.danger }]}>{error}</Text> : null}
        <Text style={[styles.label, { color: palette.subtext }]}>接口地址</Text>
        <TextInput
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          onChangeText={setDraftBaseUrl}
          placeholder="http://192.168.x.x:18000"
          placeholderTextColor={palette.icon}
          style={[
            styles.input,
            {
              backgroundColor: palette.surfaceMuted,
              borderColor: palette.border,
              color: palette.text,
            },
          ]}
          value={draftBaseUrl}
        />
        <View style={styles.quickRow}>
          <Pressable
            onPress={() => {
              void saveApiBaseUrl(draftBaseUrl);
              setError(null);
            }}
            style={[styles.quickButton, { backgroundColor: palette.accentSoft, borderColor: palette.tint }]}>
            <Text style={[styles.quickButtonText, { color: palette.tint }]}>保存地址</Text>
          </Pressable>
          <Pressable
            onPress={() => {
              setDraftBaseUrl(defaultApiBaseUrl);
              void resetApiBaseUrl();
              setError(null);
            }}
            style={[styles.quickButton, { backgroundColor: palette.surface, borderColor: palette.border }]}>
            <Text style={[styles.quickButtonText, { color: palette.text }]}>恢复默认</Text>
          </Pressable>
        </View>
        <Text style={[styles.helper, { color: palette.subtext }]}>当前连接: {apiBaseUrl}</Text>
        <Text style={[styles.helper, { color: palette.subtext }]}>
          决策视角默认是 `admin`，实验视角默认是 `pilot`。如果电脑换了 Wi-Fi 或 IP 变了，先把这里改成新的 API 地址再登录。
        </Text>
        <Text style={[styles.helper, { color: palette.subtext }]}>
          当前使用新密码，也兼容旧口径 `Alpha123456 / Pilot123456 / admin123 / pilot123`。
        </Text>
      </SurfaceCard>
    </AppScreen>
  );
}

const styles = StyleSheet.create({
  content: {
    justifyContent: 'center',
    flexGrow: 1,
    paddingTop: 24,
    paddingBottom: 56,
    position: 'relative',
  },
  decorWrap: {
    ...StyleSheet.absoluteFillObject,
  },
  decorBlob: {
    position: 'absolute',
    borderRadius: 999,
    opacity: 0.7,
  },
  decorBlobLeft: {
    width: 180,
    height: 180,
    top: -24,
    left: -52,
  },
  decorBlobRight: {
    width: 220,
    height: 220,
    top: -54,
    right: -84,
  },
  formCard: {
    gap: 10,
    borderRadius: 28,
    paddingTop: 18,
    paddingBottom: 18,
  },
  eyebrow: {
    fontSize: 13,
    fontWeight: '700',
  },
  quickRow: {
    flexDirection: 'row',
    gap: 10,
    marginBottom: 8,
  },
  quickButton: {
    flex: 1,
    borderWidth: 1,
    borderRadius: 16,
    paddingVertical: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  quickButtonText: {
    fontSize: 14,
    fontWeight: '700',
  },
  label: {
    fontSize: 13,
    fontWeight: '700',
  },
  input: {
    borderWidth: 1,
    borderRadius: 16,
    paddingHorizontal: 16,
    paddingVertical: 14,
    fontSize: 16,
  },
  button: {
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 16,
    marginTop: 8,
  },
  buttonText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '800',
  },
  error: {
    fontSize: 14,
    fontWeight: '600',
  },
  helper: {
    fontSize: 13,
    lineHeight: 20,
  },
});
