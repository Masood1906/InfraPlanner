// Shared graph design tokens — import from here, never redefine locally

export const NODE_COLOR = {
  RouterModel:            '#00d4ff',
  RouterFeature:          '#a855f7',
  OperationalImplication: '#00ff88',
  InfraRequirement:       '#ffd700',
  NodeProfile:            '#ff8c42',
  DeploymentPattern:      '#ff4466',
  KubernetesCluster:      '#38bdf8',
  DeploymentTopology:     '#e879f9',
}

export const EDGE_COLOR = {
  HAS_FEATURE:  '#00d4ff',
  IMPLIES:      '#a855f7',
  REQUIRES:     '#ffd700',
  SATISFIED_BY: '#00ff88',
  FITS_PATTERN: '#ff4466',
}

export const NODE_SIZE = {
  RouterModel:            12,
  RouterFeature:          8,
  OperationalImplication: 9,
  InfraRequirement:       8,
  NodeProfile:            9,
  DeploymentPattern:      11,
  KubernetesCluster:      8,
  DeploymentTopology:     8,
}

// Canonical layer ordering — used by both GraphViewer and ReasoningChain
export const LAYER_ORDER = [
  'RouterModel',
  'RouterFeature',
  'OperationalImplication',
  'InfraRequirement',
  'NodeProfile',
  'DeploymentPattern',
  'KubernetesCluster',
  'DeploymentTopology',
]

export const LAYERS = [
  { type: 'RouterModel',            label: 'Router' },
  { type: 'RouterFeature',          label: 'Features' },
  { type: 'OperationalImplication', label: 'Implications' },
  { type: 'InfraRequirement',       label: 'Requirements' },
  { type: 'NodeProfile',            label: 'Node Profiles' },
  { type: 'DeploymentPattern',      label: 'Deployment' },
]
