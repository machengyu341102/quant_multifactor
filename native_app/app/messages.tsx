import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { SectionHeading } from '@/components/app/section-heading';
import { StateBanner } from '@/components/app/state-banner';
import { StatusPill } from '@/components/app/status-pill';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors } from '@/constants/theme';
import { resolveAppHref } from '@/lib/app-routes';
import { formatTimestamp } from '@/lib/format';
import { getActionBoard, getAppMessages } from '@/lib/api';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRemoteResource } from '@/hooks/use-remote-resource';
import { useAuth } from '@/providers/auth-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';
import type { ActionBoardItem, AppMessage } from '@/types/trading';

type MessageCategory = 'all' | 'recommendation' | 'alert' | 'learning' | 'report';
type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral';

function classifyMessage(message: AppMessage): MessageCategory {
  const text = `${message.title} ${message.body} ${message.preview} ${message.channel}`.toLowerCase();

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

function categoryLabel(category: MessageCategory): string {
  if (category === 'recommendation') {
    return '推荐';
  }
  if (category === 'alert') {
    return '告警';
  }
  if (category === 'learning') {
    return '学习';
  }
  if (category === 'report') {
    return '报告';
  }
  return '全部';
}

function levelTone(level: string): Tone {
  if (level === 'warning') {
    return 'warning';
  }
  if (level === 'error' || level === 'critical') {
    return 'danger';
  }
  if (level === 'success') {
    return 'success';
  }
  return 'info';
}

function actionLevelTone(level: ActionBoardItem['level']): Tone {
  if (level === 'critical') {
    return 'danger';
  }
  if (level === 'warning') {
    return 'warning';
  }
  return 'info';
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

function nextActionForMessage(message: AppMessage): string {
  const text = `${message.title} ${message.body} ${message.preview} ${message.channel}`.toLowerCase();
  if (message.route?.includes('/industry-capital/')) {
    if (message.level === 'warning') {
      return '先看方向深页定位阻力是在政策、客户、价格还是供应链，再决定要不要下调优先级。';
    }
    return '先看方向深页，把官方原文、兑现时间轴、合作对象和资本验证清单过一遍。';
  }
  if (text.includes('综合榜') || text.includes('接管')) {
    return '先去推荐页看接管判断，再回决策台看今天该不该继续盯综合榜。';
  }
  if (text.includes('主线种子') || text.includes('主线孵化')) {
    return '先去决策台复核主线脉络，再决定要不要转入推荐或现场诊股。';
  }
  if (text.includes('中期波段') || text.includes('连涨接力')) {
    return '先去推荐页看波段/连涨候选，再判断今天要不要纳入主观察清单。';
  }
  const category = classifyMessage(message);
  if (category === 'recommendation') {
    return '适合回到推荐页或决策台继续深看。';
  }
  if (category === 'alert') {
    return '优先回到首页或持仓页处理风险，不要只停留在消息里。';
  }
  if (category === 'learning') {
    return '适合去决策台看今天学到了什么、还差哪一步。';
  }
  return '更适合做汇报或留档，不一定需要立刻执行动作。';
}

function actionRouteForMessage(message: AppMessage): string {
  if (message.route) {
    return message.route;
  }
  const text = `${message.title} ${message.body} ${message.preview} ${message.channel}`.toLowerCase();
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
    [token, apiBaseUrl]
  );
  const [activeCategory, setActiveCategory] = useState<MessageCategory>('all');
  const messages = data?.messages ?? [];
  const actionBoard = data?.actionBoard ?? [];
  const mirrorMessages = messages.filter((item) => item.channel === 'wechat_mirror');
  const liveMessages = messages.filter((item) => item.channel !== 'wechat_mirror');
  const latestMirrorMessage = mirrorMessages[0] ?? null;
  const counts = {
    all: messages.length,
    recommendation: messages.filter((item) => classifyMessage(item) === 'recommendation').length,
    alert: messages.filter((item) => classifyMessage(item) === 'alert').length,
    learning: messages.filter((item) => classifyMessage(item) === 'learning').length,
    report: messages.filter((item) => classifyMessage(item) === 'report').length,
  };
  const filteredMessages =
    activeCategory === 'all'
      ? messages
      : messages.filter((item) => classifyMessage(item) === activeCategory);
  const focusMessage = filteredMessages[0] ?? messages[0] ?? null;
  const categories: MessageCategory[] = ['all', 'recommendation', 'alert', 'learning', 'report'];

  return (
    <AppScreen refreshing={refreshing} onRefresh={refresh}>
      <Pressable
        onPress={() => {
          router.back();
        }}
        style={styles.backButton}>
        <Text style={[styles.backText, { color: palette.tint }]}>返回上一页</Text>
      </Pressable>

      <SectionHeading
        eyebrow="Message Center"
        title="后备消息中心"
        subtitle="APP 是主阵地；这页只负责兜底触达、留痕复盘和异常补发，不再承担主操作链路。"
      />

      <View style={[styles.hero, { backgroundColor: palette.hero }]}>
        <Text style={styles.heroEyebrow}>BACKUP STREAM</Text>
        <Text style={styles.heroTitle}>微信只是后备，不再是主战场</Text>
        <Text style={styles.heroCopy}>
          这里保留外发消息和兜底提醒，但真正的实时判断、深页和操作链已经回到 APP 内完成。
        </Text>
        <View style={styles.heroPills}>
          <StatusPill label={`总消息 ${counts.all}`} tone="info" />
          <StatusPill label={`微信镜像 ${mirrorMessages.length}`} tone="warning" />
          <StatusPill label={`APP实时 ${liveMessages.length}`} tone="success" />
          <StatusPill label={`推荐 ${counts.recommendation}`} tone="success" />
          <StatusPill label={`告警 ${counts.alert}`} tone="warning" />
          <StatusPill label={`待办 ${actionBoard.length}`} tone={actionBoard.length > 0 ? 'info' : 'neutral'} />
        </View>
      </View>

      <StateBanner error={error} isPending={isPending && !data} loadingLabel="正在读取消息中心" />

      <SurfaceCard style={styles.cardGap}>
        <View style={styles.channelSplit}>
          <View style={[styles.channelPanel, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <Text style={[styles.channelTitle, { color: palette.text }]}>APP 主阵地</Text>
            <Text style={[styles.channelCopy, { color: palette.subtext }]}>
              推荐、方向深页、持仓纪律和学习状态都以 APP 实时数据为准，先回主界面处理，再看消息回放。
            </Text>
            <View style={styles.focusPills}>
              <StatusPill label={`实时 ${liveMessages.length}`} tone="success" />
              <StatusPill label={`待办 ${actionBoard.length}`} tone={actionBoard.length > 0 ? 'info' : 'neutral'} />
            </View>
            <Pressable
              onPress={() => {
                router.push('/');
              }}
              style={[styles.primaryButton, { backgroundColor: palette.tint }]}>
              <Text style={styles.primaryButtonText}>回首页主链路</Text>
            </Pressable>
          </View>

          <View style={[styles.channelPanel, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <Text style={[styles.channelTitle, { color: palette.text }]}>微信后备</Text>
            <Text style={[styles.channelCopy, { color: palette.subtext }]}>
              {latestMirrorMessage
                ? `最近镜像时间 ${formatTimestamp(latestMirrorMessage.createdAt)}，适合兜底提醒、汇报和复盘留档。`
                : '当前还没有新的微信镜像，说明你现在应该直接看 APP。'}
            </Text>
            <View style={styles.focusPills}>
              <StatusPill label={`镜像 ${mirrorMessages.length}`} tone="warning" />
              <StatusPill label="只做备份" tone="neutral" />
            </View>
          </View>
        </View>
      </SurfaceCard>

      {actionBoard.length > 0 ? (
        <>
          <SectionHeading title="系统待办" subtitle="先把系统已经整理好的动作单看完，再决定是否需要回看后备消息。" />
          <View style={styles.actionList}>
            {actionBoard.slice(0, 3).map((item) => (
              <SurfaceCard key={item.id} style={styles.cardGap}>
                <View style={styles.focusHead}>
                  <View style={styles.focusMain}>
                    <Text style={[styles.focusTitle, { color: palette.text }]}>{item.title}</Text>
                    <Text style={[styles.focusMeta, { color: palette.subtext }]}>
                      {formatTimestamp(item.createdAt)} / {actionKindLabel(item.kind)}
                    </Text>
                  </View>
                  <View style={styles.focusPills}>
                    <StatusPill label={actionKindLabel(item.kind)} tone="info" />
                    <StatusPill label={item.level} tone={actionLevelTone(item.level)} />
                  </View>
                </View>
                <Text style={[styles.bodyText, { color: palette.text }]}>{item.summary}</Text>
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
        </>
      ) : null}

      {focusMessage ? (
        <>
          <SectionHeading title="当前焦点消息" subtitle="先把最值得讲的一条提到最上面。" />
          <SurfaceCard style={styles.cardGap}>
            <View style={styles.focusHead}>
              <View style={styles.focusMain}>
                <Text style={[styles.focusTitle, { color: palette.text }]}>{focusMessage.title}</Text>
                <Text style={[styles.focusMeta, { color: palette.subtext }]}>
                  {formatTimestamp(focusMessage.createdAt)} / {focusMessage.channel}
                </Text>
              </View>
              <View style={styles.focusPills}>
                <StatusPill label={categoryLabel(classifyMessage(focusMessage))} tone="info" />
                <StatusPill label={focusMessage.level} tone={levelTone(focusMessage.level)} />
              </View>
            </View>
            <Text style={[styles.bodyText, { color: palette.text }]}>{focusMessage.body}</Text>
            <Text style={[styles.hintText, { color: palette.subtext }]}>
              {nextActionForMessage(focusMessage)}
            </Text>
            <Pressable
              onPress={() => {
                router.push(resolveAppHref(actionRouteForMessage(focusMessage)));
              }}
              style={[styles.primaryButton, { backgroundColor: palette.tint }]}>
              <Text style={styles.primaryButtonText}>去对应页面</Text>
            </Pressable>
          </SurfaceCard>
        </>
      ) : null}

      <SectionHeading title="消息分类" subtitle="筛掉杂音，直接看推荐、告警、学习或报告。" />
      <View style={styles.filterRow}>
        {categories.map((category) => (
          <Pressable
            key={category}
            onPress={() => {
              setActiveCategory(category);
            }}
            style={[
              styles.filterChip,
              {
                backgroundColor: activeCategory === category ? palette.accentSoft : palette.surface,
                borderColor: activeCategory === category ? palette.tint : palette.border,
              },
            ]}>
            <Text
              style={[
                styles.filterChipText,
                { color: activeCategory === category ? palette.tint : palette.text },
              ]}>
              {categoryLabel(category)} {counts[category]}
            </Text>
          </Pressable>
        ))}
      </View>

      {filteredMessages.length === 0 && !error ? (
        <SurfaceCard>
          <Text style={[styles.emptyText, { color: palette.subtext }]}>
            当前这个分类还没有消息。换一个分类，或者等下一次外发同步。
          </Text>
        </SurfaceCard>
      ) : null}

      {filteredMessages.map((message) => {
        const category = classifyMessage(message);

        return (
          <SurfaceCard key={message.id} style={styles.card}>
            <View style={styles.headRow}>
              <View style={styles.titleWrap}>
                <Text style={[styles.title, { color: palette.text }]}>{message.title}</Text>
                <Text style={[styles.meta, { color: palette.subtext }]}>
                  {formatTimestamp(message.createdAt)} / {message.channel}
                </Text>
              </View>
              <View style={styles.pillStack}>
                <StatusPill label={categoryLabel(category)} tone="info" />
                <StatusPill label={message.level} tone={levelTone(message.level)} />
              </View>
            </View>

            <Text style={[styles.preview, { color: palette.subtext }]}>{message.preview || message.body}</Text>
            <Text style={[styles.bodyText, { color: palette.text }]}>{message.body}</Text>
            <View style={[styles.hintBox, { backgroundColor: palette.surfaceMuted }]}>
              <Text style={[styles.hintTitle, { color: palette.text }]}>怎么用这条消息</Text>
              <Text style={[styles.hintText, { color: palette.subtext }]}>{nextActionForMessage(message)}</Text>
            </View>
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
  hero: {
    borderRadius: 28,
    padding: 24,
    gap: 12,
  },
  heroEyebrow: {
    color: '#8CC7FF',
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 1.4,
  },
  heroTitle: {
    color: '#F7FBFF',
    fontSize: 28,
    fontWeight: '800',
    lineHeight: 34,
  },
  heroCopy: {
    color: '#C8D8EB',
    fontSize: 15,
    lineHeight: 22,
  },
  heroPills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  actionList: {
    gap: 12,
  },
  channelSplit: {
    gap: 12,
  },
  channelPanel: {
    borderWidth: 1,
    borderRadius: 22,
    padding: 16,
    gap: 12,
  },
  channelTitle: {
    fontSize: 18,
    fontWeight: '800',
    lineHeight: 24,
  },
  channelCopy: {
    fontSize: 14,
    lineHeight: 22,
  },
  cardGap: {
    gap: 14,
  },
  focusHead: {
    gap: 10,
  },
  focusMain: {
    gap: 4,
  },
  focusTitle: {
    fontSize: 20,
    fontWeight: '800',
    lineHeight: 26,
  },
  focusMeta: {
    fontSize: 13,
    lineHeight: 20,
  },
  focusPills: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
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
  filterRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 10,
  },
  filterChip: {
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  filterChipText: {
    fontSize: 13,
    fontWeight: '700',
  },
  emptyText: {
    fontSize: 14,
    lineHeight: 22,
  },
  card: {
    gap: 12,
  },
  headRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    alignItems: 'flex-start',
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
  pillStack: {
    alignItems: 'flex-end',
    gap: 8,
  },
  preview: {
    fontSize: 13,
    lineHeight: 20,
  },
  bodyText: {
    fontSize: 14,
    lineHeight: 22,
  },
  hintBox: {
    borderRadius: 18,
    padding: 14,
    gap: 6,
  },
  hintTitle: {
    fontSize: 14,
    fontWeight: '800',
  },
  hintText: {
    fontSize: 13,
    lineHeight: 20,
  },
});
