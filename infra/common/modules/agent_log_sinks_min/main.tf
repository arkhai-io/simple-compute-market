# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

resource "google_bigquery_dataset" "feedback_dataset" {
  project       = var.gcp_project_name
  dataset_id    = replace("${var.agent_name}_feedback", "-", "_")
  friendly_name = "${var.agent_name}_feedback"
  location      = var.gcp_project_region
}

resource "google_bigquery_dataset" "telemetry_logs_dataset" {
  project       = var.gcp_project_name
  dataset_id    = replace("${var.agent_name}_telemetry", "-", "_")
  friendly_name = "${var.agent_name}_telemetry"
  location      = var.gcp_project_region
}

resource "google_logging_project_sink" "feedback_export_to_bigquery" {
  name        = "${var.agent_name}_feedback"
  project     = var.gcp_project_name
  destination = "bigquery.googleapis.com/projects/${var.gcp_project_name}/datasets/${google_bigquery_dataset.feedback_dataset.dataset_id}"
  filter      = var.feedback_logs_filter

  bigquery_options {
    use_partitioned_tables = true
  }

  unique_writer_identity = true
  depends_on             = [google_bigquery_dataset.feedback_dataset]
}

resource "google_logging_project_sink" "log_export_to_bigquery" {
  name        = "${var.agent_name}_telemetry"
  project     = var.gcp_project_name
  destination = "bigquery.googleapis.com/projects/${var.gcp_project_name}/datasets/${google_bigquery_dataset.telemetry_logs_dataset.dataset_id}"
  filter      = var.telemetry_logs_filter

  bigquery_options {
    use_partitioned_tables = true
  }

  unique_writer_identity = true
  depends_on             = [google_bigquery_dataset.telemetry_logs_dataset]
}

resource "google_project_iam_member" "bigquery_data_editor" {
  project = var.gcp_project_name
  role    = "roles/bigquery.dataEditor"
  member  = google_logging_project_sink.log_export_to_bigquery.writer_identity
}

resource "google_project_iam_member" "feedback_bigquery_data_editor" {
  project = var.gcp_project_name
  role    = "roles/bigquery.dataEditor"
  member  = google_logging_project_sink.feedback_export_to_bigquery.writer_identity
}
