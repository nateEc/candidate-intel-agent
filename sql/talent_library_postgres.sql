CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS candidate_profiles (
  candidate_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  display_name TEXT,
  masked_name TEXT,
  current_title TEXT,
  current_company TEXT,
  work_years_text TEXT,
  work_years_value NUMERIC(5, 2),
  education_level TEXT,
  school TEXT,
  major TEXT,
  city TEXT,
  expected_position TEXT,
  expected_salary_text TEXT,
  expected_salary_min_k INTEGER,
  expected_salary_max_k INTEGER,
  expected_salary_months INTEGER,
  expected_annual_salary_min_k INTEGER,
  expected_annual_salary_max_k INTEGER,
  job_status TEXT,
  active_status TEXT,
  highest_grade TEXT,
  highest_score INTEGER,
  profile_summary TEXT,
  tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  source_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS candidate_identifiers (
  id BIGSERIAL PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
  identifier_type TEXT NOT NULL,
  identifier_hash TEXT NOT NULL,
  identifier_display TEXT,
  source_type TEXT,
  confidence NUMERIC(4, 3),
  evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(identifier_type, identifier_hash)
);

CREATE TABLE IF NOT EXISTS raw_candidate_sources (
  id BIGSERIAL PRIMARY KEY,
  candidate_id UUID REFERENCES candidate_profiles(candidate_id) ON DELETE SET NULL,
  source_type TEXT NOT NULL,
  source_platform TEXT NOT NULL DEFAULT 'boss_zhipin',
  source_key TEXT NOT NULL,
  source_fingerprint TEXT,
  collected_at TIMESTAMPTZ,
  raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(source_type, source_key)
);

CREATE TABLE IF NOT EXISTS candidate_contacts (
  id BIGSERIAL PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
  contact_type TEXT NOT NULL,
  contact_value TEXT NOT NULL,
  contact_hash TEXT NOT NULL,
  source_type TEXT NOT NULL,
  consent_status TEXT NOT NULL DEFAULT 'unknown',
  visibility TEXT NOT NULL DEFAULT 'restricted',
  verified_at TIMESTAMPTZ,
  evidence_span_id TEXT,
  confidence NUMERIC(4, 3),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(candidate_id, contact_type, contact_hash)
);

CREATE TABLE IF NOT EXISTS resume_versions (
  resume_version_id BIGSERIAL PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
  source_platform TEXT NOT NULL DEFAULT 'boss_zhipin',
  source_fingerprint TEXT,
  collected_at TIMESTAMPTZ,
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
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(candidate_id, resume_text_hash)
);

CREATE TABLE IF NOT EXISTS resume_evidence_spans (
  evidence_span_id TEXT PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
  resume_version_id BIGINT REFERENCES resume_versions(resume_version_id) ON DELETE SET NULL,
  source_table TEXT,
  field_path TEXT,
  text TEXT NOT NULL,
  start_char INTEGER,
  end_char INTEGER,
  confidence NUMERIC(4, 3),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS work_experiences (
  id BIGSERIAL PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
  company_name TEXT,
  title TEXT,
  department TEXT,
  start_date DATE,
  end_date DATE,
  duration_months INTEGER,
  description TEXT,
  tech_stack_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  achievements_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  salary_min_k INTEGER,
  salary_max_k INTEGER,
  evidence_span_id TEXT REFERENCES resume_evidence_spans(evidence_span_id) ON DELETE SET NULL,
  confidence NUMERIC(4, 3),
  extractor_version TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(candidate_id, company_name, title, start_date, end_date)
);

CREATE TABLE IF NOT EXISTS education_experiences (
  id BIGSERIAL PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
  school TEXT,
  major TEXT,
  degree TEXT,
  start_date DATE,
  end_date DATE,
  ranking_tags_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  evidence_span_id TEXT REFERENCES resume_evidence_spans(evidence_span_id) ON DELETE SET NULL,
  confidence NUMERIC(4, 3),
  extractor_version TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(candidate_id, school, major, degree, start_date, end_date)
);

CREATE TABLE IF NOT EXISTS projects (
  id BIGSERIAL PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
  project_name TEXT,
  role TEXT,
  start_date DATE,
  end_date DATE,
  business_context TEXT,
  technical_context TEXT,
  outcomes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  evidence_span_id TEXT REFERENCES resume_evidence_spans(evidence_span_id) ON DELETE SET NULL,
  confidence NUMERIC(4, 3),
  extractor_version TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS skills (
  id BIGSERIAL PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
  skill_name TEXT NOT NULL,
  skill_type TEXT,
  proficiency TEXT,
  last_used_at DATE,
  evidence_span_id TEXT REFERENCES resume_evidence_spans(evidence_span_id) ON DELETE SET NULL,
  confidence NUMERIC(4, 3),
  extractor_version TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(candidate_id, skill_name)
);

CREATE TABLE IF NOT EXISTS compensation_observations (
  id BIGSERIAL PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
  observation_type TEXT NOT NULL,
  salary_text TEXT,
  monthly_min_k INTEGER,
  monthly_max_k INTEGER,
  months INTEGER,
  annual_min_k INTEGER,
  annual_max_k INTEGER,
  observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  evidence_span_id TEXT REFERENCES resume_evidence_spans(evidence_span_id) ON DELETE SET NULL,
  confidence NUMERIC(4, 3),
  source_type TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS candidate_preferences (
  id BIGSERIAL PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
  preference_type TEXT NOT NULL,
  preference_value TEXT NOT NULL,
  evidence_span_id TEXT REFERENCES resume_evidence_spans(evidence_span_id) ON DELETE SET NULL,
  confidence NUMERIC(4, 3),
  source_type TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(candidate_id, preference_type, preference_value)
);

CREATE TABLE IF NOT EXISTS candidate_sensitive_attributes (
  id BIGSERIAL PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
  attribute_type TEXT NOT NULL,
  attribute_value TEXT NOT NULL,
  visibility TEXT NOT NULL DEFAULT 'restricted',
  use_allowed_for_matching BOOLEAN NOT NULL DEFAULT false,
  use_allowed_for_outreach BOOLEAN NOT NULL DEFAULT false,
  evidence_span_id TEXT REFERENCES resume_evidence_spans(evidence_span_id) ON DELETE SET NULL,
  confidence NUMERIC(4, 3),
  source_type TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS candidate_signals (
  id BIGSERIAL PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
  signal_type TEXT NOT NULL,
  signal_value TEXT,
  score NUMERIC(6, 2),
  confidence NUMERIC(4, 3),
  evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  extractor_version TEXT,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(candidate_id, signal_type, extractor_version)
);

CREATE TABLE IF NOT EXISTS candidate_matches (
  id BIGSERIAL PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
  job_id TEXT,
  job_title TEXT,
  job_description TEXT,
  score INTEGER NOT NULL,
  grade TEXT NOT NULL,
  reasons_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  risks_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  matcher_version TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS candidate_interactions (
  id BIGSERIAL PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
  interaction_type TEXT NOT NULL,
  job_title TEXT,
  message_text TEXT,
  status TEXT NOT NULL,
  channel TEXT,
  raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS talent_pools (
  pool_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL UNIQUE,
  description TEXT,
  rules_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS candidate_pool_memberships (
  id BIGSERIAL PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
  pool_id UUID NOT NULL REFERENCES talent_pools(pool_id) ON DELETE CASCADE,
  fit_score NUMERIC(6, 2),
  reason TEXT,
  assigned_by TEXT NOT NULL DEFAULT 'agent',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(candidate_id, pool_id)
);

CREATE TABLE IF NOT EXISTS candidate_tasks (
  task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  candidate_id UUID NOT NULL REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
  task_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  due_at TIMESTAMPTZ,
  title TEXT NOT NULL,
  description TEXT,
  priority TEXT NOT NULL DEFAULT 'medium',
  created_by TEXT NOT NULL DEFAULT 'agent',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS candidate_embeddings (
  id BIGSERIAL PRIMARY KEY,
  candidate_id UUID NOT NULL REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
  embedding_type TEXT NOT NULL,
  embedding_model TEXT NOT NULL,
  embedding VECTOR(384) NOT NULL,
  source_text_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(candidate_id, embedding_type, embedding_model, source_text_hash)
);

CREATE TABLE IF NOT EXISTS talent_search_documents (
  candidate_id UUID PRIMARY KEY REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  tags TEXT,
  search_vector TSVECTOR,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_events (
  id BIGSERIAL PRIMARY KEY,
  event_type TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  actor TEXT NOT NULL DEFAULT 'agent',
  event_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_candidate_profiles_grade ON candidate_profiles(highest_grade);
CREATE INDEX IF NOT EXISTS idx_candidate_profiles_city ON candidate_profiles(city);
CREATE INDEX IF NOT EXISTS idx_candidate_profiles_position ON candidate_profiles(expected_position);
CREATE INDEX IF NOT EXISTS idx_candidate_profiles_last_seen ON candidate_profiles(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_candidate_identifiers_candidate ON candidate_identifiers(candidate_id);
CREATE INDEX IF NOT EXISTS idx_candidate_identifiers_lookup ON candidate_identifiers(identifier_type, identifier_hash);
CREATE INDEX IF NOT EXISTS idx_candidate_contacts_candidate ON candidate_contacts(candidate_id);
CREATE INDEX IF NOT EXISTS idx_resume_versions_candidate ON resume_versions(candidate_id);
CREATE INDEX IF NOT EXISTS idx_work_experiences_candidate ON work_experiences(candidate_id);
CREATE INDEX IF NOT EXISTS idx_education_experiences_candidate ON education_experiences(candidate_id);
CREATE INDEX IF NOT EXISTS idx_skills_candidate ON skills(candidate_id);
CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(skill_name);
CREATE INDEX IF NOT EXISTS idx_candidate_signals_candidate ON candidate_signals(candidate_id);
CREATE INDEX IF NOT EXISTS idx_candidate_matches_candidate ON candidate_matches(candidate_id);
CREATE INDEX IF NOT EXISTS idx_candidate_interactions_candidate ON candidate_interactions(candidate_id);
CREATE INDEX IF NOT EXISTS idx_candidate_pool_memberships_pool ON candidate_pool_memberships(pool_id);
CREATE INDEX IF NOT EXISTS idx_candidate_tasks_candidate ON candidate_tasks(candidate_id);
CREATE INDEX IF NOT EXISTS idx_candidate_tasks_status ON candidate_tasks(status);
CREATE INDEX IF NOT EXISTS idx_talent_search_vector ON talent_search_documents USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_candidate_embeddings_vector ON candidate_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
