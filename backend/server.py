import os
import json
import uuid
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, validator, Field
from mangum import Mangum
import boto3
from botocore.exceptions import ClientError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(title="Professional Profile Chatbot API")

# CORS Configuration - Restrict to CloudFront domain
CLOUDFRONT_DOMAIN = os.getenv("CLOUDFRONT_DOMAIN", "*")
if CLOUDFRONT_DOMAIN and CLOUDFRONT_DOMAIN != "*":
    origins = [f"https://{CLOUDFRONT_DOMAIN}"]
else:
    # Fallback to wildcard for local development
    origins = ["*"]
    logger.warning("CORS set to wildcard - should set CLOUDFRONT_DOMAIN env var in production")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    max_age=3600,
)

# AWS Configuration
USE_S3 = os.getenv("USE_S3", "true").lower() == "true"
S3_BUCKET = os.getenv("S3_MEMORY_BUCKET", "")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
MAX_TOKENS_PER_REQUEST = int(os.getenv("MAX_TOKENS_PER_REQUEST", "1000"))
MAX_REQUESTS_PER_SESSION = int(os.getenv("MAX_REQUESTS_PER_SESSION", "20"))
MAX_SESSIONS_PER_IP = int(os.getenv("MAX_SESSIONS_PER_IP", "5"))
MAX_TOKENS_PER_SESSION = int(os.getenv("MAX_TOKENS_PER_SESSION", "10000"))
SESSION_EXPIRY_HOURS = int(os.getenv("SESSION_EXPIRY_HOURS", "24"))

# Resume files directory - UPDATE THIS PATH
RESUME_DATA_DIR = Path("backup") / "data"

# Initialize AWS clients
bedrock_client = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"))
s3_client = boto3.client("s3") if USE_S3 else None

# In-memory rate limiting and token tracking
session_rate_limits = {}  # {session_id: [timestamps]}
ip_session_tracker = {}   # {ip: [session_ids]}
session_token_usage = {}  # {session_id: total_tokens}

# System prompt
SYSTEM_PROMPT = """You are an AI assistant representing a professional based on their resume/profile documents. 
Answer questions about their experience, skills, projects, and background in a helpful and professional manner.
Keep responses concise and relevant. If asked about something not in the provided documents, politely say you don't have that information."""


# ============================================================================
# MULTI-RESUME LOADING
# ============================================================================

def load_pdf_content(file_path: Path) -> Optional[str]:
    """Load content from a single PDF file"""
    try:
        from pypdf import PdfReader
        if file_path.exists():
            reader = PdfReader(str(file_path))
            text = "\n".join(page.extract_text() for page in reader.pages)
            logger.info(f"Loaded {file_path.name}: {len(text)} characters")
            return text
    except Exception as e:
        logger.warning(f"Could not load {file_path.name}: {e}")
    return None


def load_resume_content() -> str:
    """Load content from multiple resume/profile documents"""
    content_sections = []
    
    # Define all possible resume files to check
    resume_files = {
        "linkedin.pdf": "LinkedIn Profile",
        "aboutme.pdf": "About Me / Personal Statement",
        "resume1.pdf": "Resume - Version 1",
        "resume2.pdf": "Resume - Version 2",
        "resume3.pdf": "Resume - Version 3",
        "resume4.pdf": "Resume - Version 4",
        "resume5.pdf": "Resume - Version 5",
    }
    
    files_loaded = 0
    
    # Try to load each file from the backup/data directory
    for filename, description in resume_files.items():
        file_path = RESUME_DATA_DIR / filename
        content = load_pdf_content(file_path)
        
        if content:
            content_sections.append(f"=== {description} ===\n{content}\n")
            files_loaded += 1
    
    # If no files loaded, use fallback
    if files_loaded == 0:
        logger.warning(f"No resume PDFs found in {RESUME_DATA_DIR} - using fallback content")
        return """Professional with experience in software development, cloud architecture, and AI/ML.
Skills include Python, AWS, Terraform, and modern DevOps practices."""
    
    logger.info(f"Successfully loaded {files_loaded} resume document(s) from {RESUME_DATA_DIR}")
    return "\n\n".join(content_sections)


