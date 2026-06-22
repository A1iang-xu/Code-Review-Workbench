import { useState, useEffect, useCallback } from 'react';
import type { ReviewProgress } from '../types';

export function useReviewProgress(taskId: string | undefined) {
  const [progress, setProgress] = useState<ReviewProgress | null>(null);
  const [isComplete, setIsComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const connect = useCallback(() => {
    if (!taskId) return;

    const es = new EventSource(`/api/v1/reviews/${taskId}/stream`);

    es.addEventListener('progress', (e) => {
      try {
        const data = JSON.parse(e.data);
        setProgress((prev) => ({
          ...prev,
          task_id: data.task_id,
          status: data.status,
          current_stage: data.stage,
          progress: data.progress,
          completed_agents: data.completed_agents || prev?.completed_agents || [],
        }));
      } catch { /* ignore parse errors */ }
    });

    es.addEventListener('complete', (e) => {
      try {
        const data = JSON.parse(e.data);
        setProgress((prev) => ({
          ...prev,
          task_id: data.task_id,
          status: 'completed',
          current_stage: 'done',
          progress: 1.0,
          completed_agents: prev?.completed_agents || [],
        }));
      } catch { /* ignore */ }
      setIsComplete(true);
      es.close();
    });

    es.addEventListener('error', (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data);
        setError(data.error || 'Connection error');
      } catch {
        setError('SSE connection error');
      }
      es.close();
    });

    es.onerror = () => {
      // EventSource auto-reconnects; only set error if not complete
    };

    return () => {
      es.close();
    };
  }, [taskId]);

  useEffect(() => {
    const cleanup = connect();
    return cleanup;
  }, [connect]);

  return { progress, isComplete, error };
}
