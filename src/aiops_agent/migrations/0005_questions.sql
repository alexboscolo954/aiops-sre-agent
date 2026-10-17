-- A Question's latest Answer, and the last @mention it took (a follow-up claims the
-- thread only with a newer one). One Investigation per Slack thread: the thread
-- finds its Investigation, and a redelivered mention can't start a second one.
alter table investigations add column answer jsonb, add column last_mention_ts text;
create unique index investigations_slack_thread on investigations (slack_channel, slack_ts);