# ============================================================================
# SECURITY FUNCTIONS
# ============================================================================

def detect_jailbreak_attempt(message: str) -> bool:
    """Detect common jailbreak/prompt injection patterns"""
    jailbreak_patterns = [
        "ignore previous instructions",
        "ignore all previous",
        "disregard previous",
        "forget everything",
        "new instructions",
        "you are now",
        "act as if",
        "pretend you are",
        "system:",
        "override",
        "sudo mode",
        "admin mode",
        "developer mode",
        "god mode"
    ]
    
    message_lower = message.lower()
    return any(pattern in message_lower for pattern in jailbreak_patterns)


def get_client_ip(request: Request) -> str:
    """Extract real client IP from request headers"""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host


def check_session_rate_limit(session_id: str) -> bool:
    """Limit requests per session (20 per hour)"""
    now = datetime.now()
    window_start = now - timedelta(hours=1)
    
    if session_id in session_rate_limits:
        session_rate_limits[session_id] = [
            req_time for req_time in session_rate_limits[session_id]
            if req_time > window_start
        ]
    else:
        session_rate_limits[session_id] = []
    
    if len(session_rate_limits[session_id]) >= MAX_REQUESTS_PER_SESSION:
        logger.warning(f"Rate limit exceeded for session {session_id}")
        return False
    
    session_rate_limits[session_id].append(now)
    return True


def check_ip_session_limit(ip_address: str, session_id: str) -> bool:
    """Limit number of sessions per IP (5 per day)"""
    if ip_address not in ip_session_tracker:
        ip_session_tracker[ip_address] = []
    
    if session_id not in ip_session_tracker[ip_address]:
        if len(ip_session_tracker[ip_address]) >= MAX_SESSIONS_PER_IP:
            logger.warning(f"IP session limit exceeded for {ip_address}")
            return False
        ip_session_tracker[ip_address].append(session_id)
    
    return True


def check_token_limit(session_id: str, tokens_to_add: int = 0) -> bool:
    """Track and limit token usage per session"""
    if session_id not in session_token_usage:
        session_token_usage[session_id] = 0
    
    session_token_usage[session_id] += tokens_to_add
    
    if session_token_usage[session_id] > MAX_TOKENS_PER_SESSION:
        logger.warning(f"Token limit exceeded for session {session_id}: {session_token_usage[session_id]} tokens")
        return False
    
    return True


def check_session_age(conversation: List[Dict]) -> bool:
    """Check if session has expired (older than SESSION_EXPIRY_HOURS)"""
    if not conversation:
        return True
    
    try:
        first_message = conversation[0]
        first_timestamp = datetime.fromisoformat(first_message.get("timestamp", ""))
        age = datetime.now() - first_timestamp
        
        if age > timedelta(hours=SESSION_EXPIRY_HOURS):
            logger.info(f"Session expired - age: {age.total_seconds()/3600:.1f} hours")
            return False
    except (ValueError, KeyError):
        # If timestamp parsing fails, allow the session
        pass
    
    return True


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = Field(None, max_length=36)
    
    @validator('message')
    def validate_message(cls, v):
        v = ' '.join(v.split())
        if len(v.strip()) < 1:
            raise ValueError('Message cannot be empty')
        if len(set(v)) < 5 and len(v) > 20:
            raise ValueError('Invalid message format')
        return v.strip()
    
    @validator('session_id')
    def validate_session_id(cls, v):
        if v is not None:
            try:
                uuid.UUID(v)
            except ValueError:
                raise ValueError('Invalid session ID format')
        return v


class ChatResponse(BaseModel):
    response: str
    session_id: str


