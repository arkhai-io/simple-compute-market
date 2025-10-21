module "apis_min" {
  source           = "../common/modules/apis_min"
  gcp_project_name = var.gcp_project_name
}

locals {
  agents = [
    "agent-engine-a2a-agent",
    "a2a-agent-farmer",
    "a2a-agent-trader",
  ]
}

module "agent_iam_min" {
  depends_on       = [module.apis_min]
  for_each         = toset(local.agents)
  source           = "../common/modules/agent_iam_min"
  gcp_project_name = var.gcp_project_name
  agent_name       = each.key
  vertex_sa_member = module.apis_min.vertex_sa_member
}

module "agent_log_sinks_min" {
  depends_on            = [module.apis_min]
  for_each              = toset(local.agents)
  source                = "../common/modules/agent_log_sinks_min"
  gcp_project_name      = var.gcp_project_name
  gcp_project_region    = var.gcp_project_region
  agent_name            = each.key
  feedback_logs_filter  = "jsonPayload.log_type=\"feedback\" jsonPayload.service_name=\"${each.key}\""
  telemetry_logs_filter = "labels.service_name=\"${each.key}\" labels.type=\"agent_telemetry\""
}

module "agent_storage_min" {
  for_each           = toset(local.agents)
  source             = "../common/modules/agent_storage_min"
  gcp_project_name   = var.gcp_project_name
  gcp_project_region = var.gcp_project_region
  agent_name         = each.key
}