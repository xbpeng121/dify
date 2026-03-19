#!/bin/bash
#
# Dify K8s 部署配置引导脚本
# 交互式引导用户完成 configmap.yaml 和 secrets.yaml 中的变量替换
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIGMAP="$SCRIPT_DIR/configmap.yaml"
SECRETS="$SCRIPT_DIR/secrets.yaml"

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Dify K8s 部署配置引导${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# 检查文件是否存在
if [[ ! -f "$CONFIGMAP" ]]; then
    echo "错误: 找不到 $CONFIGMAP"
    exit 1
fi
if [[ ! -f "$SECRETS" ]]; then
    echo "错误: 找不到 $SECRETS"
    exit 1
fi

# macOS 兼容的 sed -i
sed_i() {
    if [[ "$(uname)" == "Darwin" ]]; then
        sed -i '' "$@"
    else
        sed -i "$@"
    fi
}

# 读取当前值的辅助函数（从 YAML 中提取 key 对应的 value）
get_current_value() {
    local file="$1"
    local key="$2"
    grep "^  ${key}:" "$file" | head -1 | sed 's/^[^"]*"//; s/"[^"]*$//'
}

# ============================================================
# 1. 数据库配置
# ============================================================
echo -e "${CYAN}--- 数据库配置 ---${NC}"

current_db_host=$(get_current_value "$CONFIGMAP" "DB_HOST")
read -p "数据库主机地址 [${current_db_host}]: " db_host
db_host="${db_host:-$current_db_host}"

current_db_password=$(get_current_value "$SECRETS" "DB_PASSWORD")
read -p "数据库密码 [${current_db_password}]: " db_password
db_password="${db_password:-$current_db_password}"

echo ""

# ============================================================
# 2. Redis 配置
# ============================================================
echo -e "${CYAN}--- Redis 配置 ---${NC}"

current_redis_host=$(get_current_value "$CONFIGMAP" "REDIS_HOST")
read -p "Redis 主机地址 [${current_redis_host}]: " redis_host
redis_host="${redis_host:-$current_redis_host}"

current_redis_password=$(get_current_value "$SECRETS" "REDIS_PASSWORD")
read -p "Redis 密码 [${current_redis_password}]: " redis_password
redis_password="${redis_password:-$current_redis_password}"

# 自动拼接 CELERY_BROKER_URL
celery_broker_url="redis://:${redis_password}@${redis_host}:6379/1"

echo ""

# ============================================================
# 3. 阿里云 OSS 配置
# ============================================================
echo -e "${CYAN}--- 阿里云 OSS 配置 ---${NC}"

current_oss_bucket=$(get_current_value "$CONFIGMAP" "ALIYUN_OSS_BUCKET_NAME")
read -p "OSS Bucket 名称 [${current_oss_bucket}]: " oss_bucket
oss_bucket="${oss_bucket:-$current_oss_bucket}"

current_oss_ak=$(get_current_value "$SECRETS" "ALIYUN_OSS_ACCESS_KEY")
read -p "OSS Access Key [${current_oss_ak}]: " oss_ak
oss_ak="${oss_ak:-$current_oss_ak}"

current_oss_sk=$(get_current_value "$SECRETS" "ALIYUN_OSS_SECRET_KEY")
read -p "OSS Secret Key [${current_oss_sk}]: " oss_sk
oss_sk="${oss_sk:-$current_oss_sk}"

echo ""

# ============================================================
# 4. Weaviate 配置
# ============================================================
echo -e "${CYAN}--- Weaviate 配置 ---${NC}"

current_weaviate=$(get_current_value "$CONFIGMAP" "WEAVIATE_ENDPOINT")
read -p "Weaviate 地址 [${current_weaviate}]: " weaviate_endpoint
weaviate_endpoint="${weaviate_endpoint:-$current_weaviate}"

echo ""

# ============================================================
# 显示配置摘要
# ============================================================
echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}  配置摘要${NC}"
echo -e "${YELLOW}========================================${NC}"
echo -e "  数据库主机:       ${GREEN}${db_host}${NC}"
echo -e "  数据库密码:       ${GREEN}${db_password}${NC}"
echo -e "  Redis 主机:       ${GREEN}${redis_host}${NC}"
echo -e "  Redis 密码:       ${GREEN}${redis_password}${NC}"
echo -e "  Celery Broker:    ${GREEN}${celery_broker_url}${NC}"
echo -e "  OSS Bucket:       ${GREEN}${oss_bucket}${NC}"
echo -e "  OSS Access Key:   ${GREEN}${oss_ak}${NC}"
echo -e "  OSS Secret Key:   ${GREEN}${oss_sk}${NC}"
echo -e "  Weaviate 地址:    ${GREEN}${weaviate_endpoint}${NC}"
echo ""

