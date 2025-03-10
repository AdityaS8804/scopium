# ✨ Scopium ✨

## Introduction

Welcome to **Project Name** – a cutting-edge multi-chat application integrated with GitHub repository search functionality. This project leverages a modern **React** frontend styled with **Tailwind CSS** and enhanced by **shadcn UI** components, alongside a robust **Flask** backend. Users can search for any public repository, connect to it, and initiate dedicated chat sessions tailored for each repository. All chat sessions and histories are cached locally, ensuring your conversations persist even after a reload.

> *More detailed introduction coming soon...*

---

## Pre-requisites

Before you begin, ensure you have the following installed:

- **Node.js** (v14 or higher) and **npm** or **yarn** for the frontend.
- **Python 3.10+** and **pip** for the backend.
- A virtual environment tool (e.g., `venv` or `virtualenv`) for Python.
- **Tailwind CSS** configured with PostCSS (verify your `tailwind.config.js` includes your React files, e.g., `./src/**/*.{js,ts,jsx,tsx}`).
- **shadcn UI** installed and properly integrated.
- Required Python packages (listed in `requirements.txt`):
  - `flask`
  - `flask-cors`
  - `python-jwt`
  - `requests`
  - `Mistralai 0.4.2`

---

## How to Run

### Frontend

1. **Navigate to the Frontend Directory:**
   ```bash
   cd frontend

2. **Install Dependencies:**
   ```bash
   npm install

3. **Install Dependencies:**
   ```bash
   npm install

### Backend

1. **Navigate to the Backend Directory:**

   ```bash
   cd backend

2. **Create and Activate a Virtual Environment:**
   ```bash
    python -m venv venv
    # For Linux/Mac:
    source venv/bin/activate
    # For Windows:
    venv\Scripts\activate

3. **Install Required Python Packages:**
   ```bash
   pip install -r requirements.txt

4. **Start the Flask Server:**
   ```bash
   python app.py
  The backend server will run at http://127.0.0.1:5000.