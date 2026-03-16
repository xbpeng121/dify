#!/bin/bash

# Harbor 镜像仓库配置脚本

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
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

log_tip() {
    echo -e "${CYAN}[TIP]${NC} $1"
}

echo "=========================================="
echo "  Harbor 镜像仓库配置向导"
echo "=========================================="
echo ""

# 1. 获取 Harbor 信息
log_info "请输入 Harbor 配置信息："
echo ""

read -p "Harbor 地址 (如 harbor.example.com): " HARBOR_URL
read -p "Harbor 项目名称 (默认: dify): " HARBOR_PROJECT
HARBOR_PROJECT=${HARBOR_PROJECT:-dify}

echo ""
log_info "是否需要认证？"
read -p "需要用户名密码认证吗？(y/n): " -n 1 -r NEED_AUTH
echo ""

if [[ $NEED_AUTH =~ ^[Yy]$ ]]; then
    read -p "Harbor 用户名: " HARBOR_USERNAME
    read -sp "Harbor 密码: " HARBOR_PASSWORD
    echo ""
    read -p "邮箱 (可选): " HARBOR_EMAIL
    HARBOR_EMAIL=${HARBOR_EMAIL:-noreply@example.com}
fi

echo ""
log_info "=========================================="
log_info "配置摘要"
log_info "=========================================="
echo "Harbor 地址: $HARBOR_URL"
echo "项目名称: $HARBOR_PROJECT"
echo "需要认证: $NEED_AUTH"
if [[ $NEED_AUTH =~ ^[Yy]$ ]]; then
    echo "用户名: $HARBOR_USERNAME"
fi
echo ""

read -p "确认配置正确？(y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_error "已取消"
    exit 1
fi

# 2. 创建 Docker Registry Secret
if [[ $NEED_AUTH =~ ^[Yy]$ ]]; then
    log_info "创建 Harbor 认证 Secret..."
    
    kubectl create secret docker-registry harbor-secret \
        --docker-server=$HARBOR_URL \
        --docker-username=$HARBOR_USERNAME \
        --docker-password=$HARBOR_PASSWORD \
        --docker-email=$HARBOR_EMAIL \
        -n dify \
        --dry-run=client -o yaml > harbor-secret.yaml
    
    if [ $? -eq 0 ]; then
        log_info "✅ Secret 创建成功"
    else
        log_error "❌ Secret 创建失败"
        exit 1
    fi
else
    log_info "跳过认证配置（Harbor 项目为公开）"
fi

# 3. 检查 Harbor 中现有的镜像
echo ""
log_info "=========================================="
log_info "Harbor 现有镜像检查"
log_info "=========================================="
echo ""
log_info "需要将这些镜像推送到 Harbor"
echo "  ✅ $HARBOR_URL/$HARBOR_PROJECT/ubuntu/squid:latest"
echo "  ✅ $HARBOR_URL/$HARBOR_PROJECT/sibat-dify-web:1.11.4"
echo "  ✅ $HARBOR_URL/$HARBOR_PROJECT/sibat-dify-api:1.11.4"
echo "  ✅ $HARBOR_URL/$HARBOR_PROJECT/langgenius/dify-sandbox:0.2.12"
echo ""

echo ""
read -p "镜像已推送到 Harbor？(y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_warn "请先推送镜像到 Harbor，然后重新运行此脚本"
    exit 0
fi

# 4. 更新 Deployment 镜像地址
echo ""
log_info "=========================================="
log_info "更新 Kubernetes Deployment"
log_info "=========================================="
echo ""

# 让用户确认是否更新镜像地址 
read -p "是否更新deployment文件中的镜像地址？(y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_warn "跳过镜像地址更新"
    exit 0
fi
log_info "更新镜像地址..."

# 备份原文件
for file in api-deployment.yaml worker-deployment.yaml web-deployment.yaml sandbox-deployment.yaml ssrf-proxy-deployment.yaml; do
    if [ -f "$file" ]; then
        cp "$file" "${file}.bak.$(date +%Y%m%d%H%M%S)"
    fi
done

# 更新镜像地址
if [ -f "api-deployment.yaml" ]; then
    sed -i "s|image:.*dify-api.*|image: $HARBOR_URL/$HARBOR_PROJECT/sibat-dify-api:1.11.4|g" api-deployment.yaml
    log_info "✅ 已更新 api-deployment.yaml"
fi

if [ -f "worker-deployment.yaml" ]; then
    sed -i "s|image:.*dify-api.*|image: $HARBOR_URL/$HARBOR_PROJECT/sibat-dify-api:1.11.4|g" worker-deployment.yaml
    log_info "✅ 已更新 worker-deployment.yaml"
fi

if [ -f "web-deployment.yaml" ]; then
    sed -i "s|image:.*dify-web.*|image: $HARBOR_URL/$HARBOR_PROJECT/sibat-dify-web:1.11.4|g" web-deployment.yaml
    log_info "✅ 已更新 web-deployment.yaml"
fi

if [ -f "sandbox-deployment.yaml" ]; then
    sed -i "s|image:.*dify-sandbox.*|image: $HARBOR_URL/$HARBOR_PROJECT/langgenius/dify-sandbox:0.2.12|g" sandbox-deployment.yaml
    log_info "✅ 已更新 sandbox-deployment.yaml"
fi

if [ -f "ssrf-proxy-deployment.yaml" ]; then
    sed -i "s|image: ubuntu/squid.*|image: $HARBOR_URL/$HARBOR_PROJECT/ubuntu/squid:latest|g" ssrf-proxy-deployment.yaml
    log_info "✅ 已更新 ssrf-proxy-deployment.yaml"
fi


# 5. 重新部署
echo ""
log_info "=========================================="
log_info "镜像已更新，请重新部署服务"
log_info "=========================================="
echo ""
