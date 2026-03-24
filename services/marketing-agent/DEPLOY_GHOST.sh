#!/bin/bash

##############################################################################
# Ghost CMS Deployment Script for Marketing Agent
# 
# This script deploys Ghost CMS on docker1 and configures the marketing-agent
# for Ghost publishing integration.
#
# Prerequisites:
#   - SSH access to docker1 (root@192.168.0.50)
#   - Docker and docker-compose installed on docker1
#   - MySQL service running at LXC 221 (192.168.0.75:3306)
#   - Cloudflared tunnel access (LXC 201) for public domain
#
# Usage:
#   bash DEPLOY_GHOST.sh [--init-only] [--setup-only]
##############################################################################

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
DOCKER1_IP="192.168.0.50"
DOCKER1_USER="root"
GHOST_DIR="/opt/ghost"
GHOST_DOMAIN="layer8.schuettken.net"
GHOST_DB_HOST="192.168.0.75"
GHOST_DB_PORT="3306"
GHOST_DB_USER="ghost"
GHOST_DB_NAME="ghost"
GHOST_PORT="2368"

# Colors output functions
log_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

log_success() {
    echo -e "${GREEN}✓${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    if ! command -v ssh &> /dev/null; then
        log_error "SSH not found. Install openssh-client."
        exit 1
    fi
    
    if ! command -v docker &> /dev/null; then
        log_warn "Docker not found locally (OK if deploying to docker1 only)"
    fi
    
    log_success "Prerequisites check passed"
}

# Test connection to docker1
test_docker1_connection() {
    log_info "Testing connection to docker1 (${DOCKER1_IP})..."
    
    if ! ping -c 1 -W 2 "${DOCKER1_IP}" > /dev/null 2>&1; then
        log_error "Cannot ping docker1 at ${DOCKER1_IP}"
        return 1
    fi
    
    log_success "Connection to docker1 successful"
}

# Deploy Ghost via SSH
deploy_ghost_via_ssh() {
    log_info "Deploying Ghost via SSH to docker1..."
    
    # Create Ghost directory
    log_info "Creating Ghost directory on docker1..."
    ssh "${DOCKER1_USER}@${DOCKER1_IP}" "mkdir -p ${GHOST_DIR}" || {
        log_error "Failed to create directory on docker1"
        return 1
    }
    
    # Copy docker-compose
    log_info "Copying docker-compose.yml to docker1..."
    scp "$(dirname "$0")/ghost/docker-compose.yml" \
        "${DOCKER1_USER}@${DOCKER1_IP}:${GHOST_DIR}/" || {
        log_error "Failed to copy docker-compose.yml"
        return 1
    }
    
    # Generate secure password
    local db_password
    db_password=$(openssl rand -base64 32)
    
    # Create .env file
    log_info "Creating .env file on docker1..."
    ssh "${DOCKER1_USER}@${DOCKER1_IP}" cat > "${GHOST_DIR}/.env" << EOF
# Ghost Configuration
GHOST_DB_PASSWORD=${db_password}
GHOST_URL=https://${GHOST_DOMAIN}
NODE_ENV=production

# Database
GHOST_DB_HOST=${GHOST_DB_HOST}
GHOST_DB_USER=${GHOST_DB_USER}

# Mail (optional)
MAIL_HOST=smtp.sendgrid.net
MAIL_PORT=587
MAIL_SECURE=false
MAIL_USER=apikey
MAIL_PASS=your_sendgrid_api_key_here
MAIL_FROM=noreply@${GHOST_DOMAIN}
EOF
    
    log_success "Created .env file with secure password"
    
    # Start Ghost container
    log_info "Starting Ghost container..."
    ssh "${DOCKER1_USER}@${DOCKER1_IP}" \
        "cd ${GHOST_DIR} && docker-compose up -d" || {
        log_error "Failed to start Ghost container"
        return 1
    }
    
    log_success "Ghost container started"
    
    # Wait for Ghost to be ready
    log_info "Waiting for Ghost to be ready (up to 60 seconds)..."
    local max_attempts=30
    local attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
        if ssh "${DOCKER1_USER}@${DOCKER1_IP}" \
            "docker-compose -f ${GHOST_DIR}/docker-compose.yml ps | grep -q 'ghost.*Up'"; then
            log_success "Ghost container is running"
            break
        fi
        
        attempt=$((attempt + 1))
        echo -n "."
        sleep 2
    done
    
    if [ $attempt -eq $max_attempts ]; then
        log_warn "Ghost may still be starting. Check status manually."
    fi
    
    return 0
}

# Configure Cloudflared tunnel
setup_cloudflared() {
    log_info "Setting up Cloudflared tunnel..."
    log_info "Manual step required: SSH to LXC 201 and update cloudflared config"
    
    cat << 'EOF'

To complete Cloudflared setup:

1. SSH to Cloudflared LXC (192.168.0.201):
   ssh root@192.168.0.201

2. Edit /etc/cloudflared/config.yaml and add this ingress rule:
   - hostname: layer8.schuettken.net
     service: http://192.168.0.50:2368

3. Reload cloudflared:
   systemctl reload cloudflared

4. Verify with:
   curl -I https://layer8.schuettken.net/
EOF
    
    log_warn "Cloudflared setup is manual. See instructions above."
}

