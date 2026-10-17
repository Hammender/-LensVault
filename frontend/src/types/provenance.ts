export type SourceSummary = {
  source_type: string;
  text: string;
  has_details: boolean;
  site_name?: string | null;
  category_path?: string | null;
  actor_name?: string | null;
  record_method?: string;
};
