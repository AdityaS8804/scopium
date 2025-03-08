import React, { useState, useRef, useEffect } from 'react';
import { MessageSquare, Github, Send } from 'lucide-react';

interface Message {
  id: number;
  text: string;
  sender: 'user' | 'assistant';
}

function App() {
  const [message, setMessage] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [showEmptyState, setShowEmptyState] = useState(true);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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

  const handleSendMessage = () => {
    if (!message.trim()) return;
    
    const newMessage: Message = {
      id: Date.now(),
      text: message.trim(),
      sender: 'user'
    };
    
    setMessages(prev => [...prev, newMessage]);
    setMessage('');
    setShowEmptyState(false);

    // Simulate AI response
    setTimeout(() => {
      const response: Message = {
        id: Date.now() + 1,
        text: "I understand your message. How can I help you further with that?",
        sender: 'assistant'
      };
      setMessages(prev => [...prev, response]);
    }, 1000);
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div className="min-h-screen bg-gray-950 flex">
      {/* Sidebar */}
      <div className="w-64 bg-gray-900 border-r border-gray-800">
        <div className="p-4">
          <button className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-gray-800 text-gray-200 rounded-lg hover:bg-gray-700 transition-colors">
            <Github size={20} />
            <span>Connect GitHub</span>
          </button>
          <select className="w-full mt-4 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-gray-300">
            <option value="">Choose codebase...</option>
          </select>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col">
        {/* Chat Container */}
        <div className="flex-1 flex flex-col">
          <div className="flex-1 overflow-y-auto">
            {showEmptyState ? (
              <div className="h-full flex items-center justify-center p-8">
                <div className="text-center max-w-md">
                  <MessageSquare className="w-12 h-12 mx-auto mb-4 text-gray-600" />
                  <h2 className="text-xl font-semibold text-gray-200 mb-2">
                    Welcome to Your AI Assistant
                  </h2>
                  <p className="text-gray-400 mb-4">
                    This AI assistant can help you understand codebases, generate code, and answer programming questions.
                  </p>
                  <div className="space-y-3 text-left bg-gray-900 p-4 rounded-lg">
                    <p className="text-sm text-gray-300">Try asking about:</p>
                    <ul className="space-y-2 text-sm text-gray-400">
                      <li>• "Explain how this codebase works"</li>
                      <li>• "Generate a React component for..."</li>
                      <li>• "Help me understand this error..."</li>
                      <li>• "What's the best practice for..."</li>
                    </ul>
                  </div>
                </div>
              </div>
            ) : (
              <div className="p-4 space-y-4">
                {messages.map((msg) => (
                  <div
                    key={msg.id}
                    className={`max-w-2xl ${
                      msg.sender === 'user' ? 'ml-auto' : 'mr-auto'
                    }`}
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
                ))}
              </div>
            )}
          </div>

          {/* Input Area */}
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
        </div>
      </div>
    </div>
  );
}

export default App;