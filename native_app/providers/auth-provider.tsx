import { PropsWithChildren, createContext, useContext, useEffect, useState } from 'react';

import { getMe, login } from '@/lib/api';
import { deleteStoredValue, getStoredValue, setStoredValue } from '@/lib/app-storage';
import type { AppUser } from '@/types/trading';

const AUTH_TOKEN_KEY = 'alpha-ai-native.token';

interface AuthContextValue {
  token: string | null;
  user: AppUser | null;
  isBooting: boolean;
  isSigningIn: boolean;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<AppUser | null>(null);
  const [isBooting, setIsBooting] = useState(true);
  const [isSigningIn, setIsSigningIn] = useState(false);

  useEffect(() => {
    let active = true;

    async function bootstrap() {
      try {
        const storedToken = await getStoredValue(AUTH_TOKEN_KEY);

        if (!storedToken) {
          return;
        }

        const profile = await getMe(storedToken);
        if (!active) {
          return;
        }

        setToken(storedToken);
        setUser(profile);
      } catch {
        await deleteStoredValue(AUTH_TOKEN_KEY);
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

  async function signIn(username: string, password: string) {
    setIsSigningIn(true);
    try {
      const session = await login(username, password);
      await setStoredValue(AUTH_TOKEN_KEY, session.accessToken);
      setToken(session.accessToken);
      setUser(session.user);
    } finally {
      setIsSigningIn(false);
      setIsBooting(false);
    }
  }

  async function signOut() {
    await deleteStoredValue(AUTH_TOKEN_KEY);
    setToken(null);
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ token, user, isBooting, isSigningIn, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);

  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }

  return context;
}
