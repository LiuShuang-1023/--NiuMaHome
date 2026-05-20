/**
 * 收藏夹 Hook (v0.5)
 * 数据存 localStorage，跨会话持久，不依赖后端 session
 */
'use client';

import { useCallback, useEffect, useState } from 'react';
import type { Recommendation } from '@/lib/types';

const STORAGE_KEY = 'niumahome_favorites_v1';
const MAX_FAVORITES = 20;

export interface FavoriteItem {
  rec: Recommendation;
  savedAt: string; // ISO
  note?: string;   // 用户备注（可选）
}

function loadFromStorage(): FavoriteItem[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as FavoriteItem[];
  } catch {
    return [];
  }
}

function saveToStorage(items: FavoriteItem[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
  } catch {/* quota exceeded, ignore */}
}

export function useFavorites() {
  const [favorites, setFavorites] = useState<FavoriteItem[]>([]);

  // 初始化（客户端）
  useEffect(() => {
    setFavorites(loadFromStorage());
  }, []);

  const isFavorited = useCallback(
    (listingId: string) => favorites.some((f) => f.rec.listing.id === listingId),
    [favorites],
  );

  const toggle = useCallback(
    (rec: Recommendation) => {
      setFavorites((prev) => {
        const exists = prev.some((f) => f.rec.listing.id === rec.listing.id);
        let next: FavoriteItem[];
        if (exists) {
          next = prev.filter((f) => f.rec.listing.id !== rec.listing.id);
        } else {
          if (prev.length >= MAX_FAVORITES) {
            // 超上限：移除最旧的一条
            next = [...prev.slice(1), { rec, savedAt: new Date().toISOString() }];
          } else {
            next = [...prev, { rec, savedAt: new Date().toISOString() }];
          }
        }
        saveToStorage(next);
        return next;
      });
    },
    [],
  );

  const updateNote = useCallback((listingId: string, note: string) => {
    setFavorites((prev) => {
      const next = prev.map((f) =>
        f.rec.listing.id === listingId ? { ...f, note } : f,
      );
      saveToStorage(next);
      return next;
    });
  }, []);

  const remove = useCallback((listingId: string) => {
    setFavorites((prev) => {
      const next = prev.filter((f) => f.rec.listing.id !== listingId);
      saveToStorage(next);
      return next;
    });
  }, []);

  const clear = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setFavorites([]);
  }, []);

  return {
    favorites,
    isFavorited,
    toggle,
    updateNote,
    remove,
    clear,
    count: favorites.length,
  };
}
