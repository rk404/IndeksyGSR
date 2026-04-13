import { useQuery, useMutation } from '@tanstack/react-query';
import api from './client';
import type { SegmentTree, SegmentProposal, ProposalItem } from '../types';

export function useSegments() {
  return useQuery({
    queryKey: ['segments'],
    queryFn: async () => {
      const { data } = await api.get<SegmentTree>('/segments');
      return data;
    },
    staleTime: Infinity,
  });
}

export function useSuggest() {
  return useMutation({
    mutationFn: async (params: { query: string; top_n?: number }) => {
      const { data } = await api.post<SegmentProposal[]>('/suggest', params);
      return data;
    },
  });
}

export function usePropose() {
  return useMutation({
    mutationFn: async (params: {
      query: string;
      seg1: string; seg2: string; seg3: string;
      seg4: string; seg5: string; seg6: string;
      kod1: string; kod2: string; kod3: string;
      nazwa: string; indeks: string;
    }) => {
      const { data } = await api.post<{ id: string }>('/propose', params);
      return data;
    },
  });
}

export function useProposals(status?: string) {
  return useQuery({
    queryKey: ['proposals', status],
    queryFn: async () => {
      const params = status ? { status } : {};
      const { data } = await api.get<ProposalItem[]>('/proposals', { params });
      return data;
    },
  });
}

export function useApproveProposal() {
  return useMutation({
    mutationFn: async (docId: string) => {
      const { data } = await api.post(`/proposals/${docId}/approve`);
      return data;
    },
  });
}

export function useRejectProposal() {
  return useMutation({
    mutationFn: async (docId: string) => {
      const { data } = await api.post(`/proposals/${docId}/reject`);
      return data;
    },
  });
}
