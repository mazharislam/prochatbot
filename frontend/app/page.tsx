import Twin from '@/components/twin';

export default function Home() {
  return (
    <main className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
      <div className="container mx-auto px-4 py-8">
        <div className="max-w-4xl mx-auto">
          <h1 className="text-4xl font-bold text-center text-gray-800 mb-2">
            Mazhar Islam
          </h1>
          <p className="text-center text-gray-600 mb-1">
            Chat with my AI assistant
          </p>
          <h2 className="text-2xl font-semibold text-center text-gray-700 mb-1">
            LinkedIn Chat Bot
          </h2>
          <p className="text-center text-gray-500 mb-8">
            Ask me anything about my experience, skills, and projects
          </p>
          <div className="h-[600px]">
            <Twin />
          </div>
          <footer className="mt-8 text-center text-sm text-gray-500">
            <p>LinkedIn Profile Chat Bot Version 1.0</p>
          </footer>
        </div>
      </div>
    </main>
  );
}