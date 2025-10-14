import os
import json
import uuid
import logging
import time
import io
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
CLOUDFRONT_DOMAIN = os.getenv("CLOUDFRONT_DOMAIN", "*")
if CLOUDFRONT_DOMAIN and CLOUDFRONT_DOMAIN != "*":
    origins = [f"https://{CLOUDFRONT_DOMAIN}"]
else:
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
S3_MEMORY_BUCKET = os.getenv("S3_MEMORY_BUCKET", "")
S3_RESUME_BUCKET = os.getenv("S3_RESUME_BUCKET", "")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
MAX_TOKENS_PER_REQUEST = int(os.getenv("MAX_TOKENS_PER_REQUEST", "1000"))
MAX_REQUESTS_PER_SESSION = int(os.getenv("MAX_REQUESTS_PER_SESSION", "20"))
MAX_SESSIONS_PER_IP = int(os.getenv("MAX_SESSIONS_PER_IP", "5"))
MAX_TOKENS_PER_SESSION = int(os.getenv("MAX_TOKENS_PER_SESSION", "10000"))
SESSION_EXPIRY_HOURS = int(os.getenv("SESSION_EXPIRY_HOURS", "24"))

# Local fallback path for development
LOCAL_RESUME_DIR = Path("data")

# Initialize AWS clients
bedrock_client = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"))
s3_client = boto3.client("s3") if USE_S3 else None

# In-memory rate limiting and token tracking
session_rate_limits = {}
ip_session_tracker = {}
session_token_usage = {}

# Generic system prompt - personal content loaded dynamically from files
SYSTEM_PROMPT_BASE = """You are a Digital Twin chatbot representing a professional based on their profile documents.

Your communication style and professional identity will be loaded from the provided context files.
Answer questions authentically based on the documents provided, maintaining the specified tone and approach.
If information is not in the documents, acknowledge this honestly."""


# ============================================================================
# CONTENT LOADING FUNCTIONS
# ============================================================================

def load_text_file_from_s3(bucket: str, key: str) -> Optional[str]:
    """Load text file content from S3"""
    try:
        if not s3_client or not bucket:
            return None
            
        response = s3_client.get_object(Bucket=bucket, Key=key)
        text = response['Body'].read().decode('utf-8')
        logger.info(f"Loaded {key} from S3: {len(text)} characters")
        return text
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            logger.info(f"File not found in S3: {key}")
        else:
            logger.warning(f"Could not load {key} from S3: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error loading {key} from S3: {e}")
        return None


def load_text_file_from_local(file_path: Path) -> Optional[str]:
    """Load text file content from local filesystem"""
    try:
        if file_path.exists():
            text = file_path.read_text(encoding='utf-8')
            logger.info(f"Loaded {file_path.name} locally: {len(text)} characters")
            return text
    except Exception as e:
        logger.warning(f"Could not load {file_path.name} locally: {e}")
    return None


def load_pdf_from_s3(bucket: str, key: str) -> Optional[str]:
    """Load PDF content from S3"""
    try:
        if not s3_client or not bucket:
            return None
            
        response = s3_client.get_object(Bucket=bucket, Key=key)
        pdf_bytes = response['Body'].read()
        
        from pypdf import PdfReader
        pdf_file = io.BytesIO(pdf_bytes)
        reader = PdfReader(pdf_file)
        text = "\n".join(page.extract_text() for page in reader.pages)
        
        logger.info(f"Loaded {key} from S3: {len(text)} characters")
        return text
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            logger.info(f"File not found in S3: {key}")
        else:
            logger.warning(f"Could not load {key} from S3: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error loading {key} from S3: {e}")
        return None


def load_pdf_from_local(file_path: Path) -> Optional[str]:
    """Load PDF content from local filesystem"""
    try:
        from pypdf import PdfReader
        if file_path.exists():
            reader = PdfReader(str(file_path))
            text = "\n".join(page.extract_text() for page in reader.pages)
            logger.info(f"Loaded {file_path.name} locally: {len(text)} characters")
            return text
    except Exception as e:
        logger.warning(f"Could not load {file_path.name} locally: {e}")
    return None


