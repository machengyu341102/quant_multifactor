# Alpha AI Native App

这是 `quant_multifactor` 项目里的真原生移动端骨架，不再沿用旧的 PWA 手机网页壳。

## 当前已落地

- `Expo + React Native + Expo Router` 原生工程
- 五个主标签页:
  - `首页`
  - `信号`
  - `持仓`
  - `决策台`
  - `我的`
- 已接入现有后端接口:
  - `/api/system`
  - `/api/strategies`
  - `/api/signals`
  - `/api/positions`
  - `/api/learning`
- 已接入登录与 Bearer Token 鉴权
- 已接入运行时 API 地址切换
- 已接入信号详情、持仓详情和 K 线接口
- 已接入本地通知权限和风控提醒中心
- 已接入运维诊断页、健康检查和 metrics 接口

## 目录

```text
native_app/
├── app/                      # Expo Router 页面
├── components/app/           # 交易 App 基础 UI 组件
├── hooks/                    # 数据加载钩子
├── lib/                      # API / 格式化 / 配置
├── types/                    # 交易数据类型
└── app.json                  # Expo 配置
```

## 启动

### 1. 安装依赖

```bash
cd /Users/zchtech002/machengyu/quant_multifactor/native_app
npm install
```

### 2. 配置默认后端地址

```bash
cp .env.example .env
```

默认值:

```bash
EXPO_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

如果你是用手机真机调试，不要写 `127.0.0.1`，要改成电脑的局域网 IP，比如:

```bash
EXPO_PUBLIC_API_BASE_URL=http://192.168.1.190:8000
```

### 2.1 登录账号

- 决策账号: `admin`
- 实验账号: `pilot`
- 对应密码读取后端 `.env` 的 `APP_AUTH_PASSWORD` / `APP_PILOT_PASSWORD`
- 如果服务端未配置，会回退到默认值 `Alpha123456` / `Pilot123456`
- 登录页已经做了“一键体验”按钮，可以直接填入默认账号

### 2.2 运行时切换地址

- 进入 App 的“我的”页面
- 在“当前连接”卡片里直接输入新的 API Base URL
- 点“保存地址”后，后续请求会直接切到新地址
- 点“恢复默认”会回退到 `.env` / Expo 配置里的默认值

### 2.3 推送与提醒

- 当前已接入 `expo-notifications`
- 资料页可以直接申请通知权限，并发送一条测试提醒
- 首页会展示统一口径的风险提醒，关键提醒会触发本地通知
- 资料页现在可以同步远程 push token，并从后台发送一条测试远程推送
- 真机要拿到正式 Expo Push Token，还需要配置 `EXPO_PUBLIC_EAS_PROJECT_ID`

### 2.4 运维入口

- App 内入口: “我的” -> “运维诊断”
- 后端活性: `http://127.0.0.1:8000/health/live`
- 后端就绪: `http://127.0.0.1:8000/health/ready`
- Prometheus metrics: `http://127.0.0.1:8000/metrics`
- 运维摘要: `http://127.0.0.1:8000/api/ops/summary`

### 3. 启动开发环境

```bash
npm run ios
```

或:

```bash
npm run android
```

或:

```bash
npx expo start --web
```

### 3.1 直接体验

- Web 预览: `http://localhost:8081`
- 如果当前后端已运行，本机 API 默认是 `http://127.0.0.1:8000`
- 想最快体验，登录页直接点 `决策账号` 或 `实验账号`

### 4. 打安装包

项目已经补了 [eas.json](/Users/zchtech002/machengyu/quant_multifactor/native_app/eas.json) 和打包标识，离真正安装包只差签名与 EAS 项目配置。

公网正式包建议额外准备:

```bash
cp .env.production.example .env.production
```

然后把:

```bash
EXPO_PUBLIC_API_BASE_URL=https://api.example.com
```

改成真实公网 API 域名，再进行正式构建。

Android 预览包:

```bash
npx eas build --platform android --profile preview
```

本地 Android release 包:

```bash
cd /Users/zchtech002/machengyu/quant_multifactor/native_app/android
./gradlew assembleRelease
```

如果要自动把 APK 输出到共享目录并准备下载链接，可使用自带脚本：

```bash
cd /Users/zchtech002/machengyu/quant_multifactor/native_app
./scripts/build_release_apk.sh /Users/zchtech002/machengyu/public_release
python3 -m http.server --directory /Users/zchtech002/machengyu/public_release 8090
```

脚本会把 `app-release.apk` 复制为 `alpha-ai-native.apk`，算出 MD5，并提示下一步 HTTP 访问地址。

如果网络慢，`gradle.properties` 已经补了 Maven 下载超时参数。
当前默认只打 `arm64-v8a`，优先给真机内测提速；如果要恢复多 ABI，可改 [android/gradle.properties](/Users/zchtech002/machengyu/quant_multifactor/native_app/android/gradle.properties) 里的 `reactNativeArchitectures`。

如果报 `SDK location not found`，先检查本机 Android SDK 配置。处理方法:

```bash
cp android/local.properties.example android/local.properties
```

然后把 `android/local.properties` 里的 `sdk.dir` 改成真实 SDK 路径。
当前这台机器已经补齐到可本地打 Android release：

- 已安装 `Android SDK`
- 已安装 `platform-tools`
- 已安装 `cmdline-tools`
- 已安装 `build-tools 35.0.0 / 36.0.0`
- 已安装 `platforms;android-36`
- 已安装 `NDK 27.1.12297006`

所以本地 APK 构建现在卡的是环境，不是代码。

iOS 内测包:

```bash
npx eas build --platform ios --profile preview
```

正式包:

```bash
npx eas build --platform all --profile production
```

当前 bundle/package 标识:

- iOS: `com.zchtech.alphaai`
- Android: `com.zchtech.alphaai`

## 当前产品定位

这不是券商终端，也不是自动下单客户端。当前定位是:

- AI 交易助手
- 信号与持仓中心
- 学习状态与策略表现面板
- 后续承接 AI 决策解释、推送、登录和图表

## 下一阶段

建议按下面顺序继续:

1. 跑出 Android 预览安装包
2. 接入外部告警和进程守护
3. 做 TestFlight / Android 内测包

## 验证

当前这版已经完成:

- `npm run lint`
- `npx tsc --noEmit`
- `npx expo start --web` 编译启动
