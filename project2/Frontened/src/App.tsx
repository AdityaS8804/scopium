import React, { useState, useRef, useEffect } from 'react';
import { MessageSquare, Github, Send } from 'lucide-react';

interface Message {
  id: number;
  text: string;
  sender: 'user' | 'assistant';
}

interface Repository {
  id: number;
  full_name: string;
  clone_url: string;
}

const ChatApp: React.FC = () => {
  // Chat state (for the current repository session)
  const [message, setMessage] = useState('');
  const [showEmptyState, setShowEmptyState] = useState(true);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // GitHub connection state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [githubLink, setGithubLink] = useState('');
  const [ghMessage, setGhMessage] = useState('');
  const [repos, setRepos] = useState<Repository[]>([]);

  // Repository search state
  const [searchQuery, setSearchQuery] = useState('');

  // Multi-chat state: current selected repository and chat sessions keyed by repository id
  const [currentRepo, setCurrentRepo] = useState<Repository | null>(null);
  const [chats, setChats] = useState<{ [repoId: number]: Message[] }>({});
  // Chat history: list of repositories for which the user has sent at least one message
  const [chatHistory, setChatHistory] = useState<Repository[]>([]);

  // Adjust the textarea height for chat input
  const adjustTextareaHeight = () => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
    }
  };

  useEffect(() => {
    adjustTextareaHeight();
  }, [message]);

  // Send message for the current repository chat
  const handleSendMessage = () => {
    if (!message.trim() || !currentRepo) return;
    const newMessage: Message = { id: Date.now(), text: message.trim(), sender: 'user' };
    setChats((prev) => {
      const currentMessages = prev[currentRepo.id] || [];
      return { ...prev, [currentRepo.id]: [...currentMessages, newMessage] };
    });
    setMessage('');
    setShowEmptyState(false);

    // If it's the first message in this repo chat, add the repository to chat history
    if (currentRepo && !chatHistory.find((repo) => repo.id === currentRepo.id)) {
      setChatHistory((prev) => [...prev, currentRepo]);
    }

    // Simulate an assistant response for this repository chat
    setTimeout(() => {
      const response: Message = {
        id: Date.now() + 1,
        text: `I understand your message regarding ${currentRepo.full_name}. How can I help you further?`,
        sender: 'assistant'
      };
      setChats((prev) => {
        const currentMessages = prev[currentRepo.id] || [];
        return { ...prev, [currentRepo.id]: [...currentMessages, response] };
      });
    }, 1000);
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  // GitHub modal functions (for manual profile URL entry)
  const openGithubModal = () => {
    setIsModalOpen(true);
  };

  const handleGithubConnect = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!githubLink) return;
    try {
      const response = await fetch('http://127.0.0.1:5000/api/github/repos', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ github_link: githubLink })
      });
      const data = await response.json();
      if (response.ok) {
        setRepos(data.repositories);
        setGhMessage('Repositories fetched successfully!');
      } else {
        setGhMessage(data.error || 'Error fetching repositories.');
      }
    } catch (error) {
      setGhMessage('Network error fetching repositories.');
    }
    setIsModalOpen(false);
    setGithubLink('');
  };

  // Repository search: search for repositories using the search query
  const handleRepoSearch = async () => {
    if (!searchQuery.trim()) return;
    try {
      const response = await fetch('http://127.0.0.1:5000/api/github/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: searchQuery.trim() })
      });
      const data = await response.json();
      if (response.ok) {
        setRepos(data.repositories);
        setGhMessage('Search results fetched successfully!');
      } else {
        setGhMessage(data.error || 'Error searching repositories.');
      }
    } catch (error) {
      setGhMessage('Network error searching repositories.');
    }
  };

  // When a repository is clicked, set it as the current chat session.
  const handleRepoSelect = (repo: Repository) => {
    setCurrentRepo(repo);
    setChats((prev) => {
      if (!prev[repo.id]) {
        return { ...prev, [repo.id]: [] };
      }
      return prev;
    });
  };

  return (
    <div className="min-h-screen bg-gray-950 flex">
      {/* Sidebar */}
      <div className="w-64 bg-gray-900 border-r border-gray-800 p-4">
        <button
          onClick={openGithubModal}
          className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-gray-800 text-gray-200 rounded-lg hover:bg-gray-700 transition-colors"
        >
          <Github size={20} />
          <span>Connect GitHub</span>
        </button>

        {/* Search Bar */}
        <div className="mt-4">
          <input
            type="text"
            placeholder="Search repositories..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-gray-300"
          />
          <button
            onClick={handleRepoSearch}
            className="mt-2 w-full px-4 py-2 bg-blue-600 text-gray-200 rounded hover:bg-blue-500"
          >
            Search
          </button>
        </div>

        {/* Repository List */}
        <div className="mt-4">
          <p className="text-gray-300 mb-2">Choose codebase:</p>
          <div className="max-h-48 overflow-y-auto space-y-1">
            {repos.length === 0 ? (
              <div className="px-3 py-2 bg-gray-800 text-gray-300 rounded">No repos available</div>
            ) : (
              repos.map((repo) => (
                <div
                  key={repo.id}
                  onClick={() => handleRepoSelect(repo)}
                  className={`cursor-pointer px-3 py-2 rounded ${
                    currentRepo && currentRepo.id === repo.id
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
                  }`}
                >
                  {repo.full_name}
                </div>
              ))
            )}
          </div>
        </div>

        {/* Chat History Section */}
        <div className="mt-6">
          <p className="text-gray-300 mb-2">Chat History:</p>
          <div className="max-h-48 overflow-y-auto space-y-1">
            {chatHistory.length === 0 ? (
              <div className="px-3 py-2 bg-gray-800 text-gray-300 rounded">No chats yet</div>
            ) : (
              chatHistory.map((repo) => (
                <div
                  key={repo.id}
                  onClick={() => handleRepoSelect(repo)}
                  className={`cursor-pointer px-3 py-2 rounded ${
                    currentRepo && currentRepo.id === repo.id
                      ? 'bg-green-600 text-white'
                      : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
                  }`}
                >
                  {repo.full_name}
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col">
        {/* Chat Header */}
        <div className="bg-gray-800 p-4 border-b border-gray-700">
          {currentRepo ? (
            <h2 className="text-gray-200 text-lg">Chat - {currentRepo.full_name}</h2>
          ) : (
            <h2 className="text-gray-200 text-lg">Select a repository to start chatting</h2>
          )}
        </div>

        {/* Chat Container */}
        <div className="flex-1 overflow-y-auto p-4">
          {currentRepo ? (
            chats[currentRepo.id] && chats[currentRepo.id].length > 0 ? (
              chats[currentRepo.id].map((msg) => (
                <div
                  key={msg.id}
                  className={`max-w-2xl ${msg.sender === 'user' ? 'ml-auto' : 'mr-auto'}`}
                >
                  <div
                    className={`p-3 rounded-lg ${
                      msg.sender === 'user'
                        ? 'bg-gray-800 text-gray-200'
                        : 'bg-gray-900 text-gray-300'
                    }`}
                  >
                    {msg.text}
                  </div>
                </div>
              ))
            ) : (
              <div className="text-center text-gray-400">No messages yet. Start the conversation!</div>
            )
          ) : (
            <div className="h-full flex items-center justify-center p-8">
              <div className="text-center">
                <MessageSquare className="w-12 h-12 mx-auto mb-4 text-gray-600" />
                <p className="text-gray-400">
                  Select a repository from the sidebar to open a dedicated chat.
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Chat Input Area */}
        {currentRepo && (
          <div className="border-t border-gray-800 p-4 bg-gray-900">
            <div className="max-w-4xl mx-auto flex gap-4">
              <textarea
                ref={textareaRef}
                rows={1}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                onKeyDown={handleKeyPress}
                placeholder="Ask a question..."
                className="flex-1 px-4 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-600 text-gray-200 placeholder-gray-500 resize-none min-h-[40px] max-h-[200px] overflow-y-auto"
              />
              <button
                className="px-4 py-2 bg-gray-800 text-gray-200 rounded-lg hover:bg-gray-700 transition-colors flex items-center gap-2 h-fit"
                onClick={handleSendMessage}
              >
                <Send size={18} />
                <span>Send</span>
              </button>
            </div>
          </div>
        )}
      </div>

      {/* GitHub Connect Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 flex items-center justify-center bg-black bg-opacity-50">
          <div className="bg-gray-800 p-6 rounded-lg">
            <h2 className="text-gray-200 mb-4">Enter your GitHub Profile URL</h2>
            <form onSubmit={handleGithubConnect}>
              <input
                type="text"
                value={githubLink}
                onChange={(e) => setGithubLink(e.target.value)}
                placeholder="e.g., https://github.com/username"
                className="w-full p-2 mb-4 bg-gray-700 text-gray-200 rounded"
              />
              <div className="flex justify-end">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="mr-2 px-4 py-2 bg-gray-600 text-gray-200 rounded hover:bg-gray-500"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-blue-600 text-gray-200 rounded hover:bg-blue-500"
                >
                  Connect
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* GitHub Connection Message */}
      {ghMessage && (
        <div className="fixed bottom-4 right-4 bg-gray-800 p-4 rounded-lg text-gray-200 max-h-64 overflow-y-auto">
          <pre className="whitespace-pre-wrap">{ghMessage}</pre>
        </div>
      )}
    </div>
  );
};

export default ChatApp;
