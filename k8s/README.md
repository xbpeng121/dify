# Dify Kubernetes 部署指南

本指南将完成 Dify 从 Docker Compose 迁移到 Kubernetes,并使用 Ingress Nginx 作为服务代理。

## 文件来源
使用原docker部署方案中自定义的`docker-compose.yaml`文件，使用`kompose`工具转换成k8s资源文件，并手动修改资源文件内容，使其符合部署要求。

## 前置要求

1. **Kubernetes 集群** (v1.19+)
2. **kubectl** 已安装并配置
3. **Ingress Nginx Controller** 已安装
4. **数据库（Postgres、Redis、Weaviate）** 已安装
4. **外部存储 (OSS)** 配置完成
5. **Harbor私库** 已经上传依赖镜像

## 镜像需求

1. **ubuntu/squid:latest** 可从公共库拉取
2. **sibat-dify-web:1.11.4** 自编译，需手动上传
3. **sibat-dify-api:1.11.4** 自编译，需手动上传
4. **langgenius/dify-sandbox:0.2.12** 自编译，需手动上传

## 文件说明

| 文件名 | 说明 |
|--------|------|
| `k8s-namespace.yaml` | 命名空间定义 |
| `configmap.yaml` | 应用配置 |
| `secrets.yaml` | 敏感信息配置 |
| `harbor-secret.yaml` | harbor私库信息配置 |
| `api-deployment.yaml` | API 服务部署 |
| `worker-deployment.yaml` | Worker 和 Beat 部署 |
| `web-deployment.yaml` | Web 前端部署 |
| `sandbox-deployment.yaml` | 代码沙箱部署 |
| `ssrf-proxy-deployment.yaml` | SSRF 代理部署 |
| `ingress.yaml` | Ingress 路由配置 |
| `deploy.sh` | 自动化部署脚本 |
| `harbor_setup.sh` | harbor 镜像仓库配置脚本 |
| `fix_ingress_nginx.sh` | 修复 Ingress Nginx 脚本|

## 快速开始

### 1. 安装 Ingress Nginx Controller

如果还没有安装,运行:

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.1/deploy/static/provider/cloud/deploy.yaml
```

验证安装:

```bash
kubectl get pods -n ingress-nginx
```

### 2. 修改配置

根据你的环境修改以下配置:

#### `configmap.yaml`
- 数据库配置: `DB_HOST`, `DB_PORT`, `DB_DATABASE`
- Redis 配置: `REDIS_HOST`, `REDIS_PORT`
- Weaviate 配置: `WEAVIATE_ENDPOINT`
- 其他根据需要调整

#### `secrets.yaml`
**重要**: 修改所有密钥!
- `SECRET_KEY`: 应用密钥
- `DB_PASSWORD`: 数据库密码
- `REDIS_PASSWORD`: Redis 密码
- `WEAVIATE_API_KEY`: Weaviate API 密钥
- `ALIYUN_OSS_ACCESS_KEY` 和 `ALIYUN_OSS_SECRET_KEY`: 阿里云 OSS 密钥


#### `ingress.yaml`
- 如需域名，修改 `host` 为你的域名
- 如需 HTTPS,取消注释 TLS 配置

### 3. 部署应用

使用自动化脚本:

```bash
# 赋予执行权限
chmod +x harbor_setup.sh
chmod +x deploy.sh

# 初始化harbor私库，并上传镜像
sh harbor_setup.sh

# 部署所有资源
sh deploy.sh apply

# 查看状态
sh deploy.sh status

# 删除所有资源
sh deploy.sh delete
```

或手动部署:

```bash
# 1. 创建命名空间
kubectl apply -f k8s-namespace.yaml

# 2. 创建配置
kubectl apply -f configmap.yaml
kubectl apply -f secrets.yaml
kubectl apply -f harbor-secret.yaml

# 3. 部署服务
kubectl apply -f ssrf-proxy-deployment.yaml
kubectl apply -f sandbox-deployment.yaml
kubectl apply -f api-deployment.yaml
kubectl apply -f worker-deployment.yaml
kubectl apply -f web-deployment.yaml

