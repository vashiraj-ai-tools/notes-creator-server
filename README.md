# Notes Creator Server

Backend API for generating structured revision notes from YouTube videos and blog posts. Built with FastAPI and LangGraph.

## Features

- **YouTube Processing**: Extracts transcripts and processes video content.
- **Blog Scraping**: Extracts content from articles using BeautifulSoup.
- **AI-Powered Notes**: Uses Gemini AI to generate structured, educational notes.
- **Job Queue**: Handles long-running generation tasks asynchronously.
- **Firebase Auth**: Secure user authentication and management.

## Tech Stack

- **Framework**: FastAPI
- **AI/LLM**: Google Generative AI (Gemini)
- **Workflow**: LangGraph
- **Data Stores**: In-memory job store (asynchronous)

## Getting Started

### Prerequisites

- Python 3.10+
- Virtual environment tool (`venv`)

### Installation

1. **Clone the repository** (if not already done).
2. **Create a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/scripts/activate  # On Windows: venv\Scripts\activate
   ```
3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

### Configuration

1. Copy `.env.example` to `.env.local`:
   ```bash
   cp .env.example .env.local
   ```
2. Fill in the required environment variables:
   - `FIREBASE_API_KEY`: Your Firebase project API key.
   - `FIREBASE_SERVICE_ACCOUNT_PATH`: Path to your Firebase service account JSON file.
   - `JWT_SECRET`: A long random string for securing tokens.
   - `ENCRYPTION_KEY`: A Fernet encryption key (can be generated with `Fernet.generate_key()`).

### Running the Server

Run the development server using:
```bash
python main.py
```
The API will be available at `http://localhost:8080`.
Documentation (Swagger UI) can be accessed at `http://localhost:8080/docs`.

## API Structure

- `/auth`: Authentication endpoints (Firebase integration).
- `/users`: User profile and settings management.
- `/jobs`: Note generation job management (create, status, results).
