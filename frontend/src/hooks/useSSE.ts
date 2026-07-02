import { useState, useEffect, useCallback, useRef } from 'react';
import type { ReviewProgress } from '../types';

export function useReviewProgress(taskId: string | undefined) {
  const [progress, setProgress] = useState<ReviewProgress | null>(null);
  const [isComplete, setIsComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 连续失败计数：仅当多次重连仍失败才向用户报错
  const failureCountRef = useRef(0);
  const MAX_FAILURES = 3;

  const connect = useCallback(() => {
    if (!taskId) return () => {};

    // 关键修复：taskId 变化时必须重置上一次进度，否则切换审查会短暂显示旧进度
    setProgress(null);
    setIsComplete(false);
    setError(null);
    failureCountRef.current = 0;

    const es = new EventSource(`/api/v1/reviews/${taskId}/stream`);

    es.addEventListener('open', () => {
      // 连接成功：重置失败计数，清除临时错误
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
        // 协议解析失败：记录警告便于联调，不再静默吞掉
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
      // 关键修复：EventSource 在断连时会自动重连，期间会触发 error 事件。
      // 仅当连接已彻底关闭（readyState === CLOSED）或连续失败超过阈值时才报错，
      // 避免把"自动重连"误报为错误，造成用户困扰。
      const readyState = (es as EventSource).readyState;
      if (readyState === EventSource.CLOSED) {
        setError('审查进度连接已关闭');
        return;
      }

      failureCountRef.current += 1;
      if (failureCountRef.current >= MAX_FAILURES) {
        setError(`连续 ${MAX_FAILURES} 次连接失败，请检查网络或刷新页面`);
      }
      // 否则保持静默，等待 EventSource 自动重连
    });

    // 统一返回 cleanup，类型安全（始终返回函数，避免 undefined）
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
