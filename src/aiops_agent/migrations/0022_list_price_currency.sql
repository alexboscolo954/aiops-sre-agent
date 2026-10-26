-- Slice 10.5b: a list price is looked up in a currency (Azure's catalog offers several);
-- the rows already there are USD.
alter table list_prices rename column usd_hour to hour_price;
alter table list_prices add column currency text not null default 'USD';
alter table list_prices drop constraint list_prices_pkey;
alter table list_prices add primary key (currency, provider, region, instance_type);
