-- Learn & Earn streaming payout schema (Supabase/Postgres)
-- Purpose: track asynchronous Superfluid/G$ streams with idempotency + retries.

create table if not exists public.learn_earn_streams (
  id uuid primary key default gen_random_uuid(),
  reward_id uuid,
  user_wallet text not null,
  amount_gd numeric(30, 18) not null check (amount_gd > 0),
  duration_seconds integer not null check (duration_seconds > 0),
  flow_rate_wei numeric(78, 0) not null check (flow_rate_wei > 0),
  stream_token_address text not null,
  sender_wallet text not null,
  start_at timestamptz not null,
  end_at timestamptz not null,
  status text not null default 'pending_start' check (
    status in ('pending_start', 'active', 'pending_stop', 'stopped', 'start_failed', 'stop_failed')
  ),
  create_tx_hash text,
  stop_tx_hash text,
  retry_count integer not null default 0,
  idempotency_key text not null,
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint learn_earn_streams_end_after_start check (end_at > start_at)
);

create unique index if not exists learn_earn_streams_idempotency_key_uidx
  on public.learn_earn_streams (idempotency_key);

create index if not exists learn_earn_streams_status_end_at_idx
  on public.learn_earn_streams (status, end_at);

create index if not exists learn_earn_streams_user_wallet_idx
  on public.learn_earn_streams (user_wallet);

create index if not exists learn_earn_streams_reward_id_idx
  on public.learn_earn_streams (reward_id);

create or replace function public.touch_learn_earn_streams_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_touch_learn_earn_streams_updated_at on public.learn_earn_streams;
create trigger trg_touch_learn_earn_streams_updated_at
before update on public.learn_earn_streams
for each row execute function public.touch_learn_earn_streams_updated_at();

-- Optional audit table for operator/debug visibility.
create table if not exists public.learn_earn_stream_events (
  id bigserial primary key,
  stream_id uuid not null references public.learn_earn_streams(id) on delete cascade,
  event_type text not null,
  payload jsonb,
  tx_hash text,
  created_at timestamptz not null default now()
);

create index if not exists learn_earn_stream_events_stream_id_idx
  on public.learn_earn_stream_events (stream_id, created_at desc);
