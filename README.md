# Katherine Bot

A sophisticated AI chatbot application featuring a React frontend and a Python backend, designed to provide an engaging and emotionally responsive user experience.

## 🚀 Project Structure

The project is divided into two main components:

- **frontend/**: A modern web interface built with React, Vite, and Tailwind CSS.
- **backend/**: A robust Python backend powering the chat logic, memory systems, and integrations.

## 🛠️ Setup & Installation

### Backend

1. Navigate to the `backend` directory:
   ```bash
   cd backend
   ```
2. Create and activate a virtual environment (optional but recommended):
   ```bash
   python -m venv venv
   # Windows
   .\venv\Scripts\activate
   # Linux/Mac
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the server:
   ```bash
   python main.py
   ```

### Frontend

1. Navigate to the `frontend` directory:
   ```bash
   cd frontend
   ```
2. Install dependencies:
   ```bash
   npm install
   ```
3. Start the development server:
   ```bash
   npm run dev
   ```

## ✨ Features

- **Interactive Chat**: Real-time messaging interface.
- **Emotional Intelligence**: Tracks and responds to emotional context.
- **Memory System**: Persistent memory for context-aware conversations.
- **Modern UI**: Clean, responsive design using Tailwind CSS.

## CI Commands Reference

The following commands are used in the CI pipeline to ensure reproducible and isolated environments:

### Backend Setup and Tests
```bash
# Create and activate environment
python3 -m venv .venv-ci
source .venv-ci/bin/activate

# Install runtime dependencies (CPU-only PyTorch)
pip install -r backend/requirements.txt

# Install development dependencies
pip install -r backend/requirements-test.txt

# Run backend tests (isolated)
PYTHONPATH=. HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 pytest backend/tests/test_auth.py

# Run backend smoke test (isolated)
PYTHONPATH=. HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 pytest backend/tests/test_smoke.py
```

### Frontend Setup and Verification
```bash
cd frontend

# Install dependencies cleanly
npm ci

# Audit dependencies (generate JSON report without failing CI)
npm audit --json > audit.json || true

# Run linting
npm run lint

# Build frontend
npm run build
```