# Initialize Ghost admin user
init_ghost_admin() {
    log_info "Initializing Ghost admin user..."
    log_warn "This requires manual access to Ghost setup wizard"
    
    cat << EOF

Ghost setup wizard is now available:

1. Open in browser: https://${GHOST_DOMAIN}/ghost/setup
2. Create admin account:
   - Email: your-email@example.com
   - Name: Henning
   - Password: (choose secure password)
   - Blog Title: Layer 8

3. After setup, create content tags in Ghost Admin:
   - Product
   - Leadership
   - Innovation
   - Technical
   - SAP Datasphere
   - Architecture

4. In Ghost Admin, create API Integration:
   - Settings → Integrations → "New Integration"
   - Name: marketing-agent
   - Copy Admin API Key (format: key_id:secret_hex)

5. Store the key in .env:
   GHOST_ADMIN_API_KEY=key_id:secret_hex
EOF

    log_warn "Manual Ghost admin setup required"
}

# Update marketing-agent configuration
update_marketing_agent_config() {
    log_info "Updating marketing-agent configuration..."
    
    # Check if .env exists
    local env_file="$(dirname "$0")/.env"
    if [ ! -f "$env_file" ]; then
        log_warn ".env file not found. Creating from example..."
        cp "$(dirname "$0")/.env.example" "$env_file"
    fi
    
    # Prompt for Ghost API key
    log_info "Enter Ghost Admin API Key (format: key_id:secret_hex):"
    read -r ghost_api_key
    
    # Update .env
    sed -i "s|GHOST_ADMIN_API_KEY=.*|GHOST_ADMIN_API_KEY=${ghost_api_key}|" "$env_file"
    sed -i "s|GHOST_URL=.*|GHOST_URL=https://${GHOST_DOMAIN}|" "$env_file"
    
    log_success "Updated marketing-agent .env"
}

# Deploy marketing-agent
deploy_marketing_agent() {
    log_info "Deploying marketing-agent service..."
    log_warn "Marketing-agent deployment requires ops-bridge or manual docker setup"
    
    cat << 'EOF'

To deploy marketing-agent:

1. Build Docker image:
   docker build -t marketing-agent:latest .

2. Run with docker-compose:
   docker-compose up -d

3. Verify service:
   curl http://localhost:8210/health

4. Or via ops-bridge (when available):
   POST /api/v1/services/deploy
   {
     "service": "marketing-agent",
     "version": "latest"
   }
EOF

    log_warn "Marketing-agent deployment requires manual steps"
}

# Test Ghost API integration
test_ghost_integration() {
    log_info "Testing Ghost Admin API integration..."
    log_warn "This requires Ghost API key in .env"
    
    cat << 'EOF'

To test Ghost API integration:

1. Create a draft in marketing-agent:
   curl -X POST http://localhost:8210/api/v1/drafts \
     -H "Content-Type: application/json" \
     -d '{
       "title": "Test Post",
       "content": "<p>Test content</p>",
       "tags": ["test"]
     }'

2. Approve the draft (update status to 'approved')

3. Publish to Ghost:
   curl -X POST http://localhost:8210/api/v1/drafts/1/publish

4. Verify post appears in Ghost Admin at:
   https://layer8.schuettken.net/ghost/editor/post/

EOF

    log_info "Manual API testing required"
}

# Main deployment flow
main() {
    echo -e "${BLUE}"
    echo "╔════════════════════════════════════════════════════════╗"
    echo "║     Ghost CMS Deployment for Marketing Agent           ║"
    echo "╚════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    
    check_prerequisites
    test_docker1_connection || exit 1
    
    # Parse arguments
    local init_only=false
    local setup_only=false
    
    for arg in "$@"; do
        case $arg in
            --init-only) init_only=true ;;
            --setup-only) setup_only=true ;;
        esac
    done
    
    if [ "$init_only" = true ]; then
        init_ghost_admin
        exit 0
    fi
    
    if [ "$setup_only" = true ]; then
        setup_cloudflared
        update_marketing_agent_config
        exit 0
    fi
    
    # Full deployment flow
    deploy_ghost_via_ssh || {
        log_error "Ghost deployment failed"
        exit 1
    }
    
    setup_cloudflared
    
    log_info "Ghost deployment complete. Next steps:"
    echo ""
    echo "1. Complete Ghost admin setup: https://${GHOST_DOMAIN}/ghost/setup"
    echo "2. Configure Cloudflared tunnel (LXC 201)"
    echo "3. Update marketing-agent .env with Ghost API key"
    echo "4. Deploy marketing-agent service"
    echo "5. Test end-to-end publishing"
    echo ""
    
    log_success "Deployment script completed"
}

# Run main function
main "$@"