class HealthResponse(BaseModel):
    status: str
    environment: str
    bedrock_model: str
    documents_loaded: int


# ============================================================================
# MEMORY MANAGEMENT
# ============================================================================

def get_memory_path(session_id: str) -> str:
    """Get S3 key or local path for conversation memory"""
    return f"conversations/{session_id}.json"


def load_conversation(session_id: str) -> List[Dict]:
    """Load conversation history from S3 or local storage"""
    try:
        if USE_S3 and s3_client:
            response = s3_client.get_object(
                Bucket=S3_BUCKET,
                Key=get_memory_path(session_id)
            )
            return json.loads(response["Body"].read())
        else:
            memory_dir = Path("memory")
            memory_dir.mkdir(exist_ok=True)
            memory_file = memory_dir / f"{session_id}.json"
            
            if memory_file.exists():
                return json.loads(memory_file.read_text())
    except Exception as e:
        logger.info(f"No existing conversation for session {session_id}: {e}")
    
    return []


def save_conversation(session_id: str, messages: List[Dict]):
    """Save conversation history to S3 or local storage"""
    try:
        MAX_STORED_MESSAGES = 100
        if len(messages) > MAX_STORED_MESSAGES:
            messages = messages[-MAX_STORED_MESSAGES:]
        
        conversation_data = json.dumps(messages, indent=2)
        
        if USE_S3 and s3_client:
            s3_client.put_object(
                Bucket=S3_BUCKET,
                Key=get_memory_path(session_id),
                Body=conversation_data,
                ContentType="application/json"
            )
        else:
            memory_dir = Path("memory")
            memory_dir.mkdir(exist_ok=True)
            memory_file = memory_dir / f"{session_id}.json"
            memory_file.write_text(conversation_data)
            
        logger.info(f"Saved conversation for session {session_id}")
    except Exception as e:
        logger.error(f"Error saving conversation: {e}")


def delete_conversation(session_id: str):
    """Delete expired conversation"""
    try:
        if USE_S3 and s3_client:
            s3_client.delete_object(
                Bucket=S3_BUCKET,
                Key=get_memory_path(session_id)
            )
        else:
            memory_dir = Path("memory")
            memory_file = memory_dir / f"{session_id}.json"
            if memory_file.exists():
                memory_file.unlink()
        
        logger.info(f"Deleted expired conversation for session {session_id}")
    except Exception as e:
        logger.error(f"Error deleting conversation: {e}")


# ============================================================================
# BEDROCK INTEGRATION
# ============================================================================

def call_bedrock(conversation: List[Dict], user_message: str) -> tuple[str, int]:
    """Call AWS Bedrock with conversation history - returns (response, estimated_tokens)"""
    try:
        # Load resume content
        resume_content = load_resume_content()
        
        # Build system message
        system_message = f"{SYSTEM_PROMPT}\n\nProfessional Documents:\n{resume_content}"
        
        # Build conversation history (last 20 messages = 10 exchanges)
        messages = []
        for msg in conversation[-20:]:
            messages.append({
                "role": msg["role"],
                "content": [{"text": msg["content"]}]
            })
        
        # Add current user message
        messages.append({
            "role": "user",
            "content": [{"text": user_message}]
        })
        
        # Call Bedrock
        response = bedrock_client.converse(
            modelId=BEDROCK_MODEL_ID,
            messages=messages,
            system=[{"text": system_message}],
            inferenceConfig={
                "maxTokens": MAX_TOKENS_PER_REQUEST,
                "temperature": 0.7,
                "topP": 0.9
            }
        )
        
        response_text = response["output"]["message"]["content"][0]["text"]
        
        # Estimate tokens (rough approximation: 1 token ≈ 4 characters)
        estimated_tokens = (len(user_message) + len(response_text)) // 4
        
        return response_text, estimated_tokens
        
    except ClientError as e:
        logger.error(f"Bedrock API error: {e}")
        raise HTTPException(status_code=500, detail="AI service error")
    except Exception as e:
        logger.error(f"Unexpected error calling Bedrock: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/", response_model=dict)