def load_resume_content() -> str:
    """Load all profile content: style, summary, facts, and PDFs (S3 first, local fallback)"""
    content_sections = []
    
    # Load style.txt (communication style)
    try:
        style_content = None
        if S3_RESUME_BUCKET and s3_client:
            style_content = load_text_file_from_s3(S3_RESUME_BUCKET, "style.txt")
        if not style_content and LOCAL_RESUME_DIR.exists():
            style_content = load_text_file_from_local(LOCAL_RESUME_DIR / "style.txt")
        if style_content:
            content_sections.append(f"=== Communication Style ===\n{style_content}\n")
    except Exception as e:
        logger.warning(f"Could not load style.txt: {e}")
    
    # Load summary.txt (professional identity)
    try:
        summary_content = None
        if S3_RESUME_BUCKET and s3_client:
            summary_content = load_text_file_from_s3(S3_RESUME_BUCKET, "summary.txt")
        if not summary_content and LOCAL_RESUME_DIR.exists():
            summary_content = load_text_file_from_local(LOCAL_RESUME_DIR / "summary.txt")
        if summary_content:
            content_sections.append(f"=== Professional Identity ===\n{summary_content}\n")
    except Exception as e:
        logger.warning(f"Could not load summary.txt: {e}")
    
    # Load facts.json (structured data)
    try:
        facts_content = None
        if S3_RESUME_BUCKET and s3_client:
            try:
                response = s3_client.get_object(Bucket=S3_RESUME_BUCKET, Key="facts.json")
                facts_content = json.loads(response['Body'].read())
                logger.info("Loaded facts.json from S3")
            except ClientError:
                pass
        if not facts_content and LOCAL_RESUME_DIR.exists():
            facts_path = LOCAL_RESUME_DIR / "facts.json"
            if facts_path.exists():
                facts_content = json.loads(facts_path.read_text())
                logger.info("Loaded facts.json locally")
        if facts_content:
            content_sections.append(f"=== Professional Profile ===\n{json.dumps(facts_content, indent=2)}\n")
    except Exception as e:
        logger.warning(f"Could not load facts.json: {e}")
    
    # Load resume PDFs
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
    for filename, description in resume_files.items():
        content = None
        if S3_RESUME_BUCKET and s3_client:
            content = load_pdf_from_s3(S3_RESUME_BUCKET, filename)
        if not content and LOCAL_RESUME_DIR.exists():
            content = load_pdf_from_local(LOCAL_RESUME_DIR / filename)
        if content:
            content_sections.append(f"=== {description} ===\n{content}\n")
            files_loaded += 1
    
    if len(content_sections) == 0:
        logger.warning("No profile content found - using fallback")
        return "Professional with experience in technology and cybersecurity."
    
    source = "S3" if S3_RESUME_BUCKET and s3_client else "local filesystem"
    logger.info(f"Loaded {len(content_sections)} sections from {source}")
    return "\n\n".join(content_sections)


# ============================================================================
# SECURITY FUNCTIONS
# ============================================================================

def detect_jailbreak_attempt(message: str) -> bool:
    """Detect common jailbreak/prompt injection patterns"""
    jailbreak_patterns = [
        "ignore previous instructions", "ignore all previous", "disregard previous",
        "forget everything", "new instructions", "you are now", "act as if",
        "pretend you are", "system:", "override", "sudo mode", "admin mode",
        "developer mode", "god mode"
    ]
    return any(pattern in message.lower() for pattern in jailbreak_patterns)


def get_client_ip(request: Request) -> str:
    """Extract real client IP from request headers"""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host


def check_session_rate_limit(session_id: str) -> bool:
    """Limit requests per session"""
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
    """Limit number of sessions per IP"""
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
        logger.warning(f"Token limit exceeded for session {session_id}")
        return False
    
    return True


def check_session_age(conversation: List[Dict]) -> bool:
    """Check if session has expired"""
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
    resume_source: str


# ============================================================================
# MEMORY MANAGEMENT
# ============================================================================

def get_memory_path(session_id: str) -> str:
    """Get S3 key or local path for conversation memory"""
    return f"conversations/{session_id}.json"


