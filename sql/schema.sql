CREATE TABLE candidates (
  id BIGSERIAL PRIMARY KEY,
  source_platform TEXT NOT NULL DEFAULT 'boss_zhipin',
  source_fingerprint TEXT NOT NULL UNIQUE,
  masked_name TEXT,
  age INTEGER,
  gender TEXT,
  years_experience TEXT,
  education_level TEXT,
  school TEXT,
  major TEXT,
  expected_city TEXT,
  expected_position TEXT,
  expected_salary TEXT,
  job_status TEXT,
  active_status TEXT,
  short_summary TEXT,
  tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  source_url TEXT,
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_candidates_expected_position ON candidates (expected_position);
CREATE INDEX idx_candidates_expected_city ON candidates (expected_city);
CREATE INDEX idx_candidates_school ON candidates (school);
CREATE INDEX idx_candidates_last_seen_at ON candidates (last_seen_at);
CREATE INDEX idx_candidates_tags_gin ON candidates USING GIN (tags_json);

CREATE TABLE candidate_observations (
  id BIGSERIAL PRIMARY KEY,
  candidate_id BIGINT REFERENCES candidates(id),
  source_fingerprint TEXT NOT NULL,
  recruiter_id TEXT,
  search_keyword TEXT,
  search_city TEXT,
  search_filters_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  visible_card_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  parsed_confidence NUMERIC(4, 3)
);

CREATE INDEX idx_candidate_observations_fingerprint ON candidate_observations (source_fingerprint);
CREATE INDEX idx_candidate_observations_observed_at ON candidate_observations (observed_at);

CREATE TABLE candidate_resume_snapshots (
  id BIGSERIAL PRIMARY KEY,
  candidate_id BIGINT REFERENCES candidates(id),
  source_platform TEXT NOT NULL DEFAULT 'boss_zhipin',
  source_fingerprint TEXT NOT NULL,
  collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  source_url TEXT,
  parser_version TEXT NOT NULL DEFAULT 'resume_ocr_v1',
  resume_text TEXT NOT NULL,
  resume_text_hash TEXT NOT NULL,
  resume_sections_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  detail_summary TEXT,
  detail_tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  detail_schools_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  detail_companies_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  detail_positions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  ocr_engine TEXT,
  ocr_pages_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_candidate_resume_snapshots_fingerprint ON candidate_resume_snapshots (source_fingerprint);
CREATE INDEX idx_candidate_resume_snapshots_collected_at ON candidate_resume_snapshots (collected_at);
CREATE UNIQUE INDEX idx_candidate_resume_snapshots_hash ON candidate_resume_snapshots (source_fingerprint, resume_text_hash);

CREATE TABLE candidate_notes (
  id BIGSERIAL PRIMARY KEY,
  candidate_id BIGINT NOT NULL REFERENCES candidates(id),
  recruiter_id TEXT NOT NULL,
  job_id TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_candidate_notes_candidate_id ON candidate_notes (candidate_id);
CREATE INDEX idx_candidate_notes_status ON candidate_notes (status);