read -p "确认以上配置并写入文件？(y/N): " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "已取消，未做任何修改。"
    exit 0
fi

# ============================================================
# 执行替换
# ============================================================

# --- configmap.yaml ---
# DB_HOST
sed_i "s|^  DB_HOST: \".*\"|  DB_HOST: \"${db_host}\"|" "$CONFIGMAP"
# REDIS_HOST
sed_i "s|^  REDIS_HOST: \".*\"|  REDIS_HOST: \"${redis_host}\"|" "$CONFIGMAP"
# CELERY_BROKER_URL
sed_i "s|^  CELERY_BROKER_URL: \".*\"|  CELERY_BROKER_URL: \"${celery_broker_url}\"|" "$CONFIGMAP"
# ALIYUN_OSS_BUCKET_NAME
sed_i "s|^  ALIYUN_OSS_BUCKET_NAME: \".*\"|  ALIYUN_OSS_BUCKET_NAME: \"${oss_bucket}\"|" "$CONFIGMAP"
# PLUGIN_STORAGE_OSS_BUCKET
sed_i "s|^  PLUGIN_STORAGE_OSS_BUCKET: \".*\"|  PLUGIN_STORAGE_OSS_BUCKET: \"${oss_bucket}\"|" "$CONFIGMAP"
# WEAVIATE_ENDPOINT
sed_i "s|^  WEAVIATE_ENDPOINT: \".*\"|  WEAVIATE_ENDPOINT: \"${weaviate_endpoint}\"|" "$CONFIGMAP"

# --- secrets.yaml ---
# DB_PASSWORD
sed_i "s|^  DB_PASSWORD: \".*\"|  DB_PASSWORD: \"${db_password}\"|" "$SECRETS"
# REDIS_PASSWORD
sed_i "s|^  REDIS_PASSWORD: \".*\"|  REDIS_PASSWORD: \"${redis_password}\"|" "$SECRETS"
# ALIYUN_OSS_ACCESS_KEY
sed_i "s|^  ALIYUN_OSS_ACCESS_KEY: \".*\"|  ALIYUN_OSS_ACCESS_KEY: \"${oss_ak}\"|" "$SECRETS"
# ALIYUN_OSS_SECRET_KEY
sed_i "s|^  ALIYUN_OSS_SECRET_KEY: \".*\"|  ALIYUN_OSS_SECRET_KEY: \"${oss_sk}\"|" "$SECRETS"
# PLUGIN_ALIYUN_OSS_ACCESS_KEY_ID
sed_i "s|^  PLUGIN_ALIYUN_OSS_ACCESS_KEY_ID: \".*\"|  PLUGIN_ALIYUN_OSS_ACCESS_KEY_ID: \"${oss_ak}\"|" "$SECRETS"
# PLUGIN_ALIYUN_OSS_ACCESS_KEY_SECRET
sed_i "s|^  PLUGIN_ALIYUN_OSS_ACCESS_KEY_SECRET: \".*\"|  PLUGIN_ALIYUN_OSS_ACCESS_KEY_SECRET: \"${oss_sk}\"|" "$SECRETS"

echo ""
echo -e "${GREEN}配置已写入完成！${NC}"
echo "  - $CONFIGMAP"
echo "  - $SECRETS"
