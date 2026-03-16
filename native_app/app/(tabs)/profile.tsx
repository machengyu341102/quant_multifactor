import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { useRouter } from 'expo-router';

import { AppScreen } from '@/components/app/app-screen';
import { ExecutiveSummaryGrid } from '@/components/app/executive-summary-grid';
import { SectionHeading } from '@/components/app/section-heading';
import { StatusPill } from '@/components/app/status-pill';
import { SurfaceCard } from '@/components/app/surface-card';
import { Colors } from '@/constants/theme';
import { useColorScheme } from '@/hooks/use-color-scheme';
import { useRemoteResource } from '@/hooks/use-remote-resource';
import { formatTimestamp } from '@/lib/format';
import {
  getIndustryResearchPushStatus,
  getPushDevices,
  getTakeoverPushStatus,
  updateTakeoverPushSettings,
} from '@/lib/api';
import { useAuth } from '@/providers/auth-provider';
import { useNotifications } from '@/providers/notification-provider';
import { useRuntimeConfig } from '@/providers/runtime-config-provider';

const checklist = [
  '准备公网域名、HTTPS 和下载页',
  '把推送配置补齐到真机可离线下发',
  '再收一轮首页、推荐、持仓的文案和配色',
  '整理基金公司交流版演示脚本和边界说明',
];

type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral';

function buildControlVerdict(params: {
  permissionGranted: boolean;
  remoteReady: boolean;
  hasDevices: boolean;
  apiBaseUrl: string;
  role: string | undefined;
}): {
  title: string;
  tone: Tone;
  summary: string;
  blockers: string[];
} {
  const blockers: string[] = [];

  if (!params.permissionGranted) {
    blockers.push('通知权限还没完全放开，真机提醒体验还不算完整。');
  }
  if (!params.remoteReady) {
    blockers.push('远程推送还没完全同步，离线下发链路还差最后一步。');
  }
  if (!params.hasDevices) {
    blockers.push('还没有真机设备注册到后台，推送链只能算半通。');
  }
  if (params.apiBaseUrl.includes('192.168.')) {
    blockers.push('当前还是局域网地址，演示之外还不能随时随地访问。');
  }

  if (blockers.length === 0) {
    return {
      title: '控制中心状态健康',
      tone: 'success',
      summary: '账号、通知、设备和连接都在位，这一页已经更像交付控制台，而不是设置页。',
      blockers,
    };
  }

  if (blockers.length <= 2) {
    return {
      title: '离交付还差最后几步',
      tone: 'info',
      summary: '主链已经能跑，剩下是把推送、连接和分发收紧，不是重新做产品。',
      blockers,
    };
  }

  return {
    title: '现在更适合内测，不适合硬吹交付',
    tone: 'warning',
    summary: '产品链路已经通了，但从演示到持续交付之间，还有几项关键基础设施没补完。',
    blockers,
  };
}

