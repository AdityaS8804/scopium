# ✨ Scopium ✨

## Introduction

Welcome to **Scopium** – a cutting-edge multi-chat application integrated with GitHub repository search functionality. This project leverages a graphRAG system using **ArangoDB** and **Networkx**. The entire codebase gets chunked up into *nodes* and relationships between these nodes are captured in the *edges*. Coupling this with our MistralAI implementation, it allows for efficient queries spanning throughout your codebase.  
It is implemented with a modern **React** frontend styled with **Tailwind CSS** and enhanced by **shadcn UI** components, alongside a robust **Flask** backend. Users can search for any public repository, connect to it, and initiate dedicated chat sessions tailored for each repository. All chat sessions and histories are cached locally, ensuring your conversations persist even after a reload.

![image](https://github.com/user-attachments/assets/ec908e8b-ccc7-4407-aac0-bb3e4304575d)


---
## Dataset - Any repo of your choice
- Our application *dynamically* makes a graph model of any publically available repository of your choice.
- The in-built github access allows you to choose any repository you want keeping every codebase in your fingertips.

## Associated notebook - 
- The ipython notebook - ([scopium.ipynb](https://github.com/AdityaS8804/scopium/blob/main/Scopium.ipynb)) explains every process a codebase goes through in detail

# How to use it
Given are the detailed step-by-step guide to run this on your local systems.  
## Pre-requisites
**Highly recommended to use it on a system with NVIDIA and CUDA enabled**  

Before you begin, ensure you have the following installed:

- **Node.js** (v14 or higher) and **npm** or **yarn** for the frontend.
- **Python 3.10+** and **pip** for the backend.
- A virtual environment tool (e.g., `venv` or `virtualenv`) for Python.
- **Tailwind CSS** configured with PostCSS (verify your `tailwind.config.js` includes your React files, e.g., `./src/**/*.{js,ts,jsx,tsx}`).
- **shadcn UI** installed and properly integrated.

---

## How to Run

### Frontend

1. **Navigate to the Frontend Directory:**
   ```bash
   cd Frontend

2. **Install Dependencies:**
   ```bash
   npm install

3. **Run the frontend:**
   ```bash
   npm run dev
*Note - if the above method doesn't work, create your own react-vite app with tailwind CSS and shadcn UI setup and copy the src/App.tsx contents into your own src/App.tsx file and run the above commands* 

### Backend

1. **Navigate to the Backend Directory:**

   ```bash
   cd Backend

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
4. **Rename the `.env.temp` to `.env` and fill in the mentioned environment variables**   
5. **Start the Flask Server:**
   ```bash
   python server.py
  The backend server will run at http://127.0.0.1:5000.
