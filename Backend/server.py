import jwt
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
import subprocess
import sys
from flask import Flask, request, jsonify
import time
from jwt import *

import requests
from flask_cors import CORS
from dotenv import load_dotenv
import os
from arango import ArangoClient
import re
from GraphBuilder import CodebaseVisualizer
import nx_arangodb as nxadb
from GraphQuery import EnhancedCodebaseQuery
app = Flask(__name__)
CORS(app)
# Load the .env file
load_dotenv()

HOSTS = os.getenv('ARANGO_HOST')
USERNAME = os.getenv('ARANGO_USERNAME')
PASSWORD = os.getenv('ARANGO_PASSWORD')
MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY')
# Configuration variables
PRIVATE_PEM_PATH = 'D:\AdityasFiles\scopium\Server\scopiumapp.2025-03-08.private-key.pem'
CLIENT_ID = 'Iv23liiin5e6YF9k8FGG'


client = ArangoClient(hosts=HOSTS)
db = client.db(username='root', password=PASSWORD, verify=True)


@app.route('/api/github/repos', methods=['POST'])
def github_repos():
    data = request.get_json()
    github_link = data.get('github_link')
    if not github_link:
        return jsonify({'error': 'GitHub link not provided'}), 400

    try:
        username = github_link.rstrip('/').split('/')[-1]
    except Exception as e:
        return jsonify({'error': 'Invalid GitHub link', 'details': str(e)}), 400

    # ...existing code...
    try:
        with open(PRIVATE_PEM_PATH, 'rb') as pem_file:
            pem_data = pem_file.read()
        key = serialization.load_pem_private_key(
            pem_data, password=None, backend=default_backend())
        payload = {
            'iat': int(time.time()),
            'exp': int(time.time()) + 600,
            'iss': CLIENT_ID
        }
        jwt_instance = jwt.JWT()
        jwt_token = jwt_instance.encode(payload, key, alg='RS256')
    except Exception as e:
        app.logger.error("JWT generation error: %s", e)
        return jsonify({'error': 'Failed to generate JWT', 'details': str(e)}), 500

    headers = {
        'Accept': 'application/vnd.github+json'
    }
    api_url = f'https://api.github.com/users/{username}/repos'
    response = requests.get(api_url, headers=headers)
    if response.ok:
        repos = response.json()
        return jsonify({'repositories': repos}), 200
    else:
        return jsonify({
            'error': 'Failed to fetch repositories from GitHub',
            'status_code': response.status_code,
            'response': response.json()
        }), response.status_code


@app.route('/api/github/search', methods=['POST'])
def github_search():
    data = request.get_json()
    query = data.get('query')
    if not query:
        return jsonify({'error': 'Search query not provided'}), 400

    headers = {
        'Accept': 'application/vnd.github+json'
    }
    search_url = f'https://api.github.com/search/repositories?q={query}'
    response = requests.get(search_url, headers=headers)
    if response.ok:
        results = response.json().get('items', [])
        return jsonify({'repositories': results}), 200
    else:
        return jsonify({
            'error': 'Failed to search repositories on GitHub',
            'status_code': response.status_code,
            'response': response.json()
        }), response.status_code

# New dummy endpoint that receives a repository link


@app.route('/api/chat', methods=['POST'])
def dummy_endpoint():
    data = request.get_json()
    repo_link = data.get('repository_link')
    query = data.get("query")
    # Dummy processing can be done here
    repo_name = find_graph_name(repo_link)
    graph_name = '_'.join(repo_name.split('/'))
    graph_name = graph_name[:graph_name.find('.')]
    print("GRAPH NAME::::", graph_name)
    if not check_graph(graph_name):
        make_graph(repo_link, repo_name, graph_name)
    # Initialize client
    query_system = EnhancedCodebaseQuery(
        db_name="_system",
        username="root",
        password=PASSWORD,
        host=HOSTS,
        mistral_api_key=MISTRAL_API_KEY,
        model="mistral-large-latest",
        graph=graph_name
    )
    response = query_system.chat_with_codebase(query)
    print(response)
    return jsonify({"message": f"{response}"}), 200


def make_graph(repo_link, repo_name, graph_name):

    # git clone the link
    original_dir = os.getcwd()

    try:
        print(f"Starting process for: {repo_name}")

        # Create the directory if it doesn't exist
        if not os.path.exists(repo_name):
            # Make parent directories as needed
            os.makedirs(repo_name, exist_ok=True)

            # Clone the repository
            print(f"Cloning repository from {repo_link}...")
            subprocess.run(["git", "clone", repo_link, repo_name, "--depth=1"],
                           check=True)
        else:
            print(
                f"Directory '{repo_name}' already exists, skipping clone operation.")

        # Change directory to the cloned repository
        # os.chdir(repo_name)

        # Print current working directory to confirm we're in the right place
        print(f"Current directory: {os.getcwd()}")

        # Run a dummy function
        visualizer = CodebaseVisualizer(root_dir=repo_name)
        visualizer.parse_files()
        G = visualizer.build_graph()
        print(f"Graph has {len(G.nodes())} nodes and {len(G.edges())} edges")

        G_adb = nxadb.Graph(
            name=graph_name,
            db=db,
            incoming_graph_data=G,
            write_batch_size=50000,  # feel free to modify
            overwrite_graph=True
        )

        print(G_adb)
    except subprocess.CalledProcessError as e:
        print(f"Error during git clone: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)
    finally:
        # Always return to the original directory
        # os.chdir(original_dir)
        print(f"Returned to original directory: {os.getcwd()}")


def find_graph_name(repo_link):
    pattern = r"github\.com/([^/]+/[^/]+)"
    match = re.search(pattern, repo_link).group(1)
    return match


def check_graph(match):
    # Check if the graph is already there
    graph_names = [graph['name'] for graph in db.graphs()]
    print(match)
    return match in graph_names


if __name__ == '__main__':
    app.run(debug=True)
