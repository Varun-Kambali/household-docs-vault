"""The schema-1 SQL kept here so a test can build a version-1 database."""

SCHEMA_1 = """
create table people (id text primary key, name text not null default '');
create table items (
    id integer primary key autoincrement,
    sha256 text not null,
    original_name text not null,
    origin text not null check (origin in ('inbox', 'upload')),
    rel_path text,
    target text,
    pending text,
    kind text,
    state text not null,
    reasons text not null default '[]',
    question text,
    reading text,
    overrides text not null default '{}',
    document_id text,
    created_at text not null,
    updated_at text not null
);
create index items_state on items (state);
create index items_sha on items (sha256);
create index items_path on items (rel_path);
create table documents (
    id text primary key,
    item_id integer not null references items (id),
    doc_type text not null,
    owner text not null references people (id),
    area text not null,
    rel_path text not null,
    sha256 text not null,
    doc_date text not null,
    date_source text not null check (date_source in ('document', 'received')),
    description text not null,
    fields text not null,
    issues text not null,
    secret_ref text,
    created_at text not null
);
create index documents_sha on documents (sha256);
create index documents_type on documents (doc_type);
create table document_people (
    document_id text not null references documents (id) on delete cascade,
    person_id text not null references people (id),
    role text not null check (role in ('owner', 'linked')),
    primary key (document_id, person_id)
);
create table pages (
    document_id text not null references documents (id) on delete cascade,
    page integer not null,
    width integer not null,
    height integer not null,
    primary key (document_id, page)
);
create table lines (
    document_id text not null references documents (id) on delete cascade,
    page integer not null,
    idx integer not null,
    text text not null,
    box text not null,
    confidence real,
    primary key (document_id, page, idx)
);
create table jobs (
    id integer primary key autoincrement,
    item_id integer not null references items (id),
    kind text not null,
    state text not null,
    attempts integer not null default 0,
    not_before text,
    created_at text not null
);
create index jobs_state on jobs (state, id);
create table activity (
    id integer primary key autoincrement,
    csv_pending integer not null default 0,
    time text not null,
    item_id integer,
    step text not null,
    outcome text not null,
    file text,
    detail text not null
);
create table meta (key text primary key, value text not null);
"""