export default function ProfileScreen() {
  const colorScheme = useColorScheme();
  const palette = Colors[colorScheme ?? 'light'];
  const router = useRouter();
  const { token, user, signOut } = useAuth();
  const {
    isSupported,
    permissionState,
    remotePushState,
    expoPushToken,
    lastError,
    lastDispatchResult,
    requestPermission,
    registerRemotePush,
    sendPreviewNotification,
    sendRemotePreviewNotification,
    sendRemoteTakeoverNotification,
    sendRemoteTakeoverResend,
    sendRemoteTakeoverPreview,
    runRemoteTakeoverAuto,
  } = useNotifications();
  const { apiBaseUrl, defaultApiBaseUrl, saveApiBaseUrl, resetApiBaseUrl } = useRuntimeConfig();
  const [draftBaseUrl, setDraftBaseUrl] = useState(apiBaseUrl);
  const {
    data: pushDevices,
    error: pushDevicesError,
    refresh: refreshPushDevices,
  } = useRemoteResource(() => getPushDevices(token ?? undefined), [token, apiBaseUrl, remotePushState]);
  const {
    data: takeoverPushStatus,
    error: takeoverPushStatusError,
    refresh: refreshTakeoverPushStatus,
  } = useRemoteResource(() => getTakeoverPushStatus(token ?? undefined), [token, apiBaseUrl, remotePushState]);
  const {
    data: industryResearchPushStatus,
    error: industryResearchPushStatusError,
    refresh: refreshIndustryResearchPushStatus,
  } = useRemoteResource(() => getIndustryResearchPushStatus(token ?? undefined), [token, apiBaseUrl, remotePushState]);

  const maskedPushToken = expoPushToken
    ? `${expoPushToken.slice(0, 18)}...${expoPushToken.slice(-8)}`
    : '尚未同步';

  useEffect(() => {
    setDraftBaseUrl(apiBaseUrl);
  }, [apiBaseUrl]);

  const controlVerdict = buildControlVerdict({
    permissionGranted: permissionState === 'granted',
    remoteReady: remotePushState === 'ready',
    hasDevices: Boolean(pushDevices && pushDevices.length > 0),
    apiBaseUrl,
    role: user?.role,
  });

  const quickEntries = [
    {
      key: 'messages',
      title: '消息中心',
      copy: '看微信镜像、推荐和学习回放。',
      route: '/messages',
    },
    {
      key: 'feedback',
      title: '反馈窗口',
      copy: '继续收用户意见，但最终由你决策。',
      route: '/feedback',
    },
    {
      key: 'ops',
      title: '运维诊断',
      copy: '查看健康、延迟、错误率和数据状态。',
      route: '/ops',
    },
    {
      key: 'records',
      title: '交易记录',
      copy: '看最近动作、回执和组合历史。',
      route: '/records',
    },
  ];

  return (
    <AppScreen>
      <SectionHeading
        eyebrow="Control Center"
        title="控制中心"
        subtitle="这页现在不只是设置，而是把交付、推送、反馈和连接统一收口。"
      />

      <View style={[styles.hero, { backgroundColor: palette.hero }]}>
        <Text style={styles.heroEyebrow}>DELIVERY CONSOLE</Text>
        <Text style={styles.heroTitle}>{controlVerdict.title}</Text>
        <Text style={styles.heroCopy}>{controlVerdict.summary}</Text>
        <View style={styles.heroPills}>
          <StatusPill label={user?.role ?? '未登录'} tone="neutral" />
          <StatusPill
            label={permissionState === 'granted' ? '通知已开' : '通知待开'}
            tone={permissionState === 'granted' ? 'success' : 'warning'}
          />
          <StatusPill
            label={remotePushState === 'ready' ? '远程推送已通' : '远程推送待同步'}
            tone={remotePushState === 'ready' ? 'success' : 'warning'}
          />
          <StatusPill label={`${pushDevices?.length ?? 0} 台设备`} tone="info" />
        </View>
      </View>

      <SectionHeading
        title="一页交付判断"
        subtitle="先把账号、连接、推送和交付阻塞压成一页，再往下看具体配置。"
      />
      <SurfaceCard style={styles.cardGap}>
        <ExecutiveSummaryGrid
          items={[
            {
              key: 'profile-account',
              step: '01 当前账号',
              title: user?.displayName ?? '未登录',
              meta: `${user?.username ?? '--'} / 角色 ${user?.role ?? '--'}`,
              body: '当前控制中心已经承担交付、连接、反馈和推送收口，不再只是设置页。',
            },
            {
              key: 'profile-api',
              step: '02 当前连接',
              title: apiBaseUrl.includes('192.168.') ? '局域网内测链路' : '公网/正式链路',
              meta: apiBaseUrl,
              body: apiBaseUrl.includes('192.168.')
                ? '当前更适合内测和演示，距离随时随地访问还差域名、HTTPS 和正式分发。'
                : '连接层已经更接近正式产品形态，可以继续收口分发和推送。',
            },
            {
              key: 'profile-push',
              step: '03 推送状态',
              title: remotePushState === 'ready' ? '远程推送已就绪' : '远程推送待收口',
              meta: `通知 ${permissionState} / 设备 ${pushDevices?.length ?? 0} 台`,
              body: remotePushState === 'ready'
                ? '远程推送主链已经打通，接下来重点是让真机注册更稳定。'
                : '当前还没完全进入可持续离线下发状态，先把通知权限和设备注册补齐。',
            },
            {
              key: 'profile-blocker',
              step: '04 当前阻塞',
              title: controlVerdict.blockers[0] ?? '当前没有明显交付阻塞',
              meta: `状态 ${controlVerdict.title}`,
              body: controlVerdict.summary,
            },
          ]}
        />
      </SurfaceCard>

      <SectionHeading title="当前状态" subtitle="先把角色、连接和当前阻塞点说透。" />
      <SurfaceCard style={styles.cardGap}>
        <View style={styles.identityRow}>
          <View style={styles.identityMain}>
            <Text style={[styles.blockTitle, { color: palette.text }]}>
              {user?.displayName ?? '未登录'} / {user?.username ?? '--'}
            </Text>
            <Text style={[styles.blockBody, { color: palette.subtext }]}>
              角色 {user?.role ?? '--'} / 当前连接 {apiBaseUrl}
            </Text>
          </View>
          <StatusPill label={controlVerdict.title} tone={controlVerdict.tone} />
        </View>

        {controlVerdict.blockers.length > 0 ? (
          controlVerdict.blockers.map((item) => (
            <View key={item} style={styles.rowWithDot}>
              <View style={[styles.dot, { backgroundColor: palette.warning }]} />
              <Text style={[styles.blockBody, { color: palette.text }]}>{item}</Text>
            </View>
          ))
        ) : (
          <Text style={[styles.blockBody, { color: palette.text }]}>
            当前没有明显的交付阻塞，可以继续往公网和分发收口。
          </Text>
        )}
      </SurfaceCard>

      <SectionHeading title="快捷入口" subtitle="把最常用的演示和交付入口固定在一页，不再到处找。" />
      <View style={styles.entryGrid}>
        {quickEntries.map((entry) => (
          <Pressable
            key={entry.key}
            onPress={() => {
              router.push(entry.route as never);
            }}
            style={({ pressed }) => [styles.entryCard, { opacity: pressed ? 0.88 : 1 }]}>
            <SurfaceCard style={styles.entryInner}>
              <Text style={[styles.entryTitle, { color: palette.text }]}>{entry.title}</Text>
              <Text style={[styles.entryCopy, { color: palette.subtext }]}>{entry.copy}</Text>
            </SurfaceCard>
          </Pressable>
        ))}
      </View>

      <SectionHeading title="通知与设备" subtitle="这块是移动端体验能不能站住的关键，不只是一个开关。" />
      <SurfaceCard style={styles.cardGap}>
        <Text style={[styles.blockTitle, { color: palette.text }]}>通知链路</Text>
        <Text style={[styles.blockBody, { color: palette.subtext }]}>
          {isSupported
            ? permissionState === 'granted'
              ? '本地通知已授权，可直接发风控提醒。'
              : permissionState === 'denied'
                ? '通知权限被拒，需要去系统设置放开。'
                : '通知权限还没打开。'
            : '当前平台不支持原生通知。'}
        </Text>
        <Text style={[styles.blockBody, { color: palette.subtext }]}>
          远程推送状态: {remotePushState} / Token: {maskedPushToken}
        </Text>

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
              void sendPreviewNotification();
            }}
            style={[styles.ghostButton, { borderColor: palette.border }]}>
            <Text style={[styles.ghostButtonText, { color: palette.text }]}>发本地测试</Text>
          </Pressable>
        </View>

        <View style={styles.buttonRow}>
          <Pressable
            onPress={() => {
              void registerRemotePush().then(() => {
                void refreshPushDevices();
                void refreshTakeoverPushStatus();
                void refreshIndustryResearchPushStatus();
              });
            }}
            style={[styles.primaryButton, { backgroundColor: palette.tint }]}>
            <Text style={styles.primaryButtonText}>同步远程推送</Text>
          </Pressable>
          <Pressable
            onPress={() => {
              void sendRemotePreviewNotification().then(() => {
                void refreshPushDevices();
                void refreshTakeoverPushStatus();
                void refreshIndustryResearchPushStatus();
              });
            }}
            style={[styles.ghostButton, { borderColor: palette.border }]}>
            <Text style={[styles.ghostButtonText, { color: palette.text }]}>发远程测试</Text>
          </Pressable>
        </View>

        <View style={styles.buttonRow}>
          <Pressable
            onPress={() => {
              void sendRemoteTakeoverPreview().then(() => {
                void refreshTakeoverPushStatus();
                void refreshIndustryResearchPushStatus();
              });
            }}
            style={[styles.ghostButton, { borderColor: palette.border }]}>
            <Text style={[styles.ghostButtonText, { color: palette.text }]}>预演接管判断</Text>
          </Pressable>
          <Pressable
            onPress={() => {
              void sendRemoteTakeoverNotification().then(() => {
                void refreshPushDevices();
                void refreshTakeoverPushStatus();
                void refreshIndustryResearchPushStatus();
              });
            }}
            style={[styles.primaryButton, { backgroundColor: palette.tint }]}>
            <Text style={styles.primaryButtonText}>发接管判断</Text>
          </Pressable>
        </View>

        {takeoverPushStatus && takeoverPushStatus.activeDevices > 0 && !takeoverPushStatus.shouldSend ? (
          <View style={styles.buttonRow}>
            <Pressable
              onPress={() => {
                void sendRemoteTakeoverResend().then(() => {
                  void refreshPushDevices();
                  void refreshTakeoverPushStatus();
                  void refreshIndustryResearchPushStatus();
                });
              }}
              style={[styles.ghostButton, { borderColor: palette.border }]}>
              <Text style={[styles.ghostButtonText, { color: palette.text }]}>强制重发当前判断</Text>
            </Pressable>
          </View>
        ) : null}

        {lastError ? (
          <Text style={[styles.hintText, { color: palette.danger }]}>{lastError}</Text>
        ) : (
          <Text style={[styles.hintText, { color: palette.subtext }]}>
            本地提醒已接通。远程推送已经支持 token 注册和后台测试下发，真机还需要完整 EAS 配置才能拿正式 token。
          </Text>
        )}

        {lastDispatchResult ? (
          <View style={[styles.dispatchBox, { backgroundColor: palette.surfaceMuted, borderColor: palette.border }]}>
            <View style={styles.identityRow}>
              <View style={styles.identityMain}>
                <Text style={[styles.blockTitle, { color: palette.text }]}>
                  {lastDispatchResult.dryRun ? '最近一次是预演结果' : '最近一次下发结果'}
                </Text>
                <Text style={[styles.blockBody, { color: palette.subtext }]}>
                  命中 {lastDispatchResult.targetedDevices} 台 / 成功 {lastDispatchResult.sentDevices} 台 / 失败 {lastDispatchResult.failedDevices} 台
                </Text>
              </View>
              <StatusPill
                label={lastDispatchResult.dryRun ? 'dry-run' : lastDispatchResult.success ? 'ok' : 'partial'}
                tone={lastDispatchResult.dryRun ? 'info' : lastDispatchResult.success ? 'success' : 'warning'}
              />
            </View>
            {lastDispatchResult.tickets.slice(0, 2).map((ticket) => (
              <View key={`${ticket.expoPushToken}-${ticket.status}`} style={styles.rowWithDot}>
                <View style={[styles.dot, { backgroundColor: palette.tint }]} />
                <Text style={[styles.blockBody, { color: palette.text }]}>
                  {ticket.message ?? `${ticket.expoPushToken} / ${ticket.status}`}
                </Text>
              </View>
            ))}
          </View>
        ) : null}
      </SurfaceCard>

      <SurfaceCard style={styles.cardGap}>
        <Text style={[styles.blockTitle, { color: palette.text }]}>接管判断推送状态</Text>
        {takeoverPushStatusError ? (
          <Text style={[styles.hintText, { color: palette.danger }]}>{takeoverPushStatusError}</Text>
        ) : takeoverPushStatus ? (
          <>
            <View style={styles.identityRow}>
              <View style={styles.identityMain}>
                <Text style={[styles.blockBody, { color: palette.text }]}>{takeoverPushStatus.title}</Text>
                <Text style={[styles.blockBody, { color: palette.subtext }]}>{takeoverPushStatus.summary}</Text>
              </View>
              <StatusPill
                label={
                  takeoverPushStatus.deliveryState === 'no_device'
                    ? '无设备'
                    : takeoverPushStatus.deliveryState === 'pending_devices'
                      ? '补发中'
                      : takeoverPushStatus.deliveryState === 'pending_update'
                        ? '待下发'
                        : '已同步'
                }
                tone={
                  takeoverPushStatus.deliveryState === 'no_device'
                    ? 'warning'
                    : takeoverPushStatus.deliveryState === 'pending_devices'
                      ? 'warning'
                      : takeoverPushStatus.shouldSend
                      ? 'info'
                      : 'success'
                }
              />
            </View>
            <Text style={[styles.blockBody, { color: palette.subtext }]}>
              {takeoverPushStatus.recommendedAction}
            </Text>
            <Text style={[styles.blockBody, { color: palette.subtext }]}>
              已覆盖 {takeoverPushStatus.syncedDevices} / {takeoverPushStatus.activeDevices} 台，待更新{' '}
              {takeoverPushStatus.pendingDevices} 台。
            </Text>
            <Text style={[styles.blockBody, { color: palette.subtext }]}>
              自动下发 {takeoverPushStatus.autoEnabled ? '已开启' : '未开启'} /{' '}
              {takeoverPushStatus.autoReady
                ? '当前满足自动下发条件'
                : takeoverPushStatus.autoCooldownSeconds > 0
                  ? `冷却中，剩余 ${takeoverPushStatus.autoCooldownSeconds} 秒`
                  : '当前还不满足自动下发条件'}
            </Text>
            <Text style={[styles.blockBody, { color: palette.subtext }]}>
              自动下发开启后，系统会在远程推送就绪后自动跑后台检查；手动按钮仍然保留给你做强制确认。
            </Text>
            <Text style={[styles.blockBody, { color: palette.subtext }]}>
              上次真发{' '}
              {takeoverPushStatus.lastSentAt ? formatTimestamp(takeoverPushStatus.lastSentAt) : '暂无'} / 上次预演{' '}
              {takeoverPushStatus.lastPreviewAt ? formatTimestamp(takeoverPushStatus.lastPreviewAt) : '暂无'}
            </Text>
            <Text style={[styles.blockBody, { color: palette.subtext }]}>
              上次自动检查{' '}
              {takeoverPushStatus.lastAutoRunAt ? formatTimestamp(takeoverPushStatus.lastAutoRunAt) : '暂无'} / 结果{' '}
              {takeoverPushStatus.lastAutoRunStatus || '暂无'}
            </Text>
            <View style={styles.buttonRow}>
              <Pressable
                onPress={() => {
                  if (!token) {
                    return;
                  }
                  void updateTakeoverPushSettings(!takeoverPushStatus.autoEnabled, token).then(() => {
                    void refreshTakeoverPushStatus();
                    void refreshIndustryResearchPushStatus();
                  });
                }}
                style={[styles.ghostButton, { borderColor: palette.border }]}>
                <Text style={[styles.ghostButtonText, { color: palette.text }]}>
                  {takeoverPushStatus.autoEnabled ? '关闭自动下发' : '开启自动下发'}
                </Text>
              </Pressable>
              <Pressable
                onPress={() => {
                  void runRemoteTakeoverAuto().then(() => {
                    void refreshPushDevices();
                    void refreshTakeoverPushStatus();
                    void refreshIndustryResearchPushStatus();
                  });
                }}
                style={[styles.primaryButton, { backgroundColor: palette.tint }]}>
                <Text style={styles.primaryButtonText}>执行自动检查</Text>
              </Pressable>
            </View>
          </>
        ) : (
          <Text style={[styles.hintText, { color: palette.subtext }]}>正在读取接管判断推送状态。</Text>
        )}
      </SurfaceCard>

      <SurfaceCard style={styles.cardGap}>
        <Text style={[styles.blockTitle, { color: palette.text }]}>方向变化推送状态</Text>
        {industryResearchPushStatusError ? (
          <Text style={[styles.hintText, { color: palette.danger }]}>{industryResearchPushStatusError}</Text>
        ) : industryResearchPushStatus ? (
          <>
            <View style={styles.identityRow}>
              <View style={styles.identityMain}>
                <Text style={[styles.blockBody, { color: palette.text }]}>{industryResearchPushStatus.title}</Text>
                <Text style={[styles.blockBody, { color: palette.subtext }]}>
                  {industryResearchPushStatus.summary}
                </Text>
              </View>
              <StatusPill
                label={
                  industryResearchPushStatus.deliveryState === 'no_device'
                    ? '无设备'
                    : industryResearchPushStatus.deliveryState === 'active'
                      ? '已激活'
                      : '待触发'
                }
                tone={
                  industryResearchPushStatus.deliveryState === 'no_device'
                    ? 'warning'
                    : industryResearchPushStatus.deliveryState === 'active'
                      ? 'success'
                      : 'info'
                }
              />
            </View>
            <Text style={[styles.blockBody, { color: palette.subtext }]}>
              自动下发 {industryResearchPushStatus.autoEnabled ? '跟随接管判断已开启' : '当前未开启'} / 已注册{' '}
              {industryResearchPushStatus.activeDevices} 台设备。
            </Text>
            <Text style={[styles.blockBody, { color: palette.subtext }]}>
              {industryResearchPushStatus.recommendedAction}
            </Text>
            {industryResearchPushStatus.latestDirection ? (
              <Text style={[styles.blockBody, { color: palette.text }]}>
                当前方向：{industryResearchPushStatus.latestDirection}
                {industryResearchPushStatus.latestTimelineStage
                  ? ` / ${industryResearchPushStatus.latestTimelineStage}`
                  : ''}
              </Text>
            ) : null}
            {industryResearchPushStatus.latestCatalystTitle ? (
              <Text style={[styles.blockBody, { color: palette.tint }]}>
                最新催化：{industryResearchPushStatus.latestCatalystTitle}
              </Text>
            ) : null}
            <Text style={[styles.blockBody, { color: palette.subtext }]}>
              上次方向真发{' '}
              {industryResearchPushStatus.lastSentAt
                ? formatTimestamp(industryResearchPushStatus.lastSentAt)
                : '暂无'}{' '}
              / 结果 {industryResearchPushStatus.lastSentStatus || '暂无'}
            </Text>
            {industryResearchPushStatus.latestTitle ? (
              <View
                style={[
                  styles.dispatchBox,
                  { backgroundColor: palette.surfaceMuted, borderColor: palette.border },
                ]}>
                <Text style={[styles.blockTitle, { color: palette.text }]}>最近一次方向变化</Text>
                <Text style={[styles.blockBody, { color: palette.text }]}>
                  {industryResearchPushStatus.latestTitle}
                </Text>
                {industryResearchPushStatus.latestPreview ? (
                  <Text style={[styles.blockBody, { color: palette.subtext }]}>
                    {industryResearchPushStatus.latestPreview}
                  </Text>
                ) : null}
              </View>
            ) : null}
          </>
        ) : (
          <Text style={[styles.hintText, { color: palette.subtext }]}>正在读取方向变化推送状态。</Text>
        )}
      </SurfaceCard>

      <SurfaceCard style={styles.cardGap}>
        <Text style={[styles.blockTitle, { color: palette.text }]}>已注册设备</Text>
        {pushDevicesError ? (
          <Text style={[styles.hintText, { color: palette.danger }]}>{pushDevicesError}</Text>
        ) : pushDevices && pushDevices.length > 0 ? (
          pushDevices.map((device) => (
            <View key={device.expoPushToken} style={styles.deviceRow}>
              <View style={styles.deviceMain}>
                <Text style={[styles.deviceTitle, { color: palette.text }]}>
                  {device.deviceName} / {device.platform.toUpperCase()}
                </Text>
                <Text style={[styles.deviceMeta, { color: palette.subtext }]}>
                  最近同步 {formatTimestamp(device.lastSeenAt)}
                </Text>
                <Text style={[styles.deviceMeta, { color: palette.subtext }]}>
                  版本 {device.appVersion || '--'} / 权限 {device.permissionState}
                </Text>
                <Text style={[styles.deviceMeta, { color: palette.subtext }]}>
                  Token {`${device.expoPushToken.slice(0, 18)}...${device.expoPushToken.slice(-8)}`}
                </Text>
              </View>
              <View style={styles.deviceStatus}>
                <StatusPill
                  label={device.lastPushStatus ? `最近推送 ${device.lastPushStatus}` : '尚未下发'}
                  tone={device.lastPushStatus === 'ok' ? 'success' : 'neutral'}
                />
                {device.lastError ? (
                  <Text style={[styles.deviceError, { color: palette.danger }]}>{device.lastError}</Text>
                ) : null}
              </View>
            </View>
          ))
        ) : (
          <Text style={[styles.hintText, { color: palette.subtext }]}>
            还没有远程推送设备。真机登录后点一次“同步远程推送”，这里就会出现。
          </Text>
        )}
      </SurfaceCard>

      <SectionHeading title="连接与分发" subtitle="这一块决定它是局域网 Demo，还是随时可访问的产品。" />
      <SurfaceCard style={styles.cardGap}>
        <Text style={[styles.blockTitle, { color: palette.text }]}>当前连接</Text>
        <Text style={[styles.blockBody, { color: palette.subtext }]}>
          API Base URL: {apiBaseUrl}
        </Text>
        <Text style={[styles.blockBody, { color: palette.subtext }]}>
          现在支持运行时切换。真机调试时可以直接填电脑局域网地址，后面换成公网域名也不用重新改代码。
        </Text>
        <TextInput
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          onChangeText={setDraftBaseUrl}
          placeholder={defaultApiBaseUrl}
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
        <View style={styles.buttonRow}>
          <Pressable
            onPress={() => {
              void saveApiBaseUrl(draftBaseUrl);
            }}
            style={[styles.primaryButton, { backgroundColor: palette.tint }]}>
            <Text style={styles.primaryButtonText}>保存地址</Text>
          </Pressable>
          <Pressable
            onPress={() => {
              void resetApiBaseUrl();
            }}
            style={[styles.ghostButton, { borderColor: palette.border }]}>
            <Text style={[styles.ghostButtonText, { color: palette.text }]}>恢复默认</Text>
          </Pressable>
        </View>
      </SurfaceCard>

      <SurfaceCard style={styles.cardGap}>
        <Text style={[styles.blockTitle, { color: palette.text }]}>接下来要收的 4 件事</Text>
        {checklist.map((item, index) => (
          <View key={item} style={styles.checkRow}>
            <View style={[styles.indexBadge, { backgroundColor: palette.accentSoft }]}>
              <Text style={[styles.indexText, { color: palette.tint }]}>{index + 1}</Text>
            </View>
            <Text style={[styles.checkText, { color: palette.text }]}>{item}</Text>
          </View>
        ))}
      </SurfaceCard>

      <SurfaceCard style={styles.cardGap}>
        <Text style={[styles.blockTitle, { color: palette.text }]}>当前账号</Text>
        <Text style={[styles.blockBody, { color: palette.subtext }]}>
          {user?.displayName ?? '未登录'} / {user?.username ?? '--'}
        </Text>
        <Text style={[styles.blockBody, { color: palette.subtext }]}>
          退出后当前设备的登录态会被清掉，但不会影响后台数据。
        </Text>
        <Pressable
          onPress={() => {
            void signOut();
          }}
          style={[styles.primaryButton, { backgroundColor: palette.tint }]}>
          <Text style={styles.primaryButtonText}>退出登录</Text>
        </Pressable>
      </SurfaceCard>
    </AppScreen>
  );
}

