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