async def root():
    """Root endpoint"""
    return {
        "message": "Professional Profile Chatbot API",
        "version": "1.1",
        "features": ["multi-resume", "rate-limiting", "token-limits", "session-expiry"],
        "endpoints": {
            "health": "/health",
            "chat": "/chat"
        }
    }


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint"""
    # Count loaded documents from backup/data directory
    docs_count = 0
    for filename in ["linkedin.pdf", "aboutme.pdf", "resume1.pdf", "resume2.pdf", "resume3.pdf", "resume4.pdf", "resume5.pdf"]:
        if (RESUME_DATA_DIR / filename).exists():
            docs_count += 1
    
    return HealthResponse(
        status="healthy",
        environment=os.getenv("ENVIRONMENT", "development"),
        bedrock_model=BEDROCK_MODEL_ID,
        documents_loaded=docs_count
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, req: Request):
    """Main chat endpoint with comprehensive security controls"""
    session_id = request.session_id or str(uuid.uuid4())
    client_ip = get_client_ip(req)
    start_time = time.time()
    
    try:
        # Security Check 1: Detect jailbreak attempts
        if detect_jailbreak_attempt(request.message):
            logger.warning(f"Jailbreak attempt detected from IP {client_ip}, session {session_id}")
            raise HTTPException(status_code=400, detail="Invalid request detected")
        
        # Security Check 2: Session rate limiting
        if not check_session_rate_limit(session_id):
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Maximum {MAX_REQUESTS_PER_SESSION} requests per hour."
            )
        
        # Security Check 3: IP session limiting
        if not check_ip_session_limit(client_ip, session_id):
            raise HTTPException(
                status_code=429,
                detail=f"Too many sessions from your IP. Maximum {MAX_SESSIONS_PER_IP} sessions per day."
            )
        
        # Load conversation history
        conversation = load_conversation(session_id)
        
        # Security Check 4: Session age expiry
        if conversation and not check_session_age(conversation):
            logger.info(f"Session {session_id} expired - starting fresh")
            delete_conversation(session_id)
            conversation = []
        
        # Security Check 5: Token limit check
        if not check_token_limit(session_id):
            raise HTTPException(
                status_code=429,
                detail=f"Session token limit exceeded. Maximum {MAX_TOKENS_PER_SESSION} tokens per session."
            )
        
        # Log request with enhanced metrics
        logger.info(json.dumps({
            "event": "chat_request",
            "session_id": session_id,
            "ip": client_ip,
            "message_length": len(request.message),
            "conversation_length": len(conversation),
            "timestamp": datetime.now().isoformat()
        }))
        
        # Get AI response with token count
        assistant_response, tokens_used = call_bedrock(conversation, request.message)
        
        # Update token usage
        check_token_limit(session_id, tokens_used)
        
        # Calculate response time
        response_time = time.time() - start_time
        
        # Update conversation history
        conversation.append({
            "role": "user",
            "content": request.message,
            "timestamp": datetime.now().isoformat()
        })
        conversation.append({
            "role": "assistant",
            "content": assistant_response,
            "timestamp": datetime.now().isoformat()
        })
        
        # Save updated conversation
        save_conversation(session_id, conversation)
        
        # Log response with metrics
        logger.info(json.dumps({
            "event": "chat_response",
            "session_id": session_id,
            "response_length": len(assistant_response),
            "tokens_used": tokens_used,
            "total_session_tokens": session_token_usage.get(session_id, 0),
            "response_time_ms": int(response_time * 1000),
            "timestamp": datetime.now().isoformat()
        }))
        
        return ChatResponse(
            response=assistant_response,
            session_id=session_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing chat request: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# Lambda handler
handler = Mangum(app, lifespan="off")