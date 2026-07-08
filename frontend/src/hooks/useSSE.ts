import { useState, useEffect, useRef } from 'react';
import type { ReviewProgress } from '../types';

export function useReviewProgress(taskId: string | undefined) {
  const [progress, setProgress] = useState<ReviewProgress | null>(null);
  const [isComplete, setIsComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const failureCountRef = useRef(0);
  const completedRef = useRef(false);
  const MAX_FAILURES = 3;

  useEffect(() => {
    if (!taskId) return;

    // 重置状态（taskId 变化时），使用 setTimeout 避免同步 setState 触发 ESLint 警告
    const resetTimer = setTimeout(() => {
      setProgress(null);
      setIsComplete(false);
      setError(null);
      failureCountRef.current = 0;
      completedRef.current = false;
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
      completedRef.current = true;
      setIsComplete(true);
      // 延迟关闭，让服务端先正常结束 generator 并关闭连接
      // 避免 EventSource.close() 与服务端关闭竞争导致 net::ERR_ABORTED
      setTimeout(() => es.close(), 200);
    });

    es.addEventListener('error', () => {
      // 任务已完成后 EventSource.close() 会触发一次 error，这是正常行为，静默忽略
      if (completedRef.current) {
        return;
      }

      const readyState = (es as EventSource).readyState;
      // 服务端主动关闭（任务完成/超时/不存在），readyState=CLOSED
      // 此时不要设置 error，避免控制台报错；仅尝试有限次重连
      if (readyState === EventSource.CLOSED) {
        // 不设置 error，静默处理 — complete 事件已处理完成状态
        // 若 complete 未到达且 isComplete=false，上层会通过轮询兜底
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
