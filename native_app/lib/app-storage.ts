import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';

const memoryStorage = new Map<string, string>();

function getWebStorage() {
  if (typeof window === 'undefined') {
    return null;
  }

  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export async function getStoredValue(key: string) {
  if (Platform.OS === 'web') {
    const storage = getWebStorage();
    if (storage) {
      return storage.getItem(key);
    }

    return memoryStorage.get(key) ?? null;
  }

  try {
    return await SecureStore.getItemAsync(key);
  } catch (error) {
    console.error('alphaai.storage_get_failed', key, error);
    return memoryStorage.get(key) ?? null;
  }
}

export async function setStoredValue(key: string, value: string) {
  if (Platform.OS === 'web') {
    const storage = getWebStorage();
    if (storage) {
      storage.setItem(key, value);
      return;
    }

    memoryStorage.set(key, value);
    return;
  }

  try {
    await SecureStore.setItemAsync(key, value);
  } catch (error) {
    console.error('alphaai.storage_set_failed', key, error);
    memoryStorage.set(key, value);
  }
}

export async function deleteStoredValue(key: string) {
  if (Platform.OS === 'web') {
    const storage = getWebStorage();
    if (storage) {
      storage.removeItem(key);
      return;
    }

    memoryStorage.delete(key);
    return;
  }

  try {
    await SecureStore.deleteItemAsync(key);
  } catch (error) {
    console.error('alphaai.storage_delete_failed', key, error);
  } finally {
    memoryStorage.delete(key);
  }
}
