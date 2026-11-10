-- Each Investigation's Slack thread: the channel and the parent message's ts.
alter table investigations add column slack_channel text, add column slack_ts text;
