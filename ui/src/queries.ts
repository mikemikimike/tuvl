import { useQuery, useMutation, useQueryClient, useQueries } from '@tanstack/react-query'
import {
  fetchFilesIndex,
  fetchFile,
  fetchModel,
  fetchDatasource,
  fetchAgentModel,
  saveFile,
  deleteFile,
  validateFiles,
  fetchHealth,
  fetchSystemModels,
  fetchSystemEmbeddings,
  fetchSystemCollections,
  fetchVectorStatus,
  fetchPgDatasources,
  updateVectorDatasource,
  fetchIamUsers,
  createIamUser,
  deleteIamUser,
  updateIamUser,
  fetchIamRoles,
  createIamRole,
  deleteIamRole,
  updateRoleScopes,
  assignRole,
  revokeRole,
  fetchFederationProviders,
  fetchFederationProvider,
  saveFederationProvider,
  deleteFederationProvider,
  fetchTelemetryConfig,
  saveTelemetryConfig,
  fetchSystemConfig,
  fetchProject,
  saveProject,
  saveSystemConfig,
  fetchAdminModels,
  toggleModelVersion,
  forkModelVersion,
  fetchAdminScopes,
} from './api'
import type { ConfigKind, FederationProviderConfig, TelemetryConfig, SystemConfig } from './types'

export const keys = {
  health: ['health'] as const,
  files: () => ['files'] as const,
  file: (kind: ConfigKind, name: string) => ['files', kind, name] as const,
  systemModels: ['system-models'] as const,
  systemEmbeddings: ['system-embeddings'] as const,
  systemCollections: ['system-collections'] as const,
  vectorStatus: ['vector-status'] as const,
  pgDatasources: ['pg-datasources'] as const,
  iamUsers: ['iam', 'users'] as const,
  iamRoles: ['iam', 'roles'] as const,
  federationProviders: ['federation'] as const,
  federationProvider: (name: string) => ['federation', name] as const,
  telemetryConfig: ['telemetry-config'] as const,
  systemConfig: ['system-config'] as const,
  project: ['project'] as const,
  testingConfig: ['testing-config'] as const,
  adminWorkflows: ['admin-workflows'] as const,
  adminModels: ['admin-models'] as const,
  adminScopes: ['admin-scopes'] as const,
  agentRuns: ['agent-runs'] as const,
  agentTrace: (runId: string) => ['agent-trace', runId] as const,
}

export function useHealth() {
  return useQuery({ queryKey: keys.health, queryFn: fetchHealth, refetchInterval: 10_000 })
}

export function useFilesIndex() {
  return useQuery({ queryKey: keys.files(), queryFn: () => fetchFilesIndex() })
}

export function useSystemModels() {
  return useQuery({ queryKey: keys.systemModels, queryFn: fetchSystemModels })
}

export function useSystemEmbeddings() {
  return useQuery({
    queryKey: keys.systemEmbeddings,
    queryFn: fetchSystemEmbeddings,
    staleTime: 30_000,
  })
}

export function useSystemCollections() {
  return useQuery({
    queryKey: keys.systemCollections,
    queryFn: fetchSystemCollections,
    staleTime: 30_000,
  })
}

export function useVectorStatus() {
  return useQuery({
    queryKey: keys.vectorStatus,
    queryFn: fetchVectorStatus,
    staleTime: 60_000,
    retry: false,
  })
}

export function usePgDatasources() {
  return useQuery({
    queryKey: keys.pgDatasources,
    queryFn: fetchPgDatasources,
    staleTime: 60_000,
    retry: false,
  })
}

export function useUpdateVectorDatasource() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ds: string) => updateVectorDatasource(ds),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.vectorStatus })
      qc.invalidateQueries({ queryKey: keys.pgDatasources })
    },
  })
}

export function useModel(name: string) {
  return useQuery({
    queryKey: keys.file('models', name),
    queryFn: () => fetchModel(name),
    enabled: !!name,
  })
}

/** Fetch multiple model configs in parallel. Results are in the same order as `names`. */
export function useModels(names: string[]) {
  return useQueries({
    queries: names.map(name => {
      const fileName = name.endsWith('.yaml') ? name : `${name}.yaml`
      return {
        queryKey: keys.file('models', fileName),
        queryFn: () => fetchModel(fileName),
        enabled: !!name,
      }
    }),
  })
}

export function useDatasource(name: string) {
  return useQuery({
    queryKey: keys.file('datasources', name),
    queryFn: () => fetchDatasource(name),
    enabled: !!name,
  })
}

export function useAgentModel(name: string) {
  return useQuery({
    queryKey: keys.file('llms', name),
    queryFn: () => fetchAgentModel(name),
    enabled: !!name,
  })
}

/** Fetches all configured AI model configs in parallel. */
export function useAllAgentModels(names: string[]) {
  return useQueries({
    queries: names.map((name) => ({
      queryKey: keys.file('llms', name),
      queryFn: () => fetchAgentModel(name),
      enabled: !!name,
    })),
  })
}

/**
 * Reads a whole registry-style YAML file (e.g. models/embeddings.yaml)
 * through the same cache key `useSaveFile` invalidates on write, so a save
 * elsewhere is reflected here without a manual refetch.
 */
