-- 016_chat_agent.sql
-- Chat agent threads + messages, scoped to (user, client). Strict ACL:
-- threads carry client_id so tools can re-verify the user's permission
-- on every dispatch — defense in depth against route-level bugs.

create table if not exists hub.chat_threads (
  thread_id text primary key,
  user_id text not null references hub.users(user_id) on delete cascade,
  client_id text not null references hub.clients(client_id) on delete cascade,
  title text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_chat_threads_user_client
  on hub.chat_threads (user_id, client_id, updated_at desc);

-- One row per turn message. assistant rows may have tool_calls jsonb;
-- tool rows have tool_call_id + tool_name. Order by id within thread.
create table if not exists hub.chat_messages (
  id bigserial primary key,
  thread_id text not null references hub.chat_threads(thread_id)
    on delete cascade,
  role text not null,
  content text,
  tool_calls jsonb,
  tool_call_id text,
  tool_name text,
  created_at timestamptz not null default now(),
  constraint chk_chat_role check (role in ('user','assistant','tool','system'))
);

create index if not exists idx_chat_messages_thread
  on hub.chat_messages (thread_id, id);
