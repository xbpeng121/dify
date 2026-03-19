#!/bin/bash

# Dify Kubernetes 部署脚本（使用 OSS 存储）
# 用法: ./deploy.sh [apply|delete|status]

set -e

NAMESPACE="dify"
ACTION=${1}

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查 kubectl 是否安装
check_kubectl() {
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl 未安装,请先安装 kubectl"
        exit 1
    fi
    log_info "kubectl 已安装: $(kubectl version --client --short 2>/dev/null || kubectl version --client)"
}

# 检查 Ingress Nginx Controller 是否安装
check_ingress_nginx() {
    if ! kubectl get pods -n ingress-nginx &> /dev/null; then
        log_warn "Ingress Nginx Controller 未安装"
        log_warn "请运行以下命令安装:"
        echo "kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.1/deploy/static/provider/cloud/deploy.yaml"
        read -p "是否继续部署? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    else
        log_info "Ingress Nginx Controller 已安装"
    fi
}

# 应用资源
apply_resources() {
    log_info "开始部署 Dify 到 Kubernetes..."
    
    # 创建命名空间
    log_info "创建命名空间..."
    kubectl apply -f k8s-namespace.yaml
    
    # 创建 ConfigMap 和 Secrets
    log_info "创建配置和密钥..."
    kubectl apply -f configmap.yaml
    kubectl apply -f secrets.yaml

    # 创建 Harbor 镜像仓库 Secret
    log_info "创建 Harbor 镜像仓库 Secret..."
    # 判断 harbor-secret.yaml 是否存在
    if [ -f harbor-secret.yaml ]; then
        kubectl apply -f harbor-secret.yaml
    else
        log_error "harbor-secret.yaml 文件不存在，跳过 harbor-secret 创建。"
        log_error "如需创建 harbor-secret.yaml，请先运行 harbor_setup.sh 脚本生成该文件。"
    fi
    
    # 部署 SSRF Proxy
    log_info "部署 SSRF Proxy..."
    kubectl apply -f ssrf-proxy-deployment.yaml
    
    # 部署 Sandbox
    log_info "部署 Sandbox..."
    kubectl apply -f sandbox-deployment.yaml

    # 部署 plugin-daemon
    log_info "部署 Plugin Daemon..."
    kubectl apply -f plugin-daemon-deployment.yaml
    
    # 部署 API
    log_info "部署 API 服务..."
    kubectl apply -f api-deployment.yaml
    
    # 部署 Worker
    log_info "部署 Worker 服务..."
    kubectl apply -f worker-deployment.yaml
    
    # 部署 Web
    log_info "部署 Web 服务..."
    kubectl apply -f web-deployment.yaml
    
    # 创建 Ingress
    log_info "创建 Ingress..."
    kubectl apply -f ingress.yaml
    
    log_info "部署完成!"
    log_info "等待所有 Pod 就绪..."
    kubectl wait --for=condition=Ready pods --all -n $NAMESPACE --timeout=300s || log_warn "部分 Pod 未就绪"
    
    show_status
    
    echo ""
    log_info "==================== 重要说明 ===================="
    log_info "✓ 所有文件存储在阿里云 OSS"
    log_info "✓ 日志输出到 stdout (可通过 kubectl logs 查看)"
    log_info "✓ 临时文件使用容器临时目录"
    log_info "✓ 不使用任何 PVC"
    log_warn "⚠ Sandbox 依赖不持久化，Pod 重启后需重新下载"
    log_info "如需持久化 Sandbox 依赖，请另外创建包含pvc的部署脚本。"
    log_info "================================================"
}

# 删除资源
delete_resources() {
    log_warn "开始删除 Dify 资源..."
    
    kubectl delete -f ingress.yaml --ignore-not-found=true
    kubectl delete -f web-deployment.yaml --ignore-not-found=true
    kubectl delete -f worker-deployment.yaml --ignore-not-found=true
    kubectl delete -f api-deployment.yaml --ignore-not-found=true
    kubectl delete -f sandbox-deployment.yaml --ignore-not-found=true
    kubectl delete -f plugin-daemon-deployment.yaml --ignore-not-found=true    
    kubectl delete -f ssrf-proxy-deployment.yaml --ignore-not-found=true
    kubectl delete -f harbor-secret.yaml --ignore-not-found=true
    kubectl delete -f secrets.yaml --ignore-not-found=true
    kubectl delete -f configmap.yaml --ignore-not-found=true
    kubectl delete -f k8s-namespace.yaml --ignore-not-found=true
    
    log_info "删除完成!"
}

# 显示状态
show_status() {
    echo ""
    log_info "=== Namespace 状态 ==="
    kubectl get namespace $NAMESPACE 2>/dev/null || log_error "Namespace 不存在"
    
    echo ""
    log_info "=== Pods 状态 ==="
    kubectl get pods -n $NAMESPACE -o wide
    
    echo ""
    log_info "=== Services 状态 ==="
    kubectl get svc -n $NAMESPACE
    
    echo ""
    log_info "=== Ingress 状态 ==="
    kubectl get ingress -n $NAMESPACE
    
    echo ""
    log_info "=== Ingress 详情 ==="
    kubectl describe ingress dify-ingress -n $NAMESPACE 2>/dev/null || log_warn "Ingress 不存在"
    
    echo ""
    INGRESS_IP=$(kubectl get ingress dify-ingress -n $NAMESPACE -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null)
    INGRESS_HOSTNAME=$(kubectl get ingress dify-ingress -n $NAMESPACE -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null)
    
    if [ -n "$INGRESS_IP" ]; then
        log_info "访问地址: http://$INGRESS_IP"
    elif [ -n "$INGRESS_HOSTNAME" ]; then
        log_info "访问地址: http://$INGRESS_HOSTNAME"
    else
        log_warn "Ingress 地址未分配,请稍后查看"
        log_info "运行以下命令查看 Ingress 地址:"
        echo "kubectl get ingress dify-ingress -n $NAMESPACE"
    fi
}

# 主函数
main() {
    check_kubectl
    
    case $ACTION in
        apply|deploy)
            check_ingress_nginx
            apply_resources
            ;;
        delete|remove)
            delete_resources
            ;;
        status|get)
            show_status
            ;;
        *)
            log_error "未知操作: $ACTION"
            echo "用法: $0 [apply|delete|status]"
            echo "  apply  - 部署所有资源"
            echo "  delete - 删除所有资源"
            echo "  status - 显示部署状态"
            exit 1
            ;;
    esac
}

main
