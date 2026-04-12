import { useMutation } from '@tanstack/react-query';
import api from './client';
import type { SearchResponse, SearchUrlResponse, GenerateDescriptionResponse, BulkSearchResponse } from '../types';

export function useSearch() {
  return useMutation({
    mutationFn: async (params: { query: string; top_k: number; rerank: boolean }) => {
      const { data } = await api.post<SearchResponse>('/search', params);
      return data;
    },
  });
}

export function useSearchByUrl() {
  return useMutation({
    mutationFn: async (params: { url: string; top_k: number; rerank: boolean }) => {
      const { data } = await api.post<SearchUrlResponse>('/search-url', params);
      return data;
    },
  });
}

export function useSaveSelection() {
  return useMutation({
    mutationFn: async (params: {
      query: string;
      source: string;
      results: { qdrant_id: number | string | null; indeks: string; nazwa: string; jdmr_nazwa: string; score: number }[];
      groq_description: string;
    }) => {
      const { data } = await api.post('/search/save', params);
      return data;
    },
  });
}

export function useGenerateDescription() {
  return useMutation({
    mutationFn: async (params: { nazwa: string; indeks: string; query: string; model?: string }) => {
      const { data } = await api.post<GenerateDescriptionResponse>('/generate-description', params);
      return data;
    },
  });
}

export function useBulkSearch() {
  return useMutation({
    mutationFn: async (params: { file: File; rerank: boolean }) => {
      const formData = new FormData();
      formData.append('file', params.file);
      const { data } = await api.post<BulkSearchResponse>('/search/bulk', formData, {
        params: { rerank: params.rerank },
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      return data;
    },
  });
}

export function useBulkDownload() {
  return useMutation({
    mutationFn: async (params: { file: File; rerank: boolean }) => {
      const formData = new FormData();
      formData.append('file', params.file);
      const { data } = await api.post('/search/bulk/download', formData, {
        params: { rerank: params.rerank },
        headers: { 'Content-Type': 'multipart/form-data' },
        responseType: 'blob',
      });
      return data as Blob;
    },
  });
}
