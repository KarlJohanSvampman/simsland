-- CPL archive (docs/cpl_implementation_plan.md section 5): append-only history of finished conversations.
-- Live state is on the world (cpl_conversations / cpl_requests entities); these rows are never read back as state.
-- Written by backend/cpl/archive.py, which also creates them if missing.
create table if not exists cpl_conversations (
  sim_id text not null, conversation_id text not null, channel text not null,
  primary_purpose text, current_topic text, status text not null, resolution_reason text,
  initiator_id text not null, created_at double precision, started_at double precision,
  last_activity_at double precision, resolved_at double precision, context_summary jsonb,
  outcome jsonb, archived_at timestamptz default now(),
  primary key (sim_id, conversation_id));
create index if not exists cpl_conversations_initiator on cpl_conversations (sim_id, initiator_id, resolved_at desc);
create index if not exists cpl_conversations_reason on cpl_conversations (sim_id, resolution_reason);

create table if not exists cpl_participants (
  sim_id text, conversation_id text, character_id text, role text, participation_status text,
  joined_at double precision, left_at double precision, left_reason text, last_message_sequence int,
  primary key (sim_id, conversation_id, character_id));
create index if not exists cpl_participants_character on cpl_participants (sim_id, character_id, joined_at desc);

create table if not exists cpl_messages (
  sim_id text, message_id text, conversation_id text not null, sequence_number int not null,
  sender_id text not null, message_type text not null, payload jsonb not null, content text,
  world_ts double precision, delivery_status text,
  primary key (sim_id, message_id),
  unique (sim_id, conversation_id, sequence_number));

create table if not exists cpl_requests (
  sim_id text, request_id text, conversation_id text, source_message_id text, requester_id text,
  recipient_id text, request_type text, request_status text, deadline double precision, history jsonb,
  primary key (sim_id, request_id));
create index if not exists cpl_requests_recipient on cpl_requests (sim_id, recipient_id, request_status);
