export type TelegramAccount = {
  workspace_id: number;
  api_id: number | null;
  phone_masked: string | null;
  telegram_user_id: number | null;
  username: string | null;
  status: string;
  code_delivery: string | null;
  last_login_at: string | null;
  updated_at: string;
};

export type TelegramDialog = {
  peer_id: string;
  title: string;
  username: string | null;
  entity_type: "channel" | "group" | "bot";
  is_bot: boolean;
  is_forum: boolean;
  unread_count: number;
};

export type TelegramTopic = {
  topic_id: number;
  title: string;
  closed: boolean;
  pinned: boolean;
  date: string | null;
};

export type TelegramForumScan = {
  is_forum: boolean;
  peer_id: string;
  title: string;
  username: string | null;
  entity_type: string;
  topics: TelegramTopic[];
};
