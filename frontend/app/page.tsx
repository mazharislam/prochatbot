'use client';

import Twin from '@/components/twin';

export default function Home() {
  return (
    <main className="min-h-screen relative overflow-hidden" style={{
      background: 'linear-gradient(135deg, #0a1929 0%, #111e33 30%, #152538 60%, #0f1f30 100%)'
    }}>
      {/* Cyber grid background - visible with pulse animation */}
      <div 
        className="fixed top-0 left-0 w-full h-full pointer-events-none" 
        style={{
          backgroundImage: 'linear-gradient(rgba(191, 219, 254, 0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(191, 219, 254, 0.08) 1px, transparent 1px)',
          backgroundSize: '50px 50px',
          animation: 'gridPulse 4s ease-in-out infinite'
        }}
      ></div>

      <style dangerouslySetInnerHTML={{__html: `
        @keyframes gridPulse {
          0%, 100% { opacity: 0.25; }
          50% { opacity: 0.5; }
        }
      `}} />

      <div className="container mx-auto px-4 py-8 relative z-10">
        <div className="max-w-4xl mx-auto">
          <h1 className="text-4xl font-bold text-center mb-2 text-white">
            Mazhar Islam
          </h1>
          <p className="text-center text-white mb-8">
            Chat with my AI assistant about my experience, skills, and projects
          </p>
          <div className="h-[600px]">
            <Twin />
          </div>
          <footer className="mt-8 text-center text-sm text-white">
            <p>Professional Profile Chatbot Version 1.0</p>
          </footer>
        </div>
      </div>
    </main>
  );
}