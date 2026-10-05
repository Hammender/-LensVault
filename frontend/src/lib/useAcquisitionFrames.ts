import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import { captureAcquisitionFrame, locateAcquisitionFrame } from "../api/acquisition";
import { authFetch, parseResponse } from "./apiClient";
import type { AcquisitionAsset, AcquisitionCaptureResult, AcquisitionFrame } from "../types";

type DecodedFrame = { frame: AcquisitionFrame; url: string };

export function useAcquisitionFrames(
  asset: AcquisitionAsset,
  videoRef: RefObject<HTMLVideoElement>,
  onCaptured?: (result: AcquisitionCaptureResult) => void
) {
  const [decoded, setDecoded] = useState<DecodedFrame | null>(null);
  const [locating, setLocating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [capture, setCapture] = useState<AcquisitionCaptureResult | null>(null);
  const generation = useRef(0);
  const decodedRef = useRef<DecodedFrame | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const savingRef = useRef(false);
  const shownTime = useRef<number | null>(null);

  const clearFrame = useCallback(() => {
    generation.current += 1;
    abortRef.current?.abort();
    if (decodedRef.current) URL.revokeObjectURL(decodedRef.current.url);
    decodedRef.current = null;
    setDecoded(null);
    setLocating(false);
  }, []);

  useEffect(() => {
    clearFrame();
    setSaving(false);
    savingRef.current = false;
    setError(null);
    setCapture(null);
    shownTime.current = null;
    const video = videoRef.current;
    const resetShownTime = () => { shownTime.current = null; };
    video?.addEventListener("seeking", resetShownTime);
    let callbackId: number | undefined;
    let disposed = false;
    const watchFrame = (_now: number, metadata: VideoFrameCallbackMetadata) => {
      shownTime.current = metadata.mediaTime;
      if (!disposed && video?.requestVideoFrameCallback) callbackId = video.requestVideoFrameCallback(watchFrame);
    };
    if (video?.requestVideoFrameCallback) callbackId = video.requestVideoFrameCallback(watchFrame);
    return () => {
      disposed = true;
      video?.removeEventListener("seeking", resetShownTime);
      if (callbackId !== undefined) video?.cancelVideoFrameCallback(callbackId);
      generation.current += 1;
      abortRef.current?.abort();
      if (decodedRef.current) URL.revokeObjectURL(decodedRef.current.url);
      decodedRef.current = null;
    };
  }, [asset.id, asset.sha256, clearFrame, videoRef]);

  const prepareFrame = useCallback(async (direction: -1 | 0 | 1 = 0, targetTime?: number) => {
    const video = videoRef.current;
    if (!video || video.readyState < 2 || video.seeking || savingRef.current) return;
    video.pause();
    const previous = decodedRef.current?.frame;
    const requestGeneration = ++generation.current;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLocating(true);
    setError(null);
    let url: string | null = null;
    try {
      const frame = await locateAcquisitionFrame(asset.id, {
        source_sha256: asset.sha256,
        time_seconds: targetTime ?? shownTime.current ?? video.currentTime,
        frame_index: targetTime === undefined ? previous?.frame_index : undefined,
        direction
      }, controller.signal);
      const response = await authFetch(frame.image_url, { signal: controller.signal });
      if (!response.ok) await parseResponse(response);
      url = URL.createObjectURL(await response.blob());
      const image = new Image();
      image.src = url;
      await image.decode();
      if (generation.current !== requestGeneration) return;
      if (decodedRef.current) URL.revokeObjectURL(decodedRef.current.url);
      decodedRef.current = { frame, url };
      setDecoded(decodedRef.current);
      url = null;
    } catch (cause) {
      if (generation.current === requestGeneration && !controller.signal.aborted) {
        setError(cause instanceof Error ? cause.message : "选帧失败，请重试");
      }
    } finally {
      if (url) URL.revokeObjectURL(url);
      if (generation.current === requestGeneration) setLocating(false);
    }
  }, [asset.id, asset.sha256, videoRef]);

  const saveFrame = useCallback(async () => {
    const video = videoRef.current;
    if (!video || video.readyState < 2 || video.seeking || savingRef.current || locating) return;
    video.pause();
    savingRef.current = true;
    setSaving(true);
    setError(null);
    const requestGeneration = generation.current;
    try {
      const result = await captureAcquisitionFrame(asset.id, {
        source_sha256: asset.sha256,
        frame_index: decodedRef.current?.frame.frame_index,
        time_seconds: shownTime.current ?? video.currentTime
      });
      // 列表统计需要收到成功结果，即使用户已经关闭或切换了视频。
      onCaptured?.(result);
      if (generation.current === requestGeneration) setCapture(result);
    } catch (cause) {
      if (generation.current === requestGeneration) setError(cause instanceof Error ? cause.message : "截图保存失败，请重试");
    } finally {
      if (generation.current === requestGeneration) {
        savingRef.current = false;
        setSaving(false);
      }
    }
  }, [asset.id, asset.sha256, locating, onCaptured, videoRef]);

  return { decoded, locating, saving, error, capture, clearFrame, prepareFrame, saveFrame };
}
