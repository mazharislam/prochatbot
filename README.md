# Professional Profile Chatbot

> A serverless, AI-powered chatbot that represents professional profiles through conversational AI. Built with AWS Bedrock, featuring enterprise-grade security, cost optimization, and full CI/CD automation.

[![Deploy Status](https://github.com/mazharislam/prochatbot/workflows/Deploy%20Professional%20Profile%20Chatbot/badge.svg)](https://github.com/mazharislam/prochatbot/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![AWS](https://img.shields.io/badge/AWS-Serverless-orange.svg)](https://aws.amazon.com/)

**🔗 Live Demo:** [https://d120rlxmguy8lv.cloudfront.net](https://d120rlxmguy8lv.cloudfront.net)

---

## 🎯 Overview

An intelligent chatbot that represents a professional's experience, skills, and expertise through conversational AI. Built with a focus on **security**, **cost-efficiency**, and **scalability**.

### Key Features

- 🤖 **AI-Powered Conversations** - Amazon Bedrock (Nova Micro) with context-aware responses
- 🔒 **Enterprise Security** - Rate limiting, jailbreak detection, IAM least-privilege
- ☁️ **100% Serverless** - Lambda, API Gateway, S3, CloudFront ($5-20/month)
- 🚀 **Automated CI/CD** - GitHub Actions with OIDC (no long-lived credentials)
- 📊 **Session Management** - Persistent conversations with 24-hour expiry
- 🛡️ **Content Security** - Resume data in S3, never in codebase
- 🏗️ **Infrastructure as Code** - Complete Terraform automation

---

## 🏛️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                CloudFront CDN (AWS)                          │
│           TLS 1.2+, Global Edge Caching                      │
└────────────────────┬───────────────┬────────────────────────┘
                     │               │
        ┌────────────▼─────┐   ┌────▼──────────────┐
        │  S3 Frontend     │   │  API Gateway      │
        │  (Next.js SPA)   │   │  (HTTP API)       │
        └──────────────────┘   └────┬──────────────┘
                                    │
                          ┌─────────▼──────────┐
                          │  Lambda (Python)   │
                          │  FastAPI + Mangum  │
                          └──┬──────────┬──────┘
                             │          │
              ┌──────────────┘          └──────────────┐
              │                                        │
    ┌─────────▼────────┐                  ┌───────────▼──────────┐
    │  S3 Resume Data  │                  │  S3 Conversation     │
    │  (Private)       │                  │  Memory (Private)    │
    │  - PDFs          │                  │  - Session History   │
    │  - style.txt     │                  └──────────────────────┘
    │  - summary.txt   │
    │  - facts.json    │
    └────────┬─────────┘
             │
    ┌────────▼─────────┐
    │  Bedrock AI      │
    │  (Nova Micro)    │
    └──────────────────┘
```

**Technology Stack:**
- **Frontend**: Next.js 15, React, TailwindCSS, TypeScript
- **Backend**: Python 3.12, FastAPI, Mangum (ASGI adapter)
- **AI**: AWS Bedrock (Nova Micro), context-aware conversations
- **Infrastructure**: Terraform, AWS Lambda, API Gateway, CloudFront CDN, S3
- **CI/CD**: GitHub Actions with OIDC authentication

---

## 🚀 Quick Start

### Prerequisites

- AWS Account with Bedrock access
- Terraform >= 1.5
- Node.js >= 20
- Python >= 3.12
- Docker (for Lambda packaging)

### 1. Clone Repository

```bash
git clone https://github.com/mazharislam/prochatbot.git
cd prochatbot
```

### 2. Configure AWS Credentials

**For GitHub Actions (OIDC - Recommended):**

Create GitHub repository secrets:
- `AWS_ROLE_ARN`: IAM role ARN for GitHub Actions
- `AWS_ACCOUNT_ID`: Your AWS account ID
- `DEFAULT_AWS_REGION`: AWS region (e.g., us-east-1)

**For Local Development:**

```bash
aws configure
# OR use environment variables
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret
export AWS_REGION=us-east-1
```

### 3. Prepare Resume Data

Create your resume documents in `backend/data/`:

```
backend/data/
├── facts.json          # Professional metadata (name, role, skills)
├── style.txt           # Communication style guide
├── summary.txt         # Professional identity and background
├── linkedin.pdf        # LinkedIn profile export (optional)
├── aboutme.pdf         # Personal statement (optional)
└── resume1.pdf         # Primary resume (optional)
```

Upload to S3:

```bash
# Create S3 bucket for resume data
aws s3 mb s3://YOUR_ACCOUNT_ID-profile-data

# Upload files
aws s3 sync backend/data/ s3://YOUR_ACCOUNT_ID-profile-data/ \
  --exclude "*" --include "*.pdf" --include "*.txt" --include "facts.json"
```

### 4. Deploy Infrastructure

```bash
cd terraform

# Initialize Terraform
terraform init

# Create workspace
terraform workspace new dev

# Review plan
terraform plan

# Deploy
terraform apply
```

### 5. Deploy via CI/CD (Alternative)

Simply push to `main` branch:

```bash
git add .
git commit -m "Initial deployment"
git push origin main
```

GitHub Actions will automatically:
1. Package Lambda function
2. Build frontend
3. Deploy infrastructure with Terraform
4. Upload frontend to S3
5. Invalidate CloudFront cache

---

## 📋 Configuration

### Environment Variables

**Backend Lambda:**

| Variable | Description | Default |
|----------|-------------|---------|
| `S3_RESUME_BUCKET` | S3 bucket with resume PDFs and profile data | Required |
| `S3_MEMORY_BUCKET` | S3 bucket for conversation history | Required |
| `BEDROCK_MODEL_ID` | Bedrock model identifier | `amazon.nova-micro-v1:0` |
| `MAX_TOKENS_PER_REQUEST` | Max tokens per AI request | `1000` |
| `MAX_REQUESTS_PER_SESSION` | Rate limit per session/hour | `20` |
| `MAX_SESSIONS_PER_IP` | Max sessions per IP/day | `5` |
| `MAX_TOKENS_PER_SESSION` | Total tokens per session | `10000` |
| `SESSION_EXPIRY_HOURS` | Session lifetime | `24` |

**Frontend:**

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_API_URL` | API Gateway endpoint |

### Terraform Variables

See `terraform/variables.tf` for customization:

```hcl
variable "project_name" {
  default = "twin"
}

variable "environment" {
  default = "dev"
}

variable "bedrock_model_id" {
  default = "amazon.nova-micro-v1:0"
}

variable "lambda_timeout" {
  default = 60
}

variable "use_custom_domain" {
  default = false
}
```

---

## 🔒 Security Features

### Built-in Protections

- ✅ **Rate Limiting**: 20 requests/hour per session, 5 sessions/day per IP
- ✅ **Token Limits**: 10,000 tokens per session to prevent abuse
- ✅ **Session Expiry**: 24-hour automatic session termination
- ✅ **Jailbreak Detection**: Pattern-based prompt injection prevention
- ✅ **Input Validation**: Pydantic models with length/format constraints
- ✅ **CORS Restrictions**: Locked to CloudFront domain
- ✅ **IAM Least Privilege**: Scoped permissions for Lambda execution
- ✅ **Content Security**: Personal data in private S3, never in code
- ✅ **Secrets Management**: No credentials in codebase or environment variables
- ✅ **HTTPS Only**: TLS 1.2+ enforcement via CloudFront

### IAM Permissions

Lambda has restricted access to:
- Read-only access to specific S3 buckets (resume + memory)
- Bedrock invocation for specified model
- CloudWatch Logs write access

See `terraform/main.tf` for complete IAM policy.

---

## 💰 Cost Optimization

**Estimated Monthly Costs** (Moderate Usage):

| Service | Usage | Cost |
|---------|-------|------|
| Lambda | 100K invocations, 512MB, 3s avg | ~$0.50 |
| API Gateway | 100K requests | ~$0.10 |
| Bedrock Nova Micro | ~1M tokens | ~$0.75 |
| S3 Storage | 1GB | ~$0.02 |
| CloudFront | 10GB transfer | ~$0.85 |
| **Total** | | **~$2-5/month** |

**AWS Free Tier Eligible** (First 12 months):
- Lambda: 1M free requests
- API Gateway: 1M free requests  
- CloudFront: 1TB free data transfer

**Cost Optimization Features:**
- Serverless architecture (pay per use)
- CloudFront caching reduces origin requests
- Efficient token management
- Automatic session cleanup

---

## 📂 Project Structure

```
prochatbot/
├── backend/
│   ├── server.py              # FastAPI application
│   ├── lambda_handler.py      # Lambda entry point
│   ├── context.py             # Context management
│   ├── resources.py           # Resource definitions
│   ├── deploy.py              # Deployment packaging script
│   ├── requirements.txt       # Python dependencies
│   └── data/                  # Local development data
│       └── facts.json         # Professional metadata (tracked)
├── frontend/
│   ├── app/                   # Next.js app directory
│   ├── components/
│   │   └── twin.tsx           # Chat component
│   ├── public/                # Static assets
│   └── package.json           # Node dependencies
├── terraform/
│   ├── main.tf                # Core infrastructure
│   ├── variables.tf           # Input variables
│   ├── outputs.tf             # Output values
│   ├── backend.tf             # Terraform state config
│   └── provider.tf            # AWS provider config
├── .github/
│   └── workflows/
│       └── deploy.yml         # CI/CD pipeline
├── scripts/
│   └── deploy.sh              # Deployment automation
├── .gitignore                 # Git exclusions
├── README.md                  # This file
├── LICENSE                    # MIT License
└── SECURITY.md                # Security policy
```

---

## 🛠️ Development

### Local Development

**Backend:**

```bash
cd backend

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export USE_S3=false
export S3_RESUME_BUCKET=your-bucket
export BEDROCK_MODEL_ID=amazon.nova-micro-v1:0

# Run locally
uvicorn server:app --reload --port 8000
```

**Frontend:**

```bash
cd frontend

# Install dependencies
npm install

# Set API URL
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local

# Run development server
npm run dev
```

Visit `http://localhost:3000` to test locally.

### Testing

```bash
# Test health endpoint
curl http://localhost:8000/health

# Expected response:
# {
#   "status": "healthy",
#   "environment": "development",
#   "bedrock_model": "amazon.nova-micro-v1:0",
#   "documents_loaded": 3,
#   "resume_source": "local filesystem"
# }

# Test chat endpoint
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is your experience with AWS?"}'
```

---

## 📈 Monitoring

### CloudWatch Metrics

Monitor via AWS Console or CLI:

```bash
# Lambda invocations
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --dimensions Name=FunctionName,Value=twin-dev-api \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 3600 \
  --statistics Sum

# API Gateway requests
aws cloudwatch get-metric-statistics \
  --namespace AWS/ApiGateway \
  --metric-name Count \
  --dimensions Name=ApiId,Value=YOUR_API_ID \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 3600 \
  --statistics Sum
```

### Logs

```bash
# View Lambda logs
aws logs tail /aws/lambda/twin-dev-api --follow

# View specific log stream
aws logs get-log-events \
  --log-group-name /aws/lambda/twin-dev-api \
  --log-stream-name 2024/01/01/[$LATEST]abcdef123456
```

---

## 🔧 Troubleshooting

### Common Issues

**1. Lambda timeout errors**
- Increase `lambda_timeout` in `terraform/variables.tf`
- Optimize document chunking in `server.py`

**2. Rate limit exceeded**
- Adjust `MAX_REQUESTS_PER_SESSION` environment variable
- Clear session storage to reset

**3. CORS errors**
- Verify `CORS_ORIGINS` matches CloudFront domain
- Check API Gateway CORS configuration

**4. Bedrock access denied**
- Ensure Bedrock model access enabled in AWS Console
- Verify IAM policy includes `bedrock:InvokeModel`

**5. S3 file not found**
- Confirm `S3_RESUME_BUCKET` environment variable is correct
- Verify files uploaded to correct bucket
- Check IAM permissions for S3 read access

**6. CloudFront not serving latest content**
- Invalidate CloudFront cache: `aws cloudfront create-invalidation --distribution-id YOUR_ID --paths "/*"`
- Wait 5-10 minutes for invalidation to complete

---

## 🗺️ Roadmap

### Version 1.0 ✅ (Current)
- [x] Serverless architecture with AWS Bedrock
- [x] CI/CD pipeline with GitHub Actions
- [x] Enterprise security controls
- [x] Session management
- [x] S3-based document storage
- [x] CloudFront CDN distribution

### Version 2.0 🚧 (Planned)
- [ ] RAG with vector database (pgvector)
- [ ] Semantic search across documents
- [ ] Citation-backed responses
- [ ] Multi-model support (Bedrock/GPT/Claude)

---

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

Please ensure:
- Code follows existing style conventions
- Security best practices are maintained
- Documentation is updated
- No personal data or credentials included

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

**Educational Foundation:**
- **Ed Donner's - AI in Production Course (Udemy)** Digital Twin Project

**Technology & Services:**
- **AWS Bedrock** - AI model hosting and inference
- **Terraform** - Infrastructure as Code automation
- **FastAPI** - Modern Python web framework
- **Next.js** - React framework for production applications

---

## 📧 Contact & Connect

**Project Maintainer:** Mazhar Islam  
**GitHub:** [@mazharislam](https://github.com/mazharislam)  
**LinkedIn:** [linkedin.com/in/mazhar-islam](https://www.linkedin.com/in/mazhar-islam)

### 🤝 Let's Connect!

If you found this project interesting or useful:

- 💼 **[Connect with me on LinkedIn](https://www.linkedin.com/in/mazhar-islam)** - Let's discuss cloud architecture, AI, and cybersecurity!
- 💬 **[Comment on my LinkedIn post](https://www.linkedin.com/feed/update/urn:li:activity:YOUR_POST_ID)** - Share your thoughts, questions, or feedback about this project
- ⭐ **Star this repository** - It helps others discover the project
- 🔄 **Share with your network** - Help spread knowledge about serverless AI architectures

I'm always interested in discussing:
- Cloud architecture and serverless design patterns
- AI/ML integration in production systems
- Cybersecurity and Zero Trust architectures
- DevOps automation and Infrastructure as Code
- Cost optimization strategies for AWS

---

## ⚠️ Disclaimer

This is a portfolio/demonstration project showcasing cloud architecture, AI integration, and security best practices. While it implements security controls, please review and customize security measures for your specific production requirements.

---

**⭐ If you find this project useful, please consider giving it a star!**
