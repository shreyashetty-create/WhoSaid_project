# WhoSaid Project - Backend

This is the backend for **WhoSaid**, a multiplayer confession game where users anonymously submit messages and guess who said what. The backend is built using **FastAPI** and integrates with **Supabase** for real-time features and data storage.

## 🚀 Features

- FastAPI-based REST API
- Supabase Realtime for multiplayer interactions
- User authentication and anonymous message handling
- Role-based routes (admin/user)
- Room creation, joining, and guessing logic
- Scalable architecture for future frontend integration

## 🛠️ Tech Stack

- **Language**: Python 3.x
- **Framework**: FastAPI
- **Database**: Supabase (PostgreSQL)
- **Realtime**: Supabase Realtime API
- **Auth**: Supabase Auth
- **Hosting**: Local (for now)

## 📦 Setup Instructions

```bash
# Clone the repo
git clone https://github.com/shreyashetty-create/WhoSaid_project.git
cd WhoSaid_project

# Install dependencies
pip install -r requirements.txt

# Run the FastAPI server
uvicorn main:app --reload
