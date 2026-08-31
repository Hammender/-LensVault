export type TelegramAccount = {
  workspace_id: number;
  phone_masked: string | null;
  telegram_user_id: number | null;
  username: string | null;
  status: string;
  last_login_at: string | null;
  updated_at: string;
};
