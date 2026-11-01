export type ConfigKind = 'models' | 'workflows' | 'datasources' | 'llms' | 'federation'

// ── Embedding config (models/embeddings.yaml) ─────────────────────────────────

export interface EmbeddingEntry {
  name: string
  provider: string
  model: string
  dimensions: number
  api_base?: string
  api_key?: string
}

export interface EmbeddingRegistryFile {
  kind: 'EmbeddingRegistry'
  version?: string
  metadata?: { name: string }
  spec: { embeddings: EmbeddingEntry[] }
}

// ── Collection config (models/collections.yaml) ───────────────────────────────

export interface CollectionEntry {
  name: string
  description?: string
  embedding?: string  // undefined → global default
  datasource?: string // undefined → global vector datasource
}

export interface CollectionRegistryFile {
  kind: 'CollectionRegistry'
  version?: string
  metadata?: { name: string }
  spec: { collections: CollectionEntry[] }
}

export interface FilesIndex {
  models: string[]
  workflows: string[]
  datasources: string[]
  llms: string[]
  federation: string[]
  workflow_groups: Record<string, string[]>
}

export interface ModelField {
  name: string
  type: string
  /** Only present when type === 'enum'. Lists the allowed PostgreSQL enum values. */
  enum_values?: string[]
  primary_key?: boolean
  required?: boolean
  unique?: boolean
  index?: boolean
  default?: unknown
  input?: boolean
  /** Redacted from traces, logs and (unless policy allows) model prompts. */
  secure?: boolean
  description?: string
}

export interface ModelRelation {
  name: string          // response key / Python attr  e.g. "candidate"
  model: string         // MODEL_REGISTRY key           e.g. "Candidate"
  foreign_key: string   // FK column name               e.g. "candidate_id"
  type: 'many_to_one' | 'one_to_many'
}

export interface ModelConfig {
  kind: string
  enabled?: boolean
  version?: string
  metadata: { name: string; description?: string; schema_version?: string }
  spec: {
    tablename: string
    schema?: boolean
    datasource?: string
    fields: ModelField[]
    relations?: ModelRelation[]
  }
  // legacy flat shape (read-only compat)
  table?: string
  datasource?: string
  fields?: ModelField[]
}

// ── Datasource YAML shape ─────────────────────────────────────────────────────

export interface DatasourceConfig {
  kind: string
  enabled?: boolean
  metadata: { name: string; description?: string }
  spec: {
    driver?: string
    connection: Record<string, unknown>
    pooling?: Record<string, unknown>
  }
}

// ── Validation ────────────────────────────────────────────────────────────────

export interface ValidationIssue {
  severity: 'error' | 'warning'
  file: string
  line: number | null
  code: string | null
  message: string
}

/** `POST /dev/validate` — the `tuvl validate --json` report. */
export interface ValidationResult {
  valid: boolean
  errors: ValidationIssue[]
  warnings: ValidationIssue[]
  profiles: Record<string, { file: string; summary: string } & Record<string, unknown>>
}

// ── Agent Model YAML shape ────────────────────────────────────────────────────

export interface AgentModelConfig {
  kind: string
  version?: string
  enabled?: boolean
  metadata: { name: string; description?: string }
  // New format: model fields inside spec
  spec?: {
    type?: 'llm' | 'decision'
    provider?: 'laya' | 'jev' | 'llm' | 'litellm'
    model: string
    api_base?: string
    api_key?: string
    temperature?: number
    max_tokens?: number
    timeout?: number
  }
  // Legacy flat format (backward compat — read-only)
  model?: string
  api_base?: string
  api_key?: string
  temperature?: number
  max_tokens?: number
  timeout?: number
}

// ── Admin model versioning ────────────────────────────────────────────────────

export interface ModelVersionInfo {
  schema_version: string
  enabled: boolean
  fields: Array<{ name: string; type: string }>
  tablename: string
  datasource: string
  description?: string | null
}

/** Response from GET /admin/models — grouped by model name. */
export type AdminModelsResponse = Record<string, ModelVersionInfo[]>

// ── Admin scope catalogue ─────────────────────────────────────────────────────

/** Response from GET /admin/scopes. */
export interface AdminScopesResponse {
  /** CRUD scopes keyed by model name, e.g. { Candidate: ['candidate:read', ...] } */
  crud: Record<string, string[]>
  /** Workflow trigger scopes keyed by workflow name. */
  workflows: Record<string, string[]>
  /** System-level scopes (e.g. 'iam:admin'). */
  system: string[]
}

// ── Fork response ─────────────────────────────────────────────────────────────

export interface ForkVersionResponse {
  name: string
  source_version: string
  new_version: string
  file: string
}

// ── IAM ───────────────────────────────────────────────────────────────────────

export interface IamUser {
  id: string
  email: string
  is_active: boolean
  roles: string[]
  phone_number?: string | null
  first_name?: string | null
  last_name?: string | null
}

export interface IamRole {
  id: string
  name: string
  description: string | null
  scopes: string[]
}

// ── Federation provider YAML shape ──────────────────────────────────────────────────

export interface FederationProviderConfig {
  kind: string
  version?: string
  enabled?: boolean
  metadata: { name: string; description?: string }
  spec: {
    provider: 'google' | 'github' | 'microsoft' | string
    client_id: string
    client_secret: string
    auth_url?: string
    token_url?: string
    userinfo_url?: string
    scope?: string
    tenant_id?: string        // Microsoft only
    allowed_domains?: string[] // restrict login to these email domains
  }
}

// ── Telemetry config ──────────────────────────────────────────────────────────

export interface TelemetryConfig {
  enabled: boolean
  otlp_endpoint: string
  otlp_protocol?: string
  service_name: string
}

// ── System config ─────────────────────────────────────────────────────────────

export interface SystemConfig {
  deployment_mode?: string
  api: {
    expose_model_crud: boolean
    /** the dev server mounts every system route group; off = only what production mounts */
    dev_expose_all?: boolean
    /** system route groups a production server mounts (auth and runs when absent) */
    expose?: string[] | null
    /** what /docs, /redoc and /openapi.json show; absent = workflows in dev, off in production */
    docs?: string | null
  }
}

// ── Artifacts (versioned prompt/steering/skill/guardrail/hook/mcp assets) ─────

export type ArtifactType = 'prompt' | 'steering' | 'skill' | 'guardrail' | 'hook' | 'mcp' | 'judge' | 'rules'

/** Prose artifact types the create form may offer. */
export const PROSE_ARTIFACT_TYPES: ArtifactType[] = ['prompt', 'steering', 'skill']

/** Entry from GET /dev/artifacts. */
export interface ArtifactSummary {
  name: string
  type: ArtifactType
  description: string
  source: string
  versions: number[]
  latest: number
  referenced_by: string[]
}

/** Entry from GET /dev/artifacts/{name}. */
export interface ArtifactDetail {
  name: string
  type: ArtifactType
  description: string
  source: string
  version: number
  /** Prose artifacts return a string; structured (guardrail/hook/mcp) return the spec object. */
  content: string | Record<string, unknown>
  content_hash: string
}

