from flask import Flask, request, jsonify
import time
from jwt import JWT, jwk_from_pem
import requests
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Configuration variables
PRIVATE_PEM_PATH = '/Users/vedanshkumar/Documents/Fun_ml/Projects/GraphRAG/scopium/scopiumapp.2025-03-08.private-key.pem'
CLIENT_ID = 'Iv23liiin5e6YF9k8FGG'

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

    try:
        with open(PRIVATE_PEM_PATH, 'rb') as pem_file:
            pem_data = pem_file.read()
        key = jwk_from_pem(pem_data)
        payload = {
            'iat': int(time.time()),
            'exp': int(time.time()) + 600,
            'iss': CLIENT_ID
        }
        jwt_instance = JWT()
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
@app.route('/api/dummy', methods=['POST'])
def dummy_endpoint():
    data = request.get_json()
    repo_link = data.get('repository_link')
    # Dummy processing can be done here
    return jsonify({"message": f"Dummy endpoint received repository link: {repo_link}"}), 200

if __name__ == '__main__':
    app.run(debug=True)
