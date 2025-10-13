import os
import json
import uuid
import logging
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

# CORS Configuration
origins = os.getenv("CORS_ORIGINS", "*").split(",")
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

# Initialize AWS clients
bedrock_client = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"))
s3_client = boto3.client("s3") if USE_S3 else None

# In-memory rate limiting (resets on Lambda cold start)
session_rate_limits = {}  # {session_id: [timestamps]}
ip_session_tracker = {}   # {ip: [session_ids]}

# System prompt with your resume
SYSTEM_PROMPT = """You are an AI assistant representing a professional based on their resume/profile. 
Answer questions about their experience, skills, projects, and background in a helpful and professional manner.
Keep responses concise and relevant. If asked about something not in the resume, politely say you don't have that information."""


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
    # CloudFront/API Gateway adds X-Forwarded-For header
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        # Get first IP in chain (real client IP)
        return forwarded_for.split(",")[0].strip()
    return request.client.host


def check_session_rate_limit(session_id: str) -> bool:
    """Limit requests per session (20 per hour)"""
    now = datetime.now()
    window_start = now - timedelta(hours=1)
    
    # Clean old entries
    if session_id in session_rate_limits:
        session_rate_limits[session_id] = [
            req_time for req_time in session_rate_limits[session_id]
            if req_time > window_start
        ]
    else:
        session_rate_limits[session_id] = []
    
    # Check limit
    if len(session_rate_limits[session_id]) >= MAX_REQUESTS_PER_SESSION:
        logger.warning(f"Rate limit exceeded for session {session_id}")
        return False
    
    # Track this request
    session_rate_limits[session_id].append(now)
    return True


def check_ip_session_limit(ip_address: str, session_id: str) -> bool:
    """Limit number of sessions per IP (5 per day)"""
    now = datetime.now()
    window_start = now - timedelta(days=1)
    
    # Initialize or clean old sessions
    if ip_address not in ip_session_tracker:
        ip_session_tracker[ip_address] = []
    
    # Add current session if new
    if session_id not in ip_session_tracker[ip_address]:
        # Check if at limit
        if len(ip_session_tracker[ip_address]) >= MAX_SESSIONS_PER_IP:
            logger.warning(f"IP session limit exceeded for {ip_address}")
            return False
        
        # Add new session
        ip_session_tracker[ip_address].append(session_id)
    
    return True


# ============================================================================
# PYDANTIC MODELS WITH VALIDATION
# ============================================================================

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = Field(None, max_length=36)
    
    @validator('message')
    def validate_message(cls, v):
        # Remove excessive whitespace
        v = ' '.join(v.split())
        
        # Check for empty
        if len(v.strip()) < 1:
            raise ValueError('Message cannot be empty')
        
        # Check for repetitive characters (spam detection)
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
            # Local storage fallback
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
        # Limit stored messages to prevent abuse
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
            # Local storage fallback
            memory_dir = Path("memory")
            memory_dir.mkdir(exist_ok=True)
            memory_file = memory_dir / f"{session_id}.json"
            memory_file.write_text(conversation_data)
            
        logger.info(f"Saved conversation for session {session_id}")
    except Exception as e:
        logger.error(f"Error saving conversation: {e}")


# ============================================================================
# BEDROCK INTEGRATION
# ============================================================================

def load_resume_content() -> str:
    """Load resume content from PDF or fallback text"""
    try:
        from pypdf import PdfReader
        resume_path = Path("resume.pdf")
        
        if resume_path.exists():
            reader = PdfReader(str(resume_path))
            text = "\n".join(page.extract_text() for page in reader.pages)
            logger.info("Loaded resume from PDF")
            return text
    except Exception as e:
        logger.warning(f"Could not load PDF resume: {e}")
    
    # Fallback to placeholder
    return """Professional with experience in software development, cloud architecture, and AI/ML.
Skills include Python, AWS, Terraform, and modern DevOps practices."""


def call_bedrock(conversation: List[Dict], user_message: str) -> str:
    """Call AWS Bedrock with conversation history"""
    try:
        # Load resume content
        resume_content = load_resume_content()
        
        # Build system message
        system_message = f"{SYSTEM_PROMPT}\n\nResume/Profile Content:\n{resume_content}"
        
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
        
        return response["output"]["message"]["content"][0]["text"]
        
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
        "version": "1.0",
        "endpoints": {
            "health": "/health",
            "chat": "/chat"
        }
    }


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        environment=os.getenv("ENVIRONMENT", "development"),
        bedrock_model=BEDROCK_MODEL_ID
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, req: Request):
    """Main chat endpoint with security controls"""
    session_id = request.session_id or str(uuid.uuid4())
    client_ip = get_client_ip(req)
    
    try:
        # Security Check 1: Detect jailbreak attempts
        if detect_jailbreak_attempt(request.message):
            logger.warning(f"Jailbreak attempt detected from IP {client_ip}, session {session_id}")
            raise HTTPException(
                status_code=400,
                detail="Invalid request detected"
            )
        
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
        
        # Log request
        logger.info(json.dumps({
            "event": "chat_request",
            "session_id": session_id,
            "ip": client_ip,
            "message_length": len(request.message),
            "timestamp": datetime.now().isoformat()
        }))
        
        # Load conversation history
        conversation = load_conversation(session_id)
        
        # Get AI response
        assistant_response = call_bedrock(conversation, request.message)
        
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
        
        # Log response
        logger.info(json.dumps({
            "event": "chat_response",
            "session_id": session_id,
            "response_length": len(assistant_response),
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