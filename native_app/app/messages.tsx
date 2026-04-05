import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors } from '@/constants/theme';
import { resolveAppHref } from '@/lib/app-routes';
import { formatTimestamp } from '@/lib/format';
import { getActionBoard, getAppMessages } from '@/lib/api';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRemoteResource } from '@/hooks/use-remote-resource';
import { useAuth } from '@/providers/auth-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';
import type { AppMessage } from '@/types/trading';

type MessageCategory = 'recommendation' | 'alert' | 'learning' | 'report';

function classifyMessage(message: AppMessage): MessageCategory {
  const text = `${message.title} ${message.body} ${message.preview} ${message.channel}`.toLowerCase();

  if (text.includes('经营画像')) {
    return 'report';
  }
  if (text.includes('隐蔽吸筹') || text.includes('小阳吸筹')) {
    return 'recommendation';
  }
  if (text.includes('顶层世界状态') || text.includes('世界引擎') || text.includes('顶层状态归档') || text.includes('跨资产')) {
    return 'report';
  }
  if (message.route?.includes('/industry-capital/')) {
    return message.level === 'warning' ? 'alert' : 'report';
  }
  if (text.includes('综合榜') || text.includes('接管')) {
    return 'recommendation';
  }
  if (text.includes('主线种子') || text.includes('主线孵化') || text.includes('中期波段') || text.includes('连涨接力')) {
    return 'recommendation';
  }
  if (message.level === 'warning' || text.includes('止损') || text.includes('告警') || text.includes('风险')) {
    return 'alert';
  }
  if (text.includes('学习') || text.includes('精进') || text.includes('回查') || text.includes('因子')) {
    return 'learning';
  }
  if (text.includes('报告') || text.includes('日报') || text.includes('总结')) {
    return 'report';
  }
  if (text.includes('推荐') || text.includes('信号') || text.includes('买入') || text.includes('候选')) {
    return 'recommendation';
  }

  return 'report';
}

function actionKindLabel(kind: string): string {
  if (kind === 'risk_alert' || kind === 'alert') {
    return '风险';
  }
  if (kind === 'position') {
    return '持仓';
  }
  if (kind === 'industry_capital') {
    return '方向';
  }
  if (kind === 'takeover') {
    return '接管';
  }
  if (kind === 'composite_pick') {
    return '推荐';
  }
  if (kind === 'learning') {
    return '学习';
  }
  return '待办';
}

function actionRouteForMessage(message: AppMessage): string {
  if (message.route) {
    return message.route;
  }
  const text = `${message.title} ${message.body} ${message.preview} ${message.channel}`.toLowerCase();
  if (text.includes('经营画像')) {
    return '/operating-profile';
  }
  if (text.includes('隐蔽吸筹') || text.includes('小阳吸筹')) {
    return '/hidden-accumulation';
  }
  if (text.includes('顶层世界状态') || text.includes('世界引擎') || text.includes('顶层状态归档') || text.includes('跨资产')) {
    return '/world';
  }
  if (text.includes('综合榜') || text.includes('接管')) {
    return '/(tabs)/signals';
  }
  if (text.includes('主线种子') || text.includes('主线孵化')) {
    return '/(tabs)/brain';
  }
  if (text.includes('中期波段') || text.includes('连涨接力')) {
    return '/(tabs)/signals';
  }
  const category = classifyMessage(message);
  if (category === 'recommendation') {
    return '/(tabs)/signals';
  }
  if (category === 'alert') {
    return '/(tabs)/positions';
  }
  if (category === 'learning') {
    return '/(tabs)/brain';
  }
  return '/(tabs)/index';
}

