# ProfSidekick API - AI Teaching Assistant Backend

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

ProfSidekick is an AI-powered teaching assistant that helps educators deliver engaging lessons by processing presentation files and providing real-time AI enhancements. This backend provides comprehensive APIs for presentation processing, session management, and AI-powered educational features.

## 🚀 Features

- **📎 Presentation Processing**: Upload and process PowerPoint (.pptx, .ppt) and PDF files
- **🤖 AI Integration**: OpenAI Chat Completions for content analysis and Realtime API token generation
- **📚 Session Management**: Create and manage teaching sessions with Redis caching
- **💡 Enhanced AI Capabilities**: Concept explanations and intelligent question answering
- **🔐 Secure File Handling**: Secure file upload with validation and storage
- **📊 Real-time Analytics**: Session statistics and monitoring
- **🐳 Docker Ready**: Complete containerization with Docker Compose
- **📖 Auto-generated Docs**: Interactive API documentation with FastAPI

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│    Frontend     │    │   FastAPI API   │    │   PostgreSQL    │
│   (React/Vue)   │◄──►│     Backend     │◄──►│    Database     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌─────────────────┐    ┌─────────────────┐
                       │  Redis Cache    │    │  OpenAI APIs    │
                       │  (Sessions)     │    │ (Chat + RT API) │
                       └─────────────────┘    └─────────────────┘
```

## 📋 Prerequisites

- Python 3.11+
- PostgreSQL 13+
- Redis 6+
- OpenAI API Key
- Docker & Docker Compose (for containerized deployment)

## Vertex AI Setup (Math Autograder)

The autograder uses **Gemini via Vertex AI** as its primary grading provider.  
Vertex AI authenticates via [Application Default Credentials (ADC)](https://cloud.google.com/docs/authentication/application-default-credentials) — no separate API key is needed, but you must complete a one-time setup per environment.

### Local development (interactive login)

Run these two commands **once** on each developer machine, **outside the app**:

```bash
gcloud auth application-default login
gcloud config set project gen-lang-client-0696296026
```

`gcloud auth application-default login` opens a browser for Google account sign-in and writes a credential file to `~/.config/gcloud/application_default_credentials.json`.  The Vertex AI SDK picks it up automatically.

### CI / Production (non-interactive — no browser available)

`gcloud auth application-default login` is **interactive and will not work in CI or deployed environments**.  Use one of these instead:

**Option A — Service Account JSON** (Railway, Heroku, Docker, GitHub Actions):
1. Create a service account in [IAM & Admin](https://console.cloud.google.com/iam-admin/serviceaccounts) with the **Vertex AI User** role.
2. Download a JSON key for that service account.
3. Set the environment variable:
   ```
   GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
   ```
4. The SDK resolves ADC automatically from that path — no code changes needed.

**Option B — Workload Identity** (GKE, Cloud Run):
Attach the service account to the workload; ADC is injected via the metadata server.  No key file needed.

### Environment variables (already in `.env`)

| Variable | Value | Purpose |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | `gen-lang-client-0696296026` | Vertex AI billing project |
| `VERTEX_AI_LOCATION` | `us-central1` | Model region |
| `VERTEX_AI_MODEL` | `gemini-1.5-pro` | Model to use for grading |

---

## 🛠️ Installation

### Local Development Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd backend
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   ```bash
   cp env.example .env
   ```
   Edit `.env` file with your configuration:
   ```env
   OPENAI_API_KEY=your_openai_api_key_here
   DATABASE_URL=postgresql://username:password@localhost:5432/profsidekick
   REDIS_URL=redis://localhost:6379/0
   SECRET_KEY=your-secret-key-change-in-production
   ```

5. **Set up database**
   ```bash
   # Create PostgreSQL database
   createdb profsidekick
   
   # Tables will be created automatically on first run
   ```

6. **Run the application**
   ```bash
   python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

### Docker Deployment

1. **Clone and configure**
   ```bash
   git clone <repository-url>
   cd backend
   export OPENAI_API_KEY=your_openai_api_key_here
   ```

2. **Run with Docker Compose**
   ```bash
   # Basic services
   docker-compose up -d
   
   # With admin tools (pgAdmin + Redis Commander)
   docker-compose --profile admin up -d
   ```

3. **Verify deployment**
   ```bash
   curl http://localhost:8000/health
   ```

## 📡 API Endpoints

### Core Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | API information and links |
| `GET` | `/health` | Health check |
| `GET` | `/docs` | Interactive API documentation |

### Presentation Processing

#### Upload and Process Presentation
```http
POST /api/classes/create
Content-Type: multipart/form-data

presentation: <file>  # .pptx, .ppt, or .pdf file
classDetails: {       # JSON string
  "className": "Introduction to AI",
  "courseCode": "CS-101",
  "description": "Basic AI concepts",
  "duration": 60
}
```

**Response:**
```json
{
  "sessionId": "sess_abc123def456",
  "processedContent": "AI-generated teaching instructions...",
  "slides": [
    {
      "id": 1,
      "slideNumber": 1,
      "title": "Introduction",
      "imageUrl": "/static/slides/sess_abc123def456/slide_1.png",
      "thumbnailUrl": "/static/slides/sess_abc123def456/thumb_1.png",
      "content": "Slide content...",
      "teachingNotes": "Teaching guidance..."
    }
  ],
  "classDetails": {...},
  "totalSlides": 15
}
```

#### Check Processing Status
```http
GET /api/classes/status/{presentation_id}
```

### Session Management

#### Get Ephemeral Token (OpenAI Realtime API)
```http
GET /api/session/ephemeral
```

