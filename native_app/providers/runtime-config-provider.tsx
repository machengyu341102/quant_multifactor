import { PropsWithChildren, createContext, useContext, useEffect, useState } from 'react';

import { deleteStoredValue, getStoredValue, setStoredValue } from '@/lib/app-storage';
import { DEFAULT_API_BASE_URL, setApiBaseUrl } from '@/lib/config';

const API_BASE_URL_KEY = 'alpha-ai-native.api-base-url';

interface RuntimeConfigContextValue {
  apiBaseUrl: string;
  defaultApiBaseUrl: string;
  isBooting: boolean;
  saveApiBaseUrl: (value: string) => Promise<void>;
  resetApiBaseUrl: () => Promise<void>;
}

const RuntimeConfigContext = createContext<RuntimeConfigContextValue | null>(null);

export function RuntimeConfigProvider({ children }: PropsWithChildren) {
  const [apiBaseUrl, setApiBaseUrlState] = useState(DEFAULT_API_BASE_URL);
  const [isBooting, setIsBooting] = useState(true);

  useEffect(() => {
    let active = true;

    async function bootstrap() {
      try {
        const storedUrl = await getStoredValue(API_BASE_URL_KEY);
        const nextUrl = setApiBaseUrl(storedUrl);
        if (active) {
          setApiBaseUrlState(nextUrl);
        }
      } finally {
        if (active) {
          setIsBooting(false);
        }
      }
    }

    void bootstrap();

    return () => {
      active = false;
    };
  }, []);

  async function saveApiBaseUrl(value: string) {
    const trimmed = value.trim();
    const nextUrl = setApiBaseUrl(trimmed);

    if (!trimmed || nextUrl === DEFAULT_API_BASE_URL) {
      await deleteStoredValue(API_BASE_URL_KEY);
    } else {
      await setStoredValue(API_BASE_URL_KEY, nextUrl);
    }

    setApiBaseUrlState(nextUrl);
  }

  async function resetApiBaseUrl() {
    await deleteStoredValue(API_BASE_URL_KEY);
    setApiBaseUrlState(setApiBaseUrl(DEFAULT_API_BASE_URL));
  }

  if (isBooting) {
    return null;
  }

  return (
    <RuntimeConfigContext.Provider
      value={{
        apiBaseUrl,
        defaultApiBaseUrl: DEFAULT_API_BASE_URL,
        isBooting,
        saveApiBaseUrl,
        resetApiBaseUrl,
      }}>
      {children}
    </RuntimeConfigContext.Provider>
  );
}

export function useRuntimeConfig() {
  const context = useContext(RuntimeConfigContext);

  if (!context) {
    throw new Error('useRuntimeConfig must be used within RuntimeConfigProvider');
  }

  return context;
}
