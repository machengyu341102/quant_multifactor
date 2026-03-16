import { Platform } from 'react-native';
import Constants from 'expo-constants';

const fallbackBaseUrl =
  Platform.OS === 'android' ? 'http://10.0.2.2:8000' : 'http://127.0.0.1:8000';

const extra = Constants.expoConfig?.extra as
  | {
      apiBaseUrl?: string;
      easProjectId?: string;
      eas?: { projectId?: string };
    }
  | undefined;

export const DEFAULT_API_BASE_URL =
  process.env.EXPO_PUBLIC_API_BASE_URL ?? extra?.apiBaseUrl ?? fallbackBaseUrl;
export const EXPO_PROJECT_ID =
  process.env.EXPO_PUBLIC_EAS_PROJECT_ID ??
  Constants.easConfig?.projectId ??
  extra?.easProjectId ??
  extra?.eas?.projectId ??
  null;

// Nginx Basic Auth credentials (gateway layer)
// Hardcoded fallback: base64('admin:SyHG!F1eK4*Y!5Re')
export const GATEWAY_BASIC_AUTH =
  process.env.EXPO_PUBLIC_GATEWAY_BASIC_AUTH || 'YWRtaW46U3lIRyFGMWVLNCpZITVSZQ==';

let runtimeApiBaseUrl = DEFAULT_API_BASE_URL;

function normalizeApiBaseUrl(value: string) {
  return value.trim().replace(/\/+$/, '');
}

export function getApiBaseUrl() {
  return runtimeApiBaseUrl;
}

export function setApiBaseUrl(value: string | null | undefined) {
  runtimeApiBaseUrl = value ? normalizeApiBaseUrl(value) : DEFAULT_API_BASE_URL;
  return runtimeApiBaseUrl;
}