export function useRegistryFile<T>(kind: ConfigKind, name: string) {
  return useQuery({
    queryKey: keys.file(kind, name),
    queryFn: () => fetchFile<T>(kind, name),
    retry: false,
  })
}

export function useSaveFile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ kind, name, body }: { kind: ConfigKind; name: string; body: unknown }) =>
      saveFile(kind, name, body),
    onSuccess: (_data, { kind, name }) => {
      qc.invalidateQueries({ queryKey: keys.file(kind, name) })
      qc.invalidateQueries({ queryKey: keys.files() })
    },
  })
}

export function useDeleteFile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ kind, name }: { kind: ConfigKind; name: string }) =>
      deleteFile(kind, name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.files() })
    },
  })
}

export function useValidate() {
  return useMutation({ mutationFn: validateFiles })
}

// ── IAM queries & mutations ───────────────────────────────────────────────────

export function useIamUsers() {
  return useQuery({ queryKey: keys.iamUsers, queryFn: fetchIamUsers })
}

export function useIamRoles() {
  return useQuery({ queryKey: keys.iamRoles, queryFn: fetchIamRoles })
}

export function useCreateIamUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { email: string; password?: string; is_active?: boolean; phone_number?: string; first_name?: string; last_name?: string }) =>
      createIamUser(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.iamUsers }),
  })
}

export function useDeleteIamUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => deleteIamUser(userId),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.iamUsers }),
  })
}

export function useUpdateIamUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, body }: { userId: string; body: { password?: string; is_active?: boolean; phone_number?: string | null; first_name?: string | null; last_name?: string | null } }) =>
      updateIamUser(userId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.iamUsers }),
  })
}

export function useCreateIamRole() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; description?: string; scopes: string[] }) =>
      createIamRole(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.iamRoles }),
  })
}

export function useDeleteIamRole() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (roleId: string) => deleteIamRole(roleId),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.iamRoles }),
  })
}

export function useUpdateRoleScopes() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ roleId, scopes }: { roleId: string; scopes: string[] }) =>
      updateRoleScopes(roleId, scopes),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.iamRoles }),
  })
}

export function useAssignRole() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, roleId }: { userId: string; roleId: string }) =>
      assignRole(userId, roleId),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.iamUsers }),
  })
}

export function useRevokeRole() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, roleId }: { userId: string; roleId: string }) =>
      revokeRole(userId, roleId),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.iamUsers }),
  })
}

// ── Federation ────────────────────────────────────────────────────────────────

export function useFederationProviders() {
  return useQuery({ queryKey: keys.federationProviders, queryFn: fetchFederationProviders })
}

export function useFederationProvider(name: string) {
  return useQuery({
    queryKey: keys.federationProvider(name),
    queryFn: () => fetchFederationProvider(name),
    enabled: !!name,
  })
}

export function useSaveFederationProvider() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, body }: { name: string; body: FederationProviderConfig }) =>
      saveFederationProvider(name, body),
    onSuccess: (_data, { name }) => {
      qc.invalidateQueries({ queryKey: keys.federationProviders })
      qc.invalidateQueries({ queryKey: keys.federationProvider(name) })
    },
  })
}

export function useDeleteFederationProvider() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => deleteFederationProvider(name),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.federationProviders }),
  })
}

// ── Telemetry config ──────────────────────────────────────────────────────────

export function useTelemetryConfig() {
  return useQuery({
    queryKey: keys.telemetryConfig,
    queryFn: fetchTelemetryConfig,
    retry: false,
  })
}

export function useSaveTelemetryConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: TelemetryConfig) => saveTelemetryConfig(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.telemetryConfig }),
  })
}

// ── System config ─────────────────────────────────────────────────────────────

export function useSystemConfig() {
  return useQuery({
    queryKey: keys.systemConfig,
    queryFn: fetchSystemConfig,
    retry: false,
  })
}

export function useSaveSystemConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: SystemConfig) => saveSystemConfig(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.systemConfig }),
  })
}

// ── Project identity ──────────────────────────────────────────────────────────

export function useProject() {
  return useQuery({ queryKey: keys.project, queryFn: fetchProject, retry: false })
}

export function useSaveProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Parameters<typeof saveProject>[0]) => saveProject(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.project }),
  })
}

// ── Testing config ────────────────────────────────────────────────────────────

// ── Admin workflow versioning ────────────────────────────────────────────────────

// ── Admin model versioning ─────────────────────────────────────────────────────

export function useAdminModels() {
  return useQuery({
    queryKey: keys.adminModels,
    queryFn: fetchAdminModels,
    staleTime: 0,
    retry: false,
  })
}

export function useToggleModelVersion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, version }: { name: string; version: string }) =>
      toggleModelVersion(name, version),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.adminModels }),
  })
}

export function useForkModelVersion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, version, newVersion }: { name: string; version: string; newVersion: string }) =>
      forkModelVersion(name, version, newVersion),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.adminModels })
      qc.invalidateQueries({ queryKey: keys.files() })
    },
  })
}

/** Returns the flat sorted list of every scope string known to the server. */
export function useAdminScopes() {
  return useQuery({
    queryKey: keys.adminScopes,
    queryFn: fetchAdminScopes,
    staleTime: 30_000,
    retry: false,
  })
}

// ── Agent Orchestrator: live runs ─────────────────────────────────────────────

