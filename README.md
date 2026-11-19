# Scopium

**Chat with any public GitHub repository.** Scopium turns a codebase into a graph of files, classes, functions and the relationships between them, stores it in ArangoDB, and lets an LLM (Mistral) answer questions by querying that graph instead of guessing from loose text chunks. 🏆 1st place at a hackathon.

![Scopium UI](https://github.com/user-attachments/assets/ec908e8b-ccc7-4407-aac0-bb3e4304575d)

## What it does

- **Search and connect** to any public GitHub repository from the UI (GitHub App authentication).
- **One chat per repository**, with history cached in the browser so conversations survive a reload.
- **Multi-turn questions** such as "where is the auth logic?", "what calls `parse_files`?" or "why would this error happen?", answered with the actual code snippets and file locations.
- **Graphs are built once and reused.** The first question about a repo clones it and builds its graph. Later questions go straight to the stored graph.

## How it works

```
React UI ──POST /api/chat──► Flask server
                               │
                 graph for this repo exists in ArangoDB?
                     │ no                         │ yes
                     ▼                            │
       git clone --depth=1 → GraphBuilder         │
       (parse files → NetworkX DiGraph)           │
                     │                            │
                     ▼                            ▼
              nx-arangodb: store graph ───► GraphQuery + Mistral
                                             picks a tool, runs it on the graph,
                                             answers with code and locations
```

**1. Graph building (`Backend/GraphBuilder.py`).** It parses **Python** (with the `ast` module), **C++, Java and Go** (with pattern matching), and extracts files, classes, functions, imports and cross-file references, with line numbers and surrounding context. Code is also split into chunks so the LLM gets real source, not just names. The result is a NetworkX directed graph, written to ArangoDB through `nx-arangodb`.

**2. Querying (`Backend/GraphQuery.py`).** It's a tool-calling layer on top of the graph. For each question, Mistral (`mistral-large-latest`) chooses which of these tools to run:

| Tool | Answers |
|---|---|
| `find_symbol_occurrences` | Where is this symbol used? |
| `find_by_name` | Show me this function or class |
| `analyze_symbol` | What does this function or class do, and what depends on it? |
| `analyze_error` | Why does this error happen, and where should I look? |
| `search_code` | Which code mentions this term? |
| `analyze_code_structure` / `analyze_directory` | How is this part of the project organised? |

The tool output, which is real code from the graph, goes back to the model to write the answer, and the conversation history is kept for follow-up questions.

**3. API (`Backend/server.py`).**

| Endpoint | Purpose |
|---|---|
| `POST /api/github/search` | Search public repositories |
| `POST /api/github/repos` | List repositories available through the GitHub App |
| `POST /api/chat` | Ask a question about a repository (builds its graph on first use) |

**4. Frontend (`Frontend/`).** React, TypeScript and Vite, styled with Tailwind CSS and shadcn/ui.

The notebook [`Scopium.ipynb`](Scopium.ipynb) walks through each step a codebase goes through, with examples.

## Running it locally

**Prerequisites:** Node.js 14+, Python 3.10+, an ArangoDB instance, a Mistral API key and a GitHub App, for repository access. An NVIDIA GPU with CUDA is recommended.

**Backend**
```bash
python -m venv venv && source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt                     # requirements.txt is in the repo root
cd Backend
cp .env.temp .env                                   # then fill in the values below
python server.py                                    # runs on http://127.0.0.1:5000
```

`.env` needs `ARANGO_HOST`, `ARANGO_USERNAME`, `ARANGO_PASSWORD`, `ARANGO_VERIFY`, `GRAPH_NAME`, `WRITE_BATCH_SIZE` and `MISTRAL_API_KEY`. Keep `.env` and any GitHub App private key out of version control.

**Frontend**
```bash
cd Frontend
npm install
npm run dev
```

If the frontend setup gives you trouble, create a fresh React + Vite app with Tailwind CSS and shadcn/ui, and copy `src/App.tsx` into it.

## Tech stack

Python, Flask, NetworkX, ArangoDB (`python-arango`, `nx-arangodb`), Mistral AI, React, TypeScript, Vite, Tailwind CSS, shadcn/ui.
