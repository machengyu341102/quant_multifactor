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
import { ExecutiveSummaryGrid } from '@/components/app/executive-summary-grid';
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
      <View style={[styles.hero, { backgroundColor: palette.hero }]}>
        <Text style={styles.eyebrow}>ALPHA AI / ACCESS</Text>
        <Text style={styles.title}>先进入系统，再讲能力链路</Text>
        <Text style={styles.copy}>
          这一页是演示入口。登录后直接看推荐、诊股、持仓、学习和消息镜像，不用先解释技术细节。
        </Text>
        <View style={styles.heroPills}>
          <Text style={styles.heroPill}>原生 App</Text>
          <Text style={styles.heroPill}>交易闭环</Text>
          <Text style={styles.heroPill}>学习系统</Text>
        </View>
      </View>

      <SurfaceCard style={styles.summaryCard}>
        <Text style={[styles.summaryTitle, { color: palette.text }]}>入口说明</Text>
        <ExecutiveSummaryGrid
          items={[
            {
              key: 'login-role',
              step: '01 账号视角',
              title: '决策 or 实验',
              body: '决策视角看主链路，实验视角看灰度能力和验证过程。',
            },
            {
              key: 'login-api',
              step: '02 接口地址',
              title: apiBaseUrl.includes('192.168.') ? '当前为局域网地址' : '当前为正式地址',
              body: '登录前先确认地址对不对，地址错了，账号密码对也进不去。',
            },
            {
              key: 'login-password',
              step: '03 密码兼容',
              title: '新旧口径都可用',
              body: '当前使用新密码，也兼容旧口径 `Alpha123456 / Pilot123456 / admin123 / pilot123`。',
            },
          ]}
        />
      </SurfaceCard>

      <SurfaceCard style={styles.formCard}>
        <Text style={[styles.label, { color: palette.subtext }]}>演示账号</Text>
        <View style={styles.quickRow}>
          <Pressable
            onPress={() => {
              fillAccount('admin', 'SyHG!F1eK4*Y!5Re');
            }}
            style={[styles.quickButton, { backgroundColor: palette.accentSoft, borderColor: palette.tint }]}>
            <Text style={[styles.quickButtonText, { color: palette.tint }]}>决策视角</Text>
          </Pressable>
          <Pressable
            onPress={() => {
              fillAccount('pilot', 'jlCOyZM#GwUPWSH4');
            }}
            style={[styles.quickButton, { backgroundColor: palette.surface, borderColor: palette.border }]}>
            <Text style={[styles.quickButtonText, { color: palette.text }]}>实验视角</Text>
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
          placeholder="http://192.168.x.x:8000"
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
  },
  hero: {
    borderRadius: 28,
    padding: 24,
    gap: 12,
  },
  eyebrow: {
    color: '#8CC7FF',
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1.4,
  },
  title: {
    color: '#F7FBFF',
    fontSize: 28,
    fontWeight: '800',
    lineHeight: 34,
  },
  copy: {
    color: '#C8D8EB',
    fontSize: 15,
    lineHeight: 22,
  },
  formCard: {
    gap: 10,
  },
  summaryCard: {
    gap: 12,
  },
  heroPills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  heroPill: {
    color: '#07111F',
    backgroundColor: '#DCE8FF',
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
    fontSize: 12,
    fontWeight: '800',
  },
  summaryTitle: {
    fontSize: 18,
    fontWeight: '800',
    lineHeight: 24,
  },
  quickRow: {
    flexDirection: 'row',
    gap: 10,
    marginBottom: 4,
  },
  quickButton: {
    flex: 1,
    borderWidth: 1,
    borderRadius: 14,
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
    borderRadius: 18,
    paddingHorizontal: 16,
    paddingVertical: 14,
    fontSize: 16,
  },
  button: {
    borderRadius: 18,
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