# 4. 创建 Ingress
kubectl apply -f ingress.yaml
```

### 4. 验证部署

检查 Pod 状态:

```bash
kubectl get pods -n dify
```

检查服务:

```bash
kubectl get svc -n dify
```

检查 Ingress:

```bash
kubectl get ingress -n dify
kubectl describe ingress dify-ingress -n dify
```

获取访问地址:

```bash
kubectl get ingress dify-ingress -n dify
```

## 路由配置

Ingress 配置实现了以下路由规则(与原 Nginx 配置一致):

| 路径 | 后端服务 | 端口 |
|------|---------|------|
| `/console/api` | api | 5001 |
| `/api` | api | 5001 |
| `/v1` | api | 5001 |
| `/files` | api | 5001 |
| `/` | web | 3000 |

## 网络架构

```
Internet
    ↓
Ingress Nginx
    ↓
┌─────────────────────────────────┐
│  /console/api, /api, /v1, /files → API Service (5001)
│  /                                → Web Service (3000)
└─────────────────────────────────┘
    ↓                    ↓
API Pods            Web Pods
    ↓
Worker Pods
    ↓
Sandbox Service (8194)
    ↓
SSRF Proxy (3128)
```

## 存储说明

**重要**: 没有初始化 PVC，持久化存储采用AliyunOSS，sandbox依赖、日志等采用emptyDir，重启pod会丢失重新下载

## 配置 HTTPS

1. 安装 cert-manager:

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.13.0/cert-manager.yaml
```

2. 创建 ClusterIssuer:

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: your-email@example.com
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
    - http01:
        ingress:
          class: nginx
```

3. 修改 `ingress.yaml`,取消注释 TLS 配置和 annotations

## 扩展和调优

### 水平扩展

```bash
# 扩展 API
kubectl scale deployment dify-api -n dify --replicas=3

# 扩展 Worker
kubectl scale deployment dify-worker -n dify --replicas=2

# 扩展 Web
kubectl scale deployment dify-web -n dify --replicas=2
```

### 资源限制

在各个 deployment 文件中调整 `resources`:

```yaml
resources:
  requests:
    memory: "512Mi"
    cpu: "500m"
  limits:
    memory: "2Gi"
    cpu: "2000m"
```

### 自动扩展 (HPA)

```bash
# API 自动扩展
kubectl autoscale deployment dify-api -n dify \
  --cpu-percent=70 \
  --min=2 \
  --max=10

# Worker 自动扩展
kubectl autoscale deployment dify-worker -n dify \
  --cpu-percent=80 \
  --min=1 \
  --max=5
```

## 监控和日志

### 查看日志

```bash
# API 日志
kubectl logs -f deployment/dify-api -n dify

# Worker 日志
kubectl logs -f deployment/dify-worker -n dify

# Web 日志
kubectl logs -f deployment/dify-web -n dify
```

### 查看事件

```bash
kubectl get events -n dify --sort-by='.lastTimestamp'
```

## 故障排查

### Pod 无法启动

```bash
# 查看 Pod 详情
kubectl describe pod <pod-name> -n dify

# 查看日志
kubectl logs <pod-name> -n dify

# 进入 Pod 调试
kubectl exec -it <pod-name> -n dify -- /bin/bash
```

### Ingress 无法访问

```bash
# 检查 Ingress Controller
kubectl get pods -n ingress-nginx

# 查看 Ingress 详情
kubectl describe ingress dify-ingress -n dify

# 检查 Service
kubectl get svc -n dify
```

## 备份和恢复

### 备份配置

```bash
kubectl get all -n dify -o yaml > dify-backup.yaml
```

## 卸载

```bash
# 使用脚本
./deploy.sh delete

# 或手动删除
kubectl delete namespace dify
```

## 注意事项

- 注意修改所有默认密码和密钥
- 使用 Kubernetes Secrets 存储敏感信息
- 根据负载调整副本数和资源限制
- 确保外部存储有足够空间
