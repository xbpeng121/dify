#!/bin/bash

# 修复 Ingress Nginx Controller 镜像拉取问题
# 使用国内镜像源或临时禁用 admission webhook

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

echo "=========================================="
echo "  Ingress Nginx 问题修复脚本"
echo "=========================================="
echo ""

# 1. 检查当前状态
log_info "检查当前 Ingress Nginx 状态..."
kubectl get pods -n ingress-nginx

echo ""
log_info "检查失败的 Pod 详情..."
FAILED_PODS=$(kubectl get pods -n ingress-nginx --field-selector=status.phase!=Running -o name 2>/dev/null || echo "")

if [ -n "$FAILED_PODS" ]; then
    for pod in $FAILED_PODS; do
        echo ""
        log_warn "Pod: $pod"
        kubectl describe $pod -n ingress-nginx | grep -A 10 "Events:"
    done
fi

echo ""
echo "=========================================="
echo "请选择修复方案："
echo "=========================================="
echo "1. 完全卸载并使用国内镜像重新安装（推荐）"
echo "2. 临时禁用 admission webhook 验证"
echo "3. 查看详细错误信息后退出"
echo ""
read -p "请输入选项 (1-3): " choice

case $choice in
    1)
        log_info "方案 1: 使用国内镜像重新安装..."
        
        # 卸载现有的
        log_warn "正在卸载现有的 Ingress Nginx..."
        kubectl delete namespace ingress-nginx --ignore-not-found=true
        
        log_info "等待命名空间完全删除..."
        while kubectl get namespace ingress-nginx &> /dev/null; do
            echo -n "."
            sleep 2
        done
        echo ""
        
        log_info "使用国内镜像重新安装..."
        
        # 创建临时配置文件
        cat > /tmp/ingress-nginx-values.yaml <<EOF
controller:
  image:
    registry: registry.cn-hangzhou.aliyuncs.com
    image: google_containers/nginx-ingress-controller
    tag: "v1.8.1"
    digest: ""
  admissionWebhooks:
    patch:
      image:
        registry: registry.cn-hangzhou.aliyuncs.com
        image: google_containers/kube-webhook-certgen
        tag: "v20230407"
        digest: ""
EOF
        
        log_info "检查是否安装了 Helm..."
        if command -v helm &> /dev/null; then
            log_info "使用 Helm 安装..."
            helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
            helm repo update
            helm install ingress-nginx ingress-nginx/ingress-nginx \
                --namespace ingress-nginx \
                --create-namespace \
                -f /tmp/ingress-nginx-values.yaml
        else
            log_warn "Helm 未安装，使用 kubectl 安装..."
            
            # 下载官方 YAML 并修改镜像
            log_info "下载部署文件..."
            curl -sL https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.1/deploy/static/provider/cloud/deploy.yaml -o /tmp/ingress-nginx.yaml
            
            log_info "替换为国内镜像..."
            sed -i 's|registry.k8s.io/ingress-nginx/controller:.*|registry.cn-hangzhou.aliyuncs.com/google_containers/nginx-ingress-controller:v1.8.1|g' /tmp/ingress-nginx.yaml
            sed -i 's|registry.k8s.io/ingress-nginx/kube-webhook-certgen:.*|registry.cn-hangzhou.aliyuncs.com/google_containers/kube-webhook-certgen:v20230407|g' /tmp/ingress-nginx.yaml
            
            log_info "应用配置..."
            kubectl apply -f /tmp/ingress-nginx.yaml
        fi
        
        log_info "等待 Pod 启动..."
        sleep 10
        kubectl wait --namespace ingress-nginx \
            --for=condition=ready pod \
            --selector=app.kubernetes.io/component=controller \
            --timeout=120s || log_warn "等待超时，请手动检查"
        
        log_info "安装完成！"
        kubectl get pods -n ingress-nginx
        ;;
        
    2)
        log_info "方案 2: 临时禁用 admission webhook..."
        
        log_warn "删除 ValidatingWebhookConfiguration..."
        kubectl delete validatingwebhookconfigurations ingress-nginx-admission --ignore-not-found=true
        
        log_info "现在可以创建 Ingress 了"
        log_warn "注意：这只是临时方案，建议后续重新安装 Ingress Controller"
        ;;
         
    3)
        log_info "查看详细错误信息..."
        echo ""
        log_info "=== Controller Pod 详情 ==="
        kubectl describe pod -l app.kubernetes.io/component=controller -n ingress-nginx
        
        echo ""
        log_info "=== Admission Create Job 详情 ==="
        kubectl describe job ingress-nginx-admission-create -n ingress-nginx
        
        echo ""
        log_info "=== Admission Patch Job 详情 ==="
        kubectl describe job ingress-nginx-admission-patch -n ingress-nginx
        
        exit 0
        ;;
        
    *)
        log_error "无效的选项"
        exit 1
        ;;
esac

echo ""
log_info "=========================================="
log_info "修复完成！请验证状态："
log_info "=========================================="
echo "kubectl get pods -n ingress-nginx"
echo ""
log_info "如果 Pod 正常运行，可以重新部署 Dify Ingress："
echo "kubectl apply -f ingress.yaml"