def load_conversation(session_id: str) -> List[Dict]:
    """Load conversation history from S3 or local storage"""
    try:
        if USE_S3 and s3_client and S3_MEMORY_BUCKET:
            response = s3_client.get_object(
                Bucket=S3_MEMORY_BUCKET,
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
        
        if USE_S3 and s3_client and S3_MEMORY_BUCKET:
            s3_client.put_object(
                Bucket=S3_MEMORY_BUCKET,
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
        if USE_S3 and s3_client and S3_MEMORY_BUCKET:
            s3_client.delete_object(
                Bucket=S3_MEMORY_BUCKET,
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
    """Call AWS Bedrock with conversation history"""
    try:
        resume_content = load_resume_content()
        system_message = f"{SYSTEM_PROMPT_BASE}\n\nContext Documents:\n{resume_content}"
        
        messages = []
        for msg in conversation[-20:]:
            messages.append({
                "role": msg["role"],
                "content": [{"text": msg["content"]}]
            })
        
        messages.append({
            "role": "user",
            "content": [{"text": user_message}]
        })
        
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
        "version": "2.0",
        "features": ["s3-resume-storage", "multi-resume", "rate-limiting", "token-limits"],
        "endpoints": {"health": "/health", "chat": "/chat"}
    }


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint"""
    docs_count = 0
    resume_source = "unknown"
    
    resume_files = ["linkedin.pdf", "aboutme.pdf", "resume1.pdf", "resume2.pdf", 
                    "resume3.pdf", "resume4.pdf", "resume5.pdf"]
    
    if S3_RESUME_BUCKET and s3_client:
        try:
            for filename in resume_files:
                try:
                    s3_client.head_object(Bucket=S3_RESUME_BUCKET, Key=filename)
                    docs_count += 1
                except ClientError:
                    pass
            resume_source = f"S3 ({S3_RESUME_BUCKET})"
        except Exception as e:
            logger.warning(f"Could not check S3: {e}")
    
    if docs_count == 0 and LOCAL_RESUME_DIR.exists():
        for filename in resume_files:
            if (LOCAL_RESUME_DIR / filename).exists():
                docs_count += 1
        resume_source = "local filesystem"
    
    return HealthResponse(
        status="healthy",
        environment=os.getenv("ENVIRONMENT", "development"),
        bedrock_model=BEDROCK_MODEL_ID,
        documents_loaded=docs_count,
        resume_source=resume_source
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, req: Request):
    """Main chat endpoint with security controls"""
    session_id = request.session_id or str(uuid.uuid4())
    client_ip = get_client_ip(req)
    start_time = time.time()
    
    try:
        if detect_jailbreak_attempt(request.message):
            logger.warning(f"Jailbreak attempt from IP {client_ip}, session {session_id}")
            raise HTTPException(status_code=400, detail="Invalid request detected")
        
        if not check_session_rate_limit(session_id):
            raise HTTPException(status_code=429, detail=f"Rate limit exceeded. Max {MAX_REQUESTS_PER_SESSION} requests/hour.")
        
        if not check_ip_session_limit(client_ip, session_id):
            raise HTTPException(status_code=429, detail=f"Too many sessions. Max {MAX_SESSIONS_PER_IP} sessions/day.")
        
        conversation = load_conversation(session_id)
        
        if conversation and not check_session_age(conversation):
            logger.info(f"Session {session_id} expired - starting fresh")
            delete_conversation(session_id)
            conversation = []
        
        if not check_token_limit(session_id):
            raise HTTPException(status_code=429, detail=f"Token limit exceeded. Max {MAX_TOKENS_PER_SESSION} tokens/session.")
        
        logger.info(json.dumps({
            "event": "chat_request",
            "session_id": session_id,
            "ip": client_ip,
            "message_length": len(request.message),
            "timestamp": datetime.now().isoformat()
        }))
        
        assistant_response, tokens_used = call_bedrock(conversation, request.message)
        check_token_limit(session_id, tokens_used)
        
        response_time = time.time() - start_time
        
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
        
        save_conversation(session_id, conversation)
        
        logger.info(json.dumps({
            "event": "chat_response",
            "session_id": session_id,
            "tokens_used": tokens_used,
            "response_time_ms": int(response_time * 1000),
            "timestamp": datetime.now().isoformat()
        }))
        
        return ChatResponse(response=assistant_response, session_id=session_id)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing chat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# Lambda handler
handler = Mangum(app, lifespan="off")