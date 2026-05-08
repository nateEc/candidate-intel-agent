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
  detail_summary TEXT,
  detail_tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  detail_schools_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  detail_companies_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  detail_positions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  parsed_confidence NUMERIC(4, 3),
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

CREATE TABLE application_scan_runs (
  id TEXT PRIMARY KEY,
  job_filter TEXT,
  status TEXT NOT NULL DEFAULT 'running',
  candidate_count INTEGER NOT NULL DEFAULT 0,
  application_count INTEGER NOT NULL DEFAULT 0,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  raw_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE candidate_identity_links (
  identity_key TEXT PRIMARY KEY,
  source_fingerprint TEXT NOT NULL,
  confidence NUMERIC(4, 3),
  basis_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_candidate_identity_links_fingerprint ON candidate_identity_links (source_fingerprint);

CREATE TABLE candidate_applications (
  id BIGSERIAL PRIMARY KEY,
  application_key TEXT NOT NULL UNIQUE,
  source_fingerprint TEXT NOT NULL,
  scan_run_id TEXT REFERENCES application_scan_runs(id),
  job_title TEXT,
  job_filter TEXT,
  candidate_name TEXT,
  chat_status TEXT,
  last_message TEXT,
  message_time TEXT,
  observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_candidate_applications_fingerprint ON candidate_applications (source_fingerprint);
CREATE INDEX idx_candidate_applications_job ON candidate_applications (job_title);
CREATE INDEX idx_candidate_applications_scan ON candidate_applications (scan_run_id);

CREATE TABLE candidate_evaluations (
  id BIGSERIAL PRIMARY KEY,
  source_fingerprint TEXT NOT NULL,
  application_key TEXT,
  job_title TEXT,
  grade TEXT NOT NULL,
  score INTEGER NOT NULL,
  reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  risks_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  recommended_action TEXT,
  evaluator_version TEXT,
  evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  raw_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX idx_candidate_evaluations_fingerprint ON candidate_evaluations (source_fingerprint);
CREATE INDEX idx_candidate_evaluations_grade ON candidate_evaluations (grade);

CREATE TABLE candidate_interactions (
  id BIGSERIAL PRIMARY KEY,
  source_fingerprint TEXT NOT NULL,
  interaction_type TEXT NOT NULL,
  job_title TEXT,
  message_text TEXT,
  status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  raw_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX idx_candidate_interactions_fingerprint ON candidate_interactions (source_fingerprint);
CREATE INDEX idx_candidate_interactions_type ON candidate_interactions (interaction_type);

CREATE TABLE boss_job_postings (
  id BIGSERIAL PRIMARY KEY,
  source_platform TEXT NOT NULL DEFAULT 'boss_zhipin',
  source_fingerprint TEXT NOT NULL UNIQUE,
  source_url TEXT,
  search_keyword TEXT,
  search_city TEXT,
  job_title TEXT,
  company_name TEXT,
  job_city TEXT,
  salary_text TEXT,
  experience_requirement TEXT,
  education_requirement TEXT,
  recruiter_name TEXT,
  recruiter_title TEXT,
  tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  description TEXT,
  raw_card_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_boss_job_postings_company ON boss_job_postings (company_name);
CREATE INDEX idx_boss_job_postings_title ON boss_job_postings (job_title);
CREATE INDEX idx_boss_job_postings_city ON boss_job_postings (job_city);
CREATE INDEX idx_boss_job_postings_collected_at ON boss_job_postings (collected_at);
CREATE INDEX idx_boss_job_postings_tags_gin ON boss_job_postings USING GIN (tags_json);

CREATE TABLE org_intel_reports (
  id BIGSERIAL PRIMARY KEY,
  company_name TEXT NOT NULL,
  aliases_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  report_type TEXT NOT NULL DEFAULT 'single_company',
  report_markdown TEXT NOT NULL,
  source_counts_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  report_path TEXT
);

CREATE INDEX idx_org_intel_reports_company ON org_intel_reports (company_name);
CREATE INDEX idx_org_intel_reports_generated_at ON org_intel_reports (generated_at);

CREATE TABLE org_findings (
  id BIGSERIAL PRIMARY KEY,
  company_name TEXT NOT NULL,
  finding_type TEXT NOT NULL,
  title TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'medium',
  confidence NUMERIC(4, 3),
  summary TEXT NOT NULL,
  evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  report_id BIGINT REFERENCES org_intel_reports(id)
);

CREATE INDEX idx_org_findings_company ON org_findings (company_name);
CREATE INDEX idx_org_findings_type ON org_findings (finding_type);
CREATE INDEX idx_org_findings_generated_at ON org_findings (generated_at);

CREATE TABLE org_intel_jobs (
  id TEXT PRIMARY KEY,
  client_request_id TEXT,
  company_name TEXT NOT NULL,
  aliases_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  mode TEXT NOT NULL DEFAULT 'standard',
  refresh TEXT NOT NULL DEFAULT 'auto',
  status TEXT NOT NULL DEFAULT 'queued',
  current_step TEXT,
  eta_seconds INTEGER,
  eta_at TIMESTAMPTZ,
  request_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  error_message TEXT,
  report_id BIGINT REFERENCES org_intel_reports(id),
  report_path TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_org_intel_jobs_company ON org_intel_jobs (company_name);
CREATE INDEX idx_org_intel_jobs_status ON org_intel_jobs (status);
CREATE INDEX idx_org_intel_jobs_created_at ON org_intel_jobs (created_at);

CREATE TABLE org_intel_job_runs (
  id BIGSERIAL PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES org_intel_jobs(id),
  run_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  command TEXT,
  run_file TEXT,
  row_count INTEGER,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  error_message TEXT
);

CREATE INDEX idx_org_intel_job_runs_job_id ON org_intel_job_runs (job_id);

CREATE TABLE org_intel_subscriptions (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  display_name TEXT,
  cadence TEXT NOT NULL DEFAULT 'weekly',
  companies_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
  weekly_since_days INTEGER NOT NULL DEFAULT 14,
  monthly_since_days INTEGER NOT NULL DEFAULT 45,
  freshness_policy TEXT NOT NULL DEFAULT 'auto',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_org_intel_subscriptions_owner ON org_intel_subscriptions (owner_id);
CREATE INDEX idx_org_intel_subscriptions_status ON org_intel_subscriptions (status);

CREATE TABLE org_intel_digest_runs (
  id TEXT PRIMARY KEY,
  subscription_id TEXT NOT NULL REFERENCES org_intel_subscriptions(id),
  owner_id TEXT NOT NULL,
  cadence TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  current_step TEXT,
  eta_seconds INTEGER,
  eta_at TIMESTAMPTZ,
  request_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  company_jobs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  digest_markdown TEXT,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_org_intel_digest_runs_subscription ON org_intel_digest_runs (subscription_id);
CREATE INDEX idx_org_intel_digest_runs_owner ON org_intel_digest_runs (owner_id);
CREATE INDEX idx_org_intel_digest_runs_status ON org_intel_digest_runs (status);
CREATE INDEX idx_org_intel_digest_runs_created_at ON org_intel_digest_runs (created_at);
