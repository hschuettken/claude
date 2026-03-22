# Ollama Router Prometheus Integration

## Overview

The Ollama Router exposes Prometheus metrics at `/metrics` (default port 9090) for centralized monitoring of LLM inference across all nodes. Metrics cover request latency, throughput, token rates, and per-node resource utilization.

## Metrics Endpoint

**URL:** `http://192.168.0.50:9090/metrics`  
**Format:** Prometheus text format  
**Update Interval:** Real-time (metrics updated on each request)

## Available Metrics

### Request Metrics

#### `ollama_router_requests_total`
**Type:** Counter  
**Labels:** `model`, `task_type`, `node`, `status`  
**Description:** Total requests by model, task type, node, and status (success/error)

Example query: `sum(rate(ollama_router_requests_total{status="success"}[5m])) by (task_type)`

#### `ollama_router_request_duration_seconds`
**Type:** Histogram  
**Labels:** `model`, `node`  
**Description:** Request latency (e2e from router receive to response complete)

Example query: `histogram_quantile(0.95, rate(ollama_router_request_duration_seconds_bucket[5m]))`

#### `ollama_router_ttft_seconds`
**Type:** Histogram  
**Labels:** `model`, `node`  
**Description:** Time to First Token (time from request to first completion token)

Example query: `histogram_quantile(0.5, rate(ollama_router_ttft_seconds_bucket[5m]))`

#### `ollama_router_tokens_per_second`
**Type:** Histogram  
**Labels:** `model`, `node`  
**Description:** Generation speed (tokens/sec)

Example query: `histogram_quantile(0.5, rate(ollama_router_tokens_per_second_bucket[5m]))`

### Node Metrics

#### `ollama_router_node_memory_bytes`
**Type:** Gauge  
**Labels:** `node`, `type` (used/max/available)  
**Description:** Per-node memory utilization

#### `ollama_router_node_models_loaded`
**Type:** Gauge  
**Labels:** `node`  
**Description:** Count of models currently loaded per node

#### `ollama_router_queue_depth`
**Type:** Gauge  
**Labels:** `node`  
**Description:** Number of in-flight requests per node

#### `ollama_router_model_load_seconds`
**Type:** Histogram  
**Labels:** `model`, `node`  
**Description:** Time taken to load/unload models

## Prometheus Server Configuration

Add this scrape job to your Prometheus `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'ollama-router'
    static_configs:
      - targets: ['192.168.0.50:9090']
    scrape_interval: 15s
    scrape_timeout: 10s
    metrics_path: '/metrics'
```

If Prometheus is running in Docker/K3S on the same network, use the service DNS name:

```yaml
  - job_name: 'ollama-router'
    static_configs:
      - targets: ['ollama-router:9090']  # or 'router.default.svc.cluster.local:9090' in K3S
    scrape_interval: 15s
```

## Grafana Dashboard

Create dashboards to visualize:

### 1. Request Rate & Latency
- **Query:** `sum(rate(ollama_router_requests_total{status="success"}[5m])) by (task_type)`
- **Type:** Graph
- **Description:** Requests per second by task type (fast/deep/code/embedding/reasoning)

### 2. P95 Latency by Model
- **Query:** `histogram_quantile(0.95, rate(ollama_router_request_duration_seconds_bucket[5m])) by (model)`
- **Type:** Table
- **Description:** 95th percentile response time for each model

### 3. Token Generation Speed
- **Query:** `histogram_quantile(0.5, rate(ollama_router_tokens_per_second_bucket[5m])) by (model)`
- **Type:** Graph
- **Description:** Median tokens/sec for each model (quality indicator)

### 4. Node Memory Usage
- **Query:** `ollama_router_node_memory_bytes{type="used"} / ollama_router_node_memory_bytes{type="max"} * 100`
- **Type:** Gauge
- **Description:** Memory utilization % per node

### 5. Models Per Node
- **Query:** `ollama_router_node_models_loaded`
- **Type:** Table
- **Description:** Currently loaded models per node

### 6. Queue Depth (Load)
- **Query:** `ollama_router_queue_depth`
- **Type:** Graph
- **Description:** In-flight requests per node (indicates bottlenecks)

### 7. Error Rate
- **Query:** `sum(rate(ollama_router_requests_total{status="error"}[5m])) by (node)`
- **Type:** Graph
- **Description:** Errors per second by node

## Integration with Existing Monitoring

### Export to Grafana

If you already have Grafana running (e.g., for PV/EV/Home Assistant dashboards):

1. **Add Prometheus data source** (if not already present):
   - Go to: **Grafana → Configuration → Data Sources**
   - Add: `http://prometheus:9090` (or your Prometheus host:port)
   - Name: `Prometheus-LLM` or similar

2. **Import or create dashboard**:
   - Create a new dashboard in Grafana
   - Add panels with the queries listed above
   - Or import from Grafana's dashboard marketplace

### Alert Rules (Optional)

Create Prometheus alert rules to notify on issues:

```yaml
# prometheus-rules.yml
groups:
  - name: ollama_router
    rules:
      - alert: OllamaRouterHighLatency
        expr: histogram_quantile(0.95, rate(ollama_router_request_duration_seconds_bucket[5m])) > 10
        for: 2m
        annotations:
          summary: "Ollama Router P95 latency >10s"
      
      - alert: OllamaRouterHighErrorRate
        expr: sum(rate(ollama_router_requests_total{status="error"}[5m])) by (node) / sum(rate(ollama_router_requests_total[5m])) by (node) > 0.05
        for: 1m
        annotations:
          summary: "Ollama Router error rate >5%"
      
      - alert: OllamaNodeDown
        expr: up{job="ollama-router"} == 0
        for: 1m
        annotations:
          summary: "Ollama node unreachable"
      
      - alert: OllamaMemoryNearCapacity
        expr: (ollama_router_node_memory_bytes{type="used"} / ollama_router_node_memory_bytes{type="max"}) > 0.9
        for: 5m
        annotations:
          summary: "Ollama node memory >90%"
```

## Testing the Metrics Endpoint

```bash
# Check if metrics are available
curl -s http://192.168.0.50:9090/metrics | head -50

# Filter for specific metrics
curl -s http://192.168.0.50:9090/metrics | grep ollama_router_requests_total

# Send a test request to generate metrics
curl -s -X POST http://192.168.0.50:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Task-Type: fast" \
  -d '{"model":"fast/qwen2.5:7b-q4_K_M","messages":[{"role":"user","content":"Hi"}],"max_tokens":5}' \
  | jq .

# Check metrics again
curl -s http://192.168.0.50:9090/metrics | grep "ollama_router_requests_total"
```

## Troubleshooting

### Metrics not appearing

1. **Router not running:** Check if `ollama-router` service is active
   ```bash
   docker ps | grep ollama-router
   ```

2. **Port misconfiguration:** Verify router config has `prometheus.port: 9090`
   ```bash
   cat /path/to/router/config.yaml | grep -A 3 prometheus:
   ```

3. **Network access:** Test connectivity from Prometheus host
   ```bash
   curl -v http://192.168.0.50:9090/metrics
   ```

### High-cardinality labels

If Prometheus grows too large, reduce label cardinality:
- Aggregate by fewer `model` variants (group qwen variants, for example)
- Remove `node` labels if monitoring per-node detail is not needed
- Increase scrape interval from 15s to 30s

## Next Steps

1. Deploy Ollama Router (`docker-compose up -d ollama-router`)
2. Add Prometheus scrape config above
3. Wait 1-2 minutes for metrics to appear in Prometheus
4. Create Grafana dashboard with panels above
5. Set up alerts as needed
