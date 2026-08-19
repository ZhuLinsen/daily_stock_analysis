import apiClient from './index';
import { toCamelCase } from './utils';
import type { ResearchJob, ResearchJobCreateRequest } from '../types/research';

export const researchApi = {
  create: async (payload: ResearchJobCreateRequest): Promise<ResearchJob> => {
    const { data } = await apiClient.post('/research/jobs', {
      subject: payload.subject,
      market: payload.market || '',
      as_of: payload.asOf || '',
    });
    return toCamelCase(data) as ResearchJob;
  },
  get: async (jobId: string): Promise<ResearchJob> => {
    const { data } = await apiClient.get(`/research/jobs/${jobId}`);
    return toCamelCase(data) as ResearchJob;
  },
  cancel: async (jobId: string): Promise<ResearchJob> => {
    const { data } = await apiClient.post(`/research/jobs/${jobId}/cancel`);
    return toCamelCase(data) as ResearchJob;
  },
};
