'use client';

import { useState, useRef, useEffect } from 'react';
import { Send, Bot, User } from 'lucide-react';

interface Message {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    timestamp: Date;
}

export default function Twin() {
    const [messages, setMessages] = useState<Message[]>([]);
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [sessionId, setSessionId] = useState<string>('');
    const messagesEndRef = useRef<HTMLDivElement>(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    const sendMessage = async () => {
        if (!input.trim() || isLoading) return;

        const userMessage: Message = {
            id: Date.now().toString(),
            role: 'user',
            content: input,
            timestamp: new Date(),
        };

        setMessages(prev => [...prev, userMessage]);
        setInput('');
        setIsLoading(true);

        try {
            const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/chat`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    message: input,
                    session_id: sessionId || undefined,
                }),
            });

            if (!response.ok) throw new Error('Failed to send message');

            const data = await response.json();

            if (!sessionId) {
                setSessionId(data.session_id);
            }

            const assistantMessage: Message = {
                id: (Date.now() + 1).toString(),
                role: 'assistant',
                content: data.response,
                timestamp: new Date(),
            };

            setMessages(prev => [...prev, assistantMessage]);
        } catch (error) {
            console.error('Error:', error);
            const errorMessage: Message = {
                id: (Date.now() + 1).toString(),
                role: 'assistant',
                content: 'Sorry, I encountered an error. Please try again.',
                timestamp: new Date(),
            };
            setMessages(prev => [...prev, errorMessage]);
        } finally {
            setIsLoading(false);
        }
    };

    const handleKeyPress = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    };

    return (
        <div className="flex flex-col h-full rounded-lg shadow-lg" style={{
            background: 'rgba(10, 25, 41, 0.3)',
            backdropFilter: 'blur(15px)',
            border: '2px solid rgba(191, 219, 254, 0.4)',
            boxShadow: '0 20px 40px rgba(0, 0, 0, 0.4), 0 0 60px rgba(96, 165, 250, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.1)'
        }}>
            {/* Header */}
            <div className="text-white p-4 rounded-t-lg" style={{
                background: 'rgba(10, 25, 41, 0.5)',
                borderBottom: '1px solid rgba(191, 219, 254, 0.3)'
            }}>
                <h2 className="text-xl font-semibold flex items-center gap-2">
                    <Bot className="w-6 h-6" />
                    Professional Profile Chatbot
                </h2>
                <p className="text-sm mt-1" style={{ color: 'rgba(191, 219, 254, 0.8)' }}>Powered by AI</p>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {messages.length === 0 && (
                    <div className="text-center text-gray-300 mt-8">
                        <Bot className="w-12 h-12 mx-auto mb-3" style={{ color: 'rgba(191, 219, 254, 0.6)' }} />
                        <p className="text-white">Hello! I&apos;m Mazhar&apos;s AI assistant.</p>
                        <p className="text-sm mt-2" style={{ color: 'rgba(191, 219, 254, 0.8)' }}>Ask me anything about my experience and skills</p>
                    </div>
                )}

                {messages.map((message) => (
                    <div
                        key={message.id}
                        className={`flex gap-3 ${
                            message.role === 'user' ? 'justify-end' : 'justify-start'
                        }`}
                    >
                        {message.role === 'assistant' && (
                            <div className="flex-shrink-0">
                                <div className="w-8 h-8 rounded-full flex items-center justify-center" style={{
                                    background: 'linear-gradient(45deg, #3b82f6, #60a5fa)'
                                }}>
                                    <Bot className="w-5 h-5 text-white" />
                                </div>
                            </div>
                        )}

                        <div
                            className={`max-w-[70%] rounded-lg p-3 ${
                                message.role === 'user'
                                    ? 'text-white'
                                    : 'bg-white border border-gray-200 text-gray-800'
                            }`}
                            style={message.role === 'user' ? {
                                background: 'linear-gradient(45deg, #3b82f6, #60a5fa)'
                            } : {}}
                        >
                            <p className="whitespace-pre-wrap">{message.content}</p>
                            <p
                                className={`text-xs mt-1 ${
                                    message.role === 'user' ? 'text-blue-100' : 'text-gray-500'
                                }`}
                            >
                                {message.timestamp.toLocaleTimeString()}
                            </p>
                        </div>

                        {message.role === 'user' && (
                            <div className="flex-shrink-0">
                                <div className="w-8 h-8 bg-gray-600 rounded-full flex items-center justify-center">
                                    <User className="w-5 h-5 text-white" />
                                </div>
                            </div>
                        )}
                    </div>
                ))}

                {isLoading && (
                    <div className="flex gap-3 justify-start">
                        <div className="flex-shrink-0">
                            <div className="w-8 h-8 rounded-full flex items-center justify-center" style={{
                                background: 'linear-gradient(45deg, #3b82f6, #60a5fa)'
                            }}>
                                <Bot className="w-5 h-5 text-white" />
                            </div>
                        </div>
                        <div className="bg-white border border-gray-200 rounded-lg p-3">
                            <div className="flex space-x-2">
                                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" />
                                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-100" />
                                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-200" />
                            </div>
                        </div>
                    </div>
                )}

                <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <div className="p-4 rounded-b-lg" style={{
                background: 'rgba(10, 25, 41, 0.5)',
                borderTop: '1px solid rgba(191, 219, 254, 0.3)'
            }}>
                <div className="flex gap-2">
                    <input
                        type="text"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={handleKeyPress}
                        placeholder="Type your message..."
                        className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-gray-800 bg-white"
                        disabled={isLoading}
                    />
                    <button
                        onClick={sendMessage}
                        disabled={!input.trim() || isLoading}
                        className="px-4 py-2 text-white rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        style={{
                            background: 'linear-gradient(45deg, #3b82f6, #60a5fa)'
                        }}
                    >
                        <Send className="w-5 h-5" />
                    </button>
                </div>
            </div>
        </div>
    );
}