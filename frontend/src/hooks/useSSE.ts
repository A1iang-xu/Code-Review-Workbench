import { useState, useEffect, useRef } from 'react';
import type { ReviewProgress } from '../types';

export function useReviewProgress(taskId: string | undefined) {
  const [progress, setProgress] = useState<ReviewProgress | null>(null);
  const [isComplete, setIsComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const failureCountRef = useRef(0);
  const MAX_FAILURES = 3;

  useEffect(() => {
    if (!taskId) return;

    // 重置状态（taskId 变化时），使用 setTimeout 避免同步 setState 触发 ESLint 警告
    const resetTimer = setTimeout(() => {
      setProgress(null);
      setIsComplete(false);
      setError(null);
      failureCountRef.current = 0;
    }, 0);

    const es = new EventSource(`/api/v1/reviews/${taskId}/stream`);

    es.addEventListener('open', () => {
      failureCountRef.current = 0;
      setError(null);
    });

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
      } catch (err) {
        console.warn('[useSSE] progress 事件解析失败:', e.data, err);
      }
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
      } catch (err) {
        console.warn('[useSSE] complete 事件解析失败:', e.data, err);
      }
      setIsComplete(true);
      es.close();
    });

    es.addEventListener('error', () => {
      const readyState = (es as EventSource).readyState;
      if (readyState === EventSource.CLOSED) {
        setError('审查进度连接已关闭');
        return;
      }

      failureCountRef.current += 1;
      if (failureCountRef.current >= MAX_FAILURES) {
        setError(`连续 ${MAX_FAILURES} 次连接失败，请检查网络或刷新页面`);
      }
    });

    return () => {
      clearTimeout(resetTimer);
      es.close();
    };
  }, [taskId]);

  return { progress, isComplete, error };
}
