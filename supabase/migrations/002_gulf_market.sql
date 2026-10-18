-- Gulf market columns. Existing rows are Pakistan postings; Gulf scraper
-- writes market = 'gulf'. Market-scoped cleanup keeps the catalogs isolated.
-- Apply after 001_full_job_payload.sql.

alter table if exists public.jobs
    add column if not exists market text not null default 'pk',
    add column if not exists country_code text,
    add column if not exists country text,
    add column if not exists city text,
    add column if not exists state_or_emirate text,
    add column if not exists source_host text;

update public.jobs
set
    market = 'pk',
    country_code = coalesce(nullif(btrim(country_code), ''), 'PK'),
    country = coalesce(nullif(btrim(country), ''), 'Pakistan')
where market is null
   or btrim(market) = ''
   or lower(market) = 'pk';

create index if not exists jobs_market_date_scrapped_idx
    on public.jobs (market, date_scrapped desc nulls last);

create index if not exists jobs_market_country_code_idx
    on public.jobs (market, country_code);

create index if not exists jobs_country_code_city_idx
    on public.jobs (country_code, city);