const styles = StyleSheet.create({
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
  cardGap: {
    gap: 14,
  },
  identityRow: {
    gap: 12,
  },
  identityMain: {
    gap: 4,
  },
  rowWithDot: {
    flexDirection: 'row',
    gap: 10,
    alignItems: 'flex-start',
  },
  dot: {
    width: 10,
    height: 10,
    borderRadius: 999,
    marginTop: 6,
  },
  entryGrid: {
    gap: 12,
  },
  entryCard: {
    width: '100%',
  },
  entryInner: {
    gap: 6,
  },
  entryTitle: {
    fontSize: 16,
    fontWeight: '800',
  },
  entryCopy: {
    fontSize: 14,
    lineHeight: 21,
  },
  blockTitle: {
    fontSize: 18,
    fontWeight: '700',
  },
  blockBody: {
    fontSize: 14,
    lineHeight: 22,
  },
  input: {
    borderWidth: 1,
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
  },
  buttonRow: {
    flexDirection: 'row',
    gap: 10,
  },
  primaryButton: {
    flex: 1,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 14,
  },
  primaryButtonText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '800',
  },
  ghostButton: {
    flex: 1,
    borderRadius: 16,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 14,
  },
  buttonSpacer: {
    flex: 1,
  },
  ghostButtonText: {
    fontSize: 14,
    fontWeight: '700',
  },
  hintText: {
    fontSize: 13,
    lineHeight: 20,
  },
  dispatchBox: {
    marginTop: 12,
    borderWidth: 1,
    borderRadius: 18,
    padding: 14,
    gap: 10,
  },
  deviceRow: {
    gap: 10,
    paddingVertical: 10,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: 'rgba(84, 99, 116, 0.22)',
  },
  deviceMain: {
    gap: 4,
  },
  deviceTitle: {
    fontSize: 15,
    fontWeight: '700',
  },
  deviceMeta: {
    fontSize: 13,
    lineHeight: 18,
  },
  deviceStatus: {
    gap: 8,
    alignItems: 'flex-start',
  },
  deviceError: {
    fontSize: 12,
    lineHeight: 18,
  },
  checkRow: {
    flexDirection: 'row',
    gap: 12,
    alignItems: 'center',
    paddingVertical: 10,
  },
  indexBadge: {
    width: 30,
    height: 30,
    borderRadius: 999,
    alignItems: 'center',
    justifyContent: 'center',
  },
  indexText: {
    fontSize: 14,
    fontWeight: '800',
  },
  checkText: {
    flex: 1,
    fontSize: 15,
    lineHeight: 22,
  },
});
