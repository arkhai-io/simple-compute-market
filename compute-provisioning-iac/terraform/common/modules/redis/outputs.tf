output "redis_host" {
  value       = google_redis_instance.redis.host
  description = "The IP address of the Cloud Memorystore Redis instance. Use this as REDIS_HOST in Docker containers on the async provisioning server."
}

output "redis_port" {
  value       = google_redis_instance.redis.port
  description = "The port number of the Cloud Memorystore Redis instance (default: 6379)."
}

output "redis_connection_string" {
  value       = "redis://${google_redis_instance.redis.host}:${google_redis_instance.redis.port}"
  description = "Full Redis connection string (redis://host:port) for Docker container environment variables."
}

output "redis_id" {
  value       = google_redis_instance.redis.id
  description = "The fully-qualified resource name of the Redis instance."
}
