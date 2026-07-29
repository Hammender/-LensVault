import { useMemo, useState } from "react";

import type { SubtitleJob, SubtitleServiceLogs, SubtitleServiceStatus } from "../types";

export function useSubtitleController() {
  const [subtitleServiceStatus, setSubtitleServiceStatus] = useState<SubtitleServiceStatus | null>(null);
  const [subtitleServiceLogs, setSubtitleServiceLogs] = useState<SubtitleServiceLogs | null>(null);
  const [subtitleJobs, setSubtitleJobs] = useState<SubtitleJob[]>([]);
  const [subtitleJobsLoaded, setSubtitleJobsLoaded] = useState(false);
  const [subtitleServiceBusy, setSubtitleServiceBusy] = useState(false);
  const [subtitleServiceNotice, setSubtitleServiceNotice] = useState<string | null>(null);
  const [subtitleLogsOpen, setSubtitleLogsOpen] = useState(false);

  const activeSubtitleJobs = useMemo(
    () => subtitleJobs.filter((job) => ["pending", "running"].includes(job.track.status)),
    [subtitleJobs]
  );
  const visibleSubtitleJobs = useMemo(() => subtitleJobs.slice(0, 8), [subtitleJobs]);

  return {
    subtitleServiceStatus, setSubtitleServiceStatus, subtitleServiceLogs, setSubtitleServiceLogs,
    subtitleJobs, setSubtitleJobs, subtitleJobsLoaded, setSubtitleJobsLoaded, subtitleServiceBusy,
    setSubtitleServiceBusy, subtitleServiceNotice, setSubtitleServiceNotice, subtitleLogsOpen,
    setSubtitleLogsOpen, activeSubtitleJobs, visibleSubtitleJobs
  };
}