**Response:**
```json
{
  "client_secret": {
    "value": "sk-proj-abc123...",
    "expires_at": "2025-06-02T01:34:00Z"
  }
}
```

#### Retrieve Session Slides
```http
GET /api/sessions/{sessionId}/slides
```

#### Get Complete Session Details
```http
GET /api/sessions/{sessionId}
```

#### List All Sessions
```http
GET /api/sessions?limit=50
```

#### Delete Session
```http
DELETE /api/sessions/{sessionId}
```

### AI-Powered Features

#### Explain Concepts
```http
POST /api/ai/explain
Content-Type: application/json

{
  "concept": "machine learning",
  "detail_level": "medium",  // basic, medium, advanced
  "session_id": "sess_abc123"  // optional
}
```

#### Answer Questions
```http
POST /api/ai/answer
Content-Type: application/json

{
  "question": "What is the difference between AI and ML?",
  "session_id": "sess_abc123"  // optional
}
```

#### System Statistics
```http
GET /api/stats
```

## 🗄️ Database Schema

### Presentations Table
```sql
CREATE TABLE presentations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename VARCHAR(255) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_size INTEGER NOT NULL,
    file_type VARCHAR(10) NOT NULL,
    upload_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processing_status processing_status_enum DEFAULT 'pending'
);
```

### Sessions Table
```sql
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id VARCHAR(50) UNIQUE NOT NULL,
    presentation_id UUID REFERENCES presentations(id),
    class_name VARCHAR(200) NOT NULL,
    course_code VARCHAR(50),
    description TEXT,
    duration INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_content TEXT
);
```

### Slides Table
```sql
CREATE TABLE slides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id),
    slide_number INTEGER NOT NULL,
    title TEXT,
    content TEXT,
    teaching_notes TEXT,
    image_path VARCHAR(500),
    thumbnail_path VARCHAR(500)
);
```

## 🔧 Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key (required) | - |
| `DATABASE_URL` | PostgreSQL connection string | - |
| `REDIS_URL` | Redis connection string | - |
| `SECRET_KEY` | Application secret key | - |
| `DEBUG` | Enable debug mode | `False` |
| `MAX_FILE_SIZE` | Maximum upload file size | `52428800` (50MB) |
| `ALLOWED_FILE_TYPES` | Allowed file extensions | `.pptx,.ppt,.pdf` |
| `CORS_ORIGINS` | Allowed CORS origins | `http://localhost:3000` |

### File Upload Limits

- **Maximum file size**: 50MB
- **Supported formats**: `.pptx`, `.ppt`, `.pdf`
- **File validation**: Type checking and size limits enforced

## 🧪 Testing

Run the test suite:

```bash
# Install test dependencies
pip install pytest pytest-asyncio httpx

# Run tests
pytest tests/

# Run with coverage
pytest --cov=app tests/

# Run specific test file
pytest tests/test_main.py -v
```

## 🚀 Deployment

### Production Considerations

1. **Environment Setup**
   ```bash
   # Set production environment variables
   export DEBUG=false
   export SECRET_KEY=<strong-secret-key>
   export OPENAI_API_KEY=<your-openai-key>
   ```

2. **Security**
   - Use strong secret keys
   - Configure CORS origins properly
   - Set up HTTPS with reverse proxy (nginx/Apache)
   - Implement rate limiting
   - Set up monitoring and logging

3. **Database**
   - Use connection pooling
   - Set up database backups
   - Configure read replicas for scaling

4. **Redis**
   - Configure persistence
   - Set up Redis clustering for high availability
   - Monitor memory usage

5. **File Storage**
   - Consider using cloud storage (AWS S3, GCS)
   - Implement file cleanup policies
   - Set up CDN for static files

### Docker Production Deployment

```yaml
# docker-compose.prod.yml
version: '3.8'
services:
  backend:
    build: .
    environment:
      - DEBUG=false
      - SECRET_KEY=${SECRET_KEY}
    volumes:
      - uploads:/app/uploads
      - static:/app/static
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '1'
          memory: 1G
```

## 📈 Performance Optimization

- **Redis Caching**: Session data cached for 24 hours
- **Connection Pooling**: Database connection pooling enabled
- **Async Processing**: File processing and AI calls are asynchronous
- **Static File Serving**: Efficient static file serving with FastAPI
- **Image Optimization**: Slide thumbnails generated for quick loading

## 🐛 Troubleshooting

### Common Issues

1. **OpenAI API Errors**
   ```bash
   # Check API key
   curl -H "Authorization: Bearer $OPENAI_API_KEY" https://api.openai.com/v1/models
   ```

2. **Database Connection Issues**
   ```bash
   # Test PostgreSQL connection
   psql $DATABASE_URL -c "SELECT 1;"
   ```

3. **Redis Connection Issues**
   ```bash
   # Test Redis connection
   redis-cli -u $REDIS_URL ping
   ```

4. **File Upload Issues**
   - Check file size limits
   - Verify file type is supported
   - Ensure upload directory exists and is writable

### Logs and Monitoring

```bash
# Docker logs
docker-compose logs -f backend

# Application logs (when running locally)
tail -f app.log
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

- **Documentation**: `/docs` endpoint for interactive API docs
- **Issues**: Create GitHub issues for bugs and feature requests
- **Email**: support@profsidekick.com

## 🔮 Roadmap

- [ ] Authentication and user management
- [ ] Webhook support for real-time updates
- [ ] Advanced analytics and reporting
- [ ] Multi-language support
- [ ] Integration with Learning Management Systems (LMS)
- [ ] Advanced slide processing with computer vision
- [ ] Real-time collaboration features

---

**ProfSidekick API** - Empowering educators with AI-powered teaching assistance # profsidekick-api
