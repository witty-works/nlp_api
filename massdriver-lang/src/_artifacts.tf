resource "massdriver_artifact" "internal" {
  field                = "internal"
  provider_resource_id = "${var.md_metadata.name_prefix}-internal"
  name                 = "Kubernetes deployment ${var.md_metadata.name_prefix} (internal)"
  artifact = jsonencode(
    {
      data = {
        api = {
          hostname = "http://${var.md_metadata.name_prefix}.${var.namespace}.svc.cluster.local.:${var.port}"
          port     = var.port
          protocol = "http"
        }
      }
      specs = {
        api = {
          version = "1.0.0"
        }
      }
    }
  )
}