export default function MessagesScreen() {
  const router = useRouter();
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const { token } = useAuth();
  const { apiBaseUrl } = useRuntimeConfig();
  const { data, error, isPending, refreshing, refresh } = useRemoteResource(
    async () => {
      const [messages, actionBoard] = await Promise.all([
        getAppMessages(token ?? undefined, 50),
        getActionBoard(token ?? undefined, 6),
      ]);

      return { messages, actionBoard };
    },
    [token, apiBaseUrl],
    { refreshOnFocus: true }
  );
  const messages = data?.messages ?? [];
  const actionBoard = data?.actionBoard ?? [];
  const filteredMessages = messages;

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <Pressable
        onPress={() => {
          router.back();
        }}
        style={styles.backButton}>
        <Text style={[styles.backText, { color: palette.tint }]}>返回上一页</Text>
      </Pressable>

      <SectionHeading title="消息" />

      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在读取消息中心" />

      {actionBoard.length > 0 ? (
        <View style={styles.actionList}>
          {actionBoard.slice(0, 1).map((item) => (
            <SurfaceCard key={item.id} style={styles.cardGap}>
              <Text style={[styles.title, { color: palette.text }]}>{item.title}</Text>
              <Text style={[styles.bodyText, { color: palette.text }]}>{item.summary}</Text>
              <Text style={[styles.meta, { color: palette.subtext }]}>
                {actionKindLabel(item.kind)} / {item.level}
              </Text>
              <Pressable
                onPress={() => {
                  router.push(resolveAppHref(item.route ?? '/(tabs)/index'));
                }}
                style={[styles.primaryButton, { backgroundColor: palette.tint }]}>
                <Text style={styles.primaryButtonText}>{item.actionLabel}</Text>
              </Pressable>
            </SurfaceCard>
          ))}
        </View>
      ) : null}

      {filteredMessages.length === 0 && !error ? (
        <SurfaceCard>
          <Text style={[styles.emptyText, { color: palette.subtext }]}>
            当前还没有可展示的消息，等下一次同步。
          </Text>
        </SurfaceCard>
      ) : null}

      {filteredMessages.slice(0, 1).map((message) => {
        return (
          <SurfaceCard key={message.id} style={styles.card}>
            <View style={styles.headRow}>
              <View style={styles.titleWrap}>
                <Text style={[styles.title, { color: palette.text }]}>{message.title}</Text>
                <Text style={[styles.meta, { color: palette.subtext }]}>
                  {formatTimestamp(message.createdAt)}
                </Text>
              </View>
            </View>

            <Text style={[styles.preview, { color: palette.subtext }]} numberOfLines={2}>
              {message.preview || message.body}
            </Text>
            <Pressable
              onPress={() => {
                router.push(resolveAppHref(actionRouteForMessage(message)));
              }}
              style={[styles.inlineAction, { borderColor: palette.border }]}>
              <Text style={[styles.inlineActionText, { color: palette.tint }]}>打开</Text>
            </Pressable>
          </SurfaceCard>
        );
      })}
    </AppScreen>
  );
}

const styles = StyleSheet.create({
  backButton: {
    alignSelf: 'flex-start',
    paddingVertical: 6,
  },
  backText: {
    fontSize: 14,
    fontWeight: '700',
  },
  actionList: {
    gap: 12,
  },
  cardGap: {
    gap: 12,
  },
  primaryButton: {
    minHeight: 46,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 18,
  },
  primaryButtonText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '800',
  },
  inlineAction: {
    alignSelf: 'flex-start',
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
      inlineActionText: {
    fontSize: 12,
    fontWeight: '700',
  },
  emptyText: {
    fontSize: 14,
    lineHeight: 22,
  },
  card: {
    gap: 10,
  },
  headRow: {
    gap: 12,
  },
  titleWrap: {
    flex: 1,
    gap: 4,
  },
  title: {
    fontSize: 16,
    fontWeight: '800',
    lineHeight: 22,
  },
  meta: {
    fontSize: 12,
    lineHeight: 18,
  },
  preview: {
    fontSize: 13,
    lineHeight: 20,
  },
  bodyText: {
    fontSize: 14,
    lineHeight: 21,
  },
  hintText: {
    fontSize: 13,
    lineHeight: 20,
  },
});
